-- TW-E2-004: add the ordinary evidence type without replacing user catalog entries.
INSERT INTO node_types(id,investigation_id,code,name,icon_key,color,is_system,is_hidden,attribute_templates)
SELECT gen_random_uuid(), i.id, 'evidence', 'Улика', 'search', '#EAB308', false, false, '[]'::jsonb
FROM investigations i
WHERE NOT EXISTS (
  SELECT 1 FROM node_types t WHERE t.investigation_id=i.id
    AND (t.code='evidence' OR translate(btrim(t.name),'УЛИКА','улика')='улика')
);
