<p align="center">
  <img src="docs/banner.svg" alt="TraceWeave Delivery" width="720"/>
</p>

<p align="center"><strong>Docker Compose · Caddy · PostgreSQL 18</strong></p>

# TraceWeave

*Read this in other languages: [Русский](README-ru.md)*

The installation and operations repository for TraceWeave. It connects the independent backend and frontend with PostgreSQL and a single public gateway.

## Key Features

- **Local Docker installation and HTTPS server configuration.**
- **Interactive bootstrap, account creation and persistent installation state.**
- **Maintenance, compatible updates, offline backup and restore to new volumes.**
- **Canonical OpenAPI, SQL, archive schemas, specification and accepted change requests.**

## Quick Start

Build from source using [Quick Start](docs/en/quick-start.md). For a published release containing `releases/stable.json`, run:

```sh
./bootstrap.sh
```

Bootstrap prompts for email, name and a hidden password, then opens the installation at **http://127.0.0.1:8080**.

**Status:** public container images have not been released yet. Source builds are available; full P0 acceptance remains separate.

## Documentation

- [Installation](docs/en/installation.md)
- [Quick Start](docs/en/quick-start.md)
- [Architecture](docs/en/architecture.md)
- [API and Contracts](docs/en/api.md)
- [Testing](docs/en/testing.md)
- [Full Documentation](docs/en/index.md)
- [Changelog](CHANGELOG.md)

## Project Repositories

| Repository | Responsibility |
| --- | --- |
| [TraceWeaveBackend](https://github.com/andrey-torlopov/TraceWeaveBackend) | API, domain validation, PostgreSQL, immutable files and export jobs |
| [TraceWeaveFrontend](https://github.com/andrey-torlopov/TraceWeaveFrontend) | Browser application, graph, editors and local draft recovery |
| [TraceWeave](https://github.com/andrey-torlopov/TraceWeave) | Compose, gateway, operator CLI, canonical contracts and specification |

The specification and machine contracts live only in the delivery repository. Component documentation explains the implementation without maintaining another specification.
