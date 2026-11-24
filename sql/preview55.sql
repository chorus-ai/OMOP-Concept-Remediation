-- CDM 5.5 vocabulary metadata included without mapper/reviewer personal fields.
WITH observed AS (
 SELECT {column} AS old_id,count(*)::bigint AS record_count FROM {cdm}.{table} GROUP BY {column}
)
SELECT o.old_id,o.record_count,
 CASE WHEN c.concept_id IS NULL THEN NULL ELSE to_jsonb(c) || jsonb_build_object('_metadata',
   COALESCE((SELECT jsonb_agg(jsonb_build_object('concept_category',cm.concept_category,'reuse_status',cm.reuse_status) ORDER BY cm.concept_category,cm.reuse_status)
   FROM {vocab}.concept_metadata cm WHERE cm.concept_id=c.concept_id),'[]'::jsonb)) END AS old,
 COALESCE((SELECT jsonb_agg(to_jsonb(r) || jsonb_build_object(
   '_metadata',COALESCE((SELECT jsonb_agg(jsonb_build_object('relationship_predicate_id',rm.relationship_predicate_id,'relationship_group',rm.relationship_group) ORDER BY rm.relationship_predicate_id,rm.relationship_group)
       FROM {vocab}.concept_relationship_metadata rm WHERE rm.concept_id_1=r.concept_id_1 AND rm.concept_id_2=r.concept_id_2 AND rm.relationship_id=r.relationship_id),'[]'::jsonb),
   'target',CASE WHEN n.concept_id IS NULL THEN NULL ELSE to_jsonb(n) || jsonb_build_object('_metadata',
       COALESCE((SELECT jsonb_agg(jsonb_build_object('concept_category',nm.concept_category,'reuse_status',nm.reuse_status) ORDER BY nm.concept_category,nm.reuse_status)
       FROM {vocab}.concept_metadata nm WHERE nm.concept_id=n.concept_id),'[]'::jsonb)) END)
   ORDER BY r.relationship_id,r.concept_id_2,r.valid_start_date)
 FROM {vocab}.concept_relationship r LEFT JOIN {vocab}.concept n ON n.concept_id=r.concept_id_2
 WHERE r.concept_id_1=o.old_id AND r.relationship_id IN ('Maps to','Maps to value')),'[]'::jsonb) AS edges
FROM observed o LEFT JOIN {vocab}.concept c ON c.concept_id=o.old_id
ORDER BY o.old_id NULLS FIRST
