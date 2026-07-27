"""Tests for M6 audit.log size rotation (golive/core/audit.py)."""

import os
import tempfile
import unittest
from unittest import mock


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    for k in ("GOLIVE_AUDIT_MAX_BYTES", "GOLIVE_AUDIT_KEEP"):
        os.environ.pop(k, None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


class RotateBase(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def tearDown(self):
        for k in ("GOLIVE_AUDIT_MAX_BYTES", "GOLIVE_AUDIT_KEEP"):
            os.environ.pop(k, None)
        from golive.config import reset_config
        reset_config()

    def _reload_cfg(self):
        from golive.config import reset_config
        reset_config()

    def _write_until_rotated(self, n=20):
        from golive.core.audit import record
        for i in range(n):
            record("ops@example.com", "site.update", f"slug-{i}",
                   {"pad": "x" * 100})

    def _files(self):
        from golive.core.audit import audit_file
        home = audit_file().parent
        return sorted(p.name for p in home.glob("audit.log*"))


class TestRotation(RotateBase):
    def test_rotates_when_over_threshold(self):
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "500"
        self._reload_cfg()
        self._write_until_rotated(20)
        names = self._files()
        self.assertIn("audit.log", names)
        self.assertIn("audit.log.1", names)

    def test_keep_limit_discards_oldest(self):
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "300"
        os.environ["GOLIVE_AUDIT_KEEP"] = "2"
        self._reload_cfg()
        self._write_until_rotated(60)
        names = self._files()
        self.assertEqual(names, ["audit.log", "audit.log.1", "audit.log.2"])

    def test_archives_shift_up(self):
        """audit.log.1 content moves to .2 on the next rotation."""
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "300"
        os.environ["GOLIVE_AUDIT_KEEP"] = "3"
        self._reload_cfg()
        from golive.core.audit import audit_file, record
        record("a@example.com", "marker.first", "first-batch",
               {"pad": "x" * 400})           # oversized => next write rotates
        record("a@example.com", "noop", "second")
        arch1 = audit_file().with_name("audit.log.1")
        self.assertTrue(arch1.exists())
        self.assertIn("first-batch", arch1.read_text(encoding="utf-8"))
        # force a second rotation: current file must go oversized again
        record("a@example.com", "noop", "second", {"pad": "x" * 400})
        record("a@example.com", "noop", "third")
        arch2 = audit_file().with_name("audit.log.2")
        self.assertTrue(arch2.exists())
        self.assertIn("first-batch", arch2.read_text(encoding="utf-8"))

    def test_zero_disables_rotation(self):
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "0"
        self._reload_cfg()
        self._write_until_rotated(30)
        self.assertEqual(self._files(), ["audit.log"])

    def test_yaml_config_keys(self):
        home = os.environ["GOLIVE_HOME"]
        with open(os.path.join(home, "golive.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("admin:\n  audit_max_bytes: 400\n  audit_keep: 2\n")
        self._reload_cfg()
        from golive.core.audit import _rotation_settings
        self.assertEqual(_rotation_settings(), (400, 2))

    def test_env_wins_over_yaml(self):
        home = os.environ["GOLIVE_HOME"]
        with open(os.path.join(home, "golive.yaml"), "w",
                  encoding="utf-8") as f:
            f.write("admin:\n  audit_max_bytes: 400\n")
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "999"
        self._reload_cfg()
        from golive.core.audit import _rotation_settings
        self.assertEqual(_rotation_settings()[0], 999)

    def test_rename_failure_never_raises(self):
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "100"
        self._reload_cfg()
        from golive.core import audit
        audit.record("a@example.com", "x", "s", {"pad": "y" * 200})
        with mock.patch("golive.core.audit.os.replace",
                        side_effect=OSError("disk says no")):
            audit.record("a@example.com", "still.works", "s2")  # no raise
        data = audit.audit_file().read_text(encoding="utf-8")
        self.assertIn("still.works", data)

    def test_read_entries_only_current_file(self):
        """Rotated archives are not visible through read_entries()."""
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "200"
        self._reload_cfg()
        from golive.core.audit import read_entries, record
        record("a@example.com", "old.entry", "s", {"pad": "z" * 300})
        record("a@example.com", "new.entry", "s")   # triggers rotation
        actions = [e["action"] for e in read_entries(size=50)["entries"]]
        self.assertIn("new.entry", actions)
        self.assertNotIn("old.entry", actions)

    def test_malformed_env_ignored(self):
        os.environ["GOLIVE_AUDIT_MAX_BYTES"] = "not-a-number"
        self._reload_cfg()
        from golive.core.audit import _rotation_settings
        self.assertEqual(_rotation_settings()[0], 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
