-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT obligation_id, obligation_title, gate_id, owner_role, evidence_mapped, status, review_date
FROM IDENTIFIER(:catalog || '.' || :schema || '.obligation_coverage')
ORDER BY CASE status WHEN 'Gap' THEN 1 WHEN 'Expiring' THEN 2 ELSE 3 END, gate_id, obligation_id
LIMIT 100;
