"""v0.7.1 — background service management (`golive serve start|stop|...`).

Covers:
  * the full start → status → stop → restart lifecycle against a real child
  * a stale pidfile is cleaned instead of blocking a start
  * a second `start` does not spawn a second process
  * `golive serve` with no sub-action still runs in the FOREGROUND
    (this is the compatibility guarantee — every doc says `golive serve`)
  * logs tail, port-conflict classification, health-probe degradation

Each lifecycle test uses its own GOLIVE_HOME so pidfiles never collide.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP_HOME = tempfile.mkdtemp(prefix="golive_service080_")
os.environ.setdefault("GOLIVE_HOME", _TMP_HOME)

REPO_ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def temp_home():
    """Point golive.core.paths at a throwaway home for the duration.

    ``get_home()`` resolves symlinks, and on macOS ``/tmp`` is a symlink to
    ``/private/tmp`` — so resolve here too or every path comparison in this
    module fails on a mac while passing on Linux.
    """
    from golive.core import paths
    home = str(Path(tempfile.mkdtemp(prefix="golive_svc_case_")).resolve())
    prev_env = os.environ.get("GOLIVE_HOME")
    prev_resolved = paths._resolved_home
    os.environ["GOLIVE_HOME"] = home
    paths._resolved_home = None
    try:
        yield Path(home)
    finally:
        if prev_env is None:
            os.environ.pop("GOLIVE_HOME", None)
        else:
            os.environ["GOLIVE_HOME"] = prev_env
        paths._resolved_home = prev_resolved
        shutil.rmtree(home, ignore_errors=True)


@contextmanager
def captured():
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


def run_cli(*argv):
    from golive.cli import main
    with captured() as buf:
        rc = main(list(argv))
    return rc, buf.getvalue()


@contextmanager
def foreign_listener():
    """A listening socket that is NOT golive (404s /health)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


# ── lifecycle ───────────────────────────────────────────────────────────────

class TestServiceLifecycle(unittest.TestCase):
    def test_start_status_stop(self):
        from golive.core import service
        with temp_home() as home:
            port = free_port()
            res = service.start(host="127.0.0.1", port=port)
            try:
                self.assertTrue(res["ok"], res["message"])
                self.assertEqual(res["state"], "started")
                self.assertTrue(service.pid_alive(res["pid"]))

                # pidfile written where we promised
                pf = home / "golive.pid"
                self.assertTrue(pf.is_file())
                rec = json.loads(pf.read_text(encoding="utf-8"))
                self.assertEqual(rec["pid"], res["pid"])
                self.assertEqual(rec["port"], port)

                # log file written where we promised
                self.assertTrue((home / "logs" / "serve.log").is_file())

                st = service.status()
                self.assertTrue(st["running"])
                self.assertTrue(st["managed"])
                self.assertEqual(st["port"], port)
                self.assertEqual(st["pid"], res["pid"])

                health = service.probe_health("127.0.0.1", port)
                self.assertIsNotNone(health)
                self.assertEqual(health.get("status"), "ok")
            finally:
                stop = service.stop()
            self.assertTrue(stop["ok"], stop["message"])
            self.assertIn(stop["state"], ("stopped", "killed"))
            self.assertFalse(service.pid_alive(res["pid"]))
            self.assertFalse((home / "golive.pid").exists())

            after = service.status(port=port)
            self.assertFalse(after["running"])

    def test_restart_replaces_the_process(self):
        from golive.core import service
        with temp_home():
            port = free_port()
            first = service.start(host="127.0.0.1", port=port)
            self.assertTrue(first["ok"], first["message"])
            try:
                res = service.restart()
                self.assertTrue(res["ok"], res["message"])
                self.assertEqual(res["state"], "started")
                self.assertNotEqual(res["pid"], first["pid"])
                self.assertFalse(service.pid_alive(first["pid"]))
                self.assertTrue(service.pid_alive(res["pid"]))
                self.assertEqual(res["port"], port)
            finally:
                service.stop()

    def test_second_start_does_not_spawn_a_twin(self):
        from golive.core import service
        with temp_home():
            port = free_port()
            first = service.start(host="127.0.0.1", port=port)
            self.assertTrue(first["ok"], first["message"])
            try:
                again = service.start(host="127.0.0.1", port=port)
                self.assertTrue(again["ok"])
                self.assertEqual(again["state"], "already-running")
                # pidfile still points at the original process
                rec = service.read_pidfile()
                self.assertEqual(rec["pid"], first["pid"])
                self.assertTrue(service.pid_alive(first["pid"]))
            finally:
                service.stop()

    def test_serve_logs_tail_has_startup_banner(self):
        from golive.core import service
        with temp_home():
            port = free_port()
            res = service.start(host="127.0.0.1", port=port)
            self.assertTrue(res["ok"], res["message"])
            try:
                time.sleep(0.4)
                lines = service.tail(200)
                self.assertTrue(lines)
                self.assertTrue(any("golive serve" in ln for ln in lines),
                                lines[-10:])
            finally:
                service.stop()


