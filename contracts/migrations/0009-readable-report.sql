-- CR-E7-002: readable reports share the immutable revision-based export capture.
ALTER TABLE export_jobs DROP CONSTRAINT export_jobs_kind_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_kind_check
  CHECK(kind IN ('project_archive','report_markdown','report_bundle','obsidian_vault','readable_report'));
ALTER TABLE export_jobs DROP CONSTRAINT export_jobs_check;
ALTER TABLE export_jobs ADD CONSTRAINT export_jobs_check
  CHECK((kind IN ('project_archive','obsidian_vault','readable_report') AND source_revision IS NOT NULL AND report_snapshot_id IS NULL)
     OR (kind IN ('report_markdown','report_bundle') AND source_revision IS NULL AND report_snapshot_id IS NOT NULL));
