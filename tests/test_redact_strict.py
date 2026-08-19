"""``security.redact_mode: strict`` — withhold the locator metadata too.

The default keeps scheme, user, host, port and path so a refusal says which
credential to fix. An audit pointed out that those are not secret but can
still name internal topology, a tenant, or a person — and that a refusal
captured into a shared CI log carries them along. strict trades away that
convenience.

What it must not do is trade away the ability to tell two credentials apart,
which is why the fingerprint exists and why it is tested for stability.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("GOLIVE_LANG", "en")

from golive.security import scanner  # noqa: E402

DSN = "mysql://tester:P@ss!w0rd$x@db.example.test:3306/app"
DSN_PAGE = "<html><body><p>{dsn}</p></body></html>".format(dsn=DSN)

#: Parts of the DSN that strict withholds and the default keeps.
LOCATOR_PARTS = ["db.example.test", "tester", "/app", "3306"]

#: The secret itself — neither mode may ever show this.
SECRET = "P@ss!w0rd$x"


class _ModeCase(unittest.TestCase):

    def _report(self, html, mode):
        previous = os.environ.get("GOLIVE_REDACT_MODE")
        os.environ["GOLIVE_REDACT_MODE"] = mode
        try:
            import golive.config as config
            config._current = None
            result = scanner.scan_html(html, scanner.load_rules())
            return "\n".join(
                "{k} {c}".format(k=d.get("keyword", ""),
                                 c=d.get("context", ""))
                for d in result.matched_details), result
        finally:
            if previous is None:
                os.environ.pop("GOLIVE_REDACT_MODE", None)
            else:
                os.environ["GOLIVE_REDACT_MODE"] = previous
            import golive.config as config
            config._current = None


class TestStrictWithholdsLocatorMetadata(_ModeCase):

    def test_strict_removes_what_locator_keeps(self):
        strict, _ = self._report(DSN_PAGE, "strict")
        for part in LOCATOR_PARTS:
            with self.subTest(part=part):
                self.assertNotIn(
                    part, strict,
                    "strict mode still shows connection metadata")

    def test_locator_mode_still_keeps_it(self):
        """Paired with the test above, so neither can pass by doing nothing.

        If strict were accidentally applied always, the assertion above would
        still pass while the feature silently became mandatory.
        """
        located, _ = self._report(DSN_PAGE, "locator")
        self.assertIn(
            "db.example.test", located,
            "the default mode dropped the host; strict is leaking into it")

    def test_neither_mode_shows_the_password(self):
        for mode in ("locator", "strict"):
            with self.subTest(mode=mode):
                report, _ = self._report(DSN_PAGE, mode)
                self.assertNotIn(SECRET, report)

    def test_both_modes_still_block(self):
        """Redaction changes the report, never the verdict."""
        for mode in ("locator", "strict"):
            with self.subTest(mode=mode):
                _report, result = self._report(DSN_PAGE, mode)
                self.assertTrue(result.blocked)

    def test_strict_reports_a_line_number_instead_of_context(self):
        """Withholding context must not leave someone unable to find it."""
        page = ("<html><body>\n<p>ordinary text</p>\n<p>{dsn}</p>\n"
                "</body></html>").format(dsn=DSN)
        strict, _ = self._report(page, "strict")
        self.assertIn("line 3", strict)
        self.assertNotIn("ordinary text", strict)


class TestFingerprintsStayUseful(_ModeCase):

    def test_one_credential_gets_one_fingerprint(self):
        """Several rules match the same DSN with different extents.

        Fingerprinting the matched span gave a single connection string more
        than one tag in the same report, which defeats the only purpose the
        tag has.

        The page matters here. A bare DSN is matched by rules whose spans
        happen to agree, so it produces one tag either way — the first version
        of this test used one and stayed green with the fix reverted. A DSN
        inside a credential assignment is matched at two different extents,
        which is what makes the difference observable.
        """
        import re

        page = ('<html><body><script>const db_password = "{dsn}";'
                "</script></body></html>").format(dsn=DSN)
        strict, _ = self._report(page, "strict")
        tags = set(re.findall(r"#([0-9a-f]{8})", strict))
        self.assertEqual(
            len(tags), 1,
            "one credential produced {n} fingerprints: {tags}".format(
                n=len(tags), tags=sorted(tags)))

    def test_different_credentials_get_different_fingerprints(self):
        import re

        other = DSN.replace("P@ss!w0rd$x", "C0mpletely!different")
        page = ("<html><body><p>{a}</p><p>{b}</p></body></html>"
                .format(a=DSN, b=other))
        strict, _ = self._report(page, "strict")
        tags = set(re.findall(r"#([0-9a-f]{8})", strict))
        self.assertGreaterEqual(
            len(tags), 2,
            "two different credentials collapsed to one tag, so a log cannot "
            "tell them apart")

    def test_the_same_credential_fingerprints_the_same_way_twice(self):
        """Stable across runs, or a repeated refusal looks like a new one."""
        import re

        first, _ = self._report(DSN_PAGE, "strict")
        second, _ = self._report(DSN_PAGE, "strict")
        self.assertEqual(
            set(re.findall(r"#([0-9a-f]{8})", first)),
            set(re.findall(r"#([0-9a-f]{8})", second)))

    def test_the_fingerprint_does_not_contain_the_secret(self):
        tag = scanner._fingerprint(SECRET)
        self.assertNotIn(SECRET, tag)
        self.assertEqual(len(tag), 8)


class TestModeConfiguration(unittest.TestCase):

    def test_default_is_locator(self):
        from golive.config import SecurityConfig
        self.assertEqual(SecurityConfig().redact_mode, "locator")

    def test_an_unknown_mode_is_refused_not_downgraded(self):
        """A typo in a setting that reduces exposure must not be forgiven.

        Falling back to the default would hand someone who asked for strict a
        weaker mode without telling them.
        """
        from golive.config import ConfigError, REDACT_MODES
        self.assertIn("strict", REDACT_MODES)
        previous = os.environ.get("GOLIVE_REDACT_MODE")
        os.environ["GOLIVE_REDACT_MODE"] = "strictt"
        try:
            import golive.config as config
            config._current = None
            with self.assertRaises(ConfigError):
                config.get_config()
        finally:
            if previous is None:
                os.environ.pop("GOLIVE_REDACT_MODE", None)
            else:
                os.environ["GOLIVE_REDACT_MODE"] = previous
            import golive.config as config
            config._current = None


if __name__ == "__main__":
    unittest.main()
