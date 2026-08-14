"""Tests for the Postgres data and registry backends.

This file has two tiers:

1. **Contract tests** — verify the Postgres store classes have the same
   public method sets and signatures as their SQLite twins.  These run
   unconditionally (no PG needed).

2. **Integration tests** — exercise real Postgres connections.  These
   are skipped unless ``GOLIVE_PG_DSN`` is set in the environment.

**No mock objects are used for database behaviour.**  Either we connect
to a real Postgres or we skip.  This is deliberate: the project was
previously bitten by a sub-agent whose tests and implementation shared
the same misunderstanding, so both passed while real code was wrong.
"""

from __future__ import annotations

import inspect
import os
import unittest
from unittest import mock


# ── helpers ──────────────────────────────────────────────────────────────────

def _pg_dsn() -> str:
    """Return the DSN from the environment, or '' if not set."""
    return os.environ.get("GOLIVE_PG_DSN", "").strip()


def _has_psycopg() -> bool:
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        return False


PG_AVAILABLE = _has_psycopg() and bool(_pg_dsn())


# ── contract: method parity (runs without PG) ───────────────────────────────

class TestDataMethodParity(unittest.TestCase):
    """Postgres TemplateStore must be a drop-in twin of the SQLite one."""

    def _public(self, cls):
        return {n for n, _ in inspect.getmembers(cls, inspect.isfunction)
                if not n.startswith("_")}

    def test_method_sets_match(self):
        from golive.backends.data.sqlite_store import (
            TemplateStore as SqliteStore)
        from golive.backends.data.postgres_store import (
            TemplateStore as PgStore)
        pg = self._public(PgStore)
        sq = self._public(SqliteStore)
        self.assertTrue(
            pg.issubset(sq),
            f"postgres store missing methods: {sorted(sq - pg)}",
        )
        self.assertTrue(
            sq.issubset(pg),
            f"sqlite store missing methods that postgres has: {sorted(pg - sq)}",
        )

    def test_shared_method_signatures_match(self):
        from golive.backends.data.sqlite_store import (
            TemplateStore as SqliteStore)
        from golive.backends.data.postgres_store import (
            TemplateStore as PgStore)
        for name in self._public(SqliteStore):
            sq_sig = inspect.signature(getattr(SqliteStore, name))
            pg_sig = inspect.signature(getattr(PgStore, name))
            self.assertEqual(
                str(sq_sig), str(pg_sig),
                f"signature drift on {name}(): sqlite={sq_sig} pg={pg_sig}",
            )

    def test_module_exports_match(self):
        from golive.backends.data import sqlite_store, postgres_store
        self.assertEqual(sqlite_store.DEFAULT_TABLE, postgres_store.DEFAULT_TABLE)
        self.assertTrue(hasattr(postgres_store, "CREATE_TABLE_SQL"))
        self.assertEqual(sqlite_store.FILTERABLE, postgres_store.FILTERABLE)
        self.assertEqual(sqlite_store.SORTABLE, postgres_store.SORTABLE)


