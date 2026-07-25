"""M3 editor tests: registry ACL columns + auth checks + save API e2e."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP_HOME = tempfile.mkdtemp(prefix="golive_test_editor_")
os.environ["GOLIVE_HOME"] = _TMP_HOME


def _put(url, data: bytes, headers=None, method="PUT"):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "text/html; charset=utf-8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


class TestRegistryEditorColumns(unittest.TestCase):
    def test_editable_and_maintainers(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        reg = SqliteRegistry()
        site = reg.create(name="E", slug="ed-cols", owner="own@x.com")
        self.assertFalse(site["editable"])
        self.assertEqual(site["maintainers"], [])

        reg.set_editable(site["site_id"], True)
        self.assertTrue(reg.get(site["site_id"])["editable"])

        m = reg.add_maintainer(site["site_id"], "A@X.com")
        self.assertEqual(m, ["a@x.com"])           # lowercased
        reg.add_maintainer(site["site_id"], "a@x.com")  # dedup
        self.assertEqual(reg.list_maintainers(site["site_id"]), ["a@x.com"])
        reg.remove_maintainer(site["site_id"], "a@x.com")
        self.assertEqual(reg.list_maintainers(site["site_id"]), [])
        reg.delete(site["site_id"])

    def test_migration_from_v02_schema(self):
        """A v0.2 DB (no editable/maintainers) upgrades transparently."""
        import sqlite3

        from golive.backends.registry.sqlite_store import SqliteRegistry
        db = Path(_TMP_HOME) / "old_schema.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE sites (
                site_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                slug TEXT UNIQUE, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '');
            INSERT INTO sites VALUES ('abc123', 'Legacy', 'legacy',
                '2026-01-01', '2026-01-01', '', '');
        """)
        conn.commit()
        conn.close()
        reg = SqliteRegistry(db_path=db)
        site = reg.get("abc123")
        self.assertFalse(site["editable"])
        self.assertEqual(site["maintainers"], [])
        reg.set_editable("abc123", True)
        self.assertTrue(reg.get("abc123")["editable"])


class TestEditorAuth(unittest.TestCase):
    def setUp(self):
        from golive.config import Config, set_config
        self.cfg = Config()
        self.cfg.editor.token = "tok-123"
        set_config(self.cfg)

    def tearDown(self):
        from golive.config import reset_config
        reset_config()
        os.environ.pop("GOLIVE_EDITOR_TOKEN", None)

    def _site(self, **kw):
        base = {"site_id": "s1", "slug": "s1", "editable": True,
                "owner": "own@x.com", "maintainers": ["m@x.com"]}
        base.update(kw)
        return base

    def test_not_editable_rejected(self):
        from golive.server.editor_api import check_editor_auth
        ok, code, msg, _ = check_editor_auth(
            {"Authorization": "Bearer tok-123", "X-Editor-User": "own@x.com"},
            self._site(editable=False), cfg=self.cfg)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("not enabled", msg)

    def test_no_token_configured_rejects_all(self):
        from golive.config import Config
        from golive.server.editor_api import check_editor_auth
        cfg = Config()  # no editor.token, no auth.token
        ok, code, msg, _ = check_editor_auth(
            {"Authorization": "Bearer anything"}, self._site(), cfg=cfg)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("disabled", msg)

    def test_bad_token_401(self):
        from golive.server.editor_api import check_editor_auth
        ok, code, _, _ = check_editor_auth(
            {"Authorization": "Bearer WRONG", "X-Editor-User": "own@x.com"},
            self._site(), cfg=self.cfg)
        self.assertFalse(ok)
        self.assertEqual(code, 401)

    def test_wrong_user_403(self):
        from golive.server.editor_api import check_editor_auth
        ok, code, msg, ident = check_editor_auth(
            {"Authorization": "Bearer tok-123",
             "X-Editor-User": "evil@x.com"},
            self._site(), cfg=self.cfg)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertEqual(ident, "evil@x.com")

    def test_owner_and_maintainer_pass(self):
        from golive.server.editor_api import check_editor_auth
        for who in ("own@x.com", "OWN@X.com", "m@x.com"):
            ok, code, _, ident = check_editor_auth(
                {"Authorization": "Bearer tok-123", "X-Editor-User": who},
                self._site(), cfg=self.cfg)
            self.assertTrue(ok, f"{who} should pass")
            self.assertEqual(ident, who.lower())

    def test_missing_identity_when_acl_set(self):
        from golive.server.editor_api import check_editor_auth
        ok, code, msg, _ = check_editor_auth(
            {"Authorization": "Bearer tok-123"}, self._site(), cfg=self.cfg)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("X-Editor-User", msg)

    def test_zero_config_shared_token_mode(self):
        from golive.server.editor_api import check_editor_auth
        ok, _, _, _ = check_editor_auth(
            {"Authorization": "Bearer tok-123"},
            self._site(owner="", maintainers=[]), cfg=self.cfg)
        self.assertTrue(ok)

    def test_oidc_session_wins_over_header(self):
        from golive.server.editor_api import check_editor_auth
        # session says m@x.com; forged header says owner — session identity used
        ok, _, _, ident = check_editor_auth(
            {"X-Editor-User": "own@x.com"}, self._site(), cfg=self.cfg,
            session_user={"email": "m@x.com"})
        self.assertTrue(ok)
        self.assertEqual(ident, "m@x.com")

    def test_editor_token_falls_back_to_golive_token(self):
        from golive.config import Config
        from golive.server.editor_api import resolve_editor_token
        cfg = Config()
        cfg.auth.token = "serve-tok"
        self.assertEqual(resolve_editor_token(cfg), "serve-tok")
        cfg.editor.token = "editor-tok"
        self.assertEqual(resolve_editor_token(cfg), "editor-tok")


