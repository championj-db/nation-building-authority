"""Shape pipeline outputs into the view models used by the workbench UI.

All copy is derived from real fields produced by src/02-05 so that the interface
matches the exported design without static placeholders.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Source system each rule threshold is evaluated against (mirrors src/02_applicant_360.py).
_THRESHOLD_SOURCES = {
    "income_max": "Payroll reporting · bank statements",
    "dependents_min": "Birth registry · application form",
    "rent_burden_pct": "Lease agreement · property feed",
    "residency_months_min": "Movement records · identity registry",
    "residency_years_min": "Movement records · identity registry",
    "age_range": "Identity registry",
    "relationship_valid": "Household composition",
    "activity_required": "Job-search records · provider reports",
    "medical_score_min": "Medical assessment report",
    "care_hours_min": "Care plan document",
    "disability_verified": "Medical panel report",
    "work_capacity_max": "Work capacity assessment",
}


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def money(v: Any) -> str:
    n = _num(v)
    return "—" if n is None else f"${n:,.0f}"


def short_date(v: Any) -> str:
    if not v:
        return "—"
    try:
        d = v if isinstance(v, (date, datetime)) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.strftime("%-d %b")
    except ValueError:
        return str(v)


def long_date(v: Any) -> str:
    if not v:
        return "—"
    try:
        d = v if isinstance(v, (date, datetime)) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.strftime("%-d %b %Y")
    except ValueError:
        return str(v)


def status_tokens(row: dict[str, Any]) -> list[str]:
    tokens = []
    if row.get("urgency") == "urgent":
        tokens.append("urgent")
    outcome = row.get("rules_outcome")
    if outcome == "borderline":
        tokens.append("borderline")
    elif outcome == "eligible":
        tokens.append("ready")
    elif outcome == "ineligible":
        tokens.append("declined")
    return tokens


def queue_summary(row: dict[str, Any]) -> str:
    failed = int(row.get("criteria_failed") or 0)
    review = int(row.get("criteria_needs_review") or 0)
    needs_context = int(row.get("evidence_needs_context") or 0)
    if failed:
        reason = f"{failed} {'criterion' if failed == 1 else 'criteria'} not met"
    elif review:
        reason = f"{review} {'criterion needs' if review == 1 else 'criteria need'} judgement"
    elif needs_context:
        reason = "Evidence needs context"
    else:
        reason = "Rules passed"
    return f"{row.get('application_id')} · {row.get('program_name')} · {reason}"


def queue_item(row: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "application_id": row.get("application_id"),
        "full_name": row.get("full_name"),
        "program_name": row.get("program_name"),
        "queue_label": row.get("queue_label"),
        "queue_status": row.get("queue_status"),
        "priority_score": row.get("priority_score"),
        "days_since_lodged": row.get("days_since_lodged"),
        "status_tokens": status_tokens(row),
        "summary": queue_summary(row),
        "decision": (
            {"outcome": decision["outcome"], "decided_at": decision["decided_at"].isoformat(), "by": decision.get("caseworker_name")}
            if decision
            else None
        ),
    }


def household_text(a: dict[str, Any]) -> str:
    adults = int(a.get("num_adults") or 0) or max(int(a.get("household_size") or 1) - int(a.get("num_dependent_children") or 0), 1)
    kids = int(a.get("num_dependent_children") or 0)
    adult_txt = f"{adults} adult{'s' if adults != 1 else ''}"
    if not kids:
        return adult_txt
    return f"{adult_txt}, {kids} {'child' if kids == 1 else 'children'}"


def criterion_view(r: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    result = r.get("result")
    t = r.get("threshold_type")
    actual = _num(r.get("actual_value"))
    threshold = _num(r.get("threshold_value"))
    note = None
    if result != "pass":
        if t == "rent_burden_pct":
            burden = _num(a.get("rent_burden_pct"))
            parts = [f"Rent burden {burden:.1f}% against a {threshold:.0f}% threshold." if burden is not None and threshold is not None else "Rent burden requires verification."]
            if a.get("rent_increase_recent") in (True, "true"):
                parts.append(
                    f"Lease shows a recent rent increase from {money(a.get('previous_weekly_rent'))} to {money(a.get('weekly_rent'))} per week not yet reflected in the property feed."
                )
            note = " ".join(parts)
        elif t in ("residency_months_min", "residency_years_min"):
            absence = int(a.get("max_absence_days") or 0)
            months = a.get("residency_months")
            note = f"{months} months recorded residency."
            if absence:
                reason = a.get("absence_reason")
                note += f" One {absence}-day absence{f' ({reason})' if reason else ''} requires a permitted-exception assessment."
        elif result == "fail" and actual is not None and threshold is not None:
            note = f"Recorded value {actual:,.0f} does not meet the threshold of {threshold:,.0f}."
        elif result == "needs_review":
            note = "Requires caseworker judgement against the cited policy."
    return {
        "rule_id": r.get("rule_id"),
        "criterion_name": r.get("criterion_name"),
        "result": result,
        "evaluation_type": r.get("evaluation_type"),
        "policy_section": r.get("policy_section"),
        "note": note,
        "citation": f"{_THRESHOLD_SOURCES.get(t, 'Source records')} · Policy {r.get('policy_section')} · Rule {r.get('rule_id')}",
        "actual_value": actual,
        "threshold_value": threshold,
    }


def applicant_360_rows(a: dict[str, Any]) -> list[dict[str, str]]:
    if not a:
        return []
    identity = f"{'Verified' if a.get('identity_verified') in (True, 'true') else 'Unverified'} · {a.get('full_name')}"
    if a.get("id_document_type"):
        identity += f" ({str(a['id_document_type']).replace('_', ' ')})"
    kids = int(a.get("num_dependent_children") or 0)
    household = f"{household_text(a)} · household of {a.get('household_size')}"
    if a.get("shared_custody") in (True, "true"):
        household += f" · shared custody {a.get('custody_pct')}%"
    employment = f"{str(a.get('employment_type') or 'Unknown').replace('_', ' ').capitalize()} · {money(a.get('monthly_income'))} / month"
    if a.get("income_variable") in (True, "true"):
        employment += " · variable hours"
    housing = f"{str(a.get('tenure_type') or 'Unknown').replace('_', ' ').capitalize()} · {money(a.get('weekly_rent'))}/week"
    if a.get("rent_increase_recent") in (True, "true"):
        housing += f" (was {money(a.get('previous_weekly_rent'))})"
    absence = int(a.get("max_absence_days") or 0)
    movement = f"{a.get('residency_months')} months residency" + (f" · longest absence {absence} days" if absence else " · no recorded absences")
    return [
        {"domain": "Identity", "record": identity, "source": "Identity registry", "freshness": short_date(a.get("identity_verified_date"))},
        {"domain": "Household", "record": household if kids or a.get("household_size") else "—", "source": "Birth registry", "freshness": short_date(a.get("household_verified_date"))},
        {"domain": "Employment", "record": employment, "source": "Payroll reporting", "freshness": short_date(a.get("employment_verified_date"))},
        {"domain": "Housing", "record": housing, "source": "Lease + property feed", "freshness": short_date(a.get("housing_verified_date"))},
        {"domain": "Movements", "record": movement, "source": "Movement records", "freshness": short_date(a.get("refreshed_at"))},
    ]


_SYSTEM_EVENT_TITLES = {
    "application_received": "Application received",
    "applicant_360_refreshed": "Applicant 360 refreshed",
    "rules_engine_completed": "Rules engine completed",
    "agent_recommendation_generated": "Agent recommendation generated",
    "human_decision": "Human decision recorded",
    "checklist_updated": "Review checklist updated",
    "record_downloaded": "Decision record downloaded",
}


def timeline(system_events: list[dict[str, Any]], app_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge pipeline (Unity Catalog) and human (Lakebase) events, newest first.

    `origin` keeps system activity and human activity visibly distinct, per the
    assurance requirement that suggestions and decisions are never conflated.
    """
    items = []
    for e in system_events:
        items.append({
            "title": _SYSTEM_EVENT_TITLES.get(e.get("event_type"), str(e.get("event_type", "")).replace("_", " ").capitalize()),
            "description": e.get("description"),
            "detail": e.get("detail"),
            "actor": e.get("actor") or "system",
            "origin": "human" if e.get("event_type") == "human_decision" else "system",
            "timestamp": str(e.get("timestamp")),
        })
    for e in app_events:
        items.append({
            "title": _SYSTEM_EVENT_TITLES.get(e.get("event_type"), e.get("event_type")),
            "description": e.get("description"),
            "detail": e.get("detail"),
            "actor": e.get("actor"),
            "origin": "human",
            "timestamp": e["created_at"].isoformat() if hasattr(e.get("created_at"), "isoformat") else str(e.get("created_at")),
        })

    def _key(item: dict[str, Any]) -> str:
        ts = item["timestamp"] or ""
        return ts.replace("T", " ")[:19]

    return sorted(items, key=_key, reverse=True)
