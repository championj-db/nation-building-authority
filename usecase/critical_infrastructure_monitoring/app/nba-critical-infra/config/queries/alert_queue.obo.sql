-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Open alert queue joined to the latest officer decision for each alert, so the queue reflects
-- dispositions recorded through the app. Factor scores ride along for the review dialog.
WITH decisions AS (
  SELECT alert_id, disposition, officer_name, reviewed_ts
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_alert_review_audit')
  QUALIFY row_number() OVER (PARTITION BY alert_id ORDER BY reviewed_ts DESC) = 1
)
SELECT
  a.alert_id,
  a.asset_id,
  a.registration_plate,
  a.operator_name,
  a.risk_type,
  a.primary_factor,
  a.risk_score,
  a.severity,
  a.priority,
  a.alert_title,
  a.alert_summary,
  a.recommended_action,
  a.last_seen_ts,
  a.last_seen_location,
  a.created_ts,
  a.age_minutes,
  s.rest_window_anomaly_score,
  s.night_movement_score,
  s.recent_pattern_score,
  s.route_variance_score,
  s.mass_variance_score,
  s.defect_history_score,
  s.sightings_count,
  CASE
    WHEN d.disposition = 'route' THEN 'routed'
    WHEN d.disposition = 'monitor' THEN 'monitoring'
    ELSE 'open'
  END AS status,
  d.officer_name AS decided_by,
  d.reviewed_ts AS decided_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_alert') a
JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_asset_risk_score') s
  ON s.asset_id = a.asset_id
LEFT JOIN decisions d
  ON d.alert_id = a.alert_id AND d.reviewed_ts >= a.created_ts
WHERE length(:refresh) >= 0
-- within a priority band, the most recently sighted vehicle is the one a field team can still reach
ORDER BY a.priority ASC, a.last_seen_ts DESC, a.risk_score DESC
LIMIT 200
