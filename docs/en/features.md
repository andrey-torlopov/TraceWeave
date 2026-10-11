# Features

*[Русский](../ru/features.md)*

Release 0.1.8 shows all card attachments as buttons with their kind and filename. Select a button to preview one image, audio or video; other files download for local viewing. Switching stops the previous player. Add files together or consecutively. Detaching keeps the original and other attachments.

- Graph investigations with documents, attributes, relations, search and editing.
- [Arbitrary file attachments](attachments.md), including PDFs; supported image/audio/video preview and original downloads.
- [Raw Markdown/attachment ZIP export for Obsidian or one readable report](exports.md).
- Local Docker installation or your own HTTPS server; email/password sign-in.
- Managed updates, maintenance and backup/restore to new storage.

The investigation author assesses claims and connections. Automatic OSINT collection, LLM services and plugin execution are not connected in this delivery. [Limits and verification](testing.md) · [Data and security](data-and-security.md).

Two documents can have multiple relations, including identical ones. Drawing a connection fixes both endpoints in the confirmation dialog; cancel and reconnect to choose other documents. The label is the first field. Choose no direction, source to target, target to source or both directions; the endpoint preview changes immediately. Edit and delete each relation separately.

The gear button, “Graph settings”, beside the zoom controls sets how many times a card must shrink before becoming a compact node. Use an integer from 2 to 10; the default is 3. With 5, cards remain visible above 20% zoom and become nodes at 20% or below. Invalid input restores the current value with an explanation. Apply saves the setting; Cancel leaves it unchanged. The setting belongs to this investigation in the current browser and does not change documents or relations.

Version 0.1.6 accepts files up to 512 MiB, subject to the installation limit. Selecting the same file again creates an independent attachment. PDFs download for viewing in another application. The export menu offers raw data or a ZIP with one `report.md` and its originals.

Version 0.1.7 adds **Улика** (Evidence) with a magnifying-glass icon 🔍. Choose it in the document type selector. New and existing investigations receive the type; existing custom types with the same name or code remain unchanged. A type label does not change the user’s assessment.

---

[Documentation](index.md) · [README](../../README.md)
