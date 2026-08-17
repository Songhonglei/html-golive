"""golive.core.demo — the two bundled example sites.

Reason these exist: after ``pip install`` there is nothing to look at.
The user has to write an HTML file, guess a slug, start the server and
hope. Two ready-made pages turn "did it install correctly?" into a URL
you can click:

  demo-static — what golive is, which commands matter
  demo-crud   — a working to-do list backed by ``window.TemplateAPI``;
                refresh the browser and the rows are still there, which
                is the only convincing proof that the data layer is real

Both ship inside the wheel (``golive/resources/demo/``) and are published
through the normal pipeline, so they exercise exactly the code path a
user's own page takes — including data-layer injection.

Public API:
  demo_dir()                 -> Path of the bundled demo sources
  list_demos()               -> [DemoSpec, ...]
  install(...)               -> publish/refresh both demos (idempotent)
  remove(...)                -> delete the demo sites and their rows
  status(...)                -> which demos are currently published
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

#: modelCode used by demo-crud. Namespaced so it can never collide with a
#: user's own data, and so ``demo remove`` can drop exactly those rows.
DEMO_MODEL_CODE = "golive_demo_todo"


class DemoSpec:
    """One bundled example page."""

    __slots__ = ("slug", "filename", "name", "description", "model_code")

    def __init__(self, slug: str, filename: str, name: str,
                 description: str, model_code: str = ""):
        self.slug = slug
        self.filename = filename
        self.name = name
        self.description = description
        self.model_code = model_code

    @property
    def path(self) -> Path:
        return demo_dir() / self.filename

    def as_dict(self) -> dict:
        return {"slug": self.slug, "name": self.name,
                "description": self.description,
                "model_code": self.model_code,
                "source": str(self.path)}


DEMOS = (
    DemoSpec("demo-static", "demo-static.html", "golive 示例 · 介绍页",
             "golive 是什么 + 常用命令"),
    DemoSpec("demo-crud", "demo-crud.html", "golive 示例 · 待办清单",
             "TemplateAPI 的真实读写", DEMO_MODEL_CODE),
)


class DemoError(RuntimeError):
    """Raised for anything the caller should see as a clean CLI error."""


def demo_dir() -> Path:
    """Absolute path of the demo sources shipped inside the package."""
    return Path(__file__).resolve().parent.parent / "resources" / "demo"


def list_demos() -> list:
    return list(DEMOS)


def _read(spec: DemoSpec) -> str:
    p = spec.path
    if not p.is_file():
        raise DemoError(
            f"bundled demo is missing: {p}\n"
            "  The install looks incomplete — reinstall html-golive "
            "(pip install --force-reinstall html-golive).")
    return p.read_text(encoding="utf-8")


def status(registry=None) -> dict:
    """Which demos are currently published (read-only)."""
    if registry is None:
        from golive.backends.factory import get_registry
        registry = get_registry()
    out = []
    for spec in DEMOS:
        site = registry.get_by_slug(spec.slug)
        out.append({**spec.as_dict(),
                    "published": site is not None,
                    "site_id": site["site_id"] if site else ""})
    return {"demos": out,
            "published": sum(1 for d in out if d["published"]),
            "total": len(out)}


def install(registry=None, storage=None, force: bool = False) -> dict:
    """Publish (or refresh) both demos. Idempotent.

    Already published and ``force`` not set -> the page content is
    refreshed in place but the site row, its id and any data rows are
    left alone. Re-running ``golive init`` therefore never duplicates
    sites and never wipes the to-do items someone just typed in.
    """
    from golive.backends.factory import get_registry, get_storage
    from golive.inject import template_api

    registry = registry or get_registry()
    storage = storage or get_storage()

    results = []
    for spec in DEMOS:
        html = _read(spec)
        if spec.model_code:
            html = template_api.inject_into_html(html, spec.model_code)

        site = registry.get_by_slug(spec.slug)
        if site is None:
            site = registry.create(name=spec.name, slug=spec.slug)
            storage.publish(html, site["site_id"], backup_previous=False)
            action = "created"
        else:
            storage.publish(html, site["site_id"])
            registry.touch(site["site_id"])
            action = "refreshed"
        results.append({**spec.as_dict(), "action": action,
                        "site_id": site["site_id"]})
    return {"demos": results,
            "created": sum(1 for r in results if r["action"] == "created"),
            "refreshed": sum(1 for r in results if r["action"] == "refreshed")}


def remove(registry=None, storage=None, drop_data: bool = True) -> dict:
    """Delete the demo sites. ``drop_data`` also removes the to-do rows."""
    from golive.backends.factory import get_registry, get_storage

    registry = registry or get_registry()
    storage = storage or get_storage()

    removed, missing = [], []
    for spec in DEMOS:
        site = registry.get_by_slug(spec.slug)
        if site is None:
            missing.append(spec.slug)
            continue
        try:
            storage.delete(site["site_id"])
        except OSError as e:
            raise DemoError(f"could not delete site files for "
                            f"{spec.slug}: {e}") from e
        registry.delete(site["site_id"])
        removed.append(spec.slug)

    rows_deleted = 0
    if drop_data:
        rows_deleted = _drop_demo_rows()
    return {"removed": removed, "missing": missing,
            "rows_deleted": rows_deleted}


def _drop_demo_rows() -> int:
    """Delete demo-crud's rows. Never raises — data cleanup is best-effort."""
    try:
        from golive.backends.factory import get_template_store
        store = get_template_store()
        if store is None:
            return 0
        page = store.list(DEMO_MODEL_CODE, page_size=1000)
        n = 0
        for row in page.get("list", []):
            if store.delete(row.get("id")):
                n += 1
        return n
    except Exception:  # noqa: BLE001 — cleanup must not break `demo remove`
        return 0


