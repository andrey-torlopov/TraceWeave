#!/usr/bin/env python3
"""Verify published 0.1.0 -> 0.1.1 and rollback using the unmodified 0.1.0 operator.

Only fresh, marked synthetic installations are accepted. Public artifacts contain
image/source provenance and check outcomes; private runtime logs stay on the host.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import control, integration
from tools.update_integration import apply_prepared_and_edit, prepare_batch

BASE_URL = 'https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/0.1.0.json'
EMPTY_HASH = hashlib.sha256(b'').hexdigest()
PLATFORMS = ['linux/amd64', 'linux/arm64']
LIMIT = 60000
require = integration.require


def strict(raw):
    # Load the shared parser lazily, so --self-test also works without optional
    # OpenAPI packages. Its duplicate-key and finite-number rules apply in CI.
    from tools.validate_contracts import strict_json
    require(len(raw) <= LIMIT, 'Manifest exceeds the verification bound.')
    return strict_json(raw)


def published_manifest(value, version):
    control.validate_manifest(value)
    require(value['releaseId'] == version, 'Unexpected published release.')
    require(value['frontendReleaseId'] == value['frontendVersion'] == value['backendVersion'] == version,
            'Full publication must use the expected component versions.')
    require(set(value['images']) == {'backend', 'frontend', 'gateway', 'tools', 'postgres'},
            'Unexpected image selection.')
    require(value['platforms'] == PLATFORMS, 'Both native Linux platforms are required.')
    source = value['source']
    require(set(source) == {key + suffix for key in ['backend', 'frontend', 'delivery']
                           for suffix in ['', 'DiffHash']}, 'Incomplete source provenance.')
    for key in ['backend', 'frontend', 'delivery']:
        require(re.fullmatch(r'[a-f0-9]{40}', source[key]) is not None,
                'A clean published source revision is required.')
        require(source[key + 'DiffHash'] == EMPTY_HASH, 'Published source must be clean.')
    for key in ['backend', 'frontend', 'gateway', 'tools']:
        expected = r'docker\.io/andreytorlopov/traceweave-' + key + ':' + re.escape(version) + r'@sha256:[a-f0-9]{64}'
        require(re.fullmatch(expected, value['images'][key]) is not None,
                'A versioned public registry digest is required.')
    require(value['images']['postgres'] == control.PG_IMAGE, 'Unexpected database image.')
    require(value['backendContractHash'] == value['contractHash'], 'Backend/client contract differs.')
    return value


def compatible_manifest(base, candidate):
    published_manifest(base, '0.1.0')
    published_manifest(candidate, '0.1.1')
    # An image rollback is meaningful only with exactly the original schema and
    # client contract. Do not silently widen this test to a schema migration.
    for key in ['contractHash', 'backendContractHash', 'supportedClientContractHashes',
                'migrations', 'postgresMajor', 'platforms']:
        require(base[key] == candidate[key], 'Published update changes rollback compatibility metadata.')
    result = copy.deepcopy(base)
    for key in ['releaseId', 'frontendReleaseId', 'frontendVersion', 'backendVersion']:
        result[key] = candidate[key]
    for key in ['backend', 'frontend']:
        result['images'][key] = candidate['images'][key]
        result['source'][key] = candidate['source'][key]
        result['source'][key + 'DiffHash'] = candidate['source'][key + 'DiffHash']
    result['validation'] = ('Published backend/frontend 0.1.1 with retained gateway/tools/database 0.1.0; '
                            'acceptance requires a passed published-update verification.json on both native platforms.')
    control.validate_update(base, control.validate_manifest(result))
    require(set(control.changes(base, result)) == {'backend', 'frontend'},
            'Exactly backend and frontend must change.')
    return result


def write_json(path, value):
    with path.open('w') as out:
        os.chmod(path, 0o600)
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write('\n')


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def pull_and_inspect(base, selected, arch):
    directory = Path(os.environ['DOCKER_CONFIG'])
    require(directory.is_dir() and not directory.is_symlink() and not list(directory.iterdir()),
            'Native pulls require a fresh empty Docker credential directory.')
    native = command('docker', 'info', '--format', '{{.Architecture}}')
    native = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(native, native)
    require(native == arch, 'Runner is not the requested native architecture.')
    observed = {}
    for release in [base, selected]:
        for key, reference in release['images'].items():
            if reference in observed:
                continue
            subprocess.run(['docker', 'pull', reference], check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE)
            image = json.loads(command('docker', 'image', 'inspect', reference))[0]
            require(image['Os'] == 'linux' and image['Architecture'] == arch, 'Pulled image is not native Linux.')
            if key != 'postgres':
                origin = key if key in ['backend', 'frontend'] else 'delivery'
                version = release[key + 'Version'] if key in ['backend', 'frontend'] else '0.1.0'
                labels = image['Config']['Labels'] or {}
                repository = 'TraceWeave' + {'backend': 'Backend', 'frontend': 'Frontend'}.get(key, '')
                require(all(labels.get(label) == expected for label, expected in {
                    'org.opencontainers.image.version': version,
                    'org.opencontainers.image.ref.name': 'v' + version,
                    'org.opencontainers.image.revision': release['source'][origin],
                    'org.opencontainers.image.source': 'https://github.com/andrey-torlopov/' + repository,
                }.items()), 'Published OCI provenance mismatch.')
            if key in ['backend', 'frontend']:
                filename = '/app/backend-release.json' if key == 'backend' else '/opt/traceweave/frontend-release.json'
                baked = json.loads(command('docker', 'run', '--rm', '--network', 'none', '--entrypoint',
                                           'cat', reference, filename))
                if key == 'backend':
                    require(baked['backendVersion'] == release['backendVersion'] and
                            baked['contractHash'] == release['backendContractHash'] and
                            baked['sourceRevision'] == release['source']['backend'], 'Baked backend metadata mismatch.')
                else:
                    require(baked == dict(releaseId=release['frontendReleaseId'],
                                         frontendVersion=release['frontendVersion'], contractHash=release['contractHash']),
                            'Baked frontend metadata mismatch.')
            observed[reference] = dict(imageId=image['Id'], platform='linux/' + arch)
    require(not list(directory.iterdir()), 'Anonymous verification unexpectedly acquired Docker credentials.')
    return observed


def legacy_operator(directory, runtime, base, selected):
    require(directory.is_dir() and not directory.is_symlink(), 'Legacy checkout must be a real directory.')
    require(command('git', '-C', str(directory), 'rev-parse', 'HEAD') == base['source']['delivery'],
            'Legacy checkout differs from the published 0.1.0 delivery source.')
    require(not command('git', '-C', str(directory), 'status', '--porcelain', '--untracked-files=no'),
            'Legacy tracked files must remain unmodified.')
    spec = importlib.util.spec_from_file_location('published_legacy_control', directory / 'tools/control.py')
    operator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(operator)
    operator.RUNTIME = runtime
    # The actual mutations use the old wrapper + old mounted controller in the
    # published tools image. Host imports below perform read-only observations.
    operator.validate_update(base, selected)
    binary = runtime / 'no-python-bin'
    binary.mkdir(mode=0o700)
    for utility in ['docker', 'sh', 'dirname', 'basename', 'mkdir', 'chmod', 'id']:
        executable = shutil.which(utility)
        require(executable is not None, 'Missing Docker-only wrapper utility.')
        (binary / utility).symlink_to(executable)
    os.environ['PATH'] = str(binary)
    require(shutil.which('python3') is None and shutil.which('python') is None, 'Host Python leaked onto operator PATH.')
    os.environ['TW_TOOLS_IMAGE'] = base['images']['tools']
    os.environ['TW_RUNTIME_DIR'] = str(runtime)
    integration.ROOT = directory
    os.chdir(directory)
    return operator


def identities(operator, config, release):
    result = {}
    for service in ['db', 'backend', 'frontend', 'gateway']:
        cid = operator.container(service, config, release)
        state = json.loads(command('docker', 'inspect', '--format', '{{json .State}}', cid))
        require(state['Running'], 'Expected synthetic service is not running.')
        result[service] = (cid, state['StartedAt'])
    return result


def seed(owner):
    inv = owner.create('Published update persistence ' + integration.uid())
    path = '/api/v1/investigations/' + inv['id']
    graph = owner.json('GET', path + '/graph')
    note = next(value['id'] for value in graph['nodeTypes'] if value['code'] == 'note')
    node = integration.uid()
    owner.commands(path, [{'kind': 'node.create', 'node': {'id': node, 'typeId': note,
        'title': 'Original published document', 'bodyMarkdown': 'Synthetic bytes survive upgrade and rollback.'},
        'position': {'x': 12, 'y': 34}}])
    fixture = ROOT / 'tests/fixtures/media/synthetic.txt'
    data = fixture.read_bytes()
    ticket = owner.json('POST', path + '/uploads', {'idempotencyKey': integration.uid(),
        'originalName': fixture.name, 'expectedMimeType': 'text/plain', 'expectedByteSize': len(data)}, expected=201)
    complete = owner.json('PUT', path + '/uploads/' + ticket['id'] + '/content', raw=data,
                          headers={'Content-Type': 'application/octet-stream'})
    require(complete['sha256'] == hashlib.sha256(data).hexdigest(), 'Original upload checksum differs.')
    asset = integration.uid()
    owner.commands(path, [{'kind': 'asset.register', 'uploadId': ticket['id'], 'assetId': asset,
        'metadata': {'title': 'Preserved original', 'sourceUrl': None, 'sourceAuthor': None,
                     'sourceCreatedAt': None, 'noteMarkdown': ''}},
        {'kind': 'attachment.attach', 'attachment': {'id': integration.uid(), 'nodeId': node,
            'assetId': asset, 'role': 'attachment', 'caption': None, 'sortOrder': 0}}])
    document = owner.json('GET', path + '/nodes/' + node)
    return path, node, asset, data, document


def preserved(owner, fixture, cookie, csrf, account):
    path, node, asset, data, document = fixture
    require(owner.cookie == cookie and owner.csrf == csrf and owner.owner == account,
            'The original authenticated client changed.')
    require(owner.json('GET', '/api/v1/session')['user']['id'] == account,
            'Original authenticated session is no longer valid.')
    current = owner.json('GET', path + '/nodes/' + node)
    require({key: value for key, value in current.items() if key != 'revision'} ==
            {key: value for key, value in document.items() if key != 'revision'},
            'Original document/layout/attachment changed.')
    require(owner.request('GET', path + '/assets/' + asset + '/content')[0] == data, 'Immutable original bytes changed.')


def tombstones(operator, config, release):
    # /graph exposes active objects only. Read deleted records through the old
    # published ops dependency in a read-only transaction; values stay private.
    script = """import importlib.util,json
