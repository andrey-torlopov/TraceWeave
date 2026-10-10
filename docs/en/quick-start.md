# Quick Start

*[Русский](../ru/quick-start.md)*

## Build a Local Installation

Docker Engine/Desktop, Compose and a TTY are required. Clone the backend and frontend beside this delivery checkout:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git
git clone https://github.com/andrey-torlopov/TraceWeaveBackend.git
git clone https://github.com/andrey-torlopov/TraceWeaveFrontend.git
cd TraceWeave
printf 'New local release ID: '
IFS= read -r TW_RELEASE_ID
./traceweave.sh build-source --release-id "$TW_RELEASE_ID" \
  --backend-path ../TraceWeaveBackend \
  --frontend-path ../TraceWeaveFrontend
./bootstrap.sh --release "releases/$TW_RELEASE_ID.local.json"
./traceweave.sh status
```

Start the cloning commands in the directory that will hold all three checkouts. If they already exist, start at `cd TraceWeave` from their parent directory. Backend/frontend must be clean and committed. Choose a new ID using letters, digits, dots, underscores or hyphens; the builder refuses to overwrite an existing local manifest.

Bootstrap prompts for email, display name and a hidden account password. Open **http://127.0.0.1:8080** and sign in. Create an investigation and two documents, add a relation, then reload to read confirmed data from the server. Local HTTP needs no SMTP or domain.

## Subsequent Runs

```sh
./traceweave.sh stop
./bootstrap.sh
```

Stopping keeps volumes and the installed release. Keep the same checkout/runtime. A local manifest records images on this Docker-host and cannot download application images on a different host.

## Published Delivery

Public images have not been released yet. Once a verified package includes `releases/stable.json` and `releases/tools-image.txt`, a new installation uses `./bootstrap.sh` directly. See [Local Use](local-use.md), [Installation](installation.md) and [Server Deployment](server-deployment.md).

---

[Back to documentation](index.md) · [README](../../README.md)
