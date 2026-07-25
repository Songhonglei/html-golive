"""golive.backends.storage.supabase_store — site HTML on Supabase Storage.

Layout inside the bucket (default ``golive-sites``):
  <site_id>/index.html                 current published HTML
  <site_id>/backups/<ts>.html          rollback snapshots (max 10)

Uses the Supabase Storage REST API:
  POST/PUT {url}/storage/v1/object/{bucket}/{path}     upload
  GET      {url}/storage/v1/object/{bucket}/{path}     download (authed)
  DELETE   {url}/storage/v1/object/{bucket}/{path}
  POST     {url}/storage/v1/object/list/{bucket}       list

Serve mode reads through a small in-memory cache (60 s TTL) so page
views don't hammer the Storage API. ``public_url()`` returns the public
object URL when the bucket is public.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

BACKUP_MAX_KEEP = 10
CACHE_TTL = 60  # seconds
DEFAULT_TIMEOUT = 20


class SupabaseStorageError(RuntimeError):
    pass


class SupabaseStorage:
    """StorageBackend implementation on Supabase Storage."""

    def __init__(self, url: str = "", key: str = "", bucket: str = ""):
        if not (url and key and bucket):
            from golive.config import get_config
            cfg = get_config()
            url = url or cfg.supabase.url
            key = key or cfg.supabase.key
            bucket = bucket or cfg.storage.supabase_bucket
        if not url or not key:
            raise ValueError("Supabase storage needs supabase.url + key "
                             "(env GOLIVE_SUPABASE_URL / *_KEY)")
        self.base = url.rstrip("/")
        self.key = key
        self.bucket = bucket or "golive-sites"
        self._cache: dict = {}  # site_id -> (expires_at, html)

    # ── plumbing ────────────────────────────────────────────────────────────

    def _headers(self, ctype: str = "") -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        if ctype:
            h["Content-Type"] = ctype
        return h

    def _obj_url(self, path: str) -> str:
        return f"{self.base}/storage/v1/object/{self.bucket}/{path}"

    def _upload(self, path: str, content: str) -> None:
        resp = requests.post(
            self._obj_url(path), data=content.encode("utf-8"),
            headers={**self._headers("text/html; charset=utf-8"),
                     "x-upsert": "true"},
            timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            raise SupabaseStorageError(
                f"upload {path} failed (HTTP {resp.status_code}): {resp.text}")

    def _download(self, path: str) -> Optional[str]:
        resp = requests.get(self._obj_url(path), headers=self._headers(),
                            timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (400, 404):
            return None
        raise SupabaseStorageError(
            f"download {path} failed (HTTP {resp.status_code}): {resp.text}")

    def _list(self, prefix: str) -> list:
        resp = requests.post(
            f"{self.base}/storage/v1/object/list/{self.bucket}",
            json={"prefix": prefix, "limit": 100,
                  "sortBy": {"column": "name", "order": "desc"}},
            headers=self._headers("application/json"), timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            raise SupabaseStorageError(
                f"list {prefix} failed (HTTP {resp.status_code}): {resp.text}")
        return resp.json() or []

    def _remove(self, path: str) -> None:
        requests.delete(self._obj_url(path), headers=self._headers(),
                        timeout=DEFAULT_TIMEOUT)

    # ── read ────────────────────────────────────────────────────────────────

    def exists(self, site_id: str) -> bool:
        try:
            return self.read(site_id) is not None
        except FileNotFoundError:
            return False

    def read(self, site_id: str, use_cache: bool = True) -> str:
        if use_cache:
            hit = self._cache.get(site_id)
            if hit and hit[0] > time.time():
                return hit[1]
        html = self._download(f"{site_id}/index.html")
        if html is None:
            raise FileNotFoundError(f"site content not found: {site_id}")
        self._cache[site_id] = (time.time() + CACHE_TTL, html)
        return html

    def public_url(self, site_id: str) -> str:
        """Public object URL (works when the bucket is public)."""
        return f"{self.base}/storage/v1/object/public/{self.bucket}/{site_id}/index.html"

    # ── write ───────────────────────────────────────────────────────────────

    def publish(self, html: str, site_id: str, backup_previous: bool = True) -> str:
        if backup_previous:
            try:
                prev = self._download(f"{site_id}/index.html")
            except SupabaseStorageError:
                prev = None
            if prev is not None:
                self._snapshot(site_id, prev)
        self._upload(f"{site_id}/index.html", html)
        self._cache.pop(site_id, None)
        return f"{self.bucket}/{site_id}/index.html"

    def delete(self, site_id: str) -> None:
        for obj in self._list(site_id):
            name = obj.get("name", "")
            if name:
                self._remove(f"{site_id}/{name}")
        for obj in self._list(f"{site_id}/backups"):
            name = obj.get("name", "")
            if name:
                self._remove(f"{site_id}/backups/{name}")
        self._cache.pop(site_id, None)

    # ── snapshots / rollback ────────────────────────────────────────────────

    def _snapshot(self, site_id: str, html: str) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._upload(f"{site_id}/backups/{ts}.html", html)
        self._prune(site_id)

    def _prune(self, site_id: str) -> None:
        snaps = sorted(self.list_snapshots(site_id), key=lambda s: s["ts"])
        while len(snaps) > BACKUP_MAX_KEEP:
            oldest = snaps.pop(0)
            self._remove(f"{site_id}/backups/{oldest['ts']}.html")

    def list_snapshots(self, site_id: str) -> list:
        out = []
        for obj in self._list(f"{site_id}/backups"):
            name = obj.get("name", "")
            if not name.endswith(".html"):
                continue
            meta = obj.get("metadata") or {}
            out.append({
                "path": f"{site_id}/backups/{name}",
                "ts": name[:-5],
                "size": meta.get("size", 0),
            })
        out.sort(key=lambda s: s["ts"], reverse=True)
        return out

    def rollback(self, site_id: str, snapshot_ts: str = "") -> str:
        snaps = self.list_snapshots(site_id)
        if not snaps:
            raise FileNotFoundError(f"no snapshots for site {site_id}")
        target = None
        if snapshot_ts:
            for s in snaps:
                if s["ts"] == snapshot_ts:
                    target = s
                    break
            if target is None:
                raise FileNotFoundError(f"snapshot {snapshot_ts} not found")
        else:
            target = snaps[0]
        html = self._download(target["path"])
        if html is None:
            raise FileNotFoundError(f"snapshot object missing: {target['path']}")
        self.publish(html, site_id, backup_previous=True)
        return f"{self.bucket}/{site_id}/index.html"
