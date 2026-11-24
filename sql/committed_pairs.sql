-- Aggregate journal only; no patient IDs or event identifiers in output.
SELECT table_name AS "table", column_name AS "column", old_id, new_id,
       count(*)::bigint AS updated_rows,
       bool_and(after_hash <> '') AS complete
FROM {audit}.journal WHERE run_id=%s
GROUP BY table_name,column_name,old_id,new_id
ORDER BY table_name,column_name,old_id,new_id
