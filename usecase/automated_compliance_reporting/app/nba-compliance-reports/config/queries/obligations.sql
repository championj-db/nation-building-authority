-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, version, title, description, gate_id, gate_label, gate_name, owner_role, framework, framework_url,
       requirement_count, register_state, effective_from, approved_at, approved_by, change_reason, draft_version,
       draft_proposed_at, draft_change_reason
FROM IDENTIFIER(:catalog || '.' || :schema || '.obligation_register_current')
ORDER BY gate_id, obligation_id
LIMIT 500;
