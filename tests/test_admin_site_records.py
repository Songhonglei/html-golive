"""Site detail in the portal: manifest, policy and scan history.

These records are per-site, so they belong in the site drawer rather than a
tenth top-level page. The API tests cover the payload; the UI tests cover the
parts that a wrong field name would break silently — a verdict label that
reads "passed" for a page that was actually blocked is worse than no label.
"""
from __future__ import annotations

import os
import tempfile
import unittest


class _ApiCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._prev_home = os.environ.get("GOLIVE_HOME")
        os.environ["GOLIVE_HOME"] = self._tmp.name
        os.environ.setdefault("GOLIVE_LANG", "en")
        from golive.core import paths
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)
        self.addCleanup(self._restore_home)
        from golive.backends.registry import scans_store, sqlite_manifest
        sqlite_manifest.reset_cache()
        scans_store.reset_cache()

        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        self.registry = SqliteRegistry()
        self.storage = LocalStorage()
        self.site = self.registry.create(name="U", slug="u1")
        self.site_id = self.site["site_id"]
        self.storage.publish("<html><body>hi</body></html>", self.site_id,
                             backup_previous=False)

    def _restore_home(self):
        if self._prev_home is None:
            os.environ.pop("GOLIVE_HOME", None)
        else:
            os.environ["GOLIVE_HOME"] = self._prev_home

    def _detail(self):
        from golive.server import admin_api
        from golive.server.authz import Identity
        identity = Identity(email="admin@example.test", is_superadmin=True)
        status, payload = admin_api.handle(
            "GET", "/api/admin/sites/u1", {}, b"", identity,
            self.registry, self.storage)
        self.assertEqual(status, 200, payload)
        return payload


class TestSiteDetailCarriesTheRecords(_ApiCase):

    def test_the_three_keys_are_always_present(self):
        """Absent records are null/[], not a missing key.

        The drawer reads them unconditionally; a missing key would be an
        undefined in the UI rather than an empty section.
        """
        detail = self._detail()
        for key in ("manifest", "policy", "scans"):
            with self.subTest(key=key):
                self.assertIn(key, detail)

    def test_a_site_without_a_manifest_still_has_a_policy(self):
        """Each record is read separately, so one gap is not three."""
        detail = self._detail()
        self.assertIsNone(detail["manifest"])
        self.assertIsNotNone(detail["policy"])

    def test_the_manifest_comes_through_once_written(self):
        from golive.backends.registry.sqlite_manifest import get_manifests
        get_manifests().put_manifest(
            self.site_id, content_sha256="abc123", source_type="file",
            injections=["watermark"], published_with="9.9.9")
        detail = self._detail()
        self.assertEqual(detail["manifest"]["injections"], ["watermark"])
        self.assertEqual(detail["manifest"]["published_with"], "9.9.9")

    def test_the_policy_comes_through(self):
        from golive.backends.registry.sqlite_manifest import get_manifests
        get_manifests().set_policy(self.site_id, watermark_enabled=True,
                                   watermark_config={"text": "Internal"})
        detail = self._detail()
        self.assertTrue(detail["policy"]["watermark_enabled"])
        self.assertEqual(detail["policy"]["watermark_config"]["text"],
                         "Internal")

    def test_scans_come_through_newest_first(self):
        from golive.backends.registry.scans_store import get_scans_store
        store = get_scans_store()
        store.record(site_id=self.site_id, verdict="pass",
                     content_sha256="a" * 64)
        store.record(site_id=self.site_id, verdict="block",
                     content_sha256="b" * 64)
        scans = self._detail()["scans"]
        self.assertEqual(len(scans), 2)
        self.assertEqual(scans[0]["verdict"], "block")

    def test_another_sites_records_do_not_leak_in(self):
        other = self.registry.create(name="O", slug="o1")
        from golive.backends.registry.scans_store import get_scans_store
        get_scans_store().record(site_id=other["site_id"], verdict="block",
                                 content_sha256="c" * 64)
        self.assertEqual(self._detail()["scans"], [])

    def test_permission_is_still_enforced(self):
        """The records must not widen who can see a site."""
        from golive.server import admin_api
        from golive.server.authz import Identity
        outsider = Identity(email="nobody@example.test", is_superadmin=False)
        status, _payload = admin_api.handle(
            "GET", "/api/admin/sites/u1", {}, b"", outsider,
            self.registry, self.storage)
        self.assertEqual(status, 403)


class TestThePortalReadsTheRightFields(unittest.TestCase):
    """Guards the field names the drawer depends on.

    The verdict column is named ``verdict`` with three values; the first
    version of the renderer read ``sc.blocked``, which is absent from the row
    and labelled every scan — including blocked ones — as passed.
    """

    def setUp(self):
        os.environ.setdefault("GOLIVE_LANG", "en")
        from golive.server.admin_ui import render_admin_page
        self.page = render_admin_page()

    def test_the_renderer_reads_verdict(self):
        self.assertIn("sc.verdict", self.page)

    def test_the_renderer_does_not_read_a_nonexistent_blocked_field(self):
        self.assertNotIn("sc.blocked", self.page)

    def test_all_three_verdicts_are_distinguishable(self):
        for verdict in ("blocked", "warned", "passed"):
            with self.subTest(verdict=verdict):
                self.assertIn("d.scans." + verdict, self.page)

    def test_the_drawer_renders_both_new_sections(self):
        for call in ("renderManifest(", "renderScans("):
            with self.subTest(call=call):
                self.assertIn(call, self.page)

    def test_the_new_labels_exist_in_both_languages(self):
        self.assertIn("Last publish", self.page)
        self.assertIn("上次发布", self.page)

    def test_the_drawer_subtitle_is_no_longer_hardcoded_chinese(self):
        """It was inline Chinese, so an English session saw 角色 here."""
        self.assertNotIn('" · 角色: "', self.page)
        self.assertIn('t("word.role")', self.page)


if __name__ == "__main__":
    unittest.main()
