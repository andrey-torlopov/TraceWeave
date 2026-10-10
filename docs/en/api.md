# API and Contracts

*[Русский](../ru/api.md)*

## Canonical Inputs

- [OpenAPI and schemas](https://github.com/andrey-torlopov/TraceWeave/tree/main/contracts) in `TraceWeave/contracts/`.
- [Technical specification](https://github.com/andrey-torlopov/TraceWeave/blob/main/docs/TECHNICAL_SPECIFICATION.md) and accepted change requests in `TraceWeave/docs/`.
- [Docker/account change request](https://github.com/andrey-torlopov/TraceWeave/blob/main/docs/change-requests/CR-E8-001-docker-delivery.md) takes precedence over the earlier single-owner and deferred-Docker rules.

OpenAPI is version 1.1.0, serialized as JSON-compatible YAML. Contract presence describes required behavior; it does not prove every route is implemented.

## Request Protocol

Production UI and `/api/v1` share one origin. Fetch a session for the CSRF token; login uses email and password. Cookies are HttpOnly and SameSite=Strict, and Secure under HTTPS. Browser requests include `X-TraceWeave-Client-Contract`; protected requests also carry `X-TraceWeave-Account-ID`.

Ordinary investigation mutations use `POST /api/v1/investigations/{id}/commands` with `operationId`, `clientId`, `baseRevision` and commands. One accepted batch increments the revision once. Replay uses exactly the original bytes and identifier; idempotency is checked before a stale base revision. Route braces denote API parameters.

## Errors and Recovery

| Response | Meaning and client action |
| --- | --- |
| `409 revision_conflict` | Keep the draft, load the server version and resolve the difference explicitly. |
| `409 idempotency_mismatch` | The same operation ID was used with different bytes; do not disguise it as a retry. |
| `409 account_changed` | Stop the old account's pending queue. |
| `409 client_upgrade_required` | Preserve drafts before choosing to reload. |
| `413 storage_quota_exceeded` | Account or installation storage is full. |
| `503 service_maintenance` | Keep pending bytes; respect `Retry-After` and retry explicitly. |

The error envelope contains `code`, `message`, `requestId` and `details`. Use the canonical schemas for complete fields and validation, rather than copying DTO definitions into documentation.

---

[Back to documentation](index.md) · [README](../../README.md)
