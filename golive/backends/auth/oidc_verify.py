"""golive.backends.auth.oidc_verify — id_token signature verification.

Security-critical module: validates RS256 id_token signatures against
JWKS keys fetched from the IdP discovery document.

Design decisions:
  - Uses the ``cryptography`` library (industry standard) as an optional
    dependency via the ``[oidc]`` extra. If not installed and OIDC is
    configured with verify_signature=True (default), the server refuses
    to start — it NEVER silently degrades to unverified tokens.
  - JWKS keys are cached with a 1-hour TTL. When a ``kid`` is not found
    in the cache, we force a single refresh before rejecting (IdPs
    rotate keys).
  - ``alg: none`` is hard-rejected. ``alg`` must match the key type in
    the JWKS (RS256 → RSA key). This closes the two classic JWT
    attack surfaces.
  - Claims validated: ``iss`` (exact match), ``aud`` (contains
    client_id), ``exp`` (not expired), ``nbf`` (not future, with
    clock skew tolerance), ``iat`` (not too far in the future).
  - ``nonce`` is validated by the caller (oauth.py) since it requires
    per-session state.

This module is intentionally separate from oauth.py so it can be tested
in isolation with self-signed RSA keys.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Optional

# ── optional dependency ─────────────────────────────────────────────────────

_TRY_IMPORT_ERROR: Optional[str] = None

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
    from cryptography.exceptions import InvalidSignature
    _TRY_IMPORT_ERROR = None
except ImportError as _e:
    _TRY_IMPORT_ERROR = str(_e)


def is_available() -> bool:
    """True when the cryptography library is installed."""
    return _TRY_IMPORT_ERROR is None


def require_cryptography():
    """Raise a clear error if cryptography is not available."""
    if _TRY_IMPORT_ERROR is not None:
        raise RuntimeError(
            "OIDC signature verification requires the 'cryptography' "
            "library. Install it with: pip install html-golive[oidc]\n"
            "  Alternatively, set auth.oidc.verify_signature: false in "
            "golive.yaml to disable verification (NOT recommended — "
            "forged tokens will be accepted)."
        )


# ── constants ───────────────────────────────────────────────────────────────

JWKS_TTL = 3600  # 1 hour
# Tolerance for clock drift between us and the IdP. Keep this small:
# id_tokens are typically valid for only a few minutes, so a generous
# skew silently extends the life of every expired token. 60s covers
# realistic NTP drift without meaningfully widening the window.
CLOCK_SKEW = 60

# Algorithms we accept (key type from JWKS → algorithm mapping)
_ACCEPTED_ALGS = {"RS256"}
_ACCEPTED_KTY_FOR_ALG = {"RS256": "RSA"}


class TokenValidationError(Exception):
    """Raised when id_token fails any validation step."""

    def __init__(self, reason: str, *, can_retry: bool = False):
        super().__init__(reason)
        self.can_retry = can_retry


# ── JWKS cache ──────────────────────────────────────────────────────────────

class JWKSProvider:
    """Fetches and caches JWKS keys with TTL + forced refresh on unknown kid."""

    def __init__(self, jwks_uri: str, fetcher=None):
        self.jwks_uri = jwks_uri
        self._fetcher = fetcher  # callable(url, timeout) -> dict, for testing
        self._keys: dict = {}     # kid -> {key_obj, alg, kty}
        self._expires: float = 0.0
        self._last_fetch: float = 0.0

    def _do_fetch(self) -> dict:
        if self._fetcher is not None:
            return self._fetcher(self.jwks_uri)
        import requests
        resp = requests.get(self.jwks_uri, timeout=15)
        if resp.status_code != 200:
            raise TokenValidationError(
                f"JWKS fetch failed (HTTP {resp.status_code}) at {self.jwks_uri}"
            )
        return resp.json()

    def _parse_jwks(self, jwks: dict) -> None:
        require_cryptography()
        keys = {}
        for jwk in jwks.get("keys") or []:
            kid = jwk.get("kid", "")
            kty = jwk.get("kty", "")
            alg = jwk.get("alg", "RS256")
            if kty == "RSA" and alg in _ACCEPTED_ALGS:
                try:
                    pub = _rsa_public_from_jwk(jwk)
                    keys[kid] = {"key": pub, "alg": alg, "kty": kty}
                except Exception:
                    # skip unparseable keys rather than crash
                    pass
        self._keys = keys
        self._expires = time.time() + JWKS_TTL
        self._last_fetch = time.time()

    def get_key(self, kid: str):
        """Return the RSA public key for a kid, refreshing once if unknown."""
        if not self._keys or time.time() > self._expires:
            self._parse_jwks(self._do_fetch())
        entry = self._keys.get(kid)
        if entry is None:
            # Force one refresh (key rotation by IdP)
            self._parse_jwks(self._do_fetch())
            entry = self._keys.get(kid)
        if entry is None:
            raise TokenValidationError(
                f"no matching key for kid={kid!r} in JWKS",
                can_retry=True,
            )
        return entry


def _rsa_public_from_jwk(jwk: dict):
    """Build an RSAPublicKey from a JWK dict (n, e)."""
    n = _b64url_int(jwk["n"])
    e = _b64url_int(jwk["e"])
    return rsa.RSAPublicNumbers(e, n).public_key()


def _b64url_int(data: str) -> int:
    padded = data + "=" * (-len(data) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


# ── token parsing + signature verification ─────────────────────────────────

def _split_token(token: str) -> tuple:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenValidationError("malformed id_token (expected 3 parts)")
    header_b, payload_b, sig_b = parts
    return header_b, payload_b, sig_b


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _decode_segment(seg: str) -> dict:
    try:
        return json.loads(_b64url_decode(seg))
    except (ValueError, json.JSONDecodeError) as e:
        raise TokenValidationError(f"malformed token segment: {e}")


def verify_id_token(
    token: str,
    *,
    issuer: str,
    client_id: str,
    jwks_provider: JWKSProvider,
    nonce: Optional[str] = None,
    verify_signature: bool = True,
    clock_skew: int = CLOCK_SKEW,
) -> dict:
    """Verify an id_token and return its claims.

    Raises TokenValidationError on any failure.
    Returns the claims dict on success.
    """
    if verify_signature:
        require_cryptography()

    header_b, payload_b, sig_b = _split_token(token)
    header = _decode_segment(header_b)
    payload = _decode_segment(payload_b)
    signature = _b64url_decode(sig_b)

    # ── alg check ──
    alg = header.get("alg", "")
    if alg == "none":
        raise TokenValidationError(
            "id_token alg=none is rejected (security: unsigned tokens "
            "are never accepted)"
        )
    if verify_signature and alg not in _ACCEPTED_ALGS:
        raise TokenValidationError(
            f"id_token alg={alg!r} is not supported "
            f"(accepted: {', '.join(sorted(_ACCEPTED_ALGS))})"
        )

    # ── signature verification ──
    if verify_signature:
        kid = header.get("kid", "")
        if not kid:
            raise TokenValidationError(
                "id_token header missing 'kid' — required for signature "
                "verification"
            )
        entry = jwks_provider.get_key(kid)
        # Verify alg matches key type
        expected_kty = _ACCEPTED_KTY_FOR_ALG.get(alg)
        if expected_kty and entry["kty"] != expected_kty:
            raise TokenValidationError(
                f"id_token alg={alg} does not match JWKS key type "
                f"{entry['kty']!r} for kid={kid!r}"
            )
        signing_input = (header_b + "." + payload_b).encode("ascii")
        try:
            entry["key"].verify(
                signature,
                signing_input,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            raise TokenValidationError(
                "id_token signature verification failed — token is "
                "tampered or signed with a different key"
            )

    # ── claims validation ──
    now = int(time.time())

    # iss
    token_iss = payload.get("iss", "")
    if token_iss != issuer:
        raise TokenValidationError(
            f"iss mismatch: token has {token_iss!r}, expected {issuer!r}"
        )

    # aud
    token_aud = payload.get("aud", "")
    if isinstance(token_aud, str):
        aud_list = [token_aud]
    elif isinstance(token_aud, list):
        aud_list = token_aud
    else:
        raise TokenValidationError(f"malformed aud claim: {token_aud!r}")
    if client_id not in aud_list:
        raise TokenValidationError(
            f"aud mismatch: token audience {aud_list} does not include "
            f"client_id {client_id!r}"
        )

    # exp — REQUIRED by OpenID Connect Core 2.0 §2. A token without it
    # would never expire, so a leaked one would be valid forever.
    exp = payload.get("exp")
    if exp is None:
        raise TokenValidationError(
            "id_token has no exp claim — refusing a token that never expires"
        )
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        raise TokenValidationError("malformed exp claim")
    if now > exp + clock_skew:
        raise TokenValidationError(
            f"id_token expired (exp={exp}, now={now})"
        )

    # nbf
    nbf = payload.get("nbf")
    if nbf is not None:
        try:
            nbf = int(nbf)
        except (TypeError, ValueError):
            raise TokenValidationError("malformed nbf claim")
        if now + clock_skew < nbf:
            raise TokenValidationError(
                f"id_token not yet valid (nbf={nbf}, now={now})"
            )

    # iat — sanity check (not too far in the future)
    iat = payload.get("iat")
    if iat is not None:
        try:
            iat = int(iat)
        except (TypeError, ValueError):
            raise TokenValidationError("malformed iat claim")
        if iat > now + clock_skew:
            raise TokenValidationError(
                f"id_token iat is in the future (iat={iat}, now={now})"
            )

    # nonce (if provided by caller)
    if nonce is not None:
        token_nonce = payload.get("nonce", "")
        if token_nonce != nonce:
            raise TokenValidationError(
                "nonce mismatch — possible token replay attack"
            )

    return payload
