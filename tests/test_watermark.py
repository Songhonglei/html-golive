"""M3 watermark tests: identity sources, CLI flag, kill switch, escaping."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_wm_"))


class TestWatermarkInject(unittest.TestCase):
    def setUp(self):
        from golive.config import Config
        self.cfg = Config()
        os.environ.pop("GOLIVE_WATERMARK_OFF", None)

    def tearDown(self):
        os.environ.pop("GOLIVE_WATERMARK_OFF", None)
        from golive.config import reset_config
        reset_config()

    def test_static_text_source(self):
        from golive.inject import watermark
        self.cfg.watermark.text = "CONFIDENTIAL"
        out = watermark.inject_into_html(
            "<html><body><p>x</p></body></html>", cfg=self.cfg)
        self.assertIn("watermark-layer", out)
        self.assertIn('"CONFIDENTIAL"', out)
        self.assertNotIn("authMeUrl     : \"/auth/me\"", out)

    def test_auth_identity_source(self):
        from golive.inject import watermark
        out = watermark.inject_into_html(
            "<html><body></body></html>", auth_me_url="/auth/me", cfg=self.cfg)
        self.assertIn('"/auth/me"', out)
        # watermark shows email *prefix* only — the JS splits at '@'
        self.assertIn("split('@')[0]", out)

    def test_meta_tag_source_runtime(self):
        from golive.inject import watermark
        out = watermark.inject_into_html(
            "<html><body></body></html>", cfg=self.cfg)
        # no text / no auth -> JS falls back to the meta tag at runtime
        self.assertIn('meta[name="golive-watermark"]', out)

    def test_kill_switch(self):
        from golive.inject import watermark
        os.environ["GOLIVE_WATERMARK_OFF"] = "1"
        self.assertTrue(watermark.is_disabled())
        html = "<html><body></body></html>"
        out = watermark.inject_into_html(html, text="X", cfg=self.cfg)
        self.assertNotIn("watermark-layer", out)
        # kill switch also strips a previously injected layer
        os.environ.pop("GOLIVE_WATERMARK_OFF")
        injected = watermark.inject_into_html(html, text="X", cfg=self.cfg)
        os.environ["GOLIVE_WATERMARK_OFF"] = "1"
        stripped = watermark.inject_into_html(injected, text="X", cfg=self.cfg)
        self.assertNotIn("watermark-layer", stripped)

    def test_idempotent(self):
        from golive.inject import watermark
        self.cfg.watermark.text = "T"
        out = watermark.inject_into_html(
            "<html><body></body></html>", cfg=self.cfg)
        out2 = watermark.inject_into_html(out, cfg=self.cfg)
        self.assertEqual(out2.count('id="watermark-layer"'), 1)

    def test_cdn_mode(self):
        from golive.inject import watermark
        self.cfg.watermark.cdn_url = "https://cdn.example.com/wm.js"
        out = watermark.inject_into_html(
            "<html><body></body></html>", cfg=self.cfg)
        self.assertIn('src="https://cdn.example.com/wm.js"', out)
        self.assertNotIn("_createTile", out)

    def test_style_params_from_config(self):
        from golive.inject import watermark
        self.cfg.watermark.text = "T"
        self.cfg.watermark.opacity = 0.4
        self.cfg.watermark.font_size = 22
        self.cfg.watermark.rotation = -45
        self.cfg.watermark.color = "255,0,0"
        out = watermark.generate_js(text="T", cfg=self.cfg)
        self.assertIn("0.4", out)
        self.assertIn("22", out)
        self.assertIn("-45", out)
        self.assertIn('"255,0,0"', out)

    def test_report_webhook_optional(self):
        from golive.inject import watermark
        out = watermark.generate_js(text="T", cfg=self.cfg)
        self.assertIn('reportWebhook : ""', out)
        self.cfg.watermark.report_webhook = "https://hook.example.com/wm"
        out2 = watermark.generate_js(text="T", cfg=self.cfg)
        self.assertIn("https://hook.example.com/wm", out2)

    def test_xss_escaping_via_shared_util(self):
        from golive.inject import watermark
        evil = '</script><script>alert(1)</script>'
        out = watermark.generate_js(text=evil, cfg=self.cfg)
        self.assertNotIn("</script><script>alert(1)", out)

    def test_cli_flag_triggers_injection(self):
        import argparse
        from golive.cli import _apply_watermark
        from golive.config import set_config
        set_config(self.cfg)
        args = argparse.Namespace(watermark="TEAM-X", slug="demo")
        out = _apply_watermark("<html><body></body></html>", args)
        self.assertIn("watermark-layer", out)
        self.assertIn("TEAM-X", out)
        # flag absent + yaml disabled -> no injection
        args2 = argparse.Namespace(watermark=None, slug="demo")
        out2 = _apply_watermark("<html><body></body></html>", args2)
        self.assertNotIn("watermark-layer", out2)


class TestSharedEscapeUtil(unittest.TestCase):
    """All four injectors must resolve to the same escaping module."""

    def test_single_source_of_truth(self):
        from golive.inject import _escape, editor, supabase_api, template_api, watermark
        self.assertIs(template_api._json_for_script, _escape.json_for_script)
        self.assertIs(supabase_api._json_for_script, _escape.json_for_script)
        self.assertIs(editor._json_for_script, _escape.json_for_script)
        self.assertIs(watermark._json_for_script, _escape.json_for_script)
        self.assertIs(template_api._safe_comment, _escape.safe_comment)
        self.assertIs(watermark._safe_comment, _escape.safe_comment)

    def test_escape_behaviour(self):
        from golive.inject._escape import json_for_script, safe_comment
        self.assertNotIn("</script>", json_for_script("</script>"))
        self.assertNotIn("<!--", json_for_script("<!--x"))
        self.assertNotIn("\u2028", json_for_script("a\u2028b"))
        self.assertNotIn("*/", safe_comment("x*/alert(1)"))
        self.assertNotIn("\n", safe_comment("a\nb"))
        self.assertNotIn("</script>", safe_comment("</ScRiPt >"))


if __name__ == "__main__":
    unittest.main()
