"""golive.backends.registry.settings_store — global settings with dual-source merge.

v0.8.0: Moves global parameters out of yaml-only land into an API-managed
store. Same dual-source model as the permissions page:

  yaml file  → builtin defaults, read-only (declarative deployments depend on it)
  database   → API-managed overrides, higher priority than yaml

Read merges both, tagging each value with its source ('yaml' or 'database').
Every setting has a ``scope`` — ``hot`` (effective immediately) or
``restart`` (requires server restart to take effect). The API returns
this tag so the UI can warn the user.

Table:
  settings(key TEXT PRIMARY KEY, value TEXT, updated_by TEXT, updated_at TEXT)
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
"""

# ── setting definitions ─────────────────────────────────────────────────────

# Each definition: key → {description, scope, type, default, category}
# scope: "hot" (immediate) or "restart" (needs server restart)
# type: "string" | "int" | "bool" | "json"
SETTING_DEFINITIONS = {
    # ── restart class ──
    "server.host": {
        "description": "Bind address for the HTTP server",
        "scope": "restart",
        "type": "string",
        "default": "127.0.0.1",
        "category": "server",
    },
    "server.port": {
        "description": "HTTP server port",
        "scope": "restart",
        "type": "int",
        "default": 8787,
        "category": "server",
    },
    "server.public_base": {
        "description": "Public base URL for publish links",
        "scope": "restart",
        "type": "string",
        "default": "",
        "category": "server",
    },
    "data.backend": {
        "description": "Data layer backend: sqlite | supabase | none",
        "scope": "restart",
        "type": "string",
        "default": "sqlite",
        "category": "data",
    },
    "auth.provider": {
        "description": "Authentication provider: none | token | oidc | proxy",
        "scope": "restart",
        "type": "string",
        "default": "none",
        "category": "auth",
    },
    "auth.oidc.issuer": {
        "description": "OIDC IdP issuer URL",
        "scope": "restart",
        "type": "string",
        "default": "",
        "category": "auth",
    },
    "auth.oidc.client_id": {
        "description": "OIDC client ID",
        "scope": "restart",
        "type": "string",
        "default": "",
        "category": "auth",
    },
    "auth.oidc.verify_signature": {
        "description": "Verify id_token signatures (disable = security risk)",
        "scope": "restart",
        "type": "bool",
        "default": True,
        "category": "auth",
    },
    # ── hot class ──
    "watermark.enabled": {
        "description": "Enable front-end canvas watermark",
        "scope": "hot",
        "type": "bool",
        "default": False,
        "category": "watermark",
    },
    "watermark.text": {
        "description": "Watermark text (empty = use identity)",
        "scope": "hot",
        "type": "string",
        "default": "",
        "category": "watermark",
    },
    "watermark.opacity": {
        "description": "Watermark opacity (0.0–1.0)",
        "scope": "hot",
        "type": "float",
        "default": 0.15,
        "category": "watermark",
    },
    "watermark.font_size": {
        "description": "Watermark font size (px)",
        "scope": "hot",
        "type": "int",
        "default": 14,
        "category": "watermark",
    },
    "watermark.rotation": {
        "description": "Watermark rotation (degrees)",
        "scope": "hot",
        "type": "int",
        "default": -30,
        "category": "watermark",
    },
    "watermark.color": {
        "description": "Watermark color (R,G,B triplet)",
        "scope": "hot",
        "type": "string",
        "default": "150,150,150",
        "category": "watermark",
    },
    "security.llm.base_url": {
        "description": "LLM API base URL for AI security review",
        "scope": "hot",
        "type": "string",
        "default": "",
        "category": "security",
    },
    "security.llm.model": {
        "description": "LLM model name for AI security review",
        "scope": "hot",
        "type": "string",
        "default": "gpt-4o-mini",
        "category": "security",
    },
    "security.llm.strict_mode": {
        "description": "Refuse publish when LLM is not configured",
        "scope": "hot",
        "type": "bool",
        "default": False,
        "category": "security",
    },
    "security.ai_review_enabled": {
        "description": "Enable AI second-pass review for weak hits",
        "scope": "hot",
        "type": "bool",
        "default": True,
        "category": "security",
    },
    "admin.audit_max_bytes": {
        "description": "Audit log max size before rotation (bytes, 0 = off)",
        "scope": "hot",
        "type": "int",
        "default": 10485760,
        "category": "admin",
    },
    "admin.audit_keep": {
        "description": "Number of archived audit logs to keep",
        "scope": "hot",
        "type": "int",
        "default": 5,
        "category": "admin",
    },
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _coerce_value(value_str: str, expected_type: str):
    """Convert a string DB value to the proper Python type."""
    if expected_type == "bool":
        return value_str.lower() in ("true", "1", "yes")
    elif expected_type == "int":
        try:
            return int(value_str)
        except ValueError:
            return value_str
    elif expected_type == "float":
        try:
            return float(value_str)
        except ValueError:
            return value_str
    elif expected_type == "json":
        try:
            return json.loads(value_str)
        except (ValueError, TypeError):
            return value_str
    return value_str


def _serialize_value(value, expected_type: str) -> str:
    """Convert a Python value to string for DB storage."""
    if expected_type == "bool":
        return "true" if value else "false"
    elif expected_type == "json":
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


class SettingsStore:
    """Dual-source settings: yaml defaults (read-only) + DB overrides."""

    def __init__(self, db_path=None):
        if db_path is None:
            from golive.core.paths import get_registry_db
            db_path = get_registry_db()
        self.db_path = str(db_path)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all(self, yaml_values: dict = None) -> dict:
        """Return all settings grouped by category.

        Each item: {key, value, source ('yaml'|'database'|'default'),
                    scope ('hot'|'restart'), type, description, category}

        yaml_values: dict of key→value from the loaded yaml config.
        """
        yaml_values = yaml_values or {}
        db_rows = self._get_db_all()
        result = {}
        for key, defn in SETTING_DEFINITIONS.items():
            yaml_val = yaml_values.get(key, ...)
            db_val = db_rows.get(key, None)
            if db_val is not None:
                value = _coerce_value(db_val, defn["type"])
                source = "database"
            elif yaml_val is not ... and yaml_val != defn["default"]:
                value = yaml_val
                source = "yaml"
            else:
                value = defn["default"]
                source = "default"

            category = defn["category"]
            if category not in result:
                result[category] = []
            result[category].append({
                "key": key,
                "value": value,
                "source": source,
                "scope": defn["scope"],
                "type": defn["type"],
                "description": defn["description"],
            })
        return result

    def get_flat(self, yaml_values: dict = None) -> dict:
        """Return a flat key→value dict (merged)."""
        yaml_values = yaml_values or {}
        db_rows = self._get_db_all()
        out = {}
        for key, defn in SETTING_DEFINITIONS.items():
            yaml_val = yaml_values.get(key, ...)
            db_val = db_rows.get(key, None)
            if db_val is not None:
                out[key] = _coerce_value(db_val, defn["type"])
            elif yaml_val is not ...:
                out[key] = yaml_val
            else:
                out[key] = defn["default"]
        return out

    def set(self, key: str, value, updated_by: str = "") -> dict:
        """Set a setting in the database. Returns the stored item."""
        if key not in SETTING_DEFINITIONS:
            raise KeyError(f"unknown setting: {key}")
        defn = SETTING_DEFINITIONS[key]
        value_str = _serialize_value(value, defn["type"])
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings (key, value, updated_by, updated_at) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (key, value_str, (updated_by or "").strip(), _now()),
            )
        return {
            "key": key,
            "value": value,
            "source": "database",
            "scope": defn["scope"],
            "type": defn["type"],
            "description": defn["description"],
            "needs_restart": defn["scope"] == "restart",
        }

    def set_many(self, items: dict, updated_by: str = "") -> dict:
        """Set multiple settings. Returns {updated: [...], needs_restart: [...]}."""
        updated = []
        needs_restart = []
        for key, value in items.items():
            if key not in SETTING_DEFINITIONS:
                raise KeyError(f"unknown setting: {key}")
            item = self.set(key, value, updated_by=updated_by)
            updated.append(item)
            if item["needs_restart"]:
                needs_restart.append(key)
        return {"updated": updated, "needs_restart": needs_restart}

    def delete(self, key: str) -> bool:
        """Remove a DB override (falls back to yaml/default)."""
        if key not in SETTING_DEFINITIONS:
            raise KeyError(f"unknown setting: {key}")
        with self._conn() as c:
            return c.execute(
                "DELETE FROM settings WHERE key = ?", (key,)
            ).rowcount > 0

    def _get_db_all(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT key, value FROM settings"
            ).fetchall()
        return {r["key"]: r["value"] for r in rows}


