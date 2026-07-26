"""golive.core.audit — admin action audit trail (M5).

Append-only JSONL at ``$GOLIVE_HOME/audit.log``. One line per admin/write
action: who did what to which site, when, with optional detail.

Distinct from golive.core.audit_log (operation/performance log): this file
is the *security* trail consumed by ``GET /api/admin/audit`` and is never
rotated automatically — operators archive it themselves.

Writes are single ``write()`` calls on an O_APPEND file descriptor, which
is atomic for reasonable line sizes on POSIX; a failed write never breaks
the calling flow.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any, Optional

from golive.core.paths import get_home

_MAX_DETAIL_CHARS = 2000


def audit_file() -> Path:
    return get_home() / "audit.log"


def record(who: str, action: str, slug: str = "",
           detail: Optional[dict] = None) -> None:
    """Append one audit entry. Never raises."""
    try:
        entry: dict[str, Any] = {
            "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "who": (who or "").strip().lower() or "(token)",
            "action": action,
            "slug": slug or "",
        }
        if detail:
            d = json.dumps(detail, ensure_ascii=False, default=str)
            if len(d) > _MAX_DETAIL_CHARS:
                entry["detail"] = d[:_MAX_DETAIL_CHARS] + "…"  # stored as str
            else:
                entry["detail"] = json.loads(d)  # round-trip => serializable
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(audit_file(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:  # noqa: BLE001 — audit must not break the flow
        print(f"⚠️  audit write failed (non-fatal): {e}", file=sys.stderr)


def read_entries(page: int = 1, size: int = 50, slug: str = "",
                 action: str = "") -> dict:
    """Read entries newest-first with optional slug/action filters.

    Returns {"entries": [...], "total": N, "page": p, "size": s}.
    The file is read line by line (no full-file JSON load); malformed
    lines are skipped.
    """
    page = max(1, int(page))
    size = max(1, min(int(size), 200))
    path = audit_file()
    matches: list[dict] = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if slug and e.get("slug") != slug:
                        continue
                    if action and e.get("action") != action:
                        continue
                    matches.append(e)
        except OSError:
            pass
    matches.reverse()  # newest first
    total = len(matches)
    start = (page - 1) * size
    return {
        "entries": matches[start:start + size],
        "total": total,
        "page": page,
        "size": size,
    }
