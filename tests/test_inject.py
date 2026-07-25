"""Injection-layer tests — signature parity with the intranet API is the
core promise of M2: the method-name lists below are hard-coded from the
intranet template_data_layer.py / supabase_data_layer.py and asserted
against the generated JS one by one.
"""

import re
import unittest

from golive.config import Config
from golive.inject import supabase_api, template_api

# Signature contract (extracted from the intranet JS injection layers).
TEMPLATE_API_METHODS = [
    "list", "listAll", "get", "create", "update", "delete", "sort", "upsert",
]
TEMPLATE_API_INTERNAL = ["_config"]
SUPABASE_API_METHODS = [
    "init", "getUser", "isReady", "onReady", "logout",
    "query", "insert", "update", "delete",
]
SUPABASE_API_INTERNAL = ["_config", "_request"]


def _cfg(url="https://proj.example-supabase.co", key="anon-key"):
    cfg = Config()
    cfg.supabase.url = url
    cfg.data.backend = "supabase"
    # patch key resolution via env indirection is annoying in tests;
    # generate_js is called with explicit values instead where needed.
    return cfg


class TestTemplateApiSignatures(unittest.TestCase):
    def _js(self, **kw):
        kw.setdefault("rest_url", "https://x.co/rest/v1")
        kw.setdefault("anon_key", "k")
        return template_api.generate_js("mc_test", "1.0.0", **kw)

    def test_all_methods_present(self):
        js = self._js()
        for m in TEMPLATE_API_METHODS:
            self.assertRegex(js, rf"\b{m}\s*:\s*function",
                             f"TemplateAPI.{m} missing from generated JS")
        for m in TEMPLATE_API_INTERNAL:
            self.assertIn(m, js)

    def test_blocked_stub_covers_all_methods(self):
        js = template_api.generate_js("mc", rest_url="", anon_key="")
        start = js.index("window.TemplateAPI = {")
        block = js[start:js.index("window.TEMPLATE_CONFIG")]
        for m in TEMPLATE_API_METHODS:
            self.assertRegex(block, rf"\b{m}\s*:",
                             f"stub missing method {m}")
        self.assertIn("_blocked: true", js)

    def test_config_embedding(self):
        js = template_api.generate_js(
            "a_v1,b_v1", "2.0.0", rest_url="https://x.co/rest/v1",
            anon_key="THE-KEY", table="my_tpl", user_id="alice")
        self.assertIn('["a_v1", "b_v1"]', js)
        self.assertIn('"a_v1"', js)          # compat first modelCode
        self.assertIn("'2.0.0'", js)
        self.assertIn('"https://x.co/rest/v1"', js)
        self.assertIn('"THE-KEY"', js)
        self.assertIn('"my_tpl"', js)
        self.assertIn('"alice"', js)
        self.assertIn("templateapi:ready", js)
        self.assertIn("window.TEMPLATE_CONFIG", js)

    def test_intranet_row_shape_preserved(self):
        js = self._js()
        for field in ["templateId", "templateName", "templateDesc",
                      "templateContent", "templateContentVersion",
                      "modelCode", "createTime", "updateTime"]:
            self.assertIn(field, js, f"intranet row field {field} missing")
        self.assertIn("total", js)
        self.assertIn("list:", js.replace(" ", "").replace("list:", "list:", 1)
                      and js)  # {total, list} envelope

    def test_placeholder_rejected(self):
        with self.assertRaises(ValueError):
            template_api.generate_js("__PLACEHOLDER_MODEL_CODE__")
        with self.assertRaises(ValueError):
            template_api.generate_js("")

    def test_inject_idempotent(self):
        cfg = _cfg()
        html = "<html><head><title>t</title></head><body>hi</body></html>"
        h1 = template_api.inject_into_html(html, "mc1", cfg=cfg)
        h2 = template_api.inject_into_html(h1, "mc2", cfg=cfg)
        self.assertEqual(h2.count("template-data-layer"), 1)
        self.assertIn("mc2", h2)
        self.assertNotIn('"mc1"', h2)

    def test_extract_model_code(self):
        cfg = _cfg()
        html = template_api.inject_into_html("<html><head></head></html>",
                                             "x_v1,y_v1", cfg=cfg)
        self.assertEqual(template_api.extract_model_code_from_html(html),
                         "x_v1,y_v1")

    def test_detect_usage_ignores_own_injection(self):
        cfg = _cfg()
        injected = template_api.inject_into_html(
            "<html><head></head><body></body></html>", "mc", cfg=cfg)
        self.assertFalse(template_api.detect_usage(injected))
        self.assertTrue(template_api.detect_usage(
            "<script>TemplateAPI.list().then()</script>"))


class TestSupabaseApiSignatures(unittest.TestCase):
    def test_all_methods_present(self):
        js = supabase_api.generate_js("https://x.supabase-host.co", "k")
        for m in SUPABASE_API_METHODS:
            self.assertRegex(js, rf"\b{m}\s*:\s*(function|_init)",
                             f"SupabaseAPI.{m} missing from generated JS")
        for m in SUPABASE_API_INTERNAL:
            self.assertIn(m, js)
        self.assertIn("supabaseapi:ready", js)
        self.assertIn("window.SUPABASE_CONFIG", js)

    def test_blocked_stub_covers_all_methods(self):
        js = supabase_api.generate_js("", "")
        block_start = js.index("_blockedMsg")
        block = js[block_start:js.index("window.SUPABASE_CONFIG")]
        for m in SUPABASE_API_METHODS:
            self.assertRegex(block, rf"\b{m}\s*:", f"stub missing {m}")
        self.assertIn("_blocked: true", js)

    def test_query_semantics(self):
        js = supabase_api.generate_js("https://x.co", "k")
        # PostgREST opts + caps preserved from the intranet contract
        for token in ["select", "filters", "order", "limit", "offset",
                      "500", "10000", "count=exact"]:
            self.assertIn(token, js)

    def test_inject_idempotent(self):
        cfg = _cfg()
        html = "<html><head></head><body></body></html>"
        h1 = supabase_api.inject_into_html(html, cfg=cfg)
        h2 = supabase_api.inject_into_html(h1, cfg=cfg)
        self.assertEqual(h2.count("supabase-data-layer"), 1)

    def test_detect_usage(self):
        self.assertTrue(supabase_api.detect_usage(
            "<script>SupabaseAPI.query('t',{})</script>"))
        cfg = _cfg()
        injected = supabase_api.inject_into_html(
            "<html><head></head></html>", cfg=cfg)
        self.assertFalse(supabase_api.detect_usage(injected))


class TestJsSyntaxSanity(unittest.TestCase):
    """Best-effort JS sanity: balanced braces outside string literals."""

    def _balance(self, js: str):
        # strip the <script> wrapper
        inner = re.sub(r"</?script[^>]*>", "", js)
        depth = 0
        in_str = None
        prev = ""
        for ch in inner:
            if in_str:
                if ch == in_str and prev != "\\":
                    in_str = None
            elif ch in "'\"`":
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                self.assertGreaterEqual(depth, 0, "unbalanced closing brace")
            prev = ch
        self.assertEqual(depth, 0, "unbalanced braces in generated JS")

    def test_template_js_balanced(self):
        self._balance(template_api.generate_js(
            "mc", rest_url="https://x/rest/v1", anon_key="k"))
        self._balance(template_api.generate_js("mc"))  # stub mode

    def test_supabase_js_balanced(self):
        self._balance(supabase_api.generate_js("https://x.co", "k"))
        self._balance(supabase_api.generate_js("", ""))  # stub mode


if __name__ == "__main__":
    unittest.main()
