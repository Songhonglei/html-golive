"""Reading "every site" must not stop at the first page — or count it twice.

``list_all(limit=N)`` returns the *first* N rows and gives no indication that
it truncated. Two failure modes follow from that, and both were live:

1. **Silent truncation.** ``golive list``, ``doctor`` and ``GET /api/sites``
   all called ``list_all()`` bare, so past 200 sites they under-reported —
   ``/api/sites`` in particular returns a ``total`` that callers trust.

2. **Silent duplication.** The export helper paged by *growing the limit* and
   accumulating each response with ``extend()``. But a larger limit re-returns
   the rows already seen, so at exactly 500 sites the first page was counted
   twice: a 500-site export reported 1000 and archived every site twice.
   250-site fixtures never reached the threshold, which is why it survived.

The boundary cases below are the ones that matter: page_size exactly, one
over, and several multiples up.
"""
from __future__ import annotations

import unittest

from golive.backends.registry import (
    REGISTRY_PAGE_SIZE,
    paginated_registry_list,
)


class _FakeRegistry:
    """list_all(limit=N) semantics: the first N rows, newest-first."""

    def __init__(self, total: int):
        self.rows = [{"site_id": f"s{i}", "slug": f"slug-{i}"}
                     for i in range(total)]
        self.calls: list[int] = []

    def list_all(self, limit: int = 200):
        self.calls.append(limit)
        return self.rows[:limit]


class TestEverySiteIsReturnedExactlyOnce(unittest.TestCase):

    # Around the page size, where both bugs lived.
    SIZES = [0, 1, 199, 200, 201, 499, 500, 501, 999, 1000, 1001, 2100]

    def test_count_matches_and_nothing_repeats(self):
        for total in self.SIZES:
            with self.subTest(total=total):
                reg = _FakeRegistry(total)
                got = paginated_registry_list(reg, page_size=500)
                ids = [r["site_id"] for r in got]
                self.assertEqual(
                    len(ids), total,
                    f"expected {total} sites, got {len(ids)}")
                self.assertEqual(
                    len(set(ids)), total,
                    f"{len(ids) - len(set(ids))} duplicate rows returned")

    def test_exactly_page_size_does_not_double_count(self):
        """The regression: total == page_size used to return 2x the rows."""
        reg = _FakeRegistry(500)
        got = paginated_registry_list(reg, page_size=500)
        self.assertEqual(len(got), 500)

    def test_it_stops_asking_once_a_short_page_arrives(self):
        reg = _FakeRegistry(120)
        paginated_registry_list(reg, page_size=500)
        self.assertEqual(reg.calls, [500], "should need a single round trip")

    def test_it_grows_the_limit_when_the_page_comes_back_full(self):
        reg = _FakeRegistry(1200)
        paginated_registry_list(reg, page_size=500)
        self.assertEqual(reg.calls, [500, 1000, 2000])

    def test_the_default_page_size_is_above_the_registry_cap(self):
        """A default of 200 would make the first page always look full."""
        self.assertGreater(REGISTRY_PAGE_SIZE, 200)


class TestCallersUseThePagingHelper(unittest.TestCase):
    """Guard the call sites, so a bare list_all() cannot creep back in."""

    def _bare_call_lines(self, dotted: str) -> list[str]:
        """Line numbers containing a bare ``.list_all()`` call.

        Returns locations rather than the file body: asserting with
        ``assertNotIn`` on the source dumps the whole module into the failure
        message, which buries the actual finding in CI output.
        """
        import importlib
        import inspect
        src = inspect.getsource(importlib.import_module(dotted))
        return [f"line {n}: {line.strip()}"
                for n, line in enumerate(src.splitlines(), 1)
                if ".list_all()" in line]

    def test_cli_list_and_doctor_do_not_call_list_all_bare(self):
        found = self._bare_call_lines("golive.cli")
        self.assertEqual(
            found, [],
            "cli.py calls list_all() with no limit, so it stops at 200:\n  "
            + "\n  ".join(found))

    def test_the_sites_api_does_not_call_list_all_bare(self):
        found = self._bare_call_lines("golive.server.app")
        self.assertEqual(
            found, [],
            "GET /api/sites would report a truncated total:\n  "
            + "\n  ".join(found))

    def test_export_reuses_the_shared_helper(self):
        """portability must not grow a second implementation.

        Asserted on behaviour, not on source text: grepping for ``extend(``
        also matches a docstring that explains the bug, which is exactly how
        this test first failed.
        """
        from golive.core import portability

        reg = _FakeRegistry(500)
        got = portability._paginated_registry_list(reg, page_size=500)
        self.assertEqual(
            len(got), 500,
            "the accumulating implementation is back: at exactly page_size "
            "sites it returns each row twice",
        )


if __name__ == "__main__":
    unittest.main()
