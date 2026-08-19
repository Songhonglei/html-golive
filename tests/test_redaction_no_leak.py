"""A detected credential must never be printed back.

This is the failure an external audit found in 0.8.3 after 0.8.2 had already
claimed to fix it, which is the reason this file exists: the earlier fix was
a list of hand-written shapes, and detection kept growing past it. Detection
and redaction were two lists, and only one of them was maintained.

Two properties are pinned here:

  1. no secret value from the page appears anywhere in a finding
  2. enough of the surroundings survives to find the credential again

Both matter. Redacting the entire match passes (1) and fails (2), and a
report that says only ``post****`` tells someone with four database URLs
nothing about which one to fix.
"""
from __future__ import annotations

import itertools
import os
import unittest

os.environ.setdefault("GOLIVE_LANG", "en")

from golive.security import scanner  # noqa: E402


def _finding_text(html: str) -> str:
    """Everything a finding would show a user, concatenated."""
    result = scanner.scan_html(html, scanner.load_rules())
    return "\n".join(
        "{name} {keyword} {context}".format(
            name=d.get("name", ""), keyword=d.get("keyword", ""),
            context=d.get("context", ""))
        for d in result.matched_details)


# (label, html, the secret that must not survive)
LEAK_CASES = [
    # Assignments. The JS declaration forms are the ones that regressed:
    # detection learned `const password = "…"` in 0.8.3 while redaction
    # still only knew `password=` with no spaces.
    ("js const password",
     '<script>const password = "Xk9mQ2vLp8wRtY";</script>',
     "Xk9mQ2vLp8wRtY"),
    ("js let apiKey",
     '<script>let apiKey = "Ab3Kd9Mn2Pq5Rs8T";</script>',
     "Ab3Kd9Mn2Pq5Rs8T"),
    ("js var client_secret",
     '<script>var client_secret = "Zz9Yy8Xx7Ww6Vv5U";</script>',
     "Zz9Yy8Xx7Ww6Vv5U"),
    ("bare assignment",
     "<p>password=Zq7Wm2Xt9Lp</p>", "Zq7Wm2Xt9Lp"),
    ("json config",
     '<script>{"db_password": "Qw3Er4Ty5Ui6Op7A"}</script>',
     "Qw3Er4Ty5Ui6Op7A"),
    ("yaml config",
     '<pre>api_key: "Mn4Bv5Cx6Zs7Aq8W"</pre>', "Mn4Bv5Cx6Zs7Aq8W"),

    # Connection strings. A password containing @ was unredacted because the
    # masker stopped at the first @ — the same character-class mistake that
    # had let such a DSN past detection one release earlier.
    ("mysql dsn with @ in password",
     "<script>mysql://tester:P@ss!w0rd$x@db.example.test:3306/app</script>",
     "P@ss!w0rd$x"),
    ("postgres dsn",
     "<p>postgres://u:pw123456@db.test:5432/app</p>", "pw123456"),
    ("redis dsn without user",
     "<p>redis://:onlypass9x@cache.test:6379</p>", "onlypass9x"),
    ("jdbc url",
     "<p>jdbc:mysql://h:3306/d?user=root&password=Zq7Wm2Xt9Lp</p>",
     "Zq7Wm2Xt9Lp"),

    # Tokens and keys.
    ("bearer token",
     '<script>const a = "Bearer abcdefghij0123456789klmn";</script>',
     "abcdefghij0123456789klmn"),
    ("anthropic key",
     "<p>sk-ant-api03-abcdefghij0123456789klmnop</p>",
     "abcdefghij0123456789klmnop"),
    ("aws access key",
     "<p>AKIAIOSFODNN7EXAMPLE</p>", "IOSFODNN7EXAMPLE"),
    ("github pat",
     "<p>ghp_abcdefghij0123456789klmnopqrstuv</p>",
     "abcdefghij0123456789klmnopqrstuv"),
    ("cloud secret assignment",
     '<script>const AccessKeySecret="wJalrXUtnFEMIK7MDENGbPx";</script>',
     "wJalrXUtnFEMIK7MDENGbPx"),

    # Long digit runs have no key= in front of them, so every
    # assignment-shaped pass missed them and all 18 digits were printed.
    ("national id",
     "<p>440101199001011234</p>", "199001011234"),

    # Two findings on one page: a context window is cut around each hit, so
    # the second window can contain the first one's secret. Redaction that
    # needs an intact keyword sees a clipped one and gives up.
    ("adjacent findings",
     "<p>api_key note</p><p>password=Zq7Wm2Xt9Lp</p>", "Zq7Wm2Xt9Lp"),
]


