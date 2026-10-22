-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT alert_id, alert_type, severity, obligation_id, headline, detail, due_date, first_detected_at
FROM IDENTIFIER(:catalog || '.' || :schema || '.needs_attention')
ORDER BY CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, due_date
LIMIT 20;
