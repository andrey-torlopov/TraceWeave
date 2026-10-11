"""Real PostgreSQL model checks; only explicit dedicated test DSN is accepted.

The whole schema/data setup is rolled back, not destructively migrated or dropped.
"""
import os
import json
from pathlib import Path
import unittest
import uuid
import unicodedata
from urllib.parse import urlparse
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]

def uid(i):return str(uuid.UUID(int=i))

class DatabaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn=os.environ.get('RG_CONTRACT_DATABASE_URL')
        if not dsn:raise unittest.SkipTest('not_run: RG_CONTRACT_DATABASE_URL is not set; real PostgreSQL required for E0 acceptance')
        target=urlparse(dsn)
        if not target.path.removeprefix('/').startswith('traceweave_test_') or target.username!='traceweave_test':
            raise RuntimeError('refusing non-test contract database/role')
        cls.connection=psycopg.connect(dsn)
        cls.connection.execute('SET statement_timeout=15000')
        cls.connection.execute('SET lock_timeout=3000')
        cls.schema='contract_'+uuid.uuid4().hex
        cls.connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        cls.connection.execute(sql.SQL('SET LOCAL search_path TO {}, pg_catalog').format(sql.Identifier(cls.schema)))
        cls.connection.execute((ROOT/'contracts/database.sql').read_text())
        cls.connection.execute("INSERT INTO owners(id,display_name,password_hash,collection_revision,created_at,updated_at,email,email_verified_at) VALUES (%s,'Test','$argon2id$v=19$m=65536,t=3,p=1$synthetic$synthetic',0,now(),now(),'test@example.test',now())",[uid(1)])
        for inv in (10,20):
            cls.connection.execute("INSERT INTO investigations VALUES (%s,%s,'Synthetic','','active',0,now(),now(),NULL)",[uid(inv),uid(1)])
            for offset,code in ((1,'note'),(2,'group')):
                cls.connection.execute("INSERT INTO node_types VALUES (%s,%s,%s,%s,'file-text','#336699',true,false,'[]')",[uid(inv+offset),uid(inv),code,code])
            cls.connection.execute("INSERT INTO relation_types VALUES (%s,%s,'related_to','Related',false,false)",[uid(inv+3),uid(inv)])
        for node,inv,typ in ((100,10,11),(101,10,11),(102,10,12),(200,20,21)):
            cls.connection.execute("INSERT INTO nodes(id,investigation_id,type_id,title,origin,created_at,updated_at) VALUES (%s,%s,%s,'Node','{\"kind\":\"manual\"}',now(),now())",[uid(node),uid(inv),uid(typ)])
            cls.connection.execute('INSERT INTO node_layouts VALUES (%s,%s,0,0,0)',[uid(node),uid(inv)])
        cls.connection.execute("INSERT INTO blobs VALUES (%s,%s,%s,%s,4,'available',now())",[uid(300),uid(10),'aa/'+'a'*64,'a'*64])
        for asset in (301,302):
            cls.connection.execute("INSERT INTO assets(id,investigation_id,blob_id,original_name,title,mime_type,media_kind,byte_size,sha256,origin,created_at) VALUES (%s,%s,%s,'test.txt','Material','text/plain','text',4,%s,'{\"kind\":\"manual\"}',now())",[uid(asset),uid(10),uid(300),'a'*64])
        cls.connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cls.connection.execute('SET CONSTRAINTS ALL DEFERRED')
    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'connection'):
            cls.connection.rollback();cls.connection.close()
    def setUp(self):
        self.tx=self.connection.transaction(force_rollback=True);self.tx.__enter__()
    def tearDown(self):self.tx.__exit__(None,None,None)
    def execute(self,query,args=()):return self.connection.execute(query,args)
    def rejected(self,query,args=()):
        with self.assertRaises(psycopg.IntegrityError):
            with self.connection.transaction():
                self.execute(query,args);self.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def relation(self,i=400,source=100,target=101,directed=False):
        return self.execute("INSERT INTO relations(id,investigation_id,source_node_id,target_node_id,relation_type,directed,origin,created_at,updated_at) VALUES (%s,%s,%s,%s,'related_to',%s,'{\"kind\":\"manual\"}',now(),now())",[uid(i),uid(10),uid(source),uid(target),directed])
    def test_real_supported_postgres(self):self.assertGreaterEqual(int(self.execute('SHOW server_version_num').fetchone()[0]),180000)
    def test_cross_investigation_node_type(self):self.rejected('UPDATE nodes SET type_id=%s WHERE id=%s',[uid(21),uid(100)])
    def test_cross_investigation_relation(self):
        with self.assertRaises(psycopg.IntegrityError):
            with self.connection.transaction():self.relation(target=200)
    def test_self_relation(self):
        with self.assertRaises(psycopg.IntegrityError):
            with self.connection.transaction():self.relation(target=100)
    def test_parallel_active_relations(self):
        self.relation();self.relation(i=401);self.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertEqual(self.execute('SELECT count(*) FROM relations WHERE deleted_at IS NULL').fetchone()[0],2)
    def test_bidirectional_requires_directed(self):
        self.relation(directed=True);self.execute('UPDATE relations SET bidirectional=true');self.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.rejected('UPDATE relations SET directed=false')
    def test_different_direction_allowed(self):
        self.relation();self.relation(i=401,directed=True);self.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def test_canonical_undirected_relation(self):
        with self.assertRaises(psycopg.IntegrityError):
            with self.connection.transaction():self.relation(source=101,target=100)
    def test_group_inside_group_rejected(self):
        self.rejected('INSERT INTO group_memberships VALUES (%s,%s,%s,0)',[uid(10),uid(100),uid(102)])
    def test_membership_allows_group_normal_node(self):
        self.execute('INSERT INTO group_memberships VALUES (%s,%s,%s,0)',[uid(10),uid(102),uid(100)]);self.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def test_membership_cross_investigation(self):
        self.rejected('INSERT INTO group_memberships VALUES (%s,%s,%s,0)',[uid(10),uid(102),uid(200)])
    def test_deleting_endpoint_requires_atomic_relation_trash(self):
        self.relation();self.execute('INSERT INTO deletion_batches VALUES (%s,%s,now())',[uid(500),uid(10)])
        self.rejected('UPDATE nodes SET deleted_at=now(),deletion_batch_id=%s WHERE id=%s',[uid(500),uid(100)])
    def test_trashing_node_and_relation_final_state_succeeds(self):
        self.relation();self.execute('INSERT INTO deletion_batches VALUES (%s,%s,now())',[uid(500),uid(10)])
        self.execute('UPDATE nodes SET deleted_at=now(),deletion_batch_id=%s WHERE id=%s',[uid(500),uid(100)])
        self.execute('UPDATE relations SET deleted_at=now(),deletion_batch_id=%s WHERE id=%s',[uid(500),uid(400)])
        self.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def test_coordinates_reject_nan(self):self.rejected("UPDATE node_layouts SET x='NaN' WHERE node_id=%s",[uid(100)])
    def test_coordinates_reject_infinity(self):self.rejected("UPDATE node_layouts SET y='Infinity' WHERE node_id=%s",[uid(100)])
    def test_safe_revision(self):self.rejected('UPDATE investigations SET revision=9007199254740992 WHERE id=%s',[uid(10)])
    def test_real_calendar_validation(self):
        self.rejected("INSERT INTO attributes VALUES (%s,%s,%s,'Date','date','date','{\"precision\":\"day\",\"value\":\"2025-02-29\"}',0)",[uid(600),uid(10),uid(100)])
    def test_date_json_null_and_wrong_types_rejected(self):
        for value in ({'precision':'day','value':None},{'precision':None,'value':'2026-10-08'},{'precision':'year','value':2026},{'precision':3,'value':'2026'}, {'precision':'month','value':False}):
            with self.subTest(value=value):
                self.assertIs(self.execute("SELECT rg_valid_attribute('date',%s::jsonb)",[json.dumps(value)]).fetchone()[0],False)
    def test_malformed_origins_never_return_null(self):
        for value in ({},{'kind':None},{'kind':3},{'kind':'import','importId':None,'sourceInvestigationId':None,'sourceObjectId':None,'importedAt':None},{'kind':'manual','unexpected':True}):
            with self.subTest(value=value):self.assertIs(self.execute('SELECT rg_valid_origin(%s::jsonb)',[json.dumps(value)]).fetchone()[0],False)
    def test_attribute_typed_number(self):
        self.rejected("INSERT INTO attributes VALUES (%s,%s,%s,'Count','count','number','\"12\"',0)",[uid(600),uid(10),uid(100)])
    def test_geo_accuracy_positive(self):
        self.rejected("INSERT INTO attributes VALUES (%s,%s,%s,'Location','location','geo','{\"latitude\":0,\"longitude\":0,\"accuracyMeters\":0}',0)",[uid(600),uid(10),uid(100)])
    def test_duplicate_primary_attachment(self):
        self.execute("INSERT INTO node_attachments VALUES (%s,%s,%s,%s,'primary',NULL,0)",[uid(700),uid(10),uid(100),uid(301)])
        self.rejected("INSERT INTO node_attachments VALUES (%s,%s,%s,%s,'primary',NULL,1)",[uid(701),uid(10),uid(100),uid(302)])
    def test_blob_immutable(self):self.rejected('UPDATE blobs SET sha256=%s WHERE id=%s',['b'*64,uid(300)])
    def test_referenced_blob_cannot_delete(self):self.rejected('DELETE FROM blobs WHERE id=%s',[uid(300)])
    def test_asset_blob_hash_match(self):self.rejected('UPDATE assets SET sha256=%s WHERE id=%s',['b'*64,uid(301)])
    def test_evidence_subject_fk(self):
        self.rejected("INSERT INTO evidence_references(id,investigation_id,subject_kind,subject_id,source_kind,url,label,note) VALUES (%s,%s,'node',%s,'url','https://example.test','Source','')",[uid(800),uid(10),uid(200)])
    def test_evidence_exactly_one_source(self):
        self.rejected("INSERT INTO evidence_references(id,investigation_id,subject_kind,subject_id,source_kind,source_node_id,url,label,note) VALUES (%s,%s,'node',%s,'url',%s,'https://example.test','Source','')",[uid(800),uid(10),uid(100),uid(101)])
    def test_large_markdown_byte_limit(self):
        limit = 5 * 1024 * 1024
        for body in ('a' * limit, '😀' * (limit // 4)):
            with self.subTest(unicode=body[0] == '😀'):
                self.execute('UPDATE nodes SET body_markdown=%s WHERE id=%s', [body, uid(100)])
                saved, size = self.execute('SELECT body_markdown,octet_length(body_markdown) FROM nodes WHERE id=%s', [uid(100)]).fetchone()
                self.assertTrue(saved == body, 'accepted Markdown changed in PostgreSQL')
                self.assertEqual(size, limit)
                self.rejected('UPDATE nodes SET body_markdown=%s WHERE id=%s', [body + 'x', uid(100)])
                self.assertTrue(self.execute('SELECT body_markdown FROM nodes WHERE id=%s', [uid(100)]).fetchone()[0] == body,
                                'rejected oversized Markdown replaced existing data')
    def test_other_markdown_domain_keeps_one_mib_limit(self):
        self.execute('UPDATE investigations SET description_markdown=%s WHERE id=%s', ['a' * 1048576, uid(10)])
        self.rejected('UPDATE investigations SET description_markdown=%s WHERE id=%s', ['a' * 1048577, uid(10)])
    def test_operation_request_bytes_32_mib_boundary(self):
        response = json.dumps({'operationId': uid(1200), 'revision': 1, 'replayed': False,
                               'changedNodeIds': [], 'changedRelationIds': [], 'changedAssetIds': [],
                               'createdSnapshotIds': [], 'deletedIds': [], 'serverTime': '2026-10-09T00:00:00Z'})
        self.execute("INSERT INTO operations(id,investigation_id,revision_before,revision_after,actor_id,client_id,kind,created_at,request_sha256,request_bytes,response,forward_effect,reverse_effect,undoable) VALUES (%s,%s,0,1,%s,%s,'commands',now(),%s,%s,%s::jsonb,'[]','[]',true)",
                     [uid(1200), uid(10), uid(1), uid(1201), 'a' * 64, b'x' * (32 * 1024 * 1024), response])
        self.assertEqual(self.execute('SELECT octet_length(request_bytes) FROM operations WHERE id=%s', [uid(1200)]).fetchone()[0], 32 * 1024 * 1024)
        self.rejected("UPDATE operations SET request_bytes=request_bytes || '\\x78'::bytea WHERE id=%s", [uid(1200)])
    def test_fulltext_vector_gin_and_cross_fragment_and(self):
        self.execute("INSERT INTO search_objects(id,investigation_id,object_kind,object_id) VALUES (%s,%s,'node',%s)",[uid(900),uid(10),uid(100)])
        for ordinal,text in enumerate(['Привет начало','LATIN окончание']):
            self.execute("INSERT INTO search_fragments VALUES (%s,'bodyMarkdown',%s,%s,%s,DEFAULT)",[uid(900),ordinal,text,unicodedata.normalize('NFC',text).casefold()])
        found=self.execute("SELECT o.id FROM search_objects o WHERE NOT EXISTS(SELECT term FROM unnest(tsvector_to_array(to_tsvector('pg_catalog.simple',%s))) AS term WHERE NOT EXISTS(SELECT 1 FROM search_fragments f WHERE f.object_id=o.id AND vector @@ plainto_tsquery('pg_catalog.simple',term)))",[unicodedata.normalize('NFC','ПРИВЕТ latin').casefold()]).fetchall()
        self.assertEqual([str(row[0]) for row in found],[uid(900)])
        indexes=self.execute("SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND tablename='search_fragments'",[self.schema]).fetchall()
        self.assertTrue(any('USING gin (vector)' in row[0] for row in indexes))
    def test_snapshot_immutable(self):
        self.execute("INSERT INTO report_definitions VALUES (%s,%s,'Report','','all',true,true,true,now(),now())",[uid(1000),uid(10)])
        self.execute("INSERT INTO report_snapshots VALUES (%s,%s,%s,0,'1.0',now(),%s,%s,NULL)",[uid(1001),uid(10),uid(1000),'{"investigationTitle":"Synthetic","definition":{},"nodes":[],"attributes":[],"relations":[],"nodeTypes":[],"relationTypes":[],"attachments":[],"assets":[],"evidence":[],"warnings":[]}','a'*64])
        self.rejected('UPDATE report_snapshots SET source_revision=1 WHERE id=%s',[uid(1001)])

if __name__=='__main__':unittest.main()
