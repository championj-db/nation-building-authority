-- @param project_id STRING
-- @param scenario_id STRING
-- @param data_version STRING
SELECT
  month,
  financial_year,
  plan_aud_m,
  forecast_aud_m,
  actual_aud_m,
  is_actual_month
FROM {{schema}}.expenditure_monthly
WHERE project_id = :project_id
  AND scenario_id = :scenario_id
  AND fy BETWEEN (SELECT MIN(fy) - 2 FROM {{schema}}.dim_financial_year WHERE is_horizon)
             AND (SELECT MAX(fy) + 2 FROM {{schema}}.dim_financial_year WHERE is_horizon)
  AND :data_version IS NOT NULL
ORDER BY month;
