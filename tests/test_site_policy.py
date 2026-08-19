"""Site policies — intent that survives a republish.

The bug: a page published with ``--watermark`` lost the watermark the next
time it was published without repeating the flag. The flag described one
publish and nothing carried it forward, so a page marked internal quietly
stopped saying so — with no message reporting that it had.

These tests go through the CLI rather than calling the injector, because the
bug was in how a publish decides, not in whether the injector works.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE = "<html><head><title>P</title></head><body><p>hi</p></body></html>"


class _CliCase(unittest.TestCase):
    """Runs real publishes against a throwaway GOLIVE_HOME."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.src = self.root / "p.html"
        self.src.write_text(PAGE, encoding="utf-8")
        self.env = dict(os.environ)
        self.env.update({
            "GOLIVE_HOME": str(self.home),
            "GOLIVE_LANG": "en",
            "PYTHONPATH": str(REPO),
        })
        self._golive("init", "--no-serve", "--skip-skill")
        self.addCleanup(self._tmp.cleanup)

    def _golive(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "golive.cli", *argv],
            cwd=str(self.root), env=self.env, capture_output=True,
            text=True, timeout=120)

    def _publish(self, *argv):
        return self._golive("publish", str(self.src), *argv)

    def _stores(self):
        """Import inside the test process, bound to this case's home.

        ``paths.get_home()`` caches per process, so setting the environment
        variable is not enough on its own: under pytest an earlier test has
        already resolved the home to somewhere else, and every read here would
        go to that database instead of the one the subprocess just wrote. The
        first version of this file did exactly that and reported that the site
        had never been created.
        """
        sys.path.insert(0, str(REPO))
        os.environ["GOLIVE_HOME"] = str(self.home)
        from golive.core import paths
        paths.reset_cache()
        self.addCleanup(paths.reset_cache)
        from golive.backends.registry import sqlite_manifest, sqlite_store
        from golive.backends.storage import local
        sqlite_manifest.reset_cache()
        return sqlite_store.SqliteRegistry(), local.LocalStorage(), \
            sqlite_manifest.get_manifests()

    def _live_html(self, ref="p1"):
        registry, storage, _ = self._stores()
        site = registry.resolve(ref)
        self.assertIsNotNone(site, "site {r} was never created".format(r=ref))
        return storage.read(site["site_id"])

    def _has_watermark(self, ref="p1"):
        return "watermark-layer" in self._live_html(ref)

    def _policy(self, ref="p1"):
        registry, _storage, manifests = self._stores()
        return manifests.get_policy(registry.resolve(ref)["site_id"])


class TestAWatermarkSurvivesARepublish(_CliCase):

    def test_the_watermark_is_still_there_after_a_plain_republish(self):
        """The regression this feature exists for."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        self.assertTrue(self._has_watermark(), "the first publish had none")
        self._publish("--update", "p1")
        self.assertTrue(
            self._has_watermark(),
            "republishing without --watermark dropped it, which is the bug")

    def test_it_survives_more_than_one_republish(self):
        """Guards against an intent that is honoured once and then lost."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        for round_no in range(3):
            self._publish("--update", "p1")
            with self.subTest(republish=round_no + 1):
                self.assertTrue(self._has_watermark())

    def test_the_text_is_carried_forward_too(self):
        """A remembered watermark with the wrong label is still wrong."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        self._publish("--update", "p1")
        self.assertIn("Internal", self._live_html())

    def test_the_user_is_told_where_it_came_from(self):
        """An injection nobody asked for on this command line needs a source."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        out = self._publish("--update", "p1")
        self.assertIn("policy", (out.stdout + out.stderr).lower())


