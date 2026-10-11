import copy
import hashlib
import json
import os
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
            value[key] = '0.1.8'
        for key in ['backend', 'frontend', 'gateway', 'tools']:
            digest = hashlib.sha256(('synthetic application update unit fixture ' + key).encode()).hexdigest()
            value['images'][key] = 'docker.io/andreytorlopov/traceweave-' + key + ':0.1.8@sha256:' + digest
        contract = hashlib.sha256((ROOT / 'contracts/openapi.yaml').read_bytes()).hexdigest()
        value['contractHash'] = value['backendContractHash'] = contract
        value['supportedClientContractHashes'] = [contract] + json.loads((ROOT / 'contracts/client-compatibility.json').read_text())
        for version, name in [(8, '0008-file-attachments.sql'), (9, '0009-readable-report.sql'), (10, '0010-evidence-node-type.sql')]:
            value['migrations'].append({'version': version, 'sha256': hashlib.sha256((ROOT / 'contracts/migrations' / name).read_bytes()).hexdigest()})
        value['source']['delivery'] = 'f' * 40
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
                self.assertEqual(selected['releaseId'], '0.1.8')
                same_schema = base['migrations'] == candidate['migrations']
                self.assertEqual(set(control.changes(base, selected)), {'backend', 'frontend'} if same_schema else {'backend', 'frontend', 'tools'})
                for key in ['postgres', 'gateway']:
                    self.assertEqual(selected['images'][key], base['images'][key])
                if same_schema:
                    self.assertEqual(selected['images']['tools'], base['images']['tools'])
                    self.assertNotIn('toolsUpgrade', selected)
                    for key in ['tools', 'toolsDiffHash']:
                        self.assertEqual(selected['source'].get(key), base['source'].get(key))
                else:
                    self.assertEqual(selected['images']['tools'], candidate['images']['tools'])
                    self.assertEqual(selected['toolsUpgrade'], {'from': base['images']['tools'], 'to': candidate['images']['tools']})
                    self.assertEqual(selected['source']['tools'], candidate['source']['delivery'])
                    self.assertEqual(selected['source']['toolsDiffHash'], candidate['source']['deliveryDiffHash'])
                self.assertEqual(selected['migrations'][:len(base['migrations'])], base['migrations'])
                self.assertEqual(len(selected['migrations']), 10)
                self.assertEqual(selected['migrations'] == base['migrations'], version == '0.1.7')
                for key in ['delivery', 'deliveryDiffHash']:
                    self.assertEqual(selected['source'][key], base['source'][key])
                self.assertTrue(set(base['supportedClientContractHashes']) <= set(selected['supportedClientContractHashes']))

    def test_every_published_baseline_selects_its_gateway_variant_from_full_candidate(self):
        candidate = self.candidate()
        stable = control.ROOT / 'releases/stable.json'
        for filename, _ in application_update_test.BASES.values():
            with self.subTest(filename=filename):
                base = json.loads((ROOT / 'releases' / filename).read_text())
                selected = application_update_test.compatible(base, candidate)
                version = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', base['images']['gateway']).group(1)
                expected = stable.parent / application_update_test.compatible_name(base)
                fixtures = {stable: candidate, expected: selected}
                with patch.object(control, 'manifest', side_effect=lambda path: copy.deepcopy(fixtures[path])), \
                        patch.object(Path, 'exists', lambda path: path in fixtures):
                    self.assertEqual(control.bootstrap_update(base, stable), (expected, selected))

    def test_same_gateway_with_different_tools_selects_the_exact_from_version(self):
        candidate = self.candidate()
        bases = [json.loads((ROOT / 'releases' / name).read_text()) for name in
                 ['0.1.4-update-infra-0.1.0.json', '0.1.6-update-infra-0.1.0.json']]
        self.assertEqual(bases[0]['images']['gateway'], bases[1]['images']['gateway'])
        self.assertNotEqual(bases[0]['images']['tools'], bases[1]['images']['tools'])
        with tempfile.TemporaryDirectory() as directory:
            stable = Path(directory) / 'stable.json'
            control.write_json(stable, candidate)
            variants = {}
            for base in bases:
                name = application_update_test.compatible_name(base)
                variants[name] = application_update_test.compatible(base, candidate)
                control.write_json(stable.parent / name, variants[name])
            self.assertEqual(len(variants), 2)
            for base in bases:
                expected = stable.parent / application_update_test.compatible_name(base)
                self.assertEqual(control.bootstrap_update(base, stable), (expected, variants[expected.name]))

    def test_update_names_never_select_different_payloads_for_the_same_variant(self):
        variants = {}
        for filename, _ in application_update_test.BASES.values():
            base = json.loads((ROOT / 'releases' / filename).read_text())
            name = application_update_test.compatible_name(base)
            selected = application_update_test.compatible(base, self.candidate())
            if name in variants:
                self.assertEqual(variants[name], selected, filename)
            variants[name] = selected
        self.assertEqual(len(variants), 15)

    def test_published_older_tools_are_trusted_for_restore_by_local_release_catalog(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'RUNTIME', Path(directory)):
            for filename, _ in application_update_test.BASES.values():
                with self.subTest(filename=filename):
                    base = json.loads((ROOT / 'releases' / filename).read_text())
                    installed = application_update_test.compatible(base, self.candidate())
                    self.assertEqual(base['images']['tools'] == installed['images']['tools'], len(base['migrations']) == 10)
                    control.require_trusted_restore_tools(base, installed)

    def test_pulled_tools_use_new_provenance_while_gateway_retains_the_original_delivery(self):
        base = json.loads((ROOT / 'releases/0.1.0.json').read_text())
        candidate = self.candidate()
        selected = application_update_test.compatible(base, candidate)
        images = {}
        for release in [base, selected]:
            for key, reference in release['images'].items():
                if reference in images: continue
                labels = {}
                if key != 'postgres':
                    source = release['source'][key] if key in ['backend', 'frontend'] else (
                        candidate['source']['delivery'] if key == 'tools' and release is selected else base['source']['delivery'])
                    version = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', reference).group(1)
                    labels = {'org.opencontainers.image.version': version, 'org.opencontainers.image.ref.name': 'v' + version,
                              'org.opencontainers.image.revision': source, 'org.opencontainers.image.source':
                              'https://github.com/andrey-torlopov/TraceWeave' + {'backend': 'Backend', 'frontend': 'Frontend'}.get(key, '')}
                images[reference] = {'Id': 'sha256:' + hashlib.sha256(reference.encode()).hexdigest(), 'Os': 'linux',
                                     'Architecture': 'amd64', 'Config': {'Labels': labels}}
        def command(*args):
            if args == ('docker', 'info', '--format', '{{.Architecture}}'): return 'amd64'
            self.assertEqual(args[:3], ('docker', 'image', 'inspect'))
            return json.dumps([images[args[3]]])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DOCKER_CONFIG': directory}), \
                patch.object(application_update_test.previous, 'command', side_effect=command), patch('subprocess.run'):
            observed = application_update_test.pull_images(base, selected, 'amd64')
            self.assertEqual(set(observed), set(images))
            images[selected['images']['tools']]['Config']['Labels']['org.opencontainers.image.revision'] = base['source']['delivery']
            with self.assertRaisesRegex(AssertionError, 'OCI provenance'):
                application_update_test.pull_images(base, selected, 'amd64')

    def test_acceptance_cannot_change_existing_history_or_strand_pending_clients(self):
        for filename, _ in application_update_test.BASES.values():
            base = json.loads((ROOT / 'releases' / filename).read_text())
            for kind in ['history', 'client', 'version', 'short_schema', 'extra_schema', 'attachment_migration', 'report_migration', 'evidence_migration']:
                value = self.candidate()
                if kind == 'history': value['migrations'][0]['sha256'] = 'e' * 64
                elif kind == 'client': value['supportedClientContractHashes'] = [value['contractHash']]
                elif kind == 'version': value['backendVersion'] = '0.1.4'
                elif kind == 'extra_schema': value['migrations'].append({'version': 11, 'sha256': 'e' * 64})
                elif kind == 'attachment_migration': value['migrations'][7]['sha256'] = 'e' * 64
                elif kind == 'evidence_migration': value['migrations'][9]['sha256'] = 'e' * 64
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
        self.assertEqual(len(application_update_test.BASES), 24)
        self.assertEqual(len(matrix), 48)
        self.assertEqual(pairs, {(base, arch) for base in application_update_test.BASES for arch in ['amd64', 'arm64']})
        for item in matrix:
            base = json.loads((ROOT / 'releases' / application_update_test.BASES[item['base']][0]).read_text())
            version = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', base['images']['gateway']).group(1)
            original = json.loads((ROOT / 'releases' / (version + '.json')).read_text())
            self.assertEqual(item['legacy_tag'], 'v' + version)
            self.assertEqual(base['source']['delivery'], original['source']['delivery'])
            self.assertEqual(item['runner'], {'amd64': 'ubuntu-24.04', 'arm64': 'ubuntu-24.04-arm'}[item['arch']])

    def test_schema_ten_refuses_older_schema_rollback_without_changing_any_installation_files(self):
        for filename, _ in application_update_test.BASES.values():
            base = json.loads((ROOT / 'releases' / filename).read_text())
            selected = application_update_test.compatible(base, self.candidate())
            if base['migrations'] == selected['migrations']:
                continue  # Same-schema rollback is exercised on native hosts for every 0.1.7 baseline.
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

    def test_nested_helper_failure_reports_locations_without_private_values(self):
        owner = Mock()
        owner.json.return_value = {'node': {'title': 'private changed title', 'bodyMarkdown': 'private body'}}
        fixture = {'path': '/private-investigation', 'node': 'private-node',
                   'title': 'private expected title', 'body': 'private body'}
        try:
            application_update_test.integration.verify_file_report_smoke(owner, fixture, restored=True)
        except AssertionError as error:
            locations = application_update_test.failure_locations(error)
        else:
            self.fail('Changed fixture content must fail the unchanged helper assertion.')
        self.assertEqual([item['function'] for item in locations], ['verify_file_report_smoke', 'require'])
        self.assertTrue(all(item['path'] == 'tools/integration.py' and isinstance(item['line'], int) for item in locations))
        self.assertTrue(all(set(item) == {'path', 'line', 'function'} for item in locations))
        self.assertNotIn('private', json.dumps(locations))

if __name__ == '__main__': unittest.main()
