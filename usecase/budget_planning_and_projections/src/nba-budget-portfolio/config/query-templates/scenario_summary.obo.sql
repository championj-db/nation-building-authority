-- @param data_version STRING
-- Every non-archived scenario at its latest saved version, joined to the most recent computed results.
-- A scenario saved in the app shows as pending until the budget_forecast run that includes it completes.
WITH latest_def AS (
  SELECT * FROM (
    SELECT d.*, ROW_NUMBER() OVER (PARTITION BY scenario_id ORDER BY version DESC) AS rn
    FROM {{schema}}.scenario_definitions d
    WHERE status <> 'Archived'
  ) WHERE rn = 1
), workflow AS (
  SELECT scenario_id, scenario_version, event, note, actor, created_at FROM (
    SELECT e.*, ROW_NUMBER() OVER (PARTITION BY scenario_id ORDER BY created_at DESC) AS rn
    FROM {{schema}}.scenario_events e
    WHERE event IN ('Submitted', 'Returned', 'Endorsed')
  ) WHERE rn = 1
), recompute AS (
  SELECT scenario_id, job_run_id, created_at FROM (
    SELECT e.*, ROW_NUMBER() OVER (PARTITION BY scenario_id ORDER BY created_at DESC) AS rn
    FROM {{schema}}.scenario_events e
    WHERE job_run_id IS NOT NULL
  ) WHERE rn = 1
)
SELECT
  d.scenario_id,
  d.scenario_name,
  d.version AS latest_version,
  s.version AS computed_version,
  (s.version IS NULL OR s.version < d.version) AS pending_recompute,
  d.method,
  d.base_scenario_id,
  d.decision_purpose,
  d.description,
  d.created_by,
  d.created_at,
  d.source,
  CASE WHEN w.scenario_version = d.version THEN w.event ELSE d.status END AS workflow_status,
  w.actor AS workflow_actor,
  w.created_at AS workflow_at,
  w.note AS workflow_note,
  r.job_run_id AS last_job_run_id,
  s.horizon_label,
  s.total_forecast_aud_m,
  s.vs_baseline_aud_m,
  s.envelope_aud_m,
  s.headroom_aud_m,
  s.within_envelope,
  s.forecast_confidence_pct,
  s.capacity_breaches,
  s.constrained_cells,
  s.breaches_resolved_vs_baseline,
  s.peak_utilisation_pct,
  s.peak_category,
  s.peak_financial_year,
  s.peak_gap_aud_m,
  s.peak_gap_financial_year,
  s.projects_changed,
  s.regional_completions_deferred,
  s.optimizer_deferrals,
  s.levers,
  s.spend_beyond_horizon_aud_m,
  s.indicative_delay_cost_aud_m,
  s.completions_beyond_horizon,
  s.forecast_p10_aud_m,
  s.forecast_p50_aud_m,
  s.forecast_p90_aud_m,
  s.run_id
FROM latest_def d
LEFT JOIN {{schema}}.scenario_summary s USING (scenario_id)
LEFT JOIN workflow w USING (scenario_id)
LEFT JOIN recompute r USING (scenario_id)
WHERE :data_version IS NOT NULL
ORDER BY CASE d.scenario_id WHEN 'BASE' THEN 1 WHEN 'ENDORSED' THEN 2 WHEN 'CAP_BAL' THEN 3 WHEN 'ACCEL' THEN 4 ELSE 5 END, d.created_at DESC;
