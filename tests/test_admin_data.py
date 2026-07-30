"""Tests for the M6 admin data-management endpoints.

/api/admin/data/* against the in-process fake PostgREST server:
models list, paged rows (+q filter), create/update/delete, audit trail,
superadmin-only 403, no-backend 400 guidance, and escaping-safe inputs.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from tests.fake_postgrest import FakePostgrest


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    for k in ("GOLIVE_TOKEN", "GOLIVE_ADMINS",
              "GOLIVE_SUPABASE_URL", "GOLIVE_SUPABASE_ANON_KEY",
              "GOLIVE_SUPABASE_SERVICE_KEY"):
        os.environ.pop(k, None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


def _q(**kw):
    return {k: [str(v)] for k, v in kw.items()}


class DataApiBase(unittest.TestCase):
    """Fake PostgREST + supabase data backend wired via env/config."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakePostgrest()
        cls.url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()
        for k in ("GOLIVE_SUPABASE_URL", "GOLIVE_SUPABASE_ANON_KEY"):
            os.environ.pop(k, None)

    def setUp(self):
        _fresh_home()
        os.environ["GOLIVE_SUPABASE_URL"] = self.url
        os.environ["GOLIVE_SUPABASE_ANON_KEY"] = "test-key"
        home = os.environ["GOLIVE_HOME"]
        with open(os.path.join(home, "golive.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("data:\n  backend: supabase\n")
        from golive.config import reset_config
        reset_config()
        self.fake.tables.clear()
        self.fake.requests.clear()

        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server import authz
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.root = authz.Identity(email="root@example.com",
                                   is_superadmin=True)
        self.user = authz.Identity(email="user@example.com")

    def call(self, method, path, identity, body=None, query=None):
        from golive.server import admin_api
        raw = json.dumps(body).encode() if body is not None else b""
        return admin_api.handle(method, path, query or {}, raw,
                                identity, self.registry, self.storage)

    def seed(self, model="kb_main", n=3):
        for i in range(n):
            self.fake.table("golive_templates").append({
                "id": f"row-{model}-{i}",
                "model_code": model,
                "name": f"item-{i}",
                "user_id": "",
                "description": "",
                "content": {"k": f"value-{i}"},
                "version": "1.0.0",
                "sort_index": i,
                "created_at": f"2026-07-0{i + 1}T00:00:00",
                "updated_at": f"2026-07-0{i + 1}T00:00:00",
            })


class TestDataModels(DataApiBase):
    def test_models_distinct_with_counts(self):
        self.seed("kb_main", 3)
        self.seed("kb_other", 2)
        status, out = self.call("GET", "/api/admin/data/models", self.root)
        self.assertEqual(status, 200)
        models = {m["model_code"]: m["count"] for m in out["models"]}
        self.assertEqual(models, {"kb_main": 3, "kb_other": 2})

    def test_models_empty_backend(self):
        status, out = self.call("GET", "/api/admin/data/models", self.root)
        self.assertEqual(status, 200)
        self.assertEqual(out["models"], [])


class TestDataRows(DataApiBase):
    def test_paged_list(self):
        self.seed("kb_main", 5)
        status, out = self.call("GET", "/api/admin/data/rows", self.root,
                                query=_q(model="kb_main", page=1, size=2))
        self.assertEqual(status, 200)
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["rows"]), 2)
        status, out2 = self.call("GET", "/api/admin/data/rows", self.root,
                                 query=_q(model="kb_main", page=3, size=2))
        self.assertEqual(status, 200)
        self.assertEqual(len(out2["rows"]), 1)

    def test_q_filters_json_content(self):
        self.seed("kb_main", 3)
        status, out = self.call("GET", "/api/admin/data/rows", self.root,
                                query=_q(model="kb_main", q="value-1"))
        self.assertEqual(status, 200)
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["rows"][0]["name"], "item-1")

    def test_q_matches_name_case_insensitive(self):
        self.seed("kb_main", 3)
        status, out = self.call("GET", "/api/admin/data/rows", self.root,
                                query=_q(model="kb_main", q="ITEM-2"))
        self.assertEqual(status, 200)
        self.assertEqual(out["total"], 1)

    def test_missing_model_param_400(self):
        status, out = self.call("GET", "/api/admin/data/rows", self.root)
        self.assertEqual(status, 400)
        self.assertIn("model", out["error"])

    def test_bad_page_400(self):
        status, _ = self.call("GET", "/api/admin/data/rows", self.root,
                              query=_q(model="kb_main", page="x"))
        self.assertEqual(status, 400)


