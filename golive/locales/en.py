# -*- coding: utf-8 -*-
"""English translations for golive CLI.

Keys are organised by command/area. Every key in this file MUST also
exist in ``zh.py`` and vice versa — ``test_i18n`` enforces this.
"""

from __future__ import annotations

TRANSLATIONS = {

    # ── argparse: top-level ──────────────────────────────────────────────
    "arg.config": "Path to golive.yaml (default: search $GOLIVE_CONFIG → ./golive.yaml → $GOLIVE_HOME/golive.yaml)",
    "arg.config.error": "❌ Config file error: {msg}",

    # ── argparse: publish ────────────────────────────────────────────────
    "arg.publish.help": "Publish an HTML file / directory / archive",
    "arg.publish.source": "HTML file, project directory, or zip/tar.gz archive",
    "arg.publish.name": "Site name (defaults to <title>)",
    "arg.publish.slug": "Short URL path (e.g. demo → /demo)",
    "arg.publish.style": "Inject a CSS style (run `golive styles` to list)",
    "arg.publish.entry": "Entry HTML for directory/archive mode",
    "arg.publish.update": "Update an existing site (id or slug)",
    "arg.publish.owner": "Site owner identifier",
    "arg.publish.compress": "Auto-compress inline images",
    "arg.publish.skip_scan": "Skip the security scan",
    "arg.publish.data_model": "TemplateAPI modelCode (comma-separated for multiple); auto-injects data-layer JS when a backend is configured",
    "arg.publish.enable_editor": "Enable the online editor (injects editor JS + marks site editable)",
    "arg.publish.watermark": "Inject a page watermark; optional static text (omit → use OIDC identity / yaml watermark.text / page meta tag)",
    "arg.publish.port": "Serve port for URL hints",

    # ── argparse: list ─────────────────────────────────────────────────
    "arg.list.help": "List published sites",

    # ── argparse: rollback ──────────────────────────────────────────────
    "arg.rollback.help": "Roll a site back to a previous snapshot",
    "arg.rollback.site": "Site id or slug",
    "arg.rollback.snapshot": "Snapshot timestamp (default: latest)",
    "arg.rollback.dry_run": "List snapshots without rolling back",
    "arg.rollback.yes": "Skip confirmation",

    # ── argparse: maintainer ────────────────────────────────────────────
    "arg.maintainer.help": "Manage site editor permissions (owner/maintainer)",
    "arg.maintainer.email": "Maintainer email",

    # ── argparse: serve ────────────────────────────────────────────────
    "arg.serve.help": "Start the built-in HTTP server (no sub-command = foreground)",
    "arg.serve.action": "start/status/stop/restart/logs: background service management; omit to run in foreground (same as before)",
    "arg.serve.port": "Listen port (default {default_port})",
    "arg.serve.host": "Bind address (default: server.host in golive.yaml, else 127.0.0.1; use 0.0.0.0 to expose)",
    "arg.serve.lines": "logs: show last N lines (default 50)",
    "arg.serve.follow": "logs: follow output (Ctrl+C to exit)",

    # ── argparse: admin ─────────────────────────────────────────────────
    "arg.admin.help": "Admin management portal",
    "arg.admin.action": "open: print the /admin portal URL",

    # ── argparse: clone ─────────────────────────────────────────────────
    "arg.clone.help": "Clone a public web page and publish it",
    "arg.clone.url": "URL of the page to clone",
    "arg.clone.name": "Site name",
    "arg.clone.slug": "Short URL path",
    "arg.clone.headless": "Headless browser fetch (for SPAs)",
    "arg.clone.analyze_only": "Analyze only, do not publish",
    "arg.clone.save_only": "Save HTML locally only",
    "arg.clone.backend_origin": "Original backend service URL",

    # ── argparse: preview ──────────────────────────────────────────────
    "arg.preview.help": "Local live preview (with style switcher panel)",
    "arg.preview.file": "Local HTML file",
    "arg.preview.dir": "Multi-file project directory",
    "arg.preview.entry": "Entry HTML for directory mode",
    "arg.preview.site": "Published site id/slug",
    "arg.preview.css_style": "Initial CSS style",
    "arg.preview.host": "Bind address (default 127.0.0.1, local only; use --host 0.0.0.0 for remote/container)",
    "arg.preview.no_open": "Do not auto-open the browser",

    # ── argparse: styles ───────────────────────────────────────────────
    "arg.styles.help": "List built-in CSS styles",

    # ── argparse: migrate-check ────────────────────────────────────────
    "arg.migrate_check.help": "Scan HTML for internal-only references (pre-migration check)",
    "arg.migrate_check.file": "HTML file to check",

    # ── argparse: db ────────────────────────────────────────────────────
    "arg.db.help": "Database table init (output CREATE TABLE SQL)",
    "arg.db.action": "init: output CREATE TABLE SQL",
    "arg.db.print_sql": "Print SQL only (default behaviour, explicit flag)",

    # ── argparse: data ─────────────────────────────────────────────────
    "arg.data.help": "Data layer (TemplateAPI) row-level CRUD",
    "arg.data.model_code": "modelCode namespace (default: default)",
    "arg.data.id": "Template id (get/update/delete)",
    "arg.data.name": "Template name",
    "arg.data.content": "JSON content, or @file.json to read from file",
    "arg.data.desc": "Description",

    # ── argparse: doctor ───────────────────────────────────────────────
    "arg.doctor.help": "Environment health check",
    "arg.doctor.json": "Output machine-readable JSON report",

    # ── argparse: skill ────────────────────────────────────────────────
    "arg.skill.help": "Install the bundled AI agent skill",
    "arg.skill.action": "install: install to agent skills directory; status: version check; path: print packaged skill directory",
    "arg.skill.target": "Install target directory (auto-detect common locations if omitted)",
    "arg.skill.list_targets": "List detected install locations without making changes",
    "arg.skill.from_github": "Fetch latest skill from GitHub (default: use packaged version, works offline)",
    "arg.skill.force": "Overwrite an existing skill (auto-backup first)",

    # ── argparse: init ─────────────────────────────────────────────────
    "arg.init.help": "One command to bootstrap: data dir → skill → data layer → demos → serve",
    "arg.init.home": "Data directory (default ~/.golive); once set it persists — all subsequent CLI/server calls use it",
    "arg.init.port": "Serve port",
    "arg.init.host": "Serve bind address (default: local only)",
    "arg.init.skip_skill": "Do not install the AI agent skill",
    "arg.init.skill_target": "Skill install directory (skip auto-detection)",
    "arg.init.no_serve": "Exit after validation, do not keep the server running",
    "arg.init.background": "Move the server to the background after validation (survives terminal close)",

    # ── argparse: context ───────────────────────────────────────────────
    "arg.context.help": "Which config am I actually using? (read-only, creates no directories)",
    "arg.context.port": "Probe this port for a running server",
    "arg.context.json": "Output JSON",

    # ── argparse: demo ─────────────────────────────────────────────────
    "arg.demo.help": "Built-in demo sites (intro page + working todo list)",
    "arg.demo.action": "install: publish both demos; remove: clean up; status: show state",
    "arg.demo.port": "Serve port for URL hints",
    "arg.demo.keep_data": "Keep demo todo data when removing",

    # ── publish: source loading ─────────────────────────────────────────
    "skill.auto_pick": "\u2139\ufe0f  Found {count} possible locations; picking the first (non-interactive):\n     {path}  [{agent}]",
    "skill.other_candidates": "   Other candidates:",
    "skill.pick_hint": "   Choose another: golive skill install --target <DIR>  (--list-targets shows them all)",
    "skill.found_targets": "Found {count} possible install locations:",
    "skill.choose_prompt": "Pick a location [1-{max}], Enter for 1: ",
    "skill.cancelled": "\u26a0\ufe0f  Cancelled \u2014 using the first location.",
    "skill.bad_number": "'{raw}' is not a valid choice (expected 1-{max})",
    "skill.number_out_of_range": "Choice out of range: {idx} (expected 1-{max})",
    "skill.not_applicable": "\u2298 {detail}",
    "skill.no_agent": "No AI agent detected (run golive skill install when you need it, or pass --target <DIR>)",
    "skill.common_locations": "Common locations (create one, then run again):",
    "publish.success": "✅ Published \"{name}\"",
    "publish.url.public": "   URL:      {url}",
    "publish.url.local": "   Local:    {url}",
    "publish.url.lan": "   Network:  {url}   \u2190 share this one",
    "publish.url.lan_none": "   Network:  not detected (this machine only)",
    "publish.needs_host": "   (run golive serve --host 0.0.0.0 to let other machines reach it)",
    "publish.path_not_found": "❌ Path does not exist: {path}",
    "publish.dir_mode": "📁 Directory mode: bundling {path} ...",
    "publish.zip_mode": "📦 Archive mode: extracting {name} ...",
    "publish.zip_illegal_member": "❌ Archive contains an unsafe path member: {name}",
    "publish.unsupported_type": "❌ Unsupported file type: {suffix} (supported: .html / directory / .zip / .tar.gz)",

    # ── publish: style ─────────────────────────────────────────────────
    "publish.unknown_style": "❌ Unknown style `{style}`, available: {styles}",
    "publish.style_injected": "🎨 Injected CSS style: {style} ({label})",

    # ── publish: update/create ──────────────────────────────────────────
    "publish.site_not_found": "❌ Site not found: {ref}",
    "publish.updated": "\n✅ Updated site \"{name}\"",
    "publish.published": "\n✅ Published \"{name}\"",
    "publish.serve_hint": "   (If serve is not running, start it with: golive serve --port {port})",

    # ── publish: data layers ───────────────────────────────────────────
    "publish.tpl_injected": "🧩 Injected TemplateAPI data layer (modelCode: {model}, backend: {backend})",
    "publish.tpl_sqlite_hint": "   Data is stored in $GOLIVE_HOME/data.db; the page reads/writes via golive serve's /api/data.",
    "publish.tpl_supabase_unconfigured": "⚠️  Page uses TemplateAPI but Supabase is not configured — injected a stub (calls will error with guidance).\n   Configure: supabase.url in golive.yaml, GOLIVE_SUPABASE_ANON_KEY in env;\n   or switch back to data.backend: sqlite (zero-config, default).",
    "publish.tpl_backend_none": "⚠️  Page uses TemplateAPI but data.backend is none — injected a stub (calls will error with guidance).\n   Configure: data.backend: sqlite (zero-config, default) or supabase in golive.yaml.",
    "publish.sb_injected": "🧩 Injected SupabaseAPI data layer",
    "publish.sb_unconfigured": "⚠️  Page uses SupabaseAPI but Supabase is not configured — injected a stub (calls will error with guidance).\n   Configure: supabase.url + GOLIVE_SUPABASE_ANON_KEY in golive.yaml/env (remember to set RLS on your tables).",

    # ── publish: watermark ─────────────────────────────────────────────
    "publish.wm_disabled": "⏭️  GOLIVE_WATERMARK_OFF=1 — watermark disabled",
    "publish.wm_source_oidc": "OIDC user identity",
    "publish.wm_source_static": "static text \"{text}\"",
    "publish.wm_source_meta": "page meta tag",
    "publish.wm_injected": "💧 Injected watermark layer (identity source: {source})",

    # ── publish: editor ─────────────────────────────────────────────────
    "publish.editor_no_token": "⚠️  Editor is enabled but no editor token is configured — all save requests will be rejected.\n   Set GOLIVE_EDITOR_TOKEN (or golive.yaml editor.token), then open the page with ?editor_token=<token>&editor_user=<email>.",
    "publish.editor_no_owner": "⚠️  This site has no owner/maintainer — anyone with the editor token can save (shared token mode).\n   Recommended: golive publish --owner you@example.com, or golive maintainer add <slug> <email> to tighten permissions.",
    "publish.editor_injected": "✏️  Injected online editor (click the ✏️ in the bottom-right corner, or add ?edit=1 to the URL)",

    # ── list ────────────────────────────────────────────────────────────
    "list.empty": "No sites yet. Try: golive publish <file.html> --name Demo --slug demo",
    "list.count": "{count} site(s):\n",
    "list.updated_at": "    Updated {updated_at}",
    "list.owner": " · owner: {owner}",

    # ── rollback ────────────────────────────────────────────────────────
    "rollback.no_snapshots": "❌ Site \"{name}\" has no snapshots to roll back to.",
    "rollback.snapshot_count": "Site \"{name}\" has {count} snapshot(s) (newest → oldest):\n",
    "rollback.dry_run": "\n(dry-run mode, no rollback performed. Use --yes to execute, --snapshot <ts> to pick one, default: latest.)",
    "rollback.snapshot_not_found": "❌ Snapshot {ts} not found",
    "rollback.confirm": "\nRoll back to snapshot {ts}? (y/N): ",
    "rollback.cancelled": "⚠️  Cancelled",
    "rollback.done": "✅ Rolled back to {ts} (the current version was automatically saved as a new snapshot)",

    # ── maintainer ──────────────────────────────────────────────────────
    "maintainer.list_owner_unset": "(not set)",
    "maintainer.list_none": "(none)",
    "maintainer.list_header": "Editor permissions for \"{name}\":",
    "maintainer.list_owner": "  owner:       {owner}",
    "maintainer.list_maintainers": "  maintainers: {maintainers}",
    "maintainer.list_editable_yes": "yes",
    "maintainer.list_editable_no": "no",
    "maintainer.bad_email": "❌ Please provide a valid email: golive maintainer {action} {site} you@example.com",
    "maintainer.added": "✅ Added maintainer: {email}",
    "maintainer.removed": "✅ Removed maintainer: {email}",
    "maintainer.current_list": "   Current list: {maintainers}",

    # ── serve: management ───────────────────────────────────────────────
    "serve.start.started": "🚀 golive serve started in the background (pid {pid})",
    "serve.start.url": "   URL:     http://localhost:{port}/",
    "serve.start.admin": "   Admin:   http://localhost:{port}/admin",
    "serve.start.log": "   Log:     {log}",
    "serve.start.stop": "   Stop:    golive serve stop",
    "serve.already_running": "ℹ️  golive is already running on port {port}{pid}",
    "serve.already_running_hint": "   To apply new code, run: golive serve restart",
    "serve.start_failed": "❌ Failed to start: {message}",
    "serve.status.not_running": "⏹  Not running",
    "serve.status.stale_pidfile": "   (The process recorded in the pidfile has exited; the next `start` will clean it up: {pidfile})",
    "serve.status.port_taken": "   ⚠️  Port {port} is held by another program.",
    "serve.status.start_hint": "   Start with: golive serve start",
    "serve.status.pid_unknown": "pid unknown",
    "serve.status.version_unknown": "unknown version",
    "serve.status.running": "✅ Running  {version}  {pid}  port {port}",
    "serve.status.foreign": "   (Not started by `golive serve start` — probably a foreground process)",
    "serve.status.started_at": "   Started at: {started_at}",
    "serve.status.version_mismatch": "   ⚠️  CLI is {cli_version}, server is {version} — code updated but server is stale. Run: golive serve restart",
    "serve.status.url": "   URL:     http://localhost:{port}/",
    "serve.status.log": "   Log:     {log}",
    "serve.stop.ok": "{icon} {message}",
    "serve.restart.done": "🔁 Restarted: http://localhost:{port}/{pid}",
    "serve.restart.failed": "❌ Restart failed: {message}",
    "serve.logs.empty": "(No logs yet: {log_path})",
    "serve.logs.hint": "   Background service logs are here; foreground `golive serve` prints directly to the terminal.",
    "serve.unknown_action": "❌ Unknown serve sub-command: {action}",

    # ── admin ───────────────────────────────────────────────────────────
    "admin.portal": "🛠  Admin portal: {url}",
    "admin.serve_hint": "   (If serve is not running, start it with: golive serve --port {port})",

    # ── clone ────────────────────────────────────────────────────────────
    "clone.analyze_only": "ℹ️  --analyze-only mode, not publishing.",
    "clone.zip_downloaded": "📦 Downloaded archive: {source_zip}",
    "clone.zip_publish_hint": "   Publish with: golive publish {source_zip} --name \"{name}\"",
    "clone.saved": "\n✅ HTML saved to: {out}",
    "clone.placeholders": "   ⚠️  The page contains data-module placeholders (__PLACEHOLDER_) — fill them in before publishing.",
    "clone.publish_hint": "   Publish with: golive publish {out} --name \"{name}\"",

    # ── preview ────────────────────────────────────────────────────────
    "preview.no_target": "❌ Please specify <file>, --dir, or --site",

    # ── doctor ──────────────────────────────────────────────────────────
    "doctor.title": "🩺 golive doctor\n",
    "doctor.cli_version": "(CLI)",
    "doctor.service_unknown_version": "version unknown",
    "doctor.service_no_version_note": "ℹ️  This server does not report a version",
    "doctor.service_version_ok": "✅",
    "doctor.service_version_mismatch": "⚠️  Version mismatch, consider restarting",
    "doctor.service_version_mismatch_detail": "{pad} Code updated (CLI {cli_version}) but server is still old ({version}) — run: golive serve restart",
    "doctor.service_no_version_detail": "{pad} This server's /health does not return a version (0.7.x and earlier) — likely old code, consider `golive serve restart`",
    "doctor.service_port_taken": "⚠️  Port {port} is held by another program",
    "doctor.service_not_running": "not running",
    "doctor.service_start_hint": "(Start with: golive serve start --port {port})",
    "doctor.service_stale_pidfile": "{pad} ℹ️  The process in the pidfile has exited; the next `golive serve start` will clean it up",
    "doctor.home_unavailable": "(unavailable)",
    "doctor.home_not_writable": "❌ Not writable: {error}",
    "doctor.home_from_env": "  ← from $GOLIVE_HOME",
    "doctor.unknown": "(unknown)",
    "doctor.no_storage_location": "(unknown)",
    "doctor.no_data_location": "(none)",
    "doctor.storage_error": "❌ {error}",
    "doctor.registry_error": "❌ {error}",
    "doctor.data_error": "❌ {error}",
    "doctor.missing_content": "{pad} ⚠️  {count} site(s) missing content files: {first}{more}",
    "doctor.skill_check_failed": "⚠️  {error}",
    "doctor.skill_not_installed": "Not installed",
    "doctor.skill_install_hint": "(Install with: golive skill install)",
    "doctor.skill_no_version": "(no version)",
    "doctor.skill_mismatch": "⚠️  Does not match CLI; run `golive skill install --force`",
    "doctor.deps_missing": "  {level} Dependency {module} missing — {hint}",
    "doctor.problems_found": "Found {count} problem(s):",
    "doctor.healthy": "✅ Environment is healthy.",

    # ── doctor: problems ────────────────────────────────────────────────
    "doctor.problem_home_not_writable": "GOLIVE_HOME is not writable: {error}",
    "doctor.problem_registry": "Registry error: {error}",
    "doctor.problem_storage": "Storage error: {error}",
    "doctor.problem_data": "Data layer error: {error}",
    "doctor.problem_dep": "Dependency {module} missing — {hint}",

    # ── doctor: deps hints ─────────────────────────────────────────────
    "doctor.dep.bs4": "Directory bundling / cloning requires beautifulsoup4",
    "doctor.dep.requests": "Cloning / resource inlining requires requests",
    "doctor.dep.yaml": "Security scanning requires pyyaml",
    "doctor.dep.pil": "Image compression requires Pillow (optional, pip install 'html-golive[image]')",

    # ── doctor: data info ───────────────────────────────────────────────
    "doctor.data.disabled": "disabled, data.backend: none",
    "doctor.data.not_created": "not created yet, auto-created on first use",
    "doctor.data.supabase_unconfigured": "⚠️ supabase not configured (url / anon key missing)",
    "doctor.data.tables_rows": "{tables} table(s), {rows} row(s), {size}",
    "doctor.data.site_count": "{count} site(s)",
    "doctor.data.supabase_not_configured": "(bucket not configured)",

    # ── doctor: storage info ────────────────────────────────────────────
    "doctor.storage.site_count_size": "{count} site(s), {size}",
    "doctor.storage.bucket_unset": "(bucket not configured)",

    # ── doctor: registry info ───────────────────────────────────────────
    "doctor.registry.site_count": "{count} site(s)",

    # ── db ───────────────────────────────────────────────────────────────
    "db.registry_ready": "✅ registry (sqlite): {path} ready",
    "db.data_ready": "✅ data (sqlite): {path} ready (table {table})",
    "db.local_auto": "ℹ️  Local backends create tables automatically on first use; no manual init needed. For Supabase CREATE TABLE SQL, add --print-sql.",
    "db.supabase_unconfigured": "\n-- ℹ️  Supabase is not configured: paste the SQL above into the Supabase SQL Editor and run it.",
    "db.postgrest_no_ddl": "\nℹ️  PostgREST cannot execute DDL. Paste the SQL above into Supabase Dashboard → SQL Editor and run it once.",

    # ── data ────────────────────────────────────────────────────────────
    "data.disabled": "❌ Data backend is disabled (data.backend: none). Switch to data.backend: sqlite (zero-config, default) or supabase and retry.",
    "data.template_not_found": "❌ Template not found: {id}",
    "data.created": "✅ Created: {id}",
    "data.upserted": "✅ Written: {id}",
    "data.updated": "✅ Updated: {id}",
    "data.deleted": "✅ Deleted",
    "data.not_found": "⚠️  Record does not exist",
    "data.unknown_action": "❌ Unknown action: {action}",
    "data.operation_failed": "❌ Operation failed: {e}",

    # ── skill ───────────────────────────────────────────────────────────
    "skill.no_skill_md": "⚠️  No SKILL.md found in that directory — the package install may be incomplete.",
    "skill.installed": "✅ Installed skill \"{name}\"{version}",
    "skill.source": "   Source:   {origin} ({source})",
    "skill.installed_to": "   Installed to: {path}",
    "skill.file_count": "   Files:   {count} file(s) ({first}{more})",
    "skill.backup": "   Previous version backed up: {backup}",
    "skill.next_step": "\nNext: restart your AI agent so it re-scans the skills directory, then ask it to run `golive doctor` to verify.",
    "skill.install_error": "❌ {error}",
    "skill.targets_header": "Detected skill install locations (recommended order):\n",
    "skill.no_agents": "  (No installed agents detected)",
    "skill.other_candidates": "\nOther candidate locations (directories do not exist yet; create them to be auto-detected):",
    "skill.install_first": "\nInstall to the first one:\n  golive skill install\nInstall to a specific directory:\n  golive skill install --target <DIR>",
    "skill.status_golive_version": "golive version:        {version}",
    "skill.status_packaged_version": "Bundled skill version:   {version}",
    "skill.status_packaged_path": "Bundled skill path:       {path}",
    "skill.status_packaged_unknown": "(unknown)",
    "skill.status_not_found": "\nℹ️  Not found in {count} known location(s). Run:\n   golive skill install\n   (See available locations: golive skill install --list-targets)",
    "skill.status_found_in": "\nFound in {count} location(s):",
    "skill.status_version_mismatch_mark": "⚠️ ",
    "skill.status_version_ok_mark": "✅",
    "skill.status_version_unknown": "(no version)",
    "skill.status_error": "      ⚠️  {error}",
    "skill.status_multi_hint": "\nℹ️  Multiple copies exist; after upgrading golive, remember to --force each one, or different agents will read different versions.",
    "skill.status_stale": "\n⚠️  Version does not match the current golive. Sync:\n   golive skill install --force",
    "skill.status_latest": "\n✅ Up to date.",

    # ── demo ────────────────────────────────────────────────────────────
    "demo.status_header": "Demo sites: {published}/{total} published\n",
    "demo.publish_hint": "\nPublish with: golive demo install",
    "demo.install_created": "✅ Published /{slug}  —  {description}",
    "demo.install_updated": "✅ Updated /{slug}  —  {description}",
    "demo.static_url": "   Static demo: {url}",
    "demo.crud_url": "   CRUD demo:    {url}",
    "demo.serve_hint": "   (If serve is not running, start it with: golive serve --port {port})",
    "demo.removed": "✅ Removed demo sites: {sites}",
    "demo.missing": "ℹ️  Did not exist: {sites}",
    "demo.rows_deleted": "   Also cleaned up {count} demo todo rows (--keep-data to preserve)",
    "demo.error": "❌ {error}",

    # ── init wizard ────────────────────────────────────────────────────
    "init.banner": "🚀 golive init — from zero to a live page\n",
    "init.step_home": "Data directory",
    "init.step_home_not_writable": "{path} is not writable: {error}",
    "init.step_home_hint": "Try a writable path: golive init --home ~/golive-data",
    "init.step_home_created": "{path} (created{note})",
    "init.step_home_reused": "{path} (already exists, reusing{note})",
    "init.step_home_pointer_note": ", recorded at {pointer}",
    "init.step_home_pointer_error": " (could not write pointer file: {error}, effective this session only)",
    "init.step_home_from_env": "  ← from $GOLIVE_HOME",
    "init.step_env": "Environment check",
    "init.step_env_py_too_old": "Python {version} is too old (requires ≥ {min})",
    "init.step_env_port_free": "port {port} is free",
    "init.step_env_golive_reuse": "port {port} already has golive v{version} running (reusing)",
    "init.step_env_port_taken": "port {port} is held by another program",
    "init.step_env_hint": "Try a different port: golive init --port {port}",
    "init.step_skill": "agent skill",
    "init.step_skill_skipped": "skipped (--skip-skill)",
    "init.step_skill_fresh": "Already installed and up to date (v{version}): {path}",
    "init.step_skill_overwritten": " (overwrote old version)",
    "init.step_skill_installed": "{path} v{version}{note}",
    "init.step_skill_hint": "Specify a directory: golive skill install --target <DIR>; or skip: golive init --skip-skill",
    "init.step_data": "Data layer",
    "init.step_data_disabled": "data.backend = {backend} (data layer off)",
    "init.step_data_ready": "{backend} → {where} (table {table} ready)",
    "init.step_data_hint": "Check the data / registry sections in golive.yaml, or delete the config file to go back to zero-config defaults (sqlite)",
    "init.step_demos": "Demo sites",
    "init.step_demos_hint_reinstall": "Reinstall html-golive to restore bundled resources",
    "init.step_demos_hint_doctor": "Check `golive doctor` for other issues",
    "init.step_config": "Config file",
    "init.step_config_hint": "Fix the golive.yaml syntax, or delete it to use defaults",
    "init.step_start_server": "Start server",
    "init.step_start_server_ok": "http://{host}:{port}/",
    "init.step_start_server_port_err": "port {port}: {error}",
    "init.step_start_server_port_hint": "Try a different port: golive init --port {port}",
    "init.step_start_reuse": "port {port} already has golive running, reusing it",
    "init.step_verify": "Health check",
    "init.step_verify_hint": "The server is up but some checks failed: {failed}. Run `golive context` to confirm the CLI and server point to the same GOLIVE_HOME.",
    "init.hint_prefix": "       ↳ How to fix: {hint}",
    "init.no_serve_done": "\n(--no-serve: validation complete, server stopped. Start it with: golive serve --port {port})",
    "init.reused_server": "\n(The server is provided by another process; this command does not take it over.)",
    "init.background_ok": "\n(Server moved to background, pid {pid}. Manage with: golive serve status / logs / stop)",
    "init.background_failed": "\n⚠️  Failed to move to background: {error}",
    "init.background_failed_hint": "   Pages are temporarily unavailable. Run manually: golive serve start --port {port}",
    "init.forever_hint": "\n   Ctrl+C to stop the server (to keep it running after closing the terminal: golive init --background, or golive serve start --port {port})",
    "init.stopped": "\n👋 Stopped",
    "init.success_header": "🎉 All set! Open these URLs:",
    "init.partial_header": "⚠️  Some checks did not pass, but the URLs below may still work:",
    "init.static_demo": "   Static demo: {url}",
    "init.crud_demo": "   CRUD demo:    {url}",
    "init.admin_url": "   Admin panel:  {url}",

    # ── serve (app.py) ──────────────────────────────────────────────────
    "serve.app.started": "🚀 golive serve started",
    "serve.app.localhost": "   Local:  http://localhost:{port}/",
    "serve.app.lan": "   LAN:    http://{ip}:{port}/",
    "serve.app.loopback_only": "   (Local only; to share, add --host 0.0.0.0, and consider GOLIVE_TOKEN / OIDC)",
    "serve.app.oauth": "   OAuth:  http://localhost:{port}/auth/login",
    "serve.app.admin": "   Admin:  http://localhost:{port}/admin",
    "serve.app.stop": "   Ctrl+C to stop",
    "serve.app.stopped": "\n👋 Stopped",
    "serve.app.oidc_misconfig": "⚠️  OIDC configuration incomplete; OAuth login disabled: {error}",
    "serve.app.data_layer_warn_1": "   ⚠️  Data layer is exposed to the network without access control",
    "serve.app.data_layer_warn_2": "      /api/data is called directly by in-page JS and is not authenticated; bound to a",
    "serve.app.data_layer_warn_3": "      non-loopback address, anyone who can reach the port can read/write data tables.",
    "serve.app.data_layer_warn_4": "      Recommended: set GOLIVE_TOKEN, enable OIDC, or use a reverse proxy to restrict access.",
    "serve.app.data_layer_warn_5": "      For local-only use, switch back to --host 127.0.0.1.",
    "serve.app.index_empty": "No sites yet. Try `golive publish`.",

    # ── publish_utils ───────────────────────────────────────────────────
    "publish_utils.framework_detected": (
        "⚠️  Detected a {framework} project, but no build output (dist/ or build/ directory) was found.\n"
        "   Run the following commands and then retry:\n"
        "   cd {dir}\n"
        "   npm install && npm run build\n"
        "   Then run: golive publish {dir}/dist"
    ),
    "publish_utils.no_html": (
        "⚠️  Found package.json, but the directory has no HTML files and no dist/ or build/ output.\n"
        "   golive only supports static HTML projects.\n"
        "   • Frontend project: run `npm run build` first, then publish the output directory\n"
        "   • Node.js backend project: golive does not support this type"
    ),
    "publish_utils.uploader_enabled": "📤 Custom image uploader enabled (GOLIVE_UPLOADER_CMD)",
    "publish_utils.entry_not_found": "Error: specified entry file does not exist: {path}",
    "publish_utils.bundle_error": "Error: {error}",
    "publish_utils.compress_no_pillow": "⚠️  Image compression requires Pillow (pip install 'html-golive[image]'), skipping.",
    "publish_utils.compressed": "🗜️  Compressed {count} image(s), saved about {kb} KB",
    "publish_utils.size_over_10mb_compress": "⚠️  HTML size {size_mb:.1f}MB (over 10MB), attempting quality {quality} compression...",
    "publish_utils.size_compressed_ok": "   ✅ Compressed to: {size_mb:.1f}MB (quality {quality})",
    "publish_utils.size_still_over": "   Still {size_mb:.1f}MB, continuing to degrade...",
    "publish_utils.size_block_fail": "\n❌ Still over 10MB after quality 30 compression; cannot publish.",
    "publish_utils.size_block_hint": "   Suggest manually removing some large images and retrying.",
    "publish_utils.size_block_no_compress": "\n❌ HTML size {size_mb:.1f}MB exceeds the 10MB limit; publishing blocked.",
    "publish_utils.size_block_no_compress_hint": "   Please compress images and re-publish: pass --compress",
    "publish_utils.size_warn_compress": "⚠️  HTML size {size_mb:.1f}MB (over 5MB), --compress enabled, auto-compressing.",
    "publish_utils.size_warn": "⚠️  HTML size {size_mb:.1f}MB (over 5MB). Consider adding --compress to compress inline images.",
    "publish_utils.title_missing": "⚠️  No <title> tag detected; consider adding a page title (affects the site list display name)",

    # ── preview_server ─────────────────────────────────────────────────
    "preview.tailwind_downloading": "[preview] Downloading Tailwind CDN cache (subsequent previews will be instant)...",
    "preview.tailwind_cached": "[preview] Tailwind cache complete ({kb} KB)",
    "preview.tailwind_failed": "[preview] ⚠️  Tailwind cache failed, using raw CDN: {error}",
    "preview.css_inject_failed": "[preview] CSS injection failed: {error}",
    "preview.no_html": "[preview] No HTML loaded",
    "preview.site_not_found": "[preview] Site not found: {ref}",
    "preview.read_failed": "[preview] Failed to read site content: {error}",
    "preview.dir_mode": "[preview] 📁 Directory mode: {dir}",
    "preview.bundling": "[preview] Bundling (images downgraded to base64, not uploaded)...",
    "preview.bundle_failed": "[preview] ❌ Bundling failed, please check the project directory.",
    "preview.file_loaded": "[preview] Loaded local file: {path}",
    "preview.site_loaded": "[preview] Reading published site: {ref} ...",
    "preview.site_read_failed": "[preview] ❌ Could not fetch content, exiting",
    "preview.no_target": "[preview] ❌ Please specify --file, --dir, or --site",
    "preview.rebundle_failed": "[preview] ❌ Cannot import bundle module: {error}",
    "preview.dir_not_supported": "[preview] ⚠️  Cannot preview this directory:",
    "preview.dir_build_first": "[preview] Build first, then use --dir pointing at the output directory.",
    "preview.bundle_error": "[preview] ❌ Bundling failed: {error}",
    "preview.change_detected": "[preview] Change detected: {name}",
    "preview.rebundling": "[preview] 🔄 Re-bundling...",
    "preview.rebundle_done": "[preview] ✅ Bundling complete, refreshed",
    "preview.dir_change": "[preview] Directory change detected, re-bundling in 1s...",
    "preview.server_started": "🎨  Preview server started: {url}",
    "preview.url_note": "    {note}",
    "preview.dir_mode_listen": "📁  Directory mode: watching {dir} (re-bundles 1s after changes)",
    "preview.file_listen": "📁  Watching file changes (HTML + css_styles/)",
    "preview.stop": "    Ctrl+C to stop",
    "preview.stopped": "\n[preview] Stopped",
    "preview.access_lan": "(Pod/remote environment; localhost is not reachable for you, use the IP address above)",
    "preview.access_fallback": "(Could not get LAN IP; if the page is not accessible, manually substitute the server IP)",
    "preview.arg_description": "html-go-live local preview server",
    "preview.arg_epilog": (
        "Examples:\n"
        "  # Preview a local HTML file with no style\n"
        "  python3 preview_server.py --file report.html\n\n"
        "  # Preview with the xhs style injected by default\n"
        "  python3 preview_server.py --file report.html --css-style xhs\n\n"
        "  # Preview a published site (fetches live content)\n"
        "  golive preview --site demo\n\n"
        "  # Specify a port\n"
        "  python3 preview_server.py --file report.html --port 9000"
    ),
    "preview.arg_file": "Path to a local HTML file",
    "preview.arg_dir": "Multi-file project directory (auto-bundled, watched for changes)",
    "preview.arg_site": "Published site id or slug",
    "preview.arg_entry": "--dir mode: entry HTML (relative to the directory, default: auto-detect index.html)",
    "preview.arg_css_style": "Initial CSS style (default: none)",
    "preview.arg_port": f"Listen port (default 18765)",
    "preview.arg_no_browser": "Do not auto-open the browser",
}
