# -*- coding: utf-8 -*-
"""Chinese translations for golive CLI.

Keys mirror ``en.py``. Values are the original Chinese strings that
were in the codebase before i18n — do not rewrite them.

IMPORTANT: the key set must be identical to ``en.py``. The test
``test_i18n.test_translation_keys_match`` enforces this.
"""

from __future__ import annotations

TRANSLATIONS = {

    # ── argparse: top-level ──────────────────────────────────────────────
    "arg.config": "golive.yaml 配置文件路径（默认按 $GOLIVE_CONFIG → ./golive.yaml → $GOLIVE_HOME/golive.yaml 查找）",
    "arg.config.error": "❌ 配置文件错误：{msg}",

    # ── argparse: publish ────────────────────────────────────────────────
    "arg.publish.help": "发布 HTML 文件 / 目录 / 压缩包",
    "arg.publish.source": "HTML 文件、项目目录或 zip/tar.gz 压缩包",
    "arg.publish.name": "站点名称（默认取 <title>）",
    "arg.publish.slug": "短域名（如 demo → /demo）",
    "arg.publish.style": "注入 CSS 风格（golive styles 查看）",
    "arg.publish.entry": "目录/压缩包模式的入口 HTML",
    "arg.publish.update": "覆盖更新已有站点（id 或 slug）",
    "arg.publish.owner": "站点负责人标识",
    "arg.publish.compress": "自动压缩内联图片",
    "arg.publish.skip_scan": "跳过安全扫描",
    "arg.publish.data_model": "TemplateAPI modelCode（逗号分隔多个）；配置 data backend 后自动注入数据层 JS",
    "arg.publish.enable_editor": "开启在线编辑器（注入编辑器 JS + 标记站点可编辑）",
    "arg.publish.watermark": "注入页面水印；可选静态文本（不填则用 OIDC 身份 / yaml watermark.text / 页面 meta 标签）",
    "arg.publish.port": "URL 提示中的 serve 端口",

    # ── argparse: list ─────────────────────────────────────────────────
    "arg.list.help": "列出已发布站点",

    # ── argparse: rollback ──────────────────────────────────────────────
    "arg.rollback.help": "回滚站点到历史快照",
    "arg.rollback.site": "站点 id 或 slug",
    "arg.rollback.snapshot": "快照时间戳（默认最新）",
    "arg.rollback.dry_run": "仅列出快照，不执行",
    "arg.rollback.yes": "跳过确认",

    # ── argparse: maintainer ────────────────────────────────────────────
    "arg.maintainer.help": "站点编辑权限（owner/maintainer）管理",
    "arg.maintainer.email": "maintainer 邮箱",

    # ── argparse: serve ────────────────────────────────────────────────
    "arg.serve.help": "启动内置 HTTP 服务（不带子命令=前台运行）",
    "arg.serve.action": "start/status/stop/restart/logs：后台服务管理；省略则前台运行（与历史行为一致）",
    "arg.serve.port": "监听端口（默认 {default_port}）",
    "arg.serve.host": "bind address (default: server.host in golive.yaml, else 127.0.0.1; use 0.0.0.0 to expose)",
    "arg.serve.lines": "logs：显示最后 N 行（默认 50）",
    "arg.serve.follow": "logs：持续跟随输出（Ctrl+C 退出）",

    # ── argparse: admin ─────────────────────────────────────────────────
    "arg.admin.help": "运营管理门户",
    "arg.admin.action": "open: 打印 /admin 门户地址",

    # ── argparse: clone ─────────────────────────────────────────────────
    "arg.clone.help": "克隆公网页面并发布",
    "arg.clone.url": "要克隆的页面 URL",
    "arg.clone.name": "站点名称",
    "arg.clone.slug": "短域名",
    "arg.clone.headless": "无头浏览器抓取（SPA）",
    "arg.clone.analyze_only": "仅分析，不发布",
    "arg.clone.save_only": "仅保存 HTML 到本地",
    "arg.clone.backend_origin": "原始后端服务地址",

    # ── argparse: preview ──────────────────────────────────────────────
    "arg.preview.help": "本地实时预览（带风格切换面板）",
    "arg.preview.file": "本地 HTML 文件",
    "arg.preview.dir": "多文件项目目录",
    "arg.preview.entry": "目录模式入口 HTML",
    "arg.preview.site": "已发布站点 id/slug",
    "arg.preview.css_style": "初始 CSS 风格",
    "arg.preview.host": "监听地址（默认 127.0.0.1 仅本机；远程/容器环境用 --host 0.0.0.0）",
    "arg.preview.no_open": "不自动打开浏览器",

    # ── argparse: styles ───────────────────────────────────────────────
    "arg.styles.help": "列出内置 CSS 风格",

    # ── argparse: migrate-check ────────────────────────────────────────
    "arg.migrate_check.help": "扫描 HTML，报告内网专属引用（迁移前检查）",
    "arg.migrate_check.file": "要检查的 HTML 文件",

    # ── argparse: db ────────────────────────────────────────────────────
    "arg.db.help": "数据库表初始化（输出建表 SQL）",
    "arg.db.action": "init：输出建表 SQL",
    "arg.db.print_sql": "仅打印 SQL（默认行为，显式标记用）",

    # ── argparse: data ─────────────────────────────────────────────────
    "arg.data.help": "数据层（TemplateAPI）行级 CRUD",
    "arg.data.model_code": "modelCode 命名空间（默认 default）",
    "arg.data.id": "模板 id（get/update/delete）",
    "arg.data.name": "模板名称",
    "arg.data.content": "JSON 内容，或 @file.json 从文件读取",
    "arg.data.desc": "描述",

    # ── argparse: doctor ───────────────────────────────────────────────
    "arg.doctor.help": "环境健康检查",
    "arg.doctor.json": "输出机器可读的 JSON 报告",

    # ── argparse: skill ────────────────────────────────────────────────
    "arg.skill.help": "安装随包分发的 AI agent skill",
    "arg.skill.action": "install：安装到 agent skills 目录；status：版本比对；path：打印包内 skill 目录",
    "arg.skill.target": "安装目标目录（不指定则自动探测常见位置）",
    "arg.skill.list_targets": "只列出探测到的安装位置，不做任何改动",
    "arg.skill.from_github": "从 GitHub 拉取最新 skill（默认用包内版本，离线可用）",
    "arg.skill.force": "覆盖已存在的同名 skill（先自动备份）",

    # ── argparse: init ─────────────────────────────────────────────────
    "arg.init.help": "一条命令跑通：目录 → skill → 数据层 → 示例页 → 服务",
    "arg.init.home": "数据目录（默认 ~/.golive）；指定后会持久化，之后所有 CLI/服务都指向这里",
    "arg.init.port": "服务监听端口",
    "arg.init.host": "服务监听地址（默认仅本机）",
    "arg.init.skip_skill": "不安装 AI agent skill",
    "arg.init.skill_target": "skill 安装目录（跳过自动探测）",
    "arg.init.no_serve": "校验完就退出，不驻留服务",
    "arg.init.background": "校验后把服务转入后台，关掉终端也保持在线",

    # ── argparse: context ───────────────────────────────────────────────
    "arg.context.help": "我现在到底在用哪套配置？（只读，不创建任何目录）",
    "arg.context.port": "探测该端口上是否有服务在跑",
    "arg.context.json": "输出 JSON",

    # ── argparse: demo ─────────────────────────────────────────────────
    "arg.demo.help": "内置示例页（介绍页 + 真能用的待办清单）",
    "arg.demo.action": "install：发布两个示例；remove：清理；status：看状态",
    "arg.demo.port": "URL 提示中的 serve 端口",
    "arg.demo.keep_data": "remove 时保留示例待办数据",

    # ── publish: source loading ─────────────────────────────────────────
    "skill.auto_pick": "\u2139\ufe0f  \u68c0\u6d4b\u5230 {count} \u4e2a\u53ef\u5b89\u88c5\u4f4d\u7f6e\uff0c\u975e\u4ea4\u4e92\u73af\u5883\u81ea\u52a8\u9009\u62e9\u7b2c\u4e00\u4e2a\uff1a\n     {path}  [{agent}]",
    "skill.other_candidates": "   \u5176\u4ed6\u5019\u9009\uff1a",
    "skill.pick_hint": "   \u6307\u5b9a\u5176\u4ed6\u4f4d\u7f6e\uff1agolive skill install --target <DIR>\uff08--list-targets \u67e5\u770b\u5168\u90e8\uff09",
    "skill.found_targets": "\u68c0\u6d4b\u5230 {count} \u4e2a\u53ef\u5b89\u88c5\u4f4d\u7f6e\uff1a",
    "skill.choose_prompt": "\u9009\u62e9\u5b89\u88c5\u4f4d\u7f6e [1-{max}]\uff0c\u56de\u8f66\u7528 1\uff1a",
    "skill.cancelled": "\u26a0\ufe0f  \u5df2\u53d6\u6d88\uff0c\u4f7f\u7528\u7b2c\u4e00\u4e2a\u4f4d\u7f6e\u3002",
    "skill.bad_number": "'{raw}' \u4e0d\u662f\u6709\u6548\u7f16\u53f7\uff08\u5e94\u4e3a 1-{max}\uff09",
    "skill.number_out_of_range": "\u7f16\u53f7\u8d85\u51fa\u8303\u56f4\uff1a{idx}\uff08\u5e94\u4e3a 1-{max}\uff09",
    "skill.not_applicable": "\u2298 {detail}",
    "skill.no_agent": "\u672a\u68c0\u6d4b\u5230 AI agent\uff08\u9700\u8981\u65f6\u8fd0\u884c golive skill install\uff0c\u6216\u7528 --target <DIR> \u6307\u5b9a\u76ee\u5f55\uff09",
    "skill.common_locations": "\u5e38\u89c1\u5b89\u88c5\u4f4d\u7f6e\uff08\u521b\u5efa\u540e\u91cd\u65b0\u8fd0\u884c\u5373\u53ef\uff09\uff1a",
    "publish.success": "✅ 发布成功\u300c{name}\u300d",
    "publish.url.public": "   URL:     {url}",
    "publish.url.local": "   本机:    {url}",
    "publish.url.lan": "   局域网:  {url}   \u2190 分享给同事用这个",
    "publish.url.lan_none": "   局域网:  未检测到（本机可访问）",
    "publish.needs_host": "   （需要 golive serve --host 0.0.0.0 才能被其他机器访问）",
    "publish.path_not_found": "❌ 路径不存在：{path}",
    "publish.dir_mode": "📁 目录模式：打包 {path} ...",
    "publish.zip_mode": "📦 压缩包模式：解压 {name} ...",
    "publish.zip_illegal_member": "❌ 压缩包含非法路径成员：{name}",
    "publish.unsupported_type": "❌ 不支持的文件类型：{suffix}（支持 .html / 目录 / .zip / .tar.gz）",

    # ── publish: style ─────────────────────────────────────────────────
    "publish.unknown_style": "❌ 未知风格 `{style}`，可用：{styles}",
    "publish.style_injected": "🎨 已注入 CSS 风格：{style}（{label}）",

    # ── publish: update/create ──────────────────────────────────────────
    "publish.site_not_found": "❌ 未找到站点：{ref}",
    "publish.updated": "\n✅ 已更新站点「{name}」",
    "publish.published": "\n✅ 发布成功「{name}」",
    "publish.serve_hint": "   （若 serve 未启动，运行：golive serve --port {port}）",

    # ── publish: data layers ───────────────────────────────────────────
    "publish.tpl_injected": "🧩 已注入 TemplateAPI 数据层（modelCode: {model}，backend: {backend}）",
    "publish.tpl_sqlite_hint": "   数据存放在 $GOLIVE_HOME/data.db，页面通过 golive serve 的 /api/data 读写。",
    "publish.tpl_supabase_unconfigured": "⚠️  页面使用了 TemplateAPI，但 Supabase 未配置 —— 已注入 stub（调用会报错并提示配置方法）。\n   配置：golive.yaml 里 supabase.url，env 里 GOLIVE_SUPABASE_ANON_KEY；\n   或改回默认的 data.backend: sqlite（零配置）。",
    "publish.tpl_backend_none": "⚠️  页面使用了 TemplateAPI，但 data.backend 为 none —— 已注入 stub（调用会报错并提示配置方法）。\n   配置：golive.yaml 里 data.backend: sqlite（零配置，默认值）或 supabase。",
    "publish.sb_injected": "🧩 已注入 SupabaseAPI 数据层",
    "publish.sb_unconfigured": "⚠️  页面使用了 SupabaseAPI，但 Supabase 未配置 —— 已注入 stub（调用会报错并提示配置方法）。\n   配置：golive.yaml 里 supabase.url + env GOLIVE_SUPABASE_ANON_KEY（注意为表配置 RLS）。",

    # ── publish: watermark ─────────────────────────────────────────────
    "publish.wm_disabled": "⏭️  GOLIVE_WATERMARK_OFF=1 — 水印已禁用",
    "publish.wm_source_oidc": "OIDC 用户身份",
    "publish.wm_source_static": "静态文本「{text}」",
    "publish.wm_source_meta": "页面 meta 标签",
    "publish.wm_injected": "💧 已注入水印层（身份来源：{source}）",

    # ── publish: editor ─────────────────────────────────────────────────
    "publish.editor_no_token": "⚠️  编辑模式已开启，但未配置编辑令牌 —— 保存请求将全部被拒。\n   设置 GOLIVE_EDITOR_TOKEN（或 golive.yaml editor.token）后，用 ?editor_token=<token>&editor_user=<email> 打开页面。",
    "publish.editor_no_owner": "⚠️  该站点未设置 owner/maintainer —— 持有编辑令牌的任何人都可保存（共享令牌模式）。\n   建议：golive publish --owner you@example.com，或 golive maintainer add <slug> <email> 收紧权限。",
    "publish.editor_injected": "✏️  已注入在线编辑器（打开页面点右下角 ✏️，或加 ?edit=1）",

    # ── list ────────────────────────────────────────────────────────────
    "list.empty": "暂无站点。试试：golive publish <file.html> --name Demo --slug demo",
    "list.count": "共 {count} 个站点：\n",
    "list.updated_at": "    更新于 {updated_at}",
    "list.owner": " · owner: {owner}",

    # ── rollback ────────────────────────────────────────────────────────
    "rollback.no_snapshots": "❌ 站点「{name}」没有可回滚的快照。",
    "rollback.snapshot_count": "站点「{name}」共有 {count} 份快照（新→旧）：\n",
    "rollback.dry_run": "\n（dry-run 模式，未执行回滚。加 --yes 执行，--snapshot <ts> 指定快照，默认最新一份。）",
    "rollback.snapshot_not_found": "❌ 未找到快照 {ts}",
    "rollback.confirm": "\n回滚到快照 {ts}？(y/N)：",
    "rollback.cancelled": "⚠️  已取消",
    "rollback.done": "✅ 已回滚到 {ts}（当前版本已自动存为新快照）",

    # ── maintainer ──────────────────────────────────────────────────────
    "maintainer.list_owner_unset": "(未设置)",
    "maintainer.list_none": "(无)",
    "maintainer.list_header": "站点「{name}」编辑权限：",
    "maintainer.list_owner": "  owner:       {owner}",
    "maintainer.list_maintainers": "  maintainers: {maintainers}",
    "maintainer.list_editable_yes": "是",
    "maintainer.list_editable_no": "否",
    "maintainer.bad_email": "❌ 请提供合法邮箱：golive maintainer {action} {site} you@example.com",
    "maintainer.added": "✅ 已添加 maintainer：{email}",
    "maintainer.removed": "✅ 已移除 maintainer：{email}",
    "maintainer.current_list": "   当前列表：{maintainers}",

    # ── serve: management ───────────────────────────────────────────────
    "serve.start.started": "🚀 golive serve 已在后台启动（pid {pid}）",
    "serve.start.url": "   地址:   http://localhost:{port}/",
    "serve.start.admin": "   管理台: http://localhost:{port}/admin",
    "serve.start.log": "   日志:   {log}",
    "serve.start.stop": "   停止:   golive serve stop",
    "serve.already_running": "ℹ️  golive 已在端口 {port} 上运行{pid}",
    "serve.already_running_hint": "   要应用新代码请运行：golive serve restart",
    "serve.start_failed": "❌ 启动失败：{message}",
    "serve.status.not_running": "⏹  未运行",
    "serve.status.stale_pidfile": "   （pidfile 记录的进程已退出，下次 start 会自动清理：{pidfile}）",
    "serve.status.port_taken": "   ⚠️  端口 {port} 被其他程序占用。",
    "serve.status.start_hint": "   启动：golive serve start",
    "serve.status.pid_unknown": "pid 未知",
    "serve.status.version_unknown": "未知版本",
    "serve.status.running": "✅ 运行中  {version}  {pid}  端口 {port}",
    "serve.status.foreign": "   （不是由 golive serve start 启动的——可能是前台进程）",
    "serve.status.started_at": "   启动于: {started_at}",
    "serve.status.version_mismatch": "   ⚠️  CLI 是 {cli_version}，服务是 {version} —— 代码已更新但服务是旧的，运行：golive serve restart",
    "serve.status.url": "   地址:   http://localhost:{port}/",
    "serve.status.log": "   日志:   {log}",
    "serve.stop.ok": "{icon} {message}",
    "serve.restart.done": "🔁 已重启：http://localhost:{port}/{pid}",
    "serve.restart.failed": "❌ 重启失败：{message}",
    "serve.logs.empty": "（暂无日志：{log_path}）",
    "serve.logs.hint": "   后台服务的日志在这里；前台 golive serve 直接打在终端上。",
    "serve.unknown_action": "❌ 未知 serve 子命令：{action}",

    # ── admin ───────────────────────────────────────────────────────────
    "admin.portal": "🛠  管理门户: {url}",
    "admin.serve_hint": "   （若 serve 未启动，运行：golive serve --port {port}）",

    # ── clone ────────────────────────────────────────────────────────────
    "clone.analyze_only": "ℹ️  --analyze-only 模式，不执行发布操作。",
    "clone.zip_downloaded": "📦 已下载压缩包：{source_zip}",
    "clone.zip_publish_hint": "   发布：golive publish {source_zip} --name \"{name}\"",
    "clone.saved": "\n✅ HTML 已保存到: {out}",
    "clone.placeholders": "   ⚠️  页面含数据模块占位符（__PLACEHOLDER_），请填写后再发布。",
    "clone.publish_hint": "   发布：golive publish {out} --name \"{name}\"",

    # ── preview ────────────────────────────────────────────────────────
    "preview.no_target": "❌ 请指定 <file>、--dir 或 --site",

    # ── doctor ──────────────────────────────────────────────────────────
    "doctor.title": "🩺 golive doctor\n",
    "doctor.cli_version": "(CLI)",
    "doctor.service_unknown_version": "版本未知",
    "doctor.service_no_version_note": "ℹ️  该服务不报版本",
    "doctor.service_version_ok": "✅",
    "doctor.service_version_mismatch": "⚠️  版本不一致，建议重启",
    "doctor.service_version_mismatch_detail": "{pad} 代码已更新（CLI {cli_version}）但服务还是旧的（{version}）—— 运行：golive serve restart",
    "doctor.service_no_version_detail": "{pad} 该服务的 /health 没有返回版本号（0.7.x 及更早版本）—— 很可能是旧代码，建议 golive serve restart",
    "doctor.service_port_taken": "⚠️  端口 {port} 被其他程序占用",
    "doctor.service_not_running": "not running",
    "doctor.service_start_hint": "（启动：golive serve start --port {port}）",
    "doctor.service_stale_pidfile": "{pad} ℹ️  pidfile 里的进程已退出，下次 golive serve start 会自动清理",
    "doctor.home_unavailable": "(不可用)",
    "doctor.home_not_writable": "❌ 不可写：{error}",
    "doctor.home_from_env": "  ← 来自 $GOLIVE_HOME",
    "doctor.unknown": "(未知)",
    "doctor.no_storage_location": "(未知)",
    "doctor.no_data_location": "(无)",
    "doctor.storage_error": "❌ {error}",
    "doctor.registry_error": "❌ {error}",
    "doctor.data_error": "❌ {error}",
    "doctor.missing_content": "{pad} ⚠️  {count} 个站点缺少内容文件：{first}{more}",
    "doctor.skill_check_failed": "⚠️  {error}",
    "doctor.skill_not_installed": "未安装",
    "doctor.skill_install_hint": "（安装：golive skill install）",
    "doctor.skill_no_version": "(无版本号)",
    "doctor.skill_mismatch": "⚠️  与 CLI 不一致，golive skill install --force",
    "doctor.deps_missing": "  {level} 依赖 {module} 缺失 — {hint}",
    "doctor.problems_found": "发现 {count} 个问题：",
    "doctor.healthy": "✅ 环境健康。",

    # ── doctor: problems ────────────────────────────────────────────────
    "doctor.problem_home_not_writable": "GOLIVE_HOME 不可写：{error}",
    "doctor.problem_registry": "注册表异常：{error}",
    "doctor.problem_storage": "存储异常：{error}",
    "doctor.problem_data": "数据层异常：{error}",
    "doctor.problem_dep": "依赖 {module} 缺失 — {hint}",

    # ── doctor: deps hints ─────────────────────────────────────────────
    "doctor.dep.bs4": "目录打包/克隆需要 beautifulsoup4",
    "doctor.dep.requests": "克隆/资源内联需要 requests",
    "doctor.dep.yaml": "安全扫描需要 pyyaml",
    "doctor.dep.pil": "图片压缩需要 Pillow（可选，pip install 'html-golive[image]'）",

    # ── doctor: data info ───────────────────────────────────────────────
    "doctor.data.disabled": "已禁用，data.backend: none",
    "doctor.data.not_created": "尚未创建，首次使用时自动建表",
    "doctor.data.supabase_unconfigured": "⚠️ supabase 未配置（url / anon key 缺失）",
    "doctor.data.tables_rows": "{tables} 张表, {rows} 行, {size}",
    "doctor.data.site_count": "{count} 个站点",
    "doctor.data.supabase_not_configured": "(bucket 未配置)",

    # ── doctor: storage info ────────────────────────────────────────────
    "doctor.storage.site_count_size": "{count} 个站点, {size}",
    "doctor.storage.bucket_unset": "(bucket 未配置)",

    # ── doctor: registry info ───────────────────────────────────────────
    "doctor.registry.site_count": "{count} 个站点",

    # ── db ───────────────────────────────────────────────────────────────
    "db.registry_ready": "✅ registry (sqlite)：{path} 已就绪",
    "db.data_ready": "✅ data (sqlite)：{path} 已就绪（表 {table}）",
    "db.local_auto": "ℹ️  本地后端会在首次使用时自动建表，无需手动 init。需要 Supabase 建表 SQL 请加 --print-sql。",
    "db.supabase_unconfigured": "\n-- ℹ️  Supabase 未配置：请把上面的 SQL 粘到 Supabase SQL Editor 里执行。",
    "db.postgrest_no_ddl": "\nℹ️  PostgREST 不支持执行 DDL。请把上面的 SQL 粘到 Supabase Dashboard → SQL Editor 执行一次即可。",

    # ── data ────────────────────────────────────────────────────────────
    "data.disabled": "❌ data backend 已禁用（data.backend: none）。改为 data.backend: sqlite（零配置，默认值）或 supabase 后重试。",
    "data.template_not_found": "❌ 未找到模板：{id}",
    "data.created": "✅ 已创建：{id}",
    "data.upserted": "✅ 已写入：{id}",
    "data.updated": "✅ 已更新：{id}",
    "data.deleted": "✅ 已删除",
    "data.not_found": "⚠️  记录不存在",
    "data.unknown_action": "❌ 未知操作：{action}",
    "data.operation_failed": "❌ 操作失败：{e}",

    # ── skill ───────────────────────────────────────────────────────────
    "skill.no_skill_md": "⚠️  该目录下没有 SKILL.md —— 包安装可能不完整。",
    "skill.installed": "✅ 已安装 skill「{name}」{version}",
    "skill.source": "   来源：   {origin}（{source}）",
    "skill.installed_to": "   安装到： {path}",
    "skill.file_count": "   文件：   {count} 个（{first}{more}）",
    "skill.backup": "   旧版本已备份： {backup}",
    "skill.next_step": "\n下一步：重启你的 AI agent 使其重新扫描 skills 目录，然后让它执行 `golive doctor` 验证。",
    "skill.install_error": "❌ {error}",
    "skill.targets_header": "探测到的 skill 安装位置（按推荐顺序）：\n",
    "skill.no_agents": "  （没有找到任何已安装的 agent）",
    "skill.other_candidates": "\n其余候选约定（目录都不存在，建好后会被自动识别）：",
    "skill.install_first": "\n安装到第一个：\n  golive skill install\n安装到指定目录：\n  golive skill install --target <DIR>",
    "skill.status_golive_version": "golive 版本：        {version}",
    "skill.status_packaged_version": "包内 skill 版本：    {version}",
    "skill.status_packaged_path": "包内 skill 路径：    {path}",
    "skill.status_packaged_unknown": "(未知)",
    "skill.status_not_found": "\nℹ️  在 {count} 个已知位置均未发现安装。运行：\n   golive skill install\n   （先看看有哪些位置：golive skill install --list-targets）",
    "skill.status_found_in": "\n在 {count} 个位置发现已安装：",
    "skill.status_version_mismatch_mark": "⚠️ ",
    "skill.status_version_ok_mark": "✅",
    "skill.status_version_unknown": "(无版本号)",
    "skill.status_error": "      ⚠️  {error}",
    "skill.status_multi_hint": "\nℹ️  多个位置各有一份副本；升级 golive 后记得逐个 --force 同步，否则不同 agent 会读到不同版本。",
    "skill.status_stale": "\n⚠️  版本与当前 golive 不一致，同步：\n   golive skill install --force",
    "skill.status_latest": "\n✅ 已是最新。",

    # ── demo ────────────────────────────────────────────────────────────
    "demo.status_header": "示例页：{published}/{total} 已发布\n",
    "demo.publish_hint": "\n发布：golive demo install",
    "demo.install_created": "✅ {verb} /{slug}  —  {description}",
    "demo.install_updated": "✅ {verb} /{slug}  —  {description}",
    "demo.static_url": "   静态示例：{url}",
    "demo.crud_url": "   CRUD示例：{url}",
    "demo.serve_hint": "   （服务未启动就运行：golive serve --port {port}）",
    "demo.removed": "✅ 已删除示例站点：{sites}",
    "demo.missing": "ℹ️  本来就不存在：{sites}",
    "demo.rows_deleted": "   顺带清理了 {count} 条示例待办数据（--keep-data 可保留）",
    "demo.error": "❌ {error}",

    # ── init wizard ────────────────────────────────────────────────────
    "init.banner": "🚀 golive init — 从零到能打开的页面\n",
    "init.step_home": "数据目录",
    "init.step_home_not_writable": "{path} 不可写：{error}",
    "init.step_home_hint": "换一个可写路径：golive init --home ~/golive-data",
    "init.step_home_created": "{path}（新建{note}）",
    "init.step_home_reused": "{path}（已存在，复用{note}）",
    "init.step_home_pointer_note": "，已记录到 {pointer}",
    "init.step_home_pointer_error": "（无法写入指针文件：{error}，仅本次生效）",
    "init.step_home_from_env": "  ← 来自 $GOLIVE_HOME",
    "init.step_env": "环境自检",
    "init.step_env_py_too_old": "Python {version} 过旧（需要 ≥ {min}）",
    "init.step_env_port_free": "端口 {port} 空闲",
    "init.step_env_golive_reuse": "端口 {port} 上已有 golive v{version} 在跑（复用）",
    "init.step_env_port_taken": "端口 {port} 被别的程序占用",
    "init.step_env_hint": "换端口：golive init --port {port}",
    "init.step_skill": "agent skill",
    "init.step_skill_skipped": "已跳过（--skip-skill）",
    "init.step_skill_fresh": "已安装且为最新（v{version}）：{path}",
    "init.step_skill_overwritten": "（已覆盖旧版本）",
    "init.step_skill_installed": "{path} v{version}{note}",
    "init.step_skill_hint": "指定目录重试：golive skill install --target <DIR>；或先跳过：golive init --skip-skill",
    "init.step_data": "数据层",
    "init.step_data_disabled": "data.backend = {backend}（数据层已关闭）",
    "init.step_data_ready": "{backend} → {where}（表 {table} 就绪）",
    "init.step_data_hint": "检查 golive.yaml 里的 data / registry 段，或删掉配置文件回到零配置默认值（sqlite）",
    "init.step_demos": "示例页",
    "init.step_demos_hint_reinstall": "重装 html-golive 以补齐包内资源",
    "init.step_demos_hint_doctor": "看看 golive doctor 有没有报别的问题",
    "init.step_config": "配置文件",
    "init.step_config_hint": "修正 golive.yaml 语法，或删掉它回到默认配置",
    "init.step_start_server": "启动服务",
    "init.step_start_server_ok": "http://{host}:{port}/",
    "init.step_start_server_port_err": "端口 {port}：{error}",
    "init.step_start_server_port_hint": "换端口：golive init --port {port}",
    "init.step_start_reuse": "端口 {port} 上已有 golive 在跑，直接复用",
    "init.step_verify": "健康校验",
    "init.step_verify_hint": "服务起来了但这几项没过：{failed}。先看 golive context 确认 CLI 和服务端指向同一个 GOLIVE_HOME。",
    "init.hint_prefix": "       ↳ 怎么修：{hint}",
    "init.no_serve_done": "\n（--no-serve：校验完成，服务已停止。需要时运行：golive serve --port {port}）",
    "init.reused_server": "\n（服务由另一个进程提供，本命令不接管它。）",
    "init.background_ok": "\n（服务已转入后台，pid {pid}。管理：golive serve status / logs / stop）",
    "init.background_failed": "\n⚠️  转入后台失败：{error}",
    "init.background_failed_hint": "   页面暂时不可访问，请手动运行：golive serve start --port {port}",
    "init.forever_hint": "\n   Ctrl+C 停止服务（想关掉终端也保持在线：golive init --background，或 golive serve start --port {port}）",
    "init.stopped": "\n👋 已停止",
    "init.success_header": "🎉 一切就绪，打开看看：",
    "init.partial_header": "⚠️  部分校验未通过，但下面的地址可以先试试：",
    "init.static_demo": "   静态示例：{url}",
    "init.crud_demo": "   CRUD示例：{url}",
    "init.admin_url": "   管理后台：{url}",

    # ── serve (app.py) ──────────────────────────────────────────────────
    "serve.app.started": "🚀 golive serve 已启动",
    "serve.app.localhost": "   本机:  http://localhost:{port}/",
    "serve.app.lan": "   局域网: http://{ip}:{port}/",
    "serve.app.loopback_only": "   （仅本机可访问；对外分享请加 --host 0.0.0.0，并建议配合 GOLIVE_TOKEN / OIDC）",
    "serve.app.oauth": "   OAuth:  http://localhost:{port}/auth/login",
    "serve.app.admin": "   管理门户: http://localhost:{port}/admin",
    "serve.app.stop": "   Ctrl+C 停止",
    "serve.app.stopped": "\n👋 已停止",
    "serve.app.oidc_misconfig": "⚠️  OIDC 配置不完整，已禁用 OAuth 登录：{error}",
    "serve.app.data_layer_warn_1": "   ⚠️  数据层对外开放且未设访问控制",
    "serve.app.data_layer_warn_2": "      /api/data 供页面内 JS 直接调用，本身不鉴权；绑定到非本机",
    "serve.app.data_layer_warn_3": "      地址后，能访问该端口的人都可读写数据表。",
    "serve.app.data_layer_warn_4": "      建议：设置 GOLIVE_TOKEN、启用 OIDC，或用反向代理限制来源。",
    "serve.app.data_layer_warn_5": "      仅本机使用请改回 --host 127.0.0.1。",
    "serve.app.index_empty": "暂无站点，试试 golive publish",

    # ── publish_utils ───────────────────────────────────────────────────
    "publish_utils.framework_detected": (
        "⚠️  检测到 {framework} 项目，但没有找到 build 产物（dist/ 或 build/ 目录）。\n"
        "   请先执行以下命令后重试：\n"
        "   cd {dir}\n"
        "   npm install && npm run build\n"
        "   然后使用 golive publish {dir}/dist 重新运行。"
    ),
    "publish_utils.no_html": (
        "⚠️  检测到 package.json，但目录中没有 HTML 文件，也没有 dist/ 或 build/ 产物目录。\n"
        "   golive 只支持静态 HTML 项目。\n"
        "   • 前端项目：请先 npm run build，再 publish 产物目录\n"
        "   • Node.js 后端项目：golive 不支持此类型"
    ),
    "publish_utils.uploader_enabled": "📤 已启用自定义图片上传（GOLIVE_UPLOADER_CMD）",
    "publish_utils.entry_not_found": "错误：指定入口文件不存在：{path}",
    "publish_utils.bundle_error": "错误：{error}",
    "publish_utils.compress_no_pillow": "⚠️  压缩图片需要 Pillow（pip install 'html-golive[image]'），跳过压缩。",
    "publish_utils.compressed": "🗜️  压缩了 {count} 张图片，节省约 {kb} KB",
    "publish_utils.size_over_10mb_compress": "⚠️  HTML 大小 {size_mb:.1f}MB（超过 10MB），尝试质量 {quality} 压缩...",
    "publish_utils.size_compressed_ok": "   ✅ 压缩后: {size_mb:.1f}MB（质量 {quality}）",
    "publish_utils.size_still_over": "   仍有 {size_mb:.1f}MB，继续降级...",
    "publish_utils.size_block_fail": "\n❌ 压缩到质量 30 后体积仍然超过 10MB，无法发布。",
    "publish_utils.size_block_hint": "   建议手动删除部分大图后重试。",
    "publish_utils.size_block_no_compress": "\n❌ HTML 大小 {size_mb:.1f}MB，超过 10MB 上限，发布已阻断。",
    "publish_utils.size_block_no_compress_hint": "   请压缩图片后重新发布：传入 --compress 参数",
    "publish_utils.size_warn_compress": "⚠️  HTML 大小 {size_mb:.1f}MB（超过 5MB），--compress 已启用，自动压缩。",
    "publish_utils.size_warn": "⚠️  HTML 大小 {size_mb:.1f}MB（超过 5MB），建议加 --compress 压缩内联图片。",
    "publish_utils.title_missing": "⚠️  未检测到 <title> 标签，建议补充页面标题（影响站点列表展示名称）",

    # ── preview_server ─────────────────────────────────────────────────
    "preview.tailwind_downloading": "[preview] 首次下载 Tailwind CDN 缓存(之后预览无需等待)...",
    "preview.tailwind_cached": "[preview] Tailwind 缓存完成 ({kb} KB)",
    "preview.tailwind_failed": "[preview] ⚠️  Tailwind 缓存失败,使用原始 CDN:{error}",
    "preview.css_inject_failed": "[preview] CSS 注入失败:{error}",
    "preview.no_html": "[preview] No HTML loaded",
    "preview.site_not_found": "[preview] 未找到站点: {ref}",
    "preview.read_failed": "[preview] 读取站点内容失败:{error}",
    "preview.dir_mode": "[preview] 📁 目录模式：{dir}",
    "preview.bundling": "[preview] 正在打包（图片降级为 base64，不上传）…",
    "preview.bundle_failed": "[preview] ❌ 打包失败，请检查项目目录。",
    "preview.file_loaded": "[preview] 加载本地文件：{path}",
    "preview.site_loaded": "[preview] 读取已发布站点：{ref} …",
    "preview.site_read_failed": "[preview] ❌ 无法获取内容，退出",
    "preview.no_target": "[preview] ❌ 请指定 --file、--dir 或 --site",
    "preview.rebundle_failed": "[preview] ❌ 无法导入 bundle 模块：{error}",
    "preview.dir_not_supported": "[preview] ⚠️  不支持预览此目录：",
    "preview.dir_build_first": "[preview] 请先 build 后，用 --dir 指向产物目录再预览。",
    "preview.bundle_error": "[preview] ❌ 打包失败：{error}",
    "preview.change_detected": "[preview] 检测到变化：{name}",
    "preview.rebundling": "[preview] 🔄 重新打包中…",
    "preview.rebundle_done": "[preview] ✅ 打包完成，已刷新",
    "preview.dir_change": "[preview] 检测到目录变化，1s 后重新打包…",
    "preview.server_started": "🎨  预览服务已启动：{url}",
    "preview.url_note": "    {note}",
    "preview.dir_mode_listen": "📁  目录模式：监听 {dir}（变化后 1s 重新打包）",
    "preview.file_listen": "📁  监听文件变化（HTML + css_styles/）",
    "preview.stop": "    Ctrl+C 停止",
    "preview.stopped": "\n[preview] 已停止",
    "preview.access_lan": "(Pod/远程环境,localhost 对你不可达,请用上方 IP 地址打开)",
    "preview.access_fallback": "(未能获取 LAN IP,若访问不到请手动替换为服务器 IP)",
    "preview.arg_description": "html-go-live 本地预览服务",
    "preview.arg_epilog": (
        "示例:\n"
        "  # 预览本地 HTML,无风格\n"
        "  python3 preview_server.py --file report.html\n\n"
        "  # 预览时默认注入 xhs 风格\n"
        "  python3 preview_server.py --file report.html --css-style xhs\n\n"
        "  # 预览已发布站点(拉取线上内容)\n"
        "  golive preview --site demo\n\n"
        "  # 指定端口\n"
        "  python3 preview_server.py --file report.html --port 9000"
    ),
    "preview.arg_file": "本地 HTML 文件路径",
    "preview.arg_dir": "多文件项目目录（自动打包后预览，监听变化 re-bundle）",
    "preview.arg_site": "已发布站点的 id 或 slug",
    "preview.arg_entry": "--dir 模式：指定入口 HTML（相对于目录，默认自动查找 index.html）",
    "preview.arg_css_style": "初始 CSS 风格（默认无风格）",
    "preview.arg_port": f"监听端口（默认 18765)",
    "preview.arg_no_browser": "不自动打开浏览器",
}
