"""golive.backends.storage.s3 — site HTML on any S3-compatible store.

Works with AWS S3, MinIO, Tencent COS, Alibaba OSS, Volcengine TOS —
anything speaking the S3 API. Requires the optional dependency::

    pip install 'html-golive[s3]'     # installs boto3

Config (golive.yaml)::

    storage:
      backend: s3
      s3:
        endpoint: https://s3.example.com   # empty = AWS default
        bucket: golive-sites
        prefix: ""                          # optional key prefix
        region: ""
        access_key_env: GOLIVE_S3_AK
        secret_key_env: GOLIVE_S3_SK
        public_base: ""                     # optional CDN/public URL prefix

Layout: ``<prefix><site_id>/index.html`` + ``.../backups/<ts>.html``.
"""

from __future__ import annotations

import datetime
import os
import time
from typing import Optional

BACKUP_MAX_KEEP = 10
CACHE_TTL = 60


def _boto3():
    try:
        import boto3
        return boto3
    except ImportError as e:
        raise RuntimeError(
            "S3 storage needs boto3 — install with: "
            "pip install 'html-golive[s3]'") from e


# botocore error codes that mean "the object does not exist"
_NOT_FOUND_CODES = {"NoSuchKey", "NoSuchBucket", "404", "NotFound"}


def _client_error_code(exc) -> str:
    """Extract the official error code from a botocore ClientError."""
    try:
        return str(exc.response.get("Error", {}).get("Code", ""))
    except AttributeError:
        return ""


class S3Storage:
    """StorageBackend implementation on an S3-compatible object store."""

    def __init__(self, endpoint: str = "", bucket: str = "", prefix: str = "",
                 region: str = "", access_key: str = "", secret_key: str = "",
                 public_base: str = ""):
        if not bucket:
            from golive.config import get_config
            st = get_config().storage
            endpoint = endpoint or st.s3_endpoint
            bucket = bucket or st.s3_bucket
            prefix = prefix or st.s3_prefix
            region = region or st.s3_region
            access_key = access_key or os.environ.get(st.s3_access_key_env, "")
            secret_key = secret_key or os.environ.get(st.s3_secret_key_env, "")
            public_base = public_base or st.s3_public_base
        boto3 = _boto3()
        kwargs = {}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if region:
            kwargs["region_name"] = region
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self.s3 = boto3.client("s3", **kwargs)
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.public_base = public_base.rstrip("/")
        self._cache: dict = {}

    # ── keys ────────────────────────────────────────────────────────────────

    def _key(self, site_id: str, name: str = "index.html") -> str:
        return f"{self.prefix}{site_id}/{name}"

    # ── read ────────────────────────────────────────────────────────────────

    def exists(self, site_id: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(site_id))
            return True
        except Exception:
            return False

    def read(self, site_id: str, use_cache: bool = True) -> str:
        if use_cache:
            hit = self._cache.get(site_id)
            if hit and hit[0] > time.time():
                return hit[1]
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self._key(site_id))
        except self.s3.exceptions.NoSuchKey:
            raise FileNotFoundError(f"site content not found: {site_id}")
        except Exception as e:
            # official botocore API: ClientError carries a structured code —
            # match on that instead of substring-scanning str(e).
            code = _client_error_code(e)
            if code in _NOT_FOUND_CODES:
                raise FileNotFoundError(f"site content not found: {site_id}")
            if code == "AccessDenied":
                raise PermissionError(
                    f"S3 access denied reading {self._key(site_id)} — "
                    f"check credentials/bucket policy") from e
            raise
        html = obj["Body"].read().decode("utf-8")
        self._cache[site_id] = (time.time() + CACHE_TTL, html)
        return html

    def public_url(self, site_id: str) -> str:
        if self.public_base:
            return f"{self.public_base}/{self._key(site_id)}"
        return ""

    # ── write ───────────────────────────────────────────────────────────────

    def publish(self, html: str, site_id: str, backup_previous: bool = True) -> str:
        if backup_previous and self.exists(site_id):
            try:
                self._snapshot(site_id, self.read(site_id, use_cache=False))
            except FileNotFoundError:
                pass
        self.s3.put_object(
            Bucket=self.bucket, Key=self._key(site_id),
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8")
        self._cache.pop(site_id, None)
        return f"s3://{self.bucket}/{self._key(site_id)}"

    def delete(self, site_id: str) -> None:
        paginator = self.s3.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket,
                                       Prefix=f"{self.prefix}{site_id}/"):
            keys += [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
        self._cache.pop(site_id, None)

    # ── snapshots / rollback ────────────────────────────────────────────────

    def _snapshot(self, site_id: str, html: str) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.s3.put_object(
            Bucket=self.bucket, Key=self._key(site_id, f"backups/{ts}.html"),
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8")
        snaps = sorted(self.list_snapshots(site_id), key=lambda s: s["ts"])
        while len(snaps) > BACKUP_MAX_KEEP:
            oldest = snaps.pop(0)
            self.s3.delete_object(Bucket=self.bucket, Key=oldest["path"])

    def list_snapshots(self, site_id: str) -> list:
        prefix = self._key(site_id, "backups/")
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        out = []
        for obj in resp.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1]
            if not name.endswith(".html"):
                continue
            out.append({"path": obj["Key"], "ts": name[:-5],
                        "size": obj.get("Size", 0)})
        out.sort(key=lambda s: s["ts"], reverse=True)
        return out

    def rollback(self, site_id: str, snapshot_ts: str = "") -> str:
        snaps = self.list_snapshots(site_id)
        if not snaps:
            raise FileNotFoundError(f"no snapshots for site {site_id}")
        target = snaps[0]
        if snapshot_ts:
            matches = [s for s in snaps if s["ts"] == snapshot_ts]
            if not matches:
                raise FileNotFoundError(f"snapshot {snapshot_ts} not found")
            target = matches[0]
        obj = self.s3.get_object(Bucket=self.bucket, Key=target["path"])
        html = obj["Body"].read().decode("utf-8")
        self.publish(html, site_id, backup_previous=True)
        return f"s3://{self.bucket}/{self._key(site_id)}"
