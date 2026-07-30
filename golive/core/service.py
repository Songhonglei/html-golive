"""golive.core.service — background lifecycle for ``golive serve``.

``golive serve`` (no sub-action) keeps running in the foreground exactly as
it always has. This module backs the sub-actions added in v0.7.1::

    golive serve start [--port N] [--host H]
    golive serve status
    golive serve stop
    golive serve restart
    golive serve logs [-n 50] [-f]

State lives inside ``GOLIVE_HOME``:

    golive.pid        JSON: {pid, host, port, version, started_at}
    logs/serve.log    stdout+stderr of the background server

Design notes
------------
* **Standard library only** (``subprocess`` / ``signal`` / ``os`` /
  ``urllib``) — no new dependency for something this basic.
* **A stale pidfile never blocks a start.** If the recorded pid is gone the
  file is removed and the start proceeds; a pidfile is a hint, not a lock.
* **Port conflicts are explained, not just reported.** We probe ``/health``
  to tell "our own server is already up" apart from "something else owns
  this port".
* **The child is detached** (``start_new_session=True``) so closing the
  terminal does not take the server with it.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PORT = 8787
PIDFILE_NAME = "golive.pid"
LOG_NAME = "serve.log"

# how long to wait for the child to answer /health after spawning
START_TIMEOUT = 15.0
# how long a SIGTERM'd process gets before SIGKILL
STOP_TIMEOUT = 10.0


# ── paths ───────────────────────────────────────────────────────────────────

def pidfile_path() -> Path:
    from golive.core.paths import get_home
    return get_home() / PIDFILE_NAME


def log_path() -> Path:
    from golive.core.paths import get_log_dir
    return get_log_dir() / LOG_NAME


# ── pidfile ─────────────────────────────────────────────────────────────────

def read_pidfile() -> Optional[Dict[str, Any]]:
    """Parse the pidfile, or ``None`` when absent/corrupt."""
    p = pidfile_path()
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    if isinstance(data, (int, str)):
        # tolerate a bare "12345" written by hand or by an older version
        try:
            return {"pid": int(str(data).strip())}
        except ValueError:
            return None
    if not isinstance(data, dict) or not data.get("pid"):
        return None
    try:
        data["pid"] = int(data["pid"])
    except (TypeError, ValueError):
        return None
    return data


def write_pidfile(pid: int, host: str, port: int,
                  version: str = "") -> Path:
    p = pidfile_path()
    payload = {
        "pid": int(pid),
        "host": host,
        "port": int(port),
        "version": version,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def clear_pidfile() -> None:
    try:
        pidfile_path().unlink()
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """True when a process with this pid exists and is not a dead child.

    ``os.kill(pid, 0)`` alone is not enough: when *we* spawned the process
    and it has exited but not been reaped, it lingers as a zombie and still
    accepts signal 0. Reap it first (only possible for our own children,
    ``ChildProcessError`` otherwise) so callers see the truth.
    """
    if not pid or pid <= 0:
        return False
    if hasattr(os, "waitpid"):
        try:
            reaped, _status = os.waitpid(pid, os.WNOHANG)
            if reaped == pid:
                return False      # our child, exited and now reaped
        except (ChildProcessError, OSError):
            pass                  # not our child — fall through to kill(0)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True               # exists, owned by someone else
    except OSError:
        return False
    return True


# ── health probe ────────────────────────────────────────────────────────────

def _probe_host(host: str) -> str:
    """A bind address is not always a connectable address."""
    if host in ("0.0.0.0", "", "*"):
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def probe_health(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    """GET /health. Returns the decoded dict, or ``None`` if unreachable.

    Shape is whatever the server sends — v0.7.0 answers ``{"status":"ok"}``
    and newer servers add ``version`` / ``home`` / ``data_backend`` / ``pid``.
    Callers must treat every field beyond ``status`` as optional.
    """
    url = "http://{}:{}/health".format(_probe_host(host), port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def port_in_use(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((_probe_host(host), port)) == 0


def describe_port(host: str, port: int) -> Tuple[str, Optional[Dict]]:
    """Who owns this port? -> ("free" | "golive" | "other", health_or_None)."""
    if not port_in_use(host, port):
        return "free", None
    health = probe_health(host, port)
    if health is not None and "status" in health:
        return "golive", health
    return "other", None


# ── status ──────────────────────────────────────────────────────────────────

def recorded_port() -> Optional[int]:
    """Port of the managed server as recorded in the pidfile.

    Returns ``None`` when there is no pidfile, no port in it, or the
    recorded process is gone — callers should then fall back to their
    own default rather than probing a port nobody is listening on.
    """
    data = read_pidfile()
    if not data:
        return None
    port = data.get("port")
    if not port:
        return None
    pid = data.get("pid")
    if pid and not pid_alive(int(pid)):
        return None
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def status(port: Optional[int] = None,
           host: Optional[str] = None) -> Dict[str, Any]:
    """Everything a caller needs to describe the background service.

    Keys: running, managed, pid, host, port, version, health, stale_pidfile,
    started_at, log, pidfile, port_owner.
    """
    import golive
    cli_version = golive.__version__

    rec = read_pidfile()
    stale = False
    rec_pid = rec_host = rec_port = None
    if rec:
        rec_pid = rec.get("pid")
        rec_host = rec.get("host")
        rec_port = rec.get("port")
        if not pid_alive(int(rec_pid)):
            stale = True

    probe_p = port or rec_port or DEFAULT_PORT
    probe_h = host or rec_host or "127.0.0.1"
    owner, health = describe_port(probe_h, probe_p)

    running = owner == "golive"
    managed = bool(rec) and not stale and running

    svc_version = ""
    if health:
        svc_version = str(health.get("version") or "")
    svc_pid = None
    if health and health.get("pid"):
        try:
            svc_pid = int(health["pid"])
        except (TypeError, ValueError):
            svc_pid = None
    if svc_pid is None and not stale and rec_pid:
        svc_pid = int(rec_pid)

    return {
        "running": running,
        "managed": managed,
        "pid": svc_pid,
        "host": probe_h,
        "port": probe_p,
        "version": svc_version,
        "cli_version": cli_version,
        "version_match": (not svc_version) or svc_version == cli_version,
        "health": health,
        "stale_pidfile": stale,
        "started_at": (rec or {}).get("started_at", ""),
        "pidfile": str(pidfile_path()),
        "log": str(log_path()),
        "port_owner": owner,
    }


# ── start / stop / restart ──────────────────────────────────────────────────

def _spawn(host: str, port: int, config_path: str = "") -> subprocess.Popen:
    from golive.core.paths import get_home

    cmd = [sys.executable, "-m", "golive.cli"]
    if config_path:
        cmd += ["--config", config_path]
    cmd += ["serve", "--port", str(port), "--host", host]

    env = dict(os.environ)
    env["GOLIVE_HOME"] = str(get_home())      # pin: child must not re-resolve
    env.setdefault("PYTHONUNBUFFERED", "1")

    lf = log_path()
    lf.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lf, "a", encoding="utf-8")  # noqa: SIM115 — child owns it
    handle.write("\n===== {} · golive serve --host {} --port {} =====\n"
                 .format(time.strftime("%Y-%m-%d %H:%M:%S"), host, port))
    handle.flush()

    kwargs: Dict[str, Any] = dict(
        stdout=handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, cwd=str(Path.cwd()), env=env,
    )
    if hasattr(os, "setsid"):
        kwargs["start_new_session"] = True    # survive terminal close
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    finally:
        handle.close()                        # parent's copy; child keeps its own
    return proc


def start(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          config_path: str = "",
          timeout: float = START_TIMEOUT) -> Dict[str, Any]:
    """Start the server in the background (idempotent).

    Returns ``{ok, state, message, pid, port, host, log}`` where ``state`` is
    one of ``started`` | ``already-running`` | ``port-taken`` | ``failed``.
    """
    rec = read_pidfile()
    if rec and not pid_alive(int(rec["pid"])):
        clear_pidfile()
        rec = None

    # already ours and healthy? don't start a second one.
    existing_port = port
    owner, health = describe_port(host, existing_port)
    if owner == "golive":
        pid = None
        if health and health.get("pid"):
            try:
                pid = int(health["pid"])
            except (TypeError, ValueError):
                pid = None
        if pid is None and rec and int(rec.get("port", -1)) == existing_port:
            pid = int(rec["pid"])
        return {
            "ok": True, "state": "already-running", "pid": pid,
            "host": host, "port": existing_port, "log": str(log_path()),
            "message": "golive is already serving on port {}{}."
                       .format(existing_port,
                               " (pid {})".format(pid) if pid else ""),
        }
    if owner == "other":
        return {
            "ok": False, "state": "port-taken", "pid": None,
            "host": host, "port": existing_port, "log": str(log_path()),
            "message": "port {} is held by another program (it does not "
                       "answer golive's /health). Pick a different port "
                       "with --port, or free that one."
                       .format(existing_port),
        }

    proc = _spawn(host, port, config_path=config_path)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:           # died on startup
            return {
                "ok": False, "state": "failed", "pid": None,
                "host": host, "port": port, "log": str(log_path()),
                "message": "the server exited immediately (code {}). "
                           "See {}".format(proc.returncode, log_path()),
            }
        health = probe_health(host, port, timeout=1.0)
        if health is not None:
            write_pidfile(proc.pid, host, port,
                          version=str(health.get("version") or ""))
            return {
                "ok": True, "state": "started", "pid": proc.pid,
                "host": host, "port": port, "log": str(log_path()),
                "message": "started on http://{}:{}/ (pid {})"
                           .format(_probe_host(host), port, proc.pid),
            }
        time.sleep(0.2)

    # never answered — leave the process alone but tell the truth
    return {
        "ok": False, "state": "failed", "pid": proc.pid,
        "host": host, "port": port, "log": str(log_path()),
        "message": "started pid {} but /health did not answer within {:.0f}s. "
                   "See {}".format(proc.pid, timeout, log_path()),
    }


def stop(timeout: float = STOP_TIMEOUT) -> Dict[str, Any]:
    """Stop the background server. SIGTERM, then SIGKILL after ``timeout``.

    ``state``: ``stopped`` | ``killed`` | ``not-running`` | ``stale-cleaned``
    | ``unmanaged`` | ``failed``.
    """
    rec = read_pidfile()
    if not rec:
        st = status()
        if st["running"]:
            return {
                "ok": False, "state": "unmanaged", "pid": st["pid"],
                "message": "a golive server answers on port {} but there is "
                           "no pidfile — it was probably started in the "
                           "foreground. Stop it with Ctrl+C in its terminal"
                           "{}.".format(
                               st["port"],
                               ", or kill pid {}".format(st["pid"])
                               if st["pid"] else ""),
            }
        return {"ok": True, "state": "not-running", "pid": None,
                "message": "no background server is running."}

    pid = int(rec["pid"])
    if not pid_alive(pid):
        clear_pidfile()
        return {"ok": True, "state": "stale-cleaned", "pid": pid,
                "message": "pid {} is gone; removed the stale pidfile."
                           .format(pid)}

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        return {"ok": False, "state": "failed", "pid": pid,
                "message": "could not signal pid {}: {}".format(pid, e)}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            clear_pidfile()
            return {"ok": True, "state": "stopped", "pid": pid,
                    "message": "stopped pid {}.".format(pid)}
        time.sleep(0.15)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(20):
        if not pid_alive(pid):
            break
        time.sleep(0.1)
    clear_pidfile()
    if pid_alive(pid):
        return {"ok": False, "state": "failed", "pid": pid,
                "message": "pid {} survived SIGKILL — check it by hand."
                           .format(pid)}
    return {"ok": True, "state": "killed", "pid": pid,
            "message": "pid {} did not stop within {:.0f}s; sent SIGKILL."
                       .format(pid, timeout)}


def restart(host: Optional[str] = None, port: Optional[int] = None,
            config_path: str = "") -> Dict[str, Any]:
    """Stop (if running) then start, reusing the recorded host/port."""
    rec = read_pidfile() or {}
    use_host = host or rec.get("host") or "127.0.0.1"
    use_port = int(port or rec.get("port") or DEFAULT_PORT)

    stop_res = stop()
    if stop_res["state"] == "unmanaged":
        return {"ok": False, "state": "unmanaged", "pid": stop_res["pid"],
                "host": use_host, "port": use_port, "log": str(log_path()),
                "message": stop_res["message"], "stop": stop_res}

    # the OS may hold the listening socket for a moment after exit
    deadline = time.time() + 5.0
    while time.time() < deadline and port_in_use(use_host, use_port):
        time.sleep(0.15)

    start_res = start(host=use_host, port=use_port, config_path=config_path)
    start_res["stop"] = stop_res
    return start_res


# ── logs ────────────────────────────────────────────────────────────────────

def tail(lines: int = 50) -> List[str]:
    """Last ``lines`` lines of the serve log (empty list when absent)."""
    p = log_path()
    if not p.is_file():
        return []
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n") for ln in fh.readlines()[-max(1, lines):]]
    except OSError:
        return []


def follow(lines: int = 50, poll: float = 0.4, out=None) -> int:
    """Print the tail then stream new lines until Ctrl+C. Returns 0."""
    out = out or sys.stdout
    p = log_path()
    for ln in tail(lines):
        print(ln, file=out)
    if not p.is_file():
        print("(no log yet at {})".format(p), file=out)
        return 0
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while True:
                chunk = fh.readline()
                if chunk:
                    print(chunk.rstrip("\n"), file=out)
                    continue
                time.sleep(poll)
    except KeyboardInterrupt:
        print("", file=out)
    return 0
