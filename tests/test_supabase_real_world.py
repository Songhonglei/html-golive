"""Regressions from verifying Supabase against a real cloud project.

The in-process fake PostgREST server covers protocol shape, but a real
project exposed several things it could not: an object endpoint that answers
`text/plain` with no charset, a registry that cannot take an explicit
site_id, and previews that reported a number they never actually measured.
Each test here fails if its fix is reverted.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from golive.backends.storage.supabase_store import (SupabaseStorage,
                                                    SupabaseStorageError)


class _Resp:
    """Minimal stand-in for requests.Response with a controllable encoding."""

    def __init__(self, body: bytes, content_type: str = "text/plain",
                 status: int = 200, encoding=None):
        self._content = body
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = encoding

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        # Mirror requests: decode with whatever self.encoding says, which for
        # a charset-less text/* response is ISO-8859-1 per RFC 2616.
        return self._content.decode(self.encoding or "utf-8", "replace")


class TestStorageDecodesUtf8(unittest.TestCase):
    """HG-080-SB-01: authenticated downloads must not go through resp.text.

    Supabase answers the object endpoint with `text/plain` and no charset.
    requests then assumes ISO-8859-1, so every non-ASCII byte of a document
    that _upload() wrote as UTF-8 came back mangled — and `golive export`
    baked the damage into the archive.
    """

    PAGE = "<html><body>golive demo — 待办清单（真数据）🎉</body></html>"

    def _storage(self):
        return SupabaseStorage(url="https://p.supabase.co", key="svc",
                               bucket="golive-sites")

    def test_download_decodes_utf8_despite_latin1_header(self):
        st = self._storage()
        resp = _Resp(self.PAGE.encode("utf-8"), "text/plain",
                     encoding="ISO-8859-1")
        with mock.patch("golive.backends.storage.supabase_store.requests.get",
                        return_value=resp):
            got = st._download("site/index.html")
        self.assertEqual(got, self.PAGE)
        self.assertIn("待办清单", got)
        self.assertNotIn("å¾", got, "content came back mojibake")

    def test_roundtrip_is_byte_exact(self):
        """What _upload sends is what _download must return."""
        st = self._storage()
        captured = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured["body"] = data
            return _Resp(b"", status=200)

        with mock.patch("golive.backends.storage.supabase_store.requests.post",
                        side_effect=fake_post):
            st._upload("site/index.html", self.PAGE)

        resp = _Resp(captured["body"], "text/plain", encoding="ISO-8859-1")
        with mock.patch("golive.backends.storage.supabase_store.requests.get",
                        return_value=resp):
            self.assertEqual(st._download("site/index.html"), self.PAGE)

    def test_invalid_utf8_raises_with_the_path(self):
        st = self._storage()
        resp = _Resp(b"\xff\xfe not utf-8", "text/plain")
        with mock.patch("golive.backends.storage.supabase_store.requests.get",
                        return_value=resp):
            with self.assertRaises(SupabaseStorageError) as ctx:
                st._download("broken/index.html")
        self.assertIn("broken/index.html", str(ctx.exception))
        self.assertIn("UTF-8", str(ctx.exception))


class TestSupabaseRegistryTakesExplicitSiteId(unittest.TestCase):
    """HG-080-SB-02: import must be able to preserve a site_id here.

    A whole-archive import into an empty Supabase instance used to abort with
    "cannot preserve site_id on a SupabaseRegistry registry" — after already
    writing data rows and HTML, leaving orphan objects with no metadata.
    PostgREST can insert an explicit id perfectly well; the capability was
    simply missing.
    """

    @classmethod
    def setUpClass(cls):
        from tests.fake_postgrest import FakePostgrest
        cls.fake = FakePostgrest()
        cls.url = cls.fake.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.tables.clear()
        from golive.backends.postgrest import PostgrestClient
        from golive.backends.registry.supabase_store import SupabaseRegistry
        self.reg = SupabaseRegistry(
            PostgrestClient(self.url, "test-key"), table="golive_sites")

    def test_create_with_id_preserves_the_id(self):
        from golive.core.portability import _registry_create_with_id
        wanted = "0123456789abcdef0123456789abcdef"
        row = _registry_create_with_id(self.reg, wanted, "Imported",
                                       "imported-slug", "owner@example.com",
                                       "note")
        self.assertEqual(row.get("site_id"), wanted)
        back = self.reg.get(wanted)
        self.assertIsNotNone(back, "row not retrievable by its original id")
        self.assertEqual(back.get("slug"), "imported-slug")

    def test_does_not_mint_a_fresh_id(self):
        """The old fallback called create(), which invented a new id."""
        from golive.core.portability import _registry_create_with_id
        wanted = "ffffffffffffffffffffffffffffffff"
        row = _registry_create_with_id(self.reg, wanted, "N", "s2", "", "")
        self.assertEqual(row["site_id"], wanted)
        self.assertEqual(len(self.reg.list_all(limit=50)), 1)


class TestSkipDoesNotRewriteHtml(unittest.TestCase):
    """HG-080-SB-06: --on-conflict skip must leave live HTML alone.

    Import wrote every HTML file unconditionally, so a skipped site still had
    its page overwritten from the archive — an old backup silently clobbering
    newer content, which is not what "skip" means to anyone.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_skiphtml_")
        self._prev = os.environ.get("GOLIVE_HOME")
        os.environ["GOLIVE_HOME"] = self.home
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.core import paths
        paths.reset_cache()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GOLIVE_HOME", None)
        else:
            os.environ["GOLIVE_HOME"] = self._prev
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_skipped_site_keeps_its_current_html(self):
        from golive.backends.factory import (get_registry, get_storage,
                                             get_template_store)
        from golive.config import get_config
        from golive.core import portability

        cfg = get_config()
        reg, sto = get_registry(cfg), get_storage(cfg)
        store = get_template_store(cfg)
        site = reg.create(name="Live", slug="live")
        sto.publish("<html>ARCHIVED</html>", site["site_id"])
        store.create(model_code="m", name="r0", content={"i": 0})

        archive = os.path.join(self.home, "a.tar.gz")
        portability.export_archive(archive, cfg=cfg)

        # The live page moves on after the backup was taken.
        sto.publish("<html>NEWER</html>", site["site_id"])

        res = portability.import_archive(archive, cfg=cfg,
                                        on_conflict="skip", yes=True)
        self.assertEqual(res["sites_skipped"], 1)
        self.assertEqual(res["html_files_written"], 0,
                         "skip still rewrote the page from the archive")
        self.assertEqual(res.get("html_files_skipped"), 1)
        self.assertIn("NEWER", sto.read(site["site_id"]))


