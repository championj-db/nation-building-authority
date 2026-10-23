-- @param period STRING
-- @param sector STRING
-- @param data_version STRING
WITH attributed AS (
  SELECT scope_id, SUM(amount_aud_m) AS attributed_aud_m, COUNT(*) AS commentary_count, MAX(created_at) AS last_commentary_at
  FROM {{schema}}.variance_commentary
  WHERE period = :period AND scope_level = 'project'
  GROUP BY scope_id
)
SELECT
  variance.project_id,
  variance.project_name,
  variance.program_id,
  variance.program_name,
  variance.sector,
  variance.plan_aud_m,
  variance.forecast_aud_m,
  variance.actual_aud_m,
  variance.variance_aud_m,
  variance.variance_pct,
  variance.tolerance_aud_m,
  variance.outside_tolerance,
  variance.escalation_aud_m,
  variance.schedule_shift_aud_m,
  variance.scope_change_aud_m,
  variance.packaging_aud_m,
  variance.unexplained_aud_m,
  variance.primary_driver,
  variance.slip_months,
  variance.gateway_rating,
  variance.confidence_pct,
  variance.attention_reasons,
  variance.requires_attention,
  COALESCE(attributed.attributed_aud_m, 0) AS attributed_aud_m,
  COALESCE(attributed.commentary_count, 0) AS commentary_count,
  attributed.last_commentary_at
FROM {{schema}}.variance_project variance
LEFT JOIN attributed ON attributed.scope_id = variance.project_id
WHERE variance.period = :period
  AND (:sector = 'ALL' OR variance.sector = :sector)
  AND (variance.outside_tolerance OR variance.requires_attention OR ABS(variance.unexplained_aud_m) >= 10)
  AND :data_version IS NOT NULL
ORDER BY variance.requires_attention DESC, ABS(variance.variance_aud_m) DESC
LIMIT 40;
