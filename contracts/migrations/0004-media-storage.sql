-- CR-E4-001: typed original directories; all legacy storage keys stay valid.
ALTER TABLE blobs DROP CONSTRAINT blobs_storage_key_check;
ALTER TABLE blobs ADD CONSTRAINT blobs_storage_key_check
 CHECK(storage_key ~ '^((images|audio|video)/)?[a-f0-9]{2}/[a-f0-9]{64}$');

-- Legacy originals have unknown verified metadata. Never copy an untrusted MIME hint here.
ALTER TABLE blobs ADD COLUMN verified_mime_type text;
ALTER TABLE blobs ADD COLUMN media_kind text;
ALTER TABLE blobs ADD COLUMN image_width bigint;
ALTER TABLE blobs ADD COLUMN image_height bigint;
ALTER TABLE blobs ADD CONSTRAINT blobs_verified_media_check CHECK (
 (verified_mime_type IS NULL AND media_kind IS NULL AND image_width IS NULL AND image_height IS NULL)
 OR (verified_mime_type IS NOT NULL AND media_kind IS NOT NULL AND
  ((media_kind='text' AND verified_mime_type IN ('text/plain','text/markdown')) OR
   (media_kind='image' AND verified_mime_type IN ('image/jpeg','image/png','image/webp','image/gif')) OR
   (media_kind='audio' AND verified_mime_type IN ('audio/mpeg','audio/wav','audio/ogg','audio/mp4')) OR
   (media_kind='video' AND verified_mime_type IN ('video/mp4','video/webm','video/quicktime')))
  AND ((image_width IS NULL AND image_height IS NULL) OR
       (media_kind='image' AND image_width IS NOT NULL AND image_height IS NOT NULL AND
        image_width BETWEEN 1 AND 2147483647 AND image_height BETWEEN 1 AND 2147483647)))
);

CREATE OR REPLACE FUNCTION rg_blob_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.id,NEW.investigation_id,NEW.storage_key,NEW.sha256,NEW.byte_size)
 IS DISTINCT FROM ROW(OLD.id,OLD.investigation_id,OLD.storage_key,OLD.sha256,OLD.byte_size) THEN
 RAISE EXCEPTION 'immutable original identity' USING ERRCODE='23514'; END IF;
 -- Legacy metadata can be populated exactly once after the original is verified.
 IF ROW(OLD.verified_mime_type,OLD.media_kind,OLD.image_width,OLD.image_height)
 IS DISTINCT FROM ROW(NULL::text,NULL::text,NULL::bigint,NULL::bigint)
 AND ROW(NEW.verified_mime_type,NEW.media_kind,NEW.image_width,NEW.image_height)
 IS DISTINCT FROM ROW(OLD.verified_mime_type,OLD.media_kind,OLD.image_width,OLD.image_height) THEN
 RAISE EXCEPTION 'immutable verified metadata' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
