"""``golive doctor --site`` — compare a manifest against the page on disk.

Reports only. A mismatch has several possible causes — edited outside golive,
an interrupted publish, a manifest predating a feature — and each implies a
different fix, one of which is "leave it alone". Choosing automatically would
mean overwriting either the page or the record of it, so these tests also
check that nothing gets repaired.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE = "<html><head><title>D</title></head><body><p>hi</p></body></html>"


class _DoctorCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.src = self.root / "d.html"
        self.src.write_text(PAGE, encoding="utf-8")
        self.env = dict(os.environ)
        self.env.update({"GOLIVE_HOME": str(self.home),
                         "GOLIVE_LANG": "en",
                         "PYTHONPATH": str(REPO)})
        self._golive("init", "--no-serve", "--skip-skill")
        self.addCleanup(self._tmp.cleanup)

    def _golive(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "golive.cli", *argv],
            cwd=str(self.root), env=self.env, capture_output=True,
            text=True, timeout=120)

    def _publish(self, *argv):
        return self._golive("publish", str(self.src), *argv)

    def _bind(self):
        sys.path.insert(0, str(REPO))
        os.environ["GOLIVE_HOME"] = str(self.home)
        from golive.core import paths
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)
        from golive.backends.registry import sqlite_manifest
        sqlite_manifest.reset_cache()

    def _site_id(self, ref="d1"):
        self._bind()
        from golive.backends.factory import get_registry
        return get_registry().resolve(ref)["site_id"]

    def _rewrite_live_page(self, html, ref="d1"):
        """Change the published page behind golive's back."""
        site_id = self._site_id(ref)
        from golive.backends.factory import get_storage
        get_storage().publish(html, site_id)

    def _live_page(self, ref="d1"):
        site_id = self._site_id(ref)
        from golive.backends.factory import get_storage
        return get_storage().read(site_id)

    def _report(self, *extra):
        out = self._golive("doctor", "--site", "d1", *extra)
        return out.stdout + out.stderr, out.returncode


class TestAConsistentSitePasses(_DoctorCase):

    def test_a_freshly_published_site_is_clean(self):
        self._publish("--name", "D", "--slug", "d1")
        text, code = self._report()
        self.assertEqual(code, 0, text)

    def test_it_reports_the_layers_it_found(self):
        self._publish("--name", "D", "--slug", "d1", "--watermark", "Internal")
        text, code = self._report()
        self.assertEqual(code, 0, text)
        self.assertIn("watermark", text)

    def test_json_output_is_machine_readable(self):
        self._publish("--name", "D", "--slug", "d1")
        out = self._golive("doctor", "--site", "d1", "--json")
        payload = json.loads(out.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["problems"], [])


class TestItDetectsAPageChangedUnderneath(_DoctorCase):

    def test_an_edited_page_is_reported(self):
        self._publish("--name", "D", "--slug", "d1")
        self._rewrite_live_page(PAGE.replace("hi", "TAMPERED"))
        text, code = self._report()
        self.assertEqual(code, 1)
        self.assertIn("not what the last publish wrote", text)

    def test_a_missing_layer_is_reported(self):
        self._publish("--name", "D", "--slug", "d1", "--watermark", "Internal")
        from golive.inject import watermark as wm
        self._bind()
        self._rewrite_live_page(wm.remove_from_html(self._live_page()))
        text, code = self._report()
        self.assertEqual(code, 1)
        self.assertIn("absent from the page", text)

    def test_a_policy_asking_for_an_absent_watermark_is_reported(self):
        """The case that made policies worth storing in the first place.

        Asserted on wording unique to the failing branch. "policy asks for a
        watermark" is a prefix of the *passing* message too, so a first
        version of this test stayed green with the check disabled — the report
        had simply switched to saying the page did have one.
        """
        self._publish("--name", "D", "--slug", "d1", "--watermark", "Internal")
        from golive.inject import watermark as wm
        self._bind()
        self._rewrite_live_page(wm.remove_from_html(self._live_page()))
        text, _code = self._report()
        self.assertIn("but the page has none", text)
        self.assertNotIn("and the page has one", text)


class TestItOnlyReports(_DoctorCase):

    def test_the_page_is_left_exactly_as_it_was(self):
        self._publish("--name", "D", "--slug", "d1")
        self._rewrite_live_page(PAGE.replace("hi", "TAMPERED"))
        before = self._live_page()
        self._report()
        self.assertEqual(
            before, self._live_page(),
            "doctor changed the published page; it is supposed to report only")

    def test_the_manifest_is_left_alone_too(self):
        """"Fixing" by re-recording the hash would hide the problem."""
        self._publish("--name", "D", "--slug", "d1")
        self._bind()
        from golive.backends.registry.sqlite_manifest import get_manifests
        site_id = self._site_id()
        before = get_manifests().get_manifest(site_id)["content_sha256"]
        self._rewrite_live_page(PAGE.replace("hi", "TAMPERED"))
        self._report()
        self._bind()
        from golive.backends.registry.sqlite_manifest import get_manifests \
            as reopen
        self.assertEqual(
            before, reopen().get_manifest(site_id)["content_sha256"],
            "doctor rewrote the manifest instead of reporting the mismatch")

    def test_it_says_that_it_only_reports(self):
        """Otherwise a user may wait for it to repair something."""
        self._publish("--name", "D", "--slug", "d1")
        self._rewrite_live_page(PAGE.replace("hi", "TAMPERED"))
        text, _code = self._report()
        self.assertIn("does not change", text)


class TestUnknownSites(_DoctorCase):

    def test_an_unknown_ref_fails_with_a_pointer(self):
        self._publish("--name", "D", "--slug", "d1")
        out = self._golive("doctor", "--site", "nope")
        self.assertEqual(out.returncode, 1)
        self.assertIn("golive list", out.stdout + out.stderr)

    def test_the_whole_install_check_still_works(self):
        """--site narrows doctor; it must not replace it."""
        out = self._golive("doctor", "--json")
        payload = json.loads(out.stdout)
        self.assertIn("home", payload)
        self.assertNotIn("ref", payload)


if __name__ == "__main__":
    unittest.main()
