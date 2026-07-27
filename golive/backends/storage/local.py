"""golive.backends.storage.local — local-filesystem site storage.

Layout:
  $GOLIVE_HOME/sites/<site_id>/index.html      current published HTML
  $GOLIVE_HOME/backups/<site_id>/<ts>.html     rollback snapshots (max 10)
"""


from __future__ import annotations
import datetime
from pathlib import Path

from golive.core.paths import get_backups_dir, get_sites_dir

BACKUP_MAX_KEEP = 10


class LocalStorage:
    """StorageBackend reference implementation (local fs)."""

    # ── read ────────────────────────────────────────────────────────────────

    def site_path(self, site_id: str) -> Path:
        return get_sites_dir() / site_id / "index.html"

    def exists(self, site_id: str) -> bool:
        return self.site_path(site_id).exists()

    def read(self, site_id: str) -> str:
        p = self.site_path(site_id)
        if not p.exists():
            raise FileNotFoundError(f"site content not found: {site_id}")
        return p.read_text(encoding="utf-8")

    # ── write ───────────────────────────────────────────────────────────────

    def publish(self, html: str, site_id: str, backup_previous: bool = True) -> Path:
        """Write site HTML; snapshot the previous version first."""
        p = self.site_path(site_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        if backup_previous and p.exists():
            self._snapshot(site_id, p.read_text(encoding="utf-8"))
        p.write_text(html, encoding="utf-8")
        return p

    def delete(self, site_id: str) -> None:
        import shutil
        d = get_sites_dir() / site_id
        if d.exists():
            shutil.rmtree(d)

    # ── snapshots / rollback ────────────────────────────────────────────────

    def _backup_dir(self, site_id: str) -> Path:
        d = get_backups_dir() / site_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _snapshot(self, site_id: str, html: str) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snap = self._backup_dir(site_id) / f"{ts}.html"
        snap.write_text(html, encoding="utf-8")
        self._prune(site_id)
        return snap

    def _prune(self, site_id: str) -> None:
        snaps = sorted(self._backup_dir(site_id).glob("*.html"))
        while len(snaps) > BACKUP_MAX_KEEP:
            oldest = snaps.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass

    def list_snapshots(self, site_id: str) -> list:
        """Return snapshots newest-first: [{path, ts, size}]."""
        out = []
        for p in sorted(self._backup_dir(site_id).glob("*.html"), reverse=True):
            out.append({
                "path": p,
                "ts": p.stem,
                "size": p.stat().st_size,
            })
        return out

    def rollback(self, site_id: str, snapshot_ts: str = "") -> Path:
        """Restore a snapshot (latest when ts empty). Current HTML is
        snapshotted first so a rollback is itself reversible."""
        snaps = self.list_snapshots(site_id)
        if not snaps:
            raise FileNotFoundError(f"no snapshots for site {site_id}")
        target = None
        if snapshot_ts:
            for s in snaps:
                if s["ts"] == snapshot_ts:
                    target = s
                    break
            if target is None:
                raise FileNotFoundError(f"snapshot {snapshot_ts} not found")
        else:
            target = snaps[0]

        html = target["path"].read_text(encoding="utf-8")
        self.publish(html, site_id, backup_previous=True)
        return self.site_path(site_id)
