# Databricks notebook source
# MAGIC %md
# MAGIC # 03 Assess: correctly rendered checks, the payment clock, and the gold layer
# MAGIC
# MAGIC Reads the Lakeflow silver tables and the AP reference data, and publishes what the review
# MAGIC workbench and the Genie space read:
# MAGIC
# MAGIC | Table | Grain | What it holds |
# MAGIC | --- | --- | --- |
# MAGIC | `gold_documents` | document | type, status, sender, pages, queue state |
# MAGIC | `gold_invoice_assessment` | invoice / adjustment note | three-way match, checks summary, RMG 417 clock |
# MAGIC | `gold_extracted_fields` | field | value, confidence, grounding, page regions |
# MAGIC | `gold_invoice_checks` | check | each correctly rendered criterion: pass, fail or unknown |
# MAGIC | `gold_intake` | statement / letter / quote | intent, linked invoices, next action |
# MAGIC | `gold_readiness_weekly` | week | paid on time under today's terms and under the 2027 terms |
# MAGIC | `gold_extraction_accuracy` | field x scan | agreement with ground truth, routing, reviewer corrections |
# MAGIC | `gold_check_detection` | injected defect | whether the checks caught it |
# MAGIC | `gold_pipeline_status` | one row | volumes at each stage and provenance |
# MAGIC | `gold_open_queue` (view) | open invoice | days left on the clock, computed when queried |
# MAGIC
# MAGIC Checks run in arrival order through a ledger, so duplicates and remaining order value are judged
# MAGIC on what AP knew when each document arrived. Ground truth is used only for the accuracy and
# MAGIC detection measures, never for a document's status.

# COMMAND ----------

# MAGIC %pip install --quiet "holidays>=0.60"

# COMMAND ----------

import datetime as dt
import json
import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_found = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _found is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _found)

import pandas as pd  # noqa: E402

import assess  # noqa: E402
from common import (  # noqa: E402
    CHECKS, CORRESPONDENCE_INTENTS, DOC_TYPES, GIC_ANNUAL_RATE_DEFAULT, GIC_QUARTER_DEFAULT, INVOICE_TYPES,
    REVIEW_THRESHOLD, STATUSES, fq, get_params,
)
from rules import digits, money  # noqa: E402

p = get_params({"catalog": "", "schema": "", "volume": "documents", "gic_rate": str(GIC_ANNUAL_RATE_DEFAULT)}, dbutils)
CATALOG, SCHEMA, GIC = p["catalog"], p["schema"], float(p["gic_rate"])
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
exists = lambda name: spark.catalog.tableExists(f"{CATALOG}.{SCHEMA}.{name}")  # noqa: E731
TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=11)).date()  # Canberra (AEDT); the clock is a local-date clock

ctl = {r.key: json.loads(r.value) for r in spark.table(t("corpus_control")).collect()}
HOLIDAYS = {r.cal_date for r in spark.table(t("ref_business_calendar")).where("holiday_name IS NOT NULL").collect()}

# COMMAND ----------

manifest = spark.table(t("bronze_inbox_manifest")).toPandas()
classified = spark.table(t("silver_classified_documents")).select(
    "doc_id", "doc_type", "page_count", "page_images", "parse_error", "classify_error", "parsed_at", "full_text").toPandas()
