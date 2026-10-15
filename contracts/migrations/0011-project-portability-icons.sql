-- TW-E7-003 / TW-E2-005: additive portability and per-document emoji.
ALTER TABLE nodes ADD COLUMN icon_emoji text
 CHECK(icon_emoji IS NULL OR (octet_length(icon_emoji) BETWEEN 1 AND 128));
ALTER TABLE investigations ADD COLUMN presentation_seed jsonb
 CHECK(presentation_seed IS NULL OR jsonb_typeof(presentation_seed)='object');
ALTER TABLE investigations ADD COLUMN import_provenance jsonb
 CHECK(import_provenance IS NULL OR jsonb_typeof(import_provenance)='object');
ALTER TABLE import_jobs ADD COLUMN content_sha256 rg_sha256;
ALTER TABLE import_jobs ADD COLUMN validation_sha256 rg_sha256;
ALTER TABLE import_jobs ADD COLUMN uuid_map jsonb CHECK(uuid_map IS NULL OR jsonb_typeof(uuid_map)='object');
ALTER TABLE import_jobs ADD COLUMN staging_cleaned boolean NOT NULL DEFAULT false;
