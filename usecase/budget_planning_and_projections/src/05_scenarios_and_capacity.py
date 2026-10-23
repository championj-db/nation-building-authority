# Databricks notebook source
# MAGIC %md
# MAGIC # 05 Scenarios and capacity analysis
# MAGIC
# MAGIC Constructs every active scenario from data and tests it against the modelled delivery market.
# MAGIC
# MAGIC **Scenarios** (`scenario_definitions` + `scenario_levers`, latest non-archived version of each):
# MAGIC
# MAGIC | Method | Construction |
# MAGIC | --- | --- |
# MAGIC | `plan` | Endorsed plan phasing (reference) |
# MAGIC | `as_forecast` | Working baseline forecast from 04 |
# MAGIC | `levers` | Base scenario + explicit levers (defer / accelerate / escalation / scope / exclude / capacity uplift) |
# MAGIC | `auto_sequence` | `levers`, then a greedy capacity-aware sequencer that defers *Deferrable* work - lowest priority and largest contributor first - until no input category exceeds 100% of capacity or nothing more can move |
# MAGIC
# MAGIC **Capacity.** Annual demand for each of the 12 inputs = project spend x subsector demand intensity.
# MAGIC Utilisation = demand / modelled available supply (plus any uplift levers). >= 90% is *Constrained*,
# MAGIC > 100% is a *Breach*. The deliverable-spend line is forecast / peak utilisation; the gap is the
# MAGIC spend the market cannot absorb that year. Project confidence = Gateway-based confidence reduced by
# MAGIC exposure to breached inputs.
# MAGIC
# MAGIC Every number traces to a scenario version, its levers, the capacity model version and the run id.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("sequencing_step_months", "6")
dbutils.widgets.text("max_deferral_months", "24")
dbutils.widgets.text("capacity_confidence_penalty", "1.0")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

ctx = run_context()
run_id, T0, H0, HORIZON = ctx["current_run_id"], ctx["t0"], ctx["h0"], ctx["horizon"]
STEP = int(dbutils.widgets.get("sequencing_step_months"))
MAX_DEFER = int(dbutils.widgets.get("max_deferral_months"))
K_PEN = float(dbutils.widgets.get("capacity_confidence_penalty"))

base_rows = spark.table(table_name("forecast_stages_monthly")).filter(F.col("run_id") == run_id).toPandas()
base = to_paths(base_rows, ["plan_aud_m", "forecast_aud_m", "actual_aud_m"])
proj = spark.table(table_name("dim_project")).toPandas().set_index("project_id")
PIDS = list(proj.index)

defs = spark.table(table_name("scenario_definitions")).toPandas()
defs = defs[defs.status != "Archived"].sort_values("version").groupby("scenario_id").tail(1).set_index("scenario_id")
levers = spark.table(table_name("scenario_levers")).toPandas()
levers = levers.merge(defs[["version"]].reset_index(), left_on=["scenario_id", "scenario_version"], right_on=["scenario_id", "version"])

cats = spark.table(table_name("silver_capacity_categories")).toPandas().set_index("category_id")
cap_all = spark.table(table_name("silver_market_capacity")).toPandas()
cap_version = sorted(cap_all.model_version.unique())[-1]
cap = cap_all[cap_all.model_version == cap_version]
intensity = spark.table(table_name("silver_demand_intensity")).toPandas()
envelope = spark.table(table_name("silver_funding_envelope")).toPandas().set_index("fy").envelope_aud_m
defl = deflator_index(spark.table(table_name("silver_price_deflator")).toPandas(), H0)

# Indicative cost of delay for scenario deferrals: the endorsed delay-cost assumption (% of P50 per month of slip).
_dc = spark.table(table_name("silver_assumptions")).filter("assumption_id = 'DELAY-COST'").select("value_summary").collect()
_dc_pct = next((float(t.rstrip("%")) for t in (_dc[0][0].split() if _dc else []) if t.endswith("%")), 0.25)
DELAY_RATE = _dc_pct / 100.0
N_SIM = 1000
RNG = np.random.default_rng(int(get_control("seed") or 42))
FUTURE = np.arange(N_MONTHS) >= T0

CATS = list(cats.index)
I = np.array([[float(intensity[(intensity.subsector == proj.loc[p, "subsector"]) & (intensity.category_id == c)].units_per_aud_m.sum())
               for c in CATS] for p in PIDS])                                   # P x C units per $m
