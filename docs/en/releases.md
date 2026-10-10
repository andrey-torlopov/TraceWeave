# Releases and Updates

*[Русский](../ru/releases.md)*

Release **0.1.0** has public amd64/arm64 images. The verified [manifest](../../releases/0.1.0.json), [default selection](../../releases/stable.json) and [tools image](../../releases/tools-image.txt) are available here and in [GitHub Release v0.1.0](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0).

## Exact 0.1.0 Installation

Use a new destination directory:

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.0
cd TraceWeave-0.1.0
curl -fL --output releases/0.1.0.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/0.1.0.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/tools-image.txt
./bootstrap.sh --release releases/0.1.0.json
```

Delivery files must match their release manifest. Images are pinned by content digest. Private sources and registry sign-in are unnecessary. The historical tag can contain old documentation statuses; current user guides live in main.

## Updating an Existing Installation

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
