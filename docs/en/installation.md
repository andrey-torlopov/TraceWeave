# Installation

*[Русский](../ru/installation.md)*

Use [Quick Start](quick-start.md) with ready-made public images. Host Swift, Node.js and a separate PostgreSQL installation are unnecessary. Install Docker Engine or Docker Desktop with Linux containers and Compose, then start Docker:

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
```

Recorded acceptance used Engine 29.8.2 / Compose 5.5.1. Server Compose uses `!override`, which your version must support. Release 0.1.1 supports Linux amd64/arm64; macOS uses Docker's Linux environment.

## Runtime and CLI

Settings, secrets, installation state and backups default to the installation's `runtime/` directory. To choose another **absolute** path, set it before bootstrap and in every later terminal session:

```sh
export TW_RUNTIME_DIR="$HOME/traceweave-runtime"
./bootstrap.sh
```

This does not relocate the database or attachments: they stay in separate Docker volumes. Bootstrap does not offer an arbitrary database/originals directory. [Storage table](data-and-security.md#where-data-lives).

The CLI uses host Python when available, otherwise the pinned tools image. Docker-only mode requires a local Unix Docker socket; a remote TCP Docker context is unsupported. The tools container has Docker-operator authority; trust it as an administrative program.

## Local and Server Modes

Local access uses `127.0.0.1` and needs no SMTP/domain. Bootstrap prompts for email, name and a hidden password with confirmation; the allowed range is 3 Unicode scalar values to 1024 UTF-8 bytes. Choose a long, unique password for real use.

A [VPS installation](server-deployment.md) needs your domain, DNS, HTTPS and SMTP for initial email verification. `smtp://` requires STARTTLS; `smtps://` uses TLS. Passwords are entered separately and privately. Registration is disabled by default. The API service and database publish no host ports.

Use bootstrap/traceweave.sh for checked operations. Read [Operations](operations.md), [Releases](releases.md) and [protection boundaries](data-and-security.md) before uploading sensitive materials.

---

[Documentation](index.md) · [README](../../README.md)