SUPPLY0 = np.array([[float(cap[(cap.fy == fy) & (cap.category_id == c)].available_units.sum()) for c in CATS] for fy in HORIZON])  # H x C
# "Heavy user" of an input: intensity at or above the median of subsectors that use it at all.
med = np.array([np.median(col[col > 0]) if (col > 0).any() else np.inf for col in I.T])
HEAVY = I >= med
FY_MASKS = [FY_OF_MONTH == fy for fy in HORIZON]
HORIZON_MASK = np.isin(FY_OF_MONTH, HORIZON)
print(f"run {run_id}: {len(defs)} scenarios, capacity model {cap_version}, {len(CATS)} categories")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scenario construction

# COMMAND ----------


def targets(target_type: str, target_id) -> list:
    if target_type == "project":
        return [target_id] if target_id in proj.index else []
    if target_type == "program":
        return list(proj.index[proj.program_id == target_id])
    if target_type == "sector":
        return list(proj.index[proj.sector == target_id])
    if target_type == "portfolio":
        return PIDS
    return []


def apply_levers(paths: dict, lv: pd.DataFrame, notes: dict) -> tuple:
    """Apply levers in a fixed order: timing, escalation, scope, exclusion. Returns (paths, capacity uplift)."""
    paths = {p: a.copy() for p, a in paths.items()}
    uplift = np.zeros(len(CATS))
    order = {"defer_months": 0, "accelerate_months": 0, "escalation_delta_pp": 1, "scope_change_aud_m": 2, "exclude_project": 3,
             "capacity_uplift_pct": 4}
    for l in sorted(lv.itertuples(), key=lambda x: order.get(x.lever_type, 9)):
        if l.lever_type == "capacity_uplift_pct":
            if l.target_id in CATS:
                uplift[CATS.index(l.target_id)] += l.value / 100.0
            continue
        pids = targets(l.target_type, l.target_id)
        fut_total = sum(paths[p][T0:].sum() for p in pids) or 1.0
        for p in pids:
            before = paths[p]
            if l.lever_type in ("defer_months", "accelerate_months"):
                paths[p] = reschedule(before, T0, int(l.value) * (1 if l.lever_type == "defer_months" else -1))
            elif l.lever_type == "escalation_delta_pp":
                extra = np.array([(1 + l.value / 100.0) ** max(0, int(fy) - H0 + 1) for fy in FY_OF_MONTH])
                paths[p] = np.concatenate([before[:T0], before[T0:] * extra[T0:]])
            elif l.lever_type == "scope_change_aud_m":
                paths[p] = before + spread_future(before, T0, l.value * before[T0:].sum() / fut_total)
            elif l.lever_type == "exclude_project":
                paths[p] = np.concatenate([before[:T0], np.zeros(N_MONTHS - T0)])
            notes.setdefault(p, []).append(f"{l.lever_type} {l.value:g} ({l.lever_id})")
    return paths, uplift


def spend_matrix(paths: dict) -> np.ndarray:
    return np.array([[paths[p][m].sum() for m in FY_MASKS] for p in PIDS])  # P x H


def utilisation(paths: dict, uplift: np.ndarray) -> tuple:
    S_ = spend_matrix(paths)
    D = S_.T @ I                                    # H x C demand units
    supply = SUPPLY0 * (1 + uplift)
    return S_, D, supply, D / supply


def overload(U: np.ndarray) -> float:
    return float(np.clip(U - 1.0, 0, None).sum())


