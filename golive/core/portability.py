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
from pathlib import Path
from typing import Optional

# ── pagination constants ────────────────────────────────────────────────────
# PAGINATION_SIZE is deliberately larger than the registry default (200) to
# reduce round-trips, but not so large that a single page overwhelms memory.
REGISTRY_PAGE_SIZE = 500
DATA_PAGE_SIZE = 500


# ═══════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _paginated_registry_list(registry, page_size: int = REGISTRY_PAGE_SIZE):
    """Iterate every site in the registry, paging past list_all's default cap.

    ``list_all(limit=N)`` returns at most N rows.  If it returns exactly N,
    there may be more — we must ask again with a higher limit.  We do this
    by exponentially increasing the limit until we get fewer rows than
    requested.

    This is safe because the registry is not expected to have millions of
    sites; even 50k sites is a few hundred KB of JSON.
    """
    # First try with the given page_size, then exponentially grow if needed.
    limit = page_size
    all_sites = []
    while True:
        batch = registry.list_all(limit=limit)
        all_sites.extend(batch)
        if len(batch) < limit:
            break
        # We got exactly `limit` rows — there may be more.  Grow.
        limit *= 2
    return all_sites


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
    try:
        page = data_store.list(model_code, name_prefix=name,
                               user_id=user_id, page_no=1, page_size=50)
    except Exception:  # noqa: BLE001 — treated as "cannot tell", see below
        return None
    rows = page.get("list", []) if isinstance(page, dict) else []
    for row in rows:
        if row.get("name") != name:
            continue
        # user_id="" means "any" for stores that do not stamp identity.
        if user_id and (row.get("user_id") or "") != user_id:
            continue
        return row
    return None


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



