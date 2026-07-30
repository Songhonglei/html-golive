"""Tests for the bundled agent skill and `golive skill` installer (v0.7.0).

Never touches the network: --from-github is exercised with a stubbed
requests module.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from golive.core import skill_installer as si


class TestPackagedSkill(unittest.TestCase):
    def test_skill_dir_ships_with_the_package(self):
        d = si.packaged_skill_dir()
        self.assertTrue(d.is_dir(), f"{d} should exist inside the package")
        self.assertTrue((d / "SKILL.md").is_file())

    def test_frontmatter_parses(self):
        meta = si.read_skill_meta(si.packaged_skill_dir())
        self.assertEqual(meta["name"], "html-golive")
        self.assertTrue(meta["version"])
        self.assertTrue(len(meta["description"]) > 80,
                        "description should be substantial enough to route on")

    def test_description_disambiguates_from_hosted_services(self):
        meta = si.read_skill_meta(si.packaged_skill_dir())
        self.assertIn("self-hosted", meta["description"].lower())

    def test_skill_documents_the_probe_first_rule(self):
        text = (si.packaged_skill_dir() / "SKILL.md").read_text(
            encoding="utf-8")
        for needle in ("golive doctor", "golive --version", "GOLIVE_HOME",
                       "golive list"):
            self.assertIn(needle, text, f"SKILL.md must mention {needle}")

    def test_skill_covers_the_core_workflows(self):
        text = (si.packaged_skill_dir() / "SKILL.md").read_text(
            encoding="utf-8")
        for needle in ("golive publish", "--update", "golive rollback",
                       "golive serve", "--host 0.0.0.0", "--data-model",
                       "TemplateAPI", "templateapi:ready", "maintainer",
                       "sqlite", "supabase"):
            self.assertIn(needle, text, f"SKILL.md must cover {needle}")

    def test_references_present_and_non_trivial(self):
        refs = si.packaged_skill_dir() / "references"
        self.assertTrue(refs.is_dir())
        for name in ("cli.md", "data-layer.md"):
            f = refs / name
            self.assertTrue(f.is_file(), f"missing reference {name}")
            self.assertGreater(len(f.read_text(encoding="utf-8")), 1000)

    def test_verify_skill_dir_lists_files(self):
        meta = si.verify_skill_dir(si.packaged_skill_dir())
        self.assertIn("SKILL.md", meta["files"])
        self.assertIn("references/cli.md", meta["files"])

    def test_verify_rejects_directory_without_skill_md(self):
        empty = Path(tempfile.mkdtemp())
        with self.assertRaises(si.SkillInstallError):
            si.verify_skill_dir(empty)

    def test_read_meta_rejects_frontmatter_without_name(self):
        d = Path(tempfile.mkdtemp())
        (d / "SKILL.md").write_text("---\nversion: 1\n---\nbody\n",
                                    encoding="utf-8")
        with self.assertRaises(si.SkillInstallError):
            si.read_skill_meta(d)


class TestTargetDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cwd = self.tmp / "proj"
        self.home = self.tmp / "home"
        self.cwd.mkdir()
        self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_candidates_are_generated_for_cwd_and_home(self):
        cands = si.detect_targets(cwd=self.cwd, home=self.home)
        self.assertTrue(cands)
        paths = [str(c.path) for c in cands]
        self.assertTrue(any(str(self.cwd) in p for p in paths))
        self.assertTrue(any(str(self.home) in p for p in paths))

    def test_existing_directories_rank_first(self):
        (self.home / ".agent" / "skills").mkdir(parents=True)
        cands = si.detect_targets(cwd=self.cwd, home=self.home)
        self.assertTrue(cands[0].exists)
        self.assertEqual(cands[0].path, self.home / ".agent" / "skills")

    def test_project_local_beats_user_level(self):
        (self.home / ".claude" / "skills").mkdir(parents=True)
        (self.cwd / ".claude" / "skills").mkdir(parents=True)
        target = si.resolve_target(cwd=self.cwd, home=self.home)
        self.assertEqual(target, self.cwd / ".claude" / "skills")

    def test_conventions_table_is_extensible_not_hardcoded(self):
        self.assertGreaterEqual(len(si.TARGET_CONVENTIONS), 4)
        bases = {row[0] for row in si.TARGET_CONVENTIONS}
        self.assertEqual(bases, {"cwd", "home"})

    def test_explicit_target_wins(self):
        (self.home / ".claude" / "skills").mkdir(parents=True)
        chosen = self.tmp / "elsewhere"
        self.assertEqual(si.resolve_target(str(chosen), cwd=self.cwd,
                                           home=self.home), chosen)

    def test_no_candidate_raises_with_suggestions(self):
        with self.assertRaises(si.SkillInstallError) as ctx:
            si.resolve_target(cwd=self.cwd, home=self.home)
        msg = str(ctx.exception)
        self.assertIn("--target", msg)
        self.assertIn("skills", msg)


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "skills"
        self.target.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_install_copies_every_file(self):
        res = si.install(target=str(self.target))
        dest = Path(res["installed_to"])
        self.assertEqual(dest, self.target / "html-golive")
        self.assertTrue((dest / "SKILL.md").is_file())
        self.assertTrue((dest / "references" / "cli.md").is_file())
        self.assertTrue((dest / "references" / "data-layer.md").is_file())
        self.assertEqual(res["origin"], "package")
        self.assertEqual(res["name"], "html-golive")
        self.assertTrue(res["version"])

    def test_install_creates_missing_target_dir(self):
        nested = self.tmp / "a" / "b" / "skills"
        res = si.install(target=str(nested))
        self.assertTrue(Path(res["installed_to"]).is_dir())

    def test_installed_content_matches_source(self):
        res = si.install(target=str(self.target))
        src = (si.packaged_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
        dst = (Path(res["installed_to"]) / "SKILL.md").read_text(
            encoding="utf-8")
        self.assertEqual(src, dst)

    def test_second_install_refused_without_force(self):
        si.install(target=str(self.target))
        with self.assertRaises(si.SkillInstallError) as ctx:
            si.install(target=str(self.target))
        self.assertIn("--force", str(ctx.exception))

    def test_force_backs_up_the_previous_copy(self):
        first = si.install(target=str(self.target))
        marker = Path(first["installed_to"]) / "SKILL.md"
        marker.write_text("OLD VERSION", encoding="utf-8")

        second = si.install(target=str(self.target), force=True)
        self.assertTrue(second["backup"], "force must record a backup path")
        backup = Path(second["backup"])
        self.assertTrue(backup.is_dir())
        self.assertEqual((backup / "SKILL.md").read_text(encoding="utf-8"),
                         "OLD VERSION")
        self.assertIn("html-golive",
                      (Path(second["installed_to"]) / "SKILL.md")
                      .read_text(encoding="utf-8"))

    def test_no_pycache_or_dotfiles_copied(self):
        res = si.install(target=str(self.target))
        for rel in res["files"]:
            self.assertNotIn("__pycache__", rel)
            self.assertFalse(Path(rel).name.startswith("."))

    def test_install_selfcheck_runs(self):
        res = si.install(target=str(self.target))
        meta = si.read_skill_meta(res["installed_to"])
        self.assertEqual(meta["name"], "html-golive")


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cwd = self.tmp / "proj"
        self.home = self.tmp / "home"
        (self.cwd / ".claude" / "skills").mkdir(parents=True)
        self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_without_installs(self):
        st = si.status(cwd=self.tmp / "empty", home=self.home)
        self.assertEqual(st["installs"], [])
        self.assertFalse(st["in_sync"])
        self.assertTrue(st["packaged_skill_version"])
        self.assertTrue(st["golive_version"])

    def test_status_detects_install_and_reports_in_sync(self):
        si.install(target=str(self.cwd / ".claude" / "skills"))
        st = si.status(cwd=self.cwd, home=self.home)
        self.assertEqual(len(st["installs"]), 1)
        self.assertEqual(st["stale"], [])
        self.assertTrue(st["in_sync"])

    def test_status_flags_version_drift(self):
        si.install(target=str(self.cwd / ".claude" / "skills"))
        md = self.cwd / ".claude" / "skills" / "html-golive" / "SKILL.md"
        md.write_text(md.read_text(encoding="utf-8")
                      .replace(f"version: {si.read_skill_meta(si.packaged_skill_dir())['version']}",
                               "version: 0.0.1"),
                      encoding="utf-8")
        st = si.status(cwd=self.cwd, home=self.home)
        self.assertEqual(len(st["stale"]), 1)
        self.assertFalse(st["in_sync"])
        self.assertEqual(st["stale"][0]["version"], "0.0.1")

    def test_find_installed_survives_a_broken_skill_md(self):
        dest = self.cwd / ".claude" / "skills" / "html-golive"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
        found = si.find_installed(cwd=self.cwd, home=self.home)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["error"])


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeRequests:
    """Stand-in for the requests module — no sockets involved."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        if self.error:
            raise self.error
        return _FakeResponse(self.payload)


