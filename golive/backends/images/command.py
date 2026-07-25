"""golive.backends.images.command — shell-command image uploader.

The most universal custom uploader: point golive at any CLI that can
upload a file and print a URL (aws/mc/curl scripts, corporate tools...).

Config (either source; env wins):
  env      GOLIVE_UPLOADER_CMD='mytool upload {file}'
  yaml     uploader.command: "mytool upload {file}"

Behaviour:
  * the image is written to a temp file
  * ``{file}`` in the template is replaced by the temp-file path,
    ``{name}`` by the original filename (both after shlex splitting,
    so paths with spaces are safe and no shell is involved)
  * the command runs with a 60 s timeout
  * the **last stdout line** that looks like an http(s) URL is returned
  * any failure (non-zero exit, timeout, no URL) raises UploadError —
    callers fall back to base64 inlining with a warning, publishes
    never fail because an uploader misbehaves
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from golive.backends.images.base import ImageUploader, UploadError

COMMAND_TIMEOUT = 60  # seconds


class CommandUploader(ImageUploader):
    """Run a user-configured command template to upload an image."""

    def __init__(self, command_template: str):
        template = (command_template or "").strip()
        if not template:
            raise ValueError("CommandUploader needs a non-empty command template")
        if "{file}" not in template:
            raise ValueError(
                "uploader command template must contain the {file} placeholder, "
                "e.g. 'mytool upload {file}'"
            )
        self.template = template

    def upload(self, data: bytes, filename: str) -> str:
        suffix = Path(filename).suffix or ".bin"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            # shlex-split the template FIRST, then substitute placeholders
            # inside each token — no shell, and odd filenames can't inject.
            argv = [
                tok.replace("{file}", tmp_path).replace("{name}", filename)
                for tok in shlex.split(self.template)
            ]

            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=COMMAND_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                raise UploadError(
                    f"uploader command timed out after {COMMAND_TIMEOUT}s: {argv[0]}"
                )
            except FileNotFoundError:
                raise UploadError(f"uploader command not found: {argv[0]}")

            if proc.returncode != 0:
                stderr_tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
                raise UploadError(
                    f"uploader command exited {proc.returncode}: {stderr_tail[0]}"
                )

            url = _last_http_url(proc.stdout)
            if not url:
                raise UploadError(
                    "uploader command produced no http(s) URL on stdout"
                )
            return url
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def _last_http_url(stdout: str) -> str:
    """Return the last stdout line that is an http(s) URL, else ''."""
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith(("http://", "https://")):
            return line
    return ""


def get_uploader(config: dict | None = None):
    """Factory: CommandUploader when configured, else None (base64 inline).

    Priority: env GOLIVE_UPLOADER_CMD > config['uploader']['command'].
    Invalid templates warn and return None rather than breaking a publish.
    """
    template = os.environ.get("GOLIVE_UPLOADER_CMD", "").strip()
    if not template and config:
        template = str(
            (config.get("uploader") or {}).get("command") or ""
        ).strip()
    if not template:
        return None
    try:
        return CommandUploader(template)
    except ValueError as e:
        print(f"⚠️  忽略无效的 uploader 配置：{e}", file=sys.stderr)
        return None
