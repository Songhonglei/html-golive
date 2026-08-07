"""golive.core.urls — shareable URL computation for published sites.

When a user publishes a page they want a link they can send to a colleague.
``http://localhost:8787/s/xxx`` only works on the publisher's own machine;
this module computes the best available URL — public base, LAN IP, or
localhost fallback — and tells the caller whether the server is actually
reachable from other machines (``needs_host_flag``).

Public API:
  share_urls(site_path, port, cfg) -> dict

The returned dict has the shape::

    {
        "local":   "http://localhost:8787/s/xxx",     # always present
        "lan":     "http://192.168.1.23:8787/s/xxx",  # None if probe failed
        "public":  "https://pages.example.com/s/xxx", # None if not configured
        "needs_host_flag": True,                      # server bound to loopback
        "lan_ip":  "192.168.1.23",                   # for diagnostics
    }

Design notes:
  - Pure functions, no I/O except the LAN-IP socket probe (bounded at 0.5 s).
  - The LAN-IP probe is the *same* implementation that lived in
    ``golive/server/app.py`` since v0.7.2 (macOS-safe, 0.5 s timeout).
    It is moved here so both the server and the publish CLI share one
    implementation; ``app.py`` should import from here.
  - ``cfg`` accepts the ``ServerConfig`` dataclass from ``golive.config``
    or any duck-typed object with ``public_base``, ``host``, and ``port``
    attributes. ``None`` means "no config" (zero-config mode).
"""

from __future__ import annotations

import socket
from typing import Optional
from urllib.parse import urljoin


def _lan_ip() -> str:
    """Best-effort LAN address, bounded at 0.5 s.

    Moved here from ``golive/server/app.py`` so both the publish CLI and
    the server share one implementation. The UDP socket does not actually
    send anything, but on some networks (notably macOS CI runners)
    ``connect`` can block for a long time without an explicit timeout.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _strip_trailing_slash(url: str) -> str:
    """Remove trailing slash from a base URL, preserving ``/`` root."""
    if len(url) > 1 and url.endswith("/"):
        return url[:-1]
    return url


def _is_loopback(host: str) -> bool:
    """True if the server host means "this machine only"."""
    return host in ("127.0.0.1", "localhost", "::1", "")


def share_urls(
    site_path: str,
    port: int = 8787,
    cfg=None,
) -> dict:
    """Compute the best shareable URL(s) for a published site.

    Parameters
    ----------
    site_path : str
        The path component after the host — e.g. ``/s/abc123`` or
        ``/my-slug``. Leading slash is optional; this function normalises.
    port : int
        The server port (default 8787).
    cfg : ServerConfig or None
        The server config block (``golive.config.ServerConfig``). Pass
        ``None`` for zero-config mode (no ``public_base``, host defaults
        to ``0.0.0.0``).

    Returns
    -------
    dict with keys:
        - ``local``: ``http://localhost:{port}{path}`` — always present
        - ``lan``: ``http://{lan_ip}:{port}{path}`` or ``None``
        - ``public``: ``{public_base}{path}`` or ``None``
        - ``needs_host_flag``: True when server is bound to loopback and
          the LAN URL would not actually be reachable from other machines
        - ``lan_ip``: the detected LAN IP string, or ``"127.0.0.1"``
    """
    # Normalise site_path to start with /
    if not site_path.startswith("/"):
        site_path = "/" + site_path

    # Resolve config fields
    public_base = ""
    host = "0.0.0.0"
    if cfg is not None:
        public_base = getattr(cfg, "public_base", "") or ""
        host = getattr(cfg, "host", "0.0.0.0") or "0.0.0.0"

    # ── 1. public_base configured → that's the canonical URL ──
    if public_base:
        base = _strip_trailing_slash(public_base)
        return {
            "local": f"http://localhost:{port}{site_path}",
            "lan": None,
            "public": f"{base}{site_path}",
            "needs_host_flag": False,
            "lan_ip": None,
        }

    # ── 2. No public_base → probe LAN IP ──
    lan_ip = _lan_ip()
    lan_reachable = not _is_loopback(host)

    if lan_ip != "127.0.0.1":
        lan_url = f"http://{lan_ip}:{port}{site_path}"
    else:
        lan_url = None  # probe failed / no network

    return {
        "local": f"http://localhost:{port}{site_path}",
        "lan": lan_url,
        "public": None,
        "needs_host_flag": not lan_reachable,
        "lan_ip": lan_ip,
    }


def format_share_message(
    site_name: str,
    site_path: str,
    port: int = 8787,
    cfg=None,
) -> str:
    """Produce a human-friendly multi-line message for the publish CLI.

    This is the suggested text the CLI should print. The i18n layer can
    override the wording; the structure (which URLs to show) is driven by
    ``share_urls()``.

    Keys for i18n mapping:
      - ``publish.success`` — the ✅ line
      - ``publish.url.local`` — "本机" label
      - ``publish.url.lan`` — "局域网" label
      - ``publish.url.public`` — the single public URL line
      - ``publish.needs_host`` — the --host 0.0.0.0 hint
    """
    urls = share_urls(site_path, port, cfg)

    lines = [f"✅ 发布成功「{site_name}」"]

    if urls["public"]:
        # public_base configured → one clean URL, nothing else
        lines.append(f"   URL:     {urls['public']}")
        return "\n".join(lines)

    lines.append(f"   本机:    {urls['local']}")

    if urls["lan"]:
        lines.append(f"   局域网:  {urls['lan']}   ← 分享给同事用这个")
        if urls["needs_host_flag"]:
            lines.append(
                "   （需要 golive serve --host 0.0.0.0 才能被其他机器访问）"
            )
    else:
        lines.append("   局域网:  未检测到（本机可访问）")

    return "\n".join(lines)
