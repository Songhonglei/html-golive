"""golive test helpers.

Kept deliberately tiny: only things every test module may need, so that
importing the package never drags in golive itself (several modules read
``$GOLIVE_HOME`` at import time and must set it first).
"""

from __future__ import annotations

import socket
from pathlib import Path


def lan_ip_or_none():
    """Best-effort non-loopback IPv4 of this host, or None.

    ``socket.gethostbyname(socket.gethostname())`` is the obvious way to
    write this and it is wrong on macOS, where the machine's ``.local``
    hostname frequently has no A record and the call raises
    ``socket.gaierror``. Tests that want to talk to the box over a
    routable address should skip rather than fail — the thing under test
    is golive's auth model, not the developer's DNS.

    A UDP "connect" to a public address performs no traffic but makes the
    kernel pick the outbound interface, which works on macOS, Linux and
    inside containers alike; the hostname lookup is only a fallback.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except (OSError, socket.gaierror):
        return None
    return None if (not ip or ip.startswith("127.")) else ip


def same_path(a, b) -> bool:
    """Path equality that survives symlinked temp dirs.

    macOS resolves ``/tmp`` to ``/private/tmp``, so a path handed to a
    test and the path golive reports back can be the same directory and
    still compare unequal as strings.
    """
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:  # pragma: no cover — unreadable path
        return str(a) == str(b)
