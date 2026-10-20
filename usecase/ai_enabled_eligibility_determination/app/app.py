"""Eligibility Review Workbench — Databricks App.

A caseworker-facing application that presents the prioritised eligibility queue,
applicant 360, rules results, agent recommendations, evidence, and audit trail.
Human decisions are recorded back to the `decisions` table.

All environment-specific values come from environment variables — nothing is
hard-coded. See app.yaml for the configuration contract.
"""

import os
import uuid
from datetime import datetime

import gradio as gr
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

# ---------------------------------------------------------------------------
# Configuration from environment — no hard-coded catalog or schema.
# ---------------------------------------------------------------------------
CATALOG = os.environ["DATABRICKS_CATALOG"]
SCHEMA = os.environ.get("DATABRICKS_SCHEMA", "ai_enabled_eligibility_determination")


def fqn(table: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{table}"


# ---------------------------------------------------------------------------
# Data access via Databricks SDK (Statement Execution API).
# ---------------------------------------------------------------------------
w = WorkspaceClient()
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")


def _find_warehouse() -> str:
    """Find a warehouse to use, preferring the configured one."""
    if WAREHOUSE_ID:
        return WAREHOUSE_ID
    warehouses = list(w.warehouses.list())
    for wh in warehouses:
        if wh.state and wh.state.value == "RUNNING":
            return wh.id
    if warehouses:
        return warehouses[0].id
    raise RuntimeError("No SQL warehouse available.")


def run_query(sql: str) -> list[dict]:
    """Execute SQL and return rows as list of dicts."""
    wh_id = _find_warehouse()
    resp = w.statement_execution.execute_statement(
        warehouse_id=wh_id,
        statement=sql,
        wait_timeout="60s",
    )
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"Query failed: {resp.status.error}")
    columns = [col.name for col in resp.manifest.schema.columns]
    rows = []
    if resp.result and resp.result.data_array:
        for row_data in resp.result.data_array:
            rows.append(dict(zip(columns, row_data)))
    return rows


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def load_queue(filter_label: str = "All", search: str = "") -> list[dict]:
    sql = f"SELECT * FROM {fqn('caseworker_queue')} ORDER BY priority_score DESC"
    rows = run_query(sql)
    if filter_label and filter_label != "All":
        rows = [r for r in rows if r.get("queue_label") == filter_label]
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get("full_name") or "").lower()
                or s in (r.get("application_id") or "").lower()]
    return rows


def load_rules(application_id: str) -> list[dict]:
    sql = f"""
        SELECT rule_id, criterion_name, evaluation_type, result,
               policy_section, threshold_type, threshold_value, actual_value
        FROM {fqn('rules_results')}
        WHERE application_id = '{application_id}'
        ORDER BY rule_id
    """
    return run_query(sql)


def load_evidence(application_id: str) -> list[dict]:
    sql = f"""
        SELECT document_name, category, verification_status, summary
        FROM {fqn('evidence_documents')}
        WHERE application_id = '{application_id}'
    """
    return run_query(sql)


def load_audit(application_id: str) -> list[dict]:
    sql = f"""
        SELECT timestamp, event_type, description, detail, actor
        FROM {fqn('audit_trail')}
        WHERE application_id = '{application_id}'
        ORDER BY timestamp DESC
    """
    return run_query(sql)


def load_applicant_360(application_id: str) -> list[dict]:
    sql = f"""
        SELECT * FROM {fqn('applicant_360')}
        WHERE application_id = '{application_id}'
    """
    return run_query(sql)


# ---------------------------------------------------------------------------
# Decision recording
# ---------------------------------------------------------------------------
def save_decision(
    application_id: str,
    outcome: str,
    rationale: str,
    caseworker_name: str = "Demo Caseworker",
) -> str:
    decision_id = f"DEC-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch current agent verdict and rules outcome for the audit record.
    queue_rows = run_query(
        f"SELECT agent_verdict, rules_outcome FROM {fqn('caseworker_queue')} "
        f"WHERE application_id = '{application_id}' LIMIT 1"
    )
    agent_verdict = queue_rows[0].get("agent_verdict", "") if queue_rows else ""
    rules_outcome = queue_rows[0].get("rules_outcome", "") if queue_rows else ""

    insert_sql = f"""
        INSERT INTO {fqn('decisions')}
        (decision_id, application_id, caseworker_id, caseworker_name,
         outcome, rationale, decided_at, agent_verdict, rules_outcome)
        VALUES
        ('{decision_id}', '{application_id}', 'demo-user', '{caseworker_name}',
         '{outcome}', '{rationale}', '{now}', '{agent_verdict}', '{rules_outcome}')
    """
    run_query(insert_sql)

    # Also append to audit trail.
    evt_id = f"EVT-{application_id}-DEC-{uuid.uuid4().hex[:6].upper()}"
    audit_sql = f"""
        INSERT INTO {fqn('audit_trail')}
        (event_id, application_id, event_type, description, actor, detail, timestamp)
        VALUES
        ('{evt_id}', '{application_id}', 'human_decision',
         'Decision: {outcome}', '{caseworker_name}', '{rationale}', '{now}')
    """
    run_query(audit_sql)
    return f"Decision {decision_id} saved: {outcome}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def format_queue_card(row: dict) -> str:
    label = row.get("queue_label", "")
    badge_color = {"Urgent": "#dc2626", "Borderline": "#eab308", "Ready": "#3ba65e"}.get(label, "#6b7280")
    return (
        f"**{row.get('full_name', 'Unknown')}** "
        f"<span style='background:{badge_color};color:#fff;padding:2px 8px;"
        f"border-radius:12px;font-size:0.75rem;'>{label}</span>\n\n"
        f"`{row.get('application_id', '')}` \u00b7 {row.get('program_name', '')} "
        f"\u00b7 Priority: {row.get('priority_score', 0)}"
    )


