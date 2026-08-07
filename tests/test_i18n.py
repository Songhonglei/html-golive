"""Tests for golive.i18n — language detection, fallback, and interpolation."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from golive.i18n import t, get_language, set_language, _normalize


class TestLanguageDetection(unittest.TestCase):
    """Language detection priority: GOLIVE_LANG > locale > English."""

    def setUp(self):
        # Reset state before each test
        set_language("en")

    def tearDown(self):
        set_language("en")

    def test_default_is_english(self):
        """When no env vars and no locale info, default is English."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("locale.getlocale", return_value=(None, None)):
                set_language("")  # reset override
                import golive.i18n as mod
                mod._cached_lang = None
                mod._override = None
                self.assertEqual(get_language(), "en")

    def test_golive_lang_zh(self):
        """GOLIVE_LANG=zh selects Chinese."""
        with mock.patch.dict(os.environ, {"GOLIVE_LANG": "zh"}):
            set_language("")
            import golive.i18n as mod
            mod._cached_lang = None
            mod._override = None
            self.assertEqual(get_language(), "zh")

    def test_golive_lang_zh_cn(self):
        """GOLIVE_LANG=zh_CN selects Chinese."""
        self.assertEqual(_normalize("zh_CN"), "zh")

    def test_golive_lang_zh_hans(self):
        """GOLIVE_LANG=zh-Hans selects Chinese."""
        self.assertEqual(_normalize("zh-Hans"), "zh")

    def test_golive_lang_en(self):
        """GOLIVE_LANG=en selects English."""
        self.assertEqual(_normalize("en"), "en")
        self.assertEqual(_normalize("en_US"), "en")
        self.assertEqual(_normalize("en_GB.UTF-8"), "en")

    def test_golive_lang_overrides_locale(self):
        """GOLIVE_LANG takes priority over system locale."""
        with mock.patch.dict(os.environ, {"GOLIVE_LANG": "en", "LANG": "zh_CN.UTF-8"}):
            set_language("")
            import golive.i18n as mod
            mod._cached_lang = None
            mod._override = None
            self.assertEqual(get_language(), "en")

    def test_unknown_lang_falls_back_to_english(self):
        """Unrecognised GOLIVE_LANG value falls back to English."""
        self.assertEqual(_normalize("klingon"), "en")
        self.assertEqual(_normalize("fr"), "en")
        self.assertEqual(_normalize("ja"), "en")

    def test_c_and_posix_treated_as_english(self):
        """C and POSIX locales are treated as English."""
        self.assertEqual(_normalize("C"), "en")
        self.assertEqual(_normalize("POSIX"), "en")

    def test_set_language_override(self):
        """set_language() overrides everything."""
        with mock.patch.dict(os.environ, {"GOLIVE_LANG": "zh"}):
            set_language("en")
            self.assertEqual(get_language(), "en")
            set_language("zh")
            self.assertEqual(get_language(), "zh")


class TestFallbackChain(unittest.TestCase):
    """Missing key fallback: zh → en → key itself."""

    def setUp(self):
        set_language("en")

    def tearDown(self):
        set_language("en")

    def test_missing_key_in_zh_falls_back_to_en(self):
        """When zh table lacks a key, English value is returned."""
        from golive.locales import en, zh
        # Temporarily remove a key from zh
        original = zh.TRANSLATIONS.pop("publish.path_not_found", None)
        try:
            set_language("zh")
            result = t("publish.path_not_found", path="/test")
            # Should fall back to English
            self.assertEqual(result, en.TRANSLATIONS["publish.path_not_found"].format(path="/test"))
        finally:
            if original is not None:
                zh.TRANSLATIONS["publish.path_not_found"] = original

    def test_missing_key_in_en_returns_key(self):
        """When both zh and en lack a key, the key itself is returned."""
        set_language("zh")
        result = t("totally.nonexistent.key")
        self.assertEqual(result, "totally.nonexistent.key")

        set_language("en")
        result = t("totally.nonexistent.key")
        self.assertEqual(result, "totally.nonexistent.key")

    def test_missing_key_with_kwargs_returns_key(self):
        """Missing key with interpolation args returns just the key."""
        set_language("en")
        result = t("nonexistent", name="test")
        self.assertEqual(result, "nonexistent")


class TestInterpolation(unittest.TestCase):
    """{name} placeholder interpolation works correctly."""

    def setUp(self):
        set_language("en")

    def tearDown(self):
        set_language("en")

    def test_basic_interpolation(self):
        """Single placeholder is replaced."""
        result = t("publish.path_not_found", path="/tmp/missing")
        self.assertIn("/tmp/missing", result)
        self.assertNotIn("{path}", result)

    def test_multiple_placeholders(self):
        """Multiple placeholders are all replaced."""
        result = t("serve.start.started", pid=12345)
        self.assertIn("12345", result)
        self.assertNotIn("{pid}", result)

    def test_no_placeholders_no_kwargs(self):
        """Key with no placeholders works without kwargs."""
        result = t("list.empty")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_format_error_does_not_crash(self):
        """A formatting error falls back to the raw string, not an exception."""
        # Create a key with a bad placeholder
        from golive.locales import en
        original = en.TRANSLATIONS.get("test.bad")
        en.TRANSLATIONS["test.bad"] = "Hello {missing_key}"
        try:
            result = t("test.bad", name="world")
            # Should not crash; returns the raw string
            self.assertEqual(result, "Hello {missing_key}")
        finally:
            if original is not None:
                en.TRANSLATIONS["test.bad"] = original
            else:
                en.TRANSLATIONS.pop("test.bad", None)


class TestTranslationKeysMatch(unittest.TestCase):
    """en.py and zh.py must have identical key sets."""

    def test_key_sets_are_identical(self):
        """Every key in en must be in zh and vice versa."""
        from golive.locales import en, zh
        en_keys = set(en.TRANSLATIONS)
        zh_keys = set(zh.TRANSLATIONS)
        only_en = en_keys - zh_keys
        only_zh = zh_keys - en_keys
        self.assertFalse(only_en,
                         f"Keys only in en (missing from zh): {sorted(only_en)}")
        self.assertFalse(only_zh,
                         f"Keys only in zh (missing from en): {sorted(only_zh)}")

    def test_all_keys_are_strings(self):
        """All translation values must be strings."""
        from golive.locales import en, zh
        for key, val in en.TRANSLATIONS.items():
            self.assertIsInstance(val, str, f"en.{key} is not a string")
        for key, val in zh.TRANSLATIONS.items():
            self.assertIsInstance(val, str, f"zh.{key} is not a string")

    def test_no_empty_values(self):
        """No translation value should be empty."""
        from golive.locales import en, zh
        for key, val in en.TRANSLATIONS.items():
            self.assertTrue(val.strip(), f"en.{key} is empty")
        for key, val in zh.TRANSLATIONS.items():
            self.assertTrue(val.strip(), f"zh.{key} is empty")


if __name__ == "__main__":
    unittest.main()
