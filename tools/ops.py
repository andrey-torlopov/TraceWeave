#!/usr/bin/env python3
"""Private one-shot installation/database operations. Never logs credentials."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, unquote

LOCK = 8476004
STATE = Path('/state')
DATA = Path('/data')
DATABASE_CAPACITY = Path('/database-capacity')
DISK_SAFETY_BYTES = 64 * 1024 * 1024

def operator_owned(root):
    uid=int(os.environ.get('TW_OPERATOR_UID','0'));gid=int(os.environ.get('TW_OPERATOR_GID','0'))
    if os.getuid()!=0:return
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(parent)/name
            if p.is_symlink():fail('Symlink in private operator storage.')
            os.chown(p,uid,gid)
        os.chown(parent,uid,gid)

def fail(message):
    raise RuntimeError(message)

def atomic(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp-' + secrets.token_hex(6))
    with temporary.open('x') as output:
        os.chmod(temporary, mode)
        output.write(value)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    descriptor=os.open(str(path.parent),os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def safe_files(root):
    if root.is_symlink() or not root.is_dir():
        fail('Originals root must be a real directory.')
    result = []
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            p = Path(parent) / name
            mode = p.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                fail('Symlinks and special files are forbidden in originals/backup.')
            if p.is_file():
                result.append(p)
    return sorted(result)

def secret(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 8192:
        fail('Invalid private configuration file.')
    return p.read_text().strip()

def settings(admin=False):
    raw = secret(os.environ.get('RG_DATABASE_URL_FILE', '/run/secrets/db_url'))
    p = urlsplit(raw)
    if p.scheme not in ('postgres', 'postgresql') or p.hostname != 'db' or p.path != '/traceweave':
        fail('Operations are restricted to the installation db/traceweave database.')
    result = dict(host='db',port=p.port or 5432,user=unquote(p.username or ''),password=unquote(p.password or ''),dbname='traceweave',sslmode='verify-full',sslrootcert=os.environ.get('RG_DATABASE_CA_FILE','/run/secrets/db_ca'),connect_timeout=5)
    if admin:
        result.update(user='postgres',password=secret(os.environ.get('PG_ADMIN_PASSWORD_FILE','/run/secrets/db_admin_password')))
    return result

def connect(admin=False):
    import psycopg2
    c = psycopg2.connect(**settings(admin))
    c.autocommit = True
    return c

def pg_env():
    s = settings()
    child = {k:v for k,v in os.environ.items() if not k.startswith(('PG','RG_'))}
    child.update(PGHOST=s['host'],PGPORT=str(s['port']),PGUSER=s['user'],PGPASSWORD=s['password'],PGDATABASE=s['dbname'],PGSSLMODE=s['sslmode'],PGSSLROOTCERT=s['sslrootcert'],PGCONNECT_TIMEOUT='5')
    return child

def history(c):
    with c.cursor() as q:
        q.execute('SELECT version,sha256 FROM _traceweave_migrations ORDER BY version')
        return [{'version':v,'sha256':h} for v,h in q.fetchall()]

def snapshot(c):
    with c.cursor() as q:
        q.execute("SELECT current_setting('server_version'),current_setting('server_version_num')::int")
        v, n = q.fetchone()
        if n // 10000 != 18: fail('PostgreSQL 18 required.')
        q.execute('SELECT storage_key,sha256,byte_size FROM blobs ORDER BY storage_key')
        blobs = [{'path':p,'sha256':h,'bytes':n} for p,h,n in q.fetchall()]
    return v,blobs

def database_bytes(c):
    with c.cursor() as q:
        q.execute('SELECT pg_database_size(current_database())')
        value = q.fetchone()[0]
    if type(value) is not int or value <= 0:
        fail('Database size must be a positive integer.')
    return value

def capacity_budget(database_size, original_size):
    if type(database_size) is not int or database_size <= 0:
        fail('Database size must be a positive integer.')
    if type(original_size) is not int or original_size < 0:
        fail('Original size must be a nonnegative integer.')
    return 2 * database_size + original_size + DISK_SAFETY_BYTES

def require_capacity(root, required, operation):
    if root.is_symlink() or not root.is_dir():
        fail('Capacity check requires a real mounted directory: ' + str(root))
    if shutil.disk_usage(root).free < required:
        fail('Insufficient free disk space for ' + operation + '; required ' + str(required) + ' bytes.')

def check_connection(c):
    with c.cursor() as q:
        q.execute('SELECT 1')
        if q.fetchone() != (1,):fail('Maintenance lease lost.')

def copy_file(source, target, c=None):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open('rb') as i, target.open('xb') as o:
        os.chmod(target,0o600)
        for chunk in iter(lambda:i.read(1024*1024),b''):
            if c: check_connection(c)
            o.write(chunk)
        o.flush(); os.fsync(o.fileno())

def checked_process(args,c,output=None):
    # A dedicated monitor keeps the session-level lock live and aborts pg_dump
    # on connection loss. psycopg2 connections are thread safe; only monitor uses c here.
    stopped=threading.Event(); lost=[]
    process=subprocess.Popen(args,env=pg_env(),stdin=subprocess.DEVNULL,stdout=output or subprocess.PIPE,stderr=subprocess.PIPE)
    def monitor():
        while not stopped.wait(.5):
            try:check_connection(c)
            except Exception:
                lost.append(True);process.terminate();return
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        out,err=process.communicate(timeout=1800)
        if lost or process.returncode:fail('Database utility failed; private diagnostics withheld.')
    finally:
        stopped.set();thread.join(6)
        if process.poll() is None:process.kill();process.wait()
    check_connection(c)

def initialize():
    private=STATE/'secrets'; private.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not (private/'db_admin_password').exists():
        atomic(private/'db_admin_password',secrets.token_urlsafe(48)+'\n',0o444)
    if not (private/'db_app_password').exists():
        atomic(private/'db_app_password',secrets.token_urlsafe(48)+'\n',0o444)
    if not (private/'db_url').exists():
        atomic(private/'db_url','postgresql://traceweave:'+secret(private/'db_app_password')+'@db:5432/traceweave\n',0o444)
    if not (private/'smtp_password').exists():atomic(private/'smtp_password','\n',0o444)
    tls=[private/n for n in ['ca.key','ca.crt','db.key','db.crt']]
    if any(p.exists() for p in tls) and not all(p.exists() for p in tls):
        fail('Incomplete TLS material; inspect private setup before continuing.')
    if not all(p.exists() for p in tls):
        temporary=private/('tls-'+secrets.token_hex(6));temporary.mkdir(mode=0o700)
        conf=temporary/'extensions.cnf'
        conf.write_text('subjectAltName=DNS:db\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n')
        commands=[['openssl','req','-x509','-newkey','rsa:3072','-nodes','-days','3650','-subj','/CN=TraceWeave installation CA','-keyout','ca.key','-out','ca.crt'],['openssl','req','-new','-newkey','rsa:3072','-nodes','-subj','/CN=db','-keyout','db.key','-out','db.csr'],['openssl','x509','-req','-in','db.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial','-days','825','-extfile','extensions.cnf','-out','db.crt']]
        for cmd in commands:
            if subprocess.run(cmd,cwd=temporary,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE).returncode:fail('TLS generation failed.')
        for target in tls:
            shutil.copyfile(temporary/target.name,target);os.chmod(target,0o600 if target.name=='ca.key' else 0o444)
        shutil.rmtree(temporary)
    operator_owned(private)
    for root in [DATA,Path('/previous-assets'),Path('/gateway-data'),Path('/gateway-config')]:
        if root.exists():os.chown(root,10001,10001);os.chmod(root,0o700 if root==DATA else 0o755)
    (DATA/'blobs').mkdir(mode=0o700,exist_ok=True);os.chown(DATA/'blobs',10001,10001)
    print('Private secrets, TLS and volume permissions prepared; existing secrets preserved.')

def backup(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}',name):fail('Invalid backup identifier.')
    destination=STATE/'backups'/name
    if destination.exists() or destination.is_symlink():fail('Backup identifier already exists.')
    c=connect()
    try:
        with c.cursor() as q:
            q.execute('SELECT pg_try_advisory_lock(%s)',(LOCK,))
            if not q.fetchone()[0]:fail('Backend/CLI is active; offline backup refused.')
        version,blobs=snapshot(c); migrations=history(c)
        originals=DATA/'blobs'; sources=safe_files(originals)
        for source in sources:
            relative=source.relative_to(originals).as_posix()
            if not re.fullmatch(r'(?:(?:images|audio|video|files)/)?[a-f0-9]{2}/[a-f0-9]{64}',relative):fail('Unexpected original storage key.')
        database_size=database_bytes(c)
        required=capacity_budget(database_size,sum(source.stat().st_size for source in sources))
        backup_storage=destination.parent if destination.parent.exists() else STATE
        require_capacity(backup_storage,required,'backup')
        destination.mkdir(parents=True,mode=0o700,exist_ok=False)
        dump=destination/'database.dump'
        with dump.open('xb') as output:
            os.chmod(dump,0o600)
            checked_process(['pg_dump','--format=custom','--no-owner','--no-acl'],c,output)
            output.flush();os.fsync(output.fileno())
        out=destination/'blobs';out.mkdir(mode=0o700)
        manifest=[]
        for source in sources:
            relative=source.relative_to(originals).as_posix()
            if not re.fullmatch(r'(?:(?:images|audio|video|files)/)?[a-f0-9]{2}/[a-f0-9]{64}',relative):fail('Unexpected original storage key.')
            target=out/relative;copy_file(source,target,c)
            manifest.append({'path':relative,'bytes':target.stat().st_size,'sha256':sha(target)})
        by_path={item['path']:item for item in manifest}
        for item in blobs:
            if by_path.get(item['path']) != item:fail('Database original reference does not match the filesystem.')
        check_connection(c)
        selected=STATE/'backup-release.json'
        release=json.loads((selected if selected.exists() else STATE/'release.json').read_text())
        if release['migrations']!=migrations:fail('Backup release metadata differs from database history.')
        value={'formatVersion':1,'postgresVersion':version,'databaseBytes':database_size,'migrations':migrations,'release':release,'dumpSHA256':sha(dump),'originals':manifest,'databaseOriginals':blobs,'createdAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        atomic(destination/'manifest.json',json.dumps(value,indent=2)+'\n')
        operator_owned(destination);os.chown(destination.parent,int(os.environ.get('TW_OPERATOR_UID','0')),int(os.environ.get('TW_OPERATOR_GID','0')))
        print(json.dumps({'backup':name,'originalCount':len(manifest),'status':'verified'}))
    finally:c.close()

def validate_backup(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}',name):fail('Invalid backup identifier.')
    root=STATE/'backups'/name
    if root.is_symlink():fail('Backup must be a real directory.')
    for p in safe_files(root):
        relative=p.relative_to(root).as_posix()
        if not (relative.startswith('blobs/') or relative in ['database.dump','manifest.json']):fail('Unexpected backup file.')
    value=json.loads((root/'manifest.json').read_text())
    if value.get('formatVersion')!=1 or not value.get('postgresVersion','').startswith('18.'):fail('Unsupported backup version.')
    if type(value.get('databaseBytes')) is not int or value['databaseBytes'] <= 0:fail('Backup databaseBytes must be a positive integer.')
    if sha(root/'database.dump')!=value['dumpSHA256']:fail('Backup dump checksum mismatch.')
    expected=set()
    by_path={}
    for entry in value['originals']:
        key=entry['path']
        if key in expected or not re.fullmatch(r'(?:(?:images|audio|video|files)/)?[a-f0-9]{2}/[a-f0-9]{64}',key):fail('Invalid/duplicate original key.')
        expected.add(key);p=root/'blobs'/key
        if p.stat().st_size!=entry['bytes'] or sha(p)!=entry['sha256']:fail('Backup original checksum mismatch.')
        by_path[key]=entry
    references=set()
    for entry in value['databaseOriginals']:
        key=entry['path']
        if key in references or by_path.get(key)!=entry:fail('Backup database reference does not match its original.')
        references.add(key)
    if value['release']['migrations']!=value['migrations']:fail('Backup release differs from migration history.')
    if set(p.relative_to(root/'blobs').as_posix() for p in safe_files(root/'blobs'))!=expected:fail('Unexpected/missing originals in backup.')
    subprocess.run(['pg_restore','--list',str(root/'database.dump')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
    return root,value

def restore(name):
    root,value=validate_backup(name)
    sources=safe_files(root/'blobs')
    required=capacity_budget(value['databaseBytes'],sum(source.stat().st_size for source in sources))
    require_capacity(DATA,required,'original restore')
    require_capacity(DATABASE_CAPACITY,required,'database restore')
    c=connect()
    try:
        with c.cursor() as q:
            q.execute('SELECT pg_try_advisory_lock(%s)',(LOCK,))
            if not q.fetchone()[0]:fail('Restore maintenance is busy.')
            q.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
            if q.fetchone()[0]:fail('Restore requires a new empty database.')
        if list((DATA/'blobs').iterdir()):fail('Restore requires clean file storage.')
        checked_process(['pg_restore','--exit-on-error','--single-transaction','--no-owner','--no-acl','--dbname','traceweave',str(root/'database.dump')],c)
        for source in sources:
            target=DATA/'blobs'/source.relative_to(root/'blobs');copy_file(source,target,c);os.chown(target,10001,10001);os.chmod(target,0o400)
            for parent in target.parents:
                if parent==DATA:break
                os.chown(parent,10001,10001)
        version,blobs=snapshot(c)
        if history(c)!=value['migrations'] or blobs!=value['databaseOriginals']:fail('Restored database differs from manifest.')
        with c.cursor() as q:
            q.execute('BEGIN')
            q.execute('DELETE FROM sessions')
            q.execute('DELETE FROM account_tokens')
            q.execute("UPDATE upload_tickets SET state='failed',error='{\"code\":\"upload_interrupted\",\"message\":\"Загрузка прервана восстановлением.\",\"fields\":[]}'::jsonb WHERE state IN ('created','receiving','completed')")
            q.execute("UPDATE export_jobs SET state='failed',file_key=NULL,error='{\"code\":\"export_interrupted\",\"message\":\"Экспорт недоступен после восстановления. Создайте новый.\",\"fields\":[]}'::jsonb WHERE state IN ('queued','running','succeeded')")
            q.execute("UPDATE import_jobs SET state='failed',phase='failed',error='{\"code\":\"import_interrupted\",\"message\":\"Импорт прерван восстановлением.\",\"fields\":[]}'::jsonb WHERE phase NOT IN ('committed','cancelled','failed')")
            q.execute('COMMIT')
        check_connection(c)
        print('Restored into empty storage; checksums/references verified; sessions revoked and transient jobs interrupted.')
    finally:c.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init','backup','verify-backup','restore','history','owner-state','copy-assets']);parser.add_argument('value',nargs='?')
    a=parser.parse_args()
    if a.command=='init':initialize()
    elif a.command=='backup':backup(a.value)
    elif a.command=='restore':restore(a.value)
    elif a.command=='verify-backup':validate_backup(a.value);print('Backup manifest, dump and original hashes verified.')
    elif a.command=='copy-assets':
        source=Path('/assets')
        for item in safe_files(source):
            target=Path('/previous-assets')/item.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(item,target);os.chmod(target,0o644)
        print('Previous frontend assets preserved.')
    else:
        c=connect()
        try:
            if a.command=='history':print(json.dumps(history(c)))
            else:
                with c.cursor() as q:
                    q.execute('SELECT count(*),count(email) FROM owners');print(json.dumps(dict(zip(['count','withEmail'],q.fetchone()))))
        finally:c.close()

if __name__=='__main__':
    try:main()
    except Exception as error:
        if isinstance(error,RuntimeError):print(str(error),file=sys.stderr)
        else:print('Private operation failed; credentials and database diagnostics withheld.',file=sys.stderr)
        sys.exit(1)
