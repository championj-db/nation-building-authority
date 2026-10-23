# Databricks notebook source
# MAGIC %md
# MAGIC # 06 Variance reporting and app-facing gold
# MAGIC
# MAGIC Explains the gap between **plan, forecast and actual** and publishes the summary tables behind the
# MAGIC Portfolio Command Centre screens.
# MAGIC
# MAGIC * `variance_bridge` - driver attribution (Escalation, Schedule shift, Scope change, Packaging,
# MAGIC   Unexplained) at portfolio / sector / program / project level for YTD, current FY and the horizon.
# MAGIC   Drivers are differences between consecutive forecast stages, so they always sum exactly to
# MAGIC   forecast minus plan. *Unexplained* is what no recorded driver accounts for and needs attribution.
# MAGIC * `variance_project` - plan / forecast / actual, tolerance test, drivers and attention flags.
# MAGIC * `portfolio_attention_list`, `priority_exceptions` - ranked program exposure.
# MAGIC * `portfolio_kpis` - headline figures per scenario.
# MAGIC * `assurance_register` - assumptions and Gateway reviews with owner, confidence and approval.
# MAGIC * `forecast_runs` - append-only record of the run and every input version it used.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("tolerance_pct", "5")
dbutils.widgets.text("tolerance_floor_aud_m", "25")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

ctx = run_context()
run_id, T0, H0, HORIZON = ctx["current_run_id"], ctx["t0"], ctx["h0"], ctx["horizon"]
TOL_PCT = float(dbutils.widgets.get("tolerance_pct")) / 100.0
TOL_FLOOR = float(dbutils.widgets.get("tolerance_floor_aud_m"))
GOLD = {"nba_layer": "gold"}


def gold(t: str, scenario: str = None) -> pd.DataFrame:
    df = spark.table(table_name(t))
    if "run_id" in df.columns:
        df = df.filter(F.col("run_id") == run_id)
    if scenario and "scenario_id" in df.columns:
        df = df.filter(F.col("scenario_id") == scenario)
    return df.toPandas()


stages = gold("forecast_stages_monthly")
proj = gold("dim_project").set_index("project_id")
exposure = gold("capacity_exposure", "BASE")
cap_demand = gold("capacity_demand")
summary = gold("scenario_summary").set_index("scenario_id")
port_cap = gold("portfolio_capacity_fy")
confidence = gold("project_confidence")
changes = spark.table(table_name("silver_change_register")).toPandas()
stages["m"] = stages.month.map(month_idx)
STAGE_COLS = ["plan_aud_m", "schedule_aud_m", "escalation_aud_m", "scope_aud_m", "packaging_aud_m", "forecast_aud_m", "actual_aud_m"]
PERIODS = {
    "YTD": (stages.fy == H0) & (stages.m < T0),
    "CURRENT_FY": stages.fy == H0,
    "HORIZON": stages.fy.isin(HORIZON),
}
PERIOD_LABEL = {"YTD": f"{fy_label(H0)} YTD to {month_end(T0 - 1):%b %Y}", "CURRENT_FY": fy_label(H0),
                "HORIZON": f"{fy_label(HORIZON[0])}-{fy_label(HORIZON[-1])}"}
DRIVERS = [("Escalation", "escalation_aud_m", "schedule_aud_m"), ("Schedule shift", "schedule_aud_m", "plan_aud_m"),
           ("Scope change", "scope_aud_m", "escalation_aud_m"), ("Packaging", "packaging_aud_m", "scope_aud_m"),
           ("Unexplained", "forecast_aud_m", "packaging_aud_m")]
base_conf = confidence[confidence.scenario_id == "BASE"].set_index("project_id").confidence_pct

# COMMAND ----------

# MAGIC %md
# MAGIC ## Variance by project and driver bridge

# COMMAND ----------

