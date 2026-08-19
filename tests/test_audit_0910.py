"""Regressions for the three defects an external audit of 0.9.0 confirmed.

The audit report itself is worth more than its conclusions: one of its four
findings (token auth not taking effect) turned out to be caused by *our own
test brief*, which named an environment variable the code has never read —
``GOLIVE_ADMIN_TOKEN`` instead of ``GOLIVE_TOKEN``. Chasing that down is what
surfaced the real problem behind it, covered here as
:class:`TestTokenEnvNameIsNotSilentlyIgnored`: a misspelled token variable is
indistinguishable from "no auth configured", so an operator who typos it gets
a server they believe is protected.

Each class below states the defect in terms of the behaviour a user would
notice, so that reverting the fix fails for a legible reason.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest


class _Match:
    """Minimal stand-in for an re match, for calling redaction directly."""

    def __init__(self, text: str):
        self._text = text

    def group(self, _i=0):
        return self._text


class TestScanSummaryHasNoFindings(unittest.TestCase):
    """GLV-090-02: the site detail API returned every scan finding verbatim.

    ``findings`` entries carry a ``context`` window — an excerpt of the page
    around the hit. The secret inside it is redacted, but it is still page
    content, and this endpoint's job is to say whether a page was checked and
    how it came back, which needs a verdict and a count.

    The portal only ever rendered the count, so no amount of clicking through
    the UI would have shown this. Restraint in the front end is not restraint
    in the API.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["GOLIVE_HOME"] = self.tmp
        os.environ["GOLIVE_LANG"] = "en"
        from golive.core import paths
        paths.reset_cache()
        from golive.backends.registry import scans_store, sqlite_manifest
        scans_store.reset_cache()
        sqlite_manifest.reset_cache()

    def _site_with_scan(self):
        from golive.backends.registry.scans_store import get_scans_store
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        reg = SqliteRegistry()
        storage = LocalStorage()
        site = reg.create(name="W", slug="w1")
        storage.publish("<html><body>hi</body></html>", site["site_id"],
                        backup_previous=False)
        get_scans_store().record(
            site_id=site["site_id"], verdict="warn", content_sha256="a" * 64,
            findings=[{"name": "personal info", "keyword": "salary",
                       "context": "...UNIQUE_PAGE_EXCERPT_7f3a...",
                       "strength": "weak", "type": "personal_info"}])
        return reg, storage, site

    def _detail(self):
        from golive.server import admin_api
        from golive.server.authz import Identity
        reg, storage, _site = self._site_with_scan()
        _st, payload = admin_api.handle(
            "GET", "/api/admin/sites/w1", {}, b"",
            Identity(email="a@b.test", is_superadmin=True), reg, storage)
        return payload

    def test_findings_key_is_absent(self):
        scan = self._detail()["scans"][0]
        self.assertNotIn(
            "findings", scan,
            "scan records in the detail API must not carry findings; "
            "got keys: %s" % sorted(scan))

    def test_page_excerpt_does_not_appear_anywhere_in_payload(self):
        # Asserted against the whole payload, not just the scans list: a
        # future field could carry the excerpt somewhere else and a
        # scans-only assertion would pass while the leak stayed.
        payload = self._detail()
        self.assertNotIn(
            "UNIQUE_PAGE_EXCERPT_7f3a", str(payload),
            "the scan context excerpt reached the API response")

    def test_verdict_and_count_survive(self):
        scan = self._detail()["scans"][0]
        self.assertEqual(scan.get("verdict"), "warn")
        self.assertEqual(
            scan.get("finding_count"), 1,
            "dropping findings must not also drop the count the portal shows")

    def test_three_record_keys_still_always_present(self):
        payload = self._detail()
        for key in ("manifest", "policy", "scans"):
            self.assertIn(key, payload,
                          "%s must be present even when absent in storage" % key)

    def test_portal_reads_the_count_field_that_the_api_sends(self):
        """The API and the portal have to agree on the field name.

        Renaming the field server-side while the portal still reads
        ``findings.length`` would show 0 findings forever — green tests, wrong
        number on screen.
        """
        from golive.server import admin_ui
        page = admin_ui.render_admin_page()
        self.assertIn("finding_count", page,
                      "portal must read finding_count from the API")


