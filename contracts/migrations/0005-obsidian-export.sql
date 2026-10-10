-- CR-E7-001: a vault export is a revision-based technical job, distinct from
-- the full TraceWeave project archive and frozen report exports.
ALTER TABLE export_jobs DROP CONSTRAINT export_jobs_kind_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_kind_check
  CHECK(kind IN ('project_archive','report_markdown','report_bundle','obsidian_vault'));
ALTER TABLE export_jobs DROP CONSTRAINT export_jobs_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_check
  CHECK((kind IN ('project_archive','obsidian_vault') AND source_revision IS NOT NULL AND report_snapshot_id IS NULL)
     OR (kind IN ('report_markdown','report_bundle') AND source_revision IS NULL AND report_snapshot_id IS NOT NULL));
