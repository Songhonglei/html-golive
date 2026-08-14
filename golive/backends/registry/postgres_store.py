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


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class PostgresRegistry:
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

    # ── create / update ─────────────────────────────────────────────────────

    def create(self, name: str, slug: str = "", owner: str = "",
               notes: str = "") -> dict:
        site_id = uuid.uuid4().hex
        slug_norm = slug.strip().lower() or None
        now = _now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sites (site_id, name, slug, created_at, "
                "updated_at, owner, notes) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (site_id, name, slug_norm, now, now, owner, notes))
            c.commit()
        return self.get(site_id)

    def update(self, site_id: str, name=None, slug=None, notes=None) -> dict:
        fields, values = ["updated_at = %s"], [_now()]
        if name is not None:
            fields.append("name = %s")
            values.append(name)
        if slug is not None:
            fields.append("slug = %s")
            values.append(slug.strip().lower() or None)
        if notes is not None:
            fields.append("notes = %s")
            values.append(notes)
        values.append(site_id)
        with self._conn() as c:
            cur = c.execute(
                f"UPDATE sites SET {', '.join(fields)} WHERE site_id = %s",
                values)
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")
            c.commit()
        return self.get(site_id)

    def touch(self, site_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sites SET updated_at = %s WHERE site_id = %s",
                      (_now(), site_id))
            c.commit()

    def delete(self, site_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM sites WHERE site_id = %s", (site_id,))
            c.commit()
            return cur.rowcount > 0

    # ── query ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row) if row else {}
        raw = d.get("maintainers", [])
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                d["maintainers"] = parsed if isinstance(parsed, list) else []
            except (ValueError, TypeError):
                d["maintainers"] = []
        elif not isinstance(raw, list):
            d["maintainers"] = []
        else:
            d["maintainers"] = raw
        d["editable"] = bool(d.get("editable", False))
        return d

    def get(self, site_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE site_id = %s",
                            (site_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        with self._conn() as c:
            row = c.execute("SELECT * FROM sites WHERE slug = %s",
                            (slug.strip().lower(),)).fetchone()
        return self._row_to_dict(row) if row else None

    def resolve(self, ref: str) -> Optional[dict]:
        """Resolve a site by id or slug."""
        return self.get(ref) or self.get_by_slug(ref)

    def list_all(self, limit: int = 200) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM sites ORDER BY updated_at DESC LIMIT %s",
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
                "UPDATE sites SET editable = %s, updated_at = %s WHERE site_id = %s",
                (bool(editable), _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")
            c.commit()

    def set_owner(self, site_id: str, owner: str) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE sites SET owner = %s, updated_at = %s WHERE site_id = %s",
                (owner.strip(), _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")
            c.commit()

    def _write_maintainers(self, site_id: str, maintainers: list) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE sites SET maintainers = %s, updated_at = %s WHERE site_id = %s",
                (json.dumps(sorted(set(maintainers))), _now(), site_id))
            if cur.rowcount == 0:
                raise KeyError(f"site not found: {site_id}")
            c.commit()

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
