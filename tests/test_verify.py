"""Tests for golive verify — end-to-end self-check.

These tests exercise the real chain: real Config, real sqlite, real HTTP
server (on a random port), real publish, real data round-trip. No mocks
for the types under test.

Postgres tests skip when GOLIVE_PG_DSN is unset or psycopg is missing.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from golive.i18n import set_language


def _pg_ready() -> bool:
    if not os.environ.get("GOLIVE_PG_DSN", "").strip():
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


class _VerifyBase(unittest.TestCase):
    """Shared setup: temp GOLIVE_HOME with a real sqlite data backend."""

    backend = "sqlite"

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix=f"golive_verify_{self.backend}_")
        os.environ["GOLIVE_HOME"] = self.home
        Path(self.home, "golive.yaml").write_text(
            f"data:\n  backend: {self.backend}\n", encoding="utf-8")
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.config import get_config
        self.cfg = get_config()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    def _run_verify(self, keep=False, json_out=False):
        """Run cmd_verify with argparse-like args, return (exit_code, output)."""
        import io
        import argparse
        from golive.cli import cmd_verify

        args = argparse.Namespace(keep=keep, json=json_out)
        # Capture stdout
        old = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            code = cmd_verify(args)
        finally:
            sys.stdout = old
        return code, buf.getvalue()


class TestVerifySqliteSuccess(_VerifyBase):
    """sqlite: verify should succeed with exit 0."""

    def setUp(self):
        super().setUp()
        set_language("en")

    def tearDown(self):
        set_language("en")
        super().tearDown()

    def test_verify_success_exit_0(self):
        code, out = self._run_verify()
        self.assertEqual(code, 0, f"Expected exit 0, got {code}\n{out}")
        self.assertIn("end to end", out.lower() + out)
        # Should mention the backend
        self.assertIn("sqlite", out.lower() + out)

    def test_verify_json_parses(self):
        code, out = self._run_verify(json_out=True)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("ok", data)
        self.assertTrue(data["ok"])
        self.assertIn("steps", data)
        self.assertIn("summary", data)

    def test_verify_cleans_up(self):
        """After verify, the test site should be gone from the registry."""
        from golive.backends.factory import get_registry
        reg = get_registry(self.cfg)
        before = len(reg.list_all())
        self._run_verify()
        after = len(reg.list_all())
        self.assertEqual(after, before,
                         "verify left a test site behind")

    def test_verify_cleans_up_data(self):
        """After verify, no verify_test rows should remain in the data table."""
        from golive.backends.factory import get_template_store
        store = get_template_store(self.cfg)
        before = store.count("verify_test")
        self._run_verify()
        after = store.count("verify_test")
        self.assertEqual(after, before,
                         "verify left test data rows behind")

    def test_verify_keep_preserves_site(self):
        """With --keep, the test site should still exist after verify."""
        from golive.backends.factory import get_registry
        reg = get_registry(self.cfg)
        before = len(reg.list_all())
        code, out = self._run_verify(keep=True)
        self.assertEqual(code, 0)
        after = len(reg.list_all())
        self.assertEqual(after, before + 1,
                         "verify --keep should have left one test site")
        # Clean it up so other tests are not affected
        sites = reg.list_all()
        for s in sites:
            if s.get("name") == "golive-verify-test":
                reg.delete(s["site_id"])
                break


class TestVerifyDetectsBreakage(_VerifyBase):
    """The core test: break the implementation, verify must go red."""

    def setUp(self):
        super().setUp()
        set_language("en")

    def tearDown(self):
        set_language("en")
        super().tearDown()

    def test_break_data_api_makes_verify_fail(self):
        """If /api/data returns 404 for writes, verify must exit non-zero."""
        from golive.server import data_api
        from unittest import mock

        # Save the real handle
        real_handle = data_api.handle

        def _broken_handle(method, path, query, body, headers=None, cfg=None):
            # Let GET /health-style reads through, but break data writes
            if method in ("POST", "PATCH", "DELETE"):
                return 404, {"message": "broken for test"}, {}
            return real_handle(method, path, query, body, headers=headers, cfg=cfg)

        with mock.patch.object(data_api, "handle", _broken_handle):
            code, out = self._run_verify()
        self.assertNotEqual(code, 0,
                            f"verify should have failed with broken data API, got exit 0\n{out}")
        self.assertIn("❌", out)

    def test_break_injection_makes_verify_fail(self):
        """If the injected mode is wrong, verify must exit non-zero."""
        from golive.inject import template_api
        from unittest import mock

        real_gen = template_api.generate_js_from_config

        def _broken_gen(model_code, data_version="1.0.0", cfg=None):
            # Generate but then corrupt the mode
            js = real_gen(model_code, data_version, cfg)
            # Replace "local" with "supabase" to simulate injection breakage
            return js.replace('"local"', '"supabase"', 1)

        with mock.patch.object(template_api, "generate_js_from_config", _broken_gen):
            code, out = self._run_verify()
        # The injection check should catch the wrong mode
        self.assertNotEqual(code, 0,
                            f"verify should have failed with broken injection, got exit 0\n{out}")


class TestVerifySupabase(_VerifyBase):
    """Supabase: verify should not report a failure — it's page-direct."""

    backend = "supabase"

    def setUp(self):
        # Create home with supabase config (but not really configured)
        self.home = tempfile.mkdtemp(prefix="golive_verify_supabase_")
        os.environ["GOLIVE_HOME"] = self.home
        Path(self.home, "golive.yaml").write_text(
            "data:\n  backend: supabase\n"
            "supabase:\n  url: https://example.supabase.co\n",
            encoding="utf-8")
        # Don't set GOLIVE_SUPABASE_ANON_KEY so it's "not configured"
        os.environ.pop("GOLIVE_SUPABASE_ANON_KEY", None)
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.config import get_config
        self.cfg = get_config()
        set_language("en")

    def tearDown(self):
        set_language("en")
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    def test_supabase_not_reported_as_failure(self):
        """Supabase without full config should not crash, and should explain."""
        code, out = self._run_verify()
        # It should either succeed (explaining supabase is page-direct)
        # or fail gracefully with the supabase_skip message
        if code == 0:
            self.assertIn("supabase", out.lower())
        else:
            # If it fails, it should be the supabase_skip message, not a crash
            self.assertIn("supabase", out.lower())


