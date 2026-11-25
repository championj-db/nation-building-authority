-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Decision record: who reviewed what, when, the evidence viewed and the disposition.
SELECT
  r.review_id,
  r.alert_id,
  r.reviewed_ts,
  r.officer_name,
  r.disposition,
  r.evidence_viewed,
  r.notes,
  coalesce(a.registration_plate, split(r.alert_id, ':')[0]) AS registration_plate,
  a.alert_title
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_alert_review_audit') r
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_alert') a
  ON a.alert_id = r.alert_id
WHERE length(:refresh) >= 0
ORDER BY r.reviewed_ts DESC
LIMIT 20