from pathlib import Path
assert json.loads(Path('/state/synthetic-installation.json').read_text()) == {'synthetic':True,'email':'docker-owner@example.test'}
spec=importlib.util.spec_from_file_location('ops','/opt/traceweave/ops.py')
ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)
c=ops.connect()
try:
 with c.transaction():
  with c.cursor() as q:
   q.execute('SET TRANSACTION READ ONLY')
   result={}
   for table in ['nodes','relations']:
    q.execute('SELECT row_to_json(n)::text FROM '+table+" n JOIN investigations i ON i.id=n.investigation_id JOIN owners o ON o.id=i.owner_id WHERE o.email=%s AND n.deleted_at IS NOT NULL ORDER BY n.id",('docker-owner@example.test',))
    result[table]=[json.loads(row[0]) for row in q.fetchall()]
   print(json.dumps(result,separators=(',',':')))
finally:c.close()
"""
    return json.loads(operator.compose('run', '--rm', '-T', '--no-deps', '--entrypoint', 'python3', 'ops',
                                       '-c', script, config=config, release=release, capture=True))


def safe_cleanup(runtime, operator, origin):
    marker = runtime / 'synthetic-installation.json'
    if not (runtime / 'installation.json').is_file():
        return 'not_needed'
    require(not runtime.is_symlink() and strict(marker.read_bytes()) == {'synthetic': True, 'email': integration.EMAIL},
            'Unmarked installation cleanup refused.')
    config = operator.load_config()
    require(config['origin'] == origin and config['mode'] == 'local' and
            re.fullmatch(r'tw-[a-f0-9]{12}', config['installId']), 'Unexpected synthetic installation identity.')
    suffixes = dict(database='postgres', files='files', assets='assets', gatewayData='gateway-data', gatewayConfig='gateway-config')
    require(config['volumes'] == {key: config['installId'] + '-' + suffix for key, suffix in suffixes.items()},
            'Cleanup targets unexpected volumes.')
    integration.cli(runtime, 'stop')
    for volume in config['volumes'].values():
        command('docker', 'volume', 'inspect', volume)
    return 'passed'


def verify(args, evidence):
    evidence['activeCheck'] = 'published_manifest_compatibility'
    candidate = published_manifest(strict(Path(args.candidate).read_bytes()), '0.1.1')
    with urlopen(BASE_URL, timeout=30) as response:
        base = published_manifest(strict(response.read(LIMIT + 1)), '0.1.0')
    selected = compatible_manifest(base, candidate)
    contract = hashlib.sha256((ROOT / 'contracts/openapi.yaml').read_bytes()).hexdigest()
    require(contract == base['contractHash'] == selected['contractHash'], 'Harness differs from the published client contract.')
    evidence.update(source={'base': base['source'], 'candidate': candidate['source'], 'compatible': selected['source']})
    evidence['activeCheck'] = 'anonymous_native_provenance'
    evidence['images'] = pull_and_inspect(base, selected, args.arch)
    evidence['checks']['anonymous_native_provenance'] = 'passed'
    runtime = Path(args.runtime).absolute()
    require(not runtime.exists() and not runtime.is_symlink(), 'Published update test requires a fresh runtime.')
    runtime.mkdir(parents=True, mode=0o700)
    origin = 'http://127.0.0.1:' + str(args.port)
    operator = None
    try:
        write_json(runtime / 'synthetic-installation.json', {'synthetic': True, 'email': integration.EMAIL})
        operator = legacy_operator(Path(args.legacy).absolute(), runtime, base, selected)
        base_path = runtime / '0.1.0.json'
        selected_path = Path(args.output).absolute() / '0.1.1-update.json'
        write_json(base_path, base)
        write_json(selected_path, selected)
        evidence['activeCheck'] = 'published_0_1_0_bootstrap'
        integration.cli(runtime, 'bootstrap', '--release', str(base_path), '--origin', origin,
                        '--email', integration.EMAIL, '--name', 'Published synthetic owner', password=integration.PASSWORD)
        require(operator.current() == base, 'Bootstrap did not install published 0.1.0.')
        owner = integration.Client(origin)
        owner.login()
        fixture = seed(owner)
        cookie, csrf, account = owner.cookie, owner.csrf, owner.owner
        path = fixture[0]
        prepared = prepare_batch(owner, path, 'published 0.1.1')
        html = owner.request('GET', '/')[0].decode()
        entry = re.search(r'src="(/assets/[^" ]+\.js)"', html)
        require(entry is not None, 'Published Vite entry asset is missing.')
        old_asset = owner.request('GET', entry.group(1))[0]
        config = operator.load_config()
        before = identities(operator, config, base)
        evidence['checks']['published_0_1_0_bootstrap'] = 'passed'
        evidence['activeCheck'] = 'upgrade_data_session_database_assets_backup'
        integration.cli(runtime, 'update', '--release', str(selected_path), '--yes')
        require(operator.current() == selected and operator.load_config() == config,
                'Update changed installation configuration or accepted the wrong manifest.')
        after = identities(operator, config, selected)
        require(before['db'] == after['db'] and before['gateway'] == after['gateway'],
                'Update restarted the database or gateway.')
        require(all(before[key][0] != after[key][0] for key in ['backend', 'frontend']),
                'Update did not replace both application containers.')
        preserved(owner, fixture, cookie, csrf, account)
        require(owner.request('GET', entry.group(1))[0] == old_asset, 'Old pending client asset is unavailable after update.')
        require(owner.json('GET', '/release.json')['releaseId'] == '0.1.1', 'Gateway did not expose the selected release.')
        state = operator.read_json(runtime / 'operation.json')
        require(state['phase'] == 'ready' and state.get('backup'), 'Update did not finish with an offline backup.')
        backup = operator.read_json(runtime / 'backups' / state['backup'] / 'manifest.json')
        require(backup['release'] == base and backup['migrations'] == base['migrations'], 'Backup is not the pre-update release.')
        require(any(item['sha256'] == hashlib.sha256(fixture[3]).hexdigest() for item in backup['databaseOriginals']),
                'Offline backup is missing the synthetic immutable original.')
        operator.compose('run', '--rm', '-T', '--no-deps', 'ops', 'verify-backup', state['backup'],
                         config=config, release=selected, capture=True)
        evidence['checks']['upgrade_data_session_database_assets_backup'] = 'passed'
        evidence['activeCheck'] = 'pre_update_pending_exact_replay_and_new_edit'
        newer = apply_prepared_and_edit(owner, path, prepared)
        evidence['checks']['pre_update_pending_exact_replay_and_new_edit'] = 'passed'
        evidence['activeCheck'] = 'current_node_deletion_regression'
        integration.node_deletion_smoke(owner)
        # Snapshot the post-upgrade active graphs and private stored tombstones.
        investigations = owner.json('GET', '/api/v1/investigations')['items']
        snapshots = {item['id']: owner.json('GET', '/api/v1/investigations/' + item['id'] + '/graph')
                     for item in investigations}
        deleted = tombstones(operator, config, selected)
        require(len(deleted['nodes']) == 1 and len(deleted['relations']) == 4,
                'Deletion regression did not store its node and incident relation tombstones.')
        evidence['checks']['current_node_deletion_regression'] = 'passed'
        evidence['activeCheck'] = 'rollback_preserves_new_data_session_database'
        integration.cli(runtime, 'rollback', '--yes')
        require(operator.current() == base and operator.load_config() == config, 'Rollback did not restore the original release pair.')
        rolled_back = identities(operator, config, base)
        require(rolled_back['db'] == before['db'] and rolled_back['gateway'] == before['gateway'],
                'Rollback restarted the database or gateway.')
        preserved(owner, fixture, cookie, csrf, account)
        require(owner.json('GET', path + '/nodes/' + prepared.node_id)['node']['title'] == newer,
                'Rollback lost the new post-upgrade edit.')
        for identifier, snapshot in snapshots.items():
            require(owner.json('GET', '/api/v1/investigations/' + identifier + '/graph') == snapshot,
                    'Rollback lost graph data written after upgrade.')
        require(tombstones(operator, config, base) == deleted,
                'Rollback lost stored node/relation tombstones written after upgrade.')
        require(owner.json('GET', '/release.json')['releaseId'] == '0.1.0', 'Rollback gateway metadata differs.')
        evidence['checks']['rollback_preserves_new_data_session_database'] = 'passed'
    finally:
        if operator is not None:
            try:
                evidence['checks']['marked_cleanup_retains_volumes'] = safe_cleanup(runtime, operator, origin)
            except Exception:
                evidence['checks']['marked_cleanup_retains_volumes'] = 'failed'
                evidence['activeCheck'] = 'marked_cleanup_retains_volumes'
                raise


def self_test():
    base = json.loads((ROOT / 'releases/0.1.0.json').read_text())
    candidate = copy.deepcopy(base)
    for key in ['releaseId', 'frontendReleaseId', 'frontendVersion', 'backendVersion']:
        candidate[key] = '0.1.1'
    for key in ['backend', 'frontend', 'gateway', 'tools']:
        # Synthetic manifest only; these references are never pulled/published.
        candidate['images'][key] = 'docker.io/andreytorlopov/traceweave-' + key + ':0.1.1@sha256:' + hashlib.sha256(key.encode()).hexdigest()
    for key in ['backend', 'frontend', 'delivery']:
        candidate['source'][key] = hashlib.sha1(key.encode()).hexdigest()
    original_base, original_candidate = copy.deepcopy(base), copy.deepcopy(candidate)
    result = compatible_manifest(base, candidate)
    require(base == original_base and candidate == original_candidate, 'Manifest builder modified its inputs.')
    require(result['source']['delivery'] == base['source']['delivery'], 'Mixed manifest lost delivery provenance.')
    require(all(result['images'][key] == base['images'][key] for key in ['gateway', 'tools', 'postgres']), 'Infrastructure changed.')
    mutations = [
        lambda value: value['migrations'][0].update(sha256='0' * 64),
        lambda value: value.update(contractHash='0' * 64, backendContractHash='0' * 64, supportedClientContractHashes=['0' * 64]),
        lambda value: value['source'].update(deliveryDiffHash='0' * 64),
        lambda value: value['source'].update(backend='invalid'),
        lambda value: value['images'].update(frontend=base['images']['frontend']),
        lambda value: value.update(platforms=['linux/amd64']),
        lambda value: value.update(releaseId='0.1.2'),
    ]
    for mutate in mutations:
        invalid = copy.deepcopy(candidate)
        mutate(invalid)
        try:
            compatible_manifest(base, invalid)
        except (AssertionError, control.Failure):
            continue
        raise AssertionError('Unsafe published update fixture was accepted.')
    print('PASS compatible published manifest construction and seven unsafe variants; no Docker/network execution.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--candidate')
    parser.add_argument('--legacy')
    parser.add_argument('--runtime')
    parser.add_argument('--output')
    parser.add_argument('--arch', choices=['amd64', 'arm64'])
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all([args.candidate, args.legacy, args.runtime, args.output, args.arch]):
        parser.error('--candidate, --legacy, --runtime, --output and --arch are required.')
    require(1024 <= args.port <= 65535, 'Use an unprivileged loopback port.')
    # Resolve before legacy_operator changes cwd. No caller-provided Docker
    # endpoint can redirect this marked synthetic test to a remote installation.
    for key in ['candidate', 'legacy', 'runtime', 'output']:
        setattr(args, key, str(Path(getattr(args, key)).absolute()))
    for key in ['DOCKER_HOST', 'DOCKER_CONTEXT']:
        os.environ.pop(key, None)
    output = Path(args.output)
    require(not output.exists() and not output.is_symlink(), 'Public evidence directory must be new.')
    output.mkdir(parents=True, mode=0o700)
    evidence = dict(formatVersion=1, baseRelease='0.1.0', targetRelease='0.1.1', nativePlatform='linux/' + args.arch,
                    anonymousPull=True, operator='Unmodified v0.1.0 traceweave.sh and published tools:0.1.0; no host Python on operator PATH',
                    data='Fresh marked synthetic installation; stop retains all volumes', checks={}, conclusion='failed')
    if os.environ.get('GITHUB_REPOSITORY') and os.environ.get('GITHUB_RUN_ID'):
        evidence['runURL'] = 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
    try:
        verify(args, evidence)
        require(len(evidence['checks']) == 7 and all(value == 'passed' for value in evidence['checks'].values()),
                'Published update verification is incomplete.')
        evidence['conclusion'] = 'passed'
        evidence.pop('activeCheck', None)
    except Exception as error:
        evidence['errorClass'] = type(error).__name__
        print('FAIL published update verification: ' + evidence.get('activeCheck', 'preflight') +
              ' (' + evidence['errorClass'] + '); private diagnostics remain on the runner.', file=sys.stderr)
    finally:
        write_json(output / 'verification.json', evidence)
    print('Published update linux/' + args.arch + ': ' + evidence['conclusion'])
    return 0 if evidence['conclusion'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
