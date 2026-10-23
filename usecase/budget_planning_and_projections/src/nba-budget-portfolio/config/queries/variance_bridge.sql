-- @param period STRING
SELECT
  period,
  period_label,
  driver,
  driver_order,
  amount_aud_m,
  plan_aud_m,
  forecast_aud_m
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.variance_bridge
WHERE scope_level = 'portfolio'
  AND scope_id = 'PORTFOLIO'
  AND period = :period
ORDER BY driver_order;
