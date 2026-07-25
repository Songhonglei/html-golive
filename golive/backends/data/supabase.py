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
-- RLS example (anon key in the browser NEEDS policies like these):
-- alter table {table} enable row level security;
-- create policy "read all"  on {table} for select using (true);
-- create policy "insert"    on {table} for insert with check (true);
-- create policy "update"    on {table} for update using (true);
-- create policy "delete"    on {table} for delete using (true);
-- Tighten the policies to your auth setup before going to production.
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
