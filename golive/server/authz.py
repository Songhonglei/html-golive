"""golive.server.authz — role resolution for the admin portal (M5).

Roles (per request, per site):
  superadmin  — email in the effective superadmin set (see below). A valid
                *token* auth is also treated as superadmin: the static
                GOLIVE_TOKEN is operator-held by definition.
  owner       — registry ``owner`` column matches the session email.
  maintainer  — email appears in the registry ``maintainers`` list.
  (none)      — authenticated but unrelated to the site.

Superadmins come from two sources (M7), and the effective set is their
union:
  builtin  — ``admin.admins`` in golive.yaml, or the ``GOLIVE_ADMINS`` env
             (comma separated, env wins over yaml). Read-only at runtime:
             the permissions API refuses to delete these so an operator
             cannot lock themselves out.
  managed  — the ``managed_admins`` table in registry.db, maintained via
             ``/api/admin/permissions/admins``.

Identity sources, in order of trust:
  1. OIDC session (server-verified email)
  2. static token (Authorization: Bearer / X-Golive-Token) -> superadmin

This module is pure logic — no HTTP. The handler passes in the already
verified identity; nothing here reads headers or cookies.
"""

from __future__ import annotations

import os
from typing import Optional


def get_builtin_admin_emails(cfg=None) -> list:
    """Config-declared superadmins. env GOLIVE_ADMINS > yaml admin.admins.

    These are immutable at runtime — the API cannot remove them.
    """
    env_val = os.environ.get("GOLIVE_ADMINS", "").strip()
    if env_val:
        return [a.strip().lower() for a in env_val.split(",") if a.strip()]
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    return [str(a).strip().lower() for a in (cfg.admin.admins or [])
            if str(a).strip()]


def get_managed_admin_emails() -> list:
    """API-managed superadmins (registry.db). Never raises."""
    try:
        from golive.backends.registry.admin_store import get_managed_admins
        return get_managed_admins().emails()
    except Exception:  # noqa: BLE001 — a broken store must not deny builtins
        return []


def get_admin_emails(cfg=None) -> list:
    """Effective superadmin set: builtin ∪ managed, sorted and unique."""
    return sorted(set(get_builtin_admin_emails(cfg))
                  | set(get_managed_admin_emails()))


def is_builtin_admin(email: str, cfg=None) -> bool:
    return (email or "").strip().lower() in get_builtin_admin_emails(cfg)


class Identity:
    """Resolved caller identity for one request."""

    __slots__ = ("email", "via_token", "is_superadmin")

    def __init__(self, email: str = "", via_token: bool = False,
                 is_superadmin: bool = False):
        self.email = (email or "").strip().lower()
        self.via_token = via_token
        self.is_superadmin = is_superadmin

    @property
    def is_builtin_admin(self) -> bool:
        """True when superadmin status comes from config (not the API).

        Token identities have no email and are operator-held, so they
        count as builtin too.
        """
        if not self.is_superadmin:
            return False
        if self.via_token and not self.email:
            return True
        return is_builtin_admin(self.email)

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "via_token": self.via_token,
            "superadmin": self.is_superadmin,
            "builtin": self.is_builtin_admin,
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
