"""Read/write diagnostics for local SQLite and read-only Supabase API probes."""

from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
import uuid


def failure(code, error, hint, **extra):
    return {"ok": False, "code": code, "error": error, "hint": hint, **extra}


def check_sqlite(cfg):
    from golive.core.paths import get_data_db
    configured = cfg.data.sqlite_path
    path = ":memory:" if configured == ":memory:" else str(
        (Path(configured).expanduser() if configured else get_data_db()).resolve())
    started = time.monotonic()
    conn = None
    try:
        conn = sqlite3.connect(str(path), timeout=3)
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        check = conn.execute("PRAGMA quick_check(1)").fetchone()
        if not check or check[0] != "ok":
            return failure("sqlite_corrupt", "SQLite integrity check failed.",
                           "Back up the database and inspect or restore the local file.", location=str(path))
        # Exercise writes in the actual database, then roll back all probe data.
        conn.execute("BEGIN IMMEDIATE")
        table = "__golive_probe_" + uuid.uuid4().hex
        conn.execute(f'CREATE TABLE "{table}" (value INTEGER)')
        conn.execute(f'INSERT INTO "{table}" VALUES (1)')
        assert conn.execute(f'SELECT value FROM "{table}"').fetchone()[0] == 1
        return {"ok": True, "code": "sqlite_ok", "backend": "sqlite",
                "location": str(path), "table_count": len(tables),
                "checks": ["read", "write", "integrity"],
                "latency_ms": int((time.monotonic() - started) * 1000)}
    except (sqlite3.Error, OSError) as exc:
        error_code = (getattr(exc, "sqlite_errorcode", 0) or 0) & 255
        message = str(exc).lower()
        # Older supported Python versions do not attach SQLite error codes.
        if error_code in (5, 6) or "database is locked" in message or "database table is locked" in message:
            code, error, hint = "sqlite_locked", "SQLite is busy or locked.", "Another process may be writing. Try again after it finishes."
        elif error_code == 8 or isinstance(exc, PermissionError) or "readonly" in message:
            code, error, hint = "sqlite_readonly", "SQLite is not writable.", "Check write permissions on both the database file and its parent directory."
        elif error_code in (26, 11) or "not a database" in message or "malformed" in message:
            code, error, hint = "sqlite_corrupt", "The SQLite file is invalid or corrupt.", "Back up the file and inspect or restore the database."
        elif error_code == 14 or "unable to open database" in message:
            code, error, hint = "sqlite_open_failed", "The SQLite file cannot be opened.", "Check that the parent directory exists and the server can access it."
        else:
            code, error, hint = "sqlite_io_error", "SQLite read/write check failed.", "Check local disk space, filesystem health and database permissions."
        return failure(code, error, hint, location=str(path))
    finally:
        if conn is not None:
            try:
                conn.rollback()
            finally:
                conn.close()


