-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- The open review queue: every case the pipeline scored at or above the case threshold.
-- Case state (assigned, closed) is overlaid by the app from Lakebase; this is the governed list.
SELECT case_id, entity_id, entity_label, entity_sub, entity_kind, program, program_label,
       primary_signal, primary_signal_label, risk_score, risk_band, payment_value, payment_count,
       CAST(opened_date AS STRING) AS opened_date,
       datediff(current_date(), opened_date) AS age_days,
       model_version, CAST(scored_ts AS STRING) AS scored_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_case')
ORDER BY risk_score DESC, payment_value DESC, case_id
