"""Tests for the M5 admin portal page (golive/server/admin_ui.py + /admin)."""

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests import lan_ip_or_none


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    os.environ.pop("GOLIVE_TOKEN", None)
    os.environ.pop("GOLIVE_ADMINS", None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


class TestRenderAdminPage(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def _render(self, identity=None):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page(identity)

    def test_key_dom_ids_present(self):
        html = self._render()
        for dom_id in ("view-sites", "view-stats", "view-audit", "drawer",
                       "site-rows", "stat-cards", "audit-rows",
                       "login-gate", "d-maints", "d-snaps", "toast"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_data_view_dom_ids_present(self):
        """M6: data-management view elements exist."""
        html = self._render()
        for dom_id in ("nav-data", "view-data", "data-nobackend",
                       "data-main", "data-model", "data-rows", "data-q",
                       "data-add", "dm", "dm-json", "dm-err", "dm-save"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_data_nav_superadmin_only(self):
        """M6: nav-data is hidden by default and revealed for superadmin."""
        html = self._render()
        m = re.search(r'<div class="([^"]*)" data-view="data"', html)
        self.assertIsNotNone(m)
        self.assertIn("hidden", m.group(1))
        # JS reveals it inside the superadmin branch only
        js = html[html.rindex("<script>"):]
        gate = js[js.index("if (who.superadmin){"):]
        self.assertIn('$("nav-data").classList.remove("hidden")',
                      gate[:400])

    def test_data_modal_validates_json_client_side(self):
        """M6: the row modal JSON.parse-validates before saving."""
        html = self._render()
        self.assertIn('JSON.parse($("dm-json").value', html)
        self.assertIn("JSON 解析失败", html)

    def test_no_external_cdn_references(self):
        html = self._render()
        # every http(s):// occurrence must be inside a code string that the
        # page never fetches — the M5 page must not fetch anything remote.
        for m in re.finditer(r'(?:src|href)\s*=\s*["\'](https?:)?//', html):
            self.fail(f"external resource reference found: {m.group(0)}")
        self.assertNotIn("cdn.", html.lower())
        self.assertNotIn("googleapis", html.lower())
        self.assertNotIn("@import", html.lower())

    def test_boot_json_injected_and_escaped(self):
        from golive.server import authz
        evil = authz.Identity(email='x</script><script>alert(1)//@e.com')
        html = self._render(evil)
        # raw close-tag from the payload must not survive into the script
        self.assertNotIn('x</script><script>alert(1)', html)
        self.assertIn("<\\/script>", html)
        # boot JSON parses back
        m = re.search(r"window\.GOLIVE_BOOT = (.*?);</script>", html)
        self.assertIsNotNone(m)
        boot = json.loads(m.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))
        self.assertTrue(boot["authenticated"])

    def test_version_embedded(self):
        from golive import __version__
        html = self._render()
        self.assertIn(__version__, html)


class TestPortalTheming(unittest.TestCase):
    """v0.7.0: dark/light theming driven by CSS variables."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_light_variable_group_present(self):
        html = self._render()
        self.assertIn(':root[data-theme="light"]', html)
        self.assertIn(':root, :root[data-theme="dark"]', html)

    def test_both_themes_define_the_same_variables(self):
        """A missing variable in one theme silently falls back — catch it."""
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]

        def vars_of(selector):
            start = css.index(selector)
            block = css[css.index("{", start) + 1:css.index("}", start)]
            return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))

        dark = vars_of(':root, :root[data-theme="dark"]')
        light = vars_of(':root[data-theme="light"]')
        self.assertTrue(dark, "no dark variables found")
        self.assertEqual(dark, light,
                         f"theme variable drift: {dark ^ light}")

    def test_no_hardcoded_colours_outside_theme_blocks(self):
        """Every colour in the CSS body must come from a variable."""
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]
        body = css[css.index(':root[data-theme="light"]'):]
        body = body[body.index("}"):]
        leftovers = [m.group(0) for m in
                     re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", body)]
        self.assertFalse(leftovers,
                         f"hardcoded colours outside theme blocks: {leftovers}")

    def test_theme_applied_before_paint(self):
        """The init script must run in <head>, before the body renders."""
        html = self._render()
        head = html[:html.index("</head>")]
        self.assertIn("golive_admin_theme", head)
        self.assertIn('setAttribute("data-theme"', head)
        self.assertIn("prefers-color-scheme", head)

    def test_theme_persisted_and_three_state(self):
        html = self._render()
        self.assertIn('localStorage.setItem(THEME_KEY', html)
        for mode in ("system", "light", "dark"):
            self.assertIn(f'data-theme-set="{mode}"', html, mode)
        self.assertIn('id="theme-switch"', html)


class TestPortalI18n(unittest.TestCase):
    """v0.7.0: the interface chrome is bilingual (en / zh)."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def _dicts(self):
        """Parse the I18N object out of the page into two key sets."""
        html = self._render()
        start = html.index("var I18N = {")
        end = html.index("\n};\n", start)
        blob = html[start:end]
        en_part, zh_part = blob.split("\nzh: {", 1)
        key_re = re.compile(r'^\s{2}"([^"]+)":', re.M)
        return (set(key_re.findall(en_part)),
                set(key_re.findall(zh_part)), html)

    def test_both_locales_present(self):
        html = self._render()
        self.assertIn("var I18N = {", html)
        self.assertIn("\nen: {", html)
        self.assertIn("\nzh: {", html)

    def test_key_sets_are_identical(self):
        en, zh, _ = self._dicts()
        self.assertTrue(en, "no en keys parsed")
        self.assertEqual(en, zh, f"untranslated keys: {sorted(en ^ zh)}")

    def test_every_referenced_key_exists(self):
        en, _zh, html = self._dicts()
        used = set(re.findall(r'data-i18n="([^"]+)"', html))
        used |= set(re.findall(r'data-i18n-ph="([^"]+)"', html))
        used |= set(re.findall(r'\bt\("([^"]+)"', html))
        missing = used - en
        self.assertFalse(missing, f"keys used but not defined: {sorted(missing)}")

    def test_language_switcher_and_persistence(self):
        html = self._render()
        self.assertIn('id="lang-switch"', html)
        self.assertIn('data-lang="en"', html)
        self.assertIn('data-lang="zh"', html)
        self.assertIn('localStorage.setItem(LANG_KEY', html)

    def test_first_visit_follows_navigator_language(self):
        head = self._render()
        head = head[:head.index("</head>")]
        self.assertIn("navigator.language", head)
        self.assertIn("/^zh/i", head)

    def test_no_untranslated_chinese_in_markup(self):
        """All visible chrome goes through the dictionary, not the markup.

        The one exception is the language switcher itself: language names
        are always shown in their own language, never translated.
        """
        html = self._render()
        body = html[html.index("<body>"):html.index("var I18N = {")]
        switcher = re.search(r'<div class="switch" id="lang-switch".*?</div>',
                             body, re.S)
        self.assertIsNotNone(switcher)
        body = body.replace(switcher.group(0), "")
        stray = re.findall(r"[\u4e00-\u9fff]+", body)
        self.assertFalse(stray, f"hardcoded Chinese in markup: {stray}")


class TestAgentGuidance(unittest.TestCase):
    """v0.7.0: empty states hand a ready task description to an AI assistant."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_copy_button_exists_in_both_languages(self):
        html = self._render()
        self.assertIn('id="data-agent-copy"', html)
        self.assertIn('"guide.copyagent": "📋 Copy for your AI assistant"', html)
        self.assertIn('"guide.copyagent": "📋 复制给 AI 助手"', html)

    def test_prompt_has_both_language_branches(self):
        html = self._render()
        self.assertIn("function dataAgentPrompt()", html)
        self.assertIn('if (state.lang === "zh")', html)

    def test_prompt_carries_the_required_elements(self):
        """Tool + goal + real paths + steps + verification + docs URL."""
        html = self._render()
        start = html.index("function dataAgentPrompt()")
        prompt = html[start:html.index("\n}\n", start)]
        # 1. which tool, with a version
        self.assertIn("html-golive", prompt)
        self.assertIn("BOOT.version", prompt)
        # 2. the goal, offering both backends
        self.assertIn("Supabase", prompt)
        self.assertIn('snip("sqlite")', prompt)
        # 3. real paths
        self.assertIn("GOLIVE_HOME", prompt)
        self.assertIn("p.home", prompt)
        self.assertIn("p.config", prompt)
        # 4. concrete steps incl. env-var handling for the key
        self.assertIn('snip("yaml")', prompt)
        self.assertIn('snip("env")', prompt)
        # 5. verification
        self.assertIn('snip("verify")', prompt)
        self.assertIn("golive doctor", prompt)
        self.assertIn("golive serve", prompt)
        # 6. documentation link
        self.assertIn("BOOT.docs_url", prompt)

    def test_snippets_exist_for_both_languages(self):
        """The embedded yaml/shell comments are localised, not English-only."""
        html = self._render()
        start = html.index("var DATA_SNIPPETS = {")
        blob = html[start:html.index("\n};\n", start)]
        en_part, zh_part = blob.split("\nzh: {", 1)
        for key in ("sqlite:", "yaml:", "env:", "verify:"):
            self.assertIn(key, en_part, f"en {key}")
            self.assertIn(key, zh_part, f"zh {key}")
        # the Chinese pack must actually contain Chinese comments
        self.assertRegex(zh_part, r"#\s*[\u4e00-\u9fff]")
        self.assertNotRegex(en_part, r"[\u4e00-\u9fff]")

    def test_prompt_uses_generic_assistant_wording(self):
        """No vendor names — 'your AI assistant' must stay product-neutral."""
        html = self._render()
        start = html.index("var I18N = {")
        blob = html[start:html.index("\n};\n", start)]
        self.assertIn("your AI assistant", blob)
        self.assertIn("AI 助手", blob)

    def test_paths_are_real_not_placeholders(self):
        from golive.core.paths import get_home
        from golive.server.admin_ui import render_admin_page
        html = render_admin_page()
        m = re.search(r"window\.GOLIVE_BOOT = (.*?);</script>", html)
        boot = json.loads(m.group(1).replace("<\\/", "</")
                          .replace("<\\!--", "<!--"))
        self.assertEqual(boot["home"], str(get_home()))
        self.assertTrue(boot["config_path"].endswith("golive.yaml"))
        self.assertTrue(boot["docs_url"].startswith("https://github.com/"))

    def test_fallback_note_when_paths_unresolved(self):
        html = self._render()
        self.assertIn('"guide.pathnote"', html)
        self.assertIn("golive doctor", html)

    def test_env_var_guidance_and_code_copy_buttons(self):
        html = self._render()
        self.assertIn("export GOLIVE_SUPABASE_SERVICE_KEY", html)
        self.assertIn("cb-copy", html)
        self.assertIn("function wireCopyButtons(", html)
        self.assertIn('"guide.docs"', html)

    def test_sidebar_has_a_brand_separator(self):
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]
        self.assertRegex(css, r"#logo\{[^}]*border-bottom")

    def test_secrets_are_never_pre_filled(self):
        """The snippet tells you to use an env var, it doesn't invent a key."""
        html = self._render()
        self.assertIn("service_key_env: GOLIVE_SUPABASE_SERVICE_KEY", html)
        self.assertIn("your-service-role-key", html)


class TestPermissionsView(unittest.TestCase):
    """v0.7.0: superadmin-only permissions page over /api/admin/permissions."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_dom_ids_present(self):
        html = self._render()
        for dom_id in ("nav-perms", "view-perms", "perms-main",
                       "perms-unavailable", "perm-mine", "perm-mine-body",
                       "perm-admins", "perm-admin-rows", "perm-admin-email",
                       "perm-admin-add", "perm-sites", "perm-site-rows",
                       "perm-site-q", "perm-bulk", "perm-bulk-email",
                       "perm-bulk-slugs", "perm-bulk-grant",
                       "perm-bulk-revoke"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_nav_is_superadmin_only(self):
        html = self._render()
        m = re.search(r'<div class="([^"]*)" data-view="perms"', html)
        self.assertIsNotNone(m)
        self.assertIn("hidden", m.group(1))
        js = html[html.rindex("<script>"):]
        gate = js[js.index("if (who.superadmin){"):]
        self.assertIn('$("nav-perms").classList.remove("hidden")', gate[:400])

    def test_api_endpoints_wired(self):
        html = self._render()
        self.assertIn('api("GET", "/api/admin/permissions")', html)
        self.assertIn('api("POST", "/api/admin/permissions/admins"', html)
        self.assertIn('api("DELETE", "/api/admin/permissions/admins"', html)
        self.assertIn('api("POST", "/api/admin/permissions/bulk"', html)

    def test_bulk_payload_shape(self):
        """Contract with the backend: {email, role, slugs, action}."""
        html = self._render()
        start = html.index('api("POST", "/api/admin/permissions/bulk"')
        call = html[start:start + 220]
        for field in ("email:", "role: \"maintainer\"", "slugs:", "action:"):
            self.assertIn(field, call, field)

    def test_builtin_admins_are_locked(self):
        html = self._render()
        self.assertIn("builtin_admins", html)
        self.assertIn("managed_admins", html)
        self.assertIn('"perms.admins.locktip"', html)
        self.assertIn('class="lock"', html)

    def test_lock_icon_needs_no_emoji_font(self):
        """The portal bundles no fonts — an emoji glyph would be tofu."""
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]
        self.assertIn(".lock{", css)
        self.assertIn(".lock::before", css)
        self.assertNotIn("\\u{1F512}", html)
        self.assertNotIn("\U0001F512", html)

    def test_dangerous_actions_confirm(self):
        html = self._render()
        self.assertIn('window.confirm(t("confirm.deladmin"', html)
        self.assertIn('window.confirm(t("confirm.revoke"', html)

    def test_unavailable_state_for_older_servers(self):
        html = self._render()
        self.assertIn("e.status === 404 || e.status === 501", html)
        self.assertIn('"perms.unavailable"', html)

    def test_site_acl_rendered_with_escaping(self):
        html = self._render()
        self.assertIn("sites_acl", html)
        self.assertIn("esc(s.owner", html)
        self.assertIn("esc(m)", html)


class TestPortalScriptSyntax(unittest.TestCase):
    """Every inline <script> in the portal must be valid JavaScript."""

    def setUp(self):
        _fresh_home()

    def test_node_check(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        from golive.server.admin_ui import render_admin_page
        html = render_admin_page()
        blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertGreaterEqual(len(blocks), 2)
        for i, body in enumerate(blocks):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as fh:
                fh.write(body)
                tmp = fh.name
            try:
                p = subprocess.run([node, "--check", tmp],
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0,
                                 f"script #{i} syntax error: {p.stderr}")
            finally:
                os.unlink(tmp)


class TestAdminPageHttp(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def _start(self):
        from golive.config import reset_config
        reset_config()
        from golive.server.app import make_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = make_server(port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.25)
        self.addCleanup(srv.shutdown)
        return port

    def test_admin_page_loopback_200(self):
        port = self._start()
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/admin", timeout=5)
        self.assertEqual(r.status, 200)
        body = r.read().decode("utf-8")
        self.assertIn('id="view-sites"', body)
        self.assertIn("GOLIVE_BOOT", body)
        self.assertIn("text/html", r.headers.get("Content-Type", ""))

    def test_admin_page_remote_denied_without_auth(self):
        port = self._start()
        lan_ip = lan_ip_or_none()
        if lan_ip is None:
            self.skipTest("no routable non-loopback interface available")
        # rebind on all interfaces for this case
        from golive.server.app import make_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port2 = s.getsockname()[1]
        s.close()
        srv = make_server(host="0.0.0.0", port=port2)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.25)
        self.addCleanup(srv.shutdown)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(f"http://{lan_ip}:{port2}/admin", timeout=5)
        self.assertEqual(cm.exception.code, 401)

    def test_admin_page_served_when_token_auth_on(self):
        """With token auth the shell is served (API still enforces auth)."""
        os.environ["GOLIVE_TOKEN"] = "ui-secret"
        try:
            port = self._start()
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/admin",
                                       timeout=5)
            self.assertEqual(r.status, 200)
            self.assertIn("login-gate", r.read().decode("utf-8"))
            # but the API refuses without the token
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/admin/sites", timeout=5)
            self.assertEqual(cm.exception.code, 401)
        finally:
            os.environ.pop("GOLIVE_TOKEN", None)

    def test_serve_banner_mentions_admin(self):
        """The startup banner prints the portal URL (spec M5-D)."""
        import inspect
        from golive.server import app as app_mod
        src = inspect.getsource(app_mod.serve)
        self.assertIn("/admin", src)


if __name__ == "__main__":
    unittest.main()
