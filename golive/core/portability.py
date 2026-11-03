"""golive.core.portability — export, import and migrate golive state.

This module backs three CLI commands:

* ``golive export``  — produce a tar.gz archive of an entire instance
* ``golive import``   — restore an archive (possibly into a fresh instance)
* ``golive migrate``  — copy data or registry from one backend to another

Design principle: **the archive is a contract**.  ``manifest.json`` is
intentionally small so a human or script can inspect it without unpacking
the whole file.  ``registry.jsonl`` and ``data.jsonl`` are one-record-per-
line so they stream well.  ``sites/<site_id>.html`` keeps the actual page
content separate from metadata.

The single biggest correctness risk is **pagination truncation**:
``registry.list_all(limit=200)`` silently caps at 200, and the data
``list()`` / ``query()`` methods page at 20 rows by default.  Export
therefore iterates in fixed-size pages and keeps going until a page
returns fewer rows than requested.  At the end, the manifest's counts
are cross-checked against both the rows actually written and the
backend's own ``count()``; any mismatch aborts the export rather than
shipping a silently incomplete archive.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import tempfile
import datetime
import uuid
from pathlib import Path
from typing import Optional

# ── pagination constants ────────────────────────────────────────────────────
# Deliberately larger than the registry default (200) to reduce round-trips,
# but not so large that a single page overwhelms memory. Re-exported from the
# registry package so the page size has one definition.
from golive.backends.registry import (  # noqa: E402
    REGISTRY_PAGE_SIZE,
    paginated_registry_list,
)

DATA_PAGE_SIZE = 500


# ═══════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _paginated_registry_list(registry, page_size: int = REGISTRY_PAGE_SIZE):
    """Deprecated alias — see ``golive.backends.registry``.

    Kept because the export tests and the truncation guard reference it by
    name. The implementation moved to the registry package so that ``list``
    and ``doctor`` share it rather than growing their own copies.

    The earlier version here accumulated every page with ``extend()``, but
    ``list_all(limit=N)`` returns the *first* N rows, not the Nth page — so
    once an install passed 500 sites the first page was counted twice. An
    export of 500 sites reported 1000 and archived each of them twice.
    """
    return paginated_registry_list(registry, page_size)


def _paginated_data_list(store, page_size: int = DATA_PAGE_SIZE):
    """Iterate every data row across all models, paging past list()'s default.

    First we ask ``list_models()`` for every model_code.  Then for each
    model we page through ``list()`` with ``page_no`` / ``page_size`` until
    a page returns fewer rows than requested (or the total is reached).
    """
    models = store.list_models(scan_limit=100000)
    all_rows = []
    for m in models:
        model_code = m["model_code"]
        page_no = 1
        while True:
            result = store.list(model_code, page_no=page_no,
                                page_size=page_size)
            rows = result.get("list", [])
            all_rows.extend(rows)
            total = result.get("total", 0)
            if len(rows) < page_size or (page_no * page_size) >= total:
                break
            page_no += 1
    return all_rows


def _golive_version() -> str:
    from golive import __version__
    return __version__


def _backend_labels(cfg) -> dict:
    """Return the backend type labels for manifest.json."""
    return {
        "registry_backend": cfg.registry.backend or "sqlite",
        "data_backend": cfg.data.backend or "sqlite",
    }


def export_archive(
    output_path: Optional[str] = None,
    *,
    sites_only: bool = False,
    data_only: bool = False,
    site_filter: str = "",
    cfg=None,
) -> str:
    """Export the full golive state to a tar.gz archive.

    Returns the path to the written archive.

    Raises ``RuntimeError`` if the final count check fails — a partial
    archive is never written.
    """
    from golive.backends.factory import get_registry, get_storage, get_template_store
    from golive.config import get_config

    if cfg is None:
        cfg = get_config()

    registry = get_registry(cfg)
    storage = get_storage(cfg)
    data_store = get_template_store(cfg) if not sites_only else None

    # ── gather registry rows ──────────────────────────────────────────────
    if data_only:
        registry_rows = []
    else:
        all_sites = _paginated_registry_list(registry)
        if site_filter:
            # Filter by slug or site_id
            registry_rows = [
                s for s in all_sites
                if s.get("slug") == site_filter
                or s.get("site_id") == site_filter
            ]
        else:
            registry_rows = all_sites

    # ── gather data rows ───────────────────────────────────────────────────
    if data_only or (data_store is not None and not sites_only):
        if data_store is None:
            data_rows = []
        else:
            if site_filter:
                # When exporting a single site, still export all data
                # (data is not per-site in the current model — it's per
                # model_code). We include all data so the site works.
                data_rows = _paginated_data_list(data_store)
            else:
                data_rows = _paginated_data_list(data_store)
    else:
        data_rows = []

    # ── gather HTML content ────────────────────────────────────────────────
    html_files = {}
    if not data_only:
        for site in registry_rows:
            site_id = site["site_id"]
            try:
                html = storage.read(site_id)
                html_files[site_id] = html
            except FileNotFoundError:
                # Site metadata exists but content is missing — still
                # export the metadata, note the missing HTML.
                pass

    # ── cross-check counts ────────────────────────────────────────────────
    # Verify that we actually got everything by counting from the backend.
    # For registry: re-list and count.
    if not data_only and not site_filter:
        # The check must come from a *different* source than the pager.
        # Re-running _paginated_registry_list() and comparing it to itself
        # always agrees — including when the pager is the thing that is
        # broken, which is the only failure this check exists to catch.
        actual = _registry_total(registry)
        if actual is not None and actual != len(registry_rows):
            raise RuntimeError(
                f"Registry count mismatch during export: collected "
                f"{len(registry_rows)} sites but the backend holds {actual}. "
                f"Aborting rather than writing a silently incomplete archive "
                f"— a backup missing sites is worse than no backup.")

    # For data: sum count() across all models.
    if data_store is not None and not sites_only:
        models = data_store.list_models(scan_limit=100000)
        total_expected = sum(m.get("count", 0) for m in models)
        if len(data_rows) != total_expected:
            raise RuntimeError(
                f"Data row count mismatch during export: collected {len(data_rows)} "
                f"rows but backend reports {total_expected}. Aborting to avoid "
                f"writing a silently incomplete archive."
            )

    # ── build manifest ─────────────────────────────────────────────────────
    labels = _backend_labels(cfg)
    manifest = {
        "golive_version": _golive_version(),
        "exported_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "registry_backend": labels["registry_backend"],
        "data_backend": labels["data_backend"],
        "counts": {
            "sites": len(registry_rows),
            "data_rows": len(data_rows),
            "html_files": len(html_files),
        },
    }

    # ── write archive ─────────────────────────────────────────────────────
    if output_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"golive-export-{ts}.tar.gz"

    # Write to a temp file first, then rename — never ship a partial archive.
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tar.gz", dir=os.path.dirname(os.path.abspath(output_path)) or ".")
    os.close(tmp_fd)

    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            # manifest.json
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

            # registry.jsonl
            reg_buf = io.BytesIO()
            for site in registry_rows:
                reg_buf.write(
                    (json.dumps(site, ensure_ascii=False, default=str) + "\n").encode())
            reg_bytes = reg_buf.getvalue()
            info = tarfile.TarInfo("registry.jsonl")
            info.size = len(reg_bytes)
            tar.addfile(info, io.BytesIO(reg_bytes))

            # data.jsonl
            data_buf = io.BytesIO()
            for row in data_rows:
                data_buf.write(
                    (json.dumps(row, ensure_ascii=False, default=str) + "\n").encode())
            data_bytes = data_buf.getvalue()
            info = tarfile.TarInfo("data.jsonl")
            info.size = len(data_bytes)
            tar.addfile(info, io.BytesIO(data_bytes))

            # sites/<site_id>.html
            for site_id, html in html_files.items():
                html_bytes = html.encode("utf-8")
                info = tarfile.TarInfo(f"sites/{site_id}.html")
                info.size = len(html_bytes)
                tar.addfile(info, io.BytesIO(html_bytes))

        os.rename(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_path


# ═══════════════════════════════════════════════════════════════════════════
#  IMPORT
# ═══════════════════════════════════════════════════════════════════════════

def _find_existing_row(data_store, model_code: str, name: str,
                       user_id: str = ""):
    """Return an existing row matching model_code+name+user_id, or None.

    Goes through ``list()``, which every data backend implements, instead of
    a raw SQL probe. ``list(name_prefix=...)`` is a *prefix* match, so the
    candidate names are compared exactly here — otherwise importing "row-1"
    would be treated as a conflict with an existing "row-10".
    """
    page_no = 1
    while True:
        page = data_store.list(model_code, name_prefix=name,
                               user_id=user_id, page_no=page_no, page_size=50)
        rows = page["list"]
        for row in rows:
            if row.get("name") == name and (row.get("user_id") or "") == user_id:
                return row
        if len(rows) < 50 or page_no * 50 >= page.get("total", float("inf")):
            return None
        page_no += 1


def _credential_findings(html: str) -> list:
    """Strong (credential) findings in a page, as ``[{name, keyword}]``.

    Used by import, which needs the verdict without the side effects of
    ``run_scan``: no printing (import prints one summary at the end) and no
    content warnings (these pages were already published once, so warning
    about the word "salary" again is noise). A literal secret is different —
    an archive is untrusted input, and restoring one would republish it.

    Returns an empty list when the scanner is unavailable, so a missing
    optional dependency cannot make a restore impossible.
    """
    try:
        from golive.security.scanner import load_rules, scan_html
        result = scan_html(html, load_rules())
    except Exception:  # noqa: BLE001 — never block a restore on scanner setup
        return []
    return [{"name": d.get("name", ""), "keyword": d.get("keyword", "")}
            for d in result.strong_hits]


def _registry_total(registry):
    """How many sites the backend really holds, bypassing the pager.

    Deliberately a `COUNT(*)`, not another `list_all()` walk: this number is
    the independent witness the export's count check compares against. If it
    went through the same pagination code, a broken pager would agree with
    itself and the check would pass while the archive was short.

    Returns ``None`` when the backend offers no way to count cheaply — the
    caller then skips the check rather than blocking the export.
    """
    try:
        if hasattr(registry, "db_path"):
            import sqlite3
            with sqlite3.connect(registry.db_path, timeout=10) as c:
                return int(c.execute(
                    "SELECT COUNT(*) FROM sites").fetchone()[0])
        if hasattr(registry, "dsn_env"):
            with registry._conn() as c:
                cur = c.execute("SELECT COUNT(*) FROM sites")
                row = cur.fetchone()
                if row is None:
                    return None
                return int(row[0] if not isinstance(row, dict)
                           else list(row.values())[0])
    except Exception:  # noqa: BLE001 — the check is a safety net, not a gate
        return None
    return None


def _registry_create_with_id(registry, site_id: str, name: str, slug: str,
                             owner: str, notes: str) -> dict:
    """Create a registry entry with a specific site_id.

    The standard ``create()`` generates a random UUID.  For import we need
    to preserve the original site_id so HTML files and cross-references
    stay intact.
    """
    # Try direct SQL insert for sqlite and postgres backends
    if hasattr(registry, "db_path"):
        # SQLite registry
        import sqlite3
        import datetime
        slug_norm = slug.strip().lower() or None
        now = datetime.datetime.now().isoformat(timespec="microseconds")
        with sqlite3.connect(registry.db_path, timeout=10) as c:
            c.row_factory = sqlite3.Row
            c.execute(
                "INSERT INTO sites (site_id, name, slug, created_at, "
                "updated_at, owner, notes) VALUES (?,?,?,?,?,?,?)",
                (site_id, name, slug_norm, now, now, owner, notes))
        return registry.get(site_id)
    elif hasattr(registry, "dsn_env"):
        # Postgres registry
        import datetime
        slug_norm = slug.strip().lower() or None
        now = datetime.datetime.now().isoformat(timespec="microseconds")
        with registry._conn() as c:
            c.execute(
                "INSERT INTO sites (site_id, name, slug, created_at, "
                "updated_at, owner, notes) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (site_id, name, slug_norm, now, now, owner, notes))
            c.commit()
        return registry.get(site_id)
    elif hasattr(registry, "client") and hasattr(registry, "table"):
        # PostgREST-backed registry (Supabase). No SQL connection needed:
        # its own create() already builds the row and sets site_id
        # explicitly, so preserving an incoming id is just a matter of
        # putting ours in that field instead of a fresh uuid4.
        import datetime
        now = datetime.datetime.now().astimezone().isoformat(
            timespec="microseconds")
        row = {
            "site_id": site_id,
            "name": name,
            "slug": slug.strip().lower() or None,
            "created_at": now,
            "updated_at": now,
            "owner": owner,
            "notes": notes,
        }
        created = registry.client.insert(registry.table, row)
        return created[0] if created else row
    else:
        # Do NOT fall back to create(): it mints a fresh site_id, and the
        # archive's HTML is filed under the original one. The import would
        # "succeed" while every restored page pointed at storage that does
        # not exist — silent data loss is worse than refusing to import.
        raise RuntimeError(
            f"cannot preserve site_id on a "
            f"{type(registry).__name__} registry: import needs to write an "
            f"explicit site_id and this backend exposes no way to do it. "
            f"Export/import is supported for the sqlite and postgres "
            f"registries; migrate to one of those first.")



def _restore_data_record(store, row, policy):
    """Never quietly substitute a different ID for an archived record."""
    from golive.backends.data._restore import same_record, RestoreConflict, RestoreMismatch
    by_id = store.get(row["id"])
    by_key = _find_existing_row(store, row["model_code"], row["name"], row["user_id"])
    conflict = by_id or by_key
    payload = dict(row)
    if conflict:
        if policy == "migration":
            if by_id and same_record(row, by_id) and (not by_key or by_key["id"] == row["id"]):
                return "skipped", by_id
            raise RestoreConflict("Target data conflict differs from source; target left unchanged")
        if policy == "rename":
            payload["id"] = str(uuid.uuid4())
            payload["name"] += "-imported-" + row["id"][:8]
            if _find_existing_row(store, payload["model_code"], payload["name"], payload["user_id"]):
                raise RestoreConflict("Renamed data record already exists; target left unchanged")
        else:
            if by_id and any(by_id.get(k) != row[k] for k in ("model_code", "name", "user_id")):
                raise RestoreConflict("Data ID belongs to a different logical record; target left unchanged")
            if policy == "skip":
                return "skipped", conflict
            if by_key and by_key["id"] != row["id"]:
                raise RestoreConflict("Logical data key has a different ID; overwrite cannot preserve references")
    restored = store.restore_row(payload, overwrite=bool(by_id) and policy == "overwrite")
    if not same_record(payload, restored):
        raise RestoreMismatch("Data readback differs from archived identity, content or metadata")
    return "imported", restored


def _prepare_data_rows(rows):
    from golive.backends.data._restore import restore_payload
    prepared, ids, keys, defaults = [], set(), set(), {}
    for row in rows:
        payload = restore_payload(row)
        logical_key = tuple(payload[k] for k in ("model_code", "name", "user_id"))
        if payload["id"] in ids or logical_key in keys:
            raise ValueError("Archive contains duplicate data IDs or logical keys")
        ids.add(payload["id"]); keys.add(logical_key)
        missing = sorted(set(payload) - set(row))
        if missing:
            defaults[payload["id"]] = missing
        prepared.append(payload)
    return prepared, defaults


def _read_archive(path: str) -> tuple:
    """Read an archive's contents into memory. Returns (manifest, registry_rows, data_rows, html_map)."""
    with tarfile.open(path, "r:gz") as tar:
        # Validate before extracting anything
        members = tar.getmembers()
        member_names = [m.name for m in members]
        if len(set(member_names)) != len(member_names):
            raise ValueError("Archive has duplicate members")
        # Check for path traversal
        for m in members:
            if not m.isfile():
                raise ValueError("Archive members must be regular files")
            if m.name.startswith("/") or ".." in m.name:
                raise ValueError(
                    f"Refusing to extract path-traversal member: {m.name!r}"
                )

        # Read manifest
        manifest = None
        for m in members:
            if m.name == "manifest.json":
                f = tar.extractfile(m)
                if f:
                    manifest = json.loads(f.read().decode("utf-8"))
                break

        if manifest is None:
            raise ValueError("Archive is missing manifest.json")

        # Read registry.jsonl
        registry_rows = []
        for m in members:
            if m.name == "registry.jsonl":
                f = tar.extractfile(m)
                if f:
                    for line in f:
                        line = line.strip()
                        if line:
                            registry_rows.append(json.loads(line.decode("utf-8")))
                break

        # Read data.jsonl
        data_rows = []
        for m in members:
            if m.name == "data.jsonl":
                f = tar.extractfile(m)
                if f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data_rows.append(json.loads(line.decode("utf-8")))
                break

        # Read HTML files
        html_map = {}
        for m in members:
            if m.name.startswith("sites/") and m.name.endswith(".html"):
                site_id = m.name[len("sites/"):-len(".html")]
                f = tar.extractfile(m)
                if f:
                    html_map[site_id] = f.read().decode("utf-8")

    return manifest, registry_rows, data_rows, html_map


