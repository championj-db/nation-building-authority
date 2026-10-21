"""Databricks SQL access on behalf of the signed-in user.

Every Unity Catalog read runs through the Statement Execution API on the bound SQL
warehouse using the caseworker's forwarded OAuth token (`x-forwarded-access-token`),
so UC grants, row filters and column masks apply to the individual user. The app's
service principal is never used for UC data access.

Required app scope: `sql` (declared in resources/eligibility_workbench_app.yml).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.sql import (
    Disposition,
    Format,
    StatementParameterListItem,
    StatementState,
)
from fastapi import HTTPException, Request

from .config import settings

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="dbsql")
_host_config = Config()


class DataNotReadyError(RuntimeError):
    """Raised when the use case tables have not been created by the pipeline job yet."""


@dataclass(frozen=True)
class UserContext:
    token: str
    email: str
    username: str


def user_context(request: Request) -> UserContext:
    """Resolve the caller's identity and OBO token from Databricks Apps headers."""
    token = request.headers.get("x-forwarded-access-token", "")
    email = request.headers.get("x-forwarded-email", "")
    username = request.headers.get("x-forwarded-preferred-username", "") or email

    if not token:
        if settings.running_in_databricks_apps:
            # Never fall back to the service principal in a deployed app: that would
            # bypass per-user Unity Catalog governance.
            raise HTTPException(
                status_code=401,
                detail="User authorisation token missing. Confirm the app has the 'sql' user scope and that you consented on first sign-in.",
            )
        # Local development only: use the developer's own CLI credentials.
        auth_header = _host_config.authenticate().get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
        email = email or "local.developer"
        username = username or email
    return UserContext(token=token, email=email, username=username)


def _client(user: UserContext) -> WorkspaceClient:
    return WorkspaceClient(host=_host_config.host, token=user.token, auth_type="pat")


def current_user_display_name(user: UserContext) -> str:
    """Display name via SCIM /Me (covered by the implicit iam.current-user:read scope)."""
    try:
        me = _client(user).current_user.me()
        return me.display_name or me.user_name or user.username
    except Exception:  # noqa: BLE001 - identity enrichment is best effort
        log.warning("Could not resolve display name for %s", user.email)
        return user.username


def _convert(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    t = (type_name or "").upper()
    try:
        if t in ("INT", "LONG", "SHORT", "BYTE", "BIGINT", "INTEGER", "SMALLINT", "TINYINT"):
            return int(value)
        if t in ("DOUBLE", "FLOAT", "DECIMAL"):
            return float(value)
        if t == "BOOLEAN":
            return str(value).lower() == "true"
        if t in ("ARRAY", "STRUCT", "MAP"):
            return json.loads(value)
    except (ValueError, TypeError):
        return value
    return value


def query(user: UserContext, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterised statement as the user and return rows as dicts."""
    if not settings.warehouse_id:
        raise HTTPException(status_code=500, detail="DATABRICKS_WAREHOUSE_ID is not configured.")

    parameters = [
        StatementParameterListItem(name=k, value=None if v is None else str(v))
        for k, v in (params or {}).items()
    ]
    resp = _client(user).statement_execution.execute_statement(
        warehouse_id=settings.warehouse_id,
        statement=sql,
        parameters=parameters or None,
        wait_timeout="50s",
        disposition=Disposition.INLINE,
        format=Format.JSON_ARRAY,
    )
    state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        message = resp.status.error.message if resp.status and resp.status.error else str(state)
        if "TABLE_OR_VIEW_NOT_FOUND" in message or "SCHEMA_NOT_FOUND" in message:
            raise DataNotReadyError(message)
        if "PERMISSION_DENIED" in message or "INSUFFICIENT_PERMISSIONS" in message:
            raise HTTPException(status_code=403, detail=f"Unity Catalog denied access for {user.email}: {message}")
        raise HTTPException(status_code=502, detail=f"Query failed: {message}")

    columns = [(c.name, c.type_name.value if c.type_name else "STRING") for c in resp.manifest.schema.columns]
    rows: list[dict[str, Any]] = []
    chunk = resp.result
    while chunk is not None:
        for raw in chunk.data_array or []:
            rows.append({name: _convert(val, typ) for (name, typ), val in zip(columns, raw)})
        if not chunk.next_chunk_index:
            break
        chunk = _client(user).statement_execution.get_statement_result_chunk_n(
            resp.statement_id, chunk.next_chunk_index
        )
    return rows


def query_many(user: UserContext, statements: dict[str, tuple[str, dict[str, Any] | None]]) -> dict[str, list[dict]]:
    """Run independent statements concurrently (each still as the user)."""
    futures = {key: _executor.submit(query, user, sql, params) for key, (sql, params) in statements.items()}
    return {key: fut.result() for key, fut in futures.items()}
