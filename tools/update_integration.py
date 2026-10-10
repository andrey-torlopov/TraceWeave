#!/usr/bin/env python3
"""Exercise real component updates only on a marked synthetic installation."""
from __future__ import annotations
import argparse
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from integration import EMAIL, Client, cli, require, uid
from tools import control

@dataclass(frozen=True)
class PreparedBatch:
    raw: bytes
    headers: tuple[tuple[str,str], ...]
    operation_id: str
    base_revision: int
    node_id: str
    title: str

def prepare_batch(client,path,component):
    require(all([client.owner,client.contract,client.cookie,client.csrf]),'An authenticated pending-command fixture is required.')
    revision=client.json('GET',path)['revision']
    graph=client.json('GET',path+'/graph');note=next(value['id'] for value in graph['nodeTypes'] if value['code']=='note')
    node=uid();operation=uid();title='Pending before '+component+' update '+uid()
    value={'operationId':operation,'clientId':uid(),'baseRevision':revision,'commands':[
        {'kind':'node.create','node':{'id':node,'typeId':note,'title':title,'bodyMarkdown':'Exact prepared bytes survive component deployment.'},'position':{'x':12,'y':34}}]}
    headers=tuple({'Content-Type':'application/json','X-TraceWeave-Account-ID':client.owner,
                   'X-TraceWeave-Client-Contract':client.contract,'Origin':client.origin,
                   'Cookie':client.cookie,'X-CSRF-Token':client.csrf}.items())
    return PreparedBatch(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),headers,operation,revision,node,title)

def apply_prepared_and_edit(client,path,prepared):
    result=client.json('POST',path+'/commands',raw=prepared.raw,headers=dict(prepared.headers))
    replay=client.json('POST',path+'/commands',raw=prepared.raw,headers=dict(prepared.headers))
    require(result['operationId']==replay['operationId']==prepared.operation_id and
            result['revision']==replay['revision']==prepared.base_revision+1 and
            result['replayed'] is False and replay['replayed'] is True,'Exact prepared command/idempotent replay failed after update.')
    require(client.json('GET',path+'/nodes/'+prepared.node_id)['node']['title']==prepared.title,'Prepared command did not persist the expected node.')
    newer='Edited after update '+uid()
    client.commands(path,[{'kind':'node.update','nodeId':prepared.node_id,'changes':{'title':newer}}])
    require(client.json('GET',path+'/nodes/'+prepared.node_id)['node']['title']==newer,'A newer node title could not be saved after pending replay.')
    return newer

def running(config,release):
    result={}
    for service in ['backend','frontend','db']:
        cid=control.container(service,config,release)
        state=json.loads(control.execute(['docker','inspect','--format','{{json .State}}',cid],capture=True))
        result[service]=(cid,state['StartedAt'])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',required=True);p.add_argument('--frontend-release')
    p.add_argument('--backend-release');a=p.parse_args()
    if not a.frontend_release and not a.backend_release:p.error('A component release is required.')
    runtime=Path(a.runtime).resolve()
    require(json.loads((runtime/'synthetic-installation.json').read_text())=={'synthetic':True,'email':EMAIL},'Unmarked installation refused.')
    control.RUNTIME=runtime;old=control.current();config=control.load_config();client=Client(config['origin']);client.login()
    require(json.loads((runtime/'operation.json').read_text())['phase']=='ready','Synthetic stack must be ready.')
    document=client.create('Component update persistence');path='/api/v1/investigations/'+document['id']
    selected=old
    if a.frontend_release:
        html=client.request('GET','/')[0].decode();asset=re.search(r'src="(/assets/[^" ]+\.js)"',html)
        require(asset is not None,'Vite entry asset missing.');old_bytes=client.request('GET',asset.group(1))[0]
        prepared=prepare_batch(client,path,'frontend')
        before=running(config,old);backups=set((runtime/'backups').iterdir()) if (runtime/'backups').exists() else set()
        cli(runtime,'update','--release',str(Path(a.frontend_release).resolve()),'--yes')
        selected=control.current();after=running(config,selected)
        require(before['backend']==after['backend'] and before['db']==after['db'],'Frontend update restarted backend or database.')
        require(before['frontend'][0]!=after['frontend'][0],'Frontend container was not replaced.')
        now=set((runtime/'backups').iterdir()) if (runtime/'backups').exists() else set()
        require(now==backups,'Frontend update unexpectedly made a backup.')
        require(client.request('GET',asset.group(1))[0]==old_bytes,'Previous entry asset unavailable.')
        require(client.json('GET',path)['id']==document['id'],'Component update lost data/session.')
        require(client.json('GET','/release.json')['releaseId']==selected['releaseId'],'Gateway release metadata not updated.')
        newer_title=apply_prepared_and_edit(client,path,prepared)
        print('PASS frontend-only update preserves backend/database identity, sessions, data and previous hashed assets; exact pending command/replay and newer edit persist.',flush=True)

        # Select an existing image with false baked metadata. Readiness must fail,
        # keep maintenance, and retain the accepted release until explicit rollback.
        bad=copy.deepcopy(selected);bad.update(releaseId='synthetic-rejected-release',frontendVersion='synthetic-wrong-version')
        bad['images']['frontend']=old['images']['frontend'];bad['frontendReleaseId']=old['frontendReleaseId']
        bad_path=runtime/'rejected-release.json';control.write_json(bad_path,bad)
        cli(runtime,'update','--release',str(bad_path),'--yes',expect_success=False)
        require(control.current()==selected,'Failed update changed accepted manifest.')
        require(client.json('GET','/api/v1/session',expected=503)['error']['code']=='service_maintenance','Failed update opened access.')
        cli(runtime,'start',expect_success=False)
        cli(runtime,'rollback','--yes')
        require(control.current()==selected,'Rollback chose incorrect pair.')
        require(client.json('GET',path)['id']==document['id'],'Rollback lost newer data.')
        require(client.json('GET',path+'/nodes/'+prepared.node_id)['node']['title']==newer_title,'Image rollback lost the edit made after pending replay.')
        print('PASS false image metadata fails closed; start refuses interrupted update; explicit rollback preserves newer data.',flush=True)
    if a.backend_release:
        prepared=prepare_batch(client,path,'backend')
        before=running(config,selected);backups=set((runtime/'backups').iterdir()) if (runtime/'backups').exists() else set()
        cli(runtime,'update','--release',str(Path(a.backend_release).resolve()),'--yes')
        final=control.current();after=running(config,final)
        require(before['frontend']==after['frontend'] and before['db']==after['db'],'Backend update restarted frontend or database.')
        require(before['backend'][0]!=after['backend'][0],'Backend container was not replaced.')
        require(set((runtime/'backups').iterdir())>backups,'Backend update did not preserve an offline backup.')
        require(client.json('GET',path)['id']==document['id'],'Backend update lost data/session.')
        apply_prepared_and_edit(client,path,prepared)
        print('PASS backend-only update makes verified offline backup and preserves frontend/database identity, data and sessions; exact pending command/replay and newer edit persist.',flush=True)

if __name__=='__main__':main()
