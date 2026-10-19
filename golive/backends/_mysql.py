"""Lazy PyMySQL connection adapter; credentials stay in an environment DSN."""
from __future__ import annotations

import os
from urllib.parse import parse_qs, unquote, urlsplit


def connection_options(dsn: str) -> dict:
    """Parse mysql:// without echoing credentials on configuration errors."""
    try:
        url = urlsplit(dsn)
        if url.scheme not in ("mysql", "mysql+pymysql") or not url.hostname:
            raise ValueError
        if not url.username or not url.path.strip("/") or url.fragment:
            raise ValueError
        port = url.port or 3306
        query = parse_qs(url.query, keep_blank_values=True)
        if set(query) - {"ssl_ca", "ssl_cert", "ssl_key", "ssl_verify_identity", "unix_socket"}:
            raise ValueError
        opts = dict(host=url.hostname, port=port, user=unquote(url.username),
                    password=unquote(url.password or ""),
                    database=unquote(url.path.lstrip("/")), charset="utf8mb4",
                    connect_timeout=10, read_timeout=15, write_timeout=15,
                    autocommit=False, local_infile=False)
        for key, values in query.items():
            if len(values) != 1 or not values[0]:
                raise ValueError
            if key == "ssl_verify_identity":
                if values[0].lower() not in ("true", "1"):
                    raise ValueError
                opts[key] = True
            else:
                opts[key] = values[0]
        if any(k.startswith("ssl_") for k in query) or (url.hostname not in ("localhost", "127.0.0.1", "::1") and "unix_socket" not in query):
            opts.update(ssl_verify_cert=True, ssl_verify_identity=True)
        return opts
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid MySQL DSN. Use mysql://user:password@host:3306/database; "
                         "percent-encode reserved characters. TLS options: ssl_ca, ssl_cert, ssl_key.") from None


class SQLConnection:
    """Expose the small connection.execute surface used by both SQL stores."""
    def __init__(self, connection):
        self.connection = connection
        self.cursors = []

    def execute(self, statement, params=None):
        cursor = self.connection.cursor()
        self.cursors.append(cursor)
        cursor.execute(statement, params)
        return cursor

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            try:
                for cursor in self.cursors:
                    cursor.close()
            finally:
                self.connection.close()


def mysql_connect(dsn_env="GOLIVE_MYSQL_DSN"):
    try:
        import pymysql
        from pymysql.constants import CLIENT
    except ImportError:
        raise ImportError("PyMySQL is required for the mysql backend. "
                          "Install: pip install 'html-golive[mysql]'") from None
    dsn = os.environ.get(dsn_env, "").strip()
    if not dsn:
        raise RuntimeError(f"Environment variable {dsn_env} is not set; "
                           "configure a mysql:// DSN for your database.")
    opts = connection_options(dsn)
    opts.update(cursorclass=pymysql.cursors.DictCursor, client_flag=CLIENT.FOUND_ROWS)
    return SQLConnection(pymysql.connect(**opts))