# ── pidfile hygiene ─────────────────────────────────────────────────────────

class TestPidfileHygiene(unittest.TestCase):
    def test_stale_pidfile_does_not_block_start(self):
        from golive.core import service
        with temp_home() as home:
            # a pid that is certainly dead
            dead = 999999
            while service.pid_alive(dead):
                dead -= 1
            service.write_pidfile(dead, "127.0.0.1", 1, version="0.0.0")
            self.assertTrue((home / "golive.pid").is_file())

            st = service.status(port=free_port())
            self.assertTrue(st["stale_pidfile"])
            self.assertFalse(st["running"])

            port = free_port()
            res = service.start(host="127.0.0.1", port=port)
            try:
                self.assertTrue(res["ok"], res["message"])
                self.assertEqual(res["state"], "started")
                rec = service.read_pidfile()
                self.assertNotEqual(rec["pid"], dead)
            finally:
                service.stop()

    def test_stop_cleans_a_stale_pidfile(self):
        from golive.core import service
        with temp_home() as home:
            dead = 999998
            while service.pid_alive(dead):
                dead -= 1
            service.write_pidfile(dead, "127.0.0.1", 1)
            res = service.stop()
            self.assertTrue(res["ok"])
            self.assertEqual(res["state"], "stale-cleaned")
            self.assertFalse((home / "golive.pid").exists())

    def test_stop_without_pidfile_is_not_an_error(self):
        from golive.core import service
        with temp_home():
            res = service.stop()
            self.assertTrue(res["ok"])
            self.assertEqual(res["state"], "not-running")

    def test_corrupt_pidfile_is_ignored(self):
        from golive.core import service
        with temp_home() as home:
            (home / "golive.pid").write_text("not json at all",
                                             encoding="utf-8")
            self.assertIsNone(service.read_pidfile())

    def test_bare_integer_pidfile_is_tolerated(self):
        from golive.core import service
        with temp_home() as home:
            (home / "golive.pid").write_text("4242", encoding="utf-8")
            rec = service.read_pidfile()
            self.assertEqual(rec["pid"], 4242)


# ── port conflicts ──────────────────────────────────────────────────────────