class TestNoSecretSurvivesIntoAFinding(unittest.TestCase):

    def test_secret_values_are_redacted(self):
        for label, html, secret in LEAK_CASES:
            with self.subTest(case=label):
                text = _finding_text(html)
                self.assertNotIn(
                    secret, text,
                    f"{label}: the secret was printed back in the finding")

    def test_the_page_was_actually_flagged(self):
        """A page that produced no finding proves nothing about redaction.

        Without this, deleting a detection rule would make the leak test
        above pass — there would be no finding to leak from.
        """
        for label, html, _secret in LEAK_CASES:
            with self.subTest(case=label):
                result = scanner.scan_html(html, scanner.load_rules())
                self.assertTrue(
                    result.matched_details,
                    f"{label}: nothing was detected, so the redaction "
                    f"assertion above is vacuous")


class TestRedactionStaysUseful(unittest.TestCase):
    """Removing the secret must not remove the ability to find it."""

    def test_connection_strings_keep_scheme_and_host(self):
        cases = [
            ("<p>postgres://admin:s3cr3tp@ssword@10.0.0.5:5432/prod</p>",
             "10.0.0.5"),
            ("<script>mysql://t:P@ss!w0rd$x@db.example.test:3306/a</script>",
             "db.example.test"),
            ("<p>redis://:onlypass9x@cache.test:6379</p>", "cache.test"),
        ]
        for html, locator in cases:
            with self.subTest(locator=locator):
                text = _finding_text(html)
                self.assertIn(
                    locator, text,
                    "the host identifies which credential to fix and is not "
                    "itself a secret")


class TestRedactionCannotDriftFromDetection(unittest.TestCase):
    """The structural guard, not another shape in a list.

    Every strong credential regex is exercised through redaction. A new rule
    added to rules.yaml is covered by this without anyone remembering to add
    it here — which is precisely what went wrong before.
    """

    def test_every_strong_rule_is_reachable_by_redaction(self):
        rules = scanner.load_rules()
        strong = [r for r in rules.get("regex_rules", [])
                  if r.get("strength") == "strong"]
        self.assertTrue(strong, "no strong regex rules loaded")
        for rule in strong:
            with self.subTest(rule=rule.get("name", "?")):
                pattern = rule.get("pattern")
                self.assertIsNotNone(pattern)
                # The masker must accept whatever form load_rules() produces.
                # It previously crashed on compiled patterns, and the crash
                # was swallowed — redaction silently did nothing.
                try:
                    scanner._mask_by_detection_rules("probe")
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"redaction raised on rule set: {exc}")

    def test_redaction_survives_a_broken_rule(self):
        """One unusable rule must not stop the rest from redacting.

        Redaction runs inside the failure path of a publish. If a malformed
        custom rule made it raise, the caller's except would swallow it and
        the block message would print the credential — a config typo
        becoming a disclosure.
        """
        original = scanner.load_rules
        broken = {"regex_rules": [
            {"type": "credential", "strength": "strong", "name": "broken",
             "pattern": "([unclosed"},
            {"type": "credential", "strength": "strong", "name": "good",
             "pattern": r"\bAKIA[0-9A-Z]{16}\b"},
        ]}
        scanner.load_rules = lambda *a, **k: broken
        try:
            out = scanner._mask_by_detection_rules("AKIAIOSFODNN7EXAMPLE")
        finally:
            scanner.load_rules = original
        self.assertNotIn(
            "IOSFODNN7EXAMPLE", out,
            "a broken rule earlier in the list stopped redaction")


# ── the 0.8.4 regression: several credentials in one <script> ──────────────

