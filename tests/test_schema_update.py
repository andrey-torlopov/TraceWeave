import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from tools import control, schema_update_test

ROOT = Path(__file__).resolve().parents[1]

class SchemaUpdateTests(unittest.TestCase):
    def candidate(self):
        value = json.loads((ROOT / "releases/0.1.1.json").read_text())
        for key in ["releaseId", "frontendReleaseId", "frontendVersion", "backendVersion"]: value[key] = "0.1.3"
        for key in ["backend", "frontend", "gateway", "tools"]: value["images"][key] = value["images"][key].replace(":0.1.1@", ":0.1.3@")
        value["backendContractHash"] = value["contractHash"] = "c" * 64
        value["supportedClientContractHashes"] = [value["contractHash"], json.loads((ROOT / "releases/0.1.1.json").read_text())["contractHash"]]
        value["migrations"].append({"version": 7, "sha256": "d" * 64})
        return value

    def test_each_reviewed_infrastructure_is_retained_with_additive_schema(self):
        for filename in ["0.1.0.json", "0.1.1.json", "0.1.1-update.json"]:
            base = json.loads((ROOT / "releases" / filename).read_text())
            selected = schema_update_test.compatible(base, self.candidate())
            control.validate_update(base, selected)
            self.assertEqual(set(control.changes(base, selected)), {"backend", "frontend"})
            self.assertEqual(selected["migrations"][:6], base["migrations"])
            for key in ["postgres", "tools", "gateway"]: self.assertEqual(selected["images"][key], base["images"][key])
            self.assertEqual(selected["source"]["delivery"], base["source"]["delivery"])

    def test_old_history_and_pending_clients_cannot_be_stranded(self):
        base = json.loads((ROOT / "releases/0.1.1.json").read_text())
        for kind in ["history", "client", "version"]:
            value = self.candidate()
            if kind == "history": value["migrations"][0]["sha256"] = "e" * 64
            elif kind == "client": value["supportedClientContractHashes"] = [value["contractHash"]]
            else: value["backendVersion"] = "0.1.4"
            with self.subTest(kind=kind), self.assertRaises((AssertionError, control.Failure)):
                schema_update_test.compatible(base, value)

    def test_restore_reauthenticates_before_reading_the_preserved_fixture(self):
        owner = Mock(cookie='original-session', csrf='original-csrf', owner='original-account')
        owner.json.return_value = {'authenticated': False, 'user': None}
        def login():
            owner.cookie = 'fresh-session'
            owner.csrf = 'fresh-csrf'
        owner.login.side_effect = login
        fixture = object()
        with patch.object(schema_update_test.previous, 'preserved') as preserved:
            schema_update_test.preserved_after_restore(owner, fixture, 'original-account')
            preserved.assert_called_once_with(owner, fixture, 'fresh-session', 'fresh-csrf', 'original-account')
        owner.json.assert_called_once_with('GET', '/api/v1/session')
        owner.login.assert_called_once_with()

    def test_restore_refuses_live_old_sessions_and_changed_accounts(self):
        for authenticated, restored_account in [(True, 'original-account'), (False, 'another-account')]:
            owner = Mock(cookie='session', csrf='csrf', owner=restored_account)
            owner.json.return_value = {'authenticated': authenticated, 'user': {'id': 'original-account'} if authenticated else None}
            with self.subTest(authenticated=authenticated), patch.object(schema_update_test.previous, 'preserved') as preserved:
                with self.assertRaises(AssertionError):
                    schema_update_test.preserved_after_restore(owner, object(), 'original-account')
                preserved.assert_not_called()
                if authenticated: owner.login.assert_not_called()
