# Releases and Updates

*[Русский](../ru/releases.md)*

## Compatible Release Manifest

A release is a compatible pair of independent backend/frontend images plus pinned PostgreSQL/gateway/tools. Format 1 records:

| Field | Meaning |
| --- | --- |
| `releaseId`, `backendVersion`, `frontendVersion` | Delivery/component identifiers. |
| `frontendReleaseId` | ID baked into that frontend image; may differ from a later backend-only delivery ID. |
| `images` | Immutable backend/frontend/postgres/gateway/tools references; no floating tag. |
| `contractHash`, `backendContractHash` | Exact OpenAPI SHA-256 used by the components. |
| `supportedClientContractHashes` | Supported current/older client contracts, including the release's own hash. |
| `postgresMajor` | 18; major upgrade is a separate procedure. |
| `migrations` | Continuous versions and exact checksums. |
| `platforms`, `source`, `validation`, `rollback` | Build architectures, source/evidence and recovery information. |

Source builder produces an ignored `releases/*.local.json` only after clean committed source and contract checks. It retains tags/images and refuses manifest ID reuse. Local image IDs cannot be pulled on another Docker-host.

Backend metadata is `/app/backend-release.json`; frontend metadata is `/opt/traceweave/frontend-release.json`. Readiness checks baked versions/contracts and actual migration history against the manifest. A backend-only update retains the frontend image and `frontendReleaseId`. Gateway exposes the current overall release through `/release.json`, including maintenance.

## Public Packaging

Public application images have not been released. A future registry release must publish verified images for the declared architectures, check anonymous pulls, and produce immutable registry-digest manifests. Include the versioned manifest, `releases/stable.json` and `releases/tools-image.txt` with the matching tools digest; verify bootstrap on a clean host, including without host Python.

Source GitHub visibility is separate from registry visibility. The existing Docker delivery workflow builds/tests amd64 and arm64; it does not push images. Registry publishing requires its own workflow/action. Publishing does not update installed users automatically; repeat bootstrap uses their saved manifest.

## Old Tabs and Pending Requests

Clients retain exact pending bytes, account, operation ID and contract. Maintenance keeps them available for explicit replay. Unsupported clients receive `client_upgrade_required`; account changes fence old work. Do not remove supported client hashes through ordinary update. Merely editing a JSON list does not implement backend compatibility.

Before replacing frontend, the updater copies current hashed assets to the retained-assets volume. Current files take precedence; fallback serves only old `/assets/*`. HTML is not cached; hashed assets are immutable. Missing JS/CSS returns 404 rather than SPA HTML. Cleanup requires a separate compatibility decision; users choose reload after handling drafts.

## Update

```sh
printf 'Path to verified next release manifest: '
IFS= read -r TW_NEXT_RELEASE_MANIFEST
./traceweave.sh update --release "$TW_NEXT_RELEASE_MANIFEST"
./traceweave.sh status
```

Preflight checks compatibility/images/disk space before entering maintenance. Frontend-only update retains backend and skips backup/migration. Backend update gracefully stops backend and takes a checked offline backup; schema changes then run an explicit migration before restart. Ordinary update rejects changes to PostgreSQL/gateway/tools images. It does not remove volumes or run global Compose teardown.

The selected manifest switches only after readiness; the previous one and update journal retain recovery information. An interrupted phase blocks ordinary start. Use [Operations](operations.md#interrupted-operations) recovery instead of manually reopening gateway.

## Rollback

```sh
./traceweave.sh rollback
```

Image rollback requires the actual migration history to equal that of the target release. It checks maintenance and graceful shutdown, replaces compatible images and reopens only after readiness. After a schema change, leave maintenance active and use a compatible fix or restore the pre-update backup to new volumes. There is no automatic reverse migration. Registry images or privately retained image archives are required for disaster recovery; a manifest alone does not contain the image bytes.

---

[Back to documentation](index.md) · [README](../../README.md)