class TestExplicitFlagsWin(_CliCase):

    def test_no_watermark_beats_the_policy(self):
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        self._publish("--update", "p1", "--no-watermark")
        self.assertFalse(
            self._has_watermark(),
            "an explicit refusal lost to stored intent")

    def test_refusing_is_remembered_as_well(self):
        """Otherwise the watermark reappears on the next publish."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        self._publish("--update", "p1", "--no-watermark")
        self._publish("--update", "p1")
        self.assertFalse(self._has_watermark())

    def test_a_new_text_replaces_the_stored_one(self):
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        self._publish("--update", "p1", "--watermark", "Public")
        html = self._live_html()
        self.assertIn("Public", html)
        self.assertNotIn("Internal", html)

    def test_refusing_says_it_overrode_something(self):
        """Silence would read as "the flag did nothing"."""
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        out = self._publish("--update", "p1", "--no-watermark")
        self.assertTrue(
            "policy" in (out.stdout + out.stderr).lower(),
            "overriding a stored policy was not reported")


class TestPolicyDoesNotAppearFromNowhere(_CliCase):

    def test_a_page_published_without_a_watermark_stays_without_one(self):
        """Paired with the tests above so they cannot pass by always injecting."""
        self._publish("--name", "P", "--slug", "p1")
        self.assertFalse(self._has_watermark())
        self._publish("--update", "p1")
        self.assertFalse(self._has_watermark())

    def test_no_policy_row_is_written_when_no_flag_was_given(self):
        """A publish that stated no intent should not invent one.

        Storing a default would make a later change to the yaml default
        ineffective for every site published before it.
        """
        self._publish("--name", "P", "--slug", "p1")
        self.assertFalse(self._policy()["watermark_enabled"])


class TestManifestRecordsThePublish(_CliCase):

    def test_a_publish_writes_a_manifest(self):
        self._publish("--name", "P", "--slug", "p1")
        registry, _s, manifests = self._stores()
        site_id = registry.resolve("p1")["site_id"]
        self.assertIsNotNone(
            manifests.get_manifest(site_id),
            "nothing recorded what this publish produced")

    def test_the_manifest_lists_the_layers_actually_injected(self):
        self._publish("--name", "P", "--slug", "p1", "--watermark", "Internal")
        registry, _s, manifests = self._stores()
        manifest = manifests.get_manifest(registry.resolve("p1")["site_id"])
        self.assertIn("watermark", manifest["injections"])

    def test_the_manifest_does_not_claim_layers_that_are_absent(self):
        """Paired with the test above: a hardcoded list would pass that one."""
        self._publish("--name", "P", "--slug", "p1")
        registry, _s, manifests = self._stores()
        manifest = manifests.get_manifest(registry.resolve("p1")["site_id"])
        self.assertNotIn("watermark", manifest["injections"])

    def test_the_hash_matches_what_was_stored(self):
        """The manifest is meant to detect a file changed underneath us."""
        import hashlib

        self._publish("--name", "P", "--slug", "p1")
        registry, _s, manifests = self._stores()
        site_id = registry.resolve("p1")["site_id"]
        manifest = manifests.get_manifest(site_id)
        live = self._live_html().encode("utf-8", "replace")
        self.assertEqual(manifest["content_sha256"],
                         hashlib.sha256(live).hexdigest())

    def test_the_manifest_is_rewritten_on_republish(self):
        self._publish("--name", "P", "--slug", "p1")
        registry, _s, manifests = self._stores()
        site_id = registry.resolve("p1")["site_id"]
        first = manifests.get_manifest(site_id)["content_sha256"]
        self.src.write_text(PAGE.replace("hi", "changed"), encoding="utf-8")
        self._publish("--update", "p1")
        _r, _s2, manifests = self._stores()
        self.assertNotEqual(
            first, manifests.get_manifest(site_id)["content_sha256"],
            "the manifest still describes the previous publish")


class TestAPublishSurvivesABrokenPolicyTable(_CliCase):

    def test_publish_still_works_when_the_policy_read_fails(self):
        """A side table being unreadable must not cost someone a publish."""
        sys.path.insert(0, str(REPO))
        from golive import cli

        def boom(_site_id):
            raise RuntimeError("policy table unavailable")

        original = cli._site_policy
        cli._site_policy = boom
        try:
            html = cli._apply_watermark(PAGE, _Args(), policy=None)
            self.assertIsInstance(html, str)
        finally:
            cli._site_policy = original


class _Args:
    watermark = None
    no_watermark = False
    slug = ""
    source = "p.html"


if __name__ == "__main__":
    unittest.main()
