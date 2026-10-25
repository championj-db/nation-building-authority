# Databricks notebook source
# MAGIC %md
# MAGIC # 08 Validate
# MAGIC
# MAGIC End-of-run assurance, recorded in `pipeline_quality_checks`:
# MAGIC
# MAGIC * **Data** - key tables populated, primary keys unique, every interaction in serving is resolved.
# MAGIC * **Entity resolution** - pairwise F1 against synthetic ground truth >= `min_er_f1`.
# MAGIC * **AI signals** - intent accuracy against ground truth >= `min_intent_accuracy`.
# MAGIC * **Aggregates** - no agency-level cell between 1 and `small_cell_threshold - 1`.
# MAGIC * **Ownership** - every registered object still carries the ownership marker; objects in the schema
# MAGIC   that this pipeline did not create are reported (never touched).
# MAGIC * **Policy self-test** - as the job principal: no rows without a session; start a housing session on
# MAGIC   an owned / unassigned case; only permitted domains and the subject constituent are returned,
# MAGIC   identity is minimum (DOB hidden, email masked), health / licensing never appear; end the session
# MAGIC   and confirm access is gone. Self-test events are written to `access_audit_events` and labelled.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("min_er_f1", "0.85")
dbutils.widgets.text("min_intent_accuracy", "0.6")
dbutils.widgets.text("small_cell_threshold", "5")
dbutils.widgets.dropdown("policy_self_test", "true", ["true", "false"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None
MIN_F1 = float(dbutils.widgets.get("min_er_f1"))
MIN_INTENT = float(dbutils.widgets.get("min_intent_accuracy"))
K = int(dbutils.widgets.get("small_cell_threshold"))
SELF_TEST = dbutils.widgets.get("policy_self_test").lower() == "true"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("VALIDATE")
spark.sql(f"USE SCHEMA `{schema}`")
T = fqn
checks = []


def scalar(sql: str, **args):
    return spark.sql(sql, args=args or None).first()[0]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data

# COMMAND ----------

for t in ["silver_source_identities", "silver_interactions", "silver_constituents", "gold_interactions", "gold_cases",
          "gold_constituent_profile", "consent_current", "service_kpis"]:
    n = scalar(f"SELECT count(*) FROM {T(t)}") if table_exists(t) else 0
    checks.append((f"{t}_populated", n > 0, "critical", n, "> 0"))

for t, key in [("gold_interactions", "interaction_id"), ("gold_cases", "case_id"),
               ("gold_constituent_profile", "constituent_id"), ("silver_identity_xref", "source_record_id")]:
    dup = scalar(f"SELECT count(*) - count(DISTINCT {key}) FROM {T(t)}")
    checks.append((f"{t}_{key}_unique", dup == 0, "critical", dup, 0))

orphans = scalar(f"""SELECT count(*) FROM {T('gold_cases')} c LEFT ANTI JOIN {T('gold_constituent_profile')} p
                     USING (constituent_id) WHERE c.constituent_id IS NOT NULL""")
checks.append(("cases_reference_constituents", orphans == 0, "critical", orphans, 0))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Entity resolution and AI accuracy

# COMMAND ----------


def latest(table: str):
    df = spark.table(table_name(table))
    cur = df.filter(F.col("run_id") == run_id)
    return (cur if cur.limit(1).count() else df.orderBy(F.col("run_id").desc())).first()


er = latest("er_evaluation") if table_exists("er_evaluation") else None
f1 = float(er.pair_f1 or 0) if er else 0.0
checks.append(("er_pair_f1", f1 >= MIN_F1, "critical", round(f1, 4), f">= {MIN_F1}",
               f"precision={er.pair_precision:.3f} recall={er.pair_recall:.3f}" if er else "no evaluation"))

ai = latest("ai_signal_evaluation") if table_exists("ai_signal_evaluation") else None
acc = float(ai.intent_accuracy or 0) if ai else 0.0
checks.append(("ai_intent_accuracy", acc >= MIN_INTENT, "warning", round(acc, 4), f">= {MIN_INTENT}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Aggregates and ownership

# COMMAND ----------

small = scalar(f"""SELECT count(*) FROM {T('service_kpis')} WHERE agency_code <> 'ALL' AND
                   (open_journeys BETWEEN 1 AND {K - 1} OR high_need_awaiting BETWEEN 1 AND {K - 1}
                    OR inbound_contacts_7d BETWEEN 1 AND {K - 1})""")
checks.append(("kpi_small_cells_suppressed", small == 0, "critical", small, 0))
small2 = scalar(f"SELECT count(*) FROM {T('repeat_contact_by_service')} WHERE inbound_contacts BETWEEN 1 AND {K - 1}")
checks.append(("insights_small_cells_suppressed", small2 == 0, "critical", small2, 0))

registered = spark.sql(f"SELECT object_name, object_type FROM {T(REGISTRY)}").collect()
lost = [r.object_name for r in registered
        if r.object_type in ("TABLE", "VIEW") and object_exists(r.object_name) and not has_owner_property(r.object_name)]
checks.append(("registered_objects_keep_owner_marker", not lost, "critical", lost, []))
reg_names = {r.object_name for r in registered}
foreign = [r.table_name for r in spark.sql(f"""SELECT table_name FROM `{catalog}`.information_schema.tables
                                               WHERE table_schema = :s""", args={"s": schema}).collect()
           if r.table_name not in reg_names]
checks.append(("foreign_objects_in_schema", True, "info", len(foreign), "reported only",
               "not created by this pipeline, left untouched: " + ", ".join(sorted(foreign)[:20])))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Policy self-test

# COMMAND ----------

ME = scalar("SELECT session_user()")
PURPOSE = "housing_case_support"
authorised = scalar(f"""SELECT count(*) FROM {T('staff_purpose_authorisations')}
                        WHERE principal = :p AND purpose_code = :c AND valid_to IS NULL""", p=ME, c=PURPOSE) > 0
if SELF_TEST and not authorised:
    checks.append(("policy_self_test", True, "warning", "skipped", "runner authorised",
                   f"{ME} holds no {PURPOSE} authorisation (set demo_officer_principal to the job principal)"))
elif SELF_TEST:
    spark.sql(f"CALL {fn_name('end_access_session')}()")
    n0 = {t: scalar(f"SELECT count(*) FROM {T(t)}") for t in ("constituent_360", "constituent_profile", "consent_decisions")}
    checks.append(("no_rows_without_session", sum(n0.values()) == 0, "critical", n0, "all 0"))

    case = spark.sql(f"""
        SELECT case_id, constituent_id FROM {T('gold_cases')}
        WHERE is_open AND case_purpose = :c AND (owner_principal = :p OR owner_principal IS NULL)
          AND constituent_id IS NOT NULL
        ORDER BY owner_principal = :p DESC, priority_score DESC LIMIT 1""", args={"c": PURPOSE, "p": ME}).first()
    if case is None:
        checks.append(("policy_self_test_case", False, "critical", None, "an open housing case in caseload"))
    else:
        spark.sql(f"CALL {fn_name('start_access_session')}(p_purpose => :c, p_case_id => :k, "
                  f"p_justification => 'pipeline policy self-test (08_validate)')", args={"c": PURPOSE, "k": case.case_id})
        cid = case.constituent_id
        subjects = scalar(f"SELECT count(DISTINCT constituent_id) FROM {T('constituent_360')} WHERE constituent_id <> :c", c=cid)
        checks.append(("timeline_only_subject_constituent", subjects == 0, "critical", subjects, 0))

        allowed = {r.data_domain for r in spark.sql(f"""
            SELECT p.data_domain FROM {T('ref_purpose_domain_policy')} p
            LEFT JOIN {T('consent_current')} c ON c.constituent_id = :c AND c.purpose_code = p.purpose_code
                                               AND c.data_domain = p.data_domain
            WHERE p.purpose_code = :pur AND (p.access_rule = 'allow' OR (p.access_rule = 'consent' AND c.decision = 'granted'
                  AND coalesce(c.expires_at > current_timestamp(), true)))""", args={"c": cid, "pur": PURPOSE}).collect()}
        seen = {r.data_domain for r in spark.sql(f"SELECT DISTINCT data_domain FROM {T('constituent_360')}").collect()}
        checks.append(("timeline_domains_permitted", seen <= allowed, "critical", sorted(seen), f"subset of {sorted(allowed)}"))
        checks.append(("timeline_excludes_denied_domains", not (seen & {"health", "transport_licensing"}), "critical",
                       sorted(seen & {"health", "transport_licensing"}), []))
        expected = scalar(f"""SELECT count(*) FROM {T('gold_interactions')} WHERE constituent_id = :c
                              AND data_domain IN ({', '.join(sql_str(d) for d in allowed) or "''"})""", c=cid)
        got = scalar(f"SELECT count(*) FROM {T('constituent_360')}")
        checks.append(("timeline_complete_for_permitted_domains", got == expected, "critical", got, expected))

        prof = spark.sql(f"SELECT dob, email, birth_year FROM {T('constituent_profile')}").collect()
        checks.append(("profile_single_row", len(prof) == 1, "critical", len(prof), 1))
        if prof:
            p = prof[0]
            checks.append(("profile_dob_masked_minimum_identity", p.dob is None, "critical", p.dob, None))
            checks.append(("profile_email_masked", p.email is None or "***@" in p.email, "critical", p.email, "x***@domain"))
        sig_domains = {r.data_domain for r in spark.sql(f"SELECT DISTINCT data_domain FROM {T('constituent_need_signals')}").collect()}
        sig_ok = {d for (pur, d, rule, lvl, sig, _) in PURPOSE_DOMAIN_POLICY if pur == PURPOSE and sig} & allowed
        checks.append(("need_signals_only_signal_domains", sig_domains <= sig_ok, "critical", sorted(sig_domains), f"subset of {sorted(sig_ok)}"))
        unmasked = scalar(f"""SELECT count(*) FROM {T('constituent_360')}
                              WHERE data_domain NOT IN ({', '.join(sql_str(d) for d in sig_ok) or "''"}) AND intent IS NOT NULL""")
        checks.append(("signals_masked_outside_signal_domains", unmasked == 0, "critical", unmasked, 0))

        spark.sql(f"CALL {fn_name('end_access_session')}()")
        n1 = scalar(f"SELECT count(*) FROM {T('constituent_360')}")
        checks.append(("no_rows_after_session_end", n1 == 0, "critical", n1, 0))

# COMMAND ----------

failed = record_checks("08_validate", run_id, checks)
prior = spark.sql(f"""SELECT task, check_name, observed, expected FROM {T('pipeline_quality_checks')}
                      WHERE run_id = :r AND NOT passed AND severity = 'critical'""", args={"r": run_id}).collect()
print(f"critical failures this run (all tasks): {len(prior)}")
assert not failed, f"critical checks failed: {failed}"
