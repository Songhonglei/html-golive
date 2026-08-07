#!/usr/bin/env python3
"""golive — self-hosted one-command HTML deployment CLI.

Subcommands:
  init      One command: data dir → skill → data layer → demos → serve
  context   Which GOLIVE_HOME / config / registry am I actually using?
  publish   Publish a file / directory / zip archive
  list      List published sites
  demo      Install / remove the two bundled example sites
  rollback  Roll a site back to a previous snapshot
  serve     Start the built-in HTTP server
  clone     Clone a public web page and publish it
  preview   Live-preview a local HTML file (with CSS style panel)
  doctor    Environment health check
  styles    List built-in CSS styles
"""


from __future__ import annotations
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from golive import __version__
from golive.backends.registry.sqlite_store import SqliteRegistry
from golive.backends.storage.local import LocalStorage
from golive.core import publish_utils
from golive.core.paths import (get_data_db, get_home, get_registry_db,
                               get_sites_dir)
from golive.core.slug_checker import validate_slug
from golive.i18n import t
from golive.security.scanner import run_scan

DEFAULT_SERVE_PORT = 8787


def _site_url(site: dict, port: int = DEFAULT_SERVE_PORT) -> str:
    base = f"http://localhost:{port}"
    if site.get("slug"):
        return f"{base}/{site['slug']}"
    return f"{base}/s/{site['site_id']}"


# ═════════════════════════════════ publish ══════════════════════════════════

def _load_source_html(source: str, entry: str = "") -> str:
    """Resolve <file|dir|zip> into a single HTML string."""
    p = Path(source).expanduser().resolve()
    if not p.exists():
        print(t("publish.path_not_found", path=p), file=sys.stderr)
        sys.exit(1)

    if p.is_dir():
        print(t("publish.dir_mode", path=p), file=sys.stderr)
        return publish_utils.bundle_project(p, entry_html=entry or None)

    suffix = p.suffix.lower()
    if suffix in (".zip",) or p.name.lower().endswith(".tar.gz") or suffix == ".tgz":
        print(t("publish.zip_mode", name=p.name), file=sys.stderr)
        tmp_dir = Path(tempfile.mkdtemp(prefix="golive_zip_"))
        try:
            if suffix == ".zip":
                with zipfile.ZipFile(p) as zf:
                    zf.extractall(tmp_dir)
            else:
                import tarfile
                with tarfile.open(p) as tf:
                    try:
                        tf.extractall(tmp_dir, filter="data")  # Py>=3.12 / backports
                    except TypeError:  # older Python: manual traversal guard
                        base = tmp_dir.resolve()
                        for m in tf.getmembers():
                            target = (base / m.name).resolve()
                            if not str(target).startswith(str(base)):
                                print(t("publish.zip_illegal_member", name=m.name),
                                      file=sys.stderr)
                                sys.exit(1)
                        tf.extractall(tmp_dir)
            # single top-level dir? descend
            children = [c for c in tmp_dir.iterdir() if not c.name.startswith("__MACOSX")]
            root = children[0] if len(children) == 1 and children[0].is_dir() else tmp_dir
            return publish_utils.bundle_project(root, entry_html=entry or None)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if suffix in (".html", ".htm"):
        return p.read_text(encoding="utf-8")

    print(t("publish.unsupported_type", suffix=p.suffix),
          file=sys.stderr)
    sys.exit(1)


def cmd_publish(args) -> int:
    from golive.backends.factory import get_registry, get_storage
    registry = get_registry()
    storage = get_storage()

    html = _load_source_html(args.source, args.entry)

    # CSS style
    if args.style:
        from golive.core.css_style_enhancer import STYLE_MAP, inject_css, load_css
        if args.style not in STYLE_MAP:
            print(t("publish.unknown_style", style=args.style, styles=", ".join(STYLE_MAP)),
                  file=sys.stderr)
            return 1
        html = inject_css(html, load_css(args.style), args.style)
        print(t("publish.style_injected", style=args.style, label=STYLE_MAP[args.style]))

    # size gate / compression
    html = publish_utils.check_html_size(html, compress=args.compress)
    publish_utils.check_title_missing(html)

    # security scan
    ok, _scan = run_scan(html, skip_scan=args.skip_scan)
    if not ok:
        return 1

    # data-layer injection (window.TemplateAPI / window.SupabaseAPI)
    html = _apply_data_layers(html, args)

    # watermark (M3) — --watermark flag or yaml watermark.enabled
    html = _apply_watermark(html, args)

    enable_editor = bool(getattr(args, "enable_editor", False))

    # update or create
    if args.update:
        site = registry.resolve(args.update)
        if site is None:
            print(t("publish.site_not_found", ref=args.update), file=sys.stderr)
            return 1
        new_slug = None
        if args.slug and args.slug.lower() != (site.get("slug") or ""):
            okv, msg = validate_slug(args.slug, site["site_id"], registry)
            if not okv:
                print(f"❌ {msg}", file=sys.stderr)
                return 1
            new_slug = args.slug
        if enable_editor or site.get("editable"):
            html = _apply_editor_layer(html, site, registry,
                                       enable_now=enable_editor)
        storage.publish(html, site["site_id"])
        site = registry.update(site["site_id"],
                               name=args.name or None, slug=new_slug)
        print(t("publish.updated", name=site['name'] or site['site_id']))
    else:
        if args.slug:
            okv, msg = validate_slug(args.slug, "", registry)
            if not okv:
                print(f"❌ {msg}", file=sys.stderr)
                return 1
        name = args.name or _title_of(html) or Path(args.source).stem
        site = registry.create(name=name, slug=args.slug, owner=args.owner)
        if enable_editor:
            html = _apply_editor_layer(html, site, registry, enable_now=True)
        storage.publish(html, site["site_id"], backup_previous=False)
        print(t("publish.published", name=site['name']))

    print(f"   site_id: {site['site_id']}")
    if site.get("slug"):
        print(f"   slug:    {site['slug']}")
    print(f"   URL:     {_site_url(site, args.port)}")
    print(t("publish.serve_hint", port=args.port))
    return 0


