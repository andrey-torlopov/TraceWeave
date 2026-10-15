# Export data or a readable report

*[Русский](../ru/exports.md)*

Available in [release 0.1.6](releases.md).

The Export button opens two actions; on a narrow screen they appear in the investigation actions menu:

- **Save raw data** — the existing ZIP with separate Markdown documents, attachments and technical metadata. Open the extracted folder in Obsidian.
- **Export report** — a ZIP containing one `report.md` file and an `Attachments` folder with original files.

The readable report gives cards human-readable headings and includes their text, attributes, attachments, sources and relations. Each relation identifies both documents, its type, direction, assessment and confidence when provided. Internal links lead to sections in the same file or to attachments. Multiple relations between the same pair of documents remain separate.

The report adds no internal UUIDs, graph coordinates, JSON metadata or technical timestamps. Text attributes retain their literal value; unknown values, empty strings, zero and false remain distinct. Text written by the author in a card or code block is preserved, including explicitly entered identifiers.

Choose a format and select Create ZIP. The application saves documents and completes uploads before building the archive. When it is ready, select Download ZIP. Closing the dialog does not cancel the export; return to it while the investigation remains open to retrieve the result.

Both formats include all active documents and relations, regardless of search, selection or collapsed groups, together with attached files and source materials in use. Trash and historical snapshots are excluded. Use [backup](operations.md) to preserve the full installation.

The archive reflects the saved state when requested. Later card edits do not change an existing report; create a new archive to include new data. The download is available for 24 hours. Restoring a backup invalidates existing export jobs; create a new ZIP from the restored documents. A missing or damaged original causes an export error.

---

[Features](features.md) · [Files and attachments](attachments.md) · [Documentation](index.md)

## Portable projects (0.2.0)

Choose “Экспортировать проект” in the export menu for a standalone ZIP containing the full investigation: live and trashed objects, types, attributes, groups, absolute layouts, original files, report definitions and immutable snapshots. Camera, inspector, panels and sizing preferences are included. The other two export formats retain their existing Markdown/report scope.

In the investigation list, choose “Импортировать проект”, upload the ZIP, review the validated counts and confirm creation. Import creates a separate investigation under the current account with remapped UUIDs and internal links. It preserves source status, dates and provenance; the new revision starts at zero. Account credentials and undo/redo history are excluded. Existing projects are unaffected; failed validation/commit never exposes a partial project. Retrying the same confirmation replays its receipt. Jobs expire after 24 hours.

Archive format 2.0 is independent of application/database versions and pins its schema ID/hash, producer release/commits and required features. Both frozen legacy 1.0 profiles are readable; absent presentation uses default camera/panels. Unknown formats/features require a newer application and are rejected without discarding data. ZIP limits are 10 GiB upload, 512 MiB per original, 64 MiB project metadata, 50,000 entries, 20 GiB expanded data and 1000 expansion ratio, plus account/installation quotas and available disk space. Our writer uses STORE. Transfer archives only to trusted recipients: they include the trash and historical information.
