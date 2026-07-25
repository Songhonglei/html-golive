"""Tests for OIDC provider presets (v0.4.0)."""
import os
import tempfile
import unittest

from golive.backends.auth.presets import resolve_preset, SUPPORTED


def _write_cfg(body: str) -> str:
    p = os.path.join(tempfile.mkdtemp(), "golive.yaml")
    with open(p, "w") as f:
        f.write(body)
    return p


class TestResolvePreset(unittest.TestCase):
    def test_google(self):
        out = resolve_preset("google")
        self.assertEqual(out["issuer"], "https://accounts.google.com")
        self.assertIn("openid", out["scopes"])

    def test_case_insensitive(self):
        self.assertEqual(resolve_preset("GOOGLE")["issuer"],
                         resolve_preset("google")["issuer"])

    def test_auth0_needs_domain(self):
        with self.assertRaises(ValueError):
            resolve_preset("auth0")
        out = resolve_preset("auth0", domain="acme.us.auth0.com")
        self.assertEqual(out["issuer"], "https://acme.us.auth0.com")

    def test_okta_needs_domain(self):
        out = resolve_preset("okta", domain="acme.okta.com")
        self.assertEqual(out["issuer"], "https://acme.okta.com")

    def test_azure_needs_tenant(self):
        with self.assertRaises(ValueError):
            resolve_preset("azure")
        out = resolve_preset("azure", tenant="common")
        self.assertEqual(out["issuer"],
                         "https://login.microsoftonline.com/common/v2.0")

    def test_keycloak_no_issuer_template(self):
        # keycloak preset only supplies scopes; issuer stays user-provided
        out = resolve_preset("keycloak")
        self.assertNotIn("issuer", out)
        self.assertIn("openid", out["scopes"])

    def test_unknown_preset(self):
        with self.assertRaises(ValueError) as cm:
            resolve_preset("myspace")
        self.assertIn("myspace", str(cm.exception))
        self.assertIn("supported", str(cm.exception))

    def test_supported_list(self):
        for name in ("google", "auth0", "okta", "azure", "keycloak", "authentik"):
            self.assertIn(name, SUPPORTED)

    def test_no_secrets_in_presets(self):
        from golive.backends.auth import presets
        blob = repr(presets.PRESETS).lower()
        for bad in ("secret", "password", "client_secret", "api_key"):
            self.assertNotIn(bad, blob)


class TestPresetConfigIntegration(unittest.TestCase):
    def setUp(self):
        os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()

    def test_config_expands_google(self):
        from golive.config import load_config
        c = load_config(_write_cfg(
            "auth:\n  provider: oidc\n  oidc:\n"
            "    preset: google\n    client_id: abc.apps.googleusercontent.com\n"))
        self.assertEqual(c.auth.oidc_issuer, "https://accounts.google.com")
        self.assertEqual(c.auth.oidc_scopes, "openid email profile")

    def test_explicit_issuer_overrides_preset(self):
        from golive.config import load_config
        c = load_config(_write_cfg(
            "auth:\n  oidc:\n    preset: google\n"
            "    issuer: https://custom.idp.com\n    client_id: x\n"))
        self.assertEqual(c.auth.oidc_issuer, "https://custom.idp.com")

    def test_unknown_preset_raises_configerror(self):
        from golive.config import load_config, ConfigError
        with self.assertRaises(ConfigError):
            load_config(_write_cfg(
                "auth:\n  oidc:\n    preset: nope\n    client_id: x\n"))


if __name__ == "__main__":
    unittest.main()
