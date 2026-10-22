-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT source_id, source_name, connector, health, last_run_status, last_success_date,
       consecutive_failures, records_last_30d
FROM IDENTIFIER(:catalog || '.' || :schema || '.source_health')
ORDER BY CASE health WHEN 'Offline' THEN 1 WHEN 'Degraded' THEN 2 ELSE 3 END, source_name;
