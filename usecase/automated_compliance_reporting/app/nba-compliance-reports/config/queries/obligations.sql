-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, title, gate_label, owner_role, framework, requirement_count, register_state,
       effective_from, draft_version
FROM IDENTIFIER(:catalog || '.' || :schema || '.obligation_register_current')
ORDER BY gate_id, obligation_id
LIMIT 250;