class TestRegistryMethodParity(unittest.TestCase):
    """Postgres registry must be a drop-in twin of the SQLite one."""

    def _public(self, cls):
        return {n for n, _ in inspect.getmembers(cls, inspect.isfunction)
                if not n.startswith("_")}

    def test_method_sets_match(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.registry.postgres_store import PostgresRegistry
        pg = self._public(PostgresRegistry)
        sq = self._public(SqliteRegistry)
        self.assertTrue(
            pg.issubset(sq),
            f"postgres registry missing methods: {sorted(sq - pg)}",
        )
        self.assertTrue(
            sq.issubset(pg),
            f"sqlite registry missing methods that postgres has: {sorted(pg - sq)}",
        )

    def test_shared_method_signatures_match(self):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.registry.postgres_store import PostgresRegistry
        for name in self._public(SqliteRegistry):
            sq_sig = inspect.signature(getattr(SqliteRegistry, name))
            pg_sig = inspect.signature(getattr(PostgresRegistry, name))
            self.assertEqual(
                str(sq_sig), str(pg_sig),
                f"signature drift on {name}(): sqlite={sq_sig} pg={pg_sig}",
            )


# ── factory wiring (runs without PG) ────────────────────────────────────────

class TestFactoryPostgresBranch(unittest.TestCase):
    """Factory must route 'postgres' to the Postgres stores."""

    def setUp(self):
        os.environ["GOLIVE_HOME"] = "/tmp/golive_test_pg_factory"
        for k in ("GOLIVE_SUPABASE_URL", "GOLIVE_SUPABASE_ANON_KEY",
                  "GOLIVE_SUPABASE_SERVICE_KEY"):
            os.environ.pop(k, None)
        import golive.core.paths as p
        p._resolved_home = None
        from golive.config import reset_config
        reset_config()

    def _write_yaml(self, text: str):
        home = os.environ["GOLIVE_HOME"]
        os.makedirs(home, exist_ok=True)
        path = os.path.join(home, "golive.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        from golive.config import reset_config
        reset_config()

    def test_data_postgres_branch_exists(self):
        self._write_yaml("data:\n  backend: postgres\n")
        from golive.config import get_config
        cfg = get_config()
        self.assertEqual(cfg.data.backend, "postgres")

    def test_registry_postgres_branch_exists(self):
        self._write_yaml("registry:\n  backend: postgres\n")
        from golive.config import get_config
        cfg = get_config()
        self.assertEqual(cfg.registry.backend, "postgres")

    def test_missing_dsn_raises_an_actionable_error(self):
        """No DSN (or no driver) must fail with a message you can act on.

        ``mock.patch.dict`` restores the environment afterwards — an earlier
        version popped GOLIVE_PG_DSN for good, which silently disarmed every
        integration test that ran later in the same process.
        """
        self._write_yaml("data:\n  backend: postgres\n")
        from golive.config import get_config
        cfg = get_config()
        from golive.backends.factory import get_template_store
        with mock.patch.dict(os.environ, {"GOLIVE_PG_DSN": ""}, clear=False):
            with self.assertRaises((ImportError, RuntimeError)) as ctx:
                get_template_store(cfg)
        msg = str(ctx.exception)
        # Either branch must tell the operator exactly what to do next.
        self.assertTrue(
            "GOLIVE_PG_DSN" in msg or "html-golive[postgres]" in msg,
            f"error message is not actionable: {msg!r}")

    def test_factory_error_names_postgres_for_an_unknown_backend(self):
        """An unknown backend must list postgres among the valid choices."""
        self._write_yaml("data:\n  backend: nonsense\n")
        from golive.config import get_config
        from golive.backends.factory import get_template_store
        with self.assertRaises(ValueError) as ctx:
            get_template_store(get_config())
        self.assertIn("postgres", str(ctx.exception))


# ── missing psycopg error (runs without PG) ─────────────────────────────────

class TestMissingPsycopgError(unittest.TestCase):
    """When psycopg is not installed, the error must name the install command."""

    def test_missing_dep_message(self):
        from golive.backends._pg import _missing_dep
        err = _missing_dep()
        self.assertIn("psycopg", str(err))
        self.assertIn("html-golive[postgres]", str(err))


# ── integration tests (skipped without PG) ───────────────────────────────────

@unittest.skipUnless(PG_AVAILABLE,
                      "GOLIVE_PG_DSN not set or psycopg not installed — skipping PG integration tests")
class TestPostgresDataIntegration(unittest.TestCase):
    """Full CRUD against a real Postgres instance."""

    def setUp(self):
        from golive.backends.data.postgres_store import TemplateStore
        # Use a unique table per test run to avoid collisions
        import uuid
        self.table = "pg_test_" + uuid.uuid4().hex[:8]
        self.store = TemplateStore(table=self.table)

    def tearDown(self):
        # Clean up the test table
        try:
            from golive.backends._pg import pg_connect
            with pg_connect() as c:
                c.execute(f"DROP TABLE IF EXISTS {self.table}")
                c.commit()
        except Exception:
            pass

    def test_create_and_get(self):
        row = self.store.create("kb", "note-1", content={"body": "hi"},
                                description="d", version="2.0.0",
                                user_id="alice")
        self.assertTrue(row["id"])
        self.assertEqual(row["model_code"], "kb")
        self.assertEqual(row["name"], "note-1")
        self.assertEqual(row["content"], {"body": "hi"})
        self.assertEqual(row["description"], "d")
        self.assertEqual(row["version"], "2.0.0")
        self.assertEqual(row["user_id"], "alice")

        got = self.store.get(row["id"])
        self.assertEqual(got["content"], {"body": "hi"})
        self.assertIsNone(self.store.get("no-such-id"))

    def test_list_and_count(self):
        for i in range(5):
            self.store.create("kb", f"row-{i}", content={"i": i})
        out = self.store.list("kb")
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["list"]), 5)
        self.assertEqual(self.store.count("kb"), 5)
        self.assertEqual(self.store.count("missing"), 0)

    def test_list_paging(self):
        for i in range(5):
            self.store.create("kb", f"row-{i}")
        p1 = self.store.list("kb", page_no=1, page_size=2)
        p2 = self.store.list("kb", page_no=2, page_size=2)
        p3 = self.store.list("kb", page_no=3, page_size=2)
        self.assertEqual((p1["total"], p2["total"], p3["total"]), (5, 5, 5))
        self.assertEqual([len(p["list"]) for p in (p1, p2, p3)], [2, 2, 1])

    def test_list_filters_by_model(self):
        self.store.create("kb", "a")
        self.store.create("other", "b")
        self.assertEqual(self.store.list("kb")["total"], 1)
        self.assertEqual(self.store.list("other")["total"], 1)

    def test_list_name_prefix(self):
        self.store.create("kb", "alpha-1")
        self.store.create("kb", "alpha-2")
        self.store.create("kb", "beta-1")
        self.assertEqual(self.store.list("kb", name_prefix="alpha")["total"], 2)

    def test_list_user_scope(self):
        self.store.create("kb", "a", user_id="alice")
        self.store.create("kb", "b", user_id="bob")
        self.assertEqual(self.store.list("kb", user_id="alice")["total"], 1)
        self.assertEqual(self.store.list("kb")["total"], 2)

    def test_list_models(self):
        self.store.create("kb", "a")
        self.store.create("kb", "b")
        self.store.create("zeta", "c")
        models = self.store.list_models()
        self.assertEqual(models, [{"model_code": "kb", "count": 2},
                                  {"model_code": "zeta", "count": 1}])

    def test_list_models_empty(self):
        self.assertEqual(self.store.list_models(), [])

    def test_search_without_q(self):
        self.store.create("kb", "a")
        self.store.create("kb", "b")
        self.assertEqual(self.store.search("kb")["total"], 2)

    def test_search_matches_name_desc_content(self):
        self.store.create("kb", "findme", content={"body": "nothing"})
        self.store.create("kb", "other", description="findme in desc")
        self.store.create("kb", "third", content={"body": "findme inside"})
        self.store.create("kb", "nope", content={"body": "unrelated"})
        self.assertEqual(self.store.search("kb", q="findme")["total"], 3)

    def test_search_is_case_insensitive(self):
        self.store.create("kb", "MixedCase")
        self.assertEqual(self.store.search("kb", q="mixedcase")["total"], 1)

    def test_update_patch(self):
        row = self.store.create("kb", "n", content={"a": 1}, description="d0")
        out = self.store.update(row["id"], {"name": "renamed"})
        self.assertEqual(out["name"], "renamed")
        self.assertEqual(out["description"], "d0")
        self.assertEqual(out["content"], {"a": 1})

    def test_update_desc_alias_and_content(self):
        row = self.store.create("kb", "n")
        out = self.store.update(row["id"], {"desc": "new", "content": {"z": 9}})
        self.assertEqual(out["description"], "new")
        self.assertEqual(out["content"], {"z": 9})

    def test_update_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.store.update("nope", {"name": "x"})

    def test_delete(self):
        row = self.store.create("kb", "n")
        self.assertTrue(self.store.delete(row["id"]))
        self.assertFalse(self.store.delete(row["id"]))
        self.assertIsNone(self.store.get(row["id"]))

    def test_upsert_creates_then_updates(self):
        a = self.store.upsert("kb", "same", content={"v": 1})
        b = self.store.upsert("kb", "same", content={"v": 2})
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(b["content"], {"v": 2})
        self.assertEqual(self.store.count("kb"), 1)

    def test_upsert_isolates_by_user(self):
        self.store.upsert("kb", "same", content={"v": 1}, user_id="alice")
        self.store.upsert("kb", "same", content={"v": 1}, user_id="bob")
        self.assertEqual(self.store.count("kb"), 2)

    def test_unicode_and_quotes_roundtrip(self):
        payload = {"中文": "值 with 'quotes' and \"double\"", "emoji": "🚀"}
        row = self.store.create("kb", "名称 '测试'", content=payload)
        got = self.store.get(row["id"])
        self.assertEqual(got["content"], payload)
        self.assertEqual(got["name"], "名称 '测试'")

    def test_content_string_is_parsed(self):
        row = self.store.create("kb", "n", content='{"k": "v"}')
        self.assertEqual(row["content"], {"k": "v"})

    def test_content_non_json_string_wrapped(self):
        row = self.store.create("kb", "n", content="plain text")
        self.assertEqual(row["content"], {"raw": "plain text"})

    def test_content_none_becomes_empty_object(self):
        row = self.store.create("kb", "n")
        self.assertEqual(row["content"], {})

    def test_query_with_filters(self):
        self.store.create("kb", "a", content={"v": 1})
        self.store.create("kb", "b")
        rows, total = self.store.query({"model_code": ("eq", "kb")},
                                       want_count=True)
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 2)

    def test_query_like_filter(self):
        self.store.create("kb", "alpha-1")
        self.store.create("kb", "beta-1")
        rows, _ = self.store.query({"model_code": ("eq", "kb"),
                                    "name": ("like", "alpha*")})
        self.assertEqual(len(rows), 1)

    def test_insert_row(self):
        row = self.store.insert_row({"model_code": "kb", "name": "n",
                                     "content": {"x": 1}})
        self.assertEqual(row["model_code"], "kb")
        self.assertEqual(row["content"], {"x": 1})

    def test_update_rows(self):
        self.store.create("kb", "a")
        self.store.create("kb", "b")
        updated = self.store.update_rows({"model_code": ("eq", "kb")},
                                          {"description": "patched"})
        self.assertEqual(len(updated), 2)
        self.assertTrue(all(r["description"] == "patched" for r in updated))

    def test_delete_rows(self):
        self.store.create("kb", "a")
        self.store.create("kb", "b")
        n = self.store.delete_rows({"model_code": ("eq", "kb")})
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count("kb"), 0)

    def test_non_filterable_column_rejected(self):
        with self.assertRaises(ValueError):
            self.store.query({"content": ("eq", "x")})

    def test_unsupported_operator_rejected(self):
        with self.assertRaises(ValueError):
            self.store.query({"name": ("gt", "x")})