vp_rows, bridge_rows = [], []
per = {}
for pk, mask in PERIODS.items():
    agg = stages[mask].groupby("project_id")[STAGE_COLS].sum().reindex(proj.index, fill_value=0.0)
    for name, hi, lo in DRIVERS:
        agg[name] = agg[hi] - agg[lo]
    per[pk] = agg
    floor = TOL_FLOOR * (2 if pk == "HORIZON" else 1)
    for pid, r in agg.iterrows():
        var = r.forecast_aud_m - r.plan_aud_m
        tol = max(TOL_PCT * r.plan_aud_m, floor)
        drivers = {name: r[name] for name, _, _ in DRIVERS}
        primary = max(drivers, key=lambda k: abs(drivers[k])) if any(abs(v) > 1e-6 for v in drivers.values()) else None
        p = proj.loc[pid]
        vp_rows.append(dict(period=pk, period_label=PERIOD_LABEL[pk], project_id=pid, project_name=p.project_name, program_id=p.program_id,
                            program_name=p.program_name, sector=p.sector, plan_aud_m=r.plan_aud_m, forecast_aud_m=r.forecast_aud_m,
                            actual_aud_m=r.actual_aud_m, variance_aud_m=var, variance_pct=(var / r.plan_aud_m * 100) if r.plan_aud_m else None,
                            tolerance_aud_m=tol, outside_tolerance=bool(abs(var) > tol),
                            escalation_aud_m=drivers["Escalation"], schedule_shift_aud_m=drivers["Schedule shift"],
                            scope_change_aud_m=drivers["Scope change"], packaging_aud_m=drivers["Packaging"],
                            unexplained_aud_m=drivers["Unexplained"], primary_driver=primary, slip_months=int(p.slip_months),
                            gateway_rating=p.gateway_rating, confidence_pct=float(base_conf.get(pid, np.nan))))
    groups = {"portfolio": pd.Series("PORTFOLIO", index=proj.index), "sector": proj.sector, "program": proj.program_id, "project": pd.Series(proj.index, index=proj.index)}
    names = {"portfolio": lambda k: "National portfolio", "sector": lambda k: k,
             "program": lambda k: proj[proj.program_id == k].program_name.iloc[0], "project": lambda k: proj.loc[k, "project_name"]}
    for level, key in groups.items():
        g = agg.groupby(key)
        for k, r in g.sum().iterrows():
            for order, (name, _, _) in enumerate(DRIVERS, 1):
                bridge_rows.append(dict(period=pk, period_label=PERIOD_LABEL[pk], scope_level=level, scope_id=k, scope_name=names[level](k),
                                        driver=name, driver_order=order, amount_aud_m=r[name], plan_aud_m=r.plan_aud_m,
                                        forecast_aud_m=r.forecast_aud_m))

vp = pd.DataFrame(vp_rows)
# Executive attention: at least two of - material cost growth (outside tolerance and > 10%), poor assurance,
# long slip, or a material share of a breached input.
exp_h = exposure[exposure.utilisation_pct > 100].groupby("project_id").agg(max_gap_share=("share_of_demand_pct", "max"),
                                                                         gap_value_aud_m=("gap_value_aud_m", "sum"))
h = vp[vp.period == "HORIZON"].set_index("project_id")
reasons = {}
for pid, r in h.iterrows():
    rs = []
    if r.outside_tolerance and r.variance_aud_m > 0 and (r.variance_pct or 0) > 10:
        rs.append("Cost growth outside tolerance")
    if proj.loc[pid, "gateway_rating_rank"] >= 4:
        rs.append(f"Gateway {proj.loc[pid, 'gateway_rating']}")
    if r.slip_months >= 9:
        rs.append(f"Schedule slip {r.slip_months} months")
    if pid in exp_h.index and exp_h.loc[pid, "max_gap_share"] >= 5:
        rs.append("Material share of a capacity breach")
    reasons[pid] = "; ".join(rs)
