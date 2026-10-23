-- @param scenario_id STRING
-- @param sector STRING
WITH expenditure AS (
  SELECT
    scenario_id,
    project_id,
    sector,
    SUM(forecast_aud_m) AS forecast_aud_m,
    SUM(forecast_real_aud_m) AS forecast_real_aud_m,
    SUM(plan_aud_m) AS plan_aud_m
  FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.expenditure_fy
  WHERE scenario_id = :scenario_id
    AND is_horizon
    AND (:sector = 'ALL' OR sector = :sector)
  GROUP BY scenario_id, project_id, sector
), confidence AS (
  SELECT
    SUM(pc.confidence_pct * pc.horizon_spend_aud_m) / NULLIF(SUM(pc.horizon_spend_aud_m), 0) AS confidence_pct
  FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.project_confidence pc
  INNER JOIN au_pubsec_catalog.budget_planning_and_projections_jared_champion.dim_project project
    ON project.project_id = pc.project_id
  WHERE pc.scenario_id = :scenario_id
    AND (:sector = 'ALL' OR project.sector = :sector)
), capacity_gaps AS (
  SELECT
    exposure.financial_year,
    exposure.fy,
    exposure.capacity_category,
    SUM(exposure.gap_value_aud_m) AS gap_aud_m,
    COUNT(DISTINCT IF(exposure.gap_value_aud_m > 0, exposure.project_id, NULL)) AS projects_affected,
    COUNT(DISTINCT IF(exposure.gap_value_aud_m > 0, exposure.program_id, NULL)) AS programs_affected
  FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.capacity_exposure exposure
  INNER JOIN au_pubsec_catalog.budget_planning_and_projections_jared_champion.dim_project project
    ON project.project_id = exposure.project_id
  WHERE exposure.scenario_id = :scenario_id
    AND (:sector = 'ALL' OR project.sector = :sector)
  GROUP BY exposure.financial_year, exposure.fy, exposure.capacity_category
), peak_gap AS (
  SELECT *
  FROM capacity_gaps
  ORDER BY gap_aud_m DESC, fy
  LIMIT 1
), attention AS (
  SELECT COALESCE(SUM(attention_projects), 0) AS attention_projects
  FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.portfolio_attention_list
  WHERE (:sector = 'ALL' OR sector = :sector)
), base AS (
  SELECT *
  FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.portfolio_kpis
  WHERE scenario_id = :scenario_id
)
SELECT
  MAX(base.scenario_id) AS scenario_id,
  MAX(base.scenario_name) AS scenario_name,
  MAX(base.horizon_label) AS horizon_label,
  COALESCE(SUM(expenditure.forecast_aud_m), 0) AS approved_portfolio_aud_m,
  COALESCE(SUM(expenditure.forecast_real_aud_m), 0) AS approved_portfolio_real_aud_m,
  COALESCE(SUM(expenditure.plan_aud_m), 0) AS endorsed_plan_aud_m,
  COALESCE(SUM(expenditure.forecast_aud_m - expenditure.plan_aud_m), 0) AS vs_endorsed_plan_aud_m,
  COALESCE(MAX(peak_gap.gap_aud_m), 0) AS peak_capacity_gap_aud_m,
  COALESCE(MAX(peak_gap.financial_year), MAX(base.peak_capacity_gap_fy)) AS peak_capacity_gap_fy,
  COUNT(DISTINCT expenditure.project_id) AS active_projects,
  MAX(attention.attention_projects) AS attention_projects,
  MAX(confidence.confidence_pct) AS forecast_confidence_pct,
  MAX(peak_gap.projects_affected) AS projects_affected,
  MAX(peak_gap.programs_affected) AS programs_affected,
  MAX(base.capacity_breaches) AS capacity_breaches,
  MAX(base.constrained_categories_peak_fy) AS constrained_categories_peak_fy,
  MAX(base.capacity_categories) AS capacity_categories,
  MAX(base.peak_demand_capacity_pct) AS peak_demand_capacity_pct,
  MAX(base.peak_category) AS peak_category,
  MAX(base.peak_fy) AS peak_fy,
  MAX(base.resolvable_by_sequencing_aud_m) AS resolvable_by_sequencing_aud_m,
  MAX(base.ytd_actual_aud_m) AS ytd_actual_aud_m,
  MAX(base.ytd_plan_aud_m) AS ytd_plan_aud_m,
  MAX(base.current_fy_label) AS current_fy_label,
  MAX(base.current_fy_forecast_aud_m) AS current_fy_forecast_aud_m,
  MAX(base.current_fy_plan_aud_m) AS current_fy_plan_aud_m,
  MAX(base.schedule_variance_months) AS schedule_variance_months,
  MAX(base.current_fy_unexplained_aud_m) AS current_fy_unexplained_aud_m,
  MAX(base.as_of_date) AS as_of_date,
  MAX(base.actuals_through) AS actuals_through,
  MAX(base.plan_version) AS plan_version,
  MAX(base.capacity_model_version) AS capacity_model_version,
  MAX(base.figure_status) AS figure_status,
  MAX(base.refreshed_at) AS refreshed_at
FROM base
CROSS JOIN confidence
CROSS JOIN attention
LEFT JOIN expenditure ON TRUE
LEFT JOIN peak_gap ON TRUE
;