def urls(port: int = 8787, base: str = "") -> dict:
    """Public URLs for the demos + the admin portal."""
    root = base.rstrip("/") if base else f"http://localhost:{port}"
    out = {spec.slug: f"{root}/{spec.slug}" for spec in DEMOS}
    out["admin"] = f"{root}/admin"
    return out


def health_check(port: int = 8787, host: str = "127.0.0.1",
                 timeout: float = 5.0) -> dict:
    """Really fetch both demos and exercise the CRUD endpoint over HTTP.

    Printing "✅ done" without proving the server answers is how people
    end up debugging a dead port for twenty minutes. Returns a dict of
    check-name -> {ok, detail}; the caller decides how loud to be.
    """
    import json
    import urllib.error
    import urllib.request

    base = f"http://{host}:{port}"
    checks = {}

    def _get(path, expect=200):
        req = urllib.request.Request(base + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status == expect, r.status, body

    # 1. health endpoint (also tells us which version is actually running)
    try:
        ok, code, body = _get("/health")
        info = json.loads(body) if ok else {}
        checks["health"] = {
            "ok": ok,
            "detail": (f"version {info.get('version', '?')}, "
                       f"home {info.get('home', '?')}") if ok
                      else f"HTTP {code}",
        }
    except (urllib.error.URLError, OSError, ValueError) as e:
        checks["health"] = {"ok": False, "detail": str(e)}

    # 2. both demo pages render
    for spec in DEMOS:
        try:
            ok, code, body = _get("/" + spec.slug)
            checks[spec.slug] = {
                "ok": ok and len(body) > 200,
                "detail": f"HTTP {code}, {len(body)} bytes",
            }
        except (urllib.error.URLError, OSError) as e:
            checks[spec.slug] = {"ok": False, "detail": str(e)}

    # 3. the data layer really round-trips (write, read back, clean up)
    checks["crud"] = _crud_probe(base, timeout)
    return checks


def _crud_probe(base: str, timeout: float) -> dict:
    """POST a throwaway row, read it back, delete it. Proves the data layer."""
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    from golive.backends.data.sqlite_store import DEFAULT_TABLE
    try:
        from golive.config import get_config
        table = get_config().data.templates_table or DEFAULT_TABLE
    except Exception:  # noqa: BLE001
        table = DEFAULT_TABLE

    endpoint = f"{base}/api/data/{table}"
    probe_name = f"__golive_init_probe_{int(time.time() * 1000)}"

    def _call(method, path="", body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(endpoint + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)

    row_id = ""
    try:
        status_code, created = _call(
            "POST", body=[{"model_code": DEMO_MODEL_CODE, "name": probe_name,
                           "content": {"probe": True}}],
            headers={"Prefer": "return=representation"})
        if status_code != 201 or not created:
            return {"ok": False, "detail": f"insert returned HTTP {status_code}"}
        row_id = created[0].get("id", "")

        q = "?" + urllib.parse.urlencode({"id": f"eq.{row_id}", "limit": "1"})
        status_code, rows = _call("GET", q)
        if status_code != 200 or not rows:
            return {"ok": False, "detail": "row written but not readable back"}
        return {"ok": True, "detail": "insert + read-back OK"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "detail": str(e)}
    finally:
        if row_id:
            try:
                _call("DELETE", "?" + urllib.parse.urlencode(
                    {"id": f"eq.{row_id}"}))
            except Exception:  # noqa: BLE001 — probe cleanup is best-effort
                pass
