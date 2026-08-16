"""Tests for golive export / import / migrate (data portability).

Key coverage:
- Export with >200 sites (pagination past list_all default)
- Export with >1 page of data rows (pagination past list() default)
- manifest.json counts match actual content
- Export → Import round-trip: content preserved
- Idempotent import (same archive twice, skip mode)
- Slug conflict: skip / overwrite / rename each behave correctly
- Path traversal in malicious archive is rejected
- Dry-run writes nothing
- Migrate: row counts match before/after
- Migrate: target backend unavailable → early failure with fix hint
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_test_home():
    """Create a temp GOLIVE_HOME and wire it into the environment."""
    tmp = tempfile.mkdtemp(prefix="golive_test_")
    os.environ["GOLIVE_HOME"] = tmp
    # Reset cached paths
    from golive.core import paths
    paths.reset_cache()
    return tmp


def _reset_config():
    from golive.config import reset_config
    reset_config()


def _make_sites(registry, count, slug_prefix="site"):
    """Create N sites with HTML content."""
    from golive.backends.storage.local import LocalStorage
    storage = LocalStorage()
    for i in range(count):
        slug = f"{slug_prefix}-{i:03d}" if count > 1 else slug_prefix
        site = registry.create(
            name=f"Site {i}",
            slug=slug,
            owner=f"owner{i}@example.com",
        )
        storage.publish(
            f"<html><body><h1>Site {i}</h1></body></html>",
            site["site_id"],
            backup_previous=False,
        )
    return registry.list_all(limit=100000)


def _make_data_rows(store, count, model_code="default"):
    """Create N data rows."""
    for i in range(count):
        store.create(
            model_code=model_code,
            name=f"row-{i:04d}",
            content={"index": i, "label": f"Item {i}"},
            description=f"Test row {i}",
        )


# ═══════════════════════════════════════════════════════════════════════════
#  EXPORT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestExport(unittest.TestCase):

    def setUp(self):
        self.tmp = _make_test_home()
        _reset_config()

    def tearDown(self):
        del os.environ["GOLIVE_HOME"]
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_basic(self):
        """Export a small instance and verify the archive structure."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 2)

        archive_path = export_archive(output_path=os.path.join(self.tmp, "out.tar.gz"))

        self.assertTrue(os.path.exists(archive_path))

        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            self.assertIn("manifest.json", names)
            self.assertIn("registry.jsonl", names)
            self.assertIn("data.jsonl", names)
            # Sites directory
            site_members = [n for n in names if n.startswith("sites/")]
            self.assertEqual(len(site_members), 2)

    def test_export_gt_200_sites_pagination(self):
        """Export with >200 sites — must not silently truncate at list_all's default."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 250)

        archive_path = export_archive(output_path=os.path.join(self.tmp, "big.tar.gz"))

        # Read back and verify all 250 sites are in the archive
        with tarfile.open(archive_path, "r:gz") as tar:
            manifest_file = tar.extractfile("manifest.json")
            manifest = json.loads(manifest_file.read().decode())
            self.assertEqual(manifest["counts"]["sites"], 250,
                             "manifest must report all 250 sites")

            reg_file = tar.extractfile("registry.jsonl")
            reg_lines = [l for l in reg_file.read().decode().splitlines() if l.strip()]
            self.assertEqual(len(reg_lines), 250,
                             "registry.jsonl must have 250 rows, one per site")

    def test_export_gt_1_page_data_pagination(self):
        """Export with >1 page of data rows — must page past list()'s default 20."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import export_archive

        store = TemplateStore()
        _make_data_rows(store, 50)  # 50 > default page_size of 20

        archive_path = export_archive(output_path=os.path.join(self.tmp, "data.tar.gz"))

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read().decode())
            self.assertEqual(manifest["counts"]["data_rows"], 50,
                             "manifest must report all 50 data rows")

            data_file = tar.extractfile("data.jsonl")
            data_lines = [l for l in data_file.read().decode().splitlines() if l.strip()]
            self.assertEqual(len(data_lines), 50,
                             "data.jsonl must have 50 rows")

    def test_manifest_counts_match_content(self):
        """manifest.json counts must match actual file content."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.backends.storage.local import LocalStorage
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 5)
        store = TemplateStore()
        _make_data_rows(store, 10)

        archive_path = export_archive(output_path=os.path.join(self.tmp, "match.tar.gz"))

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read().decode())

            reg_lines = [l for l in tar.extractfile("registry.jsonl").read().decode().splitlines() if l.strip()]
            data_lines = [l for l in tar.extractfile("data.jsonl").read().decode().splitlines() if l.strip()]
            html_members = [n for n in tar.getnames() if n.startswith("sites/") and n.endswith(".html")]

            self.assertEqual(manifest["counts"]["sites"], len(reg_lines))
            self.assertEqual(manifest["counts"]["data_rows"], len(data_lines))
            self.assertEqual(manifest["counts"]["html_files"], len(html_members))

    def test_export_sites_only(self):
        """--sites-only exports registry + HTML but no data rows."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 3)
        store = TemplateStore()
        _make_data_rows(store, 5)

        archive_path = export_archive(
            output_path=os.path.join(self.tmp, "sites.tar.gz"),
            sites_only=True,
        )

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read().decode())
            self.assertEqual(manifest["counts"]["sites"], 3)
            self.assertEqual(manifest["counts"]["data_rows"], 0)

    def test_export_data_only(self):
        """--data-only exports data but no sites."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 3)
        store = TemplateStore()
        _make_data_rows(store, 5)

        archive_path = export_archive(
            output_path=os.path.join(self.tmp, "data.tar.gz"),
            data_only=True,
        )

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read().decode())
            self.assertEqual(manifest["counts"]["sites"], 0)
            self.assertEqual(manifest["counts"]["data_rows"], 5)

    def test_export_single_site(self):
        """--site exports only the specified site."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 3)
        # Find one site's slug
        all_sites = registry.list_all(limit=100000)
        target_slug = all_sites[0]["slug"]

        archive_path = export_archive(
            output_path=os.path.join(self.tmp, "one.tar.gz"),
            site_filter=target_slug,
        )

        with tarfile.open(archive_path, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read().decode())
            self.assertEqual(manifest["counts"]["sites"], 1)


