-- @param sector STRING
-- @param data_version STRING
SELECT
  rank,
  program_id,
  program_name,
  sector,
  projects,
  assurance_rating,
  worst_gateway_rating,
  plan_aud_m,
  forecast_aud_m,
  variance_aud_m,
  variance_pct,
  outside_tolerance,
  capacity_driver,
  capacity_gap_aud_m,
  max_slip_months,
  confidence_pct,
  attention_projects,
  requires_attention
FROM {{schema}}.portfolio_attention_list
WHERE (:sector = 'ALL' OR sector = :sector)
  AND :data_version IS NOT NULL
ORDER BY rank
LIMIT 20;
