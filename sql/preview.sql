-- Read-only. Identifiers are substituted by psycopg.sql.Identifier, never user string interpolation.
-- Aggregate distinct observed IDs before vocabulary joins. Preserve ALL mapping candidates.
WITH observed AS (
 SELECT {column} AS old_id, count(*)::bigint AS record_count
 FROM {cdm}.{table} GROUP BY {column}
)
SELECT o.old_id, o.record_count, to_jsonb(c) AS old,
 COALESCE((SELECT jsonb_agg(to_jsonb(r) || jsonb_build_object('target',to_jsonb(n))
                           ORDER BY r.relationship_id,r.concept_id_2,r.valid_start_date)
 FROM {vocab}.concept_relationship r
 LEFT JOIN {vocab}.concept n ON n.concept_id=r.concept_id_2
 WHERE r.concept_id_1=o.old_id AND r.relationship_id IN ('Maps to','Maps to value')),'[]'::jsonb) AS edges
FROM observed o LEFT JOIN {vocab}.concept c ON c.concept_id=o.old_id
ORDER BY o.old_id NULLS FIRST
