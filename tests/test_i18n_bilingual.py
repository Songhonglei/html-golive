"""Bilingual switching tests: verify that GOLIVE_LANG=zh shows Chinese
and default (unset) shows English for the newly added i18n keys.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run_with_lang(lang, args):
    """Run golive CLI with the given GOLIVE_LANG and return stdout+stderr."""
    env = dict(os.environ)
    if lang is None:
        env.pop("GOLIVE_LANG", None)
    else:
        env["GOLIVE_LANG"] = lang
    env.pop("LANG", None)
    env.pop("LC_ALL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "golive.cli"] + args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )
    return proc.stdout + proc.stderr


class TestBilingualSwitching:
    """Verify key messages switch between English and Chinese."""

    def test_clone_help_english(self):
        """clone --help should be English by default."""
        out = _run_with_lang(None, ["clone", "--help"])
        assert "URL of the page to clone" in out
        cjk = re.findall(r'[\u4e00-\u9fff]', out)
        assert len(cjk) == 0, f"Found CJK in English output: {cjk[:10]}"

    def test_clone_help_chinese(self):
        """clone --help should contain Chinese when GOLIVE_LANG=zh."""
        out = _run_with_lang("zh", ["clone", "--help"])
        cjk = re.findall(r'[\u4e00-\u9fff]', out)
        assert len(cjk) > 0, "Expected Chinese text in zh mode"

    def test_migrate_check_help_english(self):
        """migrate-check --help should be English by default."""
        out = _run_with_lang(None, ["migrate-check", "--help"])
        cjk = re.findall(r'[\u4e00-\u9fff]', out)
        assert len(cjk) == 0, f"Found CJK in English output: {cjk[:10]}"

    def test_migrate_check_help_chinese(self):
        """migrate-check --help should contain Chinese when GOLIVE_LANG=zh."""
        out = _run_with_lang("zh", ["migrate-check", "--help"])
        assert "HTML" in out

    def test_publish_help_english(self):
        """publish --help should be English by default."""
        out = _run_with_lang(None, ["publish", "--help"])
        cjk = re.findall(r'[\u4e00-\u9fff]', out)
        assert len(cjk) == 0, f"Found CJK in English output: {cjk[:10]}"

    def test_main_help_english(self):
        """--help should be English by default."""
        out = _run_with_lang(None, ["--help"])
        cjk = re.findall(r'[\u4e00-\u9fff]', out)
        assert len(cjk) == 0, f"Found CJK in English output: {cjk[:10]}"

    def test_key_messages_switch(self):
        """Specific i18n keys should produce different text in en vs zh."""
        from golive.i18n import set_language, t

        test_cases = [
            ("clone_site.banner", {}),
            ("clone_patcher.start", {}),
            ("clone_patcher.done", {}),
            ("safety.check_passed", {}),
            ("safety.abort", {}),
            ("bundle.start", {}),
            ("bundle.done", {}),
            ("migrate.clean", {}),
            ("scanner.skip", {}),
        ]

        for key, kwargs in test_cases:
            # English
            set_language("en")
            en_text = t(key, **kwargs)
            assert en_text, f"English text empty for {key}"

            # Chinese
            set_language("zh")
            zh_text = t(key, **kwargs)
            assert zh_text, f"Chinese text empty for {key}"

            # They should be different
            assert en_text != zh_text, f"en and zh are the same for {key}: {en_text}"

            # English should not contain CJK
            en_cjk = re.findall(r'[\u4e00-\u9fff]', en_text)
            assert len(en_cjk) == 0, f"English text for {key} contains CJK: {en_cjk} - {en_text}"

            # Chinese should contain CJK
            zh_cjk = re.findall(r'[\u4e00-\u9fff]', zh_text)
            assert len(zh_cjk) > 0, f"Chinese text for {key} has no CJK: {zh_text}"

        # Reset to default
        set_language("en")
