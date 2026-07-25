"""golive.backends.registry.supabase_store — site registry on Supabase.

Stores the same columns as the SQLite reference implementation in a
``golive_sites`` table via PostgREST.

Create the table once in the Supabase SQL editor (also available via
``golive db init --print-sql``):

    create table if not exists golive_sites (
        site_id    text primary key,
        name       text not null default '',
        slug       text unique,
        created_at text not null,
        updated_at text not null,
        owner      text not null default '',
        notes      text not null default ''
    );

RLS note: with a service_role key RLS is bypassed (server-side use only).
With an anon key you must add policies that allow the operations you need.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from golive.backends.postgrest import PostgrestClient, client_from_config

DEFAULT_TABLE = "golive_sites"

CREATE_TABLE_SQL = """\
create table if not exists {table} (
    site_id    text primary key,
    name       text not null default '',
    slug       text unique,
    created_at text not null,
    updated_at text not null,
    owner      text not null default '',
    notes      text not null default ''
);
-- Optional: enable RLS and restrict writes to service_role
-- alter table {table} enable row level security;
-- create policy "public read" on {table} for select using (true);
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class SupabaseRegistry:
    """RegistryBackend implementation on Supabase (PostgREST)."""

    def __init__(self, client: Optional[PostgrestClient] = None,
                 table: str = ""):
        self.client = client or client_from_config()
        if not table:
            from golive.config import get_config
            table = get_config().registry.supabase_table or DEFAULT_TABLE
        self.table = table

    # ── create / update ─────────────────────────────────────────────────────

    def create(self, name: str, slug: str = "", owner: str = "",
               notes: str = "") -> dict:
        site_id = uuid.uuid4().hex
        now = _now()
        row = {
            "site_id": site_id,
            "name": name,
            "slug": slug.strip().lower() or None,
            "created_at": now,
            "updated_at": now,
            "owner": owner,
            "notes": notes,
        }
        created = self.client.insert(self.table, row)
        return created[0] if created else row

    def update(self, site_id: str, name=None, slug=None, notes=None) -> dict:
        values = {"updated_at": _now()}
        if name is not None:
            values["name"] = name
        if slug is not None:
            values["slug"] = slug.strip().lower() or None
        if notes is not None:
            values["notes"] = notes
        rows = self.client.update(self.table,
                                  {"site_id": f"eq.{site_id}"}, values)
        if not rows:
            raise KeyError(f"site not found: {site_id}")
        return rows[0]

    def touch(self, site_id: str) -> None:
        self.client.update(self.table, {"site_id": f"eq.{site_id}"},
                           {"updated_at": _now()}, returning=False)

    def delete(self, site_id: str) -> bool:
        return self.client.delete(self.table,
                                  {"site_id": f"eq.{site_id}"}) > 0

    # ── query ───────────────────────────────────────────────────────────────

    def get(self, site_id: str) -> Optional[dict]:
        rows, _ = self.client.select(
            self.table, {"site_id": f"eq.{site_id}", "limit": "1"})
        return rows[0] if rows else None

    def get_by_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        rows, _ = self.client.select(
            self.table, {"slug": f"eq.{slug.strip().lower()}", "limit": "1"})
        return rows[0] if rows else None

    def resolve(self, ref: str) -> Optional[dict]:
        return self.get(ref) or self.get_by_slug(ref)

    def list_all(self, limit: int = 200) -> list:
        rows, _ = self.client.select(
            self.table, {"order": "updated_at.desc", "limit": str(limit)})
        return rows

    def slug_taken(self, slug: str, exclude_site_id: str = "") -> bool:
        site = self.get_by_slug(slug)
        if site is None:
            return False
        return site["site_id"] != exclude_site_id
