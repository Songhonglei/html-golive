"""Credential findings block the publish, and no flag waives them.

Two rules, decided in v0.8.2:

* **strong** findings — a literal secret (private key, DSN, ``AKIA…``,
  18-digit national ID) — always block. ``--skip-scan`` and
  ``--skip-content-scan`` do not apply. A page carrying a live credential is
  not a false positive worth arguing about.
* **weak** findings — nouns that merely suggest sensitive content ("salary",
  "token") — warn, and ``--skip-content-scan`` silences them.

``--skip-scan`` used to skip *everything*, credentials included. It is still
accepted, now meaning the same as ``--skip-content-scan``.

The other half of this is redaction: a finding is printed to stderr and can
end up in CI logs or a screenshot, so the secret must not travel with it.
Truncating to N characters is not redaction — the first 24 characters of a
DSN are the password.
"""
from __future__ import annotations

import contextlib
import io
import unittest

from golive.security.scanner import run_scan

# Assembled at runtime so this test file is not itself a scanner hit.
_PRIVATE_KEY = "-----BEGIN" + " RSA PRIVATE KEY-----"

STRONG_PAGES = {
    "private key": f"<p>{_PRIVATE_KEY}\nMIIEvQIBADANBg</p>",
    "jdbc dsn": "<p>jdbc:mysql://db.internal:3306/app</p>",
    "mongodb dsn": "<p>mongodb://root:pw@10.1.1.1:27017</p>",
    "redis dsn": "<p>redis://:passw0rd@cache:6379/0</p>",
    "postgres dsn": "<p>postgres://u:p@h:5432/d</p>",
    "mysql dsn": "<p>mysql://u:p@h:3306/d</p>",
    "aws access key": "<p>AKIAIOSFODNN7EXAMPLE</p>",
    "cloud ak/sk": '<p>AccessKeySecret="abcdefghij0123456789xyz"</p>',
    "openai key": "<p>sk-proj0123456789abcdefghijklmn</p>",
    "bearer token": "<p>authorization: Bearer eyJhbGciOiJIUzI1NiJ9</p>",
    "password assignment": "<p>password=Sup3rS3cret!</p>",
    # personal_info by category, but strong by strength: an exact 18-digit
    # match, and publishing one is a real disclosure.
    "national id": "<p>110101199003078515</p>",
}

CLEAN_PAGES = {
    "base64 image": (
        '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'
        'CAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==">'
    ),
    "years": "<p>Revenue in 2026 grew over 1999</p>",
    "css and ports": "<style>.a{padding:12px}</style><p>listens on 8787</p>",
    "url encoded": "<p>%E4%B8%AD%E6%96%87%20%3D%20test</p>",
    "version range": "<p>v0.8.2, supports 3.9~3.12</p>",
    "commit sha": "<p>commit 176baba1a4c9f8e2d3b7a6f5e4d3c2b1a0987654</p>",
    "plain prose": "<h1>Getting Started</h1><p>Publish in 30 seconds.</p>",
}

# Every way a caller could try to wave a finding through.
WAIVERS = [
    ("no flags", {}),
    ("--skip-scan", {"skip_scan": True}),
    ("--skip-content-scan", {"skip_content": True}),
    ("both flags", {"skip_scan": True, "skip_content": True}),
]


