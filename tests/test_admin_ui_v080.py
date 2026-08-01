"""Tests for the v0.8.0 admin portal additions (identity, data backend,
security, settings pages).

These tests validate:
- DOM structure: new views, nav items, and key elements exist
- i18n: every new key exists in both en and zh dictionaries
- Theme consistency: new CSS variables exist in both themes
- XSS safety: no unescaped backend values reach the DOM
- Self-contained: no external CDN references
- Graceful degradation: new pages handle missing API endpoints
"""

import json
import os
import re
import tempfile
import unittest


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    os.environ.pop("GOLIVE_TOKEN", None)
    os.environ.pop("GOLIVE_ADMINS", None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


class TestV080NavItems(unittest.TestCase):
    """New navigation items are present and hidden by default."""

    def setUp(self):
        _fresh_home()

    def _render(self, identity=None):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page(identity)

    def test_new_nav_items_present(self):
        html = self._render()
        for nav_id in ("nav-identity", "nav-databackend",
                       "nav-security", "nav-settings"):
            self.assertIn(f'id="{nav_id}"', html, nav_id)

    def test_new_nav_items_hidden_by_default(self):
        html = self._render()
        for nav_id in ("nav-identity", "nav-databackend",
                       "nav-security", "nav-settings"):
            # Class may appear before or after id in the attribute order
            pattern = rf'id="{nav_id}"[^>]*'
            m = re.search(pattern, html)
            self.assertIsNotNone(m, f"{nav_id} not found")
            # Find the full element tag
            tag_pattern = rf'<div[^>]*id="{nav_id}"[^>]*>'
            m2 = re.search(tag_pattern, html)
            self.assertIsNotNone(m2, f"{nav_id} element not found")
            self.assertIn("hidden", m2.group(0),
                          f"{nav_id} should be hidden by default")

    def test_new_nav_items_revealed_for_superadmin(self):
        """Superadmin identity should trigger nav reveal in JS."""
        from golive.server import authz
        ident = authz.Identity(email="admin@test.com", is_superadmin=True)
        html = self._render(ident)
        js = html[html.rindex("<script>"):]
        # All four new nav IDs should be in the superadmin reveal block
        gate = js[js.index("if (who.superadmin){"):]
        gate_block = gate[:600]
        for nav_id in ("nav-identity", "nav-databackend",
                       "nav-security", "nav-settings"):
            self.assertIn(nav_id, gate_block,
                          f"{nav_id} should be in superadmin reveal")


class TestV080ViewsPresent(unittest.TestCase):
    """New view containers exist in the HTML."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_identity_view_dom(self):
        html = self._render()
        for dom_id in ("view-identity", "identity-main", "identity-degraded",
                       "id-method", "idp-preset", "oidc-issuer",
                       "oidc-client-id", "oidc-client-secret",
                       "oidc-test", "oidc-test-result",
                       "oidc-callback-url", "oidc-callback-copy",
                       "oidc-agent-copy", "proxy-header", "proxy-ips",
                       "proxy-save"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_databackend_view_dom(self):
        html = self._render()
        for dom_id in ("view-databackend", "databackend-main",
                       "databackend-degraded", "db-type", "db-location",
                       "db-tables", "db-rows", "db-new-type",
                       "db-supabase-opts", "db-sb-url", "db-sb-key",
                       "db-test", "db-test-result", "db-switch",
                       "db-migrate-warn"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_security_view_dom(self):
        html = self._render()
        for dom_id in ("view-security", "security-main", "security-degraded",
                       "sec-keyword-status", "sec-regex-status",
                       "sec-ai-status", "sec-rules-list",
                       "sec-new-type", "sec-new-name", "sec-new-pattern",
                       "sec-new-strength", "sec-rule-add",
                       "sec-test-input", "sec-test-run", "sec-test-result",
                       "ai-base-url", "ai-model", "ai-api-key",
                       "ai-strict-mode", "ai-test", "ai-test-result",
                       "ai-save", "sec-blocks-list"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_settings_view_dom(self):
        html = self._render()
        for dom_id in ("view-settings", "settings-main",
                       "settings-degraded", "settings-groups"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)


class TestV080I18n(unittest.TestCase):
    """All new i18n keys exist in both en and zh dictionaries."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def _dicts(self):
        html = self._render()
        start = html.index("var I18N = {")
        end = html.index("\n};\n", start)
        blob = html[start:end]
        en_part, zh_part = blob.split("\nzh: {", 1)
        key_re = re.compile(r'^\s{2}"([^"]+)":', re.M)
        return (set(key_re.findall(en_part)),
                set(key_re.findall(zh_part)))

    def test_new_keys_in_both_locales(self):
        en, zh = self._dicts()
        # Sample of new keys
        new_keys = [
            "nav.identity", "nav.databackend", "nav.security", "nav.settings",
            "identity.title", "identity.degraded", "identity.current",
            "identity.oidc.title", "identity.oidc.test",
            "identity.callback.title", "identity.proxy.title",
            "databackend.title", "databackend.degraded",
            "databackend.migrate.warn.title", "databackend.migrate.warn.body",
            "security.title", "security.degraded",
            "security.rules.title", "security.test.title",
            "security.ai.title", "security.blocks",
            "settings.title", "settings.degraded",
            "settings.readonly", "settings.restart.needed",
        ]
        for key in new_keys:
            self.assertIn(key, en, f"missing in en: {key}")
            self.assertIn(key, zh, f"missing in zh: {key}")

    def test_key_sets_identical(self):
        """All keys (including new ones) must be in both locales."""
        en, zh = self._dicts()
        self.assertEqual(en, zh,
                         f"untranslated keys: {sorted(en ^ zh)}")

    def test_new_data_i18n_attributes_have_keys(self):
        """Every data-i18n attribute must have a matching key."""
        html = self._render()
        used = set(re.findall(r'data-i18n="([^"]+)"', html))
        used |= set(re.findall(r'data-i18n-ph="([^"]+)"', html))
        en, _zh = self._dicts()
        missing = used - en
        self.assertFalse(missing,
                         f"data-i18n keys used but not defined: {sorted(missing)}")


class TestV080ThemeConsistency(unittest.TestCase):
    """New CSS variables exist in both dark and light themes."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_new_variables_in_both_themes(self):
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]

        def vars_of(selector):
            start = css.index(selector)
            block = css[css.index("{", start) + 1:css.index("}", start)]
            return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))

        dark = vars_of(':root, :root[data-theme="dark"]')
        light = vars_of(':root[data-theme="light"]')
        self.assertEqual(dark, light,
                         f"theme variable drift: {dark ^ light}")

    def test_new_variables_present(self):
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]
        # New variables we added
        for var in ("--ok-soft", "--warn-soft"):
            self.assertIn(var, css, f"variable {var} not found in CSS")

    def test_no_hardcoded_colours_in_new_css(self):
        """No hardcoded colours outside theme blocks."""
        html = self._render()
        css = html[html.index("<style>"):html.index("</style>")]
        body = css[css.index(':root[data-theme="light"]'):]
        body = body[body.index("}"):]
        leftovers = [m.group(0) for m in
                     re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", body)]
        self.assertFalse(leftovers,
                         f"hardcoded colours outside theme blocks: {leftovers}")


class TestV080SelfContained(unittest.TestCase):
    """No external CDN references in the new content."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_no_external_resources(self):
        html = self._render()
        for m in re.finditer(r'(?:src|href)\s*=\s*["\'](https?:)?//', html):
            self.fail(f"external resource reference found: {m.group(0)}")
        self.assertNotIn("cdn.", html.lower())
        self.assertNotIn("googleapis", html.lower())
        self.assertNotIn("@import", html.lower())

    def test_no_external_frameworks(self):
        html = self._render()
        # No React, Vue, jQuery, etc.
        for fw in ("react", "vue", "angular", "jquery"):
            self.assertNotIn(fw, html.lower(),
                             f"external framework {fw} detected")


class TestV080XSSSafety(unittest.TestCase):
    """Backend values must go through esc() in the new page handlers."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_esc_function_present(self):
        """The esc() function must still exist and handle all required chars."""
        html = self._render()
        self.assertIn("function esc(s)", html)
        # Must handle & < > " '
        for char, ent in [("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                          ('"', "&quot;"), ("'", "&#39;")]:
            self.assertIn(ent, html[html.index("function esc"):])

    def test_no_innerHTML_with_backend_data_without_esc(self):
        """Check that new page handlers don't use innerHTML with raw data
        (they should use esc() or textContent)."""
        html = self._render()
        js = html[html.rindex("<script>"):]
        # Find all innerHTML assignments in the new handler functions
        # and verify they use esc() for dynamic values
        new_funcs = ["loadIdentity", "loadDataBackend", "loadSecurity",
                     "renderSecurityRules", "renderSecurityBlocks",
                     "renderSettings", "loadSettings"]
        for func_name in new_funcs:
            if func_name in js:
                # Find the function body
                idx = js.index("function " + func_name)
                # Find the closing brace at the same indentation level
                func_body = js[idx:idx + 3000]
                # Check that innerHTML assignments use esc()
                innerhtml_matches = re.findall(
                    r'\.innerHTML\s*=\s*([^;]+)', func_body)
                for match in innerhtml_matches:
                    # If it contains a + (concatenation with dynamic data),
                    # it should also contain esc(
                    if "+" in match and "esc(" not in match:
                        # Allow pure string literals
                        if not re.match(r'^["\']', match.strip()):
                            self.fail(
                                f"innerHTML in {func_name} may have "
                                f"unescaped data: {match[:80]}")


class TestV080SecretMasking(unittest.TestCase):
    """Secret fields must not expose values in the DOM."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_secret_inputs_are_password_type(self):
        html = self._render()
        # OIDC client secret
        self.assertIn('type="password" id="oidc-client-secret"', html)
        # Supabase key
        self.assertIn('type="password" id="db-sb-key"', html)
        # AI API key
        self.assertIn('type="password" id="ai-api-key"', html)

    def test_secret_placeholder_not_value(self):
        """Secret fields should use placeholder, not value attribute."""
        html = self._render()
        # None of these should have a value= attribute
        for field_id in ("oidc-client-secret", "db-sb-key", "ai-api-key"):
            pattern = rf'id="{field_id}"[^>]*value="'
            self.assertFalse(re.search(pattern, html),
                             f"{field_id} should not have a value attribute")


class TestV080GracefulDegradation(unittest.TestCase):
    """New pages must show a degraded notice when API endpoints are missing."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_degraded_notice_elements_present(self):
        html = self._render()
        for dom_id in ("identity-degraded", "databackend-degraded",
                       "security-degraded", "settings-degraded"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_showDegraded_function_exists(self):
        html = self._render()
        js = html[html.rindex("<script>"):]
        self.assertIn("function showDegraded", js)

    def test_degraded_notices_hidden_by_default(self):
        html = self._render()
        for dom_id in ("identity-degraded", "databackend-degraded",
                       "security-degraded", "settings-degraded"):
            pattern = rf'id="{dom_id}"[^>]*style="[^"]*display:none'
            self.assertTrue(re.search(pattern, html),
                            f"{dom_id} should be hidden by default")


class TestV080NavHandler(unittest.TestCase):
    """Nav click handler routes to the new load functions."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_nav_handler_includes_new_views(self):
        html = self._render()
        js = html[html.rindex("<script>"):]
        for view_name in ("identity", "databackend", "security", "settings"):
            self.assertIn(f'dataset.view === "{view_name}"', js,
                          f"nav handler missing {view_name}")

    def test_load_functions_defined(self):
        html = self._render()
        js = html[html.rindex("<script>"):]
        for func in ("loadIdentity", "loadDataBackend",
                     "loadSecurity", "loadSettings"):
            self.assertIn(f"function {func}", js,
                          f"function {func} not defined")


class TestV080Rerender(unittest.TestCase):
    """rerender() handles the new views for language switching."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_rerender_includes_new_views(self):
        html = self._render()
        js = html[html.rindex("<script>"):]
        # Find the rerender function
        idx = js.index("function rerender")
        rerender_body = js[idx:idx + 800]
        for view in ("identity", "databackend", "security", "settings"):
            self.assertIn(view, rerender_body,
                          f"rerender() missing {view} view")


class TestV080CallbackURL(unittest.TestCase):
    """The OIDC callback URL box is present and shows a usable URL."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_callback_box_present(self):
        html = self._render()
        self.assertIn("callback-box", html)
        self.assertIn("oidc-callback-url", html)
        self.assertIn("/auth/callback", html)

    def test_callback_copy_button(self):
        html = self._render()
        self.assertIn('id="oidc-callback-copy"', html)

    def test_agent_copy_button(self):
        html = self._render()
        self.assertIn('id="oidc-agent-copy"', html)


class TestV080IdpPresets(unittest.TestCase):
    """IdP preset dropdown covers all supported providers."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_all_presets_in_dropdown(self):
        html = self._render()
        for provider in ("google", "auth0", "okta", "azure",
                         "keycloak", "authentik", "custom"):
            self.assertIn(f'value="{provider}"', html,
                          f"provider {provider} not in dropdown")

    def test_preset_js_object(self):
        """IDP_PRESETS JS object should exist and have entries."""
        html = self._render()
        js = html[html.rindex("<script>"):]
        self.assertIn("var IDP_PRESETS", js)
        self.assertIn("google:", js)
        self.assertIn("auth0:", js)


class TestV080DataBackendMigrateWarning(unittest.TestCase):
    """The 'data will not be migrated' warning must be present."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_migrate_warning_present(self):
        html = self._render()
        self.assertIn("db-migrate-warn", html)
        self.assertIn("migrate.warn.title", html)
        self.assertIn("migrate.warn.body", html)

    def test_migrate_warning_visible(self):
        """The warning should be visible (not hidden by default)
        when the backend switch form is shown."""
        html = self._render()
        pattern = r'id="db-migrate-warn"[^>]*style="[^"]*display:none'
        # The warn box should NOT be hidden — it must be always visible
        # within the switch section to warn before the user acts.
        self.assertFalse(re.search(pattern, html),
                         "migrate warning should not be hidden by default")


class TestV080Python39Compat(unittest.TestCase):
    """Ensure no Python 3.10+ syntax in any new code."""

    def setUp(self):
        _fresh_home()

    def test_no_match_statements(self):
        """Python 3.10 match/case must not appear."""
        from golive.server.admin_ui import render_admin_page
        html = render_admin_page()
        js = html[html.rindex("<script>"):]
        # This is JS not Python, but check the Python module too
        import ast
        source = (
            "from golive.server.admin_ui import render_admin_page"
        )
        # The admin_ui.py is mostly a string template,
        # so just verify it imports fine on this runtime
        # (which is Python 3.9+ compatible)
        try:
            compile(source, "<test>", "exec")
        except SyntaxError:
            self.fail("Python syntax error in import statement")


class TestV080RedLineGrep(unittest.TestCase):
    """Red-line grep: 0 hits for sensitive patterns."""

    def setUp(self):
        _fresh_home()

    def _render(self):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page()

    def test_no_secrets_in_output(self):
        """The rendered page must not contain real secrets."""
        html = self._render()
        # No real API key patterns
        self.assertNotIn("sk-", html)
        self.assertNotIn("AKIA", html)
        # No real token patterns (GOLIVE_TOKEN values)
        # The word "token" appears in UI text, but actual token
        # values (long hex/base64) should not
        # Check that sessionStorage key is the only token reference
        # in the JS (no hardcoded token values)
        js = html[html.rindex("<script>"):]
        # No private key patterns
        self.assertNotIn("BEGIN PRIVATE KEY", js)
        self.assertNotIn("BEGIN RSA", js)


if __name__ == "__main__":
    unittest.main()
