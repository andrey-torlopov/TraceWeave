#!/usr/bin/env python3
"""Real Docker acceptance using only a marked synthetic installation. No endpoint mocks."""
from __future__ import annotations
import argparse
from collections import Counter
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
from urllib.parse import quote, urlsplit
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
    def request(self,method,path,value=None,raw=None,headers=None,expected=200,require_json=False,native=False):
        if native:
            require(method in ['GET','HEAD'] and value is None and raw is None,'Native downloads must be bodyless GET/HEAD requests.')
            require(not any(name.lower() in ['x-traceweave-account-id','x-traceweave-client-contract'] for name in (headers or {})),
                'Native download checks must not send custom account/contract headers.')
        h={'Accept':'*/*' if native else 'application/json'}
        if self.cookie:h['Cookie']=self.cookie
        if self.owner and not native:h['X-TraceWeave-Account-ID']=self.owner
        if self.contract and not native:h['X-TraceWeave-Client-Contract']=self.contract
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

def node_deletion_smoke(owner):
    # Keep this graph separate from the media/export/restart fixture used by smoke().
    inv=owner.create('Node deletion acceptance '+uid());path='/api/v1/investigations/'+inv['id']
    graph=owner.json('GET',path+'/graph');note=next(t['id'] for t in graph['nodeTypes'] if t['code']=='note')
    relation_codes=sorted(t['code'] for t in graph['relationTypes'] if not t['isHidden'])
    require(len(relation_codes)>=2,'Node deletion fixture requires two active relation types.')
    a,b,c=uid(),uid(),uid();incident=[uid() for _ in range(4)];unrelated=uid()
    commands=[]
    for index,node in enumerate([a,b,c]):
        commands.append({'kind':'node.create','node':{'id':node,'typeId':note,'title':'Deletion fixture '+str(index),
            'bodyMarkdown':'Preserved document '+str(index),'tags':['deletion-fixture']},'position':{'x':index*120,'y':index*40}})
    for relation,source,target,code,directed in [
        (incident[0],a,b,relation_codes[0],True),
        (incident[1],b,c,relation_codes[0],True),
        (incident[2],a,b,relation_codes[1],True),
        (incident[3],c,b,relation_codes[0],False),
        (unrelated,a,c,relation_codes[0],True),
    ]:
        commands.append({'kind':'relation.create','relation':{'id':relation,'sourceNodeId':source,'targetNodeId':target,
            'relationType':code,'directed':directed,'label':'Preserved relation','noteMarkdown':'Synthetic relation metadata',
            'assessment':'hypothesis','confidence':'medium'}})
    owner.commands(path,commands)
    fixtures=ROOT/'tests/fixtures/media';item=next(i for i in json.loads((fixtures/'manifest.json').read_text()) if i['name']=='synthetic.txt')
    data=(fixtures/item['name']).read_bytes();require(hashlib.sha256(data).hexdigest()==item['sha256'],'Deletion fixture checksum mismatch.')
    ticket=owner.json('POST',path+'/uploads',{'idempotencyKey':uid(),'originalName':item['name'],
        'expectedMimeType':item['mime'],'expectedByteSize':len(data)},expected=201)
    complete=owner.json('PUT',path+'/uploads/'+ticket['id']+'/content',raw=data,headers={'Content-Type':'application/octet-stream'})
    require(complete['sha256']==item['sha256'],'Deletion fixture upload hash differs.')
    asset,attachment_a,attachment_b=uid(),uid(),uid()
    owner.commands(path,[{'kind':'asset.register','uploadId':ticket['id'],'assetId':asset,
        'metadata':{'title':'Deletion original','sourceUrl':None,'sourceAuthor':None,'sourceCreatedAt':None,'noteMarkdown':'Retain immutable original'}},
        {'kind':'attachment.attach','attachment':{'id':attachment_a,'nodeId':a,'assetId':asset,'role':'attachment','caption':'Surviving usage','sortOrder':0}},
        {'kind':'attachment.attach','attachment':{'id':attachment_b,'nodeId':b,'assetId':asset,'role':'primary','caption':'Retained trash attachment','sortOrder':0}}])

    def state():
        return {'investigation':owner.json('GET',path),'graph':owner.json('GET',path+'/graph'),
            'documents':{node:owner.json('GET',path+'/nodes/'+node) for node in [a,b,c]},
            'relations':{relation:owner.json('GET',path+'/relations/'+relation) for relation in [*incident,unrelated]},
            'asset':owner.json('GET',path+'/assets/'+asset)}
    before=state();revision=before['investigation']['revision']
    require({x['nodeId'] for x in before['asset']['attachments']}=={a,b},'Deletion fixture must expose both active asset usages.')
    trash={'kind':'elements.trash','nodeIds':[b],'relationIds':[],'groupMode':'group_only'}
    for commands,base,status,code in [
        ([trash],revision-1,409,'revision_conflict'),
        ([dict(trash,nodeIds=[b,uid()])],revision,404,'not_found'),
        ([dict(trash,relationIds=[uid()])],revision,404,'not_found'),
        ([{'kind':'node.update','nodeId':a,'changes':{'bodyMarkdown':'Must roll back'}},trash,
          {'kind':'node.update','nodeId':uid(),'changes':{'title':'Missing node'}}],revision,404,'not_found'),
    ]:
        rejected={'operationId':uid(),'clientId':uid(),'baseRevision':base,'commands':commands}
        failure=owner.json('POST',path+'/commands',rejected,expected=status)
        require(failure['error']['code']==code,'Node deletion negative case returned the wrong error.')
        require(state()==before,'Rejected node deletion left partial data, metadata, usage or revision changes.')
        require(owner.request('GET',path+'/assets/'+asset+'/content')[0]==data,'Rejected node deletion changed the original.')

    batch={'operationId':uid(),'clientId':uid(),'baseRevision':revision,'commands':[trash]}
    result=owner.json('POST',path+'/commands',batch)
    require(result['revision']==revision+1 and not result['replayed'],'Node deletion must commit one revision.')
    require(set(result['changedNodeIds'])=={b} and set(result['changedRelationIds'])==set(incident),
        'Node deletion response must identify the node and every server-discovered incident relation.')
    require(set(result['deletedIds'])=={b,*incident} and not result['changedAssetIds'],'Node deletion must retain the asset.')
    replay=owner.json('POST',path+'/commands',batch)
    require(replay==dict(result,replayed=True),'Exact node deletion replay changed the original command result.')
    require(owner.json('GET',path)['revision']==revision+1,'Node deletion replay advanced the revision.')
    owner.request('GET',path+'/nodes/'+b,expected=404)
    deleted=owner.json('GET',path+'/nodes/'+b+'?includeDeleted=true')
    batch_id=deleted['node']['deletionBatchId'];deleted_at=deleted['node']['deletedAt']
    require(batch_id is not None and deleted_at is not None,'Trash node lacks deletion batch/time.')
    require(deleted['revision']==revision+1,'Trash document revision differs from committed deletion.')
    for field in ['id','typeId','title','bodyMarkdown','assessment','confidence','tags','extensions','createdAt','origin']:
        require(deleted['node'][field]==before['documents'][b]['node'][field],'Trash lost document field '+field+'.')
    for field in ['layout','attributes','attachments','assets','evidence']:
        require(deleted[field]==before['documents'][b][field],'Trash lost document '+field+'.')
    for relation in incident:
        owner.request('GET',path+'/relations/'+relation,expected=404)
        trashed=owner.json('GET',path+'/relations/'+relation+'?includeDeleted=true')['relation']
        require(trashed['deletionBatchId']==batch_id and trashed['deletedAt']==deleted_at,'Incident relations were not deleted in the same batch.')
        for field,value in before['relations'][relation]['relation'].items():
            if field not in ['updatedAt','deletedAt','deletionBatchId']:
                require(trashed[field]==value,'Trash changed relation metadata '+field+'.')
    after=owner.json('GET',path+'/graph')
    require(after['revision']==revision+1 and {n['id'] for n in after['nodes']}=={a,c},'Active graph retained the trashed node or lost a survivor.')
    require(after['nodes']==[n for n in before['graph']['nodes'] if n['id']!=b],'Deletion changed surviving node summaries.')
    require(after['layouts']==[x for x in before['graph']['layouts'] if x['nodeId']!=b],'Deletion changed surviving layouts or retained the deleted layout.')
    require(after['relations']==[r for r in before['graph']['relations'] if r['id']==unrelated],'Deletion retained incident relations or changed an unrelated relation.')
    for node in [a,c]:
        require(owner.json('GET',path+'/nodes/'+node)==dict(before['documents'][node],revision=revision+1),'Deletion changed a surviving document.')
    require(owner.json('GET',path+'/relations/'+unrelated)==dict(before['relations'][unrelated],revision=revision+1),'Deletion changed unrelated relation metadata.')
    current_asset=owner.json('GET',path+'/assets/'+asset)
    require(current_asset==dict(before['asset'],revision=revision+1,
        attachments=[x for x in before['asset']['attachments'] if x['nodeId']==a]),'Deleted node appears as active usage or asset metadata changed.')
    require(owner.request('GET',path+'/assets/'+asset+'/content?download=true')[0]==data,'Node deletion removed or changed downloadable original bytes.')
    mismatch=dict(batch,commands=[dict(trash,nodeIds=[a])])
    failure=owner.json('POST',path+'/commands',mismatch,expected=409)
    require(failure['error']['code']=='idempotency_mismatch' and owner.json('GET',path+'/graph')==after,
        'Changed deletion replay was accepted or changed the graph/revision.')
    print('PASS real node deletion: incoming/outgoing/parallel/undirected cascade, atomic rejection/rollback, exact replay, retained metadata/original and active asset usage.',flush=True)

