"""Connection diagnostics must test the chosen backend and report the actual failure."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch

import requests

from golive.config import Config, reset_config, set_config
from golive.core.paths import reset_cache
from golive.server import admin_api
from golive.server.authz import Identity
from golive.server.connection_checks import check_data_backend


class TestBackendConnectionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"GOLIVE_HOME": self.tmp.name,
                                      "GOLIVE_SUPABASE_SERVICE_KEY": "",
                                      "GOLIVE_SUPABASE_ANON_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        reset_cache()
        self.addCleanup(reset_cache)
        self.addCleanup(reset_config)
        self.cfg = Config()
        self.cfg.data.sqlite_path = str(Path(self.tmp.name) / "data.db")
        set_config(self.cfg)
        self.root = Identity(email="admin@example.com", is_superadmin=True)
        self.secret = "test-secret-must-not-be-echoed"

    def call(self, body, identity=None):
        return admin_api.handle("POST", "/api/admin/test/data-backend", {},
                                json.dumps(body).encode(), identity or self.root, None, None)

    def remote(self, **extra):
        return {"backend": "supabase", "url": "https://test-project.supabase.co",
                "service_key": self.secret, **extra}

    def test_sqlite_works_without_url_and_preserves_existing_data(self):
        with sqlite3.connect(self.cfg.data.sqlite_path) as conn:
            conn.execute("CREATE TABLE existing (value TEXT)")
            conn.execute("INSERT INTO existing VALUES ('preserve')")
        with patch("requests.get") as network:
            status, result = self.call({"backend": "sqlite"})
        network.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"], ["read", "write", "integrity"])
        self.assertEqual(result["table_count"], 1)
        with sqlite3.connect(self.cfg.data.sqlite_path) as conn:
            self.assertEqual(conn.execute("SELECT value FROM existing").fetchall(), [("preserve",)])
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("existing",)])

    def test_sqlite_fresh_database_is_usable_without_application_rows(self):
        status, result = self.call({"backend": "sqlite"})
        self.assertEqual((status, result["code"], result["table_count"]), (200, "sqlite_ok", 0))
        with sqlite3.connect(self.cfg.data.sqlite_path) as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

    def test_sqlite_memory_target_is_not_reinterpreted_as_a_file(self):
        self.cfg.data.sqlite_path = ":memory:"
        status, result = self.call({"backend": "sqlite"})
        self.assertEqual((status, result["code"], result["location"]), (200, "sqlite_ok", ":memory:"))

    def test_readonly_error_is_actionable_without_exposing_raw_exception(self):
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError(
            "attempt to write a readonly database " + self.secret
        )):
            _, result = self.call({"backend": "sqlite"})
        self.assertEqual(result["code"], "sqlite_readonly")
        self.assertNotIn(self.secret, json.dumps(result))

    def test_sqlite_missing_parent_and_corrupt_file_have_distinct_errors(self):
        self.cfg.data.sqlite_path = str(Path(self.tmp.name) / "missing" / "data.db")
        self.assertEqual(self.call({"backend": "sqlite"})[1]["code"], "sqlite_open_failed")
        self.cfg.data.sqlite_path = str(Path(self.tmp.name) / "corrupt.db")
        Path(self.cfg.data.sqlite_path).write_text("this is not a database")
        self.assertEqual(self.call({"backend": "sqlite"})[1]["code"], "sqlite_corrupt")

    def test_sqlite_lock_is_not_reported_as_missing_url(self):
        conn = sqlite3.connect(self.cfg.data.sqlite_path)
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE existing (value TEXT)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        status, result = self.call({"backend": "sqlite"})
        self.assertEqual((status, result["code"]), (200, "sqlite_locked"))

    def test_none_is_skipped_and_unknown_backend_is_rejected(self):
        with patch("requests.get") as network:
            status, result = self.call({"backend": "none"})
            self.assertEqual((status, result["status"], result["ok"]), (200, "skipped", None))
            self.assertEqual(self.call({"backend": "unknown"})[1]["code"], "backend_unsupported")
        network.assert_not_called()

    def test_supabase_missing_configuration_never_attempts_remote_request(self):
        with patch("requests.get") as network:
            status, result = self.call({"backend": "supabase"})
        self.assertEqual(status, 400)
        self.assertEqual(result["code"], "supabase_config_required")
        self.assertEqual(result["fields"], ["url", "key"])
        network.assert_not_called()

    def test_invalid_urls_and_keys_never_leak_or_attempt_network(self):
        cases = [
            (self.remote(url="not-a-url"), "supabase_url_invalid"),
            (self.remote(url="https://YOUR-PROJECT.supabase.co"), "supabase_url_placeholder"),
            (self.remote(url="https://user:password@test-project.supabase.co"), "supabase_url_invalid"),
            (self.remote(url="https://test-project.supabase.co/rest/v1"), "supabase_url_invalid"),
            (self.remote(service_key="invalid\nkey"), "supabase_key_invalid"),
        ]
        for body, code in cases:
            with self.subTest(code=code), patch("requests.get") as network:
                status, result = self.call(body)
                self.assertEqual((status, result["code"]), (400, code))
                self.assertNotIn(self.secret, json.dumps(result))
                network.assert_not_called()

    def test_http_statuses_are_reported_without_echoing_response_bodies(self):
        cases = {401: "supabase_unauthorized", 403: "supabase_forbidden", 404: "supabase_not_found",
                 429: "supabase_rate_limited", 503: "supabase_unavailable", 302: "supabase_redirect"}
        for status, code in cases.items():
            with self.subTest(status=status), patch("requests.get", return_value=Mock(status_code=status, text=self.secret)) as network:
                _, result = self.call(self.remote())
                self.assertEqual(result["code"], code)
                self.assertEqual(result["http_status"], status)
                self.assertNotIn(self.secret, json.dumps(result))
                self.assertFalse(network.call_args.kwargs["allow_redirects"])

    def test_timeout_tls_and_network_errors_are_distinct_and_redacted(self):
        cases = [(requests.Timeout(self.secret), "supabase_timeout"),
                 (requests.exceptions.SSLError(self.secret), "supabase_tls_error"),
                 (requests.ConnectionError(self.secret), "supabase_network_error")]
        for exception, code in cases:
            with self.subTest(code=code), patch("requests.get", side_effect=exception):
                _, result = self.call(self.remote())
                self.assertEqual(result["code"], code)
                self.assertNotIn(self.secret, json.dumps(result))

    def test_http_200_must_contain_a_schema_document(self):
        for document in ({}, [], {"login": True}):
            with self.subTest(document=document), patch("requests.get", return_value=Mock(status_code=200, json=lambda: document)):
                self.assertEqual(self.call(self.remote())[1]["code"], "supabase_invalid_response")

    def test_success_reports_numeric_count_and_supports_new_and_legacy_keys(self):
        document = {"swagger": "2.0", "definitions": {"notes": {}, "reports": {}}}
        for key in (self.secret, "eyJtest.payload.signature"):
            with self.subTest(key=key), patch("requests.get", return_value=Mock(status_code=200, json=lambda: document)) as network:
                _, result = self.call(self.remote(service_key=key))
                self.assertTrue(result["ok"])
                self.assertEqual(result["table_count"], 2)
                self.assertEqual(result["tables"], ["notes", "reports"])
                headers = network.call_args.kwargs["headers"]
                self.assertEqual(headers["apikey"], key)
                self.assertEqual("Authorization" in headers, key.startswith("eyJ"))

    def test_existing_key_is_not_forwarded_to_another_project(self):
        self.cfg.supabase.url = "https://configured.supabase.co"
        with patch.dict(os.environ, {"GOLIVE_SUPABASE_SERVICE_KEY": self.secret}), patch("requests.get") as network:
            _, result = self.call({"backend": "supabase", "url": "https://different.supabase.co"})
        self.assertEqual(result["fields"], ["key"])
        network.assert_not_called()

    def test_unexpected_diagnostic_exception_does_not_echo_secrets(self):
        with patch("requests.get", side_effect=RuntimeError(self.secret)):
            status, result = self.call(self.remote())
        self.assertEqual((status, result["code"]), (502, "backend_internal_error"))
        self.assertNotIn(self.secret, json.dumps(result))

    def test_non_admin_cannot_probe_files_or_network(self):
        user = Identity(email="viewer@example.com")
        with patch("requests.get") as network:
            self.assertEqual(self.call(self.remote(), identity=user)[0], 403)
        network.assert_not_called()
        self.assertFalse(Path(self.cfg.data.sqlite_path).exists())

    def test_real_http_probe_reads_schema_without_mutation(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, self.headers.get("apikey")))
                body = json.dumps({"swagger": "2.0", "definitions": {"notes": {}}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            _, result = check_data_backend(self.remote(url=f"http://127.0.0.1:{server.server_port}"), self.cfg)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_count"], 1)
        self.assertEqual(received, [("/rest/v1/", self.secret)])
        audit = Path(self.tmp.name) / "logs" / "audit.log"
        if audit.exists():
            self.assertNotIn(self.secret, audit.read_text())
