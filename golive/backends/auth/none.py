"""golive.backends.auth.none — no-auth provider (default for single-user)."""

from golive.backends.auth.base import AuthProvider


class NoneAuth(AuthProvider):
    """Allows everything. Fine on localhost; use TokenAuth on shared hosts."""

    name = "none"

    def verify(self, request_headers: dict) -> bool:
        return True