def verify_file_report_archive(archive,kind,fixture):
    """Check original multiplicity, links and reading/raw content without extracting ZIPs."""
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        names=[entry.filename for entry in zipped.infolist() if not entry.is_dir()]
        require(len(names)==len(set(names)) and zipped.testzip() is None,'Export contains duplicate paths or corrupt ZIP entries.')
        if kind=='readable_report':
            require('report.md' in names and all(name=='report.md' or name.startswith('Attachments/') and len(name.split('/'))==2 for name in names),
                'Readable export must contain one report and its originals only.')
            attachments=[name for name in names if name.startswith('Attachments/')]
            # Counting values matters: uploading identical bytes twice must export two copies.
            require(Counter(zipped.read(name) for name in attachments)==Counter(fixture['originals'].values()),
                'Readable export changed, omitted or deduplicated an original.')
            report=zipped.read('report.md').decode('utf-8')
            require(fixture['title'] in report and fixture['body'] in report,'Readable export lost the document content.')
            require(all(quote(name,safe='/') in report for name in attachments),'Readable export has an unlinked original.')
            identifiers=[fixture['path'].rsplit('/',1)[-1],fixture['node'],*fixture['originals']]
            require(not any(identifier in report or any(identifier in name for name in names) for identifier in identifiers),
                'Readable export exposed internal identifiers.')
        else:
            require(kind=='obsidian_vault','Unknown file/report acceptance export kind.')
            require('metadata/snapshot.json' in names and 'metadata/files.json' in names,'Raw export lost its metadata.')
            files=json.loads(zipped.read('metadata/files.json'))['assets']
            require(set(files)==set(fixture['originals']) and len(set(files.values()))==len(files),
                'Raw export changed or deduplicated asset identities.')
            for asset,data in fixture['originals'].items():
                require(files[asset].startswith('Attachments/Files/') and zipped.read(files[asset])==data,'Raw export changed an original.')
            snapshot=json.loads(zipped.read('metadata/snapshot.json'))
            nodes=[node for node in snapshot['nodes'] if node['id']==fixture['node']]
            require(len(nodes)==1 and nodes[0]['title']==fixture['title'] and nodes[0]['bodyMarkdown']==fixture['body'],
                'Raw export lost the document content.')
            require({asset['id'] for asset in snapshot['assets']}==set(fixture['originals']),'Raw snapshot lost asset identities.')