@unittest.skipUnless(PG_AVAILABLE,
                      "GOLIVE_PG_DSN not set or psycopg not installed — skipping PG integration tests")
class TestPostgresRegistryIntegration(unittest.TestCase):
    """Full registry CRUD against a real Postgres instance."""

    def setUp(self):
        from golive.backends.registry.postgres_store import PostgresRegistry
        self.reg = PostgresRegistry()
        # Track by id, not by name: a test that renames its site (test_update
        # does) would otherwise escape a name-prefix sweep and stay behind in
        # a real shared database.
        self._ids: list = []
        self._sweep_by_name()

    def tearDown(self):
        for site_id in self._ids:
            try:
                self.reg.delete(site_id)
            except Exception:  # noqa: BLE001 — cleanup must not mask failures
                pass
        self._sweep_by_name()

    def _sweep_by_name(self):
        """Best-effort sweep of leftovers from older/interrupted runs."""
        try:
            for s in self.reg.list_all(limit=1000):
                if (s.get("name") or "").startswith("pg_test_"):
                    self.reg.delete(s["site_id"])
        except Exception:  # noqa: BLE001
            pass

    def _make(self, **kw):
        """create() + remember the id so tearDown can always remove it."""
        site = self.reg.create(**kw)
        self._ids.append(site["site_id"])
        return site

    def test_create_and_get(self):
        site = self._make(name="pg_test_site", slug="pgtest1",
                               owner="alice@example.com", notes="test")
        self.assertTrue(site["site_id"])
        self.assertEqual(site["name"], "pg_test_site")
        self.assertEqual(site["slug"], "pgtest1")
        self.assertEqual(site["owner"], "alice@example.com")
        self.assertEqual(site["notes"], "test")
        self.assertFalse(site["editable"])
        self.assertEqual(site["maintainers"], [])

        got = self.reg.get(site["site_id"])
        self.assertEqual(got["name"], "pg_test_site")
        self.assertIsNone(self.reg.get("no-such-id"))

    def test_get_by_slug(self):
        site = self._make(name="pg_test_slug", slug="pgtest2")
        got = self.reg.get_by_slug("pgtest2")
        self.assertEqual(got["site_id"], site["site_id"])
        self.assertIsNone(self.reg.get_by_slug(""))

    def test_resolve(self):
        site = self._make(name="pg_test_resolve", slug="pgtest3")
        by_id = self.reg.resolve(site["site_id"])
        by_slug = self.reg.resolve("pgtest3")
        self.assertEqual(by_id["site_id"], site["site_id"])
        self.assertEqual(by_slug["site_id"], site["site_id"])
        self.assertIsNone(self.reg.resolve("nonexistent"))

    def test_update(self):
        site = self._make(name="pg_test_update", slug="pgtest4")
        out = self.reg.update(site["site_id"], name="renamed",
                              notes="updated")
        self.assertEqual(out["name"], "renamed")
        self.assertEqual(out["notes"], "updated")

    def test_update_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.update("nonexistent", name="x")

    def test_touch(self):
        site = self._make(name="pg_test_touch")
        before = site["updated_at"]
        self.reg.touch(site["site_id"])
        after = self.reg.get(site["site_id"])
        self.assertNotEqual(before, after["updated_at"])

    def test_delete(self):
        site = self._make(name="pg_test_delete")
        self.assertTrue(self.reg.delete(site["site_id"]))
        self.assertFalse(self.reg.delete(site["site_id"]))
        self.assertIsNone(self.reg.get(site["site_id"]))

    def test_list_all(self):
        self._make(name="pg_test_list1")
        self._make(name="pg_test_list2")
        sites = self.reg.list_all()
        test_sites = [s for s in sites if s["name"].startswith("pg_test_list")]
        self.assertEqual(len(test_sites), 2)

    def test_slug_taken(self):
        self._make(name="pg_test_slug_taken", slug="pgtest5")
        self.assertTrue(self.reg.slug_taken("pgtest5"))
        self.assertFalse(self.reg.slug_taken("pgtest5_unique"))
        # exclude_site_id
        site = self.reg.get_by_slug("pgtest5")
        self.assertFalse(self.reg.slug_taken("pgtest5", site["site_id"]))

    def test_set_editable(self):
        site = self._make(name="pg_test_editable")
        self.reg.set_editable(site["site_id"], True)
        got = self.reg.get(site["site_id"])
        self.assertTrue(got["editable"])
        self.reg.set_editable(site["site_id"], False)
        got = self.reg.get(site["site_id"])
        self.assertFalse(got["editable"])

    def test_set_editable_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.set_editable("nonexistent", True)

    def test_set_owner(self):
        site = self._make(name="pg_test_owner")
        self.reg.set_owner(site["site_id"], "bob@example.com")
        got = self.reg.get(site["site_id"])
        self.assertEqual(got["owner"], "bob@example.com")

    def test_set_owner_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.set_owner("nonexistent", "x")

    def test_add_remove_list_maintainers(self):
        site = self._make(name="pg_test_maint")
        m = self.reg.add_maintainer(site["site_id"], "alice@example.com")
        self.assertIn("alice@example.com", m)
        m = self.reg.add_maintainer(site["site_id"], "bob@example.com")
        self.assertIn("bob@example.com", m)
        listed = self.reg.list_maintainers(site["site_id"])
        self.assertEqual(len(listed), 2)
        m = self.reg.remove_maintainer(site["site_id"], "alice@example.com")
        self.assertNotIn("alice@example.com", m)
        listed = self.reg.list_maintainers(site["site_id"])
        self.assertEqual(len(listed), 1)

    def test_add_maintainer_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.add_maintainer("nonexistent", "x@example.com")

    def test_remove_maintainer_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.remove_maintainer("nonexistent", "x@example.com")

    def test_list_maintainers_missing_raises(self):
        with self.assertRaises(KeyError):
            self.reg.list_maintainers("nonexistent")


if __name__ == "__main__":
    unittest.main()
