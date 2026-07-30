"""Tests for the permission-management API (v0.7.0).

Covers the dual-source superadmin model (builtin config ∪ API-managed),
the /api/admin/permissions endpoints, bulk grant/revoke, audit records
and the authorisation gate.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    for k in ("GOLIVE_TOKEN", "GOLIVE_ADMINS"):
        os.environ.pop(k, None)
    import golive.core.paths as p
    p._resolved_home = None
    import golive.backends.registry.admin_store as astore
    astore._cached = None
    astore._cached_path = ""
    from golive.config import reset_config
    reset_config()


def _write_yaml(text: str):
    home = os.environ["GOLIVE_HOME"]
    with open(os.path.join(home, "golive.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    from golive.config import reset_config
    reset_config()


class PermBase(unittest.TestCase):
    def setUp(self):
        _fresh_home()
        _write_yaml("admin:\n  admins:\n    - root@example.com\n")
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server import authz
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.root = authz.Identity(email="root@example.com",
                                   is_superadmin=True)
        self.user = authz.Identity(email="user@example.com")

    def call(self, method, path, identity=None, body=None, query=None):
        from golive.server import admin_api
        raw = json.dumps(body).encode() if body is not None else b""
        return admin_api.handle(method, path, query or {}, raw,
                                identity if identity is not None else self.root,
                                self.registry, self.storage)

    def audit_actions(self):
        from golive.core.audit import read_entries
        return [e["action"] for e in read_entries(size=200)["entries"]]


class TestManagedAdminStore(PermBase):
    def test_table_created_on_first_use(self):
        from golive.backends.registry.admin_store import get_managed_admins
        store = get_managed_admins()
        self.assertEqual(store.list(), [])

    def test_add_is_idempotent(self):
        from golive.backends.registry.admin_store import get_managed_admins
        store = get_managed_admins()
        self.assertTrue(store.add("a@example.com", added_by="root@example.com"))
        self.assertFalse(store.add("a@example.com"))
        self.assertEqual(store.emails(), ["a@example.com"])

    def test_email_is_normalised(self):
        from golive.backends.registry.admin_store import get_managed_admins
        store = get_managed_admins()
        store.add("  MiXeD@Example.COM ")
        self.assertEqual(store.emails(), ["mixed@example.com"])
        self.assertTrue(store.has("MIXED@EXAMPLE.COM"))

    def test_remove(self):
        from golive.backends.registry.admin_store import get_managed_admins
        store = get_managed_admins()
        store.add("a@example.com")
        self.assertTrue(store.remove("a@example.com"))
        self.assertFalse(store.remove("a@example.com"))

    def test_rows_carry_provenance(self):
        from golive.backends.registry.admin_store import get_managed_admins
        store = get_managed_admins()
        store.add("a@example.com", added_by="root@example.com")
        row = store.list()[0]
        self.assertEqual(row["added_by"], "root@example.com")
        self.assertTrue(row["added_at"])


class TestDualSourceResolution(PermBase):
    def test_effective_set_is_union(self):
        from golive.backends.registry.admin_store import get_managed_admins
        from golive.server import authz
        get_managed_admins().add("extra@example.com")
        self.assertEqual(authz.get_builtin_admin_emails(),
                         ["root@example.com"])
        self.assertEqual(authz.get_managed_admin_emails(),
                         ["extra@example.com"])
        self.assertEqual(authz.get_admin_emails(),
                         ["extra@example.com", "root@example.com"])

    def test_managed_admin_resolves_as_superadmin(self):
        from golive.backends.registry.admin_store import get_managed_admins
        from golive.server import authz
        get_managed_admins().add("extra@example.com")
        ident = authz.resolve_identity({"email": "extra@example.com"}, False)
        self.assertTrue(ident.is_superadmin)
        self.assertFalse(ident.is_builtin_admin)

    def test_builtin_admin_flagged_builtin(self):
        from golive.server import authz
        ident = authz.resolve_identity({"email": "root@example.com"}, False)
        self.assertTrue(ident.is_superadmin)
        self.assertTrue(ident.is_builtin_admin)

    def test_env_admins_win_over_yaml(self):
        from golive.server import authz
        os.environ["GOLIVE_ADMINS"] = "envboss@example.com"
        try:
            self.assertEqual(authz.get_builtin_admin_emails(),
                             ["envboss@example.com"])
            self.assertTrue(authz.is_builtin_admin("envboss@example.com"))
            self.assertFalse(authz.is_builtin_admin("root@example.com"))
        finally:
            os.environ.pop("GOLIVE_ADMINS", None)

    def test_token_identity_counts_as_builtin(self):
        from golive.server import authz
        ident = authz.resolve_identity(None, True)
        self.assertTrue(ident.is_superadmin)
        self.assertTrue(ident.is_builtin_admin)

    def test_plain_user_is_not_superadmin(self):
        from golive.server import authz
        ident = authz.resolve_identity({"email": "nobody@example.com"}, False)
        self.assertFalse(ident.is_superadmin)
        self.assertFalse(ident.is_builtin_admin)


class TestMeEndpoint(PermBase):
    def test_me_exposes_builtin_flag(self):
        status, out = self.call("GET", "/api/admin/me")
        self.assertEqual(status, 200)
        self.assertTrue(out["builtin"])
        self.assertTrue(out["identity"]["builtin"])
        self.assertEqual(out["role"], "superadmin")

    def test_me_builtin_false_for_managed_admin(self):
        from golive.backends.registry.admin_store import get_managed_admins
        from golive.server import authz
        get_managed_admins().add("extra@example.com")
        ident = authz.resolve_identity({"email": "extra@example.com"}, False)
        status, out = self.call("GET", "/api/admin/me", ident)
        self.assertEqual(status, 200)
        self.assertTrue(out["identity"]["superadmin"])
        self.assertFalse(out["builtin"])

    def test_me_builtin_false_for_regular_user(self):
        status, out = self.call("GET", "/api/admin/me", self.user)
        self.assertEqual(out["role"], "user")
        self.assertFalse(out["builtin"])


class TestPermissionsOverview(PermBase):
    def test_shape_with_no_sites(self):
        status, out = self.call("GET", "/api/admin/permissions")
        self.assertEqual(status, 200)
        self.assertEqual(out["builtin_admins"], ["root@example.com"])
        self.assertEqual(out["managed_admins"], [])
        self.assertEqual(out["sites_acl"], [])
        self.assertEqual(out["totals"]["sites"], 0)

    def test_sites_acl_summarises_owner_and_maintainers(self):
        site = self.registry.create(name="Alpha", slug="alpha",
                                    owner="owner@example.com")
        self.registry.add_maintainer(site["site_id"], "m1@example.com")
        self.registry.add_maintainer(site["site_id"], "m2@example.com")
        _, out = self.call("GET", "/api/admin/permissions")
        row = out["sites_acl"][0]
        self.assertEqual(row["slug"], "alpha")
        self.assertEqual(row["name"], "Alpha")
        self.assertEqual(row["owner"], "owner@example.com")
        self.assertEqual(row["maintainers"],
                         ["m1@example.com", "m2@example.com"])
        self.assertEqual(out["totals"]["maintainers"], 2)

    def test_effective_admins_merges_sources(self):
        self.call("POST", "/api/admin/permissions/admins",
                  body={"email": "extra@example.com"})
        _, out = self.call("GET", "/api/admin/permissions")
        self.assertEqual(out["effective_admins"],
                         ["extra@example.com", "root@example.com"])
        self.assertEqual(out["managed_admins"][0]["email"],
                         "extra@example.com")

    def test_non_superadmin_403(self):
        status, out = self.call("GET", "/api/admin/permissions", self.user)
        self.assertEqual(status, 403)
        self.assertIn("superadmin", out["error"])


class TestManagedAdminEndpoints(PermBase):
    def test_add_then_visible_and_audited(self):
        status, out = self.call("POST", "/api/admin/permissions/admins",
                                body={"email": "New@Example.com"})
        self.assertEqual(status, 200)
        self.assertTrue(out["created"])
        self.assertEqual(out["email"], "new@example.com")
        self.assertIn("perm.admin.add", self.audit_actions())
        from golive.server import authz
        self.assertIn("new@example.com", authz.get_admin_emails())

    def test_add_twice_is_idempotent(self):
        self.call("POST", "/api/admin/permissions/admins",
                  body={"email": "dup@example.com"})
        status, out = self.call("POST", "/api/admin/permissions/admins",
                                body={"email": "dup@example.com"})
        self.assertEqual(status, 200)
        self.assertFalse(out["created"])
        self.assertEqual(len(out["managed_admins"]), 1)

    def test_add_builtin_is_noop_not_error(self):
        status, out = self.call("POST", "/api/admin/permissions/admins",
                                body={"email": "root@example.com"})
        self.assertEqual(status, 200)
        self.assertTrue(out["builtin"])
        self.assertFalse(out["created"])

    def test_add_rejects_bad_email(self):
        for bad in ("", "notanemail", "a@b", None):
            status, out = self.call("POST", "/api/admin/permissions/admins",
                                    body={"email": bad})
            self.assertEqual(status, 400, bad)
            self.assertIn("email", out["error"])

    def test_remove_managed(self):
        self.call("POST", "/api/admin/permissions/admins",
                  body={"email": "gone@example.com"})
        status, out = self.call("DELETE", "/api/admin/permissions/admins",
                                body={"email": "gone@example.com"})
        self.assertEqual(status, 200)
        self.assertTrue(out["removed"])
        self.assertEqual(out["managed_admins"], [])
        self.assertIn("perm.admin.remove", self.audit_actions())

    def test_remove_builtin_rejected_400(self):
        status, out = self.call("DELETE", "/api/admin/permissions/admins",
                                body={"email": "root@example.com"})
        self.assertEqual(status, 400)
        self.assertIn("builtin", out["error"])
        self.assertIn("golive.yaml", out["error"])
        from golive.server import authz
        self.assertIn("root@example.com", authz.get_admin_emails())
        self.assertNotIn("perm.admin.remove", self.audit_actions())

    def test_remove_unknown_404(self):
        status, out = self.call("DELETE", "/api/admin/permissions/admins",
                                body={"email": "ghost@example.com"})
        self.assertEqual(status, 404)

    def test_non_superadmin_403_on_writes(self):
        for method in ("POST", "DELETE"):
            status, _ = self.call(method, "/api/admin/permissions/admins",
                                  self.user, {"email": "x@example.com"})
            self.assertEqual(status, 403)

    def test_bad_json_400(self):
        from golive.server import admin_api
        status, out = admin_api.handle(
            "POST", "/api/admin/permissions/admins", {}, b"not json",
            self.root, self.registry, self.storage)
        self.assertEqual(status, 400)


class TestBulkGrants(PermBase):
    def setUp(self):
        super().setUp()
        self.sites = [
            self.registry.create(name=f"S{i}", slug=f"s{i}",
                                 owner="owner@example.com")
            for i in range(3)
        ]

    def bulk(self, **kw):
        payload = {"email": "m@example.com", "role": "maintainer",
                   "action": "grant", "slugs": ["s0", "s1"]}
        payload.update(kw)
        return self.call("POST", "/api/admin/permissions/bulk", body=payload)

    def test_grant_maintainer_across_sites(self):
        status, out = self.bulk()
        self.assertEqual(status, 200)
        self.assertEqual(out["applied"], ["s0", "s1"])
        self.assertEqual(out["failed"], [])
        for slug in ("s0", "s1"):
            site = self.registry.get_by_slug(slug)
            self.assertIn("m@example.com", site["maintainers"])
        self.assertNotIn("m@example.com",
                         self.registry.get_by_slug("s2")["maintainers"])
        self.assertIn("perm.bulk", self.audit_actions())

    def test_grant_is_idempotent_and_reports_skipped(self):
        self.bulk()
        status, out = self.bulk()
        self.assertEqual(out["applied"], [])
        self.assertEqual(out["skipped"], ["s0", "s1"])

    def test_revoke_maintainer(self):
        self.bulk()
        status, out = self.bulk(action="revoke")
        self.assertEqual(out["applied"], ["s0", "s1"])
        self.assertEqual(self.registry.get_by_slug("s0")["maintainers"], [])

    def test_revoke_missing_is_skipped_not_failed(self):
        status, out = self.bulk(action="revoke", slugs=["s2"])
        self.assertEqual(out["skipped"], ["s2"])
        self.assertEqual(out["failed"], [])

    def test_grant_owner_sets_owner(self):
        status, out = self.bulk(role="owner", email="new@example.com",
                                slugs=["s0"])
        self.assertEqual(out["applied"], ["s0"])
        self.assertEqual(self.registry.get_by_slug("s0")["owner"],
                         "new@example.com")

    def test_revoke_owner_rejected(self):
        status, out = self.bulk(role="owner", action="revoke")
        self.assertEqual(status, 400)
        self.assertIn("transfer", out["error"])

    def test_unknown_slug_reported_without_aborting(self):
        status, out = self.bulk(slugs=["s0", "ghost", "s1"])
        self.assertEqual(status, 200)
        self.assertEqual(out["applied"], ["s0", "s1"])
        self.assertEqual(len(out["failed"]), 1)
        self.assertEqual(out["failed"][0]["slug"], "ghost")
        self.assertIn("unknown", out["failed"][0]["error"])

    def test_site_id_accepted_as_ref(self):
        sid = self.sites[2]["site_id"]
        status, out = self.bulk(slugs=[sid])
        self.assertEqual(out["applied"], [sid])

    def test_validation_errors(self):
        cases = [
            ({"email": "bad"}, "email"),
            ({"role": "wizard"}, "role"),
            ({"action": "destroy"}, "action"),
            ({"slugs": []}, "slugs"),
            ({"slugs": "s0"}, "slugs"),
        ]
        for patch, needle in cases:
            status, out = self.bulk(**patch)
            self.assertEqual(status, 400, patch)
            self.assertIn(needle, out["error"], patch)

    def test_too_many_slugs_rejected(self):
        from golive.server.admin_api import MAX_BULK_SLUGS
        status, out = self.bulk(slugs=[f"s{i}"
                                       for i in range(MAX_BULK_SLUGS + 1)])
        self.assertEqual(status, 400)
        self.assertIn("too many", out["error"])

    def test_non_superadmin_403(self):
        status, _ = self.call("POST", "/api/admin/permissions/bulk",
                              self.user,
                              {"email": "m@example.com", "slugs": ["s0"]})
        self.assertEqual(status, 403)

    def test_audit_detail_records_outcome(self):
        self.bulk(slugs=["s0", "ghost"])
        from golive.core.audit import read_entries
        entry = [e for e in read_entries(size=50)["entries"]
                 if e["action"] == "perm.bulk"][0]
        self.assertEqual(entry["detail"]["applied"], ["s0"])
        self.assertEqual(entry["detail"]["failed"], ["ghost"])
        self.assertEqual(entry["detail"]["role"], "maintainer")


class TestRoutingEdges(PermBase):
    def test_unknown_permissions_subpath_404(self):
        status, _ = self.call("GET", "/api/admin/permissions/nope")
        self.assertEqual(status, 404)

    def test_wrong_method_404(self):
        status, _ = self.call("PATCH", "/api/admin/permissions")
        self.assertEqual(status, 404)

    def test_unauthenticated_401(self):
        from golive.server import admin_api
        status, out = admin_api.handle("GET", "/api/admin/permissions", {},
                                       b"", None, self.registry, self.storage)
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
