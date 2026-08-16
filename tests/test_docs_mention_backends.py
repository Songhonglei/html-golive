"""Docs must not quietly forget a shipped backend.

Postgres shipped in 0.7.6 with working stores, but the main data-layer guide,
the README data-layer section and two bundled skill references still described
only sqlite and supabase. Users and agents read those files to decide what is
possible, so a backend that exists but is undocumented is close to a backend
that does not exist.

These are deliberately shallow keyword checks: they cannot judge whether the
prose is *good*, only that a shipped backend is not missing entirely from the
files people actually read.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files that describe the data layer to humans or to agents. Every one of
# these must name every server-proxied backend.
DATA_LAYER_DOCS = [
    "docs/data-layer.md",
    "docs/backends.md",
    "README.md",
    "README.zh-CN.md",
    "golive.example.yaml",
    "golive/resources/skill/SKILL.md",
    "golive/resources/skill/references/data-layer.md",
    "golive/resources/skill/references/cli.md",
    "golive/backends/data/__init__.py",
]

SERVER_PROXIED = ("sqlite", "postgres")


class TestDocsMentionEveryDataBackend(unittest.TestCase):

    def test_every_data_layer_doc_names_postgres(self):
        missing = []
        for rel in DATA_LAYER_DOCS:
            path = ROOT / rel
            if not path.is_file():
                missing.append(f"{rel} (file not found)")
                continue
            text = path.read_text(encoding="utf-8").lower()
            for backend in SERVER_PROXIED:
                if backend not in text:
                    missing.append(f"{rel} (no mention of {backend!r})")
        self.assertEqual(
            [], missing,
            "docs describe the data layer without naming a shipped backend:\n  "
            + "\n  ".join(missing))

    def test_the_main_guide_has_a_postgres_setup_section(self):
        """A passing mention is not enough for the guide README points at."""
        text = (ROOT / "docs/data-layer.md").read_text(encoding="utf-8")
        headings = [ln.strip() for ln in text.splitlines()
                    if ln.startswith("## ")]
        joined = " ".join(headings).lower()
        self.assertIn(
            "postgres", joined,
            "docs/data-layer.md has no Postgres section; headings are:\n  "
            + "\n  ".join(headings))

    def test_api_data_is_not_described_as_sqlite_only(self):
        """`/api/data` serves every server-proxied backend, not just sqlite."""
        offenders = []
        for rel in DATA_LAYER_DOCS:
            path = ROOT / rel
            if not path.is_file():
                continue
            for i, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                low = line.lower()
                if "/api/data" not in low:
                    continue
                # A line tying /api/data to sqlite must also allow postgres.
                if "sqlite" in low and "postgres" not in low:
                    offenders.append(f"{rel}:{i}: {line.strip()[:90]}")
        self.assertEqual(
            [], offenders,
            "these lines tie /api/data to sqlite alone:\n  "
            + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
