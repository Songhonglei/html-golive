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
    site_id     text primary key,
    name        text not null default '',
    slug        text unique,
    created_at  text not null,
    updated_at  text not null,
    owner       text not null default '',
    notes       text not null default '',
    editable    boolean not null default false,
    maintainers jsonb not null default '[]'::jsonb
);
-- Upgrading from v0.2? Run instead:
--   alter table {table} add column if not exists editable boolean not null default false;
--   alter table {table} add column if not exists maintainers jsonb not null default '[]'::jsonb;
-- This table is written by the CLI and the server, never by the browser.
-- The recommended setup is a service_role key on the server (it bypasses
-- RLS), leaving the anon role read-only or with no access at all:
-- grant select on {table} to anon;
-- alter table {table} enable row level security;
-- create policy "public read" on {table} for select to anon using (true);
--
-- If you have no service_role key and the CLI must run on the anon key,
-- it also needs write access — publish, rename and delete all touch this
-- table:
-- grant select, insert, update, delete on {table} to anon;
-- create policy "anon write" on {table} for all to anon using (true)
--   with check (true);
-- That leaves site metadata publicly writable, so prefer the service_role
-- key whenever you can.
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

    # ── editor mode / maintainers (M3) ──────────────────────────────────────

    def set_editable(self, site_id: str, editable: bool) -> None:
        rows = self.client.update(
            self.table, {"site_id": f"eq.{site_id}"},
            {"editable": bool(editable), "updated_at": _now()})
        if not rows:
            raise KeyError(f"site not found: {site_id}")

    def set_owner(self, site_id: str, owner: str) -> None:
        rows = self.client.update(
            self.table, {"site_id": f"eq.{site_id}"},
            {"owner": owner.strip(), "updated_at": _now()})
        if not rows:
            raise KeyError(f"site not found: {site_id}")

    def _write_maintainers(self, site_id: str, maintainers: list) -> None:
        rows = self.client.update(
            self.table, {"site_id": f"eq.{site_id}"},
            {"maintainers": sorted(set(maintainers)), "updated_at": _now()})
        if not rows:
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
