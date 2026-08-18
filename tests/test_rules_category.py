"""The rules table must keep the sensitivity category, not guess it.

``security_rules.type`` is the rule *shape* ("keyword" / "regex").
``security_rules.category`` is what kind of secret it is ("credential",
"personal_info", …). The scanner needs the latter: credential hits can never
be skipped, content hits can.

Before v0.8.2 the table had no category column, and merging rules back into
the scanner recovered it with ``name.split("(")[0]`` — so a rule named
"AWS AccessKey" arrived with category "AWS AccessKey" instead of
"credential". Every deployment with a database lost the distinction, which
also perturbed the scanner's de-duplication key and its LLM-review matching,
both of which are keyed on that value.

These tests fail if the guessing ever comes back.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from golive.core import paths

VALID_CATEGORIES = {"credential", "personal_info", "unknown"}


class _RulesStoreCase(unittest.TestCase):
    """Give each test its own GOLIVE_HOME so the seeded DB is isolated."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"GOLIVE_HOME": str(self.home)})
        self._env.start()
        paths.reset_cache()

    def tearDown(self):
        self._env.stop()
        paths.reset_cache()
        self._tmp.cleanup()

    def _store(self):
        from golive.backends.registry.rules_store import get_rules_store
        return get_rules_store()


class TestCategorySurvivesTheRoundTrip(_RulesStoreCase):

    def test_builtin_rules_carry_a_real_category(self):
        rules = self._store().list_all()
        self.assertTrue(rules, "expected seeded built-in rules")
        for r in rules:
            self.assertIn(
                r["category"], VALID_CATEGORIES,
                f"rule {r['name']!r} has category {r['category']!r}; a rule "
                f"name leaked into the category column again",
            )

    def test_credential_rules_are_labelled_credential(self):
        """The private-key rule is the canonical non-skippable one."""
        by_name = {r["name"]: r for r in self._store().list_all()}
        key_rule = next((r for n, r in by_name.items() if "私钥文件头" in n), None)
        self.assertIsNotNone(key_rule, "built-in private-key rule is missing")
        self.assertEqual(key_rule["category"], "credential")

    def test_scanner_merge_emits_categories_not_rule_names(self):
        from golive.backends.registry.rules_store import (
            get_merged_rules_for_scanner,
        )
        merged = get_merged_rules_for_scanner()
        seen = {r["type"] for r in
                merged["keyword_rules"] + merged["regex_rules"]}
        self.assertTrue(seen, "merge produced no rules")
        leaked = seen - VALID_CATEGORIES
        self.assertFalse(
            leaked,
            f"these are rule names, not categories: {sorted(leaked)} — the "
            f"scanner cannot decide skippability from them",
        )

    def test_shape_and_category_stay_separate(self):
        """Regression: category must not be overwritten with the shape."""
        rules = self._store().list_all()
        shapes = {r["type"] for r in rules}
        self.assertTrue(shapes <= {"keyword", "regex"}, f"unexpected: {shapes}")
        self.assertNotIn(
            "keyword", {r["category"] for r in rules},
            "the rule shape was written into the category column",
        )


class TestOlderDatabasesMigrate(_RulesStoreCase):
    """A database written before v0.8.2 has no category column at all."""

    _OLD_SCHEMA = """
    CREATE TABLE security_rules (
        id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
        strength TEXT NOT NULL DEFAULT 'weak', pattern TEXT, keywords TEXT,
        enabled INTEGER DEFAULT 1, builtin INTEGER DEFAULT 0,
        updated_by TEXT DEFAULT '', updated_at TEXT);
    """

    def _write_old_db(self, *, disabled_rule: str = "builtin:个人信息"):
        db = self.home / "registry.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        conn.executescript(self._OLD_SCHEMA)
        # A built-in rule the operator had deliberately switched off.
        conn.execute(
            "INSERT INTO security_rules VALUES (?,?,?,?,?,?,?,?,?,?)",
            (disabled_rule, "keyword", "个人信息", "weak", None,
             json.dumps(["工资"]), 0, 1, "", "2026-01-01"),
        )
        conn.commit()
        conn.close()
        return db

    def test_the_column_is_added_in_place(self):
        db = self._write_old_db()
        self._store()  # triggers migrate + seed
        cols = {r[1] for r in
                sqlite3.connect(db).execute("PRAGMA table_info(security_rules)")}
        self.assertIn("category", cols)

    def test_existing_rows_are_backfilled_from_the_yaml(self):
        self._write_old_db()
        rows = {r["id"]: r for r in self._store().list_all()}
        target = rows.get("builtin:个人信息")
        self.assertIsNotNone(target)
        self.assertEqual(target["category"], "personal_info")

    def test_migration_does_not_re_enable_disabled_rules(self):
        """Upgrading must not quietly switch protections back on."""
        self._write_old_db()
        rows = {r["id"]: r for r in self._store().list_all()}
        self.assertFalse(
            rows["builtin:个人信息"]["enabled"],
            "the operator had disabled this rule; the upgrade re-enabled it",
        )

    def test_migration_is_idempotent(self):
        self._write_old_db()
        self._store()
        paths.reset_cache()
        # Second open must not raise "duplicate column name".
        rules = self._store().list_all()
        self.assertTrue(rules)


if __name__ == "__main__":
    unittest.main()
