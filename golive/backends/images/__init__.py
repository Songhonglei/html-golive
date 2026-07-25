"""golive.backends.images — pluggable image uploaders.

When an uploader is configured, bundled images are uploaded to your own
image host and referenced by URL; otherwise they are inlined as base64
data URIs (zero-config default).

Providers:
  CommandUploader  shell-command template (GOLIVE_UPLOADER_CMD) — v0.1
  S3Uploader       native S3 — coming in M2
"""

from golive.backends.images.base import ImageUploader, UploadError
from golive.backends.images.command import CommandUploader, get_uploader

__all__ = ["ImageUploader", "UploadError", "CommandUploader", "get_uploader"]