def _apply_data_layers(html: str, args) -> str:
    """Detect TemplateAPI/SupabaseAPI usage and inject the JS data layer.

    Configured data backend  -> real injection (page runs unchanged).
    ``data.backend: none``   -> stub injection with a clear console error
                                (publish is never blocked) + CLI warning.
    """
    from golive.config import get_config
    from golive.inject import supabase_api, template_api

    cfg = get_config()
    data_model = getattr(args, "data_model", "") or ""

    uses_tpl = template_api.detect_usage(html) or bool(data_model)
    uses_sb = supabase_api.detect_usage(html)
    if not uses_tpl and not uses_sb:
        return html

    if cfg.data.backend == "sqlite":
        backend_ready, backend_label = True, "sqlite"
    elif cfg.data.backend == "supabase":
        backend_ready = cfg.supabase.configured
        backend_label = "supabase"
    else:
        backend_ready, backend_label = False, cfg.data.backend or "none"

    if uses_tpl:
        model_code = data_model \
            or template_api.extract_model_code_from_html(html) or "default"
        html = template_api.inject_into_html(html, model_code, cfg=cfg)
        if backend_ready:
            print(t("publish.tpl_injected", model=model_code, backend=backend_label))
            if backend_label == "sqlite":
                print(t("publish.tpl_sqlite_hint"))
        elif cfg.data.backend == "supabase":
            print(t("publish.tpl_supabase_unconfigured"), file=sys.stderr)
        else:
            print(t("publish.tpl_backend_none"), file=sys.stderr)

    if uses_sb:
        html = supabase_api.inject_into_html(html, cfg=cfg)
        if cfg.supabase.configured:
            print(t("publish.sb_injected"))
            if not cfg.supabase.service_key:
                pass  # anon key in page is expected; RLS warning in docs
        else:
            print(t("publish.sb_unconfigured"), file=sys.stderr)

    return html


def _title_of(html: str) -> str:
    import re
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return m.group(1).strip()[:60] if m else ""


def _apply_watermark(html: str, args) -> str:
    """Inject the watermark layer when requested (M3).

    Trigger: ``--watermark [text]`` CLI flag, or yaml ``watermark.enabled``.
    ``GOLIVE_WATERMARK_OFF=1`` wins over everything (debug kill switch).
    """
    from golive.config import get_config
    from golive.inject import watermark as wm

    cfg = get_config()
    flag = getattr(args, "watermark", None)          # None = flag absent
    wants = (flag is not None) or cfg.watermark.enabled
    if not wants:
        return html
    if wm.is_disabled():
        print(t("publish.wm_disabled"), file=sys.stderr)
        return wm.remove_from_html(html)

    text = (flag if isinstance(flag, str) and flag else "") or cfg.watermark.text
    auth_me = "/auth/me" if cfg.auth.provider == "oidc" else ""
    html = wm.inject_into_html(html, text=text, slug=getattr(args, "slug", ""),
                               auth_me_url=auth_me, cfg=cfg)
    source = (t("publish.wm_source_oidc") if auth_me else
              (t("publish.wm_source_static", text=text) if text else t("publish.wm_source_meta")))
    print(t("publish.wm_injected", source=source))
    return html


def _apply_editor_layer(html: str, site: dict, registry,
                        enable_now: bool = False) -> str:
    """Inject the online editor JS + flip the registry editable flag."""
    from golive.config import get_config
    from golive.inject import editor as editor_inject
    from golive.server.editor_api import resolve_editor_token

    cfg = get_config()
    if enable_now and not site.get("editable"):
        registry.set_editable(site["site_id"], True)
        site = dict(site, editable=True)

    token = resolve_editor_token(cfg)
    if enable_now:
        if not token:
            print(t("publish.editor_no_token"), file=sys.stderr)
        elif not (site.get("owner") or site.get("maintainers")):
            print(t("publish.editor_no_owner"), file=sys.stderr)

    html = editor_inject.inject_into_html(
        html, slug=site.get("slug") or site["site_id"],
        site_name=site.get("name", ""))
    print(t("publish.editor_injected"))
    return html


# ═════════════════════════════════ list ═════════════════════════════════════

def cmd_list(args) -> int:
    from golive.backends.factory import get_registry
    sites = get_registry().list_all()
    if not sites:
        print(t("list.empty"))
        return 0
    print(t("list.count", count=len(sites)))
    for s in sites:
        slug = f"/{s['slug']}" if s.get("slug") else f"/s/{s['site_id']}"
        print(f"  {s['site_id']}  {slug:<20}  {s['name']}")
        print(t("list.updated_at", updated_at=s['updated_at'])
              + (t("list.owner", owner=s['owner']) if s.get("owner") else ""))
    return 0


# ═════════════════════════════════ rollback ═════════════════════════════════

def cmd_rollback(args) -> int:
    from golive.backends.factory import get_registry, get_storage
    registry = get_registry()
    storage = get_storage()
    site = registry.resolve(args.site)
    if site is None:
        print(t("publish.site_not_found", ref=args.site), file=sys.stderr)
        return 1

    snaps = storage.list_snapshots(site["site_id"])
    if not snaps:
        print(t("rollback.no_snapshots", name=site['name']), file=sys.stderr)
        return 1

    print(t("rollback.snapshot_count", name=site['name'], count=len(snaps)))
    for i, s in enumerate(snaps, 1):
        print(f"  [{i}] {s['ts']}  ({s['size'] // 1024} KB)")

    if args.dry_run:
        print(t("rollback.dry_run"))
        return 0

    target = snaps[0]
    if args.snapshot:
        matched = [s for s in snaps if s["ts"] == args.snapshot]
        if not matched:
            print(t("rollback.snapshot_not_found", ts=args.snapshot), file=sys.stderr)
            return 1
        target = matched[0]

    if not args.yes:
        try:
            ans = input(t("rollback.confirm", ts=target['ts'])).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(t("rollback.cancelled"))
            return 130
        if ans not in ("y", "yes"):
            print(t("rollback.cancelled"))
            return 0

    storage.rollback(site["site_id"], target["ts"])
    registry.touch(site["site_id"])
    print(t("rollback.done", ts=target['ts']))
    return 0


# ═════════════════════════════════ maintainer ═══════════════════════════════

def cmd_maintainer(args) -> int:
    """golive maintainer <add|remove|list> <site> [email] — editor ACL."""
    from golive.backends.factory import get_registry
    registry = get_registry()
    site = registry.resolve(args.site)
    if site is None:
        print(t("publish.site_not_found", ref=args.site), file=sys.stderr)
        return 1

    if args.maintainer_action == "list":
        owner = site.get("owner") or t("maintainer.list_owner_unset")
        maintainers = site.get("maintainers") or []
        print(t("maintainer.list_header", name=site['name'] or site['site_id']))
        print(t("maintainer.list_owner", owner=owner))
        print(t("maintainer.list_maintainers", maintainers=", ".join(maintainers) or t("maintainer.list_none")))
        editable = t("maintainer.list_editable_yes") if site.get("editable") else t("maintainer.list_editable_no")
        print(f"  editable:    {editable}")
        return 0

    email = (args.email or "").strip().lower()
    if not email or "@" not in email:
        print(t("maintainer.bad_email", action=args.maintainer_action,
                site=args.site), file=sys.stderr)
        return 1

    if args.maintainer_action == "add":
        maintainers = registry.add_maintainer(site["site_id"], email)
        print(t("maintainer.added", email=email))
    else:
        maintainers = registry.remove_maintainer(site["site_id"], email)
        print(t("maintainer.removed", email=email))
    print(t("maintainer.current_list", maintainers=", ".join(maintainers) or t("maintainer.list_none")))
    return 0


