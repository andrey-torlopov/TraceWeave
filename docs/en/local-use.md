# TraceWeave on Your Computer

*[Русский](../ru/local-use.md)*

Follow [Quick Start](quick-start.md). Ready-made images are downloaded from the public registry and run on your computer. Open http://127.0.0.1:8080; the loopback address is unavailable to other computers on your network.

```sh
./traceweave.sh status
./traceweave.sh stop
./bootstrap.sh
```

Stopping and restarting retain the database, files and accounts. Confirmed data comes from the server; the browser keeps additional local drafts and preferences. Clearing site data can delete unsaved drafts.

After images are downloaded, working locally with existing materials needs no internet. Initial installation and downloading updates need network access. Copying the installation directory alone does not copy Docker volumes. Make [backups](operations.md) and keep them separately.

[Data and network diagram](data-and-security.md) · [Runtime and storage](installation.md)

---

[Documentation](index.md) · [README](../../README.md)