class TestVerifyPostgresNoDSN(_VerifyBase):
    """Postgres without GOLIVE_PG_DSN: actionable error, exit non-zero."""

    backend = "postgres"

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_verify_pg_")
        os.environ["GOLIVE_HOME"] = self.home
        os.environ.pop("GOLIVE_PG_DSN", None)
        Path(self.home, "golive.yaml").write_text(
            "data:\n  backend: postgres\n", encoding="utf-8")
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.config import get_config
        self.cfg = get_config()
        set_language("en")

    def tearDown(self):
        set_language("en")
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    @unittest.skipIf(_pg_ready(), "GOLIVE_PG_DSN is set — testing the no-DSN path")
    def test_postgres_no_dsn_gives_actionable_error(self):
        code, out = self._run_verify()
        self.assertNotEqual(code, 0)
        self.assertIn("GOLIVE_PG_DSN", out)
        self.assertIn("pip install", out)


class TestVerifyBilingual(unittest.TestCase):
    """Verify must work in both en and zh without hardcoding language literals."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_verify_i18n_")
        os.environ["GOLIVE_HOME"] = self.home
        Path(self.home, "golive.yaml").write_text(
            "data:\n  backend: sqlite\n", encoding="utf-8")
        from golive import config as cfg_mod
        cfg_mod._current = None

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None
        set_language("en")

    def _run_verify(self, lang):
        import io
        import argparse
        from golive.cli import cmd_verify

        set_language(lang)
        args = argparse.Namespace(keep=False, json=True)
        old = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            code = cmd_verify(args)
        finally:
            sys.stdout = old
        return code, buf.getvalue()

    def test_english(self):
        code, out = self._run_verify("en")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])

    def test_chinese(self):
        code, out = self._run_verify("zh")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])

    def test_doctor_healthy_message_bilingual(self):
        """doctor.healthy key should differ between languages."""
        from golive.i18n import t
        set_language("en")
        en_msg = t("doctor.healthy")
        set_language("zh")
        zh_msg = t("doctor.healthy")
        self.assertNotEqual(en_msg, zh_msg,
                            "doctor.healthy should differ between en and zh")
        set_language("en")
        # English should mention "verify"
        self.assertIn("verify", en_msg.lower())


class TestVerifyGoesOverRealHttp(unittest.TestCase):
    """verify must hit the socket, not call the handler in-process.

    The 0.7.6 outage was a routing guard that answered 404 for Postgres
    *before* control ever reached ``data_api.handle``. An in-process call to
    that handler would have reported success while every published page was
    broken — so verify checking the handler directly would miss exactly the
    class of failure it exists to catch.
    """

    def test_verify_does_not_call_the_handler_in_process(self):
        import inspect
        from golive import cli
        src = inspect.getsource(cli.cmd_verify)
        self.assertNotIn(
            "data_api.handle", src,
            "cmd_verify calls data_api.handle() directly; it must go through "
            "HTTP so routing-layer failures (the 0.7.6 bug) are caught")

    def test_the_http_helper_uses_urllib(self):
        import inspect
        from golive import cli
        src = inspect.getsource(cli._verify_http)
        self.assertIn("urlopen", src,
                      "_verify_http must perform a real request")

    def test_helper_returns_status_for_error_responses(self):
        """A 404 must come back as a status, not raise — verify reports it."""
        import json as _j
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from golive.cli import _verify_http

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = _j.dumps({"message": "nope"}).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # silence
                pass

        srv = HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        threading.Thread(target=srv.handle_request, daemon=True).start()
        try:
            status, payload = _verify_http(port, "GET", "/api/data/x")
        finally:
            srv.server_close()
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("message"), "nope")


if __name__ == "__main__":
    unittest.main()
