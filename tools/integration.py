#!/usr/bin/env python3
"""Real Docker acceptance using only a marked synthetic installation. No endpoint mocks."""
from __future__ import annotations
import argparse
import hashlib
import http.client
from http.cookies import SimpleCookie
import io
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid
import zipfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
EMAIL='docker-owner@example.test'
SECOND='docker-second@example.test'
PASSWORD='abc'  # Public synthetic fixture; never used for a real installation.
def uid():return str(uuid.uuid4())
def require(condition,message):
    if not condition:raise AssertionError(message)

class Client:
    def __init__(self,origin,email=EMAIL):
        parts=urlsplit(origin)
        require(parts.scheme=='http' and parts.hostname=='127.0.0.1','Synthetic HTTP tests require literal loopback origin.')
        self.origin=origin;self.host=parts.hostname;self.port=parts.port;self.email=email
        self.cookie=None;self.csrf=None;self.owner=None;self.contract=None
        self.http_contract=None
        if os.environ.get('TW_VALIDATE_HTTP_CONTRACT')=='1':
            from tools.http_contract import HTTPContractValidator
            self.http_contract=HTTPContractValidator()
    def request(self,method,path,value=None,raw=None,headers=None,expected=200,require_json=False):
        h={'Accept':'application/json'}
        if self.cookie:h['Cookie']=self.cookie
        if self.owner:h['X-TraceWeave-Account-ID']=self.owner
        if self.contract:h['X-TraceWeave-Client-Contract']=self.contract
        if method in ['POST','PUT','PATCH','DELETE']:
            h['Origin']=self.origin
            if self.csrf:h['X-CSRF-Token']=self.csrf
        if value is not None:raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode();h['Content-Type']='application/json'
        h.update(headers or {})
        conn=http.client.HTTPConnection(self.host,self.port,timeout=30)
        try:
            conn.request(method,path,body=raw,headers=h);reply=conn.getresponse();body=reply.read(16*1024*1024+1)
            require(len(body)<=16*1024*1024,'Test response bound exceeded.')
            response_headers=dict((k.lower(),v) for k,v in reply.getheaders())
            if self.http_contract is not None:
                self.http_contract.validate(method,path,reply.status,response_headers,body,require_json=require_json)
            if 'set-cookie' in response_headers:
                jar=SimpleCookie();jar.load(response_headers['set-cookie'])
                if 'rg_session' in jar:self.cookie='rg_session='+jar['rg_session'].value
            if reply.status!=expected:
                if self.http_contract is not None:
                    raise AssertionError('HTTP expected status mismatch; response values suppressed.')
                try:code=json.loads(body).get('error',{}).get('code','')
                except ValueError:code=''
                raise AssertionError('HTTP '+method+' '+path+' returned '+str(reply.status)+' '+str(code)+'; expected '+str(expected))
            return body,response_headers
        finally:conn.close()
    def json(self,method,path,value=None,**kw):return json.loads(self.request(method,path,value,require_json=True,**kw)[0])
    def login(self):
        self.owner=None
        self.contract=self.json('GET','/release.json')['contractHash']
        self.csrf=self.json('GET','/api/v1/session')['csrfToken']
        value=self.json('POST','/api/v1/session/login',{'email':self.email,'password':PASSWORD})
        self.csrf=value['csrfToken'];self.owner=value['user']['id'];return value
    def create(self,title):
        return self.json('POST','/api/v1/investigations',{'idempotencyKey':uid(),'title':title,'descriptionMarkdown':'Синтетическое Docker-исследование'},expected=201)['investigation']
    def commands(self,path,commands):
        revision=self.json('GET',path)['revision']
        batch={'operationId':uid(),'clientId':uid(),'baseRevision':revision,'commands':commands}
        result=self.json('POST',path+'/commands',batch)
        replay=self.json('POST',path+'/commands',batch)
        require(result['revision']==revision+1 and replay['replayed'] and replay['revision']==result['revision'],'Command idempotency/revision failed.')
        return batch

def cli(runtime,*args,password=None,expect_success=True):
    env=os.environ.copy();env['TW_RUNTIME_DIR']=str(runtime)
    log=runtime/('integration-'+uid()+'.log')
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    if password is None:
        with os.fdopen(fd,'w') as out:
            code=subprocess.run(['sh',str(ROOT/'traceweave.sh'),*args],env=env,stdout=out,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL).returncode
    else:
        master,slave=pty.openpty();process=subprocess.Popen(['sh',str(ROOT/'traceweave.sh'),*args],env=env,stdin=slave,stdout=slave,stderr=slave,start_new_session=True);os.close(slave)
        output=b'';sent=0;deadline=time.monotonic()+900;eof=False
        try:
            while time.monotonic()<deadline:
                if select.select([master],[],[],.2)[0]:
                    try:chunk=os.read(master,65536)
                    except OSError:eof=True;break
                    if not chunk:eof=True;break
                    os.write(fd,chunk);output=(output+chunk)[-8192:]
                    prompt=b'Password: ' if sent==0 else b'Confirm password: '
                    if sent<2 and prompt in output:
                        os.write(master,password.encode()+b'\n');sent+=1;output=b''
                if process.poll() is not None:break
            if process.poll() is None and eof:process.wait(timeout=10)
            if process.poll() is None:
                process.terminate();process.wait(timeout=10);raise AssertionError('Synthetic operator CLI timed out; inspect private log.')
            code=process.wait()
        finally:os.close(master);os.close(fd)
    require((code==0)==expect_success,'Operator CLI status unexpected for '+args[0]+'. Inspect private '+str(log))

