# Releases and Updates

*[Русский](../ru/releases.md)*

Delivery **0.1.4** uses public amd64/arm64 images. The verified [manifest](../../releases/0.1.4.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.4](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.4).

## New Installation

Use a new directory:

```sh
git clone --branch v0.1.4 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.4
cd TraceWeave-0.1.4
curl -fL --output releases/0.1.4.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.4/0.1.4.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.4/tools-image.txt
./bootstrap.sh --release releases/0.1.4.json
```

Images are pinned by digest. Private sources and registry sign-in are unnecessary. Historical tags may contain earlier documentation statuses; current guides live in main.

## Existing Installation

From its original directory with the same runtime:

```sh
git pull --ff-only
./bootstrap.sh
./traceweave.sh status
```

The script displays installed and available versions and offers an update. After approval it downloads images, enters maintenance, creates and verifies an offline database/originals backup and checks readiness. Moving from 0.1.3 needs no migration; moving from 0.1.0/0.1.1 applies existing migration 7 automatically. No manual SQL or migration selection is required. Reload the browser tab after completion.

For 0.1.0, 0.1.1 and 0.1.3 installations, bootstrap selects the reviewed compatible manifest for the retained infrastructure: [0.1.0](../../releases/0.1.4-update-infra-0.1.0.json), [0.1.1](../../releases/0.1.4-update-infra-0.1.1.json) or [0.1.3](../../releases/0.1.4-update-infra-0.1.3.json). Backend/frontend become 0.1.4 while database, gateway, tools, runtime and storage remain selected. Sessions, originals and earlier open-tab assets remain available; old prepared requests can replay their exact original bytes.

Declining, end of input or non-interactive execution keeps the installed release. Use `./bootstrap.sh --yes` for an explicitly approved automated update. Bootstrap does not downgrade and directs interrupted operations to `resume`/recovery. Git pull alone does not replace containers; Docker Hub publication does not update running installations.

## Rollback and Recovery

The database schema is unchanged between 0.1.3 and 0.1.4; `./traceweave.sh rollback --yes` restores the previous images while preserving data. After moving from 0.1.0/0.1.1 to schema 7, ordinary image rollback is refused. Use a compatible fixing release or [restore a verified backup](operations.md) into new volumes. Restore returns data to its backup snapshot, retains previous volumes and creates a safety backup of the current state. It revokes existing sessions; sign in again after restoration.

Release 0.1.4 adds [graph detail settings](features.md): a gear button, an integer shrink factor from 2 to 10 and a default of 3. With 5, cards become compact nodes at 20% zoom or below. Parallel relations, four directions and node deletion with all incident relations remain available.

---

[Documentation](index.md) · [README](../../README.md)

Verification: [publication](../../releases/verification/0.1.4/publication.json), [clean-host amd64](../../releases/verification/0.1.4/registry-amd64.json), [clean-host arm64](../../releases/verification/0.1.4/registry-arm64.json). Ten native [application update cases](../../releases/verification/0.1.4/) cover 0.1.0, 0.1.1 and all three 0.1.3 infrastructure selections, graph-settings JavaScript, exact prepared-request replay, rollback and backup restore.
