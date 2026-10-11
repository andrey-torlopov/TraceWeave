# Changelog

## 0.1.4 — 2026-10-11

- Add graph settings beside zoom controls with an integer card shrink factor from 2 to 10 (default 3); 5 switches to compact nodes at 20% zoom and below.
- Restore the saved value after invalid input; persist per-investigation view preferences without changing documents, relations or revision.
- Select exact compatible update manifests for retained 0.1.0, 0.1.1 and 0.1.3 infrastructure.
- Keep the API and migration history unchanged from 0.1.3; verify same-schema image rollback and backup restore on native amd64/arm64.

## 0.1.3 — 2026-10-11

- Allow parallel relations, including identical type/direction/label pairs, while preserving separate IDs and idempotent commands.
- Show fixed endpoint titles with a live direction preview, place the relation label first and offer four directions.
- Preserve the entire local direction choice and fixed endpoints when reviewing conflicting server edits.
- Add two-way rendering and Obsidian export; reverse direction swaps the stored endpoints.
- Apply append-only migration 7 through guided bootstrap after a verified offline backup; retain old pending-client compatibility.
- Select reviewed update manifests for retained 0.1.0 infrastructure and fresh 0.1.1 installations.
- Refuse image rollback across the schema change; recover the verified pre-update backup into new volumes.

## 0.1.2 — superseded before stable promotion

- Preserve the published immutable tags and images; use 0.1.3 for corrected conflict review.

## 0.1.1 — 2026-10-10

- Deliver node deletion with cascading incident relations through backend/frontend 0.1.1.
- Exercise cascade, atomic failure/replay and retained original downloads in native publication and anonymous registry checks.
- Keep database migrations and the API contract unchanged.

## Unreleased

### Guided bootstrap updates

- Display installed backend/frontend versions and offer a newer compatible local release when bootstrap is repeated.
- Select the verified 0.1.1 update manifest for an existing 0.1.0 installation, retaining its infrastructure.
- Run the existing backup/migration/readiness pipeline after confirmation; preserve the installed release when declined and refuse automatic downgrades or incomplete-operation replacement.

### Documentation boundary and banners — 2026-10-10

- Use the TraceWeave illustration with distinct backend/frontend paper-card markers.
- Keep user installation, operation and data/security guides public; centralize engineering requirements and protocols in private backend documentation.
- Correct release 0.1.0 availability and link the full project from both private components.

### Documentation — 2026-10-10

- Add English and Russian READMEs, language navigation and documentation indexes.
- Document the current installation, architecture, contracts and verification boundaries.
- Use Letopis as the documentation structure and presentation reference.

This entry records documentation changes; it does not announce a container or P0 release.