inv = spark.table(t("silver_invoice_extraction")).select("doc_id", "doc_type", "fields_json", "citations_json", "elements_json", "extract_error").toPandas()
stm = spark.table(t("silver_statement_extraction")).select("doc_id", "fields_json", "citations_json", "elements_json").toPandas() if exists("silver_statement_extraction") else pd.DataFrame(columns=["doc_id", "fields_json"])
cor = spark.table(t("silver_correspondence_extraction")).select("doc_id", "fields_json", "citations_json", "elements_json").toPandas() if exists("silver_correspondence_extraction") else pd.DataFrame(columns=["doc_id", "fields_json"])
pos = [r.asDict() for r in spark.table(t("ref_purchase_orders")).collect()]
suppliers = [r.asDict() for r in spark.table(t("ref_suppliers")).collect()]
contracts = {r.contract_id: r.asDict() for r in spark.table(t("ref_contracts")).collect()}
receipts = [r.asDict() for r in spark.table(t("ref_goods_receipts")).collect()]
history = spark.table(t("bronze_processing_history")).toPandas()
# The simulated history is generated once; as days pass it must not claim the future. A decision
# dated after today has not happened yet (the document is still open), and an accepted invoice
# with a payment date after today is accepted but not yet paid.
history["decided_date"] = pd.to_datetime(history["decided_date"]).dt.date
history["paid_date"] = pd.to_datetime(history["paid_date"]).dt.date
history = history[history["decided_date"] <= TODAY].copy()
unpaid = history["paid_date"].notna() & (history["paid_date"] > TODAY)
history.loc[unpaid, ["paid_date", "late_days_current", "late_days_2027"]] = None
history.loc[unpaid, "interest_current"] = 0.0
truth = spark.table(t("bronze_ground_truth")).toPandas()
wb_dec = spark.table(t("silver_workbench_decisions")).toPandas() if exists("silver_workbench_decisions") else pd.DataFrame()
wb_cor = spark.table(t("silver_workbench_corrections")).toPandas() if exists("silver_workbench_corrections") else pd.DataFrame()

# A VARIANT JSON null arrives as the string "null"; only a real error list counts as a parse error.
classified["parse_error"] = [None if (e is None or str(e) in ("null", "[]")) else e for e in classified["parse_error"]]
docs = manifest.merge(classified, on="doc_id", how="left")
docs["arrival_date"] = pd.to_datetime(docs["arrival_date"]).dt.date
docs = docs.sort_values(["arrival_ts", "doc_id"]).reset_index(drop=True)
print(f"documents landed {len(manifest)}, classified {classified['doc_id'].nunique()}, invoice extractions {len(inv)}")

# COMMAND ----------

# Invoices and adjustment notes, through the ledger in arrival order.
ledger = assess.Ledger(pos, suppliers, receipts)
inv_by_id = inv.set_index("doc_id").to_dict("index")
hist_by_id = history.set_index("doc_id").to_dict("index") if len(history) else {}
wb_by_id = wb_dec.sort_values("decided_at").groupby("doc_id").tail(1).set_index("doc_id").to_dict("index") if len(wb_dec) else {}

field_out, check_out, summary_out = [], [], []
for _, d in docs.iterrows():
    if d["doc_type"] not in INVOICE_TYPES or d["doc_id"] not in inv_by_id:
        continue
    x = inv_by_id[d["doc_id"]]
    result = assess.assess_invoice({
        "doc_id": d["doc_id"], "doc_type": d["doc_type"], "arrival_date": d["arrival_date"], "channel": d["channel"],
        "fields_json": x["fields_json"], "citations_json": x["citations_json"], "elements_json": x["elements_json"],
        "full_text": d["full_text"] or "",
    }, ledger, HOLIDAYS, TODAY)
    for r in result["rows"]:
        field_out.append({"doc_id": d["doc_id"], **r})
    for i, c in enumerate(result["checks"]):
        meta = CHECKS[c.code]
        check_out.append({"doc_id": d["doc_id"], "check_code": c.code, "display_order": i, "label": meta["label"],
                          "criterion": meta["criterion"], "source": meta["source"], "source_url": meta["url"],
                          "supplier_fault": meta["supplier_fault"], "passed": c.passed,
                          "result": "pass" if c.passed else ("unknown" if c.passed is None else "fail"),
                          "detail": c.detail, "return_reason": meta["return_reason"] if c.passed is False else None})
    s = result["summary"]
    h = hist_by_id.get(d["doc_id"])
    wb = wb_by_id.get(d["doc_id"])
    if wb:
        queue_state, decision, decided_by, decided_at, source = "decided", wb["decision"], wb["decided_by"], wb["decided_at"], "workbench"
    elif h:
        queue_state, decision, decided_by, decided_at, source = "decided", h["decision"], h["decided_by"], pd.Timestamp(h["decided_date"]), "simulated_history"
    else:
        queue_state, decision, decided_by, decided_at, source = "open", None, None, None, None
    contract = contracts.get(s["contract_id"]) or {}
    summary_out.append({
        **s,
        "status_label": STATUSES[s["status"]],
        "fields_below_threshold": s["fields_below_threshold"], "failed_checks": s["failed_checks"], "return_reasons": s["return_reasons"],
        "arrival_ts": d["arrival_ts"], "arrival_date": d["arrival_date"], "channel": d["channel"],
        "contract_description": contract.get("description"), "contract_category": contract.get("category"),
        "contract_manager": contract.get("contract_manager"), "contract_value_inc_gst": contract.get("value_inc_gst"),
        "queue_state": queue_state, "decision": decision, "decided_by": decided_by, "decided_at": decided_at, "decision_source": source,
        "paid_date": h.get("paid_date") if h else None,
        "simulated_late_days_current": h.get("late_days_current") if h else None,
        "simulated_late_days_2027": h.get("late_days_2027") if h else None,
        "simulated_interest_current": h.get("interest_current") if h else None,
    })