class ArchiveValidationError(ValueError):
    """Archive parsing/validation failed before a target was opened."""


def _validated_archive(archive_path):
    try:
        manifest, registry_rows, data_rows, html_map = _read_archive(archive_path)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("counts"), dict):
            raise ValueError("Archive manifest/counts must be objects")
        if any(not isinstance(row, dict) for row in registry_rows):
            raise ValueError("Archive registry rows must be objects")
        site_ids = set()
        for site in registry_rows:
            ident = site.get("site_id")
            if not isinstance(ident, str) or not ident or ident in site_ids or any(c in ident for c in ("/", "\\", "\x00")):
                raise ValueError("Archive site IDs must be unique safe strings")
            site_ids.add(ident)
            for key in ("name", "owner", "notes"):
                if not isinstance(site.get(key, ""), str):
                    raise ValueError("Archive site metadata must be strings")
            if site.get("slug") is not None and not isinstance(site.get("slug"), str):
                raise ValueError("Archive site slug must be a string")
            # Older registry archives serialized this JSON column as text.
            if isinstance(site.get("maintainers"), str):
                site["maintainers"] = json.loads(site["maintainers"])
            if not isinstance(site.get("maintainers", []), list) or any(not isinstance(m, str) for m in site.get("maintainers", [])):
                raise ValueError("Archive maintainers must be a list of strings")
        data_rows, data_defaults = _prepare_data_rows(data_rows)

        # Validate manifest counts
        manifest_counts = manifest.get("counts", {})
        if any(type(value) is not int or value < 0 for value in manifest_counts.values()):
            raise ValueError("Archive counts must be nonnegative integers")
        if len(registry_rows) != manifest_counts.get("sites", 0):
            raise ValueError(
                f"Archive manifest claims {manifest_counts.get('sites')} sites "
                f"but registry.jsonl has {len(registry_rows)} rows. "
                "Archive may be corrupt."
            )
        if len(data_rows) != manifest_counts.get("data_rows", 0):
            raise ValueError(
                f"Archive manifest claims {manifest_counts.get('data_rows')} data rows "
                f"but data.jsonl has {len(data_rows)} rows. "
                "Archive may be corrupt."
            )
        if "html_files" in manifest_counts and len(html_map) != manifest_counts["html_files"]:
            raise ValueError("Archive HTML count differs from manifest")
        return manifest, registry_rows, data_rows, html_map, data_defaults
    except (ValueError, OSError, tarfile.TarError, UnicodeError, TypeError, AttributeError) as error:
        message = ("Archive path traversal is forbidden" if str(error).startswith("Refusing to extract path-traversal member:")
                   else "Archive is invalid or unreadable")
        raise ArchiveValidationError(message) from None