class TestPortConflicts(unittest.TestCase):
    def test_foreign_program_on_port_is_named_as_such(self):
        from golive.core import service
        with temp_home():
            with foreign_listener() as port:
                owner, health = service.describe_port("127.0.0.1", port)
                self.assertEqual(owner, "other")
                self.assertIsNone(health)

                res = service.start(host="127.0.0.1", port=port)
                self.assertFalse(res["ok"])
                self.assertEqual(res["state"], "port-taken")
                self.assertIn("another program", res["message"])

    def test_free_port_is_reported_free(self):
        from golive.core import service
        owner, health = service.describe_port("127.0.0.1", free_port())
        self.assertEqual(owner, "free")
        self.assertIsNone(health)

    def test_probe_host_maps_wildcard_to_loopback(self):
        from golive.core import service
        self.assertEqual(service._probe_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(service._probe_host(""), "127.0.0.1")
        self.assertEqual(service._probe_host("127.0.0.1"), "127.0.0.1")

    def test_probe_health_on_dead_port_returns_none(self):
        from golive.core import service
        self.assertIsNone(service.probe_health("127.0.0.1", free_port(),
                                               timeout=0.4))


# ── CLI wiring & foreground compatibility ───────────────────────────────────

class TestServeCliWiring(unittest.TestCase):
    def test_bare_serve_still_runs_in_foreground(self):
        """The compatibility guarantee: `golive serve` must NOT background."""
        import golive.cli as cli

        calls = {}

        def fake_serve(host="127.0.0.1", port=8787):
            calls["host"], calls["port"] = host, port

        import golive.server.app as app
        original = app.serve
        app.serve = fake_serve
        try:
            with captured():
                rc = cli.main(["serve", "--port", "18999",
                               "--host", "127.0.0.1"])
        finally:
            app.serve = original

        self.assertEqual(rc, 0)
        self.assertEqual(calls, {"host": "127.0.0.1", "port": 18999})
        # nothing was backgrounded
        self.assertIsNone(__import__(
            "golive.core.service", fromlist=["x"]).read_pidfile())

    def test_bare_serve_without_port_uses_the_default(self):
        import golive.cli as cli
        import golive.server.app as app

        calls = {}
        original = app.serve
        app.serve = lambda host="127.0.0.1", port=0: calls.update(
            host=host, port=port)
        try:
            with captured():
                rc = cli.main(["serve", "--host", "127.0.0.1"])
        finally:
            app.serve = original
        self.assertEqual(rc, 0)
        self.assertEqual(calls["port"], cli.DEFAULT_SERVE_PORT)

    def test_serve_status_when_not_running(self):
        with temp_home():
            rc, out = run_cli("serve", "status", "--port", str(free_port()))
            self.assertEqual(rc, 1)
            self.assertIn("未运行", out)
            self.assertIn("golive serve start", out)

    def test_serve_stop_when_not_running_is_quiet_success(self):
        with temp_home():
            rc, out = run_cli("serve", "stop")
            self.assertEqual(rc, 0)
            self.assertIn("no background server", out)

    def test_serve_logs_without_a_log_file(self):
        with temp_home():
            rc, out = run_cli("serve", "logs", "-n", "5")
            self.assertEqual(rc, 0)
            self.assertIn("暂无日志", out)

    def test_serve_start_status_stop_through_the_cli(self):
        with temp_home():
            port = free_port()
            rc, out = run_cli("serve", "start", "--port", str(port),
                              "--host", "127.0.0.1")
            self.assertEqual(rc, 0, out)
            self.assertIn("后台启动", out)
            try:
                rc, out = run_cli("serve", "status", "--port", str(port))
                self.assertEqual(rc, 0, out)
                self.assertIn("运行中", out)

                rc, out = run_cli("serve", "logs", "-n", "5")
                self.assertEqual(rc, 0)

                rc, out = run_cli("serve", "restart")
                self.assertEqual(rc, 0, out)
                self.assertIn("已重启", out)
            finally:
                rc, out = run_cli("serve", "stop")
            self.assertEqual(rc, 0, out)

    def test_serve_rejects_unknown_subaction(self):
        from golive.cli import main
        # argparse `choices` should reject it before we ever get to dispatch
        with self.assertRaises(SystemExit):
            main(["serve", "frobnicate"])


class TestServePathsUnderGoliveHome(unittest.TestCase):
    def test_pidfile_and_log_live_in_golive_home(self):
        from golive.core import service
        with temp_home() as home:
            self.assertEqual(service.pidfile_path(), home / "golive.pid")
            self.assertEqual(service.log_path(),
                             home / "logs" / "serve.log")


if __name__ == "__main__":
    unittest.main()
