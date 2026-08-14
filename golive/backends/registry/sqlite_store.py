"""golive.backends.registry.sqlite_store — SQLite site registry.

Table:
  sites(site_id TEXT PK, name, slug UNIQUE, created_at, updated_at,
        owner, notes, editable, maintainers)

site_id: uuid4().hex — 32 hex chars.
slug is stored lowercase; empty slug allowed (site addressable via /s/<id>).
editable: 0/1 — whether the online editor is enabled for the site (M3).
maintainers: JSON array of emails allowed to edit besides the owner (M3).
"""


from __future__ import annotations
import datetime
import json
import sqlite3
import uuid
from typing import Optional

from golive.core.paths import get_registry_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    site_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    slug        TEXT UNIQUE,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    owner       TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    editable    INTEGER NOT NULL DEFAULT 0,
    maintainers TEXT NOT NULL DEFAULT '[]'
);
"""

# columns added after v0.2 — migrated in-place for existing databases
_MIGRATIONS = [
    ("owner", "ALTER TABLE sites ADD COLUMN owner TEXT NOT NULL DEFAULT ''"),
    ("editable", "ALTER TABLE sites ADD COLUMN editable INTEGER NOT NULL DEFAULT 0"),
    ("maintainers", "ALTER TABLE sites ADD COLUMN maintainers TEXT NOT NULL DEFAULT '[]'"),
]


def _now() -> str:
    # Microseconds, not seconds: touch() promises the timestamp moves, and a
    # create()+touch() inside the same second must still produce a new value.
    # ISO-8601 strings stay lexicographically sortable either way, so existing
    # second-precision rows keep ordering correctly against new ones.
    return datetime.datetime.now().isoformat(timespec="microseconds")


class SqliteRegistry:
    """RegistryBackend reference implementation (SQLite)."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or get_registry_db())
        with self._conn() as c:
            c.executescript(_SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(sites)")}
            for col, ddl in _MIGRATIONS:
                if col not in cols:
                    c.execute(ddl)

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

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        raw = d.get("maintainers", "[]")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            d["maintainers"] = parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            d["maintainers"] = []
        d["editable"] = bool(d.get("editable", 0))
        return d

    def get(self, site_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE site_id = ?",
                            (site_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE slug = ?",
                            (slug.strip().lower(),)).fetchone()
        return self._row_to_dict(row) if row else None

    def resolve(self, ref: str) -> Optional[dict]:
        """Resolve a site by id or slug."""
        return self.get(ref) or self.get_by_slug(ref)

    def list_all(self, limit: int = 200) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM sites ORDER BY updated_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def slug_taken(self, slug: str, exclude_site_id: str = "") -> bool:
        site = self.get_by_slug(slug)
        if site is None:
            return False
        return site["site_id"] != exclude_site_id

    # ── editor mode / maintainers (M3) ──────────────────────────────────────

    def set_editable(self, site_id: str, editable: bool) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE sites SET editable = ?, updated_at = ? WHERE site_id = ?",
                (1 if editable else 0, _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")

    def set_owner(self, site_id: str, owner: str) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE sites SET owner = ?, updated_at = ? WHERE site_id = ?",
                (owner.strip(), _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")

    def _write_maintainers(self, site_id: str, maintainers: list) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE sites SET maintainers = ?, updated_at = ? WHERE site_id = ?",
                (json.dumps(sorted(set(maintainers))), _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")

    def add_maintainer(self, site_id: str, email: str) -> list:
        site = self.get(site_id)
        if site is None:
            raise KeyError(f"site not found: {site_id}")
        m = list(site.get("maintainers") or [])
        email = email.strip().lower()
        if email and email not in m:
            m.append(email)
            self._write_maintainers(site_id, m)
        return sorted(set(m))

    def remove_maintainer(self, site_id: str, email: str) -> list:
        site = self.get(site_id)
        if site is None:
            raise KeyError(f"site not found: {site_id}")
        email = email.strip().lower()
        m = [x for x in (site.get("maintainers") or []) if x != email]
        self._write_maintainers(site_id, m)
        return m

    def list_maintainers(self, site_id: str) -> list:
        site = self.get(site_id)
        if site is None:
            raise KeyError(f"site not found: {site_id}")
        return list(site.get("maintainers") or [])
