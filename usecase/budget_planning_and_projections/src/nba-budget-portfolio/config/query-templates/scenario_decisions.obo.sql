-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  decision.iteration,
  decision.project_id,
  decision.project_name,
  decision.defer_months,
  decision.cumulative_defer_months,
  decision.trigger_financial_year,
  category.capacity_category AS trigger_category,
  decision.trigger_utilisation_pct
FROM {{schema}}.scenario_sequencing_decisions decision
LEFT JOIN {{schema}}.dim_capacity_category category ON category.category_id = decision.trigger_category_id
WHERE decision.scenario_id = :scenario_id
  AND :data_version IS NOT NULL
ORDER BY decision.iteration
LIMIT 60;
