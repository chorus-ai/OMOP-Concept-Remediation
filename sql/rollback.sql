-- Exact audit journal reversal; refuses rows changed since this run.
UPDATE {cdm}.{table} AS t SET {column} = %s
WHERE t.{pk} = %s AND t.{column} = %s
  AND md5(row_to_json(t)::text) = %s
RETURNING md5(row_to_json(t)::text)
