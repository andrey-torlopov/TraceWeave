"""Test-only validation of JSON HTTP responses against the canonical OpenAPI.

Importing this module needs only the standard library. Optional validation
dependencies are loaded when HTTPContractValidator is constructed. Nothing is
fetched from the network; diagnostics never include response values or keys.
"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts' / 'openapi.yaml'
METHODS = frozenset(('get', 'head', 'post', 'put', 'patch', 'delete', 'options', 'trace'))


class HTTPContractError(AssertionError):
    """A sanitized acceptance failure, without HTTP response contents."""


def _pointer(parts):
    return '#/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in parts)


class HTTPContractValidator:
    def __init__(self, contract_path=CONTRACT):
        try:
            from jsonschema import FormatChecker
            from tools.validate_contracts import ContractValidator, resolve_ref, strict_json, walk
        except ImportError:
            raise HTTPContractError('HTTP contract validation dependencies missing; install tools/requirements-validation.txt.') from None
        self._validator_type = ContractValidator
        self._format_checker = FormatChecker()
        self._strict_json = strict_json
        self._resolve_ref = resolve_ref
        try:
            # The canonical .yaml is JSON-compatible YAML, deliberately parsed
            # with the same strict UTF-8/JSON rules as wire contract fixtures.
            self.api = strict_json(Path(contract_path).read_bytes())
            if self.api.get('openapi') != '3.1.0':
                raise ValueError('unsupported OpenAPI version')
            for _, value in walk(self.api):
                if isinstance(value, dict) and '$ref' in value:
                    resolve_ref(self.api, value['$ref'])
            self._routes = []
            for template, item in self.api['paths'].items():
                segments = re.split(r'(\{[^{}]+\})', template)
                pattern = ''.join('[^/]+' if segment.startswith('{') else re.escape(segment) for segment in segments)
                self._routes.append((template, re.compile('^' + pattern + '$'), item))
            # OpenAPI gives concrete paths precedence over templated siblings.
            self._routes.sort(key=lambda route: (route[0].count('{'), -len(route[0])))
        except (OSError, ValueError, TypeError, KeyError):
            raise HTTPContractError('HTTP contract document is unavailable or invalid; canonical schemas required.') from None
        self._validators = {}

    def _operation(self, method, path):
        try:
            pathname = urlsplit(path).path
        except ValueError:
            raise HTTPContractError('HTTP contract violation: undeclared route.') from None
        if method.lower() not in METHODS:
            raise HTTPContractError('HTTP contract violation: undeclared method.')
        for template, pattern, item in self._routes:
            if pattern.fullmatch(pathname):
                operation = item.get(method.lower())
                if operation is None:
                    raise HTTPContractError('HTTP contract violation: undeclared method at ' + template + '.')
                return template, operation
        raise HTTPContractError('HTTP contract violation: undeclared route.')

    def _response(self, operation, status, location):
        response = operation['responses'].get(str(status))
        if response is None:
            raise HTTPContractError(location + ' undeclared response status.')
        if '$ref' in response:
            response = self._resolve_ref(self.api, response['$ref'])
        return response

    def validate(self, method, path, status, headers, body, *, require_json=False):
        """Validate JSON successes/errors; exclude HEAD and non-JSON media/HTML.

        A declared JSON-only response cannot evade validation by sending the
        wrong Content-Type. Explicit Client.json also requires declared JSON.
        Return the decoded value for JSON, or None for excluded response bodies.
        """
        if method.upper() == 'HEAD':
            return None
        content_type = next((value for name, value in headers.items() if name.lower() == 'content-type'), '')
        media_type = content_type.split(';', 1)[0].strip().lower()
        is_json = media_type == 'application/json' or media_type.endswith('+json')
        try:
            template, operation = self._operation(method, path)
        except HTTPContractError:
            if not is_json and not require_json:
                return None
            raise
        location = 'HTTP contract violation: ' + method.upper() + ' ' + template + ' status ' + str(status) + ':'
        response = self._response(operation, status, location)
        content = response.get('content', {})
        declared_json = {name: definition for name, definition in content.items()
                         if name == 'application/json' or name.endswith('+json')}
        if not is_json:
            if require_json or (declared_json and len(declared_json) == len(content)):
                raise HTTPContractError(location + ' JSON Content-Type required.')
            return None
        if media_type not in declared_json:
            raise HTTPContractError(location + ' undeclared JSON Content-Type.')
        schema = declared_json[media_type].get('schema')
        if schema is None:
            raise HTTPContractError(location + ' response schema missing.')
        try:
            value = self._strict_json(body)
        except (ValueError, UnicodeError):
            raise HTTPContractError(location + ' invalid UTF-8 JSON body.') from None
        key = (method.lower(), template, str(status), media_type)
        if key not in self._validators:
            # Keep local component refs rooted at the complete canonical
            # document, including refs inside oneOf/allOf response schemas.
            self._validators[key] = self._validator_type({**self.api, **schema}, format_checker=self._format_checker)
        error = next(self._validators[key].iter_errors(value), None)
        if error is not None:
            # Instance paths and ValidationError.message may contain confidential
            # values or unknown property names. Only schema paths are safe.
            raise HTTPContractError(location + ' schema ' + _pointer(error.absolute_schema_path) + ' violation.') from None
        return value
