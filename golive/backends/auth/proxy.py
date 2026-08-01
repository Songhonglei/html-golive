"""golive.backends.auth.proxy — trusted reverse-proxy auth provider.

For enterprises that terminate authentication at nginx / APISIX / a
WAF and forward identity in HTTP headers. The proxy is trusted only
when the source IP is in ``auth.proxy.trusted_ips`` — an empty list
refuses to start (no default trust-all).

Config (golive.yaml):
  auth:
    provider: proxy
    proxy:
      header: X-Forwarded-User       # default; the header carrying identity
      email_header: X-Forwarded-Email # optional; falls back to header value
      groups_header: X-Forwarded-Groups  # optional
      trusted_ips:
        - 10.0.0.0/8
        - 192.168.0.0/16
        - 127.0.0.1/32

Security model:
  - ``trusted_ips`` is mandatory. An empty list → startup error.
  - Source IP is taken from ``REMOTE_ADDR`` (socket-level, not forgeable
    by headers when there's no intermediary). If a trusted proxy sets
    ``X-Forwarded-For``, the *rightmost* untrusted IP is used — but in
    practice, if you're behind a known proxy, ``REMOTE_ADDR`` is the
    proxy's IP and that's what we check.
  - Headers from non-trusted IPs are ignored entirely (not just
    rejected — the request proceeds as anonymous, so the admin portal
    shows a login prompt rather than a confusing 403).
  - Groups/roles from headers are informational only (for future RBAC).
"""

from __future__ import annotations

import ipaddress
import os
import sys
from typing import Optional

from golive.backends.auth.base import AuthProvider


class ProxyAuthError(RuntimeError):
    pass


class ProxyAuth(AuthProvider):
    """Trusted reverse-proxy header authentication."""

    name = "proxy"

    def __init__(self, header: str = "X-Forwarded-User",
                 email_header: str = "",
                 groups_header: str = "",
                 trusted_ips: list = None):
        if not trusted_ips:
            from golive.config import get_config
            au = get_config().auth
            header = header if header != "X-Forwarded-User" else au.proxy_header
            email_header = email_header or au.proxy_email_header
            groups_header = groups_header or au.proxy_groups_header
            trusted_ips = au.proxy_trusted_ips

        if not trusted_ips:
            raise ProxyAuthError(
                "auth.proxy.trusted_ips is empty — trusted reverse-proxy "
                "mode requires at least one CIDR. Without it, anyone could "
                "forge the identity header. Add trusted proxy IPs/CIDRs "
                "to golive.yaml:\n"
                "  auth:\n"
                "    provider: proxy\n"
                "    proxy:\n"
                "      trusted_ips:\n"
                "        - 10.0.0.0/8\n"
                "        - 127.0.0.1/32\n"
            )

        self.header = (header or "X-Forwarded-User").strip()
        self.email_header = (email_header or "").strip()
        self.groups_header = (groups_header or "").strip()
        self._networks = []
        for cidr in trusted_ips:
            cidr = str(cidr).strip()
            if not cidr:
                continue
            try:
                # Handle bare IPs (treat as /32)
                if "/" not in cidr:
                    cidr = cidr + "/32"
                self._networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError as e:
                raise ProxyAuthError(
                    f"invalid CIDR in auth.proxy.trusted_ips: {cidr!r} ({e})"
                )
        if not self._networks:
            raise ProxyAuthError(
                "auth.proxy.trusted_ips contains no valid CIDRs — "
                "at least one trusted proxy IP range is required"
            )

    def _is_trusted(self, source_ip: str) -> bool:
        """Return True when source_ip is within any trusted CIDR."""
        if not source_ip:
            return False
        try:
            addr = ipaddress.ip_address(source_ip)
        except ValueError:
            return False
        return any(addr in net for net in self._networks)

    def _get_source_ip(self, request_headers: dict) -> str:
        """Extract the socket-level remote address.

        In the stdlib server, this comes from ``self.client_address[0]``
        and is passed in the headers dict by the handler. We look for
        ``REMOTE_ADDR`` (set by the server handler) and fall back to
        ``X-Real-IP`` (set by nginx) — but only when the *connection*
        is from a trusted proxy.
        """
        headers = {str(k).lower(): str(v) for k, v in (request_headers or {}).items()}
        return headers.get("remote_addr", "") or headers.get("x-real-ip", "")

    def session_user(self, request_headers: dict) -> Optional[dict]:
        """Resolve the proxy header into a user dict (or None)."""
        headers = {str(k): str(v) for k, v in (request_headers or {}).items()}
        source_ip = self._get_source_ip(headers)

        if not self._is_trusted(source_ip):
            # Not from a trusted proxy — treat as anonymous, not an error.
            # The admin portal will show a login prompt.
            return None

        # Try the configured header (case-insensitive lookup)
        identity = ""
        for k, v in headers.items():
            if k.lower() == self.header.lower():
                identity = v.strip()
                break

        if not identity:
            return None

        email = identity
        if self.email_header:
            for k, v in headers.items():
                if k.lower() == self.email_header.lower():
                    email = v.strip().lower()
                    break
        if not email:
            email = identity.lower() if "@" in identity else ""

        groups = []
        if self.groups_header:
            for k, v in headers.items():
                if k.lower() == self.groups_header.lower():
                    groups = [g.strip() for g in v.split(",") if g.strip()]
                    break

        return {
            "sub": identity,
            "email": email,
            "name": identity,
            "groups": groups,
        }

    # ── AuthProvider interface ──────────────────────────────────────────────

    def verify(self, request_headers: dict) -> bool:
        return self.session_user(request_headers) is not None

    def identity(self, request_headers: dict) -> str:
        user = self.session_user(request_headers)
        return (user or {}).get("email", "")