fields = pd.DataFrame(field_out)
checks = pd.DataFrame(check_out)
summary = pd.DataFrame(summary_out)
print(summary["status"].value_counts().to_dict())

# COMMAND ----------

# Statements, correspondence and quotes: the rest of the inbox.
inv_numbers = {}
for _, s in summary.iterrows():
    if s["invoice_number"]:
        inv_numbers.setdefault((s["supplier_id"], assess.normalise_invoice_number(s["invoice_number"])), s["doc_id"])
supplier_by_name = {assess.normalise_name(s["name"]): s for s in suppliers}
intake_out = []
for _, d in docs.iterrows():
    if d["doc_type"] in INVOICE_TYPES or pd.isna(d["doc_type"]):
        continue
    row = {"doc_id": d["doc_id"], "doc_type": d["doc_type"], "arrival_ts": d["arrival_ts"], "arrival_date": d["arrival_date"],
           "sender": d["sender"], "subject": d["subject"], "supplier_id": None, "supplier_name": None, "intent": None,
           "intent_label": None, "next_action": None, "summary": None, "referenced_invoices": [], "linked_doc_ids": [],
           "unmatched_invoices": [], "bank_details_differ": None, "balance_due": None, "overdue_amount": None, "risk_flag": None}
    src = stm if d["doc_type"] == "supplier_statement" else cor if d["doc_type"] == "correspondence" else None
    f = {}
    if src is not None and len(src) and d["doc_id"] in set(src["doc_id"]):
        raw = json.loads(src.set_index("doc_id").loc[d["doc_id"], "fields_json"] or "{}") or {}
        f = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in raw.items()}
    sup = supplier_by_name.get(assess.normalise_name(f.get("supplier_name")))
    if sup:
        row.update(supplier_id=sup["supplier_id"], supplier_name=sup["name"])
    else:
        row["supplier_name"] = f.get("supplier_name")
    listed = f.get("invoice_numbers") or f.get("referenced_invoice_numbers") or []
    listed = [x.get("value") if isinstance(x, dict) else x for x in listed if x]
    linked = [inv_numbers.get((row["supplier_id"], assess.normalise_invoice_number(n))) for n in listed]
    row["referenced_invoices"] = [str(n) for n in listed]
    row["linked_doc_ids"] = [x for x in linked if x]
    row["unmatched_invoices"] = [str(n) for n, x in zip(listed, linked) if not x]
    if d["doc_type"] == "supplier_statement":
        row.update(balance_due=money(f.get("balance_due")), overdue_amount=money(f.get("overdue_amount")),
                   next_action="Reconcile against the ledger." + (" Chase the invoices we have not received." if row["unmatched_invoices"] else ""),
                   summary=f"Statement listing {len(listed)} invoice(s)" + (f", {len(row['unmatched_invoices'])} not in our inbox" if row["unmatched_invoices"] else ""))
    elif d["doc_type"] == "correspondence":
        intent = f.get("intent") if f.get("intent") in CORRESPONDENCE_INTENTS else "other"
        meta = CORRESPONDENCE_INTENTS[intent]
        row.update(intent=intent, intent_label=meta["label"], next_action=meta["action"], summary=f.get("summary"))
        if intent == "bank_details_change":
            new = (digits(f.get("new_bank_bsb")), digits(f.get("new_bank_account")))
            held = (digits(sup["bsb"]), digits(sup["account"])) if sup else (None, None)
            row["bank_details_differ"] = bool(sup) and new != held
            row["risk_flag"] = "Bank details change requested by letter. Verify through the vendor master contact before any change."
    else:
        row.update(next_action="Not a request for payment. Forward to the contract manager; do not enter it in AP.",
                   summary="Quotation for future work")
    intake_out.append(row)
