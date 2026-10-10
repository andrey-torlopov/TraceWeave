# Quick Start

*[Русский](../ru/quick-start.md)*

Install Docker with Linux containers, Docker Compose and Git; use an interactive terminal. Component source access and GitHub/Docker Hub accounts are unnecessary. Release 0.1.0 images are public for amd64 and arm64.

From the parent directory of a new installation:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
cd TraceWeave
./bootstrap.sh
./traceweave.sh status
```

Bootstrap downloads pinned images, prepares storage and prompts for email, display name and a hidden password. Open **http://127.0.0.1:8080** and sign in. Create an investigation, two documents and a relation; reload after confirmed saving.

The `releases/` directory selects verified release 0.1.0. For an exact earlier delivery use [Releases](releases.md). Cloning current documentation does not change installed container versions.

```sh
./traceweave.sh stop
./bootstrap.sh
```

Stopping retains data and the installed release. Repeat bootstrap starts that installation. Preserve its runtime and Docker volumes. A new installation can use `./bootstrap.sh --port 18080` when the default port is occupied; its URL will be http://127.0.0.1:18080.

[Where data lives and what leaves the host](data-and-security.md) · [Installation](installation.md) · [VPS](server-deployment.md)

---

[Documentation](index.md) · [README](../../README.md)
