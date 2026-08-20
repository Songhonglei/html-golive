"""Leak regressions from an external audit of 0.9.1.

Two disclosures that the whole existing suite passed over, which is the part
worth keeping in mind: 1013 tests were green while both of these were live.
Every earlier leak test asserted on a *whole* credential, so a redactor that
emitted most of one looked correct.

So the assertions here walk every substring of the secret and reject any run
found beyond the prefix the design deliberately keeps. Concretely: redaction
is allowed to print a recognisable prefix plus a few characters
(``AKIA****``, ``eyJhbGc****``) — that is what makes a refusal identifiable —
and nothing from the tail. `_TAIL_START` is where "identifiable" ends and
disclosure begins.

Both bugs were character-class or ordering mistakes that read correctly:

* the DSN tail class excluded ``@``, so the engine backtracked the secret to
  the *first* ``@`` and left the rest of the password in the clear. Five
  variations of this one mistake have now shipped.
* the JWT value class omitted ``.``, so redaction stopped at the first dot and
  the payload and signature segments came through untouched. The neighbouring
  ``Bearer`` pass had the dot, so a token behind ``Bearer`` was fine while a
  bare one leaked — an asymmetry that survives review because both lines look
  right on their own.
* findings were truncated to 48 characters *before* redaction, and a JWT cut
  at 48 is no longer three dot-separated segments, so the JWT branch never
  fired. Truncation is not redaction.
"""

from __future__ import annotations

import importlib
import os
import unittest

# A JWT-shaped value: three base64url segments. Not a real token.
FAKE_JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkZha2UifQ"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c")

FAKE_SECRETS = {
    "jwt": FAKE_JWT,
    "aws": "AKIAIOSFODNN7EXAMPLE",
    "openai": "sk-abc123def456ghi789jkl012mno345pq",
    "github": "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
    "pypi": "pypi-AgEIcHlwaS5vcmcCJDExMTExMTEx",
}

# Passwords whose @ sits at different offsets — the DSN bug only showed up
# when the password contained one, and only past that point.
FAKE_DSN_PASSWORDS = (
    "Pa@ss:w/o!rd$123",
    "xY@9:z/A!b$Qw7",
    "T0k3n@Sec:re/t!V$al",
    "a@b@c@d:e",
    "P@ss!w0rd$x",
    "plain123456",
)

#: Offset past which any run of secret characters is a disclosure.
#: Redaction keeps a prefix plus about four characters on purpose; beyond
#: twelve there is no legitimate reason for the original to appear.
_TAIL_START = 12

#: Shortest run counted as a leak. Six, not the whole value: the audit found
#: 48 characters of a JWT and 9 of a password, both of which a whole-value
#: assertion waves through.
_RUN = 6


def _reload_scanner(mode: str):
    os.environ["GOLIVE_LANG"] = "en"
    os.environ["GOLIVE_REDACT_MODE"] = mode
    import golive.config as config
    config._current = None
    import golive.security.scanner as scanner
    importlib.reload(scanner)
    return scanner


def _report_text(scanner, html: str) -> str:
    """Everything a user or the scan history would see for this page."""
    result = scanner.scan_html(html, scanner.load_rules())
    return " ".join("%s %s" % (d.get("keyword", ""), d.get("context", ""))
                    for d in result.matched_details)


class _LeakAssertions(unittest.TestCase):

    def assert_tail_absent(self, secret: str, text: str, where: str):
        for start in range(_TAIL_START, len(secret) - _RUN + 1):
            run = secret[start:start + _RUN]
            self.assertNotIn(
                run, text,
                "%s disclosed %r — %d characters of the secret starting at "
                "offset %d. Redaction may keep a prefix; it may not keep the "
                "tail.\nsecret: %r\noutput: %r"
                % (where, run, _RUN, start, secret, text))