vp["attention_reasons"] = vp.project_id.map(reasons)
vp["requires_attention"] = vp.attention_reasons.map(lambda s_: len([x for x in (s_ or "").split("; ") if x]) >= 2)
vp["run_id"] = run_id
write_table(vp, "variance_project", "Plan vs forecast vs actual by project for YTD, the current FY and the five-year horizon, with tolerance test, driver attribution and executive-attention flags (Working baseline).",
            {"period": "YTD (current FY to the last closed month), CURRENT_FY, or HORIZON (five years).",
             "tolerance_aud_m": "Reporting tolerance: max(5% of plan, $25m per year / $50m over the horizon).",
             "unexplained_aud_m": "Variance not explained by any recorded driver (cost performance and actuals timing); needs attribution.",
             "primary_driver": "Driver with the largest absolute contribution to the variance.",
             "requires_attention": "True when two or more executive-attention rules fire (see attention_reasons)."}, tags=GOLD)
bridge = pd.DataFrame(bridge_rows)
bridge["run_id"] = run_id
write_table(bridge, "variance_bridge", "Variance bridge: forecast minus endorsed plan attributed to Escalation, Schedule shift, Scope change, Packaging and Unexplained, by period and scope level. Drivers sum to forecast - plan.",
            {"scope_level": "portfolio | sector | program | project.", "amount_aud_m": "Driver contribution, AUD m (positive increases the forecast).",
             "driver_order": "Display order of the driver in the bridge."}, tags=GOLD)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Program attention list and priority exceptions

# COMMAND ----------

RANK_NAME = {1: "Green", 2: "Amber/Green", 3: "Amber", 4: "Amber/Red", 5: "Red"}
SHORT = {"Skilled civil labour": "Labour constraint", "Electrical equipment": "Long-lead equipment", "Concrete": "Concrete supply"}
constrained = exposure[exposure.utilisation_pct >= 90]
hz = vp[vp.period == "HORIZON"]
att_rows, exc_rows = [], []
for prog_id, g in hz.groupby("program_id"):
    pids = list(g.project_id)
    pe = exposure[exposure.program_id == prog_id]
    gap_by_cat = pe.groupby("capacity_category").gap_value_aud_m.sum()
    if len(gap_by_cat) and gap_by_cat.max() > 0.5:
        driver = gap_by_cat.idxmax()
    else:
        c = constrained[constrained.program_id == prog_id].groupby("capacity_category").share_of_demand_pct.sum()
        driver = c.idxmax() if len(c) else pe.groupby("capacity_category").share_of_demand_pct.sum().idxmax()
    gap_fy = pe[pe.capacity_category == driver].groupby("financial_year").gap_value_aud_m.sum()
    peak_fy = gap_fy.idxmax() if len(gap_fy) and gap_fy.max() > 0 else None
    plan_, fc_ = g.plan_aud_m.sum(), g.forecast_aud_m.sum()
    var = fc_ - plan_
    tol = max(TOL_PCT * plan_, 2 * TOL_FLOOR)
    worst = int(proj.loc[pids, "gateway_rating_rank"].max())
    w_ = proj.loc[pids, "eac_forecast_aud_m"]
    typical = int(np.clip(round(float((proj.loc[pids, "gateway_rating_rank"] * w_).sum() / w_.sum())), 1, 5))
    conf = float((g.confidence_pct * g.forecast_aud_m).sum() / max(g.forecast_aud_m.sum(), 1e-9))
    slip = int(g.slip_months.max())
    unexpl = g.unexplained_aud_m.sum()
    pname = g.program_name.iloc[0]
    att_rows.append(dict(program_id=prog_id, program_name=pname, sector=g.sector.iloc[0], projects=len(pids),
                         assurance_rating=RANK_NAME[typical], assurance_rank=typical, worst_gateway_rating=RANK_NAME[worst], plan_aud_m=plan_, forecast_aud_m=fc_, variance_aud_m=var,
                         variance_pct=var / plan_ * 100 if plan_ else None, outside_tolerance=bool(abs(var) > tol), capacity_driver=driver,
                         capacity_gap_aud_m=float(gap_by_cat.sum()) if len(gap_by_cat) else 0.0, max_slip_months=slip, confidence_pct=conf,
                         attention_projects=int(g.requires_attention.sum()),
                         requires_attention=bool(g.requires_attention.any() or typical >= 4)))
    sched_reason = changes[(changes.project_id.isin(pids)) & (changes.change_type == "Schedule") & (changes.status == "Approved")].description
    pack = changes[(changes.project_id.isin(pids)) & (changes.change_type == "Packaging") & (changes.status == "Approved")]
    if var > tol:
        what = SHORT.get(driver, f"{driver} constraint") if (len(gap_by_cat) and gap_by_cat.max() > 0.5) else g.groupby("primary_driver").variance_aud_m.sum().idxmax()
        exc_rows.append(dict(program_id=prog_id, program_name=pname, exception_type="Cost growth", delta_value=var, delta_unit="AUD m",
                             description=" · ".join(x for x in [what, peak_fy, f"confidence {conf:.0f}%"] if x), score=abs(var) + (gap_by_cat.sum() if len(gap_by_cat) else 0) * 0.25))
    if slip >= 9:
        reason = sched_reason.mode().iloc[0] if len(sched_reason) else "Approved schedule change"
        exc_rows.append(dict(program_id=prog_id, program_name=pname, exception_type="Schedule slip", delta_value=float(slip), delta_unit="months",
                             description=f"{reason} · Gateway {RANK_NAME[typical].lower()}", score=slip * 120.0))
    if var < -max(0.4 * TOL_PCT * plan_, 2 * TOL_FLOOR):  # savings are reported at the tighter tolerance
        exc_rows.append(dict(program_id=prog_id, program_name=pname, exception_type="Saving", delta_value=var, delta_unit="AUD m",
                             description=(pack.description.iloc[0] + " reduces peak demand") if len(pack) else "Forecast below plan",
                             score=abs(var) * 0.8))
    # Unexplained variance has a tighter tolerance (40% of the cost tolerance): it has no recorded cause.
    if abs(unexpl) > max(0.4 * TOL_PCT * plan_, 2 * TOL_FLOOR):
        exc_rows.append(dict(program_id=prog_id, program_name=pname, exception_type="Unexplained variance", delta_value=unexpl, delta_unit="AUD m",
                             description="Forecast variance outside tolerance - not explained by recorded drivers", score=abs(unexpl) * 1.5))
    if typical >= 4 and not any(e["program_id"] == prog_id for e in exc_rows):
        exc_rows.append(dict(program_id=prog_id, program_name=pname, exception_type="Assurance", delta_value=None, delta_unit=None,
                             description=f"Gateway {RANK_NAME[typical]} · confidence {conf:.0f}%", score=300.0))

