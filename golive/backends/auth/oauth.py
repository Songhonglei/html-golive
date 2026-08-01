"""golive.backends.auth.oauth — generic OIDC AuthProvider (M3 → v0.8.0).

Works with any OpenID Connect IdP that publishes a discovery document
(``/.well-known/openid-configuration``): Google, Keycloak, Authentik,
Okta, Auth0, self-hosted Dex … GitHub's OAuth is not OIDC — use an OIDC
bridge (e.g. Dex) or a provider that issues OIDC tokens.

Flow (implemented in golive.server.app via this provider):
  GET /auth/login     -> 302 to IdP authorization endpoint (state + PKCE + nonce)
  GET /auth/callback  -> code -> token -> verify id_token -> userinfo -> session
  GET /auth/logout    -> clear cookie (+ optional IdP end_session redirect)
  GET /auth/me        -> current session identity JSON

v0.8.0 changes (OIDC production hardening):
  - id_token signature verification via JWKS (RS256)
  - nonce generation + validation (replay attack prevention)
  - alg=none hard-rejected; alg/key-type mismatch rejected
  - claims validated: iss, aud, exp, nbf, iat (with clock skew tolerance)
  - JWKS cached 1h, force-refreshed on unknown kid
  - ``auth.oidc.verify_signature: false`` to opt out (NOT recommended;
    prints a prominent warning at startup)
  - ``cryptography`` is an optional dependency ([oidc] extra). Without it,
    OIDC with default verify_signature=True refuses to start.

Config (golive.yaml):
  auth:
    provider: oidc
    oidc:
      issuer: https://accounts.google.com
      client_id: xxx.apps.googleusercontent.com
      client_secret_env: GOLIVE_OIDC_CLIENT_SECRET
      redirect_uri: http://localhost:8787/auth/callback
      scopes: "openid email profile"
      session_ttl: 28800
      cookie_secret_env: GOLIVE_COOKIE_SECRET
      force_secure_cookie: false
      verify_signature: true   # default; set false to disable (dangerous)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.parse
from typing import Optional

from golive.backends.auth.base import AuthProvider

COOKIE_NAME = "golive_session"
STATE_TTL = 600          # seconds an auth request (state/PKCE/nonce) stays valid
DEFAULT_TIMEOUT = 15


class OIDCError(RuntimeError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_or_create_cookie_secret() -> str:
    """Return a stable cookie-signing secret persisted under GOLIVE_HOME.

    Generated once (0600 file) so signed session cookies survive a server
    restart without the operator having to set GOLIVE_COOKIE_SECRET. If the
    home dir is unwritable we fall back to an ephemeral per-process key and
    warn — sessions then die on restart, but auth still works.
    """
    try:
        from golive.core.paths import get_home
        path = get_home() / ".cookie_secret"
        if path.exists():
            val = path.read_text(encoding="utf-8").strip()
            if val:
                return val
        val = secrets.token_hex(32)
        path.write_text(val, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return val
    except Exception as e:  # noqa: BLE001 — degrade to ephemeral
        print(f"⚠️  could not persist cookie secret ({e}); using an "
              f"ephemeral key — sessions will not survive a restart. "
              f"Set GOLIVE_COOKIE_SECRET to silence this.", file=sys.stderr)
        return secrets.token_hex(32)


class OIDCAuth(AuthProvider):
    """Generic OIDC provider with PKCE + signed session cookies + id_token verification."""

    name = "oidc"

    def __init__(self, issuer: str = "", client_id: str = "",
                 client_secret: str = "", redirect_uri: str = "",
                 scopes: str = "openid email profile",
                 session_ttl: int = 8 * 3600, cookie_secret: str = "",
                 force_secure_cookie: bool = False,
                 verify_signature: bool = True):
        if not issuer:
            from golive.config import get_config
            au = get_config().auth
            issuer = au.oidc_issuer
            client_id = client_id or au.oidc_client_id
            client_secret = client_secret or au.oidc_client_secret
            redirect_uri = redirect_uri or au.oidc_redirect_uri
            scopes = au.oidc_scopes or scopes
            session_ttl = au.oidc_session_ttl or session_ttl
            cookie_secret = cookie_secret or au.oidc_cookie_secret
            force_secure_cookie = au.oidc_force_secure_cookie
            verify_signature = au.oidc_verify_signature
        if not issuer or not client_id:
            raise OIDCError("auth.oidc.issuer and auth.oidc.client_id are required")
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.session_ttl = int(session_ttl)
        self.force_secure_cookie = bool(force_secure_cookie)

        # Signature verification (v0.8.0)
        self.verify_signature = verify_signature
        if not verify_signature:
            print(
                "⚠️  ⚠️  ⚠️  OIDC id_token signature verification is DISABLED.\n"
                "  auth.oidc.verify_signature: false in golive.yaml\n"
                "  This means FORGED id_tokens will be accepted without\n"
                "  detection. This is a security risk — only use this in\n"
                "  development or when your IdP does not support signature\n"
                "  verification. NEVER enable this in production.\n",
                file=sys.stderr,
            )
        elif self.verify_signature:
            from golive.backends.auth.oidc_verify import is_available, require_cryptography
            if not is_available():
                require_cryptography()  # raises with a clear message
                raise OIDCError(  # pragma: no cover — require_cryptography raises first
                    "OIDC signature verification requires the 'cryptography' "
                    "library. Install with: pip install html-golive[oidc]\n"
                    "  Or set auth.oidc.verify_signature: false to disable "
                    "(NOT recommended)."
                )

        # cookie secret precedence: explicit arg > env > persisted file.
        _sec = cookie_secret or os.environ.get("GOLIVE_COOKIE_SECRET", "")
        if not _sec:
            _sec = _load_or_create_cookie_secret()
        self._cookie_secret = _sec.encode("utf-8")
        self._discovery: Optional[dict] = None
        self._sessions: dict = {}       # sid -> {sub, email, name, exp}
        self._pending: dict = {}        # state -> {verifier, nonce, exp}
        self._jwks_provider = None      # lazy-init on first complete_login

    # ── discovery ───────────────────────────────────────────────────────────

    def discovery(self) -> dict:
        if self._discovery is None:
            import requests
            url = self.issuer + "/.well-known/openid-configuration"
            resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                raise OIDCError(f"OIDC discovery failed (HTTP {resp.status_code}) at {url}")
            doc = resp.json()
            for key in ("authorization_endpoint", "token_endpoint"):
                if key not in doc:
                    raise OIDCError(f"OIDC discovery document missing {key}")
            self._discovery = doc
        return self._discovery

    def _get_jwks_provider(self):
        """Lazy-init the JWKS provider from the discovery document."""
        if self._jwks_provider is None:
            from golive.backends.auth.oidc_verify import JWKSProvider
            doc = self.discovery()
            jwks_uri = doc.get("jwks_uri", "")
            if not jwks_uri:
                raise OIDCError(
                    "OIDC discovery document does not contain jwks_uri — "
                    "cannot verify id_token signatures"
                )
            self._jwks_provider = JWKSProvider(jwks_uri)
        return self._jwks_provider

    # ── login: build the authorization redirect ─────────────────────────────

    def _prune_pending(self) -> None:
        now = time.time()
        for k in [k for k, v in self._pending.items() if v["exp"] < now]:
            self._pending.pop(k, None)

    def begin_login(self) -> str:
        """Return the IdP authorization URL (registers state + PKCE + nonce)."""
        self._prune_pending()
        doc = self.discovery()
        state = secrets.token_urlsafe(24)
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        nonce = secrets.token_urlsafe(24)
        self._pending[state] = {
            "verifier": verifier,
            "nonce": nonce,
            "exp": time.time() + STATE_TTL,
        }
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": nonce,
        }
        return doc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

    # ── callback: code -> tokens -> verify -> userinfo -> session ──────────

    def complete_login(self, code: str, state: str) -> dict:
        """Exchange the code; verify id_token; return {sid, cookie_value, user}.

        Raises OIDCError on any failure.
        """
        import requests

        pend = self._pending.pop(state or "", None)
        if pend is None or pend["exp"] < time.time():
            raise OIDCError("invalid or expired state (possible CSRF) — retry login")

        doc = self.discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": pend["verifier"],
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        resp = requests.post(doc["token_endpoint"], data=data,
                             headers={"Accept": "application/json"},
                             timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            raise OIDCError(f"token exchange failed (HTTP {resp.status_code}): "
                            f"{resp.text[:200]}")
        tokens = resp.json()

        # ── verify id_token (v0.8.0) ──
        id_token = tokens.get("id_token", "")
        verified_claims = {}
        if id_token and self.verify_signature:
            from golive.backends.auth.oidc_verify import (
                verify_id_token, TokenValidationError,
            )
            try:
                verified_claims = verify_id_token(
                    id_token,
                    issuer=self.issuer,
                    client_id=self.client_id,
                    jwks_provider=self._get_jwks_provider(),
                    nonce=pend.get("nonce"),
                    verify_signature=True,
                )
            except TokenValidationError as e:
                raise OIDCError(f"id_token verification failed: {e}")
        elif id_token and not self.verify_signature:
            # Verification explicitly disabled — decode without verifying
            # (backward compat, but warn at startup already)
            try:
                payload = id_token.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                verified_claims = json.loads(base64.urlsafe_b64decode(payload))
            except (ValueError, TypeError):
                pass

        user = self._resolve_user(doc, tokens, verified_claims)
        if not (user.get("sub") or user.get("email")):
            raise OIDCError("IdP returned no usable identity (sub/email)")

        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = {**user, "exp": time.time() + self.session_ttl}
        return {"sid": sid, "cookie_value": self._sign_sid(sid), "user": user}

    def _resolve_user(self, doc: dict, tokens: dict,
                      verified_claims: dict = None) -> dict:
        """userinfo endpoint preferred; fall back to verified id_token claims."""
        import requests

        access_token = tokens.get("access_token", "")
        userinfo_ep = doc.get("userinfo_endpoint", "")
        if access_token and userinfo_ep:
            try:
                resp = requests.get(
                    userinfo_ep,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 200:
                    ui = resp.json()
                    return {"sub": str(ui.get("sub", "")),
                            "email": str(ui.get("email", "")).lower(),
                            "name": str(ui.get("name", "")
                                        or ui.get("preferred_username", ""))}
            except requests.RequestException:
                pass

        # fallback: verified id_token claims (already validated above)
        if verified_claims:
            return {"sub": str(verified_claims.get("sub", "")),
                    "email": str(verified_claims.get("email", "")).lower(),
                    "name": str(verified_claims.get("name", ""))}
        return {}

    # ── cookie signing / session lookup ─────────────────────────────────────

    def _sign_sid(self, sid: str) -> str:
        mac = hmac.new(self._cookie_secret, sid.encode("ascii"),
                       hashlib.sha256).hexdigest()
        return f"{sid}.{mac}"

    def _verify_cookie(self, cookie_value: str) -> Optional[str]:
        if not cookie_value or "." not in cookie_value:
            return None
        sid, mac = cookie_value.rsplit(".", 1)
        expect = hmac.new(self._cookie_secret, sid.encode("ascii"),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expect):
            return None
        return sid

    def _prune_sessions(self) -> None:
        now = time.time()
        for k in [k for k, v in self._sessions.items() if v["exp"] < now]:
            self._sessions.pop(k, None)

    def session_user(self, request_headers: dict) -> Optional[dict]:
        """Resolve the session cookie into a user dict (or None)."""
        headers = {str(k).lower(): str(v) for k, v in (request_headers or {}).items()}
        raw = headers.get("cookie", "")
        cookie_value = ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE_NAME:
                cookie_value = v
                break
        sid = self._verify_cookie(cookie_value)
        if not sid:
            return None
        self._prune_sessions()
        sess = self._sessions.get(sid)
        if not sess or sess["exp"] < time.time():
            self._sessions.pop(sid, None)
            return None
        return {"sub": sess.get("sub", ""), "email": sess.get("email", ""),
                "name": sess.get("name", "")}

    def logout(self, request_headers: dict) -> None:
        headers = {str(k).lower(): str(v) for k, v in (request_headers or {}).items()}
        raw = headers.get("cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE_NAME:
                sid = self._verify_cookie(v)
                if sid:
                    self._sessions.pop(sid, None)
                break

    def build_cookie(self, cookie_value: str, secure: bool) -> str:
        attrs = [f"{COOKIE_NAME}={cookie_value}", "Path=/", "HttpOnly",
                 "SameSite=Lax", f"Max-Age={self.session_ttl}"]
        if secure or self.force_secure_cookie:
            attrs.append("Secure")
        return "; ".join(attrs)

    def clear_cookie(self) -> str:
        return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def end_session_url(self, post_logout_redirect: str = "") -> str:
        """IdP end_session URL when the IdP advertises one ('' otherwise)."""
        try:
            ep = self.discovery().get("end_session_endpoint", "")
        except OIDCError:
            return ""
        if not ep:
            return ""
        if post_logout_redirect:
            return ep + "?" + urllib.parse.urlencode(
                {"post_logout_redirect_uri": post_logout_redirect})
        return ep

    # ── AuthProvider interface ──────────────────────────────────────────────

    def verify(self, request_headers: dict) -> bool:
        return self.session_user(request_headers) is not None

    def identity(self, request_headers: dict) -> str:
        user = self.session_user(request_headers)
        return (user or {}).get("email", "")
