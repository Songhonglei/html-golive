"""golive.core.http_client — thin requests wrapper with sane defaults.

All outbound HTTP in golive goes through this module so that timeout,
User-Agent and error handling stay consistent.

Error contract:
  http_get_json / http_post_json never raise; they return
  {"success": False, "errorMsg": "..."} on any failure.
  http_get_bytes returns (bytes | None, error_msg).
"""

from __future__ import annotations

from typing import Optional

import requests

DEFAULT_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def build_headers(extra: Optional[dict] = None) -> dict:
    headers = dict(_BASE_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def http_get_bytes(url: str, *, timeout: int = DEFAULT_TIMEOUT,
                   max_bytes: int = 0) -> tuple[Optional[bytes], str]:
    """GET raw bytes. Returns (data, "") or (None, error_msg).

    max_bytes > 0 enforces a streaming size cap.
    """
    try:
        resp = requests.get(url, headers=build_headers(), timeout=timeout,
                            stream=bool(max_bytes))
        resp.raise_for_status()
        if max_bytes:
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > max_bytes:
                return None, f"resource exceeds size cap ({cl} bytes > {max_bytes})"
            chunks, downloaded = [], 0
            for chunk in resp.iter_content(chunk_size=65536):
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    return None, f"resource exceeds size cap (> {max_bytes} bytes)"
                chunks.append(chunk)
            return b"".join(chunks), ""
        return resp.content, ""
    except Exception as e:  # noqa: BLE001 — contract: never raise
        return None, str(e)


def http_get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """GET JSON. Never raises."""
    try:
        resp = requests.get(url, headers=build_headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "errorMsg": str(e)}


def http_post_json(url: str, body: dict, *, timeout: int = DEFAULT_TIMEOUT,
                   headers: Optional[dict] = None) -> dict:
    """POST JSON body, parse JSON response. Never raises."""
    try:
        resp = requests.post(url, json=body, timeout=timeout,
                             headers=build_headers(headers))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "errorMsg": str(e)}
