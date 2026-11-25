-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, obligation_version, obligation_title, gate_id, gate_label, gate_order, owner_role, framework,
       requirements_total, requirements_complete, requirements_expiring, requirements_gap, evidence_mapped,
       pending_review_count, status, review_date, days_to_review, register_state
FROM IDENTIFIER(:catalog || '.' || :schema || '.obligation_coverage')
ORDER BY CASE status WHEN 'Gap' THEN 1 WHEN 'Expiring' THEN 2 ELSE 3 END, gate_order, obligation_id
LIMIT 500;
