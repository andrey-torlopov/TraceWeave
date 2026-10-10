-- CR-E2-002: only document bodies grow; other Markdown fields retain their limits.
CREATE DOMAIN rg_document_markdown AS text CHECK (octet_length(VALUE) <= 5242880);

ALTER TABLE nodes ALTER COLUMN body_markdown TYPE rg_document_markdown USING body_markdown::text;

-- Preserve complete idempotency request bytes, including JSON string escaping.
ALTER TABLE operations DROP CONSTRAINT operations_request_bytes_check;
ALTER TABLE operations ADD CONSTRAINT operations_request_bytes_check CHECK (octet_length(request_bytes) <= 33554432);
