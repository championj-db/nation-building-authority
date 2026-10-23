SELECT
  scenario_id,
  scenario_name,
  version,
  method,
  status,
  horizon_label,
  total_forecast_aud_m,
  total_forecast_real_aud_m,
  vs_baseline_aud_m,
  headroom_aud_m,
  within_envelope,
  forecast_confidence_pct,
  capacity_breaches,
  breaches_resolved_vs_baseline,
  peak_utilisation_pct,
  peak_category,
  peak_financial_year,
  projects_changed,
  regional_completions_deferred
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.scenario_summary
ORDER BY CASE scenario_id WHEN 'BASE' THEN 1 WHEN 'CAP_BAL' THEN 2 WHEN 'ACCEL' THEN 3 ELSE 4 END;
