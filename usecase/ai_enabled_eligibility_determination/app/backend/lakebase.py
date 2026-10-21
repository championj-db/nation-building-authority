"""Lakebase (Autoscaling Postgres) operational store.

Lakebase is the transactional system of record for the human side of the workflow:

* decisions         - append-only human determinations (never updated or deleted)
* review_checklist  - per caseworker, per application "Before deciding" state
* app_audit_events  - human actions taken in the workbench

The app connects as its own service principal (PGUSER, injected by the `lakebase` app
resource with CAN_CONNECT_AND_CREATE) and owns the schema it creates. Every row records
the OBO-resolved caseworker identity, so attribution never falls back to the service
principal. OAuth database credentials expire after ~1 hour, so a fresh credential is
minted for each new pooled connection and connections are recycled well before expiry.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

log = logging.getLogger(__name__)

OUTCOMES = ("Eligible", "Not eligible", "Request more information")
CHECKLIST_FIELDS = ("rules_reviewed", "citations_opened", "conflicts_resolved")

_sp_client: WorkspaceClient | None = None
_token_lock = threading.Lock()
_token: tuple[str, float] | None = None  # (token, expiry epoch seconds)


def _mint_token() -> str:
    """Return a cached Lakebase OAuth credential for the app service principal."""
    global _sp_client, _token
    with _token_lock:
        if _token and _token[1] - time.time() > 300:
            return _token[0]
        if _sp_client is None:
            _sp_client = WorkspaceClient()
        cred = _sp_client.postgres.generate_database_credential(endpoint=settings.lakebase_endpoint)
        _token = (cred.token, time.time() + 45 * 60)
        return cred.token


class _LakebaseConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any):  # type: ignore[override]
        kwargs["password"] = _mint_token()
        return super().connect(conninfo, **kwargs)


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()
_schema_ready = False


def configured() -> bool:
    return bool(settings.lakebase_endpoint and os.environ.get("PGHOST"))


def _get_pool() -> ConnectionPool:
    global _pool
    if not configured():
        raise RuntimeError("Lakebase is not configured (LAKEBASE_ENDPOINT / PGHOST missing).")
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                conninfo="",
                connection_class=_LakebaseConnection,
                kwargs={
                    "host": os.environ["PGHOST"],
                    "port": int(os.environ.get("PGPORT", "5432")),
                    "dbname": os.environ.get("PGDATABASE", "databricks_postgres"),
                    "user": os.environ["PGUSER"],
                    "sslmode": os.environ.get("PGSSLMODE", "require"),
                    "application_name": os.environ.get("PGAPPNAME", "eligibility-workbench"),
                    "row_factory": dict_row,
                },
                min_size=1,
                max_size=8,
                max_lifetime=40 * 60,  # recycle before the OAuth credential expires
                max_idle=10 * 60,
                check=ConnectionPool.check_connection,  # survives scale-to-zero wake-ups
                open=True,
            )
        return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    ensure_schema()
    with _get_pool().connection() as conn:
        yield conn


def ensure_schema() -> None:
    """Create the app-owned schema and tables (idempotent)."""
    global _schema_ready
    if _schema_ready:
        return
    s = settings.lakebase_schema
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS {s};

    CREATE TABLE IF NOT EXISTS {s}.decisions (
        decision_id          TEXT PRIMARY KEY,
        application_id       TEXT NOT NULL,
        applicant_name       TEXT,
        program_name         TEXT,
        outcome              TEXT NOT NULL CHECK (outcome IN ('Eligible', 'Not eligible', 'Request more information')),
        rationale            TEXT NOT NULL,
        caseworker_email     TEXT NOT NULL,
        caseworker_name      TEXT,
        agent_verdict        TEXT,
        rules_outcome        TEXT,
        ruleset_version      TEXT,
        agent_model_endpoint TEXT,
        checklist            JSONB,
        decided_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS decisions_application_idx ON {s}.decisions (application_id, decided_at DESC);

    CREATE TABLE IF NOT EXISTS {s}.review_checklist (
        application_id     TEXT NOT NULL,
        caseworker_email   TEXT NOT NULL,
        rules_reviewed     BOOLEAN NOT NULL DEFAULT FALSE,
        citations_opened   BOOLEAN NOT NULL DEFAULT FALSE,
        conflicts_resolved BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (application_id, caseworker_email)
    );

    CREATE TABLE IF NOT EXISTS {s}.app_audit_events (
        event_id       TEXT PRIMARY KEY,
        application_id TEXT NOT NULL,
        event_type     TEXT NOT NULL,
        description    TEXT NOT NULL,
        detail         TEXT,
        actor          TEXT NOT NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS app_audit_events_application_idx ON {s}.app_audit_events (application_id, created_at DESC);
    """
    with _get_pool().connection() as conn:
        conn.execute(ddl)
    _schema_ready = True
    log.info("Lakebase schema %s ready", s)