intake = pd.DataFrame(intake_out)

# COMMAND ----------

# Document register: one row per document, whatever its type.
status_by_doc = summary.set_index("doc_id")["status"].to_dict() if len(summary) else {}
reg = []
for _, d in docs.iterrows():
    dtp = d["doc_type"] if isinstance(d["doc_type"], str) else None
    status = status_by_doc.get(d["doc_id"]) or ("not_invoice" if dtp else "processing")
    live = d["doc_id"] not in hist_by_id and (d["batch_id"] != "seed" or (TODAY - d["arrival_date"]).days <= 14)
    reg.append({"doc_id": d["doc_id"], "arrival_ts": d["arrival_ts"], "arrival_date": d["arrival_date"], "channel": d["channel"],
                "sender": d["sender"], "subject": d["subject"], "attachment_name": d["attachment_name"], "path": d["path"],
                "batch_id": d["batch_id"], "doc_type": dtp, "doc_type_label": DOC_TYPES.get(dtp, {}).get("label") if dtp else None,
                "status": status, "status_label": STATUSES.get(status, "Processing"),
                "page_count": None if pd.isna(d["page_count"]) else int(d["page_count"]),
                "page_images": [] if d["page_images"] is None or isinstance(d["page_images"], float) else [str(x) for x in d["page_images"]],
                "parse_error": d["parse_error"] if isinstance(d["parse_error"], str) else None,
                "parsed_at": d["parsed_at"], "in_live_window": live})
register = pd.DataFrame(reg)

# COMMAND ----------

def write(df: pd.DataFrame, name: str, ddl: str, comment: str) -> None:
    cols = [c.split()[0] for c in ddl.split(", ")]
    frame = df[cols] if len(df) else pd.DataFrame(columns=cols)
    sdf = spark.createDataFrame(frame.astype(object).where(pd.notna(frame), None), ddl) if len(frame) else spark.createDataFrame([], ddl)
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t(name))
    spark.sql(f"COMMENT ON TABLE {t(name)} IS {json.dumps(comment)}")
    print(f"{name}: {len(frame)} rows")


write(register, "gold_documents",
      "doc_id STRING, arrival_ts TIMESTAMP_NTZ, arrival_date DATE, channel STRING, sender STRING, subject STRING, attachment_name STRING, "
      "path STRING, batch_id STRING, doc_type STRING, doc_type_label STRING, status STRING, status_label STRING, page_count INT, "
      "page_images ARRAY<STRING>, parse_error STRING, parsed_at TIMESTAMP, in_live_window BOOLEAN",
      "Document register: every document in the AP inbox with its classified type, status and page images. Synthetic documents.")

write(summary, "gold_invoice_assessment",
      "doc_id STRING, doc_type STRING, status STRING, status_label STRING, lowest_required_confidence DOUBLE, "
      "fields_below_threshold ARRAY<STRING>, failed_checks ARRAY<STRING>, return_reasons ARRAY<STRING>, supplier_id STRING, "
      "supplier_name STRING, invoice_number STRING, invoice_date DATE, po_number_quoted STRING, po_number STRING, contract_id STRING, "
      "po_value_inc_gst DOUBLE, po_billed_before_inc_gst DOUBLE, subtotal_ex_gst DOUBLE, gst_amount DOUBLE, total_inc_gst DOUBLE, "
      "receipt_id STRING, receipt_date DATE, duplicate_of STRING, einvoice BOOLEAN, trigger_date DATE, clock_regime STRING, "
      "term_label STRING, pay_by_date DATE, pay_by_2027_date DATE, arrival_ts TIMESTAMP_NTZ, arrival_date DATE, channel STRING, "
      "contract_description STRING, contract_category STRING, contract_manager STRING, contract_value_inc_gst DOUBLE, "
      "queue_state STRING, decision STRING, decided_by STRING, decided_at TIMESTAMP, decision_source STRING, paid_date DATE, "
      "simulated_late_days_current INT, simulated_late_days_2027 INT, simulated_interest_current DOUBLE",
      "One row per tax invoice or adjustment note: machine status (ready, needs_review, awaiting_delivery, exception), "
      "three-way match, failed correctly rendered checks and the RMG 417 payment clock. trigger_date is the day both "
      "delivery was acknowledged and a correctly rendered invoice was received; pay_by_date applies the terms in force on it, "
      "pay_by_2027_date the 10-business-day terms. Decisions marked simulated_history are synthetic.")