def create_file_report_exports(owner,fixture):
    captures={};path=fixture['path'];revision=owner.json('GET',path)['revision']
    for kind in ['obsidian_vault','readable_report']:
        body={'kind':kind,'sourceRevision':revision,'idempotencyKey':uid()}
        job=owner.json('POST',path+'/exports',body,expected=202)
        replay=owner.json('POST',path+'/exports',body,expected=202)
        require(replay['id']==job['id'],'File/report export retry created a second job.')
        export=path+'/exports/'+job['id'];deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            job=owner.json('GET',export)
            if job['state'] in ['succeeded','failed','cancelled']:break
            time.sleep(.1)
        require(job['state']=='succeeded' and job['kind']==kind and job['sourceRevision']==revision,'File/report export did not finish its captured revision.')
        archive,headers=owner.request('GET',export+'/download',native=True)
        require(hashlib.sha256(archive).hexdigest()==job['sha256'] and len(archive)==job['byteSize'],'File/report ZIP checksum or length differs.')
        require(headers.get('content-type')=='application/zip' and headers.get('content-disposition','').startswith('attachment;'),'Export download headers are unsafe.')
        verify_file_report_archive(archive,kind,fixture)
        captures[kind]={'path':export,'bytes':archive}
    return captures

def verify_file_report_smoke(owner,fixture,*,restored=False):
    """Verify retained originals; after restore recreate deliberately transient ZIPs."""
    path=fixture['path'];document=owner.json('GET',path+'/nodes/'+fixture['node'])
    require(document['node']['title']==fixture['title'] and document['node']['bodyMarkdown']==fixture['body'],'File/report fixture document changed.')
    attachments={item['id']:item['assetId'] for item in document['attachments']}
    require(all(attachments.get(key)==asset for key,asset in fixture['attachments'].items()),'File attachment identities were lost or deduplicated.')
    for asset,data in fixture['originals'].items():
        metadata=owner.json('GET',path+'/assets/'+asset)['asset']
        require(metadata==fixture['assets'][asset],'Registered file metadata changed.')
        content=path+'/assets/'+asset+'/content'
        for method in ['GET','HEAD']:
            received,headers=owner.request(method,content,native=True)
            require(received==(data if method=='GET' else b''),'Native file download changed the original bytes.')
            require(headers.get('content-length')==str(len(data)) and headers.get('content-type')==metadata['mimeType'],'Native file download MIME/length differs.')
            require(headers.get('x-content-type-options')=='nosniff' and headers.get('content-disposition','').startswith('attachment;'),
                'Native generic/PDF download must remain a nosniff attachment.')
            require("filename*=UTF-8''"+quote(metadata['originalName'],safe='') in headers['content-disposition'],'Native download lost its original filename.')
            require(headers.get('etag')=='"'+hashlib.sha256(data).hexdigest()+'"','Native file download checksum differs.')
        if data:require(owner.request('GET',content,native=True,headers={'Range':'bytes=0-0'},expected=206)[0]==data[:1],'Native file Range differs.')
    for kind,capture in fixture['exports'].items():
        job=owner.json('GET',capture['path'])
        if restored:
            require(job['state']=='failed' and job['error']['code']=='export_interrupted' and not job['downloadAvailable'],
                'Restore must invalidate transient exports explicitly.')
        else:
            require(job['state']=='succeeded','Persisted export is no longer available.')
            archive,headers=owner.request('GET',capture['path']+'/download',native=True)
            require(archive==capture['bytes'],'A completed export changed after capture.')
            require(owner.request('HEAD',capture['path']+'/download',native=True)[1].get('content-length')==str(len(archive)),
                'Native export HEAD length differs.')
            verify_file_report_archive(archive,kind,fixture)
    if restored:
        captures=create_file_report_exports(owner,fixture)
        with zipfile.ZipFile(io.BytesIO(captures['readable_report']['bytes'])) as fresh, zipfile.ZipFile(io.BytesIO(fixture['exports']['readable_report']['bytes'])) as prior:
            require(fresh.read('report.md')==prior.read('report.md'),'Restored reading report content changed.')
        return captures
    return fixture['exports']

