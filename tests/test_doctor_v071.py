"""v0.7.1 — `golive doctor` as the single verification entry point.

Covers:
  * no service running → doctor reports "not running", never errors
  * CLI/service version match and mismatch rendering
  * --json is parseable and carries the three backend layers
  * degradation when /health omits `version` (a 0.7.x server)
  * existing checks (GOLIVE_HOME, registry, deps) are still present
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP_HOME = tempfile.mkdtemp(prefix="golive_doctor080_")
os.environ["GOLIVE_HOME"] = _TMP_HOME


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_health_server(payload, port=0):
    """A tiny HTTP server answering /health with ``payload`` (dict or None)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/health" and payload is not None:
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *a):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, srv.server_address[1]


@contextmanager
def health_server(payload):
    srv, port = _make_health_server(payload)
    try:
        yield port
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def captured():
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


def run_doctor(*argv):
    """Run `golive doctor ...`, returning (exit_code, stdout)."""
    from golive.cli import main
    with captured() as buf:
        rc = main(["doctor", *argv])
    return rc, buf.getvalue()


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── tests ───────────────────────────────────────────────────────────────────

class TestDoctorServiceNotRunning(unittest.TestCase):
    def test_no_service_is_not_an_error(self):
        rc, out = run_doctor("--port", str(free_port()))
        self.assertEqual(rc, 0, out)
        self.assertIn("not running", out)
        self.assertIn("golive serve start", out)

    def test_json_when_not_running(self):
        rc, out = run_doctor("--port", str(free_port()), "--json")
        self.assertEqual(rc, 0, out)
        rep = json.loads(out)
        self.assertFalse(rep["service"]["running"])
        self.assertEqual(rep["service"]["port_owner"], "free")


class TestDoctorVersionComparison(unittest.TestCase):
    def test_matching_version_is_clean(self):
        from golive import __version__
        payload = {"status": "ok", "version": __version__,
                   "home": _TMP_HOME, "data_backend": "sqlite", "pid": 4242}
        with health_server(payload) as port:
            rc, out = run_doctor("--port", str(port))
        self.assertEqual(rc, 0, out)
        self.assertIn("running service", out)
        self.assertIn(__version__, out)
        self.assertIn("pid 4242", out)
        self.assertNotIn("Version mismatch", out)

    def test_version_mismatch_tells_you_to_restart(self):
        payload = {"status": "ok", "version": "0.0.1-old",
                   "home": _TMP_HOME, "data_backend": "sqlite", "pid": 4243}
        with health_server(payload) as port:
            rc, out = run_doctor("--port", str(port))
        self.assertIn("Version mismatch", out)
        self.assertIn("golive serve restart", out)
        self.assertIn("0.0.1-old", out)
        # a stale service is a warning, not a hard failure
        self.assertEqual(rc, 0, out)

    def test_health_without_version_degrades_gracefully(self):
        with health_server({"status": "ok"}) as port:
            rc, out = run_doctor("--port", str(port))
        self.assertEqual(rc, 0, out)
        self.assertIn("running service", out)
        self.assertNotIn("Traceback", out)

    def test_json_reports_version_mismatch(self):
        payload = {"status": "ok", "version": "0.0.1-old", "pid": 7,
                   "home": _TMP_HOME, "data_backend": "sqlite"}
        with health_server(payload) as port:
            rc, out = run_doctor("--port", str(port), "--json")
        rep = json.loads(out)
        self.assertTrue(rep["service"]["running"])
        self.assertFalse(rep["service"]["version_match"])
        self.assertEqual(rep["service"]["version"], "0.0.1-old")
        self.assertEqual(rep["service"]["pid"], 7)


class TestDoctorPortOwnedByOtherProgram(unittest.TestCase):
    def test_foreign_listener_is_called_out(self):
        # a server that 404s /health is not golive
        with health_server(None) as port:
            rc, out = run_doctor("--port", str(port))
        self.assertIn("not running", out)
        self.assertIn("held by another", out)
        self.assertEqual(rc, 0, out)


