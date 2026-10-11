"""The readable report is revision-based and preserves the existing export modes."""
import unittest
from test_contracts import API, example, schema_validator, uid
from jsonschema import ValidationError


class ReadableReportContractTests(unittest.TestCase):
    def test_both_revision_based_formats_are_supported(self):
        for kind in ('obsidian_vault', 'readable_report'):
            schema_validator('ExportCreate', API).validate(dict(kind=kind, idempotencyKey=uid(92), sourceRevision=42))
            job = example('ExportJob')
            job.update(kind=kind, sourceRevision=42, reportSnapshotId=None)
            schema_validator('ExportJob', API).validate(job)

    def test_report_rejects_missing_revision_and_snapshot_parameters(self):
        valid = dict(kind='readable_report', idempotencyKey=uid(93), sourceRevision=0)
        for invalid in ({'sourceRevision': None}, {'sourceRevision': -1}, {'sourceRevision': True}, {'reportSnapshotId': uid(94)}, {'includeLayout': True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                schema_validator('ExportCreate', API).validate({**valid, **invalid})
        del valid['sourceRevision']
        with self.assertRaises(ValidationError):
            schema_validator('ExportCreate', API).validate(valid)
