"""v0.8.0 settings store tests: dual-source merge, hot/restart scope."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_settings_"))

from golive.backends.registry.settings_store import (
    SettingsStore, SETTING_DEFINITIONS, get_yaml_snapshot,
)


class TestSettingsStore(unittest.TestCase):
    """Dual-source settings: yaml (read-only) + database (managed)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="golive_settings_")
        self.store = SettingsStore(os.path.join(self.tmp, "test.db"))

    def test_get_all_returns_all_definitions(self):
        """Every defined setting appears in get_all()."""
        grouped = self.store.get_all(yaml_values={})
        total = sum(len(items) for items in grouped.values())
        self.assertEqual(total, len(SETTING_DEFINITIONS))

    def test_default_values_when_no_overrides(self):
        """Without yaml or DB, values are defaults."""
        grouped = self.store.get_all(yaml_values={})
        # Find server.port
        server_items = grouped.get("server", [])
        port_item = next(i for i in server_items if i["key"] == "server.port")
        self.assertEqual(port_item["value"], 8787)
        self.assertEqual(port_item["source"], "default")
        self.assertEqual(port_item["scope"], "restart")

    def test_yaml_values_take_precedence_over_defaults(self):
        """Yaml values are marked as 'yaml' source."""
        grouped = self.store.get_all(yaml_values={"server.port": 9090})
        server_items = grouped.get("server", [])
        port_item = next(i for i in server_items if i["key"] == "server.port")
        self.assertEqual(port_item["value"], 9090)
        self.assertEqual(port_item["source"], "yaml")

    def test_db_overrides_take_precedence_over_yaml(self):
        """Database values are highest priority."""
        self.store.set("server.port", 7777, updated_by="admin@test.com")
        grouped = self.store.get_all(yaml_values={"server.port": 9090})
        server_items = grouped.get("server", [])
        port_item = next(i for i in server_items if i["key"] == "server.port")
        self.assertEqual(port_item["value"], 7777)
        self.assertEqual(port_item["source"], "database")

    def test_set_returns_needs_restart_for_restart_scope(self):
        """Restart-scoped settings return needs_restart=True."""
        result = self.store.set("server.port", 8888, updated_by="admin@test.com")
        self.assertTrue(result["needs_restart"])
        self.assertEqual(result["scope"], "restart")

    def test_set_returns_no_restart_for_hot_scope(self):
        """Hot-scoped settings return needs_restart=False."""
        result = self.store.set("watermark.enabled", True, updated_by="admin@test.com")
        self.assertFalse(result["needs_restart"])
        self.assertEqual(result["scope"], "hot")

    def test_set_many_returns_updated_and_needs_restart(self):
        """Batch update returns both updated items and restart list."""
        result = self.store.set_many({
            "server.port": 9999,
            "watermark.enabled": True,
        }, updated_by="admin@test.com")
        self.assertEqual(len(result["updated"]), 2)
        self.assertIn("server.port", result["needs_restart"])
        self.assertNotIn("watermark.enabled", result["needs_restart"])

    def test_delete_removes_db_override(self):
        """Delete reverts to yaml/default."""
        self.store.set("server.port", 7777, updated_by="admin@test.com")
        removed = self.store.delete("server.port")
        self.assertTrue(removed)
        # After delete, should be default
        grouped = self.store.get_all(yaml_values={})
        server_items = grouped.get("server", [])
        port_item = next(i for i in server_items if i["key"] == "server.port")
        self.assertEqual(port_item["source"], "default")
        self.assertEqual(port_item["value"], 8787)

    def test_delete_nonexistent_returns_false(self):
        """Delete on a key with no DB override returns False."""
        removed = self.store.delete("server.port")
        self.assertFalse(removed)

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            self.store.set("unknown.setting", "value")

    def test_bool_type_coercion(self):
        """Boolean settings are stored as string and coerced back."""
        self.store.set("watermark.enabled", True, updated_by="admin@test.com")
        grouped = self.store.get_all(yaml_values={})
        wm_items = grouped.get("watermark", [])
        enabled_item = next(i for i in wm_items if i["key"] == "watermark.enabled")
        self.assertTrue(enabled_item["value"])
        self.assertEqual(enabled_item["type"], "bool")

    def test_int_type_coercion(self):
        """Integer settings are stored as string and coerced back."""
        self.store.set("server.port", 12345, updated_by="admin@test.com")
        grouped = self.store.get_all(yaml_values={})
        server_items = grouped.get("server", [])
        port_item = next(i for i in server_items if i["key"] == "server.port")
        self.assertEqual(port_item["value"], 12345)
        self.assertEqual(port_item["type"], "int")

    def test_get_flat_returns_dict(self):
        """get_flat returns a simple key→value dict."""
        flat = self.store.get_flat(yaml_values={"server.port": 9090})
        self.assertEqual(flat["server.port"], 9090)
        self.assertIn("watermark.enabled", flat)

    def test_scope_tags_are_consistent(self):
        """Every setting has a valid scope tag."""
        grouped = self.store.get_all(yaml_values={})
        for category, items in grouped.items():
            for item in items:
                self.assertIn(item["scope"], ("hot", "restart"),
                              f"bad scope for {item['key']}: {item['scope']}")

    def test_categories_are_present(self):
        """All expected categories appear in the grouped result."""
        grouped = self.store.get_all(yaml_values={})
        expected_categories = {"server", "data", "auth", "watermark",
                               "security", "admin"}
        self.assertTrue(expected_categories.issubset(set(grouped.keys())))


class TestYamlSnapshot(unittest.TestCase):
    """Verify get_yaml_snapshot reads from the loaded config."""

    def test_snapshot_returns_known_keys(self):
        snapshot = get_yaml_snapshot()
        self.assertIn("server.port", snapshot)
        self.assertIn("auth.provider", snapshot)
        self.assertIn("watermark.enabled", snapshot)


if __name__ == "__main__":
    unittest.main()
