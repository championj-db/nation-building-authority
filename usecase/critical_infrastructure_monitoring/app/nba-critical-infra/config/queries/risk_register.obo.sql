-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Highest-scoring entities, alerting or not, with every contributing factor for review.
SELECT
  s.asset_id,
  s.registration_plate,
  s.operator_name,
  s.risk_type,
  s.primary_factor,
  s.risk_score,
  s.recommended_action,
  s.alert_threshold,
  s.last_seen_ts,
  concat(s.last_seen_road, ', ', s.last_seen_locality) AS last_seen_location,
  s.rest_window_anomaly_score,
  s.night_movement_score,
  s.recent_pattern_score,
  s.route_variance_score,
  s.mass_variance_score,
  s.defect_history_score,
  s.sightings_count,
  s.model_version,
  s.run_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_asset_risk_score') s
WHERE length(:refresh) >= 0
ORDER BY s.risk_score DESC, s.last_seen_ts DESC
LIMIT 12
