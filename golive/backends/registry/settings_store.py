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
import math
import os
import re
import sqlite3
from urllib.parse import urlsplit
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
        "description": "Data layer backend: sqlite | postgres | supabase | none",
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

_CONSTRAINTS = {
    "server.port": {"min": 1, "max": 65535},
    "data.backend": {"options": ["sqlite", "postgres", "supabase", "none"]},
    "auth.provider": {"options": ["none", "token", "oidc", "proxy"]},
    "watermark.opacity": {"min": 0, "max": 1, "step": 0.01},
    "watermark.font_size": {"min": 1, "max": 256},
    "watermark.rotation": {"min": -360, "max": 360},
    "admin.audit_max_bytes": {"min": 0, "max": 9223372036854775807},
    "admin.audit_keep": {"min": 1, "max": 100},
}

ENV_SETTING_OVERRIDES = {
    "auth.provider": "GOLIVE_TOKEN",
    "watermark.text": "GOLIVE_WATERMARK_TEXT",
    "watermark.enabled": "GOLIVE_WATERMARK_OFF",
    "security.llm.base_url": "GOLIVE_LLM_BASE_URL",
    "security.llm.model": "GOLIVE_LLM_MODEL",
    "admin.audit_max_bytes": "GOLIVE_AUDIT_MAX_BYTES",
    "admin.audit_keep": "GOLIVE_AUDIT_KEEP",
}


def environment_locked_keys():
    result = set()
    for key, name in ENV_SETTING_OVERRIDES.items():
        value = os.environ.get(name, "").strip()
        if not value or (name == "GOLIVE_WATERMARK_OFF" and value != "1"):
            continue
        if key.startswith("admin.audit_"):
            try:
                int(value)
            except ValueError:
                continue
        result.add(key)
    return result


def _validate_value(key, value):
    if key not in SETTING_DEFINITIONS:
        raise KeyError(f"unknown setting: {key}")
    kind = SETTING_DEFINITIONS[key]["type"]
    if kind == "bool":
        if type(value) is not bool:
            raise ValueError(f"{key}: expected a boolean")
    elif kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key}: expected a {kind}")
        if (isinstance(value, float) and not math.isfinite(value)) or (
            kind == "int" and int(value) != value
        ):
            raise ValueError(f"{key}: expected a finite {kind}")
        try:
            value = int(value) if kind == "int" else float(value)
        except OverflowError:
            raise ValueError(f"{key}: expected a finite {kind}") from None
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{key}: expected a string")
        if len(value) > 4096:
            raise ValueError(f"{key}: value is too long (max 4096 characters)")
    constraints = _CONSTRAINTS.get(key, {})
    if "options" in constraints and value not in constraints["options"]:
        raise ValueError(f"{key}: choose one of {', '.join(constraints['options'])}")
    for bound in ("min", "max"):
        if bound in constraints:
            limit = constraints[bound]
            if (bound == "min" and value < limit) or (bound == "max" and value > limit):
                raise ValueError(f"{key}: {bound} is {limit}")
    if key == "server.host" and (not value.strip() or re.search(r"\s", value)):
        raise ValueError(f"{key}: enter a hostname or IP address")
    if key in ("server.public_base", "auth.oidc.issuer", "security.llm.base_url") and value:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{key}: expected an absolute http(s) URL")
    if key == "watermark.color":
        if not re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value) or any(
            int(channel) > 255 for channel in value.split(",")
        ):
            raise ValueError(f"{key}: expected R,G,B with each channel from 0 to 255")
    return value


def get_database_overrides() -> dict:
    """Read overrides without creating a home, database, or settings table."""
    from golive.core.paths import peek_home
    db_path = peek_home() / "registry.db"
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():
            return {}
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    finally:
        conn.close()
    return {
        key: _validate_value(key, _coerce_value(value, SETTING_DEFINITIONS[key]["type"]))
        for key, value in rows if key in SETTING_DEFINITIONS
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
        env_keys = environment_locked_keys()
        result = {}
        for key, defn in SETTING_DEFINITIONS.items():
            yaml_val = yaml_values.get(key, ...)
            db_val = db_rows.get(key, None)
            if key in env_keys and key in yaml_values:
                value = yaml_val
                source = "environment"
            elif db_val is not None:
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
                "readonly": source == "environment",
                **_CONSTRAINTS.get(key, {}),
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
        return self.set_many({key: value}, updated_by)["updated"][0]

    def set_many(self, items: dict, updated_by: str = "") -> dict:
        """Validate the complete batch before writing it in one transaction."""
        items = {key: _validate_value(key, value) for key, value in items.items()}
        now = _now()
        with self._conn() as c:
            c.executemany(
                "INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                [(key, _serialize_value(value, SETTING_DEFINITIONS[key]["type"]),
                  (updated_by or "").strip(), now) for key, value in items.items()],
            )
        updated = [self._stored_item(key, value) for key, value in items.items()]
        return {"updated": updated,
                "needs_restart": [item["key"] for item in updated if item["needs_restart"]]}

    @staticmethod
    def _stored_item(key, value):
        defn = SETTING_DEFINITIONS[key]
        return {
            "key": key,
            "value": value,
            "source": "database",
            "scope": defn["scope"],
            "type": defn["type"],
            "description": defn["description"],
            "needs_restart": defn["scope"] == "restart",
        }

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
    from golive.config import get_config, load_config
    cfg = load_config(cli_path=get_config().source_path or None, apply_settings=False)
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
        "security.ai_review_enabled": cfg.security.ai_review_enabled,
        "admin.audit_max_bytes": cfg.admin.audit_max_bytes,
        "admin.audit_keep": cfg.admin.audit_keep,
    }
