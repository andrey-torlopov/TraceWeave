# Operations and Recovery

*[Русский](../ru/operations.md)*

Run commands from the installation checkout with the same `TW_RUNTIME_DIR`. The controller serializes mutations with `runtime/operation.lock`; phase/journal files remain outside containers. Do not remove them to bypass a failed operation.

## Command Reference

| Command | Result |
| --- | --- |
| `./traceweave.sh start` | Start/check db and gateway, then applications; validate release/schema/readiness. |
| `./traceweave.sh stop` | Confirm maintenance, stop backend gracefully, then the other services; retain volumes. |
| `./traceweave.sh restart` | Restart applications under maintenance without stopping PostgreSQL/gateway. |
| `./traceweave.sh status` | URL, release, phase, volumes and Compose status. |
| `./traceweave.sh logs backend db` | Last 100 lines of the selected allowed services. |
| `./traceweave.sh maintenance on` | Enable maintenance; finish through checked `resume`, not manual maintenance off. |
| `./traceweave.sh resume` | Phase-specific recovery. |

Gateway maintenance returns HTML/JSON 503 with `service_maintenance`, no-store and Retry-After 15. `/release.json` remains readable. Backend exit must be graceful, with no running/OOMKilled state and code 0 or 143. SIGKILL/OOM leaves access closed and a recoverable interrupted phase. The frontend keeps drafts/pending bytes; it does not forcibly reload or silently replay another account's work.

## Accounts and Mail

Bootstrap creates the first account. Administrative `account create` is only for an empty installation; additional users use explicitly enabled HTTPS/SMTP registration. To reset a selected existing account:

```sh
printf 'Existing account email: '
IFS= read -r TW_ACCOUNT_EMAIL
./traceweave.sh account reset-password --email "$TW_ACCOUNT_EMAIL"
```

Password entry is hidden. Mail settings are changed with [configure-mail](installation.md#https-and-smtp). Changing an account does not transfer ownership of its research.

## Private Offline Backup

```sh
./traceweave.sh backup
```

The controller verifies maintenance, stops backend, holds the maintenance lease and creates a database custom-format dump plus immutable originals. Losing the lease aborts the dump. After successful checks it starts backend and reopens access. The printed directory is under `runtime/backups/`.

The manifest records release images, versions, migration history, database size and SHA-256 of dump/originals. Ops checks free space using `requiredBytes = 2 × databaseBytes + originalBytes + 64 × 1024 × 1024`; update also checks 1 GiB in runtime. Staging/transient export output is not a completed research result.

Backup contains all accounts and private authentication data. Keep files private and encrypted on separate protected storage, outside Git/webroot/user export. Separately preserve `runtime/secrets/`, `installation.json`, `release.json` and required manifests. Check that the operation completed before moving the directory. To restore an external copy, return the complete original directory into this installation's private `runtime/backups/`, without symlinks or overwriting another backup ID.

## Restore to New Volumes

```sh
printf 'Existing backup directory name under runtime/backups/: '
IFS= read -r TW_BACKUP_NAME
./traceweave.sh restore --backup "$TW_BACKUP_NAME"
```

Restore validates manifests/images/hashes, requests confirmation, enters maintenance and takes a safety backup of the current state. It creates new database/files volumes; old volumes are retained. Capacity is checked against both new storage mounts using the backup's positive `databaseBytes` and the same budget above. Preflight does not reserve space; allow for shared disks and ongoing growth.

After restoring/checking dump, blobs, references and migrations, sessions/tokens are revoked and transient jobs interrupted. Readiness precedes switching to the restored installation. Users sign in again. Later data is retained in the old volumes/safety backup, not merged with the selected older snapshot.

## Interrupted Operations

Read `status` and logs first; keep maintenance enabled. Do not start a second update/backup/restore.

| Phase | Recovery |
| --- | --- |
| `bootstrap-*` | Repeat bootstrap with the same manifest/origin and account details, or its prompted resume procedure. |
| `update-*` | `resume` uses saved source/pending manifests; compatible `rollback` is an alternative. After schema changes, use a fix or backup restore. |
| `rollback-*` | Repeat the compatible rollback after fixing its cause. |
| `backup-*`, `restart-*`, `stopping`, `maintenance-*` | `resume` checks current services before reopening access. An incomplete backup stays failed. |
| `restore-*` | Automatic resume is refused; use `restore-revert` or an explicitly verified operator recovery. |
| `stopped-interrupted` | Resume the original interrupted phase. |

`./traceweave.sh restore-revert` returns to saved pre-restore volumes/release and retains the restore candidate. It does not merge records written after restoration. Update/rollback/resume/restore require TTY confirmation; `--yes` skips only the confirmation, not guards, hashes or password entry. Never substitute volume deletion or raw Compose teardown for recovery.

---

[Back to documentation](index.md) · [README](../../README.md)
