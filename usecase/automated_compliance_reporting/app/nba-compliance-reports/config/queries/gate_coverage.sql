-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT gate_id, gate_label, gate_name, gate_order, obligations_total, obligations_complete,
       obligations_expiring, obligations_gap, coverage_pct
FROM IDENTIFIER(:catalog || '.' || :schema || '.gate_coverage')
ORDER BY gate_order;
