"""Manifests and per-site policies on SQLite — the contract reference.

Two tables, kept out of ``sites``: that table already carries nine columns
and these records have a different lifecycle. A manifest is rewritten on
every publish; a policy outlives any single publish and must survive one.

Separate tables also mean a page republished without ``--watermark`` keeps
the watermark its policy asks for, which is the behaviour 0.9.0 fixes.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from golive.backends.registry import _records as R
from golive.core.paths import get_registry_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS site_manifests (
    site_id        TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    content_sha256 TEXT NOT NULL DEFAULT '',
    source_type    TEXT NOT NULL DEFAULT 'unknown',
    injections     TEXT NOT NULL DEFAULT '[]',
    data_models    TEXT NOT NULL DEFAULT '[]',
    published_with TEXT NOT NULL DEFAULT '',
    published_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_policies (
    site_id           TEXT PRIMARY KEY,
    visibility        TEXT NOT NULL DEFAULT 'public',
    security_policy   TEXT NOT NULL DEFAULT 'baseline',
    watermark_enabled INTEGER NOT NULL DEFAULT 0,
    watermark_config  TEXT NOT NULL DEFAULT '{}',
    updated_at        TEXT NOT NULL DEFAULT '',
    updated_by        TEXT NOT NULL DEFAULT ''
);
"""


class SqliteManifests:
    """Manifest + policy storage for the SQLite registry backend."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or get_registry_db())
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── manifests ───────────────────────────────────────────────────────────

    def put_manifest(self, site_id: str, content_sha256: str = "",
                     source_type: str = "unknown", injections=None,
                     data_models=None, published_with: str = "") -> dict:
        """Record what a publish actually produced. Replaces any prior row."""
        row = R.manifest_row(
            site_id, content_sha256=content_sha256, source_type=source_type,
            injections=injections, data_models=data_models,
            published_with=published_with)
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO site_manifests (site_id, "
                "schema_version, content_sha256, source_type, injections, "
                "data_models, published_with, published_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (row["site_id"], row["schema_version"], row["content_sha256"],
                 row["source_type"], R.dump_json(row["injections"]),
                 R.dump_json(row["data_models"]), row["published_with"],
                 row["published_at"]))
        return row

    def get_manifest(self, site_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM site_manifests WHERE site_id = ?",
                          (site_id,)).fetchone()
        return R.manifest_from_db(dict(r)) if r else None

    def list_manifests(self, limit: int = 500) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM site_manifests ORDER BY published_at DESC "
                "LIMIT ?", (limit,)).fetchall()
        return [R.manifest_from_db(dict(r)) for r in rows]

    def delete_manifest(self, site_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM site_manifests WHERE site_id = ?",
                            (site_id,))
            return cur.rowcount > 0

    # ── policies ────────────────────────────────────────────────────────────

    def get_policy(self, site_id: str) -> dict:
        """Always returns a policy — defaults when no row exists."""
        with self._conn() as c:
            r = c.execute("SELECT * FROM site_policies WHERE site_id = ?",
                          (site_id,)).fetchone()
        return R.policy_from_db(dict(r) if r else None, site_id)

    def set_policy(self, site_id: str, visibility=None,
                   security_policy=None, watermark_enabled=None,
                   watermark_config=None, updated_by: str = "") -> dict:
        """Patch a policy. Unset arguments keep their current value.

        Merging rather than replacing matters: enabling a watermark must not
        reset visibility to the default, and the admin portal patches one
        field at a time.
        """
        current = self.get_policy(site_id)
        merged = dict(current)
        if visibility is not None:
            merged["visibility"] = visibility
        if security_policy is not None:
            merged["security_policy"] = security_policy
        if watermark_enabled is not None:
            merged["watermark_enabled"] = bool(watermark_enabled)
        if watermark_config is not None:
            merged["watermark_config"] = watermark_config
        merged["updated_at"] = R.now()
        merged["updated_by"] = updated_by or current.get("updated_by", "")
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO site_policies (site_id, visibility, "
                "security_policy, watermark_enabled, watermark_config, "
                "updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
                (site_id, merged["visibility"], merged["security_policy"],
                 1 if merged["watermark_enabled"] else 0,
                 R.dump_json(merged["watermark_config"]),
                 merged["updated_at"], merged["updated_by"]))
        # Re-read so validation in policy_from_db applies to what we return.
        return self.get_policy(site_id)

    def delete_policy(self, site_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM site_policies WHERE site_id = ?",
                            (site_id,))
            return cur.rowcount > 0
