# Releases and Updates

*[Русский](../ru/releases.md)*

Delivery **0.1.7** uses public amd64/arm64 images. The [manifest](../../releases/0.1.7.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.7](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.7). See the [release notes](../../releases/0.1.7-preparation.md) for changes and verification.

The published 0.1.5 tags and images remain immutable, but the candidate was not promoted: update acceptance found a restore error. [The candidate record](../../releases/0.1.5-preparation.md) contains the completed checks and failure. Use release 0.1.7, which includes that correction.

## New Installation

Use a new directory:

```sh
git clone --branch main --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave
cd TraceWeave
./bootstrap.sh --release releases/0.1.7.json
```

Images are pinned by digest. Private sources and registry sign-in are unnecessary. Historical tags may contain earlier documentation statuses; current guides live in main.

## Existing Installation

For a checkout already tracking `main`, run from its directory with the same runtime:

```sh
git pull --ff-only && ./bootstrap.sh
./traceweave.sh status
```

If the installation was cloned from a release tag, its checkout has a detached HEAD and cannot use that pull command. Start in the **original installation directory**, with the original `TW_RUNTIME_DIR` set if you used a custom location. The following checks the existing runtime, prints its absolute path and creates a separate checkout tracking `main`:

```sh
TW_EXISTING_RUNTIME=${TW_RUNTIME_DIR:-$PWD/runtime}
if [ ! -L "$TW_EXISTING_RUNTIME" ] &&
   [ -f "$TW_EXISTING_RUNTIME/installation.json" ] &&
   TW_RUNTIME_DIR=$(CDPATH= cd -- "$TW_EXISTING_RUNTIME" && pwd -P); then
  export TW_RUNTIME_DIR
  printf 'Existing runtime: %s\n' "$TW_RUNTIME_DIR"
  TW_DELIVERY_DIR=$(mktemp -d "$(dirname "$PWD")/TraceWeave-main.XXXXXX") &&
  git clone --branch main --depth 1 https://github.com/andrey-torlopov/TraceWeave.git "$TW_DELIVERY_DIR" &&
  printf '%s\n' "$TW_RUNTIME_DIR" > "$TW_DELIVERY_DIR/.git/traceweave-runtime-path" &&
  cd "$TW_DELIVERY_DIR" &&
  printf 'Delivery directory: %s\n' "$PWD" &&
  ./bootstrap.sh &&
  ./traceweave.sh status
else
  printf 'Existing installation.json not found, or runtime is a symlink. Check the original runtime location.\n' >&2
fi
```

Keep the original checkout, runtime and Docker volumes in place. The new checkout stores only the runtime path in its local Git metadata. In **each new terminal**, enter this new checkout and restore the variable before any `bootstrap.sh` or `traceweave.sh` command:

```sh
TW_RUNTIME_DIR=$(cat .git/traceweave-runtime-path) &&
test -f "$TW_RUNTIME_DIR/installation.json" &&
export TW_RUNTIME_DIR &&
./traceweave.sh status
```

If this check fails, locate the original runtime before continuing. Once it succeeds, use the ordinary `git pull --ff-only` and bootstrap commands above for later updates. Keep this absolute `TW_RUNTIME_DIR` for backup, restore and other CLI commands too.

The script displays installed and available versions and offers an update. After approval it downloads images, enters maintenance, creates and verifies an offline database/originals backup and checks readiness. The update brings the database to schema 10: installations on 0.1.0/0.1.1 apply migrations 7–10, those on 0.1.3/0.1.4 apply migrations 8–10, and 0.1.6 applies migration 10. Existing migration history and original files remain unchanged. No manual SQL or migration selection is required. Reload the browser tab after completion.

Bootstrap selects the compatible manifest by the installed tools and retained gateway. Nine variants cover fourteen published baselines: infrastructure-only manifests for gateways 0.1.0, 0.1.1, 0.1.3, 0.1.4 and 0.1.6, plus four `0.1.7-update-from-0.1.6-infra-VERSION.json` manifests for 0.1.6 with an older gateway. No manual selection is needed. Backend/frontend and backup tools become 0.1.7; PostgreSQL and gateway images, runtime and storage remain selected. Sessions, originals and earlier open-tab assets remain available; old prepared requests can replay their exact original bytes. The [release notes](../../releases/0.1.7-preparation.md) describe the migration and preservation rules.

Declining, end of input or non-interactive execution keeps the installed release. Use `./bootstrap.sh --yes` for an explicitly approved automated update. Bootstrap does not downgrade and directs interrupted operations to `resume`/recovery. Git pull alone does not replace containers; Docker Hub publication does not update running installations.

## Rollback and Recovery

After migration to schema 10, image-only rollback to 0.1.6 (schema 9), or to an earlier schema, is refused. An older backend cannot open the migrated database. Use a compatible fixing release or [restore a verified backup](operations.md) into new volumes. Restore returns data to its backup snapshot, retains previous volumes and creates a safety backup of the current state. It revokes existing sessions; sign in again after restoration. A newer safety backup can subsequently restore the state before recovery, using that backup’s matching tools. Keep the reviewed release manifests in `releases/`: the tools image must be known from installed history or this local catalog before the restore can run. See [Operations](operations.md) for the trust check and transient export handling.

Release 0.1.7 adds **Улика** (Evidence) with the 🔍 magnifier in the document type selector. Existing documents and assessments are preserved, and a custom type with the same code or name is not overwritten or duplicated.

Release 0.1.6 added [arbitrary files and PDF downloads](attachments.md), plus a choice of [raw data or one readable report](exports.md). It fixes authenticated media previews/downloads and includes arbitrary-file originals in backup/restore. It also fixes reading interrupted upload/export/import job errors after restore, including errors written by earlier tools; restored export jobs report their unavailable ZIP instead of failing to load. Graph detail settings, parallel relations, four directions and node deletion with all incident relations remain available.

## Recorded Verification

Publication and CI for the exact 0.1.7 revision passed on native amd64/arm64. Anonymous installation passed on both architectures, as did all 28 guided updates from 14 published baselines, including retained-infrastructure 0.1.6 variants. Checks cover the evidence type in existing and new investigations, persistence, both exports, original file bytes, backup/restore and incompatible rollback refusal. [Publication](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38152843115), [CI](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38152733591), [registry](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38154645985), [updates](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38154648811). Machine-readable [evidence](../../releases/verification/0.1.7/publication.json) is attached to the release. Real Safari and full P0 acceptance were not run separately.

---

[Documentation](index.md) · [README](../../README.md)
