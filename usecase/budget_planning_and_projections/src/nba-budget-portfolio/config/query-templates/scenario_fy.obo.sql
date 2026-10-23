-- @param data_version STRING
SELECT
  comparison.scenario_id,
  comparison.financial_year,
  comparison.fy,
  comparison.forecast_aud_m,
  comparison.baseline_forecast_aud_m,
  comparison.delta_vs_baseline_aud_m,
  comparison.peak_utilisation_pct,
  comparison.capacity_breaches,
  comparison.status,
  capacity.capacity_aud_m,
  capacity.envelope_aud_m,
  capacity.forecast_p10_aud_m,
  capacity.forecast_p90_aud_m
FROM {{schema}}.scenario_comparison comparison
LEFT JOIN {{schema}}.portfolio_capacity_fy capacity USING (scenario_id, fy, financial_year)
WHERE :data_version IS NOT NULL
ORDER BY comparison.scenario_id, comparison.fy;
