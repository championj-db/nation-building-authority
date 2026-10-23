-- @param period STRING
-- @param data_version STRING
SELECT
  period,
  period_label,
  driver,
  driver_order,
  amount_aud_m,
  plan_aud_m,
  forecast_aud_m
FROM {{schema}}.variance_bridge
WHERE scope_level = 'portfolio'
  AND scope_id = 'PORTFOLIO'
  AND period = :period
  AND :data_version IS NOT NULL
ORDER BY driver_order;