att = pd.DataFrame(att_rows).sort_values(["requires_attention", "variance_aud_m"], ascending=[False, False])
att["rank"] = range(1, len(att) + 1)
att["run_id"] = run_id
write_table(att, "portfolio_attention_list", "Program attention list (Working baseline, horizon): plan vs forecast, worst Gateway rating, capacity driver, slip and confidence, ranked by exposure.",
            {"assurance_rating": "Program Gateway rating: forecast-weighted average of its projects' latest ratings.",
             "worst_gateway_rating": "Worst latest Gateway rating among the program's projects.",
             "capacity_driver": "Delivery input contributing most to the program's capacity gap (or its most constrained input).",
             "capacity_gap_aud_m": "Program's attributed share of capacity gaps across the horizon, AUD m."}, tags=GOLD)
exc = pd.DataFrame(exc_rows).sort_values("score", ascending=False)
exc["rank"] = range(1, len(exc) + 1)
exc["exception_id"] = [f"EXC-{i:03d}" for i in exc["rank"]]
exc["status"] = "Open"
exc["run_id"] = run_id
write_table(exc, "priority_exceptions", "Priority exceptions ranked by financial and delivery exposure (Working baseline): cost growth, schedule slip, savings, unexplained variance and assurance.",
            {"delta_value": "Size of the exception in delta_unit (AUD m or months).", "score": "Exposure score used for ranking."}, tags=GOLD)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Headline KPIs per scenario

# COMMAND ----------

