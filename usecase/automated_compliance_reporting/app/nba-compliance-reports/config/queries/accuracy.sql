-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
SELECT method, labelled_items, correct, accuracy, evaluated_at, notes
FROM IDENTIFIER(:catalog || '.' || :schema || '.mapping_evaluation')
WHERE run_id = (SELECT max_by(run_id, evaluated_at) FROM IDENTIFIER(:catalog || '.' || :schema || '.mapping_evaluation'))
ORDER BY CASE method WHEN 'resolved' THEN 1 WHEN 'rule' THEN 2 WHEN 'ai' THEN 3 WHEN 'ai_confident' THEN 4 WHEN 'human' THEN 5 ELSE 6 END;
