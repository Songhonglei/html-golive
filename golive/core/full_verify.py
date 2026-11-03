"""Opt-in acceptance against real CLI, HTTP, browser, SQL and process restart.

The server is a disposable subprocess, never the user's managed service.
Only a random model/site created by this run is removed during cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit
import uuid


COVERAGE = ("preflight", "cli", "publish", "health", "browser_create", "browser_read",
            "browser_update", "browser_upsert", "browser_sort", "browser_pagination",
            "browser_refresh", "sql_evidence", "admin_backend", "restart_persistence", "browser_delete", "cleanup")


def run(args):
    from golive.config import get_config
    from golive.core.backend_info import data_backend_info
    from golive.core.paths import peek_home
    from golive.backends.factory import get_registry, get_storage, get_template_store
    from golive.cli import _verify_http

    cfg = get_config()
    requested_dir = getattr(args, "report_dir", "")
    report_dir = Path(requested_dir).expanduser().resolve() if requested_dir else Path(tempfile.mkdtemp(prefix="golive-verify-full-"))
    try:
        if requested_dir:
            # Never overwrite an earlier acceptance report.
            report_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        report_dir.chmod(0o700)
    except OSError:
        result = {"ok": False, "mode": "full", "code": "report_directory_unavailable",
                  "error": "Choose a new writable report directory; existing reports are never overwritten."}
        print(json.dumps(result) if getattr(args, "json", False) else result["error"])
        return 2
    model = "verify_" + uuid.uuid4().hex[:20]
    slug = model.replace("_", "-")
    results = []
    browser_events = []
    site = store = registry = storage = process = None
    port = None
    secrets = []
    for key, value in os.environ.items():
        if value and any(word in key.upper() for word in ("TOKEN", "PASSWORD", "DSN", "_KEY", "PROXY")):
            secrets.append(value)
            try:
                parsed = urlsplit(value)
                secrets.extend(unquote(part) for part in (parsed.username, parsed.password) if part)
            except ValueError:
                pass
    secrets = sorted(set(s for s in secrets if len(s) >= 4), key=len, reverse=True)

    def scrub(value):
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    def save(name, value):
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)
        path = report_dir / name
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(scrub(content))

    def content_of(row):
        value = row["templateContent"]
        return json.loads(value) if isinstance(value, str) else value

    def record(name, status="passed", detail=""):
        results.append({"step": name, "ok": status == "passed", "status": status, "detail": scrub(detail)})

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def cli(*argv):
        command = [sys.executable, "-m", "golive.cli"]
        if cfg.source_path:
            command += ["--config", cfg.source_path]
        proc = subprocess.run(command + list(argv), env=child_env, capture_output=True, text=True, timeout=45)
        cli_log.append({"arguments": list(argv), "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        require(proc.returncode == 0, "CLI command failed: " + argv[0] + " (see cli.log.json)")
        return json.loads(proc.stdout) if argv[0] == "data" else proc.stdout

    child_env = dict(os.environ, GOLIVE_HOME=str(peek_home()))
    child_env["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
    cli_log = []
    server_log = None

    def start():
        nonlocal process, port
        command = [sys.executable, "-m", "golive.cli"]
        if cfg.source_path:
            command += ["--config", cfg.source_path]
        process = subprocess.Popen(command + ["serve", "--host", "127.0.0.1", "--port", str(port)], env=child_env,
                                   stdout=server_log, stderr=server_log)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(process.poll() is None, "Temporary server exited; see server.log")
            try:
                status, health = _verify_http(port, "GET", "/health", timeout=1)
                if status == 200 and health.get("pid") == process.pid:
                    require(health.get("data_backend") == cfg.data.backend, "Child server backend differs from CLI")
                    require(Path(health.get("home", "")).resolve() == peek_home().resolve(), "Child server home differs from CLI")
                    return health
            except OSError:
                pass
            time.sleep(.1)
        raise RuntimeError("Temporary server readiness timed out")

    def stop():
        nonlocal process
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process = None

    current = "preflight"
    try:
        require(cfg.data.backend in ("sqlite", "mysql", "postgres"), "Full mode currently requires SQLite/MySQL/Postgres; no backend fallback was used")
        require(cfg.data.sqlite_path != ":memory:" or cfg.data.backend != "sqlite", "Restart persistence requires a file-backed SQLite database")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Install html-golive[verify], then run python -m playwright install chromium") from None
        store, registry, storage = get_template_store(cfg), get_registry(cfg), get_storage(cfg)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        fd = os.open(str(report_dir / "server.log"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        server_log = os.fdopen(fd, "w")
        record("preflight", detail="Real browser required. Random test namespace: " + model)
        current = "cli"
        a = cli("data", "create", "--model-code", model, "--name", "cli-row", "--content", '{"中文":"🧪","nested":{"v":1}}', "--json")
        ident = a["id"]
        require(a["ok"] and a["record"]["content"]["中文"] == "🧪", "CLI create failed")
        require(cli("data", "get", "--id", ident)["id"] == ident, "CLI get failed")
        require(cli("data", "update", "--id", ident, "--content", '{"updated":true}', "--json")["record"]["content"] == {"updated": True}, "CLI update failed")
        require(cli("data", "upsert", "--model-code", model, "--name", "cli-row", "--content", '{"upserted":true}', "--json")["id"] == ident, "CLI upsert changed identity")
        require(cli("data", "sort", "--id", ident, "--sort-index", "50", "--json")["record"]["sort_index"] == 50, "CLI sort failed")
        require(cli("data", "list", "--model-code", model, "--page-no", "1", "--page-size", "1")["list"][0]["id"] == ident, "CLI list failed")
        other = cli("data", "upsert", "--model-code", model, "--name", "cli-other", "--content", '{}', "--json")["id"]
        page_two = cli("data", "list", "--model-code", model, "--page-no", "2", "--page-size", "1")
        require(page_two["total"] == 2 and len(page_two["list"]) == 1 and page_two["list"][0]["id"] == other, "CLI page two failed")
        require(cli("data", "delete", "--id", ident, "--json")["ok"], "CLI delete failed")
        require(cli("data", "delete", "--id", other, "--json")["ok"], "CLI second delete failed")
        record("cli", detail="create/get/list/update/upsert/sort/pagination/delete with JSON writes")
        current = "publish"
        source = report_dir / "page.html"
        save("page.html", "<!doctype html><html><head><meta charset='utf-8'><title>Full acceptance</title><link rel='icon' href='data:,'></head><body><h1>OpenGoLive acceptance</h1></body></html>")
        cli("publish", str(source), "--slug", slug, "--data-model", model, "--name", model)
        site = registry.get_by_slug(slug)
        require(site is not None, "Published site missing from registry")
        record("publish", detail="Published through the CLI with TemplateAPI injection")
        current = "health"
        health = start()
        record("health", detail=json.dumps(health))
        url = f"http://127.0.0.1:{port}/s/{site['site_id']}"
        current = "browser_create"
        with sync_playwright() as pw:
            channel = getattr(args, "browser_channel", "chromium")
            browser = pw.chromium.launch(channel=channel if channel != "chromium" else None)
            try:
                page = browser.new_page()
                page.on("console", lambda msg: browser_events.append({"type": msg.type, "text": msg.text}))
                page.on("pageerror", lambda error: browser_events.append({"type": "pageerror", "text": str(error)}))
                page.goto(url, wait_until="networkidle")
                page.wait_for_function("!!window.TemplateAPI")
                current = "browser_create"
                content = {"中文": "你好 🧪", "nested": {"list": [1, None, True]}}
                first = page.evaluate("value => TemplateAPI.create({name:'browser-first',content:value})", content)
                second = page.evaluate("() => TemplateAPI.create({name:'browser-second',content:{n:2}})")
                require(first and second and first != second, "Browser create returned invalid IDs")
                record(current)
                current = "browser_read"
                require(content_of(page.evaluate("id => TemplateAPI.get(id)", first)) == content, "Browser content mismatch")
                record(current)
                current = "browser_update"
                page.evaluate("id => TemplateAPI.update(id,{content:{updated:true}})", first)
                require(content_of(page.evaluate("id => TemplateAPI.get(id)", first)) == {"updated": True}, "Browser update failed")
                record(current)
                current = "browser_upsert"
                require(page.evaluate("() => TemplateAPI.upsert({name:'browser-first',content:{upserted:true}})") == first, "Browser upsert changed identity")
                third = page.evaluate("() => TemplateAPI.upsert({name:'browser-third',content:{n:3}})")
                require(third and third not in (first, second), "Browser upsert create failed")
                record(current)
                current = "browser_sort"
                page.evaluate("id => TemplateAPI.sort(id,100)", first)
                page.evaluate("id => TemplateAPI.sort(id,50)", second)
                rows = page.evaluate("() => TemplateAPI.listAll({pageSize:10})")
                require([r["templateId"] for r in rows["list"]] == [first, second, third], "Browser sort order mismatch")
                record(current)
                current = "browser_pagination"
                rows = page.evaluate("() => TemplateAPI.listAll({pageNo:2,pageSize:1})")
                require(rows["total"] == 3 and len(rows["list"]) == 1 and rows["list"][0]["templateId"] == second, "Browser page/total mismatch")
                record(current)
                current = "browser_refresh"
                page.reload(wait_until="networkidle")
                require(content_of(page.evaluate("id => TemplateAPI.get(id)", first)) == {"upserted": True}, "Refresh lost content")
                record(current)
                current = "sql_evidence"
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", store.table), "Unsafe evidence table identifier")
                placeholder = "?" if cfg.data.backend == "sqlite" else "%s"
                query = f"SELECT id, model_code, name, content, sort_index FROM {store.table} WHERE model_code={placeholder} ORDER BY sort_index DESC"
                with store._conn() as conn:
                    version_query = "SELECT sqlite_version() AS version" if cfg.data.backend == "sqlite" else "SELECT VERSION() AS version"
                    version = dict(conn.execute(version_query).fetchone())
                    database = None
                    if cfg.data.backend in ("mysql", "postgres"):
                        database_query = "SELECT DATABASE() AS database_name" if cfg.data.backend == "mysql" else "SELECT current_database() AS database_name"
                        database = dict(conn.execute(database_query).fetchone())
                    evidence = [dict(r) for r in conn.execute(query, (model,)).fetchall()]
                require([r["id"] for r in evidence] == [first, second, third], "Direct SQL disagrees with browser IDs/order")
                evidence_content = evidence[0]["content"]
                if isinstance(evidence_content, str):
                    evidence_content = json.loads(evidence_content)
                require(evidence_content == {"upserted": True}, "Direct SQL content mismatch")
                save("sql-evidence.json", {"backend": data_backend_info(cfg), "version": version, "database": database, "query": query, "parameters": [model], "rows": evidence})
                record(current, detail="sql-evidence.json: independent SELECT agrees with browser")
                current = "admin_backend"
                admin = browser.new_page()
                admin.on("console", lambda msg: browser_events.append({"page": "admin", "type": msg.type, "text": msg.text}))
                admin.on("pageerror", lambda error: browser_events.append({"page": "admin", "type": "pageerror", "text": str(error)}))
                token = os.environ.get("GOLIVE_TOKEN", "")
                if token:
                    admin.add_init_script("sessionStorage.setItem('golive_admin_token', " + json.dumps(token) + ");")
                admin.goto(f"http://127.0.0.1:{port}/admin", wait_until="networkidle")
                admin.locator("#nav-databackend").click()
                admin.wait_for_function("backend => document.querySelector('#db-new-type').value === backend && document.querySelector('#db-type').textContent === backend", arg=cfg.data.backend)
                expected = {"mysql": "MySQL", "postgres": "PostgreSQL", "sqlite": "SQLite"}[cfg.data.backend]
                require(expected in admin.locator("#db-test").inner_text(), "Connection button does not identify backend")
                probes_before = store.count("__golive_probe")
                with admin.expect_response(lambda response: response.url.endswith("/api/admin/test/data-backend")) as response:
                    admin.locator("#db-test").click()
                diagnostic = response.value.json()
                require(diagnostic.get("ok") is True and diagnostic.get("backend") == cfg.data.backend, "Admin probed a different backend or failed")
                admin.wait_for_selector("#db-test-result.ok", state="visible")
                message = admin.locator("#db-test-result").inner_text()
                require(cfg.data.backend in message and diagnostic["location"] in message, "Probe result omitted backend/target")
                require(store.count("__golive_probe") == probes_before, "Admin connection probe left rows behind")
                require(admin.locator("#db-tables").inner_text() == "1" and admin.locator("#db-models").inner_text() != "—", "Admin table/model counts missing")
                admin.locator('button[aria-label="中文"]').click()
                admin.wait_for_function("expected => document.querySelector('#db-test').textContent === '测试 ' + expected", arg=expected)
                require(admin.locator("#db-new-type").input_value() == cfg.data.backend, "Language switch reset test backend")
                admin.screenshot(path=str(report_dir / "admin.png"), full_page=True)
                (report_dir / "admin.png").chmod(0o600)
                save("admin-probe.json", diagnostic)
                admin.close()
                record(current, detail="Current backend selected; target-labelled button/result, model/table counts and probe rollback verified")
                current = "restart_persistence"
                old_pid = process.pid
                stop()
                health = start()
                require(health["pid"] != old_pid, "Server process did not change")
                page.reload(wait_until="networkidle")
                persisted = page.evaluate("id => TemplateAPI.get(id)", first)
                require(content_of(persisted) == {"upserted": True} and persisted["sortIndex"] == 100, "Restart lost content or sorting")
                require(page.evaluate("() => TemplateAPI.listAll({pageSize:10})")["total"] == 3, "Restart lost rows")
                record(current, detail=f"New server PID {health['pid']}; content, order and row count preserved")
                current = "browser_delete"
                for ident in (first, second, third):
                    page.evaluate("id => TemplateAPI.delete(id)", ident)
                    require(page.evaluate("id => TemplateAPI.get(id)", ident) is None, "Deleted row still readable")
                require(page.evaluate("() => TemplateAPI.listAll({})")["total"] == 0, "Browser delete left rows")
                require(not any(e["type"] in ("error", "pageerror") for e in browser_events), "Browser logged errors; see browser.log.json")
                record(current)
                page.screenshot(path=str(report_dir / "browser.png"), full_page=True)
                (report_dir / "browser.png").chmod(0o600)
            finally:
                browser.close()
    except Exception as error:
        record(current, "failed", str(error))
    finally:
        cleanup_errors = []
        try:
            stop()
        except Exception:
            cleanup_errors.append("Temporary server stop failed")
        if server_log:
            server_log.close()
            save("server.log", (report_dir / "server.log").read_text())
        if not getattr(args, "keep", False):
            try:
                if store:
                    while True:
                        rows = store.list(model, page_size=100)["list"]
                        if not rows:
                            break
                        for row in rows:
                            require(store.delete(row["id"]), "Test row cleanup was not confirmed")
                if registry and not site:
                    site = registry.get_by_slug(slug)
                if site:
                    storage.delete(site["site_id"])
                    registry.delete(site["site_id"])
            except Exception:
                cleanup_errors.append("Remove remaining test data/site in namespace " + model)
        record("cleanup", "failed" if cleanup_errors else "passed", "; ".join(cleanup_errors) or ("Test site retained; temporary server stopped" if getattr(args, "keep", False) else "Test data/site removed; temporary server stopped"))
        completed = {r["step"] for r in results}
        for step in COVERAGE:
            if step not in completed:
                record(step, "skipped", "Not reached after an earlier failure")
        results.sort(key=lambda item: COVERAGE.index(item["step"]))
        save("browser.log.json", browser_events)
        save("cli.log.json", cli_log)
        ok = all(r["status"] == "passed" for r in results)
        from golive import __version__
        report = {"ok": ok, "mode": "full", "golive_version": __version__,
                  "browser_channel": getattr(args, "browser_channel", "chromium"),
                  "site_id": site["site_id"] if site else None, "backend": data_backend_info(cfg), "model": model,
                  "steps": results, "report_dir": str(report_dir), "remote_tls_verified": False,
                  "summary": "Full acceptance passed" if ok else "Full acceptance incomplete or failed"}
        save("report.json", report)
        save("report.md", "# Full acceptance\n\n" + report["summary"] + "\n\n" + "\n".join(f"- {r['step']}: {r['status']} {r['detail']}" for r in results) + "\n")
    if getattr(args, "json", False):
        print(json.dumps(scrub(report), ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['status']}: {result['step']} {result['detail']}")
        print("Report: " + str(report_dir / "report.json"))
    return 0 if ok else 1
