"""Instance-local groups; additive migration beside managed_admins.

Membership is explicit verified-login email membership, never client claims.
Each mutation and its durable audit event commit in the same transaction.
"""

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS permission_groups (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS permission_group_members (
    group_id TEXT REFERENCES permission_groups(id) ON DELETE CASCADE,
    email TEXT NOT NULL, PRIMARY KEY(group_id, email));
CREATE TABLE IF NOT EXISTS permission_group_grants (
    group_id TEXT REFERENCES permission_groups(id) ON DELETE CASCADE,
    site_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('viewer','maintainer')),
    PRIMARY KEY(group_id, site_id));
CREATE INDEX IF NOT EXISTS permission_members_email ON permission_group_members(email);
CREATE INDEX IF NOT EXISTS permission_grants_site ON permission_group_grants(site_id);
CREATE TABLE IF NOT EXISTS permission_group_sites (site_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS permission_group_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
    actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
"""


class GroupStore:
    def __init__(self, db_path=None):
        if db_path is None:
            from golive.core.paths import get_registry_db
            db_path = get_registry_db()
        self.db_path = str(db_path)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self):
        with self._conn() as c:
            return [dict(row, members=[r[0] for r in c.execute(
                "SELECT email FROM permission_group_members WHERE group_id=? ORDER BY email", (row['id'],))],
                grants=[dict(r) for r in c.execute(
                    "SELECT site_id,role FROM permission_group_grants WHERE group_id=? ORDER BY site_id", (row['id'],))])
                for row in c.execute("SELECT id,name FROM permission_groups ORDER BY name")]

    def events(self, limit=100, before=None):
        with self._conn() as c:
            return [dict(r, detail=json.loads(r['detail'])) for r in c.execute(
                "SELECT * FROM permission_group_events WHERE (? IS NULL OR id < ?) "
                "ORDER BY id DESC LIMIT ?", (before, before, limit))]

    def change(self, action, actor, group_id='', value='', site_id='', role=''):
        detail = {'group_id': group_id}
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if action == 'create':
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
                    raise ValueError('name must contain 1 to 80 characters')
                value = value.strip()
                group_id = uuid.uuid4().hex
                try:
                    c.execute("INSERT INTO permission_groups VALUES (?,?)", (group_id, value))
                except sqlite3.IntegrityError:
                    raise ValueError('group name already exists') from None
                detail = {'group_id': group_id, 'name': value}
                changed = True
            else:
                if not c.execute("SELECT 1 FROM permission_groups WHERE id=?", (group_id,)).fetchone():
                    raise KeyError('unknown group')
                if action == 'delete':
                    changed = c.execute("DELETE FROM permission_groups WHERE id=?", (group_id,)).rowcount > 0
                elif action in ('member.add', 'member.remove'):
                    if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value.strip()):
                        raise ValueError('email must be a valid email')
                    value = value.strip().lower()
                    detail['email'] = value
                    if action == 'member.add':
                        changed = c.execute("INSERT OR IGNORE INTO permission_group_members VALUES (?,?)", (group_id, value)).rowcount > 0
                    else:
                        changed = c.execute("DELETE FROM permission_group_members WHERE group_id=? AND email=?", (group_id, value)).rowcount > 0
                elif action in ('grant', 'revoke'):
                    detail.update(site_id=site_id, role=role)
                    if action == 'grant':
                        if role not in ('viewer', 'maintainer'):
                            raise ValueError('role must be viewer or maintainer')
                        # Once enrolled, revoking the last group must never
                        # reopen an ownerless site's legacy token-only mode.
                        c.execute("INSERT OR IGNORE INTO permission_group_sites VALUES (?)", (site_id,))
                        changed = c.execute("INSERT INTO permission_group_grants VALUES (?,?,?) "
                            "ON CONFLICT(group_id,site_id) DO UPDATE SET role=excluded.role "
                            "WHERE role!=excluded.role", (group_id, site_id, role)).rowcount > 0
                    else:
                        changed = c.execute("DELETE FROM permission_group_grants WHERE group_id=? AND site_id=?", (group_id, site_id)).rowcount > 0
                else:
                    raise ValueError('unknown group action')
            if changed:
                c.execute("INSERT INTO permission_group_events(at,actor,action,detail) VALUES (?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), actor, action, json.dumps(detail)))
        return {'success': True, 'changed': changed, 'group_id': group_id}

    def role(self, email, site_id):
        with self._conn() as c:
            roles = {r[0] for r in c.execute(
                "SELECT g.role FROM permission_group_grants g JOIN permission_group_members m "
                "ON g.group_id=m.group_id WHERE m.email=? AND g.site_id=?",
                (email.strip().lower(), site_id))}
        return 'maintainer' if 'maintainer' in roles else ('viewer' if 'viewer' in roles else '')

    def requires_identity(self, site_id):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM permission_group_sites WHERE site_id=?", (site_id,)).fetchone() is not None


def get_group_store():
    return GroupStore()
