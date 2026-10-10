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

For publication from GitHub tags, the source builder accepts independent `--backend-version`, `--frontend-version`, and `--delivery-version` values using `MAJOR.MINOR.PATCH` without `v`. Backend/frontend versions are passed to the existing Dockerfiles and recorded in the manifest; an explicit frontend version also becomes its `frontendReleaseId`. Gateway/tools use the delivery version in OCI labels. All four images receive OCI version/source/ref.name labels and component revision labels; an explicit delivery version additionally records and checks the delivery checkout before and after building. The publication workflow checks tag checkouts and tag/version agreement. Omitting these options preserves the existing local release-ID behavior. [Project task](../tasks/TW-E8-002-github-release-tags.md).

Backend metadata is `/app/backend-release.json`; frontend metadata is `/opt/traceweave/frontend-release.json`. Readiness checks baked versions/contracts and actual migration history against the manifest. A backend-only update retains the frontend image and `frontendReleaseId`. Gateway exposes the current overall release through `/release.json`, including maintenance.

## Public Packaging

The first public release `0.1.0` is published on Docker Hub as `andreytorlopov/traceweave-{backend,frontend,gateway,tools}:0.1.0` for `linux/amd64` and `linux/arm64`. Each source repository uses GitHub tag `v0.1.0`; the baked version is `0.1.0`. [Native validation and publication passed](https://github.com/andrey-torlopov/TraceWeaveBackend/actions/runs/38072087934); [fresh-host anonymous registry acceptance passed](https://github.com/andrey-torlopov/TraceWeave/actions/runs/38073642033), including Docker-only bootstrap/lifecycle and HTTPS/SMTP/accounts. The verified manifest is [releases/0.1.0.json](../../releases/0.1.0.json); [releases/stable.json](../../releases/stable.json) selects this release for a new installation, with [releases/tools-image.txt](../../releases/tools-image.txt) providing its tools digest. Matching assets and publication evidence are available in [GitHub Release v0.1.0](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0). All four image repositories are Public with immutable tags. Backend/frontend GitHub sources remain private.

The delivery workflow builds/tests without pushing images; the separate Docker Hub workflow publishes the tested images. Publishing does not update installed users automatically; repeat bootstrap uses their saved manifest.

## Docker Hub Publication Settings

Backend/frontend contain `.github/workflows/dockerhub.yml`. A `vMAJOR.MINOR.PATCH` tag push publishes that component after native Linux amd64/arm64 validation. Manual `full_release=true` publishes backend/frontend/gateway/tools using one new version. GitHub `v0.1.0` maps to Docker `0.1.0` and baked version `0.1.0`; tested images are transferred without rebuilding, and manifests record version tags with registry digests. Existing tags cannot be republished.

Both source repositories require Secrets `DOCKERHUB_TOKEN` (Docker Hub Read/Write PAT, already provided by the owner) and `SOURCE_REPOSITORIES_TOKEN` (GitHub fine-grained PAT with Contents: Read for the private backend/frontend repositories). Variables: `DOCKERHUB_USERNAME=andreytorlopov`, `TRACEWEAVE_DELIVERY_TAG=v0.1.0`, `TRACEWEAVE_COUNTERPART_TAG=v0.1.0`. The counterpart is frontend for a backend run and backend for a frontend run. **TraceWeave** requires only `SOURCE_REPOSITORIES_TOKEN` for integration CI; it does not need Docker Hub settings. The default `GITHUB_TOKEN` cannot read another private repository. [Private checkout documentation](https://github.com/actions/checkout#checkout-multiple-repos-private).

All four `andreytorlopov/traceweave-{backend,frontend,gateway,tools}` Docker Hub repositories must be Public with **All tags are immutable**; the workflow checks this before building. The first full release has already run manually from backend Actions with `release_tag=v0.1.0` and `full_release=true`. Do not republish existing tags. The next full release needs a new matching version in all three GitHub repositories; a component-only release needs a new tag for that component. Image availability and installable-manifest acceptance require separate evidence. [Current release protocol](../tasks/TW-E8-003-dockerhub-publication.md).

## Old Tabs and Pending Requests

Clients retain exact pending bytes, account, operation ID and contract. Maintenance keeps them available for explicit replay. Unsupported clients receive `client_upgrade_required`; account changes fence old work. Do not remove supported client hashes through ordinary update. Merely editing a JSON list does not implement backend compatibility.

Before replacing frontend, the updater copies current hashed assets to the retained-assets volume. Current files take precedence; fallback serves only old `/assets/*`. HTML is not cached; hashed assets are immutable. Missing JS/CSS returns 404 rather than SPA HTML. Cleanup requires a separate compatibility decision; users choose reload after handling drafts.

## New Installation of a Specific Version

Use source tag `v0.1.0` and assets from the same [GitHub Release](https://github.com/andrey-torlopov/TraceWeave/releases/tag/v0.1.0), saved under `releases/`. The target directory must be new:

```sh
set -eu
git clone --branch v0.1.0 --depth 1 https://github.com/andrey-torlopov/TraceWeave.git TraceWeave-0.1.0
cd TraceWeave-0.1.0
curl -fL --output releases/0.1.0.json https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/0.1.0.json
curl -fL --output releases/tools-image.txt https://github.com/andrey-torlopov/TraceWeave/releases/download/v0.1.0/tools-image.txt
./bootstrap.sh --release "$PWD/releases/0.1.0.json"
./traceweave.sh status
```

Git, curl, Docker and the Compose plugin are required; host Python is optional. The wrapper reads `releases/tools-image.txt` to run the published tools container. Its reference must match `images.tools`; retain this file for subsequent commands. Enter the initial account details in interactive bootstrap. A new installation uses the selected manifest; repeat bootstrap retains an existing installation's version.

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