def format_case_detail(row: dict) -> str:
    return (
        f"### {row.get('full_name', '')}\n"
        f"**Application** {row.get('application_id', '')} \u00b7 "
        f"{row.get('program_name', '')} \u00b7 Lodged {row.get('lodged_date', '')}\n\n"
        f"| Field | Value |\n|---|---|\n"
        f"| Household | {row.get('household_size', '')} members "
        f"({row.get('num_dependent_children', '')} children) |\n"
        f"| Income | ${row.get('monthly_income', '')} / month |\n"
        f"| Rent | ${row.get('weekly_rent', '')} / week "
        f"({'recent increase' if row.get('rent_increase_recent') == 'true' else 'stable'}) |\n"
        f"| Rent burden | {row.get('rent_burden_pct', 'N/A')}% |\n"
        f"| Residency | {row.get('residency_months', '')} months |\n"
        f"| Longest absence | {row.get('max_absence_days', '0')} days |\n"
    )


def format_rules(rules: list[dict]) -> str:
    lines = ["| Criterion | Result | Policy | Actual | Threshold |\n|---|---|---|---|---|"]
    for r in rules:
        icon = "\u2705" if r["result"] == "pass" else "\u26a0\ufe0f" if r["result"] == "needs_review" else "\u274c"
        lines.append(
            f"| {icon} {r['criterion_name']} | {r['result']} | {r['policy_section']} "
            f"| {r.get('actual_value', '')} | {r.get('threshold_value', '')} |"
        )
    return "\n".join(lines)


def format_recommendation(row: dict) -> str:
    verdict = row.get("agent_verdict") or "No recommendation (rules passed)"
    rec = row.get("agent_recommendation") or "All criteria passed deterministically."
    return (
        f"### System Recommendation\n\n"
        f"**{verdict}**\n\n{rec}\n\n"
        f"---\n*Recommendation only. Review the cited evidence and record your own decision.*"
    )


def format_evidence(evidence: list[dict]) -> str:
    lines = ["| Document | Category | Status | Summary |\n|---|---|---|---|"]
    for e in evidence:
        status_icon = "\u2705" if e["verification_status"] == "verified" else "\u26a0\ufe0f"
        lines.append(
            f"| {e['document_name']} | {e['category']} "
            f"| {status_icon} {e['verification_status']} | {e['summary']} |"
        )
    return "\n".join(lines)