class TestDoctorBackendLayers(unittest.TestCase):
    def test_three_layers_present_in_text(self):
        from golive.core.paths import get_home
        rc, out = run_doctor("--port", str(free_port()))
        for label in ("storage", "registry", "data backend"):
            self.assertIn(label, out)
        self.assertIn("GOLIVE_HOME", out)
        # whichever home is active in this process, doctor must print it
        self.assertIn(str(get_home()), out)
        self.assertIn("admin portal", out)
        self.assertIn("/admin", out)

    def test_three_layers_present_in_json(self):
        rc, out = run_doctor("--port", str(free_port()), "--json")
        rep = json.loads(out)
        for key in ("storage", "registry", "data"):
            self.assertIn(key, rep)
            self.assertIn("backend", rep[key])
            self.assertIn("location", rep[key])
        self.assertEqual(rep["storage"]["backend"], "local")
        self.assertEqual(rep["registry"]["backend"], "sqlite")
        self.assertEqual(rep["data"]["backend"], "sqlite")
        self.assertIn("cli_version", rep)
        self.assertIn("admin_url", rep)
        self.assertIn("skill", rep)
        self.assertIn("deps", rep)
        self.assertIn("problems", rep)

    def test_registry_counts_published_sites(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        reg = SqliteRegistry()
        before = len(reg.list_all())
        site = reg.create(name="doctor-count", slug="doctor-count")
        LocalStorage().publish("<h1>x</h1>", site["site_id"],
                               backup_previous=False)
        try:
            rc, out = run_doctor("--port", str(free_port()), "--json")
            rep = json.loads(out)
            self.assertEqual(rep["registry"]["sites"], before + 1)
            self.assertEqual(rep["storage"]["sites"], before + 1)
            self.assertEqual(rep["registry"]["missing_content"], [])
        finally:
            reg.delete(site["site_id"])

    def test_data_layer_counts_rows(self):
        from golive.backends.data.sqlite_store import TemplateStore
        store = TemplateStore()
        row = store.create("doctor_model", "doctor-row", content={"a": 1})
        try:
            rc, out = run_doctor("--port", str(free_port()), "--json")
            rep = json.loads(out)
            self.assertGreaterEqual(rep["data"]["tables"], 1)
            self.assertGreaterEqual(rep["data"]["rows"], 1)
            self.assertTrue(rep["data"]["location"].endswith(".db"))
        finally:
            store.delete(row["id"])


class TestDoctorKeepsOldChecks(unittest.TestCase):
    def test_dependency_check_survives(self):
        rc, out = run_doctor("--port", str(free_port()), "--json")
        rep = json.loads(out)
        mods = {d["module"] for d in rep["deps"]}
        self.assertEqual(mods, {"bs4", "requests", "yaml", "PIL"})
        for dep in rep["deps"]:
            self.assertIn("required", dep)
            self.assertIn("available", dep)

    def test_home_source_is_reported(self):
        rc, out = run_doctor("--port", str(free_port()), "--json")
        rep = json.loads(out)
        self.assertTrue(rep["home"]["writable"])
        self.assertEqual(rep["home"]["source"], "$GOLIVE_HOME")

    def test_skill_section_never_raises(self):
        rc, out = run_doctor("--port", str(free_port()), "--json")
        rep = json.loads(out)
        self.assertIn("installs", rep["skill"])
        self.assertIsInstance(rep["skill"]["installs"], list)


class TestDoctorHelpers(unittest.TestCase):
    def test_display_width_counts_wide_glyphs(self):
        from golive.cli import _disp_width, _pad
        self.assertEqual(_disp_width("abc"), 3)
        # CJK characters have double width
        self.assertEqual(_disp_width("未安装"), 6)
        self.assertEqual(_disp_width(_pad("未安装", 10)), 10)

    def test_fmt_bytes(self):
        from golive.cli import _fmt_bytes
        self.assertEqual(_fmt_bytes(85), "85 B")
        self.assertTrue(_fmt_bytes(2048).endswith("KB"))
        self.assertTrue(_fmt_bytes(5 * 1024 * 1024).endswith("MB"))


if __name__ == "__main__":
    unittest.main()
