"""Eligibility Review Workbench — Databricks App (FastAPI).

Caseworker-facing workbench for the AI-Enabled Eligibility Determination use case.

* Reads (queue, applicant 360, rules, evidence, policy, system audit trail) run on
  Databricks SQL **on behalf of the signed-in user** (scope: `sql`), so Unity Catalog
  governance applies per caseworker.
* Human actions (decisions, review checklist, app audit events) are written to
  **Lakebase** as the transactional system of record, attributed to the OBO identity.
* The UI in ./static is a direct port of design/eligibility-review-workbench.html.

All configuration is injected by the Declarative Automation Bundle; see
resources/eligibility_workbench_app.yml.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend import lakebase, presenters
from backend.config import settings
from backend.dbsql import DataNotReadyError, UserContext, current_user_display_name, query, query_many, user_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("eligibility-workbench")

STATIC_DIR = Path(__file__).parent / "static"
fqn = settings.fqn


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Prepare the Lakebase schema in the background so a cold (scaled-to-zero)
    # endpoint never blocks the app from becoming healthy.
    def _init() -> None:
        try:
            if lakebase.configured():
                lakebase.ensure_schema()
        except Exception:  # noqa: BLE001
            log.exception("Lakebase schema initialisation deferred; will retry on first use")

    threading.Thread(target=_init, daemon=True).start()
    yield


app = FastAPI(title="Eligibility Review Workbench", lifespan=lifespan)


@app.exception_handler(DataNotReadyError)
async def _data_not_ready(_: Request, exc: DataNotReadyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Eligibility data has not been produced yet. Run the eligibility determination job for this bundle target.",
            "code": "DATA_NOT_READY",
        },
    )


def _lakebase_safe(fn, default):
    """Read from Lakebase without failing the whole response if it is unavailable."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001
        log.exception("Lakebase read failed")
        return default, f"Lakebase unavailable: {exc.__class__.__name__}"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
_display_names: dict[str, str] = {}


def display_name(user: UserContext) -> str:
    if user.email not in _display_names:
        _display_names[user.email] = current_user_display_name(user)
    return _display_names[user.email]


@app.get("/api/me")
def me(user: UserContext = Depends(user_context)) -> dict[str, Any]:
    name = display_name(user)
    initials = "".join(p[0] for p in name.replace(".", " ").split()[:2]).upper() or "?"
    return {
        "email": user.email,
        "display_name": name,
        "initials": initials,
        "environment": settings.environment,
        "lakebase_configured": lakebase.configured(),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
_QUEUE_SQL = f"""
    SELECT application_id, full_name, program_id, program_name, lodged_date, urgency,
           queue_status, queue_label, priority_score, days_since_lodged, rules_outcome,
           criteria_passed, criteria_failed, criteria_needs_review, criteria_total,
           agent_verdict, evidence_count, evidence_verified, evidence_needs_context
    FROM {fqn('caseworker_queue')}
    ORDER BY priority_score DESC, application_id
"""


@app.get("/api/queue")
def get_queue(user: UserContext = Depends(user_context)) -> dict[str, Any]:
    rows = query(user, _QUEUE_SQL)
    latest, lb_error = _lakebase_safe(lakebase.latest_decisions, {})
    return {
        "items": [presenters.queue_item(r, latest.get(r["application_id"])) for r in rows],
        "lakebase_error": lb_error,
    }


@app.get("/api/queue/export")
def export_queue(user: UserContext = Depends(user_context)) -> Response:
    rows = query(user, _QUEUE_SQL)
    latest, _ = _lakebase_safe(lakebase.latest_decisions, {})
    buf = io.StringIO()
    fields = [
        "application_id", "full_name", "program_name", "lodged_date", "queue_label", "priority_score",
        "rules_outcome", "criteria_passed", "criteria_failed", "criteria_needs_review", "agent_verdict",
    ]
    writer = csv.writer(buf)
    writer.writerow(fields + ["human_decision", "decided_at"])
    for r in rows:
        d = latest.get(r["application_id"])
        writer.writerow([r.get(f) for f in fields] + [d["outcome"] if d else "", d["decided_at"].isoformat() if d else ""])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="eligibility-queue-{stamp}.csv"'},
    )


