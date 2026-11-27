-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- SIMULATED history: invoices paid per week against today's terms and the 1 January 2027 terms.
SELECT CAST(week AS STRING) AS week, invoices_paid, late_current, late_2027, interest_current, value_paid,
       median_business_days_to_pay, pct_late_current, pct_late_2027
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_readiness_weekly')
ORDER BY week
