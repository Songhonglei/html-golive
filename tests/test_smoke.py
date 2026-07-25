"""Smoke tests for golive M1 core.

Run: python -m pytest tests/  (or python tests/test_smoke.py)
Uses a temp GOLIVE_HOME so it never touches real data.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP_HOME = tempfile.mkdtemp(prefix="golive_test_home_")
os.environ["GOLIVE_HOME"] = _TMP_HOME


class TestRegistryAndStorage(unittest.TestCase):
    def test_publish_update_rollback(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage

        reg = SqliteRegistry()
        storage = LocalStorage()

        site = reg.create(name="T", slug="t-demo")
        self.assertEqual(len(site["site_id"]), 32)

        storage.publish("<h1>v1</h1>", site["site_id"], backup_previous=False)
        self.assertEqual(storage.read(site["site_id"]), "<h1>v1</h1>")

        storage.publish("<h1>v2</h1>", site["site_id"])
        self.assertEqual(storage.read(site["site_id"]), "<h1>v2</h1>")
        self.assertEqual(len(storage.list_snapshots(site["site_id"])), 1)

        storage.rollback(site["site_id"])
        self.assertEqual(storage.read(site["site_id"]), "<h1>v1</h1>")

        self.assertIsNotNone(reg.get_by_slug("t-demo"))
        self.assertIsNotNone(reg.resolve(site["site_id"]))
        reg.delete(site["site_id"])
        self.assertIsNone(reg.get(site["site_id"]))


class TestSlugChecker(unittest.TestCase):
    def test_reserved_and_format(self):
        from golive.core.slug_checker import check_format, check_reserved

        self.assertFalse(check_format("a")[0])          # too short
        self.assertFalse(check_format("bad slug!")[0])  # bad chars
        self.assertTrue(check_format("good-slug_1")[0])
        self.assertTrue(check_reserved("api")[0])
        self.assertTrue(check_reserved("a-p-i")[0])     # variant-proof
        self.assertFalse(check_reserved("myreport")[0])


class TestSecurityScanner(unittest.TestCase):
    def test_strong_hit_blocks(self):
        from golive.security.scanner import scan_html

        bad = '<script>var k = "AKIAIOSFODNN7EXAMPLE";</script>'
        result = scan_html(bad)
        self.assertTrue(result.blocked)

    def test_clean_html_passes(self):
        from golive.security.scanner import scan_html

        ok = "<html><body><h1>Weather report</h1><p>Sunny.</p></body></html>"
        result = scan_html(ok)
        self.assertFalse(result.blocked)


if __name__ == "__main__":
    unittest.main()
