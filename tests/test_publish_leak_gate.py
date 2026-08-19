"""Release gate: a refused publish must not leak through *any* exit.

The unit tests in test_redaction_no_leak.py inspect findings in process. That
is necessary and not sufficient: it says nothing about what actually reaches a
terminal or lands in the database, and every leak in 0.8.2 through 0.8.4 was
found by an outside party running the CLI rather than by the suite.

So this runs the real command in a subprocess against a real GOLIVE_HOME and
then greps both exits — captured output and every text column of the registry
database — for the planted values. An external audit of 0.8.5 recommended
keeping exactly this as a release gate.

Kept deliberately small: the ordering dimension is covered exhaustively by
the in-process tests, and spawning 72 subprocesses would trade minutes of CI
time for a dimension already pinned.

What this file does and does not catch, established by reverting each fix and
watching the result:

  caught here   page-wide secret collection removed -> console AND database
                assertions both fail
  caught here   DSN locator blanked -> the actionability assertion fails
  not caught    value extraction for whole-match rules (AKIA, JWT) removed —
                this page still redacts those through shape rules, so the
                in-process tests own that case

Stated rather than implied, because the first version of this gate used
newline-separated credentials and stayed green with the fix reverted. A gate
that cannot fail is worse than no gate: it reports safety it never checked.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: label -> (line as it would be written, the value that must never surface)
PLANTED = {
    "password variable":
        ('const password = "Xk9mQ2vLp8wRtY";', "Xk9mQ2vLp8wRtY"),
    "bearer jwt":
        ('const auth = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0'
         '.abcdefghijklmnop";',
         "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop"),
    "mysql dsn":
        ('const dsn = "mysql://tester:P@ss!w0rd$x@db.example.test:3306/app";',
         "P@ss!w0rd$x"),
    "openai key":
        ('const key = "sk-abcdefghij0123456789klmnopqrstuv";',
         "abcdefghij0123456789klmnopqrstuv"),
    "aws key":
        ('const ak = "AKIAIOSFODNN7EXAMPLE";', "IOSFODNN7EXAMPLE"),
}

#: The DSN metadata that must survive, or a refusal stops being actionable.
DSN_LOCATOR = "db.example.test"


def _run(args, home, cwd):
    env = dict(os.environ)
    env["GOLIVE_HOME"] = home
    env["GOLIVE_LANG"] = "en"
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "golive.cli"] + args,
        capture_output=True, text=True, env=env, cwd=cwd, timeout=180)


class TestRefusedPublishLeaksThroughNoExit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="golive-leak-gate-")
        cls.home = os.path.join(cls.tmp, "home")
        result = _run(["init", "--no-serve", "--skip-skill"], cls.home,
                      cls.tmp)
        if result.returncode != 0:
            raise unittest.SkipTest(
                "golive init failed, cannot run the gate: "
                + (result.stderr or result.stdout)[-400:])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _publish_crowded_page(self, slug):
        # No separator between the lines, and this is not cosmetic. With
        # newlines this page does not leak even with the page-wide collection
        # disabled, so a gate written that way passes against the bug it
        # exists to catch — verified by reverting the fix and watching it stay
        # green. Packing the credentials tight makes the context windows
        # overlap, which is the condition that produced the leak.
        body = "".join(line for line, _secret in PLANTED.values())
        path = os.path.join(self.tmp, slug + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<html><body><script>" + body
                     + "</script></body></html>")
        return _run(["publish", path, "--name", slug, "--slug", slug],
                    self.home, self.tmp)

    def test_the_publish_is_refused(self):
        result = self._publish_crowded_page("gate-refused")
        self.assertNotEqual(
            result.returncode, 0,
            "a page carrying five credentials was published")
        combined = (result.stdout + result.stderr).lower()
        # Distinguish "the scan refused it" from "the command fell over".
        # A crash also exits non-zero, and reading that as a block is how a
        # broken check looks identical to a passing one.
        self.assertTrue(
            any(word in combined
                for word in ("credential", "security scan", "blocked")),
            "non-zero exit, but nothing says the scan refused it: "
            + combined[-300:])

    def test_no_planted_value_reaches_the_console(self):
        result = self._publish_crowded_page("gate-console")
        combined = result.stdout + result.stderr
        for label, (_line, secret) in PLANTED.items():
            with self.subTest(planted=label):
                self.assertNotIn(
                    secret, combined,
                    f"{label} was printed by the refusal")

    def test_no_planted_value_reaches_the_database(self):
        self._publish_crowded_page("gate-db")
        found = []
        for db_path in glob.glob(os.path.join(self.home, "*.db")):
            with open(db_path, "rb") as fh:
                blob = fh.read()
            for label, (_line, secret) in PLANTED.items():
                if secret.encode("utf-8") in blob:
                    found.append(f"{label} in {os.path.basename(db_path)}")
        self.assertEqual(
            found, [],
            "planted credentials are sitting in the registry database: "
            + ", ".join(found))

    def test_the_refusal_stays_actionable(self):
        """Redaction that removes the locator passes a leak test and fails
        the user: four masked DSNs and no way to tell them apart."""
        result = self._publish_crowded_page("gate-locator")
        combined = result.stdout + result.stderr
        self.assertIn(
            DSN_LOCATOR, combined,
            "the DSN host was redacted away; the refusal no longer says "
            "which connection string to fix")

    def test_a_clean_page_still_publishes(self):
        """The gate must not pass by refusing everything."""
        path = os.path.join(self.tmp, "clean.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<html><head><title>ok</title></head><body>"
                     "<p>Configure your API key before starting.</p>"
                     "</body></html>")
        result = _run(["publish", path, "--name", "clean", "--slug",
                       "gate-clean"], self.home, self.tmp)
        self.assertEqual(
            result.returncode, 0,
            "an ordinary page was refused: "
            + (result.stderr or result.stdout)[-300:])


if __name__ == "__main__":
    unittest.main()
