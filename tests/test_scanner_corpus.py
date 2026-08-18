"""Measure the credential scanner against a corpus of sample pages.

``tests/corpus/must_block`` must be refused; ``tests/corpus/must_pass`` must
publish without a BLOCK. The directories are walked at run time, so a new
case is a new file — there is no list here to keep in sync.

False positives get their own half of the corpus deliberately. A scanner that
cries wolf gets routed around: someone reaches for ``--skip-content-scan`` by
reflex, or stops publishing the page that actually mattered. Both failure
directions are regressions.
"""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from golive.security.scanner import run_scan

CORPUS = Path(__file__).resolve().parent / "corpus"
MUST_BLOCK = CORPUS / "must_block"
MUST_PASS = CORPUS / "must_pass"

# Every flag combination a caller could try. Credentials must survive all of
# them; see tests/test_scan_gate.py for the rule.
WAIVERS = (
    ("no flags", {}),
    ("--skip-scan", {"skip_scan": True}),
    ("--skip-content-scan", {"skip_content": True}),
    ("both", {"skip_scan": True, "skip_content": True}),
)


def _scan(html: str, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        ok, result = run_scan(html, **kwargs)
    return ok, result, buf.getvalue()


def _cases(directory: Path):
    return sorted(directory.glob("*.html"))


class TestCorpusIsPresent(unittest.TestCase):
    """Guard against the corpus silently disappearing from a package."""

    def test_both_halves_have_samples(self):
        self.assertTrue(_cases(MUST_BLOCK), f"no samples in {MUST_BLOCK}")
        self.assertTrue(_cases(MUST_PASS), f"no samples in {MUST_PASS}")

    def test_the_corpus_itself_carries_no_real_secret(self):
        """Samples are assembled from fragments and use fake values."""
        for path in _cases(MUST_BLOCK) + _cases(MUST_PASS):
            with self.subTest(sample=path.name):
                text = path.read_text(encoding="utf-8")
                # A real AWS key is 20 chars starting AKIA; ours says EXAMPLE.
                if "AKIA" in text:
                    self.assertIn("EXAMPLE", text)


class TestEverythingInMustBlockIsRefused(unittest.TestCase):

    def test_each_sample_blocks_under_every_flag(self):
        for path in _cases(MUST_BLOCK):
            html = path.read_text(encoding="utf-8")
            for label, kwargs in WAIVERS:
                with self.subTest(sample=path.name, flags=label):
                    ok, _, _ = _scan(html, **kwargs)
                    self.assertFalse(
                        ok,
                        f"corpus/must_block/{path.name} published with "
                        f"{label}",
                    )

    def test_the_report_never_echoes_the_full_secret(self):
        """Findings reach stderr, CI logs and screenshots."""
        for path in _cases(MUST_BLOCK):
            html = path.read_text(encoding="utf-8")
            with self.subTest(sample=path.name):
                _, result, report = _scan(html)
                blob = report + " ".join(
                    f"{d.get('context', '')}{d.get('keyword', '')}"
                    for d in (result.matched_details if result else []))
                # Long unbroken secret-ish runs should not survive verbatim.
                for token in _secret_like_tokens(html):
                    self.assertNotIn(
                        token, blob,
                        f"{path.name}: {token[:8]}… appeared unredacted")


def _secret_like_tokens(html: str) -> list:
    """Long opaque runs from a sample — the parts that must be redacted."""
    import re
    tokens = []
    # DSN passwords: scheme://user:PASSWORD@
    tokens += re.findall(r'://[^\s:/@]+:([^\s@/]{6,})@', html)
    # Values assigned to a key-ish name
    tokens += re.findall(
        r'(?:password|secret|token)\s*[=:]\s*["\']?([A-Za-z0-9@!$%^&*_\-]{8,})',
        html, re.IGNORECASE)
    return [t for t in tokens if len(t) >= 8]


class TestEverythingInMustPassIsAllowed(unittest.TestCase):

    def test_each_sample_publishes_without_a_block(self):
        for path in _cases(MUST_PASS):
            html = path.read_text(encoding="utf-8")
            with self.subTest(sample=path.name):
                ok, result, report = _scan(html)
                strong = [d["name"] for d in (result.strong_hits if result
                                              else [])]
                self.assertTrue(
                    ok,
                    f"corpus/must_pass/{path.name} was blocked by "
                    f"{strong or 'an unknown rule'}",
                )
                self.assertFalse(
                    strong,
                    f"corpus/must_pass/{path.name} produced credential "
                    f"findings: {strong}",
                )

    def test_placeholders_are_not_mistaken_for_secrets(self):
        """Docs telling people to set a key must remain publishable."""
        sample = MUST_PASS / "placeholder_secrets.html"
        if not sample.exists():
            self.skipTest("sample not present")
        ok, _, _ = _scan(sample.read_text(encoding="utf-8"))
        self.assertTrue(ok)


class TestTheCorpusIsSelfDocumenting(unittest.TestCase):
    """The corpus lives in the repository, not the wheel.

    ``pyproject.toml`` packages only ``golive*``, so these samples are a
    development asset — run from a checkout or in CI, not from an installed
    package. That is the right split; the note here just records it so nobody
    concludes the corpus went missing from a release.
    """

    def test_the_samples_are_documented(self):
        self.assertTrue(CORPUS.is_dir())
        readme = CORPUS / "README.md"
        self.assertTrue(
            readme.is_file(),
            "corpus/README.md explains how to add a case; keep it next to "
            "the samples")

    def test_both_directories_are_described_in_the_readme(self):
        text = (CORPUS / "README.md").read_text(encoding="utf-8")
        self.assertIn("must_block", text)
        self.assertIn("must_pass", text)


if __name__ == "__main__":
    unittest.main()