class TestDataWrites(DataApiBase):
    def test_create_update_delete_roundtrip(self):
        status, out = self.call("POST", "/api/admin/data/rows", self.root,
                                body={"model": "kb_main", "name": "hello",
                                      "data": {"a": 1}})
        self.assertEqual(status, 200)
        row_id = out["row"]["id"]
        self.assertEqual(out["row"]["content"], {"a": 1})

        status, out = self.call("PATCH", f"/api/admin/data/rows/{row_id}",
                                self.root,
                                body={"data": {"a": 2}, "name": "hello2"})
        self.assertEqual(status, 200)
        self.assertEqual(out["row"]["content"], {"a": 2})
        self.assertEqual(out["row"]["name"], "hello2")

        status, out = self.call("DELETE", f"/api/admin/data/rows/{row_id}",
                                self.root)
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.table("golive_templates"), [])

    def test_create_requires_model_and_object_data(self):
        status, _ = self.call("POST", "/api/admin/data/rows", self.root,
                              body={"data": {"a": 1}})
        self.assertEqual(status, 400)
        status, _ = self.call("POST", "/api/admin/data/rows", self.root,
                              body={"model": "m", "data": [1, 2]})
        self.assertEqual(status, 400)
        status, _ = self.call("POST", "/api/admin/data/rows", self.root,
                              body={"model": "m", "data": "str"})
        self.assertEqual(status, 400)

    def test_update_unknown_row_404(self):
        status, _ = self.call("PATCH", "/api/admin/data/rows/nope",
                              self.root, body={"data": {"x": 1}})
        self.assertEqual(status, 404)

    def test_delete_unknown_row_404(self):
        status, _ = self.call("DELETE", "/api/admin/data/rows/nope",
                              self.root)
        self.assertEqual(status, 404)

    def test_update_nothing_400(self):
        self.seed("kb_main", 1)
        status, _ = self.call("PATCH", "/api/admin/data/rows/row-kb_main-0",
                              self.root, body={})
        self.assertEqual(status, 400)

    def test_writes_audited(self):
        from golive.core.audit import read_entries
        _, out = self.call("POST", "/api/admin/data/rows", self.root,
                           body={"model": "kb_main", "data": {"a": 1}})
        row_id = out["row"]["id"]
        self.call("PATCH", f"/api/admin/data/rows/{row_id}", self.root,
                  body={"data": {"a": 2}})
        self.call("DELETE", f"/api/admin/data/rows/{row_id}", self.root)
        actions = [e["action"] for e in read_entries(size=10)["entries"]]
        self.assertEqual(actions[:3],
                         ["data.delete", "data.update", "data.create"])

    def test_malicious_model_name_stored_verbatim_not_executed(self):
        evil = '<script>alert(1)</script>"'
        status, out = self.call("POST", "/api/admin/data/rows", self.root,
                                body={"model": evil, "data": {"x": 1}})
        self.assertEqual(status, 200)
        # stored as data, listed as data — nothing interpolates it into HTML
        status, out = self.call("GET", "/api/admin/data/models", self.root)
        codes = [m["model_code"] for m in out["models"]]
        self.assertIn(evil, codes)


class TestDataPermissions(DataApiBase):
    def test_non_superadmin_403(self):
        for method, path in [
            ("GET", "/api/admin/data/models"),
            ("GET", "/api/admin/data/rows"),
            ("POST", "/api/admin/data/rows"),
            ("PATCH", "/api/admin/data/rows/x"),
            ("DELETE", "/api/admin/data/rows/x"),
        ]:
            status, out = self.call(method, path, self.user, body={})
            self.assertEqual(status, 403, f"{method} {path}")
            self.assertIn("superadmin", out["error"])

    def test_unauthenticated_401(self):
        from golive.server import admin_api
        status, _ = admin_api.handle("GET", "/api/admin/data/models", {},
                                     b"", None, self.registry, self.storage)
        self.assertEqual(status, 401)


class TestDataNoBackend(unittest.TestCase):
    """data.backend: none — the data layer is explicitly disabled.

    (sqlite is the default since v0.7.0, so 'no backend' now requires an
    explicit opt-out in golive.yaml.)
    """

    def setUp(self):
        _fresh_home()
        home = os.environ["GOLIVE_HOME"]
        with open(os.path.join(home, "golive.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("data:\n  backend: none\n")
        from golive.config import reset_config
        reset_config()
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server import authz
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.root = authz.Identity(email="root@example.com",
                                   is_superadmin=True)

    def test_all_endpoints_400_with_hint(self):
        from golive.server import admin_api
        for method, path in [
            ("GET", "/api/admin/data/models"),
            ("GET", "/api/admin/data/rows"),
            ("POST", "/api/admin/data/rows"),
            ("PATCH", "/api/admin/data/rows/x"),
            ("DELETE", "/api/admin/data/rows/x"),
        ]:
            status, out = admin_api.handle(
                method, path, {}, b"{}", self.root,
                self.registry, self.storage)
            self.assertEqual(status, 400, f"{method} {path}")
            self.assertEqual(out["error"], "no data backend configured")
            self.assertIn("golive.yaml", out["hint"])

    def test_permission_checked_before_backend(self):
        """403 (not 400) for non-superadmin even without a backend."""
        from golive.server import admin_api, authz
        user = authz.Identity(email="u@example.com")
        status, _ = admin_api.handle("GET", "/api/admin/data/models", {},
                                     b"", user, self.registry, self.storage)
        self.assertEqual(status, 403)


class TestStoreHelpers(unittest.TestCase):
    """Direct TemplateStore.list_models / search coverage."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakePostgrest()
        cls.url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.tables.clear()
        from golive.backends.postgrest import PostgrestClient
        from golive.backends.data.supabase import TemplateStore
        self.store = TemplateStore(
            client=PostgrestClient(self.url, "k"), table="golive_templates")

    def test_search_without_q_is_server_paged(self):
        for i in range(4):
            self.fake.table("golive_templates").append(
                {"id": str(i), "model_code": "m", "name": f"n{i}",
                 "content": {}, "sort_index": i, "created_at": str(i)})
        out = self.store.search("m", page_no=2, page_size=3)
        self.assertEqual(out["total"], 4)
        self.assertEqual(len(out["list"]), 1)

    def test_search_q_paginates_hits(self):
        for i in range(5):
            self.fake.table("golive_templates").append(
                {"id": str(i), "model_code": "m", "name": "hit",
                 "content": {"i": i}, "sort_index": i, "created_at": str(i)})
        out = self.store.search("m", q="hit", page_no=2, page_size=2)
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["list"]), 2)

    def test_list_models_ignores_empty_codes(self):
        self.fake.table("golive_templates").extend([
            {"id": "1", "model_code": "a"},
            {"id": "2", "model_code": ""},
            {"id": "3", "model_code": "a"},
        ])
        out = self.store.list_models()
        self.assertEqual(out, [{"model_code": "a", "count": 2}])


if __name__ == "__main__":
    unittest.main()
