-- @param scenario_id STRING
-- @param sector STRING
-- @param price_basis STRING
SELECT
  expenditure.financial_year,
  expenditure.fy,
  SUM(expenditure.plan_aud_m) / 1000 AS plan_aud_bn,
  SUM(CASE WHEN :price_basis = 'real' THEN expenditure.forecast_real_aud_m ELSE expenditure.forecast_aud_m END) / 1000 AS forecast_aud_bn,
  SUM(expenditure.actual_aud_m) / 1000 AS actual_aud_bn,
  MAX(CASE WHEN :sector = 'ALL' THEN capacity.capacity_aud_m ELSE NULL END) / 1000 AS capacity_aud_bn
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.expenditure_fy expenditure
LEFT JOIN au_pubsec_catalog.budget_planning_and_projections_jared_champion.portfolio_capacity_fy capacity
  USING (scenario_id, fy, financial_year)
WHERE scenario_id = :scenario_id
  AND is_horizon
  AND (:sector = 'ALL' OR expenditure.sector = :sector)
GROUP BY expenditure.financial_year, expenditure.fy
ORDER BY expenditure.fy;
