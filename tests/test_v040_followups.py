"""Tests for v0.4.0 M3-WARN follow-ups: editor image button + cookie persist."""
import os
import tempfile
import unittest


class TestEditorImageButton(unittest.TestCase):
    def test_toolbar_has_image_button_and_handlers(self):
        from golive.inject import editor
        js = editor.generate_js("demo", site_name="Demo", api_base="")
        for token in ("__golive_editor_img__", "__golive_editor_file__",
                      "_pickImage", "_onFilePicked", "_insertImgNode",
                      "_fileToDataURL"):
            self.assertIn(token, js, f"missing {token}")

    def test_upload_uses_raw_body_with_filename_header(self):
        from golive.inject import editor
        js = editor.generate_js("demo")
        self.assertIn("X-Filename", js)
        self.assertIn("/upload", js)
        # no FormData/multipart — server expects raw body
        self.assertNotIn("FormData", js)

    def test_501_falls_back_to_inline(self):
        from golive.inject import editor
        js = editor.generate_js("demo")
        # graceful inline path when no uploader configured
        self.assertIn("501", js)
        self.assertIn("readAsDataURL", js)

    def test_new_ids_excluded_from_editable_collection(self):
        from golive.inject import editor
        js = editor.generate_js("demo")
        # new UI ids must be in EDITOR_IDS so they aren't made editable
        idx = js.index("EDITOR_IDS")
        block = js[idx:idx + 400]
        for _id in ("__golive_editor_img__", "__golive_editor_file__",
                    "__golive_editor_save__", "__golive_editor_cancel__"):
            self.assertIn(_id, block)

    def test_js_escaped_config(self):
        # confirms the shared escape util is still used (no raw interpolation)
        from golive.inject import editor, _escape
        self.assertIs(editor._json_for_script, _escape.json_for_script)


class TestCookieSecretPersistence(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["GOLIVE_HOME"] = self.home
        os.environ.pop("GOLIVE_COOKIE_SECRET", None)
        # reset cached home
        import golive.core.paths as p
        p._resolved_home = None

    def test_persist_and_reload(self):
        from golive.backends.auth.oauth import _load_or_create_cookie_secret
        s1 = _load_or_create_cookie_secret()
        s2 = _load_or_create_cookie_secret()
        self.assertEqual(s1, s2)
        self.assertEqual(len(s1), 64)

    def test_file_mode_0600(self):
        from golive.backends.auth.oauth import _load_or_create_cookie_secret
        from golive.core.paths import get_home
        _load_or_create_cookie_secret()
        f = get_home() / ".cookie_secret"
        self.assertTrue(f.exists())
        self.assertEqual(oct(f.stat().st_mode)[-3:], "600")

    def test_env_wins_over_file(self):
        os.environ["GOLIVE_COOKIE_SECRET"] = "env-secret-value"
        from golive.backends.auth.oauth import OIDCAuth
        a = OIDCAuth(issuer="https://idp.example.com", client_id="x")
        self.assertEqual(a._cookie_secret, b"env-secret-value")
        os.environ.pop("GOLIVE_COOKIE_SECRET", None)


if __name__ == "__main__":
    unittest.main()
