# Releases and Updates

*[Русский](../ru/releases.md)*

Delivery **0.1.6** uses public amd64/arm64 images. The [manifest](../../releases/0.1.6.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.6](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.6). See the [release notes](../../releases/0.1.6-preparation.md) for changes and verification.

The published 0.1.5 tags and images remain immutable, but the candidate was not promoted: update acceptance found a restore error. [The candidate record](../../releases/0.1.5-preparation.md) contains the completed checks and failure. Use the corrected release 0.1.6.

## New Installation

Use a new directory:

```sh
git clone --branch main --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave
cd TraceWeave
./bootstrap.sh --release releases/0.1.6.json
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

The script displays installed and available versions and offers an update. After approval it downloads images, enters maintenance, creates and verifies an offline database/originals backup and checks readiness. The update brings the database to schema 9: installations on 0.1.0/0.1.1 apply migrations 7–9, and those on 0.1.3/0.1.4 apply migrations 8–9. Existing migration history and original files remain unchanged. No manual SQL or migration selection is required. Reload the browser tab after completion.

Bootstrap selects the compatible manifest for the installation’s retained infrastructure: [0.1.0](../../releases/0.1.6-update-infra-0.1.0.json), [0.1.1](../../releases/0.1.6-update-infra-0.1.1.json), [0.1.3](../../releases/0.1.6-update-infra-0.1.3.json) or [0.1.4](../../releases/0.1.6-update-infra-0.1.4.json). These four selections also cover installations updated through earlier compatible manifests. Backend/frontend and backup tools become 0.1.6; PostgreSQL and gateway images, runtime and storage remain selected. The manifest explicitly authorizes the coordinated tools upgrade needed to back up arbitrary files. Sessions, originals and earlier open-tab assets remain available; old prepared requests can replay their exact original bytes.

Declining, end of input or non-interactive execution keeps the installed release. Use `./bootstrap.sh --yes` for an explicitly approved automated update. Bootstrap does not downgrade and directs interrupted operations to `resume`/recovery. Git pull alone does not replace containers; Docker Hub publication does not update running installations.

## Rollback and Recovery

After migration to schema 9, image-only rollback to 0.1.3/0.1.4 (schema 7), or to an earlier schema, is refused. An older backend cannot open the migrated database. Use a compatible fixing release or [restore a verified backup](operations.md) into new volumes. Restore returns data to its backup snapshot, retains previous volumes and creates a safety backup of the current state. It revokes existing sessions; sign in again after restoration. A newer safety backup can subsequently restore the state before recovery, using that backup’s matching tools. Keep the reviewed release manifests in `releases/`: the tools image must be known from installed history or this local catalog before the restore can run. See [Operations](operations.md) for the trust check and transient export handling.

Release 0.1.6 adds [arbitrary files and PDF downloads](attachments.md), plus a choice of [raw data or one readable report](exports.md). It fixes authenticated media previews/downloads and includes arbitrary-file originals in backup/restore. It also fixes reading interrupted upload/export/import job errors after restore, including errors written by earlier tools; restored export jobs report their unavailable ZIP instead of failing to load. Graph detail settings, parallel relations, four directions and node deletion with all incident relations remain available.

## Recorded Verification

[Source CI](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38148015729) passed on amd64 and arm64 at the exact tagged commit; [saved evidence](../../releases/verification/0.1.6/source-ci.json). The arm64 job passed an unchanged retry after an earlier account-bootstrap failure of unknown cause.

[Full publication](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38148083930) and [anonymous registry acceptance](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38150048960) passed on native amd64 and arm64. The [application-update run](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38150050904) passed all 18 cases across nine published baselines and both architectures, including arbitrary files, both export formats and safety-backup recovery after restoring an older release.

Saved evidence: [publication](../../releases/verification/0.1.6/publication.json), [registry amd64](../../releases/verification/0.1.6/registry-amd64.json), [registry arm64](../../releases/verification/0.1.6/registry-arm64.json) and [all update records](../../releases/verification/0.1.6/). These checks do not constitute full P0 acceptance or manual verification in real Safari.

---

[Documentation](index.md) · [README](../../README.md)
