-- Preserve every existing owner UUID/hash and foreign key; attach email only through operator CLI.
ALTER TABLE owners DROP COLUMN singleton;
ALTER TABLE owners ADD COLUMN email text;
ALTER TABLE owners ADD COLUMN email_verified_at timestamptz;
ALTER TABLE owners ADD CONSTRAINT owners_email_shape CHECK(email IS NULL OR (octet_length(email)<=254 AND email=lower(btrim(email)) AND email ~ '^[!-~]+@[a-z0-9.-]+$'));
ALTER TABLE owners ADD CONSTRAINT owners_verified_email CHECK(email_verified_at IS NULL OR email IS NOT NULL);
CREATE UNIQUE INDEX owners_email_unique ON owners(email) WHERE email IS NOT NULL;
-- Old sessions cannot silently continue across the owner-to-accounts transition.
DELETE FROM sessions;
CREATE TABLE account_tokens (
 token_hash rg_sha256 PRIMARY KEY, owner_id uuid NOT NULL REFERENCES owners(id),
 purpose text NOT NULL CHECK(purpose IN ('verification','reset')),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 UNIQUE(owner_id,purpose), CHECK(expires_at>created_at)
);
CREATE INDEX account_tokens_expiry ON account_tokens(expires_at);
CREATE TABLE account_attempts (
 action text NOT NULL, key_hash rg_sha256 NOT NULL,
 attempts integer NOT NULL CHECK(attempts>=0), window_started_at timestamptz NOT NULL,
 PRIMARY KEY(action,key_hash)
);
CREATE INDEX account_attempts_expiry ON account_attempts(window_started_at);
