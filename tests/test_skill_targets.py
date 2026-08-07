"""v0.7.1 — skill install target detection (Codex, Cursor, multi-target).

The user story behind this file: someone running Codex installed the
skill, golive dropped it into ``~/.claude/skills`` because that
directory happened to exist, and Codex never saw it. Detection now ranks
by *which agent is actually installed*, offers a choice when several
are, and never blocks a non-interactive run.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from golive.core import skill_installer as si


class TargetBase(unittest.TestCase):
    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        from golive.i18n import set_language
        set_language("en")
        self.tmp = Path(tempfile.mkdtemp(prefix="golive_targets_"))
        self.cwd = self.tmp / "proj"
        self.home = self.tmp / "home"
        self.cwd.mkdir()
        self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def paths(self, cands):
        return [c.path for c in cands]


class TestCodexIsDetected(TargetBase):
    def test_codex_is_in_the_conventions_table(self):
        rels = {row[1] for row in si.TARGET_CONVENTIONS}
        self.assertIn(".codex/skills", rels)

    def test_cursor_is_in_the_conventions_table(self):
        rels = {row[1] for row in si.TARGET_CONVENTIONS}
        self.assertIn(".cursor/skills", rels)

    def test_legacy_conventions_are_kept(self):
        rels = {row[1] for row in si.TARGET_CONVENTIONS}
        for rel in (".claude/skills", ".agent/skills",
                    ".config/agent/skills", ".local/share/agent/skills"):
            self.assertIn(rel, rels, f"{rel} must not be dropped")

    def test_conventions_table_still_two_scopes(self):
        bases = {row[0] for row in si.TARGET_CONVENTIONS}
        self.assertEqual(bases, {"cwd", "home"})

    def test_bare_codex_dir_ranks_first(self):
        """~/.codex exists but ~/.codex/skills does not — still the winner."""
        (self.home / ".codex").mkdir()
        cands = si.detect_targets(cwd=self.cwd, home=self.home)
        self.assertEqual(cands[0].path, self.home / ".codex" / "skills")
        self.assertTrue(cands[0].agent_present)
        self.assertFalse(cands[0].exists)
        self.assertEqual(cands[0].agent, "Codex")

    def test_codex_beats_a_conventional_but_absent_claude_dir(self):
        (self.home / ".codex").mkdir()
        cands = si.detect_targets(cwd=self.cwd, home=self.home)
        codex_i = self.paths(cands).index(self.home / ".codex" / "skills")
        claude_i = self.paths(cands).index(self.home / ".claude" / "skills")
        self.assertLess(codex_i, claude_i)

    def test_existing_skills_dir_beats_a_merely_present_agent(self):
        (self.home / ".codex").mkdir()
        (self.home / ".claude" / "skills").mkdir(parents=True)
        cands = si.detect_targets(cwd=self.cwd, home=self.home)
        self.assertEqual(cands[0].path, self.home / ".claude" / "skills")
        self.assertTrue(cands[0].exists)

    def test_install_goes_to_codex_when_codex_is_the_only_agent(self):
        (self.home / ".codex").mkdir()
        res = si.install(cwd=self.cwd, home=self.home, interactive=False)
        self.assertEqual(Path(res["installed_to"]),
                         self.home / ".codex" / "skills" / si.SKILL_NAME)
        self.assertEqual(res["target_choice"], "only")
        self.assertTrue((Path(res["installed_to"]) / "SKILL.md").is_file())


class TestViability(TargetBase):
    def test_nothing_installed_means_no_viable_target(self):
        self.assertEqual(si.viable_targets(cwd=self.cwd, home=self.home), [])

    def test_viable_lists_only_real_candidates(self):
        (self.home / ".codex").mkdir()
        (self.cwd / ".cursor" / "skills").mkdir(parents=True)
        viable = si.viable_targets(cwd=self.cwd, home=self.home)
        self.assertEqual(len(viable), 2)
        self.assertEqual(viable[0].path, self.cwd / ".cursor" / "skills")

    def test_no_target_still_raises_with_guidance(self):
        with self.assertRaises(si.SkillInstallError) as ctx:
            si.resolve_target(cwd=self.cwd, home=self.home)
        msg = str(ctx.exception)
        self.assertIn("--target", msg)
        self.assertIn("skills", msg)


class TestMultipleTargets(TargetBase):
    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        from golive.i18n import set_language
        set_language("en")
        super().setUp()
        (self.home / ".codex").mkdir()
        (self.home / ".claude" / "skills").mkdir(parents=True)
        (self.cwd / ".cursor").mkdir()

    def test_non_tty_picks_first_and_explains(self):
        buf = io.StringIO()
        path, how = si.choose_target(cwd=self.cwd, home=self.home,
                                     interactive=False, stream=buf)
        self.assertEqual(how, "auto")
        self.assertEqual(path, self.home / ".claude" / "skills")  # exists wins
        out = buf.getvalue()
        self.assertIn("自动选择第一个", out)
        self.assertIn("--target", out, "must tell the user how to override")
        # every other candidate is listed so the choice is auditable
        self.assertIn(str(self.home / ".codex" / "skills"), out)
        self.assertIn(str(self.cwd / ".cursor" / "skills"), out)

    def test_non_tty_never_blocks(self):
        """No prompt is issued: input() would raise OSError under pytest."""
        import builtins
        original = builtins.input

        def explode(*_a, **_kw):  # pragma: no cover — must never run
            raise AssertionError("choose_target prompted in a non-TTY run")

        builtins.input = explode
        try:
            si.choose_target(cwd=self.cwd, home=self.home,
                             interactive=False, stream=io.StringIO())
        finally:
            builtins.input = original

    def test_interactive_menu_honours_the_number(self):
        import builtins
        buf = io.StringIO()
        original = builtins.input
        builtins.input = lambda *_a, **_kw: "2"
        try:
            path, how = si.choose_target(cwd=self.cwd, home=self.home,
                                         interactive=True, stream=buf)
        finally:
            builtins.input = original
        self.assertEqual(how, "chosen")
        viable = si.viable_targets(cwd=self.cwd, home=self.home)
        self.assertEqual(path, viable[1].path)
        self.assertIn("[1]", buf.getvalue())
        self.assertIn("[3]", buf.getvalue())

    def test_interactive_empty_answer_takes_the_default(self):
        import builtins
        original = builtins.input
        builtins.input = lambda *_a, **_kw: ""
        try:
            path, how = si.choose_target(cwd=self.cwd, home=self.home,
                                         interactive=True,
                                         stream=io.StringIO())
        finally:
            builtins.input = original
        self.assertEqual(how, "chosen")
        self.assertEqual(path, self.home / ".claude" / "skills")

    def test_interactive_bad_number_is_a_clean_error(self):
        import builtins
        original = builtins.input
        builtins.input = lambda *_a, **_kw: "99"
        try:
            with self.assertRaises(si.SkillInstallError) as ctx:
                si.choose_target(cwd=self.cwd, home=self.home,
                                 interactive=True, stream=io.StringIO())
        finally:
            builtins.input = original
        self.assertIn("99", str(ctx.exception))

    def test_interactive_non_numeric_is_a_clean_error(self):
        import builtins
        original = builtins.input
        builtins.input = lambda *_a, **_kw: "codex"
        try:
            with self.assertRaises(si.SkillInstallError):
                si.choose_target(cwd=self.cwd, home=self.home,
                                 interactive=True, stream=io.StringIO())
        finally:
            builtins.input = original

    def test_ctrl_c_falls_back_instead_of_crashing(self):
        import builtins
        original = builtins.input

        def interrupted(*_a, **_kw):
            raise KeyboardInterrupt

        builtins.input = interrupted
        try:
            path, how = si.choose_target(cwd=self.cwd, home=self.home,
                                         interactive=True,
                                         stream=io.StringIO())
        finally:
            builtins.input = original
        self.assertEqual(how, "auto")
        self.assertEqual(path, self.home / ".claude" / "skills")

    def test_explicit_target_skips_all_detection(self):
        elsewhere = self.tmp / "elsewhere"
        res = si.install(target=str(elsewhere), cwd=self.cwd, home=self.home,
                         interactive=False)
        self.assertEqual(res["target_choice"], "explicit")
        self.assertEqual(Path(res["target_dir"]), elsewhere)


class TestListTargetsCli(TargetBase):
    """`golive skill install --list-targets` — read-only inspection."""

    def _run(self):
        import contextlib

        from golive.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["skill", "install", "--list-targets"])
        return code, buf.getvalue()

    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        from golive.i18n import set_language
        set_language("en")
        super().setUp()
        self._old_cwd = os.getcwd()
        self._old_home = os.environ.get("HOME")
        self._old_golive_home = os.environ.get("GOLIVE_HOME")
        os.environ["GOLIVE_HOME"] = str(self.tmp / "golive-home")
        import golive.core.paths as p
        p.reset_cache()
        os.chdir(self.cwd)
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.chdir(self._old_cwd)
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        if self._old_golive_home is not None:
            os.environ["GOLIVE_HOME"] = self._old_golive_home
        else:
            os.environ.pop("GOLIVE_HOME", None)
        import golive.core.paths as p
        p.reset_cache()
        super().tearDown()

    def test_lists_detected_paths_and_changes_nothing(self):
        (self.home / ".codex").mkdir()
        (self.cwd / ".cursor" / "skills").mkdir(parents=True)
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn(str(self.cwd / ".cursor" / "skills"), out)
        self.assertIn(str(self.home / ".codex" / "skills"), out)
        self.assertIn("Codex", out)
        self.assertIn("Cursor", out)
        # strictly read-only
        self.assertFalse((self.home / ".codex" / "skills").exists())
        self.assertFalse((self.cwd / ".cursor" / "skills" /
                          si.SKILL_NAME).exists())

    def test_lists_conventions_even_when_no_agent_present(self):
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("No installed agents detected", out)
        self.assertIn(".codex", out)

    def test_marks_locations_that_already_have_the_skill(self):
        target = self.home / ".codex" / "skills"
        target.mkdir(parents=True)
        si.install(target=str(target), cwd=self.cwd, home=self.home,
                   interactive=False)
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("html-golive already installed", out)


class TestStatusAcrossLocations(TargetBase):
    def test_status_counts_every_location(self):
        a = self.home / ".codex" / "skills"
        b = self.cwd / ".cursor" / "skills"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        si.install(target=str(a), cwd=self.cwd, home=self.home,
                   interactive=False)
        si.install(target=str(b), cwd=self.cwd, home=self.home,
                   interactive=False)
        st = si.status(cwd=self.cwd, home=self.home)
        self.assertEqual(st["install_count"], 2)
        self.assertEqual(len(st["installs"]), 2)
        self.assertTrue(st["candidates"], "status should expose candidates")

    def test_status_reports_the_agent_per_location(self):
        a = self.home / ".codex" / "skills"
        a.mkdir(parents=True)
        si.install(target=str(a), cwd=self.cwd, home=self.home,
                   interactive=False)
        st = si.status(cwd=self.cwd, home=self.home)
        self.assertEqual(st["installs"][0]["agent"], "Codex")

    def test_status_with_no_installs(self):
        st = si.status(cwd=self.cwd, home=self.home)
        self.assertEqual(st["install_count"], 0)
        self.assertFalse(st["in_sync"])


class TestCandidateShape(TargetBase):
    def test_describe_is_human_readable(self):
        (self.home / ".codex").mkdir()
        cand = si.detect_targets(cwd=self.cwd, home=self.home)[0]
        text = cand.describe()
        self.assertIn("Codex", text)
        self.assertIn(str(cand.path), text)

    def test_as_dict_is_json_safe(self):
        import json
        (self.home / ".codex").mkdir()
        cand = si.detect_targets(cwd=self.cwd, home=self.home)[0]
        json.dumps(cand.as_dict())   # must not raise
        self.assertEqual(cand.as_dict()["agent"], "Codex")
        self.assertEqual(cand.as_dict()["scope"], "home")


if __name__ == "__main__":
    unittest.main()
