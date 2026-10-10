# Verification and Limits

*[Русский](../ru/testing.md)*

Release 0.1.0 is published for Linux amd64/arm64. Recorded [fresh native host acceptance](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38073642033) covers anonymous pulls, Docker-only bootstrap, persistence after restart, backup/restore, HTTPS and account workflows. See the [release evidence](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0).

After installation, run `./traceweave.sh status`, sign in, create a **test** investigation/document, wait for confirmed saving and reload. Test restore on a separate synthetic installation, not the only copy of real research.

Container publication is not complete product acceptance or an independent security audit. The full browser/performance matrix, manual Safari and some planned capabilities need separate verification. Headless WebKit is not manual Safari evidence.

A local draft does not guarantee the last keystroke survives a crash. Media support depends on browser codecs. The application does not encrypt the database, originals or backups at rest. See [trust boundaries](data-and-security.md).

---

[Documentation](index.md) · [README](../../README.md)
