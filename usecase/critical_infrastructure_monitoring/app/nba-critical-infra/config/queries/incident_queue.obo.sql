-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Open incidents joined to the latest officer decision for each, so the queue reflects
-- dispositions recorded through the app. Factor scores ride along for the review dialog.
WITH decisions AS (
  SELECT incident_id, disposition, officer_name, reviewed_ts
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_incident_review_audit')
  QUALIFY row_number() OVER (PARTITION BY incident_id ORDER BY reviewed_ts DESC) = 1
)
SELECT
  i.incident_id, i.created_ts, i.age_minutes, i.asset_id, i.asset_code, i.asset_name, i.asset_class,
  i.asset_class_label, i.sector, i.sector_label, i.operator_name, i.locality, i.state, i.latitude,
  i.longitude, i.risk_score, i.risk_rating, i.priority, i.likelihood, i.consequence_score,
  i.consequence_multiplier, i.dominant_factor, i.trigger_key, i.incident_title, i.evidence_summary,
  i.recommended_action, i.impact_summary, i.limit_exceedance_score, i.anomaly_score,
  i.hazard_exposure_score, i.condition_score, i.trigger_metric, i.trigger_metric_label, i.trigger_unit,
  i.trigger_value, i.trigger_value_ts, i.trigger_warn_limit, i.trigger_alarm_limit, i.trigger_direction,
  i.hazard_title, i.hazard_type, i.hazard_severity, i.condition_grade, i.inspection_overdue,
  i.people_served, i.people_affected, i.downstream_assets, i.downstream_sectors, i.detected_lag_minutes,
  CASE d.disposition WHEN 'dispatch' THEN 'dispatched' WHEN 'notify' THEN 'notified'
       WHEN 'monitor' THEN 'monitoring' ELSE 'open' END AS status,
  d.officer_name AS decided_by,
  d.reviewed_ts AS decided_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_incident') i
LEFT JOIN decisions d ON d.incident_id = i.incident_id AND d.reviewed_ts >= i.created_ts
WHERE length(:refresh) >= 0
ORDER BY i.priority ASC, i.risk_score DESC, i.people_affected DESC
LIMIT 300
