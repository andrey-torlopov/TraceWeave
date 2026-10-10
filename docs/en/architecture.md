# Architecture Overview

*[Русский](../ru/architecture.md)*

## Repositories and Services

This repository is the orchestrator, not a monorepo. Backend and frontend have independent Git history and lock files; `releases/source-lock.json` pins the compatible source revisions used by CI.

| Service | Responsibility and data |
| --- | --- |
| `gateway` | Single public HTTP/HTTPS entry, routing, maintenance and `/release.json`; Caddy certificates have persistent volumes. |
| `frontend` | Compiled static UI; current and retained assets, no originals or database secrets. |
| `backend` | Swift API, validation and jobs; private immutable originals/staging/exports. |
| `db` | PostgreSQL 18, UTF-8 and TLS verify-full for hostname `db`; private persistent volume. |
| `migrate`, `owner`, `ops` | One-shot administrative services; not permanently running applications. |

Local mode publishes only the gateway at loopback port 8080. Server mode uses `compose.server.yaml` to publish ports 80/443. Backend and database ports stay internal. A fixed gateway peer address is the only trusted reverse proxy.

## Operator State

`bootstrap.sh` and `traceweave.sh` call the Python controller; a tools container supplies Python when it is absent on the host. Only the operator tools container gets the Docker socket. Runtime files store installation configuration, secrets, the selected manifest, phases, lock and journal outside application containers.

Bootstrap generates private database credentials/CA, creates volumes, migrates and creates the first account. Repeat bootstrap starts the installed release. Update is an explicit compatible operation with preflight, maintenance and readiness checks. Offline backup combines the database dump and immutable originals; restore creates new volumes and retains the old ones.

## Requirements and Contracts

The canonical [specification](../TECHNICAL_SPECIFICATION.md), [contract decisions](../contract-decisions.md), [ADR](../adr/) and [change requests](../change-requests/) remain in this repository. Language guides explain operation without creating translated normative copies. [CR-E8-001](../change-requests/CR-E8-001-docker-delivery.md) activates Docker/accounts; earlier deferred-Docker rules do not block this package.

---

[Back to documentation](index.md) · [README](../../README.md)
