"""Response boundary tests using canonical schemas and isolated HTTP replies."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.http_contract import HTTPContractError, HTTPContractValidator
from tools.integration import Client

JSON_HEADERS = {'Content-Type': 'application/json; charset=utf-8'}
INVESTIGATION = '/api/v1/investigations/30000000-0000-4000-8000-000000000001'
CONTENT = INVESTIGATION + '/assets/30000000-0000-4000-8000-000000000002/content'
SECRET = 'confidential-password-token@example.test'


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class HTTPContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = HTTPContractValidator()
        cls.schemas = cls.validator.api['components']['schemas']

    def example(self, name):
        return deepcopy(self.schemas[name]['examples'][0])

    def validate(self, value, method='GET', path='/api/v1/session', status=200, headers=JSON_HEADERS):
        return self.validator.validate(method, path, status, headers, wire(value))

    def assert_private_failure(self, action):
        with self.assertRaises(HTTPContractError) as caught:
            action()
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        return str(caught.exception)

    def test_get_and_post_nested_component_refs(self):
        anonymous = self.example('SessionAnonymous')
        authenticated = self.example('SessionAuthenticated')
        self.assertEqual(self.validate(anonymous), anonymous)
        self.assertEqual(self.validate(authenticated, 'POST', '/api/v1/session/login'), authenticated)
        created = self.example('InvestigationCreated')
        self.assertEqual(self.validate(created, 'POST', '/api/v1/investigations', 201), created)

    def test_template_query_and_error_statuses(self):
        for method, path, status, schema in [
            ('GET', INVESTIGATION + '?cursor=' + SECRET, 404, 'ErrorNotFound'),
            ('POST', INVESTIGATION + '/commands', 409, 'ErrorAccountChanged'),
            ('GET', '/api/v1/session', 503, 'ErrorServiceMaintenance'),
        ]:
            with self.subTest(method=method, status=status):
                example = self.example(schema)
                self.assertEqual(self.validate(example, method, path, status), example)

    def test_extra_top_level_and_nested_fields_are_rejected_without_keys(self):
        for nested in [False, True]:
            value = self.example('SessionAuthenticated')
            target = value['user'] if nested else value
            target[SECRET] = SECRET
            message = self.assert_private_failure(lambda: self.validate(value, 'POST', '/api/v1/session/login'))
            self.assertIn('schema #/', message)

    def test_required_null_wrong_type_and_missing_fields(self):
        for field, invalid in [('user', None), ('csrfToken', 123), ('authenticated', None)]:
            value = self.example('SessionAuthenticated')
            value[field] = invalid
            with self.subTest(field=field):
                self.assert_private_failure(lambda: self.validate(value, 'POST', '/api/v1/session/login'))
        value = self.example('SessionAuthenticated')
        del value['user']['emailVerified']
        self.assert_private_failure(lambda: self.validate(value, 'POST', '/api/v1/session/login'))

    def test_uuid_email_and_real_datetime_formats(self):
        for field, invalid in [('id', SECRET), ('email', 'missing-at-sign')]:
            value = self.example('SessionAuthenticated')
            value['user'][field] = invalid
            self.assert_private_failure(lambda: self.validate(value, 'POST', '/api/v1/session/login'))
        value = self.example('SessionAuthenticated')
        # Matches the timestamp pattern, but is not a calendar date.
        value['expiresAt'] = '2026-02-30T12:00:00.000Z'
        self.assert_private_failure(lambda: self.validate(value, 'POST', '/api/v1/session/login'))

    def test_error_details_cannot_change_null_to_object(self):
        value = self.example('ErrorServiceMaintenance')
        value['error']['details'] = {SECRET: SECRET}
        self.assert_private_failure(lambda: self.validate(value, status=503))

    def test_status_selects_error_schema_not_success_schema(self):
        self.assert_private_failure(lambda: self.validate(self.example('SessionAnonymous'), status=404))
        self.assert_private_failure(lambda: self.validate(self.example('ErrorNotFound'), status=200))
        self.assert_private_failure(lambda: self.validate(self.example('ErrorAccountChanged'), status=404))

    def test_unknown_route_method_and_status_refused(self):
        value = self.example('SessionAnonymous')
        for method, path, status in [
            ('GET', '/api/v1/' + SECRET + '?token=' + SECRET, 200),
            ('POST', '/api/v1/session', 200),
            ('GET', '/api/v1/session', 299),
        ]:
            self.assert_private_failure(lambda: self.validate(value, method, path, status))

    def test_json_content_type_is_declared_and_required(self):
        value = self.example('SessionAnonymous')
        for headers in [{}, {'Content-Type': 'text/plain'}, {'Content-Type': 'application/problem+json'}]:
            self.assert_private_failure(lambda: self.validate(value, headers=headers))
        self.assertEqual(self.validate(value, headers={'content-type': 'Application/JSON; charset=UTF-8'}), value)

    def test_media_and_html_excluded_but_media_json_error_validated(self):
        self.assertIsNone(self.validator.validate('GET', CONTENT, 200, {'Content-Type': 'image/png'}, b'not JSON'))
        self.assertIsNone(self.validator.validate('GET', '/', 503, {'Content-Type': 'text/html'}, b'<html>maintenance</html>'))
        error = self.example('ErrorNotFound')
        self.assertEqual(self.validate(error, path=CONTENT, status=404), error)
        error['error'][SECRET] = SECRET
        self.assert_private_failure(lambda: self.validate(error, path=CONTENT, status=404))

    def test_head_excludes_absent_body_even_for_json_error(self):
        self.assertIsNone(self.validator.validate('HEAD', CONTENT, 404, JSON_HEADERS, b''))

    def test_explicit_json_call_rejects_html_even_without_known_route(self):
        self.assert_private_failure(lambda: self.validator.validate('GET', '/' + SECRET, 200,
            {'Content-Type': 'text/html'}, b'<html></html>', require_json=True))

    def test_strict_json_rejects_duplicate_nonfinite_surrogate_and_encoding(self):
        for body in [b'{"' + SECRET.encode() + b'":1,"' + SECRET.encode() + b'":2}',
                     b'{"value":NaN}', b'{"value":1e999}', b'{"value":"\\ud800"}',
                     '{"value":1}'.encode('utf-16'), b'not JSON ' + SECRET.encode()]:
            with self.subTest(body_kind=type(body).__name__):
                self.assert_private_failure(lambda: self.validator.validate('GET', '/api/v1/session', 200, JSON_HEADERS, body))

    def test_component_response_ref_and_custom_utf8_constraint(self):
        api = deepcopy(self.validator.api)
        api['components']['responses'] = {'StrictText': {'description': 'test boundary', 'content': {
            'application/json': {'schema': {'type': 'string', 'maxLength': 3, 'x-maxUtf8Bytes': 3}}}}}
        api['paths']['/contract-test'] = {'get': {'responses': {'200': {'$ref': '#/components/responses/StrictText'}}}}
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / 'openapi.yaml'
            contract.write_bytes(wire(api))
            validator = HTTPContractValidator(contract)
            self.assertEqual(validator.validate('GET', '/contract-test', 200, JSON_HEADERS, wire('abc')), 'abc')
            self.assert_private_failure(lambda: validator.validate('GET', '/contract-test', 200, JSON_HEADERS, wire('яя')))

    def test_concrete_route_precedes_template_and_external_refs_are_forbidden(self):
        api = deepcopy(self.validator.api)
        api['paths']['/api/v1/investigations/concrete'] = {'get': {'responses': {'200': {'description': 'test boundary',
            'content': {'application/json': {'schema': {'const': 'concrete'}}}}}}}
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / 'openapi.yaml'
            contract.write_bytes(wire(api))
            validator = HTTPContractValidator(contract)
            self.assertEqual(validator.validate('GET', '/api/v1/investigations/concrete', 200, JSON_HEADERS, wire('concrete')), 'concrete')
            api['components']['schemas']['External'] = {'$ref': 'https://example.test/' + SECRET}
            contract.write_bytes(wire(api))
            self.assert_private_failure(lambda: HTTPContractValidator(contract))


class FakeReply:
    def __init__(self, status, body, headers):
        self.status = status
        self.body = body
        self.headers = headers

    def read(self, limit):
        return self.body[:limit]

    def getheaders(self):
        return list(self.headers.items())


class FakeConnection:
    def __init__(self, reply):
        self.reply = reply
        self.closed = False

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return self.reply

    def close(self):
        self.closed = True


class ClientHookTests(unittest.TestCase):
    def call(self, reply, action, flag='1'):
        connection = FakeConnection(reply)
        with patch.dict(os.environ, {'TW_VALIDATE_HTTP_CONTRACT': flag}):
            # Initialize optional packages before replacing stdlib HTTPConnection:
            # urllib3 inspects the real class while importing validation tooling.
            client = Client('http://127.0.0.1:18084')
            with patch('tools.integration.http.client.HTTPConnection', return_value=connection):
                try:
                    return action(client)
                finally:
                    self.assertTrue(connection.closed)

    def test_request_checks_expected_json_errors_not_only_json_helper(self):
        api = json.loads((ROOT / 'contracts/openapi.yaml').read_text())
        for status, name in [(404, 'ErrorNotFound'), (409, 'ErrorAccountChanged'), (503, 'ErrorServiceMaintenance')]:
            valid = deepcopy(api['components']['schemas'][name]['examples'][0])
            reply = FakeReply(status, wire(valid), JSON_HEADERS)
            self.assertEqual(self.call(reply, lambda client: client.request('GET', INVESTIGATION, expected=status))[0], wire(valid))
            valid['error'][SECRET] = SECRET
            with self.assertRaises(HTTPContractError) as caught:
                self.call(FakeReply(status, wire(valid), JSON_HEADERS), lambda client: client.request('GET', INVESTIGATION, expected=status))
            self.assertNotIn(SECRET, str(caught.exception))

    def test_json_helper_requires_declared_json_content_type(self):
        with self.assertRaises(HTTPContractError):
            self.call(FakeReply(200, b'{}', {'Content-Type': 'text/html'}), lambda client: client.json('GET', '/'))

    def test_unexpected_status_does_not_print_body_query_or_values(self):
        api = json.loads((ROOT / 'contracts/openapi.yaml').read_text())
        error = deepcopy(api['components']['schemas']['ErrorNotFound']['examples'][0])
        error['error']['message'] = SECRET
        with self.assertRaises(AssertionError) as caught:
            self.call(FakeReply(404, wire(error), JSON_HEADERS), lambda client: client.request('GET', INVESTIGATION + '?token=' + SECRET))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_flag_disabled_preserves_stdlib_json_behavior(self):
        self.assertEqual(self.call(FakeReply(200, wire({SECRET: None}), {}), lambda client: client.json('GET', '/outside-contract'), flag='0'), {SECRET: None})
        # Verify lazy imports in a fresh interpreter with optional packages
        # explicitly unavailable, rather than relying on this test's imports.
        script = '''import importlib.abc, os, sys
class DenyOptional(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in ('jsonschema', 'openapi_spec_validator', 'yaml'):
   raise ImportError('optional validation package unavailable')
sys.meta_path.insert(0, DenyOptional())
from tools.integration import Client
assert Client('http://127.0.0.1:18084').http_contract is None
assert 'tools.http_contract' not in sys.modules
'''
        env = {**os.environ, 'TW_VALIDATE_HTTP_CONTRACT': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