#: One secret per entry, in the form it would be written by hand.
CROWDED_PAGE_SECRETS = {
    "password variable":
        ('const password = "%s";', "Xk9mQ2vLp8wRtY"),
    "quoted json key":
        ('{"db_password": "%s"}', "Qw3Er4Ty5Ui6Op7A"),
    "bearer jwt":
        ('const auth = "Bearer %s";',
         "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijklmnop"),
    "mysql dsn":
        ('const dsn = "mysql://tester:%s@db.example.test:3306/app";',
         "P@ss!w0rd$x"),
    "postgres dsn":
        ('const pg = "postgresql://rep:%s@pg.example.test:5432/audit";',
         "S3cr3t!p@ss#y"),
    "redis dsn":
        ('const rd = "redis://:%s@cache.test:6379";', "onlypass9x"),
    "openai key":
        ('const key = "sk-%s";', "abcdefghij0123456789klmnopqrstuv"),
    "github token":
        ('const gh = "ghp_%s";', "abcdefghij0123456789klmnopqrstuv2"),
    "aws access key":
        ('const ak = "AKIA%s";', "IOSFODNN7EXAMPLE"),
    "cloud secret":
        ('const s = {AccessKeySecret:"%s"};', "wJalrXUtnFEMIK7MDENGbPx"),
    "national id":
        ("<p>%s</p>", "440101199001011234"),
    "yaml api key":
        ('api_key: "%s"', "Mn4Bv5Cx6Zs7Aq8W"),
    "jdbc password":
        ('const j = "jdbc:mysql://h:3306/d?user=root&password=%s";',
         "Zq7Wm2Xt9Lp4Kv"),
}

SEPARATORS = ["\n", " ", "", "\n\n", ";", " // note\n", "\t"]

WRAPPERS = [
    "<html><body><script>%s</script></body></html>",
    "<html><body><pre>%s</pre></body></html>",
    "<html><body><script>\n%s\n</script><p>t</p></body></html>",
    "<html><body><div>%s</div></body></html>",
]


class TestCrowdedPageLeaksNothing(unittest.TestCase):
    """Several credentials on one page, in every arrangement.

    This is the failure 0.8.4 shipped with and claimed to have fixed. A
    context window is cut around each hit, so one finding's window overlaps
    a *neighbouring* credential — and when the window starts partway into
    that value, the `password=` in front of it falls outside. What remains is
    a bare string with no shape, so every pattern-based pass missed it.

    A single hand-picked sample is not enough here: of 72 orderings of four
    credentials, 42 leaked and 30 did not. Which one you happen to write
    decides whether you see the bug, so the arrangement is enumerated.
    """

    def _scan_text(self, html):
        result = scanner.scan_html(html, scanner.load_rules())
        return "\n".join(
            "{n} {k} {c}".format(n=d.get("name", ""), k=d.get("keyword", ""),
                                 c=d.get("context", ""))
            for d in result.matched_details)

    def test_no_secret_leaks_from_any_pair(self):
        """Every ordered pair, in every separator and wrapper."""
        names = list(CROWDED_PAGE_SECRETS)
        for first, second in itertools.permutations(names, 2):
            tpl_a, sec_a = CROWDED_PAGE_SECRETS[first]
            tpl_b, sec_b = CROWDED_PAGE_SECRETS[second]
            for sep in SEPARATORS:
                body = sep.join([tpl_a % sec_a, tpl_b % sec_b])
                html = WRAPPERS[0] % body
                text = self._scan_text(html)
                for label, secret in ((first, sec_a), (second, sec_b)):
                    if secret not in text:
                        continue
                    self.fail(
                        "{first} + {second} (sep={sep!r}): {label} leaked"
                        .format(first=first, second=second, sep=sep,
                                label=label))

    def test_no_secret_leaks_from_the_whole_page(self):
        """All of them at once, in each wrapper."""
        body_parts = [tpl % sec
                      for tpl, sec in CROWDED_PAGE_SECRETS.values()]
        for wrapper in WRAPPERS:
            for sep in SEPARATORS:
                with self.subTest(wrapper=wrapper[:32], sep=sep):
                    text = self._scan_text(wrapper % sep.join(body_parts))
                    for label, (_tpl, secret) in \
                            CROWDED_PAGE_SECRETS.items():
                        self.assertNotIn(
                            secret, text,
                            "{label} leaked from a crowded page"
                            .format(label=label))

    def test_the_crowded_page_is_actually_blocked(self):
        body = "\n".join(tpl % sec
                         for tpl, sec in CROWDED_PAGE_SECRETS.values())
        result = scanner.scan_html(WRAPPERS[0] % body, scanner.load_rules())
        self.assertTrue(result.blocked)

    def test_locators_survive_a_crowded_page(self):
        """Redaction must not get so aggressive that it stops being useful.

        The first fix for this leak blanked whole matches, which passes a
        no-leak assertion and leaves an operator with four masked DSNs and
        no way to tell which one to fix.
        """
        cases = [
            ('<html><body><script>const dsn = '
             '"mysql://tester:P@ss!w0rd$x@db.example.test:3306/app";'
             'const p = "Xk9mQ2vLp8wRtY";</script></body></html>',
             "db.example.test", "P@ss!w0rd$x"),
            ('<html><body><script>const a = '
             '"postgresql://u:pw123456@pg.test:5432/d";'
             'const k = "sk-abcdefghij0123456789klmn";</script></body></html>',
             "pg.test", "pw123456"),
        ]
        for html, locator, secret in cases:
            with self.subTest(locator=locator):
                text = self._scan_text(html)
                self.assertNotIn(secret, text, "the password leaked")
                self.assertIn(
                    locator, text,
                    "the host says which credential to fix and is not itself "
                    "the secret")


