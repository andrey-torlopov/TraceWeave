"""File attachments stay inert while preserving upload/archive byte limits."""
import copy
import unittest
from test_contracts import API, ARCHIVE, example, schema_validator, archive_validator, uid
from jsonschema import ValidationError


class FileAttachmentContractTests(unittest.TestCase):
    def test_generic_and_pdf_uploads_accept_empty_and_maximum_size(self):
        for mime in ('application/octet-stream', 'application/pdf'):
            for size in (0, 536870912):
                value = dict(idempotencyKey=uid(90), originalName='arbitrary.data', expectedMimeType=mime, expectedByteSize=size)
                schema_validator('UploadCreate', API).validate(value)
            value['expectedByteSize'] = 536870913
            with self.assertRaises(ValidationError):
                schema_validator('UploadCreate', API).validate(value)

    def test_file_assets_are_accepted_in_api_and_portable_archive(self):
        for mime in ('application/octet-stream', 'application/pdf'):
            value = example('Asset')
            value.update(mediaKind='file', mimeType=mime)
            schema_validator('Asset', API).validate(value)
            archive_validator('Asset', ARCHIVE).validate(value)
        value['mimeType'] = 'text/html'
        with self.assertRaises(ValidationError):
            schema_validator('Asset', API).validate(value)

    def test_active_content_requires_generic_profile(self):
        for mime in ('text/html', 'image/svg+xml', 'application/javascript'):
            value = dict(idempotencyKey=uid(91), originalName='active.html', expectedMimeType=mime, expectedByteSize=10)
            with self.assertRaises(ValidationError):
                schema_validator('UploadCreate', API).validate(value)
            value['expectedMimeType'] = 'application/octet-stream'
            schema_validator('UploadCreate', API).validate(value)

    def test_file_capabilities_declare_pdf_and_wildcard(self):
        for mime, extensions in [('application/pdf', ['pdf']), ('application/octet-stream', ['*'])]:
            schema_validator('MediaFormat', API).validate(dict(mimeType=mime, mediaKind='file', extensions=extensions))
