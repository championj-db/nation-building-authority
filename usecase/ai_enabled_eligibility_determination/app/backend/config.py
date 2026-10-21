"""Runtime configuration.

Every environment-specific value is injected at runtime from app resources declared in the
Declarative Automation Bundle (resources/eligibility_workbench_app.yml). Nothing is hard-coded.

Catalog and schema resolve from DATABRICKS_CATALOG / DATABRICKS_SCHEMA when set, otherwise from
DATABRICKS_VOLUME, the bound landing volume. App volume resources expose the volume path
(/Volumes/<catalog>/<schema>/<volume>); a dotted catalog.schema.volume name is also accepted.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_\-]+$")


def _identifier(name: str, value: str) -> str:
    """Guard identifiers that are interpolated into SQL (catalog/schema names)."""
    if not value or not _IDENTIFIER.match(value):
        raise RuntimeError(f"Environment variable {name} is missing or not a valid identifier: {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    warehouse_id: str
    lakebase_endpoint: str
    lakebase_schema: str
    environment: str
    running_in_databricks_apps: bool

    def fqn(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{_identifier('table', table)}`"


def _catalog_and_schema() -> tuple[str, str]:
    catalog = os.environ.get("DATABRICKS_CATALOG", "")
    schema = os.environ.get("DATABRICKS_SCHEMA", "")
    volume = os.environ.get("DATABRICKS_VOLUME", "")
    if (not catalog or not schema) and volume:
        v = volume.strip().replace("`", "")
        if v.startswith("/"):
            # /Volumes/<catalog>/<schema>/<volume>[/...]
            segments = [p for p in v.split("/") if p]
            parts = segments[1:4] if segments and segments[0] == "Volumes" else []
        else:
            parts = v.split(".")
        if len(parts) == 3:
            catalog = catalog or parts[0]
            schema = schema or parts[1]
    if not catalog or not schema:
        raise RuntimeError(
            "Could not resolve catalog/schema: set DATABRICKS_CATALOG and DATABRICKS_SCHEMA, "
            f"or bind the landing volume as DATABRICKS_VOLUME (got DATABRICKS_VOLUME={volume!r})"
        )
    return (
        _identifier("DATABRICKS_CATALOG", catalog),
        _identifier("DATABRICKS_SCHEMA", schema),
    )


def load_settings() -> Settings:
    catalog, schema = _catalog_and_schema()
    return Settings(
        catalog=catalog,
        schema=schema,
        warehouse_id=os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
        lakebase_endpoint=os.environ.get("LAKEBASE_ENDPOINT", ""),
        lakebase_schema=_identifier("LAKEBASE_SCHEMA", os.environ.get("LAKEBASE_SCHEMA", "eligibility_workbench")).replace("-", "_"),
        environment=os.environ.get("APP_ENVIRONMENT", "dev"),
        # DATABRICKS_APP_NAME is injected by the Databricks Apps runtime.
        running_in_databricks_apps=bool(os.environ.get("DATABRICKS_APP_NAME")),
    )


settings = load_settings()