def check_supabase(data, cfg):
    import requests

    url = str(data.get("url") or cfg.supabase.url or "").strip().rstrip("/")
    key = str(data.get("key") or data.get("service_key") or "").strip()
    # Never send an existing server key to a different project entered in the form.
    if not key and url == cfg.supabase.url.strip().rstrip("/"):
        key = cfg.supabase.key
    missing = ([] if url else ["url"]) + ([] if key else ["key"])
    if missing:
        return 400, failure("supabase_config_required", "Supabase connection configuration is incomplete.",
                            "Provide the project URL and an API key. No remote request was made.", fields=missing)
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in ("http", "https") and parsed.hostname
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and parsed.path in ("", "/"))
        parsed.port  # also validate a malformed port
    except ValueError:
        valid = False
    if not valid:
        return 400, failure("supabase_url_invalid", "The Supabase project URL is invalid.",
                            "Use the project root URL, without credentials, query parameters or /rest/v1.", fields=["url"])
    if "your-project" in parsed.hostname.lower() or "yourproject" in parsed.hostname.lower():
        return 400, failure("supabase_url_placeholder", "The Supabase URL is still an example placeholder.",
                            "Replace it with your actual project URL. No remote request was made.", fields=["url"])
    if any(char.isspace() for char in key):
        return 400, failure("supabase_key_invalid", "The API key contains whitespace.",
                            "Paste the complete API key without spaces or newlines.", fields=["key"])

    started = time.monotonic()
    headers = {"apikey": key, "Accept": "application/openapi+json"}
    # New publishable/secret keys are not JWT bearer tokens.
    if key.startswith("eyJ") and key.count(".") == 2:
        headers["Authorization"] = "Bearer " + key
    try:
        response = requests.get(url + "/rest/v1/", headers=headers, timeout=15, allow_redirects=False)
        latency = int((time.monotonic() - started) * 1000)
        status = response.status_code
        if status != 200:
            if status == 401:
                code, error, hint = "supabase_unauthorized", "Supabase rejected the API key (HTTP 401).", "Check that the key is active and belongs to this project."
            elif status == 403:
                code, error, hint = "supabase_forbidden", "Supabase denied Data API access (HTTP 403).", "Check API access, schema exposure and role permissions."
            elif status == 404:
                code, error, hint = "supabase_not_found", "The Data API endpoint was not found (HTTP 404).", "Check the project URL and whether the Data API is enabled."
            elif status == 429:
                code, error, hint = "supabase_rate_limited", "Supabase rate limit reached (HTTP 429).", "Wait before retrying and check project rate limits."
            elif 300 <= status < 400:
                code, error, hint = "supabase_redirect", "The endpoint returned a redirect.", "Use the final project root URL. Redirects are not followed to protect the API key."
            elif status >= 500:
                code, error, hint = "supabase_unavailable", "The Supabase service is unavailable.", "The endpoint responded, but the service reported an error. Check project status and the gateway."
            else:
                code, error, hint = "supabase_http_error", "The Data API returned an unexpected HTTP status.", "Check the project URL and Data API configuration."
            return 200, failure(code, error, hint, http_status=status, latency_ms=latency)
        try:
            document = response.json()
            if not isinstance(document, dict) or not (document.get("swagger") or document.get("openapi")):
                raise ValueError("not an OpenAPI document")
            schemas = document.get("definitions", document.get("components", {}).get("schemas", {}))
            if not isinstance(schemas, dict):
                raise ValueError("invalid schema listing")
        except (ValueError, TypeError, AttributeError):
            return 200, failure("supabase_invalid_response", "The response is not a Data API schema document.",
                                "The URL may point to a dashboard, login page or another service.", http_status=200, latency_ms=latency)
        return 200, {"ok": True, "code": "supabase_ok", "backend": "supabase", "url": url,
                     "table_count": len(schemas), "tables": list(schemas)[:50], "latency_ms": latency}
    except requests.exceptions.SSLError:
        return 200, failure("supabase_tls_error", "TLS certificate verification failed.",
                            "Check the certificate, hostname and the server's trusted CA certificates.")
    except requests.Timeout:
        return 200, failure("supabase_timeout", "The connection timed out after 15 seconds.",
                            "Check connectivity and whether the project is paused or unavailable.")
    except requests.ConnectionError:
        return 200, failure("supabase_network_error", "The server could not reach the Supabase endpoint.",
                            "Check DNS, network connectivity, proxy and firewall settings. This is not proof that the key is invalid.")
    except requests.RequestException:
        return 200, failure("supabase_request_error", "The Data API request could not be completed.",
                            "Check the project URL, API key format and server network configuration.")


def check_data_backend(data, cfg):
    backend = str(data.get("backend") or ("supabase" if data.get("url") else cfg.data.backend) or "none")
    if backend == "sqlite":
        return 200, check_sqlite(cfg)
    if backend == "supabase":
        return check_supabase(data, cfg)
    if backend == "none":
        return 200, {"ok": None, "status": "skipped", "code": "backend_disabled", "backend": "none"}
    return 400, failure("backend_unsupported", "Connection tests are not implemented for this backend.",
                        "Choose SQLite or Supabase for this test.")
