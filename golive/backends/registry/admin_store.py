"""golive.backends.registry.admin_store — API-managed superadmin list (M7).

golive has two superadmin sources:

  builtin  — ``admin.admins`` in golive.yaml / ``GOLIVE_ADMINS`` env.
             Read-only at runtime: the API can never remove these, so an
             operator cannot lock themselves out of their own instance.
  managed  — this table. Added/removed through
             ``/api/admin/permissions/admins`` by an existing superadmin.

The effective superadmin set is the union of both (see
golive.server.authz.get_admin_emails).

Storage: a ``managed_admins`` table inside ``$GOLIVE_HOME/registry.db``,
created on first access — existing installs pick it up with no migration
step. It lives next to the audit log rather than in the pluggable
registry backend on purpose: who may administer *this* deployment is
local operator state, and it must stay resolvable even when a remote
registry is unreachable.

Table:
  managed_admins(email TEXT PRIMARY KEY, added_by TEXT, added_at TEXT)
"""

from __future__ import annotations

import datetime
import sqlite3
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS managed_admins (
    email    TEXT PRIMARY KEY,
    added_by TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class ManagedAdmins:
    """CRUD for the API-managed superadmin list."""

    def __init__(self, db_path=None):
        if db_path is None:
            from golive.core.paths import get_registry_db
            db_path = get_registry_db()
        self.db_path = str(db_path)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _norm(email: str) -> str:
        return (email or "").strip().lower()

    def list(self) -> list:
        """[{email, added_by, added_at}, ...] sorted by email."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT email, added_by, added_at FROM managed_admins "
                "ORDER BY email").fetchall()
        return [dict(r) for r in rows]

    def emails(self) -> list:
        return [r["email"] for r in self.list()]

    def has(self, email: str) -> bool:
        email = self._norm(email)
        if not email:
            return False
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM managed_admins WHERE email = ?",
                (email,)).fetchone() is not None

    def add(self, email: str, added_by: str = "") -> bool:
        """Insert (idempotent). Returns True when a new row was created."""
        email = self._norm(email)
        if not email:
            raise ValueError("email must not be empty")
        if self.has(email):
            return False
        with self._conn() as c:
            c.execute(
                "INSERT INTO managed_admins (email, added_by, added_at) "
                "VALUES (?,?,?)",
                (email, self._norm(added_by) or added_by or "", _now()))
        return True

    def remove(self, email: str) -> bool:
        """Delete. Returns True when a row was actually removed."""
        email = self._norm(email)
        with self._conn() as c:
            return c.execute("DELETE FROM managed_admins WHERE email = ?",
                             (email,)).rowcount > 0


_cached: Optional[ManagedAdmins] = None
_cached_path = ""


def get_managed_admins() -> ManagedAdmins:
    """Process-wide ManagedAdmins bound to the current GOLIVE_HOME."""
    global _cached, _cached_path
    from golive.core.paths import get_registry_db
    path = str(get_registry_db())
    if _cached is None or _cached_path != path:
        _cached = ManagedAdmins(path)
        _cached_path = path
    return _cached
