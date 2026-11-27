# Databricks notebook source
# MAGIC %md
# MAGIC # 04 Accounts Payable Genie space
# MAGIC
# MAGIC Creates or updates a Genie space over the gold layer so AP officers and team leads can ask
# MAGIC questions in plain English ("which invoices are due this week?", "who has an invoice we
# MAGIC returned twice?"). The workbench embeds it as its Ask panel.
# MAGIC
# MAGIC * Only gold tables and the contract register are exposed. Extracted bank details and the vendor
# MAGIC   master are deliberately left out.
# MAGIC * Every example SQL runs against the current tables before publishing, so a schema change fails
# MAGIC   this task rather than shipping a broken space.
# MAGIC * Idempotent: the space id is kept in `corpus_control`; re-runs update the same space.

# COMMAND ----------

import json
import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_found = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _found is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _found)

from databricks.sdk import WorkspaceClient  # noqa: E402

from common import fq, get_params  # noqa: E402

p = get_params({"catalog": "", "schema": "", "warehouse_id": "", "space_title": "Accounts Payable Genie - Document Assurance"}, dbutils)
CATALOG, SCHEMA, WAREHOUSE, TITLE = p["catalog"], p["schema"], p["warehouse_id"], p["space_title"]
if not WAREHOUSE:
    dbutils.notebook.exit("no warehouse_id supplied; Genie space not created")
t = lambda name: fq(CATALOG, SCHEMA, name).replace("`", "")  # noqa: E731
TABLES = ["gold_open_queue", "gold_invoice_assessment", "gold_invoice_checks", "gold_documents", "gold_intake",
          "gold_readiness_weekly", "gold_check_detection", "gold_pipeline_status", "ref_contracts"]

INSTRUCTIONS = """You answer questions from accounts payable (AP) officers and team leads at the Nation Building Authority, an Australian Government entity, about supplier documents in the AP inbox.

Payment terms (Supplier Pay On-Time or Pay Interest Policy, RMG 417): the payment clock starts the day after BOTH delivery is acknowledged AND a correctly rendered invoice is received (trigger_date). Until 31 December 2026 the term is 20 calendar days (5 for Peppol e-invoices). From 1 January 2027 it is 10 business days for all invoices. pay_by_date applies the terms in force on the trigger date; pay_by_2027_date applies the 2027 terms. Late payment accrues interest at the ATO general interest charge rate, payable when it exceeds $100.

For anything about what is open, due, overdue or at risk, use gold_open_queue: it has calendar_days_left, business_days_left and clock_state ('overdue', 'due_soon' = 3 business days or fewer, 'on_track', 'not_started'). 'Due this week' means business_days_left between 0 and 5. Exceptions and invoices awaiting delivery have no clock (clock_state = 'not_started').

status values: 'ready' (all checks passed, fields confident: ready to accept), 'needs_review' (a required field is below the confidence threshold, or a check could not be evaluated), 'exception' (a correctly rendered check failed: it should go back to the supplier), 'awaiting_delivery' (no goods receipt yet). Machine status is a recommendation; decisions are in decision / decision_source. decision_source = 'simulated_history' is synthetic history, not a real decision.

failed_checks is an array of check codes; gold_invoice_checks has one row per check with label, detail and result ('pass', 'fail', 'unknown'). Check codes: addressed_to_buyer, tax_invoice_label, supplier_abn_valid, supplier_abn_matches_vendor, recipient_identity, po_quoted, po_matches, gst_calculated, within_po_value, not_duplicate, delivery_acknowledged.

gold_intake holds supplier statements, letters and quotes. A bank details change request (intent = 'bank_details_change') must never be actioned from the letter; say so when asked.

Money is AUD including GST unless the column says ex_gst. Dates are Canberra local dates. All data is synthetic; contracts come from public AusTender notices with suppliers replaced. Always say which status or clock filter you applied."""

