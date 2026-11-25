-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT evidence_id, title, file_format, source_id, source_name, connector, latest_version, version_count,
       approved_version, collected_at, source_modified_at, approval_status, signed, checksum, integrity_verified,
       content_excerpt, mapping_state, mapping_method, artefact_type, mapped_obligations, suggested_obligations,
       ai_confidence, ai_rationale, model_endpoint, reviewer, reviewed_at, freshness_threshold_days, expires_on,
       days_to_expiry, freshness_status
FROM IDENTIFIER(:catalog || '.' || :schema || '.evidence_inbox')
ORDER BY CASE mapping_state WHEN 'Needs review' THEN 1 WHEN 'Unmapped' THEN 2 WHEN 'Mapped' THEN 3 ELSE 4 END,
         collected_at DESC, evidence_id
LIMIT 1000;
