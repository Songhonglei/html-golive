"""Tests for the M5 admin API (golive/server/admin_api.py + authz).

Most cases call the transport-free ``admin_api.handle()`` directly;
a small HTTP section exercises identity resolution through the real
server (token => superadmin, configured-token-but-no-header => 401).
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    os.environ.pop("GOLIVE_TOKEN", None)
    os.environ.pop("GOLIVE_ADMINS", None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


def _q(**kw):
    """helper: query dict in parse_qs shape."""
    return {k: [str(v)] for k, v in kw.items()}


class AdminApiBase(unittest.TestCase):
    def setUp(self):
        _fresh_home()
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server import authz
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.authz = authz

        self.alice = authz.Identity(email="alice@example.com")   # owner
        self.bob = authz.Identity(email="bob@example.com")       # maintainer
        self.eve = authz.Identity(email="eve@example.com")       # outsider
        self.root = authz.Identity(email="root@example.com",
                                   is_superadmin=True)

        self.site = self.registry.create("Demo", "demo",
                                         owner="alice@example.com")
        self.registry.add_maintainer(self.site["site_id"], "bob@example.com")
        self.storage.publish("<html><title>v1</title></html>",
                             self.site["site_id"], backup_previous=False)
        self.other = self.registry.create("Other", "other",
                                          owner="eve@example.com")
        self.storage.publish("<html><title>o</title></html>",
                             self.other["site_id"], backup_previous=False)

    def call(self, method, path, identity, body=None, query=None):
        from golive.server import admin_api
        raw = json.dumps(body).encode() if body is not None else b""
        return admin_api.handle(method, path, query or {}, raw,
                                identity, self.registry, self.storage)


class TestAuthzRoles(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def test_env_admins_parsed(self):
        from golive.server import authz
        os.environ["GOLIVE_ADMINS"] = "Ops@Example.com , two@example.com"
        try:
            self.assertEqual(authz.get_admin_emails(),
                             ["ops@example.com", "two@example.com"])
        finally:
            os.environ.pop("GOLIVE_ADMINS", None)

    def test_yaml_admins(self):
        from golive.config import load_config
        cfg_dir = tempfile.mkdtemp()
        cfg_path = os.path.join(cfg_dir, "golive.yaml")
        with open(cfg_path, "w") as f:
            f.write("admin:\n  admins: [Boss@Example.com]\n")
        cfg = load_config(cfg_path)
        self.assertEqual(cfg.admin.admins, ["boss@example.com"])
        from golive.server import authz
        self.assertEqual(authz.get_admin_emails(cfg), ["boss@example.com"])

    def test_resolve_identity(self):
        from golive.server import authz
        self.assertIsNone(authz.resolve_identity(None, False))
        tok = authz.resolve_identity(None, True)
        self.assertTrue(tok.is_superadmin)          # token => superadmin
        os.environ["GOLIVE_ADMINS"] = "sa@example.com"
        try:
            sa = authz.resolve_identity({"email": "SA@example.com"}, False)
            self.assertTrue(sa.is_superadmin)
            nobody = authz.resolve_identity({"email": "x@example.com"}, False)
            self.assertFalse(nobody.is_superadmin)
        finally:
            os.environ.pop("GOLIVE_ADMINS", None)

    def test_site_role_matrix(self):
        from golive.server import authz
        site = {"owner": "a@x.com", "maintainers": ["m@x.com"]}
        self.assertEqual(authz.site_role(authz.Identity("a@x.com"), site), "owner")
        self.assertEqual(authz.site_role(authz.Identity("m@x.com"), site), "maintainer")
        self.assertEqual(authz.site_role(authz.Identity("z@x.com"), site), "")
        self.assertEqual(
            authz.site_role(authz.Identity("z@x.com", is_superadmin=True), site),
            "superadmin")
        self.assertEqual(authz.site_role(None, site), "")


class TestMeAndList(AdminApiBase):
    def test_unauthenticated_401(self):
        status, body = self.call("GET", "/api/admin/me", None)
        self.assertEqual(status, 401)

    def test_me_roles(self):
        status, body = self.call("GET", "/api/admin/me", self.alice)
        self.assertEqual(status, 200)
        self.assertIn("demo", body["owned"])
        status, body = self.call("GET", "/api/admin/me", self.bob)
        self.assertIn("demo", body["maintained"])

    def test_superadmin_sees_all(self):
        status, body = self.call("GET", "/api/admin/sites", self.root)
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)

    def test_user_sees_only_own_sites(self):
        status, body = self.call("GET", "/api/admin/sites", self.alice)
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["sites"][0]["slug"], "demo")
        # maintainer also sees the site
        status, body = self.call("GET", "/api/admin/sites", self.bob)
        self.assertEqual(body["total"], 1)
        # outsider only sees their own
        status, body = self.call("GET", "/api/admin/sites", self.eve)
        self.assertEqual([s["slug"] for s in body["sites"]], ["other"])

    def test_search_and_pagination(self):
        status, body = self.call("GET", "/api/admin/sites", self.root,
                                 query=_q(q="dem"))
        self.assertEqual(body["total"], 1)
        status, body = self.call("GET", "/api/admin/sites", self.root,
                                 query=_q(page=2, size=1))
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["sites"]), 1)

    def test_bad_pagination_400(self):
        status, _ = self.call("GET", "/api/admin/sites", self.root,
                              query=_q(page="x"))
        self.assertEqual(status, 400)


class TestDetailAndPatch(AdminApiBase):
    def test_detail_includes_snapshots(self):
        # create a snapshot by re-publishing
        self.storage.publish("<html><title>v2</title></html>",
                             self.site["site_id"])
        status, body = self.call("GET", "/api/admin/sites/demo", self.alice)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["snapshots"]), 1)
        self.assertEqual(body["role"], "owner")

    def test_detail_outsider_403(self):
        status, _ = self.call("GET", "/api/admin/sites/demo", self.eve)
        self.assertEqual(status, 403)

    def test_patch_owner_ok(self):
        status, body = self.call("PATCH", "/api/admin/sites/demo", self.alice,
                                 body={"name": "New", "editable": True})
        self.assertEqual(status, 200)
        site = self.registry.get_by_slug("demo")
        self.assertEqual(site["name"], "New")
        self.assertTrue(site["editable"])

    def test_patch_maintainer_403(self):
        status, _ = self.call("PATCH", "/api/admin/sites/demo", self.bob,
                              body={"name": "Nope"})
        self.assertEqual(status, 403)

    def test_patch_unknown_field_400(self):
        status, _ = self.call("PATCH", "/api/admin/sites/demo", self.alice,
                              body={"slug": "hack"})
        self.assertEqual(status, 400)

    def test_patch_bad_json_400(self):
        from golive.server import admin_api
        status, _ = admin_api.handle("PATCH", "/api/admin/sites/demo", {},
                                     b"not json", self.alice,
                                     self.registry, self.storage)
        self.assertEqual(status, 400)


class TestDeleteTransferMaintainers(AdminApiBase):
    def test_delete_requires_confirm(self):
        status, _ = self.call("DELETE", "/api/admin/sites/demo", self.alice,
                              body={})
        self.assertEqual(status, 400)
        status, _ = self.call("DELETE", "/api/admin/sites/demo", self.alice,
                              body={"confirm": "wrong"})
        self.assertEqual(status, 400)
        self.assertIsNotNone(self.registry.get_by_slug("demo"))

    def test_delete_maintainer_403(self):
        status, _ = self.call("DELETE", "/api/admin/sites/demo", self.bob,
                              body={"confirm": "demo"})
        self.assertEqual(status, 403)

    def test_delete_owner_ok_removes_storage_and_registry(self):
        sid = self.site["site_id"]
        status, body = self.call("DELETE", "/api/admin/sites/demo",
                                 self.alice, body={"confirm": "demo"})
        self.assertEqual(status, 200)
        self.assertIsNone(self.registry.get_by_slug("demo"))
        self.assertFalse(self.storage.exists(sid))

    def test_transfer_maintainer_403(self):
        status, _ = self.call("POST", "/api/admin/sites/demo/transfer",
                              self.bob, body={"to": "bob@example.com"})
        self.assertEqual(status, 403)

    def test_transfer_owner_then_old_owner_loses_rights(self):
        status, body = self.call("POST", "/api/admin/sites/demo/transfer",
                                 self.alice, body={"to": "carol@example.com"})
        self.assertEqual(status, 200)
        self.assertEqual(body["owner"], "carol@example.com")
        # old owner can no longer PATCH / transfer / delete
        status, _ = self.call("PATCH", "/api/admin/sites/demo", self.alice,
                              body={"name": "X"})
        self.assertEqual(status, 403)
        status, _ = self.call("DELETE", "/api/admin/sites/demo", self.alice,
                              body={"confirm": "demo"})
        self.assertEqual(status, 403)
        # new owner can
        carol = self.authz.Identity(email="carol@example.com")
        status, _ = self.call("PATCH", "/api/admin/sites/demo", carol,
                              body={"name": "Carol's"})
        self.assertEqual(status, 200)

    def test_transfer_invalid_email_400(self):
        status, _ = self.call("POST", "/api/admin/sites/demo/transfer",
                              self.alice, body={"to": "not-an-email"})
        self.assertEqual(status, 400)

    def test_maintainer_add_remove(self):
        status, body = self.call("POST", "/api/admin/sites/demo/maintainers",
                                 self.alice, body={"email": "new@example.com"})
        self.assertEqual(status, 200)
        self.assertIn("new@example.com", body["maintainers"])
        status, body = self.call("DELETE", "/api/admin/sites/demo/maintainers",
                                 self.alice, body={"email": "new@example.com"})
        self.assertEqual(status, 200)
        self.assertNotIn("new@example.com", body["maintainers"])

    def test_maintainer_manage_by_maintainer_403(self):
        status, _ = self.call("POST", "/api/admin/sites/demo/maintainers",
                              self.bob, body={"email": "x@example.com"})
        self.assertEqual(status, 403)

    def test_unknown_site_404(self):
        status, _ = self.call("GET", "/api/admin/sites/nope", self.root)
        self.assertEqual(status, 404)


class TestRollback(AdminApiBase):
    def _snapshot(self):
        self.storage.publish("<html><title>v2</title></html>",
                             self.site["site_id"])
        return self.storage.list_snapshots(self.site["site_id"])[0]["ts"]

    def test_rollback_maintainer_ok(self):
        ts = self._snapshot()
        status, body = self.call("POST", "/api/admin/sites/demo/rollback",
                                 self.bob, body={"snapshot": ts})
        self.assertEqual(status, 200)
        self.assertIn("v1", self.storage.read(self.site["site_id"]))

    def test_rollback_outsider_403(self):
        ts = self._snapshot()
        status, _ = self.call("POST", "/api/admin/sites/demo/rollback",
                              self.eve, body={"snapshot": ts})
        self.assertEqual(status, 403)

    def test_rollback_missing_snapshot_404(self):
        self._snapshot()
        status, _ = self.call("POST", "/api/admin/sites/demo/rollback",
                              self.alice, body={"snapshot": "19700101_000000_0"})
        self.assertEqual(status, 404)


class TestStatsAndAudit(AdminApiBase):
    def test_stats_requires_superadmin(self):
        status, _ = self.call("GET", "/api/admin/stats", self.alice)
        self.assertEqual(status, 403)
        status, body = self.call("GET", "/api/admin/stats", self.root)
        self.assertEqual(status, 200)
        self.assertEqual(body["total_sites"], 2)
        self.assertGreater(body["total_bytes"], 0)
        self.assertLessEqual(len(body["top_sites"]), 10)

    def test_audit_requires_superadmin_and_records_writes(self):
        # generate audit entries
        self.call("PATCH", "/api/admin/sites/demo", self.alice,
                  body={"name": "A2"})
        self.call("POST", "/api/admin/sites/demo/maintainers", self.alice,
                  body={"email": "x@example.com"})
        status, _ = self.call("GET", "/api/admin/audit", self.alice)
        self.assertEqual(status, 403)
        status, body = self.call("GET", "/api/admin/audit", self.root)
        self.assertEqual(status, 200)
        actions = [e["action"] for e in body["entries"]]
        self.assertIn("site.update", actions)
        self.assertIn("maintainer.add", actions)
        # newest first
        self.assertEqual(actions[0], "maintainer.add")
        # who recorded
        whos = {e["who"] for e in body["entries"]}
        self.assertIn("alice@example.com", whos)

    def test_audit_filters(self):
        self.call("PATCH", "/api/admin/sites/demo", self.alice,
                  body={"name": "A2"})
        self.call("PATCH", "/api/admin/sites/other", self.eve,
                  body={"name": "O2"})
        status, body = self.call("GET", "/api/admin/audit", self.root,
                                 query=_q(slug="demo"))
        self.assertEqual(body["total"], 1)
        status, body = self.call("GET", "/api/admin/audit", self.root,
                                 query=_q(action="site.update"))
        self.assertEqual(body["total"], 2)


class TestAuditModule(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def test_record_and_read_roundtrip(self):
        from golive.core import audit
        audit.record("a@x.com", "site.update", "demo", {"k": "v"})
        audit.record("b@x.com", "site.delete", "demo2")
        out = audit.read_entries()
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["entries"][0]["action"], "site.delete")
        self.assertEqual(out["entries"][1]["detail"], {"k": "v"})

    def test_malformed_lines_skipped(self):
        from golive.core import audit
        audit.record("a@x.com", "x", "s")
        with open(audit.audit_file(), "a") as f:
            f.write("NOT JSON\n\n")
        self.assertEqual(audit.read_entries()["total"], 1)

    def test_empty_who_becomes_token(self):
        from golive.core import audit
        audit.record("", "x", "s")
        self.assertEqual(audit.read_entries()["entries"][0]["who"], "(token)")


class TestHttpIdentity(unittest.TestCase):
    """HTTP-level identity resolution through the real server."""

    def setUp(self):
        _fresh_home()

    def _start(self):
        from golive.config import reset_config
        reset_config()
        from golive.server.app import make_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = make_server(port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.25)
        self.addCleanup(srv.shutdown)
        return port

    def _get(self, port, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     headers=headers or {})
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_zero_config_loopback_is_superadmin(self):
        port = self._start()
        status, body = self._get(port, "/api/admin/me")
        self.assertEqual(status, 200)
        self.assertTrue(body["identity"]["superadmin"])

    def test_token_configured_no_header_401(self):
        os.environ["GOLIVE_TOKEN"] = "m5-secret"
        try:
            port = self._start()
            status, _ = self._get(port, "/api/admin/me")
            self.assertEqual(status, 401)
            status, body = self._get(
                port, "/api/admin/me",
                {"Authorization": "Bearer m5-secret"})
            self.assertEqual(status, 200)
            self.assertTrue(body["identity"]["superadmin"])
        finally:
            os.environ.pop("GOLIVE_TOKEN", None)

    def test_registry_owner_column_migration(self):
        """A pre-owner database gets the column added transparently."""
        import sqlite3
        from golive.core.paths import get_registry_db
        db = str(get_registry_db())
        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE sites (site_id TEXT PRIMARY KEY, "
            "name TEXT NOT NULL DEFAULT '', slug TEXT UNIQUE, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "notes TEXT NOT NULL DEFAULT '');")
        conn.execute("INSERT INTO sites VALUES ('old1','Old','old-site',"
                     "'2026-01-01T00:00:00','2026-01-01T00:00:00','')")
        conn.commit()
        conn.close()
        from golive.backends.registry.sqlite_store import SqliteRegistry
        reg = SqliteRegistry(db)
        site = reg.get("old1")
        self.assertEqual(site["owner"], "")        # NULL/absent -> '' default
        self.assertEqual(site["maintainers"], [])


if __name__ == "__main__":
    unittest.main()