def seed_second_account(runtime):
    # The local setup CLI intentionally creates only the first operator. This
    # explicit SQL fixture establishes a second verified synthetic owner; public
    # registration is tested separately with a real SMTP/TLS fixture.
    from tools import control
    control.RUNTIME=runtime
    script="""import importlib.util,json,uuid
from pathlib import Path
assert json.loads(Path('/state/synthetic-installation.json').read_text())=={'synthetic':True,'email':'docker-owner@example.test'}
s=importlib.util.spec_from_file_location('ops','/opt/traceweave/ops.py');ops=importlib.util.module_from_spec(s);s.loader.exec_module(ops)
c=ops.connect()
try:
 with c.cursor() as q:
  q.execute('SELECT id FROM owners WHERE email=%s',('docker-owner@example.test',));assert q.fetchone() is not None
  q.execute('INSERT INTO owners(id,display_name,email,email_verified_at,password_hash,created_at,updated_at) SELECT %s,%s,%s,now(),password_hash,now(),now() FROM owners WHERE email=%s ON CONFLICT(email) WHERE email IS NOT NULL DO NOTHING',(str(uuid.uuid4()),'Docker synthetic second','docker-second@example.test','docker-owner@example.test'))
finally:c.close()
print('Second verified synthetic account fixture ready.')
"""
    control.compose('run','--rm','-T','--no-deps','--entrypoint','python3','ops','-c',script,capture=True)

