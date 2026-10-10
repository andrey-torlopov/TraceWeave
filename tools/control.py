#!/usr/bin/env python3
"""TraceWeave operator CLI. Persistent phases fail closed; data volumes are never removed."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parent.parent
RUNTIME=Path(os.environ.get('TW_RUNTIME_DIR',str(ROOT/'runtime'))).absolute()
PG_IMAGE='postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
GATEWAY_IMAGE='caddy:2.11.2-alpine@sha256:834468128c7696cec0ceea6172f7d692daf645ae51983ca76e39da54a97c570d'
TOOLS_TAG='traceweave/tools:docker-1'
class Failure(RuntimeError):pass

def operator_ids():
    return (int(os.environ.get('TW_OPERATOR_UID',os.getuid())),int(os.environ.get('TW_OPERATOR_GID',os.getgid())))

def operator_owned(path):
    if os.getuid()==0:os.chown(path,*operator_ids())

def execute(args,capture=False,interactive=False,check=True,env=None):
    child=os.environ.copy()
    # Prevent inherited Compose/PG settings from selecting another installation.
    for key in list(child):
        if key.startswith(('COMPOSE_','PG')):child.pop(key)
    if env:child.update(env)
    result=subprocess.run(args,cwd=ROOT,env=child,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,stdin=None if interactive else subprocess.DEVNULL)
    if check and result.returncode:
        raise Failure('Command failed: '+args[0]+' '+('compose' if 'compose' in args else args[1] if len(args)>1 else '')+'. Inspect private diagnostics with logs; maintenance is preserved.')
    return result.stdout.strip() if capture else result.returncode

def atomic(path,value,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.tmp-'+secrets.token_hex(5))
    with temp.open('x') as f:
        os.chmod(temp,mode);f.write(value);f.flush();os.fsync(f.fileno())
    operator_owned(temp)
    temp.replace(path)
    directory=os.open(str(path.parent),os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)

def write_json(path,value,mode=0o600):atomic(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n',mode)
def read_json(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):raise Failure('Missing or invalid '+str(path)+'.') from None

def hash_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

@contextmanager
def operation_lock():
    if RUNTIME.is_symlink():raise Failure('Runtime must not be a symlink.')
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(RUNTIME,0o700);operator_owned(RUNTIME)
    with (RUNTIME/'operation.lock').open('a+') as f:
        os.chmod(RUNTIME/'operation.lock',0o600);operator_owned(RUNTIME/'operation.lock')
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Failure('Another installation operation is running.') from None
        yield

def load_config():return read_json(RUNTIME/'installation.json')
def manifest(path):
    return validate_manifest(read_json(path))

def validate_manifest(m):
    if m.get('formatVersion')!=1 or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}',m.get('releaseId','')):raise Failure('Invalid release manifest.')
    for key in ['backend','frontend','postgres','gateway','tools']:
        image=m.get('images',{}).get(key,'')
        if not re.fullmatch(r'(?:[a-zA-Z0-9._/:+-]+@)?sha256:[a-f0-9]{64}',image):raise Failure('Release images must use immutable digests/image IDs: '+key)
    for key in ['contractHash','backendContractHash']:
        if not re.fullmatch('[a-f0-9]{64}',m.get(key,'')):raise Failure('Invalid contract hash: '+key)
    for key in ['frontendVersion','frontendReleaseId','backendVersion']:
        if not re.fullmatch('[a-zA-Z0-9._-]{1,80}',m.get(key,'')):raise Failure('Invalid component version: '+key)
    if m.get('postgresMajor')!=18:raise Failure('PostgreSQL major changes need a separate database upgrade plan.')
    if not m.get('migrations') or not isinstance(m.get('supportedClientContractHashes'),list):raise Failure('Incomplete migration/client compatibility metadata.')
    if m['contractHash'] not in m['supportedClientContractHashes']:raise Failure('Release does not support its own client.')
    expected_versions=list(range(1,len(m['migrations'])+1))
    if [v.get('version') for v in m['migrations']]!=expected_versions or any(not re.fullmatch('[a-f0-9]{64}',v.get('sha256','')) for v in m['migrations']):raise Failure('Invalid migration history.')
    for value in m['supportedClientContractHashes']:
        if not re.fullmatch('[a-f0-9]{64}',value):raise Failure('Invalid supported contract hash.')
    return m

def current():return manifest(RUNTIME/'release.json')
def compose_env(config,release):
    values=dict(TW_INSTALL_ID=config['installId'],TW_PUBLIC_ORIGIN=config['origin'],TW_PORT=str(config['port']),TW_RUNTIME_DIR=str(RUNTIME),TW_APPLICATION_SUBNET=config['subnet'],TW_GATEWAY_IP=config['gatewayIP'],TW_DATABASE_VOLUME=config['volumes']['database'],TW_FILES_VOLUME=config['volumes']['files'],TW_ASSETS_VOLUME=config['volumes']['assets'],TW_GATEWAY_DATA_VOLUME=config['volumes']['gatewayData'],TW_GATEWAY_CONFIG_VOLUME=config['volumes']['gatewayConfig'],TW_BACKEND_IMAGE=release['images']['backend'],TW_FRONTEND_IMAGE=release['images']['frontend'],TW_POSTGRES_IMAGE=release['images']['postgres'],TW_GATEWAY_IMAGE=release['images']['gateway'],TW_TOOLS_IMAGE=release['images']['tools'],TW_SUPPORTED_CLIENT_CONTRACTS=','.join(release['supportedClientContractHashes']),TW_REGISTRATION_ENABLED=str(config.get('registrationEnabled',False)).lower(),TW_SMTP_URL=config.get('smtpURL',''),TW_SMTP_USER=config.get('smtpUser',''),TW_SMTP_FROM=config.get('smtpFrom',''))
    values['TW_SERVER_BIND']=config.get('serverBind','0.0.0.0')
    values['TW_APPLICATION_DYNAMIC_RANGE']=config.get('dynamicIPRange','')
    values['TW_OPERATOR_UID'],values['TW_OPERATOR_GID']=map(str,operator_ids())
    return values

def compose(*args,config=None,release=None,capture=False,interactive=False,check=True):
    config=config or load_config();release=release or current()
    env=compose_env(config,release)
    cmd=['docker','compose','--project-directory',str(ROOT),'-f',str(ROOT/'compose.yaml')]
    if config['mode']=='server':cmd+=['-f',str(ROOT/'compose.server.yaml')]
    return execute(cmd+list(args),capture,interactive,check,env)

def phase(name,**extra):
    value={'phase':name,'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra}
    write_json(RUNTIME/'operation.json',value)
    with (RUNTIME/'journal.jsonl').open('a') as f:
        os.chmod(RUNTIME/'journal.jsonl',0o600);f.write(json.dumps(value)+'\n');f.flush();os.fsync(f.fileno())
    operator_owned(RUNTIME/'journal.jsonl')

def container(service,config=None,release=None,include_stopped=False):
    options=['ps']+(['-a'] if include_stopped else [])+['-q',service]
    return compose(*options,config=config,release=release,capture=True)

def is_running(service):
    cid=container(service)
    return bool(cid and execute(['docker','inspect','--format','{{.State.Running}}',cid],capture=True)=='true')

def release_metadata(release):return {k:release[k] for k in ['releaseId','frontendVersion','contractHash','supportedClientContractHashes']}

def caddy_config(config,release,maintenance):
    origin=urlsplit(config['origin']);host=origin.netloc
    html=(ROOT/'gateway/maintenance.html').read_text().strip()
    headers="""header {
        X-Content-Type-Options nosniff
        Referrer-Policy no-referrer
        Content-Security-Policy \"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; frame-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'\"
    }"""
    common='''handle /gateway-health {\n        respond "ok" 200\n    }
    handle /release.json {\n        root * /etc/traceweave\n        header Cache-Control no-store\n        header Content-Type application/json\n        file_server\n    }\n'''+headers+'\n'
    if maintenance:
        error=json.dumps({'error':{'code':'service_maintenance','message':'Идёт обслуживание сервиса.','requestId':'00000000-0000-4000-8000-000000000000','details':None}},ensure_ascii=False,separators=(',',':'))
        common+='''header Cache-Control no-store
    header Retry-After 15
    @api path /api/* /health/*
    handle @api {\n        header Content-Type application/json\n        respond '''+json.dumps(error,ensure_ascii=False)+''' 503\n    }
    handle {\n        header Content-Type "text/html; charset=utf-8"\n        respond '''+json.dumps(html,ensure_ascii=False)+''' 503\n    }\n'''
    else:
        common+='''@api path /api/* /health/*
    handle @api {
        reverse_proxy backend:8080 {
            header_up X-Forwarded-For {http.request.remote.host}
            header_up X-Forwarded-Proto '''+origin.scheme+'''
            header_up -X-Forwarded-Host
            flush_interval -1
            transport http {\n                response_header_timeout 30s\n            }
        }
    }
    handle {\n        reverse_proxy frontend:8080\n    }\n'''
    # /gateway-health is reachable on the internal HTTP port even on an HTTPS host.
    global_config='{\n    admin 127.0.0.1:2019\n    http_port 8080\n    https_port 8443\n}\n'
    site='http://'+origin.hostname if config['mode']=='local' else 'https://'+origin.hostname
    text=global_config+'\n'+site+' {\n    '+common+'}\n'
    forbidden=json.dumps({'error':{'code':'forbidden','message':'Forbidden host','requestId':'00000000-0000-4000-8000-000000000000','details':None}},separators=(',',':'))
    rejection='''@badApi path /api/* /health/*
    handle @badApi {\n        header Content-Type application/json\n        header Cache-Control no-store\n        respond '''+json.dumps(forbidden)+''' 403\n    }
    handle {\n        respond "Forbidden host" 403\n    }\n'''
    if config['mode']=='server':text+='\n:8080 {\n    handle /gateway-health {\n        respond "ok" 200\n    }\n    '+rejection+'}\n\nhttps://:8443 {\n    '+rejection+'}\n'
    else:text+='\n:8080 {\n    '+rejection+'}\n'
    directory=RUNTIME/'gateway';directory.mkdir(mode=0o755,parents=True,exist_ok=True);os.chmod(directory,0o755)
    write_json(directory/'release.json',release_metadata(release),0o644)
    atomic(directory/'Caddyfile',text,0o644)
    write_json(RUNTIME/'maintenance.json',{'enabled':maintenance},0o600)

def reload_gateway(config,release,enabled):
    caddy_config(config,release,enabled)
    if container('gateway',config,release):
        compose('exec','-T','gateway','caddy','reload','--config','/etc/traceweave/Caddyfile','--adapter','caddyfile',config=config,release=release)
    else:compose('up','-d','--no-deps','gateway',config=config,release=release)

def public_request(path,config=None):
    config=config or load_config()
    if os.environ.get('TW_CONTAINER_CONTROL')=='1' and config['mode']=='local':
        text=compose('exec','-T','gateway','wget','-S','-O','-','--header','Host: '+urlsplit(config['origin']).netloc,'http://127.0.0.1:8080'+path,capture=True,check=False)
        # Use a short-lived curl tools container on the application network for precise status.
        network=execute(['docker','inspect','--format','{{range $name, $value := .NetworkSettings.Networks}}{{$name}} {{end}}',container('gateway')],capture=True).split()
        appnet=next(n for n in network if n.endswith('_application'))
        out=execute(['docker','run','--rm','--network',appnet,'--entrypoint','curl',current()['images']['tools'],'-sS','--max-time','10','-w','\n%{http_code}','-H','Host: '+urlsplit(config['origin']).netloc,'http://'+config['gatewayIP']+':8080'+path],capture=True)
        body,status=out.rsplit('\n',1);return int(status),body
    try:
        with urlopen(Request(config['origin']+path,headers={'Cache-Control':'no-cache'}),timeout=10) as response:return response.status,response.read(2*1024*1024).decode('utf-8')
    except HTTPError as response:return response.code,response.read(2*1024*1024).decode('utf-8')

def maintenance_check(config):
    for path in ['/','/api/v1/session']:
        code,body=public_request(path,config)
        if code!=503:raise Failure('Gateway maintenance check failed for '+path)
        if path.startswith('/api') and json.loads(body)['error']['code']!='service_maintenance':raise Failure('Gateway returned invalid maintenance JSON.')

def ready(config=None,release=None):
    config=config or load_config();release=release or current()
    # Check private backend route with public Host. It is never published on the host.
    compose('exec','-T','backend','/usr/local/bin/traceweave-healthcheck',config=config,release=release)
    compose('exec','-T','frontend','wget','-q','--spider','http://127.0.0.1:8080/',config=config,release=release)
    baked=json.loads(compose('exec','-T','frontend','cat','/opt/traceweave/frontend-release.json',config=config,release=release,capture=True))
    if baked!={'releaseId':release['frontendReleaseId'],'frontendVersion':release['frontendVersion'],'contractHash':release['contractHash']}:
        raise Failure('Frontend image metadata differs from selected release.')
    backend=json.loads(compose('exec','-T','backend','cat','/app/backend-release.json',config=config,release=release,capture=True))
    if backend.get('backendVersion')!=release['backendVersion'] or backend.get('contractHash')!=release['backendContractHash']:
        raise Failure('Backend image metadata differs from selected release.')
    history=json.loads(compose('run','--rm','-T','--no-deps','ops','history',config=config,release=release,capture=True))
    if history!=release['migrations']:raise Failure('Database migration history differs from selected release.')

def wait_services(services,config=None,release=None):
    compose('up','-d','--wait','--wait-timeout','240',*services,config=config,release=release)

def start_services(config,release):
    # Reserve the gateway's trusted fixed address before dynamic application
    # endpoints connect. This also supports older installations without ip_range.
    wait_services(['db','gateway'],config,release)
    wait_services(['backend','frontend'],config,release)

def stop_backend(config,release):
    cid=container('backend',config,release,include_stopped=True)
    compose('stop','--timeout','180','backend',config=config,release=release)
    if cid:
        state=json.loads(execute(['docker','inspect','--format','{{json .State}}',cid],capture=True))
        if state['Running'] or state.get('OOMKilled') or state.get('ExitCode') not in [0,143]:
            raise Failure('Backend did not stop gracefully. Maintenance is preserved; inspect interrupted jobs before recovery.')

def ensure_images(release):
    for image in release['images'].values():
        if execute(['docker','image','inspect',image],capture=True,check=False)=='':
            if image.startswith('sha256:'):raise Failure('Local release image missing; run build-source or import published images.')
            execute(['docker','pull',image])

def confirm(message,yes=False):
    if yes:return
    if not sys.stdin.isatty():raise Failure(message+' Confirmation requires a TTY (or explicit --yes for a reviewed synthetic operation).')
    if input(message+'\nВведите YES: ')!='YES':raise Failure('Operation cancelled.')

def unused_port(port):
    if os.environ.get('TW_CONTAINER_CONTROL')=='1':
        # A loopback bind inside the operator namespace cannot test the host.
        # Reserve a real daemon-published host port before persisting config.
        image=os.environ.get('TW_OPERATOR_IMAGE',TOOLS_TAG)
        cid=execute(['docker','run','--rm','-d','-p','127.0.0.1:'+str(port)+':12345','--entrypoint','sleep',image,'30'],capture=True)
        try:return
        finally:execute(['docker','stop','--time','1',cid],capture=True)
    with socket.socket() as s:
        try:s.bind(('127.0.0.1',port))
        except OSError:raise Failure('Local port '+str(port)+' is busy; choose --port.') from None

def initialize_volumes(config,release):
    uid,gid=map(str,operator_ids())
    execute(['docker','run','--rm','-e','TW_OPERATOR_UID='+uid,'-e','TW_OPERATOR_GID='+gid,'--mount','type=bind,source='+str(RUNTIME)+',target=/state','-v',config['volumes']['files']+':/data','-v',config['volumes']['assets']+':/previous-assets','-v',config['volumes']['gatewayData']+':/gateway-data','-v',config['volumes']['gatewayConfig']+':/gateway-config',release['images']['tools'],'init'])

def configure_mail(a,config=None,release=None,bootstrap_only=False):
    config=config or load_config();release=release or current()
    url=urlsplit(a.smtp_url or '')
    if url.scheme not in ['smtp','smtps'] or not url.hostname or url.username or url.password or url.path not in ['', '/'] or url.query or url.fragment:
        raise Failure('Provide --smtp-url smtp(s)://HOST:PORT without credentials or a path.')
    if not a.smtp_user or not a.smtp_from:raise Failure('Mail requires --smtp-user and --smtp-from.')
    if a.enable_registration and config['mode']!='server':raise Failure('Public registration requires HTTPS.')
    if not sys.stdin.isatty():raise Failure('SMTP password requires hidden input from a TTY.')
    password=getpass.getpass('Пароль SMTP: ')
    if not password or len(password.encode())>4096 or any(c in password for c in ['\r','\n','\x00']):raise Failure('Invalid SMTP password.')
    if not bootstrap_only:
        phase('maintenance-configuring-mail');reload_gateway(config,release,True);maintenance_check(config)
        stop_backend(config,release)
    atomic(RUNTIME/'secrets/smtp_password',password+'\n',0o444)
    config.update(smtpURL=a.smtp_url,smtpUser=a.smtp_user,smtpFrom=a.smtp_from,registrationEnabled=bool(a.enable_registration))
    write_json(RUNTIME/'installation.json',config)
    if not bootstrap_only:
        compose('up','-d','--no-deps','--force-recreate','--wait','--wait-timeout','240','backend',config=config,release=release)
        ready(config,release);reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId'])
        print('SMTP configured; registration '+('enabled' if a.enable_registration else 'disabled')+'.')

def bootstrap_text(value,prompt,flag):
    if value:return value
    if not sys.stdin.isatty():raise Failure('Первый аккаунт: нужен терминал для ввода '+flag+'; либо передайте этот аргумент явно.')
    try:
        while True:
            value=input(prompt).strip()
            if value:return value
            print('Введите непустое значение.')
    except EOFError:raise Failure('Ввод первого аккаунта прерван. Повторите bootstrap в терминале.') from None

def stable_version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value):return None
    return tuple(int(part) for part in value.split('.'))

def bootstrap_update(old,path):
    """Discover only a local, newer stable application pair and a valid update."""
    target=manifest(path)
    keys=['backendVersion','frontendVersion']
    before=[stable_version(old[key]) for key in keys];after=[stable_version(target[key]) for key in keys]
    if not all(before+after) or not stable_version(old['releaseId']) or not stable_version(target['releaseId']):
        return None
    if stable_version(target['releaseId'])<stable_version(old['releaseId']) or any(
            new<previous for previous,new in zip(before,after)) or before==after:return None
    try:validate_update(old,target)
    except Failure:
        selected_path=path.parent/(target['releaseId']+'-update.json')
        if not selected_path.exists():selected_path=ROOT/'releases'/(target['releaseId']+'-update.json')
        selected=manifest(selected_path)
        fields=['formatVersion','releaseId','frontendReleaseId','frontendVersion','backendVersion',
                'contractHash','backendContractHash','supportedClientContractHashes','migrations','postgresMajor','platforms']
        if any(selected.get(key)!=target.get(key) for key in fields) or any(
                selected['images'][key]!=target['images'][key] for key in ['backend','frontend']):
            raise Failure('Compatible manifest does not match the selected application release.')
        for key in ['backend','frontend','backendDiffHash','frontendDiffHash']:
            if selected.get('source',{}).get(key)!=target.get('source',{}).get(key):
                raise Failure('Compatible manifest does not match the selected application source.')
        validate_update(old,selected)
        return selected_path,selected
    return path,target

def bootstrap_existing(a,old,state):
    print('Установлено: backend '+old['backendVersion']+', frontend '+old['frontendVersion']+'.')
    if not isinstance(state,dict) or state.get('phase') not in ['ready','stopped']:
        raise Failure('Установка содержит незавершённую операцию. Обновление и повторная миграция не запущены; '
                      'прочитайте status и используйте resume/rollback или восстановление по docs/ru/operations.md.')
    path=Path(a.release).resolve()
    try:discovered=bootstrap_update(old,path)
    except (Failure,OSError,ValueError,KeyError,TypeError,AttributeError):
        print('Локальный manifest обновления отсутствует, повреждён или несовместим. Запускаю установленный выпуск.')
        start();return
    if discovered is None:
        print('Более новая совместимая пара приложений не выбрана. Запускаю установленный выпуск.')
        start();return
    selected_path,selected=discovered
    print('Доступно обновление: backend '+selected['backendVersion']+', frontend '+selected['frontendVersion']+'.')
    if 'backend' in changes(old,selected):
        print('Перед обновлением будет создана и проверена резервная копия базы и оригиналов.')
    if selected['migrations']==old['migrations']:
        print('Изменений схемы базы нет; миграции не нужны. Данные и вход в аккаунт сохраняются.')
    else:
        print('После резервной копии схема базы обновится автоматически. Для возврата прежней схемы потребуется '
              'восстановление копии; данные и вход в аккаунт сохраняются.')
    accepted=a.yes
    if not accepted and sys.stdin.isatty():
        try:accepted=input('Обновить сейчас? [y/N]: ').strip().casefold() in ['y','yes','д','да']
        except EOFError:accepted=False
    if not accepted:
        print('Обновление отложено. Для обновления этой установки выполните:\n'+
              'TW_RUNTIME_DIR='+shlex.quote(str(RUNTIME))+' '+shlex.quote(str(ROOT/'traceweave.sh'))+
              ' update --release '+shlex.quote(str(selected_path)))
        start();return
    selected_args=argparse.Namespace(**vars(a));selected_args.release=str(selected_path);selected_args.yes=True
    update_command(selected_args,reviewed_release=selected,start_stopped=state['phase']=='stopped')

def bootstrap(a,resuming=False):
    if (RUNTIME/'installation.json').exists():
        config=load_config();release=current()
        if config['origin']!=a.origin and a.origin!='http://127.0.0.1:8080':raise Failure('Existing installation origin is fixed; use a separate runtime for another installation.')
        state=read_json(RUNTIME/'operation.json')
        if not resuming:bootstrap_existing(a,release,state);return
        if not isinstance(state,dict) or state.get('phase') not in [
                'bootstrap-preparing','bootstrap-migrating','bootstrap-owner','bootstrap-verifying']:
            raise Failure('Unknown interrupted bootstrap phase; preserve runtime and use recovery.')
    else:
        if (RUNTIME/'operation.json').exists():
            raise Failure('Installation configuration is incomplete. Preserve runtime and use recovery before bootstrap.')
        if Path(a.release)==ROOT/'releases/stable.json' and not Path(a.release).is_file():
            raise Failure('Готовый релиз ещё не установлен: releases/stable.json отсутствует. '
                          'Образы TraceWeave необходимо опубликовать вместе с этим манифестом. '
                          'Для уже собранного локального релиза передайте путь к его манифесту через --release. '
                          'Подробности: docs/local-use.md.')
        release=manifest(Path(a.release).resolve())
        origin=urlsplit(a.origin)
        if origin.path or origin.query or origin.fragment or origin.username or origin.password or origin.scheme not in ['http','https'] or not origin.hostname:raise Failure('Origin must be an HTTP(S) origin without a path.')
        if origin.scheme=='http' and origin.hostname!='127.0.0.1':raise Failure('Local HTTP is restricted to 127.0.0.1.')
        mode='local' if origin.scheme=='http' else 'server';port=a.port or origin.port or (8080 if mode=='local' else 443)
        if mode=='server' and origin.port not in [None,443]:raise Failure('Server HTTPS origin must use standard port443.')
        if mode=='local':unused_port(port);a.origin='http://127.0.0.1:'+str(port)
        install='tw-'+secrets.token_hex(6);octet=secrets.randbelow(180)+30
        config={'installId':install,'origin':a.origin,'port':port,'mode':mode,'subnet':'172.28.'+str(octet)+'.0/24','gatewayIP':'172.28.'+str(octet)+'.2','registrationEnabled':False,'volumes':{key:install+'-'+suffix for key,suffix in [('database','postgres'),('files','files'),('assets','assets'),('gatewayData','gateway-data'),('gatewayConfig','gateway-config')]}}
        config['dynamicIPRange']='172.28.'+str(octet)+'.128/25'
        write_json(RUNTIME/'installation.json',config);write_json(RUNTIME/'release.json',release)
    phase('bootstrap-preparing');ensure_images(release)
    for volume in config['volumes'].values():execute(['docker','volume','create','--label','traceweave.installation='+config['installId'],volume],capture=True)
    # No service is exposed until all private settings/permissions exist.
    initialize_volumes(config,release)
    if a.smtp_url:configure_mail(a,config,release,bootstrap_only=True)
    caddy_config(config,release,True);wait_services(['db','gateway'],config,release);maintenance_check(config)
    stop_backend(config,release)
    phase('bootstrap-migrating');compose('run','--rm','-T','--no-deps','migrate',config=config,release=release)
    owner=json.loads(compose('run','--rm','-T','--no-deps','ops','owner-state',config=config,release=release,capture=True))
    if owner['count']==0:
        a.email=bootstrap_text(a.email,'Email для входа: ','--email')
        a.name=bootstrap_text(a.name,'Ваше имя: ','--name')
        phase('bootstrap-owner');compose('run','--rm','--no-deps','owner','account','create','--email',a.email,'--name',a.name,config=config,release=release,interactive=True)
    elif owner['count']!=owner['withEmail']:
        a.email=bootstrap_text(a.email,'Email старого владельца (UUID и пароль сохранятся): ','--email')
        compose('run','--rm','--no-deps','owner','account','attach-email','--email',a.email,config=config,release=release,interactive=True)
    phase('bootstrap-verifying');wait_services(['backend','frontend'],config,release);ready(config,release)
    reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId'])
    print('TraceWeave: '+config['origin'])

def start():
    config=load_config();release=current();state=read_json(RUNTIME/'operation.json')
    if state['phase'] not in ['ready','stopped']:raise Failure('Interrupted operation: start refused. Use resume or explicit recovery while maintenance remains enabled.')
    ensure_images(release);caddy_config(config,release,True);start_services(config,release);ready(config,release);reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId']);print(config['origin'])

def stop():
    config=load_config();release=current()
    state=read_json(RUNTIME/'operation.json')
    safe=state['phase'] in ['ready','stopped']
    phase('stopping',previousPhase=state['phase'])
    if is_running('gateway'):reload_gateway(config,release,True);maintenance_check(config)
    else:caddy_config(config,release,True)
    stop_backend(config,release);compose('stop','--timeout','180','frontend','gateway','db',config=config,release=release)
    phase('stopped' if safe else 'stopped-interrupted',releaseId=release['releaseId'],previousOperation=state)

def do_backup(config=None,release=None):
    config=config or load_config();release=release or current()
    history=json.loads(compose('run','--rm','-T','--no-deps','ops','history',config=config,release=release,capture=True))
    if history!=release['migrations']:
        pending=manifest(RUNTIME/'pending-release.json')
        if history!=pending['migrations']:raise Failure('Cannot back up an unknown schema as a compatible release.')
        release=pending
    write_json(RUNTIME/'backup-release.json',release)
    name=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
    compose('run','--rm','-T','--no-deps','ops','backup',name,config=config,release=release)
    return name

def backup_command():
    config=load_config();release=current();phase('backup-entering')
    reload_gateway(config,release,True);maintenance_check(config);stop_backend(config,release)
    phase('backup-copying');name=do_backup(config,release);phase('backup-verifying',backup=name)
    wait_services(['backend'],config,release);ready(config,release);reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId'],backup=name);print('Backup: '+str(RUNTIME/'backups'/name))

def changes(old,new):return [key for key in old['images'] if old['images'][key]!=new['images'][key]]
def validate_update(old,new):
    if new['images']['postgres']!=old['images']['postgres'] or new['images']['gateway']!=old['images']['gateway'] or new['images']['tools']!=old['images']['tools']:raise Failure('Database/gateway/tools image updates require a separate maintenance procedure.')
    if not all(v in new['supportedClientContractHashes'] for v in old['supportedClientContractHashes']):raise Failure('Release would strand a supported old client/pending command; incompatible update refused.')
    old_m=old['migrations'];new_m=new['migrations']
    if new_m[:len(old_m)]!=old_m:raise Failure('Migration history is not append-only.')
    if new_m!=old_m and new['images']['backend']==old['images']['backend']:raise Failure('Schema changes require a new backend image.')
    if new['images']['backend']==old['images']['backend'] and new['supportedClientContractHashes']!=old['supportedClientContractHashes']:
        raise Failure('New client compatibility metadata requires a coordinated backend release.')

def preserve_assets(config,release):
    cid=container('frontend',config,release)
    if not cid:return
    temporary=RUNTIME/('assets-'+secrets.token_hex(4));temporary.mkdir(mode=0o700)
    execute(['docker','cp',cid+':/srv/assets/.',str(temporary)])
    try:
        execute(['docker','run','--rm','--mount','type=bind,source='+str(temporary)+',target=/assets,readonly','-v',config['volumes']['assets']+':/previous-assets',release['images']['tools'],'copy-assets'])
    finally:shutil.rmtree(temporary)

def install_update(config,old,new,backup=None):
    changed=changes(old,new)
    phase('update-entering',old=old['releaseId'],target=new['releaseId'],changed=changed,backup=backup)
    reload_gateway(config,old,True);maintenance_check(config)
    phase('update-maintenance',old=old['releaseId'],target=new['releaseId'],changed=changed,backup=backup)
    preserve_assets(config,old)
    if 'backend' in changed:
        stop_backend(config,old)
        if not backup:backup=do_backup(config,old)
        phase('update-backed-up',old=old['releaseId'],target=new['releaseId'],backup=backup)
        if new['migrations']!=old['migrations']:
            phase('update-migrating',old=old['releaseId'],target=new['releaseId'],backup=backup)
            compose('run','--rm','-T','--no-deps','migrate',config=config,release=new)
    phase('update-starting',old=old['releaseId'],target=new['releaseId'],backup=backup)
    for service in ['backend','frontend']:
        if service in changed:compose('up','-d','--no-deps','--wait','--wait-timeout','240',service,config=config,release=new)
    for service in ['backend','frontend']:
        if service not in changed and not is_running(service):
            compose('up','-d','--no-deps','--wait','--wait-timeout','240',service,config=config,release=new)
    ready(config,new)
    write_json(RUNTIME/'previous-release.json',old);write_json(RUNTIME/'release.json',new)
    reload_gateway(config,new,False);phase('ready',releaseId=new['releaseId'],backup=backup);print('Installed '+new['releaseId'])

def update_command(a,reviewed_release=None,start_stopped=False):
    config=load_config();old=current();new=manifest(Path(a.release).resolve())
    if reviewed_release is not None and new!=reviewed_release:
        raise Failure('Выбранный manifest изменился во время подтверждения. Повторите bootstrap для проверки нового выпуска.')
    validate_update(old,new)
    if start_stopped:start()
    ensure_images(new)
    changed=changes(old,new)
    if not changed:print('Selected release already installed.');return
    print(json.dumps({'current':old['releaseId'],'target':new['releaseId'],'changed':changed,'schemaChanged':old['migrations']!=new['migrations'],'rollback':'image rollback' if old['migrations']==new['migrations'] else 'restore into new volumes'},ensure_ascii=False))
    if shutil.disk_usage(RUNTIME).free<1024**3:raise Failure('At least 1GiB free space required; account for the full backup size before updating.')
    confirm('Начать обслуживание и установить выбранный релиз?',a.yes)
    write_json(RUNTIME/'pending-release.json',new);write_json(RUNTIME/'update-source.json',old)
    install_update(config,old,new)

def rollback(a):
    config=load_config();old=read_json(RUNTIME/'update-source.json') if (RUNTIME/'update-source.json').exists() else current();target=manifest(RUNTIME/'previous-release.json') if (RUNTIME/'previous-release.json').exists() and read_json(RUNTIME/'operation.json')['phase']=='ready' else old
    if not is_running('db'):
        caddy_config(config,old,True);wait_services(['db','gateway'],config,old);reload_gateway(config,old,True);maintenance_check(config)
    history=json.loads(compose('run','--rm','-T','--no-deps','ops','history',config=config,release=old,capture=True))
    if history!=target['migrations']:raise Failure('Schema has changed. Image rollback refused; restore the pre-update backup into new volumes, or install a correcting compatible release.')
    confirm('Вернуть предыдущий совместимый релиз? Новые данные сохранятся.',a.yes)
    phase('rollback-entering',target=target['releaseId'])
    reload_gateway(config,target,True);maintenance_check(config);stop_backend(config,old);compose('up','-d','--no-deps','--wait','--wait-timeout','240','backend','frontend',config=config,release=target);ready(config,target);write_json(RUNTIME/'release.json',target);reload_gateway(config,target,False);phase('ready',releaseId=target['releaseId']);print('Rollback completed.')

def restore_command(a):
    config=load_config();old=current();name=Path(a.backup).name
    compose('run','--rm','-T','--no-deps','ops','verify-backup',name,config=config,release=old)
    source=read_json(RUNTIME/'backups'/name/'manifest.json');target=validate_manifest(source['release']);ensure_images(target)
    confirm('Восстановить выбранную копию в НОВЫЕ volumes и переключить установку? Прежние volumes будут сохранены.',a.yes)
    write_json(RUNTIME/'restore-old-installation.json',config);write_json(RUNTIME/'restore-old-release.json',old)
    phase('restore-entering',backup=name)
    reload_gateway(config,old,True);maintenance_check(config);stop_backend(config,old)
    # Preserve the state after the chosen backup so post-backup writes remain recoverable.
    safety=do_backup(config,old);new=json.loads(json.dumps(config));suffix='-restore-'+secrets.token_hex(4)
    new['volumes']['database']+=suffix;new['volumes']['files']+=suffix
    write_json(RUNTIME/'restore-old-installation.json',config);write_json(RUNTIME/'restore-old-release.json',old);write_json(RUNTIME/'restore-target-installation.json',new);write_json(RUNTIME/'restore-target-release.json',target)
    phase('restore-preparing',backup=name,safetyBackup=safety)
    for key in ['database','files']:execute(['docker','volume','create','--label','traceweave.installation='+config['installId'],new['volumes'][key]],capture=True)
    initialize_volumes(new,target)
    compose('stop','db',config=config,release=old);compose('up','-d','--force-recreate','--wait','--wait-timeout','240','db',config=new,release=target)
    phase('restore-copying',backup=name,safetyBackup=safety);compose('run','--rm','-T','--no-deps','ops','restore',name,config=new,release=target)
    phase('restore-verifying',backup=name,safetyBackup=safety)
    compose('up','-d','--no-deps','--force-recreate','--wait','--wait-timeout','240','backend','frontend',config=new,release=target);ready(new,target)
    write_json(RUNTIME/'installation.json',new);write_json(RUNTIME/'previous-release.json',old);write_json(RUNTIME/'release.json',target);reload_gateway(new,target,False);phase('ready',releaseId=target['releaseId'],restoredBackup=name,safetyBackup=safety);print('Restore completed; previous volumes and safety backup preserved.')

def resume(a):
    state=read_json(RUNTIME/'operation.json');name=state['phase']
    if name=='stopped-interrupted':
        state=state['previousOperation'];write_json(RUNTIME/'operation.json',state);name=state['phase']
    if name.startswith('bootstrap-'):bootstrap(a,resuming=True);return
    if name.startswith('update-'):
        confirm('Продолжить прерванное обновление под заглушкой?',a.yes)
        config=load_config();old=manifest(RUNTIME/'update-source.json');target=manifest(RUNTIME/'pending-release.json')
        caddy_config(config,old,True);wait_services(['db','gateway'],config,old);reload_gateway(config,old,True);maintenance_check(config)
        history=json.loads(compose('run','--rm','-T','--no-deps','ops','history',config=config,release=target,capture=True))
        if history not in [old['migrations'],target['migrations']]:raise Failure('Unexpected schema state; leave maintenance enabled and inspect migrations.')
        install_update(config,old,target,backup=state.get('backup'));return
    if name.startswith(('backup-','restart-','stopping','maintenance-')):
        config=load_config();release=current();confirm('Проверить текущий релиз и завершить обслуживание?',a.yes);start_services(config,release);ready(config,release);reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId']);return
    if name.startswith('restore-'):raise Failure('Restore interrupted. Use restore-revert to recover the preserved old volumes, or inspect restore-target-installation.json and complete verification manually before opening access.')
    start()

def restore_revert(a):
    config=load_config();old=read_json(RUNTIME/'restore-old-installation.json');release=manifest(RUNTIME/'restore-old-release.json')
    confirm('Переключить обратно на сохранённые volumes до restore?',a.yes);phase('restore-reverting')
    caddy_config(config,release,True);wait_services(['db','gateway'],config,release);reload_gateway(config,release,True);maintenance_check(config)
    stop_backend(config,release);compose('stop','--timeout','180','db',config=config,release=release)
    compose('up','-d','--force-recreate','--wait','--wait-timeout','240','db',config=old,release=release)
    compose('up','-d','--no-deps','--force-recreate','--wait','--wait-timeout','240','backend','frontend',config=old,release=release)
    ready(old,release);write_json(RUNTIME/'installation.json',old);write_json(RUNTIME/'release.json',release)
    reload_gateway(old,release,False);phase('ready',releaseId=release['releaseId']);print('Previous installation restored; candidate volumes preserved.')

def build_source(a):
    backend=Path(a.backend_path).resolve();frontend=Path(a.frontend_path).resolve()
    if not (backend/'Package.swift').is_file() or not (frontend/'package-lock.json').is_file():raise Failure('Provide independent backend/frontend source checkouts.')
    rid=a.release_id
    if not re.fullmatch('[a-zA-Z0-9._-]{1,80}',rid):raise Failure('Invalid release ID.')
    versions={name:getattr(a,name+'_version',None) for name in ['backend','frontend','delivery']}
    for name,version in versions.items():
        if version is not None and (len(version)>80 or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version)):
            raise Failure('Invalid '+name+' version; use MAJOR.MINOR.PATCH without a v prefix.')
    tagged_delivery=versions['delivery'] is not None
    versions={name:version if version is not None else rid for name,version in versions.items()}
    frontend_release=versions['frontend'] if getattr(a,'frontend_version',None) is not None else rid
    path=ROOT/'releases'/str(rid+'.local.json')
    if path.exists():raise Failure('Release ID already has a local manifest; choose a new --release-id to preserve rollback images.')
    git=lambda p,*args:execute(['git','-c','safe.directory='+str(p),'-C',str(p),*args],capture=True)
    revision=lambda p:git(p,'rev-parse','HEAD')
    dirty=lambda p:hashlib.sha256(git(p,'diff','--no-ext-diff','--no-textconv','HEAD').encode()).hexdigest()
    def state():
        source={'backend':revision(backend),'frontend':revision(frontend),'backendDiffHash':dirty(backend),'frontendDiffHash':dirty(frontend)}
        checkouts=[backend,frontend]
        if tagged_delivery:
            source.update(delivery=revision(ROOT),deliveryDiffHash=dirty(ROOT));checkouts.append(ROOT)
        return source,hash_file(ROOT/'contracts/openapi.yaml'),[git(p,'status','--porcelain=v1','--untracked-files=all') for p in checkouts]
    before=state()
    if any(before[2]):raise Failure('Source checkouts must be committed and clean, including untracked files; no build started.')
    contract=before[1];tools_image='traceweave/tools:'+rid
    def labels(component):
        name=component if component in ['backend','frontend'] else 'delivery'
        repository='TraceWeave'+({'backend':'Backend','frontend':'Frontend'}.get(component,''))
        values={'org.opencontainers.image.version':versions[name],'org.opencontainers.image.source':'https://github.com/andrey-torlopov/'+repository}
        if name in before[0]:values['org.opencontainers.image.revision']=before[0][name]
        if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',versions[name]):values['org.opencontainers.image.ref.name']='v'+versions[name]
        return [argument for key,value in values.items() for argument in ['--label',key+'='+value]]
    execute(['docker','build',*labels('tools'),'-t',tools_image,'-f',str(ROOT/'tools/Dockerfile'),str(ROOT)])
    execute(['docker','build',*labels('gateway'),'-t','traceweave/gateway:'+rid,'-f',str(ROOT/'gateway/Dockerfile'),str(ROOT)])
    execute(['docker','build',*labels('backend'),'--build-arg','BACKEND_VERSION='+versions['backend'],'--build-arg','OPENAPI_CONTRACT_SHA256='+contract,'--build-arg','SOURCE_REVISION='+before[0]['backend'],'-t','traceweave/backend:'+rid,str(backend)])
    execute(['docker','build',*labels('frontend'),'--build-context','contract='+str(ROOT/'contracts'),'--build-arg','OPENAPI_CONTRACT_SHA256='+contract,'--build-arg','RELEASE_ID='+frontend_release,'--build-arg','FRONTEND_VERSION='+versions['frontend'],'-t','traceweave/frontend:'+rid,str(frontend)])
    execute(['docker','pull',PG_IMAGE])
    images={k:execute(['docker','image','inspect','--format','{{.Id}}',v],capture=True) for k,v in [('backend','traceweave/backend:'+rid),('frontend','traceweave/frontend:'+rid),('tools',tools_image),('gateway','traceweave/gateway:'+rid)]}
    images.update(postgres=PG_IMAGE)
    migrations=[]
    for p in sorted((backend/'Sources/ResearchGraphInfrastructure/Resources').glob('*.sql')):
        migrations.append({'version':int(p.name[:4]),'sha256':hash_file(p)})
    if state()!=before:raise Failure('Source or contract changed during build; no release manifest written. Retry with a new ID from stable checkouts.')
    architecture=execute(['docker','info','--format','{{.Architecture}}'],capture=True)
    value={'formatVersion':1,'releaseId':rid,'frontendReleaseId':frontend_release,'frontendVersion':versions['frontend'],'backendVersion':versions['backend'],'backendContractHash':contract,'images':images,'postgresMajor':18,'contractHash':contract,'supportedClientContractHashes':[contract],'migrations':migrations,'platforms':['linux/'+('arm64' if architecture in ['arm64','aarch64'] else 'amd64')],'source':before[0],'validation':'built; run integration before publication','rollback':'same migration history only; otherwise restore verified backup'}
    write_json(path,value,0o644);print('Local immutable release: '+str(path))

def parser():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['bootstrap','start','stop','restart','status','logs','backup','restore','update','rollback','resume','restore-revert','maintenance','configure-mail','account','build-source']);p.add_argument('extra',nargs='*');p.add_argument('--release',default=str(ROOT/'releases/stable.json'));p.add_argument('--release-id',default='docker-1');p.add_argument('--backend-version');p.add_argument('--frontend-version');p.add_argument('--delivery-version');p.add_argument('--origin',default='http://127.0.0.1:8080');p.add_argument('--port',type=int);p.add_argument('--email');p.add_argument('--name');p.add_argument('--backup');p.add_argument('--yes',action='store_true');p.add_argument('--smtp-url');p.add_argument('--smtp-user');p.add_argument('--smtp-from');p.add_argument('--enable-registration',action='store_true');p.add_argument('--backend-path',default=str(ROOT.parent/'TraceWeaveBackend'));p.add_argument('--frontend-path',default=str(ROOT.parent/'TraceWeaveFrontend'));return p

def main():
    a=parser().parse_args()
    execute(['docker','info','--format','{{.ServerVersion}}'],capture=True);execute(['docker','compose','version'],capture=True)
    if a.command=='status':
        config=load_config();release=current();print(json.dumps({'url':config['origin'],'releaseId':release['releaseId'],'operation':read_json(RUNTIME/'operation.json'),'volumes':config['volumes']},ensure_ascii=False,indent=2));compose('ps');return
    if a.command=='logs':
        services=a.extra or ['backend','frontend','gateway','db']
        if any(x not in ['backend','frontend','gateway','db'] for x in services):raise Failure('Unknown service.')
        compose('logs','--tail','100',*services);return
    with operation_lock():
        if (RUNTIME/'operation.json').exists() and a.command in ['backup','update','restart','maintenance','configure-mail']:
            if read_json(RUNTIME/'operation.json')['phase']!='ready':
                raise Failure('An earlier operation is incomplete; use resume/rollback/restore recovery before a new operation.')
        if a.command=='bootstrap':bootstrap(a)
        elif a.command=='start':start()
        elif a.command=='stop':stop()
        elif a.command=='backup':backup_command()
        elif a.command=='update':update_command(a)
        elif a.command=='rollback':rollback(a)
        elif a.command=='resume':resume(a)
        elif a.command=='restore':
            if not a.backup:raise Failure('restore requires --backup NAME from this installation backups directory.')
            restore_command(a)
        elif a.command=='restore-revert':restore_revert(a)
        elif a.command=='configure-mail':configure_mail(a)
        elif a.command=='restart':
            config=load_config();release=current();phase('restart-entering');reload_gateway(config,release,True);maintenance_check(config);stop_backend(config,release);compose('restart','--timeout','180','frontend');wait_services(['backend'],config,release);ready(config,release);reload_gateway(config,release,False);phase('ready',releaseId=release['releaseId'])
        elif a.command=='maintenance':
            config=load_config();release=current()
            if a.extra!=['on']:raise Failure('Only maintenance on is allowed directly. Use resume to verify and reopen.')
            phase('maintenance-entering');reload_gateway(config,release,True);maintenance_check(config);phase('maintenance-enabled')
        elif a.command=='account':
            if not a.extra or a.extra[0] not in ['reset-password','create'] or not a.email:raise Failure('account create/reset-password --email EMAIL required.')
            arguments=['account',a.extra[0],'--email',a.email]
            if a.extra[0]=='create':
                if not a.name:raise Failure('account create requires --name NAME.')
                arguments+=['--name',a.name]
            compose('run','--rm','--no-deps','owner',*arguments,interactive=True)
        elif a.command=='build-source':build_source(a)

if __name__=='__main__':
    try:main()
    except (Failure,OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error,Failure) else 'Operation failed; inspect private installation state. Maintenance remains closed on incomplete operations.',file=sys.stderr);sys.exit(1)
