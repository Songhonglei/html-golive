"""MySQL 8.4+ business data, using the same SQL CRUD contract as PostgreSQL."""
from __future__ import annotations

import re
from golive.backends._mysql import mysql_connect
from golive.backends.data._sql_store import SQLTemplateStore

DEFAULT_TABLE = "golive_templates"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS `{table}` (
    id VARCHAR(36) PRIMARY KEY,
    model_code VARCHAR(191) NOT NULL,
    name VARCHAR(191) NOT NULL,
    user_id VARCHAR(191) NOT NULL DEFAULT '',
    description LONGTEXT NOT NULL,
    content JSON NOT NULL,
    version VARCHAR(191) NOT NULL DEFAULT '1.0.0',
    sort_index INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_template (model_code, name, user_id),
    KEY ix_model (model_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin
"""
CREATE_TABLE_SQL = _SCHEMA


class TemplateStore(SQLTemplateStore):
    def __init__(self, dsn_env: str = "", table: str = ""):
        if not dsn_env or not table:
            from golive.config import get_config
            cfg = get_config()
            dsn_env = dsn_env or cfg.registry.mysql_dsn_env
            table = table or cfg.data.templates_table
        self.dsn_env = dsn_env or "GOLIVE_MYSQL_DSN"
        self.table = table or DEFAULT_TABLE
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", self.table):
            raise ValueError("MySQL table name must be an ASCII identifier of at most 64 characters")
        with self._conn() as c:
            c.execute(_SCHEMA.format(table=self.table))

    def _conn(self):
        return mysql_connect(self.dsn_env)
