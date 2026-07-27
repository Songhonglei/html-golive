"""golive.core.audit — admin action audit trail (M5).

Append-only JSONL at ``$GOLIVE_HOME/audit.log``. One line per admin/write
action: who did what to which site, when, with optional detail.

Distinct from golive.core.audit_log (operation/performance log): this file
is the *security* trail consumed by ``GET /api/admin/audit``.

Size rotation (M6): before each write, when ``audit.log`` exceeds
``admin.audit_max_bytes`` (default 10 MB, env GOLIVE_AUDIT_MAX_BYTES,
0 = disabled) it is renamed to ``audit.log.1`` and older archives shift
up (``audit.log.1`` -> ``audit.log.2``, ...), keeping ``admin.audit_keep``
generations (default 5, env GOLIVE_AUDIT_KEEP). Rotation failures never
block the write. ``GET /api/admin/audit`` reads only the current
``audit.log`` — rotated archives are for operators to grep/ship.

Writes are single ``write()`` calls on an O_APPEND file descriptor, which
is atomic for reasonable line sizes on POSIX; a failed write never breaks
the calling flow.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from golive.core.paths import get_home

_MAX_DETAIL_CHARS = 2000


def audit_file() -> Path:
    return get_home() / "audit.log"


def _rotation_settings() -> tuple:
    """(max_bytes, keep) from config; safe fallbacks on any failure."""
    try:
        from golive.config import get_config
        adm = get_config().admin
        return max(0, int(adm.audit_max_bytes)), max(1, int(adm.audit_keep))
    except Exception:  # noqa: BLE001 — audit must not break the flow
        return 10 * 1024 * 1024, 5


def _rotate_if_needed(path: Path) -> None:
    """Shift audit.log -> .1 -> .2 ... when over the size threshold.

    Never raises: any OSError along the way leaves the current file in
    place and the write proceeds (the log just grows past the limit).
    """
    max_bytes, keep = _rotation_settings()
    if max_bytes <= 0:
        return
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{keep}")
        if oldest.exists():
            os.remove(oldest)
        for i in range(keep - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            if src.exists():
                os.replace(src, path.with_name(f"{path.name}.{i + 1}"))
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError as e:
        print(f"⚠️  audit rotation failed (non-fatal): {e}",
              file=sys.stderr)


def record(who: str, action: str, slug: str = "",
           detail: Optional[dict] = None) -> None:
    """Append one audit entry (rotating first when oversized). Never raises."""
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
        path = audit_file()
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
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
