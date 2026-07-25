"""golive.backends.postgrest — minimal PostgREST REST client.

Shared by the Supabase registry / data backends. Talks to
``{SUPABASE_URL}/rest/v1/<table>`` with ``apikey`` + ``Authorization:
Bearer`` headers (service_role key preferred, anon key otherwise).

Only the small PostgREST surface golive needs:
  select / insert / upsert / update / delete / count

All methods raise PostgrestError with the server's message on failure.
"""

from __future__ import annotations

import json
from typing import Optional

import requests

DEFAULT_TIMEOUT = 15


class PostgrestError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class PostgrestClient:
    def __init__(self, url: str, key: str, timeout: int = DEFAULT_TIMEOUT):
        if not url:
            raise ValueError("Supabase URL is empty — set supabase.url in "
                             "golive.yaml or env GOLIVE_SUPABASE_URL")
        if not key:
            raise ValueError("Supabase key is empty — set env "
                             "GOLIVE_SUPABASE_SERVICE_KEY or "
                             "GOLIVE_SUPABASE_ANON_KEY")
        self.base = url.rstrip("/") + "/rest/v1"
        self.key = key
        self.timeout = timeout

    # ── plumbing ────────────────────────────────────────────────────────────

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, table: str, params: Optional[dict] = None,
                 body=None, headers: Optional[dict] = None):
        url = f"{self.base}/{table}"
        resp = requests.request(
            method, url, params=params or {},
            data=json.dumps(body) if body is not None else None,
            headers=self._headers(headers), timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
                msg = detail.get("message") or detail.get("hint") or resp.text
            except ValueError:
                msg = resp.text
            raise PostgrestError(
                f"PostgREST {method} {table} failed "
                f"(HTTP {resp.status_code}): {msg}", resp.status_code)
        return resp

    # ── API ─────────────────────────────────────────────────────────────────

    def select(self, table: str, params: Optional[dict] = None,
               count: bool = False):
        """SELECT rows. Returns (rows, total) — total is None unless count."""
        headers = {"Prefer": "count=exact"} if count else None
        resp = self._request("GET", table, params=params, headers=headers)
        rows = resp.json()
        total = None
        if count:
            # Content-Range: 0-19/42
            cr = resp.headers.get("Content-Range", "")
            if "/" in cr:
                tail = cr.rsplit("/", 1)[1]
                total = int(tail) if tail.isdigit() else len(rows)
            else:
                total = len(rows)
        return rows, total

    def insert(self, table: str, rows, returning: bool = True) -> list:
        if not isinstance(rows, list):
            rows = [rows]
        prefer = "return=representation" if returning else "return=minimal"
        resp = self._request("POST", table, body=rows,
                             headers={"Prefer": prefer})
        return resp.json() if returning else []

    def upsert(self, table: str, rows, on_conflict: str = "",
               returning: bool = True) -> list:
        if not isinstance(rows, list):
            rows = [rows]
        prefer = "resolution=merge-duplicates"
        prefer += ",return=representation" if returning else ",return=minimal"
        params = {"on_conflict": on_conflict} if on_conflict else None
        resp = self._request("POST", table, params=params, body=rows,
                             headers={"Prefer": prefer})
        return resp.json() if returning else []

    def update(self, table: str, filters: dict, values: dict,
               returning: bool = True) -> list:
        prefer = "return=representation" if returning else "return=minimal"
        resp = self._request("PATCH", table, params=filters, body=values,
                             headers={"Prefer": prefer})
        return resp.json() if returning else []

    def delete(self, table: str, filters: dict) -> int:
        resp = self._request("DELETE", table, params=filters,
                             headers={"Prefer": "return=representation"})
        try:
            return len(resp.json())
        except ValueError:
            return 0

    def count(self, table: str, filters: Optional[dict] = None) -> int:
        params = dict(filters or {})
        params["select"] = "id" if "select" not in params else params["select"]
        params["limit"] = "1"
        _, total = self.select(table, params=params, count=True)
        return total or 0


def client_from_config(cfg=None) -> PostgrestClient:
    """Build a PostgrestClient from the current golive Config."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    return PostgrestClient(cfg.supabase.url, cfg.supabase.key)
