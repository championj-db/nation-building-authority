-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- @param case_id STRING = IP-2048
SELECT node_id, label, kind, sub_label, role
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_case_graph_node')
WHERE case_id = :case_id
ORDER BY role, node_id
