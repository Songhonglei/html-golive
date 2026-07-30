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
        print(f"❌ 路径不存在：{p}", file=sys.stderr)
        sys.exit(1)

    if p.is_dir():
        print(f"📁 目录模式：打包 {p} ...", file=sys.stderr)
        return publish_utils.bundle_project(p, entry_html=entry or None)

    suffix = p.suffix.lower()
    if suffix in (".zip",) or p.name.lower().endswith(".tar.gz") or suffix == ".tgz":
        print(f"📦 压缩包模式：解压 {p.name} ...", file=sys.stderr)
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
                                print(f"❌ 压缩包含非法路径成员：{m.name}",
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

    print(f"❌ 不支持的文件类型：{p.suffix}（支持 .html / 目录 / .zip / .tar.gz）",
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
            print(f"❌ 未知风格 `{args.style}`，可用：{', '.join(STYLE_MAP)}",
                  file=sys.stderr)
            return 1
        html = inject_css(html, load_css(args.style), args.style)
        print(f"🎨 已注入 CSS 风格：{args.style}（{STYLE_MAP[args.style]}）")

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
            print(f"❌ 未找到站点：{args.update}", file=sys.stderr)
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
        print(f"\n✅ 已更新站点「{site['name'] or site['site_id']}」")
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
        print(f"\n✅ 发布成功「{site['name']}」")

    print(f"   site_id: {site['site_id']}")
    if site.get("slug"):
        print(f"   slug:    {site['slug']}")
    print(f"   URL:     {_site_url(site, args.port)}")
    print(f"   （若 serve 未启动，运行：golive serve --port {args.port}）")
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
            print(f"🧩 已注入 TemplateAPI 数据层"
                  f"（modelCode: {model_code}，backend: {backend_label}）")
            if backend_label == "sqlite":
                print("   数据存放在 $GOLIVE_HOME/data.db，页面通过 "
                      "golive serve 的 /api/data 读写。")
        elif cfg.data.backend == "supabase":
            print("⚠️  页面使用了 TemplateAPI，但 Supabase 未配置 —— "
                  "已注入 stub（调用会报错并提示配置方法）。\n"
                  "   配置：golive.yaml 里 supabase.url，env 里 "
                  "GOLIVE_SUPABASE_ANON_KEY；\n"
                  "   或改回默认的 data.backend: sqlite（零配置）。",
                  file=sys.stderr)
        else:
            print("⚠️  页面使用了 TemplateAPI，但 data.backend 为 none —— "
                  "已注入 stub（调用会报错并提示配置方法）。\n"
                  "   配置：golive.yaml 里 data.backend: sqlite（零配置，"
                  "默认值）或 supabase。",
                  file=sys.stderr)

    if uses_sb:
        html = supabase_api.inject_into_html(html, cfg=cfg)
        if cfg.supabase.configured:
            print("🧩 已注入 SupabaseAPI 数据层")
            if not cfg.supabase.service_key:
                pass  # anon key in page is expected; RLS warning in docs
        else:
            print("⚠️  页面使用了 SupabaseAPI，但 Supabase 未配置 —— "
                  "已注入 stub（调用会报错并提示配置方法）。\n"
                  "   配置：golive.yaml 里 supabase.url + env "
                  "GOLIVE_SUPABASE_ANON_KEY（注意为表配置 RLS）。",
                  file=sys.stderr)

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
        print("⏭️  GOLIVE_WATERMARK_OFF=1 — 水印已禁用", file=sys.stderr)
        return wm.remove_from_html(html)

    text = (flag if isinstance(flag, str) and flag else "") or cfg.watermark.text
    auth_me = "/auth/me" if cfg.auth.provider == "oidc" else ""
    html = wm.inject_into_html(html, text=text, slug=getattr(args, "slug", ""),
                               auth_me_url=auth_me, cfg=cfg)
    source = ("OIDC 用户身份" if auth_me else
              (f"静态文本「{text}」" if text else "页面 meta 标签"))
    print(f"💧 已注入水印层（身份来源：{source}）")
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
            print("⚠️  编辑模式已开启，但未配置编辑令牌 —— 保存请求将全部被拒。\n"
                  "   设置 GOLIVE_EDITOR_TOKEN（或 golive.yaml editor.token）后，"
                  "用 ?editor_token=<token>&editor_user=<email> 打开页面。",
                  file=sys.stderr)
        elif not (site.get("owner") or site.get("maintainers")):
            print("⚠️  该站点未设置 owner/maintainer —— 持有编辑令牌的任何人都可保存"
                  "（共享令牌模式）。\n"
                  "   建议：golive publish --owner you@example.com，"
                  "或 golive maintainer add <slug> <email> 收紧权限。",
                  file=sys.stderr)

    html = editor_inject.inject_into_html(
        html, slug=site.get("slug") or site["site_id"],
        site_name=site.get("name", ""))
    print(f"✏️  已注入在线编辑器（打开页面点右下角 ✏️，或加 ?edit=1）")
    return html


# ═════════════════════════════════ list ═════════════════════════════════════

def cmd_list(args) -> int:
    from golive.backends.factory import get_registry
    sites = get_registry().list_all()
    if not sites:
        print("暂无站点。试试：golive publish <file.html> --name Demo --slug demo")
        return 0
    print(f"共 {len(sites)} 个站点：\n")
    for s in sites:
        slug = f"/{s['slug']}" if s.get("slug") else f"/s/{s['site_id']}"
        print(f"  {s['site_id']}  {slug:<20}  {s['name']}")
        print(f"    更新于 {s['updated_at']}"
              + (f" · owner: {s['owner']}" if s.get("owner") else ""))
    return 0


# ═════════════════════════════════ rollback ═════════════════════════════════

def cmd_rollback(args) -> int:
    from golive.backends.factory import get_registry, get_storage
    registry = get_registry()
    storage = get_storage()
    site = registry.resolve(args.site)
    if site is None:
        print(f"❌ 未找到站点：{args.site}", file=sys.stderr)
        return 1

    snaps = storage.list_snapshots(site["site_id"])
    if not snaps:
        print(f"❌ 站点「{site['name']}」没有可回滚的快照。", file=sys.stderr)
        return 1

    print(f"站点「{site['name']}」共有 {len(snaps)} 份快照（新→旧）：\n")
    for i, s in enumerate(snaps, 1):
        print(f"  [{i}] {s['ts']}  ({s['size'] // 1024} KB)")

    if args.dry_run:
        print("\n（dry-run 模式，未执行回滚。加 --yes 执行，"
              "--snapshot <ts> 指定快照，默认最新一份。）")
        return 0

    target = snaps[0]
    if args.snapshot:
        matched = [s for s in snaps if s["ts"] == args.snapshot]
        if not matched:
            print(f"❌ 未找到快照 {args.snapshot}", file=sys.stderr)
            return 1
        target = matched[0]

    if not args.yes:
        try:
            ans = input(f"\n回滚到快照 {target['ts']}？(y/N)：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️  已取消")
            return 130
        if ans not in ("y", "yes"):
            print("⚠️  已取消")
            return 0

    storage.rollback(site["site_id"], target["ts"])
    registry.touch(site["site_id"])
    print(f"✅ 已回滚到 {target['ts']}（当前版本已自动存为新快照）")
    return 0


# ═════════════════════════════════ maintainer ═══════════════════════════════

def cmd_maintainer(args) -> int:
    """golive maintainer <add|remove|list> <site> [email] — editor ACL."""
    from golive.backends.factory import get_registry
    registry = get_registry()
    site = registry.resolve(args.site)
    if site is None:
        print(f"❌ 未找到站点：{args.site}", file=sys.stderr)
        return 1

    if args.maintainer_action == "list":
        owner = site.get("owner") or "(未设置)"
        maintainers = site.get("maintainers") or []
        print(f"站点「{site['name'] or site['site_id']}」编辑权限：")
        print(f"  owner:       {owner}")
        print(f"  maintainers: {', '.join(maintainers) or '(无)'}")
        print(f"  editable:    {'是' if site.get('editable') else '否'}")
        return 0

    email = (args.email or "").strip().lower()
    if not email or "@" not in email:
        print("❌ 请提供合法邮箱：golive maintainer "
              f"{args.maintainer_action} {args.site} you@example.com",
              file=sys.stderr)
        return 1

    if args.maintainer_action == "add":
        maintainers = registry.add_maintainer(site["site_id"], email)
        print(f"✅ 已添加 maintainer：{email}")
    else:
        maintainers = registry.remove_maintainer(site["site_id"], email)
        print(f"✅ 已移除 maintainer：{email}")
    print(f"   当前列表：{', '.join(maintainers) or '(无)'}")
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
            print(f"🚀 golive serve 已在后台启动（pid {res['pid']}）")
            print(f"   地址:   http://localhost:{res['port']}/")
            print(f"   管理台: http://localhost:{res['port']}/admin")
            print(f"   日志:   {res['log']}")
            print(f"   停止:   golive serve stop")
            return 0
        if res["state"] == "already-running":
            print(f"ℹ️  golive 已在端口 {res['port']} 上运行"
                  + (f"（pid {res['pid']}）" if res.get("pid") else ""))
            print("   要应用新代码请运行：golive serve restart")
            return 0
        print(f"❌ 启动失败：{res['message']}", file=sys.stderr)
        return 1

    if action == "status":
        st = service.status(port=port_given,
                            host=getattr(args, "host", None))
        if not st["running"]:
            print("⏹  未运行")
            if st["stale_pidfile"]:
                print(f"   （pidfile 记录的进程已退出，"
                      f"下次 start 会自动清理：{st['pidfile']}）")
            if st["port_owner"] == "other":
                print(f"   ⚠️  端口 {st['port']} 被其他程序占用。")
            print(f"   启动：golive serve start")
            return 1
        pid = f"pid {st['pid']}" if st["pid"] else "pid 未知"
        ver = st["version"] or "未知版本"
        print(f"✅ 运行中  {ver}  {pid}  端口 {st['port']}")
        if not st["managed"]:
            print("   （不是由 golive serve start 启动的——可能是前台进程）")
        if st["started_at"]:
            print(f"   启动于: {st['started_at']}")
        if not st["version_match"]:
            print(f"   ⚠️  CLI 是 {st['cli_version']}，服务是 {st['version']}"
                  f" —— 代码已更新但服务是旧的，运行：golive serve restart")
        print(f"   地址:   http://localhost:{st['port']}/")
        print(f"   日志:   {st['log']}")
        return 0

    if action == "stop":
        res = service.stop()
        icon = "✅" if res["ok"] else "⚠️ "
        print(f"{icon} {res['message']}")
        return 0 if res["ok"] else 1

    if action == "restart":
        res = service.restart(host=getattr(args, "host", None),
                              port=port_given,
                              config_path=cfg_path)
        if res.get("stop", {}).get("message"):
            print(f"   {res['stop']['message']}")
        if res["state"] in ("started", "already-running"):
            print(f"🔁 已重启：http://localhost:{res['port']}/"
                  + (f"（pid {res['pid']}）" if res.get("pid") else ""))
            return 0
        print(f"❌ 重启失败：{res['message']}", file=sys.stderr)
        return 1

    if action == "logs":
        n = getattr(args, "lines", 50)
        if getattr(args, "follow", False):
            return service.follow(n)
        rows = service.tail(n)
        if not rows:
            print(f"（暂无日志：{service.log_path()}）")
            print("   后台服务的日志在这里；前台 golive serve 直接打在终端上。")
            return 0
        for line in rows:
            print(line)
        return 0

    print(f"❌ 未知 serve 子命令：{action}", file=sys.stderr)
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
    print(f"🛠  管理门户: {url}")
    print(f"   （若 serve 未启动，运行：golive serve --port {args.port}）")
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
        print("ℹ️  --analyze-only 模式，不执行发布操作。")
        return 0

    if result["source_zip"]:
        print(f"📦 已下载压缩包：{result['source_zip']}")
        print(f"   发布：golive publish {result['source_zip']}"
              f" --name \"{args.name or result['name']}\"")
        return 0

    html = result["html"]
    name = args.name or result["name"]

    if args.save_only or result["sensitive_findings"]:
        out = save_to_local(html, args.url)
        print(f"\n✅ HTML 已保存到: {out}")
        if result["sensitive_findings"]:
            print("   ⚠️  页面含数据模块占位符（__PLACEHOLDER_），请填写后再发布。")
        print(f"   发布：golive publish {out} --name \"{name}\"")
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
        print("❌ 请指定 <file>、--dir 或 --site", file=sys.stderr)
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
            out["detail"] = f"{count} 个站点, {_fmt_bytes(size)}"
        elif backend == "s3":
            out["location"] = (getattr(cfg.storage, "s3_bucket", "")
                               or "(bucket 未配置)")
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
        out["detail"] = f"{len(sites)} 个站点"
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
            out["detail"] = "已禁用，data.backend: none"
            return out
        if backend in ("", "sqlite"):
            import sqlite3
            out["backend"] = "sqlite"
            db = Path(getattr(cfg.data, "sqlite_path", "") or get_data_db())
            out["location"] = str(db)
            if not db.exists():
                out["tables"], out["rows"] = 0, 0
                out["detail"] = "尚未创建，首次使用时自动建表"
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
            out["detail"] = (f"{len(names)} 张表, {rows} 行, "
                             f"{_fmt_bytes(db.stat().st_size)}")
        elif backend == "supabase":
            out["location"] = (getattr(cfg.data, "templates_table", "")
                               or "golive_templates")
            configured = bool(getattr(cfg.supabase, "configured", False))
            out["detail"] = ("configured" if configured
                             else "⚠️ supabase 未配置（url / anon key 缺失）")
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
    specs = (("bs4", "目录打包/克隆需要 beautifulsoup4", True),
             ("requests", "克隆/资源内联需要 requests", True),
             ("yaml", "安全扫描需要 pyyaml", True),
             ("PIL", "图片压缩需要 Pillow（可选，pip install "
                     "'html-golive[image]'）", False))
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
        problems.append(f"GOLIVE_HOME 不可写：{rep['home']['error']}")
    if rep["registry"]["error"]:
        problems.append(f"注册表异常：{rep['registry']['error']}")
    if rep["storage"]["error"]:
        problems.append(f"存储异常：{rep['storage']['error']}")
    if rep["data"]["error"]:
        problems.append(f"数据层异常：{rep['data']['error']}")
    for dep in rep["deps"]:
        if dep["required"] and not dep["available"]:
            problems.append(f"依赖 {dep['module']} 缺失 — {dep['hint']}")
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

    print("🩺 golive doctor\n")
    row("golive", rep["cli_version"], "(CLI)")

    svc = rep["service"]
    if svc["running"]:
        ver = svc["version"] or "版本未知"
        pid = f"pid {svc['pid']}" if svc["pid"] else "pid ?"
        if not svc["version"]:
            note = "ℹ️  该服务不报版本"
        elif svc["version_match"]:
            note = "✅"
        else:
            note = "⚠️  版本不一致，建议重启"
        row("running service", f"{ver}  {pid}  port {svc['port']}", note)
        if not svc["version_match"]:
            print(f"{' ' * label_w} 代码已更新（CLI {rep['cli_version']}）但服务"
                  f"还是旧的（{svc['version']}）—— 运行：golive serve restart")
        elif not svc["version"]:
            print(f"{' ' * label_w} 该服务的 /health 没有返回版本号"
                  f"（0.7.x 及更早版本）—— 很可能是旧代码，"
                  f"建议 golive serve restart")
    elif svc["port_owner"] == "other":
        row("running service", "not running",
            f"⚠️  端口 {svc['port']} 被其他程序占用")
    else:
        row("running service", "not running",
            f"（启动：golive serve start --port {svc['port']}）")
    if svc["stale_pidfile"]:
        print(f"{' ' * label_w} ℹ️  pidfile 里的进程已退出，"
              f"下次 golive serve start 会自动清理")

    home = rep["home"]
    row("GOLIVE_HOME", home["path"] or "(不可用)",
        f"(from {home['source']})" if home["writable"]
        else f"❌ 不可写：{home['error']}")

    st = rep["storage"]
    row("storage", f"{st['backend']} → {st['location'] or '(未知)'}",
        paren(st["detail"]) or (f"❌ {st['error']}" if st["error"] else ""))

    rg = rep["registry"]
    row("registry", f"{rg['backend']} → {rg['location'] or '(未知)'}",
        paren(rg["detail"]) or (f"❌ {rg['error']}" if rg["error"] else ""))
    if rg["missing_content"]:
        miss = rg["missing_content"]
        print(f"{' ' * label_w} ⚠️  {len(miss)} 个站点缺少内容文件："
              f"{', '.join(miss[:3])}{' ...' if len(miss) > 3 else ''}")

    dt = rep["data"]
    row("data backend", f"{dt['backend']} → {dt['location'] or '(无)'}",
        paren(dt["detail"]) or (f"❌ {dt['error']}" if dt["error"] else ""))

    sk = rep["skill"]
    if sk["error"]:
        row("skill", "检查失败", f"⚠️  {sk['error']}")
    elif not sk["installs"]:
        row("skill", "未安装", "（安装：golive skill install）")
    else:
        for item in sk["installs"]:
            ver = item["version"] or "(无版本号)"
            mark = "✅" if item["version"] == sk["packaged_version"] else \
                "⚠️  与 CLI 不一致，golive skill install --force"
            row("skill", f"{item['path']}  {ver}", mark)

    row("admin portal", rep["admin_url"])

    missing_deps = [d for d in rep["deps"] if not d["available"]]
    if missing_deps:
        print()
        for dep in missing_deps:
            level = "❌" if dep["required"] else "⚠️ "
            print(f"  {level} 依赖 {dep['module']} 缺失 — {dep['hint']}")


def cmd_doctor(args) -> int:
    port = args.port
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
        print(f"发现 {len(problems)} 个问题：")
        for prob in problems:
            print(f"  ❌ {prob}")
        return 1
    print("✅ 环境健康。")
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
            print(f"✅ registry (sqlite)：{get_home() / 'registry.db'} 已就绪")
        if local_data:
            from golive.backends.data.sqlite_store import TemplateStore
            store = TemplateStore()
            print(f"✅ data (sqlite)：{store.db_path} 已就绪"
                  f"（表 {store.table}）")
        if local_registry and local_data:
            print("ℹ️  本地后端会在首次使用时自动建表，无需手动 init。"
                  "需要 Supabase 建表 SQL 请加 --print-sql。")
            return 0

    sql = ("-- golive registry table\n" + REG_SQL.format(table=reg_table)
           + "\n-- golive data-layer (TemplateAPI) table\n"
           + TPL_SQL.format(table=tpl_table))

    if args.print_sql or not cfg.supabase.configured:
        print(sql)
        if not cfg.supabase.configured:
            print("\n-- ℹ️  Supabase 未配置：请把上面的 SQL 粘到 Supabase "
                  "SQL Editor 里执行。", file=sys.stderr)
        return 0

    # supabase configured & no --print-sql: PostgREST cannot run DDL —
    # point the user at the SQL editor rather than pretending we can.
    print(sql)
    print("\nℹ️  PostgREST 不支持执行 DDL。请把上面的 SQL 粘到 Supabase "
          "Dashboard → SQL Editor 执行一次即可。", file=sys.stderr)
    return 0


def cmd_data(args) -> int:
    """golive data <list|get|create|update|delete|upsert> — template rows."""
    import json as _json

    from golive.backends.factory import get_template_store
    store = get_template_store()
    if store is None:
        print("❌ data backend 已禁用（data.backend: none）。改为 "
              "data.backend: sqlite（零配置，默认值）或 supabase 后重试。",
              file=sys.stderr)
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
                print(f"❌ 未找到模板：{args.id}", file=sys.stderr)
                return 1
            print(_json.dumps(row, ensure_ascii=False, indent=2, default=str))
        elif args.action == "create":
            row = store.create(args.model_code, args.name,
                               content=_load_content(args.content),
                               description=args.desc)
            print(f"✅ 已创建：{row.get('id', '?')}")
        elif args.action == "upsert":
            row = store.upsert(args.model_code, args.name,
                               content=_load_content(args.content))
            print(f"✅ 已写入：{row.get('id', '?')}")
        elif args.action == "update":
            patch = {}
            if args.name:
                patch["name"] = args.name
            if args.content:
                patch["content"] = _load_content(args.content)
            if args.desc:
                patch["desc"] = args.desc
            row = store.update(args.id, patch)
            print(f"✅ 已更新：{row.get('id', '?')}")
        elif args.action == "delete":
            ok = store.delete(args.id)
            print("✅ 已删除" if ok else "⚠️  记录不存在")
        else:
            print(f"❌ 未知操作：{args.action}", file=sys.stderr)
            return 1
    except Exception as e:  # noqa: BLE001 — surface backend errors cleanly
        print(f"❌ 操作失败：{e}", file=sys.stderr)
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
                print("⚠️  该目录下没有 SKILL.md —— 包安装可能不完整。",
                      file=sys.stderr)
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
        print(f"✅ 已安装 skill「{res['name']}」"
              f"{' v' + res['version'] if res['version'] else ''}")
        print(f"   来源：   {'GitHub' if res['origin'] == 'github' else '包内'}"
              f"（{res['source']}）")
        print(f"   安装到： {res['installed_to']}")
        print(f"   文件：   {len(res['files'])} 个"
              f"（{', '.join(res['files'][:4])}"
              f"{' ...' if len(res['files']) > 4 else ''}）")
        if res["backup"]:
            print(f"   旧版本已备份： {res['backup']}")
        print("\n下一步：重启你的 AI agent 使其重新扫描 skills 目录，"
              "然后让它执行 `golive doctor` 验证。")
        return 0
    except si.SkillInstallError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


def _skill_list_targets(si) -> int:
    """`golive skill install --list-targets` — look, don't touch."""
    cands = si.detect_targets()
    viable = [c for c in cands if c.exists or c.agent_present]
    print("探测到的 skill 安装位置（按推荐顺序）：\n")
    if viable:
        for i, c in enumerate(viable, 1):
            print(f"  [{i}] {c.describe()}")
    else:
        print("  （没有找到任何已安装的 agent）")
    others = [c for c in cands if c not in viable]
    if others:
        print("\n其余候选约定（目录都不存在，建好后会被自动识别）：")
        for c in others:
            print(f"      {c.path}  [{c.agent}]")
    print("\n安装到第一个："
          "\n  golive skill install"
          "\n安装到指定目录："
          "\n  golive skill install --target <DIR>")
    return 0


def _skill_status(si) -> int:
    """Version comparison across *every* detected location."""
    st = si.status()
    print(f"golive 版本：        {st['golive_version']}")
    print(f"包内 skill 版本：    "
          f"{st['packaged_skill_version'] or '(未知)'}")
    print(f"包内 skill 路径：    {st['packaged_skill_path']}")
    if not st["installs"]:
        print("\nℹ️  在 "
              f"{len(st['candidates'])} 个已知位置均未发现安装。运行："
              "\n   golive skill install"
              "\n   （先看看有哪些位置：golive skill install --list-targets）")
        return 0
    print(f"\n在 {st['install_count']} 个位置发现已安装：")
    for item in st["installs"]:
        mark = "✅" if item["version"] == \
            st["packaged_skill_version"] else "⚠️ "
        ver = item["version"] or "(无版本号)"
        agent = item.get("agent", "")
        print(f"  {mark} {ver}  {item['path']}"
              f"{'  [' + agent + ']' if agent else ''}")
        if item["error"]:
            print(f"      ⚠️  {item['error']}")
    if st["install_count"] > 1:
        print("\nℹ️  多个位置各有一份副本；升级 golive 后记得逐个 "
              "--force 同步，否则不同 agent 会读到不同版本。")
    if st["stale"]:
        print("\n⚠️  版本与当前 golive 不一致，同步："
              "\n   golive skill install --force")
        return 0
    print("\n✅ 已是最新。")
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
            print(f"示例页：{st['published']}/{st['total']} 已发布\n")
            for d in st["demos"]:
                mark = "✅" if d["published"] else "  "
                print(f"  {mark} /{d['slug']:<12} {d['description']}")
            if st["published"] < st["total"]:
                print("\n发布：golive demo install")
            return 0

        if args.demo_action == "install":
            res = demo.install()
            for d in res["demos"]:
                verb = "已发布" if d["action"] == "created" else "已更新"
                print(f"✅ {verb} /{d['slug']}  —  {d['description']}")
            u = demo.urls(port=args.port)
            print(f"\n   静态示例：{u['demo-static']}")
            print(f"   CRUD示例：{u['demo-crud']}")
            print(f"   （服务未启动就运行：golive serve --port {args.port}）")
            return 0

        # remove
        res = demo.remove(drop_data=not args.keep_data)
        if res["removed"]:
            print(f"✅ 已删除示例站点：{', '.join(res['removed'])}")
        if res["missing"]:
            print(f"ℹ️  本来就不存在：{', '.join(res['missing'])}")
        if res["rows_deleted"]:
            print(f"   顺带清理了 {res['rows_deleted']} 条示例待办数据"
                  "（--keep-data 可保留）")
        return 0
    except demo.DemoError as e:
        print(f"❌ {e}", file=sys.stderr)
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
                        help="golive.yaml 配置文件路径（默认按 $GOLIVE_CONFIG → "
                             "./golive.yaml → $GOLIVE_HOME/golive.yaml 查找）")
    sub = parser.add_subparsers(dest="command")

    # publish
    p = sub.add_parser("publish", help="发布 HTML 文件 / 目录 / 压缩包")
    p.add_argument("source", help="HTML 文件、项目目录或 zip/tar.gz 压缩包")
    p.add_argument("--name", default="", help="站点名称（默认取 <title>）")
    p.add_argument("--slug", default="", help="短域名（如 demo → /demo）")
    p.add_argument("--style", default="", help="注入 CSS 风格（golive styles 查看）")
    p.add_argument("--entry", default="", help="目录/压缩包模式的入口 HTML")
    p.add_argument("--update", default="", help="覆盖更新已有站点（id 或 slug）")
    p.add_argument("--owner", default="", help="站点负责人标识")
    p.add_argument("--compress", action="store_true", help="自动压缩内联图片")
    p.add_argument("--skip-scan", action="store_true", help="跳过安全扫描")
    p.add_argument("--data-model", default="",
                   help="TemplateAPI modelCode（逗号分隔多个）；配置 data backend "
                        "后自动注入数据层 JS")
    p.add_argument("--enable-editor", action="store_true",
                   help="开启在线编辑器（注入编辑器 JS + 标记站点可编辑）")
    p.add_argument("--watermark", nargs="?", const="", default=None,
                   metavar="TEXT",
                   help="注入页面水印；可选静态文本（不填则用 OIDC 身份 / "
                        "yaml watermark.text / 页面 meta 标签）")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help="URL 提示中的 serve 端口")
    p.set_defaults(func=cmd_publish)

    # list
    p = sub.add_parser("list", help="列出已发布站点")
    p.set_defaults(func=cmd_list)

    # rollback
    p = sub.add_parser("rollback", help="回滚站点到历史快照")
    p.add_argument("site", help="站点 id 或 slug")
    p.add_argument("--snapshot", default="", help="快照时间戳（默认最新）")
    p.add_argument("--dry-run", action="store_true", help="仅列出快照，不执行")
    p.add_argument("--yes", action="store_true", help="跳过确认")
    p.set_defaults(func=cmd_rollback)

    # maintainer
    p = sub.add_parser("maintainer", help="站点编辑权限（owner/maintainer）管理")
    p.add_argument("maintainer_action", choices=["add", "remove", "list"])
    p.add_argument("site", help="站点 id 或 slug")
    p.add_argument("email", nargs="?", default="", help="maintainer 邮箱")
    p.set_defaults(func=cmd_maintainer)

    # serve
    p = sub.add_parser("serve", help="启动内置 HTTP 服务（不带子命令=前台运行）")
    p.add_argument("serve_action", nargs="?", default="",
                   choices=["", "start", "status", "stop", "restart", "logs"],
                   help="start/status/stop/restart/logs：后台服务管理；"
                        "省略则前台运行（与历史行为一致）")
    p.add_argument("--port", type=int, default=None,
                   help=f"监听端口（默认 {DEFAULT_SERVE_PORT}）")
    p.add_argument("--host", default=None,
                   help="bind address (default: server.host in golive.yaml, "
                        "else 127.0.0.1; use 0.0.0.0 to expose)")
    p.add_argument("-n", "--lines", type=int, default=50,
                   help="logs：显示最后 N 行（默认 50）")
    p.add_argument("-f", "--follow", action="store_true",
                   help="logs：持续跟随输出（Ctrl+C 退出）")
    p.set_defaults(func=cmd_serve)

    # admin
    p = sub.add_parser("admin", help="运营管理门户")
    p.add_argument("admin_action", choices=["open"], help="open: 打印 /admin 门户地址")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.set_defaults(func=cmd_admin)

    # clone
    p = sub.add_parser("clone", help="克隆公网页面并发布")
    p.add_argument("url", help="要克隆的页面 URL")
    p.add_argument("--name", default="", help="站点名称")
    p.add_argument("--slug", default="", help="短域名")
    p.add_argument("--headless", action="store_true", help="无头浏览器抓取（SPA）")
    p.add_argument("--analyze-only", action="store_true", help="仅分析，不发布")
    p.add_argument("--save-only", action="store_true", help="仅保存 HTML 到本地")
    p.add_argument("--backend-origin", default="", help="原始后端服务地址")
    p.add_argument("--skip-backend-rewrite", action="store_true")
    p.set_defaults(func=cmd_clone)

    # preview
    p = sub.add_parser("preview", help="本地实时预览（带风格切换面板）")
    p.add_argument("file", nargs="?", default="", help="本地 HTML 文件")
    p.add_argument("--dir", default="", help="多文件项目目录")
    p.add_argument("--entry", default="", help="目录模式入口 HTML")
    p.add_argument("--site", default="", help="已发布站点 id/slug")
    p.add_argument("--css-style", default=None, help="初始 CSS 风格")
    p.add_argument("--port", type=int, default=18765)
    p.add_argument("--host", default="127.0.0.1",
                   help="监听地址（默认 127.0.0.1 仅本机；远程/容器环境用 --host 0.0.0.0）")
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p.set_defaults(func=cmd_preview)

    # styles
    p = sub.add_parser("styles", help="列出内置 CSS 风格")
    p.set_defaults(func=cmd_styles)

    # migrate-check
    p = sub.add_parser("migrate-check",
                       help="扫描 HTML，报告内网专属引用（迁移前检查）")
    p.add_argument("file", help="要检查的 HTML 文件")
    p.set_defaults(func=lambda a: __import__(
        "golive.core.migrate_check", fromlist=["run"]).run(a.file))

    # db
    p = sub.add_parser("db", help="数据库表初始化（输出建表 SQL）")
    p.add_argument("db_action", choices=["init"], help="init：输出建表 SQL")
    p.add_argument("--print-sql", action="store_true",
                   help="仅打印 SQL（默认行为，显式标记用）")
    p.set_defaults(func=cmd_db)

    # data
    p = sub.add_parser("data", help="数据层（TemplateAPI）行级 CRUD")
    p.add_argument("action",
                   choices=["list", "get", "create", "update", "delete",
                            "upsert"])
    p.add_argument("--model-code", default="default",
                   help="modelCode 命名空间（默认 default）")
    p.add_argument("--id", default="", help="模板 id（get/update/delete）")
    p.add_argument("--name", default="", help="模板名称")
    p.add_argument("--content", default="",
                   help="JSON 内容，或 @file.json 从文件读取")
    p.add_argument("--desc", default="", help="描述")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_data)

    # doctor
    p = sub.add_parser("doctor", help="环境健康检查")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.add_argument("--json", action="store_true",
                   help="输出机器可读的 JSON 报告")
    p.set_defaults(func=cmd_doctor)

    # skill
    p = sub.add_parser("skill", help="安装随包分发的 AI agent skill")
    p.add_argument("skill_action", choices=["install", "status", "path"],
                   help="install：安装到 agent skills 目录；"
                        "status：版本比对；path：打印包内 skill 目录")
    p.add_argument("--target", default="",
                   help="安装目标目录（不指定则自动探测常见位置）")
    p.add_argument("--list-targets", action="store_true",
                   help="只列出探测到的安装位置，不做任何改动")
    p.add_argument("--from-github", action="store_true",
                   help="从 GitHub 拉取最新 skill（默认用包内版本，离线可用）")
    p.add_argument("--force", action="store_true",
                   help="覆盖已存在的同名 skill（先自动备份）")
    p.set_defaults(func=cmd_skill)

    # init
    p = sub.add_parser("init",
                       help="一条命令跑通：目录 → skill → 数据层 → 示例页 → 服务")
    p.add_argument("--home", default="", metavar="DIR",
                   help="数据目录（默认 ~/.golive）；指定后会持久化，"
                        "之后所有 CLI/服务都指向这里")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.add_argument("--host", default="127.0.0.1",
                   help="服务监听地址（默认仅本机）")
    p.add_argument("--skip-skill", action="store_true",
                   help="不安装 AI agent skill")
    p.add_argument("--skill-target", default="", metavar="DIR",
                   help="skill 安装目录（跳过自动探测）")
    p.add_argument("--no-serve", action="store_true",
                   help="校验完就退出，不驻留服务")
    p.set_defaults(func=cmd_init)

    # context
    p = sub.add_parser("context",
                       help="我现在到底在用哪套配置？（只读，不创建任何目录）")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help="探测该端口上是否有服务在跑")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_context)

    # demo
    p = sub.add_parser("demo", help="内置示例页（介绍页 + 真能用的待办清单）")
    p.add_argument("demo_action", choices=["install", "remove", "status"],
                   help="install：发布两个示例；remove：清理；status：看状态")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT,
                   help="URL 提示中的 serve 端口")
    p.add_argument("--keep-data", action="store_true",
                   help="remove 时保留示例待办数据")
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
        print(f"❌ 配置文件错误：{e}", file=sys.stderr)
        return 1

    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
