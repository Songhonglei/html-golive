"""Scan history — always local SQLite, whatever the registry backend is.

Scan records are this machine's audit trail, not business data: they are
high-volume, discardable, and nobody wants them migrated when they move the
registry to Postgres. ``settings`` and ``security_rules`` already work this
way; this table follows them.

**Findings are stored redacted.** Keeping the matched credential would move
the secret out of the page and into a database — a second copy, in a file
that gets backed up. Only the rule name and a masked excerpt are kept, and
a test greps the database file to prove it.

Retention is capped per site (see ``scan_keep``): every publish writes a row,
so an unbounded table would grow for the life of the install.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Optional

from golive.backends.registry import _records as R
from golive.core.paths import get_registry_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_scans (
    scan_id         TEXT PRIMARY KEY,
    site_id         TEXT NOT NULL DEFAULT '',
    content_sha256  TEXT NOT NULL DEFAULT '',
    ruleset_hash    TEXT NOT NULL DEFAULT '',
    policy          TEXT NOT NULL DEFAULT 'baseline',
    scanner_version TEXT NOT NULL DEFAULT '',
    verdict         TEXT NOT NULL DEFAULT 'pass',
    categories      TEXT NOT NULL DEFAULT '[]',
    findings        TEXT NOT NULL DEFAULT '[]',
    ai_used         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_site
    ON security_scans(site_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_cache
    ON security_scans(content_sha256, ruleset_hash, policy, scanner_version);
"""

VERDICTS = ("pass", "warn", "block")


def _redact_findings(findings) -> list:
    """Strip findings down to what is safe to keep.

    Runs the same masker the scan report uses, so the two cannot drift: if
    output redaction improves, storage improves with it.
    """
    from golive.security.scanner import _mask_secret_literal
    safe = []
    for f in (findings or []):
        if not isinstance(f, dict):
            continue
        excerpt = str(f.get("context", ""))[:200]
        keyword = str(f.get("keyword", ""))[:80]
        safe.append({
            "name": str(f.get("name", ""))[:80],
            "type": str(f.get("type", ""))[:40],
            "strength": str(f.get("strength", ""))[:16],
            # Both fields can carry the literal that matched.
            "keyword": _mask_secret_literal(keyword),
            "context": _mask_secret_literal(excerpt),
        })
    return safe


class ScansStore:
    """Scan history with per-site retention."""

    def __init__(self, db_path=None, keep: int = None):
        self.db_path = str(db_path or get_registry_db())
        self._keep_override = keep
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _keep(self) -> int:
        if self._keep_override is not None:
            return int(self._keep_override)
        try:
            from golive.config import get_config
            return int(getattr(get_config().security, "scan_keep", 20))
        except Exception:
            # A broken config must not stop a publish from recording its scan.
            return 20

    # ── writing ─────────────────────────────────────────────────────────────

    def record(self, site_id: str = "", content_sha256: str = "",
               ruleset_hash: str = "", policy: str = "baseline",
               scanner_version: str = "", verdict: str = "pass",
               categories=None, findings=None, ai_used: bool = False) -> dict:
        """Store one scan result. Findings are redacted before they land."""
        scan_id = uuid.uuid4().hex
        row = {
            "scan_id": scan_id,
            "site_id": site_id or "",
            "content_sha256": content_sha256 or "",
            "ruleset_hash": ruleset_hash or "",
            "policy": policy or "baseline",
            "scanner_version": scanner_version or "",
            "verdict": verdict if verdict in VERDICTS else "pass",
            "categories": sorted(set(categories or [])),
            "findings": _redact_findings(findings),
            "ai_used": bool(ai_used),
            "created_at": R.now(),
        }
        with self._conn() as c:
            c.execute(
                "INSERT INTO security_scans (scan_id, site_id, "
                "content_sha256, ruleset_hash, policy, scanner_version, "
                "verdict, categories, findings, ai_used, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (row["scan_id"], row["site_id"], row["content_sha256"],
                 row["ruleset_hash"], row["policy"], row["scanner_version"],
                 row["verdict"], R.dump_json(row["categories"]),
                 R.dump_json(row["findings"]),
                 1 if row["ai_used"] else 0, row["created_at"]))
        self._prune(row["site_id"])
        return row

    def _prune(self, site_id: str) -> int:
        """Drop the oldest rows for one site beyond the retention limit.

        Scoped per site so a site published hundreds of times cannot evict
        the only scan record another site has. ``keep <= 0`` disables pruning,
        matching the audit log's convention.
        """
        keep = self._keep()
        if keep <= 0 or not site_id:
            return 0
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM security_scans WHERE site_id = ? AND scan_id "
                "NOT IN (SELECT scan_id FROM security_scans WHERE site_id = ? "
                "ORDER BY created_at DESC, scan_id DESC LIMIT ?)",
                (site_id, site_id, keep))
            return cur.rowcount

    # ── reading ─────────────────────────────────────────────────────────────

    def _row(self, r) -> dict:
        d = dict(r)
        d["categories"] = R.load_json(d.get("categories"), [])
        d["findings"] = R.load_json(d.get("findings"), [])
        d["ai_used"] = bool(d.get("ai_used"))
        return d

    def latest_for_site(self, site_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM security_scans WHERE site_id = ? "
                "ORDER BY created_at DESC, scan_id DESC LIMIT 1",
                (site_id,)).fetchone()
        return self._row(r) if r else None

    def history_for_site(self, site_id: str, limit: int = 20) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM security_scans WHERE site_id = ? "
                "ORDER BY created_at DESC, scan_id DESC LIMIT ?",
                (site_id, limit)).fetchall()
        return [self._row(r) for r in rows]

    def find_cached(self, content_sha256: str, ruleset_hash: str,
                    policy: str, scanner_version: str) -> Optional[dict]:
        """A previous verdict for this exact page *and* this exact ruleset.

        All four parts are required. Reusing a verdict because it is "recent"
        would serve a stale answer for an edited page, or keep clearing a page
        after the rule that would now catch it was added.
        """
        if not content_sha256 or not ruleset_hash:
            return None
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM security_scans WHERE content_sha256 = ? AND "
                "ruleset_hash = ? AND policy = ? AND scanner_version = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (content_sha256, ruleset_hash, policy or "baseline",
                 scanner_version or "")).fetchone()
        return self._row(r) if r else None

    def count(self, site_id: str = "") -> int:
        with self._conn() as c:
            if site_id:
                r = c.execute("SELECT COUNT(*) AS n FROM security_scans "
                              "WHERE site_id = ?", (site_id,)).fetchone()
            else:
                r = c.execute(
                    "SELECT COUNT(*) AS n FROM security_scans").fetchone()
        return int(r["n"])

    def delete_for_site(self, site_id: str) -> int:
        with self._conn() as c:
            cur = c.execute("DELETE FROM security_scans WHERE site_id = ?",
                            (site_id,))
            return cur.rowcount


_store = None


def get_scans_store() -> ScansStore:
    """Process-wide store bound to the current GOLIVE_HOME."""
    global _store
    path = str(get_registry_db())
    if _store is None or _store.db_path != path:
        _store = ScansStore(path)
    return _store


def reset_cache() -> None:
    """Drop the cached store — tests switch GOLIVE_HOME between cases."""
    global _store
    _store = None
