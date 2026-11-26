-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- @param case_id STRING = IP-2048
SELECT src, dst, relation
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_case_graph_edge')
WHERE case_id = :case_id
ORDER BY src, dst
