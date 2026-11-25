-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param refresh STRING = initial
-- Decision briefs, latest state per brief (append-only: sign-off is a newer row).
SELECT brief_id, created_ts, officer, title, policy_question, access_basis, audience, settings, findings,
       suppression_applied, status, signed_off_by, signed_off_ts,
       min(created_ts) OVER (PARTITION BY brief_id) AS prepared_ts,
       first_value(officer) OVER (PARTITION BY brief_id ORDER BY created_ts) AS prepared_by
FROM IDENTIFIER(:catalog || '.' || :schema || '.app_brief')
WHERE length(:refresh) >= 0
QUALIFY row_number() OVER (PARTITION BY brief_id ORDER BY created_ts DESC) = 1
ORDER BY prepared_ts DESC
LIMIT 50