EXAMPLES = [
    ("Which invoices are due in the next five business days?",
     f"""SELECT doc_id, supplier_name, invoice_number, total_inc_gst, status_label, pay_by_date, business_days_left
FROM {t('gold_open_queue')}
WHERE clock_state IN ('due_soon', 'on_track') AND business_days_left BETWEEN 0 AND 5
ORDER BY business_days_left, total_inc_gst DESC"""),
    ("Which open invoices are overdue and what interest has accrued?",
     f"""SELECT doc_id, supplier_name, invoice_number, total_inc_gst, pay_by_date, calendar_days_left, interest_accrued
FROM {t('gold_open_queue')}
WHERE clock_state = 'overdue'
ORDER BY calendar_days_left"""),
    ("Why are invoices being sent back to suppliers?",
     f"""SELECT c.label AS failed_check, COUNT(*) AS invoices
FROM {t('gold_invoice_checks')} c
JOIN {t('gold_invoice_assessment')} a ON a.doc_id = c.doc_id
WHERE c.result = 'fail' AND c.supplier_fault AND a.status = 'exception'
GROUP BY c.label
ORDER BY invoices DESC"""),
    ("How ready are we for the 10 business day terms?",
     f"""SELECT week, invoices_paid, pct_late_current, pct_late_2027, median_business_days_to_pay
FROM {t('gold_readiness_weekly')}
ORDER BY week"""),
    ("Which suppliers have asked to change their bank details?",
     f"""SELECT doc_id, arrival_date, supplier_name, bank_details_differ, risk_flag
FROM {t('gold_intake')}
WHERE intent = 'bank_details_change'
ORDER BY arrival_date DESC"""),
    ("How much is waiting in the queue by status?",
     f"""SELECT status_label, COUNT(*) AS invoices, ROUND(SUM(total_inc_gst), 2) AS value_inc_gst
FROM {t('gold_open_queue')}
GROUP BY status_label
ORDER BY invoices DESC"""),
]
SAMPLE_QUESTIONS = [
    "Which invoices are due in the next five business days?",
    "Why are invoices being sent back to suppliers?",
    "How ready are we for the 10 business day terms?",
    "Which suppliers have asked to change their bank details?",
    "Which contracts have the most invoices waiting for delivery to be acknowledged?",
]

for q, sql in EXAMPLES:
    n = spark.sql(sql).count()
    print(f"{n:>4} rows  {q}")

# COMMAND ----------


def hex_id(prefix: int, i: int) -> str:
    return f"{prefix}{i:031d}"


space = {
    "version": 2,
    "config": {"sample_questions": [{"id": hex_id(1, i), "question": [q]} for i, q in enumerate(SAMPLE_QUESTIONS, 1)]},
    "data_sources": {"tables": [{"identifier": t(x)} for x in sorted(TABLES)]},
    "instructions": {
        "text_instructions": [{"id": hex_id(3, 1), "content": [line + "\n" for line in INSTRUCTIONS.split("\n")]}],
        "example_question_sqls": [{"id": hex_id(2, i), "question": [q], "sql": [line + "\n" for line in sql.split("\n")]}
                                  for i, (q, sql) in enumerate(EXAMPLES, 1)],
    },
}
description = ("Ask about supplier invoices in the AP inbox: what is due, what failed the correctly rendered checks, and readiness "
               "for the 1 January 2027 payment terms. Synthetic documents; contracts from public AusTender data, pseudonymised.")


def get_control(key):
    rows = spark.sql(f"SELECT value FROM {fq(CATALOG, SCHEMA, 'corpus_control')} WHERE key = '{key}'").collect()
    return json.loads(rows[0].value) if rows else None


def set_control(key, value):
    spark.sql(f"MERGE INTO {fq(CATALOG, SCHEMA, 'corpus_control')} c USING (SELECT '{key}' AS key, '{json.dumps(value)}' AS value) s "
              "ON c.key = s.key WHEN MATCHED THEN UPDATE SET value = s.value WHEN NOT MATCHED THEN INSERT *")


w = WorkspaceClient()
space_id = get_control("genie_space_id")
existing = None
if space_id:
    try:
        existing = w.genie.get_space(space_id)
    except Exception as e:  # noqa: BLE001  deleted or no longer accessible: recreate
        print(f"stored space {space_id} not available ({type(e).__name__}); recreating")
        existing = None
if not existing:
    token = None
    while True:
        page = w.genie.list_spaces(page_size=100, page_token=token)
        existing = next((s for s in (page.spaces or []) if s.title == TITLE), None)
        token = page.next_page_token
        if existing or not token:
            break
    if existing:
        space_id = existing.space_id
if existing:
    w.genie.update_space(space_id, serialized_space=json.dumps(space), title=TITLE, description=description, warehouse_id=WAREHOUSE)
    print(f"updated Genie space {space_id}")
else:
    created = w.genie.create_space(warehouse_id=WAREHOUSE, serialized_space=json.dumps(space), title=TITLE, description=description)
    space_id = created.space_id
    print(f"created Genie space {space_id}")
set_control("genie_space_id", space_id)
dbutils.jobs.taskValues.set("genie_space_id", space_id)
