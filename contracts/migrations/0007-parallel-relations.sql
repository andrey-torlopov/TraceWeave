-- CR-E3-003: distinct relation UUIDs may describe the same semantic relationship.
-- Existing data and the immutable migrations 0001-0006 are preserved.
DROP INDEX relations_active_identity;
ALTER TABLE relations ADD COLUMN bidirectional boolean NOT NULL DEFAULT false;
ALTER TABLE relations ADD CONSTRAINT relations_bidirectional_direction CHECK (NOT bidirectional OR directed);
CREATE INDEX relations_active_pair ON relations(investigation_id,source_node_id,target_node_id) WHERE deleted_at IS NULL;
