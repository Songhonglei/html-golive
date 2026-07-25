"""golive.backends.auth.presets — one-line OIDC provider presets.

Set ``auth.oidc.preset: google`` (or okta / auth0 / keycloak / authentik /
azure) and golive fills in the well-known public fields for that IdP —
issuer template, default scopes — so you only supply ``client_id`` and
the secret env. Explicit ``auth.oidc.*`` fields always override a preset.

Presets only ever contain PUBLIC, non-secret values. Never put a client
secret here.
"""

from __future__ import annotations

# Each preset supplies the fields that are safe to hard-code for a given
# IdP. `issuer` may contain a `{domain}` / `{tenant}` placeholder that is
# resolved from auth.oidc.domain / auth.oidc.tenant when present.
PRESETS: dict = {
    "google": {
        "issuer": "https://accounts.google.com",
        "scopes": "openid email profile",
    },
    "auth0": {
        # requires auth.oidc.domain: your-tenant.us.auth0.com
        "issuer": "https://{domain}",
        "scopes": "openid email profile",
    },
    "okta": {
        # requires auth.oidc.domain: your-org.okta.com
        "issuer": "https://{domain}",
        "scopes": "openid email profile",
    },
    "azure": {
        # requires auth.oidc.tenant: <tenant-id> or "organizations"/"common"
        "issuer": "https://login.microsoftonline.com/{tenant}/v2.0",
        "scopes": "openid email profile",
    },
    "keycloak": {
        # requires auth.oidc.issuer OR domain+realm; kept generic
        # e.g. issuer: https://kc.example.com/realms/myrealm
        "scopes": "openid email profile",
    },
    "authentik": {
        # requires auth.oidc.issuer: https://authentik.example.com/application/o/<slug>/
        "scopes": "openid email profile",
    },
}

SUPPORTED = sorted(PRESETS.keys())


def resolve_preset(preset: str, *, domain: str = "", tenant: str = "",
                   realm: str = "") -> dict:
    """Return {issuer, scopes} for a named preset, or raise ValueError.

    `domain` / `tenant` / `realm` fill placeholders where a preset needs
    tenant-specific host info. Fields the preset omits are returned empty
    so the caller keeps whatever the user configured explicitly.
    """
    key = (preset or "").strip().lower()
    if key not in PRESETS:
        raise ValueError(
            f"unknown auth.oidc.preset: {preset!r} "
            f"(supported: {', '.join(SUPPORTED)})"
        )
    spec = dict(PRESETS[key])
    issuer = spec.get("issuer", "")
    if "{domain}" in issuer:
        if not domain:
            raise ValueError(
                f"auth.oidc.preset: {key} requires auth.oidc.domain "
                f"(e.g. your-tenant.{key}.com)"
            )
        issuer = issuer.replace("{domain}", domain.strip().rstrip("/"))
    if "{tenant}" in issuer:
        if not tenant:
            raise ValueError(
                "auth.oidc.preset: azure requires auth.oidc.tenant "
                "(tenant id, or 'organizations' / 'common')"
            )
        issuer = issuer.replace("{tenant}", tenant.strip())
    out = {"scopes": spec.get("scopes", "")}
    if issuer:
        out["issuer"] = issuer.rstrip("/")
    return out