class TestDsnLocatorSurvivesAssignment(unittest.TestCase):
    """GLV-090-03 (partial): a DSN inside a ``password = "..."`` assignment.

    The same DSN is matched both by the connection-string rule and by the
    broad credential-assignment rule. Redaction anchored its DSN pattern at
    position 0, so for the assignment match — which starts at ``password = "``
    — the DSN went unrecognised and the whole span collapsed to ``my****``.
    Nothing leaked; what was lost was the host, user and port that tell a
    reader which of their connection strings to go fix.

    Fixing this re-introduced a *leak* on the first attempt: the secret group
    excluded ``@``, so a password containing one was cut short and its tail
    stayed in clear text. That is the fourth time this character class has
    been got wrong in this file, which is why the leak assertions here run
    across password shapes rather than the single shape being fixed.
    """

    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        os.environ.pop("GOLIVE_REDACT_MODE", None)
        import golive.config as C
        C._current = None

    PASSWORDS = ("P@ss!w0rd$x", "simple123", "a@b@c@d", "Xk9mQ2vLp8wRtY",
                 "with:colon", "trailing@")

    def test_locator_kept_for_bare_dsn_and_common_wrappers(self):
        import golive.security.scanner as S
        host = "db.example.test"
        for body in (
            'mysql://tester:P@ss!w0rd$x@%s:3306/app' % host,
            '{"db_password": "mysql://tester:P@ss!w0rd$x@%s:3306/app"}' % host,
            'dsn: mysql://tester:P@ss!w0rd$x@%s:3306/app' % host,
        ):
            with self.subTest(body=body[:40]):
                result = S.scan_html(
                    "<html><body><script>%s</script></body></html>" % body,
                    S.load_rules())
                blob = " ".join(
                    "%s %s" % (d.get("keyword", ""), d.get("context", ""))
                    for d in result.matched_details)
                self.assertIn(host, blob,
                              "locator lost: a refusal has to say which "
                              "connection string it was about")

    #: Shortest run of password characters that counts as a leak.
    #:
    #: Asserting on the *whole* password is the trap this file exists to
    #: avoid, and the first version of this test fell into it: the broken
    #: regex stopped at the first ``@``, so it emitted
    #: ``mysql://****@ss!w0rd$x@host`` — the password minus its first
    #: character. ``assertNotIn(pw, ...)`` passed with the tail sitting in
    #: plain view. A partial credential is still a credential.
    LEAK_SUBSTRING_LEN = 5

    def _assert_no_leak(self, password: str, text: str, where: str):
        for start in range(0, max(1, len(password) - self.LEAK_SUBSTRING_LEN + 1)):
            chunk = password[start:start + self.LEAK_SUBSTRING_LEN]
            if len(chunk) < self.LEAK_SUBSTRING_LEN:
                break
            self.assertNotIn(
                chunk, text,
                "%s leaked %r — a %d-char run of the password %r survived: %r"
                % (where, chunk, self.LEAK_SUBSTRING_LEN, password, text))

    def test_no_password_leaks_across_password_shapes(self):
        """The guard that matters most: the fix must not become a leak."""
        import golive.security.scanner as S
        rules = S.load_rules()
        for pw in self.PASSWORDS:
            dsn = "mysql://tester:%s@db.example.test:3306/app" % pw
            for label, frag in (("bare", dsn),
                                ("assigned", 'const password = "%s";' % dsn)):
                with self.subTest(pw=pw, shape=label):
                    # Direct call: the redaction primitive itself, not just
                    # the assembled report, so a leak cannot hide behind a
                    # later scrubbing pass that happens to catch it.
                    self._assert_no_leak(
                        pw, S._keep_shape_drop_value(_Match(frag)),
                        "shape redaction")
                    result = S.scan_html(
                        "<html><body><script>%s</script></body></html>" % frag,
                        rules)
                    blob = " ".join(
                        "%s %s" % (d.get("keyword", ""), d.get("context", ""))
                        for d in result.matched_details)
                    self._assert_no_leak(pw, blob, "scan report")

    def test_dsn_is_still_blocked(self):
        import golive.security.scanner as S
        result = S.scan_html(
            '<html><body><script>const password = '
            '"mysql://t:P@ss!w0rd$x@db.example.test:3306/app";</script>'
            '</body></html>', S.load_rules())
        self.assertTrue(result.blocked,
                        "improving the message must not stop the refusal")


