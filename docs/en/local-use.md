# TraceWeave on Your Computer

*[Русский](../ru/local-use.md)*

## Current Source Build

Install and start Docker, then follow [Quick Start](quick-start.md). It builds a local manifest from the three independent repositories. If images already exist on this Docker-host, select their existing manifest from the delivery checkout:

```sh
printf 'Path to existing local release manifest: '
IFS= read -r TW_RELEASE_MANIFEST
test -f "$TW_RELEASE_MANIFEST"
./bootstrap.sh --release "$TW_RELEASE_MANIFEST"
```

Local image IDs work only on their original Docker-host. Copying the manifest does not copy images.

## Published Release

Public application images have not been released yet. When a verified delivery package includes the immutable release files, clone that published delivery revision and run `./bootstrap.sh`. Docker downloads the selected images and prepares the database. The script prompts for email, name and a hidden password and prints **http://127.0.0.1:8080**.

Sign in with that email/password. The local address is available only on your computer; no SSH, domain or SMTP is required. If port 8080 is occupied on a new installation, add `--port 18080` to bootstrap and use **http://127.0.0.1:18080**. An existing installation retains its saved origin.

## Stop and Restart

```sh
./traceweave.sh stop
./bootstrap.sh
```

The installed release, account and research data survive stopping. Keep the checkout/runtime and Docker volumes. Repeat bootstrap uses the installed manifest and does not update the application.

If installation was interrupted, repeat bootstrap with the same manifest or use the phase-specific [Operations](operations.md) recovery procedure. Detailed prerequisites and builds are in [Installation](installation.md).

---

[Back to documentation](index.md) · [README](../../README.md)
