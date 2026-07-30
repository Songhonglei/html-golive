"""Tests for the default SQLite data backend (v0.7.0).

Covers: table auto-creation, CRUD, list paging, list_models, search,
upsert semantics, interface parity with the PostgREST TemplateStore, the
factory wiring, and the PostgREST-shaped /api/data adapter used by pages.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    for k in ("GOLIVE_SUPABASE_URL", "GOLIVE_SUPABASE_ANON_KEY",
              "GOLIVE_SUPABASE_SERVICE_KEY"):
        os.environ.pop(k, None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


def _write_yaml(text: str):
    home = os.environ["GOLIVE_HOME"]
    with open(os.path.join(home, "golive.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    from golive.config import reset_config
    reset_config()


class SqliteStoreBase(unittest.TestCase):
    def setUp(self):
        _fresh_home()
        from golive.backends.data.sqlite_store import TemplateStore
        self.store = TemplateStore()


class TestSchemaBootstrap(SqliteStoreBase):
    def test_db_file_and_table_created_on_first_use(self):
        import sqlite3
        self.assertTrue(os.path.exists(self.store.db_path),
                        "data.db should be created on first access")
        with sqlite3.connect(self.store.db_path) as c:
            names = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("golive_templates", names)

    def test_db_lives_in_golive_home(self):
        self.assertTrue(
            self.store.db_path.startswith(os.environ["GOLIVE_HOME"]),
            f"{self.store.db_path} should sit inside GOLIVE_HOME")
        self.assertTrue(self.store.db_path.endswith("data.db"))

    def test_reopen_is_idempotent(self):
        from golive.backends.data.sqlite_store import TemplateStore
        self.store.create("m", "a", content={"x": 1})
        second = TemplateStore()
        self.assertEqual(second.count("m"), 1)

    def test_custom_table_name_from_config(self):
        _write_yaml("data:\n  supabase:\n    templates_table: my_rows\n")
        from golive.backends.data.sqlite_store import TemplateStore
        store = TemplateStore()
        self.assertEqual(store.table, "my_rows")
        store.create("m", "a")
        self.assertEqual(store.count("m"), 1)

    def test_invalid_table_name_rejected(self):
        from golive.backends.data.sqlite_store import TemplateStore
        with self.assertRaises(ValueError):
            TemplateStore(table="bad; DROP TABLE x")

    def test_sqlite_path_override(self):
        target = os.path.join(tempfile.mkdtemp(), "custom.db")
        _write_yaml(f"data:\n  sqlite:\n    path: {target}\n")
        from golive.backends.data.sqlite_store import TemplateStore
        store = TemplateStore()
        self.assertEqual(store.db_path, target)
        self.assertTrue(os.path.exists(target))


class TestCrud(SqliteStoreBase):
    def test_create_returns_full_row(self):
        row = self.store.create("kb", "note-1", content={"body": "hi"},
                                description="d", version="2.0.0",
                                user_id="alice")
        self.assertTrue(row["id"])
        self.assertEqual(row["model_code"], "kb")
        self.assertEqual(row["name"], "note-1")
        self.assertEqual(row["description"], "d")
        self.assertEqual(row["version"], "2.0.0")
        self.assertEqual(row["user_id"], "alice")
        self.assertEqual(row["content"], {"body": "hi"})
        self.assertEqual(row["sort_index"], 0)
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])

    def test_get_roundtrip_and_missing(self):
        row = self.store.create("kb", "n", content={"a": [1, 2]})
        got = self.store.get(row["id"])
        self.assertEqual(got["content"], {"a": [1, 2]})
        self.assertIsNone(self.store.get("no-such-id"))

    def test_content_string_is_parsed(self):
        row = self.store.create("kb", "n", content='{"k": "v"}')
        self.assertEqual(row["content"], {"k": "v"})

    def test_content_non_json_string_wrapped(self):
        row = self.store.create("kb", "n", content="plain text")
        self.assertEqual(row["content"], {"raw": "plain text"})

    def test_content_none_becomes_empty_object(self):
        row = self.store.create("kb", "n")
        self.assertEqual(row["content"], {})

    def test_update_patch_semantics(self):
        row = self.store.create("kb", "n", content={"a": 1}, description="d0")
        out = self.store.update(row["id"], {"name": "renamed"})
        self.assertEqual(out["name"], "renamed")
        self.assertEqual(out["description"], "d0", "untouched field kept")
        self.assertEqual(out["content"], {"a": 1})

    def test_update_desc_alias_and_content(self):
        row = self.store.create("kb", "n")
        out = self.store.update(row["id"], {"desc": "new", "content": {"z": 9}})
        self.assertEqual(out["description"], "new")
        self.assertEqual(out["content"], {"z": 9})

    def test_update_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.store.update("nope", {"name": "x"})

    def test_delete(self):
        row = self.store.create("kb", "n")
        self.assertTrue(self.store.delete(row["id"]))
        self.assertFalse(self.store.delete(row["id"]))
        self.assertIsNone(self.store.get(row["id"]))

    def test_upsert_creates_then_updates(self):
        a = self.store.upsert("kb", "same", content={"v": 1})
        b = self.store.upsert("kb", "same", content={"v": 2})
        self.assertEqual(a["id"], b["id"], "upsert must reuse the row")
        self.assertEqual(b["content"], {"v": 2})
        self.assertEqual(self.store.count("kb"), 1)

    def test_upsert_isolates_by_user(self):
        self.store.upsert("kb", "same", content={"v": 1}, user_id="alice")
        self.store.upsert("kb", "same", content={"v": 1}, user_id="bob")
        self.assertEqual(self.store.count("kb"), 2)

    def test_unicode_and_quotes_roundtrip(self):
        payload = {"中文": "值 with 'quotes' and \"double\"", "emoji": "🚀"}
        row = self.store.create("kb", "名称 '测试'", content=payload)
        got = self.store.get(row["id"])
        self.assertEqual(got["content"], payload)
        self.assertEqual(got["name"], "名称 '测试'")


class TestListAndSearch(SqliteStoreBase):
    def seed(self, model="kb", n=5):
        for i in range(n):
            self.store.create(model, f"row-{i}",
                              content={"i": i, "tag": "even" if i % 2 == 0
                                       else "odd"},
                              description=f"desc {i}")

    def test_list_envelope_and_total(self):
        self.seed(n=5)
        out = self.store.list("kb")
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["list"]), 5)
        self.assertIn("content", out["list"][0])

    def test_list_paging(self):
        self.seed(n=5)
        p1 = self.store.list("kb", page_no=1, page_size=2)
        p2 = self.store.list("kb", page_no=2, page_size=2)
        p3 = self.store.list("kb", page_no=3, page_size=2)
        self.assertEqual((p1["total"], p2["total"], p3["total"]), (5, 5, 5))
        self.assertEqual([len(p["list"]) for p in (p1, p2, p3)], [2, 2, 1])
        ids = {r["id"] for r in p1["list"]} | {r["id"] for r in p2["list"]}
        self.assertEqual(len(ids), 4, "pages must not overlap")

    def test_list_filters_by_model(self):
        self.seed("kb", 3)
        self.seed("other", 2)
        self.assertEqual(self.store.list("kb")["total"], 3)
        self.assertEqual(self.store.list("other")["total"], 2)

    def test_list_name_prefix(self):
        self.store.create("kb", "alpha-1")
        self.store.create("kb", "alpha-2")
        self.store.create("kb", "beta-1")
        out = self.store.list("kb", name_prefix="alpha")
        self.assertEqual(out["total"], 2)

    def test_list_user_scope(self):
        self.store.create("kb", "a", user_id="alice")
        self.store.create("kb", "b", user_id="bob")
        self.assertEqual(self.store.list("kb", user_id="alice")["total"], 1)
        self.assertEqual(self.store.list("kb")["total"], 2)

    def test_count(self):
        self.seed(n=4)
        self.assertEqual(self.store.count("kb"), 4)
        self.assertEqual(self.store.count("missing"), 0)

    def test_list_models(self):
        self.seed("kb", 3)
        self.seed("zeta", 1)
        models = self.store.list_models()
        self.assertEqual(models, [{"model_code": "kb", "count": 3},
                                  {"model_code": "zeta", "count": 1}])

    def test_list_models_empty(self):
        self.assertEqual(self.store.list_models(), [])

    def test_search_without_q_delegates_to_list(self):
        self.seed(n=3)
        self.assertEqual(self.store.search("kb")["total"], 3)

    def test_search_matches_name_desc_and_content(self):
        self.store.create("kb", "findme", content={"body": "nothing"})
        self.store.create("kb", "other", description="findme in desc")
        self.store.create("kb", "third", content={"body": "findme inside"})
        self.store.create("kb", "nope", content={"body": "unrelated"})
        self.assertEqual(self.store.search("kb", q="findme")["total"], 3)

    def test_search_is_case_insensitive(self):
        self.store.create("kb", "MixedCase")
        self.assertEqual(self.store.search("kb", q="mixedcase")["total"], 1)

    def test_search_pages_hits(self):
        for i in range(5):
            self.store.create("kb", f"hit-{i}", content={"k": "needle"})
        out = self.store.search("kb", q="needle", page_no=2, page_size=2)
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["list"]), 2)


class TestInterfaceParity(unittest.TestCase):
    """The sqlite store must be a drop-in twin of the PostgREST one."""

    def _public(self, cls):
        return {n for n, _ in inspect.getmembers(cls, inspect.isfunction)
                if not n.startswith("_")}

    def test_method_sets_match(self):
        from golive.backends.data.sqlite_store import (
            TemplateStore as SqliteStore)
        from golive.backends.data.supabase import TemplateStore as PgStore
        pg = self._public(PgStore)
        sq = self._public(SqliteStore)
        self.assertTrue(pg.issubset(sq),
                        f"sqlite store missing: {sorted(pg - sq)}")

    def test_shared_method_signatures_match(self):
        from golive.backends.data.sqlite_store import (
            TemplateStore as SqliteStore)
        from golive.backends.data.supabase import TemplateStore as PgStore
        for name in self._public(PgStore):
            pg_sig = inspect.signature(getattr(PgStore, name))
            sq_sig = inspect.signature(getattr(SqliteStore, name))
            self.assertEqual(str(pg_sig), str(sq_sig),
                             f"signature drift on {name}()")

    def test_module_exports_match(self):
        from golive.backends.data import sqlite_store, supabase
        self.assertEqual(sqlite_store.DEFAULT_TABLE, supabase.DEFAULT_TABLE)
        self.assertTrue(hasattr(sqlite_store, "CREATE_TABLE_SQL"))


class TestFactoryWiring(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def test_default_backend_is_sqlite_store(self):
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.backends.factory import get_template_store
        self.assertIsInstance(get_template_store(), TemplateStore)

    def test_none_backend_returns_none(self):
        _write_yaml("data:\n  backend: none\n")
        from golive.backends.factory import get_template_store
        self.assertIsNone(get_template_store())

    def test_unknown_backend_raises(self):
        _write_yaml("data:\n  backend: mystery\n")
        from golive.backends.factory import get_template_store
        with self.assertRaises(ValueError):
            get_template_store()


class TestInjectionMode(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def test_sqlite_mode_injects_local_endpoint_without_key(self):
        from golive.config import get_config
        from golive.inject import template_api
        js = template_api.generate_js_from_config("kb", cfg=get_config())
        self.assertIn('mode       : "sqlite"', js)
        self.assertIn('baseUrl    : "/api/data"', js)
        # the runtime block guard must exempt sqlite mode (no API key there)
        self.assertIn("(CFG.mode !== 'sqlite' && !CFG.apiKey)", js)
        # ...and the request headers must not send an empty apikey
        self.assertIn("if (CFG.mode !== 'sqlite') {", js)

    def test_api_base_override(self):
        _write_yaml("data:\n  api_base: https://pages.example.com/api/data\n")
        from golive.config import get_config
        from golive.inject import template_api
        js = template_api.generate_js_from_config("kb", cfg=get_config())
        self.assertIn('"https://pages.example.com/api/data"', js)

    def test_none_backend_still_stubs(self):
        _write_yaml("data:\n  backend: none\n")
        from golive.config import get_config
        from golive.inject import template_api
        js = template_api.generate_js_from_config("kb", cfg=get_config())
        # empty baseUrl -> the runtime guard blocks every method
        self.assertIn('baseUrl    : ""', js)
        self.assertIn('mode       : "supabase"', js)
        self.assertIn("_blocked: true", js)


class TestLocalDataApi(unittest.TestCase):
    """PostgREST-shaped /api/data adapter (what published pages call)."""

    def setUp(self):
        _fresh_home()
        from golive.backends.data.sqlite_store import TemplateStore
        self.store = TemplateStore()

    def call(self, method, query=None, body=None, headers=None,
             path="/api/data/golive_templates"):
        from golive.server import data_api
        raw = json.dumps(body).encode() if body is not None else b""
        return data_api.handle(method, path, query or {}, raw, headers or {})

    def test_select_returns_rows(self):
        self.store.create("kb", "a", content={"v": 1})
        status, rows, _ = self.call("GET", {"model_code": ["eq.kb"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], {"v": 1})

    def test_select_count_header(self):
        for i in range(3):
            self.store.create("kb", f"r{i}")
        status, rows, headers = self.call(
            "GET", {"model_code": ["eq.kb"], "limit": ["2"]},
            headers={"Prefer": "count=exact"})
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 2)
        self.assertTrue(headers["Content-Range"].endswith("/3"))

    def test_like_filter(self):
        self.store.create("kb", "alpha-1")
        self.store.create("kb", "beta-1")
        _, rows, _ = self.call("GET", {"model_code": ["eq.kb"],
                                       "name": ["like.alpha*"]})
        self.assertEqual(len(rows), 1)

    def test_insert_with_representation(self):
        status, rows, _ = self.call(
            "POST", body={"model_code": "kb", "name": "n",
                          "content": {"x": 1}},
            headers={"Prefer": "return=representation"})
        self.assertEqual(status, 201)
        self.assertEqual(rows[0]["content"], {"x": 1})
        self.assertEqual(self.store.count("kb"), 1)

    def test_patch_by_id(self):
        row = self.store.create("kb", "n")
        status, rows, _ = self.call(
            "PATCH", {"id": [f"eq.{row['id']}"]}, body={"name": "renamed"},
            headers={"Prefer": "return=representation"})
        self.assertEqual(status, 200)
        self.assertEqual(rows[0]["name"], "renamed")

    def test_patch_requires_filter(self):
        status, payload, _ = self.call("PATCH", {}, body={"name": "x"})
        self.assertEqual(status, 400)
        self.assertIn("filter", payload["message"])

    def test_delete_by_id(self):
        row = self.store.create("kb", "n")
        status, payload, _ = self.call("DELETE", {"id": [f"eq.{row['id']}"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted"], 1)
        self.assertIsNone(self.store.get(row["id"]))

    def test_delete_requires_filter(self):
        status, _, _ = self.call("DELETE", {})
        self.assertEqual(status, 400)

    def test_unknown_table_404(self):
        status, _, _ = self.call("GET", path="/api/data/secrets")
        self.assertEqual(status, 404)

    def test_non_filterable_column_rejected(self):
        status, payload, _ = self.call("GET", {"content": ["eq.x"]})
        self.assertEqual(status, 400)
        self.assertIn("filterable", payload["message"])

    def test_unsupported_operator_rejected(self):
        status, payload, _ = self.call("GET", {"name": ["gt.x"]})
        self.assertEqual(status, 400)
        self.assertIn("operator", payload["message"])

    def test_disabled_when_backend_is_supabase(self):
        _write_yaml("data:\n  backend: supabase\n")
        status, _, _ = self.call("GET", {"model_code": ["eq.kb"]})
        self.assertEqual(status, 404)

    def test_order_whitelist_ignores_unknown_column(self):
        self.store.create("kb", "a")
        status, rows, _ = self.call("GET", {"model_code": ["eq.kb"],
                                            "order": ["content.desc"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)


class TestAdminApiOnSqlite(unittest.TestCase):
    """The M6 admin data endpoints must work on the default backend."""

    def setUp(self):
        _fresh_home()
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        from golive.server import authz
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.root = authz.Identity(email="root@example.com",
                                   is_superadmin=True)

    def call(self, method, path, body=None, query=None):
        from golive.server import admin_api
        raw = json.dumps(body).encode() if body is not None else b""
        return admin_api.handle(method, path, query or {}, raw, self.root,
                                self.registry, self.storage)

    def test_create_list_update_delete_cycle(self):
        status, out = self.call("POST", "/api/admin/data/rows",
                                {"model": "kb", "name": "n",
                                 "data": {"v": 1}})
        self.assertEqual(status, 200, out)
        row_id = out["row"]["id"]

        status, out = self.call("GET", "/api/admin/data/models")
        self.assertEqual(out["models"], [{"model_code": "kb", "count": 1}])

        status, out = self.call("GET", "/api/admin/data/rows",
                                query={"model": ["kb"]})
        self.assertEqual(out["total"], 1)

        status, out = self.call("PATCH", f"/api/admin/data/rows/{row_id}",
                                {"name": "renamed"})
        self.assertEqual(out["row"]["name"], "renamed")

        status, out = self.call("DELETE", f"/api/admin/data/rows/{row_id}")
        self.assertEqual(status, 200)
        self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()
