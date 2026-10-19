"""golive.backends.data.postgres_store — Postgres data layer.

Drop-in twin of :class:`golive.backends.data.sqlite_store.TemplateStore`,
backed by a self-hosted PostgreSQL instance.  Reads the DSN from
``$GOLIVE_PG_DSN`` (configurable via ``data.postgres_dsn_env`` in
golive.yaml).

The SQL dialect differences from the SQLite twin:

* Placeholder ``?`` → ``%s``
* ``content TEXT`` → ``content JSONB`` (queried natively, but
  ``_row_to_dict`` still returns a plain dict — the external contract
  is unchanged).
* ``INSERT OR REPLACE`` → ``INSERT ... ON CONFLICT ... DO UPDATE``
* ``LIKE ? ESCAPE`` → ``LIKE %s`` (Postgres default escape is
  backslash, matching SQLite's behaviour for ``%`` literals).

All 12 public methods have identical signatures and return types to the
SQLite store.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Optional

from golive.backends._pg import pg_connect, get_dsn
from golive.backends.data._sql_store import SQLTemplateStore

DEFAULT_TABLE = "golive_templates"

# Columns a caller (including the HTTP adapter) may filter/sort on.
FILTERABLE = ("id", "model_code", "name", "user_id", "version")
SORTABLE = ("sort_index", "created_at", "updated_at", "name", "model_code")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id          TEXT PRIMARY KEY,
    model_code  TEXT NOT NULL,
    name        TEXT NOT NULL,
    user_id     TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    content     JSONB NOT NULL DEFAULT '{{}}',
    version     TEXT NOT NULL DEFAULT '1.0.0',
    sort_index  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (model_code, name, user_id)
);
CREATE INDEX IF NOT EXISTS idx_{table}_model ON {table} (model_code);
"""

CREATE_TABLE_SQL = _SCHEMA  # exported for ``golive db init`` symmetry


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _valid_table(name: str) -> str:
    """Guard the only identifier we interpolate into SQL."""
    cleaned = (name or "").strip() or DEFAULT_TABLE
    if not cleaned.replace("_", "").isalnum():
        raise ValueError(f"invalid table name: {name!r} "
                         "(letters, digits and underscore only)")
    return cleaned


class TemplateStore(SQLTemplateStore):
    """CRUD for golive_templates on Postgres (self-hosted data backend)."""

    def __init__(self, dsn_env: str = "", table: str = ""):
        if not table or not dsn_env:
            try:
                from golive.config import get_config
                cfg = get_config()
            except Exception:  # noqa: BLE001 — stay usable without config
                cfg = None
            if not table and cfg is not None:
                table = cfg.data.templates_table or DEFAULT_TABLE
            if not dsn_env and cfg is not None:
                dsn_env = cfg.registry.postgres_dsn_env or "GOLIVE_PG_DSN"
        if not dsn_env:
            dsn_env = "GOLIVE_PG_DSN"
        self.dsn_env = dsn_env
        self.table = _valid_table(table)
        with self._conn() as c:
            c.execute(_SCHEMA.format(table=self.table))
            c.commit()

    def _conn(self):
        return pg_connect(self.dsn_env)
