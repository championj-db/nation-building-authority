-- @param sector STRING
SELECT
  rank,
  program_name,
  sector,
  projects,
  assurance_rating,
  plan_aud_m,
  forecast_aud_m,
  variance_aud_m,
  capacity_driver,
  confidence_pct,
  requires_attention
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.portfolio_attention_list
WHERE (:sector = 'ALL' OR sector = :sector)
ORDER BY rank
LIMIT 20;