# ═════════════════════════════════ serve ════════════════════════════════════

def cmd_serve(args) -> int:
    """golive serve [start|status|stop|restart|logs] — HTTP server.

    No sub-action = foreground server (unchanged since v0.1). The
    sub-actions added in v0.7.1 manage a detached background process.
    """
    action = (getattr(args, "serve_action", "") or "").strip()
    if action:
        return _serve_manage(action, args)

    from golive.server.app import serve
    host = args.host
    if host is None:  # --host not given: golive.yaml server.host, else loopback
        try:
            from golive.config import get_config
            host = get_config().server.host or "127.0.0.1"
        except Exception:
            host = "127.0.0.1"
    serve(host=host, port=args.port or DEFAULT_SERVE_PORT)
    return 0


def _serve_default_host(args) -> str:
    host = getattr(args, "host", None)
    if host:
        return host
    try:
        from golive.config import get_config
        return get_config().server.host or "127.0.0.1"
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _serve_manage(action: str, args) -> int:
    """Background lifecycle sub-actions for `golive serve`."""
    from golive.core import service

    cfg_path = getattr(args, "config", "") or ""
    port_given = getattr(args, "port", None)
    port = port_given or service.DEFAULT_PORT

    if action == "start":
        res = service.start(host=_serve_default_host(args), port=port,
                            config_path=cfg_path)
        if res["state"] == "started":
            print(t("serve.start.started", pid=res['pid']))
            print(t("serve.start.url", port=res['port']))
            print(t("serve.start.admin", port=res['port']))
            print(t("serve.start.log", log=res['log']))
            print(t("serve.start.stop"))
            return 0
        if res["state"] == "already-running":
            pid_str = f"（pid {res['pid']}）" if res.get("pid") else ""
            print(t("serve.already_running", port=res['port'], pid=pid_str))
            print(t("serve.already_running_hint"))
            return 0
        print(t("serve.start_failed", message=res['message']), file=sys.stderr)
        return 1

    if action == "status":
        st = service.status(port=port_given,
                            host=getattr(args, "host", None))
        if not st["running"]:
            print(t("serve.status.not_running"))
            if st["stale_pidfile"]:
                print(t("serve.status.stale_pidfile", pidfile=st['pidfile']))
            if st["port_owner"] == "other":
                print(t("serve.status.port_taken", port=st['port']))
            print(t("serve.status.start_hint"))
            return 1
        pid = f"pid {st['pid']}" if st["pid"] else t("serve.status.pid_unknown")
        ver = st["version"] or t("serve.status.version_unknown")
        print(t("serve.status.running", version=ver, pid=pid, port=st['port']))
        if not st["managed"]:
            print(t("serve.status.foreign"))
        if st["started_at"]:
            print(t("serve.status.started_at", started_at=st['started_at']))
        if not st["version_match"]:
            print(t("serve.status.version_mismatch", cli_version=st['cli_version'], version=st['version']))
        print(t("serve.status.url", port=st['port']))
        print(t("serve.status.log", log=st['log']))
        return 0

    if action == "stop":
        res = service.stop()
        icon = "✅" if res["ok"] else "⚠️ "
        print(t("serve.stop.ok", icon=icon, message=res['message']))
        return 0 if res["ok"] else 1

    if action == "restart":
        res = service.restart(host=getattr(args, "host", None),
                              port=port_given,
                              config_path=cfg_path)
        if res.get("stop", {}).get("message"):
            print(f"   {res['stop']['message']}")
        if res["state"] in ("started", "already-running"):
            pid_str = f"（pid {res['pid']}）" if res.get("pid") else ""
            print(t("serve.restart.done", port=res['port'], pid=pid_str))
            return 0
        print(t("serve.restart.failed", message=res['message']), file=sys.stderr)
        return 1

    if action == "logs":
        n = getattr(args, "lines", 50)
        if getattr(args, "follow", False):
            return service.follow(n)
        rows = service.tail(n)
        if not rows:
            print(t("serve.logs.empty", log_path=service.log_path()))
            print(t("serve.logs.hint"))
            return 0
        for line in rows:
            print(line)
        return 0

    print(t("serve.unknown_action", action=action), file=sys.stderr)
    return 1


def cmd_admin(args) -> int:
    """golive admin open — print the admin portal URL."""
    from golive.config import get_config
    base = ""
    try:
        base = get_config().server.public_base
    except Exception:
        pass
    url = f"{base}/admin" if base else f"http://localhost:{args.port}/admin"
    print(t("admin.portal", url=url))
    print(t("admin.serve_hint", port=args.port))
    return 0


# ═════════════════════════════════ clone ════════════════════════════════════

def cmd_clone(args) -> int:
    from golive.core.clone_site import run_clone, save_to_local

    result = run_clone(
        args.url,
        use_headless=args.headless,
        analyze_only=args.analyze_only,
        backend_origin=args.backend_origin,
        skip_backend_rewrite=args.skip_backend_rewrite,
    )
    if args.analyze_only:
        print(t("clone.analyze_only"))
        return 0

    if result["source_zip"]:
        print(t("clone.zip_downloaded", source_zip=result['source_zip']))
        print(t("clone.zip_publish_hint", source_zip=result['source_zip'], name=args.name or result['name']))
        return 0

    html = result["html"]
    name = args.name or result["name"]

    if args.save_only or result["sensitive_findings"]:
        out = save_to_local(html, args.url)
        print(t("clone.saved", out=out))
        if result["sensitive_findings"]:
            print(t("clone.placeholders"))
        print(t("clone.publish_hint", out=out, name=name))
        return 0

    # direct publish through the same pipeline
    ns = argparse.Namespace(
        source="", entry="", name=name, slug=args.slug, style="",
        compress=True, skip_scan=False, update="", owner="",
        port=DEFAULT_SERVE_PORT,
    )
    # write html to temp file and reuse cmd_publish
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(html)
        ns.source = tmp.name
    try:
        return cmd_publish(ns)
    finally:
        Path(ns.source).unlink(missing_ok=True)


