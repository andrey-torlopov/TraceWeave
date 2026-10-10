#!/usr/bin/env python3
"""Real fault acceptance, restricted to explicitly marked synthetic installations."""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import control
import integration

require = integration.require


def synthetic_scope(runtime, test_root):
    allowed = {(PROJECT / 'var/docker-tests').resolve(), (ROOT / 'runtime/tests_ci').resolve()}
    require(test_root in allowed and runtime.parent == test_root and runtime != test_root, 'Runtime must be an explicit child of the approved synthetic test root.')
    require(not runtime.is_symlink() and not test_root.is_symlink(), 'Synthetic runtime/root must not be a symlink.')
    require(json.loads((runtime / 'synthetic-installation.json').read_text()) == {'synthetic': True, 'email': integration.EMAIL},
        'Refusing an unmarked installation.')


class Suite:
    def __init__(self, runtime, protocol, test_root):
        synthetic_scope(runtime, test_root)
        self.runtime, self.protocol = runtime, protocol
        control.RUNTIME = runtime
        self.config = control.load_config()
        require(self.config['mode'] == 'local', 'Fault acceptance requires a synthetic local installation.')
        self.install = self.config['installId']
        require(all(value.startswith(self.install + '-') for value in self.config['volumes'].values()), 'Foreign volume namespace refused.')
        self.release = control.current()
        self.owner = integration.Client(self.config['origin'])
        require(self.owner.port and 1024 <= self.owner.port <= 65535, 'Synthetic loopback port must be explicit and unprivileged.')
        self.owner.login()
        self.owner_id = self.owner.owner

    def record(self, value):
        self.protocol.write(value + '\n'); self.protocol.flush()
        print(value, flush=True)

    def command(self, arguments, capture=False, check=True):
        child = os.environ.copy()
        for key in list(child):
            if key.startswith(('COMPOSE_', 'PG')):
                child.pop(key)
        child.update(control.compose_env(self.config, control.current()))
        result = subprocess.run(arguments, cwd=ROOT, env=child, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else self.protocol, stderr=self.protocol, timeout=420)
        if check:
            require(result.returncode == 0, 'Fault suite command failed; inspect the private protocol.')
        return result.stdout.decode().strip() if capture else result.returncode

    def compose(self, *arguments, capture=False, check=True):
        return self.command(['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT / 'compose.yaml'),
            *arguments], capture=capture, check=check)

    def cli(self, *arguments, success=True, reason=None):
        previous = set(self.runtime.glob('integration-*.log'))
        integration.cli(self.runtime, *arguments, expect_success=success)
        created = set(self.runtime.glob('integration-*.log')) - previous
        require(len(created) == 1, 'Operator command did not produce exactly one private diagnostic log.')
        log = next(iter(created))
        require(log.stat().st_mode & 0o077 == 0, 'Operator diagnostic permissions are not private.')
        if reason:
            require(reason in log.read_text(), 'Operator failure did not match the required cause: ' + reason + '. See private ' + str(log))
        self.protocol.write('CLI ' + arguments[0] + ': ' + ('success' if success else 'expected refusal') + '; ' + log.name + '\n')
        self.protocol.flush()

    def state(self):
        return json.loads((self.runtime / 'operation.json').read_text())

    def accepted_backups(self):
        return {str(path.relative_to(self.runtime)) for path in (self.runtime / 'backups').glob('*/manifest.json')}

    def identity(self):
        return {name: (self.runtime / name).read_bytes() for name in ['installation.json', 'release.json', 'operation.json', 'maintenance.json']}

    def containers(self):
        return {name: self.compose('ps', '-a', '-q', name, capture=True) for name in ['backend', 'frontend', 'gateway', 'db']}

    def maintenance(self):
        for path in ['/', '/api/v1/session']:
            body, headers = self.owner.request('GET', path, expected=503)
            require(headers.get('cache-control') == 'no-store' and headers.get('retry-after') == '15', 'Maintenance response headers differ.')
            if path.startswith('/api'):
                require(json.loads(body)['error']['code'] == 'service_maintenance', 'Maintenance API envelope differs.')

    def available(self, investigation=None):
        self.owner.json('GET', '/health/ready')
        require(control.current() == self.release and self.state()['phase'] == 'ready', 'Accepted final release did not return to ready.')
        require(self.owner.json('GET', '/api/v1/session')['user']['id'] == self.owner_id, 'Account/session identity changed unexpectedly.')
        if investigation:
            require(self.owner.json('GET', '/api/v1/investigations/' + investigation)['id'] == investigation, 'Post-backup data was lost.')

    def security(self):
        for service in ['backend', 'frontend', 'gateway']:
            identifier = self.compose('ps', '-q', service, capture=True)
            metadata = json.loads(self.command(['docker', 'inspect', identifier], capture=True))[0]
            require(metadata['State']['Running'] and metadata['HostConfig']['ReadonlyRootfs'], service + ' root filesystem is writable.')
            require('ALL' in metadata['HostConfig']['CapDrop'], service + ' retains capabilities.')
            require(any(item.startswith('no-new-privileges') for item in metadata['HostConfig']['SecurityOpt']), service + ' allows privilege escalation.')
            require(self.compose('exec', '-T', service, 'id', '-u', capture=True) == '10001', service + ' effective uid differs.')
        for service in ['backend', 'frontend', 'db']:
            identifier = self.compose('ps', '-q', service, capture=True)
            bindings = json.loads(self.command(['docker', 'inspect', '--format', '{{json .HostConfig.PortBindings}}', identifier], capture=True))
            require(not bindings, service + ' has a host port.')
        values = self.compose('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'traceweave', '-Atc',
            "SELECT count(*)||'|'||bool_and(s.ssl)::text FROM pg_stat_activity a JOIN pg_stat_ssl s ON s.pid=a.pid WHERE a.usename='traceweave' AND a.datname='traceweave' AND a.backend_type='client backend'; SELECT rolsuper::text||'|'||rolcreaterole::text||'|'||rolcreatedb::text FROM pg_roles WHERE rolname='traceweave'", capture=True).splitlines()
        require(len(values) == 2 and int(values[0].split('|')[0]) >= 1 and values[0].split('|')[1] == 'true', 'Actual application database connections are not all TLS.')
        require(values[1] == 'false|false|false', 'Application database role is privileged.')
        originals = self.compose('exec', '-T', 'backend', 'sh', '-c',
            'find /var/lib/traceweave/blobs -type f -exec stat -c "%u %a" {} +', capture=True).splitlines()
        require(originals and all(item == '10001 400' for item in originals), 'Originals are missing or not owned uid10001/mode0400.')
        self.record('PASS actual container uid10001, read-only root, dropped capabilities, no private-service host ports; PostgreSQL TLS/unprivileged role and immutable originals0400.')

    def live_backup_refusal(self):
        name = 'fault-live-' + uuid.uuid4().hex[:12]
        before, identities = self.accepted_backups(), self.identity()
        require(self.compose('run', '--rm', '-T', '--no-deps', 'ops', 'backup', name, check=False) != 0,
            'Offline operations accepted a backup while backend retained its maintenance lease.')
        require(not (self.runtime / 'backups' / name).exists() and self.accepted_backups() == before, 'Rejected live backup produced an accepted manifest.')
        require(self.identity() == identities, 'Direct offline refusal changed installation state.')
        self.available()
        self.record('PASS direct offline backup with live backend refused before creating a backup/manifest, without installation changes.')

    def corrupt_restore(self):
        candidates = sorted(path.parent for path in (self.runtime / 'backups').glob('*/manifest.json') if not path.parent.name.startswith('fault-'))
        require(candidates, 'Verified synthetic backup required.')
        source = candidates[-1]
        self.compose('run', '--rm', '-T', '--no-deps', 'ops', 'verify-backup', source.name)
        original_digest = control.hash_file(source / 'database.dump')
        target = self.runtime / 'backups' / ('fault-corrupt-' + uuid.uuid4().hex[:12])
        shutil.copytree(source, target)
        for root, directories, files in os.walk(target):
            Path(root).chmod(0o700)
            for name in files:
                (Path(root) / name).chmod(0o600)
        with (target / 'database.dump').open('ab') as output:
            output.write(b'SYNTHETIC-CORRUPTION\n'); output.flush(); os.fsync(output.fileno())
        identities, containers = self.identity(), self.containers()
        self.cli('restore', '--backup', target.name, '--yes', success=False, reason='Backup dump checksum mismatch.')
        require(self.identity() == identities and self.containers() == containers, 'Corrupt restore changed maintenance, installation or container identities.')
        require(control.hash_file(source / 'database.dump') == original_digest, 'The original verified backup was modified.')
        self.available()
        self.record('PASS corrupt COPY of verified dump rejected before maintenance and identity changes; original backup preserved.')

    def graceful_upload(self):
        investigation = self.owner.create('Fault acceptance active upload ' + uuid.uuid4().hex[:12])
        path = '/api/v1/investigations/' + investigation['id']
        payload = (ROOT / 'tests/fixtures/media/synthetic.png').read_bytes()
        ticket = self.owner.json('POST', path + '/uploads', {'idempotencyKey': integration.uid(), 'originalName': 'synthetic.png',
            'expectedMimeType': 'image/png', 'expectedByteSize': len(payload)}, expected=201)
        connection = http.client.HTTPConnection(self.owner.host, self.owner.port, timeout=120)
        outcome, worker = [], None
        try:
            connection.putrequest('PUT', path + '/uploads/' + ticket['id'] + '/content')
            for name, value in {'Content-Type': 'application/octet-stream', 'Content-Length': str(len(payload)), 'Cookie': self.owner.cookie,
                'X-CSRF-Token': self.owner.csrf, 'Origin': self.owner.origin, 'X-TraceWeave-Account-ID': self.owner.owner,
                'X-TraceWeave-Client-Contract': self.owner.contract}.items():
                connection.putheader(name, value)
            connection.endheaders(); offset = len(payload) // 2; connection.send(payload[:offset])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.owner.json('GET', path + '/uploads/' + ticket['id'])['state'] == 'receiving':
                    break
                time.sleep(.05)
            else:
                connection.send(payload[offset:]); reply = connection.getresponse(); reply.read(16384)
                require(reply.status == 200, 'Synthetic partial upload failed before maintenance.')
                self.record('NOT_RUN graceful active-upload overlap: receiving state was not observable before the test deadline.')
                return
            def backup():
                try:
                    self.cli('backup'); outcome.append(None)
                except Exception as error:
                    outcome.append(error)
            worker = threading.Thread(target=backup, daemon=True); worker.start()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    self.owner.request('GET', '/api/v1/session', expected=503)
                    break
                except AssertionError:
                    time.sleep(.05)
            else:
                raise AssertionError('Real maintenance503 did not occur while the partial upload was active.')
            connection.send(payload[offset:]); reply = connection.getresponse(); result = json.loads(reply.read(16384))
            require(reply.status == 200 and result['state'] == 'completed' and result['sha256'] == hashlib.sha256(payload).hexdigest(),
                'Active upload was lost instead of finishing through maintenance shutdown.')
            worker.join(300); require(not worker.is_alive() and len(outcome) == 1 and outcome[0] is None, 'Concurrent backup did not complete successfully.')
            self.available(investigation['id'])
            self.record('PASS real receiving PNG PUT completed with identical payload/hash after observed maintenance503 during backup; graceful backend stop accepted.')
        finally:
            connection.close()
            if worker:
                worker.join(300)
                require(not worker.is_alive(), 'Concurrent operator backup remains active; inspect private state before further recovery.')

    def metadata_update(self):
        newer = self.owner.create('Must survive image rollback ' + uuid.uuid4().hex[:12])['id']
        candidate = copy.deepcopy(self.release)
        candidate['releaseId'] = 'fault-frontend-metadata-' + uuid.uuid4().hex[:12]
        # LABEL-only derivative preserves the actual selected app and requires
        # no second source build or old release image. All images stay local.
        nonce = uuid.uuid4().hex[:12]
        source_tag, candidate_tag = 'traceweave/fault-source:' + nonce, 'traceweave/fault-candidate:' + nonce
        context = self.runtime / ('fault-image-' + nonce); context.mkdir(mode=0o700)
        dockerfile = context / 'Dockerfile'
        dockerfile.write_text('FROM ' + source_tag + '\nLABEL traceweave.synthetic-fault="' + nonce + '"\n'); dockerfile.chmod(0o600)
        self.command(['docker', 'tag', self.release['images']['frontend'], source_tag])
        self.command(['docker', 'build', '--network', 'none', '--pull=false', '-t', candidate_tag, str(context)])
        candidate['images']['frontend'] = self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', candidate_tag], capture=True)
        candidate['frontendReleaseId'] = candidate['frontendVersion'] = 'synthetic-mismatch-' + nonce
        require(candidate['images']['frontend'] != self.release['images']['frontend'], 'The wrong-metadata image must differ.')
        target = self.runtime / (candidate['releaseId'] + '.json')
        control.write_json(target, candidate)
        self.cli('update', '--release', str(target), '--yes', success=False, reason='Frontend image metadata differs from selected release.')
        self.maintenance()
        require(control.current() == self.release and self.state()['phase'] == 'update-starting', 'Bad metadata was accepted or operation state lost.')
        self.cli('stop')
        require(self.state()['phase'] == 'stopped-interrupted', 'Interrupted update stop lost its recovery state.')
        self.cli('resume', '--yes', success=False, reason='Frontend image metadata differs from selected release.')
        self.maintenance()
        for service in ['db', 'gateway', 'backend']:
            identifier = self.compose('ps', '-q', service, capture=True)
            require(identifier and self.command(['docker', 'inspect', '--format', '{{.State.Running}}', identifier], capture=True) == 'true',
                'Resume did not start ' + service + ' under maintenance.')
        self.cli('rollback', '--yes')
        self.available(newer)
        self.record('PASS real wrong-frontend-metadata update failed closed; whole-stack stop/resume retained maintenance, rollback restored final images and newer data.')

    def killed_backend(self):
        before = self.accepted_backups()
        identifier = self.compose('ps', '-q', 'backend', capture=True)
        require(identifier and json.loads(self.command(['docker', 'inspect', '--format', '{{json .Config.Labels}}', identifier], capture=True))['com.docker.compose.project'] == self.install,
            'Refusing to kill a foreign backend container.')
        self.command(['docker', 'kill', '-s', 'KILL', identifier])
        state = json.loads(self.command(['docker', 'inspect', '--format', '{{json .State}}', identifier], capture=True))
        require(not state['Running'] and state['ExitCode'] == 137, 'Forced-stop fixture did not produce an exited137 backend.')
        self.cli('backup', success=False, reason='Backend did not stop gracefully.')
        require(self.accepted_backups() == before and self.state()['phase'] == 'backup-entering', 'Forced-stop backup was accepted.')
        self.maintenance()
        self.cli('resume', '--yes')
        self.available()
        self.record('PASS actual SIGKILL/exit137 backend refused backup before manifest acceptance, then resume restored ready final release/session.')

    def run(self):
        self.available()
        self.security()
        self.live_backup_refusal()
        self.corrupt_restore()
        self.graceful_upload()
        self.metadata_update()
        self.killed_backend()

    def graceful_export(self):
        self.available()
        nonce = uuid.uuid4().hex[:12]
        original = self.runtime / ('fault-export-' + nonce + '.wav')
        descriptor = os.open(original, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            with wave.open(output, 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
                block = bytes(65536)
                for _ in range(2048):
                    audio.writeframesraw(block)
        size, digest = original.stat().st_size, control.hash_file(original)
        investigation = self.owner.create('Synthetic active export ' + nonce)
        path = '/api/v1/investigations/' + investigation['id']
        ticket = self.owner.json('POST', path + '/uploads', {'idempotencyKey': integration.uid(), 'originalName': original.name,
            'expectedMimeType': 'audio/wav', 'expectedByteSize': size}, expected=201)
        headers = {'Cookie': self.owner.cookie, 'X-CSRF-Token': self.owner.csrf, 'Origin': self.owner.origin,
            'X-TraceWeave-Account-ID': self.owner.owner, 'X-TraceWeave-Client-Contract': self.owner.contract}
        connection = http.client.HTTPConnection(self.owner.host, self.owner.port, timeout=120)
        try:
            connection.putrequest('PUT', path + '/uploads/' + ticket['id'] + '/content')
            for name, value in {**headers, 'Content-Type': 'application/octet-stream', 'Content-Length': str(size)}.items():
                connection.putheader(name, value)
            connection.endheaders()
            with original.open('rb') as source:
                while block := source.read(65536):
                    connection.send(block)
            response = connection.getresponse(); uploaded = json.loads(response.read(16384))
            require(response.status == 200 and uploaded['sha256'] == digest, 'Legitimate synthetic WAV upload failed.')
        finally:
            connection.close()
        graph = self.owner.json('GET', path + '/graph'); node, asset = integration.uid(), integration.uid()
        note = next(item['id'] for item in graph['nodeTypes'] if item['code'] == 'note')
        self.owner.commands(path, [
            {'kind': 'node.create', 'node': {'id': node, 'typeId': note, 'title': 'Synthetic silence', 'bodyMarkdown': 'Deterministic silence for bounded export shutdown acceptance.'}, 'position': {'x': 0, 'y': 0}},
            {'kind': 'asset.register', 'uploadId': ticket['id'], 'assetId': asset, 'metadata': {'title': 'Synthetic silence', 'sourceUrl': None, 'sourceAuthor': None, 'sourceCreatedAt': None, 'noteMarkdown': ''}},
            {'kind': 'attachment.attach', 'attachment': {'id': integration.uid(), 'nodeId': node, 'assetId': asset, 'role': 'attachment', 'caption': None, 'sortOrder': 0}},
        ])
        self.record('Prepared bounded legitimate WAV bytes=' + str(size) + '; streamed upload/hash and registered attachment verified.')
        for attempt in range(1, 3):
            revision = self.owner.json('GET', path)['revision']
            job = self.owner.json('POST', path + '/exports', {'kind': 'obsidian_vault', 'sourceRevision': revision,
                'idempotencyKey': integration.uid()}, expected=202)
            target = path + '/exports/' + job['id']
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                job = self.owner.json('GET', target)
                if job['state'] in ['running', 'succeeded', 'failed', 'cancelled']:
                    break
                time.sleep(.01)
            if job['state'] != 'running':
                self.record('NOT_RUN active-export overlap attempt ' + str(attempt) + ': pre-backup observed state=' + job['state'])
                continue
            self.record('Observed actual HTTP export running before backup, attempt=' + str(attempt))
            outcome = []
            def backup():
                try:
                    self.cli('backup'); outcome.append(None)
                except Exception as error:
                    outcome.append(error)
            worker = threading.Thread(target=backup, daemon=True); worker.start()
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        self.owner.request('GET', '/api/v1/session', expected=503)
                        break
                    except AssertionError:
                        time.sleep(.02)
                else:
                    raise AssertionError('Export backup never exposed actual maintenance503.')
                identifier = str(uuid.UUID(job['id']))
                observed = self.compose('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'traceweave', '-Atc',
                    "SELECT state FROM export_jobs WHERE id='" + identifier + "'", capture=True)
                self.record('Read-only PostgreSQL export state AFTER real maintenance503: ' + observed)
            finally:
                worker.join(300)
                require(not worker.is_alive() and len(outcome) == 1 and outcome[0] is None, 'Active-export backup did not complete.')
            self.available(investigation['id'])
            job = self.owner.json('GET', target)
            require(job['state'] == 'succeeded', 'Graceful shutdown did not finish the real export.')
            archive_path = self.runtime / ('fault-export-archive-' + nonce + '-' + str(attempt) + '.zip')
            connection = http.client.HTTPConnection(self.owner.host, self.owner.port, timeout=120)
            try:
                connection.request('GET', target + '/download', headers=headers)
                response = connection.getresponse(); require(response.status == 200, 'Real export download failed.')
                hasher, count = hashlib.sha256(), 0
                fd = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    while block := response.read(65536):
                        count += len(block); require(count <= size + 1024 * 1024, 'Synthetic export exceeded its bounded size.')
                        hasher.update(block); output.write(block)
                require(count == job['byteSize'] and hasher.hexdigest() == job['sha256'], 'Downloaded real ZIP size/hash differs.')
            finally:
                connection.close()
            with zipfile.ZipFile(archive_path) as archive:
                require(archive.testzip() is None, 'Downloaded ZIP CRC integrity failed.')
                names = [name for name in archive.namelist() if name.endswith('.wav')]
                require(len(names) == 1, 'ZIP did not include exactly the attached WAV original.')
                hasher = hashlib.sha256()
                with archive.open(names[0]) as source:
                    while block := source.read(65536):
                        hasher.update(block)
                require(hasher.hexdigest() == digest, 'Exported WAV differs from the immutable original.')
            if observed == 'running':
                self.record('PASS real running export remained active AFTER maintenance503 during backup, finished through graceful stop; streamed ZIP hash/CRC and original verified.')
                return
            self.record('NOT_RUN active-export overlap attempt ' + str(attempt) + ': job finished before post503 SQL observation; completed ZIP verified without claiming overlap.')
        self.record('NOT_RUN sustained active-export overlap: both bounded attempts were too fast; no status manipulation, process suspension or production change used.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', default=str(PROJECT / 'var/docker-tests/final'))
    parser.add_argument('--test-root', default=str(PROJECT / 'var/docker-tests'), help='Approved synthetic namespace: workspace var/docker-tests or checkout runtime/tests_ci.')
    parser.add_argument('--export-only', action='store_true', help='Run bounded active-export/backup acceptance independently of the fault suite.')
    parser.add_argument('--protocol', default=str(PROJECT / 'var/docker-fault-test.log'))
    arguments = parser.parse_args()
    runtime, protocol_path, test_root = Path(arguments.runtime).resolve(), Path(arguments.protocol).resolve(), Path(arguments.test_root).resolve()
    synthetic_scope(runtime, test_root)
    require(protocol_path.is_relative_to((PROJECT / 'var').resolve()) or protocol_path.is_relative_to(test_root), 'Protocol must stay in private project var/synthetic namespace.')
    protocol_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(protocol_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as protocol:
        suite = Suite(runtime, protocol, test_root)
        try:
            if arguments.export_only:
                suite.graceful_export()
            else:
                suite.run()
            suite.cli('stop')
        finally:
            # A failed scenario stays closed and retains its interrupted state.
            # Stop services directly if the safe controller stop cannot accept
            # the intentionally forced exit; never remove volumes or backups.
            suite.compose('stop', '--timeout', '180', 'backend', 'frontend', 'gateway', 'db')
            suite.record('Owned final synthetic stack stopped; all volumes, invalid copies and private recovery logs preserved.')


if __name__ == '__main__':
    main()
