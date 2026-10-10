"""Operator invariants, using private temporary state and mocked Docker only."""
from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("traceweave_control_test_subject", TOOLS / "control.py")
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


def release_fixture():
    contract = "a" * 64
    return {
        "formatVersion": 1,
        "releaseId": "synthetic-1",
        "frontendReleaseId": "synthetic-1",
        "frontendVersion": "synthetic-1",
        "backendVersion": "synthetic-1",
        "contractHash": contract,
        "backendContractHash": contract,
        "supportedClientContractHashes": [contract],
        "postgresMajor": 18,
        "images": {name: "sha256:" + str(number) * 64 for number, name in enumerate(
            ["backend", "frontend", "postgres", "gateway", "tools"], start=1)},
        "migrations": [{"version": 1, "sha256": "b" * 64}],
    }


def config_fixture():
    return {
        "installId": "tw-synthetic",
        "origin": "http://127.0.0.1:8080",
        "port": 8080,
        "mode": "local",
        "subnet": "172.28.40.0/24",
        "gatewayIP": "172.28.40.2",
        "dynamicIPRange": "172.28.40.128/25",
        "volumes": {name: "tw-synthetic-" + name for name in
                    ["database", "files", "assets", "gatewayData", "gatewayConfig"]},
    }


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="traceweave-control-test-")
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name) / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.addCleanup(patch.stopall)
        patch.object(control, "RUNTIME", self.runtime).start()
        patch.object(control.subprocess, "run", side_effect=AssertionError("Unit test attempted an unmocked external command")).start()
        patch.object(control, "urlopen", side_effect=AssertionError("Unit test attempted an unmocked network request")).start()
        self.release = release_fixture()
        self.config = config_fixture()
        control.write_json(self.runtime / "release.json", self.release)
        control.write_json(self.runtime / "installation.json", self.config)
        control.phase("ready", releaseId=self.release["releaseId"])

    def candidate(self, backend=False):
        value = copy.deepcopy(self.release)
        value.update(releaseId="synthetic-2", frontendReleaseId="synthetic-2", frontendVersion="synthetic-2")
        value["images"]["frontend"] = "sha256:" + "6" * 64
        if backend:
            value["images"]["backend"] = "sha256:" + "7" * 64
            value["backendVersion"] = "synthetic-2"
        return value

    def write_candidate(self, value):
        path = self.runtime / "candidate.json"
        control.write_json(path, value)
        return path

    def fresh_bootstrap(self, *arguments):
        for name in ["installation.json", "release.json", "operation.json", "journal.jsonl"]:
            (self.runtime / name).unlink(missing_ok=True)
        release = self.write_candidate(self.release)
        return control.parser().parse_args(["bootstrap", "--release", str(release), *arguments])

    @contextlib.contextmanager
    def bootstrap_dependencies(self, owner):
        with contextlib.ExitStack() as stack:
            dependencies = {name: stack.enter_context(patch.object(control, name)) for name in
                            ["ensure_images", "initialize_volumes", "caddy_config", "wait_services",
                             "maintenance_check", "stop_backend", "ready", "reload_gateway", "unused_port", "execute"]}
            def compose(*arguments, **keywords):
                if arguments[-2:] == ("ops", "owner-state"):
                    return json.dumps(owner)
                return None
            dependencies["compose"] = stack.enter_context(patch.object(control, "compose", side_effect=compose))
            yield dependencies

    def test_first_bootstrap_missing_stable_manifest_has_no_installation_volume_or_account_side_effects(self):
        self.fresh_bootstrap()
        with patch.object(control, "ROOT", self.runtime / "delivery"):
            arguments = control.parser().parse_args(["bootstrap"])
            self.assertEqual(Path(arguments.release), control.ROOT / "releases/stable.json")
            with patch.object(control, "execute") as execute, patch.object(control, "compose") as compose, \
                    patch.object(control, "initialize_volumes") as initialize, \
                    patch.object(control, "unused_port") as port, patch.object(control, "bootstrap_text") as prompt:
                with self.assertRaisesRegex(control.Failure, "stable.json.*отсутствует"):
                    control.bootstrap(arguments)
            for effect in [execute, compose, initialize, port, prompt]:
                effect.assert_not_called()
        for name in ["installation.json", "release.json", "operation.json", "journal.jsonl"]:
            self.assertFalse((self.runtime / name).exists())

    def test_first_owner_prompts_only_after_owner_state_and_passes_complete_create_arguments(self):
        arguments = self.fresh_bootstrap()
        values = iter(["   ", " owner@example.test ", " Owner Name "])
        with self.bootstrap_dependencies({"count": 0, "withEmail": 0}) as dependencies:
            def answer(prompt):
                self.assertTrue(any(call.args[-2:] == ("ops", "owner-state") for call in dependencies["compose"].call_args_list))
                return next(values)
            with patch.object(control.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", side_effect=answer) as prompt:
                control.bootstrap(arguments)
        self.assertEqual(prompt.call_count, 3)
        create = next(call for call in dependencies["compose"].call_args_list if "create" in call.args)
        self.assertEqual(create.args, ("run", "--rm", "--no-deps", "owner", "account", "create",
                                       "--email", "owner@example.test", "--name", "Owner Name"))
        self.assertTrue(create.kwargs["interactive"])
        self.assertEqual(create.kwargs["release"], self.release)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "ready")

    def test_repeat_ready_or_stopped_bootstrap_starts_saved_release_without_account_prompt(self):
        for phase in ["ready", "stopped"]:
            with self.subTest(phase=phase):
                control.phase(phase, releaseId=self.release["releaseId"])
                arguments = control.parser().parse_args(["bootstrap"])
                with patch.object(control, "start") as start, patch.object(control, "compose") as compose, \
                        patch.object(control, "bootstrap_text") as prompt, patch("builtins.input") as input_value:
                    control.bootstrap(arguments)
                start.assert_called_once_with()
                compose.assert_not_called(); prompt.assert_not_called(); input_value.assert_not_called()
                self.assertEqual(control.current(), self.release)

    def test_first_owner_non_tty_missing_email_or_name_refuses_without_creating_account_or_opening_access(self):
        variants = [("--email", ["--name", "Operator"]), ("--name", ["--email", "owner@example.test"])]
        for missing, flags in variants:
            with self.subTest(missing=missing):
                arguments = self.fresh_bootstrap(*flags)
                with self.bootstrap_dependencies({"count": 0, "withEmail": 0}) as dependencies, \
                        patch.object(control.sys.stdin, "isatty", return_value=False), patch("builtins.input") as prompt:
                    with self.assertRaisesRegex(control.Failure, missing):
                        control.bootstrap(arguments)
                prompt.assert_not_called()
                self.assertFalse(any("create" in call.args for call in dependencies["compose"].call_args_list))
                dependencies["ready"].assert_not_called(); dependencies["reload_gateway"].assert_not_called()
                self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "bootstrap-migrating")

    def test_explicit_first_owner_fields_are_not_rewritten_or_prompted_when_controller_has_no_tty(self):
        email, name = "Owner+Case@example.test", " Explicit Name "
        arguments = self.fresh_bootstrap("--email", email, "--name", name)
        with self.bootstrap_dependencies({"count": 0, "withEmail": 0}) as dependencies, \
                patch.object(control.sys.stdin, "isatty", return_value=False), patch("builtins.input") as prompt:
            control.bootstrap(arguments)
        prompt.assert_not_called()
        create = next(call for call in dependencies["compose"].call_args_list if "create" in call.args)
        self.assertEqual(create.args[-4:], ("--email", email, "--name", name))
        self.assertTrue(create.kwargs["interactive"])  # Backend still owns the hidden password TTY.

    def test_first_owner_eof_is_a_graceful_refusal_before_account_creation_or_readiness(self):
        arguments = self.fresh_bootstrap()
        with self.bootstrap_dependencies({"count": 0, "withEmail": 0}) as dependencies, \
                patch.object(control.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesRegex(control.Failure, "Ввод первого аккаунта прерван"):
                control.bootstrap(arguments)
        self.assertFalse(any("create" in call.args for call in dependencies["compose"].call_args_list))
        dependencies["ready"].assert_not_called(); dependencies["reload_gateway"].assert_not_called()

    def test_manifest_accepts_content_addressed_images_and_complete_contract_metadata(self):
        self.release["images"]["backend"] = "registry.example/traceweave/backend@sha256:" + "1" * 64
        self.assertEqual(control.manifest(self.write_candidate(self.release)), self.release)

    def test_manifest_rejects_floating_or_incomplete_release(self):
        variants = [
            ("floating image", lambda m: m["images"].update(backend="traceweave/backend:latest")),
            ("wrong postgres major", lambda m: m.update(postgresMajor=17)),
            ("unsafe release identifier", lambda m: m.update(releaseId="../escape")),
            ("missing backend contract", lambda m: m.pop("backendContractHash")),
            ("wrong component version", lambda m: m.update(frontendVersion="")),
            ("missing frontend image release", lambda m: m.pop("frontendReleaseId")),
            ("missing own client", lambda m: m.update(supportedClientContractHashes=["c" * 64])),
            ("invalid supported hash", lambda m: m["supportedClientContractHashes"].append("short")),
            ("migration gap", lambda m: m["migrations"].append({"version": 3, "sha256": "c" * 64})),
            ("invalid migration digest", lambda m: m["migrations"][0].update(sha256="short")),
        ]
        for label, mutate in variants:
            with self.subTest(label=label):
                value = copy.deepcopy(self.release)
                mutate(value)
                with self.assertRaises(control.Failure):
                    control.manifest(self.write_candidate(value))

    def test_update_preserves_every_supported_pending_client(self):
        candidate = self.candidate(backend=True)
        candidate["contractHash"] = "c" * 64
        candidate["backendContractHash"] = "c" * 64
        candidate["supportedClientContractHashes"] = ["a" * 64, "c" * 64]
        control.validate_update(self.release, candidate)
        candidate["supportedClientContractHashes"] = ["c" * 64]
        with self.assertRaisesRegex(control.Failure, "pending command"):
            control.validate_update(self.release, candidate)

    def test_update_requires_append_only_history_and_new_backend_for_schema_change(self):
        candidate = self.candidate(backend=True)
        candidate["migrations"].append({"version": 2, "sha256": "c" * 64})
        control.validate_update(self.release, candidate)
        candidate["migrations"][0]["sha256"] = "d" * 64
        with self.assertRaisesRegex(control.Failure, "append-only"):
            control.validate_update(self.release, candidate)
        candidate = self.candidate()
        candidate["migrations"].append({"version": 2, "sha256": "c" * 64})
        with self.assertRaisesRegex(control.Failure, "new backend"):
            control.validate_update(self.release, candidate)

    def test_frontend_only_update_cannot_silently_change_backend_compatibility(self):
        candidate = self.candidate()
        candidate["supportedClientContractHashes"].append("c" * 64)
        with self.assertRaisesRegex(control.Failure, "coordinated backend"):
            control.validate_update(self.release, candidate)

    def test_frontend_only_update_does_not_stop_backend_migrate_or_copy_database(self):
        candidate = self.candidate()
        with patch.object(control, "compose") as compose, \
                patch.object(control, "reload_gateway") as gateway, \
                patch.object(control, "maintenance_check"), \
                patch.object(control, "preserve_assets"), \
                patch.object(control, "is_running", return_value=True), \
                patch.object(control, "ready"), \
                patch.object(control, "do_backup") as backup:
            control.install_update(self.config, self.release, candidate)
        backup.assert_not_called()
        self.assertEqual(len(compose.call_args_list), 1)
        self.assertEqual(compose.call_args.args, ("up", "-d", "--no-deps", "--wait", "--wait-timeout", "240", "frontend"))
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True, False])
        self.assertEqual(control.current(), candidate)

    def test_failed_update_readiness_retains_maintenance_and_old_selected_release(self):
        candidate = self.candidate()
        with patch.object(control, "compose"), patch.object(control, "maintenance_check"), \
                patch.object(control, "preserve_assets"), \
                patch.object(control, "is_running", return_value=True), \
                patch.object(control, "ready", side_effect=control.Failure("not ready")), \
                patch.object(control, "reload_gateway") as gateway:
            with self.assertRaisesRegex(control.Failure, "not ready"):
                control.install_update(self.config, self.release, candidate)
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "update-starting")

    def test_resumed_frontend_update_starts_unchanged_stopped_backend_before_readiness(self):
        candidate = self.candidate()
        sequence = []
        def application_start(*arguments, **kwargs):
            self.assertEqual(arguments[:6], ("up", "-d", "--no-deps", "--wait", "--wait-timeout", "240"))
            self.assertEqual(kwargs["release"], candidate)
            sequence.append(arguments[-1])
        with patch.object(control, "compose", side_effect=application_start), \
                patch.object(control, "reload_gateway") as gateway, patch.object(control, "maintenance_check"), \
                patch.object(control, "preserve_assets"), patch.object(control, "is_running", return_value=False) as running, \
                patch.object(control, "stop_backend") as stop, patch.object(control, "do_backup") as backup, \
                patch.object(control, "ready", side_effect=lambda *args: sequence.append("ready")), \
                contextlib.redirect_stdout(io.StringIO()):
            control.install_update(self.config, self.release, candidate)
        self.assertEqual(sequence, ["frontend", "backend", "ready"])
        running.assert_called_once_with("backend")
        stop.assert_not_called()
        backup.assert_not_called()
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True, False])
        self.assertEqual(control.current(), candidate)

    def test_start_rejects_interrupted_phases_before_any_docker_operation(self):
        for name in ["update-migrating", "restore-verifying", "backup-copying", "stopped-interrupted"]:
            with self.subTest(phase=name), patch.object(control, "compose") as compose, \
                    patch.object(control, "ensure_images") as images:
                control.phase(name)
                with self.assertRaisesRegex(control.Failure, "Interrupted operation"):
                    control.start()
                compose.assert_not_called()
                images.assert_not_called()

    def test_stop_preserves_interrupted_operation_for_resume(self):
        control.phase("update-migrating", backup="synthetic-backup")
        interrupted = control.read_json(self.runtime / "operation.json")
        with patch.object(control, "compose"), patch.object(control, "container", return_value=""), \
                patch.object(control, "reload_gateway"), patch.object(control, "maintenance_check"):
            control.stop()
        state = control.read_json(self.runtime / "operation.json")
        self.assertEqual(state["phase"], "stopped-interrupted")
        self.assertEqual(state["previousOperation"], interrupted)

    def test_forced_or_oom_backend_stop_is_not_accepted_as_graceful(self):
        for state in [{"Running": False, "ExitCode": 137, "OOMKilled": False},
                      {"Running": False, "ExitCode": 0, "OOMKilled": True},
                      {"Running": True, "ExitCode": 0, "OOMKilled": False}]:
            with self.subTest(state=state), patch.object(control, "container", return_value="synthetic-container"), \
                    patch.object(control, "compose"), patch.object(control, "execute", return_value=json.dumps(state)):
                with self.assertRaisesRegex(control.Failure, "did not stop gracefully"):
                    control.stop_backend(self.config, self.release)
        for code in [0, 143]:
            with self.subTest(code=code), patch.object(control, "container", return_value="synthetic-container"), \
                    patch.object(control, "compose"), patch.object(control, "execute", return_value=json.dumps({"Running": False, "ExitCode": code, "OOMKilled": False})):
                control.stop_backend(self.config, self.release)

    def test_resume_unknown_schema_never_installs_or_opens_gateway(self):
        candidate = self.candidate(backend=True)
        candidate["migrations"].append({"version": 2, "sha256": "c" * 64})
        control.write_json(self.runtime / "pending-release.json", candidate)
        control.write_json(self.runtime / "update-source.json", self.release)
        control.phase("update-migrating")
        with patch.object(control, "compose", return_value=json.dumps([{"version": 99, "sha256": "d" * 64}])), \
                patch.object(control, "install_update") as install, \
                patch.object(control, "reload_gateway") as gateway, \
                patch.object(control, "caddy_config"), patch.object(control, "maintenance_check"), \
                patch.object(control, "wait_services") as services:
            with self.assertRaisesRegex(control.Failure, "Unexpected schema"):
                control.resume(SimpleNamespace(yes=True))
        install.assert_not_called()
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        services.assert_called_once_with(["db", "gateway"], self.config, self.release)

    def test_backup_uses_pending_release_if_database_is_already_migrated(self):
        pending = self.candidate(backend=True)
        pending["migrations"].append({"version": 2, "sha256": "c" * 64})
        control.write_json(self.runtime / "pending-release.json", pending)
        with patch.object(control, "compose", side_effect=[json.dumps(pending["migrations"]), None]) as compose:
            name = control.do_backup(self.config, self.release)
        self.assertRegex(name, r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{6}$")
        self.assertEqual(control.read_json(self.runtime / "backup-release.json"), pending)
        self.assertEqual(compose.call_args.kwargs["release"], pending)

    def test_backup_unknown_schema_stops_before_dump(self):
        control.write_json(self.runtime / "pending-release.json", self.candidate(backend=True))
        with patch.object(control, "compose", return_value="[]") as compose:
            with self.assertRaisesRegex(control.Failure, "unknown schema"):
                control.do_backup(self.config, self.release)
        self.assertEqual(compose.call_count, 1)
        self.assertFalse((self.runtime / "backup-release.json").exists())

    def test_ready_verifies_baked_frontend_backend_and_database_metadata(self):
        # A backend-only release retains the previous immutable frontend image.
        self.release["releaseId"] = "global-synthetic-2"
        frontend = {"releaseId": self.release["frontendReleaseId"],
                    "frontendVersion": self.release["frontendVersion"], "contractHash": self.release["contractHash"]}
        backend = {"backendVersion": self.release["backendVersion"], "contractHash": self.release["backendContractHash"]}
        with patch.object(control, "compose", side_effect=[None, None, json.dumps(frontend), json.dumps(backend), json.dumps(self.release["migrations"])]) as compose:
            control.ready(self.config, self.release)
        self.assertEqual(compose.call_count, 5)
        for component in ["frontend", "backend", "history"]:
            with self.subTest(component=component):
                front = dict(frontend)
                back = dict(backend)
                history = copy.deepcopy(self.release["migrations"])
                if component == "frontend": front["contractHash"] = "c" * 64
                elif component == "backend": back["backendVersion"] = "wrong-version"
                else: history[0]["sha256"] = "c" * 64
                with patch.object(control, "compose", side_effect=[None, None, json.dumps(front), json.dumps(back), json.dumps(history)]):
                    with self.assertRaises(control.Failure):
                        control.ready(self.config, self.release)

    def test_restore_revert_pairs_old_database_with_saved_old_release(self):
        candidate = self.candidate(backend=True)
        current_config = copy.deepcopy(self.config)
        current_config["volumes"]["database"] += "-restore-candidate"
        control.write_json(self.runtime / "installation.json", current_config)
        control.write_json(self.runtime / "release.json", candidate)
        control.write_json(self.runtime / "restore-old-installation.json", self.config)
        control.write_json(self.runtime / "restore-old-release.json", self.release)
        with patch.object(control, "compose") as compose, patch.object(control, "ready") as ready, \
                patch.object(control, "caddy_config"), patch.object(control, "wait_services"), \
                patch.object(control, "maintenance_check"), patch.object(control, "stop_backend"), \
                patch.object(control, "reload_gateway"):
            control.restore_revert(SimpleNamespace(yes=True))
        ready.assert_called_once_with(self.config, self.release)
        self.assertEqual(compose.call_args.kwargs["config"], self.config)
        self.assertEqual(compose.call_args.kwargs["release"], self.release)
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.load_config(), self.config)

    def test_stopped_restore_revert_starts_gateway_database_before_reload_and_verifies_saved_pair(self):
        candidate = self.candidate(backend=True)
        current_config = copy.deepcopy(self.config)
        current_config["volumes"]["database"] += "-restore-candidate"
        current_config["volumes"]["files"] += "-restore-candidate"
        control.write_json(self.runtime / "installation.json", current_config)
        control.write_json(self.runtime / "release.json", candidate)
        control.write_json(self.runtime / "restore-old-installation.json", self.config)
        control.write_json(self.runtime / "restore-old-release.json", self.release)
        sequence = []

        def configure(config, release, maintenance):
            self.assertEqual((config, release, maintenance), (current_config, self.release, True))
            sequence.append("maintenance-config")

        def start_dependencies(services, config, release):
            self.assertEqual((services, config, release), (["db", "gateway"], current_config, self.release))
            sequence.append("gateway-database-ready")

        def gateway(config, release, maintenance):
            self.assertEqual(release, self.release)
            if maintenance:
                self.assertEqual(config, current_config)
                sequence.append("maintenance-reload")
            else:
                self.assertEqual(config, self.config)
                self.assertEqual(control.current(), self.release)
                self.assertEqual(control.load_config(), self.config)
                sequence.append("open-saved-pair")

        def confirm_maintenance(config):
            self.assertEqual(config, current_config)
            sequence.append("maintenance-confirmed")

        def backend_stop(config, release):
            self.assertEqual((config, release), (current_config, self.release))
            sequence.append("backend-stop")

        def compose(*arguments, **keywords):
            self.assertEqual(keywords["release"], self.release)
            if arguments[0] == "stop":
                self.assertEqual(arguments, ("stop", "--timeout", "180", "db"))
                self.assertEqual(keywords["config"], current_config)
                sequence.append("candidate-database-stop")
            elif arguments[-1] == "db":
                self.assertEqual(arguments, ("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "240", "db"))
                self.assertEqual(keywords["config"], self.config)
                sequence.append("saved-database-ready")
            else:
                self.assertEqual(arguments, ("up", "-d", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "240", "backend", "frontend"))
                self.assertEqual(keywords["config"], self.config)
                sequence.append("saved-applications-ready")

        def ready(config, release):
            self.assertEqual((config, release), (self.config, self.release))
            self.assertEqual(control.current(), candidate)
            self.assertEqual(control.load_config(), current_config)
            sequence.append("saved-pair-verified")

        with patch.object(control, "caddy_config", side_effect=configure), \
                patch.object(control, "wait_services", side_effect=start_dependencies), \
                patch.object(control, "reload_gateway", side_effect=gateway), \
                patch.object(control, "maintenance_check", side_effect=confirm_maintenance), \
                patch.object(control, "stop_backend", side_effect=backend_stop), \
                patch.object(control, "compose", side_effect=compose), patch.object(control, "ready", side_effect=ready):
            control.restore_revert(SimpleNamespace(yes=True))
        self.assertEqual(sequence, ["maintenance-config", "gateway-database-ready", "maintenance-reload",
                                   "maintenance-confirmed", "backend-stop", "candidate-database-stop",
                                   "saved-database-ready", "saved-applications-ready", "saved-pair-verified", "open-saved-pair"])
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "ready")

    def test_restore_rejects_unvalidated_backup_release_before_image_pull_or_maintenance(self):
        target = self.candidate(backend=True)
        target["images"]["backend"] = "traceweave/backend:latest"
        backup = self.runtime / "backups" / "synthetic-backup"
        control.write_json(backup / "manifest.json", {"release": target})
        with patch.object(control, "compose"), \
                patch.object(control, "ensure_images", side_effect=control.Failure("Invalid release reached image operations")) as images, \
                patch.object(control, "reload_gateway") as gateway, patch.object(control, "execute") as execute:
            with self.assertRaises(control.Failure):
                control.restore_command(SimpleNamespace(backup="synthetic-backup", yes=True))
        images.assert_not_called()
        gateway.assert_not_called()
        execute.assert_not_called()

    def test_failed_restore_readiness_keeps_old_release_and_preserved_volumes(self):
        target = self.candidate(backend=True)
        backup = self.runtime / "backups" / "synthetic-backup"
        control.write_json(backup / "manifest.json", {"release": target})
        sequence = []
        def safety_backup(*args):
            sequence.append("safety-backup")
            return "synthetic-safety"
        def command(arguments, **kwargs):
            sequence.append(arguments[:3])
            return ""
        with patch.object(control, "compose"), patch.object(control, "stop_backend"), \
                patch.object(control, "ensure_images"), patch.object(control, "maintenance_check"), \
                patch.object(control, "initialize_volumes"), patch.object(control, "execute", side_effect=command), \
                patch.object(control, "do_backup", side_effect=safety_backup), \
                patch.object(control, "reload_gateway") as gateway, \
                patch.object(control, "ready", side_effect=control.Failure("candidate not ready")):
            with self.assertRaisesRegex(control.Failure, "candidate not ready"):
                control.restore_command(SimpleNamespace(backup="synthetic-backup", yes=True))
        self.assertEqual(sequence[0], "safety-backup")
        self.assertEqual(sequence[1:], [["docker", "volume", "create"], ["docker", "volume", "create"]])
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.load_config(), self.config)
        self.assertEqual(control.read_json(self.runtime / "restore-old-release.json"), self.release)
        self.assertEqual(control.read_json(self.runtime / "restore-old-installation.json"), self.config)
        saved_target = control.read_json(self.runtime / "restore-target-installation.json")
        for key in ["database", "files"]:
            self.assertNotEqual(saved_target["volumes"][key], self.config["volumes"][key])
        for key in ["assets", "gatewayData", "gatewayConfig"]:
            self.assertEqual(saved_target["volumes"][key], self.config["volumes"][key])
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "restore-verifying")

    def test_runtime_lock_rejects_symlink_and_overlapping_operator(self):
        target = Path(self.temporary.name) / "target"
        target.mkdir()
        linked = Path(self.temporary.name) / "linked-runtime"
        linked.symlink_to(target, target_is_directory=True)
        with patch.object(control, "RUNTIME", linked):
            with self.assertRaisesRegex(control.Failure, "symlink"):
                with control.operation_lock():
                    self.fail("symlink runtime was accepted")
        with control.operation_lock():
            with self.assertRaisesRegex(control.Failure, "Another installation"):
                with control.operation_lock():
                    self.fail("overlapping operation acquired lock")

    def test_execute_removes_inherited_database_and_compose_configuration(self):
        environment = {"COMPOSE_FILE": "/wrong.yaml", "PGPASSWORD": "private-synthetic-secret", "SAFE_VALUE": "kept"}
        with patch.dict(os.environ, environment), patch.object(control.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok\n", "")) as run:
            self.assertEqual(control.execute(["docker", "info"], capture=True), "ok")
        child = run.call_args.kwargs["env"]
        self.assertNotIn("COMPOSE_FILE", child)
        self.assertNotIn("PGPASSWORD", child)
        self.assertEqual(child["SAFE_VALUE"], "kept")

    def test_start_reserves_gateway_address_before_dynamic_application_services(self):
        for legacy in [False, True]:
            config = copy.deepcopy(self.config)
            if legacy: config.pop("dynamicIPRange")
            with self.subTest(legacy=legacy), patch.object(control, "compose") as compose:
                control.start_services(config, self.release)
            self.assertEqual([call.args[-2:] for call in compose.call_args_list], [("db", "gateway"), ("backend", "frontend")])
            for call in compose.call_args_list:
                self.assertEqual(call.args[:5], ("up", "-d", "--wait", "--wait-timeout", "240"))
                self.assertEqual(call.kwargs, {"config": config, "release": self.release})

    def test_start_does_not_attach_dynamic_services_if_gateway_reservation_fails(self):
        with patch.object(control, "compose", side_effect=control.Failure("gateway startup failed")) as compose:
            with self.assertRaisesRegex(control.Failure, "gateway startup failed"):
                control.start_services(self.config, self.release)
        self.assertEqual(compose.call_count, 1)
        self.assertEqual(compose.call_args.args[-2:], ("db", "gateway"))

    def test_dynamic_allocation_range_excludes_trusted_gateway_address(self):
        environment = control.compose_env(self.config, self.release)
        dynamic = ipaddress.ip_network(environment["TW_APPLICATION_DYNAMIC_RANGE"])
        application = ipaddress.ip_network(environment["TW_APPLICATION_SUBNET"])
        gateway = ipaddress.ip_address(environment["TW_GATEWAY_IP"])
        self.assertTrue(dynamic.subnet_of(application))
        self.assertNotIn(gateway, dynamic)
        self.assertIn(gateway, application)

    def source_build_fixture(self, name="source-build"):
        root = (Path(self.temporary.name) / name).resolve()
        backend = root / "backend"
        frontend = root / "frontend"
        for path in [root / "contracts", root / "releases", backend, frontend,
                     backend / "Sources" / "ResearchGraphInfrastructure" / "Resources"]:
            path.mkdir(parents=True, exist_ok=True)
        (root / "contracts" / "openapi.yaml").write_text("openapi: 3.1.0\ninfo: {title: Synthetic contract, version: unit}\n")
        (backend / "Package.swift").write_text("// Synthetic checkout fixture; never compiled.\n")
        (frontend / "package-lock.json").write_text("{}\n")
        (backend / "Sources" / "ResearchGraphInfrastructure" / "Resources" / "0001.sql").write_text("SELECT 1;\n")
        fixture = SimpleNamespace(root=root, backend=backend, frontend=frontend, commands=[],
                                  revisions={str(backend): "a" * 40, str(frontend): "b" * 40, str(root): "c" * 40},
                                  diffs={str(backend): "", str(frontend): "", str(root): ""},
                                  statuses={str(backend): "", str(frontend): "", str(root): ""}, after_frontend_build=None)
        fixture.arguments = SimpleNamespace(backend_path=str(backend), frontend_path=str(frontend), release_id="synthetic-built")
        def command(arguments, **kwargs):
            fixture.commands.append(arguments)
            if arguments[:2] == ["git", "-c"]:
                checkout = arguments[4]
                self.assertEqual(arguments[2:4], ["safe.directory=" + checkout, "-C"])
                if arguments[5:] == ["rev-parse", "HEAD"]: return fixture.revisions[checkout]
                if arguments[5:] == ["diff", "--no-ext-diff", "--no-textconv", "HEAD"]: return fixture.diffs[checkout]
                if arguments[5:] == ["status", "--porcelain=v1", "--untracked-files=all"]: return fixture.statuses[checkout]
            elif arguments[:2] == ["docker", "build"]:
                tag = arguments[arguments.index("-t") + 1]
                if tag.startswith("traceweave/frontend:") and fixture.after_frontend_build:
                    fixture.after_frontend_build()
                return ""
            elif arguments == ["docker", "pull", control.PG_IMAGE]: return ""
            elif arguments[:3] == ["docker", "image", "inspect"]:
                component = arguments[-1].split("/")[-1].split(":")[0]
                return "sha256:" + str(["backend", "frontend", "gateway", "tools"].index(component) + 1) * 64
            elif arguments == ["docker", "info", "--format", "{{.Architecture}}"]: return "aarch64"
            raise AssertionError("Unexpected mocked build command: " + repr(arguments))
        fixture.command = command
        return fixture

    def test_source_build_preserves_immutable_component_metadata_and_tools_per_release(self):
        fixture = self.source_build_fixture()
        with patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command), contextlib.redirect_stdout(io.StringIO()):
            control.build_source(fixture.arguments)
        release = control.manifest(fixture.root / "releases" / "synthetic-built.local.json")
        builds = [command for command in fixture.commands if command[:2] == ["docker", "build"]]
        self.assertEqual(len(builds), 4)
        tags = [command[command.index("-t") + 1] for command in builds]
        self.assertEqual(tags, ["traceweave/tools:synthetic-built", "traceweave/gateway:synthetic-built", "traceweave/backend:synthetic-built", "traceweave/frontend:synthetic-built"])
        self.assertIn("SOURCE_REVISION=" + fixture.revisions[str(fixture.backend)], builds[2])
        self.assertIn("OPENAPI_CONTRACT_SHA256=" + control.hash_file(fixture.root / "contracts" / "openapi.yaml"), builds[2])
        self.assertEqual(release["platforms"], ["linux/arm64"])
        self.assertEqual(release["source"]["backend"], fixture.revisions[str(fixture.backend)])
        self.assertEqual(release["migrations"], [{"version": 1, "sha256": control.hash_file(fixture.backend / "Sources" / "ResearchGraphInfrastructure" / "Resources" / "0001.sql")}])

    def test_source_build_rejects_reused_release_identifier_before_external_commands(self):
        fixture = self.source_build_fixture()
        destination = fixture.root / "releases" / "synthetic-built.local.json"
        saved = b"Previously accepted immutable release.\n"
        destination.write_bytes(saved)
        with patch.object(control, "ROOT", fixture.root), patch.object(control, "execute") as execute:
            with self.assertRaisesRegex(control.Failure, "already has a local manifest"):
                control.build_source(fixture.arguments)
        execute.assert_not_called()
        self.assertEqual(destination.read_bytes(), saved)

    def test_tagged_source_build_keeps_independent_component_versions_and_provenance(self):
        fixture = self.source_build_fixture()
        fixture.arguments.backend_version = "0.1.1"
        fixture.arguments.frontend_version = "0.1.0"
        fixture.arguments.delivery_version = "0.2.0"
        with patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command), contextlib.redirect_stdout(io.StringIO()):
            control.build_source(fixture.arguments)
        release = control.manifest(fixture.root / "releases" / "synthetic-built.local.json")
        self.assertEqual((release["releaseId"], release["backendVersion"], release["frontendVersion"], release["frontendReleaseId"]),
                         ("synthetic-built", "0.1.1", "0.1.0", "0.1.0"))
        builds = [command for command in fixture.commands if command[:2] == ["docker", "build"]]
        for command, component, version in zip(builds, ["delivery", "delivery", "backend", "frontend"], ["0.2.0", "0.2.0", "0.1.1", "0.1.0"]):
            self.assertIn("org.opencontainers.image.version=" + version, command)
            self.assertIn("org.opencontainers.image.ref.name=v" + version, command)
            checkout = getattr(fixture, component) if component != "delivery" else fixture.root
            self.assertIn("org.opencontainers.image.revision=" + fixture.revisions[str(checkout)], command)
        self.assertIn("BACKEND_VERSION=0.1.1", builds[2])
        self.assertIn("FRONTEND_VERSION=0.1.0", builds[3])
        self.assertIn("RELEASE_ID=0.1.0", builds[3])
        self.assertEqual(release["source"]["delivery"], fixture.revisions[str(fixture.root)])

    def test_tagged_source_build_rejects_invalid_versions_before_external_commands(self):
        for component in ["backend", "frontend", "delivery"]:
            for index, version in enumerate(["", "v0.1.0", "0.1", "01.1.0", "0.1.0-rc.1", "../escape", "9" * 80 + ".1.0"]):
                fixture = self.source_build_fixture(component + "-" + str(index))
                setattr(fixture.arguments, component + "_version", version)
                with self.subTest(component=component, version=version), patch.object(control, "ROOT", fixture.root), patch.object(control, "execute") as execute:
                    with self.assertRaisesRegex(control.Failure, "Invalid " + component + " version"):
                        control.build_source(fixture.arguments)
                execute.assert_not_called()

    def test_tagged_source_build_refuses_dirty_or_drifting_delivery(self):
        for changed_before in [True, False]:
            fixture = self.source_build_fixture("delivery-" + str(changed_before))
            fixture.arguments.delivery_version = "0.1.0"
            if changed_before:
                fixture.statuses[str(fixture.root)] = " M tools/control.py"
            else:
                fixture.after_frontend_build = lambda: fixture.revisions.update({str(fixture.root): "d" * 40})
            with self.subTest(changed_before=changed_before), patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command):
                with self.assertRaisesRegex(control.Failure, "committed and clean" if changed_before else "changed during build"):
                    control.build_source(fixture.arguments)
            self.assertFalse((fixture.root / "releases" / "synthetic-built.local.json").exists())
            if changed_before:self.assertFalse(any(command[0] == "docker" for command in fixture.commands))

    def test_source_or_contract_drift_during_build_never_writes_release_manifest(self):
        for kind in ["backend-head", "frontend-diff", "new-untracked", "contract"]:
            fixture = self.source_build_fixture(kind)
            def mutate():
                if kind == "backend-head": fixture.revisions[str(fixture.backend)] = "c" * 40
                elif kind == "frontend-diff": fixture.diffs[str(fixture.frontend)] = "Synthetic tracked source edit."
                elif kind == "new-untracked": fixture.statuses[str(fixture.backend)] = "?? Sources/New.swift"
                else: (fixture.root / "contracts" / "openapi.yaml").write_text("openapi: 3.1.0\ninfo: {title: Changed contract, version: changed}\n")
            fixture.after_frontend_build = mutate
            with self.subTest(kind=kind), patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command):
                with self.assertRaisesRegex(control.Failure, "changed during build"):
                    control.build_source(fixture.arguments)
            self.assertFalse((fixture.root / "releases" / "synthetic-built.local.json").exists())
            self.assertEqual(len([command for command in fixture.commands if command[:2] == ["docker", "build"]]), 4)

    def test_source_build_rejects_dirty_and_untracked_checkouts_before_any_image_build(self):
        for kind, status in [("tracked", " M Sources/Changed.swift"), ("untracked", "?? Sources/New.swift")]:
            fixture = self.source_build_fixture(kind)
            fixture.statuses[str(fixture.backend)] = status
            with self.subTest(kind=kind), patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command):
                with self.assertRaisesRegex(control.Failure, "committed and clean"):
                    control.build_source(fixture.arguments)
            self.assertFalse(any(command[0] == "docker" for command in fixture.commands))
            self.assertFalse((fixture.root / "releases" / "synthetic-built.local.json").exists())

    def test_server_gateway_rejects_unknown_https_host_in_ready_and_maintenance_modes(self):
        config = {**self.config, "mode": "server", "origin": "https://traceweave.unit.test", "port": 443}
        for maintenance in [False, True]:
            with self.subTest(maintenance=maintenance):
                control.caddy_config(config, self.release, maintenance)
                content = (self.runtime / "gateway" / "Caddyfile").read_text()
                self.assertIn("https://traceweave.unit.test {", content)
                self.assertIn('https://:8443 {\n    @badApi path /api/* /health/*\n', content)
                self.assertIn(':8080 {\n    handle /gateway-health', content)
                self.assertEqual(control.read_json(self.runtime / "maintenance.json"), {"enabled": maintenance})

    def test_unknown_host_api_health_rejections_are_closed_json_for_every_gateway_listener(self):
        with patch.object(sys, "path", [str(TOOLS), *sys.path]):
            from validate_contracts import schema_validator
        validator = schema_validator("ErrorForbidden")
        configs = [self.config, {**self.config, "mode": "server", "origin": "https://traceweave.unit.test", "port": 443}]
        for config in configs:
            for maintenance in [False, True]:
                with self.subTest(mode=config["mode"], maintenance=maintenance):
                    control.caddy_config(config, self.release, maintenance)
                    content = (self.runtime / "gateway" / "Caddyfile").read_text()
                    listeners = re.findall(r"^(:8080|https://:8443) \{\n(.*?)^\}", content, re.MULTILINE | re.DOTALL)
                    self.assertEqual([address for address, _ in listeners],
                                     [":8080"] if config["mode"] == "local" else [":8080", "https://:8443"])
                    for address, listener in listeners:
                        with self.subTest(listener=address):
                            self.assertIn("@badApi path /api/* /health/*", listener)
                            blocks = re.findall(r"handle @badApi \{\n(.*?)^    \}", listener, re.MULTILINE | re.DOTALL)
                            self.assertEqual(len(blocks), 1)
                            block = blocks[0]
                            self.assertIn("header Content-Type application/json", block)
                            self.assertIn("header Cache-Control no-store", block)
                            response = re.search(r"respond (.+)$", block, re.MULTILINE)
                            self.assertIsNotNone(response)
                            encoded, consumed = json.JSONDecoder().raw_decode(response.group(1))
                            self.assertEqual(response.group(1)[consumed:].strip(), "403")
                            body = json.loads(encoded)
                            validator.validate(body)
                            self.assertEqual(body["error"]["message"], "Forbidden host")
                            self.assertNotIn("{http.request.", block)
                            self.assertNotIn("{host}", block)
                            self.assertNotIn(config["origin"], encoded)
                            self.assertIn('handle {\n        respond "Forbidden host" 403', listener)

    def test_stopped_interrupted_update_resumes_database_under_maintenance_before_history(self):
        candidate = self.candidate(backend=True)
        control.write_json(self.runtime / "update-source.json", self.release)
        control.write_json(self.runtime / "pending-release.json", candidate)
        interrupted = {"phase": "update-migrating", "backup": "verified-synthetic-backup"}
        control.phase("stopped-interrupted", previousOperation=interrupted)
        sequence = []
        def history(*arguments, **kwargs):
            self.assertEqual(arguments[-2:], ("ops", "history"))
            sequence.append("history")
            return json.dumps(self.release["migrations"])
        with patch.object(control, "caddy_config", side_effect=lambda *args: sequence.append("maintenance-config")), \
                patch.object(control, "wait_services", side_effect=lambda *args: sequence.append("db-gateway")) as services, \
                patch.object(control, "reload_gateway", side_effect=lambda *args: sequence.append("gateway-" + str(args[2]))) as gateway, \
                patch.object(control, "maintenance_check", side_effect=lambda *args: sequence.append("maintenance-check")), \
                patch.object(control, "compose", side_effect=history), \
                patch.object(control, "install_update", side_effect=lambda *args, **kwargs: sequence.append("install")) as install:
            control.resume(SimpleNamespace(yes=True))
        self.assertEqual(sequence, ["maintenance-config", "db-gateway", "gateway-True", "maintenance-check", "history", "install"])
        services.assert_called_once_with(["db", "gateway"], self.config, self.release)
        install.assert_called_once_with(self.config, self.release, candidate, backup="verified-synthetic-backup")
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        self.assertEqual(control.read_json(self.runtime / "operation.json"), interrupted)

    def rollback_fixture(self):
        current = self.candidate(backend=True)
        control.write_json(self.runtime / "release.json", current)
        control.write_json(self.runtime / "previous-release.json", self.release)
        return current

    def test_rollback_restarts_stopped_database_under_maintenance_before_history(self):
        current = self.rollback_fixture()
        sequence = []
        def commands(*arguments, **kwargs):
            if arguments[-2:] == ("ops", "history"):
                sequence.append("history")
                return json.dumps(self.release["migrations"])
            self.assertEqual(arguments[-2:], ("backend", "frontend"))
            sequence.append("applications")
            return ""
        with patch.object(control, "is_running", return_value=False), \
                patch.object(control, "caddy_config", side_effect=lambda *args: sequence.append("maintenance-config")), \
                patch.object(control, "wait_services", side_effect=lambda *args: sequence.append("db-gateway")) as services, \
                patch.object(control, "reload_gateway", side_effect=lambda *args: sequence.append("gateway-" + str(args[2]))) as gateway, \
                patch.object(control, "maintenance_check", side_effect=lambda *args: sequence.append("maintenance-check")), \
                patch.object(control, "stop_backend", side_effect=lambda *args: sequence.append("graceful-stop")) as stop, \
                patch.object(control, "compose", side_effect=commands), patch.object(control, "ready", side_effect=lambda *args: sequence.append("ready")), \
                contextlib.redirect_stdout(io.StringIO()):
            control.rollback(SimpleNamespace(yes=True))
        self.assertLess(sequence.index("db-gateway"), sequence.index("history"))
        self.assertLess(sequence.index("maintenance-check"), sequence.index("history"))
        self.assertLess(sequence.index("graceful-stop"), sequence.index("applications"))
        self.assertLess(sequence.index("ready"), sequence.index("gateway-False"))
        services.assert_called_once_with(["db", "gateway"], self.config, current)
        stop.assert_called_once_with(self.config, current)
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True, True, False])
        self.assertEqual(control.current(), self.release)

    def test_forced_backend_stop_during_rollback_preserves_maintenance_and_current_release(self):
        current = self.rollback_fixture()
        def commands(*arguments, **kwargs):
            if arguments[-2:] == ("ops", "history"): return json.dumps(self.release["migrations"])
            self.assertEqual(arguments, ("stop", "--timeout", "180", "backend"))
            return ""
        with patch.object(control, "is_running", return_value=True), \
                patch.object(control, "reload_gateway") as gateway, patch.object(control, "maintenance_check"), \
                patch.object(control, "container", return_value="synthetic-backend"), \
                patch.object(control, "execute", return_value=json.dumps({"Running": False, "ExitCode": 137, "OOMKilled": False})), \
                patch.object(control, "compose", side_effect=commands) as compose, patch.object(control, "ready") as ready:
            with self.assertRaisesRegex(control.Failure, "did not stop gracefully"):
                control.rollback(SimpleNamespace(yes=True))
        self.assertFalse(any(call.args[0] == "up" for call in compose.call_args_list))
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        ready.assert_not_called()
        self.assertEqual(control.current(), current)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "rollback-entering")

    def test_forced_backend_stop_during_mail_configuration_preserves_previous_secret_and_config(self):
        path = self.runtime / "secrets" / "smtp_password"
        control.atomic(path, "Previous synthetic secret.\n", 0o444)
        arguments = SimpleNamespace(smtp_url="smtps://mail.unit.test:465", smtp_user="synthetic-user", smtp_from="owner@unit.test", enable_registration=False)
        with patch.object(control.sys.stdin, "isatty", return_value=True), \
                patch.object(control.getpass, "getpass", return_value="New synthetic secret."), \
                patch.object(control, "reload_gateway") as gateway, patch.object(control, "maintenance_check"), \
                patch.object(control, "container", return_value="synthetic-backend"), \
                patch.object(control, "execute", return_value=json.dumps({"Running": False, "ExitCode": 137, "OOMKilled": False})), \
                patch.object(control, "compose") as compose, patch.object(control, "ready") as ready:
            with self.assertRaisesRegex(control.Failure, "did not stop gracefully"):
                control.configure_mail(arguments, copy.deepcopy(self.config), self.release)
        self.assertEqual([call.args[2] for call in gateway.call_args_list], [True])
        self.assertEqual(compose.call_args.args, ("stop", "--timeout", "180", "backend"))
        self.assertFalse(any(call.args[0] == "up" for call in compose.call_args_list))
        ready.assert_not_called()
        self.assertEqual(path.read_text(), "Previous synthetic secret.\n")
        self.assertEqual(control.load_config(), self.config)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "maintenance-configuring-mail")

    def test_docker_operator_probes_actual_host_port_and_removes_only_probe_container(self):
        image = "sha256:" + "9" * 64
        with patch.dict(os.environ, {"TW_CONTAINER_CONTROL": "1", "TW_OPERATOR_IMAGE": image}), \
                patch.object(control, "execute", side_effect=["synthetic-port-probe", ""]) as execute, \
                patch.object(control.socket, "socket", side_effect=AssertionError("Container namespace cannot check host port")):
            control.unused_port(8099)
        self.assertEqual([call.args[0] for call in execute.call_args_list], [
            ["docker", "run", "--rm", "-d", "-p", "127.0.0.1:8099:12345", "--entrypoint", "sleep", image, "30"],
            ["docker", "stop", "--time", "1", "synthetic-port-probe"],
        ])

    def test_busy_host_port_rejects_bootstrap_before_persisting_installation_or_creating_volumes(self):
        unused_runtime = Path(self.temporary.name) / "new-installation"
        unused_runtime.mkdir(mode=0o700)
        release = self.write_candidate(self.release)
        arguments = SimpleNamespace(release=str(release), origin="http://127.0.0.1:8099", port=8099)
        with patch.object(control, "RUNTIME", unused_runtime), \
                patch.dict(os.environ, {"TW_CONTAINER_CONTROL": "1", "TW_OPERATOR_IMAGE": "sha256:" + "9" * 64}), \
                patch.object(control, "execute", side_effect=control.Failure("host port occupied")) as execute, \
                patch.object(control, "ensure_images") as images:
            with self.assertRaisesRegex(control.Failure, "host port occupied"):
                control.bootstrap(arguments)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0][:4], ["docker", "run", "--rm", "-d"])
        images.assert_not_called()
        self.assertEqual(list(unused_runtime.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