def format_audit(events: list[dict]) -> str:
    lines = []
    for e in events:
        lines.append(
            f"**{e['event_type'].replace('_', ' ').title()}**\n"
            f"{e['description']}\n"
            f"`{e['timestamp']}` \u00b7 {e['actor']}\n\n---\n"
        )
    return "\n".join(lines) if lines else "No audit events."


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
def build_app():
    queue_data = []

    with gr.Blocks(
        title="Eligibility Review Workbench \u00b7 Nation Building Authority",
        theme=gr.themes.Base(
            primary_hue="neutral",
            neutral_hue="slate",
            font=["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        ),
        css="""
            .queue-item { cursor: pointer; padding: 12px; border-bottom: 1px solid #e5e7eb; }
            .queue-item:hover { background: #f5f5f5; }
        """,
    ) as app:
        gr.Markdown(
            "## \U0001f3db\ufe0f Nation Building Authority \u00b7 Eligibility Review Workbench\n"
            "Prioritised benefit applications with governed evidence, policy citations "
            "and rules assembled for authorised review."
        )

        with gr.Row():
            filter_dd = gr.Dropdown(
                choices=["All", "Urgent", "Borderline", "Ready", "Declined"],
                value="All", label="Filter", scale=1,
            )
            search_box = gr.Textbox(label="Search name or application ID", scale=2)
            refresh_btn = gr.Button("\u21bb Refresh queue", scale=1)

        with gr.Row():
            # Left panel: queue list
            with gr.Column(scale=1):
                queue_list = gr.Dataframe(
                    headers=["application_id", "full_name", "program_name",
                             "queue_label", "priority_score"],
                    label="Applications",
                    interactive=False,
                    wrap=True,
                )

            # Right panel: case detail
            with gr.Column(scale=2):
                selected_app_id = gr.State(value="")

                case_header = gr.Markdown("*Select an application from the queue.*")

                with gr.Tabs():
                    with gr.Tab("Review"):
                        with gr.Row():
                            with gr.Column(scale=2):
                                summary_md = gr.Markdown("")
                                rules_md = gr.Markdown("")
                            with gr.Column(scale=1):
                                recommendation_md = gr.Markdown("")

                    with gr.Tab("Applicant 360"):
                        applicant_360_md = gr.Markdown("")

                    with gr.Tab("Evidence"):
                        evidence_md = gr.Markdown("")

                    with gr.Tab("Audit Trail"):
                        audit_md = gr.Markdown("")

                gr.Markdown("### Record Decision")
                with gr.Row():
                    outcome_dd = gr.Dropdown(
                        choices=["Eligible", "Not eligible", "Request more information"],
                        label="Outcome", scale=1,
                    )
                    rationale_tb = gr.Textbox(
                        label="Decision rationale",
                        placeholder="Explain how the evidence and policy support your decision",
                        lines=3, scale=2,
                    )
                decision_btn = gr.Button("Save decision", variant="primary")
                decision_status = gr.Markdown("")

        # --- Event handlers ---
        def refresh_queue(filter_label, search):
            nonlocal queue_data
            queue_data = load_queue(filter_label, search)
            table = [
                [r.get("application_id", ""), r.get("full_name", ""),
                 r.get("program_name", ""), r.get("queue_label", ""),
                 r.get("priority_score", 0)]
                for r in queue_data
            ]
            return table

        def select_case(evt: gr.SelectData):
            if not queue_data:
                return "", "", "", "", "", "", ""
            row_idx = evt.index[0] if hasattr(evt.index, '__iter__') else evt.index
            if row_idx >= len(queue_data):
                return "", "", "", "", "", "", ""
            row = queue_data[row_idx]
            app_id = row.get("application_id", "")

            header = format_case_detail(row)
            rules = format_rules(load_rules(app_id))
            rec = format_recommendation(row)
            evidence = format_evidence(load_evidence(app_id))
            audit = format_audit(load_audit(app_id))

            a360_rows = load_applicant_360(app_id)
            a360_text = ""
            if a360_rows:
                a = a360_rows[0]
                a360_text = (
                    "### Applicant 360\n"
                    "Unified view assembled from governed source systems.\n\n"
                    "| Domain | Current Record | Source | Freshness |\n|---|---|---|---|\n"
                    f"| Identity | {'Verified' if a.get('identity_verified') == 'true' else 'Unverified'}"
                    f" \u00b7 {a.get('full_name', '')} | Identity registry "
                    f"| {a.get('identity_verified_date', '')} |\n"
                    f"| Household | {a.get('num_dependent_children', '')} dependent children "
                    f"| Birth registry | {a.get('household_verified_date', '')} |\n"
                    f"| Employment | {a.get('employment_type', '')} \u00b7 ${a.get('monthly_income', '')}/mo "
                    f"| Payroll reporting | {a.get('employment_verified_date', '')} |\n"
                    f"| Housing | {a.get('tenure_type', '')} \u00b7 ${a.get('weekly_rent', '')}/week "
                    f"| Lease + property feed | {a.get('housing_verified_date', '')} |\n"
                )

            return app_id, header, rules, rec, a360_text, evidence, audit

        def record_decision(app_id, outcome, rationale):
            if not app_id:
                return "No application selected."
            if not outcome:
                return "Please select an outcome."
            if not rationale:
                return "Please provide a rationale."
            return save_decision(app_id, outcome, rationale)

        refresh_btn.click(
            refresh_queue, inputs=[filter_dd, search_box], outputs=[queue_list],
        )
        filter_dd.change(
            refresh_queue, inputs=[filter_dd, search_box], outputs=[queue_list],
        )
        search_box.change(
            refresh_queue, inputs=[filter_dd, search_box], outputs=[queue_list],
        )
        queue_list.select(
            select_case,
            outputs=[selected_app_id, case_header, rules_md, recommendation_md,
                     applicant_360_md, evidence_md, audit_md],
        )
        decision_btn.click(
            record_decision,
            inputs=[selected_app_id, outcome_dd, rationale_tb],
            outputs=[decision_status],
        )

        # Auto-load queue on startup.
        app.load(refresh_queue, inputs=[filter_dd, search_box], outputs=[queue_list])

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(server_name="0.0.0.0", server_port=8000)