def _make_tarball(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestFromGithubOffline(unittest.TestCase):
    """--from-github paths, exercised with a stubbed requests module."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "skills"
        self.target.mkdir()
        self._saved = sys.modules.get("requests")

    def tearDown(self):
        if self._saved is not None:
            sys.modules["requests"] = self._saved
        else:
            sys.modules.pop("requests", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _install_fake(self, fake):
        sys.modules["requests"] = fake

    def test_downloaded_skill_is_installed(self):
        tarball = _make_tarball({
            "html-golive-main/golive/resources/skill/SKILL.md":
                "---\nname: html-golive\nversion: 9.9.9\n"
                "description: remote copy\n---\nremote body\n",
            "html-golive-main/golive/resources/skill/references/cli.md":
                "remote cli reference",
            "html-golive-main/README.md": "ignored",
        })
        self._install_fake(_FakeRequests(payload=tarball))
        res = si.install(target=str(self.target), from_github=True)
        self.assertEqual(res["origin"], "github")
        self.assertEqual(res["version"], "9.9.9")
        dest = Path(res["installed_to"])
        self.assertIn("remote body",
                      (dest / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue((dest / "references" / "cli.md").is_file())
        self.assertFalse((dest / "README.md").exists(),
                         "only the skill subtree should be extracted")

    def test_network_failure_suggests_the_bundled_copy(self):
        self._install_fake(_FakeRequests(error=OSError("name resolution")))
        with self.assertRaises(si.SkillInstallError) as ctx:
            si.install(target=str(self.target), from_github=True)
        msg = str(ctx.exception)
        self.assertIn("--from-github", msg)
        self.assertIn("bundled", msg)

    def test_archive_without_skill_dir_is_reported(self):
        self._install_fake(_FakeRequests(
            payload=_make_tarball({"html-golive-main/README.md": "x"})))
        with self.assertRaises(si.SkillInstallError) as ctx:
            si.install(target=str(self.target), from_github=True)
        self.assertIn("no skill directory", str(ctx.exception))

    def test_corrupt_archive_is_reported(self):
        self._install_fake(_FakeRequests(payload=b"not a tarball"))
        with self.assertRaises(si.SkillInstallError):
            si.install(target=str(self.target), from_github=True)

    def test_path_traversal_entries_are_skipped(self):
        tarball = _make_tarball({
            "html-golive-main/golive/resources/skill/SKILL.md":
                "---\nname: html-golive\nversion: 1.0.0\n"
                "description: d\n---\nbody\n",
            "html-golive-main/golive/resources/skill/../../../evil.md":
                "pwned",
        })
        self._install_fake(_FakeRequests(payload=tarball))
        res = si.install(target=str(self.target), from_github=True)
        self.assertFalse((self.tmp / "evil.md").exists())
        self.assertTrue(Path(res["installed_to"], "SKILL.md").is_file())


class TestCliSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["GOLIVE_HOME"] = str(self.tmp / "home")
        import golive.core.paths as p
        p._resolved_home = None
        from golive.config import reset_config
        reset_config()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skill_path_exits_zero(self):
        from golive.cli import main
        self.assertEqual(main(["skill", "path"]), 0)

    def test_skill_status_exits_zero(self):
        from golive.cli import main
        self.assertEqual(main(["skill", "status"]), 0)

    def test_skill_install_with_target(self):
        from golive.cli import main
        target = self.tmp / "skills"
        target.mkdir()
        self.assertEqual(main(["skill", "install", "--target", str(target)]), 0)
        self.assertTrue((target / "html-golive" / "SKILL.md").is_file())

    def test_duplicate_install_exits_nonzero(self):
        from golive.cli import main
        target = self.tmp / "skills"
        target.mkdir()
        main(["skill", "install", "--target", str(target)])
        self.assertEqual(main(["skill", "install", "--target", str(target)]), 1)

    def test_force_install_exits_zero(self):
        from golive.cli import main
        target = self.tmp / "skills"
        target.mkdir()
        main(["skill", "install", "--target", str(target)])
        self.assertEqual(
            main(["skill", "install", "--target", str(target), "--force"]), 0)


class TestPackaging(unittest.TestCase):
    def test_pyproject_declares_the_skill_files(self):
        root = Path(si.__file__).resolve().parent.parent.parent
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("resources/skill/SKILL.md", text)
        self.assertIn("resources/skill/references/*.md", text)


if __name__ == "__main__":
    unittest.main()
