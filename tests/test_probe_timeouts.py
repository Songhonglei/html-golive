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


class TestServerBindSkipsReverseDNS(unittest.TestCase):
    """Binding must not depend on a name lookup succeeding.

    ``HTTPServer.server_bind`` calls ``socket.getfqdn()`` to fill in a
    field we only use for logging. When the resolver is slow the server
    silently hangs before printing anything — the hardest possible
    failure to diagnose, and exactly what happened on macOS.
    """

    def test_app_server_overrides_server_bind(self):
        from golive.server.app import _ThreadingServer
        import http.server
        self.assertIsNot(_ThreadingServer.server_bind,
                         http.server.HTTPServer.server_bind)

    def test_bind_is_fast_and_sets_server_name(self):
        import time
        from golive.server.app import _ThreadingServer, GoliveHandler
        started = time.time()
        srv = _ThreadingServer(("127.0.0.1", 0), GoliveHandler)
        try:
            elapsed = time.time() - started
            self.assertLess(elapsed, 2.0, "bind should not wait on a resolver")
            self.assertEqual(srv.server_name, "127.0.0.1")
            self.assertTrue(srv.server_port)
        finally:
            srv.server_close()

    def test_preview_server_also_skips_the_lookup(self):
        src = (REPO / "golive" / "core" / "preview_server.py").read_text(
            encoding="utf-8")
        self.assertIn("def server_bind", src,
                      "preview server must override server_bind too")


if __name__ == "__main__":
    unittest.main()
