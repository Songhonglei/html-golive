"""golive.backends.auth.token — static-token auth provider.

Token source order:
  1. explicit token passed to constructor (from golive.yaml)
  2. env GOLIVE_TOKEN

Clients authenticate with either header:
  Authorization: Bearer <token>
  X-Golive-Token: <token>
"""

import hmac
import os

from golive.backends.auth.base import AuthProvider


class TokenAuth(AuthProvider):
    name = "token"

    def __init__(self, token: str = ""):
        self.token = token or os.environ.get("GOLIVE_TOKEN", "")

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def verify(self, request_headers: dict) -> bool:
        if not self.configured:
            return False
        # normalize header keys to lowercase
        headers = {str(k).lower(): str(v) for k, v in (request_headers or {}).items()}
        candidate = headers.get("x-golive-token", "")
        if not candidate:
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                candidate = auth[7:].strip()
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self.token)


def get_auth_provider():
    """Factory: TokenAuth when GOLIVE_TOKEN is set, else NoneAuth."""
    tok = os.environ.get("GOLIVE_TOKEN", "")
    if tok:
        return TokenAuth(tok)
    from golive.backends.auth.none import NoneAuth
    return NoneAuth()
