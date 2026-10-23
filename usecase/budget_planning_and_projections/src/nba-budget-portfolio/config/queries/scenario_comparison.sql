-- @param scenario_id STRING
SELECT
  financial_year,
  fy,
  forecast_aud_m,
  baseline_forecast_aud_m,
  delta_vs_baseline_aud_m,
  peak_utilisation_pct,
  capacity_breaches,
  status
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.scenario_comparison
WHERE scenario_id = :scenario_id
ORDER BY fy;
