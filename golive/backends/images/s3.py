"""golive.backends.images.s3 — native S3-compatible image uploader.

Requires the optional dependency: ``pip install 'html-golive[s3]'``.

Config (golive.yaml)::

    uploader:
      s3:
        endpoint: https://s3.example.com   # empty = AWS default
        bucket: golive-img
        prefix: img/
        region: ""
        access_key_env: GOLIVE_S3_AK
        secret_key_env: GOLIVE_S3_SK
        public_base: https://cdn.example.com   # URL prefix for returned links

Returned URL: ``{public_base}/{prefix}{hash}{suffix}`` — when public_base
is empty, falls back to ``{endpoint}/{bucket}/{key}`` (path-style), which
works for MinIO-style deployments with public buckets.

Alternatively, any CLI-based flow still works through ``CommandUploader``
(``GOLIVE_UPLOADER_CMD``).
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

from golive.backends.images.base import ImageUploader, UploadError


class S3Uploader(ImageUploader):
    """Upload images to an S3-compatible bucket and return a public URL."""

    def __init__(self, endpoint: str = "", bucket: str = "", prefix: str = "img/",
                 region: str = "", access_key: str = "", secret_key: str = "",
                 public_base: str = ""):
        if not bucket:
            from golive.config import get_config
            up = get_config().uploader
            endpoint = endpoint or up.s3_endpoint
            bucket = bucket or up.s3_bucket
            prefix = up.s3_prefix if prefix == "img/" else prefix
            region = region or up.s3_region
            access_key = access_key or os.environ.get(up.s3_access_key_env, "")
            secret_key = secret_key or os.environ.get(up.s3_secret_key_env, "")
            public_base = public_base or up.s3_public_base
        if not bucket:
            raise ValueError("S3Uploader needs a bucket (uploader.s3.bucket)")
        try:
            import boto3
        except ImportError as e:
            raise UploadError(
                "S3 uploader needs boto3 — pip install 'html-golive[s3]'"
            ) from e
        kwargs = {}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if region:
            kwargs["region_name"] = region
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self.s3 = boto3.client("s3", **kwargs)
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.public_base = public_base.rstrip("/")

    def upload(self, data: bytes, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".bin"
        digest = hashlib.sha256(data).hexdigest()[:16]
        key = f"{self.prefix}{digest}{suffix}"
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data,
                               ContentType=ctype)
        except Exception as e:
            raise UploadError(f"S3 upload failed: {e}") from e
        if self.public_base:
            return f"{self.public_base}/{key}"
        if self.endpoint:
            return f"{self.endpoint}/{self.bucket}/{key}"
        region = getattr(self.s3.meta, "region_name", "") or "us-east-1"
        return f"https://{self.bucket}.s3.{region}.amazonaws.com/{key}"