def file_report_smoke(owner,*,path=None,node=None):
    """Reusable real HTTP fixture for initial Docker acceptance and post-upgrade checks.

    Returns path/node, originals {assetId: bytes}, assets {assetId: metadata},
    attachments {attachmentId: assetId}, and exports {kind: {path, bytes}}.
    Retain the fixture in memory for restart or backup restore verification.
    """
    require((path is None)==(node is None),'Supply both existing investigation and node, or neither.')
    if path is None:
        investigation=owner.create('File report acceptance '+uid());path='/api/v1/investigations/'+investigation['id']
        graph=owner.json('GET',path+'/graph');note=next(item['id'] for item in graph['nodeTypes'] if item['code']=='note');node=uid()
        owner.commands(path,[{'kind':'node.create','node':{'id':node,'typeId':note,'title':'File report document',
            'bodyMarkdown':'Immutable file report content survives backup'},'position':{'x':12,'y':34}}])
    document=owner.json('GET',path+'/nodes/'+node)['node']
    fixture={'path':path,'node':node,'title':document['title'],'body':document['bodyMarkdown'],'originals':{},'assets':{},'attachments':{},'exports':{}}
    generic=b'\x00\x01\xffSynthetic binary\x00\r\n'
    pdf=b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'
    originals=[('данные.bin','application/octet-stream',generic),('документ.pdf','application/pdf',pdf),
        ('пустой.txt','application/octet-stream',b''),('данные.bin','application/octet-stream',generic)]
    uploads=[]
    for index,(name,mime,data) in enumerate(originals):
        digest=hashlib.sha256(data).hexdigest()
        ticket=owner.json('POST',path+'/uploads',{'idempotencyKey':uid(),'originalName':name,'expectedMimeType':mime,'expectedByteSize':len(data)},expected=201)
        uploads.append(ticket['id'])
        complete=owner.json('PUT',path+'/uploads/'+ticket['id']+'/content',raw=data,headers={'Content-Type':'application/octet-stream'})
        require(complete['state']=='completed' and complete['sha256']==digest and complete['receivedBytes']==len(data)
            and complete['mediaKind']=='file' and complete['verifiedMimeType']==mime,
            'Generic/PDF/empty upload classification or checksum differs.')
        asset=uid();attachment=uid()
        owner.commands(path,[{'kind':'asset.register','uploadId':ticket['id'],'assetId':asset,'metadata':{'title':'File material '+str(index+1),
            'sourceUrl':None,'sourceAuthor':None,'sourceCreatedAt':None,'noteMarkdown':''}},
            {'kind':'attachment.attach','attachment':{'id':attachment,'nodeId':node,'assetId':asset,'role':'attachment','caption':None,'sortOrder':index}}])
        metadata=owner.json('GET',path+'/assets/'+asset)['asset']
        require(metadata['id']==asset and metadata['originalName']==name and metadata['mediaKind']=='file' and metadata['mimeType']==mime
            and metadata['sha256']==digest and metadata['byteSize']==len(data),'Registered generic/PDF/empty asset differs from its upload.')
        fixture['originals'][asset]=data;fixture['assets'][asset]=metadata;fixture['attachments'][attachment]=asset
    require(len(set(uploads))==len(originals) and len(fixture['originals'])==len(originals) and len(fixture['attachments'])==len(originals),
        'Repeated file upload must create independent upload, asset and attachment identities.')
    fixture['exports']=create_file_report_exports(owner,fixture)
    verify_file_report_smoke(owner,fixture)
    print('PASS generic/PDF/empty files, independent repeated upload, native cookie-only GET/HEAD/Range and byte-exact raw/readable exports.',flush=True)
    return fixture


