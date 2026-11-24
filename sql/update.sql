-- One set-based update per table, restricted to frozen primary keys and row fingerprints.
-- remediation_stage has UNIQUE(table_name,column_name,row_id), so UPDATE FROM is deterministic.
WITH changed AS (
 UPDATE {cdm}.{table} AS t SET {column} = p.new_id
 FROM pg_temp.remediation_stage p
 WHERE p.table_name=%s AND p.column_name=%s AND t.{pk}=p.row_id
   AND t.{column}=p.old_id AND md5(row_to_json(t)::text)=p.before_hash
 RETURNING t.{pk} AS row_id, md5(row_to_json(t)::text) AS after_hash
), audited AS (
 UPDATE {audit}.journal j SET after_hash=c.after_hash FROM changed c
 WHERE j.run_id=%s AND j.table_name=%s AND j.column_name=%s AND j.row_id=c.row_id
 RETURNING j.row_id
)
SELECT count(*)::bigint AS changed FROM audited
