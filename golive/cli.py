#!/usr/bin/env python3
"""golive — self-hosted one-command HTML deployment CLI.

Subcommands:
  publish   Publish a file / directory / zip archive
  list      List published sites
  rollback  Roll a site back to a previous snapshot
  serve     Start the built-in HTTP server
  clone     Clone a public web page and publish it
  preview   Live-preview a local HTML file (with CSS style panel)
  doctor    Environment health check
  styles    List built-in CSS styles
"""

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
from golive.core.paths import get_home, get_registry_db, get_sites_dir
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
        storage.publish(html, site["site_id"], backup_previous=False)
        print(f"\n✅ 发布成功「{site['name']}」")

    print(f"   site_id: {site['site_id']}")
    if site.get("slug"):
        print(f"   slug:    {site['slug']}")
    print(f"   URL:     {_site_url(site, args.port)}")
    print(f"   （若 serve 未启动，运行：golive serve --port {args.port}）")
    return 0


def _title_of(html: str) -> str:
    import re
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return m.group(1).strip()[:60] if m else ""


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


# ═════════════════════════════════ serve ════════════════════════════════════

def cmd_serve(args) -> int:
    from golive.server.app import serve
    serve(host=args.host, port=args.port)
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

def cmd_doctor(args) -> int:
    import socket

    print("🩺 golive doctor\n")
    problems = 0

    # 1. GOLIVE_HOME writable
    try:
        home = get_home()
        probe = home / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
        print(f"  ✅ GOLIVE_HOME 可写：{home}")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ GOLIVE_HOME 不可写：{e}")
        problems += 1

    # 2. registry DB
    try:
        reg = SqliteRegistry()
        n = len(reg.list_all())
        print(f"  ✅ 注册表可读：{get_registry_db()}（{n} 个站点）")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 注册表异常：{e}")
        problems += 1

    # 3. sites dir consistency
    try:
        reg = SqliteRegistry()
        storage = LocalStorage()
        missing = [s["site_id"] for s in reg.list_all()
                   if not storage.exists(s["site_id"])]
        if missing:
            print(f"  ⚠️  {len(missing)} 个站点缺少内容文件：{', '.join(missing[:3])}...")
        else:
            print(f"  ✅ 站点内容完整：{get_sites_dir()}")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 站点目录检查失败：{e}")
        problems += 1

    # 4. serve port
    port = args.port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
    if in_use:
        print(f"  ℹ️  端口 {port} 已被占用（可能 golive serve 已在运行）")
    else:
        print(f"  ✅ 端口 {port} 空闲（golive serve --port {port} 可启动）")

    # 5. optional deps
    for mod, hint in (("bs4", "目录打包/克隆需要 beautifulsoup4"),
                      ("requests", "克隆/资源内联需要 requests"),
                      ("yaml", "安全扫描需要 pyyaml"),
                      ("PIL", "图片压缩需要 Pillow（可选，pip install 'html-golive[image]'）")):
        try:
            __import__(mod)
            print(f"  ✅ 依赖 {mod} 可用")
        except ImportError:
            level = "⚠️ " if mod == "PIL" else "❌"
            print(f"  {level} 依赖 {mod} 缺失 — {hint}")
            if mod != "PIL":
                problems += 1

    print()
    if problems:
        print(f"发现 {problems} 个问题，请按上方提示修复。")
        return 1
    print("✅ 环境健康。")
    return 0


# ═════════════════════════════════ db / data ════════════════════════════════

def cmd_db(args) -> int:
    """golive db init — print (or apply) backend table schemas."""
    from golive.backends.data.supabase import CREATE_TABLE_SQL as TPL_SQL
    from golive.backends.data.supabase import DEFAULT_TABLE as TPL_TABLE
    from golive.backends.registry.supabase_store import CREATE_TABLE_SQL as REG_SQL
    from golive.backends.registry.supabase_store import DEFAULT_TABLE as REG_TABLE
    from golive.config import get_config

    cfg = get_config()
    reg_table = cfg.registry.supabase_table or REG_TABLE
    tpl_table = cfg.data.templates_table or TPL_TABLE
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
        print("❌ data backend 未配置。请在 golive.yaml 设置 "
              "data.backend: supabase 并配置 supabase.url + key。",
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

    # serve
    p = sub.add_parser("serve", help="启动内置 HTTP 服务")
    p.add_argument("--port", type=int, default=DEFAULT_SERVE_PORT)
    p.add_argument("--host", default="0.0.0.0")
    p.set_defaults(func=cmd_serve)

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
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)

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
