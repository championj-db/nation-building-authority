-- @param project_id STRING
-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  financial_year,
  capacity_category,
  share_of_demand_pct,
  utilisation_pct,
  gap_value_aud_m,
  heavy_user
FROM {{schema}}.capacity_exposure
WHERE project_id = :project_id
  AND scenario_id = :scenario_id
  AND (utilisation_pct >= 90 OR gap_value_aud_m > 0)
  AND :data_version IS NOT NULL
ORDER BY gap_value_aud_m DESC, utilisation_pct DESC
LIMIT 12;
