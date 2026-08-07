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

from golive.i18n import t

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
            t("init.step_home"), False, t("init.step_home_not_writable", path=home, error=e),
            t("init.step_home_hint"))

    # writability probe — mkdir succeeding does not imply we can write files
    probe = home / ".golive_init_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return StepResult(
            t("init.step_home"), False, t("init.step_home_not_writable", path=home, error=e),
            t("init.step_home_hint"))

    # Persist + export so the config loader, the server and every later
    # CLI run in any shell resolve the same home. This is the whole fix
    # for "golive list shows nothing but publish said it worked".
    note = ""
    if opts.home:
        os.environ["GOLIVE_HOME"] = str(home)
        paths.reset_cache()
        try:
            pointer = paths.write_home_pointer(home)
            note = t("init.step_home_pointer_note", pointer=pointer)
        except OSError as e:
            note = t("init.step_home_pointer_error", error=e)
    if existed:
        detail = t("init.step_home_reused", path=home, note=note)
    else:
        detail = t("init.step_home_created", path=home, note=note)
    if os.environ.get("GOLIVE_HOME", "").strip() and not opts.home:
        detail += t("init.step_home_from_env")
    return StepResult(t("init.step_home"), True, detail)


def _step_env(opts: InitOptions, out) -> StepResult:
    """Python version + port availability."""
    problems, notes = [], []
    if sys.version_info[:2] < MIN_PYTHON:
        problems.append(
            t("init.step_env_py_too_old",
              version=".".join(map(str, sys.version_info[:3])),
              min=".".join(map(str, MIN_PYTHON))))
    else:
        notes.append(f"Python {'.'.join(map(str, sys.version_info[:3]))}")

    if _port_free(opts.host, opts.port):
        notes.append(t("init.step_env_port_free", port=opts.port))
    else:
        running = _golive_already_serving(opts.port)
        if running:
            notes.append(t("init.step_env_golive_reuse",
                           port=opts.port, version=running.get('version', '?')))
        else:
            problems.append(t("init.step_env_port_taken", port=opts.port))

    if problems:
        return StepResult(t("init.step_env"), False, "；".join(problems),
                          t("init.step_env_hint", port=opts.port + 1))
    return StepResult(t("init.step_env"), True, "；".join(notes))


def _step_skill(opts: InitOptions, out) -> StepResult:
    """Detect the agent actually installed here and drop the skill in it."""
    if opts.skip_skill:
        return StepResult(t("init.step_skill"), True, t("init.step_skill_skipped"),
                          skipped=True)
    from golive.core import skill_installer as si
    try:
        already = si.find_installed()
        packaged = si.read_skill_meta(si.packaged_skill_dir()).get("version", "")
        fresh = [i for i in already if i["version"] == packaged]
        if fresh:
            return StepResult(
                t("init.step_skill"), True,
                t("init.step_skill_fresh", version=packaged, path=fresh[0]['path']))
        res = si.install(target=opts.skill_target or None,
                         force=bool(already),
                         interactive=opts.interactive)
        note = t("init.step_skill_overwritten") if res["backup"] else ""
        return StepResult(t("init.step_skill"), True,
                          t("init.step_skill_installed", path=res['installed_to'],
                            version=res['version'], note=note))
    except si.SkillInstallError as e:
        return StepResult(
            t("init.step_skill"), False, str(e),
            t("init.step_skill_hint"))


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
                t("init.step_data"), True,
                t("init.step_data_disabled", backend=cfg.data.backend))
        where = getattr(store, "db_path", cfg.data.backend)
        return StepResult(t("init.step_data"), True,
                          t("init.step_data_ready", backend=cfg.data.backend,
                            where=where, table=getattr(store, 'table', '?')))
    except Exception as e:  # noqa: BLE001 — any backend failure lands here
        return StepResult(
            t("init.step_data"), False, str(e),
            t("init.step_data_hint"))


def _step_demos(opts: InitOptions, out) -> StepResult:
    try:
        from golive.core import demo
        res = demo.install()
        bits = [f"{d['slug']}（{'created' if d['action'] == 'created' else 'updated'}）"
                for d in res["demos"]]
        return StepResult(t("init.step_demos"), True, "；".join(bits))
    except Exception as e:  # noqa: BLE001
        from golive.core.demo import DemoError
        hint = (t("init.step_demos_hint_reinstall")
                if isinstance(e, DemoError)
                else t("init.step_demos_hint_doctor"))
        return StepResult(t("init.step_demos"), False, str(e), hint)


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
            t("init.step_verify"), False, detail,
            t("init.step_verify_hint", failed=", ".join(failed)))
    return StepResult(t("init.step_verify"), True, detail)


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
            print(t("init.hint_prefix", hint=step.hint), file=out)

    print(t("init.banner"), file=out)

    emit(_step_home(opts, out))
    if not steps[-1].ok:
        return 1, steps

    # config must be (re)loaded *after* GOLIVE_HOME is settled, otherwise
    # we would read a golive.yaml from the previous home.
    try:
        from golive.config import ConfigError, load_config, set_config
        set_config(load_config())
    except ConfigError as e:
        emit(StepResult(t("init.step_config"), False, str(e),
                        t("init.step_config_hint")))
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
            emit(StepResult(t("init.step_start_server"), False,
                            t("init.step_start_server_port_err", port=opts.port, error=e),
                            t("init.step_start_server_port_hint", port=opts.port + 1)))
            return 1, steps
        emit(StepResult(t("init.step_start_server"), True,
                        t("init.step_start_server_ok", host=opts.host, port=opts.port)))
    else:
        emit(StepResult(t("init.step_start_server"), True,
                        t("init.step_start_reuse", port=opts.port)))

    try:
        emit(_step_verify(opts, out, opts.port))
        verified = steps[-1].ok
        _print_entrypoints(opts, out, verified)

        if opts.no_serve:
            print(t("init.no_serve_done", port=opts.port), file=out)
            return (0 if verified else 1), steps

        if reused:
            print(t("init.reused_server"), file=out)
            return (0 if verified else 1), steps

        if opts.background:
            srv.shutdown()
            srv.server_close()
            srv = None
            from golive.core import service
            try:
                info = service.start(port=opts.port, host=opts.host)
                print(t("init.background_ok", pid=info.get('pid')), file=out)
            except Exception as e:
                print(t("init.background_failed", error=e), file=out)
                print(t("init.background_failed_hint", port=opts.port), file=out)
                return 1, steps
            return (0 if verified else 1), steps

        print(t("init.forever_hint", port=opts.port), file=out)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print(t("init.stopped"), file=out)
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
        print(t("init.success_header"), file=out)
    else:
        print(t("init.partial_header"), file=out)
    print(t("init.static_demo", url=u['demo-static']), file=out)
    print(t("init.crud_demo", url=u['demo-crud']), file=out)
    print(t("init.admin_url", url=u['admin']), file=out)
