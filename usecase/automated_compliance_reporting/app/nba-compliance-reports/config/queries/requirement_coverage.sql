-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, obligation_version, requirement_id, artefact_type, requirement_description, expected_source_id,
       max_age_days, mandatory, mapped_evidence_count, best_evidence_id, best_evidence_title, best_artefact_version,
       expires_on, days_to_expiry, pending_review_count, status, gap_reason
FROM IDENTIFIER(:catalog || '.' || :schema || '.requirement_coverage')
ORDER BY obligation_id, requirement_id;
