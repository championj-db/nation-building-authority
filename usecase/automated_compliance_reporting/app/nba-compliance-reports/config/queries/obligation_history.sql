-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, version, title, approval_state, effective_from, effective_to, retired_on, proposed_at,
       approved_at, approved_by, change_reason, requirement_count
FROM IDENTIFIER(:catalog || '.' || :schema || '.obligation_register')
ORDER BY obligation_id, version DESC;
