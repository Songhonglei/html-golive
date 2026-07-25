"""golive.backends.registry.sqlite_store — SQLite site registry.

Table:
  sites(site_id TEXT PK, name, slug UNIQUE, created_at, updated_at,
        owner, notes)

site_id: uuid4().hex — 32 hex chars.
slug is stored lowercase; empty slug allowed (site addressable via /s/<id>).
"""

import datetime
import sqlite3
import uuid
from typing import Optional

from golive.core.paths import get_registry_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    site_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    slug       TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    owner      TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class SqliteRegistry:
    """RegistryBackend reference implementation (SQLite)."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or get_registry_db())
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── create / update ─────────────────────────────────────────────────────

    def create(self, name: str, slug: str = "", owner: str = "",
               notes: str = "") -> dict:
        site_id = uuid.uuid4().hex
        slug_norm = slug.strip().lower() or None
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sites (site_id, name, slug, created_at, "
                "updated_at, owner, notes) VALUES (?,?,?,?,?,?,?)",
                (site_id, name, slug_norm, now, now, owner, notes))
        return self.get(site_id)

    def update(self, site_id: str, name=None, slug=None, notes=None) -> dict:
        fields, values = ["updated_at = ?"], [_now()]
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if slug is not None:
            fields.append("slug = ?")
            values.append(slug.strip().lower() or None)
        if notes is not None:
            fields.append("notes = ?")
            values.append(notes)
        values.append(site_id)
        with self._conn() as c:
            cur = c.execute(
                f"UPDATE sites SET {', '.join(fields)} WHERE site_id = ?",
                values)
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")
        return self.get(site_id)

    def touch(self, site_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sites SET updated_at = ? WHERE site_id = ?",
                      (_now(), site_id))

    def delete(self, site_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM sites WHERE site_id = ?", (site_id,))
            return cur.rowcount > 0

    # ── query ───────────────────────────────────────────────────────────────

    def get(self, site_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE site_id = ?",
                            (site_id,)).fetchone()
        return dict(row) if row else None

    def get_by_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE slug = ?",
                            (slug.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def resolve(self, ref: str) -> Optional[dict]:
        """Resolve a site by id or slug."""
        return self.get(ref) or self.get_by_slug(ref)

    def list_all(self, limit: int = 200) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM sites ORDER BY updated_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def slug_taken(self, slug: str, exclude_site_id: str = "") -> bool:
        site = self.get_by_slug(slug)
        if site is None:
            return False
        return site["site_id"] != exclude_site_id
