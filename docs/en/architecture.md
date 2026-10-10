# How TraceWeave Works

*[Русский](../ru/architecture.md)*

TraceWeave runs on the computer or server where you start Docker. Your browser receives the interface and connects to one entry point. The application service checks access, stores documents/relations in PostgreSQL and keeps original attachments in separate file storage.

| Part | Role |
| --- | --- |
| Browser | Graph and document UI; additional local drafts and preferences |
| Gateway | Local HTTP or server HTTPS entry; request routing |
| Interface | Serves the compiled application files to the browser |
| Application service | Checks access and reads/writes investigations and files |
| PostgreSQL | Documents, relations, positions, accounts and service records |
| Administrative tools | Operator-triggered lifecycle, updates and consistent backup/restore |

Component sources are private; running the published delivery does not require them. The public package contains operator commands and pinned image versions. Containers run on your host; Docker Hub supplies downloads.

For diagrams, storage, external connections and trust boundaries read **[Data and Security](data-and-security.md)**.

---

[Documentation](index.md) · [README](../../README.md)