# ═════════════════════════════════ preview ══════════════════════════════════

def cmd_preview(args) -> int:
    import pathlib

    from golive.core.preview_server import start_preview
    html_path = pathlib.Path(args.file).resolve() if args.file else None
    project_dir = pathlib.Path(args.dir).resolve() if args.dir else None
    if not any([html_path, project_dir, args.site]):
        print(t("preview.no_target"), file=sys.stderr)
        return 1
    start_preview(
        html_path=html_path,
        site_ref=args.site,
        project_dir=project_dir,
        entry_html=args.entry or None,
        initial_style=args.css_style,
        port=args.port,
        host=args.host,
        open_browser=not args.no_open,
    )
    return 0


# ═════════════════════════════════ styles ═══════════════════════════════════

def cmd_styles(args) -> int:
    from golive.core.css_style_enhancer import list_styles
    list_styles()
    return 0


# ═════════════════════════════════ doctor ═══════════════════════════════════

def _fmt_bytes(n: int) -> str:
    """Human-readable size (doctor output only)."""
    step = 1024.0
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < step or unit == "GB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} GB"


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _doctor_home_info() -> dict:
    """GOLIVE_HOME + where it came from + writability."""
    import os as _os
    info = {"path": "", "source": "default (~/.golive)", "writable": False,
            "error": ""}
    if _os.environ.get("GOLIVE_HOME", "").strip():
        info["source"] = "$GOLIVE_HOME"
    try:
        home = get_home()
        info["path"] = str(home)
        probe = home / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
        info["writable"] = True
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
    return info


def _doctor_storage_info(cfg) -> dict:
    """Storage backend type, location and size."""
    backend = (cfg.storage.backend if cfg else "") or "local"
    out = {"backend": backend, "location": "", "sites": None,
           "size_bytes": None, "detail": "", "error": ""}
    try:
        if backend in ("", "local"):
            sites_dir = get_sites_dir()
            out["backend"] = "local"
            out["location"] = str(sites_dir)
            count = sum(1 for p in sites_dir.iterdir() if p.is_dir())
            size = _dir_size(sites_dir)
            out["sites"] = count
            out["size_bytes"] = size
            out["detail"] = t("doctor.storage.site_count_size", count=count, size=_fmt_bytes(size))
        elif backend == "s3":
            out["location"] = (getattr(cfg.storage, "s3_bucket", "")
                               or t("doctor.storage.bucket_unset"))
            out["detail"] = getattr(cfg.storage, "s3_endpoint", "") or ""
        elif backend == "supabase":
            out["location"] = (getattr(cfg.storage, "supabase_bucket", "")
                               or "golive-sites")
            out["detail"] = getattr(cfg.supabase, "url", "") or ""
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _doctor_registry_info(cfg) -> dict:
    """Registry backend type, location, site count and orphan check."""
    backend = (cfg.registry.backend if cfg else "") or "sqlite"
    out = {"backend": backend, "location": "", "sites": None,
           "missing_content": [], "detail": "", "error": ""}
    try:
        if backend in ("", "sqlite"):
            out["backend"] = "sqlite"
            out["location"] = str(get_registry_db())
            reg = SqliteRegistry()
        else:
            from golive.backends.factory import get_registry
            reg = get_registry(cfg)
            out["location"] = (getattr(cfg.registry, "supabase_table", "")
                               or "golive_sites")
        sites = reg.list_all()
        out["sites"] = len(sites)
        out["detail"] = t("doctor.registry.site_count", count=len(sites))
        if (cfg.storage.backend if cfg else "local") in ("", "local"):
            storage = LocalStorage()
            out["missing_content"] = [s["site_id"] for s in sites
                                      if not storage.exists(s["site_id"])]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _doctor_data_info(cfg) -> dict:
    """Data-layer backend type, location, table/row counts."""
    backend = (cfg.data.backend if cfg else "") or "sqlite"
    out = {"backend": backend, "location": "", "tables": None, "rows": None,
           "detail": "", "error": ""}
    try:
        if backend == "none":
            out["detail"] = t("doctor.data.disabled")
            return out
        if backend in ("", "sqlite"):
            import sqlite3
            out["backend"] = "sqlite"
            db = Path(getattr(cfg.data, "sqlite_path", "") or get_data_db())
            out["location"] = str(db)
            if not db.exists():
                out["tables"], out["rows"] = 0, 0
                out["detail"] = t("doctor.data.not_created")
                return out
            with sqlite3.connect(str(db), timeout=5) as conn:
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")]
                rows = 0
                for name in names:
                    try:
                        rows += conn.execute(
                            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    except Exception:  # noqa: BLE001
                        continue
            out["tables"], out["rows"] = len(names), rows
            out["detail"] = t("doctor.data.tables_rows",
                              tables=len(names), rows=rows,
                              size=_fmt_bytes(db.stat().st_size))
        elif backend == "supabase":
            out["location"] = (getattr(cfg.data, "templates_table", "")
                               or "golive_templates")
            configured = bool(getattr(cfg.supabase, "configured", False))
            out["detail"] = ("configured" if configured
                             else t("doctor.data.supabase_unconfigured"))
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _doctor_service_info(port: int) -> dict:
    """Version/pid of the golive server currently answering on ``port``."""
    from golive.core import service
    out = {"running": False, "pid": None, "port": port, "version": "",
           "home": "", "data_backend": "", "version_match": True,
           "port_owner": "free", "stale_pidfile": False, "managed": False,
           "started_at": ""}
    try:
        st = service.status(port=port)
    except Exception:  # noqa: BLE001 — doctor must never crash
        return out
    out.update({
        "running": st["running"], "pid": st["pid"], "port": st["port"],
        "version": st["version"], "version_match": st["version_match"],
        "port_owner": st["port_owner"], "stale_pidfile": st["stale_pidfile"],
        "managed": st["managed"], "started_at": st["started_at"],
    })
    health = st.get("health") or {}
    out["home"] = str(health.get("home") or "")
    out["data_backend"] = str(health.get("data_backend") or "")
    return out


def _doctor_skill_info() -> dict:
    """Installed agent-skill locations and whether they match this golive."""
    out = {"packaged_version": "", "installs": [], "in_sync": None,
           "error": ""}
    try:
        from golive.core import skill_installer as si
        st = si.status()
        out["packaged_version"] = st.get("packaged_skill_version", "") or ""
        out["installs"] = [{"path": i["path"], "version": i["version"]}
                           for i in st.get("installs", [])]
        out["in_sync"] = st.get("in_sync")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def _doctor_deps_info() -> list:
    specs = (("bs4", t("doctor.dep.bs4"), True),
             ("requests", t("doctor.dep.requests"), True),
             ("yaml", t("doctor.dep.yaml"), True),
             ("PIL", t("doctor.dep.pil"), False))
    out = []
    for mod, hint, required in specs:
        try:
            __import__(mod)
            ok = True
        except ImportError:
            ok = False
        out.append({"module": mod, "available": ok, "required": required,
                    "hint": hint})
    return out


def _doctor_collect(port: int) -> dict:
    """Gather the whole report (shared by the text and --json renderers)."""
    import golive

    try:
        from golive.config import get_config
        cfg = get_config()
    except Exception:  # noqa: BLE001
        cfg = None

    admin_url = ""
    try:
        base = cfg.server.public_base if cfg else ""
    except Exception:  # noqa: BLE001
        base = ""
    admin_url = f"{base}/admin" if base else f"http://localhost:{port}/admin"

    return {
        "cli_version": golive.__version__,
        "home": _doctor_home_info(),
        "service": _doctor_service_info(port),
        "storage": _doctor_storage_info(cfg),
        "registry": _doctor_registry_info(cfg),
        "data": _doctor_data_info(cfg),
        "skill": _doctor_skill_info(),
        "deps": _doctor_deps_info(),
        "admin_url": admin_url,
    }


def _doctor_problems(rep: dict) -> list:
    """Blocking issues only — warnings are printed but do not fail doctor."""
    problems = []
    if not rep["home"]["writable"]:
        problems.append(t("doctor.problem_home_not_writable", error=rep['home']['error']))
    if rep["registry"]["error"]:
        problems.append(t("doctor.problem_registry", error=rep['registry']['error']))
    if rep["storage"]["error"]:
        problems.append(t("doctor.problem_storage", error=rep['storage']['error']))
    if rep["data"]["error"]:
        problems.append(t("doctor.problem_data", error=rep['data']['error']))
    for dep in rep["deps"]:
        if dep["required"] and not dep["available"]:
            problems.append(t("doctor.problem_dep", module=dep['module'], hint=dep['hint']))
    return problems


def _disp_width(text: str) -> int:
    """Display width: East-Asian wide glyphs and emoji count as two cells."""
    import unicodedata
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_width(text))


