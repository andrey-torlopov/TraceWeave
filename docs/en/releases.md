# Releases and Updates

*[Русский](../ru/releases.md)*

Delivery **0.2.2** uses public amd64/arm64 images. The [manifest](../../releases/0.2.2.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.2.2](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.2.2). See the [release notes](../../releases/0.2.2-preparation.md) for changes and verification.

## 0.2.2

Document cards open in reading mode with formatted notes, attachments and readable attributes. The accessible ✍️ toggle beside Close exposes the existing editor without discarding shared drafts. Header controls stay visible; narrow screens and both themes are supported. API 1.4.0/schema 11 unchanged. Native publication, anonymous installation and all 254 updates passed; [verification](../../releases/verification/0.2.2/verification-summary.json).

## 0.2.1

Fixed-size graph action menus, a resizable editor with per-project browser width preferences and immediate attachment-status reconciliation. The maintenance page preserves real HTML newlines. API 1.4.0/schema 11 unchanged. Native publication, anonymous installation and all 180 updates passed; [verification](../../releases/verification/0.2.1/verification-summary.json).

The published 0.1.5 tags and images remain immutable, but the candidate was not promoted: update acceptance found a restore error. [The candidate record](../../releases/0.1.5-preparation.md) contains the completed checks and failure. Use release 0.2.2, which includes that correction.

## New Installation

Use a new directory:

```sh
git clone --branch main --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave
cd TraceWeave
./bootstrap.sh --release releases/0.2.2.json
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

The script displays installed and available versions and offers an update. After approval it downloads images, enters maintenance, creates and verifies an offline database/originals backup and applies missing migrations through schema 11. Updating from 0.1.7–0.1.9 adds migration 11; earlier releases also apply their other missing migrations in order. Existing migration history and original files remain unchanged. No manual SQL or migration selection is required. Reload the browser tab after completion.

Bootstrap selects an exact manifest by installed tools and gateway versions. Backend/frontend become 0.2.2. For installations already on schema 11, the installed tools remain unchanged; older schemas receive a coordinated tools update. PostgreSQL, gateway, runtime and storage are retained. Sessions, originals, open-tab assets and exact prepared requests remain available. See the [release notes](../../releases/0.2.2-preparation.md).

Declining, end of input or non-interactive execution keeps the installed release. Use `./bootstrap.sh --yes` for an explicitly approved automated update. Bootstrap does not downgrade and directs interrupted operations to `resume`/recovery. Git pull alone does not replace containers; Docker Hub publication does not update running installations.

## Rollback and Recovery

Image-only rollback from 0.2.2 to 0.2.1 is supported when the migration histories match.

Image-only rollback from 0.2.1 to 0.2.0 is supported when the migration histories match.

Release 0.2.0 upgrades the database to schema 11. `./traceweave.sh rollback --yes` refuses image-only rollback to 0.1.9 or an earlier schema: the old backend cannot open the migrated database.

Use a compatible fixing release or [restore a verified backup](operations.md) into new volumes. Restore returns data to its backup snapshot, retains previous volumes and creates a safety backup of the current state. It revokes existing sessions; sign in again. A newer safety backup can recover the state before restoration with its matching tools. Keep reviewed release manifests in `releases/`: the tools image must be known from installed history or this local catalog. After recovery, verify status, sign-in, documents and original downloads.

Release 0.2.0 adds [full project ZIP transfer](exports.md), an icon grid for document types and a personal emoji for the selected card. Emoji leaves the type and other cards unchanged and survives transfer.

Release 0.1.9 adds independently configurable icon size and a decimal card-to-icon threshold. See [Graph settings](features.md).

Release 0.1.8 shows all card attachments as buttons with their kind and filename. Select a button to preview one image, audio or video; other files download for local viewing. Switching stops the previous player. Add files together or consecutively. Detaching keeps the original and other attachments.

Release 0.1.7 adds **Улика** (Evidence) with the 🔍 magnifier in the document type selector. Existing documents and assessments are preserved, and a custom type with the same code or name is not overwritten or duplicated.

Release 0.1.6 added [arbitrary files and PDF downloads](attachments.md), plus a choice of [raw data or one readable report](exports.md). It fixes authenticated media previews/downloads and includes arbitrary-file originals in backup/restore. It also fixes reading interrupted upload/export/import job errors after restore, including errors written by earlier tools; restored export jobs report their unavailable ZIP instead of failing to load. Graph detail settings, parallel relations, four directions and node deletion with all incident relations remain available.

## Recorded Verification

Publication and anonymous installation of 0.2.0 passed on native Linux amd64/arm64. The built amd64 container passed 10 Chromium editor/transfer scenarios, 33 graph scenarios and 11 attachment scenarios. Anonymous pulls produced the exact tested native image IDs. A real ZIP64 writer/reader roundtrip of 4,831,854,009 bytes passed on macOS arm64 with matching original sizes and SHA-256. [Publication](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38752689149), [CI](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38751555640), [registry](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38756147808). All 124 native update cases from 62 published installation variants passed, including automatic backup, migration 11, exact pending replay and both directions of backup recovery: [record](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38757674385). Real Safari, Firefox, the load matrix and complete P0 acceptance were not run separately.

---

[Documentation](index.md) · [README](../../README.md)
