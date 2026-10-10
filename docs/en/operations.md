# Operations and Recovery

*[Русский](../ru/operations.md)*

Run commands from the installation directory with the same `TW_RUNTIME_DIR`. Preserve runtime and Docker volumes; do not delete them to bypass failures.

## Daily Commands

| Command | Result |
| --- | --- |
| `./traceweave.sh status` | Origin, release, phase and service status |
| `./traceweave.sh start` | Start the installed application |
| `./traceweave.sh stop` | Graceful stop retaining data |
| `./traceweave.sh restart` | Restart under maintenance |
| `./traceweave.sh logs backend db` | Recent log lines for selected services |
| `./traceweave.sh resume` | Checked continuation of supported interrupted operations |

Maintenance temporarily closes access. Wait for completion and retain browser drafts. Configure SMTP with `./traceweave.sh configure-mail` and your provider's parameters from [Server Deployment](server-deployment.md). Password entry is hidden. Keep private logs/settings private.

## Private Backup

```sh
./traceweave.sh backup
```

The application enters maintenance, consistently copies the database and originals, verifies the copy and resumes work. A completed backup lives in the printed directory under `runtime/backups/`. Confirm completion and copy the **entire directory** to separate protected storage.

Backup includes every account and private authentication records. TraceWeave does not encrypt it; use encryption and restricted access. Separately preserve private `runtime/secrets/`, `installation.json`, `release.json` and the matching delivery files. Never put them in Git, webroot or shared export directories. See [storage and trust boundaries](data-and-security.md).

## Restore to New Storage

Return a complete external backup under its original name to this installation's private `runtime/backups/`, without overwriting another copy or using symlinks. Enter its name, not a path:

```sh
printf 'Completed backup name under runtime/backups/: '
IFS= read -r TW_BACKUP_NAME
./traceweave.sh restore --backup "$TW_BACKUP_NAME"
./traceweave.sh status
```

Restore asks for confirmation, creates a safety backup of current state and new database/files volumes. Old volumes remain. Allow space for both copies and new storage. Sign in again after successful restore. Later records remain in the earlier volumes/safety backup; they are not automatically merged with the chosen older snapshot.

## Interrupted Operations

Read `status` and logs first, fix the cause and retain maintenance. Repeat bootstrap with the same runtime and selected release. Supported update/backup/restart phases use `resume`; interrupted restore refuses automatic resume. `./traceweave.sh restore-revert` returns to saved previous volumes/release while retaining the restore candidate.

Use [Releases](releases.md) for updates/rollback. Do not launch a second competing operation or substitute volume deletion/raw `docker compose down` for recovery. If the CLI refuses an operation, preserve its state and diagnostic messages for investigation.

---

[Documentation](index.md) · [README](../../README.md)
