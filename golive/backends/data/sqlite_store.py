"""golive.backends.data.sqlite_store — zero-config local data layer.

Drop-in twin of :class:`golive.backends.data.supabase.TemplateStore`, but
backed by a plain SQLite file at ``$GOLIVE_HOME/data.db``. This is the
**default** data backend: publishing a page that calls
``window.TemplateAPI`` works with no external service to register.

Table (created on first access — no manual ``init`` step):

    CREATE TABLE IF NOT EXISTS golive_templates (
        id          TEXT PRIMARY KEY,      -- uuid4 string
        model_code  TEXT NOT NULL,
        name        TEXT NOT NULL,
        user_id     TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        content     TEXT NOT NULL DEFAULT '{}',   -- JSON blob
        version     TEXT NOT NULL DEFAULT '1.0.0',
        sort_index  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        UNIQUE (model_code, name, user_id)
    );

Column semantics match the Supabase/PostgREST table one-for-one, and rows
come back as dicts with ``content`` already decoded to a Python object —
so ``golive data ...``, the admin portal and the browser data layer all
behave the same whichever backend is configured.

Browser access: pages cannot open a local SQLite file, so the injected
``window.TemplateAPI`` talks to ``golive serve``'s ``/api/data/<table>``
endpoint (a PostgREST-shaped adapter — see golive.server.data_api) which
in turn calls this store. The low-level :meth:`query` / :meth:`insert_row`
/ :meth:`update_rows` / :meth:`delete_rows` helpers exist for that
adapter; application code should prefer the high-level methods.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Optional

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
    content     TEXT NOT NULL DEFAULT '{{}}',
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


class TemplateStore:
    """CRUD for golive_templates on local SQLite (default data backend)."""

    def __init__(self, db_path=None, table: str = ""):
        if not table or not db_path:
            try:
                from golive.config import get_config
                cfg = get_config()
            except Exception:  # noqa: BLE001 — stay usable without config
                cfg = None
            if not table and cfg is not None:
                table = cfg.data.templates_table or DEFAULT_TABLE
            if not db_path and cfg is not None:
                db_path = cfg.data.sqlite_path or None
        if not db_path:
            from golive.core.paths import get_data_db
            db_path = get_data_db()
        self.db_path = str(db_path)
        self.table = _valid_table(table)
        with self._conn() as c:
            c.executescript(_SCHEMA.format(table=self.table))

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── row mapping ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        raw = d.get("content")
        if isinstance(raw, str):
            try:
                d["content"] = json.loads(raw)
            except ValueError:
                d["content"] = {"raw": raw}
        elif raw is None:
            d["content"] = {}
        return d

    @staticmethod
    def _jsonify(content):
        """Normalise arbitrary content into a JSON-able object."""
        if content is None:
            return {}
        if isinstance(content, str):
            try:
                return json.loads(content)
            except ValueError:
                return {"raw": content}
        return content

    @classmethod
    def _dump(cls, content) -> str:
        return json.dumps(cls._jsonify(content), ensure_ascii=False,
                          default=str)

    # ── queries ─────────────────────────────────────────────────────────────

    def list(self, model_code: str, name_prefix: str = "", user_id: str = "",
             page_no: int = 1, page_size: int = 20) -> dict:
        where = ["model_code = ?"]
        params: list = [model_code]
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if name_prefix:
            where.append("name LIKE ?")
            params.append(name_prefix.replace("%", r"\%") + "%")
        clause = " AND ".join(where)
        offset = (max(int(page_no), 1) - 1) * int(page_size)
        with self._conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE {clause}",
                params).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE {clause} "
                "ORDER BY sort_index DESC, created_at DESC LIMIT ? OFFSET ?",
                params + [int(page_size), offset]).fetchall()
        return {"total": total, "list": [self._row_to_dict(r) for r in rows]}

    def get(self, template_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(f"SELECT * FROM {self.table} WHERE id = ?",
                            (str(template_id),)).fetchone()
        return self._row_to_dict(row) if row else None

    def count(self, model_code: str) -> int:
        with self._conn() as c:
            return c.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE model_code = ?",
                (model_code,)).fetchone()[0]

    def list_models(self, scan_limit: int = 10000) -> list:
        """Distinct model_code values + row count each (admin portal, M6).

        ``scan_limit`` caps how many rows are considered, mirroring the
        PostgREST implementation (which cannot do a server-side DISTINCT);
        SQLite groups natively, so the cap only bounds pathological tables.
        """
        with self._conn() as c:
            rows = c.execute(
                f"SELECT model_code, COUNT(*) AS n FROM ("
                f"  SELECT model_code FROM {self.table} LIMIT ?"
                f") GROUP BY model_code ORDER BY model_code",
                (int(scan_limit),)).fetchall()
        return [{"model_code": r["model_code"], "count": r["n"]}
                for r in rows if r["model_code"]]

    def search(self, model_code: str, q: str = "", page_no: int = 1,
               page_size: int = 20, scan_limit: int = 2000) -> dict:
        """Paged rows for one model with substring filter (M6).

        Without ``q`` this delegates to :meth:`list`. With ``q`` we scan up
        to ``scan_limit`` rows of the model and match case-insensitively
        over name/description/content — same contract as the PostgREST twin.
        """
        page_no = max(1, int(page_no))
        page_size = max(1, min(int(page_size), 200))
        if not q:
            return self.list(model_code, page_no=page_no, page_size=page_size)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE model_code = ? "
                "ORDER BY sort_index DESC, created_at DESC LIMIT ?",
                (model_code, int(scan_limit))).fetchall()
        needle = q.lower()
        hits = []
        for r in rows:
            d = self._row_to_dict(r)
            hay = " ".join([
                str(d.get("name") or ""),
                str(d.get("description") or ""),
                json.dumps(d.get("content"), ensure_ascii=False, default=str),
            ]).lower()
            if needle in hay:
                hits.append(d)
        start = (page_no - 1) * page_size
        return {"total": len(hits), "list": hits[start:start + page_size]}

    # ── writes ──────────────────────────────────────────────────────────────

    def create(self, model_code: str, name: str, content=None,
               description: str = "", version: str = "1.0.0",
               user_id: str = "") -> dict:
        row_id = str(uuid.uuid4())
        now = _now()
        with self._conn() as c:
            c.execute(
                f"INSERT INTO {self.table} (id, model_code, name, user_id, "
                "description, content, version, sort_index, created_at, "
                "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row_id, model_code, name, user_id, description,
                 self._dump(content), version, 0, now, now))
        return self.get(row_id)

    def update(self, template_id: str, patch: dict) -> dict:
        mapping = {"name": "name", "desc": "description",
                   "description": "description", "version": "version",
                   "model_code": "model_code", "modelCode": "model_code",
                   "sort_index": "sort_index"}
        sets, params = ["updated_at = ?"], [_now()]
        for k, col in mapping.items():
            if k in patch and patch[k] is not None:
                sets.append(f"{col} = ?")
                params.append(patch[k])
        if "content" in patch:
            sets.append("content = ?")
            params.append(self._dump(patch["content"]))
        params.append(str(template_id))
        with self._conn() as c:
            cur = c.execute(
                f"UPDATE {self.table} SET {', '.join(sets)} WHERE id = ?",
                params)
            if cur.rowcount == 0:
                raise KeyError(f"template not found: {template_id}")
        return self.get(template_id)

    def upsert(self, model_code: str, name: str, content=None,
               user_id: str = "", **kw) -> dict:
        with self._conn() as c:
            row = c.execute(
                f"SELECT id FROM {self.table} WHERE model_code = ? "
                "AND name = ? AND user_id = ? LIMIT 1",
                (model_code, name, user_id)).fetchone()
        if row:
            return self.update(row["id"], {"content": content, **kw})
        return self.create(model_code, name, content=content,
                           user_id=user_id, **kw)

    def delete(self, template_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(f"DELETE FROM {self.table} WHERE id = ?",
                            (str(template_id),))
            return cur.rowcount > 0

    # ── PostgREST-shaped surface (used by golive.server.data_api) ───────────

    def _where(self, filters: dict) -> tuple:
        """Translate {col: (op, value)} into a SQL WHERE clause + params.

        ``op`` is 'eq' or 'like' (PostgREST ``*`` wildcards become ``%``).
        Unknown columns raise ValueError — the column list is a whitelist,
        values are always bound parameters.
        """
        parts, params = [], []
        for col, (op, val) in (filters or {}).items():
            if col not in FILTERABLE:
                raise ValueError(f"column not filterable: {col}")
            if op == "eq":
                parts.append(f"{col} = ?")
                params.append(val)
            elif op == "like":
                parts.append(f"{col} LIKE ?")
                params.append(str(val).replace("%", r"\%").replace("*", "%"))
            else:
                raise ValueError(f"unsupported operator: {op}")
        return (" AND ".join(parts) or "1=1"), params

    @staticmethod
    def _order_sql(order: str) -> str:
        """'sort_index.desc,created_at.desc' -> SQL ORDER BY body."""
        terms = []
        for chunk in (order or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            col, _, direction = chunk.partition(".")
            if col not in SORTABLE:
                continue
            terms.append(f"{col} {'DESC' if direction.lower() == 'desc' else 'ASC'}")
        return ", ".join(terms) or "sort_index DESC, created_at DESC"

    def query(self, filters: dict, order: str = "", limit: int = 20,
              offset: int = 0, want_count: bool = False) -> tuple:
        """Filtered read. Returns ``(rows, total_or_None)``."""
        clause, params = self._where(filters)
        with self._conn() as c:
            total = None
            if want_count:
                total = c.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE {clause}",
                    params).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE {clause} "
                f"ORDER BY {self._order_sql(order)} LIMIT ? OFFSET ?",
                params + [max(1, int(limit)), max(0, int(offset))]).fetchall()
        return [self._row_to_dict(r) for r in rows], total

    def insert_row(self, row: dict) -> dict:
        """Insert one raw row dict (column names as in the table)."""
        return self.create(
            model_code=str(row.get("model_code") or ""),
            name=str(row.get("name") or ""),
            content=row.get("content"),
            description=str(row.get("description") or ""),
            version=str(row.get("version") or "1.0.0"),
            user_id=str(row.get("user_id") or ""),
        )

    def update_rows(self, filters: dict, values: dict) -> list:
        """Patch every row matching ``filters``. Returns the updated rows."""
        clause, params = self._where(filters)
        with self._conn() as c:
            ids = [r["id"] for r in c.execute(
                f"SELECT id FROM {self.table} WHERE {clause}", params)]
        patch = dict(values)
        patch.pop("updated_at", None)   # always stamped by update()
        return [self.update(i, patch) for i in ids]

    def delete_rows(self, filters: dict) -> int:
        clause, params = self._where(filters)
        with self._conn() as c:
            cur = c.execute(f"DELETE FROM {self.table} WHERE {clause}",
                            params)
            return cur.rowcount
