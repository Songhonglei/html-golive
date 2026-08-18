"""golive.backends.registry.rules_store — security rules with dual-source merge.

v0.8.0: Fixes the ``pip install -U`` overwrites-user-rules bug. The built-in
``rules.yaml`` lives inside the package and gets overwritten on upgrade.
This store adds a database layer:

  built-in (rules.yaml) → read-only, cannot be deleted (can be disabled)
  database (custom)     → user-managed, can be added/edited/deleted

The scanner merges both sources. Built-in rules can be toggled
(enabled/disabled) but never removed — preventing users from accidentally
losing critical credential-detection rules.

Table:
  security_rules(
    id          TEXT PRIMARY KEY,   -- 'builtin:<name>' or 'custom:<uuid>'
    type        TEXT NOT NULL,      -- keyword | regex
    name        TEXT NOT NULL,
    strength    TEXT NOT NULL,      -- strong | weak
    pattern     TEXT,               -- for regex rules
    keywords    TEXT,               -- JSON array for keyword rules
    enabled     INTEGER DEFAULT 1,
    builtin     INTEGER DEFAULT 0,  -- 1 = built-in (read-only body)
    updated_by  TEXT DEFAULT '',
    updated_at  TEXT
  )
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_rules (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'unknown',
    strength    TEXT NOT NULL DEFAULT 'weak',
    pattern     TEXT,
    keywords    TEXT,
    enabled     INTEGER DEFAULT 1,
    builtin     INTEGER DEFAULT 0,
    updated_by  TEXT DEFAULT '',
    updated_at  TEXT
);
"""

# ``type`` and ``category`` mean different things and are easy to confuse:
#
#   type      — rule *shape*: "keyword" or "regex". Decides how to match.
#   category  — what kind of secret it is: "credential", "personal_info", …
#               Decides whether a hit may ever be skipped.
#
# The scanner needs ``category``: credential hits are non-skippable, content
# hits are. Until v0.8.2 this table had no category column, so the merge back
# into the scanner guessed it from the rule name — meaning every deployment
# with a database silently lost the distinction. Added as a migration so
# existing installs pick it up without a manual step.
_MIGRATIONS = [
    ("category", "ALTER TABLE security_rules ADD COLUMN "
                 "category TEXT NOT NULL DEFAULT 'unknown'"),
]

_RULES_FILE = Path(__file__).parent.parent.parent / "security" / "rules.yaml"


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _load_builtin_rules() -> list:
    """Load the built-in rules.yaml and return as normalized dicts."""
    if yaml is None:
        raise RuntimeError("pyyaml is required (pip install pyyaml)")
    data = yaml.safe_load(_RULES_FILE.read_text(encoding="utf-8")) or {}
    rules = []
    # ``type`` in rules.yaml is the sensitivity *category*; in this table
    # ``type`` is the rule *shape*. Keep both — the category is what decides
    # whether a hit can be skipped, so losing it is a security regression.
    for r in data.get("keyword_rules") or []:
        rules.append({
            "id": f"builtin:{r.get('name', 'unnamed')}",
            "type": "keyword",
            "name": r.get("name", "unnamed"),
            "category": r.get("type", "unknown"),
            "strength": r.get("strength", "weak"),
            "keywords": json.dumps(r.get("keywords") or [], ensure_ascii=False),
            "pattern": None,
            "enabled": True,
            "builtin": True,
        })
    for r in data.get("regex_rules") or []:
        rules.append({
            "id": f"builtin:{r.get('name', 'unnamed')}",
            "type": "regex",
            "name": r.get("name", "unnamed"),
            "category": r.get("type", "unknown"),
            "strength": r.get("strength", "weak"),
            "keywords": None,
            "pattern": r.get("pattern", ""),
            "enabled": True,
            "builtin": True,
        })
    return rules


