-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT evidence_id, title, source_name, file_format, latest_version, approval_status, mapping_state,
       mapping_method, artefact_type, ai_confidence, freshness_status, expires_on, collected_at,
       integrity_verified
FROM IDENTIFIER(:catalog || '.' || :schema || '.evidence_inbox')
ORDER BY collected_at DESC
LIMIT 200;
