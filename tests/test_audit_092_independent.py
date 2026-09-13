"""Leak regressions from the independent black-box audit of 0.9.2.

The audit found that both P0 disclosures shared one structure with the 0.9.1
findings: the suite asserted on *whole* credentials while the failure mode
was a *clipped fragment* of one. These tests pin the exact layouts the audit
measured, at the audit's own disclosure bar (runs of >= 6 secret characters
count; the redactor deliberately keeps short identifying prefixes).

* GLV-092-01 — a context window cut mid-DSN-password left 15–21 characters
  after the password's internal ``@`` in clear text. Two causes stacked: the
  page-secret extraction stopped at the first ``@`` (so only the fragment
  before it was known to the scrubber), and the scrubber only removed *suffixes*
  of known values — a window clipped at both ends holds a middle.
* GLV-092-02 — a context window starting partway into a JWT's 43-character
  signature carried the signature's last 3–9 characters, because the suffix
  loop only chased tails of >= 12 characters.
* GLV-092-03 — strict mode's ``****#fingerprint`` tag was re-masked on its way
  into the scan history, producing a *different* fingerprint from a different
  canonical. The tag exists to recognise the same credential across surfaces.
* GLV-092-04 — the sdist omitted ``tests/__init__.py``, ``fake_idp.py`` and
  ``fake_postgrest.py``, so the suite could not even be collected from the
  published archive.
* GLV-093-01 (audit of 0.9.3) — the fix for GLV-092-04 over-shot: the same
  data-files entries that fed the sdist also landed 52 test assets in the
  wheel's ``.data/data/tests/``, violating the runtime-only promise. The
  0.9.3 wheel gate checked ``startswith('tests/')`` — a prefix assertion
  about where pollution was expected, not an exhaustive check of where it
  could be. Test assets now reach the sdist via MANIFEST.in (which never
  feeds the wheel), and the gate checks every path segment.
"""

from __future__ import annotations

import base64
import os
import tarfile
import unittest

from tests.test_audit_0911_leaks import (
    _reload_scanner, _report_text, _LeakAssertions,
)

#: The 0911 helper reloads the config singleton under whatever mode it is
#: handed and leaves the environment that way. Its own suite ends on
#: ``locator``; ending on ``strict`` here poisoned every later test that
#: reads the ambient redaction mode through the reloaded config — the same
#: module object, one shared process. Restore in tearDown, not by ordering.
_REDACT_BEFORE = os.environ.get("GOLIVE_REDACT_MODE")


def _restore_redact_mode():
    if _REDACT_BEFORE is None:
        os.environ.pop("GOLIVE_REDACT_MODE", None)
    else:
        os.environ["GOLIVE_REDACT_MODE"] = _REDACT_BEFORE
    import golive.config as config
    config._current = None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


#: A standard HS256 JWT: 36-char header, 56-char payload, 43-char signature.
#: The signature length is what RFC 7515 produces for HMAC-SHA256; the audit
#: measured the leak specifically against this shape.
FAKE_JWT = "%s.%s.%s" % (
    _b64(b'{"alg":"HS256","typ":"JWT"}'),
    _b64(b'{"sub":"1234567890","name":"John Doe","iat":1516239022}'),
    "TJVA95OrM7E2cBab30RMHrHDcEfxjoYZgeFONFh7HgQ",
)

#: 25 characters with an internal @ at offset 7 — long enough that a
#: 30-character window cut from the scheme keyword ends mid-password.
FAKE_PW = "SecretP@ssw0rdXXXXXXXXXXXX"

#: The disclosure bar the audit used: any run of >= 6 consecutive characters
#: of the secret. (The redactor keeps short identifying prefixes on purpose;
#: four is the floor the scrubber chases fragments down to.)
_RUN = 6


class TestDsnPasswordMiddleIsRedacted(_LeakAssertions):
    """GLV-092-01: the clipped middle of a password leaked."""

    def tearDown(self):
        _restore_redact_mode()

    def test_window_cut_mid_password(self):
        """The audit layout: scheme keyword window ends inside the password.

        The keyword rule's window is [hit-30, hit+len+30] around the
        ``postgres://`` keyword, so the window ends 30 characters past the
        scheme — inside a 25-character password — and the text after the
        password's internal @ came through unredacted.
        """
        for mode in ("locator", "strict"):
            scanner = _reload_scanner(mode)
            with self.subTest(mode=mode):
                dsn = "postgres://user:%s@db.internal.example.com/main" % FAKE_PW
                text = _report_text(
                    scanner,
                    "<html><body>config = %s</body></html>" % dsn)
                # None of a password is a legitimate locator: check every
                # >= 4-character run from offset 0.
                for start in range(0, len(FAKE_PW) - 3):
                    run = FAKE_PW[start:start + 4]
                    self.assertNotIn(
                        run, text,
                        "%s leaked %r (4 chars from offset %d) of the "
                        "password\noutput: %r" % (mode, run, start, text))

    def test_page_secret_extraction_uses_last_at(self):
        """The extraction feeding the scrubber must know the whole password.

        Not an outcome assertion: the 0.9.2 leak survived *because* the page
        set only held the fragment before the first @, so the scrubber had
        no way to know the rest was secret. Pin the extraction itself.
        """
        scanner = _reload_scanner("locator")
        dsn = "postgres://user:%s@db.internal.example.com/main" % FAKE_PW
        values = scanner._secret_values_in(dsn, scanner.load_rules())
        self.assertIn(FAKE_PW, values,
                      "the full password must be extracted; got %r" % (values,))


