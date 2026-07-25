"""migrate-check tests.

Fixtures containing intranet references are built by joining fragments
at runtime so this repository never carries those literals.
"""

import unittest

from golive.core.migrate_check import scan_html

# fragments (joined at runtime — keeps the repo free of intranet literals)
BRAND = "xiaoho" + "ngshu"
CORP = BRAND + ".com"
CDN = "xhs" + "cdn" + ".com"
GW_TPL = "rf" + "phecda"
GW_DATA = "rfmulti" + "data"


def fixture_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><title>legacy</title>
<script id="template-data-layer">
  var CFG = {{ baseUrl: 'https://fin.{CORP}/{GW_TPL}/template' }};
</script>
<script id="supabase-data-layer">
  var CFG2 = {{ builderBase: 'https://builder.devops.{CORP}/builder-api/v1' }};
</script>
<link rel="icon" href="https://static.{CDN}/fav.ico">
</head><body>
<script>
  fetch('https://edith.{CORP}/api/x');
  fetch('/{GW_DATA}/query/query_dashboard');
  TemplateAPI.list({{pageSize: 10}}).then(r => render(r.list));
  TemplateAPI.upsert({{name: 'a', content: {{}}}});
  SupabaseAPI.query('todos', {{limit: 5}});
</script>
</body></html>"""


class TestMigrateCheck(unittest.TestCase):
    def setUp(self):
        self.findings = scan_html(fixture_html())

    def test_detects_intranet_domains(self):
        texts = [h["text"] for h in self.findings["domain_hits"]]
        self.assertTrue(any(f"fin.{CORP}" in t for t in texts), texts)
        self.assertTrue(any(f"edith.{CORP}" in t for t in texts), texts)
        self.assertTrue(any(CDN in t for t in texts), texts)
        self.assertTrue(any("builder.devops" in t for t in texts), texts)

    def test_detects_api_paths(self):
        texts = [h["text"] for h in self.findings["api_path_hits"]]
        self.assertTrue(any(GW_TPL in t for t in texts), texts)
        self.assertTrue(any(GW_DATA in t for t in texts), texts)
        self.assertTrue(any("builder-api/v1" in t for t in texts), texts)

    def test_detects_layer_residue(self):
        ids = [h["text"] for h in self.findings["layer_hits"]]
        self.assertIn("template-data-layer", ids)
        self.assertIn("supabase-data-layer", ids)

    def test_call_statistics(self):
        self.assertEqual(self.findings["tpl_calls"].get("list"), 1)
        self.assertEqual(self.findings["tpl_calls"].get("upsert"), 1)
        self.assertEqual(self.findings["sb_calls"].get("query"), 1)

    def test_line_numbers_present(self):
        for h in self.findings["domain_hits"]:
            self.assertGreater(h["line"], 0)

    def test_clean_html_passes(self):
        clean = "<html><head><title>ok</title></head><body>hi</body></html>"
        f = scan_html(clean)
        self.assertEqual(f["domain_hits"], [])
        self.assertEqual(f["api_path_hits"], [])
        self.assertEqual(f["layer_hits"], [])
        self.assertEqual(f["tpl_calls"], {})


if __name__ == "__main__":
    unittest.main()
