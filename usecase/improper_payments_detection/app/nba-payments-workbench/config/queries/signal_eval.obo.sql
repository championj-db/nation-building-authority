-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- Model evaluation per primary signal against the seeded ground truth (synthetic only).
SELECT primary_signal, primary_signal_label, cases, true_improper, precision
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_signal_eval')
ORDER BY cases DESC, primary_signal
