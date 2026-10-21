# Databricks notebook source
# MAGIC %md
# MAGIC # Generate compliance report - Automated Compliance Reporting
# MAGIC
# MAGIC Generates a **reproducible** report from point-in-time inputs and writes an output package to
# MAGIC the volume (`reports/<report_id>/`): `report.html` (human-readable, print to PDF),
# MAGIC `findings.json` (machine-readable) and `evidence_manifest.csv`.
# MAGIC
# MAGIC * Findings come from `requirement_coverage(as_of)` in `_common`: register versions in force,
# MAGIC   evidence versions collected and mappings decided **on or before** `as_of_date`.
# MAGIC * `findings_digest` = sha256 over the canonical findings. `reproduce_report_id` regenerates a
# MAGIC   past report and records whether the digest matches in `report_reproductions`.
# MAGIC * The executive summary is drafted by a foundation model (`summary_ai_generated = true`, model
# MAGIC   and prompt version recorded) and is excluded from the digest. Reports are created as **Draft**;
# MAGIC   approval and issue are human steps recorded in `report_status_events`.
# MAGIC
# MAGIC Modes: `report_type` = `monthly_summary` (all gates) | `gate_review` (one `gate_id`) |
# MAGIC `all_gate_reviews`; `bootstrap_reports=true` seeds a history of issued monthly summaries.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.dropdown("report_type", "monthly_summary", ["monthly_summary", "gate_review", "all_gate_reviews"])
dbutils.widgets.text("gate_id", "")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("reproduce_report_id", "")
dbutils.widgets.dropdown("bootstrap_reports", "false", ["false", "true"])
dbutils.widgets.text("model_endpoint", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("template_version", "v1.0")
dbutils.widgets.text("expiry_warning_days", "14")
dbutils.widgets.text("min_confidence", "0.5")
dbutils.widgets.text("requested_by", "report.service")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
report_type = dbutils.widgets.get("report_type")
gate_param = dbutils.widgets.get("gate_id")
as_of_param = dbutils.widgets.get("as_of_date")
reproduce_report_id = dbutils.widgets.get("reproduce_report_id").strip()
bootstrap = dbutils.widgets.get("bootstrap_reports") == "true"
model_endpoint = dbutils.widgets.get("model_endpoint")
template_version = dbutils.widgets.get("template_version")
warn_days = int(dbutils.widgets.get("expiry_warning_days"))
min_confidence = float(dbutils.widgets.get("min_confidence"))
requested_by = dbutils.widgets.get("requested_by") or "report.service"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import csv
import html
import io
import os
import uuid

PROMPT_VERSION = "report-summary-v1"
FINDING_FIELDS = ["obligation_id", "obligation_version", "requirement_id", "artefact_type", "status", "gap_reason",
                  "evidence_id", "artefact_version", "checksum", "evidence_modified_on", "expires_on"]
GATES = {r["gate_id"]: r.asDict() for r in spark.table(fqn("review_gates")).collect()}


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def compute_findings(as_of: str, gate_id: str | None):
    """Point-in-time findings + digest. Pure function of append-only / versioned inputs."""
    req = requirement_coverage(as_of, warn_days, min_confidence)
    if gate_id:
        req = req.filter(F.col("gate_id") == gate_id)
    rows = [r.asDict() for r in req.orderBy("requirement_id").collect()]
    canonical = json.dumps([{k: _iso(r["best_evidence_id" if k == "evidence_id" else
                                     "best_artefact_version" if k == "artefact_version" else
                                     "best_checksum" if k == "checksum" else k]) for k in FINDING_FIELDS} for r in rows],
                           sort_keys=True, separators=(",", ":"))
    return req, rows, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def register_fingerprint(as_of: str, gate_id: str | None):
    reg = spark.sql(f"""
      SELECT obligation_id, version, gate_id, effective_from FROM {fqn('obligation_register')}
      WHERE approval_state = 'Approved' AND effective_from <= CAST(:as_of AS DATE)
        AND (effective_to IS NULL OR effective_to > CAST(:as_of AS DATE)) AND (retired_on IS NULL OR retired_on > CAST(:as_of AS DATE))
    """, args={"as_of": as_of})
    if gate_id:
        reg = reg.filter(F.col("gate_id") == gate_id)
    keys = sorted(f"{r['obligation_id']}:v{r['version']}" for r in reg.collect())
    release = spark.sql(f"""SELECT count(DISTINCT effective_from) AS n FROM {fqn('obligation_register')}
                           WHERE approval_state = 'Approved' AND effective_from <= CAST(:as_of AS DATE)""", args={"as_of": as_of}).first()["n"]
    return hashlib.sha256("|".join(keys).encode()).hexdigest(), f"v{release}"


def table_versions():
    out = {}
    for t in ("obligation_register", "obligation_requirements", "evidence_bronze", "mapping_reviews", "mapping_ai_suggestions"):
        out[t] = spark.sql(f"DESCRIBE HISTORY {fqn(t)} LIMIT 1").first()["version"]
    return json.dumps(out, sort_keys=True)


def next_number(table: str, column: str, prefix: str) -> int:
    m = spark.sql(f"SELECT max(CAST(regexp_extract({column}, '{prefix}-(\\\\d+)', 1) AS INT)) AS m FROM {fqn(table)}").first()["m"]
    return (m or 0) + 1


def draft_summary(title: str, as_of: str, obl_rows, rows) -> tuple[str, bool]:
    gaps = [r for r in obl_rows if r["status"] == "Gap"]
    expiring = [r for r in obl_rows if r["status"] == "Expiring"]
    req_by_obl = {}
    for r in rows:
        if r["status"] != "Complete":
            reason = r["gap_reason"] or "expires in {} days".format(r["days_to_expiry"])
            req_by_obl.setdefault(r["obligation_id"], []).append("{}: {}".format(r["artefact_type"], reason))
    facts = "\n".join(f"- {o['obligation_id']} {o['obligation_title']} ({o['status']}): {'; '.join(req_by_obl.get(o['obligation_id'], []))}"
                      for o in gaps + expiring) or "- none"
    prompt = (
        "You are drafting the executive summary of a compliance assurance report for the Nation Building Authority "
        "(all data is synthetic). Write 3 to 5 plain sentences, at most 120 words, summarising evidence coverage. "
        "Use only the facts below. Do not interpret legislation or policy, do not give a delivery confidence rating, "
        "and do not recommend approval. Refer to obligations by ID.\n\n"
        f"Report: {title} as at {as_of}\n"
        f"Obligations in scope: {len(obl_rows)}; complete: {sum(o['status'] == 'Complete' for o in obl_rows)}; "
        f"expiring within {warn_days} days: {len(expiring)}; with gaps: {len(gaps)}.\n"
        f"Obligations needing attention:\n{facts}"
    )
    try:
        text = spark.sql(
            "SELECT ai_query(:ep, :prompt, modelParameters => named_struct('temperature', 0.0, 'max_tokens', 400)) AS s",
            args={"ep": model_endpoint, "prompt": prompt},
        ).first()["s"]
        return text.strip(), True
    except Exception as exc:  # noqa: BLE001 - fall back to a deterministic summary
        print(f"AI summary unavailable ({exc.__class__.__name__}); using template summary")
        return (f"As at {as_of}, {len(obl_rows) - len(gaps)} of {len(obl_rows)} obligations have current evidence; "
                f"{len(expiring)} have evidence expiring within {warn_days} days and {len(gaps)} have open gaps"
                + (f" ({', '.join(o['obligation_id'] for o in gaps)})." if gaps else ".")), False

# COMMAND ----------

# MAGIC %md
# MAGIC ## Output package

# COMMAND ----------

def write_package(meta: dict, obl_rows, rows, manifest_rows) -> str:
    out_dir = f"{REPORTS_ROOT}/{meta['report_id']}"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/findings.json", "w") as f:
        json.dump({"report": {k: _iso(v) for k, v in meta.items()},
                   "obligations": [{k: _iso(v) for k, v in o.items()} for o in obl_rows],
                   "findings": [{k: _iso(v) for k, v in r.items()} for r in rows]}, f, indent=2, default=str)
    with open(f"{out_dir}/evidence_manifest.csv", "w", newline="") as f:
        cols = ["evidence_id", "artefact_version", "title", "source_id", "checksum", "source_modified_at", "collected_at"]
        w = csv.writer(f)
        w.writerow(cols)
        for m in manifest_rows:
            w.writerow([_iso(m[c]) for c in cols])
    esc = lambda v: html.escape("" if v is None else str(_iso(v)))  # noqa: E731
    obl_html = "".join(
        f"<tr><td>{esc(o['obligation_id'])} v{esc(o['obligation_version'])}</td><td>{esc(o['obligation_title'])}</td>"
        f"<td>{esc(GATES[o['gate_id']]['gate_label'])}</td><td>{esc(o['owner_role'])}</td><td>{esc(o['status'])}</td>"
        f"<td>{esc(', '.join(o['gap_reasons'] or []))}</td><td>{esc(o['review_date'])}</td></tr>" for o in obl_rows)
    req_html = "".join(
        f"<tr><td>{esc(r['requirement_id'])}</td><td>{esc(r['artefact_type'])}</td><td>{esc(r['status'])}</td>"
        f"<td>{esc(r['best_evidence_id'])} {('v' + esc(r['best_artefact_version'])) if r['best_artefact_version'] else ''}</td>"
        f"<td>{esc(r['expires_on'])}</td><td class=mono>{esc((r['best_checksum'] or '')[:12])}</td></tr>" for r in rows)
    doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8><title>{esc(meta['title'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;color:#0B2026;margin:40px;max-width:1000px}}h1{{font-size:28px;margin:0}}
.meta{{color:#555;margin:6px 0 24px}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th,td{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}
th{{font:11px ui-monospace,monospace;text-transform:uppercase;color:#666}}.mono{{font-family:ui-monospace,monospace;font-size:12px}}.notice{{background:#f4f1ee;padding:12px;border-radius:8px}}</style></head><body>
<h1>{esc(meta['title'])}</h1>
<p class=meta>{esc(meta['report_id'])} &middot; evidence as at {esc(meta['as_of_date'])} &middot; obligation register {esc(meta['register_version_label'])} &middot; evidence snapshot {esc(meta['evidence_snapshot_id'])} &middot; template {esc(meta['template_version'])}</p>
<h2>Executive summary</h2><p>{esc(meta['executive_summary'])}</p>
<p class=notice>{'Summary drafted by AI (' + esc(meta['model_endpoint']) + ', ' + esc(meta['prompt_version']) + ') from the findings below; findings are computed deterministically. ' if meta['summary_ai_generated'] else ''}Synthetic data. This report records evidence coverage; it does not interpret regulation.</p>
<h2>Obligations</h2><table><tr><th>Obligation</th><th>Title</th><th>Gate</th><th>Owner</th><th>Status</th><th>Gap reasons</th><th>Review date</th></tr>{obl_html}</table>
<h2>Evidence requirements</h2><table><tr><th>Requirement</th><th>Artefact</th><th>Status</th><th>Evidence</th><th>Expires</th><th>Checksum</th></tr>{req_html}</table>
<p class=mono>findings digest {esc(meta['findings_digest'])}<br>register fingerprint {esc(meta['register_fingerprint'])}</p>
</body></html>"""
    with open(f"{out_dir}/report.html", "w") as f:
        f.write(doc)
    return out_dir

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate / reproduce

# COMMAND ----------

def generate(kind: str, gate_id: str | None, as_of: str, actor: str) -> str:
    req, rows, digest = compute_findings(as_of, gate_id)
    if not rows:
        print(f"No obligations in scope for {kind} {gate_id or ''} as at {as_of}; skipped")
        return ""
    obl_rows = [o.asDict() for o in obligation_coverage(req).orderBy("obligation_id").collect()]
    fingerprint, release = register_fingerprint(as_of, gate_id)
    n = next_number("compliance_reports", "report_id", "REP")
    report_id, snapshot_id = f"REP-{n:03d}", f"ES-{n:03d}"
    if kind == "gate_review":
        title = f"{GATES[gate_id]['gate_label']} assurance review"
    else:
        title = f"Monthly compliance summary - {date.fromisoformat(as_of):%b %Y}"
    prior = spark.table(fqn("compliance_reports")).filter(F.col("report_type") == kind)
    prior = prior.filter(F.col("gate_id") == gate_id) if gate_id else prior.filter(F.col("gate_id").isNull())
    summary, ai_generated = draft_summary(title, as_of, obl_rows, rows)
    generated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    manifest = (spark.table(fqn("evidence_artefacts"))
                .join(req.filter(F.col("best_evidence_id").isNotNull())
                      .select(F.col("best_evidence_id").alias("evidence_id"), F.col("best_artefact_version").alias("artefact_version")).distinct(),
                      ["evidence_id", "artefact_version"])
                .orderBy("evidence_id"))
    manifest_rows = [m.asDict() for m in manifest.collect()]

    meta = dict(
        report_id=report_id, report_type=kind, title=title, gate_id=gate_id or None, as_of_date=date.fromisoformat(as_of),
        register_fingerprint=fingerprint, register_version_label=release, evidence_snapshot_id=snapshot_id,
        template_version=template_version, report_version=prior.count() + 1, obligations_in_scope=len(obl_rows),
        obligations_complete=sum(o["status"] == "Complete" for o in obl_rows),
        obligations_expiring=sum(o["status"] == "Expiring" for o in obl_rows),
        obligations_gap=sum(o["status"] == "Gap" for o in obl_rows), evidence_items=len(manifest_rows),
        findings_digest=digest, executive_summary=summary, summary_ai_generated=ai_generated,
        model_endpoint=model_endpoint if ai_generated else None, prompt_version=PROMPT_VERSION if ai_generated else None,
        table_versions=table_versions(), output_path=f"{REPORTS_ROOT}/{report_id}", generated_at=generated_at, generated_by=actor,
    )
    write_package(meta, obl_rows, rows, manifest_rows)

    spark.createDataFrame([meta], spark.table(fqn("compliance_reports")).schema).write.mode("append").saveAsTable(fqn("compliance_reports"))
    (req.select(F.lit(report_id).alias("report_id"), "obligation_id", "obligation_version", "obligation_title", "gate_id", "owner_role",
                "requirement_id", "artefact_type", "status", "gap_reason", F.col("best_evidence_id").alias("evidence_id"),
                F.col("best_artefact_version").alias("artefact_version"), F.col("best_checksum").alias("checksum"),
                "evidence_modified_on", "expires_on", F.col("days_to_expiry").cast("int").alias("days_to_expiry"))
        .write.mode("append").saveAsTable(fqn("report_findings")))
    (manifest.select(F.lit(snapshot_id).alias("snapshot_id"), F.lit(report_id).alias("report_id"), "evidence_id", "artefact_version",
                     "title", "source_id", "checksum", "source_modified_at", "collected_at",
                     F.lit(generated_at).cast("timestamp").alias("captured_at"))
        .write.mode("append").saveAsTable(fqn("evidence_snapshots")))
    record_status(report_id, "Draft", actor, "Generated")

    events = spark.createDataFrame([dict(
        event_type="report.generated", entity_type="report", entity_id=report_id, related_id=snapshot_id,
        summary=f"{actor} created {report_id} from obligation register {release} and evidence snapshot {snapshot_id}",
        actor=actor, occurred_at=generated_at,
        payload=json.dumps({"title": title, "as_of_date": as_of, "findings_digest": digest, "register_fingerprint": fingerprint,
                            "template_version": template_version, "gaps": meta["obligations_gap"],
                            "expiring": meta["obligations_expiring"], "summary_ai_generated": ai_generated}),
        dedup_key=f"report.generated|{report_id}")],
        "event_type STRING, entity_type STRING, entity_id STRING, related_id STRING, summary STRING, actor STRING, occurred_at TIMESTAMP, payload STRING, dedup_key STRING")
    append_audit_events(events)
    print(f"{report_id} {title} as at {as_of}: {meta['obligations_gap']} gaps, {meta['obligations_expiring']} expiring, digest {digest[:12]}")
    return report_id


def record_status(report_id: str, status: str, actor: str, comment: str):
    changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    spark.createDataFrame([(report_id, status, actor, changed_at, comment)], spark.table(fqn("report_status_events")).schema) \
        .write.mode("append").saveAsTable(fqn("report_status_events"))
    append_audit_events(spark.createDataFrame([dict(
        event_type="report.status_changed", entity_type="report", entity_id=report_id, related_id=status,
        summary=f"{report_id} marked {status} by {actor}", actor=actor, occurred_at=changed_at,
        payload=json.dumps({"status": status, "comment": comment}),
        dedup_key=f"report.status_changed|{report_id}|{status}|{changed_at.isoformat()}")],
        "event_type STRING, entity_type STRING, entity_id STRING, related_id STRING, summary STRING, actor STRING, occurred_at TIMESTAMP, payload STRING, dedup_key STRING"))


def reproduce(report_id: str, actor: str) -> bool:
    original = spark.table(fqn("compliance_reports")).filter(F.col("report_id") == report_id).first()
    assert original, f"Report {report_id} not found"
    _, _, digest = compute_findings(original["as_of_date"].isoformat(), original["gate_id"])
    matches = digest == original["findings_digest"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rep_id = f"RPR-{uuid.uuid4().hex[:10].upper()}"
    spark.createDataFrame([(rep_id, report_id, now, original["findings_digest"], digest, matches, actor)],
                          spark.table(fqn("report_reproductions")).schema).write.mode("append").saveAsTable(fqn("report_reproductions"))
    append_audit_events(spark.createDataFrame([dict(
        event_type="report.reproduced", entity_type="report", entity_id=report_id, related_id=rep_id,
        summary=f"{report_id} regenerated from point-in-time inputs: digest {'matches' if matches else 'DOES NOT match'}",
        actor=actor, occurred_at=now, payload=json.dumps({"original": original["findings_digest"], "reproduced": digest}),
        dedup_key=f"report.reproduced|{rep_id}")],
        "event_type STRING, entity_type STRING, entity_id STRING, related_id STRING, summary STRING, actor STRING, occurred_at TIMESTAMP, payload STRING, dedup_key STRING"))
    print(f"{report_id}: reproduced digest {'MATCHES' if matches else 'DOES NOT MATCH'} ({digest[:12]} vs {original['findings_digest'][:12]})")
    return matches

# COMMAND ----------

as_of = resolve_as_of(as_of_param)

if reproduce_report_id:
    ok = reproduce(reproduce_report_id, requested_by)
    dbutils.notebook.exit(json.dumps({"report_id": reproduce_report_id, "reproduced": ok}))

created = []
if bootstrap and spark.table(fqn("compliance_reports")).count() > 0:
    print("Reports already exist; bootstrap seeding skipped (idempotent).")
elif bootstrap:
    # Seed history: issued monthly summaries for the last six month-ends, then the current gate reviews.
    today = date.fromisoformat(as_of)
    month_ends = []
    d = today.replace(day=1) - timedelta(days=1)
    while len(month_ends) < 6:
        month_ends.insert(0, d)
        d = d.replace(day=1) - timedelta(days=1)
    approver = "Senior Responsible Official (synthetic)"
    for me in month_ends:
        rid = generate("monthly_summary", None, me.isoformat(), "report.service")
        record_status(rid, "Ready for approval", "Assurance analyst 01 (synthetic)", "Reviewed against evidence manifest")
        record_status(rid, "Issued", approver, "Approved for issue (synthetic backfill)")
        created.append(rid)
    rid = generate("gate_review", "GATE-1", (today - timedelta(days=4)).isoformat(), "report.service")
    record_status(rid, "Ready for approval", "Assurance analyst 01 (synthetic)", "Reviewed against evidence manifest")
    created += [rid, generate("gate_review", "GATE-2", as_of, "report.service")]
elif report_type == "monthly_summary":
    created.append(generate("monthly_summary", None, as_of, requested_by))
elif report_type == "gate_review":
    assert gate_param in GATES, f"gate_id must be one of {sorted(GATES)}"
    created.append(generate("gate_review", gate_param, as_of, requested_by))
else:
    for gid in sorted(GATES):
        created.append(generate("gate_review", gid, as_of, requested_by))

created = [c for c in created if c]
# Every report must reproduce from its own point-in-time inputs.
for rid in created:
    assert reproduce(rid, "report.service"), f"{rid} is not reproducible"

# COMMAND ----------

display(spark.sql(f"""
  SELECT r.report_id, r.title, r.as_of_date, r.obligations_in_scope, r.obligations_gap, r.obligations_expiring,
         s.status, r.findings_digest, r.output_path
  FROM {fqn('compliance_reports')} r
  JOIN (SELECT report_id, max_by(status, changed_at) AS status FROM {fqn('report_status_events')} GROUP BY report_id) s USING (report_id)
  ORDER BY r.report_id DESC"""))