class TestDoctorRejectsEmptySiteRef(unittest.TestCase):
    """GLV-090-04: ``doctor --site ''`` silently ran the whole-install check.

    An empty string is falsy, so a script whose variable interpolation failed
    got exit 0 and a healthy-looking report for a site that was never looked
    at — the worst shape for a check to fail in.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["GOLIVE_HOME"] = self.tmp
        os.environ["GOLIVE_LANG"] = "en"
        from golive.core import paths
        paths.reset_cache()

    def _run(self, argv):
        import contextlib
        import io
        from golive import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:  # argparse paths
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_empty_site_ref_is_refused(self):
        code, out, err = self._run(["doctor", "--site", "", "--json"])
        self.assertNotEqual(code, 0,
                            "an empty --site must not exit 0")
        self.assertNotIn(
            "cli_version", out,
            "an empty --site must not fall through to the global report")
        self.assertTrue(err.strip(), "refusal must say what was wrong")

    def test_absent_flag_still_runs_the_global_check(self):
        """The distinction being drawn is absent vs empty, so prove both."""
        code, out, _err = self._run(["doctor", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("cli_version", out,
                      "plain doctor must still report the install")

    def test_whitespace_only_ref_is_refused_too(self):
        code, _out, _err = self._run(["doctor", "--site", "   ", "--json"])
        self.assertNotEqual(code, 0,
                            "a whitespace-only ref is an interpolation "
                            "failure just the same")


class TestTokenEnvNameIsNotSilentlyIgnored(unittest.TestCase):
    """The real defect behind the audit's false positive.

    ``GOLIVE_TOKEN`` enables token auth. Anything else — including the
    plausible-looking ``GOLIVE_ADMIN_TOKEN`` — is not read, and the server
    starts with no auth at all. On loopback that means an unconditional
    superadmin, so the operator gets exactly the access they were trying to
    restrict and no indication that their setting did nothing.

    The auth behaviour itself is correct and is pinned here so that the
    warning added for the typo case cannot drift into changing it.
    """

    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        for key in ("GOLIVE_TOKEN", "GOLIVE_ADMIN_TOKEN"):
            os.environ.pop(key, None)

    def tearDown(self):
        for key in ("GOLIVE_TOKEN", "GOLIVE_ADMIN_TOKEN"):
            os.environ.pop(key, None)

    def test_correct_variable_enables_token_auth(self):
        from golive.backends.auth.token import get_auth_provider
        os.environ["GOLIVE_TOKEN"] = "secret123"
        self.assertNotEqual(
            getattr(get_auth_provider(), "name", "none"), "none",
            "GOLIVE_TOKEN must switch on token auth")

    def test_wrong_token_is_not_authenticated(self):
        from golive.backends.auth.token import get_auth_provider
        from golive.server import authz
        os.environ["GOLIVE_TOKEN"] = "secret123"
        auth = get_auth_provider()
        for headers in ({"Authorization": "Bearer WRONG"}, {}):
            with self.subTest(headers=headers):
                ok = auth.verify(dict(headers))
                self.assertFalse(ok)
                self.assertIsNone(
                    authz.resolve_identity(None, ok),
                    "a bad or absent token must not resolve an identity")

    def test_misspelled_variable_is_reported(self):
        """A near-miss variable name must produce a visible warning.

        Without this the failure mode is silent and total: the operator
        believes the portal is behind a token and it is wide open to every
        process on the box.
        """
        from golive.server import app as app_mod
        warnings = app_mod.auth_env_warnings(
            {"GOLIVE_ADMIN_TOKEN": "secret123"})
        self.assertTrue(
            warnings, "a misspelled token variable must be warned about")
        joined = " ".join(warnings)
        self.assertIn("GOLIVE_ADMIN_TOKEN", joined,
                      "the warning must name the variable actually set")
        self.assertIn("GOLIVE_TOKEN", joined,
                      "the warning must name the variable that works")
        self.assertNotIn("secret123", joined,
                         "the warning must not echo the value")

    def test_correct_variable_produces_no_warning(self):
        from golive.server import app as app_mod
        self.assertEqual(
            app_mod.auth_env_warnings({"GOLIVE_TOKEN": "secret123"}), [],
            "the supported variable must not be flagged")

    def test_unrelated_variables_are_not_flagged(self):
        from golive.server import app as app_mod
        self.assertEqual(
            app_mod.auth_env_warnings(
                {"GOLIVE_HOME": "/tmp/x", "PATH": "/usr/bin",
                 "GOLIVE_LANG": "en"}),
            [], "only credential-looking near-misses should be flagged")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestRuleNamesAreTranslated(unittest.TestCase):
    """The 21 built-in rule names were Chinese literals in every locale.

    Missed by the 0.7.5 translation pass because they live in rules.yaml
    rather than in code, so an English operator got ``[机密凭证（强特征）]``
    on every refusal. Built-in rules now carry a ``name_key`` into the locale
    tables; ``name`` remains the fallback so a user-supplied rule file needs
    no key and shows its own text rather than a raw key.

    The value has to survive the round trip through the security_rules table,
    which is where the first attempt at this failed: the column was added to
    the DDL and the upsert but not to the SELECT projection, so it went in and
    silently never came back.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["GOLIVE_HOME"] = self.tmp
        from golive.core import paths
        paths.reset_cache()
        import golive.config as C
        C._current = None

    def _names(self, lang):
        os.environ["GOLIVE_LANG"] = lang
        import golive.config as C
        C._current = None
        # set_language, not poking a private cache: the first version of this
        # test cleared a name that does not exist, so the table stayed on the
        # previous locale and the zh assertion read en output.
        import golive.i18n
        golive.i18n.set_language(lang)
        import golive.security.scanner as S
        result = S.scan_html(
            '<html><body><script>const api_key="sk-'
            'abc123def456ghi789jkl012mno345pq";</script></body></html>',
            S.load_rules())
        return [d.get("name", "") for d in result.matched_details]

    def test_english_locale_has_no_chinese_rule_names(self):
        names = self._names("en")
        self.assertTrue(names, "expected the sample page to match rules")
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(
                    re.search(r"[\u4e00-\u9fff]", name),
                    "rule name %r is Chinese under GOLIVE_LANG=en" % name)

    def test_chinese_locale_still_reads_naturally(self):
        names = self._names("zh")
        self.assertTrue(
            any(re.search(r"[\u4e00-\u9fff]", n) for n in names),
            "zh locale should still show Chinese rule names, got %s" % names)

    def test_name_key_survives_the_registry_round_trip(self):
        """Guards the SELECT projection specifically."""
        import golive.backends.registry.rules_store as RS
        merged = RS.get_merged_rules_for_scanner()
        with_key = [r for r in merged["keyword_rules"] if r.get("name_key")]
        self.assertTrue(
            with_key,
            "no rule came back with a name_key — the column is written but "
            "not selected, so translation can never happen")

    def test_custom_rule_without_key_keeps_its_own_name(self):
        import golive.security.scanner as S
        self.assertEqual(
            S._rule_display_name({"name": "My Custom Rule"}),
            "My Custom Rule",
            "a third-party rule must not be forced through the locale table")

    def test_unknown_key_falls_back_to_the_literal(self):
        import golive.security.scanner as S
        self.assertEqual(
            S._rule_display_name({"name": "Fallback Name",
                                  "name_key": "scanner.rule.does_not_exist"}),
            "Fallback Name",
            "a stale key must not surface as a raw key to the user")
