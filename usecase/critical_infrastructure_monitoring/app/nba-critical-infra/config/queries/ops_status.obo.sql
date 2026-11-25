-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Headline operating picture: the latest risk-engine run, feed freshness and processing lag.
-- processing_lag_seconds = time from the newest bronze ingest to the gold scoring run.
WITH runs AS (
  -- previous run's figures ride along so each KPI shows a comparison, not a bare number
  SELECT *,
    lead(open_alerts) OVER (ORDER BY run_ts DESC) AS prev_open_alerts,
    lead(median_queue_time_minutes) OVER (ORDER BY run_ts DESC) AS prev_median_queue_time_minutes,
    lead(run_ts) OVER (ORDER BY run_ts DESC) AS prev_run_ts
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_ops_metrics')
),
latest_run AS (
  SELECT * FROM runs ORDER BY run_ts DESC LIMIT 1
),
feed AS (
  SELECT max(_ingest_ts) AS latest_ingest_ts
  FROM IDENTIFIER(:catalog || '.' || :schema || '.bronze_sightings')
),
sightings AS (
  SELECT max(event_ts) AS latest_sighting_ts
  FROM IDENTIFIER(:catalog || '.' || :schema || '.silver_sighting')
  WHERE event_ts <= current_timestamp()
)
SELECT
  r.run_ts,
  r.as_of_date,
  r.sightings_today,
  r.identity_resolution_rate,
  r.median_queue_time_minutes,
  r.risk_signals_last_8h,
  r.open_alerts AS run_open_alerts,
  r.prev_open_alerts,
  r.prev_median_queue_time_minutes,
  r.prev_run_ts,
  s.latest_sighting_ts,
  f.latest_ingest_ts,
  greatest(0, unix_timestamp(r.run_ts) - unix_timestamp(f.latest_ingest_ts)) AS processing_lag_seconds,
  round((unix_timestamp(current_timestamp()) - unix_timestamp(r.run_ts)) / 60.0, 0) AS minutes_since_run
FROM latest_run r CROSS JOIN feed f CROSS JOIN sightings s
WHERE length(:refresh) >= 0