def _doctor_render(rep: dict, port: int) -> None:
    """One screen: version, service, three backends, skill, portal."""
    label_w, value_w = 16, 46

    def row(label: str, value: str, note: str = "") -> None:
        if note:
            print(f"{_pad(label, label_w)} {_pad(value, value_w)}  "
                  f"{note}".rstrip())
        else:
            print(f"{_pad(label, label_w)} {value}".rstrip())

    def paren(detail: str) -> str:
        """Wrap a detail string in brackets without doubling them up."""
        if not detail:
            return ""
        if detail[0] in "（(⚠❌✅":
            return detail
        return f"（{detail}）"

    print(t("doctor.title"))
    row("golive", rep["cli_version"], t("doctor.cli_version"))

    svc = rep["service"]
    if svc["running"]:
        ver = svc["version"] or t("doctor.service_unknown_version")
        pid = f"pid {svc['pid']}" if svc["pid"] else "pid ?"
        if not svc["version"]:
            note = t("doctor.service_no_version_note")
        elif svc["version_match"]:
            note = t("doctor.service_version_ok")
        else:
            note = t("doctor.service_version_mismatch")
        row("running service", f"{ver}  {pid}  port {svc['port']}", note)
        if not svc["version_match"]:
            print(t("doctor.service_version_mismatch_detail",
                    pad=" " * label_w, cli_version=rep['cli_version'], version=svc['version']))
        elif not svc["version"]:
            print(t("doctor.service_no_version_detail", pad=" " * label_w))
    elif svc["port_owner"] == "other":
        row("running service", t("doctor.service_not_running"),
            t("doctor.service_port_taken", port=svc['port']))
    else:
        row("running service", t("doctor.service_not_running"),
            t("doctor.service_start_hint", port=svc['port']))
    if svc["stale_pidfile"]:
        print(t("doctor.service_stale_pidfile", pad=" " * label_w))

    home = rep["home"]
    row("GOLIVE_HOME", home["path"] or t("doctor.home_unavailable"),
        f"(from {home['source']})" if home["writable"]
        else t("doctor.home_not_writable", error=home['error']))

    st = rep["storage"]
    row("storage", f"{st['backend']} → {st['location'] or t('doctor.unknown')}",
        paren(st["detail"]) or (t("doctor.storage_error", error=st['error']) if st["error"] else ""))

    rg = rep["registry"]
    row("registry", f"{rg['backend']} → {rg['location'] or t('doctor.unknown')}",
        paren(rg["detail"]) or (t("doctor.registry_error", error=rg['error']) if rg["error"] else ""))
    if rg["missing_content"]:
        miss = rg["missing_content"]
        print(t("doctor.missing_content",
                pad=" " * label_w, count=len(miss),
                first=", ".join(miss[:3]),
                more=" ..." if len(miss) > 3 else ""))

    dt = rep["data"]
    row("data backend", f"{dt['backend']} → {dt['location'] or t('doctor.no_data_location')}",
        paren(dt["detail"]) or (t("doctor.data_error", error=dt['error']) if dt["error"] else ""))

    sk = rep["skill"]
    if sk["error"]:
        row("skill", t("doctor.skill_check_failed", error=""),
            t("doctor.skill_check_failed", error=sk['error']))
    elif not sk["installs"]:
        row("skill", t("doctor.skill_not_installed"), t("doctor.skill_install_hint"))
    else:
        for item in sk["installs"]:
            ver = item["version"] or t("doctor.skill_no_version")
            mark = t("doctor.skill_mismatch") if item["version"] != sk["packaged_version"] else \
                t("doctor.service_version_ok")
            row("skill", f"{item['path']}  {ver}", mark)

    row("admin portal", rep["admin_url"])

    missing_deps = [d for d in rep["deps"] if not d["available"]]
    if missing_deps:
        print()
        for dep in missing_deps:
            level = "❌" if dep["required"] else "⚠️ "
            print(t("doctor.deps_missing", level=level, module=dep['module'], hint=dep['hint']))


