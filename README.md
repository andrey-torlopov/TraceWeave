<p align="center">
  <img src="docs/banner.png" alt="TraceWeave" width="960"/>
</p>

# TraceWeave

*[Русский](README-ru.md)*

## Why This Project Exists

<p align="center">
  <img src="docs/why-traceweave.png" alt="TraceWeave: it is all connected" width="560"/>
</p>

When materials are scattered across files, tabs and notes, their connections are easy to lose. TraceWeave brings documents, sources and conclusions into one graph so an investigation can be understood, checked and continued.

TraceWeave is a manual investigation application: documents, materials and connections on a graph. Run it on your computer or your own server; data stays on the host you choose.

## Quick Start

Install and start Docker with Compose. From the parent directory of a new installation:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
cd TraceWeave
./bootstrap.sh
```

Enter email, display name and a hidden password. Open **http://127.0.0.1:8080**. Ready-made **0.1.1** images are public for amd64/arm64; private component sources and registry sign-in are unnecessary.

## Documentation

- [Installation and Requirements](docs/en/installation.md)
- **[Where Data Lives, What Leaves the Host and Protection Boundaries](docs/en/data-and-security.md)**
- [VPS Deployment](docs/en/server-deployment.md)
- [Backup, Restore and Maintenance](docs/en/operations.md)
- [Releases and Updates](docs/en/releases.md)
- [Limits and Recorded Verification](docs/en/testing.md)
- [All User Documentation](docs/en/index.md)

Confirmed documents and relations live in PostgreSQL; originals use a separate volume. The browser keeps additional drafts. TraceWeave connects no telemetry, LLM or automatic external collection. The application does not encrypt data at rest: the host operator and administrators can access it.

[GitHub Release v0.1.1](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.1) · [Changelog](CHANGELOG.md)
