"""golive.backends.data.supabase — Python-side template CRUD (PostgREST).

The open-source data layer stores TemplateAPI records in one table:

    create table if not exists golive_templates (
        id          uuid primary key default gen_random_uuid(),
        model_code  text not null,
        name        text not null,
        user_id     text not null default '',
        description text not null default '',
        content     jsonb,
        version     text not null default '1.0.0',
        sort_index  bigint not null default 0,
        created_at  timestamptz not null default now(),
        updated_at  timestamptz not null default now(),
        unique (model_code, name, user_id)
    );

``model_code`` maps the intranet modelCode concept: a namespace per site
(or per logical dataset). The injected window.TemplateAPI (see
golive.inject.template_api) talks PostgREST directly from the browser;
this module is the server-side/CLI twin used by ``golive data ...``.
"""

from __future__ import annotations

import json
from typing import Optional

from golive.backends.postgrest import PostgrestClient, client_from_config

DEFAULT_TABLE = "golive_templates"

CREATE_TABLE_SQL = """\
create table if not exists {table} (
    id          uuid primary key default gen_random_uuid(),
    model_code  text not null,
    name        text not null,
    user_id     text not null default '',
    description text not null default '',
    content     jsonb,
    version     text not null default '1.0.0',
    sort_index  bigint not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (model_code, name, user_id)
);
-- Two separate gates guard this table, and you need BOTH:
--   GRANT decides whether the anon role may touch the table at all;
--   RLS   decides which rows it may touch.
-- Newer Supabase projects no longer expose new tables to the Data API
-- automatically, so grant explicitly rather than relying on the default.
-- Without the grant, PostgREST answers 401 / 42501 "permission denied"
-- even when the policies below are in place.
-- grant select, insert, update, delete on {table} to anon;
--
-- RLS example (the browser holds only the anon key, so it NEEDS policies):
-- alter table {table} enable row level security;
-- create policy "read all"  on {table} for select to anon using (true);
-- create policy "insert"    on {table} for insert to anon with check (true);
-- create policy "update"    on {table} for update to anon using (true);
-- create policy "delete"    on {table} for delete to anon using (true);
--
-- These four are wide open: anyone who loads the page can read and write
-- every row. Fine for a smoke test, not for real data — narrow them to
-- `to authenticated`, add an owner column, or check auth.uid() before
-- putting anything you care about in here.
-- Note: with no SELECT policy, reads return 200 with an empty array rather
-- than an error. That is normal RLS row hiding, not a broken connection.
"""


class TemplateStore:
    """CRUD for golive_templates via PostgREST."""

    def __init__(self, client: Optional[PostgrestClient] = None,
                 table: str = ""):
        self.client = client or client_from_config()
        if not table:
            from golive.config import get_config
            table = get_config().data.templates_table or DEFAULT_TABLE
        self.table = table

    # ── queries ─────────────────────────────────────────────────────────────

    def list(self, model_code: str, name_prefix: str = "", user_id: str = "",
             page_no: int = 1, page_size: int = 20) -> dict:
        params = {
            "model_code": f"eq.{model_code}",
            "order": "sort_index.desc,created_at.desc",
            "limit": str(page_size),
            "offset": str((max(page_no, 1) - 1) * page_size),
        }
        if user_id:
            params["user_id"] = f"eq.{user_id}"
        if name_prefix:
            params["name"] = f"like.{name_prefix}*"
        rows, total = self.client.select(self.table, params, count=True)
        return {"total": total or 0, "list": rows}

    def get(self, template_id: str) -> Optional[dict]:
        rows, _ = self.client.select(
            self.table, {"id": f"eq.{template_id}", "limit": "1"})
        return rows[0] if rows else None

    def count(self, model_code: str) -> int:
        return self.client.count(self.table,
                                 {"model_code": f"eq.{model_code}"})

    def list_models(self, scan_limit: int = 10000) -> list:
        """Distinct model_code values + row count each (admin portal, M6).

        PostgREST has no first-class DISTINCT, so we pull the model_code
        column (capped at ``scan_limit`` rows) and aggregate client-side.
        Returns [{"model_code": str, "count": int}, ...] sorted by code.
        """
        rows, _ = self.client.select(self.table, {
            "select": "model_code",
            "limit": str(scan_limit),
        })
        counts: dict = {}
        for r in rows:
            code = str(r.get("model_code") or "")
            if code:
                counts[code] = counts.get(code, 0) + 1
        return [{"model_code": c, "count": n}
                for c, n in sorted(counts.items())]

    def search(self, model_code: str, q: str = "", page_no: int = 1,
               page_size: int = 20, scan_limit: int = 2000) -> dict:
        """Paged rows for one model with best-effort substring filter (M6).

        Without ``q`` this delegates to :meth:`list` (server-side paging).
        With ``q`` we fetch up to ``scan_limit`` rows of the model and do a
        case-insensitive containment match over name/description/content
        client-side — PostgREST cannot LIKE into arbitrary jsonb portably.
        """
        page_no = max(1, int(page_no))
        page_size = max(1, min(int(page_size), 200))
        if not q:
            return self.list(model_code, page_no=page_no,
                             page_size=page_size)
        rows, _ = self.client.select(self.table, {
            "model_code": f"eq.{model_code}",
            "order": "sort_index.desc,created_at.desc",
            "limit": str(scan_limit),
        })
        needle = q.lower()
        hits = []
        for r in rows:
            hay = " ".join([
                str(r.get("name") or ""),
                str(r.get("description") or ""),
                json.dumps(r.get("content"), ensure_ascii=False,
                           default=str),
            ]).lower()
            if needle in hay:
                hits.append(r)
        start = (page_no - 1) * page_size
        return {"total": len(hits), "list": hits[start:start + page_size]}

    # ── writes ──────────────────────────────────────────────────────────────

    def create(self, model_code: str, name: str, content=None,
               description: str = "", version: str = "1.0.0",
               user_id: str = "") -> dict:
        row = {
            "model_code": model_code,
            "name": name,
            "user_id": user_id,
            "description": description,
            "content": self._jsonify(content),
            "version": version,
        }
        created = self.client.insert(self.table, row)
        return created[0] if created else row

    def update(self, template_id: str, patch: dict) -> dict:
        values = {"updated_at": "now()"}
        mapping = {"name": "name", "desc": "description",
                   "description": "description", "version": "version",
                   "model_code": "model_code", "modelCode": "model_code",
                   "sort_index": "sort_index"}
        for k, col in mapping.items():
            if k in patch and patch[k] is not None:
                values[col] = patch[k]
        if "content" in patch:
            values["content"] = self._jsonify(patch["content"])
        rows = self.client.update(self.table,
                                  {"id": f"eq.{template_id}"}, values)
        if not rows:
            raise KeyError(f"template not found: {template_id}")
        return rows[0]

    def upsert(self, model_code: str, name: str, content=None,
               user_id: str = "", **kw) -> dict:
        rows, _ = self.client.select(self.table, {
            "model_code": f"eq.{model_code}", "name": f"eq.{name}",
            "user_id": f"eq.{user_id}", "limit": "1"})
        if rows:
            return self.update(rows[0]["id"], {"content": content, **kw})
        return self.create(model_code, name, content=content,
                           user_id=user_id, **kw)

    def delete(self, template_id: str) -> bool:
        return self.client.delete(self.table,
                                  {"id": f"eq.{template_id}"}) > 0

    @staticmethod
    def _jsonify(content):
        if content is None:
            return {}
        if isinstance(content, str):
            try:
                return json.loads(content)
            except ValueError:
                return {"raw": content}
        return content
