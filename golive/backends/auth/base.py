"""golive.backends.auth.base — AuthProvider interface."""

from abc import ABC, abstractmethod


class AuthProvider(ABC):
    """Auth abstraction for serve-mode write operations (and M3 editor)."""

    name = "base"

    @abstractmethod
    def verify(self, request_headers: dict) -> bool:
        """Return True when the request is allowed to perform write ops."""

    def identity(self, request_headers: dict) -> str:
        """Best-effort caller identity (empty string when unknown)."""
        return ""
