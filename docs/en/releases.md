# Releases and Updates

*[Русский](../ru/releases.md)*

Release **0.1.1** has public amd64/arm64 images. The verified [manifest](../../releases/0.1.1.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.1](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.1).

## Exact 0.1.1 Installation

Use a new destination directory:

```sh
git clone --branch v0.1.1 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.1
cd TraceWeave-0.1.1
curl -fL --output releases/0.1.1.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/0.1.1.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/tools-image.txt
./bootstrap.sh --release releases/0.1.1.json
```

Delivery files must match their release manifest. Images are pinned by content digest. Private sources and registry sign-in are unnecessary. The historical tag can contain old documentation statuses; current user guides live in main.

## Updating an Existing Installation

To upgrade **0.1.0**, retain its delivery directory and runtime. Use the separate [update manifest](../../releases/0.1.1-update.json): it selects backend/frontend 0.1.1 and retains gateway/tools 0.1.0 and the existing PostgreSQL18.6 image. The full `0.1.1.json` is for a new installation; the existing operator refuses gateway/tools changes through ordinary update.

From the installed 0.1.0 directory:

```sh
curl -fL --output releases/0.1.1-update.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.1/0.1.1-update.json
./traceweave.sh update --release releases/0.1.1-update.json
./traceweave.sh status
```

The update takes an offline backup and retains earlier browser assets for open tabs. Migration history and the contract stay compatible; `./traceweave.sh rollback` restores the previous image pair while retaining data written after the update. Original files remain stored. Release 0.1.1 adds node deletion from its menu, inspector and editor, removing every incident relation.

Updates are explicit. After obtaining a compatible delivery and its verified manifest, run from the installation checkout with the same runtime:

```sh
printf 'Absolute path to the verified update manifest: '
IFS= read -r TW_RELEASE_MANIFEST
test -f "$TW_RELEASE_MANIFEST"
./traceweave.sh update --release "$TW_RELEASE_MANIFEST"
./traceweave.sh status
```

Review preflight and confirm in the terminal. The update retains volumes and, when needed, takes a backup/migrates under maintenance. Do not mix arbitrary component versions. An open browser tab may request a reload after preserving drafts.

Image rollback requires compatible schema history:

```sh
./traceweave.sh rollback
```

After schema changes you may need a compatible fixing release or the earlier backup. See [recovery](operations.md). Publishing a release does not update existing installations.

---

[Documentation](index.md) · [README](../../README.md)
