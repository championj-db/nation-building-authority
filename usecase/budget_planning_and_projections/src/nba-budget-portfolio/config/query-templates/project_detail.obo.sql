-- @param project_id STRING
-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  project.project_id,
  project.project_name,
  project.program_id,
  project.program_name,
  project.sector,
  project.subsector,
  project.jurisdiction,
  project.region_type,
  project.delivery_agency,
  project.delivery_model,
  project.lifecycle_stage,
  project.priority_tier,
  project.schedule_flexibility,
  project.funding_source,
  project.tec_p50_aud_m,
  project.tec_p90_aud_m,
  project.contingency_pct,
  project.bcr,
  project.latest_gate_name,
  project.gateway_rating,
  project.gateway_report_date,
  project.baseline_start,
  project.baseline_finish,
  project.plan_finish,
  project.forecast_finish,
  project.percent_complete,
  drivers.slip_months,
  drivers.delay_cost_aud_m,
  drivers.approved_scope_aud_m,
  drivers.approved_packaging_aud_m,
  drivers.cost_performance_pct,
  drivers.actual_to_date_aud_m,
  drivers.plan_to_date_aud_m,
  drivers.eac_plan_aud_m,
  drivers.eac_forecast_aud_m,
  drivers.pending_changes,
  confidence.base_confidence_pct,
  confidence.capacity_penalty_pct,
  confidence.confidence_pct
FROM {{schema}}.dim_project project
LEFT JOIN {{schema}}.forecast_project_drivers drivers ON drivers.project_id = project.project_id
LEFT JOIN {{schema}}.project_confidence confidence
  ON confidence.project_id = project.project_id AND confidence.scenario_id = :scenario_id
WHERE project.project_id = :project_id
  AND :data_version IS NOT NULL;
