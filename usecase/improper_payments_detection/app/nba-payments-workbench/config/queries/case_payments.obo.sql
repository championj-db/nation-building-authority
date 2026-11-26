-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- @param case_id STRING = IP-2048
SELECT payment_id, CAST(payment_date AS STRING) AS payment_date, amount, invoice_ref, approver, flagged
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_case_payment')
WHERE case_id = :case_id
ORDER BY payment_date DESC, payment_id
