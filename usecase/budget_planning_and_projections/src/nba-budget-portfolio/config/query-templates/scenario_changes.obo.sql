-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  project_id,
  project_name,
  program_id,
  program_name,
  sector,
  region_type,
  baseline_horizon_aud_m,
  scenario_horizon_aud_m,
  delta_aud_m,
  baseline_finish,
  scenario_finish,
  finish_shift_months,
  completion_moves_beyond_horizon,
  delay_cost_aud_m,
  changes
FROM {{schema}}.scenario_project_changes
WHERE scenario_id = :scenario_id
  AND :data_version IS NOT NULL
ORDER BY ABS(delta_aud_m) DESC
LIMIT 60;
