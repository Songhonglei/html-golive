"""MySQL 8.4+ site metadata; HTML stays in the configured object/file storage."""
from __future__ import annotations

from golive.backends._mysql import mysql_connect
from golive.backends.registry._sql_store import SQLRegistry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    site_id CHAR(32) PRIMARY KEY,
    name TEXT NOT NULL,
    slug VARCHAR(255) UNIQUE,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    owner VARCHAR(320) NOT NULL DEFAULT '',
    notes LONGTEXT NOT NULL,
    editable BOOLEAN NOT NULL DEFAULT FALSE,
    maintainers JSON NOT NULL DEFAULT (JSON_ARRAY())
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin
"""
CREATE_TABLE_SQL = _SCHEMA


class MySQLRegistry(SQLRegistry):
    def __init__(self, dsn_env: str = ""):
        if not dsn_env:
            from golive.config import get_config
            dsn_env = get_config().registry.mysql_dsn_env
        self.dsn_env = dsn_env or "GOLIVE_MYSQL_DSN"
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self):
        return mysql_connect(self.dsn_env)