def _doctor_target_port(args) -> int:
    """Which port doctor should look at.

    An explicit ``--port`` always wins. Otherwise prefer the port the
    managed server actually recorded in its pidfile: a user who ran
    ``golive serve start --port 9000`` should not be told "not running"
    just because doctor guessed the default.
    """
    explicit = getattr(args, "port", None)
    if explicit and explicit != DEFAULT_SERVE_PORT:
        return int(explicit)
    try:
        from golive.core import service
        recorded = service.recorded_port()
        if recorded:
            return int(recorded)
    except Exception:       # noqa: BLE001 — doctor must never crash
        pass
    return int(explicit or DEFAULT_SERVE_PORT)


def cmd_doctor(args) -> int:
    port = _doctor_target_port(args)
    rep = _doctor_collect(port)
    problems = _doctor_problems(rep)
    rep["problems"] = problems
    rep["ok"] = not problems

    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 1 if problems else 0

    _doctor_render(rep, port)
    print()
    if problems:
        print(t("doctor.problems_found", count=len(problems)))
        for prob in problems:
            print(f"  ❌ {prob}")
        return 1
    print(t("doctor.healthy"))
    return 0


# ═════════════════════════════════ db / data ════════════════════════════════

def cmd_db(args) -> int:
    """golive db init — create local tables / print remote table schemas."""
    from golive.backends.data.supabase import CREATE_TABLE_SQL as TPL_SQL
    from golive.backends.data.supabase import DEFAULT_TABLE as TPL_TABLE
    from golive.backends.registry.supabase_store import CREATE_TABLE_SQL as REG_SQL
    from golive.backends.registry.supabase_store import DEFAULT_TABLE as REG_TABLE
    from golive.config import get_config

    cfg = get_config()
    reg_table = cfg.registry.supabase_table or REG_TABLE
    tpl_table = cfg.data.templates_table or TPL_TABLE

    # Local backends create their own tables on first use — report and exit
    # unless the user explicitly asked for the remote SQL.
    local_registry = cfg.registry.backend in ("", "sqlite")
    local_data = cfg.data.backend in ("", "sqlite")
    if (local_registry or local_data) and not args.print_sql:
        from golive.core.paths import get_home
        if local_registry:
            from golive.backends.factory import get_registry
            get_registry()
            print(t("db.registry_ready", path=get_home() / 'registry.db'))
        if local_data:
            from golive.backends.data.sqlite_store import TemplateStore
            store = TemplateStore()
            print(t("db.data_ready", path=store.db_path, table=store.table))
        if local_registry and local_data:
            print(t("db.local_auto"))
            return 0

    sql = ("-- golive registry table\n" + REG_SQL.format(table=reg_table)
           + "\n-- golive data-layer (TemplateAPI) table\n"
           + TPL_SQL.format(table=tpl_table))

    if args.print_sql or not cfg.supabase.configured:
        print(sql)
        if not cfg.supabase.configured:
            print(t("db.supabase_unconfigured"), file=sys.stderr)
        return 0

    # supabase configured & no --print-sql: PostgREST cannot run DDL —
    # point the user at the SQL editor rather than pretending we can.
    print(sql)
    print(t("db.postgrest_no_ddl"), file=sys.stderr)
    return 0


def cmd_data(args) -> int:
    """golive data <list|get|create|update|delete|upsert> — template rows."""
    import json as _json

    from golive.backends.factory import get_template_store
    store = get_template_store()
    if store is None:
        print(t("data.disabled"), file=sys.stderr)
        return 1

    def _load_content(raw):
        if not raw:
            return None
        if raw.startswith("@"):
            return _json.loads(Path(raw[1:]).read_text(encoding="utf-8"))
        return _json.loads(raw)

    try:
        if args.action == "list":
            data = store.list(args.model_code, name_prefix=args.name,
                              page_size=args.limit)
            print(_json.dumps(data, ensure_ascii=False, indent=2, default=str))
        elif args.action == "get":
            row = store.get(args.id)
            if row is None:
                print(t("data.template_not_found", id=args.id), file=sys.stderr)
                return 1
            print(_json.dumps(row, ensure_ascii=False, indent=2, default=str))
        elif args.action == "create":
            row = store.create(args.model_code, args.name,
                               content=_load_content(args.content),
                               description=args.desc)
            print(t("data.created", id=row.get('id', '?')))
        elif args.action == "upsert":
            row = store.upsert(args.model_code, args.name,
                               content=_load_content(args.content))
            print(t("data.upserted", id=row.get('id', '?')))
        elif args.action == "update":
            patch = {}
            if args.name:
                patch["name"] = args.name
            if args.content:
                patch["content"] = _load_content(args.content)
            if args.desc:
                patch["desc"] = args.desc
            row = store.update(args.id, patch)
            print(t("data.updated", id=row.get('id', '?')))
        elif args.action == "delete":
            ok = store.delete(args.id)
            print(t("data.deleted") if ok else t("data.not_found"))
        else:
            print(t("data.unknown_action", action=args.action), file=sys.stderr)
            return 1
    except Exception as e:  # noqa: BLE001 — surface backend errors cleanly
        print(t("data.operation_failed", e=e), file=sys.stderr)
        return 1
    return 0


# ═════════════════════════════════ skill ════════════════════════════════════

def cmd_skill(args) -> int:
    """golive skill <install|status|path> — the bundled agent skill."""
    from golive.core import skill_installer as si

    action = args.skill_action
    try:
        if action == "path":
            path = si.packaged_skill_dir()
            print(path)
            if not (path / "SKILL.md").is_file():
                print(t("skill.no_skill_md"), file=sys.stderr)
                return 1
            return 0

        if action == "status":
            return _skill_status(si)

        # install
        if getattr(args, "list_targets", False):
            return _skill_list_targets(si)

        res = si.install(target=args.target or None,
                         from_github=args.from_github,
                         force=args.force)
        ver_str = f" v{res['version']}" if res['version'] else ""
        print(t("skill.installed", name=res['name'], version=ver_str))
        origin = t("skill.source", origin='GitHub' if res['origin'] == 'github' else 'bundled', source=res['source'])
        print(f"   {origin.lstrip()}")
        print(t("skill.installed_to", path=res['installed_to']))
        more = " ..." if len(res['files']) > 4 else ""
        print(t("skill.file_count", count=len(res['files']),
                first=", ".join(res['files'][:4]), more=more))
        if res["backup"]:
            print(t("skill.backup", backup=res['backup']))
        print(t("skill.next_step"))
        return 0
    except si.NoAgentDetected as e:
        # Not an error: the user simply has no AI agent installed. Say so
        # plainly, on stdout, and exit 0 — a red ✗ here reads as breakage.
        print(t("skill.not_applicable", detail=e))
        return 0
    except si.SkillInstallError as e:
        print(t("skill.install_error", error=e), file=sys.stderr)
        return 1


