# Files and attachments

*[Русский](../ru/attachments.md)*

Available in [release 0.1.8](releases.md). Uploaded originals retain their bytes and names.

Release 0.1.8 shows all card attachments as buttons with their kind and filename. Select a button to preview one image, audio or video; other files download for local viewing. Switching stops the previous player. Add files together or consecutively. Detaching keeps the original and other attachments.

In a card’s Materials section, select Add files. You can choose multiple files, including PDFs, documents, spreadsheets, archives and files without an extension. All files shows the full selection; image, audio and video filters help narrow it down.

The maximum size is 512 MiB per file. An administrator can set a lower limit; the current value appears beside the file picker. Wait for the Attached state: the file uploads first and is then linked to the card.

- Images, audio and video retain their existing viewers. Playback depends on the browser and codec; the original remains available to download.
- Other files appear with a paperclip and their original name. Select the name to download the original.
- PDFs download for viewing in another application in this version; there is no embedded PDF preview.

A file can be attached to different cards. Selecting the same file again creates a separate material and attachment, even when the bytes and name match. Detach removes the link to a card and keeps the original in the investigation.

A failed upload creates no material or attachment. If an upload is interrupted, use Retry upload. When a save response is unconfirmed, the interface offers to check the save, avoiding a duplicate attachment after a network failure.

---

[Features](features.md) · [Data and security](data-and-security.md) · [Documentation](index.md)
