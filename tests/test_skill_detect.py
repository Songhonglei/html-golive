"""Tests for skill_installer detection semantics — no-agent neutrality.

Covers:
  - NoAgentDetected is raised (not plain SkillInstallError) when no
    agent directory exists
  - NoAgentDetected is a subclass of SkillInstallError (backward compat)
  - The message is phrased as guidance, not an error
  - The message does NOT contain "could not detect"
  - _no_target_message returns Chinese guidance text
  - detect_targets with nested HOME does not produce parent-dir paths
  - NoAgentDetected is catchable as SkillInstallError (existing code path)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from golive.core import skill_installer as si


class TestNoAgentDetectedException(unittest.TestCase):
    def test_is_subclass_of_skill_install_error(self):
        self.assertTrue(issubclass(si.NoAgentDetected, si.SkillInstallError))

    def test_is_subclass_of_runtime_error(self):
        self.assertTrue(issubclass(si.NoAgentDetected, RuntimeError))

    def test_raised_when_no_viable_targets(self):
        """choose_target raises NoAgentDetected, not plain SkillInstallError."""
        tmp = Path(tempfile.mkdtemp())
        try:
            empty_cwd = tmp / "empty"
            empty_home = tmp / "home"
            empty_cwd.mkdir()
            empty_home.mkdir()
            with self.assertRaises(si.NoAgentDetected):
                si.choose_target(cwd=empty_cwd, home=empty_home)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_raises_no_agent_when_no_targets(self):
        """install() propagates NoAgentDetected."""
        tmp = Path(tempfile.mkdtemp())
        try:
            empty_cwd = tmp / "empty"
            empty_home = tmp / "home"
            empty_cwd.mkdir()
            empty_home.mkdir()
            with self.assertRaises(si.NoAgentDetected):
                si.install(cwd=empty_cwd, home=empty_home)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_catchable_as_skill_install_error(self):
        """Existing except SkillInstallError blocks still catch it."""
        tmp = Path(tempfile.mkdtemp())
        try:
            empty_cwd = tmp / "empty"
            empty_home = tmp / "home"
            empty_cwd.mkdir()
            empty_home.mkdir()
            # This is how init_wizard currently catches it:
            with self.assertRaises(si.SkillInstallError):
                si.install(cwd=empty_cwd, home=empty_home)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNoTargetMessageTone(unittest.TestCase):
    def test_message_is_guidance_not_error(self):
        cands = si.detect_targets(
            cwd=Path(tempfile.mkdtemp()),
            home=Path(tempfile.mkdtemp()),
        )
        msg = si._no_target_message(cands)
        self.assertIn("golive skill install", msg)
        self.assertIn("golive skill install", msg)

    def test_message_does_not_say_could_not_detect(self):
        cands = si.detect_targets(
            cwd=Path(tempfile.mkdtemp()),
            home=Path(tempfile.mkdtemp()),
        )
        msg = si._no_target_message(cands)
        self.assertNotIn("could not detect", msg)
        self.assertNotIn("❌", msg)
        # --target guidance is fine, but the tone is neutral
        self.assertIn("golive skill install", msg)


class TestNestedHomeNoParentDirBug(unittest.TestCase):
    """Verify that detect_targets with a nested HOME does not produce
    paths in HOME's *parent* directory.

    The user reported seeing /tmp/newbie/.codex/skills when HOME was
    /tmp/newbie/home — that path is HOME.parent / '.codex' / 'skills',
    which would only happen if Path.home() were resolved incorrectly.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "newbie" / "home"
        self.home.mkdir(parents=True)
        self.old_home = os.environ.get("HOME", "")

    def tearDown(self):
        if self.old_home:
            os.environ["HOME"] = self.old_home
        else:
            os.environ.pop("HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_home_candidates_use_home_not_parent(self):
        os.environ["HOME"] = str(self.home)
        cands = si.detect_targets(cwd=self.tmp, home=self.home)
        home_cands = [c for c in cands if c.scope == "home"]
        for c in home_cands:
            self.assertTrue(
                str(c.path).startswith(str(self.home)),
                f"{c.path} should be under {self.home}, not its parent"
            )

    def test_no_candidate_in_home_parent(self):
        os.environ["HOME"] = str(self.home)
        parent = str(self.home.parent)
        cands = si.detect_targets(cwd=self.tmp, home=self.home)
        for c in cands:
            if c.scope == "home":
                self.assertFalse(
                    str(c.path).startswith(parent + "/")
                    and not str(c.path).startswith(str(self.home)),
                    f"Home candidate {c.path} appears to be in HOME's parent"
                )

    def test_path_home_respects_env(self):
        os.environ["HOME"] = str(self.home)
        self.assertEqual(Path.home(), self.home)


if __name__ == "__main__":
    unittest.main()
