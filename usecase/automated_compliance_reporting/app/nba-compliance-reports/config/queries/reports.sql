-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
-- @param refresh STRING = 0
-- refresh only varies the cache key so the app can re-read after a report or verification run.
SELECT report_id, title, report_type, gate_id, as_of_date, report_version, register_version_label,
       evidence_snapshot_id, template_version, obligations_in_scope, obligations_complete, obligations_expiring,
       obligations_gap, evidence_items, executive_summary, summary_ai_generated, model_endpoint, prompt_version,
       generated_at, generated_by, findings_digest
FROM IDENTIFIER(:catalog || '.' || :schema || '.compliance_reports')
WHERE :refresh IS NOT NULL
ORDER BY generated_at DESC, report_id DESC
LIMIT 200;