def _skill_list_targets(si) -> int:
    """`golive skill install --list-targets` — look, don't touch."""
    cands = si.detect_targets()
    viable = [c for c in cands if c.exists or c.agent_present]
    print(t("skill.targets_header"))
    if viable:
        for i, c in enumerate(viable, 1):
            print(f"  [{i}] {c.describe()}")
    else:
        print(t("skill.no_agents"))
    others = [c for c in cands if c not in viable]
    if others:
        print(t("skill.other_candidates"))
        for c in others:
            print(f"      {c.path}  [{c.agent}]")
    print(t("skill.install_first"))
    return 0


def _skill_status(si) -> int:
    """Version comparison across *every* detected location."""
    st = si.status()
    print(t("skill.status_golive_version", version=st['golive_version']))
    print(t("skill.status_packaged_version",
            version=st['packaged_skill_version'] or t("skill.status_packaged_unknown")))
    print(t("skill.status_packaged_path", path=st['packaged_skill_path']))
    if not st["installs"]:
        print(t("skill.status_not_found", count=len(st['candidates'])))
        return 0
    print(t("skill.status_found_in", count=st['install_count']))
    for item in st["installs"]:
        mark = t("skill.status_version_ok_mark") if item["version"] == \
            st["packaged_skill_version"] else t("skill.status_version_mismatch_mark")
        ver = item["version"] or t("skill.status_version_unknown")
        agent = item.get("agent", "")
        print(f"  {mark} {ver}  {item['path']}"
              f"{'  [' + agent + ']' if agent else ''}")
        if item["error"]:
            print(t("skill.status_error", error=item['error']))
    if st["install_count"] > 1:
        print(t("skill.status_multi_hint"))
    if st["stale"]:
        print(t("skill.status_stale"))
        return 0
    print(t("skill.status_latest"))
    return 0


# ═════════════════════════════════ context ══════════════════════════════════

def cmd_context(args) -> int:
    """golive context — which GOLIVE_HOME / config / data am I using?"""
    import json as _json

    from golive.core import context as ctx
    info = ctx.collect(port=args.port)
    if args.json:
        print(_json.dumps(info, ensure_ascii=False, indent=2, default=str))
        return 0
    print(ctx.render(info))
    return 0


# ═════════════════════════════════ init ═════════════════════════════════════

def cmd_init(args) -> int:
    """golive init — one command from pip install to three working URLs."""
    from golive.core.init_wizard import InitOptions, run

    code, _steps = run(InitOptions(
        home=args.home,
        port=args.port,
        host=args.host or "127.0.0.1",
        skip_skill=args.skip_skill,
        no_serve=args.no_serve,
        background=getattr(args, "background", False),
        skill_target=args.skill_target,
    ))
    return code


# ═════════════════════════════════ demo ═════════════════════════════════════

def cmd_demo(args) -> int:
    """golive demo <install|remove|status> — the two bundled examples."""
    from golive.core import demo

    try:
        if args.demo_action == "status":
            st = demo.status()
            print(t("demo.status_header", published=st['published'], total=st['total']))
            for d in st["demos"]:
                mark = "✅" if d["published"] else "  "
                print(f"  {mark} /{d['slug']:<12} {d['description']}")
            if st["published"] < st["total"]:
                print(t("demo.publish_hint"))
            return 0

        if args.demo_action == "install":
            res = demo.install()
            for d in res["demos"]:
                verb = t("demo.install_created") if d["action"] == "created" else t("demo.install_updated")
                print(t("demo.install_created" if d["action"] == "created" else "demo.install_updated",
                        slug=d['slug'], description=d['description']))
            u = demo.urls(port=args.port)
            print(t("demo.static_url", url=u['demo-static']))
            print(t("demo.crud_url", url=u['demo-crud']))
            print(t("demo.serve_hint", port=args.port))
            return 0

        # remove
        res = demo.remove(drop_data=not args.keep_data)
        if res["removed"]:
            print(t("demo.removed", sites=", ".join(res['removed'])))
        if res["missing"]:
            print(t("demo.missing", sites=", ".join(res['missing'])))
        if res["rows_deleted"]:
            print(t("demo.rows_deleted", count=res['rows_deleted']))
        return 0
    except demo.DemoError as e:
        print(t("demo.error", error=e), file=sys.stderr)
        return 1


