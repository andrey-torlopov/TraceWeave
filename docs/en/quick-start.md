# Quick Start

*[Русский](../ru/quick-start.md)*

Install Docker with Linux containers, Docker Compose and Git; use an interactive terminal. Component source access and GitHub/Docker Hub accounts are unnecessary. Release 0.1.8 images are public for amd64 and arm64.

From the parent directory of a new installation:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
cd TraceWeave
./bootstrap.sh
./traceweave.sh status
```

Bootstrap downloads pinned images, prepares storage and prompts for email, display name and a hidden password. Open **http://127.0.0.1:8080** and sign in. Create an investigation, two documents and a relation; reload after confirmed saving. Use Materials → Add files to attach originals, including PDFs. The [export menu](exports.md) offers raw data for Obsidian or one readable report with its attachments.

Choose **«Удалить узел»** in the node menu beside its connection and editing actions. Deletion is also available in the document inspector and full editor. The confirmation shows the affected relation count; after confirmed saving, the node and every incoming/outgoing relation disappear from the graph. Original attachment files remain stored. Cancel leaves the graph unchanged; use the offered retry after an error. Archived investigations cannot be changed.

The `releases/` directory selects release 0.1.8. For an exact earlier delivery use [Releases](releases.md). Cloning current documentation does not change installed container versions.

```sh
./traceweave.sh stop
./bootstrap.sh
```

Stopping retains data and the installed release. Repeat bootstrap displays the installed version. If the delivery directory contains a newer compatible release, it offers an update with a backup; the script applies migrations only when needed. Declining keeps the installed release. Preserve runtime and Docker volumes. A new installation can use `./bootstrap.sh --port 18080` when the default port is occupied; its URL will be http://127.0.0.1:18080.

If the installation checkout tracks `main`, check for an update from its directory with the same `TW_RUNTIME_DIR`. If it was cloned from a release tag (detached HEAD), first follow the [existing-installation instructions](releases.md#existing-installation), which preserve the original runtime in a new checkout.

```sh
git pull --ff-only && ./bootstrap.sh
```

The script compares local manifests after `git pull`; version discovery makes no hidden network requests. Confirm the update, wait for completion and reload the browser tab. From 0.1.7 to 0.1.8 the database remains at schema 10 and PostgreSQL, gateway and backup tools remain selected; same-schema image rollback is available. Earlier stable versions migrate to schema 10 with compatible tools. No manual manifest or SQL selection is needed. Image-only rollback to a different schema remains refused; use the verified backup. See [Releases](releases.md).

[Where data lives and what leaves the host](data-and-security.md) · [Installation](installation.md) · [VPS](server-deployment.md)

---

[Documentation](index.md) · [README](../../README.md)