_cached: Optional[SettingsStore] = None
_cached_path = ""


def get_settings_store() -> SettingsStore:
    """Process-wide SettingsStore bound to the current GOLIVE_HOME."""
    global _cached, _cached_path
    from golive.core.paths import get_registry_db
    path = str(get_registry_db())
    if _cached is None or _cached_path != path:
        _cached = SettingsStore(path)
        _cached_path = path
    return _cached


def get_yaml_snapshot() -> dict:
    """Return a flat dict of yaml-sourced values for the known settings."""
    from golive.config import get_config
    cfg = get_config()
    return {
        "server.host": cfg.server.host,
        "server.port": cfg.server.port,
        "server.public_base": cfg.server.public_base,
        "data.backend": cfg.data.backend,
        "auth.provider": cfg.auth.provider,
        "auth.oidc.issuer": cfg.auth.oidc_issuer,
        "auth.oidc.client_id": cfg.auth.oidc_client_id,
        "auth.oidc.verify_signature": cfg.auth.oidc_verify_signature,
        "watermark.enabled": cfg.watermark.enabled,
        "watermark.text": cfg.watermark.text,
        "watermark.opacity": cfg.watermark.opacity,
        "watermark.font_size": cfg.watermark.font_size,
        "watermark.rotation": cfg.watermark.rotation,
        "watermark.color": cfg.watermark.color,
        "security.llm.base_url": cfg.security.llm.base_url,
        "security.llm.model": cfg.security.llm.model,
        "security.llm.strict_mode": cfg.security.llm.strict_mode,
        "security.ai_review_enabled": True,  # derived; no direct config field
        "admin.audit_max_bytes": cfg.admin.audit_max_bytes,
        "admin.audit_keep": cfg.admin.audit_keep,
    }
