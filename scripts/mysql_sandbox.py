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


def run(command, **kwargs):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=120, **kwargs)
    if result.returncode:
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


def client(root, state, sql):
    if state["engine"] == "docker":
        command = ["docker", "exec", "-i", state["container"], "mysql", "--defaults-extra-file=/run/golive-root.cnf", "--batch", "--skip-column-names"]
    else:
        command = ["mysql", "--defaults-extra-file=" + str(root / "root.cnf"), "--batch", "--skip-column-names"]
    return run(command, input=sql)


def stop(root, state):
    if state["engine"] == "docker":
        run(["docker", "stop", state["container"]])
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
    state = {"marker": MARKER, "directory": str(root), "engine": engine,
             "port": args.port, "container": "golive-mysql-" + secrets.token_hex(6)}
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
        run(["docker", "run", "-d", "--name", state["container"],
             "--env-file", str(root / "docker.env"), "-p", f"127.0.0.1:{args.port}:3306",
             "--mount", f"type=bind,src={root / 'root.cnf'},dst=/run/golive-root.cnf,readonly",
             "--mount", f"type=bind,src={root},dst=/sandbox", args.image,
             "--datadir=/sandbox/data", "--mysqlx=OFF"])
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
    try:
        if args.action == "start":
            start(args, root)
        else:
            state = load(root)
            stop(root, state)
            if args.action == "cleanup":
                if state["engine"] == "docker":
                    run(["docker", "rm", state["container"]])
                shutil.rmtree(root)
            print("Sandbox " + args.action + " completed")
        return 0
    except Exception as error:
        # Exceptions intentionally contain no command output or passwords.
        print(str(error) if isinstance(error, RuntimeError) else "Sandbox failed; check directory, ports and private logs.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
