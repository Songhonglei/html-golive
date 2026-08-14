"""End-to-end coverage for the published-page data path.

The v0.7.6 Postgres release shipped a working store layer but a broken page
layer: publish refused to treat postgres as ready, the injected script fell
back to supabase mode, and ``/api/data`` answered 404. Every store-level test
passed, so nothing caught it.

These tests walk the whole chain the browser actually uses:

    golive.yaml -> publish readiness -> injected TemplateAPI script
                -> HTTP /api/data -> factory -> store -> database

SQLite runs everywhere. Postgres runs only when GOLIVE_PG_DSN is set (and
psycopg is installed); otherwise those cases skip rather than pretend.
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

TABLE = "golive_templates"


def _pg_ready() -> bool:
    if not os.environ.get("GOLIVE_PG_DSN", "").strip():
        return False
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


PG_READY = _pg_ready()


class _BackendCase(unittest.TestCase):
    """Shared assertions, run once per server-proxied backend."""

    backend = "sqlite"

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix=f"golive_e2e_{self.backend}_")
        os.environ["GOLIVE_HOME"] = self.home
        Path(self.home, "golive.yaml").write_text(
            f"data:\n  backend: {self.backend}\n", encoding="utf-8")
        from golive import config as cfg_mod
        cfg_mod._current = None
        from golive.config import get_config
        self.cfg = get_config()
        self._created_ids: list = []

    def tearDown(self):
        # Postgres is a shared database: remove only what this test made.
        for rid in self._created_ids:
            try:
                from golive.backends.factory import get_template_store
                get_template_store(self.cfg).delete(rid)
            except Exception:  # noqa: BLE001 — cleanup must not mask failures
                pass
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    # ── the chain, one link at a time ───────────────────────────────────

    def test_publish_considers_the_backend_ready(self):
        from golive.backends.factory import data_backend_ready
        ready, label = data_backend_ready(self.cfg)
        self.assertTrue(ready, f"{self.backend} should be publish-ready")
        self.assertEqual(label, self.backend)

    def test_injected_script_points_at_the_local_endpoint(self):
        from golive.inject import template_api
        js = template_api.generate_js_from_config("e2e", cfg=self.cfg)
        self.assertIn('mode       : "local"', js)
        self.assertIn('baseUrl    : "/api/data"', js)
        # The runtime guard must not be able to fire for a local backend:
        # it only demands a key from supabase. (The literal "_blocked: true"
        # always appears inside the guard's else-branch source, so it is not
        # a usable signal — assert on the condition instead.)
        self.assertIn("(CFG.mode === 'supabase' && !CFG.apiKey)", js)
        self.assertNotIn("CFG.mode !== 'sqlite'", js)

    def test_injected_script_carries_no_credentials(self):
        from golive.inject import template_api
        js = template_api.generate_js_from_config("e2e", cfg=self.cfg)
        for secret in ("GOLIVE_PG_DSN", "postgresql://", "postgres://"):
            self.assertNotIn(secret, js)
        self.assertIn('apiKey     : ""', js)

    def test_http_crud_round_trip(self):
        """POST -> GET -> PATCH -> DELETE through the /api/data handler."""
        from golive.server import data_api

        # create
        row = {"model_code": "e2e", "name": "e2e-row",
               "content": {"hello": "world"}}
        st, payload, _h = data_api.handle(
            "POST", f"/api/data/{TABLE}", {}, json.dumps([row]).encode(),
            headers={"Prefer": "return=representation"}, cfg=self.cfg)
        self.assertIn(st, (200, 201), f"create failed: {payload}")
        created = payload[0] if isinstance(payload, list) else payload
        rid = created["id"]
        self._created_ids.append(rid)

        # read back
        st, payload, _h = data_api.handle(
            "GET", f"/api/data/{TABLE}", {"id": [f"eq.{rid}"]}, b"",
            cfg=self.cfg)
        self.assertEqual(st, 200)
        self.assertEqual(payload[0]["name"], "e2e-row")
        self.assertEqual(payload[0]["content"], {"hello": "world"})

        # patch
        st, payload, _h = data_api.handle(
            "PATCH", f"/api/data/{TABLE}", {"id": [f"eq.{rid}"]},
            json.dumps({"description": "patched"}).encode(),
            headers={"Prefer": "return=representation"}, cfg=self.cfg)
        self.assertEqual(st, 200, f"patch failed: {payload}")
        self.assertEqual(payload[0]["description"], "patched")

        # delete
        st, _payload, _h = data_api.handle(
            "DELETE", f"/api/data/{TABLE}", {"id": [f"eq.{rid}"]}, b"",
            cfg=self.cfg)
        self.assertIn(st, (200, 204))
        self._created_ids.remove(rid)

        st, payload, _h = data_api.handle(
            "GET", f"/api/data/{TABLE}", {"id": [f"eq.{rid}"]}, b"",
            cfg=self.cfg)
        self.assertEqual(payload, [])

    def test_admin_data_api_sees_the_backend(self):
        from golive.server import admin_api
        store = admin_api._data_store()
        self.assertIsNotNone(
            store, f"admin data API must support {self.backend}")


class TestSqliteChain(_BackendCase):
    backend = "sqlite"


@unittest.skipUnless(
    PG_READY, "GOLIVE_PG_DSN not set or psycopg missing — skipping PG e2e")
class TestPostgresChain(_BackendCase):
    backend = "postgres"


class TestRegistryTouchAdvancesTheTimestamp(unittest.TestCase):
    """touch() must always move updated_at, even in the same second.

    The registry used second-precision timestamps, so create()+touch() in
    quick succession left updated_at unchanged and callers could not tell a
    stale record from a just-touched one.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_touch_")
        os.environ["GOLIVE_HOME"] = self.home
        from golive import config as cfg_mod
        cfg_mod._current = None

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    def test_touch_changes_updated_at_immediately(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        reg = SqliteRegistry()
        site = reg.create(name="touch-me")
        before = reg.get(site["site_id"])["updated_at"]
        reg.touch(site["site_id"])          # no sleep on purpose
        after = reg.get(site["site_id"])["updated_at"]
        self.assertNotEqual(before, after,
                            "touch() left updated_at unchanged")
        self.assertGreater(after, before,
                           "updated_at must move forward, not backwards")


class TestSupabaseStaysPageDirect(unittest.TestCase):
    """Supabase must keep talking to its own project, not /api/data."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_e2e_sb_")
        os.environ["GOLIVE_HOME"] = self.home
        Path(self.home, "golive.yaml").write_text(
            "data:\n  backend: supabase\n", encoding="utf-8")
        from golive import config as cfg_mod
        cfg_mod._current = None

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        from golive import config as cfg_mod
        cfg_mod._current = None

    def test_not_server_proxied(self):
        from golive.config import get_config
        from golive.backends.factory import is_server_proxied_data
        self.assertFalse(is_server_proxied_data(get_config()))

    def test_local_endpoint_refuses_supabase(self):
        from golive.config import get_config
        from golive.server import data_api
        st, _payload, _h = data_api.handle(
            "GET", f"/api/data/{TABLE}", {}, b"", cfg=get_config())
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