class TestEditorSaveE2E(unittest.TestCase):
    """Full HTTP round-trip through the built-in server."""

    @classmethod
    def setUpClass(cls):
        os.environ["GOLIVE_EDITOR_TOKEN"] = "e2e-token"
        from golive.config import reset_config
        reset_config()
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server.app import make_server
        cls.registry = SqliteRegistry()
        cls.storage = LocalStorage()
        cls.site = cls.registry.create(name="E2E", slug="e2e-edit",
                                       owner="own@x.com")
        cls.registry.set_editable(cls.site["site_id"], True)
        cls.storage.publish("<html><body><h1>v1</h1></body></html>",
                            cls.site["site_id"], backup_previous=False)
        cls.locked = cls.registry.create(name="Locked", slug="locked-site")
        cls.storage.publish("<h1>locked</h1>", cls.locked["site_id"],
                            backup_previous=False)
        cls.srv = make_server(host="127.0.0.1", port=0)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.pop("GOLIVE_EDITOR_TOKEN", None)
        from golive.config import reset_config
        reset_config()

    def test_save_roundtrip_with_snapshot(self):
        new_html = "<html><body><h1>v2 edited</h1></body></html>"
        status, body = _put(
            f"{self.base}/api/sites/e2e-edit/content", new_html.encode(),
            headers={"Authorization": "Bearer e2e-token",
                     "X-Editor-User": "own@x.com"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["success"])
        self.assertTrue(body["snapshot_id"])
        stored = self.storage.read(self.site["site_id"])
        self.assertIn("v2 edited", stored)
        # editor layer re-injected so the page stays editable after reload
        self.assertIn("golive-inline-editor", stored)
        # previous version snapshotted
        snaps = self.storage.list_snapshots(self.site["site_id"])
        self.assertGreaterEqual(len(snaps), 1)

    def test_not_editable_site_rejected(self):
        status, body = _put(
            f"{self.base}/api/sites/locked-site/content", b"<h1>x</h1>",
            headers={"Authorization": "Bearer e2e-token"})
        self.assertEqual(status, 403)
        self.assertIn("not enabled", body["error"])

    def test_wrong_user_rejected(self):
        status, _ = _put(
            f"{self.base}/api/sites/e2e-edit/content", b"<h1>x</h1>",
            headers={"Authorization": "Bearer e2e-token",
                     "X-Editor-User": "stranger@x.com"})
        self.assertEqual(status, 403)

    def test_bad_token_rejected(self):
        status, _ = _put(
            f"{self.base}/api/sites/e2e-edit/content", b"<h1>x</h1>",
            headers={"Authorization": "Bearer WRONG",
                     "X-Editor-User": "own@x.com"})
        self.assertEqual(status, 401)

    def test_malicious_html_blocked_by_scanner(self):
        # strong credential hit must be blocked — edit channel is no bypass
        evil = ('<html><body><script>'
                'var api_key = "AKIAIOSFODNN7EXAMPLE";'
                '</script></body></html>')
        status, body = _put(
            f"{self.base}/api/sites/e2e-edit/content", evil.encode(),
            headers={"Authorization": "Bearer e2e-token",
                     "X-Editor-User": "own@x.com"})
        self.assertEqual(status, 422)
        # content unchanged
        self.assertNotIn("AKIA", self.storage.read(self.site["site_id"]))

    def test_wrong_content_type_415(self):
        req = urllib.request.Request(
            f"{self.base}/api/sites/e2e-edit/content",
            data=b"{}", method="PUT")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer e2e-token")
        req.add_header("X-Editor-User", "own@x.com")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 415)

    def test_upload_without_uploader_501(self):
        status, body = _put(
            f"{self.base}/api/sites/e2e-edit/upload", b"\x89PNG fake",
            headers={"Authorization": "Bearer e2e-token",
                     "X-Editor-User": "own@x.com",
                     "X-Filename": "x.png"},
            method="POST")
        self.assertEqual(status, 501)


class TestEditorInject(unittest.TestCase):
    def test_inject_idempotent_and_escaped(self):
        from golive.inject import editor
        html = "<html><body><p>hi</p></body></html>"
        out = editor.inject_into_html(html, slug="demo", site_name="D")
        self.assertIn("golive-inline-editor", out)
        out2 = editor.inject_into_html(out, slug="demo2")
        self.assertEqual(out2.count("golive-inline-editor"), 1)

        evil = editor.inject_into_html(html, slug='</script><script>alert(1)')
        self.assertNotIn("</script><script>alert(1)", evil)

    def test_cli_maintainer_commands(self):
        from golive.cli import main
        from golive.backends.registry.sqlite_store import SqliteRegistry
        reg = SqliteRegistry()
        site = reg.create(name="CLI", slug="cli-maint", owner="o@x.com")
        self.assertEqual(main(["maintainer", "add", "cli-maint", "m1@x.com"]), 0)
        self.assertEqual(main(["maintainer", "list", "cli-maint"]), 0)
        self.assertEqual(reg.list_maintainers(site["site_id"]), ["m1@x.com"])
        self.assertEqual(main(["maintainer", "remove", "cli-maint", "m1@x.com"]), 0)
        self.assertEqual(reg.list_maintainers(site["site_id"]), [])
        self.assertEqual(main(["maintainer", "add", "cli-maint", "notanemail"]), 1)


if __name__ == "__main__":
    unittest.main()
