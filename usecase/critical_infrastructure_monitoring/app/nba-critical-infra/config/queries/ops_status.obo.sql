-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Headline operating picture: the latest risk-engine run, feed health and processing lag, with the
-- previous run's figures so each KPI carries a comparison.
WITH runs AS (
  SELECT *,
    lead(open_incidents) OVER (ORDER BY run_ts DESC) AS prev_open_incidents,
    lead(sensors_reporting) OVER (ORDER BY run_ts DESC) AS prev_sensors_reporting,
    lead(median_detection_minutes) OVER (ORDER BY run_ts DESC) AS prev_median_detection_minutes
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_ops_metrics')
)
SELECT
  run_ts, open_incidents, extreme_incidents, readings_today, sensors_reporting, sensors_total,
  median_lateness_minutes, late_readings, quarantine_rate, median_detection_minutes, active_hazards,
  latest_reading_ts, latest_ingest_ts, model_version,
  prev_open_incidents, prev_sensors_reporting, prev_median_detection_minutes,
  greatest(0, unix_timestamp(run_ts) - unix_timestamp(latest_ingest_ts)) AS processing_lag_seconds,
  round((unix_timestamp(current_timestamp()) - unix_timestamp(run_ts)) / 60.0, 0) AS minutes_since_run
FROM runs
WHERE length(:refresh) >= 0
ORDER BY run_ts DESC
LIMIT 1
