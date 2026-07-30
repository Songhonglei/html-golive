"""Tests for the GitHub Pages landing pages (docs/index.html + index.zh.html).

The pages are static marketing assets, but they ship in the repo and are
served publicly, so they get the same treatment as the portal: no unexpected
outbound references, valid JS, and the two language versions must stay in
sync structurally.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

DOCS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
EN = os.path.join(DOCS, "index.html")
ZH = os.path.join(DOCS, "index.zh.html")

# Hosts the landing page is allowed to reference: the project's own
# repository, its package page and the shield/badge services rendering the
# CI + version badges. Anything else is a regression.
#
# Two entries are not network references at all and are allowlisted as such:
#   www.w3.org      SVG xmlns in the inline data: favicon
#   localhost:8787  sample terminal output shown to the reader
ALLOWED_HOSTS = {
    "github.com",
    "img.shields.io",
    "pypi.org",
    "www.w3.org",
    "localhost:8787",
}


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _hosts(html):
    return {m.group(1).lower()
            for m in re.finditer(r'https?://([^/"\'\s>)]+)', html)}


class TestLandingPagesExist(unittest.TestCase):
    def test_both_pages_exist(self):
        self.assertTrue(os.path.isfile(EN), "docs/index.html missing")
        self.assertTrue(os.path.isfile(ZH), "docs/index.zh.html missing")

    def test_lang_attributes(self):
        self.assertIn('<html lang="en">', _read(EN))
        self.assertIn('<html lang="zh-CN">', _read(ZH))

    def test_zh_title_and_description_localised(self):
        html = _read(ZH)
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"[\u4e00-\u9fff]",
                         "zh title is not translated")
        d = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
        self.assertIsNotNone(d)
        self.assertRegex(d.group(1), r"[\u4e00-\u9fff]",
                         "zh description is not translated")

    def test_en_page_stays_english(self):
        """Guards against the generator overwriting the English page."""
        html = _read(EN)
        body = html[html.index("<body>"):]
        # a handful of CJK characters may not appear in the English page body
        self.assertNotRegex(body, r"[\u4e00-\u9fff]{4,}")


class TestLanguageSwitching(unittest.TestCase):
    def test_nav_cross_links(self):
        self.assertIn('href="index.zh.html" class="lang-link"', _read(EN))
        self.assertIn('href="index.html" class="lang-link"', _read(ZH))

    def test_footer_cross_links(self):
        en_foot = _read(EN)
        en_foot = en_foot[en_foot.index("<footer"):]
        self.assertIn('href="index.zh.html"', en_foot)
        zh_foot = _read(ZH)
        zh_foot = zh_foot[zh_foot.index("<footer"):]
        self.assertIn('href="index.html"', zh_foot)

    def test_hreflang_alternates_on_both(self):
        for path in (EN, ZH):
            html = _read(path)
            self.assertIn('rel="alternate" hreflang="en" href="index.html"',
                          html, path)
            self.assertIn(
                'rel="alternate" hreflang="zh-CN" href="index.zh.html"',
                html, path)


class TestStructuralParity(unittest.TestCase):
    def test_same_stylesheet(self):
        """One design, two languages — the CSS must be byte-identical."""
        a, b = _read(EN), _read(ZH)
        self.assertEqual(a[a.index("<style>"):a.index("</style>")],
                         b[b.index("<style>"):b.index("</style>")])

    def test_same_script(self):
        a, b = _read(EN), _read(ZH)
        self.assertEqual(a[a.rindex("<script>"):].strip(),
                         b[b.rindex("<script>"):].strip())

    def test_same_section_ids(self):
        def ids(html):
            return re.findall(r'<section id="([^"]+)"', html)
        self.assertEqual(ids(_read(EN)), ids(_read(ZH)))


class TestNoUnexpectedExternals(unittest.TestCase):
    def test_no_external_stylesheets_or_scripts(self):
        for path in (EN, ZH):
            html = _read(path)
            for m in re.finditer(
                    r'<(?:link[^>]*rel=["\']stylesheet["\']|script)[^>]*'
                    r'(?:href|src)\s*=\s*["\'](https?:)?//', html):
                self.fail(f"{path}: external asset {m.group(0)}")
            self.assertNotIn("@import", html.lower(), path)

    def test_only_allowlisted_hosts(self):
        for path in (EN, ZH):
            extra = _hosts(_read(path)) - ALLOWED_HOSTS
            self.assertFalse(extra, f"{path}: unexpected hosts {sorted(extra)}")


class TestLandingScriptSyntax(unittest.TestCase):
    def test_inline_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        for path in (EN, ZH):
            html = _read(path)
            for i, body in enumerate(
                    re.findall(r"<script>(.*?)</script>", html, re.S)):
                with tempfile.NamedTemporaryFile(
                        "w", suffix=".js", delete=False,
                        encoding="utf-8") as fh:
                    fh.write(body)
                    tmp = fh.name
                try:
                    p = subprocess.run([node, "--check", tmp],
                                       capture_output=True, text=True)
                    self.assertEqual(p.returncode, 0,
                                     f"{path} script #{i}: {p.stderr}")
                finally:
                    os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
