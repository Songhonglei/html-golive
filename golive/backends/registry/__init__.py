"""Registry backends, plus helpers shared by everything that reads them.

``list_all(limit=N)`` returns at most N rows and says nothing about whether
more exist — so any caller that means "every site" has to page. Callers that
forget silently see only the first page: ``golive list`` quietly stops at 200
sites, and ``doctor`` reports a site count that is simply wrong.

The paging helper lives here rather than in the module that needed it first,
so that "read every site" has one implementation instead of one per caller.
"""
from __future__ import annotations

#: Rows per request when walking the whole registry. Large enough that normal
#: installs finish in one round trip.
REGISTRY_PAGE_SIZE = 500


def paginated_registry_list(registry, page_size: int = REGISTRY_PAGE_SIZE):
    """Return every site in the registry, paging past ``list_all``'s cap.

    ``list_all(limit=N)`` returns at most N rows. Getting exactly N back means
    there may be more, so we ask again with a larger limit until a short page
    comes back.

    Safe to hold in memory: the registry stores metadata, not page content —
    even 50k sites is a few hundred KB.
    """
    limit = page_size
    while True:
        batch = registry.list_all(limit=limit)
        if len(batch) < limit:
            return batch
        # Exactly `limit` rows — there may be more behind them.
        limit *= 2