def _audit(cur: psycopg.Cursor, application_id: str, event_type: str, description: str, detail: str | None, actor: str) -> None:
    cur.execute(
        f"INSERT INTO {settings.lakebase_schema}.app_audit_events "
        "(event_id, application_id, event_type, description, detail, actor) VALUES (%s, %s, %s, %s, %s, %s)",
        (f"EVT-{uuid.uuid4().hex[:12].upper()}", application_id, event_type, description, detail, actor),
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
def record_decision(
    *,
    application_id: str,
    applicant_name: str | None,
    program_name: str | None,
    outcome: str,
    rationale: str,
    caseworker_email: str,
    caseworker_name: str,
    agent_verdict: str | None,
    rules_outcome: str | None,
    ruleset_version: str | None,
    agent_model_endpoint: str | None,
    checklist: dict[str, bool],
) -> dict[str, Any]:
    decision_id = f"DEC-{uuid.uuid4().hex[:10].upper()}"
    s = settings.lakebase_schema
    with connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {s}.decisions
                (decision_id, application_id, applicant_name, program_name, outcome, rationale,
                 caseworker_email, caseworker_name, agent_verdict, rules_outcome, ruleset_version,
                 agent_model_endpoint, checklist)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *""",
            (
                decision_id, application_id, applicant_name, program_name, outcome, rationale,
                caseworker_email, caseworker_name, agent_verdict, rules_outcome, ruleset_version,
                agent_model_endpoint, json.dumps(checklist),
            ),
        )
        row = cur.fetchone()
        _audit(
            cur,
            application_id,
            "human_decision",
            f"Human decision recorded: {outcome}",
            f"System recommended {agent_verdict or 'no recommendation'} · rules {rules_outcome or 'n/a'} · {decision_id}",
            caseworker_name or caseworker_email,
        )
    return row


def decisions_for(application_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            f"SELECT * FROM {settings.lakebase_schema}.decisions WHERE application_id = %s ORDER BY decided_at DESC",
            (application_id,),
        ).fetchall()


def latest_decisions() -> dict[str, dict[str, Any]]:
    """Latest decision per application (for queue badges)."""
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT ON (application_id) application_id, outcome, decided_at, caseworker_name
                FROM {settings.lakebase_schema}.decisions
                ORDER BY application_id, decided_at DESC"""
        ).fetchall()
    return {r["application_id"]: r for r in rows}


def recent_decisions(limit: int = 200) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            f"SELECT * FROM {settings.lakebase_schema}.decisions ORDER BY decided_at DESC LIMIT %s",
            (limit,),
        ).fetchall()


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------
def get_checklist(application_id: str, caseworker_email: str) -> dict[str, bool]:
    with connection() as conn:
        row = conn.execute(
            f"SELECT rules_reviewed, citations_opened, conflicts_resolved FROM {settings.lakebase_schema}.review_checklist "
            "WHERE application_id = %s AND caseworker_email = %s",
            (application_id, caseworker_email),
        ).fetchone()
    return {k: bool(row[k]) if row else False for k in CHECKLIST_FIELDS}


def set_checklist(application_id: str, caseworker_email: str, actor: str, updates: dict[str, bool]) -> dict[str, bool]:
    current = get_checklist(application_id, caseworker_email)
    changed = {k: v for k, v in updates.items() if k in CHECKLIST_FIELDS and current.get(k) != v}
    if not changed:
        return current
    merged = {**current, **changed}
    s = settings.lakebase_schema
    with connection() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {s}.review_checklist
                (application_id, caseworker_email, rules_reviewed, citations_opened, conflicts_resolved, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (application_id, caseworker_email) DO UPDATE SET
                  rules_reviewed = EXCLUDED.rules_reviewed,
                  citations_opened = EXCLUDED.citations_opened,
                  conflicts_resolved = EXCLUDED.conflicts_resolved,
                  updated_at = now()""",
            (application_id, caseworker_email, merged["rules_reviewed"], merged["citations_opened"], merged["conflicts_resolved"]),
        )
        labels = {
            "rules_reviewed": "Rules result reviewed",
            "citations_opened": "Policy citations opened",
            "conflicts_resolved": "Conflicting evidence resolved",
        }
        for k, v in changed.items():
            _audit(cur, application_id, "checklist_updated", f"{labels[k]} {'confirmed' if v else 'cleared'}", None, actor)
    return merged


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------
def record_event(application_id: str, event_type: str, description: str, detail: str | None, actor: str) -> None:
    with connection() as conn, conn.transaction(), conn.cursor() as cur:
        _audit(cur, application_id, event_type, description, detail, actor)


def events_for(application_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            f"SELECT * FROM {settings.lakebase_schema}.app_audit_events WHERE application_id = %s ORDER BY created_at DESC",
            (application_id,),
        ).fetchall()