def import_archive(
    archive_path: str,
    *,
    dry_run: bool = False,
    on_conflict: str = "skip",
    yes: bool = False,
    cfg=None,
) -> dict:
    """Import a golive archive.

    Returns a dict with:
        - ``sites_imported``: count of sites written
        - ``sites_skipped``: count of sites skipped (conflict, skip mode)
        - ``sites_overwritten``: count of sites overwritten
        - ``sites_renamed``: count of sites renamed
        - ``data_rows_imported``: count of data rows written
        - ``data_rows_skipped``: count of data rows skipped (conflict)
        - ``html_files_written``: count of HTML files written
        - ``conflicts``: list of {slug, existing_site_id, imported_site_id}
        - ``errors``: list of error messages
    """
    from golive.backends.factory import get_registry, get_storage, get_template_store
    from golive.config import get_config

    if cfg is None:
        cfg = get_config()

    if on_conflict not in ("skip", "overwrite", "rename"):
        raise ValueError("Unknown import conflict policy")
    manifest, registry_rows, data_rows, html_map, data_defaults = _validated_archive(archive_path)

    if dry_run:
        return {"ok": True, "dry_run": True, "sites_imported": 0,
                "sites_skipped": 0, "sites_overwritten": 0, "sites_renamed": 0,
                "data_rows_imported": 0, "data_rows_skipped": 0,
                "html_files_written": 0, "conflicts": [], "errors": [],
                "summary": {"sites_to_import": len(registry_rows),
                            "data_rows_to_import": len(data_rows),
                            "html_files_to_write": len(html_map),
                            "conflicts": [], "conflict_count": None,
                            "target_inspected": False,
                            "data_metadata_defaults": data_defaults}}

    # No target files/tables are opened until archive validation has passed.
    registry = get_registry(cfg)
    storage = get_storage(cfg)
    data_store = get_template_store(cfg)
    if data_rows and (data_store is None or not callable(getattr(data_store, "restore_row", None))):
        raise RuntimeError("Target data backend cannot preserve archived record identity")

    # ── dry run: report what would happen ──────────────────────────────────
    conflicts = []
    for site in registry_rows:
        slug = site.get("slug")
        site_id = site.get("site_id")
        if slug and registry.slug_taken(slug):
            conflicts.append({
                "slug": slug,
                "existing_site_id": registry.get_by_slug(slug).get("site_id", ""),
                "imported_site_id": site_id,
            })

    summary = {
        "sites_to_import": len(registry_rows),
        "data_rows_to_import": len(data_rows),
        "html_files_to_write": len(html_map),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "data_metadata_defaults": data_defaults,
    }

    # ── confirm before writing (unless --yes) ──────────────────────────────
    if not yes:
        print(f"\n  Sites to import:    {len(registry_rows)}")
        print(f"  Data rows to import: {len(data_rows)}")
        print(f"  HTML files:         {len(html_map)}")
        print(f"  Slug conflicts:     {len(conflicts)}")
        print(f"  Conflict strategy:  {on_conflict}")
        try:
            ans = input("\n  Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return {"cancelled": True}
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return {"cancelled": True}

    # ── import registry rows ────────────────────────────────────────────────
    sites_imported = 0
    # Sites this run created (as opposed to ones that already existed). Only
    # these may be rolled back if their HTML turns out to carry a credential:
    # deleting a pre-existing site would destroy data the archive never owned.
    created_site_ids = set()
    sites_skipped = 0
    sites_overwritten = 0
    sites_renamed = 0
    errors = []
    site_writes_uncertain = False

    # Build a mapping from original site_id → actual site_id in the target
    # (they may differ if rename or overwrite changes the ID). A site absent
    # from this map is one whose registry row we did not write, so its HTML
    # must not be written either.
    site_id_map = {}
    # Sites that already existed and were left alone: their live HTML must
    # survive the import untouched.
    sites_skipped_ids = set()
    # For reporting: original site_id → the archived registry row.
    registry_by_id = {row.get("site_id", ""): row for row in registry_rows}

    for i, site in enumerate(registry_rows):
        site_id = site.get("site_id", "")
        slug = site.get("slug", "")
        name = site.get("name", "")
        owner = site.get("owner", "")
        notes = site.get("notes", "")
        editable = site.get("editable", False)
        maintainers = site.get("maintainers", [])

        try:
            # Check if site_id already exists
            existing = registry.get(site_id)

            # Check slug conflict
            slug_conflict = bool(slug) and registry.slug_taken(slug, exclude_site_id=site_id)

            if existing:
                # Site with same site_id exists
                if on_conflict == "skip":
                    site_id_map[site_id] = site_id
                    sites_skipped_ids.add(site_id)
                    sites_skipped += 1
                    continue
                elif on_conflict == "overwrite":
                    # Delete and recreate with the same site_id
                    registry.delete(site_id)
                    _registry_create_with_id(registry, site_id, name, slug,
                                             owner, notes)
                    if editable:
                        registry.set_editable(site_id, True)
                    for m in (maintainers or []):
                        registry.add_maintainer(site_id, m)
                    site_id_map[site_id] = site_id
                    sites_overwritten += 1
                elif on_conflict == "rename":
                    # Create with a new slug and new site_id
                    new_slug = f"{slug}-imported-{site_id[:8]}" if slug else None
                    new_site = registry.create(name=name, slug=new_slug or "",
                                               owner=owner, notes=notes)
                    if editable:
                        registry.set_editable(new_site["site_id"], True)
                    for m in (maintainers or []):
                        registry.add_maintainer(new_site["site_id"], m)
                    site_id_map[site_id] = new_site["site_id"]
                    created_site_ids.add(new_site["site_id"])
                    sites_renamed += 1
            elif slug_conflict:
                # Slug taken by a different site_id
                if on_conflict == "skip":
                    site_id_map[site_id] = site_id
                    sites_skipped_ids.add(site_id)
                    sites_skipped += 1
                    continue
                elif on_conflict == "overwrite":
                    # Delete the existing site that holds this slug
                    existing_by_slug = registry.get_by_slug(slug)
                    if existing_by_slug:
                        registry.delete(existing_by_slug["site_id"])
                    # Create with the original site_id
                    _registry_create_with_id(registry, site_id, name, slug,
                                             owner, notes)
                    if editable:
                        registry.set_editable(site_id, True)
                    for m in (maintainers or []):
                        registry.add_maintainer(site_id, m)
                    site_id_map[site_id] = site_id
                    sites_overwritten += 1
                elif on_conflict == "rename":
                    new_slug = f"{slug}-imported-{site_id[:8]}" if slug else ""
                    new_site = registry.create(name=name, slug=new_slug,
                                               owner=owner, notes=notes)
                    if editable:
                        registry.set_editable(new_site["site_id"], True)
                    for m in (maintainers or []):
                        registry.add_maintainer(new_site["site_id"], m)
                    site_id_map[site_id] = new_site["site_id"]
                    created_site_ids.add(new_site["site_id"])
                    sites_renamed += 1
            else:
                # No conflict — create with original site_id
                _registry_create_with_id(registry, site_id, name, slug,
                                         owner, notes)
                if editable:
                    registry.set_editable(site_id, True)
                for m in (maintainers or []):
                    registry.add_maintainer(site_id, m)
                site_id_map[site_id] = site_id
                created_site_ids.add(site_id)
                sites_imported += 1

        except Exception:
            site_writes_uncertain = True
            errors.append(
                f"Site {site_id}: restore failed; target may be partial; "
                f"[imported {sites_imported + sites_overwritten + sites_renamed} so far]"
            )

    # ── import data rows ───────────────────────────────────────────────────
    data_rows_imported = 0
    data_rows_skipped = 0
    data_id_map = {}
    data_errors = []
    data_exact_restore = not bool(data_defaults)
    data_writes_uncertain = False

    if data_store is not None and data_rows:
        for row in data_rows:
            try:
                from golive.backends.data._restore import same_record
                state, restored = _restore_data_record(data_store, row, on_conflict)
                data_id_map[row["id"]] = restored["id"]
                data_exact_restore = data_exact_restore and same_record(row, restored)
                if state == "skipped":
                    data_rows_skipped += 1
                else:
                    data_rows_imported += 1

            except Exception as error:
                # Driver exceptions can contain passwords, DSNs and row content.
                from golive.backends.data._restore import RestoreConflict, RestoreMismatch
                code = ("identity_conflict" if isinstance(error, RestoreConflict) else
                        "restore_mismatch" if isinstance(error, RestoreMismatch) else "restore_failed")
                data_errors.append({"id": row["id"], "code": code})
                data_writes_uncertain = data_writes_uncertain or code != "identity_conflict"
                errors.append(
                    f"Data record {row['id']}: restore failed (conflict, unavailable backend "
                    f"or readback mismatch); target may be partial; imported {data_rows_imported} so far")
                data_exact_restore = False

    # ── import HTML files ───────────────────────────────────────────────────
    html_files_written = 0

    html_files_skipped = 0
    html_files_blocked = []

    for orig_site_id, html in html_map.items():
        # Only write HTML for sites whose registry entry we actually wrote.
        # Two cases used to slip through because the lookup fell back to the
        # original id:
        #   * the registry row failed  → the HTML landed as an orphan object
        #     with no metadata pointing at it;
        #   * the site was skipped     → an old archive silently overwrote
        #     newer live HTML, which is not what "skip" means to anyone.
        target_site_id = site_id_map.get(orig_site_id)
        if target_site_id is None:
            continue                      # registry row failed — already logged
        if orig_site_id in sites_skipped_ids:
            html_files_skipped += 1
            continue

        # An archive can arrive from another machine, another colleague or a
        # version-control checkout, so its pages are as untrusted as anything
        # passed to `publish`. Scanned per page rather than up front, and a
        # finding blocks only that page: aborting the whole restore would
        # leave the operator unable to recover a backup because of one bad
        # page — and since import is not atomic, mid-way is the worst place
        # to stop. Content warnings are not consulted here; the pages were
        # already published once.
        blocking = _credential_findings(html)
        if blocking:
            slug = (registry_by_id.get(orig_site_id) or {}).get("slug", "")
            # Roll back the registry row we just created for this site.
            # Leaving it behind produced a site that resolves and lists but
            # serves nothing — indistinguishable from a storage failure, and
            # a later republish would treat the slug as taken. Only rows this
            # run created are removed; a site that already existed keeps its
            # metadata and its live HTML untouched.
            rolled_back = False
            if target_site_id in created_site_ids:
                try:
                    registry.delete(target_site_id)
                    rolled_back = True
                    sites_imported = max(0, sites_imported - 1)
                except Exception:
                    site_writes_uncertain = True
                    errors.append(
                        f"Site {slug or target_site_id}: held back for a "
                        f"credential, but its registry entry could not be "
                        "removed; target may be partial")
            html_files_blocked.append({
                "site_id": orig_site_id,
                "slug": slug,
                "findings": blocking,
                "registry_rolled_back": rolled_back,
            })
            continue

        try:
            storage.publish(html, target_site_id, backup_previous=False)
            html_files_written += 1
        except Exception:
            site_writes_uncertain = True
            errors.append(f"HTML for {orig_site_id}: restore failed; target may be partial")

    return {
        "ok": not errors and not html_files_blocked,
        "partial": bool(errors or html_files_blocked) and bool(sites_imported or sites_overwritten or data_rows_imported or html_files_written or data_writes_uncertain or site_writes_uncertain),
        "site_writes_uncertain": site_writes_uncertain,
        "dry_run": False,
        "sites_imported": sites_imported,
        "sites_skipped": sites_skipped,
        "sites_overwritten": sites_overwritten,
        "sites_renamed": sites_renamed,
        "data_rows_imported": data_rows_imported,
        "data_rows_skipped": data_rows_skipped,
        "data_id_map": data_id_map,
        "data_errors": data_errors,
        "data_writes_uncertain": data_writes_uncertain,
        "data_identity_preserved": len(data_id_map) == len(data_rows) and all(k == v for k, v in data_id_map.items()),
        "data_exact_restore": data_exact_restore and len(data_id_map) == len(data_rows),
        "data_metadata_defaults": data_defaults,
        "references_rewritten": False,
        "html_files_skipped": html_files_skipped,
        # Pages held back because they carry a literal credential. Reported
        # separately from `errors`: nothing malfunctioned, and the rest of the
        # restore succeeded.
        "html_files_blocked": html_files_blocked,
        "html_files_written": html_files_written,
        "conflicts": conflicts,
        "errors": errors,
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  MIGRATE
# ═══════════════════════════════════════════════════════════════════════════

def _check_postgres_available(dsn_env: str) -> tuple:
    """Check if postgres backend is usable. Returns (ready, error_msg)."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False, (
            "psycopg is required for the postgres backend.\n"
            "  pip install 'html-golive[postgres]'\n"
            "  # or: pip install 'psycopg[binary]>=3.1'"
        )

    dsn = os.environ.get(dsn_env, "").strip()
    if not dsn:
        return False, (
            f"Environment variable {dsn_env} is not set.\n"
            f"  export {dsn_env}='host=localhost dbname=golive user=postgres'"
        )

    return True, ""


def migrate_backend(
    layer: str,
    target: str,
    *,
    dry_run: bool = False,
    cfg=None,
) -> dict:
    """Migrate data or registry from one backend to another.

    ``layer`` is 'data' or 'registry'.
    ``target`` is the target backend name ('postgres', 'sqlite', etc.).

    Returns a dict with migration status and counts.
    """
    from golive.config import get_config

    if cfg is None:
        cfg = get_config()

    if layer not in ("data", "registry"):
        raise ValueError(f"layer must be 'data' or 'registry', got {layer!r}")

    # ── validate target backend before touching anything ────────────────────
    # For dry-run, we only need the source — skip target validation entirely.
    if not dry_run and target == "postgres":
        dsn_env = cfg.registry.postgres_dsn_env or "GOLIVE_PG_DSN"
        ready, msg = _check_postgres_available(dsn_env)
        if not ready:
            return {
                "ok": False,
                "error": msg,
                "hint": "Fix the above and re-run:\n"
                        f"  golive migrate {layer} --to {target}",
            }
    elif target not in ("sqlite", "supabase", "postgres", "mysql"):
        raise ValueError(f"unknown target backend: {target!r}")

    if not dry_run and target == "mysql":
        import importlib.util
        from golive.backends.factory import sql_dsn_env
        dsn_env = sql_dsn_env(cfg, "mysql")
        if importlib.util.find_spec("pymysql") is None or not os.environ.get(dsn_env, "").strip():
            return {"ok": False, "error": f"MySQL requires {dsn_env} and pip install 'html-golive[mysql]'"}

    # ── get source backend (current) ───────────────────────────────────────
    if layer == "data":
        source_backend = cfg.data.backend or "sqlite"
        from golive.backends.factory import get_template_store
        source_store = get_template_store(cfg)
        if source_store is None:
            return {
                "ok": False,
                "error": "Current data backend is 'none' — nothing to migrate.",
            }
    else:
        source_backend = cfg.registry.backend or "sqlite"
        from golive.backends.factory import get_registry
        source_store = get_registry(cfg)

    # Migrating a backend onto itself is a no-op that only looks like work:
    # every row gets rewritten in place, refreshing timestamps for nothing.
    # Refuse it outright rather than previewing it — the dry run used to
    # report "Target existing: 0" for a table that plainly held rows,
    # because source and target are the same table.
    if target == source_backend:
        return {
            "ok": False,
            "error": (
                f"The {layer} layer already uses {target!r} — nothing to "
                f"migrate. Name a different target backend, or check "
                f"`golive doctor` if you expected another one to be active."
            ),
        }

    # ── read all source data FIRST (before instantiating target) ────────────
    if layer == "data":
        source_rows = _paginated_data_list(source_store)
        source_rows, _ = _prepare_data_rows(source_rows)
        source_count = sum(m.get("count", 0) for m in
                            source_store.list_models(scan_limit=100000))
    else:
        source_rows = _paginated_registry_list(source_store)
        source_count = len(source_rows)

    if dry_run:
        return {"ok": True, "dry_run": True, "source_backend": source_backend,
                "target_backend": target, "source_count": source_count,
                "target_existing": None, "would_migrate": source_count,
                "target_has_data": False, "target_inspected": False,
                "warning": "", "preview_note": "Target not inspected; conflicts and connectivity are unknown. Preview opens no target tables."}

    # A real migration may initialize its explicitly selected target.
    try:
        if layer == "data":
            target_cfg = _clone_config_with(cfg, data_backend=target)
            target_store = get_template_store(target_cfg)
            if target_store is None or not callable(getattr(target_store, "restore_row", None)):
                return {"ok": False, "code": "unsupported_restore",
                        "error": "Target backend cannot preserve record identity."}
            target_count = sum(m.get("count", 0) for m in target_store.list_models(scan_limit=100000))
        else:
            target_cfg = _clone_config_with(cfg, registry_backend=target)
            target_store = get_registry(target_cfg)
            target_count = len(target_store.list_all(limit=100000))
    except Exception:
        return {"ok": False, "code": "target_unavailable",
                "error": "Target backend is unavailable; check configuration and connectivity."}

    # ── migrate ─────────────────────────────────────────────────────────────
    migrated = 0
    skipped = 0
    errors = []

    if layer == "data":
        for row in source_rows:
            try:
                state, _ = _restore_data_record(target_store, row, "migration")
                if state == "skipped":
                    skipped += 1
                else:
                    migrated += 1
            except Exception:
                errors.append(f"Data record {row['id']}: migration failed (target conflict, "
                              "connection failure or readback mismatch); no ID substitution was attempted")
    else:
        for site in source_rows:
            try:
                site_id = site.get("site_id", "")
                # Check if already exists
                existing = target_store.get(site_id)
                if existing:
                    # Skip — don't overwrite in migration
                    skipped += 1
                    continue
                slug = site.get("slug", "")
                name = site.get("name", "")
                owner = site.get("owner", "")
                notes = site.get("notes", "")
                editable = site.get("editable", False)
                maintainers = site.get("maintainers", [])

                # Handle slug conflict
                if slug and target_store.slug_taken(slug, exclude_site_id=site_id):
                    raise ValueError("Target slug belongs to a different site")

                new_site = _registry_create_with_id(target_store, site_id, name, slug, owner, notes)
                if editable:
                    target_store.set_editable(new_site["site_id"], True)
                for m in (maintainers or []):
                    target_store.add_maintainer(new_site["site_id"], m)
                migrated += 1
            except Exception:
                errors.append(f"Site {site.get('site_id', '?')}: migration failed; "
                              f"target may be partial; migrated {migrated} so far")

    # ── verify counts ───────────────────────────────────────────────────────
    if layer == "data":
        target_models_after = target_store.list_models(scan_limit=100000)
        target_count_after = sum(m.get("count", 0) for m in target_models_after)
    else:
        target_sites_after = target_store.list_all(limit=100000)
        target_count_after = len(target_sites_after)

    count_ok = (target_count_after - target_count) == migrated

    result = {
        "ok": not errors and count_ok,
        "code": "ok" if not errors and count_ok else "partial_failure" if migrated else "migration_failed",
        "dry_run": False,
        "source_backend": source_backend,
        "target_backend": target,
        "source_count": source_count,
        "target_existing_before": target_count,
        "migrated": migrated,
        "skipped": skipped,
        "partial": bool(errors) and (migrated > 0 or target_count_after != target_count),
        "target_count_after": target_count_after,
        "count_ok": count_ok,
        "errors": errors,
    }

    if errors:
        result["error"] = "Migration incomplete; inspect per-record errors; target may contain completed records."

    if not count_ok:
        result["ok"] = False
        result["error"] = (
            f"Count mismatch: source had {source_count} rows, "
            f"target had {target_count} before, "
            f"{target_count_after} after "
            f"(migrated {migrated}). "
            f"Expected target_after = target_before + migrated = "
            f"{target_count + migrated}, got {target_count_after}."
        )

    if count_ok and not errors:
        result["next_steps"] = (
            f"Migration complete. Source data is untouched — "
            f"the {source_backend} database is still in place.\n"
            f"Update golive.yaml to use backend: {target} for the {layer} layer, "
            f"then restart golive serve.\n"
            f"Once you've confirmed everything works, you can remove the "
            f"old {source_backend} database."
        )

    return result


def _clone_config_with(cfg, **overrides):
    """Clone a Config with specific backend fields overridden."""
    from dataclasses import replace
    from golive.config import Config, DataConfig, RegistryConfig

    # For data backend override
    if "data_backend" in overrides:
        new_data = replace(cfg.data, backend=overrides["data_backend"])
        return replace(cfg, data=new_data)

    # For registry backend override
    if "registry_backend" in overrides:
        new_reg = replace(cfg.registry, backend=overrides["registry_backend"])
        return replace(cfg, registry=new_reg)

    return cfg
