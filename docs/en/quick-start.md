# Quick Start

*[Русский](../ru/quick-start.md)*

Install Docker with Linux containers, Docker Compose and Git; use an interactive terminal. Component source access and GitHub/Docker Hub accounts are unnecessary. Release 0.1.2 images are public for amd64 and arm64.

From the parent directory of a new installation:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
cd TraceWeave
./bootstrap.sh
./traceweave.sh status
```

Bootstrap downloads pinned images, prepares storage and prompts for email, display name and a hidden password. Open **http://127.0.0.1:8080** and sign in. Create an investigation, two documents and a relation; reload after confirmed saving.

Choose **«Удалить узел»** in the node menu beside its connection and editing actions. Deletion is also available in the document inspector and full editor. The confirmation shows the affected relation count; after confirmed saving, the node and every incoming/outgoing relation disappear from the graph. Original attachment files remain stored. Cancel leaves the graph unchanged; use the offered retry after an error. Archived investigations cannot be changed.

The `releases/` directory selects verified release 0.1.2. For an exact earlier delivery use [Releases](releases.md). Cloning current documentation does not change installed container versions.

```sh
./traceweave.sh stop
./bootstrap.sh
```

Stopping retains data and the installed release. Repeat bootstrap displays the installed version. If the delivery directory contains a newer compatible release, it offers an update with a backup; the script applies migrations only when needed. Declining keeps the installed release. Preserve runtime and Docker volumes. A new installation can use `./bootstrap.sh --port 18080` when the default port is occupied; its URL will be http://127.0.0.1:18080.

To check for an available update from the original installation directory:

```sh
git pull --ff-only
./bootstrap.sh
```

The script compares local manifests after `git pull`; version discovery makes no hidden network requests. Confirm the offered update, wait for completion and reload the browser tab. Moving from 0.1.0/0.1.1 to 0.1.2 needs no manual manifest selection. See [Releases](releases.md) for details and commands for the old script.

[Where data lives and what leaves the host](data-and-security.md) · [Installation](installation.md) · [VPS](server-deployment.md)

---

[Documentation](index.md) · [README](../../README.md)