cur, ytd, hor = per["CURRENT_FY"], per["YTD"], per["HORIZON"]
active = hor[hor.forecast_aud_m > 0.5].index
slip_w = float((proj.loc[active, "slip_months"] * hor.loc[active, "forecast_aud_m"]).sum() / hor.loc[active, "forecast_aud_m"].sum())
endorsed_total = float(hor.plan_aud_m.sum())
gap = port_cap.pivot_table(index="fy", columns="scenario_id", values="capacity_gap_aud_m", aggfunc="sum")
# Gap removed in the baseline's peak-gap year by capacity-aware sequencing (no scope removed).
resolvable = (float(gap["BASE"].max() - gap.loc[gap["BASE"].idxmax(), "CAP_BAL"])
              if "CAP_BAL" in gap.columns and gap["BASE"].max() > 0 else None)
kpi_rows = []
for sid, s in summary.iterrows():
    cd = cap_demand[cap_demand.scenario_id == sid]
    peak_row = cd.loc[cd.utilisation_pct.idxmax()]
    peak_cells = cd[cd.financial_year == peak_row.financial_year]
    breached = cd[cd.utilisation_pct > 100]
    ex = gold("capacity_exposure", sid)
    ex = ex.merge(breached[["fy", "category_id"]], on=["fy", "category_id"])
    ex = ex[ex.heavy_user & (ex.share_of_demand_pct >= 2)]
    kpi_rows.append(dict(
        scenario_id=sid, scenario_name=s.scenario_name, horizon_label=s.horizon_label,
        approved_portfolio_aud_m=s.total_forecast_aud_m, approved_portfolio_real_aud_m=s.total_forecast_real_aud_m,
        endorsed_plan_aud_m=endorsed_total, vs_endorsed_plan_aud_m=s.total_forecast_aud_m - endorsed_total,
        peak_capacity_gap_aud_m=s.peak_gap_aud_m, peak_capacity_gap_fy=s.peak_gap_financial_year,
        active_projects=int(len(active)), attention_projects=int(vp[(vp.period == "HORIZON") & vp.requires_attention].shape[0]),
        forecast_confidence_pct=s.forecast_confidence_pct, capacity_breaches=int(s.capacity_breaches),
        constrained_categories_peak_fy=int((peak_cells.utilisation_pct >= 90).sum()), capacity_categories=int(peak_cells.shape[0]),
        peak_demand_capacity_pct=float(peak_row.utilisation_pct), peak_category=peak_row.capacity_category, peak_fy=peak_row.financial_year,
        projects_affected=int(ex.project_id.nunique()), programs_affected=int(ex.program_id.nunique()),
        resolvable_by_sequencing_aud_m=resolvable,
        ytd_actual_aud_m=float(ytd.actual_aud_m.sum()), ytd_plan_aud_m=float(ytd.plan_aud_m.sum()),
        current_fy_label=fy_label(H0), current_fy_forecast_aud_m=float(cur.forecast_aud_m.sum()), current_fy_plan_aud_m=float(cur.plan_aud_m.sum()),
        schedule_variance_months=slip_w, current_fy_unexplained_aud_m=float(cur["Unexplained"].sum()),
        as_of_date=date.fromisoformat(ctx["forecast_as_of"]), actuals_through=date.fromisoformat(ctx["actuals_through"]),
        plan_version=ctx["plan_version"], capacity_model_version=get_control("capacity_model_version"),
        figure_status="Working", refreshed_at=datetime.now(timezone.utc)))
kpis = pd.DataFrame(kpi_rows)
kpis["run_id"] = run_id
write_table(kpis, "portfolio_kpis", "Headline portfolio KPIs per scenario for the command centre (overview, capacity and variance cards). One row per scenario; variance KPIs are from the Working baseline.",
            {"approved_portfolio_aud_m": "Forecast expenditure over the horizon for the scenario, AUD m nominal.",
             "peak_capacity_gap_aud_m": "Largest annual capacity gap in the horizon, AUD m.",
             "resolvable_by_sequencing_aud_m": "Baseline peak-year capacity gap removed by Capacity balanced sequencing without removing scope, AUD m.",
             "projects_affected": "Projects that are heavy users holding >= 2% of demand for an input in a breached year.",
             "schedule_variance_months": "Forecast-weighted average approved slip, months.",
             "current_fy_unexplained_aud_m": "Current-FY variance not explained by recorded drivers, AUD m."}, tags=GOLD)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assurance register and run record

