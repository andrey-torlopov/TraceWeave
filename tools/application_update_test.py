#!/usr/bin/env python3
"""Anonymous native application update on fresh, marked synthetic installations."""
from __future__ import annotations
import argparse
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import control, integration
from tools import published_update_test as previous
from tools.update_integration import prepare_batch, apply_prepared_and_edit
require = integration.require
TARGET_VERSION = '0.1.7'
TARGET_SCHEMA = 10
BASES = {'original': ('0.1.0.json', '0.1.0'), 'previous': ('0.1.1.json', '0.1.1'),
         'retained': ('0.1.3-update.json', '0.1.3'), 'full': ('0.1.3.json', '0.1.3'),
         'retained-v011': ('0.1.3-update-from-0.1.1.json', '0.1.3'),
         'v014-full': ('0.1.4.json', '0.1.4'),
         'v014-infra-v010': ('0.1.4-update-infra-0.1.0.json', '0.1.4'),
         'v014-infra-v011': ('0.1.4-update-infra-0.1.1.json', '0.1.4'),
         'v014-infra-v013': ('0.1.4-update-infra-0.1.3.json', '0.1.4'),
         'v016-full': ('0.1.6.json', '0.1.6'),
         'v016-infra-v010': ('0.1.6-update-infra-0.1.0.json', '0.1.6'),
         'v016-infra-v011': ('0.1.6-update-infra-0.1.1.json', '0.1.6'),
         'v016-infra-v013': ('0.1.6-update-infra-0.1.3.json', '0.1.6'),
         'v016-infra-v014': ('0.1.6-update-infra-0.1.4.json', '0.1.6')}
CHECKS = {'anonymous_native_provenance', 'published_previous_bootstrap',
          'guided_automatic_backup_migration', 'graph_settings_frontend_asset', 'old_pending_relation_exact_replay',
          'parallel_four_directions_and_isolated_deletion', 'files_and_reports_after_update', 'evidence_type_existing_and_new', 'repeat_bootstrap',
          'rollback_matches_migration_history', 'backup_restore_new_volumes', 'safety_backup_restores_new_schema',
          'marked_cleanup_retains_volumes'}


def compatible(base, candidate):
    previous.published_manifest(candidate, TARGET_VERSION)
    control.validate_manifest(base)
    require(base['backendVersion'] == base['frontendVersion'] and base['backendVersion'] in ['0.1.0', '0.1.1', '0.1.3', '0.1.4', '0.1.6'], 'Expected previous application pair.')
    require(len(base['migrations']) in [6, 7, 9] and len(candidate['migrations']) == TARGET_SCHEMA and
            candidate['migrations'][:len(base['migrations'])] == base['migrations'], 'Existing migration history must be preserved.')
    feature_migrations = [{'version': version, 'sha256': hashlib.sha256((ROOT / 'contracts/migrations' / name).read_bytes()).hexdigest()}
                          for version, name in [(8, '0008-file-attachments.sql'), (9, '0009-readable-report.sql'), (10, '0010-evidence-node-type.sql')]]
    require(candidate['migrations'][7:] == feature_migrations, 'Candidate feature migrations differ from the harness.')
    result = copy.deepcopy(candidate)
    for key in ['gateway', 'postgres']:
        result['images'][key] = base['images'][key]
    for key in ['delivery', 'deliveryDiffHash']:
        result['source'][key] = base['source'][key]
    result['source']['tools'] = candidate['source']['delivery']
    result['source']['toolsDiffHash'] = candidate['source']['deliveryDiffHash']
    result['toolsUpgrade'] = {'from': base['images']['tools'], 'to': candidate['images']['tools']}
    result['validation'] = 'Published ' + TARGET_VERSION + ' applications and tools with retained gateway/database; native application-update acceptance required.'
    control.validate_update(base, result)
    return result


