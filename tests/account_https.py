#!/usr/bin/env python3
"""Real HTTPS/account/SMTP acceptance in a marked synthetic Docker installation."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from email.parser import BytesParser
from email import policy
import hashlib
import http.client
from http.cookies import SimpleCookie
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
TEST_ROOT = PROJECT / 'var/docker-tests'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'tools'))
import integration
import control


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Client:
    def __init__(self, origin, ca_file):
        parts = urlsplit(origin)
        require(parts.scheme == 'https' and parts.hostname == '127.0.0.1', 'HTTPS fixture requires literal loopback.')
        self.origin, self.host, self.port = origin, parts.hostname, parts.port
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.cookie = self.csrf = self.owner = self.contract = None

    def request(self, method, path, value=None, headers=None, expected=200):
        supplied = {'Accept': 'application/json'}
        if self.cookie:
            supplied['Cookie'] = self.cookie
        if self.owner:
            supplied['X-TraceWeave-Account-ID'] = self.owner
        if self.contract:
            supplied['X-TraceWeave-Client-Contract'] = self.contract
        if method in ['POST', 'PATCH', 'PUT', 'DELETE']:
            supplied['Origin'] = self.origin
            if self.csrf:
                supplied['X-CSRF-Token'] = self.csrf
        raw = None
        if value is not None:
            supplied['Content-Type'] = 'application/json'
            raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        supplied.update(headers or {})
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=30)
        try:
            connection.request(method, path, body=raw, headers=supplied)
            reply = connection.getresponse()
            body = reply.read(2_097_153)
            require(len(body) <= 2_097_152, 'HTTPS fixture response bound exceeded.')
            result_headers = {name.lower(): value for name, value in reply.getheaders()}
            if 'set-cookie' in result_headers:
                jar = SimpleCookie()
                jar.load(result_headers['set-cookie'])
                if 'rg_session' in jar:
                    self.cookie = 'rg_session=' + jar['rg_session'].value
            if reply.status != expected:
                try:
                    code = json.loads(body).get('error', {}).get('code', '')
                except ValueError:
                    code = ''
                raise AssertionError(f'HTTPS {method} {path} returned {reply.status} {code}; expected {expected}.')
            return body, result_headers
        finally:
            connection.close()

    def json(self, method, path, value=None, **options):
        return json.loads(self.request(method, path, value, **options)[0])

    def bootstrap(self):
        self.owner = None
        self.contract = self.json('GET', '/release.json')['contractHash']
        body, headers = self.request('GET', '/api/v1/session')
        value = json.loads(body)
        self.csrf = value['csrfToken']
        require(not value['authenticated'], 'Expected a fresh anonymous session.')
        cookie = headers.get('set-cookie', '').lower()
        require(all(item in cookie for item in ['secure', 'httponly', 'samesite=strict']), 'HTTPS cookie flags incomplete.')

    def login(self, email, password):
        self.owner = None
        value = self.json('POST', '/api/v1/session/login', {'email': email, 'password': password})
        self.csrf, self.owner = value['csrfToken'], value['user']['id']
        require(value['authenticated'] and value['user']['emailVerified'], 'Verified email session missing.')
        return value


class Fixture:
    def __init__(self, runtime, release, port, protocol):
        self.runtime, self.release, self.port = runtime, release, port
        self.origin = 'https://127.0.0.1:' + str(port)
        self.certificates = runtime / 'account-certificates'
        self.capture = runtime / 'account-mail'
        self.protocol = protocol
        self.config = None
        self.tokens = []

    def record(self, message):
        # Checks only: neither HTTP/session payloads nor SMTP messages enter logs.
        self.protocol.write(message + '\n')
        self.protocol.flush()
        print(message, flush=True)

    def command(self, arguments, capture=False, check=True, environment=None):
        child = self.environment()
        if environment:
            child.update(environment)
        result = subprocess.run(arguments, cwd=ROOT, env=child, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else self.protocol, stderr=self.protocol, timeout=300)
        if check:
            require(result.returncode == 0, 'Synthetic fixture command failed; inspect the private protocol.')
        return result.stdout.decode().strip() if capture else result.returncode

    def environment(self):
        environment = os.environ.copy()
        for key in list(environment):
            if key.startswith(('COMPOSE_', 'PG')):
                environment.pop(key)
        if self.config:
            environment.update(control.compose_env(self.config, self.release))
        environment.update(TW_ACCOUNT_TEST_ORIGIN=self.origin, TW_ACCOUNT_TEST_PORT=str(self.port))
        return environment

    def compose(self, *arguments, capture=False):
        return self.command(['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT / 'compose.yaml'),
            '-f', str(ROOT / 'tests/compose.account-test.yaml'), *arguments], capture=capture)

    def load_synthetic_config(self, local_port):
        marker = self.runtime / 'synthetic-installation.json'
        require(marker.is_file() and json.loads(marker.read_text()) == {'synthetic': True, 'suite': 'docker-account-https'},
            'Refusing to control an unmarked runtime.')
        candidate = json.loads((self.runtime / 'installation.json').read_text())
        require(candidate['origin'] == 'http://127.0.0.1:' + str(local_port) and candidate['mode'] == 'local',
            'Existing synthetic bootstrap origin differs.')
        install = candidate.get('installId', '')
        require(re.fullmatch('tw-[a-f0-9]{12}', install) is not None, 'Synthetic installation identity is invalid.')
        expected = {key: install + suffix for key, suffix in [('database', '-postgres'), ('files', '-files'),
            ('assets', '-assets'), ('gatewayData', '-gateway-data'), ('gatewayConfig', '-gateway-config')]}
        require(candidate['volumes'] == expected, 'Refusing to control volumes outside this synthetic installation.')
        self.config = candidate

    def prepare(self, local_port, existing=False):
        marker = self.runtime / 'synthetic-installation.json'
        if existing:
            require(marker.is_file() and json.loads(marker.read_text()) == {'synthetic': True, 'suite': 'docker-account-https'},
                'Refusing to resume an unmarked runtime.')
            require(json.loads((self.runtime / 'release.json').read_text()) == self.release, 'Existing synthetic release differs.')
            self.load_synthetic_config(local_port)
        else:
            require(not self.runtime.exists(), 'A fresh test requires a nonexistent runtime; no previous data is deleted.')
            self.runtime.mkdir(parents=True, mode=0o700)
            marker.write_text(json.dumps({'synthetic': True, 'suite': 'docker-account-https'}))
            marker.chmod(0o600)
        if not existing:
            integration.cli(self.runtime, 'bootstrap', '--release', str(self.release_path), '--origin',
                'http://127.0.0.1:' + str(local_port), '--email', integration.EMAIL, '--name', 'Synthetic HTTPS operator', password=integration.PASSWORD)
            self.load_synthetic_config(local_port)
        if existing:
            self.compose('stop', '--timeout', '120')
        else:
            integration.cli(self.runtime, 'stop')
        self.config = json.loads((self.runtime / 'installation.json').read_text())
        # Test-only address: avoid competing with the first dynamic application IP
        # while this override starts all its synthetic services concurrently.
        self.config['gatewayIP'] = str(ipaddress.ip_network(self.config['subnet']).broadcast_address - 1)
        self.certificates.mkdir(mode=0o755, exist_ok=True)
        self.capture.mkdir(mode=0o700, exist_ok=True)
        control.atomic(self.runtime / 'secrets/smtp_password', 'synthetic-smtp-password\n', 0o444)
        self.command(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Synthetic account test CA',
            '-keyout', str(self.certificates / 'ca.key'), '-out', str(self.certificates / 'ca.crt'),
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-addext', 'subjectKeyIdentifier=hash', '-addext', 'authorityKeyIdentifier=keyid:always'])
        for name, subject, alternative in [('gateway', '127.0.0.1', 'IP:127.0.0.1'), ('smtp', 'smtp', 'DNS:smtp')]:
            self.command(['openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=' + subject,
                '-keyout', str(self.certificates / (name + '.key')), '-out', str(self.certificates / (name + '.csr'))])
            extensions = self.certificates / (name + '.ext')
            extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nsubjectAltName=' + alternative + '\n')
            self.command(['openssl', 'x509', '-req', '-days', '2', '-in', str(self.certificates / (name + '.csr')),
                '-CA', str(self.certificates / 'ca.crt'), '-CAkey', str(self.certificates / 'ca.key'), '-CAcreateserial',
                '-extfile', str(extensions), '-out', str(self.certificates / (name + '.crt'))])
        self.command(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=smtp',
            '-addext', 'subjectAltName=DNS:smtp', '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign,cRLSign',
            '-addext', 'extendedKeyUsage=serverAuth', '-addext', 'subjectKeyIdentifier=hash',
            '-addext', 'authorityKeyIdentifier=keyid:always',
            '-keyout', str(self.certificates / 'untrusted.key'), '-out', str(self.certificates / 'untrusted.crt')])
        self.command(['openssl', 'verify', '-x509_strict', '-CAfile', str(self.certificates / 'ca.crt'),
            str(self.certificates / 'gateway.crt'), str(self.certificates / 'smtp.crt')])
        # Read-only synthetic service keys are within the operator's private parent.
        # The non-root gateway uid10001 must read its fixture key.
        for path in self.certificates.iterdir():
            path.chmod(0o644 if path.name in ['ca.crt', 'gateway.crt', 'gateway.key', 'smtp.crt', 'smtp.key'] else 0o600)
        control.RUNTIME = self.runtime
        self.gateway_configuration(self.config, self.release, False, control.caddy_config)
        self.compose('up', '-d', '--wait', '--wait-timeout', '180', 'db', 'smtp', 'backend', 'frontend', 'gateway')
        deadline = time.monotonic() + 120
        last_failure = 'unknown'
        while time.monotonic() < deadline:
            try:
                Client(self.origin, self.certificates / 'ca.crt').json('GET', '/health/ready')
                break
            except (OSError, AssertionError) as error:
                last_failure = type(error).__name__ + ': ' + str(error)
                time.sleep(.5)
        else:
            raise AssertionError('Synthetic HTTPS backend did not become ready: ' + last_failure)
        self.record('PASS isolated bootstrap on loopback HTTP; separate HTTPS gateway and authenticated TLS SMTP are ready.')

    def gateway_configuration(self, config, release, maintenance, writer):
        server_config = {**config, 'mode': 'server', 'origin': self.origin}
        writer(server_config, release, maintenance)
        caddy = self.runtime / 'gateway/Caddyfile'
        text = caddy.read_text()
        require(text.count('https://127.0.0.1 {') == 1, 'Generated fixture gateway configuration changed unexpectedly.')
        # Literal IP clients omit SNI; keep chain and IP hostname verification on
        # while selecting the already-loaded loopback fixture certificate.
        text = text.replace('https_port 8443', 'https_port 8443\n    default_sni 127.0.0.1')
        text = text.replace('https://127.0.0.1 {', 'https://127.0.0.1 {\n    tls /etc/account-test/gateway.crt /etc/account-test/gateway.key')
        caddy.write_text(text)
        caddy.chmod(0o644)

    def token(self, email, action, after):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for path in sorted(self.capture.glob('*.eml'), key=lambda item: item.stat().st_mtime_ns, reverse=True):
                if path.name in after:
                    continue
                require(path.stat().st_size <= 32_768 and path.stat().st_mode & 0o077 == 0, 'SMTP capture is not private and bounded.')
                message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
                if message['To'] != email:
                    continue
                match = re.search(r'https://127\.0\.0\.1:\d+/\?accountAction=[^\s]+', message.get_content())
                require(match is not None, 'Captured SMTP message has no account link.')
                link = urlsplit(match.group(0)); query = parse_qs(link.query)
                require(link.scheme + '://' + link.netloc == self.origin and query.get('accountAction') == [action], 'SMTP link points outside the fixture.')
                token = query['token'][0]
                require(re.fullmatch('[A-Za-z0-9_-]{43}', token) is not None, 'Account challenge format is invalid.')
                self.tokens.append(token)
                return token
            time.sleep(.05)
        raise AssertionError('The expected private SMTP message was not captured.')

    def mail_snapshot(self):
        return {path.name for path in self.capture.glob('*.eml')}

    def verify(self):
        try:
            connection = http.client.HTTPSConnection('127.0.0.1', self.port, timeout=5)
            try:
                connection.request('GET', '/release.json'); connection.getresponse()
            finally:
                connection.close()
            raise AssertionError('An untrusted HTTPS client accepted the synthetic CA.')
        except ssl.SSLCertVerificationError:
            pass
        client = Client(self.origin, self.certificates / 'ca.crt'); client.bootstrap()
        require(client.json('GET', '/api/v1/accounts/config') == {'registrationEnabled': True}, 'HTTPS+SMTP registration gate is closed.')
        for headers in [{'Origin': 'https://untrusted.example.test'}, {'X-CSRF-Token': 'invalid'}, {'Host': 'untrusted.example.test'}]:
            client.request('POST', '/api/v1/accounts/register', {'email': 'forbidden@example.test', 'displayName': 'Synthetic', 'password': 'abc'}, headers=headers, expected=403)
        suffix = uuid.uuid4().hex[:12]
        email = 'docker.new+' + suffix + '@example.test'; unknown = 'unknown+' + suffix + '@example.test'
        before = self.mail_snapshot()
        accepted = client.json('POST', '/api/v1/accounts/register',
            {'email': '  Docker.New+' + suffix + '@Example.Test  ', 'displayName': 'Synthetic public', 'password': 'abc'}, expected=202)
        require(accepted == {'accepted': True}, 'Public registration response is not generic.')
        first_token = self.token(email, 'verify', before)
        client.request('POST', '/api/v1/session/login', {'email': email, 'password': 'abc'}, expected=401)
        before = self.mail_snapshot()
        require(client.json('POST', '/api/v1/accounts/verification/request', {'email': email}, expected=202) == accepted, 'Verification request response differs.')
        current_token = self.token(email, 'verify', before)
        require(current_token != first_token, 'Verification resend reused its challenge.')
        hashes = self.compose('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'traceweave', '-Atc',
            "SELECT t.token_hash FROM account_tokens t JOIN owners o ON o.id=t.owner_id WHERE o.email='" + email + "'", capture=True).splitlines()
        require(hashes == [hashlib.sha256(current_token.encode()).hexdigest()] and current_token not in hashes, 'PostgreSQL did not store only the current token digest.')
        client.request('POST', '/api/v1/accounts/verify-email', {'token': first_token}, expected=422)
        require(client.json('POST', '/api/v1/accounts/verify-email', {'token': current_token}) == accepted, 'Email verification failed.')
        client.request('POST', '/api/v1/accounts/verify-email', {'token': current_token}, expected=422)
        session = client.login(email.upper(), 'abc')
        require(session['user']['email'] == email, 'Canonical email missing in the authenticated session.')
        client.owner = session['user']['id']
        profile = client.json('PATCH', '/api/v1/profile', {'displayName': 'Synthetic renamed'})
        require(profile['displayName'] == 'Synthetic renamed' and profile['id'] == client.owner, 'Profile update changed identity or lost the name.')
        other = Client(self.origin, self.certificates / 'ca.crt'); other.bootstrap(); other.login(email, 'abc')
        changed = client.json('POST', '/api/v1/profile/password', {'currentPassword': 'abc', 'password': 'def'})
        client.csrf, client.owner = changed['csrfToken'], changed['user']['id']
        other.request('GET', '/api/v1/profile', expected=401)
        require(client.json('GET', '/api/v1/profile')['id'] == profile['id'], 'Password rotation lost the current account.')
        wrong = Client(self.origin, self.certificates / 'ca.crt'); wrong.bootstrap()
        wrong.request('POST', '/api/v1/session/login', {'email': email, 'password': 'abc'}, expected=401)
        other.bootstrap(); other.login(email, 'def')
        before = self.mail_snapshot()
        duplicate = wrong.json('POST', '/api/v1/accounts/register', {'email': email, 'displayName': 'Must not overwrite', 'password': 'zzz'}, expected=202)
        require(duplicate == accepted, 'Duplicate registration exposes account existence.')
        decoy = self.token(email, 'verify', before)
        wrong.request('POST', '/api/v1/accounts/verify-email', {'token': decoy}, expected=422)
        require(client.json('GET', '/api/v1/profile')['displayName'] == 'Synthetic renamed', 'Duplicate registration overwrote the account.')
        before = self.mail_snapshot()
        known_reply = wrong.json('POST', '/api/v1/accounts/password-reset/request', {'email': email}, expected=202)
        reset = self.token(email, 'reset', before)
        before = self.mail_snapshot()
        unknown_reply = wrong.json('POST', '/api/v1/accounts/password-reset/request', {'email': unknown}, expected=202)
        unknown_token = self.token(unknown, 'reset', before)
        require(known_reply == unknown_reply == accepted, 'Password reset reveals account eligibility.')
        wrong.request('POST', '/api/v1/accounts/password-reset/complete', {'token': unknown_token, 'password': 'ghi'}, expected=422)
        require(wrong.json('POST', '/api/v1/accounts/password-reset/complete', {'token': reset, 'password': 'ghi'}) == accepted, 'Password reset failed.')
        wrong.request('POST', '/api/v1/accounts/password-reset/complete', {'token': reset, 'password': 'ghi'}, expected=422)
        for previous in [client, other]:
            previous.request('GET', '/api/v1/profile', expected=401)
        final = Client(self.origin, self.certificates / 'ca.crt'); final.bootstrap()
        final.request('POST', '/api/v1/session/login', {'email': email, 'password': 'def'}, expected=401)
        final.login(email, 'ghi')
        require(final.json('GET', '/api/v1/profile')['displayName'] == 'Synthetic renamed', 'Recovery changed profile identity.')
        self.record('PASS verified HTTPS cookies, Origin/CSRF/Host rejection, email canonicalization, hashed one-use verification and resend.')
        self.record('PASS login/profile/password rotation, reset, invalid decoys and old-session revocation; known/unknown responses remain generic.')
        (self.capture / 'reject').write_text('synthetic-auth-failure\n'); (self.capture / 'reject').chmod(0o600)
        try:
            for address in [email, unknown]:
                result = wrong.json('POST', '/api/v1/accounts/password-reset/request', {'email': address}, expected=503)
                require(result['error']['code'] == 'mail_unavailable', 'SMTP authentication failure is not fail-closed.')
        finally:
            (self.capture / 'reject').unlink()
        self.record('PASS SMTP authentication failure returns generic503 for eligible and unknown accounts.')
        original_certificate = (self.certificates / 'smtp.crt').read_bytes()
        original_key = (self.certificates / 'smtp.key').read_bytes()
        try:
            self.compose('stop', '--timeout', '10', 'smtp')
            shutil.copyfile(self.certificates / 'untrusted.crt', self.certificates / 'smtp.crt')
            shutil.copyfile(self.certificates / 'untrusted.key', self.certificates / 'smtp.key')
            self.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '30', 'smtp')
            for address in [email, unknown]:
                result = wrong.json('POST', '/api/v1/accounts/password-reset/request', {'email': address}, expected=503)
                require(result['error']['code'] == 'mail_unavailable', 'Backend accepted an untrusted SMTP certificate.')
        finally:
            (self.certificates / 'smtp.crt').write_bytes(original_certificate)
            (self.certificates / 'smtp.key').write_bytes(original_key)
            self.compose('stop', '--timeout', '10', 'smtp')
            self.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '30', 'smtp')
        self.record('PASS actual Linux SMTP transport rejects an untrusted certificate; HTTPS clients also require trusted CA.')
        logs = self.compose('logs', '--no-color', '--tail', '200', 'backend', 'smtp', 'gateway', capture=True)
        require(not any(token in logs for token in self.tokens), 'A challenge appeared in a container log.')
        self.record('PASS no captured verification/reset challenge appeared in bounded backend/SMTP/gateway logs.')
        return email, profile['id']

    def lifecycle(self, email, owner_id):
        # The production controller performs real stop/start, readiness, history
        # and maintenance checks. Only test composition, TLS files and the HTTPS
        # CA client are adapted for this nonstandard loopback port. No HTTP or
        # database response is mocked.
        names = ['compose', 'load_config', 'caddy_config', 'public_request', 'execute']
        originals = {name: getattr(control, name) for name in names}
        self.config.update(mode='server', origin=self.origin, port=self.port)

        def compose(*arguments, config=None, release=None, capture=False, interactive=False, check=True):
            require(not interactive, 'Lifecycle test must not request interactive input.')
            if config:
                require(config['installId'] == self.config['installId'], 'Controller selected another installation.')
            if release:
                require(release == self.release, 'Controller selected another fixture release.')
            return self.command(['docker', 'compose', '--project-directory', str(ROOT), '-f', str(ROOT / 'compose.yaml'),
                '-f', str(ROOT / 'tests/compose.account-test.yaml'), *arguments], capture=capture, check=check)

        def execute(arguments, capture=False, interactive=False, check=True, env=None):
            require(not interactive, 'Lifecycle test must not request interactive input.')
            return self.command(arguments, capture=capture, check=check, environment=env)

        def public_request(path, config=None):
            client = Client(self.origin, self.certificates / 'ca.crt')
            expected = 503 if path in ['/', '/api/v1/session'] else 200
            body, _ = client.request('GET', path, expected=expected)
            return expected, body.decode()

        control.compose, control.execute = compose, execute
        control.load_config = lambda: self.config.copy()
        control.public_request = public_request
        control.caddy_config = lambda config, release, maintenance: self.gateway_configuration(
            config, release, maintenance, originals['caddy_config'])
        try:
            with control.operation_lock(), redirect_stdout(self.protocol), redirect_stderr(self.protocol):
                control.phase('ready', releaseId=self.release['releaseId'])
                control.stop()
                # Exercise the original .2 address that previously raced with
                # dynamic frontend/backend addresses, on this existing network.
                self.config['gatewayIP'] = str(ipaddress.ip_network(self.config['subnet']).network_address + 2)
                control.start()
                client = Client(self.origin, self.certificates / 'ca.crt'); client.bootstrap(); client.login(email, 'ghi')
                require(client.json('GET', '/api/v1/profile')['id'] == owner_id, 'First HTTPS stop/start lost the account.')
                control.stop()
                control.start()
                require(client.json('GET', '/api/v1/profile')['id'] == owner_id, 'Second HTTPS stop/start lost the session or account.')
                control.stop()
        finally:
            for name, original in originals.items():
                setattr(control, name, original)
        self.record('PASS two real production-controller HTTPS stop/start cycles, gateway .2 startup ordering, account/session persistence and maintenance503.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--test-root', default=str(TEST_ROOT), help='Approved synthetic namespace: workspace var/docker-tests or checkout runtime/tests_ci.')
    parser.add_argument('--initial-port', type=int, default=18081)
    parser.add_argument('--https-port', type=int, default=19443)
    parser.add_argument('--existing', action='store_true', help='Resume only this suite\'s marked synthetic runtime.')
    parser.add_argument('--protocol', default=str(PROJECT / 'var/accounts-docker-test.log'))
    arguments = parser.parse_args()
    runtime = Path(arguments.runtime).resolve()
    test_root = Path(arguments.test_root).resolve()
    require(test_root in {TEST_ROOT.resolve(), (ROOT / 'runtime/tests_ci').resolve()} and runtime.parent == test_root,
        'Account runtime must be an explicit child of the approved synthetic test root.')
    require(not Path(arguments.runtime).is_symlink() and not Path(arguments.test_root).is_symlink(), 'Synthetic runtime/root must not be symlinks.')
    require(arguments.initial_port != 18080 and arguments.https_port != 18080, 'The coordinator stack port18080 is reserved.')
    release_path = Path(arguments.release).resolve()
    release = control.validate_manifest(json.loads(release_path.read_text()))
    protocol_path = Path(arguments.protocol).resolve()
    require(protocol_path.is_relative_to((PROJECT / 'var').resolve()) or protocol_path.is_relative_to(test_root),
        'Private protocol must be inside project var/synthetic namespace.')
    protocol_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(protocol_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as protocol:
        fixture = Fixture(runtime, release, arguments.https_port, protocol)
        fixture.release_path = release_path
        control.RUNTIME = runtime
        try:
            fixture.prepare(arguments.initial_port, arguments.existing)
            email, owner_id = fixture.verify()
            fixture.lifecycle(email, owner_id)
        finally:
            # A partially failed bootstrap can already have created services.
            # Validate its marker, loopback origin and exact volume namespace
            # before attempting cleanup; preserve every volume on failure.
            if not fixture.config and (runtime / 'installation.json').is_file():
                fixture.load_synthetic_config(arguments.initial_port)
            if fixture.config:
                fixture.compose('stop', '--timeout', '120')
                fixture.record('Synthetic account stack stopped; private captures, certificates and all data volumes preserved.')


if __name__ == '__main__':
    main()
