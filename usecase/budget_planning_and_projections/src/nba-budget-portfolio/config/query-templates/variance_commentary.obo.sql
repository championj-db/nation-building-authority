-- @param period STRING
-- @param data_version STRING
SELECT
  commentary.commentary_id,
  commentary.period,
  commentary.scope_level,
  commentary.scope_id,
  COALESCE(project.project_name, program.program_name, 'Portfolio') AS scope_name,
  commentary.reason_code,
  commentary.amount_aud_m,
  commentary.commentary,
  commentary.source,
  commentary.actor,
  commentary.created_at
FROM {{schema}}.variance_commentary commentary
LEFT JOIN {{schema}}.dim_project project ON commentary.scope_level = 'project' AND project.project_id = commentary.scope_id
LEFT JOIN {{schema}}.dim_program program ON commentary.scope_level = 'program' AND program.program_id = commentary.scope_id
WHERE commentary.period = :period
  AND :data_version IS NOT NULL
ORDER BY commentary.created_at DESC
LIMIT 50;
