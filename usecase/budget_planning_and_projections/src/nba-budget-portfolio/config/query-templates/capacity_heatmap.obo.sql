-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  category_id,
  capacity_category,
  unit,
  financial_year,
  fy,
  demand_units,
  available_units,
  utilisation_pct,
  baseline_utilisation_pct,
  status,
  gap_units,
  gap_value_aud_m,
  capacity_model_version
FROM {{schema}}.capacity_demand
WHERE scenario_id = :scenario_id
  AND :data_version IS NOT NULL
ORDER BY capacity_category, fy;