def evidence_type_smoke(owner, *, path=None):
    fresh = path is None
    if fresh:
        path = '/api/v1/investigations/' + owner.create('Evidence acceptance ' + uid())['id']
    graph = owner.json('GET', path + '/graph')
    types = [item for item in graph['nodeTypes'] if item['code'] == 'evidence']
    require(len(types) == 1, 'Expected one evidence type in the investigation catalog.')
    kind = types[0]
    require(kind['name'] == 'Улика' and kind['iconKey'] == 'search' and not kind['isSystem']
            and not kind['isHidden'] and kind['attributeTemplates'] == [], 'Evidence type metadata differs.')
    node = uid(); title = 'Synthetic evidence'; body = 'Evidence survives persistence and export'
    owner.commands(path, [{'kind': 'node.create', 'node': {'id': node, 'typeId': kind['id'], 'title': title,
                    'bodyMarkdown': body}, 'position': {'x': 600, 'y': 300}}])
    document = owner.json('GET', path + '/nodes/' + node)['node']
    require(document['typeId'] == kind['id'] and document['bodyMarkdown'] == body, 'Evidence document did not persist.')
    reloaded = owner.json('GET', path + '/graph')
    require([item for item in reloaded['nodeTypes'] if item['code'] == 'evidence'] == types,
            'Reload duplicated or changed the evidence type.')
    if fresh:
        fixture = dict(path=path, node=node, title=title, body=body, originals={})
        captures = create_file_report_exports(owner, fixture)
        for format, capture in captures.items():
            with zipfile.ZipFile(io.BytesIO(capture['bytes'])) as zipped:
                if format == 'readable_report':
                    require('- Тип: Улика' in zipped.read('report.md').decode('utf-8'), 'Readable report lost the evidence type.')
                else:
                    snapshot = json.loads(zipped.read('metadata/snapshot.json'))
                    require(any(item['id'] == kind['id'] and item['code'] == 'evidence' and item['iconKey'] == 'search'
                                for item in snapshot['nodeTypes']), 'Raw export lost the evidence type/icon.')
    print('PASS evidence catalog, ordinary document persistence and reload' + ('; both exports.' if fresh else ' after upgrade.'), flush=True)