write(fields, "gold_extracted_fields",
      "doc_id STRING, field STRING, label STRING, display_order INT, required BOOLEAN, value STRING, model_confidence DOUBLE, "
      "routing_confidence DOUBLE, grounded BOOLEAN, type_valid BOOLEAN, in_cited_region BOOLEAN, below_threshold BOOLEAN, regions_json STRING, cited_text STRING, field_type STRING",
      f"Extracted invoice fields from ai_extract v2.1. model_confidence is the function's score; routing_confidence also "
      f"requires the value to be found in its cited text and to parse as its type. Required fields below {REVIEW_THRESHOLD} "
      "route the document to a reviewer. regions_json holds page-image pixel boxes for the evidence. Not a probability of correctness.")

write(checks, "gold_invoice_checks",
      "doc_id STRING, check_code STRING, display_order INT, label STRING, criterion STRING, source STRING, source_url STRING, "
      "supplier_fault BOOLEAN, passed BOOLEAN, result STRING, detail STRING, return_reason STRING",
      "Correctly rendered criteria (RMG 417, Commonwealth Contracting Suite, ATO tax invoice rules) evaluated per invoice. "
      "result is pass, fail, or unknown when a field it needs could not be read.")

write(intake, "gold_intake",
      "doc_id STRING, doc_type STRING, arrival_ts TIMESTAMP_NTZ, arrival_date DATE, sender STRING, subject STRING, supplier_id STRING, "
      "supplier_name STRING, intent STRING, intent_label STRING, next_action STRING, summary STRING, referenced_invoices ARRAY<STRING>, "
      "linked_doc_ids ARRAY<STRING>, unmatched_invoices ARRAY<STRING>, bank_details_differ BOOLEAN, balance_due DOUBLE, "
      "overdue_amount DOUBLE, risk_flag STRING",
      "Statements, supplier correspondence and quotes: what they ask for, the invoices they refer to, and the next action.")

# COMMAND ----------

# Readiness: invoices paid each week, judged against today's terms and the 1 January 2027 terms.
# Workbench acceptances carry no payment date (payment happens downstream), so readiness is measured
# on the simulated history only.
paid = history[history["paid_date"].notna()].copy()
paid["week"] = pd.to_datetime(paid["paid_date"]).dt.to_period("W-SUN").dt.start_time.dt.date
paid = paid.merge(summary[["doc_id", "total_inc_gst"]], on="doc_id", how="left")
weekly = paid.groupby("week").agg(
    invoices_paid=("doc_id", "count"),
    late_current=("late_days_current", lambda s: int((s > 0).sum())),
    late_2027=("late_days_2027", lambda s: int((s > 0).sum())),
    interest_current=("interest_current", "sum"),
    value_paid=("total_inc_gst", "sum"),
).reset_index()
paid["bd_to_pay"] = [
    sum(1 for i in range(1, (pd.Timestamp(r.paid_date) - pd.Timestamp(r.trigger_date)).days + 1)
        if (dt.date.fromisoformat(str(r.trigger_date)[:10]) + dt.timedelta(days=i)).weekday() < 5
        and (dt.date.fromisoformat(str(r.trigger_date)[:10]) + dt.timedelta(days=i)) not in HOLIDAYS)
    for r in paid.itertuples()]
med = paid.groupby("week")["bd_to_pay"].median().rename("median_business_days_to_pay").reset_index()
weekly = weekly.merge(med, on="week")
weekly["pct_late_current"] = (100 * weekly["late_current"] / weekly["invoices_paid"]).round(1)
weekly["pct_late_2027"] = (100 * weekly["late_2027"] / weekly["invoices_paid"]).round(1)
write(weekly, "gold_readiness_weekly",
      "week DATE, invoices_paid INT, late_current INT, late_2027 INT, interest_current DOUBLE, value_paid DOUBLE, "
      "median_business_days_to_pay DOUBLE, pct_late_current DOUBLE, pct_late_2027 DOUBLE",
      "SIMULATED processing history: invoices paid per week, how many were late under the current RMG 417 terms, and how many "
      "would have been late under the 10-business-day terms from 1 January 2027. Indicates readiness; not real payment data.")

