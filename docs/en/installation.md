# Installation

*[Русский](../ru/installation.md)*

For the shortest path use [Quick Start](quick-start.md) or [Local Use](local-use.md). Remote installation is covered by [Server Deployment](server-deployment.md).

## Requirements

Docker Engine/Desktop with Linux containers, Compose and a TTY are required. The recorded delivery environment used Engine 29.8.2 and Compose 5.5.1. The server override uses Compose `!override`; verify support in the installed plugin:

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
```

Only gateway publishes a host port. PostgreSQL 18 uses TLS verify-full for `db`; frontend/gateway cannot read originals. Public images are not released yet. Local manifests contain Docker-host image IDs, while a published manifest must contain accessible immutable registry digests for the required architecture.

## Host Python or Docker-Only CLI

`traceweave.sh` uses host `python3` when available. Otherwise it runs a short-lived tools container with the checkout at the same absolute path and the local Unix Docker socket. Remote TCP Docker contexts are not supported in this mode. The tools container has Docker-operator authority; the application containers do not receive the socket.

For an initial source build without host Python:

```sh
docker build -t traceweave/tools:docker-1 -f tools/Dockerfile .
export TW_TOOLS_IMAGE=traceweave/tools:docker-1
./traceweave.sh --help
```

The wrapper can build this missing default tag from the checkout. Arbitrary missing tags are rejected. A verified published package instead provides `releases/tools-image.txt` containing the tools digest matching `releases/stable.json`; the wrapper can pull it without host Python. A private registry requires prior authentication.

Runtime defaults to this checkout's `runtime/`. An absolute `TW_RUNTIME_DIR` selects another private directory; use the same path on every later command. CLI produces Compose environment from installation/release state; do not substitute raw `docker compose up` or manual `.env` edits.

Source builds mount only the necessary checkouts read-only. Standard Git worktrees additionally mount the verified common Git metadata directory; nonstandard layouts require host Python. An external `--release` mounts only that file. Bind paths containing commas are rejected.

## Source Build

Check out backend and frontend as siblings, and keep them clean/committed. Generated frontend API must already match this repository's contract. Use [Quick Start](quick-start.md), which prompts for a fresh ID and creates `releases/<chosen-id>.local.json` only after successful builds.

The builder records source commits/diff hashes and the contract hash before and after building tools, gateway, backend and frontend, and pins PostgreSQL. It refuses source changes during the build or an existing manifest with the chosen ID. Tags retain local images; the manifest pins immutable IDs. A manifest represents only the current Docker daemon's architecture. Building neither publishes images nor updates an installation.

For Docker-only operation after the build, select its actual tools ID:

```sh
TW_TOOLS_IMAGE=$(docker image inspect --format '{{.Id}}' "traceweave/tools:$TW_RELEASE_ID")
export TW_TOOLS_IMAGE
./bootstrap.sh --release "releases/$TW_RELEASE_ID.local.json"
```

`TW_RELEASE_ID` is the value read during the source build. Local manifests are ignored by Git. See [Releases](releases.md) for registry packaging.

## Bootstrap and Database

Bootstrap generates PostgreSQL passwords, CA and certificates, creates persistent volumes, runs migrations and asks for the first account's email/name/password. Password entry is hidden and confirmed: 3 Unicode scalars minimum, 1024 UTF-8 bytes maximum, no trimming/normalization. Do not pass passwords as arguments or environment variables.

Local HTTP accepts hostname `127.0.0.1` only; default is port 8080. `--port` chooses another port for a new installation. The stored origin belongs to that installation. The internal gateway uses a fixed trusted address and a separate dynamic application IP range. Repeated bootstrap preserves secrets, data and accounts. A historical owner without email requires explicit operator email attachment; the browser cannot claim that owner.

## HTTPS and SMTP

Server origin is HTTPS with a real hostname, no URL path/query/credentials and standard ports 80/443. DNS must point to the server; Caddy obtains and retains certificates. SMTP is needed for the first HTTPS account's email verification. Bootstrap accepts mail flags; existing installations use:

```sh
printf 'SMTP URL with port, without credentials: '
IFS= read -r TW_SMTP_URL
printf 'SMTP login: '
IFS= read -r TW_SMTP_USER
printf 'Sender email: '
IFS= read -r TW_SMTP_FROM
./traceweave.sh configure-mail --smtp-url "$TW_SMTP_URL" \
  --smtp-user "$TW_SMTP_USER" --smtp-from "$TW_SMTP_FROM"
```

Use `smtp://` with mandatory STARTTLS or `smtps://`; credentials are entered separately and privately. Public registration stays disabled unless the operator explicitly adds `--enable-registration`. No SMTP server is bundled. For full VPS/SSH/DNS/bootstrap steps use [Server Deployment](server-deployment.md).

Storage defaults are 10 GiB per account and 100 GiB per installation. Pending reservations count toward quotas. A full account/installation returns `413 storage_quota_exceeded`; ordinary detach does not delete originals. Preserve volumes and follow [Operations](operations.md) for backup/recovery.

---

[Back to documentation](index.md) · [README](../../README.md)
