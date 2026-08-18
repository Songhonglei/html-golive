"""Untrusted HTML is scanned on every path that writes it to storage.

There are six places that call ``storage.publish``. Whether each needs a
credential scan depends on where the HTML came from, not on how it is
written:

===========================  ============  ==========================
call site                    scanned       why
===========================  ============  ==========================
cli.cmd_publish (create)     yes           user-supplied file
cli.cmd_publish (update)     yes           user-supplied file
server.editor_api.save       yes           typed into the browser
core.portability.import      yes (v0.8.2)  archive from anywhere
core.demo.install            no            HTML shipped in the package
cli.cmd_verify               no            constant in the source
===========================  ============  ==========================

Import scans per page and holds back only the offending page. Aborting the
whole restore would leave someone unable to recover a backup because of one
bad page — and since import is not atomic, stopping midway is the worst
outcome. A held-back page is reported and makes the exit code non-zero, so a
scripted restore cannot report success while pages are missing.
"""
from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from golive.core import paths
from golive.core.portability import _credential_findings

# Assembled so this file is not itself a scanner hit.
_DSN = "postgres://adm:" + "Leak3dSecret99" + "@10.0.0.9:5432/prod"
LEAKY_HTML = f"<html><body><p>DB: {_DSN}</p></body></html>"
CLEAN_HTML = "<html><head><title>ok</title></head><body><p>fine</p></body></html>"


class TestCredentialFindingsHelper(unittest.TestCase):
    """Import needs the verdict without run_scan's printing or warnings."""

    def test_it_reports_a_credential(self):
        found = _credential_findings(LEAKY_HTML)
        self.assertTrue(found, "the DSN was not detected")
        self.assertTrue(all("name" in f and "keyword" in f for f in found))

    def test_it_ignores_content_warnings(self):
        """Pages in an archive were already published once."""
        self.assertEqual(_credential_findings("<p>本月工资明细</p>"), [])

    def test_a_clean_page_yields_nothing(self):
        self.assertEqual(_credential_findings(CLEAN_HTML), [])

    def test_it_does_not_print(self):
        """Import prints one summary; the helper must stay quiet."""
        import contextlib
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            _credential_findings(LEAKY_HTML)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")

    def test_a_broken_scanner_does_not_block_a_restore(self):
        with mock.patch("golive.security.scanner.load_rules",
                        side_effect=RuntimeError("no pyyaml")):
            self.assertEqual(_credential_findings(LEAKY_HTML), [])


class TestImportHoldsBackOnlyTheOffendingPage(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self._env = mock.patch.dict(os.environ, {"GOLIVE_HOME": str(self.home)})
        self._env.start()
        paths.reset_cache()
        import golive.config as cfg_mod
        cfg_mod._current = None

    def tearDown(self):
        self._env.stop()
        paths.reset_cache()
        import golive.config as cfg_mod
        cfg_mod._current = None
        self._tmp.cleanup()

    def _archive(self, pages: dict) -> str:
        """Build a minimal archive: {slug: html}."""
        path = Path(self._tmp.name) / "archive.tar.gz"
        rows = [{"site_id": f"sid{i:03d}", "slug": slug, "name": slug,
                 "owner": "", "notes": "", "editable": 0, "maintainers": "[]",
                 "created_at": "2026-01-01T00:00:00",
                 "updated_at": "2026-01-01T00:00:00"}
                for i, slug in enumerate(pages)]
        manifest = {
            "golive_version": "0.8.2", "schema_version": 1,
            "registry_backend": "sqlite", "data_backend": "sqlite",
            "storage_backend": "local",
            "counts": {"sites": len(rows), "data_rows": 0,
                       "html_files": len(pages)},
        }
        with tarfile.open(path, "w:gz") as tar:
            def _add(name: str, text: str):
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

            _add("manifest.json", json.dumps(manifest))
            _add("registry.jsonl",
                 "\n".join(json.dumps(r) for r in rows) + "\n")
            _add("data.jsonl", "")
            for row, html in zip(rows, pages.values()):
                _add(f"sites/{row['site_id']}.html", html)
        return str(path)

    def _import(self, pages: dict) -> dict:
        from golive.core.portability import import_archive
        return import_archive(self._archive(pages), yes=True)

    def test_the_clean_pages_are_still_restored(self):
        result = self._import({"ok1": CLEAN_HTML, "leaky": LEAKY_HTML,
                               "ok2": CLEAN_HTML})
        self.assertEqual(
            result["html_files_written"], 2,
            "a single bad page stopped the rest of the restore")

    def test_the_page_with_a_credential_is_not_written(self):
        result = self._import({"ok1": CLEAN_HTML, "leaky": LEAKY_HTML})
        blocked = result["html_files_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["slug"], "leaky")
        self.assertTrue(blocked[0]["findings"])

    def test_a_held_back_page_is_not_reported_as_an_error(self):
        """Nothing malfunctioned — the rest of the restore succeeded."""
        result = self._import({"leaky": LEAKY_HTML})
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["html_files_blocked"])

    def test_a_fully_clean_archive_is_unaffected(self):
        result = self._import({"a": CLEAN_HTML, "b": CLEAN_HTML,
                               "c": CLEAN_HTML})
        self.assertEqual(result["html_files_written"], 3)
        self.assertEqual(result["html_files_blocked"], [])

    def test_the_secret_is_redacted_in_the_report(self):
        result = self._import({"leaky": LEAKY_HTML})
        blob = json.dumps(result["html_files_blocked"], ensure_ascii=False)
        self.assertNotIn("Leak3dSecret99", blob)


class TestTrustedSourcesAreNotScanned(unittest.TestCase):
    """Scanning package-shipped HTML would risk locking golive out of itself."""

    def test_the_bundled_demos_carry_no_credentials(self):
        demo_dir = Path(__file__).resolve().parents[1] / "golive/resources/demo"
        for page in demo_dir.glob("*.html"):
            with self.subTest(page=page.name):
                self.assertEqual(
                    _credential_findings(page.read_text(encoding="utf-8")), [],
                    f"{page.name} would be blocked if demo install scanned; "
                    f"remove the literal or the demo becomes unpublishable")


class TestEveryWritePathIsAccountedFor(unittest.TestCase):
    """A new storage.publish() call site must make a deliberate choice."""

    #: (module dotted path, expected number of publish call sites)
    EXPECTED = {
        "golive.cli": 3,             # publish create, publish update, verify
        "golive.server.editor_api": 1,
        "golive.core.portability": 1,
        "golive.core.demo": 2,       # created, refreshed
    }

    def test_the_number_of_write_sites_has_not_changed(self):
        import importlib
        import inspect
        for dotted, expected in self.EXPECTED.items():
            with self.subTest(module=dotted):
                src = inspect.getsource(importlib.import_module(dotted))
                actual = sum(
                    1 for line in src.splitlines()
                    if ".publish(" in line and not line.strip().startswith("#"))
                self.assertEqual(
                    actual, expected,
                    f"{dotted} now has {actual} storage.publish() call(s), "
                    f"expected {expected}. If you added one, decide whether "
                    f"its HTML is untrusted and needs a credential scan, then "
                    f"update this count.")


if __name__ == "__main__":
    unittest.main()