def _scan(html: str, **kwargs):
    """run_scan, capturing the stderr report."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        ok, result = run_scan(html, **kwargs)
    return ok, result, buf.getvalue()


class TestCredentialsCannotBeWaived(unittest.TestCase):

    def test_every_strong_finding_blocks_under_every_flag(self):
        for label, page in STRONG_PAGES.items():
            for flag_label, kwargs in WAIVERS:
                with self.subTest(page=label, flags=flag_label):
                    ok, _, _ = _scan(page, **kwargs)
                    self.assertFalse(
                        ok,
                        f"{label} was published with {flag_label} — a literal "
                        f"secret must never be publishable",
                    )

    def test_the_block_message_does_not_offer_a_way_around(self):
        ok, _, report = _scan(STRONG_PAGES["postgres dsn"])
        self.assertFalse(ok)
        self.assertNotIn(
            "--skip-scan", report,
            "the block message still advertises a flag that no longer works",
        )
        self.assertIn("cannot be skipped", report.lower())


class TestContentWarningsAreWaivable(unittest.TestCase):

    CONTENT_PAGE = "<p>本月工资明细与薪酬结构</p>"

    def test_content_only_page_publishes_with_a_warning(self):
        ok, result, report = _scan(self.CONTENT_PAGE)
        self.assertTrue(ok, "weak findings must not block")
        self.assertTrue(result.has_sensitive)
        self.assertFalse(result.strong_hits)

    def test_skip_content_silences_the_warning(self):
        ok, _, report = _scan(self.CONTENT_PAGE, skip_content=True)
        self.assertTrue(ok)
        self.assertIn("waived", report.lower())

    def test_legacy_skip_scan_still_waives_content(self):
        ok, _, report = _scan(self.CONTENT_PAGE, skip_scan=True)
        self.assertTrue(ok)
        self.assertIn("waived", report.lower())

    def test_the_result_is_still_returned_when_waived(self):
        """Waiving the warning must not hide what was found."""
        _, result, _ = _scan(self.CONTENT_PAGE, skip_content=True)
        self.assertIsNotNone(
            result, "callers and the audit trail still need the findings")
        self.assertTrue(result.has_sensitive)


class TestCleanPagesAreNotFlagged(unittest.TestCase):
    """False positives push people towards bypassing the scanner entirely."""

    def test_ordinary_content_publishes_without_a_block(self):
        for label, page in CLEAN_PAGES.items():
            with self.subTest(page=label):
                ok, result, _ = _scan(page)
                self.assertTrue(ok, f"{label} was blocked")
                self.assertFalse(
                    result.strong_hits if result else [],
                    f"{label} produced a credential finding",
                )


class TestSecretsAreRedactedFromTheReport(unittest.TestCase):

    CASES = {
        "dsn password": (
            "s3cretP4ssw0rdDoNotLeak987654321",
            "<p>postgres://admin:s3cretP4ssw0rdDoNotLeak987654321"
            "@10.0.0.5:5432/prod</p>",
        ),
        "openai key": (
            "sk-proj0123456789abcdefghijklmnop",
            "<p>sk-proj0123456789abcdefghijklmnop</p>",
        ),
        "aws key": (
            "AKIAIOSFODNN7EXAMPLE", "<p>AKIAIOSFODNN7EXAMPLE</p>"),
        "bearer token": (
            "eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "<p>authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig</p>",
        ),
        "password value": (
            "Sup3rS3cretValue123", "<p>password=Sup3rS3cretValue123</p>"),
    }

    def test_the_full_secret_never_appears_anywhere_in_the_output(self):
        for label, (secret, page) in self.CASES.items():
            with self.subTest(case=label):
                _, result, report = _scan(page)
                haystack = report + " ".join(
                    f"{d.get('context', '')}{d.get('keyword', '')}"
                    for d in (result.matched_details if result else [])
                )
                self.assertNotIn(
                    secret, haystack,
                    f"the {label} travelled into the report verbatim",
                )

    def test_redaction_keeps_the_finding_locatable(self):
        """Over-redacting is its own failure — the user must find the line."""
        _, result, report = _scan(self.CASES["dsn password"][1])
        self.assertIn("postgres://", report)
        self.assertIn("10.0.0.5", report, "the host was redacted away too")
        self.assertIn("****", report)


if __name__ == "__main__":
    unittest.main()


class TestPlaceholdersAreExemptWithoutOpeningABypass(unittest.TestCase):
    """`password=***` in a guide is documentation, not a leak.

    Blocking setup documentation is how people learn to publish with the scan
    waived — and that habit is what lets a real secret through later. So a
    credential keyword followed only by a placeholder is allowed.

    The exemption has to match the *whole* value. Accepting a mere prefix
    would be a bypass: `password=xxxRealSecret` would read as a placeholder
    and publish the secret sitting right behind it.
    """

    PLACEHOLDERS = (
        "<p>password=***</p>",
        "<p>password=</p>",
        "<p>password=$DB_PASSWORD</p>",
        "<p>token: {{ api_token }}</p>",
        '<p>secret_key = "REPLACE_ME"</p>',
        "<p>api_key=your-api-key</p>",
        # As written in an HTML guide, entity-encoded.
        "<p>API_KEY=&lt;your-key-here&gt;</p>",
    )

    DISGUISED = (
        # Each starts with something placeholder-shaped, then a real secret.
        "<p>password=xxxRealSecret999</p>",
        "<p>password=***RealSecret999</p>",
        "<p>password=changemeRealSecret9</p>",
        "<p>api_key=your-key api_key=sk-abcdefghij0123456789</p>",
        "<p>password=*** password=RealSecret123456</p>",
    )

    def test_documentation_placeholders_publish(self):
        for page in self.PLACEHOLDERS:
            with self.subTest(page=page):
                ok, _, _ = _scan(page)
                self.assertTrue(ok, f"a placeholder was treated as a secret")

    def test_a_secret_hiding_behind_a_placeholder_still_blocks(self):
        for page in self.DISGUISED:
            with self.subTest(page=page):
                ok, _, _ = _scan(page)
                self.assertFalse(
                    ok,
                    "prefixing a secret with placeholder text bypassed the "
                    "scanner",
                )

    def test_the_exemption_does_not_reach_other_rule_types(self):
        """Only strong credential keywords; DSNs and key files are untouched."""
        for page in ("<p>postgres://u:realpw123@h:5432/d</p>",
                     "<pre>" + "-----BEGIN" + " RSA PRIVATE KEY-----</pre>"):
            with self.subTest(page=page[:40]):
                ok, _, _ = _scan(page)
                self.assertFalse(ok)
