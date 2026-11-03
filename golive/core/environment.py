"""Offline environment diagnostics; never print proxy URLs or credentials."""
from __future__ import annotations

import importlib.util
import os
import shutil
import ssl
import sys
import urllib.request


def collect_environment(cfg):
    implementation = ssl.OPENSSL_VERSION
    supported = implementation.startswith("OpenSSL ") and ssl.OPENSSL_VERSION_INFO >= (1, 1, 1)
    proxy_vars = [key for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                                  "http_proxy", "https_proxy", "all_proxy", "no_proxy") if os.environ.get(key)]
    try:
        system = sorted(k for k in urllib.request.getproxies() if k != "no")
    except (OSError, ValueError):
        system = []
    warnings = []
    if not supported:
        warnings.append("urllib3 v2 requires OpenSSL 1.1.1+. Use a Python built with OpenSSL (for example Homebrew Python), then recreate the virtual environment. Do not disable TLS verification.")
    if system and not any(k.lower() in ("http_proxy", "https_proxy", "all_proxy") for k in proxy_vars):
        warnings.append("System proxy detected without shell proxy variables. Homebrew and CLI downloads may need HTTP_PROXY/HTTPS_PROXY/ALL_PROXY exported explicitly; keep credentials out of shell history.")
    mysql = None
    if "mysql" in (cfg.registry.backend, cfg.data.backend):
        from golive.backends.factory import sql_dsn_env
        env = sql_dsn_env(cfg, "mysql")
        mysql = {"dsn_env": env, "dsn_set": bool(os.environ.get(env, "").strip()),
                 "driver_available": importlib.util.find_spec("pymysql") is not None,
                 "docker_available": shutil.which("docker") is not None,
                 "mysqld_available": shutil.which("mysqld") is not None,
                 "hint": "Use an existing dedicated MySQL 8.4+ connection, or run scripts/mysql_sandbox.py start --directory <isolated-directory>. Missing local Docker/MySQL is not an error for a remote DSN."}
    return {"python_executable": sys.executable, "ssl": {"implementation": implementation, "urllib3_v2_supported": supported},
            "proxy": {"environment_variables": proxy_vars, "detected_schemes": system,
                      "remote_tls_verified": False}, "mysql": mysql, "warnings": warnings}
