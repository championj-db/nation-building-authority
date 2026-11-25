-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Decision record: who reviewed what, when, the evidence viewed and the disposition.
SELECT r.review_id, r.incident_id, r.reviewed_ts, r.officer_name, r.disposition, r.evidence_viewed,
       r.notes, i.asset_name, i.sector, i.incident_title
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_incident_review_audit') r
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_incident') i ON i.incident_id = r.incident_id
WHERE length(:refresh) >= 0
ORDER BY r.reviewed_ts DESC
LIMIT 20
