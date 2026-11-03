#!/usr/bin/env python3
"""Own-directory MySQL 8.4 sandbox. No global installs or service changes.

start prints only the protected environment-file path. Source that file in
one shell; stop preserves data, cleanup removes only this sandbox directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time

MARKER = "opengolive-mysql-sandbox-v1"
_log_root = None
_secrets = []


def log_failure(command, output):
    if _log_root is None or not _log_root.exists():
        return
    value = output.decode(errors="replace") if isinstance(output, bytes) else (output or "")
    for secret in _secrets:
        value = value.replace(secret, "[redacted]")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(_log_root / "commands.log"), flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(Path(command[0]).name + ": " + value + "\n")


def run(command, **kwargs):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=120, **kwargs)
    except subprocess.TimeoutExpired as error:
        log_failure(command, error.stderr)
        raise RuntimeError("Sandbox command timed out: " + Path(command[0]).name + ". Check image/network/daemon; owned resources were preserved for cleanup.") from None
    if result.returncode:
        log_failure(command, result.stdout + result.stderr)
        raise RuntimeError("Sandbox command failed: " + Path(command[0]).name + ". Inspect the private sandbox logs.")
    return result.stdout


def save(path, content):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)


def load(root):
    if root.is_symlink():
        raise RuntimeError("Sandbox directory must not be a symlink")
    state = json.loads((root / "sandbox.json").read_text())
    if state.get("marker") != MARKER or Path(state.get("directory", "")).resolve() != root.resolve():
        raise RuntimeError("Directory is not an owned MySQL sandbox")
    return state


def docker_identity(root, state):
    """An immutable container ID and private ownership labels precede control."""
    import re
    if not re.fullmatch(r"golive-mysql-[0-9a-f]{12}", state.get("container", "")):
        raise RuntimeError("Invalid sandbox container record; preserving resources")
    target = state.get("container_id") or state["container"]
    if state.get("container_id") and not re.fullmatch(r"[0-9a-f]{64}", target):
        raise RuntimeError("Invalid sandbox container ID; preserving resources")
    template = '{{.Id}}\n{{.State.Running}}\n{{index .Config.Labels "io.opengolive.sandbox"}}\n{{index .Config.Labels "io.opengolive.directory"}}'
    result = subprocess.run(["docker", "inspect", "--format", template, target],
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        if "no such object" in result.stderr.lower() or "no such container" in result.stderr.lower():
            return None
        raise RuntimeError("Cannot inspect sandbox container; preserving resources")
    fields = result.stdout.strip().splitlines()
    if (len(fields) != 4 or not state.get("sandbox_id")
            or fields[2] != state["sandbox_id"] or fields[3] != str(root.resolve())
            or (state.get("container_id") and fields[0] != state["container_id"])):
        raise RuntimeError("Container identity mismatch; preserving resources")
    return {"id": fields[0], "running": fields[1] == "true"}


def client(root, state, sql):
    if state["engine"] == "docker":
        owned = docker_identity(root, state)
        if not owned or not owned["running"]:
            raise RuntimeError("Owned MySQL container is not running")
        command = ["docker", "exec", "--user", "0", "-i", owned["id"], "mysql", "--defaults-extra-file=/run/golive-root.cnf", "--batch", "--skip-column-names"]
    else:
        command = ["mysql", "--defaults-extra-file=" + str(root / "root.cnf"), "--batch", "--skip-column-names"]
    return run(command, input=sql)


def stop(root, state):
    if state["engine"] == "docker":
        owned = docker_identity(root, state)
        if owned and owned["running"]:
            run(["docker", "stop", owned["id"]])
    else:
        # Authenticate over this sandbox's unique Unix socket, never kill a PID.
        sock = root / "mysql.sock"
        if sock.exists():
            client(root, state, "SHUTDOWN;")
            deadline = time.monotonic() + 20
            while sock.exists() and time.monotonic() < deadline:
                time.sleep(.2)
            if sock.exists():
                raise RuntimeError("Sandbox has not stopped; preserving directory")


def start(args, root):
    if root.exists():
        raise RuntimeError("Choose a NEW dedicated directory; existing directories are never reused")
    if not 1 <= args.port <= 65535 or not 1 <= args.server_port <= 65535 or args.port == args.server_port:
        raise RuntimeError("Choose different valid database and service ports")
    for port in (args.port, args.server_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    engine = args.engine
    if engine == "auto":
        engine = "docker" if shutil.which("docker") else "native"
    required = ("docker",) if engine == "docker" else ("mysql", "mysqld")
    if any(not shutil.which(tool) for tool in required):
        raise RuntimeError("Missing " + "/".join(required) + ". Install MySQL 8.4+ or Docker, or use a dedicated remote DSN. No installation was attempted.")
    if engine == "docker":
        run(["docker", "info"])
    else:
        import re
        version = re.search(r"Ver (\d+)\.(\d+)", run(["mysqld", "--version"]))
        if not version or tuple(map(int, version.groups())) < (8, 4):
            raise RuntimeError("MySQL 8.4+ is required")
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    password, root_password = secrets.token_hex(24), secrets.token_hex(24)
    _secrets.extend([password, root_password])
    state = {"marker": MARKER, "directory": str(root), "engine": engine,
             "port": args.port, "container": "golive-mysql-" + secrets.token_hex(6),
             "sandbox_id": secrets.token_hex(16)}
    save(root / "sandbox.json", json.dumps(state))
    socket_path = str(root / "mysql.sock")
    config = "[client]\nuser=root\npassword=" + root_password + "\n"
    if engine == "native":
        config += "protocol=socket\nsocket=" + socket_path + "\n"
    save(root / "root.cnf", config)
    if engine == "native":
        # Unix sockets have a platform length limit; reject before launching.
        if len(socket_path.encode()) > 100:
            raise RuntimeError("Use a shorter sandbox directory (Unix socket path limit)")
        run(["mysqld", "--no-defaults", "--initialize-insecure", "--datadir=" + str(root / "data"), "--log-error=" + str(root / "mysql.log")])
        with (root / "launcher.log").open("w") as log:
            subprocess.Popen(["mysqld", "--no-defaults", "--datadir=" + str(root / "data"),
                              "--bind-address=127.0.0.1", "--port=" + str(args.port), "--mysqlx=OFF",
                              "--socket=" + socket_path, "--pid-file=" + str(root / "mysql.pid"),
                              "--log-error=" + str(root / "mysql.log")], stdout=log, stderr=log, start_new_session=True)
    else:
        save(root / "docker.env", "MYSQL_ROOT_PASSWORD=" + root_password + "\n")
        container_id = run(["docker", "run", "-d", "--name", state["container"],
             "--label", "io.opengolive.sandbox=" + state["sandbox_id"],
             "--label", "io.opengolive.directory=" + str(root.resolve()),
             "--env-file", str(root / "docker.env"), "-p", f"127.0.0.1:{args.port}:3306",
             "--mount", f"type=bind,src={root / 'root.cnf'},dst=/run/golive-root.cnf,readonly",
             # The image's private anonymous /var/lib/mysql volume is owned by
             # mysql. A bind under our host 0700 directory is inaccessible to
             # that UID on Linux; never relax the credential directory instead.
             args.image, "--mysqlx=OFF"]).strip()
        state["container_id"] = container_id
        temporary = root / ("sandbox-" + secrets.token_hex(6) + ".json")
        save(temporary, json.dumps(state))
        os.replace(temporary, root / "sandbox.json")
    deadline = time.monotonic() + 90
    while True:
        try:
            if engine == "native":
                # Initial account has no password; input never appears in argv/log output.
                run(["mysql", "--no-defaults", "--protocol=socket", "--socket=" + socket_path, "-u", "root"],
                    input="ALTER USER 'root'@'localhost' IDENTIFIED BY '" + root_password + "';")
            client(root, state, "SELECT 1;")
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise RuntimeError("MySQL readiness timed out; use stop/cleanup with the same directory") from None
            time.sleep(.5)
    client(root, state, "CREATE DATABASE golive_acceptance CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;\n"
           "CREATE USER 'golive_test'@'%' IDENTIFIED BY '" + password + "';\n"
           "GRANT ALL PRIVILEGES ON golive_acceptance.* TO 'golive_test'@'%';\n")
    home = root / "golive-home"
    home.mkdir(mode=0o700)
    save(home / "golive.yaml", "storage:\n  backend: local\nregistry:\n  backend: mysql\ndata:\n  backend: mysql\nserver:\n  host: 127.0.0.1\n  port: " + str(args.server_port) + "\n")
    env = {"GOLIVE_HOME": str(home), "GOLIVE_CONFIG": str(home / "golive.yaml"),
           "GOLIVE_MYSQL_DSN": f"mysql://golive_test:{password}@127.0.0.1:{args.port}/golive_acceptance"}
    save(root / "environment.sh", "\n".join("export " + key + "=" + shlex.quote(value) for key, value in env.items()) + "\n")
    print("Sandbox ready. Load credentials without printing them: source " + shlex.quote(str(root / "environment.sh")))
    print("Stop: " + shlex.join([sys.executable, __file__, "stop", "--directory", str(root)]))
    print("Cleanup: " + shlex.join([sys.executable, __file__, "cleanup", "--directory", str(root)]))


def main():
    global _log_root
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "cleanup"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--engine", choices=("auto", "docker", "native"), default="auto")
    parser.add_argument("--port", type=int, default=13306)
    parser.add_argument("--server-port", type=int, default=8788)
    parser.add_argument("--image", default="mysql:8.4.13")
    args = parser.parse_args()
    os.umask(0o077)
    root = args.directory.expanduser().absolute()
    _log_root = root
    try:
        if args.action == "start":
            start(args, root)
        else:
            state = load(root)
            for line in (root / "root.cnf").read_text().splitlines() if (root / "root.cnf").exists() else []:
                if line.startswith("password="):
                    _secrets.append(line.split("=", 1)[1])
            stop(root, state)
            if args.action == "cleanup":
                if state["engine"] == "docker":
                    owned = docker_identity(root, state)
                    if owned:
                        # Remove only this container's anonymous volumes, never shared volumes.
                        run(["docker", "rm", "-v", owned["id"]])
                shutil.rmtree(root)
            print("Sandbox " + args.action + " completed")
        return 0
    except Exception as error:
        # Exceptions intentionally contain no command output or passwords.
        print(str(error) if isinstance(error, RuntimeError) else "Sandbox failed; check directory, ports and private logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
