"""Backend tests against the in-process fake PostgREST server.

Covers:
  * PostgrestClient URL / header / params construction (via request log)
  * SupabaseRegistry CRUD round-trip
  * TemplateStore CRUD + upsert round-trip
"""

import unittest

from golive.backends.data.supabase import TemplateStore
from golive.backends.postgrest import PostgrestClient, PostgrestError
from golive.backends.registry.supabase_store import SupabaseRegistry
from tests.fake_postgrest import FakePostgrest


class FakeBackendBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakePostgrest()
        cls.url = cls.fake.start()
        cls.client = PostgrestClient(cls.url, "test-key")

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.tables.clear()
        self.fake.requests.clear()


class TestPostgrestClient(FakeBackendBase):
    def test_headers_and_url(self):
        self.client.select("golive_sites", {"limit": "1"})
        method, table, params, _ = self.fake.requests[-1]
        self.assertEqual((method, table), ("GET", "golive_sites"))
        self.assertEqual(params.get("limit"), "1")

    def test_missing_key_rejected(self):
        bad = PostgrestClient(self.url, "x")
        bad.key = ""  # simulate missing key at request time

        # our fake replies 401 when apikey header is empty
        with self.assertRaises(PostgrestError):
            bad.select("golive_sites")

    def test_count_header(self):
        self.fake.table("t").extend({"id": str(i), "v": i} for i in range(5))
        rows, total = self.client.select("t", {"limit": "2"}, count=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(total, 5)

    def test_empty_url_raises(self):
        with self.assertRaises(ValueError):
            PostgrestClient("", "k")
        with self.assertRaises(ValueError):
            PostgrestClient("http://x", "")


class TestSupabaseRegistry(FakeBackendBase):
    def _registry(self):
        return SupabaseRegistry(client=self.client, table="golive_sites")

    def test_crud_roundtrip(self):
        reg = self._registry()
        site = reg.create("Demo", slug="Demo-Slug", owner="alice")
        self.assertEqual(site["slug"], "demo-slug")  # lowercased
        sid = site["site_id"]

        self.assertEqual(reg.get(sid)["name"], "Demo")
        self.assertEqual(reg.get_by_slug("demo-slug")["site_id"], sid)
        self.assertEqual(reg.resolve("demo-slug")["site_id"], sid)

        updated = reg.update(sid, name="Demo2", notes="n")
        self.assertEqual(updated["name"], "Demo2")

        self.assertTrue(reg.slug_taken("demo-slug"))
        self.assertFalse(reg.slug_taken("demo-slug", exclude_site_id=sid))
        self.assertFalse(reg.slug_taken("free-slug"))

        self.assertEqual(len(reg.list_all()), 1)
        self.assertTrue(reg.delete(sid))
        self.assertIsNone(reg.get(sid))

    def test_update_missing_raises(self):
        reg = self._registry()
        with self.assertRaises(KeyError):
            reg.update("nope", name="x")


class TestTemplateStore(FakeBackendBase):
    def _store(self):
        return TemplateStore(client=self.client, table="golive_templates")

    def test_crud_roundtrip(self):
        store = self._store()
        row = store.create("mc1", "tpl_a", content={"k": 1}, description="d")
        tid = row["id"]
        self.assertEqual(store.get(tid)["name"], "tpl_a")

        data = store.list("mc1")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["list"][0]["content"], {"k": 1})

        store.update(tid, {"content": {"k": 2}, "desc": "d2"})
        self.assertEqual(store.get(tid)["content"], {"k": 2})

        self.assertTrue(store.delete(tid))
        self.assertIsNone(store.get(tid))

    def test_upsert_create_then_update(self):
        store = self._store()
        r1 = store.upsert("mc1", "same_name", content={"v": 1})
        r2 = store.upsert("mc1", "same_name", content={"v": 2})
        self.assertEqual(r1["id"], r2["id"])
        data = store.list("mc1")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["list"][0]["content"], {"v": 2})

    def test_model_code_namespacing(self):
        store = self._store()
        store.create("mc1", "a")
        store.create("mc2", "a")
        self.assertEqual(store.list("mc1")["total"], 1)
        self.assertEqual(store.count("mc2"), 1)

    def test_content_string_parsing(self):
        store = self._store()
        row = store.create("mc1", "j", content='{"x": true}')
        self.assertEqual(row["content"], {"x": True})
        row2 = store.create("mc1", "raw", content="not-json")
        self.assertEqual(row2["content"], {"raw": "not-json"})


if __name__ == "__main__":
    unittest.main()
