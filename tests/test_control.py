"""Operator invariants, using private temporary state and mocked Docker only."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
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

    def tools_candidate(self):
        value = self.candidate(backend=True)
        value['images']['tools'] = 'sha256:' + '8' * 64
        value['migrations'].append({'version': 2, 'sha256': 'c' * 64})
        value['toolsUpgrade'] = {'from': self.release['images']['tools'], 'to': value['images']['tools']}
        value.setdefault('source', {}).update(tools='9' * 40, toolsDiffHash=hashlib.sha256(b'').hexdigest())
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

    def guided_fixture(self, full=False, state="ready"):
        self.release.update(releaseId="0.1.0", frontendReleaseId="0.1.0", frontendVersion="0.1.0", backendVersion="0.1.0")
        self.release["source"] = {"backend": "1" * 40, "frontend": "2" * 40, "delivery": "3" * 40,
                                  "backendDiffHash": "a" * 64, "frontendDiffHash": "a" * 64, "deliveryDiffHash": "a" * 64}
        control.write_json(self.runtime / "release.json", self.release)
        control.phase(state, releaseId=self.release["releaseId"])
        for name in ["pending-release.json", "update-source.json", "previous-release.json"]:
            (self.runtime / name).unlink(missing_ok=True)
        directory = self.runtime.parent / "delivery with spaces"
        (directory / "releases").mkdir(parents=True, exist_ok=True)
        patch.object(control, "ROOT", directory).start()
        selected = self.candidate(backend=True)
        selected.update(releaseId="0.1.1", frontendReleaseId="0.1.1", frontendVersion="0.1.1", backendVersion="0.1.1")
        selected["source"].update(backend="4" * 40, frontend="5" * 40)
        target = copy.deepcopy(selected)
        if full:
            target["images"].update(gateway="sha256:" + "8" * 64, tools="sha256:" + "9" * 64)
            target["source"]["delivery"] = "6" * 40
        path = directory / "releases/stable.json"
        compatible = directory / "releases/0.1.1-update.json"
        control.write_json(path, target)
        control.write_json(compatible, selected)
        return path, compatible, target, selected

    @contextlib.contextmanager
    def guided_dependencies(self, answer="YES", tty=True):
        output = io.StringIO()
        sequence = []
        def commit(config, old, selected):
            sequence.append("update")
            control.write_json(self.runtime / "release.json", selected)
            control.phase("ready", releaseId=selected["releaseId"])
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(output))
            dependencies = {"output": output, "sequence": sequence}
            dependencies["start"] = stack.enter_context(patch.object(control, "start", side_effect=lambda: sequence.append("start")))
            dependencies["pull"] = stack.enter_context(patch.object(control, "ensure_images"))
            dependencies["install"] = stack.enter_context(patch.object(control, "install_update", side_effect=commit))
            dependencies["compose"] = stack.enter_context(patch.object(control, "compose"))
            dependencies["account"] = stack.enter_context(patch.object(control, "bootstrap_text"))
            stack.enter_context(patch.object(control.shutil, "disk_usage", return_value=SimpleNamespace(free=2 * 1024**3)))
            stack.enter_context(patch.object(control.sys.stdin, "isatty", return_value=tty))
            dependencies["prompt"] = stack.enter_context(patch("builtins.input", side_effect=answer if isinstance(answer, BaseException) or callable(answer) else None,
                                                               return_value=answer))
            yield dependencies

    def assert_guided_no_update(self, dependencies):
        dependencies["start"].assert_called_once_with()
        for name in ["install", "pull", "account", "compose"]:
            dependencies[name].assert_not_called()
        self.assertEqual(control.current(), self.release)
        self.assertFalse((self.runtime / "pending-release.json").exists())
        self.assertFalse((self.runtime / "update-source.json").exists())

    def test_guided_bootstrap_full_release_selects_exact_compatible_pair_with_one_confirmation(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap"]))
        dependencies["prompt"].assert_called_once()
        dependencies["start"].assert_not_called()
        dependencies["pull"].assert_called_once_with(selected)
        dependencies["install"].assert_called_once_with(self.config, self.release, selected)
        self.assertEqual(control.read_json(self.runtime / "pending-release.json"), selected)
        self.assertEqual(control.read_json(self.runtime / "update-source.json"), self.release)
        self.assertEqual(control.current(), selected)
        self.assertIn("backend 0.1.0, frontend 0.1.0", dependencies["output"].getvalue())
        self.assertIn("миграции не нужны", dependencies["output"].getvalue())
        dependencies["account"].assert_not_called(); dependencies["compose"].assert_not_called()

    def test_guided_bootstrap_selects_reviewed_variant_for_installed_infrastructure(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        wrong = copy.deepcopy(selected)
        wrong["images"]["gateway"] = "sha256:" + "7" * 64
        control.write_json(compatible, wrong)
        variant = path.parent / "0.1.1-update-from-0.1.0.json"
        control.write_json(variant, selected)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(path), "--yes"]))
        self.assertEqual(control.current(), selected)
        self.assertEqual(dependencies["sequence"], ["update"])
        self.assertIn("Доступно обновление:", dependencies["output"].getvalue())

    def test_guided_bootstrap_explicit_compatible_manifest_uses_reviewed_path(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(compatible)]))
        dependencies["install"].assert_called_once_with(self.config, self.release, selected)
        dependencies["prompt"].assert_called_once()

    def test_guided_bootstrap_selects_exact_retained_infrastructure_when_application_versions_match(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        self.release["images"]["tools"] = "docker.io/andreytorlopov/traceweave-tools:0.1.0@sha256:" + "3" * 64
        selected["images"]["tools"] = self.release["images"]["tools"]
        self.release["images"]["gateway"] = "docker.io/andreytorlopov/traceweave-gateway:0.1.0@sha256:" + "4" * 64
        selected["images"]["gateway"] = self.release["images"]["gateway"]
        control.write_json(self.runtime / "release.json", self.release)
        wrong = copy.deepcopy(selected)
        wrong["images"]["gateway"] = "sha256:" + "7" * 64
        control.write_json(compatible, wrong)
        variant = path.parent / "0.1.1-update-infra-0.1.0.json"
        control.write_json(variant, selected)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(path), "--yes"]))
        self.assertEqual(control.current(), selected)
        dependencies["install"].assert_called_once_with(self.config, self.release, selected)

    def test_guided_bootstrap_infrastructure_selector_cannot_substitute_application_images(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        self.release["images"]["tools"] = "docker.io/andreytorlopov/traceweave-tools:0.1.0@sha256:" + "3" * 64
        self.release["images"]["gateway"] = "docker.io/andreytorlopov/traceweave-gateway:0.1.0@sha256:" + "4" * 64
        selected["images"]["gateway"] = self.release["images"]["gateway"]
        control.write_json(self.runtime / "release.json", self.release)
        compatible.unlink()
        selected["images"].update(tools=self.release["images"]["tools"], frontend="sha256:" + "7" * 64)
        control.write_json(path.parent / "0.1.1-update-infra-0.1.0.json", selected)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(path), "--yes"]))
        self.assert_guided_no_update(dependencies)

    def test_guided_tools_upgrade_selects_gateway_variant_and_exact_candidate_tools_provenance(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        self.release['images']['gateway'] = 'docker.io/andreytorlopov/traceweave-gateway:0.1.0@sha256:' + '4' * 64
        self.release['images']['tools'] = 'docker.io/andreytorlopov/traceweave-tools:0.1.4@sha256:' + '5' * 64
        control.write_json(self.runtime / 'release.json', self.release)
        target['migrations'].append({'version': 2, 'sha256': 'c' * 64})
        target['source']['deliveryDiffHash'] = hashlib.sha256(b'').hexdigest()
        selected['migrations'] = target['migrations']
        selected['images'].update(gateway=self.release['images']['gateway'], tools=target['images']['tools'])
        selected['source'].update(tools=target['source']['delivery'], toolsDiffHash=target['source']['deliveryDiffHash'])
        selected['toolsUpgrade'] = {'from': self.release['images']['tools'], 'to': selected['images']['tools']}
        control.write_json(path, target)
        compatible.unlink()
        variant = path.parent / '0.1.1-update-infra-0.1.0.json'
        control.write_json(variant, selected)
        self.assertEqual(control.bootstrap_update(self.release, path), (variant, selected))
        for field in ['image', 'source']:
            with self.subTest(field=field):
                invalid = copy.deepcopy(selected)
                if field == 'image':
                    invalid['images']['tools'] = 'sha256:' + '7' * 64
                    invalid['toolsUpgrade']['to'] = invalid['images']['tools']
                else: invalid['source']['tools'] = '8' * 40
                control.write_json(variant, invalid)
                with self.assertRaisesRegex(control.Failure, 'tools image/source'):
                    control.bootstrap_update(self.release, path)

    def test_guided_bootstrap_external_full_manifest_can_use_exact_checked_in_compatible_release(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        external = self.runtime.parent / "external candidate/full.json"
        control.write_json(external, target)
        self.assertFalse((external.parent / "0.1.1-update.json").exists())
        with self.guided_dependencies(answer="y") as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(external)]))
        dependencies["pull"].assert_called_once_with(selected)
        dependencies["install"].assert_called_once_with(self.config, self.release, selected)
        dependencies["prompt"].assert_called_once()

    def test_guided_bootstrap_external_candidate_fallback_rejects_substitution_and_does_not_shadow_bad_adjacent_file(self):
        for invalid_adjacent in [False, True]:
            with self.subTest(invalid_adjacent=invalid_adjacent):
                path, compatible, target, selected = self.guided_fixture(full=True)
                external = self.runtime.parent / "external candidate/full.json"
                adjacent = external.parent / "0.1.1-update.json"
                control.write_json(external, target)
                if invalid_adjacent:
                    adjacent.write_text("{")
                else:
                    adjacent.unlink(missing_ok=True)
                    selected["images"]["backend"] = "sha256:" + "8" * 64
                    control.write_json(compatible, selected)
                with self.guided_dependencies() as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap", "--release", str(external), "--yes"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_not_called()

    def test_guided_bootstrap_rejects_manifest_replacement_during_confirmation_before_update_side_effects(self):
        for state in ["ready", "stopped"]:
            with self.subTest(state=state):
                path, compatible, target, selected = self.guided_fixture(full=True, state=state)
                def replace_target(prompt):
                    control.write_json(compatible, self.release)
                    return "yes"
                with self.guided_dependencies(answer=replace_target) as dependencies:
                    with self.assertRaisesRegex(control.Failure, "manifest изменился"):
                        control.bootstrap(control.parser().parse_args(["bootstrap"]))
                dependencies["prompt"].assert_called_once()
                for name in ["start", "install", "pull", "compose", "account"]:
                    dependencies[name].assert_not_called()
                self.assertEqual(control.current(), self.release)
                self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], state)
                self.assertFalse((self.runtime / "pending-release.json").exists())
                self.assertFalse((self.runtime / "update-source.json").exists())

    def test_guided_bootstrap_decline_and_eof_start_old_without_update_side_effects_and_show_exact_command(self):
        for answer in ["n", "", "NO", EOFError()]:
            with self.subTest(answer=type(answer).__name__ + str(answer)):
                path, compatible, target, selected = self.guided_fixture(full=True)
                with self.guided_dependencies(answer=answer) as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_called_once()
                printed = dependencies["output"].getvalue().splitlines()
                command = next(line for line in printed if line.startswith("TW_RUNTIME_DIR="))
                self.assertEqual(shlex.split(command), ["TW_RUNTIME_DIR=" + str(self.runtime), str(control.ROOT / "traceweave.sh"),
                                                       "update", "--release", str(compatible.resolve())])

    def test_guided_bootstrap_non_tty_needs_explicit_yes_to_update(self):
        for accepted in [False, True]:
            with self.subTest(accepted=accepted):
                path, compatible, target, selected = self.guided_fixture(full=True)
                arguments = control.parser().parse_args(["bootstrap", *(["--yes"] if accepted else [])])
                with self.guided_dependencies(tty=False) as dependencies:
                    control.bootstrap(arguments)
                dependencies["prompt"].assert_not_called()
                if accepted:
                    dependencies["install"].assert_called_once_with(self.config, self.release, selected)
                    dependencies["start"].assert_not_called()
                else:
                    self.assert_guided_no_update(dependencies)

    def test_guided_bootstrap_stopped_installation_starts_before_accepted_update(self):
        path, compatible, target, selected = self.guided_fixture(full=True, state="stopped")
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap"]))
        self.assertEqual(dependencies["sequence"], ["start", "update"])
        dependencies["prompt"].assert_called_once()
        dependencies["install"].assert_called_once_with(self.config, self.release, selected)

    def test_guided_bootstrap_matching_application_pair_ignores_infrastructure_or_release_id_changes(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        matching = copy.deepcopy(self.release)
        matching["images"].update(gateway=target["images"]["gateway"], tools=target["images"]["tools"])
        matching["releaseId"] = "0.1.1"
        control.write_json(path, matching)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
        self.assert_guided_no_update(dependencies)
        dependencies["prompt"].assert_not_called()

    def test_guided_bootstrap_downgrade_prerelease_and_opaque_versions_never_guess_an_update(self):
        variants = [
            lambda old, new: new.update(frontendVersion="0.0.9"),
            lambda old, new: new.update(backendVersion="0.0.9"),
            lambda old, new: new.update(releaseId="0.0.9"),
            lambda old, new: new.update(frontendVersion="0.1.1-rc.1"),
            lambda old, new: old.update(backendVersion="custom-1"),
            lambda old, new: new.update(releaseId="custom-2"),
            lambda old, new: old.update(releaseId="custom-1"),
        ]
        for mutate in variants:
            with self.subTest(variant=variants.index(mutate)):
                path, compatible, target, selected = self.guided_fixture()
                mutate(self.release, target)
                control.write_json(self.runtime / "release.json", self.release)
                control.write_json(path, target)
                with self.guided_dependencies() as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_not_called()

    def test_guided_bootstrap_missing_invalid_or_incompatible_candidate_safely_starts_old(self):
        for contents in [None, "{", "[]", '{"formatVersion":1}', '{"migrations":["bad"]}']:
            with self.subTest(contents=contents):
                path, compatible, target, selected = self.guided_fixture()
                if contents is None:path.unlink()
                else:path.write_text(contents)
                with self.guided_dependencies() as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_not_called()
                self.assertIn("несовместим", dependencies["output"].getvalue())

    def test_guided_bootstrap_missing_or_corrupt_compatible_manifest_never_installs_full_infrastructure(self):
        for contents in [None, "{", "[]"]:
            with self.subTest(contents=contents):
                path, compatible, target, selected = self.guided_fixture(full=True)
                if contents is None:compatible.unlink()
                else:compatible.write_text(contents)
                with self.guided_dependencies() as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_not_called()

    def test_guided_bootstrap_rejects_compatible_target_substitution_and_preserves_validation(self):
        variants = [
            lambda m: m["images"].update(backend="sha256:" + "8" * 64),
            lambda m: m["images"].update(frontend="sha256:" + "8" * 64),
            lambda m: m.update(frontendReleaseId="different"),
            lambda m: m.update(backendContractHash="c" * 64),
            lambda m: m["supportedClientContractHashes"].append("c" * 64),
            lambda m: m["migrations"].append({"version": 2, "sha256": "c" * 64}),
            lambda m: m["source"].update(backend="9" * 40),
            lambda m: m["images"].update(tools="sha256:" + "8" * 64),
        ]
        for mutate in variants:
            with self.subTest(variant=variants.index(mutate)):
                path, compatible, target, selected = self.guided_fixture(full=True)
                mutate(selected); control.write_json(compatible, selected)
                with self.guided_dependencies() as dependencies:
                    control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                self.assert_guided_no_update(dependencies)
                dependencies["prompt"].assert_not_called()

    def test_guided_bootstrap_interrupted_operation_requires_explicit_recovery_without_discovery_or_migration(self):
        for state in ["update-migrating", "restore-verifying", "bootstrap-owner", "stopped-interrupted"]:
            with self.subTest(state=state):
                self.guided_fixture(full=True, state=state)
                with self.guided_dependencies() as dependencies, patch.object(control, "bootstrap_update") as discover:
                    with self.assertRaisesRegex(control.Failure, "незавершённую"):
                        control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                for name in ["start", "install", "pull", "compose", "account", "prompt"]:
                    dependencies[name].assert_not_called()
                discover.assert_not_called()
                self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], state)

    def test_guided_bootstrap_missing_operation_or_configuration_does_not_recreate_installation(self):
        for missing in ["operation.json", "installation.json"]:
            with self.subTest(missing=missing):
                self.guided_fixture(full=True)
                control.write_json(self.runtime / "installation.json", self.config)
                (self.runtime / missing).unlink()
                with self.guided_dependencies() as dependencies:
                    with self.assertRaises(control.Failure):
                        control.bootstrap(control.parser().parse_args(["bootstrap", "--yes"]))
                for name in ["start", "install", "pull", "compose", "account", "prompt"]:
                    dependencies[name].assert_not_called()
                self.assertFalse((self.runtime / missing).exists())

    def test_explicit_resume_initial_bootstrap_uses_saved_release_without_new_release_discovery(self):
        self.guided_fixture(full=True, state="bootstrap-owner")
        arguments = control.parser().parse_args(["resume", "--yes"])
        with self.bootstrap_dependencies({"count": 1, "withEmail": 1}) as dependencies, \
                patch.object(control, "bootstrap_update") as discover, patch("builtins.input") as prompt:
            control.resume(arguments)
        discover.assert_not_called(); prompt.assert_not_called()
        migrate = next(call for call in dependencies["compose"].call_args_list if call.args[-1] == "migrate")
        self.assertEqual(migrate.kwargs["release"], self.release)
        self.assertFalse(any("create" in call.args or "attach-email" in call.args for call in dependencies["compose"].call_args_list))
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "ready")

    def test_failed_initial_image_pull_keeps_explicitly_resumable_bootstrap_using_saved_release(self):
        path, compatible, target, selected = self.guided_fixture(full=True)
        arguments = self.fresh_bootstrap()
        with self.bootstrap_dependencies({"count": 1, "withEmail": 1}) as dependencies:
            dependencies["ensure_images"].side_effect = control.Failure("Synthetic image pull failed")
            with self.assertRaisesRegex(control.Failure, "Synthetic image pull failed"):
                control.bootstrap(arguments)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "bootstrap-preparing")
        self.assertEqual(control.current(), self.release)
        saved_config = control.load_config()
        for name in ["execute", "initialize_volumes", "caddy_config", "wait_services", "compose"]:
            dependencies[name].assert_not_called()
        resume = control.parser().parse_args(["resume", "--release", str(path), "--yes"])
        with self.bootstrap_dependencies({"count": 1, "withEmail": 1}) as dependencies, \
                patch.object(control, "bootstrap_update") as discover, patch("builtins.input") as prompt:
            control.resume(resume)
        discover.assert_not_called(); prompt.assert_not_called()
        dependencies["ensure_images"].assert_called_once_with(self.release)
        migrate = next(call for call in dependencies["compose"].call_args_list if call.args[-1] == "migrate")
        self.assertEqual(migrate.kwargs["release"], self.release)
        self.assertFalse(any("create" in call.args or "attach-email" in call.args for call in dependencies["compose"].call_args_list))
        self.assertEqual(control.load_config(), saved_config)
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.read_json(self.runtime / "operation.json")["phase"], "ready")

    def test_explicit_resume_unknown_bootstrap_phase_does_not_migrate_or_open_gateway(self):
        self.guided_fixture(full=True, state="bootstrap-unknown")
        with self.guided_dependencies() as dependencies:
            with self.assertRaisesRegex(control.Failure, "Unknown interrupted bootstrap"):
                control.resume(control.parser().parse_args(["resume", "--yes"]))
        for name in ["start", "install", "pull", "compose", "account", "prompt"]:
            dependencies[name].assert_not_called()

    def test_guided_bootstrap_schema_append_is_automatic_and_describes_backup_restore(self):
        path, compatible, target, selected = self.guided_fixture()
        target["migrations"].append({"version": 2, "sha256": "c" * 64})
        control.write_json(path, target)
        with self.guided_dependencies() as dependencies:
            control.bootstrap(control.parser().parse_args(["bootstrap"]))
        dependencies["install"].assert_called_once_with(self.config, self.release, target)
        dependencies["prompt"].assert_called_once()
        self.assertIn("схема базы обновится автоматически", dependencies["output"].getvalue())
        self.assertIn("восстановление копии", dependencies["output"].getvalue())

    def test_guided_bootstrap_keeps_existing_account_fields_and_private_mail_configuration(self):
        self.guided_fixture()
        settings = dict(self.config, smtpURL="smtps://mail.unit.test:465", smtpUser="synthetic-user", registrationEnabled=False)
        control.write_json(self.runtime / "installation.json", settings)
        control.atomic(self.runtime / "secrets/smtp_password", "Private synthetic value.\n", 0o444)
        arguments = control.parser().parse_args(["bootstrap", "--yes", "--email", "replacement@example.test", "--name", "Replacement"])
        with self.guided_dependencies() as dependencies:
            control.bootstrap(arguments)
        dependencies["account"].assert_not_called(); dependencies["compose"].assert_not_called()
        self.assertEqual(control.load_config(), settings)
        self.assertEqual((self.runtime / "secrets/smtp_password").read_text(), "Private synthetic value.\n")
        self.assertNotIn("Private synthetic value", dependencies["output"].getvalue())

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

    def test_tools_upgrade_requires_explicit_exact_transition_clean_source_and_schema_backend_change(self):
        candidate = self.tools_candidate()
        control.validate_manifest(candidate)
        control.validate_update(self.release, candidate)
        mutations = {
            'missing marker': lambda value: value.pop('toolsUpgrade'),
            'wrong old image': lambda value: value['toolsUpgrade'].update({'from': 'sha256:' + '9' * 64}),
            'wrong new image': lambda value: value['toolsUpgrade'].update({'to': 'sha256:' + '9' * 64}),
            'extra transition field': lambda value: value['toolsUpgrade'].update(unreviewed=True),
            'missing source': lambda value: value.pop('source'),
            'dirty source': lambda value: value['source'].update(toolsDiffHash='e' * 64),
            'malformed source': lambda value: value['source'].update(tools='v0.1.5'),
            'unchanged schema': lambda value: value.update(migrations=copy.deepcopy(self.release['migrations'])),
            'unchanged backend': lambda value: value['images'].update(backend=self.release['images']['backend']),
            'history rewrite': lambda value: value['migrations'][0].update(sha256='e' * 64),
            'gateway change': lambda value: value['images'].update(gateway='sha256:' + 'e' * 64),
            'postgres change': lambda value: value['images'].update(postgres='sha256:' + 'e' * 64),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                invalid = copy.deepcopy(candidate); mutation(invalid)
                with self.assertRaises(control.Failure): control.validate_update(self.release, invalid)

    def test_resume_revalidates_tools_transition_before_maintenance_or_image_operations(self):
        candidate = self.tools_candidate()
        candidate['toolsUpgrade']['from'] = 'sha256:' + 'e' * 64
        control.write_json(self.runtime / 'update-source.json', self.release)
        control.write_json(self.runtime / 'pending-release.json', candidate)
        control.phase('update-migrating', old=self.release['releaseId'], target=candidate['releaseId'])
        with patch.object(control, 'compose') as compose, patch.object(control, 'caddy_config') as configure, \
                patch.object(control, 'install_update') as install:
            with self.assertRaisesRegex(control.Failure, 'matching toolsUpgrade'):
                control.resume(SimpleNamespace(yes=True))
        compose.assert_not_called(); configure.assert_not_called(); install.assert_not_called()

    def test_coordinated_tools_update_backs_up_old_release_and_verifies_new_release_without_infrastructure_restart(self):
        candidate = self.tools_candidate()
        calls = []
        with patch.object(control, 'compose', side_effect=lambda *args, **kwargs: calls.append((args, kwargs))) as compose, \
                patch.object(control, 'reload_gateway'), patch.object(control, 'maintenance_check'), \
                patch.object(control, 'preserve_assets'), patch.object(control, 'is_running', return_value=True), \
                patch.object(control, 'stop_backend'), patch.object(control, 'do_backup', return_value='synthetic-pre-tools') as backup, \
                patch.object(control, 'ready') as ready:
            control.install_update(self.config, self.release, candidate)
        backup.assert_called_once_with(self.config, self.release)
        ready.assert_called_once_with(self.config, candidate)
        self.assertEqual([args[-1] for args, _ in calls], ['migrate', 'backend', 'frontend'])
        self.assertTrue(all(keywords['release'] == candidate for _, keywords in calls))
        self.assertEqual(control.current(), candidate)

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

    def test_restore_verifies_safety_backup_with_target_tools_before_changing_current_state(self):
        target = self.tools_candidate()
        backup = self.runtime / 'backups' / 'synthetic-safety'
        control.write_json(backup / 'manifest.json', {'release': target})
        # The first restore recorded the formerly installed schema/tools release.
        control.write_json(self.runtime / 'previous-release.json', target)
        calls = []
        def compose(*arguments, **keywords):
            calls.append((arguments, keywords))
            if arguments[-2:] == ('verify-backup', 'synthetic-safety'):
                self.assertEqual(keywords['release']['images']['tools'], target['images']['tools'])
                self.assertEqual(control.current(), self.release)
                self.assertEqual(control.read_json(self.runtime / 'operation.json')['phase'], 'ready')
        with patch.object(control, 'compose', side_effect=compose), patch.object(control, 'ensure_images') as images, \
                patch.object(control, 'reload_gateway'), patch.object(control, 'maintenance_check'), \
                patch.object(control, 'stop_backend'), patch.object(control, 'do_backup', return_value='synthetic-old-safety') as safety, \
                patch.object(control, 'execute'), patch.object(control, 'initialize_volumes'), patch.object(control, 'ready'):
            control.restore_command(SimpleNamespace(backup='synthetic-safety', yes=True))
        images.assert_called_once_with(target)
        self.assertEqual(calls[0][0][-3:], ('ops', 'verify-backup', 'synthetic-safety'))
        safety.assert_called_once_with(self.config, self.release)
        self.assertEqual(control.current(), target)
        self.assertNotEqual(control.load_config()['volumes']['database'], self.config['volumes']['database'])

    def test_restore_rejects_symlink_metadata_and_failed_or_changed_verification_before_mutation(self):
        target = self.tools_candidate()
        control.write_json(self.runtime / 'previous-release.json', target)
        backup = self.runtime / 'backups' / 'synthetic-safety'
        metadata = backup / 'manifest.json'
        for mode in ['directory', 'symlink', 'failed', 'changed']:
            with self.subTest(mode=mode):
                if metadata.is_dir() and not metadata.is_symlink(): metadata.rmdir()
                else: metadata.unlink(missing_ok=True)
                control.write_json(metadata, {'release': target})
                if mode == 'directory':
                    metadata.unlink(); metadata.mkdir()
                elif mode == 'symlink':
                    metadata.rename(backup / 'outside.json')
                    metadata.symlink_to(backup / 'outside.json')
                def verify(*args, **kwargs):
                    if mode == 'failed': raise control.Failure('backup checksum rejected')
                    control.write_json(metadata, {'release': self.release})
                before = {name: (self.runtime / name).read_bytes() for name in ['release.json', 'installation.json', 'operation.json']}
                with patch.object(control, 'ensure_images') as images, patch.object(control, 'compose', side_effect=verify) as compose, \
                        patch.object(control, 'reload_gateway') as gateway, patch.object(control, 'execute') as execute:
                    with self.assertRaises(control.Failure): control.restore_command(SimpleNamespace(backup='synthetic-safety', yes=True))
                gateway.assert_not_called(); execute.assert_not_called()
                if mode in ['directory', 'symlink']: images.assert_not_called(); compose.assert_not_called()
                self.assertEqual({name: (self.runtime / name).read_bytes() for name in before}, before)

    def test_restore_cannot_execute_or_pull_tools_selected_only_by_an_untrusted_backup(self):
        target = self.tools_candidate()
        target['images']['tools'] = 'untrusted.invalid/backup-tools@sha256:' + 'f' * 64
        target['toolsUpgrade']['to'] = target['images']['tools']
        backup = self.runtime / 'backups' / 'synthetic-untrusted'
        control.write_json(backup / 'manifest.json', {'release': target})
        # Pending/uninstalled payloads do not grant trust either.
        control.write_json(self.runtime / 'pending-release.json', target)
        with patch.object(control, 'ensure_images') as images, patch.object(control, 'compose') as compose, \
                patch.object(control, 'confirm', side_effect=control.Failure('declined')) as confirm, \
                patch.object(control, 'reload_gateway') as gateway, patch.object(control, 'execute') as execute:
            with self.assertRaisesRegex(control.Failure, 'reviewed release manifest'):
                control.restore_command(SimpleNamespace(backup='synthetic-untrusted', yes=False))
        images.assert_not_called(); compose.assert_not_called(); confirm.assert_not_called()
        gateway.assert_not_called(); execute.assert_not_called()
        self.assertEqual(control.current(), self.release)
        self.assertEqual(control.read_json(self.runtime / 'operation.json')['phase'], 'ready')

    def test_restore_trusts_valid_local_release_catalog_but_not_invalid_or_symlink_manifests(self):
        target = self.tools_candidate()
        directory = self.runtime.parent / 'trusted-delivery'
        catalog = directory / 'releases'
        control.write_json(catalog / 'source-lock.json', {'backend': 'a' * 40, 'frontend': 'b' * 40})
        control.write_json(catalog / 'invalid.json', {'formatVersion': 1, 'images': {'tools': target['images']['tools']}})
        control.write_json(catalog / 'malformed.json', {'formatVersion': 1, 'releaseId': []})
        outside = self.runtime / 'untrusted-manifest.json'
        control.write_json(outside, target)
        (catalog / 'symlink.json').symlink_to(outside)
        with patch.object(control, 'ROOT', directory):
            with self.assertRaisesRegex(control.Failure, 'not trusted'):
                control.require_trusted_restore_tools(target, self.release)
            control.write_json(catalog / 'reviewed.local.json', target)
            control.require_trusted_restore_tools(target, self.release)

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

    def test_source_build_records_reviewed_old_client_compatibility(self):
        fixture = self.source_build_fixture()
        reviewed = fixture.root / "contracts" / "client-compatibility.json"
        reviewed.write_text(json.dumps(["d" * 64, "d" * 64]))
        with patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command), contextlib.redirect_stdout(io.StringIO()):
            control.build_source(fixture.arguments)
        release = control.manifest(fixture.root / "releases" / "synthetic-built.local.json")
        self.assertEqual(release["supportedClientContractHashes"], [release["contractHash"], "d" * 64])

    def test_source_build_rejects_invalid_or_drifting_client_compatibility(self):
        for index, value in enumerate([{}, ["invalid"], [42], ["d" * 64]]):
            fixture = self.source_build_fixture("compatibility-" + str(index))
            reviewed = fixture.root / "contracts" / "client-compatibility.json"
            reviewed.write_text(json.dumps(value))
            if index == 3:
                fixture.after_frontend_build = lambda: reviewed.write_text(json.dumps(["e" * 64]))
            with patch.object(control, "ROOT", fixture.root), patch.object(control, "execute", side_effect=fixture.command):
                with self.assertRaisesRegex(control.Failure, "changed during build" if index == 3 else "Invalid reviewed"):
                    control.build_source(fixture.arguments)
            self.assertFalse((fixture.root / "releases" / "synthetic-built.local.json").exists())
            if index != 3: self.assertFalse(any(command[0] == "docker" for command in fixture.commands))

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