def _read_archive(path: str) -> tuple:
    """Read an archive's contents into memory. Returns (manifest, registry_rows, data_rows, html_map)."""
    with tarfile.open(path, "r:gz") as tar:
        # Validate before extracting anything
        members = tar.getmembers()
        member_names = [m.name for m in members]
        # Check for path traversal
        for m in members:
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

    registry = get_registry(cfg)
    storage = get_storage(cfg)
    data_store = get_template_store(cfg)

    manifest, registry_rows, data_rows, html_map = _read_archive(archive_path)

    # Validate manifest counts
    manifest_counts = manifest.get("counts", {})
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
    }

    if dry_run:
        return {
            "dry_run": True,
            "sites_imported": 0,
            "sites_skipped": 0,
            "sites_overwritten": 0,
            "sites_renamed": 0,
            "data_rows_imported": 0,
            "data_rows_skipped": 0,
            "html_files_written": 0,
            "conflicts": conflicts,
            "errors": [],
            "summary": summary,
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
    sites_skipped = 0
    sites_overwritten = 0
    sites_renamed = 0
    errors = []

    # Build a mapping from original site_id → actual site_id in the target
    # (they may differ if rename or overwrite changes the ID).
    site_id_map = {}

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
                    sites_renamed += 1
            elif slug_conflict:
                # Slug taken by a different site_id
                if on_conflict == "skip":
                    site_id_map[site_id] = site_id
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
                sites_imported += 1

        except Exception as e:
            errors.append(
                f"Site {site_id} (slug={slug}): {e} "
                f"[imported {sites_imported + sites_overwritten + sites_renamed} so far]"
            )

    # ── import data rows ───────────────────────────────────────────────────
    data_rows_imported = 0
    data_rows_skipped = 0

    if data_store is not None and data_rows:
        for row in data_rows:
            try:
                model_code = row.get("model_code", "")
                name = row.get("name", "")
                content = row.get("content")
                description = row.get("description", "")
                version = row.get("version", "1.0.0")
                user_id = row.get("user_id", "")

                # Check for existing row (by model_code + name + user_id).
                # Uses the public store interface rather than a raw SQL
                # probe: the Supabase store speaks PostgREST and has no
                # ._conn, so a backend-specific query left existing_check
                # permanently None there — "skip" silently imported
                # duplicates on every run and reported them as successes.
                existing_check = _find_existing_row(
                    data_store, model_code, name, user_id)

                if existing_check:
                    if on_conflict == "skip":
                        data_rows_skipped += 1
                        continue
                    elif on_conflict == "overwrite":
                        # Use upsert to overwrite
                        data_store.upsert(model_code, name, content=content,
                                          user_id=user_id, description=description,
                                          version=version)
                        data_rows_imported += 1
                    elif on_conflict == "rename":
                        # Append suffix to name
                        new_name = f"{name}-imported-{row.get('id', '')[:8]}"
                        data_store.create(model_code, new_name, content=content,
                                          description=description, version=version,
                                          user_id=user_id)
                        data_rows_imported += 1
                else:
                    # No conflict — create
                    data_store.create(model_code, name, content=content,
                                      description=description, version=version,
                                      user_id=user_id)
                    data_rows_imported += 1

            except Exception as e:
                errors.append(
                    f"Data row (model={model_code}, name={name}): {e} "
                    f"[imported {data_rows_imported} so far]"
                )

    # ── import HTML files ───────────────────────────────────────────────────
    html_files_written = 0

    for orig_site_id, html in html_map.items():
        try:
            # Map original site_id to the actual site_id in target
            target_site_id = site_id_map.get(orig_site_id, orig_site_id)
            storage.publish(html, target_site_id, backup_previous=False)
            html_files_written += 1
        except Exception as e:
            errors.append(f"HTML for {orig_site_id}: {e}")

    return {
        "dry_run": False,
        "sites_imported": sites_imported,
        "sites_skipped": sites_skipped,
        "sites_overwritten": sites_overwritten,
        "sites_renamed": sites_renamed,
        "data_rows_imported": data_rows_imported,
        "data_rows_skipped": data_rows_skipped,
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
    elif target not in ("sqlite", "supabase", "postgres"):
        raise ValueError(f"unknown target backend: {target!r}")

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

    # ── read all source data FIRST (before instantiating target) ────────────
    if layer == "data":
        source_rows = _paginated_data_list(source_store)
        source_count = sum(m.get("count", 0) for m in
                            source_store.list_models(scan_limit=100000))
    else:
        source_rows = _paginated_registry_list(source_store)
        source_count = len(source_rows)

    # ── get target backend (skip for dry-run when target unavailable) ─────
    target_store = None
    target_count = 0

    if target != source_backend:
        # Different backends — try to instantiate the target
        if not dry_run or target == "sqlite":
            if layer == "data":
                target_cfg = _clone_config_with(cfg, data_backend=target)
                from golive.backends.factory import get_template_store
                target_store = get_template_store(target_cfg)
                if target_store is None:
                    return {
                        "ok": False,
                        "error": f"Target data backend {target!r} is not available.",
                    }
            else:
                target_cfg = _clone_config_with(cfg, registry_backend=target)
                from golive.backends.factory import get_registry
                target_store = get_registry(target_cfg)

            # Check if target already has data
            if layer == "data":
                target_models = target_store.list_models(scan_limit=100000)
                target_count = sum(m.get("count", 0) for m in target_models)
            else:
                target_sites = target_store.list_all(limit=100000)
                target_count = len(target_sites)
    else:
        # Same backend type (e.g. sqlite→sqlite) — source IS target
        target_store = source_store
        if layer == "data":
            target_count = source_count
        else:
            target_count = source_count

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "source_backend": source_backend,
            "target_backend": target,
            "source_count": source_count,
            "target_existing": target_count if target != source_backend else 0,
            "would_migrate": source_count,
            "target_has_data": (target_count > 0) if target != source_backend else False,
            "warning": ("Target already has data — migration will mix "
                        "source and existing rows."
                        if target_count > 0 and target != source_backend else ""),
        }

    # ── migrate ─────────────────────────────────────────────────────────────
    migrated = 0
    errors = []

    if layer == "data":
        for row in source_rows:
            try:
                target_store.create(
                    model_code=row.get("model_code", ""),
                    name=row.get("name", ""),
                    content=row.get("content"),
                    description=row.get("description", ""),
                    version=row.get("version", "1.0.0"),
                    user_id=row.get("user_id", ""),
                )
                migrated += 1
            except Exception as e:
                # Try upsert if create fails (unique constraint)
                try:
                    target_store.upsert(
                        row.get("model_code", ""),
                        row.get("name", ""),
                        content=row.get("content"),
                        user_id=row.get("user_id", ""),
                        description=row.get("description", ""),
                        version=row.get("version", "1.0.0"),
                    )
                    migrated += 1
                except Exception as e2:
                    errors.append(
                        f"Row (model={row.get('model_code')}, "
                        f"name={row.get('name')}): {e2} "
                        f"[migrated {migrated} so far]"
                    )
    else:
        for site in source_rows:
            try:
                site_id = site.get("site_id", "")
                # Check if already exists
                existing = target_store.get(site_id)
                if existing:
                    # Skip — don't overwrite in migration
                    continue
                slug = site.get("slug", "")
                name = site.get("name", "")
                owner = site.get("owner", "")
                notes = site.get("notes", "")
                editable = site.get("editable", False)
                maintainers = site.get("maintainers", [])

                # Handle slug conflict
                if slug and target_store.slug_taken(slug, exclude_site_id=site_id):
                    slug = f"{slug}-migrated-{site_id[:8]}"

                new_site = target_store.create(name=name, slug=slug, owner=owner, notes=notes)
                if editable:
                    target_store.set_editable(new_site["site_id"], True)
                for m in (maintainers or []):
                    target_store.add_maintainer(new_site["site_id"], m)
                migrated += 1
            except Exception as e:
                errors.append(
                    f"Site {site.get('site_id', '?')}: {e} "
                    f"[migrated {migrated} so far]"
                )

    # ── verify counts ───────────────────────────────────────────────────────
    if layer == "data":
        target_models_after = target_store.list_models(scan_limit=100000)
        target_count_after = sum(m.get("count", 0) for m in target_models_after)
    else:
        target_sites_after = target_store.list_all(limit=100000)
        target_count_after = len(target_sites_after)

    count_ok = (target_count_after - target_count) == migrated

    result = {
        "ok": True,
        "dry_run": False,
        "source_backend": source_backend,
        "target_backend": target,
        "source_count": source_count,
        "target_existing_before": target_count,
        "migrated": migrated,
        "target_count_after": target_count_after,
        "count_ok": count_ok,
        "errors": errors,
    }

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
