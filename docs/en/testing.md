# Testing and Acceptance

*[Русский](../ru/testing.md)*

## Local Contract and Operator Checks

The existing CI installs pinned validation dependencies, validates contracts and runs isolated operator tests before image builds. Reproduce its non-container checks with a disposable virtual environment:

```sh
TW_CHECK_VENV=$(mktemp -d "${TMPDIR:-/tmp}/traceweave-checks.XXXXXX")
python3 -m venv "$TW_CHECK_VENV"
"$TW_CHECK_VENV/bin/pip" install -r tools/requirements-validation.txt
"$TW_CHECK_VENV/bin/python" tools/validate_contracts.py
"$TW_CHECK_VENV/bin/python" -m unittest discover -s tests -v
"$TW_CHECK_VENV/bin/python" -m unittest discover -s tests/contracts -p test_contracts.py -v
python3 -I tools/ci_release_tests.py --self-test
sh -n bootstrap.sh traceweave.sh db/entrypoint.sh db/init.sh
```

These checks do not migrate the application database. Real lifecycle tests are separate and create data; only point them at marked synthetic installations.

## Full Delivery Checks

[Docker delivery CI](../../.github/workflows/delivery.yml) checks locked independent source revisions on Linux amd64 and arm64. It builds images, then exercises real API/media/export/restart/maintenance/restore, selective updates, marked fault recovery, account isolation, SMTP and HTTPS. It does not publish images.

| Runner | Scope |
| --- | --- |
| `tools/integration.py` | Synthetic installation and API lifecycle |
| `tools/update_integration.py` | Frontend-only/backend-only transitions |
| `tools/fault_integration.py` | Marked synthetic failure/recovery cases |
| `tests/account_https.py` | Account/mail/HTTPS acceptance fixtures |

Use each runner's `--help` and required marked test root; preserve its evidence. Running a component unit suite or generating documentation is not equivalent to this protocol.

## Acceptance Boundary

E0/E1 and the scoped local Docker package have recorded acceptance separately. Full P0 remains separate, including unresolved [extensions 16 KiB](../change-requests/CR-E2-001-extensions-byte-limit.md), browser/performance checks and all applicable AC. Real Safari requires its own manual evidence; headless WebKit is insufficient. Never relabel historical or skipped checks as current passes.

---

[Back to documentation](index.md) · [README](../../README.md)
