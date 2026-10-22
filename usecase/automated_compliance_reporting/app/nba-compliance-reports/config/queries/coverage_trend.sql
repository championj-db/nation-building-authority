-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT as_of_date,
       ROUND(100.0 * SUM(requirements_complete) / NULLIF(SUM(requirements_total), 0), 1) AS coverage_pct,
       SUM(requirements_gap) AS requirements_gap,
       SUM(requirements_expiring) AS requirements_expiring
FROM IDENTIFIER(:catalog || '.' || :schema || '.coverage_history')
GROUP BY as_of_date
ORDER BY as_of_date;
