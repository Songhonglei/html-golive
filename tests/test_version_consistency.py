"""The version must be one number, not four that drift apart.

``golive/__init__.py`` is the single source of truth — the CLI, ``/health``
and ``golive context`` all read it. But ``pyproject.toml`` and the bundled
skill's frontmatter carry their own literals, and a release that bumps only
some of them ships a package whose reported version does not match what pip
installed. That is exactly the kind of mismatch that makes bug reports
impossible to place.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Only the [project] version, not a dependency pin.
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml has no top-level version"
    return m.group(1)


def _skill_frontmatter_version() -> str:
    text = (ROOT / "golive/resources/skill/SKILL.md").read_text(
        encoding="utf-8")
    m = re.search(r"^version:\s*([0-9][^\s]*)", text, re.MULTILINE)
    assert m, "bundled SKILL.md has no version in its frontmatter"
    return m.group(1)


class TestVersionConsistency(unittest.TestCase):

    def test_package_and_pyproject_agree(self):
        from golive import __version__
        self.assertEqual(
            __version__, _pyproject_version(),
            "golive.__version__ and pyproject.toml disagree — pip would "
            "install one number while the CLI reports another")

    def test_bundled_skill_agrees(self):
        from golive import __version__
        self.assertEqual(
            __version__, _skill_frontmatter_version(),
            "the bundled skill advertises a different version than the "
            "package that ships it")

    def test_health_endpoint_reports_the_package_version(self):
        """doctor compares /health against the local CLI, so it must match."""
        from golive import __version__
        from golive.server.app import _health_payload
        self.assertEqual(_health_payload().get("version"), __version__)

    def test_changelog_documents_the_current_version(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        from golive import __version__
        self.assertIn(
            f"[{__version__}]", text,
            f"CHANGELOG.md has no entry for {__version__} — releases must "
            "say what changed")


if __name__ == "__main__":
    unittest.main()
