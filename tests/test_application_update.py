import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import yaml
from tools import application_update_test, control
from tools.update_integration import PreparedBatch

ROOT = Path(__file__).resolve().parents[1]

class ApplicationUpdateTests(unittest.TestCase):
    def candidate(self):
        # Synthetic in-memory validation input, never written as a release or pulled.
        value = json.loads((ROOT / 'releases/0.1.4.json').read_text())
        for key in ['releaseId', 'frontendReleaseId', 'frontendVersion', 'backendVersion']:
            value[key] = '0.1.5'
        for key in ['backend', 'frontend', 'gateway', 'tools']:
            digest = hashlib.sha256(('synthetic application update unit fixture ' + key).encode()).hexdigest()
            value['images'][key] = 'docker.io/andreytorlopov/traceweave-' + key + ':0.1.5@sha256:' + digest
        contract = hashlib.sha256((ROOT / 'contracts/openapi.yaml').read_bytes()).hexdigest()
        value['contractHash'] = value['backendContractHash'] = contract
        value['supportedClientContractHashes'] = [contract] + json.loads((ROOT / 'contracts/client-compatibility.json').read_text())
        for version, name in [(8, '0008-file-attachments.sql'), (9, '0009-readable-report.sql')]:
            value['migrations'].append({'version': version, 'sha256': hashlib.sha256((ROOT / 'contracts/migrations' / name).read_bytes()).hexdigest()})
        return value

    def test_all_published_baselines_retain_their_exact_infrastructure_and_history(self):
        for filename, version in application_update_test.BASES.values():
            with self.subTest(filename=filename):
                base = json.loads((ROOT / 'releases' / filename).read_text())
                self.assertEqual(base['releaseId'], version)
                candidate = self.candidate()
                before = copy.deepcopy((base, candidate))
                selected = application_update_test.compatible(base, candidate)
                control.validate_update(base, selected)
                self.assertEqual((base, candidate), before)
                self.assertEqual(selected['releaseId'], '0.1.5')
                self.assertEqual(set(control.changes(base, selected)), {'backend', 'frontend'})
                for key in ['postgres', 'tools', 'gateway']:
                    self.assertEqual(selected['images'][key], base['images'][key])
                self.assertEqual(selected['migrations'][:len(base['migrations'])], base['migrations'])
                self.assertEqual(len(selected['migrations']), 9)
                self.assertNotEqual(selected['migrations'], base['migrations'])
                for key in ['delivery', 'deliveryDiffHash']:
                    self.assertEqual(selected['source'][key], base['source'][key])
                self.assertTrue(set(base['supportedClientContractHashes']) <= set(selected['supportedClientContractHashes']))

    def test_acceptance_cannot_change_existing_history_or_strand_pending_clients(self):
        for filename, _ in application_update_test.BASES.values():
            base = json.loads((ROOT / 'releases' / filename).read_text())
            for kind in ['history', 'client', 'version', 'short_schema', 'extra_schema', 'attachment_migration', 'report_migration']:
                value = self.candidate()
                if kind == 'history': value['migrations'][0]['sha256'] = 'e' * 64
                elif kind == 'client': value['supportedClientContractHashes'] = [value['contractHash']]
                elif kind == 'version': value['backendVersion'] = '0.1.4'
                elif kind == 'extra_schema': value['migrations'].append({'version': 10, 'sha256': 'e' * 64})
                elif kind == 'attachment_migration': value['migrations'][7]['sha256'] = 'e' * 64
                elif kind == 'report_migration': value['migrations'][8]['sha256'] = 'e' * 64
                else: value['migrations'].pop()
                with self.subTest(filename=filename, kind=kind), self.assertRaises((AssertionError, control.Failure)):
                    application_update_test.compatible(base, value)

    def test_same_application_version_has_three_distinct_retained_infrastructures(self):
        baselines = [json.loads((ROOT / 'releases' / name).read_text()) for name in
                     ['0.1.3.json', '0.1.3-update.json', '0.1.3-update-from-0.1.1.json']]
        self.assertEqual({item['releaseId'] for item in baselines}, {'0.1.3'})
        self.assertEqual(len({item['images']['tools'] for item in baselines}), 3)
        for base in baselines:
            selected = application_update_test.compatible(base, self.candidate())
            self.assertEqual(selected['source']['delivery'], base['source']['delivery'])

    def test_published_014_has_four_distinct_infrastructures_with_schema_seven(self):
        baselines = [json.loads((ROOT / 'releases' / filename).read_text())
                     for filename, version in application_update_test.BASES.values() if version == '0.1.4']
        self.assertEqual(len(baselines), 4)
        self.assertEqual(len({item['images']['tools'] for item in baselines}), 4)
        self.assertEqual(len({item['source']['delivery'] for item in baselines}), 4)
        for base in baselines:
            self.assertEqual(len(base['migrations']), 7)

    def test_workflow_covers_every_baseline_on_both_native_architectures(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/application-update.yml').read_text())
        matrix = workflow['jobs']['published-update']['strategy']['matrix']['include']
        pairs = {(item['base'], item['arch']) for item in matrix}
        self.assertEqual(len(application_update_test.BASES), 9)
        self.assertEqual(len(matrix), 18)
        self.assertEqual(pairs, {(base, arch) for base in application_update_test.BASES for arch in ['amd64', 'arm64']})
        for item in matrix:
            base = json.loads((ROOT / 'releases' / application_update_test.BASES[item['base']][0]).read_text())
            version = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', base['images']['tools']).group(1)
            original = json.loads((ROOT / 'releases' / (version + '.json')).read_text())
            self.assertEqual(item['legacy_tag'], 'v' + version)
            self.assertEqual(base['source']['delivery'], original['source']['delivery'])
            self.assertEqual(item['runner'], {'amd64': 'ubuntu-24.04', 'arm64': 'ubuntu-24.04-arm'}[item['arch']])

    def test_schema_nine_refuses_image_rollback_without_changing_any_installation_files(self):
        for filename, _ in application_update_test.BASES.values():
            base = json.loads((ROOT / 'releases' / filename).read_text())
            selected = application_update_test.compatible(base, self.candidate())
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory, \
                    patch.object(control, 'RUNTIME', Path(directory)):
                for name, value in [('release.json', selected), ('previous-release.json', base), ('operation.json', {'phase': 'ready'})]:
                    control.write_json(Path(directory) / name, value)
                before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
                with patch.object(control, 'load_config', return_value={}), \
                        patch.object(control, 'is_running', return_value=True), \
                        patch.object(control, 'compose', return_value=json.dumps(selected['migrations'])) as compose, \
                        patch.object(control, 'phase') as phase, patch.object(control, 'reload_gateway') as gateway, \
                        patch.object(control, 'stop_backend') as stop:
                    with self.assertRaisesRegex(control.Failure, 'Schema has changed. Image rollback refused'):
                        control.rollback(SimpleNamespace(yes=True))
                    compose.assert_called_once_with('run', '--rm', '-T', '--no-deps', 'ops', 'history', config={}, release=selected, capture=True)
                    phase.assert_not_called(); gateway.assert_not_called(); stop.assert_not_called()
                self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()}, before)

    def test_pending_replay_preserves_original_bytes_and_contract_headers(self):
        raw = b'{ "operationId": "synthetic-operation", "commands": [], "baseRevision": 17 }'
        headers = (('X-TraceWeave-Client-Contract', '5b9da16997f94c15dd952224292961c2de8f90b31a12e0ff4d14da89a6048281'),
                   ('Cookie', 'synthetic-old-session'), ('X-CSRF-Token', 'synthetic-old-csrf'))
        prepared = PreparedBatch(raw, headers, 'synthetic-operation', 17, 'synthetic-node', 'Pending title')
        client = Mock()
        client.json.side_effect = [
            {'operationId': prepared.operation_id, 'revision': 18, 'replayed': False},
            {'operationId': prepared.operation_id, 'revision': 18, 'replayed': True},
            {'node': {'title': prepared.title}}, {'node': {'title': 'Edited after update synthetic-edit'}}]
        with patch('tools.update_integration.uid', return_value='synthetic-edit'):
            application_update_test.apply_prepared_and_edit(client, '/synthetic-investigation', prepared)
        for call in client.json.call_args_list[:2]:
            self.assertEqual(call.args, ('POST', '/synthetic-investigation/commands'))
            self.assertEqual(call.kwargs, {'raw': raw, 'headers': dict(headers)})
        client.commands.assert_called_once_with('/synthetic-investigation', [
            {'kind': 'node.update', 'nodeId': prepared.node_id, 'changes': {'title': 'Edited after update synthetic-edit'}}])

if __name__ == '__main__': unittest.main()