class RulesStore:
    """Dual-source security rules: built-in yaml (read-only) + DB (managed)."""

    def __init__(self, db_path=None):
        if db_path is None:
            from golive.core.paths import get_registry_db
            db_path = get_registry_db()
        self.db_path = str(db_path)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            self._migrate(c)
        self._seed_builtin()

    @staticmethod
    def _migrate(conn):
        """Add columns missing from older databases (idempotent)."""
        have = {r[1] for r in conn.execute(
            "PRAGMA table_info(security_rules)").fetchall()}
        for column, ddl in _MIGRATIONS:
            if column not in have:
                conn.execute(ddl)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _seed_builtin(self):
        """Insert built-in rules if not present (idempotent).

        On upgrade, new rules in rules.yaml are picked up; existing
        rules keep their enabled/disabled state (matched by id).
        """
        builtins = _load_builtin_rules()
        with self._conn() as c:
            for r in builtins:
                # category is re-asserted on upgrade so databases written by
                # an older version (which had no such column) get backfilled
                # from the yaml on the next run.
                c.execute(
                    "INSERT INTO security_rules "
                    "(id, type, name, category, strength, pattern, keywords, "
                    "enabled, builtin, updated_by, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,1,1,'',?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  type=excluded.type, name=excluded.name, "
                    "  category=excluded.category, "
                    "  strength=excluded.strength, pattern=excluded.pattern, "
                    "  keywords=excluded.keywords, builtin=1",
                    (r["id"], r["type"], r["name"], r["category"],
                     r["strength"], r["pattern"], r["keywords"], _now())
                )

    def list_all(self) -> list:
        """Return all rules (built-in + custom), with enabled state."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, type, name, category, strength, pattern, keywords, "
                "enabled, builtin, updated_by, updated_at "
                "FROM security_rules ORDER BY builtin DESC, name"
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            if item.get("keywords"):
                try:
                    item["keywords"] = json.loads(item["keywords"])
                except (ValueError, TypeError):
                    item["keywords"] = []
            else:
                item["keywords"] = []
            item["enabled"] = bool(item.get("enabled", 1))
            item["builtin"] = bool(item.get("builtin", 0))
            result.append(item)
        return result

    def list_enabled(self) -> list:
        """Return only enabled rules (for the scanner to consume)."""
        return [r for r in self.list_all() if r["enabled"]]

    def add(self, rule: dict, updated_by: str = "") -> dict:
        """Add a custom rule. Returns the created rule."""
        if rule.get("builtin"):
            raise ValueError("cannot add built-in rules through the API")
        rule_type = str(rule.get("type") or "").strip().lower()
        if rule_type not in ("keyword", "regex"):
            raise ValueError("type must be 'keyword' or 'regex'")
        name = str(rule.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        strength = str(rule.get("strength") or "weak").strip().lower()
        if strength not in ("strong", "weak"):
            raise ValueError("strength must be 'strong' or 'weak'")
        import uuid
        rule_id = f"custom:{uuid.uuid4().hex[:12]}"
        keywords = json.dumps(
            [str(k) for k in (rule.get("keywords") or [])],
            ensure_ascii=False,
        ) if rule_type == "keyword" else None
        pattern = str(rule.get("pattern") or "") if rule_type == "regex" else None
        if rule_type == "regex" and not pattern:
            raise ValueError("pattern is required for regex rules")
        if rule_type == "keyword" and (not keywords or keywords == "[]"):
            raise ValueError("keywords is required for keyword rules")
        with self._conn() as c:
            c.execute(
                "INSERT INTO security_rules "
                "(id, type, name, strength, pattern, keywords, "
                " enabled, builtin, updated_by, updated_at) "
                "VALUES (?,?,?,?,?,?,1,0,?,?)",
                (rule_id, rule_type, name, strength, pattern, keywords,
                 (updated_by or "").strip(), _now())
            )
        return self.get(rule_id)

    def update(self, rule_id: str, patch: dict, updated_by: str = "") -> dict:
        """Update a rule. Built-in rules can only toggle enabled."""
        existing = self.get(rule_id)
        if existing is None:
            raise KeyError(f"rule not found: {rule_id}")
        is_builtin = existing.get("builtin", False)
        allowed = {"enabled"} if is_builtin else {
            "enabled", "name", "strength", "pattern", "keywords", "type"
        }
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(
                f"cannot update fields {sorted(unknown)} on "
                f"{'built-in' if is_builtin else 'custom'} rule"
            )
        sets = []
        params = []
        for k in ("name", "strength", "pattern", "type"):
            if k in patch:
                sets.append(f"{k} = ?")
                params.append(str(patch[k]))
        if "keywords" in patch:
            sets.append("keywords = ?")
            params.append(json.dumps(
                [str(k) for k in patch["keywords"]],
                ensure_ascii=False,
            ))
        if "enabled" in patch:
            sets.append("enabled = ?")
            params.append(1 if patch["enabled"] else 0)
        sets.append("updated_by = ?")
        params.append((updated_by or "").strip())
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(rule_id)
        with self._conn() as c:
            c.execute(
                f"UPDATE security_rules SET {', '.join(sets)} WHERE id = ?",
                params,
            )
        return self.get(rule_id)

    def delete(self, rule_id: str) -> bool:
        """Delete a custom rule. Built-in rules cannot be deleted."""
        existing = self.get(rule_id)
        if existing is None:
            return False
        if existing.get("builtin"):
            raise ValueError(
                "built-in rules cannot be deleted — disable them instead "
                f"(PATCH with {{\"enabled\": false}})"
            )
        with self._conn() as c:
            return c.execute(
                "DELETE FROM security_rules WHERE id = ? AND builtin = 0",
                (rule_id,)
            ).rowcount > 0

    def get(self, rule_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, type, name, category, strength, pattern, keywords, "
                "enabled, builtin, updated_by, updated_at "
                "FROM security_rules WHERE id = ?",
                (rule_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        if item.get("keywords"):
            try:
                item["keywords"] = json.loads(item["keywords"])
            except (ValueError, TypeError):
                item["keywords"] = []
        else:
            item["keywords"] = []
        item["enabled"] = bool(item.get("enabled", 1))
        item["builtin"] = bool(item.get("builtin", 0))
        return item

    def test_text(self, text: str) -> dict:
        """Run a text sample against all enabled rules. Returns hits + verdict."""
        import re as _re
        rules = self.list_enabled()
        hits = []
        for r in rules:
            if r["type"] == "keyword":
                for kw in (r.get("keywords") or []):
                    kw = str(kw)
                    if kw.lower() in text.lower():
                        hits.append({
                            "rule_id": r["id"],
                            "rule_name": r["name"],
                            "type": "keyword",
                            "keyword": kw,
                            "strength": r["strength"],
                        })
            elif r["type"] == "regex":
                try:
                    pattern = _re.compile(r["pattern"], _re.IGNORECASE)
                    m = pattern.search(text)
                    if m:
                        hits.append({
                            "rule_id": r["id"],
                            "rule_name": r["name"],
                            "type": "regex",
                            "keyword": m.group(0)[:24],
                            "strength": r["strength"],
                        })
                except _re.error:
                    pass
        has_strong = any(h["strength"] == "strong" for h in hits)
        return {
            "verdict": "block" if has_strong else (
                "warn" if hits else "pass"
            ),
            "hits": hits,
            "total_rules_checked": len(rules),
            "total_hits": len(hits),
        }


_cached: Optional[RulesStore] = None
_cached_path = ""


def get_rules_store() -> RulesStore:
    """Process-wide RulesStore bound to the current GOLIVE_HOME."""
    global _cached, _cached_path
    from golive.core.paths import get_registry_db
    path = str(get_registry_db())
    if _cached is None or _cached_path != path:
        _cached = RulesStore(path)
        _cached_path = path
    return _cached


def get_merged_rules_for_scanner(extra_files=None) -> dict:
    """Return rules in the format the scanner expects, merged from both sources.

    This replaces the scanner's internal load_rules() when the rules store
    is active.
    """
    import re as _re
    store = get_rules_store()
    enabled = store.list_enabled()
    keyword_rules = []
    regex_rules = []
    # The scanner's "type" is this table's "category". Before v0.8.2 this was
    # derived from the rule name, which silently degraded 'credential' into
    # whatever the name happened to start with — and the scanner keys both its
    # de-duplication and its LLM-review matching on that value.
    for r in enabled:
        category = r.get("category") or "unknown"
        if r["type"] == "keyword":
            keyword_rules.append({
                "type": category,
                "name": r["name"],
                "strength": r["strength"],
                "keywords": r.get("keywords") or [],
            })
        elif r["type"] == "regex":
            try:
                regex_rules.append({
                    "type": category,
                    "name": r["name"],
                    "strength": r["strength"],
                    "pattern": _re.compile(r["pattern"], _re.IGNORECASE),
                })
            except _re.error:
                pass
    return {"keyword_rules": keyword_rules, "regex_rules": regex_rules}
