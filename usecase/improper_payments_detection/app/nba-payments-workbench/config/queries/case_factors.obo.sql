-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- @param case_id STRING = IP-2048
SELECT rank, factor_code, title, detail, contribution, source
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_case_factor')
WHERE case_id = :case_id
ORDER BY rank
