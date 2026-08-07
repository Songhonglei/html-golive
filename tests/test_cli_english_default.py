"""Tests for CLI English-default behaviour.

Verifies that `golive --help` and sub-command helps produce English output
by default (no CJK characters), and that GOLIVE_LANG=zh switches to Chinese.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest

# Regex to detect CJK (Chinese/Japanese/Korean) characters
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

# Environment for "clean" runs — no language-related vars
CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("LANG", "LC_ALL", "GOLIVE_LANG", "LC_CTYPE")}


def _run_cli(*args, **env_overrides):
    """Run `python3 -m golive.cli <args>` and return stdout+stderr."""
    env = dict(CLEAN_ENV)
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-m", "golive.cli", *args],
        capture_output=True, text=True, timeout=15, env=env,
    )
    return proc.stdout + proc.stderr


def _run_cli_no_env(*args):
    """Run CLI with LANG and LC_ALL stripped from the environment."""
    env = dict(os.environ)
    env.pop("LANG", None)
    env.pop("LC_ALL", None)
    env.pop("LC_CTYPE", None)
    env.pop("GOLIVE_LANG", None)
    proc = subprocess.run(
        [sys.executable, "-m", "golive.cli", *args],
        capture_output=True, text=True, timeout=15, env=env,
    )
    return proc.stdout + proc.stderr


class TestEnglishDefault(unittest.TestCase):
    """Default (no env vars) output must be English — no CJK characters."""

    def test_main_help_no_cjk(self):
        """`golive --help` output contains no CJK characters by default."""
        output = _run_cli_no_env("--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK characters in --help: {''.join(cjk_matches)}")

    def test_publish_help_no_cjk(self):
        """`golive publish --help` output contains no CJK characters."""
        output = _run_cli_no_env("publish", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in publish --help: {''.join(cjk_matches)}")

    def test_serve_help_no_cjk(self):
        """`golive serve --help` output contains no CJK characters."""
        output = _run_cli_no_env("serve", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in serve --help: {''.join(cjk_matches)}")

    def test_list_help_no_cjk(self):
        """`golive list --help` output contains no CJK characters."""
        output = _run_cli_no_env("list", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in list --help: {''.join(cjk_matches)}")

    def test_init_help_no_cjk(self):
        """`golive init --help` output contains no CJK characters."""
        output = _run_cli_no_env("init", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in init --help: {''.join(cjk_matches)}")

    def test_doctor_help_no_cjk(self):
        """`golive doctor --help` output contains no CJK characters."""
        output = _run_cli_no_env("doctor", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in doctor --help: {''.join(cjk_matches)}")

    def test_admin_help_no_cjk(self):
        """`golive admin --help` output contains no CJK characters."""
        output = _run_cli_no_env("admin", "--help")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK in admin --help: {''.join(cjk_matches)}")


class TestChineseOverride(unittest.TestCase):
    """GOLIVE_LANG=zh activates Chinese output."""

    def test_help_with_zh_contains_cjk(self):
        """`golive --help` with GOLIVE_LANG=zh contains Chinese characters."""
        output = _run_cli("--help", GOLIVE_LANG="zh")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertTrue(len(cjk_matches) > 0,
                        "Expected Chinese characters with GOLIVE_LANG=zh, got none")


class TestEnglishOverride(unittest.TestCase):
    """GOLIVE_LANG=en forces English even when locale is zh_CN."""

    def test_en_overrides_zh_locale(self):
        """GOLIVE_LANG=en produces English even with LANG=zh_CN.UTF-8."""
        output = _run_cli("--help",
                          GOLIVE_LANG="en", LANG="zh_CN.UTF-8", LC_ALL="zh_CN.UTF-8")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK with GOLIVE_LANG=en + zh locale: {''.join(cjk_matches)}")


class TestUnknownLangFallsBackToEnglish(unittest.TestCase):
    """Unrecognised GOLIVE_LANG value falls back to English without crashing."""

    def test_klingon_falls_back(self):
        """GOLIVE_LANG=klingon produces English, not an error."""
        output = _run_cli("--help", GOLIVE_LANG="klingon")
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [],
                         f"Found CJK with GOLIVE_LANG=klingon: {''.join(cjk_matches)}")

    def test_empty_golive_lang_falls_back(self):
        """Empty GOLIVE_LANG falls back to English (via locale)."""
        output = _run_cli("--help", GOLIVE_LANG="", LANG="", LC_ALL="")
        # No CJK in clean environment
        cjk_matches = CJK_PATTERN.findall(output)
        self.assertEqual(cjk_matches, [])


if __name__ == "__main__":
    unittest.main()
