-- @param scenario_id STRING
-- @param financial_year STRING
-- @param category_id STRING
-- @param data_version STRING
SELECT
  exposure.project_id,
  exposure.project_name,
  exposure.program_id,
  exposure.program_name,
  project.schedule_flexibility,
  project.priority_tier,
  project.region_type,
  exposure.spend_aud_m,
  exposure.share_of_demand_pct,
  exposure.gap_value_aud_m,
  exposure.heavy_user,
  confidence.confidence_pct
FROM {{schema}}.capacity_exposure exposure
JOIN {{schema}}.dim_project project ON project.project_id = exposure.project_id
LEFT JOIN {{schema}}.project_confidence confidence
  ON confidence.scenario_id = exposure.scenario_id AND confidence.project_id = exposure.project_id
WHERE exposure.scenario_id = :scenario_id
  AND exposure.financial_year = :financial_year
  AND exposure.category_id = :category_id
  AND :data_version IS NOT NULL
ORDER BY exposure.share_of_demand_pct DESC
LIMIT 15;
