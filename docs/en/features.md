# Features

*[Русский](../ru/features.md)*

## Dossier and quick preview (0.2.3 candidate)

These changes are prepared in source; the published stable release remains 0.2.2.

**Graph / Dossier** switches views of the same nodes. Dossier includes all active nodes, including isolated nodes and groups, with **List / Cards** layouts. Gallery covers use real primary images when safely previewable, plus type, title, existing subtitle and counts. Large originals are not decoded for covers; image-free records show their type.

The catalogue supports type filtering, title/update sorting and literal case-insensitive server search over saved titles, Markdown and attributes. Subtitle and tag text are not searched. Catalogue pages contain up to 50 records; load further server matches explicitly. Filters keep the investigation total and never close a selected document outside the results.

Resources appear **above the note**. No attachments means no empty resource block; empty attributes do not reserve a column. Attachment captions remain distinct from filenames. Existing evidence, typed attributes and all actual relations appear beside or below the note. Incoming, outgoing, undirected, bidirectional and parallel relations retain their identities. Show in Graph selects the same node. Deep links preserve view/selection; Back/Forward restore reading and scroll. View/filter changes do not mutate the server revision.

The quick inspector opens **read-only**. Edit, Delete node and Open card are at the top. Edit opens the full card with editing enabled; normal card opening starts in reading mode. Long quick-preview notes explicitly show an excerpt; the full text remains in the card. Every surface shares the same draft, saving and conflict/replay behavior.

Reading cards have a **1200 CSS px** desktop minimum; editing retains the 1000 px minimum. Both clamp to narrow viewports and retain the per-project/user browser width preference. No separate workflow status such as Studied is introduced: existing user assessments remain distinct from processing state. API and database schema are unchanged.

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