class TestDryRunNeverInventsATargetCount(unittest.TestCase):
    """HG-080-SB-05: an unmeasured target must read "unknown", not 0.

    `migrate --dry-run` skipped opening a non-sqlite target entirely and then
    printed the initial 0 as though it had counted, so a Supabase table with
    rows in it previewed as empty.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_dryrun_")
        self._prev = os.environ.get("GOLIVE_HOME")
        os.environ["GOLIVE_HOME"] = self.home
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.core import paths
        paths.reset_cache()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GOLIVE_HOME", None)
        else:
            os.environ["GOLIVE_HOME"] = self._prev
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_same_backend_is_refused_not_previewed_as_empty(self):
        """R2-NEW-01: sqlite→sqlite used to preview "Target existing: 0".

        Source and target are the same table there, so the 0 described a
        table that plainly held rows. Migrating a backend onto itself is a
        no-op that rewrites every row in place, so it is refused outright.
        """
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import migrate_backend

        store = TemplateStore()
        for i in range(2):
            store.create(model_code="m", name=f"same{i}", content={"i": i})

        for dry in (True, False):
            res = migrate_backend("data", "sqlite", dry_run=dry)
            self.assertFalse(res.get("ok"), f"dry_run={dry} was allowed")
            self.assertIn("already uses", res.get("error", ""))
            self.assertNotEqual(res.get("target_existing"), 0,
                                "must not report a fabricated zero")
        # Nothing was touched.
        self.assertEqual(sum(m.get("count", 0)
                             for m in store.list_models()), 2)

    def test_unreachable_target_reports_none_not_zero(self):
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import migrate_backend

        store = TemplateStore()
        for i in range(3):
            store.create(model_code="m", name=f"r{i}", content={"i": i})

        # postgres without psycopg installed → target cannot be opened.
        res = migrate_backend("data", "postgres", dry_run=True)
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res["source_count"], 3)
        self.assertIsNone(res["target_existing"])
        self.assertFalse(res["target_has_data"])
        self.assertEqual(res.get("warning", ""), "",
                         "must not warn about data it never looked at")


class TestGeneratedSqlMentionsGrants(unittest.TestCase):
    """HG-080-SB-04: GRANT and RLS are two separate gates.

    Newer Supabase projects do not expose new tables to the Data API
    automatically. With the grant missing, PostgREST answers 401 / 42501 even
    when the policies are in place, so the printed SQL has to say so.
    """

    def test_data_table_sql_covers_grant_and_row_hiding(self):
        from golive.backends.data.supabase import CREATE_TABLE_SQL
        sql = CREATE_TABLE_SQL.replace("{table}", "golive_templates")
        self.assertIn("grant", sql.lower())
        self.assertIn("42501", sql)
        self.assertIn("to anon", sql.lower())
        # Empty-array-on-no-policy is the single most confusing RLS behaviour.
        self.assertIn("empty array", sql.lower())

    def test_registry_table_sql_covers_grant(self):
        from golive.backends.registry.supabase_store import CREATE_TABLE_SQL
        sql = CREATE_TABLE_SQL.replace("{table}", "golive_sites")
        self.assertIn("grant", sql.lower())
        self.assertIn("service_role", sql)


class TestDemoTextIsBackendNeutral(unittest.TestCase):
    """HG-080-SB-03: the demo claimed "no cloud, no API key" on Supabase.

    Published against Supabase, that page ships an anon key — telling the
    reader there is no API key invites them to skip the RLS setup the mode
    depends on.
    """

    def _demo(self, name: str) -> str:
        from pathlib import Path
        import golive
        p = Path(golive.__file__).parent / "resources" / "demo" / name
        return p.read_text(encoding="utf-8")

    def test_crud_demo_does_not_hardcode_sqlite(self):
        html = self._demo("demo-crud.html")
        self.assertNotIn("没有 API key", html)
        self.assertNotIn("写进了本机 SQLite", html)
        # Describes whatever backend it was actually published against.
        self.assertIn("_config", html)
        self.assertIn("supabase", html)

    def test_crud_demo_warns_about_anon_key_on_supabase(self):
        html = self._demo("demo-crud.html")
        self.assertIn("RLS", html)

    def test_static_demo_mentions_the_alternatives(self):
        html = self._demo("demo-static.html")
        self.assertIn("Supabase", html)


if __name__ == "__main__":
    unittest.main()