# ---------------------------------------------------------------------------
# Case detail
# ---------------------------------------------------------------------------
def _case_statements(application_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
    p = {"app_id": application_id}
    return {
        "queue": (f"SELECT * EXCEPT (criteria_detail) FROM {fqn('caseworker_queue')} WHERE application_id = :app_id", p),
        "a360": (f"SELECT * FROM {fqn('applicant_360')} WHERE application_id = :app_id", p),
        "rules": (
            f"""SELECT rule_id, criterion_name, evaluation_type, policy_section, result, ruleset_version,
                       threshold_type, threshold_value, actual_value, evaluated_at, program_id
                FROM {fqn('rules_results')} WHERE application_id = :app_id ORDER BY rule_id""",
            p,
        ),
        "evidence": (
            f"""SELECT document_id, document_name, document_type, category, submitted_date,
                       verification_status, summary
                FROM {fqn('evidence_documents')} WHERE application_id = :app_id ORDER BY document_id""",
            p,
        ),
        "policies": (
            f"""SELECT p.policy_id, p.section, p.title, p.text, p.version, p.effective_date
                FROM {fqn('policy_documents')} p
                JOIN {fqn('applications')} a ON a.program_id = p.program_id
                WHERE a.application_id = :app_id ORDER BY p.section""",
            p,
        ),
        "agent": (
            f"""SELECT verdict, agent_recommendation, model_endpoint, generated_at
                FROM {fqn('agent_recommendations')} WHERE application_id = :app_id""",
            p,
        ),
        "audit": (
            f"""SELECT event_id, event_type, description, detail, actor, timestamp
                FROM {fqn('audit_trail')} WHERE application_id = :app_id ORDER BY timestamp DESC""",
            p,
        ),
    }


def _load_case(user: UserContext, application_id: str) -> dict[str, Any]:
    data = query_many(user, _case_statements(application_id))
    if not data["queue"]:
        # Either the application does not exist or UC policies hide it from this user.
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found or not visible to you.")
    return data


def _case_view(user: UserContext, application_id: str) -> dict[str, Any]:
    data = _load_case(user, application_id)
    q = data["queue"][0]
    a = data["a360"][0] if data["a360"] else {}
    agent = data["agent"][0] if data["agent"] else None
    rules = data["rules"]
    ruleset = f"{rules[0]['program_id']}-{rules[0]['ruleset_version']}" if rules else None

    decisions, lb_err1 = _lakebase_safe(lambda: lakebase.decisions_for(application_id), [])
    app_events, lb_err2 = _lakebase_safe(lambda: lakebase.events_for(application_id), [])
    checklist, lb_err3 = _lakebase_safe(
        lambda: lakebase.get_checklist(application_id, user.email), {k: False for k in lakebase.CHECKLIST_FIELDS}
    )

    return {
        "application_id": application_id,
        "full_name": q.get("full_name"),
        "program_name": q.get("program_name"),
        "lodged_date": presenters.long_date(q.get("lodged_date")),
        "queue_label": q.get("queue_label"),
        "urgency": q.get("urgency"),
        "status_tokens": presenters.status_tokens(q),
        "rules_outcome": q.get("rules_outcome"),
        "refreshed_at": q.get("refreshed_at"),
        "summary": {
            "household": presenters.household_text(a or q),
            "income": f"{presenters.money(q.get('monthly_income'))} / month",
            "residence": f"{q.get('residency_months')} months {'verified' if q.get('identity_verified') in (True, 'true') else 'declared'}",
            "rent": f"{presenters.money(q.get('weekly_rent'))} / week",
            "rent_burden": f"{q.get('rent_burden_pct')}%" if q.get("rent_burden_pct") is not None else "—",
            "lodged_days": q.get("days_since_lodged"),
        },
        "ruleset": ruleset,
        "criteria": [presenters.criterion_view(r, a or q) for r in rules],
        "counts": {
            "passed": q.get("criteria_passed"),
            "failed": q.get("criteria_failed"),
            "review": q.get("criteria_needs_review"),
            "total": q.get("criteria_total"),
        },
        "recommendation": (
            {
                "verdict": agent.get("verdict"),
                "text": agent.get("agent_recommendation"),
                "model_endpoint": agent.get("model_endpoint"),
                "generated_at": agent.get("generated_at"),
            }
            if agent
            else None
        ),
        "applicant_360": presenters.applicant_360_rows(a),
        "evidence": data["evidence"],
        "policies": data["policies"],
        "timeline": presenters.timeline(data["audit"], app_events),
        "decisions": decisions,
        "checklist": checklist,
        "lakebase_error": lb_err1 or lb_err2 or lb_err3,
    }


@app.get("/api/cases/{application_id}")
def get_case(application_id: str, user: UserContext = Depends(user_context)) -> JSONResponse:
    return JSONResponse(jsonable_encoder(_case_view(user, application_id)))


@app.get("/api/cases/{application_id}/record")
def download_record(application_id: str, user: UserContext = Depends(user_context)) -> Response:
    view = _case_view(user, application_id)
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": user.email,
        "notice": "System recommendations and human decisions are recorded separately. Recommendations are not determinations.",
        **view,
    }
    _lakebase_safe(
        lambda: lakebase.record_event(application_id, "record_downloaded", "Decision record downloaded", None, display_name(user)),
        None,
    )
    return Response(
        content=json.dumps(jsonable_encoder(record), indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{application_id}-decision-record.json"'},
    )


class ChecklistUpdate(BaseModel):
    rules_reviewed: bool | None = None
    citations_opened: bool | None = None
    conflicts_resolved: bool | None = None


@app.put("/api/cases/{application_id}/checklist")
def update_checklist(application_id: str, body: ChecklistUpdate, user: UserContext = Depends(user_context)) -> dict[str, bool]:
    # Confirms the caller can see the case under their own UC permissions before writing.
    if not query(user, f"SELECT 1 FROM {fqn('caseworker_queue')} WHERE application_id = :app_id", {"app_id": application_id}):
        raise HTTPException(status_code=404, detail="Application not found or not visible to you.")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return lakebase.set_checklist(application_id, user.email, display_name(user), updates)
    except Exception as exc:  # noqa: BLE001
        log.exception("Checklist update failed")
        raise HTTPException(status_code=503, detail=f"Could not save checklist to Lakebase: {exc}") from exc


class DecisionIn(BaseModel):
    outcome: str
    rationale: str = Field(min_length=20, max_length=5000)

    @field_validator("outcome")
    @classmethod
    def _valid_outcome(cls, v: str) -> str:
        if v not in lakebase.OUTCOMES:
            raise ValueError(f"Outcome must be one of: {', '.join(lakebase.OUTCOMES)}")
        return v

    @field_validator("rationale")
    @classmethod
    def _trim(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 20:
            raise ValueError("Rationale must explain the decision (at least 20 characters).")
        return v


@app.post("/api/cases/{application_id}/decision")
def record_decision(application_id: str, body: DecisionIn, user: UserContext = Depends(user_context)) -> JSONResponse:
    # Snapshot the system state the caseworker saw, read under their own permissions,
    # so the decision record is reproducible and independent of client input.
    snap = query_many(
        user,
        {
            "queue": (
                f"SELECT full_name, program_name, agent_verdict, rules_outcome FROM {fqn('caseworker_queue')} WHERE application_id = :app_id",
                {"app_id": application_id},
            ),
            "rules": (
                f"SELECT first(program_id) AS program_id, first(ruleset_version) AS ruleset_version FROM {fqn('rules_results')} WHERE application_id = :app_id",
                {"app_id": application_id},
            ),
            "agent": (
                f"SELECT model_endpoint FROM {fqn('agent_recommendations')} WHERE application_id = :app_id",
                {"app_id": application_id},
            ),
        },
    )
    if not snap["queue"]:
        raise HTTPException(status_code=404, detail="Application not found or not visible to you.")
    q = snap["queue"][0]
    r = snap["rules"][0] if snap["rules"] else {}
    checklist, _ = _lakebase_safe(lambda: lakebase.get_checklist(application_id, user.email), {})
    try:
        row = lakebase.record_decision(
            application_id=application_id,
            applicant_name=q.get("full_name"),
            program_name=q.get("program_name"),
            outcome=body.outcome,
            rationale=body.rationale,
            caseworker_email=user.email,
            caseworker_name=display_name(user),
            agent_verdict=q.get("agent_verdict"),
            rules_outcome=q.get("rules_outcome"),
            ruleset_version=f"{r.get('program_id')}-{r.get('ruleset_version')}" if r.get("ruleset_version") else None,
            agent_model_endpoint=snap["agent"][0]["model_endpoint"] if snap["agent"] else None,
            checklist=checklist,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Decision write failed")
        raise HTTPException(status_code=503, detail=f"Decision was not saved: Lakebase unavailable ({exc.__class__.__name__}).") from exc
    return JSONResponse(jsonable_encoder(row))


# ---------------------------------------------------------------------------
# Policy library and audit views
# ---------------------------------------------------------------------------
@app.get("/api/policies")
def get_policies(user: UserContext = Depends(user_context)) -> list[dict[str, Any]]:
    return query(
        user,
        f"""SELECT p.policy_id, p.program_id, coalesce(n.program_name, p.program_id) AS program_name,
                   p.version, p.section, p.title, p.text, p.effective_date
            FROM {fqn('policy_documents')} p
            LEFT JOIN (SELECT DISTINCT program_id, program_name FROM {fqn('applications')}) n
              ON n.program_id = p.program_id
            ORDER BY program_name, p.section""",
    )


@app.get("/api/decisions")
def get_decisions(user: UserContext = Depends(user_context)) -> dict[str, Any]:
    # Only surface decisions for applications the caller can see in Unity Catalog.
    visible = {r["application_id"] for r in query(user, f"SELECT application_id FROM {fqn('caseworker_queue')}")}
    rows, lb_error = _lakebase_safe(lakebase.recent_decisions, [])
    items = [
        {**r, "agrees_with_system": _agrees(r.get("outcome"), r.get("agent_verdict"), r.get("rules_outcome"))}
        for r in rows
        if r["application_id"] in visible
    ]
    return jsonable_encoder({"items": items, "lakebase_error": lb_error})


def _agrees(outcome: str | None, verdict: str | None, rules_outcome: str | None) -> bool | None:
    expected = None
    if verdict:
        expected = {"Likely eligible": "Eligible", "Likely not eligible": "Not eligible", "Request more information": "Request more information"}.get(verdict)
    elif rules_outcome:
        expected = {"eligible": "Eligible", "ineligible": "Not eligible"}.get(rules_outcome)
    return None if expected is None else expected == outcome


# ---------------------------------------------------------------------------
# Static UI
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
