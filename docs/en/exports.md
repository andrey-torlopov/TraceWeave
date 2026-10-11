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
