"""golive.backends._pg — shared helpers for Postgres backends.

Both the data and registry Postgres stores use these helpers to:

* Read the DSN from the environment (``GOLIVE_PG_DSN`` by default).
* Provide a context-managed connection (psycopg3).
* Avoid importing psycopg at module level so that ``golive --help`` and
  the default SQLite path work without the ``[postgres]`` extra installed.

The connection is a plain ``psycopg.connect()`` call — no connection pool,
because golive is a single-process CLI/server and the SQLite backends it
mirrors also open a fresh connection per operation.  If a deployment needs
pooling it can be added later without changing the store API.
"""

from __future__ import annotations

import os
from typing import Optional


def _missing_dep() -> "ImportError":
    return ImportError(
        "psycopg is required for the postgres backend.\n"
        "  pip install 'html-golive[postgres]'\n"
        "  # or: pip install 'psycopg[binary]>=3.1'"
    )


def get_dsn(dsn_env: str = "GOLIVE_PG_DSN") -> str:
    """Return the DSN string from the environment, or raise."""
    dsn = os.environ.get(dsn_env, "").strip()
    if not dsn:
        raise RuntimeError(
            f"environment variable {dsn_env} is not set; "
            "set it to a libpq connection string, e.g.\n"
            f"  export {dsn_env}='host=localhost dbname=golive user=postgres'"
        )
    return dsn


def pg_connect(dsn_env: str = "GOLIVE_PG_DSN"):
    """Open a psycopg connection.

    Called inside each store method so the import error surfaces only
    when postgres is actually used — not when golive starts.
    """
    try:
        import psycopg  # noqa: I001
    except ImportError:
        raise _missing_dep() from None

    dsn = get_dsn(dsn_env)
    conn = psycopg.connect(dsn, autocommit=False)
    # psycopg3 returns RealDictCursor when configured via row_factory
    from psycopg.rows import dict_row
    conn.row_factory = dict_row
    return conn
