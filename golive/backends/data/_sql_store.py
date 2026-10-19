"""Shared parameter-bound SQL CRUD for PostgreSQL and MySQL stores."""
from __future__ import annotations
import datetime
import json
import uuid
from typing import Optional

FILTERABLE = ("id", "model_code", "name", "user_id", "version")
SORTABLE = ("sort_index", "created_at", "updated_at", "name", "model_code")

def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

class SQLTemplateStore:
    def _conn(self):
        raise NotImplementedError

    # ── row mapping ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row) if row else {}
        raw = d.get("content")
        if isinstance(raw, str):
            try:
                d["content"] = json.loads(raw)
            except ValueError:
                d["content"] = {"raw": raw}
        elif raw is None:
            d["content"] = {}
        # psycopg3 returns JSONB as dict already, but we normalise anyway
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
        where = ["model_code = %s"]
        params: list = [model_code]
        if user_id:
            where.append("user_id = %s")
            params.append(user_id)
        if name_prefix:
            where.append("name LIKE %s ESCAPE '!'")
            params.append(name_prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%")
        clause = " AND ".join(where)
        offset = (max(int(page_no), 1) - 1) * int(page_size)
        with self._conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) AS count FROM {self.table} WHERE {clause}",
                params).fetchone()["count"]
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE {clause} "
                "ORDER BY sort_index DESC, created_at DESC LIMIT %s OFFSET %s",
                params + [int(page_size), offset]).fetchall()
        return {"total": total, "list": [self._row_to_dict(r) for r in rows]}

    def get(self, template_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(f"SELECT * FROM {self.table} WHERE id = %s",
                            (str(template_id),)).fetchone()
        return self._row_to_dict(row) if row else None

    def count(self, model_code: str) -> int:
        with self._conn() as c:
            row = c.execute(
                f"SELECT COUNT(*) AS cnt FROM {self.table} WHERE model_code = %s",
                (model_code,)).fetchone()
        return row["cnt"]

    def list_models(self, scan_limit: int = 10000) -> list:
        """Distinct model_code values + row count each (admin portal, M6)."""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT model_code, COUNT(*) AS n FROM ("
                f"  SELECT model_code FROM {self.table} LIMIT %s"
                f") sub GROUP BY model_code ORDER BY model_code",
                (int(scan_limit),)).fetchall()
        return [{"model_code": r["model_code"], "count": r["n"]}
                for r in rows if r["model_code"]]

    def search(self, model_code: str, q: str = "", page_no: int = 1,
               page_size: int = 20, scan_limit: int = 2000) -> dict:
        """Paged rows for one model with substring filter (M6)."""
        page_no = max(1, int(page_no))
        page_size = max(1, min(int(page_size), 200))
        if not q:
            return self.list(model_code, page_no=page_no, page_size=page_size)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE model_code = %s "
                "ORDER BY sort_index DESC, created_at DESC LIMIT %s",
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
                "updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (row_id, model_code, name, user_id, description,
                 self._dump(content), version, 0, now, now))
            c.commit()
        return self.get(row_id)

    def update(self, template_id: str, patch: dict) -> dict:
        mapping = {"name": "name", "desc": "description",
                   "description": "description", "version": "version",
                   "model_code": "model_code", "modelCode": "model_code",
                   "sort_index": "sort_index"}
        sets, params = ["updated_at = %s"], [_now()]
        for k, col in mapping.items():
            if k in patch and patch[k] is not None:
                sets.append(f"{col} = %s")
                params.append(patch[k])
        if "content" in patch:
            sets.append("content = %s")
            params.append(self._dump(patch["content"]))
        params.append(str(template_id))
        with self._conn() as c:
            cur = c.execute(
                f"UPDATE {self.table} SET {', '.join(sets)} WHERE id = %s",
                params)
            if cur.rowcount == 0:
                raise KeyError(f"template not found: {template_id}")
            c.commit()
        return self.get(template_id)

    def upsert(self, model_code: str, name: str, content=None,
               user_id: str = "", **kw) -> dict:
        with self._conn() as c:
            row = c.execute(
                f"SELECT id FROM {self.table} WHERE model_code = %s "
                "AND name = %s AND user_id = %s LIMIT 1",
                (model_code, name, user_id)).fetchone()
        if row:
            return self.update(row["id"], {"content": content, **kw})
        return self.create(model_code, name, content=content,
                           user_id=user_id, **kw)

    def delete(self, template_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(f"DELETE FROM {self.table} WHERE id = %s",
                            (str(template_id),))
            c.commit()
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
                parts.append(f"{col} = %s")
                params.append(val)
            elif op == "like":
                parts.append(f"{col} LIKE %s")
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
                row = c.execute(
                    f"SELECT COUNT(*) AS cnt FROM {self.table} WHERE {clause}",
                    params).fetchone()
                total = row["cnt"]
            rows = c.execute(
                f"SELECT * FROM {self.table} WHERE {clause} "
                f"ORDER BY {self._order_sql(order)} LIMIT %s OFFSET %s",
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
            rows = c.execute(
                f"SELECT id FROM {self.table} WHERE {clause}", params).fetchall()
        patch = dict(values)
        patch.pop("updated_at", None)   # always stamped by update()
        return [self.update(r["id"], patch) for r in rows]

    def delete_rows(self, filters: dict) -> int:
        clause, params = self._where(filters)
        with self._conn() as c:
            cur = c.execute(f"DELETE FROM {self.table} WHERE {clause}",
                            params)
            c.commit()
            return cur.rowcount