def sequence(paths: dict, uplift: np.ndarray, notes: dict) -> tuple:
    """Greedy capacity-aware sequencing of Deferrable work. Returns (paths, decisions)."""
    paths = {p: a.copy() for p, a in paths.items()}
    deferred = {p: 0 for p in PIDS}
    tier_w = {1: 0.5, 2: 1.0, 3: 1.5}
    flexible = np.array([proj.loc[p, "schedule_flexibility"] == "Deferrable" for p in PIDS])
    decisions, stuck = [], set()
    for it in range(200):
        S_, D, supply, U = utilisation(paths, uplift)
        cells = [(U[h, c], h, c) for h in range(len(HORIZON)) for c in range(len(CATS)) if U[h, c] > 1.0 and (h, c) not in stuck]
        if not cells:
            break
        u_, h, c = max(cells)
        contrib = S_[:, h] * I[:, c]
        weight = {p: tier_w.get(int(proj.loc[p, "priority_tier"]), 1.0) for p in PIDS}
        cand = [i for i, p in enumerate(PIDS)
                if flexible[i] and deferred[p] + STEP <= MAX_DEFER and contrib[i] > 0 and paths[p][T0:].sum() > 0]
        cand = sorted(cand, key=lambda i: -contrib[i] * weight[PIDS[i]])[:8]
        # Accept the deferral that removes the most over-utilisation per $ pushed beyond the horizon,
        # and only if it reduces total over-utilisation (no shifting the problem into later years).
        current = overload(U)
        best, best_gain, best_path = None, 1e-9, None
        for i in cand:
            p = PIDS[i]
            trial = dict(paths)
            trial[p] = reschedule(paths[p], T0, STEP)
            moved_out = max(0.0, paths[p][HORIZON_MASK].sum() - trial[p][HORIZON_MASK].sum())
            gain = (current - overload(utilisation(trial, uplift)[3])) * weight[p] / (1 + moved_out / 1000.0)
            if gain > best_gain:
                best, best_gain, best_path = p, gain, trial[p]
        if best is None:
            stuck.add((h, c))
            continue
        paths[best] = best_path
        deferred[best] += STEP
        notes.setdefault(best, []).append(f"optimizer defer {STEP} mo ({fy_label(HORIZON[h])} {cats.loc[CATS[c], 'category_name']} at {u_ * 100:.0f}%)")
        decisions.append(dict(iteration=it + 1, project_id=best, defer_months=STEP, cumulative_defer_months=deferred[best],
                              trigger_fy=HORIZON[h], trigger_financial_year=fy_label(HORIZON[h]), trigger_category_id=CATS[c],
                              trigger_utilisation_pct=round(u_ * 100, 1)))
    return paths, decisions


built, building = {}, set()


def build(sid: str) -> dict:
    if sid in built:
        return built[sid]
    assert sid not in building, f"circular scenario base reference at {sid}"
    building.add(sid)
    d = defs.loc[sid]
    notes, decisions = {}, []
    if d.method == "plan":
        paths, uplift = dict(base["plan_aud_m"]), np.zeros(len(CATS))
    elif d.method == "as_forecast":
        paths, uplift = dict(base["forecast_aud_m"]), np.zeros(len(CATS))
    else:
        parent_id = d.base_scenario_id if isinstance(d.base_scenario_id, str) and d.base_scenario_id in defs.index else "BASE"
        parent = build(parent_id)
        paths, uplift = apply_levers(parent["paths"], levers[levers.scenario_id == sid], notes)
        uplift = uplift + parent["uplift"]
        if d.method == "auto_sequence":
            paths, decisions = sequence(paths, uplift, notes)
    built[sid] = dict(paths=paths, uplift=uplift, notes=notes, decisions=decisions)
    building.discard(sid)
    return built[sid]


for sid in defs.index:
    build(sid)
print("built:", ", ".join(f"{s} ({defs.loc[s].method})" for s in built))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Capacity, exposure and confidence per scenario

# COMMAND ----------

last_h = HORIZON[-1]
horizon_end_idx = month_idx(fy_end(last_h))


def finish_idx(a: np.ndarray):
    nz = np.nonzero(a > 1e-6)[0]
    return int(nz[-1]) if len(nz) else None


monthly, cap_rows, exp_rows, port_rows, conf_rows, summ_rows, cmp_rows, chg_rows, dec_rows = ([] for _ in range(9))
base_built = built["BASE"]
_, _, _, U_base = utilisation(base_built["paths"], base_built["uplift"])
base_fy = spend_matrix(base_built["paths"]).sum(axis=0)

