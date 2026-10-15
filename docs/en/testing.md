# Verification and Limits

*[Русский](../ru/testing.md)*

Release 0.2.0 is published for Linux amd64/arm64. Recorded [fresh native host acceptance](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38756147808) covers anonymous pulls of the exact tested image IDs, Docker-only bootstrap, complete cross-account project transfer, persistence after restart, backup/restore, HTTPS and account workflows. See the [release evidence](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.2.0).

After installation, run `./traceweave.sh status`, sign in, create a **test** investigation/document, wait for confirmed saving and reload. Test restore on a separate synthetic installation, not the only copy of real research.

The [publication CI](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38752689149) passed 10 Chromium editor/transfer scenarios, 33 graph scenarios and 11 attachment scenarios against real backend/PostgreSQL. Checks include personal emoji and types, geometry and camera after transfer, errors/retries, retained attachments and exact original bytes. Archived investigations support reading and export.

All 124 [native update cases](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38757674385) from 62 published installation variants passed. They cover automatic verified backup and migration 11 with the tools upgrade, original bytes and exact pending request replay, refusal of incompatible image-only rollback, previous-backup restore and recovery from the newer safety backup.

A separate real ZIP64 writer/reader roundtrip of 4,831,854,009 bytes passed on macOS arm64 with originals at the 512 MiB boundary. The model, presentation, sizes and SHA-256 matched after extraction. This test did not measure peak RSS or maximum concurrent load. See [Exports](exports.md) for upload and original limits.

Container publication is not complete product acceptance or an independent security audit. The full browser/performance matrix, manual Safari and some planned capabilities need separate verification. Headless WebKit is not manual Safari evidence.

A local draft does not guarantee the last keystroke survives a crash. Media support depends on browser codecs. The application does not encrypt the database, originals or backups at rest. See [trust boundaries](data-and-security.md).

---

[Documentation](index.md) · [README](../../README.md)
