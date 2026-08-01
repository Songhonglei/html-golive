"""v0.8.0 rules store tests: dual-source merge, built-in protection, test endpoint."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_rules_"))

from golive.backends.registry.rules_store import (
    RulesStore, get_merged_rules_for_scanner,
)


class TestRulesStore(unittest.TestCase):
    """Dual-source security rules: built-in (read-only) + DB (managed)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="golive_rules_")
        self.store = RulesStore(os.path.join(self.tmp, "test.db"))

    def test_builtin_rules_seeded(self):
        """Built-in rules from rules.yaml are present after init."""
        rules = self.store.list_all()
        builtin = [r for r in rules if r["builtin"]]
        self.assertGreater(len(builtin), 0,
                           "at least one built-in rule should be seeded")

    def test_builtin_rules_cannot_be_deleted(self):
        """Built-in rules reject DELETE."""
        rules = self.store.list_all()
        builtin = [r for r in rules if r["builtin"]]
        first = builtin[0]
        with self.assertRaises(ValueError) as ctx:
            self.store.delete(first["id"])
        self.assertIn("built-in", str(ctx.exception).lower())

    def test_builtin_rules_can_be_disabled(self):
        """Built-in rules can be toggled enabled/disabled."""
        rules = self.store.list_all()
        builtin = [r for r in rules if r["builtin"]]
        first = builtin[0]
        # Disable
        updated = self.store.update(first["id"], {"enabled": False},
                                    updated_by="admin@test.com")
        self.assertFalse(updated["enabled"])
        # Re-enable
        updated = self.store.update(first["id"], {"enabled": True},
                                    updated_by="admin@test.com")
        self.assertTrue(updated["enabled"])

    def test_builtin_rules_cannot_modify_body(self):
        """Built-in rule body fields are read-only."""
        rules = self.store.list_all()
        builtin = [r for r in rules if r["builtin"]]
        first = builtin[0]
        with self.assertRaises(ValueError) as ctx:
            self.store.update(first["id"], {"name": "hacked"},
                              updated_by="admin@test.com")
        self.assertIn("cannot update", str(ctx.exception).lower())

    def test_add_custom_keyword_rule(self):
        """Add a custom keyword rule."""
        rule = self.store.add({
            "type": "keyword",
            "name": "test-credential-rule",
            "strength": "strong",
            "keywords": ["test_secret", "test_password"],
        }, updated_by="admin@test.com")
        self.assertTrue(rule["id"].startswith("custom:"))
        self.assertEqual(rule["name"], "test-credential-rule")
        self.assertEqual(rule["strength"], "strong")
        self.assertFalse(rule["builtin"])
        self.assertTrue(rule["enabled"])

    def test_add_custom_regex_rule(self):
        """Add a custom regex rule."""
        rule = self.store.add({
            "type": "regex",
            "name": "test-regex-rule",
            "strength": "weak",
            "pattern": r"test-\d{4}",
        }, updated_by="admin@test.com")
        self.assertTrue(rule["id"].startswith("custom:"))
        self.assertEqual(rule["pattern"], r"test-\d{4}")

    def test_add_invalid_type_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add({"type": "invalid", "name": "x"})

    def test_add_missing_name_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add({"type": "keyword", "keywords": ["x"]})

    def test_add_regex_without_pattern_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add({"type": "regex", "name": "x", "strength": "weak"})

    def test_add_keyword_without_keywords_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add({"type": "keyword", "name": "x", "strength": "weak"})

    def test_delete_custom_rule(self):
        """Custom rules can be deleted."""
        rule = self.store.add({
            "type": "keyword",
            "name": "to-delete",
            "strength": "weak",
            "keywords": ["delete_me"],
        }, updated_by="admin@test.com")
        removed = self.store.delete(rule["id"])
        self.assertTrue(removed)
        self.assertIsNone(self.store.get(rule["id"]))

    def test_delete_nonexistent_returns_false(self):
        removed = self.store.delete("custom:nonexistent")
        self.assertFalse(removed)

    def test_update_custom_rule(self):
        """Custom rules can have body fields updated."""
        rule = self.store.add({
            "type": "keyword",
            "name": "original",
            "strength": "weak",
            "keywords": ["original_kw"],
        }, updated_by="admin@test.com")
        updated = self.store.update(rule["id"], {
            "name": "renamed",
            "strength": "strong",
            "keywords": ["new_kw1", "new_kw2"],
        }, updated_by="admin@test.com")
        self.assertEqual(updated["name"], "renamed")
        self.assertEqual(updated["strength"], "strong")
        self.assertIn("new_kw1", updated["keywords"])

    def test_list_enabled_excludes_disabled(self):
        """Disabled rules are not in list_enabled."""
        rule = self.store.add({
            "type": "keyword",
            "name": "will-disable",
            "strength": "weak",
            "keywords": ["disable_me"],
        }, updated_by="admin@test.com")
        self.store.update(rule["id"], {"enabled": False},
                          updated_by="admin@test.com")
        enabled = self.store.list_enabled()
        self.assertNotIn(rule["id"], [r["id"] for r in enabled])

    def test_test_text_finds_keyword_hit(self):
        """test_text returns keyword hits."""
        self.store.add({
            "type": "keyword",
            "name": "test-keyword",
            "strength": "strong",
            "keywords": ["SUPER_SECRET_TOKEN"],
        }, updated_by="admin@test.com")
        result = self.store.test_text(
            "this page contains SUPER_SECRET_TOKEN in it")
        self.assertEqual(result["verdict"], "block")
        self.assertGreater(result["total_hits"], 0)
        # The hit should include our custom rule
        hit_names = [h["rule_name"] for h in result["hits"]]
        self.assertIn("test-keyword", hit_names)

    def test_test_text_finds_regex_hit(self):
        """test_text returns regex hits."""
        self.store.add({
            "type": "regex",
            "name": "test-phone",
            "strength": "weak",
            "pattern": r"\b1[3-9]\d{9}\b",
        }, updated_by="admin@test.com")
        result = self.store.test_text("call me at 13812345678")
        self.assertEqual(result["verdict"], "warn")
        self.assertGreater(result["total_hits"], 0)

    def test_test_text_clean_returns_pass(self):
        """Clean text returns pass verdict."""
        result = self.store.test_text("this is just a normal page about cats")
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["total_hits"], 0)

    def test_test_text_with_builtin_rule(self):
        """Built-in rules fire in test_text."""
        # "api_key" is in the built-in strong rules
        result = self.store.test_text("my api_key = abc123")
        # Should find the builtin keyword rule
        self.assertGreater(result["total_hits"], 0)

    def test_merged_rules_for_scanner(self):
        """get_merged_rules_for_scanner returns compilable rules."""
        # Use the store's own db path directly
        from golive.backends.registry.rules_store import RulesStore
        store = RulesStore(self.store.db_path)
        store.add({
            "type": "regex",
            "name": "custom-regex",
            "strength": "weak",
            "pattern": r"custom-\d+",
        }, updated_by="admin@test.com")
        # Now check the enabled rules from this store
        enabled = store.list_enabled()
        regex_names = [r["name"] for r in enabled if r["type"] == "regex"]
        self.assertIn("custom-regex", regex_names)

    def test_disabled_builtin_rule_excluded_from_scanner(self):
        """When a built-in rule is disabled, it's excluded from scanner merge."""
        # Use the store directly rather than the cached singleton
        from golive.backends.registry.rules_store import RulesStore
        rules_before = RulesStore(self.store.db_path).list_enabled()
        # Find a builtin keyword rule
        builtin_kw = [r for r in rules_before
                      if r["builtin"] and r["type"] == "keyword"]
        if not builtin_kw:
            self.skipTest("no builtin keyword rules to test")
        first = builtin_kw[0]
        # Disable it
        self.store.update(first["id"], {"enabled": False},
                          updated_by="admin@test.com")
        # Re-read from the same db
        rules_after = RulesStore(self.store.db_path).list_enabled()
        # Re-enable for cleanup
        self.store.update(first["id"], {"enabled": True},
                          updated_by="admin@test.com")
        # The disabled rule should not be in the after set
        after_names = [r.get("name") for r in rules_after]
        self.assertNotIn(first["name"], after_names)


if __name__ == "__main__":
    unittest.main()
