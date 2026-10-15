"""Positive examples and independent negative P0 contract cases."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SPECIFICATION=Path(os.environ.get('TW_SPECIFICATION_PATH', str(ROOT.parent/'TraceWeaveBackend/docs/project/TECHNICAL_SPECIFICATION.md')))
sys.path.insert(0,str(ROOT/'tools'))
from validate_contracts import (load_contracts, schema_validator, archive_validator, strict_json,
                               validate_project, validate_archive_directory, validate_contracts)
from jsonschema import ValidationError

API, ARCHIVE=load_contracts()
DOCUMENT_MARKDOWN_BYTES = 5 * 1024 * 1024
COMMAND_JSON_BYTES = 32 * 1024 * 1024

def uid(i): return f'30000000-0000-4000-8000-{i:012d}'
def example(name): return copy.deepcopy(API['components']['schemas'][name]['examples'][0])

def project_fixture():
    p={'format':'research-graph.project','formatVersion':'1.0','investigation':example('Investigation')}
    p['investigation'].pop('ownerId'); p['investigation']['id']=uid(1)
    p['investigation']['status']='active';p['investigation']['archivedAt']=None
    for key in ('nodeTypes','relationTypes','nodes','attributes','layouts','memberships','relations','assets','attachments','evidence','reports','snapshots','snapshotAssets','deletionBatches','blobs'):p[key]=[]
    for index,code in ((2,'note'),(3,'group')):
        row=example('NodeType');row.update(id=uid(index),investigationId=uid(1),code=code,isSystem=True);p['nodeTypes'].append(row)
    rt=example('RelationType');rt.update(id=uid(4),investigationId=uid(1),code='related_to');p['relationTypes'].append(rt)
    for index,typ in ((10,2),(11,2),(12,3)):
        row=example('Node');row.pop('iconEmoji',None);row.update(id=uid(index),investigationId=uid(1),typeId=uid(typ));p['nodes'].append(row)
        p['layouts'].append({'nodeId':uid(index),'investigationId':uid(1),'x':index*10,'y':0,'zIndex':0})
    rel=example('Relation');rel.update(id=uid(20),investigationId=uid(1),sourceNodeId=uid(10),targetNodeId=uid(11),relationType='related_to',directed=False);p['relations'].append(rel)
    p['memberships'].append({'investigationId':uid(1),'groupNodeId':uid(12),'memberNodeId':uid(10),'sortOrder':0})
    return p

class ContractTests(unittest.TestCase):
    def reject(self,name,value):
        with self.assertRaises((ValidationError,ValueError)):schema_validator(name,API).validate(value)
    def test_all_schemas_openapi_and_examples(self):
        result=validate_contracts();self.assertEqual(result['commandKinds'],35);self.assertEqual(result['operations'],47)
    def test_command_catalog_matches_spec(self):
        spec=SPECIFICATION.read_text()
        section=spec.split('### 14.5. Каталог команд P0')[1].split('### 14.6.')[0]
        expected=set(re.findall(r'^\| `([a-zA-Z]+\.[a-zA-Z]+)`',section,re.M))
        actual=set(API['components']['schemas']['Command']['discriminator']['mapping'])
        self.assertEqual(actual,expected)
    def test_routes_match_spec(self):
        spec=SPECIFICATION.read_text().split('### 14.3. Маршруты P0')[1].split('### 14.4.')[0]
        expected=set()
        for methods,path in re.findall(r'^\| `([A-Z, ]+) ([^`]+)`',spec,re.M):
            for method in methods.split(', '):expected.add((method.lower(),path))
        actual={(method,path) for path,ops in API['paths'].items() for method in ops}
        # OQ05 additive read-only JSON form for long terms, approved by coordinator.
        expected.add(('post','/api/v1/investigations/{id}/search'))
        # CR-E8-001 explicitly extends the P0 catalog with accounts and release metadata.
        expected.update({('get','/api/v1/accounts/config'),('post','/api/v1/accounts/register'),('post','/api/v1/accounts/verify-email'),('post','/api/v1/accounts/verification/request'),('post','/api/v1/accounts/password-reset/request'),('post','/api/v1/accounts/password-reset/complete'),('get','/api/v1/profile'),('patch','/api/v1/profile'),('post','/api/v1/profile/password'),('get','/release.json')})
        self.assertEqual(actual,expected)
    def test_mutations_require_origin_csrf(self):
        for path,ops in API['paths'].items():
            for method,op in ops.items():
                if method in ('post','put','delete','patch'):
                    headers={p['name'] for p in op['parameters'] if p['in']=='header' and p['required']}
                    self.assertTrue({'Origin','X-CSRF-Token'}<=headers,(method,path))
    def test_data_routes_require_authentication(self):
        for path,ops in API['paths'].items():
            if not path.startswith('/health') and path not in ('/api/v1/session','/api/v1/session/login','/api/v1/accounts/config','/api/v1/accounts/register','/api/v1/accounts/verify-email','/api/v1/accounts/verification/request','/api/v1/accounts/password-reset/request','/api/v1/accounts/password-reset/complete','/release.json'):
                for operation in ops.values():self.assertEqual(operation['security'],[{'sessionCookie':[]}])
    def test_long_search_query_whole_megabyte(self):schema_validator('SearchRequest',API).validate({'q':'a'*1048576})
    def test_long_search_query_utf8_limit(self):self.reject('SearchRequest',{'q':'я'*524289})
    def test_long_search_is_read_only(self):self.assertTrue(API['paths']['/api/v1/investigations/{id}/search']['post']['x-readOnly'])
    def test_unknown_command_field(self):
        v=example('CommandNodeUpdate');v['nodeIdTypo']=uid(9);self.reject('Command',v)
    def test_unknown_command_discriminator(self):self.reject('Command',{'kind':'node.execute','code':'danger'})
    def test_empty_patch(self):self.reject('NodeChanges',{})
    def test_patch_cannot_change_service_dates(self):self.reject('NodeChanges',{'createdAt':'2026-10-08T12:00:00Z'})
    def test_uuid_lowercase(self):self.reject('UUID','ABCDEF00-0000-4000-8000-000000000001')
    def test_revision_safe_integer(self):self.reject('Revision',9007199254740992)
    def test_coordinate_limit(self):v=example('NodeLayout');v['x']=1000001;self.reject('NodeLayout',v)
    def test_zindex_limit(self):v=example('NodeLayout');v['zIndex']=1000001;self.reject('NodeLayout',v)
    def test_document_markdown_five_mib_ascii_unicode_and_next_byte(self):
        for body in ('a' * DOCUMENT_MARKDOWN_BYTES, '😀' * (DOCUMENT_MARKDOWN_BYTES // 4)):
            self.assertEqual(len(body.encode('utf-8')), DOCUMENT_MARKDOWN_BYTES)
            for name in ('Node', 'NodeInput', 'NodeChanges', 'GroupNodeInput'):
                with self.subTest(schema=name, unicode=body[0] == '😀'):
                    value = {'bodyMarkdown': body} if name == 'NodeChanges' else example(name)
                    value['bodyMarkdown'] = body
                    schema_validator(name, API).validate(value)
                    value['bodyMarkdown'] += 'x'
                    self.reject(name, value)
    def test_other_markdown_fields_retain_one_mib_limit(self):
        schema_validator('InvestigationChanges', API).validate({'descriptionMarkdown': 'a' * 1048576})
        self.reject('InvestigationChanges', {'descriptionMarkdown': 'a' * 1048577})
    def test_five_mib_escaped_document_fits_command_json_limit(self):
        value = example('CommandBatch')
        value['commands'] = [{'kind': 'node.update', 'nodeId': uid(10), 'changes': {'bodyMarkdown': '\x01' * DOCUMENT_MARKDOWN_BYTES}}]
        size = len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
        self.assertGreater(size, 6 * DOCUMENT_MARKDOWN_BYTES)
        self.assertLess(size, COMMAND_JSON_BYTES)
        schema_validator('CommandBatch', API).validate(value)
    def test_command_batch_exact_32_mib_and_next_byte(self):
        value = example('CommandBatch')
        value['commands'] = [{'kind': 'node.update', 'nodeId': uid(10), 'changes': {'bodyMarkdown': 'a' * DOCUMENT_MARKDOWN_BYTES}} for _ in range(6)]
        value['commands'].append({'kind': 'node.update', 'nodeId': uid(10), 'changes': {'bodyMarkdown': ''}})
        prefix = len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
        value['commands'][-1]['changes']['bodyMarkdown'] = 'a' * (COMMAND_JSON_BYTES - prefix)
        self.assertEqual(len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()), COMMAND_JSON_BYTES)
        schema_validator('CommandBatch', API).validate(value)
        value['commands'][-1]['changes']['bodyMarkdown'] += 'x'
        self.reject('CommandBatch', value)
    def test_capabilities_document_and_command_limits_are_required(self):
        value = example('Limits')
        self.assertEqual(value['maxDocumentMarkdownBytes'], DOCUMENT_MARKDOWN_BYTES)
        self.assertEqual(value['maxCommandJsonBytes'], COMMAND_JSON_BYTES)
        for key in ('maxDocumentMarkdownBytes', 'maxCommandJsonBytes'):
            missing = {name: item for name, item in value.items() if name != key}
            self.reject('Limits', missing)
    def test_scalar_length_allows_emoji(self):schema_validator('NodeChanges',API).validate({'title':'😀'*200})
    def test_length_after_nfc_accepts_decomposed_input(self):schema_validator('NodeChanges',API).validate({'title':'e\u0301'*200})
    def test_length_after_trim_accepts_whitespace_input(self):schema_validator('NodeChanges',API).validate({'title':' '*201+'a'+' '*201})
    def test_length_counts_zwj_scalars_not_graphemes(self):self.reject('NodeChanges',{'title':'👩‍💻'*67})
    def test_nullable_patch(self):schema_validator('NodeChanges',API).validate({'subtitle':None})
    def test_personal_emoji_is_one_qualified_sequence(self):
        for value in ['😀', '👩🏽‍🔬', '🇷🇺', '1️⃣', None]:schema_validator('NodeChanges',API).validate({'iconEmoji':value})
        for value in ['', 'a', '😀😀', ' 😀', '❤', '🏽']:self.reject('NodeChanges',{'iconEmoji':value})
    def test_type_group_reserved(self):v=example('NodeTypeInput');v['code']='group';self.reject('NodeTypeInput',v)
    def test_duplicate_tags(self):self.reject('NodeChanges',{'tags':['tag','tag']})
    def test_normalized_duplicate_tags(self):self.reject('NodeChanges',{'tags':['tag',' tag ']})
    def test_normalized_empty_title(self):self.reject('NodeChanges',{'title':'   '})
    def test_typed_attribute_wrong_form(self):v=example('AttributeInputNumber');v['value']='12';self.reject('AttributeInput',v)
    def test_unknown_typed_value_is_null(self):v=example('AttributeInputNumber');v['value']=None;schema_validator('AttributeInput',API).validate(v)
    def test_invalid_calendar_day(self):self.reject('CalendarDate',{'precision':'day','value':'2025-02-29'})
    def test_invalid_calendar_zero_year(self):self.reject('CalendarDate',{'precision':'year','value':'0000'})
    def test_valid_leap_day(self):schema_validator('CalendarDate',API).validate({'precision':'day','value':'2024-02-29'})
    def test_bad_geo(self):self.reject('GeoValue',{'latitude':91,'longitude':0,'accuracyMeters':None})
    def test_zero_accuracy(self):self.reject('GeoValue',{'latitude':0,'longitude':0,'accuracyMeters':0})
    def test_javascript_url(self):v=example('EvidenceInputUrl');v['url']='javascript:alert(1)';self.reject('EvidenceInput',v)
    def test_evidence_multiple_sources(self):v=example('EvidenceInputNode');v['assetId']=uid(9);self.reject('EvidenceInput',v)
    def test_empty_trash(self):self.reject('Command',{'kind':'elements.trash','nodeIds':[],'relationIds':[],'groupMode':'group_only'})
    def test_snapshot_isolated_batch(self):
        v=example('CommandBatch');v['commands']=[example('CommandReportSnapshotcreate'),example('CommandInvestigationArchive')];self.reject('CommandBatch',v)
    def test_undo_isolated_batch(self):
        v=example('CommandBatch');v['commands']=[example('CommandOperationUndo'),example('CommandInvestigationArchive')];self.reject('CommandBatch',v)
    def test_nonempty_batch(self):v=example('CommandBatch');v['commands']=[];self.reject('CommandBatch',v)
    def test_max_batch(self):v=example('CommandBatch');v['commands']=[{'kind':'investigation.archive'}]*201;self.reject('CommandBatch',v)
    def test_export_variants_disallow_mixed_payload(self):v=example('ExportCreateProjectArchive');v['reportSnapshotId']=uid(9);self.reject('ExportCreate',v)
    def test_download_only_success(self):v=example('ExportJob');v['downloadAvailable']=True;self.reject('ExportJob',v)
    def test_error_shape_is_closed(self):v=example('ErrorRevisionConflict');v['error']['details']['stack']='secret';self.reject('ErrorResponse',v)
    def test_raw_duplicate_keys(self):
        with self.assertRaises(ValueError):strict_json('{"x":1,"x":2}')
    def test_raw_json_is_utf8_only(self):
        for encoding in ('utf-16','utf-32'):
            with self.assertRaises(ValueError):strict_json('{"title":"text"}'.encode(encoding))
    def test_raw_json_rejects_unpaired_surrogates(self):
        for raw in (r'{"title":"\ud800"}',r'{"title":"\udfff"}',r'{"\ud800":1}'):
            with self.assertRaises(ValueError):strict_json(raw)
    def test_raw_json_valid_surrogate_pair_is_a_scalar(self):self.assertEqual(strict_json(r'"\ud83d\ude00"'),'😀')
    def test_raw_nonfinite_number(self):
        for raw in ('NaN','Infinity','-Infinity','1e999'):
            with self.assertRaises(ValueError):strict_json(raw)
    def test_namespace_extensions(self):schema_validator('Extensions',API).validate({'org.example':{'custom':['data',4]}})
    def test_persisted_title_rejects_nul(self):self.reject('NodeChanges',{'title':'before\0after'})
    def test_persisted_markdown_rejects_nul(self):self.reject('InvestigationChanges',{'descriptionMarkdown':'before\0after'})
    def test_extension_string_rejects_nul(self):self.reject('Extensions',{'org.example':{'nested':['before\0after']}})
    def test_extension_object_key_rejects_nul(self):self.reject('Extensions',{'org.example':{'before\0after':'value'}})
    def test_password_can_contain_nul(self):schema_validator('LoginRequest',API).validate({'email':'owner@example.test','password':'A valid password\0suffix'})
    def test_plain_extension_key_rejected(self):self.reject('Extensions',{'command':'shell'})
    def test_extension_size(self):self.reject('Extensions',{'org.example':'a'*16384})

class ArchiveTests(unittest.TestCase):
    def setUp(self):self.project=project_fixture()
    def reject_project(self):
        with self.assertRaises((ValueError,ValidationError)):validate_project(self.project)
    def test_valid_graph(self):validate_project(self.project)
    def test_archive_persisted_markdown_rejects_nul(self):self.project['nodes'][0]['bodyMarkdown']='before\0after';self.reject_project()
    def test_archive_and_snapshot_keep_five_mib_document_text(self):
        for body in ('a' * DOCUMENT_MARKDOWN_BYTES, '😀' * (DOCUMENT_MARKDOWN_BYTES // 4)):
            self.project['nodes'][0]['bodyMarkdown'] = body
            validate_project(self.project)
            snapshot = example('SnapshotContent')
            snapshot['nodes'] = [copy.deepcopy(self.project['nodes'][0])]
            schema_validator('SnapshotContent', API).validate(snapshot)
            archive_validator('SnapshotContent', ARCHIVE).validate(snapshot)
            self.project['nodes'][0]['bodyMarkdown'] += 'x'
            self.reject_project()
            snapshot['nodes'][0]['bodyMarkdown'] += 'x'
            with self.assertRaises(ValidationError): schema_validator('SnapshotContent', API).validate(snapshot)
            with self.assertRaises(ValidationError): archive_validator('SnapshotContent', ARCHIVE).validate(snapshot)
    def test_owner_secrets_excluded(self):self.project['investigation']['ownerId']=uid(100);self.reject_project()
    def test_unknown_project_fields(self):self.project['session']='secret';self.reject_project()
    def test_duplicate_uuid(self):self.project['nodes'][1]['id']=uid(10);self.reject_project()
    def test_cross_investigation(self):self.project['nodes'][0]['investigationId']=uid(100);self.reject_project()
    def test_missing_type(self):self.project['nodes'][0]['typeId']=uid(100);self.reject_project()
    def test_missing_layout(self):self.project['layouts'].pop();self.reject_project()
    def test_self_relation(self):self.project['relations'][0]['targetNodeId']=uid(10);self.reject_project()
    def test_parallel_relations_allowed(self):
        r=copy.deepcopy(self.project['relations'][0]);r['id']=uid(21);self.project['relations'].append(r);validate_project(self.project)
    def test_bidirectional_relation(self):
        r=self.project['relations'][0];r['directed']=True;r['bidirectional']=True;validate_project(self.project)
        r['directed']=False;self.reject_project()
    def test_uncanonical_undirected(self):r=self.project['relations'][0];r['sourceNodeId'],r['targetNodeId']=r['targetNodeId'],r['sourceNodeId'];self.reject_project()
    def test_nested_group(self):self.project['memberships'][0]['memberNodeId']=uid(12);self.reject_project()
    def test_two_group_memberships(self):self.project['memberships'].append(copy.deepcopy(self.project['memberships'][0]));self.reject_project()
    def test_manifest_path_traversal(self):
        v={'format':'research-graph.archive','formatVersion':'1.0','exportedAt':'2026-10-08T12:00:00Z','sourceInvestigationId':uid(1),'sourceRevision':0,'projectPath':'project.json','includesTrash':True,'includesSnapshots':True,'files':[{'path':'../escape','byteSize':0,'sha256':'a'*64}]}
        with self.assertRaises(ValidationError):archive_validator('Manifest',ARCHIVE).validate(v)
    def test_archive_directory_hashes_and_tampering(self):
        with tempfile.TemporaryDirectory() as raw:
            directory=Path(raw);data=json.dumps(self.project).encode();(directory/'project.json').write_bytes(data)
            manifest={'format':'research-graph.archive','formatVersion':'1.0','exportedAt':'2026-10-08T12:00:00Z','sourceInvestigationId':uid(1),'sourceRevision':0,'projectPath':'project.json','includesTrash':True,'includesSnapshots':True,'files':[{'path':'project.json','byteSize':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}
            (directory/'manifest.json').write_text(json.dumps(manifest));validate_archive_directory(directory)
            (directory/'project.json').write_bytes(data+b' ')
            with self.assertRaises(ValueError):validate_archive_directory(directory)
    def snapshot(self):
        report=example('ReportDefinition');report.update(id=uid(50),investigationId=uid(1),selectedNodeIds=[],orderedConclusionIds=[])
        self.project['reports'].append(report)
        snapshot=example('ReportSnapshot');snapshot.update(id=uid(51),investigationId=uid(1),reportDefinitionId=uid(50))
        snapshot['content'].update(definition=copy.deepcopy(report),nodes=copy.deepcopy(self.project['nodes']),relations=copy.deepcopy(self.project['relations']),nodeTypes=copy.deepcopy(self.project['nodeTypes']),relationTypes=copy.deepcopy(self.project['relationTypes']))
        self.project['snapshots'].append(snapshot);return snapshot
    def test_snapshot_freezes_original_text(self):
        snapshot=self.snapshot();snapshot['content']['nodes'][0]['bodyMarkdown']='Historical version'
        self.project['nodes'][0]['bodyMarkdown']='Edited current version';validate_project(self.project)
    def test_snapshot_missing_endpoint(self):
        snapshot=self.snapshot();snapshot['content']['nodes'].pop(0);self.reject_project()
    def test_snapshot_definition_identity(self):
        snapshot=self.snapshot();snapshot['content']['definition']['id']=uid(55);self.reject_project()
    def test_snapshot_missing_type(self):
        snapshot=self.snapshot();snapshot['content']['nodeTypes']=[];self.reject_project()
    def test_snapshot_historical_node_need_not_exist_live(self):
        snapshot=self.snapshot();row=copy.deepcopy(snapshot['content']['nodes'][0]);row['id']=uid(999)
        snapshot['content']['nodes'].append(row);validate_project(self.project)
    def test_unsupported_version(self):self.project['formatVersion']='2.0';self.reject_project()

if __name__=='__main__':unittest.main()
