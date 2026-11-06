"""CLI JSON failures must remain parseable without echoing private inputs."""
from __future__ import annotations

import contextlib
import io
import json
import os
from urllib.parse import unquote, urlsplit


class JSONArgumentError(Exception):
    pass


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def decode_json(value):
    return json.loads(value, parse_constant=_reject_constant)


def redact_failure(value):
    names = {key for key in os.environ if any(part in key.upper() for part in ("TOKEN", "PASSWORD", "SECRET", "DSN", "_KEY", "PROXY"))}
    # Custom *_env names need the same protection as conventional env names.
    from golive.config import get_config
    cfg = get_config()
    for section in vars(cfg).values():
        if hasattr(section, "__dict__"):
            names.update(item for key, item in vars(section).items()
                         if key.endswith("_env") and isinstance(item, str))
    secrets = {os.environ.get(name, "") for name in names}
    secrets.add(cfg.auth.token)
    for secret in list(secrets):
        try:
            password = urlsplit(secret).password
            if password:
                secrets.add(unquote(password))
        except ValueError:
            pass
    secrets = sorted((s for s in secrets if isinstance(s, str) and len(s) >= 4), key=len, reverse=True)

    def scrub(item, root=False):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[redacted]")
            return item
        if isinstance(item, dict):
            return {key: (entry if root and key in ("command", "operation", "code") else scrub(entry))
                    for key, entry in item.items()}
        if isinstance(item, list):
            return [scrub(entry) for entry in item]
        return item
    return scrub(value, root=True)


def wants_json(argv):
    before_positionals = argv[:argv.index("--")] if "--" in argv else argv
    return any(arg == "--json" or arg.startswith("--json=") for arg in before_positionals)


def operation(argv, commands):
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--config":
            index += 2
            continue
        if item.startswith("--config=") or item.startswith("-"):
            index += 1
            continue
        command = item if item in commands else "cli"
        action = argv[index + 1] if index + 1 < len(argv) else ""
        if command == "data" and action in ("create", "update", "upsert", "delete", "sort", "list", "get"):
            return command, action
        return command, command
    return "cli", "cli"


def failure_code(error):
    import requests
    if isinstance(error, (TimeoutError, requests.exceptions.Timeout)):
        return "backend_timeout"
    if isinstance(error, (ConnectionError, requests.exceptions.ConnectionError)):
        return "backend_unavailable"
    if type(error).__name__ in ("IntegrityError", "UniqueViolation"):
        return "conflict"
    if type(error).__name__ in ("OperationalError", "InterfaceError") and type(error).__module__.startswith(("psycopg", "pymysql")):
        return "backend_unavailable"
    if error.args and error.args[0] in (2002, 2003, 2006, 2013):
        return "backend_unavailable"
    return "backend_error"


def emit_error(command, action, code, message, uncertain=False):
    result = {"ok": False, "command": command, "operation": action,
              "code": code, "id": None, "record": None, "error": message}
    if uncertain:
        result["write_state"] = "unknown"
    print(json.dumps(result, ensure_ascii=False))


def run_json(callback, args):
    """Only a completed JSON document reaches stdout; discard partial logs."""
    output, diagnostics = io.StringIO(), io.StringIO()
    action = getattr(args, "action", None) if args.command == "data" else args.command
    mutating = (args.command in ("import", "migrate") or
                (args.command == "data" and action in ("create", "update", "upsert", "delete", "sort")))
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            status = callback(args)
    except KeyboardInterrupt:
        emit_error(args.command, action, "interrupted", "Operation interrupted; inspect the target before retrying.", mutating)
        return 130
    except Exception as error:
        emit_error(args.command, action, failure_code(error),
                   "Operation failed; check configuration, connectivity and target state.", mutating)
        return 1
    try:
        result = decode_json(output.getvalue())
    except ValueError:
        emit_error(args.command, action, "invalid_output", "Operation did not return one complete JSON result; inspect the target before retrying.", mutating)
        return 1
    if status or (isinstance(result, dict) and result.get("ok") is False):
        try:
            safe_result = redact_failure(result)
        except Exception:
            emit_error(args.command, action, "redaction_failed", "Cannot safely report failure details; inspect target state.", mutating)
            return 1
        print(json.dumps(safe_result, ensure_ascii=False, indent=2))
    else:
        print(output.getvalue().strip())
    return int(status or 0)