# COMMAND ----------

# Accuracy against ground truth (synthetic corpus only) and reviewer corrections.
tr = truth.set_index("doc_id")
acc = []
for _, r in fields.iterrows():
    if r["doc_id"] not in tr.index:
        continue
    true = json.loads(tr.loc[r["doc_id"], "truth_json"]).get(r["field"])
    expected = assess.canonical(r["field"], true)
    got = r["value"]
    if r["field"] in ("subtotal_ex_gst", "gst_amount", "total_inc_gst") and expected and got:
        match = abs((money(expected) or 0) - (money(got) or 0)) <= 0.01
    elif r["field"] in ("supplier_name", "recipient_name", "document_title"):
        # The extractor may carry the next address line ("... Accounts Payable"); the name still matches.
        e, g = assess.normalise_name(expected), assess.normalise_name(got)
        match = e == g or (bool(e) and bool(g) and (g.startswith(e) or e.startswith(g)))
    else:
        match = (expected or None) == (got or None)
    acc.append({"field": r["field"], "label": r["label"], "scanned": bool(tr.loc[r["doc_id"], "scanned"]), "match": match,
                "routed": bool(r["below_threshold"]), "routing_confidence": r["routing_confidence"], "doc_id": r["doc_id"]})
acc = pd.DataFrame(acc)
corrected = set()
if len(wb_cor):
    corrected = set(zip(wb_cor["doc_id"], wb_cor["field"]))
acc["corrected"] = [(d, f) in corrected for d, f in zip(acc["doc_id"], acc["field"])]
reviewed_docs = set(wb_dec["doc_id"]) if len(wb_dec) else set()
acc["reviewed"] = acc["doc_id"].isin(reviewed_docs)
agg = acc.groupby(["field", "label", "scanned"]).agg(
    fields=("match", "size"), matches_truth=("match", "sum"), routed_to_review=("routed", "sum"),
    mean_routing_confidence=("routing_confidence", "mean"), reviewed=("reviewed", "sum"), corrected_by_reviewer=("corrected", "sum"),
    wrong_but_not_routed=("match", lambda s: int(((~s) & (~acc.loc[s.index, "routed"])).sum())),
).reset_index()
agg["accuracy_pct"] = (100 * agg["matches_truth"] / agg["fields"]).round(1)
write(agg, "gold_extraction_accuracy",
      "field STRING, label STRING, scanned BOOLEAN, fields INT, matches_truth INT, routed_to_review INT, mean_routing_confidence DOUBLE, "
      "reviewed INT, corrected_by_reviewer INT, wrong_but_not_routed INT, accuracy_pct DOUBLE",
      "Extraction measured on the SYNTHETIC corpus: agreement with ground truth per field, split by scanned versus born-digital, how often "
      "the field was routed to review, how often a wrong value was NOT routed (the risk), and reviewer corrections from the workbench. "
      "Says nothing about real or degraded documents.")

det = summary[["doc_id", "status", "failed_checks"]].merge(truth[["doc_id", "defect", "expected_failed_check", "doc_type"]], on="doc_id")
# A late receipt (history) legitimately clears a no_receipt defect: only count it while no receipt exists.
receipted_docs = {r["doc_id"] for r in receipts}
det.loc[(det["defect"] == "no_receipt") & det["doc_id"].isin(receipted_docs), "expected_failed_check"] = None
det["caught"] = [(e is None) or (e in (f or [])) for e, f in zip(det["expected_failed_check"], det["failed_checks"])]
# A false alarm is a clean invoice the machine would send back to its supplier.
det["false_alarm"] = [(e is None) and s == "exception" for e, s in zip(det["expected_failed_check"], det["status"])]
detection = det.groupby("defect").agg(documents=("doc_id", "count"), caught=("caught", "sum"), false_alarms=("false_alarm", "sum"),
                                       to_exception=("status", lambda s: int((s == "exception").sum())),
                                       to_review=("status", lambda s: int((s == "needs_review").sum())),
                                       to_ready=("status", lambda s: int((s == "ready").sum()))).reset_index()
