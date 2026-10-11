# Features

*[Русский](../ru/features.md)*

- Graph investigations with documents, attributes, relations, search and editing.
- Image/audio/video attachments, supported media preview and original downloads.
- Markdown and attachment ZIP export for Obsidian.
- Local Docker installation or your own HTTPS server; email/password sign-in.
- Managed updates, maintenance and backup/restore to new storage.

The investigation author assesses claims and connections. Automatic OSINT collection, LLM services and plugin execution are not connected in this delivery. [Limits and verification](testing.md) · [Data and security](data-and-security.md).

Two documents can have multiple relations, including identical ones. Drawing a connection fixes both endpoints in the confirmation dialog; cancel and reconnect to choose other documents. The label is the first field. Choose no direction, source to target, target to source or both directions; the endpoint preview changes immediately. Edit and delete each relation separately.

The gear button, “Graph settings”, beside the zoom controls sets how many times a card must shrink before becoming a compact node. Use an integer from 2 to 10; the default is 3. With 5, cards remain visible above 20% zoom and become nodes at 20% or below. Invalid input restores the current value with an explanation. Apply saves the setting; Cancel leaves it unchanged. The setting belongs to this investigation in the current browser and does not change documents or relations.

---

[Documentation](index.md) · [README](../../README.md)