def smoke(runtime,origin):
    owner=Client(origin);session=owner.login();require(session['user']['email']==EMAIL,'Canonical email missing.')
    require(owner.json('GET','/api/v1/accounts/config')['registrationEnabled'] is False,'Local registration must be disabled.')
    inv=owner.create('Docker acceptance '+uid());path='/api/v1/investigations/'+inv['id']
    graph=owner.json('GET',path+'/graph');note=next(t['id'] for t in graph['nodeTypes'] if t['code']=='note');node=uid()
    batch=owner.commands(path,[{'kind':'node.create','node':{'id':node,'typeId':note,'title':'Docker document','bodyMarkdown':'Docker content survives restart'},'position':{'x':12,'y':34}}])
    require(owner.json('GET',path+'/nodes/'+node)['node']['title']=='Docker document','Document read failed.')
    files=file_report_smoke(owner,path=path,node=node)
    fixtures=ROOT/'tests/fixtures/media';originals=dict(files['originals']);assets=list(originals)
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
    for asset in files['originals']:
        for method in ['GET','HEAD']:second.request(method,path+'/assets/'+asset+'/content',native=True,expected=404)
    for capture in files['exports'].values():
        second.request('GET',capture['path'],expected=404)
        for method in ['GET','HEAD']:second.request(method,capture['path']+'/download',native=True,expected=404)
    verify_file_report_smoke(owner,files)
    second.request('POST',path+'/commands',batch,expected=404)
    owner.request('GET',path,headers={'X-TraceWeave-Account-ID':second.owner},expected=409)
    owner.request('POST',path+'/commands',batch,headers={'X-TraceWeave-Client-Contract':'0'*64},expected=409)
    owner.request('POST',path+'/commands',batch,headers={'Origin':'https://untrusted.example.test'},expected=403)
    owner.request('POST',path+'/commands',batch,headers={'X-CSRF-Token':'invalid'},expected=403)
    owner.request('GET',path,headers={'Host':'untrusted.example.test'},expected=403)
    node_deletion_smoke(owner)
    evidence_type_smoke(owner)
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
    for asset,data in originals.items():require(owner.request('GET',path+'/assets/'+asset+'/content',native=True)[0]==data,'Restart lost original.')
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
    for asset,data in originals.items():require(owner.request('GET',path+'/assets/'+asset+'/content',native=True)[0]==data,'Restore lost original.')
    new=json.loads((runtime/'installation.json').read_text())['volumes'];require(new['database']!=old['database'] and new['files']!=old['files'],'Restore overwrote original volumes.')
    print('PASS repeat bootstrap, persistent restart, real maintenance/release, backup hashes, restore into new volumes and session revocation.',flush=True)
    cli(runtime,'stop')
    print('Synthetic stack stopped; private runtime, safety backup and all volumes preserved: '+str(runtime),flush=True)

if __name__=='__main__':main()
