-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT
  as_of_date, obligations, obligations_complete, obligations_expiring, obligations_gap,
  requirements_total, requirements_met, evidence_coverage_pct, open_alerts, open_high_alerts,
  evidence_needs_review, evidence_unmapped, sources_not_online, last_collected_at,
  mapping_accuracy, mapping_labelled_items, ai_suggestion_accuracy, ai_labelled_items,
  accuracy_evaluated_at, expiry_warning_days, refreshed_at
FROM IDENTIFIER(:catalog || '.' || :schema || '.compliance_overview')
ORDER BY as_of_date DESC
LIMIT 1;