def smoke(runtime,origin):
    owner=Client(origin);session=owner.login();require(session['user']['email']==EMAIL,'Canonical email missing.')
    require(owner.json('GET','/api/v1/accounts/config')['registrationEnabled'] is False,'Local registration must be disabled.')
    inv=owner.create('Docker acceptance '+uid());path='/api/v1/investigations/'+inv['id']
    graph=owner.json('GET',path+'/graph');note=next(t['id'] for t in graph['nodeTypes'] if t['code']=='note');node=uid()
    batch=owner.commands(path,[{'kind':'node.create','node':{'id':node,'typeId':note,'title':'Docker document','bodyMarkdown':'Docker content survives restart'},'position':{'x':12,'y':34}}])
    require(owner.json('GET',path+'/nodes/'+node)['node']['title']=='Docker document','Document read failed.')
    fixtures=ROOT/'tests/fixtures/media';originals={};assets=[]
    for item in json.loads((fixtures/'manifest.json').read_text()):
        if not item['name'].startswith('synthetic.'):continue
        data=(fixtures/item['name']).read_bytes();require(hashlib.sha256(data).hexdigest()==item['sha256'],'Synthetic fixture checksum mismatch.')
        ticket=owner.json('POST',path+'/uploads',{'idempotencyKey':uid(),'originalName':item['name'],'expectedMimeType':item['mime'],'expectedByteSize':len(data)},expected=201)
        complete=owner.json('PUT',path+'/uploads/'+ticket['id']+'/content',raw=data,headers={'Content-Type':'application/octet-stream'})
        require(complete['sha256']==item['sha256'] and complete['mediaKind']==item['kind'],'Linux media probing/hash failed for '+item['name'])
        asset=uid();assets.append(asset);originals[asset]=data
        owner.commands(path,[{'kind':'asset.register','uploadId':ticket['id'],'assetId':asset,'metadata':{'title':item['name'],'sourceUrl':None,'sourceAuthor':None,'sourceCreatedAt':None,'noteMarkdown':''}}, {'kind':'attachment.attach','attachment':{'id':uid(),'nodeId':node,'assetId':asset,'role':'attachment','caption':None,'sortOrder':len(assets)}}])
        content=path+'/assets/'+asset+'/content'
        require(owner.request('GET',content)[0]==data,'Original bytes differ.')
        require(owner.request('HEAD',content)[1].get('content-length')==str(len(data)),'HEAD size differs.')
        if data:require(owner.request('GET',content,headers={'Range':'bytes=0-0'},expected=206)[0]==data[:1],'Range differs.')
    body={'kind':'obsidian_vault','sourceRevision':owner.json('GET',path)['revision'],'idempotencyKey':uid()}
    job=owner.json('POST',path+'/exports',body,expected=202);export=path+'/exports/'+job['id']
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        job=owner.json('GET',export)
        if job['state'] in ['succeeded','failed','cancelled']:break
        time.sleep(.1)
    require(job['state']=='succeeded','Real export did not succeed.')
    archive=owner.request('GET',export+'/download')[0];require(hashlib.sha256(archive).hexdigest()==job['sha256'],'ZIP checksum differs.')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        require(z.testzip() is None and 'metadata/snapshot.json' in z.namelist(),'Invalid real ZIP.')
        contents=[z.read(n) for n in z.namelist() if not n.endswith('/')]
        require(all(data in contents for data in originals.values()),'ZIP omitted originals.')
    second=Client(origin,SECOND);second.login()
    require(inv['id'] not in [i['id'] for i in second.json('GET','/api/v1/investigations')['items']],'Foreign investigation leaked in list.')
    for method,target in [('GET',path),('GET',path+'/graph'),('GET',path+'/nodes/'+node),('GET',export),('GET',export+'/download'),('HEAD',path+'/assets/'+assets[0]+'/content'),('GET',path+'/assets/'+assets[0]+'/content')]:
        second.request(method,target,expected=404)
    second.request('POST',path+'/commands',batch,expected=404)
    owner.request('GET',path,headers={'X-TraceWeave-Account-ID':second.owner},expected=409)
    owner.request('POST',path+'/commands',batch,headers={'X-TraceWeave-Client-Contract':'0'*64},expected=409)
    owner.request('POST',path+'/commands',batch,headers={'Origin':'https://untrusted.example.test'},expected=403)
    owner.request('POST',path+'/commands',batch,headers={'X-CSRF-Token':'invalid'},expected=403)
    owner.request('GET',path,headers={'Host':'untrusted.example.test'},expected=403)
    print('PASS real email/session, command replay, all synthetic media, HEAD/Range, ZIP and two-account access boundaries.',flush=True)
    return owner,path,node,originals

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--release',required=True);p.add_argument('--runtime',required=True);p.add_argument('--port',type=int,default=18080);p.add_argument('--existing',action='store_true');p.add_argument('--smoke-only',action='store_true');a=p.parse_args()
    runtime=Path(a.runtime).resolve();marker=runtime/'synthetic-installation.json';origin='http://127.0.0.1:'+str(a.port)
    if a.existing:
        require(marker.is_file() and json.loads(marker.read_text())=={'synthetic':True,'email':EMAIL},'Refusing an unmarked existing installation.')
    else:
        require(not runtime.exists(),'A new test requires a fresh runtime path; nothing is deleted.')
        runtime.mkdir(parents=True,mode=0o700);marker.write_text(json.dumps({'synthetic':True,'email':EMAIL}));os.chmod(marker,0o600)
        cli(runtime,'bootstrap','--release',str(Path(a.release).resolve()),'--origin',origin,'--email',EMAIL,'--name','Docker synthetic owner',password=PASSWORD)
        seed_second_account(runtime)
    owner,path,node,originals=smoke(runtime,origin)
    if a.smoke_only:return
    cli(runtime,'bootstrap','--release',str(Path(a.release).resolve()),'--origin',origin)
    cli(runtime,'restart')
    require(owner.json('GET',path+'/nodes/'+node)['node']['bodyMarkdown']=='Docker content survives restart','Restart lost document.')
    for asset,data in originals.items():require(owner.request('GET',path+'/assets/'+asset+'/content')[0]==data,'Restart lost original.')
    cli(runtime,'maintenance','on')
    for target in ['/','/api/v1/session']:
        body,headers=owner.request('GET',target,expected=503)
        require(headers.get('cache-control')=='no-store' and headers.get('retry-after')=='15','Maintenance caching/retry headers invalid.')
        if target.startswith('/api'):require(json.loads(body)['error']['code']=='service_maintenance','Maintenance JSON invalid.')
    owner.request('GET','/release.json');cli(runtime,'resume','--yes')
    cli(runtime,'backup')
    state=json.loads((runtime/'operation.json').read_text());backup=state['backup'];saved=json.loads((runtime/'backups'/backup/'manifest.json').read_text())
    require(saved['databaseOriginals'] and saved['migrations'],'Backup has no database/original evidence.')
    added=owner.create('Created after backup '+uid())
    old=json.loads((runtime/'installation.json').read_text())['volumes']
    cli(runtime,'restore','--backup',backup,'--yes')
    require(owner.json('GET','/api/v1/session')['authenticated'] is False,'Restore did not revoke old session.')
    owner.login();require(owner.json('GET',path+'/nodes/'+node)['node']['bodyMarkdown']=='Docker content survives restart','Restore lost document.')
    owner.request('GET','/api/v1/investigations/'+added['id'],expected=404)
    for asset,data in originals.items():require(owner.request('GET',path+'/assets/'+asset+'/content')[0]==data,'Restore lost original.')
    new=json.loads((runtime/'installation.json').read_text())['volumes'];require(new['database']!=old['database'] and new['files']!=old['files'],'Restore overwrote original volumes.')
    print('PASS repeat bootstrap, persistent restart, real maintenance/release, backup hashes, restore into new volumes and session revocation.',flush=True)
    cli(runtime,'stop')
    print('Synthetic stack stopped; private runtime, safety backup and all volumes preserved: '+str(runtime),flush=True)

if __name__=='__main__':main()
