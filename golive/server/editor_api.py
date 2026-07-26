"""golive.server.editor_api — save channel for the online editor (M3).

Handles::

  PUT  /api/sites/<slug>/content    save edited HTML
  POST /api/sites/<slug>/upload     upload an image (when configured)

Authorization model (single-writer, no CRDT):
  1. the site must have editing enabled (registry ``editable`` flag —
     set via ``golive publish --enable-editor``);
  2. the request must carry a valid editor token
     (``GOLIVE_EDITOR_TOKEN`` / yaml ``editor.token``; falls back to the
     serve token ``GOLIVE_TOKEN``) **or** an authenticated OIDC session;
  3. the claimed editor identity (``X-Editor-User`` header, or the OIDC
     session email) must be the site owner or a registered maintainer.
     When the site has no owner AND no maintainers, any valid token is
     accepted (zero-config mode) — a warning is printed at publish time.

Every save re-runs the publish-time security gate (code-safety checker +
rule/AI scanner) so the edit channel can never bypass the scan, snapshots
the previous version (rollback safety net), and writes an audit entry.
"""

from __future__ import annotations

import hmac
import json
import sys
import time

MAX_HTML_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def resolve_editor_token(cfg=None) -> str:
    """editor.token > auth.token ('' = editing API disabled)."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    return cfg.editor.token or cfg.auth.token


def check_editor_auth(headers: dict, site: dict, cfg=None,
                      session_user: dict = None) -> tuple:
    """Return (ok, status_code, error_message, editor_identity)."""
    if not site.get("editable"):
        return False, 403, ("editing is not enabled for this site "
                            "(publish with --enable-editor)"), ""

    identity = ""
    hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}

    if session_user and session_user.get("email"):
        # OIDC session wins: identity is server-verified
        identity = session_user["email"].lower()
    else:
        token = resolve_editor_token(cfg)
        if not token:
            return False, 403, ("editing API disabled: no editor token "
                                "configured (set GOLIVE_EDITOR_TOKEN)"), ""
        candidate = hdrs.get("x-golive-token", "")
        if not candidate:
            auth = hdrs.get("authorization", "")
            if auth.lower().startswith("bearer "):
                candidate = auth[7:].strip()
        if not candidate or not hmac.compare_digest(candidate, token):
            return False, 401, "invalid editor token", ""
        identity = hdrs.get("x-editor-user", "").strip().lower()

    owner = (site.get("owner") or "").strip().lower()
    maintainers = [str(m).strip().lower()
                   for m in (site.get("maintainers") or [])]

    if owner or maintainers:
        if not identity:
            return False, 403, ("X-Editor-User header required "
                                "(must match site owner or a maintainer)"), ""
        if identity != owner and identity not in maintainers:
            return False, 403, (f"'{identity}' is not the site owner "
                                f"or a maintainer"), identity
    # zero-config mode (no owner, no maintainers): any valid token passes
    return True, 200, "", identity


def save_content(site: dict, html: str, editor: str,
                 registry, storage, cfg=None) -> tuple:
    """Validate + scan + snapshot + overwrite. Returns (status, body_dict)."""
    t0 = time.time()
    site_id = site["site_id"]

    if not html or not html.strip():
        return 400, {"error": "empty body"}
    size = len(html.encode("utf-8"))
    if size > MAX_HTML_BYTES:
        return 413, {"error": f"HTML too large ({size} bytes > "
                              f"{MAX_HTML_BYTES} limit)"}

    # security gate — same pipeline as publish; the edit channel must
    # never become a scanner bypass.
    from golive.core.code_safety_checker import run_check as code_safety_check
    from golive.security.scanner import run_scan

    # auto_yes: server context is non-interactive; WARN-level issues pass
    # (same as publish --yes), BLOCK-level issues always refuse.
    passed, issues = code_safety_check(html, auto_yes=True)
    if not passed:
        blocks = [i for i in issues if i.get("level") == "BLOCK"]
        return 422, {"error": "code safety check failed",
                     "details": [i.get("label", "") for i in blocks[:5]]}

    ok, _scan = run_scan(html, skip_scan=False, cfg=cfg)
    if not ok:
        return 422, {"error": "security scan blocked the content "
                              "(sensitive data detected)"}

    # keep the editor layer working after save: re-inject before persisting
    # (the client strips editor UI from the DOM before upload)
    from golive.inject import editor as editor_inject
    html_to_store = editor_inject.inject_into_html(
        html, slug=site.get("slug") or site_id, site_name=site.get("name", ""))

    # snapshot happens inside storage.publish(backup_previous=True)
    storage.publish(html_to_store, site_id, backup_previous=True)
    snaps = storage.list_snapshots(site_id)
    snapshot_id = snaps[0]["ts"] if snaps else ""
    registry.touch(site_id)

    from golive.core.audit_log import log_call
    log_call(operation="editor_save", endpoint=f"/api/sites/{site.get('slug') or site_id}/content",
             params={"editor": editor, "slug": site.get("slug", ""),
                     "site_id": site_id, "htmlSize": size},
             success=True, duration_ms=int((time.time() - t0) * 1000),
             result={"snapshot_id": snapshot_id})

    # admin audit trail (M5) — one line per write action
    from golive.core.audit import record
    record(editor or "(token)", "editor.save",
           site.get("slug") or site_id,
           {"size": size, "snapshot_id": snapshot_id})

    return 200, {"success": True, "snapshot_id": snapshot_id, "size": size}


def upload_image(site: dict, data: bytes, filename: str, editor: str) -> tuple:
    """Upload an image through the configured ImageUploader.

    Returns (status, body_dict). 501 when no uploader is configured —
    the front-end then keeps images inline (base64)."""
    if len(data) > MAX_UPLOAD_BYTES:
        return 413, {"error": f"file too large (> {MAX_UPLOAD_BYTES} bytes)"}

    from golive.backends.images.command import get_uploader
    uploader = get_uploader()
    if uploader is None:
        return 501, {"error": "no image uploader configured — "
                              "images stay inline (base64)"}
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        return 415, {"error": f"unsupported image type: {suffix}"}
    try:
        url = uploader.upload(data, filename)
        if not url:
            return 502, {"error": "uploader returned no URL"}
        from golive.core.audit_log import log_call
        log_call(operation="editor_upload", endpoint="upload",
                 params={"editor": editor, "site_id": site["site_id"],
                         "filename": filename, "size": len(data)},
                 success=True, duration_ms=0, result={"url": url})
        return 200, {"success": True, "url": url}
    except Exception as e:  # noqa: BLE001 — surfaced as API error
        print(f"⚠️  editor upload failed: {e}", file=sys.stderr)
        return 502, {"error": f"upload failed: {e}"}