for sid, b in built.items():
    d = defs.loc[sid]
    S_, D, supply, U = utilisation(b["paths"], b["uplift"])
    fy_tot = S_.sum(axis=0)
    # capacity_demand + portfolio deliverable line
    for h, fy in enumerate(HORIZON):
        peak_c = int(np.argmax(U[h]))
        cap_line = fy_tot[h] / U[h, peak_c] if U[h, peak_c] > 0 else None
        plan_fy = sum(base["plan_aud_m"][p][FY_MASKS[h]].sum() for p in PIDS)
        actual_fy = sum(base["actual_aud_m"][p][FY_MASKS[h]].sum() for p in PIDS)
        port_rows.append(dict(scenario_id=sid, fy=fy, financial_year=fy_label(fy), plan_aud_m=plan_fy, forecast_aud_m=fy_tot[h],
                              actual_aud_m=actual_fy, capacity_aud_m=cap_line, capacity_gap_aud_m=max(0.0, fy_tot[h] - (cap_line or 0)),
                              binding_category_id=CATS[peak_c], binding_category=cats.loc[CATS[peak_c], "category_name"],
                              peak_utilisation_pct=U[h, peak_c] * 100, envelope_aud_m=float(envelope.get(fy, np.nan)),
                              plan_real_aud_m=plan_fy / defl[fy], forecast_real_aud_m=fy_tot[h] / defl[fy],
                              capacity_real_aud_m=(cap_line / defl[fy]) if cap_line else None))
        for c, cid in enumerate(CATS):
            util = U[h, c]
            gap_units = max(0.0, D[h, c] - supply[h, c])
            gap_value = fy_tot[h] * max(0.0, 1 - 1 / util) if util > 0 else 0.0
            status = "Breach" if util * 100 > cats.loc[cid, "breach_threshold_pct"] else (
                "Constrained" if util * 100 >= cats.loc[cid, "constrained_threshold_pct"] else "Within capacity")
            cap_rows.append(dict(scenario_id=sid, fy=fy, financial_year=fy_label(fy), category_id=cid, capacity_category=cats.loc[cid, "category_name"],
                                 unit=cats.loc[cid, "unit"], demand_units=D[h, c], available_units=supply[h, c], utilisation_pct=util * 100,
                                 status=status, gap_units=gap_units, gap_value_aud_m=gap_value, capacity_model_version=cap_version,
                                 baseline_utilisation_pct=U_base[h, c] * 100))
            col = S_[:, h] * I[:, c]
            for i in np.nonzero(col > 0)[0]:
                share = col[i] / D[h, c]
                exp_rows.append(dict(scenario_id=sid, fy=fy, financial_year=fy_label(fy), category_id=cid, capacity_category=cats.loc[cid, "category_name"],
                                     project_id=PIDS[i], project_name=proj.loc[PIDS[i], "project_name"], program_id=proj.loc[PIDS[i], "program_id"],
                                     program_name=proj.loc[PIDS[i], "program_name"], spend_aud_m=S_[i, h], demand_units=col[i],
                                     share_of_demand_pct=share * 100, utilisation_pct=util * 100, gap_units=gap_units * share,
                                     gap_value_aud_m=gap_value * share, heavy_user=bool(HEAVY[i, c])))
    # confidence
    pen_fy = np.where(HEAVY[:, None, :], np.clip(1 - 1 / np.where(U > 0, U, 1), 0, None)[None, :, :], 0).max(axis=2)  # P x H
    w = S_ / np.where(S_.sum(axis=1, keepdims=True) > 0, S_.sum(axis=1, keepdims=True), 1)
    pen = (w * pen_fy).sum(axis=1)
    conf = (proj.base_confidence_pct.to_numpy() * (1 - K_PEN * pen)).clip(10, 99)
    for i, p in enumerate(PIDS):
        conf_rows.append(dict(scenario_id=sid, project_id=p, base_confidence_pct=proj.loc[p, "base_confidence_pct"],
                              capacity_penalty_pct=pen[i] * K_PEN * 100, confidence_pct=conf[i], horizon_spend_aud_m=S_[i].sum()))
    port_conf = float((conf * S_.sum(axis=1)).sum() / S_.sum())
    # Monte Carlo range: lognormal cost uncertainty on unspent work only (actuals are fixed), wider for
    # low-confidence projects and later years, with a portfolio-wide market factor and a modest upward
    # skew (overruns are more likely than underruns). Seeded, so a re-run reproduces the same range.
    fut = np.array([[b["paths"][p][FY_MASKS[h] & FUTURE].sum() for h in range(len(HORIZON))] for p in PIDS])  # P x H
    sig = (0.02 + 0.20 * (1 - conf / 100.0))[:, None] * np.sqrt(1 + np.arange(len(HORIZON)))[None, :]
    z = 0.8 * RNG.standard_normal((N_SIM, len(PIDS), 1)) + 0.6 * RNG.standard_normal((N_SIM, 1, 1))
    sims = ((S_ - fut)[None] + fut[None] * np.exp(sig[None] * z + 0.15 * sig[None])).sum(axis=1)  # N x H
    pct = np.percentile(sims, [10, 50, 90], axis=0)
    hpct = np.percentile(sims.sum(axis=1), [10, 50, 90])
    for r in port_rows:
        if r["scenario_id"] == sid:
            h = HORIZON.index(r["fy"])
            r.update(forecast_p10_aud_m=float(pct[0, h]), forecast_p50_aud_m=float(pct[1, h]), forecast_p90_aud_m=float(pct[2, h]))
    # changes vs baseline
    deferred_regional = 0
    for i, p in enumerate(PIDS):
        a, a0 = b["paths"][p], base_built["paths"][p]
        f, f0 = finish_idx(a), finish_idx(a0)
        dh = a[HORIZON_MASK].sum() - a0[HORIZON_MASK].sum()
        if sid != "BASE" and (abs(dh) > 0.5 or f != f0):
            moved_out = (f0 is not None and f is not None and f0 <= horizon_end_idx < f)
            if moved_out and proj.loc[p, "region_type"] in ("Regional", "Remote"):
                deferred_regional += 1
            shift = (f - f0) if (f is not None and f0 is not None) else 0
            chg_rows.append(dict(scenario_id=sid, project_id=p, project_name=proj.loc[p, "project_name"], program_name=proj.loc[p, "program_name"],
                                 program_id=proj.loc[p, "program_id"], sector=proj.loc[p, "sector"],
                                 delay_cost_aud_m=max(0, shift) * DELAY_RATE * float(proj.loc[p, "tec_p50_aud_m"]),
                                 baseline_horizon_aud_m=a0[HORIZON_MASK].sum(), scenario_horizon_aud_m=a[HORIZON_MASK].sum(), delta_aud_m=dh,
                                 baseline_finish=month_end(f0) if f0 is not None else None, scenario_finish=month_end(f) if f is not None else None,
                                 finish_shift_months=(f - f0) if (f is not None and f0 is not None) else None,
                                 completion_moves_beyond_horizon=bool(moved_out), region_type=proj.loc[p, "region_type"],
                                 changes="; ".join(b["notes"].get(p, [])) or "inherited from base scenario"))
    for dec in b["decisions"]:
        dec_rows.append(dict(scenario_id=sid, **dec, project_name=proj.loc[dec["project_id"], "project_name"]))
    total_h = fy_tot.sum()
    env_total = float(sum(envelope.get(fy, 0.0) for fy in HORIZON))
    breaches = int((U > 1.0).sum())
    pk = np.unravel_index(np.argmax(U), U.shape)
    gaps = [r for r in port_rows if r["scenario_id"] == sid]
    pg = max(gaps, key=lambda r: r["capacity_gap_aud_m"])
    summ_rows.append(dict(
        scenario_id=sid, scenario_name=d.scenario_name, version=int(d.version), method=d.method, status=d.status,
        horizon_label=f"{fy_label(HORIZON[0])}-{fy_label(HORIZON[-1])}", total_forecast_aud_m=total_h,
        total_forecast_real_aud_m=float(sum(fy_tot[h] / defl[fy] for h, fy in enumerate(HORIZON))),
        vs_baseline_aud_m=total_h - base_fy.sum(), envelope_aud_m=env_total, headroom_aud_m=env_total - total_h,
        within_envelope=bool(total_h <= env_total), forecast_confidence_pct=port_conf, capacity_breaches=breaches,
        constrained_cells=int((U >= 0.9).sum()), breaches_resolved_vs_baseline=int((U_base > 1.0).sum()) - breaches,
        peak_utilisation_pct=float(U[pk] * 100), peak_category=cats.loc[CATS[pk[1]], "category_name"], peak_financial_year=fy_label(HORIZON[pk[0]]),
        peak_gap_aud_m=pg["capacity_gap_aud_m"], peak_gap_financial_year=pg["financial_year"],
        projects_changed=sum(1 for r in chg_rows if r["scenario_id"] == sid), regional_completions_deferred=deferred_regional,
        spend_beyond_horizon_aud_m=float(sum(max(0.0, -r["delta_aud_m"]) for r in chg_rows
                                             if r["scenario_id"] == sid and d.method != "plan" and (r["finish_shift_months"] or 0) > 0)),
        indicative_delay_cost_aud_m=float(sum(r["delay_cost_aud_m"] for r in chg_rows if r["scenario_id"] == sid)),
        completions_beyond_horizon=sum(1 for r in chg_rows if r["scenario_id"] == sid and r["completion_moves_beyond_horizon"]),
        forecast_p10_aud_m=float(hpct[0]), forecast_p50_aud_m=float(hpct[1]), forecast_p90_aud_m=float(hpct[2]),
        optimizer_deferrals=len(b["decisions"]), levers=int((levers.scenario_id == sid).sum()), capacity_model_version=cap_version))
    for h, fy in enumerate(HORIZON):
        cmp_rows.append(dict(scenario_id=sid, fy=fy, financial_year=fy_label(fy), forecast_aud_m=fy_tot[h], baseline_forecast_aud_m=base_fy[h],
                             delta_vs_baseline_aud_m=fy_tot[h] - base_fy[h], peak_utilisation_pct=float(U[h].max() * 100),
                             capacity_breaches=int((U[h] > 1.0).sum()),
                             status="Breach" if U[h].max() > 1.0 else ("Constrained" if U[h].max() >= 0.9 else "Within capacity")))
    # monthly expenditure for the scenario
    sp = {"plan_aud_m": base["plan_aud_m"], "forecast_aud_m": b["paths"], "actual_aud_m": base["actual_aud_m"]}
    monthly.append(paths_to_rows(sp, list(sp), extra={"scenario_id": sid}))
    print(f"{sid:<9} ${total_h / 1000:6.1f}bn  conf {port_conf:4.1f}%  breaches {breaches}  peak {U[pk] * 100:5.1f}% "
          f"{cats.loc[CATS[pk[1]], 'category_name']} {fy_label(HORIZON[pk[0]])}  gap ${pg['capacity_gap_aud_m'] / 1000:.1f}bn {pg['financial_year']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write gold

# COMMAND ----------

GOLD = {"nba_layer": "gold"}


def with_run(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows
    df["run_id"] = run_id
    return df


mon = pd.concat(monthly, ignore_index=True)
for c in ("plan_aud_m", "forecast_aud_m", "actual_aud_m"):
    mon[c.replace("_aud_m", "_real_aud_m")] = mon[c] / mon.fy.map(defl)
mon["is_actual_month"] = mon.month.map(lambda d_: month_idx(d_) < T0)
mon = mon.merge(proj[["program_id", "program_name", "project_name", "sector"]].reset_index(), on="project_id")
write_table(with_run(mon), "expenditure_monthly", "Monthly plan, forecast and actual expenditure by scenario and project (AUD m nominal and real).", tags=GOLD)

fy_df = (spark.table(table_name("expenditure_monthly"))
         .groupBy("run_id", "scenario_id", "project_id", "project_name", "program_id", "program_name", "sector", "fy", "financial_year")
         .agg(*[F.sum(c).alias(c) for c in ("plan_aud_m", "forecast_aud_m", "actual_aud_m", "plan_real_aud_m", "forecast_real_aud_m", "actual_real_aud_m")])
         .withColumn("variance_aud_m", F.col("forecast_aud_m") - F.col("plan_aud_m"))
         .withColumn("is_horizon", F.col("fy").isin(HORIZON)))
write_table(fy_df, "expenditure_fy", "Annual (financial-year) plan, forecast and actual expenditure by scenario and project. Main table for multi-year expenditure questions.",
            {"is_horizon": "True for the five financial years of the planning horizon."}, tags=GOLD)

write_table(with_run(port_rows), "portfolio_capacity_fy",
            "Portfolio expenditure vs modelled delivery capacity by scenario and FY: plan, forecast, deliverable-spend capacity line and capacity gap (AUD m).",
            {"capacity_aud_m": "Spend the modelled market can deliver that year = forecast / peak input utilisation.",
             "capacity_gap_aud_m": "Forecast spend above deliverable capacity, AUD m (0 when within capacity).",
             "binding_category": "Delivery input with the highest utilisation that year.",
             "envelope_aud_m": "Funding envelope for the year, AUD m.",
             "forecast_p10_aud_m": "10th percentile of simulated forecast spend for the year (1,000 seeded draws on unspent work), AUD m.",
             "forecast_p50_aud_m": "Median simulated forecast spend for the year, AUD m.",
             "forecast_p90_aud_m": "90th percentile of simulated forecast spend for the year, AUD m."}, tags=GOLD)
write_table(with_run(cap_rows), "capacity_demand",
            "Demand vs modelled available supply for each delivery-market input by scenario and FY, with utilisation and status (Within capacity / Constrained >= 90% / Breach > 100%).",
            {"demand_units": "Portfolio demand in the category unit.", "available_units": "Supply available to the portfolio (incl. scenario uplift levers).",
             "utilisation_pct": "demand / available x 100.", "gap_units": "Demand above supply, category units.",
             "gap_value_aud_m": "Portfolio spend that year that cannot be delivered given this input = forecast x (1 - 1/utilisation).",
             "baseline_utilisation_pct": "Utilisation of the same input and year in the Working baseline."}, tags=GOLD)
write_table(with_run(exp_rows), "capacity_exposure",
            "Project exposure to each delivery-market input by scenario and FY: share of demand and attributed share of any capacity gap. Use for 'which projects are most exposed to labour' questions.",
            {"share_of_demand_pct": "Project share of total portfolio demand for the input that year, %.",
             "gap_units": "Project's attributed share of the input gap, category units.",
             "gap_value_aud_m": "Project's attributed share of the gap value, AUD m. For labour gap use capacity_category = 'Skilled civil labour'.",
             "heavy_user": "True when the project's subsector uses this input at or above the median intensity."}, tags=GOLD)
write_table(with_run(conf_rows), "project_confidence", "Forecast confidence by scenario and project: Gateway-based confidence less exposure to breached capacity inputs.",
            {"capacity_penalty_pct": "Percentage-point reduction from exposure to breached inputs.", "confidence_pct": "Scenario forecast confidence, %."}, tags=GOLD)
write_table(with_run(summ_rows), "scenario_summary",
            "One row per scenario: horizon total, affordability vs envelope, spend-weighted confidence, capacity breaches, peak utilisation and gap, projects changed and regional completions deferred.",
            {"total_forecast_aud_m": "Forecast expenditure over the five-year horizon, AUD m nominal.",
             "vs_baseline_aud_m": "Horizon total minus Working baseline, AUD m.",
             "headroom_aud_m": "Funding envelope minus horizon total (negative = unaffordable).",
             "capacity_breaches": "Count of (year, input) cells above 100% utilisation.",
             "regional_completions_deferred": "Regional/remote projects whose completion moves beyond the horizon vs baseline.",
             "spend_beyond_horizon_aud_m": "Horizon spend pushed past FY31 by deferring projects (later completion) vs baseline, AUD m.",
             "indicative_delay_cost_aud_m": "Indicative cost of later completions at the endorsed delay-cost rate; not added to the forecast, AUD m.",
             "completions_beyond_horizon": "Projects whose completion moves beyond the horizon vs baseline.",
             "forecast_p90_aud_m": "90th percentile of simulated horizon spend, AUD m."}, tags=GOLD)
write_table(with_run(cmp_rows), "scenario_comparison", "Scenario vs Working baseline by FY: forecast, delta and capacity status.", tags=GOLD)
chg = pd.DataFrame(chg_rows) if chg_rows else pd.DataFrame(columns=["scenario_id", "project_id"])
write_table(with_run(chg), "scenario_project_changes", "Projects whose timing or cost differs from the Working baseline in each scenario, with the levers or sequencing decisions that caused it.",
            {"delay_cost_aud_m": "Indicative cost of the later completion at the endorsed delay-cost rate (% of P50 per month); not in the forecast, AUD m."}, tags=GOLD)
dec = pd.DataFrame(dec_rows) if dec_rows else pd.DataFrame(columns=["scenario_id", "iteration", "project_id"])
write_table(with_run(dec), "scenario_sequencing_decisions", "Audit trail of the capacity-aware sequencer: each deferral, the project, and the breached input-year that triggered it.", tags=GOLD)

dim_s = defs.reset_index()[["scenario_id", "scenario_name", "version", "base_scenario_id", "method", "status", "decision_purpose", "description",
                            "created_by", "created_at", "source"]]
dim_s["lever_count"] = dim_s.scenario_id.map(levers.scenario_id.value_counts()).fillna(0).astype(int)
write_table(with_run(dim_s), "dim_scenario", "Scenario dimension: active version of each scenario and how it is constructed.", tags=GOLD)
dim_c = cats.reset_index().drop(columns=["_delivery_date", "_source_file"], errors="ignore").rename(columns={"category_name": "capacity_category"})
dim_c["capacity_model_version"] = cap_version
write_table(with_run(dim_c), "dim_capacity_category", "Delivery-market input categories with units, supply growth and utilisation thresholds.", tags=GOLD)
set_control("capacity_model_version", cap_version)
