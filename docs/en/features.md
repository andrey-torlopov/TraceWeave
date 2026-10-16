# Features

*[Русский](../ru/features.md)*

## Reading and editing cards (0.2.2)

Double-click a node or choose “Открыть карточку” (Open card) to read its title, type, formatted note, attachments and attributes. A wide screen places attributes beside the note; a phone stacks them below the note and materials. Preview and download files without enabling editing.

The **✍️ Редактирование** (Editing) toggle beside Close exposes the existing form. A green frame and visible mode label show its state; Enter/Space also activate it. Toggle again to return to reading. Both modes share the same draft, with a notice for unconfirmed changes. Every new opening starts in reading mode. Archived projects cannot enable editing.

Desktop cards start at a 1000 px minimum. Drag the right ↔ handle or use its arrow keys to resize; the preference is remembered for this project in this browser. Narrow screens clamp the card to the viewport.

Release 0.1.8 shows all card attachments as buttons with their kind and filename. Select a button to preview one image, audio or video; other files download for local viewing. Switching stops the previous player. Add files together or consecutively. Detaching keeps the original and other attachments.

- Graph investigations with documents, attributes, relations, search and editing.
- [Arbitrary file attachments](attachments.md), including PDFs; supported image/audio/video preview and original downloads.
- [Raw Markdown/attachment ZIP export for Obsidian or one readable report](exports.md).
- Local Docker installation or your own HTTPS server; email/password sign-in.
- Managed updates, maintenance and backup/restore to new storage.

The investigation author assesses claims and connections. Automatic OSINT collection, LLM services and plugin execution are not connected in this delivery. [Limits and verification](testing.md) · [Data and security](data-and-security.md).

Two documents can have multiple relations, including identical ones. Drawing a connection fixes both endpoints in the confirmation dialog; cancel and reconnect to choose other documents. The label is the first field. Choose no direction, source to target, target to source or both directions; the endpoint preview changes immediately. Edit and delete each relation separately.

The gear button, “Graph settings”, beside the zoom controls has two independent settings. The card shrink factor accepts 1.1–10 (default 3): the card becomes an icon at zoom = 1 / factor and below. Smaller values switch earlier. Icon diameter accepts 1–4 card heights (default 2), measured at the same zoom. Further zooming out also shrinks the icon. Both fields accept decimal points or commas, such as 1.75 or 1,75. Apply saves both together; an invalid field restores its saved value with an explanation and applies neither setting. Cancel leaves both unchanged. Preferences belong to this investigation in the current browser. Node centers, documents, relations, saved coordinates and revision remain unchanged by view settings.

Version 0.1.6 accepts files up to 512 MiB, subject to the installation limit. Selecting the same file again creates an independent attachment. PDFs download for viewing in another application. The export menu offers raw data or a ZIP with one `report.md` and its originals.

Version 0.1.7 adds **Улика** (Evidence) with a magnifying-glass icon 🔍. Choose it in the document type selector. New and existing investigations receive the type; existing custom types with the same name or code remain unchanged. A type label does not change the user’s assessment.

---

[Documentation](index.md) · [README](../../README.md)

## Document symbols (0.2.0)

Choose a semantic type from the icon grid. A single qualified Emoji 17.0 sequence can override the symbol for this document, including flags, skin tones and ZWJ sequences. This preserves its semantic type, attributes and templates. Resetting the symbol restores the type icon; other documents are unaffected.
