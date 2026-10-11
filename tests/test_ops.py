"""Backup and restore integrity checks without PostgreSQL or user data."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("traceweave_ops_test_subject", TOOLS / "ops.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.statement = ""

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, statement, parameters=None):
        self.statement = statement
        self.connection.statements.append((statement, parameters))

    def fetchone(self):
        if "pg_try_advisory_lock" in self.statement: return (self.connection.lock_acquired,)
        if "pg_tables" in self.statement: return (self.connection.table_count,)
        if "pg_database_size" in self.statement: return (self.connection.database_size,)
        if self.statement == "SELECT 1": return (1,)
        raise AssertionError("Unexpected synthetic SQL: " + self.statement)


class FakeConnection:
    def __init__(self, lock_acquired=True, table_count=0, database_size=1024 * 1024):
        self.lock_acquired = lock_acquired
        self.table_count = table_count
        self.database_size = database_size
        self.statements = []
        self.closed = False

    def cursor(self): return FakeCursor(self)
    def close(self): self.closed = True


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="traceweave-ops-test-")
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "state"
        self.data = Path(self.temporary.name) / "data"
        self.database_capacity = Path(self.temporary.name) / "database-capacity"
        self.state.mkdir(mode=0o700)
        (self.data / "blobs").mkdir(parents=True, mode=0o700)
        self.database_capacity.mkdir(mode=0o700)
        self.addCleanup(patch.stopall)
        patch.object(ops, "STATE", self.state).start()
        patch.object(ops, "DATA", self.data).start()
        patch.object(ops, "DATABASE_CAPACITY", self.database_capacity).start()
        self.disk_usage = patch.object(ops.shutil, "disk_usage", return_value=SimpleNamespace(free=1024 * 1024 * 1024)).start()
        self.pg_restore = patch.object(ops.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)).start()
        self.name = "synthetic-backup"
        self.root = self.state / "backups" / self.name
        self.root.mkdir(parents=True, mode=0o700)
        self.contents = b"Synthetic immutable original.\n"
        digest = hashlib.sha256(self.contents).hexdigest()
        self.key = "images/" + digest[:2] + "/" + digest
        self.original = self.root / "blobs" / self.key
        self.original.parent.mkdir(parents=True, mode=0o700)
        self.original.write_bytes(self.contents)
        (self.root / "database.dump").write_bytes(b"Synthetic dump checked by mocked pg_restore.\n")
        self.entry = {"path": self.key, "bytes": len(self.contents), "sha256": digest}
        self.migrations = [{"version": 1, "sha256": "a" * 64}]
        self.value = {
            "formatVersion": 1, "postgresVersion": "18.6", "migrations": self.migrations,
            "databaseBytes": 1024 * 1024,
            "release": {"releaseId": "synthetic-1", "migrations": self.migrations},
            "dumpSHA256": ops.sha(self.root / "database.dump"),
            "originals": [self.entry], "databaseOriginals": [self.entry],
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.value))

    def test_valid_backup_checks_dump_original_sizes_hashes_and_archive_listing(self):
        root, value = ops.validate_backup(self.name)
        self.assertEqual(root, self.root)
        self.assertEqual(value, self.value)
        self.pg_restore.assert_called_once_with(["pg_restore", "--list", str(self.root / "database.dump")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    def test_invalid_name_cannot_escape_installation_backup_directory(self):
        for name in ["../synthetic-backup", "/tmp/backup", "a/b", "", ".", "backup.name"]:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                ops.validate_backup(name)
        self.pg_restore.assert_not_called()

    def test_dump_corruption_is_rejected_before_archive_parser(self):
        (self.root / "database.dump").write_bytes(b"altered")
        with self.assertRaisesRegex(RuntimeError, "dump checksum"):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_original_corruption_size_and_hash_are_rejected(self):
        for contents in [b"short", b"X" * len(self.contents)]:
            with self.subTest(contents=contents):
                self.original.write_bytes(contents)
                with self.assertRaisesRegex(RuntimeError, "original checksum"):
                    ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_manifest_rejects_duplicate_or_traversal_original_keys(self):
        variants = [[self.entry, self.entry], [{**self.entry, "path": "../../outside"}], [{**self.entry, "path": "images/00/not-a-digest"}]]
        for originals in variants:
            with self.subTest(originals=originals):
                self.value["originals"] = originals
                self.write_manifest()
                with self.assertRaisesRegex(RuntimeError, "original key"):
                    ops.validate_backup(self.name)

    def test_database_original_references_must_match_verified_files_before_restore(self):
        cases = [[self.entry, self.entry], [{**self.entry, "bytes": self.entry["bytes"] + 1}],
                 [{**self.entry, "sha256": "a" * 64}],
                 [{**self.entry, "path": "aa/" + "a" * 64}]]
        for references in cases:
            with self.subTest(references=references):
                self.value["databaseOriginals"] = references
                self.write_manifest()
                with self.assertRaises(RuntimeError):
                    ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_missing_referenced_original_is_rejected_even_when_manifest_file_set_matches(self):
        self.value["originals"] = []
        self.original.unlink()
        self.write_manifest()
        with self.assertRaises(RuntimeError):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_backup_release_history_must_match_dump_history_before_restore(self):
        self.value["release"]["migrations"] = [{"version": 1, "sha256": "b" * 64}]
        self.write_manifest()
        with self.assertRaises(RuntimeError):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_extra_original_or_unexpected_top_level_file_is_rejected(self):
        paths = [self.root / "blobs" / "aa" / ("a" * 64), self.root / "database.dump.extra", self.root / "manifest.json.extra", self.root / "other" / "private"]
        for path in paths:
            with self.subTest(path=path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unexpected")
                with self.assertRaisesRegex(RuntimeError, "Unexpected"):
                    ops.validate_backup(self.name)
                path.unlink()
        self.pg_restore.assert_not_called()

    def test_missing_original_or_dump_cannot_validate(self):
        for path in [self.original, self.root / "database.dump"]:
            with self.subTest(path=path):
                content = path.read_bytes()
                path.unlink()
                with self.assertRaises((RuntimeError, OSError)):
                    ops.validate_backup(self.name)
                path.write_bytes(content)

    def test_backup_symlinks_are_rejected_at_root_file_and_directory(self):
        linked_root = self.state / "backups" / "linked-root"
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "real directory"):
            ops.validate_backup("linked-root")
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(self.contents)
        self.original.unlink()
        self.original.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "Symlinks"):
            ops.validate_backup(self.name)
        self.original.unlink()
        self.original.write_bytes(self.contents)
        linked_dir = self.root / "blobs" / "linked-dir"
        linked_dir.symlink_to(outside.parent, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "Symlinks"):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation unavailable")
    def test_special_files_are_rejected_without_reading_or_blocking(self):
        fifo = self.root / "blobs" / "fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(RuntimeError, "special files"):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def test_unsupported_backup_version_is_rejected(self):
        for change in [{"formatVersion": 2}, {"postgresVersion": "17.6"}]:
            with self.subTest(change=change):
                original = copy.deepcopy(self.value)
                self.value.update(change)
                self.write_manifest()
                with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                    ops.validate_backup(self.name)
                self.value = original

    def test_invalid_archive_listing_is_not_reported_as_valid(self):
        self.pg_restore.side_effect = subprocess.CalledProcessError(1, "pg_restore")
        with self.assertRaises(subprocess.CalledProcessError):
            ops.validate_backup(self.name)

    def test_database_size_is_required_positive_integer_before_archive_listing(self):
        for size in [None, 0, -1, True, False, "1048576", 1.5]:
            with self.subTest(size=size):
                self.value["databaseBytes"] = size
                self.write_manifest()
                with self.assertRaisesRegex(RuntimeError, "databaseBytes"):
                    ops.validate_backup(self.name)
        del self.value["databaseBytes"]
        self.write_manifest()
        with self.assertRaisesRegex(RuntimeError, "databaseBytes"):
            ops.validate_backup(self.name)
        self.pg_restore.assert_not_called()

    def backup_patches(self, connection):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(ops, "connect", return_value=connection))
        def dump(arguments, c, output=None):
            self.assertEqual(arguments[0], "pg_dump")
            self.assertIs(c, connection)
            output.write(b"Synthetic backup dump.\n")
        process = stack.enter_context(patch.object(ops, "checked_process", side_effect=dump))
        stack.enter_context(patch.object(ops, "snapshot", return_value=("18.6", [self.entry])))
        stack.enter_context(patch.object(ops, "history", return_value=self.migrations))
        stack.enter_context(patch.object(ops, "operator_owned"))
        stack.enter_context(patch.object(ops.os, "chown"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        source = self.data / "blobs" / self.key
        source.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        source.write_bytes(self.contents)
        (self.state / "release.json").write_text(json.dumps(self.value["release"]))
        return stack, process

    def test_backup_records_actual_database_size_and_accepts_exact_capacity(self):
        connection = FakeConnection(database_size=3 * 1024 * 1024)
        stack, process = self.backup_patches(connection)
        required = 2 * connection.database_size + len(self.contents) + 64 * 1024 * 1024
        self.disk_usage.return_value.free = required
        with stack:
            ops.backup("new-backup")
        process.assert_called_once()
        value = json.loads((self.state / "backups" / "new-backup" / "manifest.json").read_text())
        self.assertEqual(value["databaseBytes"], connection.database_size)
        self.assertEqual(value["originals"], [self.entry])
        self.assertIn(("SELECT pg_database_size(current_database())", None), connection.statements)
        self.disk_usage.assert_called_once_with(self.state / "backups")
        self.assertTrue(connection.closed)

    def test_backup_verify_restore_preserves_files_and_existing_storage_categories(self):
        fixtures = Path(__file__).parent / "fixtures" / "media"
        payloads = {}
        for category, contents in [
            ("", (fixtures / "synthetic.txt").read_bytes()),
            ("images", (fixtures / "synthetic.png").read_bytes()),
            ("audio", (fixtures / "synthetic.wav").read_bytes()),
            ("video", (fixtures / "synthetic.mp4").read_bytes()),
            ("files", b"\x00\xffSynthetic arbitrary attachment\x00"),
            ("files", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
            ("files", b""),
        ]:
            digest = hashlib.sha256(contents).hexdigest()
            key = (category + "/" if category else "") + digest[:2] + "/" + digest
            payloads[key] = contents
            original = self.data / "blobs" / key
            original.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            original.write_bytes(contents)
            original.chmod(0o400)
        entries = [{"path": key, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
                   for key, contents in sorted(payloads.items())]
        (self.state / "release.json").write_text(json.dumps(self.value["release"]))
        backup_connection = FakeConnection()

        def dump(arguments, connection, output=None):
            self.assertEqual(arguments[0], "pg_dump")
            self.assertIs(connection, backup_connection)
            output.write(b"Synthetic mixed original database dump.\n")

        with patch.object(ops, "connect", return_value=backup_connection), \
                patch.object(ops, "snapshot", return_value=("18.6", entries)), \
                patch.object(ops, "history", return_value=self.migrations), \
                patch.object(ops, "checked_process", side_effect=dump) as dumping, \
                patch.object(ops, "operator_owned"), patch.object(ops.os, "chown"), \
                contextlib.redirect_stdout(io.StringIO()):
            ops.backup("mixed-originals")
        dumping.assert_called_once()
        self.assertTrue(backup_connection.closed)
        backup_root, manifest = ops.validate_backup("mixed-originals")
        self.assertEqual(manifest["originals"], entries)
        self.assertEqual(manifest["databaseOriginals"], entries)
        self.assertEqual(manifest["dumpSHA256"], ops.sha(backup_root / "database.dump"))

        restored_data = Path(self.temporary.name) / "restored-data"
        (restored_data / "blobs").mkdir(parents=True, mode=0o700)
        restore_connection = FakeConnection()
        with patch.object(ops, "DATA", restored_data), \
                patch.object(ops, "connect", return_value=restore_connection), \
                patch.object(ops, "snapshot", return_value=("18.6", entries)), \
                patch.object(ops, "history", return_value=self.migrations), \
                patch.object(ops, "checked_process") as restoring, \
                patch.object(ops.os, "chown"), contextlib.redirect_stdout(io.StringIO()):
            ops.restore("mixed-originals")
        restoring.assert_called_once()
        self.assertEqual(restoring.call_args.args[0][0], "pg_restore")
        self.assertTrue(restore_connection.closed)
        for key, contents in payloads.items():
            with self.subTest(storage_key=key):
                original = self.data / "blobs" / key
                backup_file = backup_root / "blobs" / key
                restored = restored_data / "blobs" / key
                for path in [original, backup_file, restored]:
                    self.assertEqual(path.read_bytes(), contents)
                    self.assertEqual(ops.sha(path), hashlib.sha256(contents).hexdigest())
                self.assertEqual(stat.S_IMODE(original.stat().st_mode), 0o400)
                self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o400)
        self.assertEqual(sorted(path.relative_to(restored_data / "blobs").as_posix()
                                for path in ops.safe_files(restored_data / "blobs")), sorted(payloads))

    def test_file_storage_keys_reject_traversal_and_bad_digest_before_restore(self):
        digest = self.entry["sha256"]
        invalid_keys = ["files/../" + digest, "/files/aa/" + digest,
                        "files/aa/" + digest[:-1], "files/aa/" + "g" * 64,
                        "files/aa/" + digest + ".bin", "files\\aa\\" + digest]
        for key in invalid_keys:
            with self.subTest(storage_key=key):
                self.value["originals"] = [{**self.entry, "path": key}]
                self.write_manifest()
                with patch.object(ops, "connect") as connecting, \
                        patch.object(ops, "checked_process") as process:
                    with self.assertRaisesRegex(RuntimeError, "original key"):
                        ops.restore(self.name)
                connecting.assert_not_called()
                process.assert_not_called()
        self.pg_restore.assert_not_called()
        self.assertEqual(list((self.data / "blobs").iterdir()), [])

    def test_files_symlink_rejected_before_backup_or_restore_mutation(self):
        outside = Path(self.temporary.name) / "outside-file"
        outside.write_bytes(b"Synthetic file outside the originals directory.")
        key = "files/aa/" + "a" * 64
        linked_original = self.data / "blobs" / key
        linked_original.parent.mkdir(parents=True, mode=0o700)
        linked_original.symlink_to(outside)
        connection = FakeConnection()
        stack, process = self.backup_patches(connection)
        with stack, self.assertRaisesRegex(RuntimeError, "Symlinks"):
            ops.backup("linked-files")
        process.assert_not_called()
        self.assertFalse((self.state / "backups" / "linked-files").exists())
        linked_backup = self.root / "blobs" / key
        linked_backup.parent.mkdir(parents=True, mode=0o700)
        linked_backup.symlink_to(outside)
        with patch.object(ops, "connect") as connecting, \
                patch.object(ops, "checked_process") as restoring:
            with self.assertRaisesRegex(RuntimeError, "Symlinks"):
                ops.restore(self.name)
        connecting.assert_not_called()
        restoring.assert_not_called()
        self.pg_restore.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"Synthetic file outside the originals directory.")

    def test_file_digest_mismatch_rejected_before_restore_mutation(self):
        key = "files/" + self.entry["sha256"][:2] + "/" + self.entry["sha256"]
        corrupted = self.root / "blobs" / key
        corrupted.parent.mkdir(parents=True, mode=0o700)
        self.original.rename(corrupted)
        corrupted.write_bytes(b"X" * len(self.contents))
        entry = {**self.entry, "path": key}
        self.value.update(originals=[entry], databaseOriginals=[entry])
        self.write_manifest()
        with patch.object(ops, "connect") as connecting, \
                patch.object(ops, "checked_process") as process, \
                patch.object(ops, "copy_file") as copying:
            with self.assertRaisesRegex(RuntimeError, "original checksum"):
                ops.restore(self.name)
        connecting.assert_not_called()
        process.assert_not_called()
        copying.assert_not_called()
        self.pg_restore.assert_not_called()
        self.assertEqual(list((self.data / "blobs").iterdir()), [])

    def test_backup_low_disk_counts_unreferenced_originals_and_writes_nothing(self):
        connection = FakeConnection()
        stack, process = self.backup_patches(connection)
        orphan = b"Unreferenced immutable original retained for recovery.\n"
        digest = hashlib.sha256(orphan).hexdigest()
        source = self.data / "blobs" / digest[:2] / digest
        source.parent.mkdir(parents=True, mode=0o700)
        source.write_bytes(orphan)
        required = 2 * connection.database_size + len(self.contents) + len(orphan) + 64 * 1024 * 1024
        self.disk_usage.return_value.free = required - 1
        with stack, patch.object(ops, "copy_file") as copying:
            with self.assertRaisesRegex(RuntimeError, "Insufficient free disk space for backup"):
                ops.backup("low-capacity")
        process.assert_not_called()
        copying.assert_not_called()
        self.assertFalse((self.state / "backups" / "low-capacity").exists())
        self.assertEqual(source.read_bytes(), orphan)
        self.assertTrue(connection.closed)

    def test_backup_invalid_database_size_fails_before_dump_or_destination_creation(self):
        for size in [0, -1, True, "1048576"]:
            with self.subTest(size=size):
                connection = FakeConnection(database_size=size)
                stack, process = self.backup_patches(connection)
                with stack, self.assertRaisesRegex(RuntimeError, "positive integer"):
                    ops.backup("invalid-size")
                process.assert_not_called()
                self.assertFalse((self.state / "backups" / "invalid-size").exists())
                self.assertTrue(connection.closed)

    def test_restore_checks_both_target_filesystems_before_connecting_or_mutating(self):
        required = 2 * self.value["databaseBytes"] + len(self.contents) + 64 * 1024 * 1024
        for low_path in [self.data, self.database_capacity]:
            with self.subTest(filesystem=low_path):
                self.disk_usage.side_effect = lambda path: SimpleNamespace(free=required - 1 if path == low_path else required)
                with patch.object(ops, "connect") as connecting, patch.object(ops, "checked_process") as process, patch.object(ops, "copy_file") as copying:
                    with self.assertRaisesRegex(RuntimeError, "Insufficient free disk space"):
                        ops.restore(self.name)
                connecting.assert_not_called()
                process.assert_not_called()
                copying.assert_not_called()
                self.assertEqual(list((self.data / "blobs").iterdir()), [])

    def test_restore_requires_real_database_capacity_mount_before_target_mutation(self):
        self.database_capacity.rmdir()
        with patch.object(ops, "connect") as connecting, patch.object(ops, "checked_process") as process:
            with self.assertRaisesRegex(RuntimeError, "real mounted directory"):
                ops.restore(self.name)
        connecting.assert_not_called()
        process.assert_not_called()
        self.database_capacity.symlink_to(self.data, target_is_directory=True)
        with patch.object(ops, "connect") as connecting:
            with self.assertRaisesRegex(RuntimeError, "real mounted directory"):
                ops.restore(self.name)
        connecting.assert_not_called()

    def restore_patches(self, connection):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(ops, "connect", return_value=connection))
        process = stack.enter_context(patch.object(ops, "checked_process"))
        stack.enter_context(patch.object(ops, "snapshot", return_value=("18.6", [self.entry])))
        stack.enter_context(patch.object(ops, "history", return_value=self.migrations))
        stack.enter_context(patch.object(ops.os, "chown"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return stack, process

    def test_restore_uses_new_empty_storage_and_revokes_sessions_and_account_tokens(self):
        connection = FakeConnection()
        stack, process = self.restore_patches(connection)
        self.disk_usage.return_value.free = 2 * self.value["databaseBytes"] + len(self.contents) + 64 * 1024 * 1024
        with stack:
            ops.restore(self.name)
        process.assert_called_once()
        arguments = process.call_args.args[0]
        self.assertIn("--single-transaction", arguments)
        self.assertIn("--exit-on-error", arguments)
        restored = self.data / "blobs" / self.key
        self.assertEqual(restored.read_bytes(), self.contents)
        self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o400)
        statements = [statement for statement, _ in connection.statements]
        self.assertIn("DELETE FROM sessions", statements)
        self.assertIn("DELETE FROM account_tokens", statements)
        for table in ["upload_tickets", "export_jobs", "import_jobs"]:
            self.assertTrue(any(statement.startswith("UPDATE " + table + " ") for statement in statements), table)
        self.assertLess(statements.index("BEGIN"), statements.index("DELETE FROM sessions"))
        self.assertGreater(statements.index("COMMIT"), statements.index("DELETE FROM account_tokens"))
        self.assertTrue(connection.closed)
        self.assertEqual([call.args[0] for call in self.disk_usage.call_args_list], [self.data, self.database_capacity])

    def test_restored_job_errors_follow_the_shared_api_failure_contract(self):
        connection = FakeConnection()
        stack, _ = self.restore_patches(connection)
        with stack:
            ops.restore(self.name)
        specification = json.loads((TOOLS.parent / "contracts/openapi.yaml").read_text())
        validator = Draft202012Validator({"$ref": "#/components/schemas/JobFailure",
                                          "components": specification["components"]})
        statements = [statement for statement, _ in connection.statements]
        for table, code in [("upload_tickets", "upload_interrupted"), ("export_jobs", "export_interrupted"),
                            ("import_jobs", "import_interrupted")]:
            with self.subTest(table=table):
                updates = [statement for statement in statements if statement.startswith("UPDATE " + table + " ")]
                self.assertEqual(len(updates), 1)
                error = json.loads(re.search(r"error='(.*?)'::jsonb", updates[0]).group(1))
                validator.validate(error)
                self.assertEqual(error["code"], code)
                self.assertEqual(error["fields"], [])

    def test_restore_rejects_existing_database_before_dump_or_original_mutation(self):
        connection = FakeConnection(table_count=1)
        stack, process = self.restore_patches(connection)
        with stack, self.assertRaisesRegex(RuntimeError, "new empty database"):
            ops.restore(self.name)
        process.assert_not_called()
        self.assertEqual(list((self.data / "blobs").iterdir()), [])
        self.assertTrue(connection.closed)

    def test_restore_rejects_existing_originals_without_overwriting(self):
        existing = self.data / "blobs" / "preserved"
        existing.write_bytes(b"existing data")
        connection = FakeConnection()
        stack, process = self.restore_patches(connection)
        with stack, self.assertRaisesRegex(RuntimeError, "clean file storage"):
            ops.restore(self.name)
        process.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"existing data")

    def test_restore_requires_exclusive_maintenance_lease(self):
        connection = FakeConnection(lock_acquired=False)
        stack, process = self.restore_patches(connection)
        with stack, self.assertRaisesRegex(RuntimeError, "maintenance is busy"):
            ops.restore(self.name)
        process.assert_not_called()
        self.assertTrue(connection.closed)

    def test_restored_reference_mismatch_does_not_revoke_or_report_success(self):
        connection = FakeConnection()
        stack, _ = self.restore_patches(connection)
        with stack, patch.object(ops, "snapshot", return_value=("18.6", [])):
            with self.assertRaisesRegex(RuntimeError, "differs from manifest"):
                ops.restore(self.name)
        self.assertNotIn("DELETE FROM sessions", [statement for statement, _ in connection.statements])
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
