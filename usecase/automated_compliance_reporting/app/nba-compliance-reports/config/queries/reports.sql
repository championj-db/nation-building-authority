-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT report_id, title, report_type, as_of_date, report_version, obligations_in_scope,
       obligations_complete, obligations_expiring, obligations_gap, evidence_items,
       executive_summary, summary_ai_generated, generated_at, generated_by, findings_digest
FROM IDENTIFIER(:catalog || '.' || :schema || '.compliance_reports')
ORDER BY generated_at DESC
LIMIT 100;
