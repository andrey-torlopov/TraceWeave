-- CR-E4-002: inert arbitrary originals; existing blobs and identities remain unchanged.
ALTER TABLE blobs DROP CONSTRAINT blobs_storage_key_check;
ALTER TABLE blobs ADD CONSTRAINT blobs_storage_key_check
 CHECK(storage_key ~ '^((images|audio|video|files)/)?[a-f0-9]{2}/[a-f0-9]{64}$');

ALTER TABLE blobs DROP CONSTRAINT blobs_verified_media_check;
ALTER TABLE blobs ADD CONSTRAINT blobs_verified_media_check CHECK (
 (verified_mime_type IS NULL AND media_kind IS NULL AND image_width IS NULL AND image_height IS NULL)
 OR (verified_mime_type IS NOT NULL AND media_kind IS NOT NULL AND
  ((media_kind='text' AND verified_mime_type IN ('text/plain','text/markdown')) OR
   (media_kind='image' AND verified_mime_type IN ('image/jpeg','image/png','image/webp','image/gif')) OR
   (media_kind='audio' AND verified_mime_type IN ('audio/mpeg','audio/wav','audio/ogg','audio/mp4')) OR
   (media_kind='video' AND verified_mime_type IN ('video/mp4','video/webm','video/quicktime')) OR
   (media_kind='file' AND verified_mime_type IN ('application/octet-stream','application/pdf')))
  AND ((image_width IS NULL AND image_height IS NULL) OR
       (media_kind='image' AND image_width IS NOT NULL AND image_height IS NOT NULL AND
        image_width BETWEEN 1 AND 2147483647 AND image_height BETWEEN 1 AND 2147483647)))
);

ALTER TABLE assets DROP CONSTRAINT assets_mime_type_check;
ALTER TABLE assets ADD CONSTRAINT assets_mime_type_check
 CHECK(mime_type IN ('text/plain','text/markdown','image/jpeg','image/png','image/webp','image/gif','audio/mpeg','audio/wav','audio/ogg','audio/mp4','video/mp4','video/webm','video/quicktime','application/octet-stream','application/pdf'));
ALTER TABLE assets DROP CONSTRAINT assets_media_kind_check;
ALTER TABLE assets ADD CONSTRAINT assets_media_kind_check CHECK(media_kind IN ('text','image','audio','video','file'));
ALTER TABLE assets ADD CONSTRAINT assets_file_format_check
 CHECK((media_kind='file') = (mime_type IN ('application/octet-stream','application/pdf')));