def compatible_name(base):
    gateway = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', base['images']['gateway']).group(1)
    tools = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', base['images']['tools']).group(1)
    # Retained gateways can now coexist with newer tools; their exact from-images differ.
    prefix = '-update-from-' + base['releaseId'] if tools != gateway else '-update'
    return TARGET_VERSION + prefix + '-infra-' + gateway + '.json'


def pull_images(base, selected, arch):
    directory = Path(os.environ['DOCKER_CONFIG'])
    require(directory.is_dir() and not directory.is_symlink() and not list(directory.iterdir()), 'Fresh anonymous Docker configuration required.')
    native = previous.command('docker', 'info', '--format', '{{.Architecture}}')
    require({'x86_64': 'amd64', 'aarch64': 'arm64'}.get(native, native) == arch, 'Native runner architecture differs.')
    observed = {}
    import subprocess
    for release in [base, selected]:
        for key, reference in release['images'].items():
            if reference in observed: continue
            subprocess.run(['docker', 'pull', reference], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            image = json.loads(previous.command('docker', 'image', 'inspect', reference))[0]
            require(image['Os'] == 'linux' and image['Architecture'] == arch, 'Pulled image architecture differs.')
            if key != 'postgres':
                version = re.search(r':([0-9]+\.[0-9]+\.[0-9]+)@sha256:', reference).group(1)
                origin = key if key in ['backend', 'frontend'] or (key == 'tools' and 'tools' in release['source']) else 'delivery'
                repository = 'TraceWeave' + {'backend': 'Backend', 'frontend': 'Frontend'}.get(key, '')
                expected = {'org.opencontainers.image.version': version, 'org.opencontainers.image.ref.name': 'v' + version,
                            'org.opencontainers.image.revision': release['source'][origin],
                            'org.opencontainers.image.source': 'https://github.com/andrey-torlopov/' + repository}
                require(all((image['Config']['Labels'] or {}).get(label) == value for label, value in expected.items()), 'OCI provenance differs.')
            observed[reference] = {'imageId': image['Id'], 'platform': 'linux/' + arch}
    require(not list(directory.iterdir()), 'Anonymous pulls acquired credentials.')
    return observed


def guided_candidate(runtime, directory, git, revision, candidate_path):
    previous.checked_source(git, directory, revision)
    require(integration.ROOT == directory and Path.cwd() == directory and shutil.which('python3') is None,
            'Guided candidate must use the same installation with no host Python.')
    import subprocess
    log = runtime / ('integration-guided-schema-' + integration.uid() + '.log')
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        result = subprocess.run([str(directory / 'bootstrap.sh'), '--yes', '--release', str(candidate_path)],
                                cwd=directory, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
    require(result.returncode == 0, 'Guided candidate failed; private diagnostics remain on runner.')
    return log.read_text()


def relation_regression(owner):
    path = '/api/v1/investigations/' + owner.create('Parallel published relations')['id']
    graph = owner.json('GET', path + '/graph')
    type_id = next(item['id'] for item in graph['nodeTypes'] if item['code'] == 'note')
    source, target = sorted([integration.uid(), integration.uid()])
    items = []
    for directed, reverse, both in [(False, False, False), (True, False, False), (True, True, False), (True, False, True), (True, False, True)]:
        item = {'id': integration.uid(), 'sourceNodeId': target if reverse else source, 'targetNodeId': source if reverse else target,
                'relationType': 'related_to', 'directed': directed, 'label': 'Published parallel', 'assessment': 'unreviewed', 'noteMarkdown': '', 'confidence': None}
        if both: item['bidirectional'] = True
        items.append(item)
    owner.commands(path, [{'kind': 'node.create', 'node': {'id': node, 'typeId': type_id, 'title': 'Synthetic endpoint'},
                          'position': {'x': index * 420, 'y': 0}} for index, node in enumerate([source, target])] +
                         [{'kind': 'relation.create', 'relation': item} for item in items])
    saved = owner.json('GET', path + '/graph')
    require(len(saved['relations']) == 5, 'Parallel relations were collapsed.')
    for item in items:
        current = owner.json('GET', path + '/relations/' + item['id'])['relation']
        require(all(current[key] == value for key, value in item.items()) and current['bidirectional'] == item.get('bidirectional', False), 'Direction or identity differs.')
    owner.commands(path, [{'kind': 'elements.trash', 'nodeIds': [], 'relationIds': [items[-1]['id']], 'groupMode': 'group_only'}])
    require({item['id'] for item in owner.json('GET', path + '/graph')['relations']} == {item['id'] for item in items[:-1]}, 'Deleting one parallel relation changed another.')
    integration.node_deletion_smoke(owner)


def preserved_after_restore(owner, fixture, account):
    # Specification 21.4 requires restored backups to revoke every old session.
    session = owner.json('GET', '/api/v1/session')
    require(session['authenticated'] is False and session['user'] is None, 'Restore did not revoke the old session.')
    owner.login()
    require(owner.owner == account, 'Restore changed the original account identity.')
    previous.preserved(owner, fixture, owner.cookie, owner.csrf, account)


def failure_locations(error):
    """Public diagnostics identify assertions without response values or locals."""
    allowed = {ROOT / 'tools' / name for name in ['application_update_test.py', 'integration.py']}
    locations = []
    trace = error.__traceback__
    while trace is not None:
        path = Path(trace.tb_frame.f_code.co_filename).resolve()
        if path in allowed:
            locations.append({'path': path.relative_to(ROOT).as_posix(), 'line': trace.tb_lineno,
                              'function': trace.tb_frame.f_code.co_name})
        trace = trace.tb_next
    return locations


def verify(args, evidence):
    candidate = previous.published_manifest(previous.strict(Path(args.candidate).read_bytes()), TARGET_VERSION)
    filename = BASES[args.base][0]
    base = previous.strict((ROOT / 'releases' / filename).read_bytes())
    selected = compatible(base, candidate)
    expected_name = compatible_name(base)
    checked = selected
    require(hashlib.sha256((ROOT / 'contracts/openapi.yaml').read_bytes()).hexdigest() == candidate['contractHash'], 'Harness contract differs.')
    git = str(Path(shutil.which('git')).resolve())
    revision = previous.command(git, '-C', str(ROOT), 'rev-parse', 'HEAD')
    previous.checked_source(git, ROOT, revision)
    evidence.update(baseRelease=base['releaseId'], source={'base': base['source'], 'target': selected['source']}, guidedOperatorRevision=revision)
    evidence['activeCheck'] = 'anonymous_native_provenance'
    evidence['images'] = pull_images(base, selected, args.arch)
    evidence['checks']['anonymous_native_provenance'] = 'passed'
    runtime, legacy = Path(args.runtime), Path(args.legacy)
    require(not runtime.exists() and not runtime.is_symlink(), 'Fresh runtime required.')
    runtime.mkdir(mode=0o700, parents=True)
    previous.write_json(runtime / 'synthetic-installation.json', {'synthetic': True, 'email': integration.EMAIL})
    origin = 'http://127.0.0.1:' + str(args.port)
    operator = None
    before_config = None
    try:
        # The old controller only bootstraps its own release. The current checked
        # controller below owns the explicit schema/tools transition.
        operator = previous.legacy_operator(legacy, runtime, base, base)
        base_path = runtime / 'previous.json'
        candidate_path = runtime / 'candidate.json'
        previous.write_json(candidate_path, candidate)
        previous.write_json(runtime / expected_name, selected)
        previous.write_json(Path(args.output) / expected_name, selected)
        previous.write_json(base_path, base)
        evidence['activeCheck'] = 'published_previous_bootstrap'
        integration.cli(runtime, 'bootstrap', '--release', str(base_path), '--origin', origin, '--email', integration.EMAIL,
                        '--name', 'Synthetic schema owner', password=integration.PASSWORD)
        owner = integration.Client(origin); owner.login()
        fixture = previous.seed(owner)
        cookie, csrf, account = owner.cookie, owner.csrf, owner.owner
        path = fixture[0]
        prepared = prepare_batch(owner, path, 'application ' + TARGET_VERSION)
        body = json.loads(prepared.raw)
        body['commands'].append({'kind': 'relation.create', 'relation': {'id': integration.uid(), 'sourceNodeId': fixture[1],
            'targetNodeId': prepared.node_id, 'relationType': 'related_to', 'directed': True, 'label': 'Legacy pending relation',
            'assessment': 'unreviewed', 'noteMarkdown': '', 'confidence': None}})
        prepared = replace(prepared, raw=json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode())
        html = owner.request('GET', '/')[0].decode()
        entry = re.search(r'src="(/assets/[^" ]+\.js)"', html).group(1)
        old_asset = owner.request('GET', entry)[0]
        before_config = operator.load_config(); before = previous.identities(operator, before_config, base)
        evidence['checks']['published_previous_bootstrap'] = 'passed'
        evidence['activeCheck'] = 'guided_automatic_backup_migration'
        previous.command(git, '-C', str(legacy), 'fetch', '--no-tags', '--update-shallow', str(ROOT), revision)
        previous.checkout_source(git, legacy, revision)
        output = guided_candidate(runtime, legacy, git, revision, candidate_path)
        explanation = 'миграции не нужны' if base['migrations'] == selected['migrations'] else 'схема базы обновится автоматически'
        require(explanation in output, 'Bootstrap did not explain the actual migration requirement.')
        require(operator.current() == checked and operator.load_config() == before_config, 'Bootstrap selected wrong pair or changed configuration.')
        after = previous.identities(operator, before_config, selected)
        require(before['db'] == after['db'] and before['gateway'] == after['gateway'], 'Migration restarted retained infrastructure.')
        require(all(before[key][0] != after[key][0] for key in ['backend', 'frontend']), 'Application containers were not replaced.')
        previous.preserved(owner, fixture, cookie, csrf, account)
        require(owner.request('GET', entry)[0] == old_asset, 'Old pending frontend asset disappeared.')
        state = operator.read_json(runtime / 'operation.json')
        require(state['phase'] == 'ready' and state.get('backup'), 'No pre-update backup recorded.')
        backup_name = state['backup']; backup = operator.read_json(runtime / 'backups' / backup_name / 'manifest.json')
        require(backup['release'] == base and backup['migrations'] == base['migrations'], 'Backup is not the old schema.')
        require(any(item['sha256'] == hashlib.sha256(fixture[3]).hexdigest() for item in backup['databaseOriginals']), 'Backup omitted original bytes.')
        operator.compose('run', '--rm', '-T', '--no-deps', 'ops', 'verify-backup', backup_name, config=before_config, release=selected, capture=True)
        evidence['checks']['guided_automatic_backup_migration'] = 'passed'
        evidence['activeCheck'] = 'graph_settings_frontend_asset'
        require(owner.json('GET', '/release.json')['frontendVersion'] == TARGET_VERSION, 'Updated frontend version differs.')
        current_html = owner.request('GET', '/')[0].decode()
        current_entry = re.search(r'src="(/assets/[^" ]+\.js)"', current_html).group(1)
        # A catalog-only release can ship byte-identical frontend JS; release metadata
        # and replaced container IDs above verify the selected frontend version.
        current_asset = owner.request('GET', current_entry)[0].decode('utf-8')
        require(all(text in current_asset for text in ['Настройки графа', 'Уменьшение карточки до узла, раз', 'Восстановлено текущее значение']), 'Published frontend omits graph settings.')
        evidence['checks']['graph_settings_frontend_asset'] = 'passed'
        evidence['activeCheck'] = 'old_pending_relation_exact_replay'
        apply_prepared_and_edit(owner, path, prepared)
        require(owner.json('GET', path + '/relations/' + body['commands'][-1]['relation']['id'])['relation']['bidirectional'] is False, 'Legacy pending relation changed direction.')
        evidence['checks']['old_pending_relation_exact_replay'] = 'passed'
        evidence['activeCheck'] = 'parallel_four_directions_and_isolated_deletion'
        relation_regression(owner)
        evidence['checks']['parallel_four_directions_and_isolated_deletion'] = 'passed'
        evidence['activeCheck'] = 'files_and_reports_after_update'
        file_fixture = integration.file_report_smoke(owner)
        evidence['checks']['files_and_reports_after_update'] = 'passed'
        evidence['activeCheck'] = 'evidence_type_existing_and_new'
        integration.evidence_type_smoke(owner, path=path)
        integration.evidence_type_smoke(owner)
        evidence['checks']['evidence_type_existing_and_new'] = 'passed'
        evidence['activeCheck'] = 'repeat_bootstrap'
        snapshots = {item['id']: owner.json('GET', '/api/v1/investigations/' + item['id'] + '/graph') for item in owner.json('GET', '/api/v1/investigations')['items']}
        backups = set((runtime / 'backups').iterdir())
        guided_candidate(runtime, legacy, git, revision, candidate_path)
        require(previous.identities(operator, before_config, selected) == after and set((runtime / 'backups').iterdir()) == backups, 'Repeated bootstrap reran update.')
        for identifier, graph in snapshots.items(): require(owner.json('GET', '/api/v1/investigations/' + identifier + '/graph') == graph, 'Repeated bootstrap changed data.')
        evidence['checks']['repeat_bootstrap'] = 'passed'
        evidence['activeCheck'] = 'rollback_matches_migration_history'
        if base['migrations'] != selected['migrations']:
            integration.cli(runtime, 'rollback', '--yes', expect_success=False)
            require(operator.current() == checked and previous.identities(operator, before_config, selected) == after, 'Refused rollback changed running services.')
        else:
            integration.cli(runtime, 'rollback', '--yes')
            require(operator.current() == base, 'Same-schema image rollback failed.')
            previous.preserved(owner, fixture, cookie, csrf, account)
            for identifier, graph in snapshots.items(): require(owner.json('GET', '/api/v1/investigations/' + identifier + '/graph') == graph, 'Image rollback changed data.')
            integration.cli(runtime, 'update', '--release', str(runtime / expected_name), '--yes')
            require(operator.current() == checked, 'Reapplying the verified application pair failed.')
            previous.preserved(owner, fixture, cookie, csrf, account)
        evidence['checks']['rollback_matches_migration_history'] = 'passed'
        evidence['activeCheck'] = 'backup_restore_new_volumes'
        integration.cli(runtime, 'restore', '--backup', backup_name, '--yes')
        restored = operator.load_config()
        require(operator.current() == base and restored['volumes']['database'] != before_config['volumes']['database'] and
                restored['volumes']['files'] != before_config['volumes']['files'], 'Schema restore did not use new volumes.')
        preserved_after_restore(owner, fixture, account)
        require(owner.json('GET', '/release.json')['releaseId'] == base['releaseId'], 'Restored frontend differs.')
        state = operator.read_json(runtime / 'operation.json')
        require(state['phase'] == 'ready' and state.get('safetyBackup'), 'Restore omitted post-upgrade safety backup.')
        for volume in before_config['volumes'].values(): previous.command('docker', 'volume', 'inspect', volume)
        evidence['checks']['backup_restore_new_volumes'] = 'passed'
        evidence['activeCheck'] = 'safety_backup_restores_new_schema'
        safety_name = state['safetyBackup']
        safety = operator.read_json(runtime / 'backups' / safety_name / 'manifest.json')
        require(safety['release'] == selected and safety['migrations'] == selected['migrations'], 'Safety backup lost the new schema/tools selection.')
        for data in file_fixture['originals'].values():
            require(any(item['path'].startswith('files/') and item['bytes'] == len(data) and
                        item['sha256'] == hashlib.sha256(data).hexdigest() for item in safety['databaseOriginals']),
                    'Safety backup omitted a new file original.')
        integration.cli(runtime, 'restore', '--backup', safety_name, '--yes')
        recovered = operator.load_config()
        require(operator.current() == selected and all(recovered['volumes'][key] != restored['volumes'][key] for key in ['database', 'files']),
                'Safety restore did not recover the new release into new volumes.')
        preserved_after_restore(owner, fixture, account)
        integration.verify_file_report_smoke(owner, file_fixture, restored=True)
        for identifier, graph in snapshots.items():
            require(owner.json('GET', '/api/v1/investigations/' + identifier + '/graph') == graph, 'Safety restore changed post-update data.')
        require(owner.json('GET', '/release.json')['releaseId'] == TARGET_VERSION, 'Safety restore selected the wrong frontend.')
        for config in [before_config, restored]:
            for volume in config['volumes'].values(): previous.command('docker', 'volume', 'inspect', volume)
        evidence['checks']['safety_backup_restores_new_schema'] = 'passed'
    finally:
        if operator is not None and (runtime / 'installation.json').is_file():
            require(previous.strict((runtime / 'synthetic-installation.json').read_bytes()) == {'synthetic': True, 'email': integration.EMAIL}, 'Unmarked cleanup refused.')
            integration.cli(runtime, 'stop')
            for volume in operator.load_config()['volumes'].values(): previous.command('docker', 'volume', 'inspect', volume)
            evidence['checks']['marked_cleanup_retains_volumes'] = 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True); parser.add_argument('--legacy', required=True)
    parser.add_argument('--runtime', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--base', choices=list(BASES), required=True)
    parser.add_argument('--arch', choices=['amd64', 'arm64'], required=True); parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    require(1024 <= args.port <= 65535, 'Unprivileged loopback port required.')
    for key in ['candidate', 'legacy', 'runtime', 'output']: setattr(args, key, str(Path(getattr(args, key)).absolute()))
    for key in ['DOCKER_HOST', 'DOCKER_CONTEXT']: os.environ.pop(key, None)
    output = Path(args.output)
    require(not output.exists() and not output.is_symlink(), 'Fresh public evidence directory required.')
    output.mkdir(mode=0o700, parents=True)
    evidence = {'formatVersion': 1, 'baseRelease': BASES[args.base][1], 'baseInfrastructure': args.base, 'targetRelease': TARGET_VERSION,
                'nativePlatform': 'linux/' + args.arch, 'anonymousPull': True, 'checks': {}, 'conclusion': 'failed'}
    if os.environ.get('GITHUB_REPOSITORY') and os.environ.get('GITHUB_RUN_ID'):
        evidence['runURL'] = 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
    try:
        verify(args, evidence)
        require(set(evidence['checks']) == CHECKS and all(value == 'passed' for value in evidence['checks'].values()), 'Incomplete application update acceptance.')
        evidence['conclusion'] = 'passed'; evidence.pop('activeCheck', None)
    except Exception as error:
        evidence['errorClass'] = type(error).__name__
        locations = failure_locations(error)
        if locations:
            evidence['errorLocations'] = locations
            evidence['errorLocation'] = next((location for location in reversed(locations)
                                              if location['function'] != 'require'), locations[-1])
        print('FAIL application update: ' + evidence.get('activeCheck', 'preflight') + ' (' + type(error).__name__ + '); private diagnostics remain on runner.', file=sys.stderr)
    finally: previous.write_json(output / 'verification.json', evidence)
    print('Published application update ' + args.base + ' linux/' + args.arch + ': ' + evidence['conclusion'])
    return 0 if evidence['conclusion'] == 'passed' else 1

if __name__ == '__main__': raise SystemExit(main())