write(detection, "gold_check_detection",
      "defect STRING, documents INT, caught INT, false_alarms INT, to_exception INT, to_review INT, to_ready INT",
      "For each defect injected into the SYNTHETIC corpus: how many documents carried it, how many the checks caught, and where they were "
      "routed. 'none' rows count false alarms on clean invoices.")

cls = docs[["doc_id", "doc_type"]].merge(truth[["doc_id", "doc_type"]].rename(columns={"doc_type": "true_type"}), on="doc_id")
classification_accuracy = round(100 * float((cls["doc_type"] == cls["true_type"]).mean()), 1) if len(cls) else None

status = {
    "documents_landed": int(len(manifest)), "documents_parsed": int(classified["doc_id"].nunique()),
    "parse_errors": int(classified["parse_error"].notna().sum()), "documents_classified": int(classified["doc_type"].notna().sum()),
    "invoices_extracted": int(len(inv)), "invoices_assessed": int(len(summary)),
    "open_invoices": int((summary["queue_state"] == "open").sum()) if len(summary) else 0,
    "straight_through_pct": round(100 * float((summary["status"] == "ready").mean()), 1) if len(summary) else None,
    "classification_accuracy_pct": classification_accuracy,
    "last_arrival_ts": str(manifest["arrival_ts"].max()), "last_parsed_at": str(classified["parsed_at"].max()),
    "assessed_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "as_of": ctl.get("as_of"),
    "contracts_source": ctl.get("contracts_source"), "contracts_fetched_at": ctl.get("contracts_fetched_at"),
    "gic_rate": GIC, "gic_quarter": GIC_QUARTER_DEFAULT if abs(GIC - GIC_ANNUAL_RATE_DEFAULT) < 1e-9 else "custom",
    "review_threshold": REVIEW_THRESHOLD, "arrival_batches": int(ctl.get("arrival_batches", 0)),
}
write(pd.DataFrame([status]), "gold_pipeline_status",
      "documents_landed INT, documents_parsed INT, parse_errors INT, documents_classified INT, invoices_extracted INT, invoices_assessed INT, "
      "open_invoices INT, straight_through_pct DOUBLE, classification_accuracy_pct DOUBLE, last_arrival_ts STRING, last_parsed_at STRING, "
      "assessed_at STRING, as_of STRING, contracts_source STRING, contracts_fetched_at STRING, gic_rate DOUBLE, gic_quarter STRING, "
      "review_threshold DOUBLE, arrival_batches INT",
      "One row: volumes at each pipeline stage, straight-through rate, provenance of the contract data, and the interest rate in use.")

# COMMAND ----------

# Days left are computed when the queue is read, so the queue stays right without re-running this step.
spark.sql(f"""
CREATE OR REPLACE VIEW {t('gold_open_queue')}
COMMENT 'Open invoices with days left on the RMG 417 clock, computed at query time in Canberra local date. Exceptions and invoices awaiting delivery have no clock: it has not started.'
AS
WITH today AS (SELECT CAST(from_utc_timestamp(current_timestamp(), 'Australia/Sydney') AS DATE) AS d)
SELECT a.*,
       DATEDIFF(a.pay_by_date, today.d) AS calendar_days_left,
       cp.business_day_seq - ct.business_day_seq AS business_days_left,
       c2.business_day_seq - ct.business_day_seq AS business_days_left_2027,
       CASE WHEN a.pay_by_date IS NULL THEN 'not_started'
            WHEN a.pay_by_date < today.d THEN 'overdue'
            WHEN cp.business_day_seq - ct.business_day_seq <= 3 THEN 'due_soon'
            ELSE 'on_track' END AS clock_state,
       CASE WHEN a.pay_by_date < today.d THEN ROUND(a.total_inc_gst * {GIC} / 365 * DATEDIFF(today.d, a.pay_by_date), 2) ELSE 0 END AS interest_accrued
FROM {t('gold_invoice_assessment')} a
CROSS JOIN today
JOIN {t('ref_business_calendar')} ct ON ct.cal_date = today.d
LEFT JOIN {t('ref_business_calendar')} cp ON cp.cal_date = a.pay_by_date
LEFT JOIN {t('ref_business_calendar')} c2 ON c2.cal_date = a.pay_by_2027_date
WHERE a.queue_state = 'open'
""")
print("gold_open_queue view ready")
