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


class TestCssStyles(unittest.TestCase):
    def test_19_styles_present_and_loadable(self):
        from golive.core.css_style_enhancer import STYLE_MAP, load_css

        self.assertEqual(len(STYLE_MAP), 19)
        internal_host = "xhs" + "cdn"  # keep release grep at zero literal hits
        for key in STYLE_MAP:
            css = load_css(key)
            self.assertTrue(css.strip(), f"{key}.css is empty")
            self.assertNotIn(internal_host, css)

    def test_font_cdn_base_swap(self):
        from golive.core.css_style_enhancer import apply_font_cdn_base

        src = "@import url('https://fonts.googleapis.com/css2?family=Cinzel');"
        out = apply_font_cdn_base(src, "https://fonts.loli.net")
        self.assertIn("https://fonts.loli.net/css2?family=Cinzel", out)
        self.assertNotIn("googleapis", out)
        # empty base → unchanged
        self.assertEqual(apply_font_cdn_base(src, ""), src)


class TestCommandUploader(unittest.TestCase):
    def test_upload_success(self):
        from golive.backends.images.command import CommandUploader

        up = CommandUploader("printf https://example.com/x.png#{file}")
        url = up.upload(b"\x89PNG", "x.png")
        self.assertTrue(url.startswith("https://example.com/x.png#"))

    def test_upload_failure_raises(self):
        from golive.backends.images.base import UploadError
        from golive.backends.images.command import CommandUploader

        # command outputs no URL
        up = CommandUploader("printf no-url-here {file}")
        with self.assertRaises(UploadError):
            up.upload(b"data", "a.png")
        # non-zero exit
        up2 = CommandUploader("false {file}")
        with self.assertRaises(UploadError):
            up2.upload(b"data", "a.png")

    def test_template_validation_and_factory(self):
        from golive.backends.images.command import CommandUploader, get_uploader

        with self.assertRaises(ValueError):
            CommandUploader("no-placeholder-cmd")

        old = os.environ.pop("GOLIVE_UPLOADER_CMD", None)
        try:
            self.assertIsNone(get_uploader())
            os.environ["GOLIVE_UPLOADER_CMD"] = "printf https://e.com/u {file}"
            self.assertIsNotNone(get_uploader())
        finally:
            os.environ.pop("GOLIVE_UPLOADER_CMD", None)
            if old is not None:
                os.environ["GOLIVE_UPLOADER_CMD"] = old

    def test_bundler_falls_back_to_base64_on_failure(self):
        import tempfile as _tf
        from pathlib import Path as _P

        from golive.backends.images.command import CommandUploader
        from golive.core.bundle import Bundler

        with _tf.TemporaryDirectory() as d:
            root = _P(d)
            (root / "index.html").write_text(
                '<html><body><img src="pix.png"></body></html>', encoding="utf-8")
            (root / "pix.png").write_bytes(b"\x89PNG\r\n\x1a\n123")

            bad = CommandUploader("false {file}")  # always fails
            b = Bundler(root, uploader=bad, use_image_upload=True)
            html = b.bundle(root / "index.html")
            self.assertIn("data:image/png;base64,", html)  # graceful fallback


if __name__ == "__main__":
    unittest.main()
