-- @param sector STRING
-- @param data_version STRING
SELECT
  exception.rank,
  exception.exception_id,
  exception.program_id,
  exception.program_name,
  exception.exception_type,
  exception.delta_value,
  exception.delta_unit,
  exception.description,
  exception.status
FROM {{schema}}.priority_exceptions exception
LEFT JOIN {{schema}}.portfolio_attention_list attention
  ON attention.program_id = exception.program_id
WHERE (:sector = 'ALL' OR attention.sector = :sector)
  AND :data_version IS NOT NULL
ORDER BY exception.rank
LIMIT 6;