class TestJwtSignatureTailIsRedacted(_LeakAssertions):
    """GLV-092-02: the signature's last characters leaked via a window."""

    def tearDown(self):
        _restore_redact_mode()

    def test_assignment_window_overlapping_signature(self):
        """A credential assignment whose window starts inside the signature.

        The ``password: "…"`` regex rule fires after the JWT; its 30-character
        lead-in starts 3–9 characters before the JWT ends, so the window opens
        mid-signature and the suffix loop (>= 12 chars only) let the tail
        through. Sweep the gap so every alignment is covered.
        """
        signature = FAKE_JWT.rsplit(".", 1)[1]
        for mode in ("locator", "strict"):
            scanner = _reload_scanner(mode)
            for gap in range(0, 40):
                with self.subTest(mode=mode, gap=gap):
                    filler = "y" * gap
                    html = ('<html><body>Bearer %s %s password: '
                            '"hunter2secret"</body></html>'
                            % (FAKE_JWT, filler))
                    text = _report_text(scanner, html)
                    for start in range(0, len(signature) - _RUN + 1):
                        run = signature[start:start + _RUN]
                        self.assertNotIn(
                            run, text,
                            "%s/gap=%d disclosed %r of the JWT signature"
                            % (mode, gap, run))


class TestStrictFingerprintIsStable(unittest.TestCase):
    """GLV-092-03: strict fingerprints must survive the history re-mask."""

    def tearDown(self):
        _restore_redact_mode()

    def test_history_fingerprint_matches_cli(self):
        import re

        from golive.backends.registry.scans_store import _redact_findings
        scanner = _reload_scanner("strict")
        dsn = "postgres://user:StrictP@ssw0rdZZZZZZ@db.example.com/main"
        result = scanner.scan_html(
            "<html><body>config = %s</body></html>" % dsn,
            scanner.load_rules())
        cli_text = " ".join(d.get("keyword", "") for d in result.matched_details)
        stored = _redact_findings(result.matched_details)
        db_text = " ".join(f["keyword"] for f in stored)
        cli_fps = set(re.findall(r"#([0-9a-f]{8})", cli_text))
        db_fps = set(re.findall(r"#([0-9a-f]{8})", db_text))
        self.assertTrue(cli_fps, "strict mode should tag the credential")
        self.assertEqual(
            cli_fps, db_fps,
            "the scan history fingerprint must equal the CLI fingerprint — "
            "the tag exists to recognise the same credential across surfaces")


class TestSdistShipsTestHelpers(unittest.TestCase):
    """GLV-092-04: the sdist must collect its own suite."""

    def test_helper_files_in_sdist(self):
        """The three helpers the audit found missing.

        Skipped when the sdist is not built (running from a checkout): the
        check only means something against the built archive.
        """
        import glob
        sdists = sorted(
            glob.glob(os.path.join(
                os.path.dirname(__file__), "..", "dist", "*.tar.gz")),
            key=os.path.getmtime)
        if not sdists:
            self.skipTest("no sdist built next to the checkout")
        newest = sdists[-1]
        names = set()
        with tarfile.open(newest) as tar:
            for n in tar.getnames():
                names.add(n.split("/", 1)[1] if "/" in n else n)
        for helper in ("tests/__init__.py",
                       "tests/fake_idp.py",
                       "tests/fake_postgrest.py"):
            self.assertIn(
                helper, names,
                "%s missing from %s — the suite cannot be collected from "
                "the archive" % (helper, os.path.basename(newest)))


class TestWheelStaysRuntimeOnly(unittest.TestCase):
    """GLV-093-01: no test asset may reach the wheel, at any path depth."""

    def test_wheel_has_no_tests_at_any_depth(self):
        """Every member path is checked, not just the top-level layout.

        The 0.9.3 gate asserted ``startswith('tests/')`` and the pollution
        lived at ``html_golive-0.9.3.data/data/tests/`` — a prefix check
        about the expected shape of a violation cannot catch a violation of
        a different shape. The auditor's check walks every path segment.
        """
        from pathlib import Path, PurePosixPath
        from zipfile import ZipFile

        wheels = sorted(Path(__file__).parent.parent.glob("dist/*.whl"),
                        key=lambda p: p.stat().st_mtime)
        if not wheels:
            self.skipTest("no wheel built next to the checkout")
        with ZipFile(wheels[-1]) as archive:
            unexpected = [
                name for name in archive.namelist()
                if "tests" in PurePosixPath(name).parts]
        self.assertEqual(
            unexpected, [],
            "test assets must not ship in the wheel: %r" % (unexpected,))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
