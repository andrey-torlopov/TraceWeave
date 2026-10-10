"""Offline Docker-only wrapper preflight; every Docker call hits a stub."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
WRAPPER = Path(__file__).resolve().parents[1] / 'traceweave.sh'
PUBLIC_PIN = 'ghcr.io/andrey-torlopov/traceweave/tools@sha256:' + 'a' * 64
EXPLICIT_PIN = 'registry.example.test/custom/tools@sha256:' + 'b' * 64
STUB_STOP = 73


class WrapperPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='traceweave-wrapper-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / 'delivery checkout'
        self.checkout.mkdir()
        shutil.copy2(WRAPPER, self.checkout / 'traceweave.sh')
        (self.checkout / 'releases').mkdir()
        self.bin = self.root / 'stub-bin'
        self.bin.mkdir()
        # Keep only the host utilities needed before the intentional stop.
        # In particular, neither python3 nor a real docker is on this PATH.
        for command in ('dirname', 'cat'):
            executable = shutil.which(command)
            self.assertIsNotNone(executable, command + ' is required by the wrapper test')
            (self.bin / command).symlink_to(executable)
        self.calls_file = self.root / 'docker-argv.bin'
        docker = self.bin / 'docker'
        docker.write_text('''#!/bin/sh
set -eu
printf '%s\\0' "$@" >> "$TW_STUB_CALLS"
printf '\\0' >> "$TW_STUB_CALLS"
case "${1-} ${2-}" in
  'image inspect') exit "${TW_STUB_INSPECT_STATUS:-1}";;
  'pull '*|'build '*) exit 73;;
  'context inspect') exit 73;;
  *) echo 'Unexpected command in offline Docker preflight test.' >&2; exit 74;;
esac
''')
        docker.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('TW_')}
        self.env.update(PATH=str(self.bin), TW_STUB_CALLS=str(self.calls_file))
        no_python = subprocess.run(['/bin/sh', '-c', 'command -v python3'], env=self.env,
                                   capture_output=True, text=True, timeout=5)
        self.assertNotEqual(no_python.returncode, 0, 'Test PATH must select Docker-only fallback')

    def pin_file(self, content):
        (self.checkout / 'releases' / 'tools-image.txt').write_text(content)

    def run_wrapper(self, **environment):
        result = subprocess.run(['/bin/sh', str(self.checkout / 'traceweave.sh'), 'status'],
                                cwd=self.checkout, env={**self.env, **environment},
                                capture_output=True, text=True, timeout=5)
        calls = []
        if self.calls_file.exists():
            for invocation in self.calls_file.read_bytes().split(b'\0\0'):
                if invocation:
                    calls.append([argument.decode('utf-8') for argument in invocation.split(b'\0')])
        return result, calls

    def test_public_pin_is_passed_unchanged_to_inspect_and_pull_without_build(self):
        for terminal_newline in ('', '\n'):
            with self.subTest(terminal_newline=bool(terminal_newline)):
                self.pin_file(PUBLIC_PIN + terminal_newline)
                self.calls_file.unlink(missing_ok=True)
                result, calls = self.run_wrapper()
                self.assertEqual(result.returncode, STUB_STOP, result.stderr)
                self.assertEqual(calls, [['image', 'inspect', PUBLIC_PIN], ['pull', PUBLIC_PIN]])

    def test_cached_public_pin_does_not_pull_or_build(self):
        self.pin_file(PUBLIC_PIN + '\n')
        result, calls = self.run_wrapper(TW_STUB_INSPECT_STATUS='0')
        self.assertEqual(result.returncode, STUB_STOP, result.stderr)
        self.assertEqual(calls[0], ['image', 'inspect', PUBLIC_PIN])
        self.assertEqual([call[:2] for call in calls], [['image', 'inspect'], ['context', 'inspect']])

    def test_malformed_pins_fail_before_any_docker_command(self):
        repository = 'ghcr.io/andrey-torlopov/traceweave/tools@sha256:'
        malformed = {
            'empty': '',
            'floating tag': 'ghcr.io/andrey-torlopov/traceweave/tools:latest\n',
            '64 nonhex characters': repository + 'z' * 64 + '\n',
            'uppercase digest': repository + 'A' * 64 + '\n',
            'short digest': repository + 'a' * 63 + '\n',
            'long digest': repository + 'a' * 65 + '\n',
            'repository whitespace': 'ghcr.io/unsafe tools@sha256:' + 'a' * 64 + '\n',
            'second reference line': PUBLIC_PIN + '\n' + EXPLICIT_PIN + '\n',
            'extra blank line': PUBLIC_PIN + '\n\n',
            'extra text line': PUBLIC_PIN + '\nextra\n',
            'duplicate digest suffix': PUBLIC_PIN + '@sha256:' + 'a' * 64 + '\n',
        }
        for label, content in malformed.items():
            with self.subTest(pin_kind=label):
                self.pin_file(content)
                self.calls_file.unlink(missing_ok=True)
                result, calls = self.run_wrapper()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('Invalid published operator', result.stderr)
                self.assertEqual(calls, [], 'Malformed pin must not reach even local image inspect')

    def test_shell_payload_is_rejected_without_execution_or_registry_access(self):
        marker = self.root / 'payload-was-executed'
        # This command uses only shell builtins, so PATH isolation alone cannot
        # hide a mistaken eval or command substitution of file contents.
        for payload in ['$(printf executed > "' + str(marker) + '")',
                        '`printf executed > "' + str(marker) + '"`',
                        '; printf executed > "' + str(marker) + '";']:
            with self.subTest(payload_kind=payload[0]):
                self.pin_file('ghcr.io/' + payload + '@sha256:' + 'a' * 64 + '\n')
                result, calls = self.run_wrapper()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('Invalid published operator', result.stderr)
                self.assertEqual(calls, [])
                self.assertFalse(marker.exists(), 'Pin file contents must never be evaluated')

    def test_explicit_tools_image_has_priority_over_malformed_pin_file(self):
        self.pin_file('malformed file must be ignored\n')
        result, calls = self.run_wrapper(TW_TOOLS_IMAGE=EXPLICIT_PIN)
        self.assertEqual(result.returncode, STUB_STOP, result.stderr)
        self.assertEqual(calls, [['image', 'inspect', EXPLICIT_PIN], ['pull', EXPLICIT_PIN]])

    def test_explicit_cached_local_image_has_priority_over_public_pin(self):
        self.pin_file(PUBLIC_PIN + '\n')
        explicit = 'sha256:' + 'c' * 64
        result, calls = self.run_wrapper(TW_TOOLS_IMAGE=explicit, TW_STUB_INSPECT_STATUS='0')
        self.assertEqual(result.returncode, STUB_STOP, result.stderr)
        self.assertEqual(calls[0], ['image', 'inspect', explicit])
        self.assertEqual([call[:2] for call in calls], [['image', 'inspect'], ['context', 'inspect']])

    def test_no_pin_file_preserves_default_local_tools_build(self):
        result, calls = self.run_wrapper()
        self.assertEqual(result.returncode, STUB_STOP, result.stderr)
        default = 'traceweave/tools:docker-1'
        self.assertEqual(calls, [['image', 'inspect', default],
                                ['build', '-t', default, '-f', str(self.checkout / 'tools' / 'Dockerfile'), str(self.checkout)]])


if __name__ == '__main__':
    unittest.main()
