"""Acceptance guard tests; real Docker/HTTP scenarios remain in integration.py."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.integration import Client, verify_file_report_archive


class NativeDownloadTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {'TW_VALIDATE_HTTP_CONTRACT': '0'}):
            self.client = Client('http://127.0.0.1:18080')
        self.client.cookie = 'rg_session=synthetic'
        self.client.owner = 'synthetic-account'
        self.client.contract = 'a' * 64
        self.client.csrf = 'synthetic-csrf'
        self.connection = Mock()
        self.connection.getresponse.return_value.status = 200
        self.connection.getresponse.return_value.read.return_value = b''
        self.connection.getresponse.return_value.getheaders.return_value = []

    def test_native_get_head_keep_session_without_custom_guard_headers(self):
        for method in ['GET', 'HEAD']:
            with self.subTest(method=method), patch('tools.integration.http.client.HTTPConnection', return_value=self.connection):
                self.client.request(method, '/synthetic/content', native=True)
                headers = self.connection.request.call_args.kwargs['headers']
                self.assertEqual(headers, {'Accept': '*/*', 'Cookie': 'rg_session=synthetic'})
                self.connection.close.assert_called()

    def test_ordinary_requests_keep_account_contract_origin_and_csrf(self):
        with patch('tools.integration.http.client.HTTPConnection', return_value=self.connection):
            self.client.request('POST', '/synthetic/commands', {})
        headers = self.connection.request.call_args.kwargs['headers']
        self.assertEqual(headers['X-TraceWeave-Account-ID'], self.client.owner)
        self.assertEqual(headers['X-TraceWeave-Client-Contract'], self.client.contract)
        self.assertEqual(headers['Origin'], self.client.origin)
        self.assertEqual(headers['X-CSRF-Token'], self.client.csrf)
        self.assertEqual(headers['Cookie'], self.client.cookie)

    def test_native_mode_cannot_mask_regression_with_custom_headers_or_mutation(self):
        invalid = [
            ('GET', {'headers': {'x-traceweave-account-id': 'synthetic'}}),
            ('HEAD', {'headers': {'X-TRACEWEAVE-CLIENT-CONTRACT': 'a' * 64}}),
            ('GET', {'value': {}}),
            ('HEAD', {'raw': b'body'}),
            ('POST', {}),
        ]
        with patch('tools.integration.http.client.HTTPConnection') as transport:
            for method, kwargs in invalid:
                with self.subTest(method=method, kwargs=kwargs), self.assertRaises(AssertionError):
                    self.client.request(method, '/synthetic/content', native=True, **kwargs)
            transport.assert_not_called()


class ExportArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = {
            'path': '/api/v1/investigations/investigation-identifier',
            'node': 'document-identifier',
            'title': 'Synthetic document',
            'body': 'Immutable synthetic content',
            'originals': {'binary-first': b'\x00\xff', 'pdf-identifier': b'%PDF-synthetic',
                          'empty-identifier': b'', 'binary-second': b'\x00\xff'},
        }
        self.attachments = {f'Attachments/Material-{index}.bin': data
                            for index, data in enumerate(self.fixture['originals'].values())}
        links = '\n'.join(f'[Original]({name})' for name in self.attachments)
        self.report = (self.fixture['title'] + '\n' + self.fixture['body'] + '\n' + links).encode()

    def archive(self, entries):
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w') as zipped:
            for name, data in entries.items():
                zipped.writestr(name, data)
        return result.getvalue()

    def readable(self, attachments=None, report=None, extra=None):
        return self.archive({'report.md': self.report if report is None else report,
                             **(self.attachments if attachments is None else attachments), **(extra or {})})

    def raw_entries(self):
        files = {asset: 'Attachments/Files/' + asset + '.bin' for asset in self.fixture['originals']}
        return {'metadata/files.json': json.dumps({'assets': files}),
                'metadata/snapshot.json': json.dumps({
                    'nodes': [{'id': self.fixture['node'], 'title': self.fixture['title'], 'bodyMarkdown': self.fixture['body']}],
                    'assets': [{'id': asset} for asset in files]}),
                **{files[asset]: data for asset, data in self.fixture['originals'].items()}}

    def test_both_formats_accept_two_identical_originals_and_an_empty_file(self):
        verify_file_report_archive(self.readable(), 'readable_report', self.fixture)
        verify_file_report_archive(self.archive(self.raw_entries()), 'obsidian_vault', self.fixture)

    def test_readable_rejects_missing_duplicate_empty_or_modified_original(self):
        for name in ['Attachments/Material-2.bin', 'Attachments/Material-3.bin']:
            attachments = dict(self.attachments)
            del attachments[name]
            with self.subTest(missing=name), self.assertRaisesRegex(AssertionError, 'omitted or deduplicated'):
                verify_file_report_archive(self.readable(attachments=attachments), 'readable_report', self.fixture)
        attachments = dict(self.attachments)
        attachments['Attachments/Material-0.bin'] += b'changed'
        with self.assertRaisesRegex(AssertionError, 'changed, omitted'):
            verify_file_report_archive(self.readable(attachments=attachments), 'readable_report', self.fixture)

    def test_readable_rejects_unlinked_original_or_leaked_metadata(self):
        with self.assertRaisesRegex(AssertionError, 'unlinked'):
            verify_file_report_archive(self.readable(report=self.report.replace(b'Attachments/Material-0.bin', b'missing')),
                                       'readable_report', self.fixture)
        with self.assertRaisesRegex(AssertionError, 'one report'):
            verify_file_report_archive(self.readable(extra={'metadata/snapshot.json': b'{}'}), 'readable_report', self.fixture)
        with self.assertRaisesRegex(AssertionError, 'internal identifiers'):
            verify_file_report_archive(self.readable(report=self.report + b'\ndocument-identifier'), 'readable_report', self.fixture)

    def test_raw_rejects_deduplicated_identity_and_changed_snapshot_document(self):
        entries = self.raw_entries()
        mapping = json.loads(entries['metadata/files.json'])
        mapping['assets']['binary-second'] = mapping['assets']['binary-first']
        entries['metadata/files.json'] = json.dumps(mapping)
        with self.assertRaisesRegex(AssertionError, 'deduplicated asset identities'):
            verify_file_report_archive(self.archive(entries), 'obsidian_vault', self.fixture)
        fixture = deepcopy(self.fixture)
        fixture['body'] = 'Changed live content'
        with self.assertRaisesRegex(AssertionError, 'lost the document content'):
            verify_file_report_archive(self.archive(self.raw_entries()), 'obsidian_vault', fixture)


if __name__ == '__main__':
    unittest.main()
