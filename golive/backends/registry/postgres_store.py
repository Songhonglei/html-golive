"""golive.backends.registry.postgres_store — Postgres site registry.

Drop-in twin of :class:`golive.backends.registry.sqlite_store.SqliteRegistry`,
backed by a self-hosted PostgreSQL instance.  Reads the DSN from
``$GOLIVE_PG_DSN`` (configurable via ``registry.postgres_dsn_env`` in
golive.yaml).

Table:
  sites(site_id TEXT PK, name, slug UNIQUE, created_at, updated_at,
        owner, notes, editable, maintainers)

site_id: uuid4().hex — 32 hex chars.
slug is stored lowercase; empty slug allowed (site addressable via /s/<id>).
editable: BOOLEAN — whether the online editor is enabled for the site.
maintainers: JSONB array of emails allowed to edit besides the owner.

All 16 public methods have identical signatures and return types to the
SQLite registry.
"""

from __future__ import annotations
import datetime
import json
import uuid
from typing import Optional

from golive.backends._pg import pg_connect
from golive.backends.registry._sql_store import SQLRegistry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    site_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    slug        TEXT UNIQUE,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    owner       TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    editable    BOOLEAN NOT NULL DEFAULT FALSE,
    maintainers JSONB NOT NULL DEFAULT '[]'
);
"""

# columns added after v0.2 — migrated in-place for existing databases
_MIGRATIONS = [
    ("owner", "ALTER TABLE sites ADD COLUMN owner TEXT NOT NULL DEFAULT ''"),
    ("editable", "ALTER TABLE sites ADD COLUMN editable BOOLEAN NOT NULL DEFAULT FALSE"),
    ("maintainers", "ALTER TABLE sites ADD COLUMN maintainers JSONB NOT NULL DEFAULT '[]'"),
]


CREATE_TABLE_SQL = _SCHEMA

def _now() -> str:
    # Microseconds — same contract as the SQLite registry (see the note
    # there): touch() must always advance updated_at, even within one second.
    return datetime.datetime.now().isoformat(timespec="microseconds")


class PostgresRegistry(SQLRegistry):
    """RegistryBackend implementation (PostgreSQL)."""

    def __init__(self, dsn_env: str = ""):
        if not dsn_env:
            try:
                from golive.config import get_config
                cfg = get_config()
                dsn_env = cfg.registry.postgres_dsn_env or "GOLIVE_PG_DSN"
            except Exception:
                dsn_env = "GOLIVE_PG_DSN"
        self.dsn_env = dsn_env
        with self._conn() as c:
            c.execute(_SCHEMA)
            # column migration (idempotent — check information_schema)
            cols = {r["column_name"] for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sites'").fetchall()}
            for col, ddl in _MIGRATIONS:
                if col not in cols:
                    try:
                        c.execute(ddl)
                    except Exception:
                        pass  # column may already exist from CREATE TABLE
            c.commit()

    def _conn(self):
        return pg_connect(self.dsn_env)
