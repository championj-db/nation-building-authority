-- @param cycle STRING
-- @param data_version STRING
-- Current state of each program's monthly forecast submission (latest event wins).
WITH latest AS (
  SELECT * FROM (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY program_id ORDER BY created_at DESC) AS rn
    FROM {{schema}}.forecast_submissions s
    WHERE cycle = :cycle
  ) WHERE rn = 1
), submitted AS (
  SELECT * FROM (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY program_id ORDER BY created_at DESC) AS rn
    FROM {{schema}}.forecast_submissions s
    WHERE cycle = :cycle AND status = 'Submitted'
  ) WHERE rn = 1
), events AS (
  SELECT program_id, COUNT(*) AS events FROM {{schema}}.forecast_submissions WHERE cycle = :cycle GROUP BY program_id
)
SELECT
  attention.program_id,
  attention.program_name,
  attention.sector,
  program.delivery_agency,
  program.program_executive,
  attention.plan_aud_m,
  attention.forecast_aud_m,
  attention.variance_aud_m,
  attention.outside_tolerance,
  attention.assurance_rating,
  attention.requires_attention,
  COALESCE(latest.status, 'Not submitted') AS status,
  latest.actor AS status_actor,
  latest.actor_role AS status_role,
  latest.created_at AS status_at,
  latest.commentary AS status_note,
  submitted.commentary AS submission_commentary,
  submitted.actor AS submitted_by,
  submitted.created_at AS submitted_at,
  submitted.forecast_aud_m AS submitted_forecast_aud_m,
  COALESCE(events.events, 0) AS events
FROM {{schema}}.portfolio_attention_list attention
JOIN {{schema}}.dim_program program ON program.program_id = attention.program_id
LEFT JOIN latest ON latest.program_id = attention.program_id
LEFT JOIN submitted ON submitted.program_id = attention.program_id
LEFT JOIN events ON events.program_id = attention.program_id
WHERE :data_version IS NOT NULL
ORDER BY CASE COALESCE(latest.status, 'Not submitted') WHEN 'Submitted' THEN 1 WHEN 'Returned' THEN 2 WHEN 'Not submitted' THEN 3 WHEN 'Approved' THEN 4 ELSE 5 END,
  attention.rank;