class TestJwtIsRedactedInEveryLayout(_LeakAssertions):
    """GLV-091-02: 48 characters of a JWT reached the BLOCK line."""

    LAYOUTS = {
        "bare": '<script>const x="%s";</script>',
        "bearer": '<script>const a="Bearer %s";</script>',
        "assigned": '<script>const token = "%s";</script>',
        # The layout from the audit: four credentials in one script, separated
        # only by JavaScript syntax, so each finding's context window overlaps
        # its neighbours.
        "crowded": ('<script>const p="mysql://u:P@s!x@h.test:3306/a";'
                    'const a="%s";const w="AKIAIOSFODNN7EXAMPLE";'
                    'const k="sk-abc123def456ghi789jkl012mno345pq";</script>'),
    }

    def test_no_jwt_tail_in_any_mode_or_layout(self):
        for mode in ("locator", "strict"):
            scanner = _reload_scanner(mode)
            for name, template in self.LAYOUTS.items():
                with self.subTest(mode=mode, layout=name):
                    text = _report_text(
                        scanner,
                        "<html><body>%s</body></html>" % (template % FAKE_JWT))
                    self.assert_tail_absent(FAKE_JWT, text,
                                            "%s/%s" % (mode, name))

    def test_signature_segment_specifically(self):
        """The third segment is the part that authenticates the token."""
        signature = FAKE_JWT.rsplit(".", 1)[1]
        for mode in ("locator", "strict"):
            scanner = _reload_scanner(mode)
            with self.subTest(mode=mode):
                text = _report_text(
                    scanner,
                    '<html><body><script>const x="%s";</script></body></html>'
                    % FAKE_JWT)
                self.assertNotIn(
                    signature, text,
                    "the JWT signature segment appeared in full")
                self.assert_tail_absent(signature, text, mode)

    def test_jwt_is_still_blocked(self):
        scanner = _reload_scanner("locator")
        result = scanner.scan_html(
            '<html><body><script>const x="%s";</script></body></html>'
            % FAKE_JWT, scanner.load_rules())
        self.assertTrue(result.blocked, "a JWT must still stop the publish")


class TestDsnPasswordTailIsRedacted(_LeakAssertions):
    """GLV-091-01: the password past its first @ stayed in clear text."""

    def test_no_password_tail_across_at_positions(self):
        for mode in ("locator", "strict"):
            scanner = _reload_scanner(mode)
            for password in FAKE_DSN_PASSWORDS:
                dsn = "mysql://tester:%s@db.example.test:3306/app" % password
                for shape, fragment in (
                    ("bare", dsn),
                    ("assigned", 'const password = "%s";' % dsn),
                    ("json", '{"db": "%s"}' % dsn),
                    ("yaml", "dsn: %s" % dsn),
                ):
                    with self.subTest(mode=mode, password=password,
                                      shape=shape):
                        text = _report_text(
                            scanner,
                            "<html><body><script>%s</script></body></html>"
                            % fragment)
                        # Passwords are short, so check from offset 0 here:
                        # none of a password is a legitimate locator.
                        for start in range(0, len(password) - 4 + 1):
                            run = password[start:start + 4]
                            self.assertNotIn(
                                run, text,
                                "%s/%s leaked %r from password %r\noutput: %r"
                                % (mode, shape, run, password, text))

    def test_locator_still_identifies_the_connection(self):
        """Redaction has to stay useful, or people will disable it."""
        scanner = _reload_scanner("locator")
        text = _report_text(
            scanner,
            '<html><body><script>mysql://tester:Pa@ss:w/o!rd$123'
            '@db.example.test:3306/app</script></body></html>')
        self.assertIn("db.example.test", text,
                      "locator mode must still say which host it was")

    def test_strict_withholds_the_host(self):
        scanner = _reload_scanner("strict")
        text = _report_text(
            scanner,
            '<html><body><script>mysql://tester:Pa@ss:w/o!rd$123'
            '@db.example.test:3306/app</script></body></html>')
        self.assertNotIn("db.example.test", text,
                         "strict mode must not disclose the host")


class TestTruncationHappensAfterRedaction(unittest.TestCase):
    """The ordering bug behind GLV-091-02, pinned directly.

    Slicing a credential before redacting it can destroy the shape the
    redactor matches on, and then nothing is redacted at all. Asserting on
    the ordering rather than only on the outcome, because the outcome test
    above would still pass if someone reintroduced the slice at a length that
    happens to keep a JWT intact.
    """

    def test_findings_are_not_sliced_before_redaction(self):
        import inspect
        import golive.security.scanner as scanner
        source = inspect.getsource(scanner)
        offenders = [
            "_mask_secret_literal(m.group(0)[:",
            "_mask_secret_literal(match.group(0)[:",
        ]
        for bad in offenders:
            self.assertNotIn(
                bad, source,
                "a finding is sliced before redaction (%r): truncation "
                "destroys the shape the redactor recognises, which is how 48 "
                "characters of a JWT reached the BLOCK line in 0.9.1" % bad)

    def test_redacting_a_full_jwt_masks_every_segment(self):
        scanner = _reload_scanner("locator")
        masked = scanner._mask_secret_literal(FAKE_JWT)
        for index, segment in enumerate(FAKE_JWT.split(".")):
            with self.subTest(segment=index):
                self.assertNotIn(
                    segment, masked,
                    "segment %d of the JWT survived redaction" % index)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
