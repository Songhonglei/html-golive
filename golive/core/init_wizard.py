"""golive.core.init_wizard — ``golive init``: pip install to live page.

Before this existed, getting from ``pip install html-golive`` to a page
you could actually open meant six steps scattered across the docs:
pick a data directory, make sure the CLI and the server agree on it,
install the agent skill into the *right* folder, initialise the data
layer, publish something, start the server, then figure out whether the
data layer really works. A first-time user reported losing a long
evening to exactly that sequence.

``golive init`` runs all of it in order, verifies the result over real
HTTP, and prints three URLs.

Design rules:
  * idempotent — re-running never duplicates sites or wipes user data
  * non-interactive-safe — every prompt has a default; CI never blocks
  * no tracebacks — each step reports "what failed / how to fix it"
  * honest — the success banner is only printed after an HTTP round-trip

Public API:
  run(opts) -> (exit_code, [StepResult, ...])
  InitOptions — the knobs the CLI exposes
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import List, Optional

MIN_PYTHON = (3, 9)
DEFAULT_PORT = 8787


class InitOptions:
    """Everything ``golive init`` can be told to do."""

    __slots__ = ("home", "port", "host", "skip_skill", "no_serve", "background",
                 "skill_target", "interactive", "stream")

    def __init__(self, home: str = "", port: int = DEFAULT_PORT,
                 host: str = "127.0.0.1", skip_skill: bool = False,
                 no_serve: bool = False, background: bool = False,
                 skill_target: str = "",
                 interactive: Optional[bool] = None, stream=None):
        self.home = home
        self.port = port
        self.host = host
        self.skip_skill = skip_skill
        self.no_serve = no_serve
        self.background = background
        self.skill_target = skill_target
        self.interactive = interactive
        self.stream = stream


class StepResult:
    """Outcome of one wizard step."""

    __slots__ = ("name", "ok", "detail", "hint", "skipped")

    def __init__(self, name: str, ok: bool, detail: str = "",
                 hint: str = "", skipped: bool = False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.hint = hint
        self.skipped = skipped

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "hint": self.hint, "skipped": self.skipped}

    def __repr__(self):  # pragma: no cover — debugging aid
        return f"<Step {self.name} ok={self.ok} skipped={self.skipped}>"


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        return s.connect_ex((probe_host, port)) != 0


def _golive_already_serving(port: int) -> dict:
    """When the port is busy, find out whether it is *our* server."""
    import json
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return payload
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return {}


# ── steps ────────────────────────────────────────────────────────────────────

def _step_home(opts: InitOptions, out) -> StepResult:
    """Resolve, create and (when asked) persist the data directory."""
    from golive.core import paths

    if opts.home:
        home = Path(opts.home).expanduser()
    else:
        home, _src = paths.resolve_home()

    existed = home.is_dir()
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return StepResult(
            "数据目录", False, f"{home}：{e}",
            "换一个可写路径：golive init --home ~/golive-data")

    # writability probe — mkdir succeeding does not imply we can write files
    probe = home / ".golive_init_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return StepResult(
            "数据目录", False, f"{home} 不可写：{e}",
            "换一个可写路径：golive init --home ~/golive-data")

    # Persist + export so the config loader, the server and every later
    # CLI run in any shell resolve the same home. This is the whole fix
    # for "golive list shows nothing but publish said it worked".
    note = ""
    if opts.home:
        os.environ["GOLIVE_HOME"] = str(home)
        paths.reset_cache()
        try:
            pointer = paths.write_home_pointer(home)
            note = f"，已记录到 {pointer}"
        except OSError as e:
            note = f"（无法写入指针文件：{e}，仅本次生效）"
    detail = f"{home}（{'已存在，复用' if existed else '新建'}{note}）"
    if os.environ.get("GOLIVE_HOME", "").strip() and not opts.home:
        detail += "  ← 来自 $GOLIVE_HOME"
    return StepResult("数据目录", True, detail)


def _step_env(opts: InitOptions, out) -> StepResult:
    """Python version + port availability."""
    problems, notes = [], []
    if sys.version_info[:2] < MIN_PYTHON:
        problems.append(
            f"Python {'.'.join(map(str, sys.version_info[:3]))} 过旧"
            f"（需要 ≥ {'.'.join(map(str, MIN_PYTHON))}）")
    else:
        notes.append(f"Python {'.'.join(map(str, sys.version_info[:3]))}")

    if _port_free(opts.host, opts.port):
        notes.append(f"端口 {opts.port} 空闲")
    else:
        running = _golive_already_serving(opts.port)
        if running:
            notes.append(f"端口 {opts.port} 上已有 golive "
                         f"v{running.get('version', '?')} 在跑（复用）")
        else:
            problems.append(f"端口 {opts.port} 被别的程序占用")

    if problems:
        return StepResult("环境自检", False, "；".join(problems),
                          f"换端口：golive init --port {opts.port + 1}")
    return StepResult("环境自检", True, "；".join(notes))


def _step_skill(opts: InitOptions, out) -> StepResult:
    """Detect the agent actually installed here and drop the skill in it."""
    if opts.skip_skill:
        return StepResult("agent skill", True, "已跳过（--skip-skill）",
                          skipped=True)
    from golive.core import skill_installer as si
    try:
        already = si.find_installed()
        packaged = si.read_skill_meta(si.packaged_skill_dir()).get("version", "")
        fresh = [i for i in already if i["version"] == packaged]
        if fresh:
            return StepResult(
                "agent skill", True,
                f"已安装且为最新（v{packaged}）：{fresh[0]['path']}")
        res = si.install(target=opts.skill_target or None,
                         force=bool(already),
                         interactive=opts.interactive)
        note = "（已覆盖旧版本）" if res["backup"] else ""
        return StepResult("agent skill", True,
                          f"{res['installed_to']} v{res['version']}{note}")
    except si.SkillInstallError as e:
        return StepResult(
            "agent skill", False, str(e),
            "指定目录重试：golive skill install --target <DIR>"
            "；或先跳过：golive init --skip-skill")


def _step_data(opts: InitOptions, out) -> StepResult:
    """Create registry.db + data.db so nothing is lazily created later."""
    try:
        from golive.backends.factory import get_registry, get_template_store
        from golive.config import get_config
        cfg = get_config()
        get_registry()
        store = get_template_store()
        if store is None:
            return StepResult(
                "数据层", True,
                f"data.backend = {cfg.data.backend}（数据层已关闭）")
        where = getattr(store, "db_path", cfg.data.backend)
        return StepResult("数据层", True,
                          f"{cfg.data.backend} → {where}（表 "
                          f"{getattr(store, 'table', '?')} 就绪）")
    except Exception as e:  # noqa: BLE001 — any backend failure lands here
        return StepResult(
            "数据层", False, str(e),
            "检查 golive.yaml 里的 data / registry 段，"
            "或删掉配置文件回到零配置默认值（sqlite）")


def _step_demos(opts: InitOptions, out) -> StepResult:
    try:
        from golive.core import demo
        res = demo.install()
        bits = [f"{d['slug']}（{'新建' if d['action'] == 'created' else '刷新'}）"
                for d in res["demos"]]
        return StepResult("示例页", True, "；".join(bits))
    except Exception as e:  # noqa: BLE001
        from golive.core.demo import DemoError
        hint = ("重装 html-golive 以补齐包内资源"
                if isinstance(e, DemoError)
                else "看看 golive doctor 有没有报别的问题")
        return StepResult("示例页", False, str(e), hint)


def _start_server(opts: InitOptions):
    """Background server for the health check. Returns (srv, thread) or None."""
    import threading

    from golive.server.app import make_server
    srv = make_server(host=opts.host, port=opts.port)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t


def _step_verify(opts: InitOptions, out, port: int) -> StepResult:
    from golive.core import demo
    checks = demo.health_check(port=port)
    failed = [k for k, v in checks.items() if not v["ok"]]
    detail = "；".join(f"{k} {'✅' if v['ok'] else '❌'} {v['detail']}"
                       for k, v in checks.items())
    if failed:
        return StepResult(
            "健康校验", False, detail,
            "服务起来了但这几项没过：" + ", ".join(failed) +
            "。先看 golive context 确认 CLI 和服务端指向同一个 GOLIVE_HOME。")
    return StepResult("健康校验", True, detail)


# ── driver ───────────────────────────────────────────────────────────────────

def run(opts: Optional[InitOptions] = None) -> tuple:
    """Run the wizard. Returns ``(exit_code, [StepResult, ...])``.

    The server is left running (blocking) unless ``no_serve`` is set, in
    which case it is started only long enough to prove the setup works
    and then shut down again — verifying and then telling the user to
    start it themselves.
    """
    opts = opts or InitOptions()
    out = opts.stream or sys.stdout
    steps: List[StepResult] = []

    def emit(step: StepResult):
        steps.append(step)
        icon = "⏭️ " if step.skipped else ("✅" if step.ok else "❌")
        print(f"  {icon} {step.name}：{step.detail}", file=out)
        if not step.ok and step.hint:
            print(f"       ↳ 怎么修：{step.hint}", file=out)

    print("🚀 golive init — 从零到能打开的页面\n", file=out)

    emit(_step_home(opts, out))
    if not steps[-1].ok:
        return 1, steps

    # config must be (re)loaded *after* GOLIVE_HOME is settled, otherwise
    # we would read a golive.yaml from the previous home.
    try:
        from golive.config import ConfigError, load_config, set_config
        set_config(load_config())
    except ConfigError as e:
        emit(StepResult("配置文件", False, str(e),
                        "修正 golive.yaml 语法，或删掉它回到默认配置"))
        return 1, steps

    for fn in (_step_env, _step_skill, _step_data, _step_demos):
        emit(fn(opts, out))
        # a failed skill install is annoying, not fatal — keep going so the
        # user still ends up with working demo pages
        if not steps[-1].ok and steps[-1].name != "agent skill":
            return 1, steps

    # ── serve + verify ──────────────────────────────────────────────────
    reused = bool(_golive_already_serving(opts.port))
    srv = None
    if not reused:
        try:
            srv, _t = _start_server(opts)
        except OSError as e:
            emit(StepResult("启动服务", False, f"端口 {opts.port}：{e}",
                            f"换端口：golive init --port {opts.port + 1}"))
            return 1, steps
        emit(StepResult("启动服务", True,
                        f"http://{opts.host}:{opts.port}/"))
    else:
        emit(StepResult("启动服务", True,
                        f"端口 {opts.port} 上已有 golive 在跑，直接复用"))

    try:
        emit(_step_verify(opts, out, opts.port))
        verified = steps[-1].ok
        _print_entrypoints(opts, out, verified)

        if opts.no_serve:
            print("\n（--no-serve：校验完成，服务已停止。"
                  f"需要时运行：golive serve --port {opts.port}）", file=out)
            return (0 if verified else 1), steps

        if reused:
            print("\n（服务由另一个进程提供，本命令不接管它。）", file=out)
            return (0 if verified else 1), steps

        if opts.background:
            # Hand the port over to a detached server so the user can close
            # this terminal and still have the pages up.
            srv.shutdown()
            srv.server_close()
            srv = None
            from golive.core import service
            try:
                info = service.start(port=opts.port, host=opts.host)
                print(f"\n（服务已转入后台，pid {info.get('pid')}。"
                      f"管理：golive serve status / logs / stop）", file=out)
            except Exception as e:
                print(f"\n⚠️  转入后台失败：{e}", file=out)
                print(f"   页面暂时不可访问，请手动运行："
                      f"golive serve start --port {opts.port}", file=out)
                return 1, steps
            return (0 if verified else 1), steps

        print("\n   Ctrl+C 停止服务"
              f"（想关掉终端也保持在线：golive init --background，"
              f"或 golive serve start --port {opts.port}）", file=out)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 已停止", file=out)
        return (0 if verified else 1), steps
    finally:
        if srv is not None:
            srv.shutdown()
            srv.server_close()


def _print_entrypoints(opts: InitOptions, out, verified: bool) -> None:
    from golive.core import demo
    u = demo.urls(port=opts.port)
    print("", file=out)
    if verified:
        print("🎉 一切就绪，打开看看：", file=out)
    else:
        print("⚠️  部分校验未通过，但下面的地址可以先试试：", file=out)
    print(f"   静态示例：{u['demo-static']}", file=out)
    print(f"   CRUD示例：{u['demo-crud']}", file=out)
    print(f"   管理后台：{u['admin']}", file=out)
