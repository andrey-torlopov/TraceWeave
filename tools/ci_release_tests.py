#!/usr/bin/env python3
"""Derive component-only CI releases from two real builds of one locked source pair.

These are successive synthetic versions of current code. They do not represent
compatibility with a previously published release or fabricate registry digests.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import control
from update_integration import prepare_batch, apply_prepared_and_edit


def component_releases(base, following):
    base = control.validate_manifest(copy.deepcopy(base))
    following = control.validate_manifest(copy.deepcopy(following))
    if base.get('source') != following.get('source'):
        raise control.Failure('Synthetic CI versions must use the same exact source pair.')
    source = base.get('source', {})
    if any(not re.fullmatch('[a-f0-9]{40}', source.get(key, '')) for key in ['backend', 'frontend']):
        raise control.Failure('Both actual source commits must be recorded.')
    for key in ['contractHash', 'backendContractHash', 'supportedClientContractHashes', 'migrations', 'postgresMajor', 'platforms']:
        if base.get(key) != following.get(key):
            raise control.Failure('Synthetic current-code versions differ in '+key+'.')
    for key in ['backend', 'frontend']:
        if base['images'][key] == following['images'][key]:
            raise control.Failure('A separately built '+key+' image is required.')

    frontend = copy.deepcopy(base)
    frontend['releaseId'] = 'ci-frontend-only'
    frontend['images']['frontend'] = following['images']['frontend']
    for key in ['frontendReleaseId', 'frontendVersion']:
        frontend[key] = following[key]
    backend = copy.deepcopy(frontend)
    backend['releaseId'] = 'ci-backend-only'
    backend['images']['backend'] = following['images']['backend']
    backend['backendVersion'] = following['backendVersion']
    for value in [frontend, backend]:
        value['validation'] = 'synthetic successive versions of the same locked source pair; not a previous published release'
        control.validate_manifest(value)
    control.validate_update(base, frontend)
    control.validate_update(frontend, backend)
    return frontend, backend


class ComponentReleaseTests(unittest.TestCase):
    def setUp(self):
        # Unit fixtures only; production manifests always come from build-source.
        self.base = {
            'formatVersion': 1, 'releaseId': 'unit-base', 'frontendReleaseId': 'unit-base',
            'frontendVersion': 'unit-base', 'backendVersion': 'unit-base', 'postgresMajor': 18,
            'images': {key: 'sha256:'+format(number, '064x') for number, key in enumerate(
                ['backend', 'frontend', 'postgres', 'gateway', 'tools'], 1)},
            'contractHash': 'c'*64, 'backendContractHash': 'c'*64,
            'supportedClientContractHashes': ['c'*64],
            'migrations': [{'version': 1, 'sha256': 'd'*64}], 'platforms': ['linux/amd64'],
            'source': {'backend': 'a'*40, 'frontend': 'b'*40},
        }
        self.following = copy.deepcopy(self.base)
        self.following.update(releaseId='unit-next', frontendReleaseId='unit-next',
                              frontendVersion='unit-next', backendVersion='unit-next')
        self.following['images'].update(backend='sha256:'+'e'*64, frontend='sha256:'+'f'*64,
                                        gateway='sha256:'+'8'*64, tools='sha256:'+'9'*64)

    def test_only_requested_component_changes_and_metadata_matches_actual_image(self):
        frontend, backend = component_releases(self.base, self.following)
        self.assertEqual(control.changes(self.base, frontend), ['frontend'])
        self.assertEqual(control.changes(frontend, backend), ['backend'])
        self.assertEqual(frontend['frontendReleaseId'], self.following['frontendReleaseId'])
        self.assertEqual(backend['backendVersion'], self.following['backendVersion'])
        for key in ['postgres', 'gateway', 'tools']:
            self.assertEqual(backend['images'][key], self.base['images'][key])
        self.assertEqual(self.base['releaseId'], 'unit-base')
        self.assertEqual(frontend['source'], self.base['source'])

    def test_different_source_pair_is_not_misrepresented_as_current_code(self):
        self.following['source']['backend'] = '0'*40
        with self.assertRaises(control.Failure):
            component_releases(self.base, self.following)

    def test_missing_exact_source_commit_is_rejected(self):
        self.base.pop('source'); self.following.pop('source')
        with self.assertRaises(control.Failure):
            component_releases(self.base, self.following)

    def test_unchanged_component_cannot_skip_real_update(self):
        for key in ['backend', 'frontend']:
            with self.subTest(component=key):
                following = copy.deepcopy(self.following)
                following['images'][key] = self.base['images'][key]
                with self.assertRaises(control.Failure):
                    component_releases(self.base, following)

    def test_schema_and_contract_change_require_a_real_compatibility_fixture(self):
        for key, value in [('backendContractHash', '0'*64),
                           ('migrations', self.base['migrations']+[{'version': 2, 'sha256': '0'*64}])]:
            with self.subTest(field=key):
                following = copy.deepcopy(self.following); following[key] = value
                with self.assertRaises(control.Failure):
                    component_releases(self.base, following)

    def test_mutable_image_tag_is_rejected(self):
        self.following['images']['frontend'] = 'traceweave/frontend:unit-next'
        with self.assertRaises(control.Failure):
            component_releases(self.base, self.following)

    def test_isolated_cli_writes_valid_manifests_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='traceweave-ci-manifests-') as temporary:
            directory = Path(temporary)
            base, following = directory/'base.json', directory/'next.json'
            base.write_text(json.dumps(self.base)); following.write_text(json.dumps(self.following))
            command = [sys.executable, '-I', str(Path(__file__).resolve()), '--base', str(base),
                       '--next', str(following), '--output-dir', str(directory/'out')]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = [directory/'out'/name for name in ['ci-frontend-only.local.json', 'ci-backend-only.local.json']]
            snapshots = [path.read_bytes() for path in outputs]
            for path in outputs:
                control.validate_manifest(json.loads(path.read_bytes()))
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            refused = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(refused.returncode, 1)
            self.assertIn('refusing to replace rollback identities', refused.stderr)
            self.assertEqual([path.read_bytes() for path in outputs], snapshots)

    def test_pending_command_reuses_exact_bytes_and_original_identity_contract_headers(self):
        class ClientFixture:
            owner = '30000000-0000-4000-8000-000000000001'
            contract = 'c'*64
            cookie = 'rg_session=synthetic-unit-session'
            csrf = 'synthetic-unit-csrf'
            origin = 'http://127.0.0.1:18080'

            def __init__(self):
                self.sent = []; self.title = None

            def json(self, method, path, **keywords):
                if method == 'POST':
                    self.sent.append((keywords['raw'], keywords['headers']))
                    batch = json.loads(keywords['raw'])
                    if len(self.sent) == 1:
                        self.title = batch['commands'][0]['node']['title']
                    return {'operationId': batch['operationId'], 'revision': batch['baseRevision']+1,
                            'replayed': len(self.sent) > 1}
                if path.endswith('/graph'):
                    return {'nodeTypes': [{'id': '30000000-0000-4000-8000-000000000002', 'code': 'note'}]}
                if '/nodes/' in path:
                    return {'node': {'title': self.title}}
                return {'revision': 2}

            def commands(self, path, commands):
                self.title = commands[0]['changes']['title']

        client = ClientFixture()
        prepared = prepare_batch(client, '/api/v1/investigations/unit-fixture', 'frontend')
        original = dict(prepared.headers)
        client.contract = '0'*64  # A release probe must not rewrite an already prepared request.
        apply_prepared_and_edit(client, '/api/v1/investigations/unit-fixture', prepared)
        self.assertEqual(client.sent, [(prepared.raw, original), (prepared.raw, original)])
        self.assertEqual(original['X-TraceWeave-Account-ID'], client.owner)
        self.assertEqual(original['X-TraceWeave-Client-Contract'], 'c'*64)
        self.assertEqual(json.loads(prepared.raw)['baseRevision'], 2)
        self.assertTrue(client.title.startswith('Edited after update '))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base'); parser.add_argument('--next', dest='following')
    parser.add_argument('--output-dir', default=str(control.ROOT/'releases'))
    parser.add_argument('--self-test', action='store_true')
    arguments = parser.parse_args()
    if arguments.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComponentReleaseTests))
        return 0 if result.wasSuccessful() else 1
    if not arguments.base or not arguments.following:
        parser.error('--base and --next must reference real build-source manifests.')
    frontend, backend = component_releases(control.read_json(Path(arguments.base).resolve()),
                                           control.read_json(Path(arguments.following).resolve()))
    directory = Path(arguments.output_dir).resolve()
    outputs = [(directory/(value['releaseId']+'.local.json'), value) for value in [frontend, backend]]
    if any(path.exists() or path.is_symlink() for path, _ in outputs):
        raise control.Failure('CI component manifests already exist; refusing to replace rollback identities.')
    directory.mkdir(parents=True, exist_ok=True)
    for path, value in outputs:
        control.write_json(path, value, 0o644)
        print('Synthetic current-code component release: '+str(path))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except control.Failure as error:
        print('CI release refusal: '+str(error), file=sys.stderr)
        sys.exit(1)
