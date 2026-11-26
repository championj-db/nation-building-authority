-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- Synthetic triage history (cases closed before this queue), aggregated the same way the app
-- aggregates outcomes recorded in the workbench, so the two can be shown side by side.
SELECT primary_signal, primary_signal_label, risk_band, outcome, count(*) AS decided,
       CAST(max(decided_ts) AS STRING) AS last_decided_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_outcome_history')
GROUP BY primary_signal, primary_signal_label, risk_band, outcome
