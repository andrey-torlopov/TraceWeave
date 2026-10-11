# Releases and Updates

*[Русский](../ru/releases.md)*

Delivery **0.1.3** uses public amd64/arm64 images. The verified [manifest](../../releases/0.1.3.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.3](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.3).

## New Installation

Use a new directory:

```sh
git clone --branch v0.1.3 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.3
cd TraceWeave-0.1.3
curl -fL --output releases/0.1.3.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.3/0.1.3.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.3/tools-image.txt
./bootstrap.sh --release releases/0.1.3.json
```

Images are pinned by digest. Private sources and registry sign-in are unnecessary. Historical tags may contain earlier documentation statuses; current guides live in main.

## Existing Installation

From its original directory with the same runtime:

```sh
git pull --ff-only
./bootstrap.sh
./traceweave.sh status
```

The script displays installed and available versions and offers an update. After approval it downloads images, enters maintenance, creates and verifies an offline database/originals backup, applies migration 7 automatically and checks readiness. No manual SQL or migration selection is required. Reload the browser tab after completion.

For 0.1.0 and 0.1.1 installations, bootstrap selects the reviewed compatible manifest automatically: [retained 0.1.0 infrastructure](../../releases/0.1.3-update.json) or [full 0.1.1 installation](../../releases/0.1.3-update-from-0.1.1.json). Backend/frontend become 0.1.3 while database, gateway, tools, runtime and storage remain selected. Sessions, originals and earlier open-tab assets remain available; old prepared requests can replay their exact original bytes.

Declining, end of input or non-interactive execution keeps the installed release. Use `./bootstrap.sh --yes` for an explicitly approved automated update. Bootstrap does not downgrade and directs interrupted operations to `resume`/recovery. Git pull alone does not replace containers; Docker Hub publication does not update running installations.

## Recovery After Migration

Release 0.1.3 changes the database schema. Ordinary `./traceweave.sh rollback` refuses old images on the new schema. Use a compatible fixing release or [restore a verified backup](operations.md) into new volumes. Restore returns data to its backup snapshot, retains previous volumes and creates a safety backup of the current state. It revokes existing sessions; sign in again after restoration.

Release 0.1.3 allows parallel relations, four directions and fixed dialog endpoints. Deleting a node still removes all incoming/outgoing relations.

---

[Documentation](index.md) · [README](../../README.md)

Verification: [publication](../../releases/verification/0.1.3/publication.json), [clean-host amd64](../../releases/verification/0.1.3/registry-amd64.json), [clean-host arm64](../../releases/verification/0.1.3/registry-arm64.json). Six native [schema update cases](../../releases/verification/0.1.3/) cover 0.1.0 and both 0.1.1 infrastructure selections.