# COMMAND ----------

assump = spark.table(table_name("silver_assumptions")).toPandas()
reg = assump.rename(columns={"assumption_id": "record_id", "title": "record", "assumption_type": "record_type"})[
    ["record_id", "record", "record_type", "owner", "confidence", "approval_status", "version", "last_reviewed", "next_review_due",
     "evidence_reference", "value_summary"]]
rv = spark.table(table_name("silver_gateway_reviews")).filter("is_latest").toPandas().merge(
    proj[["program_id", "program_name"]].reset_index(), on="project_id")
worst_rv = rv.assign(rank=rv.delivery_confidence.map({v: k for k, v in RANK_NAME.items()})).sort_values(["rank", "report_date"], ascending=False).groupby("program_id").head(1)
CONF = {1: "High", 2: "Medium", 3: "Medium", 4: "Low", 5: "Low"}
reg_rv = pd.DataFrame(dict(
    record_id=worst_rv.review_id, record=worst_rv.program_name, record_type=worst_rv.gate.map(lambda g_: f"Gateway {g_} review"),
    owner="Program Executive", confidence=worst_rv["rank"].map(CONF),
    approval_status=worst_rv["rank"].map(lambda r_: "Action required" if r_ >= 4 else ("Awaiting attestation" if r_ == 3 else "Endorsed")),
    version=1, last_reviewed=worst_rv.report_date, next_review_due=worst_rv.report_date.map(lambda d_: d_ + timedelta(days=180)),
    evidence_reference=worst_rv.review_id, value_summary=worst_rv.delivery_confidence + " - " + worst_rv.summary))
register = pd.concat([reg, reg_rv], ignore_index=True).sort_values("last_reviewed", ascending=False)
register["run_id"] = run_id
write_table(register, "assurance_register", "Assumption and assurance register: material forecast inputs and the latest program Gateway reviews with owner, confidence, approval status and review dates.",
            {"approval_status": "Endorsed | Working | Awaiting attestation | Action required."}, tags=GOLD)

versions = dict(zip(assump.assumption_id, assump.version.astype(int)))
scen = spark.table(table_name("dim_scenario")).filter(F.col("run_id") == run_id).select("scenario_id", "version").toPandas()
params = {k: get_control(k) for k in ("horizon_years", "performance_window_months", "world_anchor_date", "seed")}
params.update(tolerance_pct=TOL_PCT * 100, tolerance_floor_aud_m=TOL_FLOOR)
run_row = spark.createDataFrame([(
    run_id, ctx["run_type"], date.fromisoformat(ctx["forecast_as_of"]), date.fromisoformat(ctx["actuals_through"]), month_start(T0),
    H0, HORIZON[-1], ctx["plan_version"], get_control("capacity_model_version"), json.dumps(versions, sort_keys=True),
    json.dumps(dict(zip(scen.scenario_id, scen.version.astype(int))), sort_keys=True), json.dumps(params, sort_keys=True),
    datetime.fromisoformat(get_control("run_started_at")), datetime.now(timezone.utc).replace(tzinfo=None), "completed")],
    spark.table(table_name("forecast_runs")).schema)
# forecast_runs is append-only: record each run once (a re-run of this task for the same run is a no-op).
if spark.table(table_name("forecast_runs")).filter(F.col("run_id") == run_id).limit(1).count() == 0:
    run_row.write.mode("append").saveAsTable(table_name("forecast_runs"))
k = kpis.set_index("scenario_id").loc["BASE"]
print(f"run {run_id}: portfolio ${k.approved_portfolio_aud_m / 1000:.1f}bn ({k.vs_endorsed_plan_aud_m / 1000:+.1f}bn vs endorsed), "
      f"peak gap ${k.peak_capacity_gap_aud_m / 1000:.1f}bn {k.peak_capacity_gap_fy}, {k.active_projects} active, {k.attention_projects} need attention, "
      f"confidence {k.forecast_confidence_pct:.0f}%; {len(exc)} exceptions; register {len(register)} records")
