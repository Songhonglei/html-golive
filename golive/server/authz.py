"""golive.server.authz — role resolution for the admin portal (M5).

Roles (per request, per site):
  superadmin  — email listed in admin.admins (golive.yaml) or GOLIVE_ADMINS
                env (comma separated, env wins). A valid *token* auth is
                also treated as superadmin: the static GOLIVE_TOKEN is
                operator-held by definition.
  owner       — registry ``owner`` column matches the session email.
  maintainer  — email appears in the registry ``maintainers`` list.
  (none)      — authenticated but unrelated to the site.

Identity sources, in order of trust:
  1. OIDC session (server-verified email)
  2. static token (Authorization: Bearer / X-Golive-Token) -> superadmin

This module is pure logic — no HTTP. The handler passes in the already
verified identity; nothing here reads headers or cookies.
"""

from __future__ import annotations

import os
from typing import Optional


def get_admin_emails(cfg=None) -> list:
    """Superadmin email list. env GOLIVE_ADMINS > yaml admin.admins."""
    env_val = os.environ.get("GOLIVE_ADMINS", "").strip()
    if env_val:
        return [a.strip().lower() for a in env_val.split(",") if a.strip()]
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    return [str(a).strip().lower() for a in (cfg.admin.admins or [])
            if str(a).strip()]


class Identity:
    """Resolved caller identity for one request."""

    __slots__ = ("email", "via_token", "is_superadmin")

    def __init__(self, email: str = "", via_token: bool = False,
                 is_superadmin: bool = False):
        self.email = (email or "").strip().lower()
        self.via_token = via_token
        self.is_superadmin = is_superadmin

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "via_token": self.via_token,
            "superadmin": self.is_superadmin,
        }


def resolve_identity(session_user: Optional[dict],
                     token_ok: bool, cfg=None) -> Optional[Identity]:
    """Build an Identity from the request's auth evidence.

    ``session_user``: dict from OIDCAuth.session_user() or None.
    ``token_ok``: True when a *configured* static token verified.
    Returns None when the caller is not authenticated at all.
    """
    if session_user and session_user.get("email"):
        email = str(session_user["email"]).strip().lower()
        return Identity(email=email, via_token=False,
                        is_superadmin=email in get_admin_emails(cfg))
    if token_ok:
        # the static token is held by the operator -> superadmin
        return Identity(email="", via_token=True, is_superadmin=True)
    return None


def site_role(identity: Optional[Identity], site: dict) -> str:
    """Return 'superadmin' | 'owner' | 'maintainer' | '' for a site."""
    if identity is None:
        return ""
    if identity.is_superadmin:
        return "superadmin"
    if not identity.email:
        return ""
    owner = (site.get("owner") or "").strip().lower()
    if identity.email == owner:
        return "owner"
    maintainers = [str(m).strip().lower()
                   for m in (site.get("maintainers") or [])]
    if identity.email in maintainers:
        return "maintainer"
    return ""


def can_view(identity: Optional[Identity], site: dict) -> bool:
    return site_role(identity, site) in ("superadmin", "owner", "maintainer")


def can_edit_meta(identity: Optional[Identity], site: dict) -> bool:
    """PATCH name/description/editable — owner or superadmin."""
    return site_role(identity, site) in ("superadmin", "owner")


def can_delete(identity: Optional[Identity], site: dict) -> bool:
    return site_role(identity, site) in ("superadmin", "owner")


def can_transfer(identity: Optional[Identity], site: dict) -> bool:
    return site_role(identity, site) in ("superadmin", "owner")


def can_manage_maintainers(identity: Optional[Identity], site: dict) -> bool:
    return site_role(identity, site) in ("superadmin", "owner")


def can_rollback(identity: Optional[Identity], site: dict) -> bool:
    return site_role(identity, site) in ("superadmin", "owner", "maintainer")
