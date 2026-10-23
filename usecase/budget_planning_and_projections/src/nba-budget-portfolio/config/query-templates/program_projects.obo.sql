-- @param program_id STRING
-- @param scenario_id STRING
-- @param data_version STRING
WITH horizon AS (
  SELECT project_id, SUM(plan_aud_m) AS plan_aud_m, SUM(forecast_aud_m) AS forecast_aud_m, SUM(actual_aud_m) AS actual_aud_m
  FROM {{schema}}.expenditure_fy
  WHERE scenario_id = :scenario_id AND is_horizon AND program_id = :program_id
  GROUP BY project_id
)
SELECT
  project.project_id,
  project.project_name,
  project.jurisdiction,
  project.region_type,
  project.lifecycle_stage,
  project.delivery_model,
  project.schedule_flexibility,
  project.priority_tier,
  project.gateway_rating,
  project.latest_gate_name,
  project.slip_months,
  project.percent_complete,
  project.eac_plan_aud_m,
  project.eac_forecast_aud_m,
  project.plan_finish,
  project.forecast_finish,
  horizon.plan_aud_m,
  horizon.forecast_aud_m,
  horizon.forecast_aud_m - horizon.plan_aud_m AS variance_aud_m,
  confidence.confidence_pct,
  program.program_executive,
  program.delivery_agency
FROM {{schema}}.dim_project project
JOIN {{schema}}.dim_program program ON program.program_id = project.program_id
LEFT JOIN horizon ON horizon.project_id = project.project_id
LEFT JOIN {{schema}}.project_confidence confidence
  ON confidence.project_id = project.project_id AND confidence.scenario_id = :scenario_id
WHERE project.program_id = :program_id
  AND :data_version IS NOT NULL
ORDER BY ABS(horizon.forecast_aud_m - horizon.plan_aud_m) DESC;