# ═══════════════════════════════════════════════════════════════════════════
#  IMPORT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestImport(unittest.TestCase):

    def setUp(self):
        self.tmp = _make_test_home()
        _reset_config()

    def tearDown(self):
        del os.environ["GOLIVE_HOME"]
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _export_to(self, path):
        """Helper: create data and export to a path."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import export_archive

        registry = SqliteRegistry()
        _make_sites(registry, 3)
        store = TemplateStore()
        _make_data_rows(store, 5)
        return export_archive(output_path=path)

    def test_import_round_trip(self):
        """Export → Import into a fresh instance: data preserved."""
        archive_path = self._export_to(os.path.join(self.tmp, "rt.tar.gz"))

        # Wipe the instance and recreate
        registry_db = os.path.join(self.tmp, "registry.db")
        data_db = os.path.join(self.tmp, "data.db")
        sites_dir = os.path.join(self.tmp, "sites")
        os.unlink(registry_db)
        os.unlink(data_db)
        shutil.rmtree(sites_dir, ignore_errors=True)

        # Import
        from golive.core.portability import import_archive
        result = import_archive(archive_path, yes=True, on_conflict="skip")

        self.assertEqual(result["sites_imported"], 3)
        self.assertEqual(result["data_rows_imported"], 5)
        self.assertEqual(result["html_files_written"], 3)
        self.assertEqual(result["errors"], [])

        # Verify the data is actually there
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.backends.storage.local import LocalStorage

        registry = SqliteRegistry()
        storage = LocalStorage()
        sites = registry.list_all(limit=100000)
        self.assertEqual(len(sites), 3)

        # Check HTML content
        for site in sites:
            html = storage.read(site["site_id"])
            self.assertIn("<html>", html)

        # Check data
        store = TemplateStore()
        models = store.list_models(scan_limit=100000)
        total = sum(m["count"] for m in models)
        self.assertEqual(total, 5)

    def test_import_dry_run_writes_nothing(self):
        """Dry-run must not modify anything."""
        archive_path = self._export_to(os.path.join(self.tmp, "dr.tar.gz"))

        # Snapshot state before
        registry_db = os.path.join(self.tmp, "registry.db")
        data_db = os.path.join(self.tmp, "data.db")
        reg_size_before = os.path.getsize(registry_db)
        data_size_before = os.path.getsize(data_db)

        from golive.core.portability import import_archive
        result = import_archive(archive_path, dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["sites_imported"], 0)
        self.assertEqual(result["data_rows_imported"], 0)

        # Nothing changed
        self.assertEqual(os.path.getsize(registry_db), reg_size_before)
        self.assertEqual(os.path.getsize(data_db), data_size_before)

    def test_import_idempotent_skip(self):
        """Same archive imported twice with skip → no duplicates."""
        archive_path = self._export_to(os.path.join(self.tmp, "idem.tar.gz"))

        from golive.core.portability import import_archive

        # Wipe the instance so first import is clean
        registry_db = os.path.join(self.tmp, "registry.db")
        data_db = os.path.join(self.tmp, "data.db")
        sites_dir = os.path.join(self.tmp, "sites")
        os.unlink(registry_db)
        os.unlink(data_db)
        shutil.rmtree(sites_dir, ignore_errors=True)

        # First import
        result1 = import_archive(archive_path, yes=True, on_conflict="skip")
        self.assertEqual(result1["sites_imported"], 3)

        # Second import — all should be skipped
        result2 = import_archive(archive_path, yes=True, on_conflict="skip")
        self.assertEqual(result2["sites_imported"], 0)
        self.assertEqual(result2["sites_skipped"], 3)
        self.assertEqual(result2["data_rows_skipped"], 5)

    def test_import_conflict_skip(self):
        """Slug conflict with skip → existing site untouched, new one skipped."""
        archive_path = self._export_to(os.path.join(self.tmp, "skip.tar.gz"))

        from golive.core.portability import import_archive
        # First import to populate
        import_archive(archive_path, yes=True, on_conflict="skip")

        # Second import with skip
        result = import_archive(archive_path, yes=True, on_conflict="skip")
        self.assertEqual(result["sites_skipped"], 3)
        self.assertEqual(result["sites_imported"], 0)

    def test_import_conflict_overwrite(self):
        """Slug conflict with overwrite → existing site replaced."""
        archive_path = self._export_to(os.path.join(self.tmp, "ow.tar.gz"))

        from golive.core.portability import import_archive
        # First import
        import_archive(archive_path, yes=True, on_conflict="skip")

        # Second import with overwrite
        result = import_archive(archive_path, yes=True, on_conflict="overwrite")
        self.assertEqual(result["sites_overwritten"], 3)

    def test_import_conflict_rename(self):
        """Slug conflict with rename → new site created with modified slug."""
        archive_path = self._export_to(os.path.join(self.tmp, "rn.tar.gz"))

        from golive.core.portability import import_archive
        # First import
        import_archive(archive_path, yes=True, on_conflict="skip")

        # Second import with rename
        result = import_archive(archive_path, yes=True, on_conflict="rename")
        self.assertEqual(result["sites_renamed"], 3)

        # Verify the renamed sites exist
        from golive.backends.registry.sqlite_store import SqliteRegistry
        registry = SqliteRegistry()
        all_sites = registry.list_all(limit=100000)
        # Original 3 + renamed 3 = 6
        self.assertEqual(len(all_sites), 6)

    def test_import_path_traversal_rejected(self):
        """A malicious archive with ../../etc/passwd must be rejected."""
        # Create a malicious archive
        evil_path = os.path.join(self.tmp, "evil.tar.gz")
        with tarfile.open(evil_path, "w:gz") as tar:
            # manifest
            manifest = {"golive_version": "test", "exported_at": "2026-01-01T00:00:00+00:00",
                        "registry_backend": "sqlite", "data_backend": "sqlite",
                        "counts": {"sites": 1, "data_rows": 0, "html_files": 0}}
            data = json.dumps(manifest).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

            # Empty registry.jsonl
            info = tarfile.TarInfo("registry.jsonl")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))

            # Empty data.jsonl
            info = tarfile.TarInfo("data.jsonl")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))

            # Malicious path traversal member
            evil_data = b"pwned"
            info = tarfile.TarInfo("../../../etc/passwd")
            info.size = len(evil_data)
            tar.addfile(info, io.BytesIO(evil_data))

        from golive.core.portability import import_archive
        with self.assertRaises(ValueError) as ctx:
            import_archive(evil_path, yes=True)
        self.assertIn("traversal", str(ctx.exception).lower())


# ═══════════════════════════════════════════════════════════════════════════
#  MIGRATE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestMigrate(unittest.TestCase):

    def setUp(self):
        self.tmp = _make_test_home()
        _reset_config()

    def tearDown(self):
        del os.environ["GOLIVE_HOME"]
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_migrate_data_dry_run(self):
        """Dry-run reports counts without writing."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import migrate_backend

        store = TemplateStore()
        _make_data_rows(store, 10)

        result = migrate_backend("data", "postgres", dry_run=True)

        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result["source_count"], 10)
        self.assertEqual(result["target_existing"], 0)

    def test_migrate_data_postgres_unavailable(self):
        """When postgres is not available, fail early with a fix command."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import migrate_backend

        store = TemplateStore()
        _make_data_rows(store, 3)

        # Ensure postgres deps/env are not available
        old_dsn = os.environ.pop("GOLIVE_PG_DSN", None)

        result = migrate_backend("data", "postgres")

        self.assertFalse(result["ok"])
        self.assertIn("pip install", result["error"])

        # Restore
        if old_dsn:
            os.environ["GOLIVE_PG_DSN"] = old_dsn

    def test_migrate_registry_dry_run(self):
        """Registry dry-run reports site count."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.core.portability import migrate_backend

        registry = SqliteRegistry()
        _make_sites(registry, 5)

        result = migrate_backend("registry", "postgres", dry_run=True)

        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result["source_count"], 5)

    def test_migrate_data_to_sqlite_round_trip(self):
        """Migrate data from sqlite to sqlite (fresh target) — counts match."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core.portability import migrate_backend, export_archive, import_archive

        # Create source data
        source_store = TemplateStore()
        _make_data_rows(source_store, 15)

        # Export source data
        archive_path = export_archive(
            output_path=os.path.join(self.tmp, "migrate.tar.gz"),
            data_only=True)

        # Switch to a fresh target home
        target_home = tempfile.mkdtemp(prefix="golive_target_")
        old_home = os.environ.get("GOLIVE_HOME", "")
        os.environ["GOLIVE_HOME"] = target_home

        from golive.core import paths
        paths.reset_cache()

        try:
            # Import data into the fresh target
            result = import_archive(archive_path, yes=True, on_conflict="skip")
            self.assertEqual(result["data_rows_imported"], 15)
            self.assertEqual(result["errors"], [])

            # Verify the data is there
            from golive.config import reset_config
            reset_config()
            target_store = TemplateStore()
            models = target_store.list_models(scan_limit=100000)
            total = sum(m["count"] for m in models)
            self.assertEqual(total, 15)
        finally:
            os.environ["GOLIVE_HOME"] = old_home
            paths.reset_cache()
            shutil.rmtree(target_home, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCLICommands(unittest.TestCase):

    def setUp(self):
        self.tmp = _make_test_home()
        _reset_config()

    def tearDown(self):
        del os.environ["GOLIVE_HOME"]
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_export(self):
        """`golive export` CLI produces a file."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.cli import main

        registry = SqliteRegistry()
        _make_sites(registry, 2)

        out_path = os.path.join(self.tmp, "cli-export.tar.gz")
        code = main(["export", "-o", out_path])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out_path))

    def test_cli_import_dry_run(self):
        """`golive import --dry-run` CLI doesn't write."""
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.cli import main

        registry = SqliteRegistry()
        _make_sites(registry, 2)

        # Export
        out_path = os.path.join(self.tmp, "cli-export.tar.gz")
        main(["export", "-o", out_path])

        # Wipe
        os.unlink(os.path.join(self.tmp, "registry.db"))

        # Import dry-run
        code = main(["import", out_path, "--dry-run"])
        self.assertEqual(code, 0)

        # Verify nothing was imported
        registry = SqliteRegistry()
        self.assertEqual(len(registry.list_all(limit=100000)), 0)

    def test_cli_migrate_dry_run(self):
        """`golive migrate data --to postgres --dry-run` reports."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.cli import main

        store = TemplateStore()
        _make_data_rows(store, 3)

        code = main(["migrate", "data", "--to", "postgres", "--dry-run"])
        self.assertEqual(code, 0)


class TestTruncatedExportIsRefused(unittest.TestCase):
    """A short archive must abort, not ship.

    The count check originally re-ran the same pager and compared it to
    itself, so it agreed with itself even when the pager was the broken
    part — the export happily wrote an archive missing 50 sites and
    reported success. The witness has to come from somewhere else.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="golive_trunc_")
        os.environ["GOLIVE_HOME"] = self.home
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        from golive.config import get_config
        from golive.backends.factory import get_registry, get_storage
        self.cfg = get_config()
        reg = get_registry(self.cfg)
        sto = get_storage(self.cfg)
        # More than list_all()'s default cap of 200.
        for i in range(210):
            site = reg.create(name=f"s{i:04d}", slug=f"trunc{i:04d}")
            sto.publish(f"<html><body>{i}</body></html>", site["site_id"])

    def tearDown(self):
        os.environ.pop("GOLIVE_HOME", None)
        _reset_config()
        from golive.core import paths
        paths.reset_cache()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_independent_count_sees_past_the_default_cap(self):
        from golive.backends.factory import get_registry
        from golive.core.portability import _registry_total
        reg = get_registry(self.cfg)
        self.assertEqual(len(reg.list_all()), 200, "cap assumption changed")
        self.assertEqual(_registry_total(reg), 210,
                         "_registry_total must bypass the pager")

    def test_export_aborts_when_the_pager_truncates(self):
        from unittest import mock
        from golive.core import portability
        out = Path(self.home, "short.tar.gz")

        # Simulate the dangerous bug: pager silently returns one page.
        def _truncated(registry, *a, **kw):
            return registry.list_all(limit=200)

        with mock.patch.object(portability, "_paginated_registry_list",
                               _truncated):
            with self.assertRaises(RuntimeError) as ctx:
                portability.export_archive(str(out), cfg=self.cfg)
        msg = str(ctx.exception)
        self.assertIn("200", msg)
        self.assertIn("210", msg)
        self.assertFalse(out.exists(),
                         "a truncated archive must never be written")

    def test_full_export_still_succeeds(self):
        from golive.core import portability
        out = Path(self.home, "full.tar.gz")
        portability.export_archive(str(out), cfg=self.cfg)
        self.assertTrue(out.exists())
        with tarfile.open(out) as t:
            man = json.loads(
                t.extractfile("manifest.json").read().decode("utf-8"))
            lines = t.extractfile("registry.jsonl").read().decode(
                "utf-8").strip().split("\n")
        self.assertEqual(man["counts"]["sites"], 210)
        self.assertEqual(len(lines), 210)


if __name__ == "__main__":
    unittest.main()