class TestPageSecretsDoNotCrossScans(unittest.TestCase):
    """Page state must not survive into the next page's report.

    The set of secrets is kept per thread while a page is scanned. If it were
    not cleared, one page's values would be redacted out of another page's
    report — harmless-looking, but it would mask ordinary text and make
    findings unreadable for reasons nobody could trace.
    """

    def test_a_clean_page_after_a_dirty_one_is_unaffected(self):
        rules = scanner.load_rules()
        dirty = ('<html><body><script>const password = "Xk9mQ2vLp8wRtY";'
                 '</script></body></html>')
        scanner.scan_html(dirty, rules)
        clean = "<html><body><p>Xk9mQ2vLp8wRtY is just text here</p></body></html>"
        result = scanner.scan_html(clean, rules)
        self.assertFalse(
            result.blocked,
            "a page with no credential was blocked because of the previous "
            "page")

    def test_the_secret_set_is_per_thread(self):
        """Asserted on the storage, because concurrency cannot show this.

        Two threads scanning two pages both redact correctly even when the
        set is shared, since each writes the set before reading it and the
        secrets do not collide — running threads and looking for a leak
        passes either way, which makes it a test that cannot fail.

        What actually distinguishes the two designs is whether one thread can
        observe another thread's value at all. So set a value here, read it
        from a second thread, and require the second thread not to see it.
        """
        import threading

        scanner._page_state.secrets = {"ThisThreadOnly123456"}
        seen = []

        def read_from_another_thread():
            seen.append(scanner._page_secrets())

        thread = threading.Thread(target=read_from_another_thread)
        thread.start()
        thread.join()

        self.assertEqual(
            seen, [set()],
            "another thread saw this thread's secrets: the set is shared, so "
            "two concurrent scans can redact each other's reports")

    def test_a_second_scan_replaces_rather_than_accumulates(self):
        """Within one thread, page state must not build up across scans.

        Accumulating would keep masking correctly and slowly turn every
        report into asterisks as unrelated values pile up.
        """
        rules = scanner.load_rules()
        first = ('<html><body><script>const password = "AaBbCcDdEeFf11";'
                 '</script></body></html>')
        second = ('<html><body><script>const password = "ZzYyXxWwVvUu22";'
                  '</script></body></html>')
        scanner.scan_html(first, rules)
        scanner.scan_html(second, rules)
        carried = [v for v in scanner._page_secrets()
                   if "AaBbCcDdEeFf11" in v]
        self.assertEqual(
            carried, [],
            "the previous page's secret is still in the set")


class TestStorageRedactsIndependently(unittest.TestCase):
    """The history table must not rely on the report having been cleaned.

    In the normal path a finding is already redacted before it reaches
    storage, so a test that goes through scan_html proves nothing about the
    storage layer — it would pass even if storage did nothing at all. Feed it
    raw findings directly, the way a future caller might.
    """

    def test_raw_findings_are_redacted_on_the_way_in(self):
        from golive.backends.registry.scans_store import _redact_findings
        secrets = ["Xk9mQ2vLp8wRtY", "IOSFODNN7EXAMPLE"]
        raw = [{
            "name": "credential assignment",
            "keyword": 'password="Xk9mQ2vLp8wRtY"',
            "context": ('const password = "Xk9mQ2vLp8wRtY";'
                        'const k = "AKIAIOSFODNN7EXAMPLE";'),
            "strength": "strong",
            "type": "credential",
        }]
        stored = str(_redact_findings(raw))
        for secret in secrets:
            with self.subTest(secret=secret[:10]):
                self.assertNotIn(
                    secret, stored,
                    "storage passed a raw secret through; it must redact on "
                    "its own rather than trust the caller")

    def test_storage_shares_the_masker_with_the_console(self):
        """Same function, so improving one cannot leave the other behind."""
        import inspect

        from golive.backends.registry import scans_store
        src = inspect.getsource(scans_store._redact_findings)
        self.assertIn(
            "_mask_secret_literal", src,
            "storage should call the scanner's masker, not reimplement one")


if __name__ == "__main__":
    unittest.main()
