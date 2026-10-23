-- @param scenario_id STRING
-- @param sector STRING
-- @param price_basis STRING
-- @param data_version STRING
SELECT
  expenditure.financial_year,
  expenditure.fy,
  SUM(CASE WHEN :price_basis = 'real' THEN expenditure.plan_real_aud_m ELSE expenditure.plan_aud_m END) / 1000 AS plan_aud_bn,
  SUM(CASE WHEN :price_basis = 'real' THEN expenditure.forecast_real_aud_m ELSE expenditure.forecast_aud_m END) / 1000 AS forecast_aud_bn,
  SUM(CASE WHEN :price_basis = 'real' THEN expenditure.actual_real_aud_m ELSE expenditure.actual_aud_m END) / 1000 AS actual_aud_bn,
  MAX(CASE WHEN :sector = 'ALL' THEN
        CASE WHEN :price_basis = 'real' THEN capacity.capacity_real_aud_m ELSE capacity.capacity_aud_m END END) / 1000 AS capacity_aud_bn,
  MAX(CASE WHEN :sector = 'ALL' AND :price_basis <> 'real' THEN capacity.forecast_p10_aud_m END) / 1000 AS p10_aud_bn,
  MAX(CASE WHEN :sector = 'ALL' AND :price_basis <> 'real' THEN capacity.forecast_p90_aud_m END) / 1000 AS p90_aud_bn,
  MAX(CASE WHEN :sector = 'ALL' THEN capacity.binding_category END) AS binding_category,
  MAX(CASE WHEN :sector = 'ALL' THEN capacity.capacity_gap_aud_m END) / 1000 AS capacity_gap_aud_bn
FROM {{schema}}.expenditure_fy expenditure
LEFT JOIN {{schema}}.portfolio_capacity_fy capacity
  USING (scenario_id, fy, financial_year)
WHERE scenario_id = :scenario_id
  AND is_horizon
  AND (:sector = 'ALL' OR expenditure.sector = :sector)
  AND :data_version IS NOT NULL
GROUP BY expenditure.financial_year, expenditure.fy
ORDER BY expenditure.fy;