# ═════════════════════════════════ main ═════════════════════════════════════

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="golive",
        description="🚀 golive — self-hosted one-command HTML deployment",
    )
    parser.add_argument("--version", action="version",
                        version=f"golive {__version__}")
    parser.add_argument("--config", default="", metavar="PATH",
                        help=t("arg.config"))
    sub = parser.add_subparsers(dest="command")

    # publish
    p = sub.add_parser("publish", help=t("arg.publish.help"))
    p.add_argument("source", help=t("arg.publish.source"))
    p.add_argument("--name", default="", help=t("arg.publish.name"))
    p.add_argument("--slug", default="", help=t("arg.publish.slug"))
    p.add_argument("--style", default="", help=t("arg.publish.style"))
    p.add_argument("--entry", default="", help=t("arg.publish.entry"))
    p.add_argument("--update", default="", help=t("arg.publish.update"))
    p.add_argument("--owner", default="", help=t("arg.publish.owner"))
    p.add_argument("--compress", action="store_true", help=t("arg.publish.compress"))
    p.add_argument("--skip-scan", action="store_true", help=t("arg.publish.skip_scan"))
    p.add_argument("--data-model", default="",
                   help=t("arg.publish.data_model"))
    p.add_argument("--enable-editor", action="store_true",
                   help=t("arg.publish.enable_editor"))
    p.add_argument("--watermark", nargs="?", const="", default=None,
                   metavar="TEXT",
                   help=t("arg.publish.watermark"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help=t("arg.publish.port"))
    p.set_defaults(func=cmd_publish)

    # list
    p = sub.add_parser("list", help=t("arg.list.help"))
    p.set_defaults(func=cmd_list)

    # rollback
    p = sub.add_parser("rollback", help=t("arg.rollback.help"))
    p.add_argument("site", help=t("arg.rollback.site"))
    p.add_argument("--snapshot", default="", help=t("arg.rollback.snapshot"))
    p.add_argument("--dry-run", action="store_true", help=t("arg.rollback.dry_run"))
    p.add_argument("--yes", action="store_true", help=t("arg.rollback.yes"))
    p.set_defaults(func=cmd_rollback)

    # maintainer
    p = sub.add_parser("maintainer", help=t("arg.maintainer.help"))
    p.add_argument("maintainer_action", choices=["add", "remove", "list"])
    p.add_argument("site", help=t("arg.rollback.site"))
    p.add_argument("email", nargs="?", default="", help=t("arg.maintainer.email"))
    p.set_defaults(func=cmd_maintainer)

    # serve
    p = sub.add_parser("serve", help=t("arg.serve.help"))
    p.add_argument("serve_action", nargs="?", default="",
                   choices=["", "start", "status", "stop", "restart", "logs"],
                   help=t("arg.serve.action"))
    p.add_argument("--port", type=int, default=None,
                   help=t("arg.serve.port", default_port=DEFAULT_SERVE_PORT))
    p.add_argument("--host", default=None,
                   help=t("arg.serve.host"))
    p.add_argument("-n", "--lines", type=int, default=50,
                   help=t("arg.serve.lines"))
    p.add_argument("-f", "--follow", action="store_true",
                   help=t("arg.serve.follow"))
    p.set_defaults(func=cmd_serve)

    # admin
    p = sub.add_parser("admin", help=t("arg.admin.help"))
    p.add_argument("admin_action", choices=["open"], help=t("arg.admin.action"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.set_defaults(func=cmd_admin)

    # clone
    p = sub.add_parser("clone", help=t("arg.clone.help"))
    p.add_argument("url", help=t("arg.clone.url"))
    p.add_argument("--name", default="", help=t("arg.clone.name"))
    p.add_argument("--slug", default="", help=t("arg.clone.slug"))
    p.add_argument("--headless", action="store_true", help=t("arg.clone.headless"))
    p.add_argument("--analyze-only", action="store_true", help=t("arg.clone.analyze_only"))
    p.add_argument("--save-only", action="store_true", help=t("arg.clone.save_only"))
    p.add_argument("--backend-origin", default="", help=t("arg.clone.backend_origin"))
    p.add_argument("--skip-backend-rewrite", action="store_true")
    p.set_defaults(func=cmd_clone)

    # preview
    p = sub.add_parser("preview", help=t("arg.preview.help"))
    p.add_argument("file", nargs="?", default="", help=t("arg.preview.file"))
    p.add_argument("--dir", default="", help=t("arg.preview.dir"))
    p.add_argument("--entry", default="", help=t("arg.preview.entry"))
    p.add_argument("--site", default="", help=t("arg.preview.site"))
    p.add_argument("--css-style", default=None, help=t("arg.preview.css_style"))
    p.add_argument("--port", type=int, default=18765)
    p.add_argument("--host", default="127.0.0.1",
                   help=t("arg.preview.host"))
    p.add_argument("--no-open", action="store_true", help=t("arg.preview.no_open"))
    p.set_defaults(func=cmd_preview)

    # styles
    p = sub.add_parser("styles", help=t("arg.styles.help"))
    p.set_defaults(func=cmd_styles)

    # migrate-check
    p = sub.add_parser("migrate-check",
                       help=t("arg.migrate_check.help"))
    p.add_argument("file", help=t("arg.migrate_check.file"))
    p.set_defaults(func=lambda a: __import__(
        "golive.core.migrate_check", fromlist=["run"]).run(a.file))

    # db
    p = sub.add_parser("db", help=t("arg.db.help"))
    p.add_argument("db_action", choices=["init"], help=t("arg.db.action"))
    p.add_argument("--print-sql", action="store_true",
                   help=t("arg.db.print_sql"))
    p.set_defaults(func=cmd_db)

    # data
    p = sub.add_parser("data", help=t("arg.data.help"))
    p.add_argument("action",
                   choices=["list", "get", "create", "update", "delete",
                            "upsert"])
    p.add_argument("--model-code", default="default",
                   help=t("arg.data.model_code"))
    p.add_argument("--id", default="", help=t("arg.data.id"))
    p.add_argument("--name", default="", help=t("arg.data.name"))
    p.add_argument("--content", default="",
                   help=t("arg.data.content"))
    p.add_argument("--desc", default="", help=t("arg.data.desc"))
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_data)

    # doctor
    p = sub.add_parser("doctor", help=t("arg.doctor.help"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.add_argument("--json", action="store_true",
                   help=t("arg.doctor.json"))
    p.set_defaults(func=cmd_doctor)

    # skill
    p = sub.add_parser("skill", help=t("arg.skill.help"))
    p.add_argument("skill_action", choices=["install", "status", "path"],
                   help=t("arg.skill.action"))
    p.add_argument("--target", default="",
                   help=t("arg.skill.target"))
    p.add_argument("--list-targets", action="store_true",
                   help=t("arg.skill.list_targets"))
    p.add_argument("--from-github", action="store_true",
                   help=t("arg.skill.from_github"))
    p.add_argument("--force", action="store_true",
                   help=t("arg.skill.force"))
    p.set_defaults(func=cmd_skill)

    # init
    p = sub.add_parser("init",
                       help=t("arg.init.help"))
    p.add_argument("--home", default="", metavar="DIR",
                   help=t("arg.init.home"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.add_argument("--host", default="127.0.0.1",
                   help=t("arg.init.host"))
    p.add_argument("--skip-skill", action="store_true",
                   help=t("arg.init.skip_skill"))
    p.add_argument("--skill-target", default="", metavar="DIR",
                   help=t("arg.init.skill_target"))
    p.add_argument("--no-serve", action="store_true",
                   help=t("arg.init.no_serve"))
    p.add_argument("--background", action="store_true",
                   help=t("arg.init.background"))
    p.set_defaults(func=cmd_init)

    # context
    p = sub.add_parser("context",
                       help=t("arg.context.help"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help=t("arg.context.port"))
    p.add_argument("--json", action="store_true", help=t("arg.context.json"))
    p.set_defaults(func=cmd_context)

    # demo
    p = sub.add_parser("demo", help=t("arg.demo.help"))
    p.add_argument("demo_action", choices=["install", "remove", "status"],
                   help=t("arg.demo.action"))
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help=t("arg.demo.port"))
    p.add_argument("--keep-data", action="store_true",
                   help=t("arg.demo.keep_data"))
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)

    # Make `golive init --home <DIR>` stick: export the recorded home into
    # the environment *before* the config loader looks for golive.yaml, so
    # the CLI and the server can never end up on different data dirs.
    from golive.core.paths import bootstrap_home_env
    bootstrap_home_env()

    from golive.config import ConfigError, load_config, set_config
    try:
        set_config(load_config(cli_path=args.config or None))
    except ConfigError as e:
        print(t("arg.config.error", msg=e), file=sys.stderr)
        return 1

    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
