"""Network probes must never be able to stall startup.

A silent, apparently-alive server is one of the worst failure modes we
can hand a user: the process is there, the port looks bound, and nothing
in the log explains anything. That is exactly what an unbounded
``socket.connect`` to a public address produces on networks that neither
answer nor refuse — the CI macOS runner being one of them.

Every such probe is cosmetic (it exists to print a nicer URL), so every
such probe gets a timeout.
"""
from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class TestOutboundProbesAreBounded(unittest.TestCase):

    def _sources(self):
        for path in (REPO / "golive").rglob("*.py"):
            yield path, path.read_text(encoding="utf-8")

    def test_every_external_connect_sets_a_timeout(self):
        """No `connect(("8.8.8.8", ...))` without a preceding settimeout."""
        offenders = []
        for path, src in self._sources():
            lines = src.splitlines()
            for i, line in enumerate(lines):
                if re.search(r'connect\(\("(?:\d{1,3}\.){3}\d{1,3}"', line):
                    window = "\n".join(lines[max(0, i - 4):i + 1])
                    if "settimeout" not in window:
                        offenders.append(f"{path.name}:{i + 1}")
        self.assertEqual(offenders, [],
                         "unbounded outbound probe(s): " + ", ".join(offenders))

    def test_lan_ip_has_a_timeout(self):
        from golive.server import app
        self.assertIn("settimeout", inspect.getsource(app._lan_ip))

    def test_lan_ip_returns_loopback_on_failure(self):
        """Failure must be fast and harmless, not an exception."""
        from golive.server.app import _lan_ip
        self.assertTrue(_lan_ip())          # never raises, never empty

    def test_loopback_serve_skips_the_probe(self):
        """Binding to localhost should not touch the network at all."""
        import inspect as _i
        from golive.server import app
        src = _i.getsource(app.serve)
        probe_line = src.index("_lan_ip()")
        guard_line = src.index("if not loopback")
        self.assertLess(guard_line, probe_line,
                        "_lan_ip() must sit behind the loopback guard")


if __name__ == "__main__":
    unittest.main()
