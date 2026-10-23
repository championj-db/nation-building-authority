-- @param scenario_id STRING
-- @param financial_year STRING
SELECT
  capacity_category,
  unit,
  demand_units,
  available_units,
  utilisation_pct,
  status,
  gap_units,
  gap_value_aud_m,
  financial_year,
  fy,
  capacity_model_version
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.capacity_demand
WHERE scenario_id = :scenario_id
  AND financial_year = :financial_year
ORDER BY utilisation_pct DESC
LIMIT 12;
