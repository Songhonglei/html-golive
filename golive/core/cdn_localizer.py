#!/usr/bin/env python3
"""golive.core.cdn_localizer — external CDN resource localization.

Scans HTML for external resources (script/link/img/@import/url()) and
localizes them so the published page has no runtime dependency on
third-party CDNs:

  - With an ``uploader`` callable (M2 ImageUploader backend):
    download -> upload -> replace URL.
  - Without an uploader (M1 default): download -> inline as base64
    data URI (small resources only).

A configurable ``never_localize`` list (domains that must stay remote,
e.g. cdn.tailwindcss.com whose JIT compiler cannot be snapshotted) can
be extended via golive.yaml::

  localize:
    never:
      - cdn.tailwindcss.com

Public API:
  scan_external_resources(html) -> list[dict]
  localize(html, do_download=True, uploader=None, log=print) -> (html, stats)
"""

import base64
import mimetypes
import re
import tempfile
from pathlib import Path

from golive.core.http_client import http_get_bytes

# Resources that must never be localized (runtime compilers / license limits)
_DEFAULT_NEVER = {
    "cdn.tailwindcss.com": "Tailwind CDN 是运行时 JIT 编译器，快照后样式会失效",
}

# Max size for base64 inlining (when no uploader is available)
_INLINE_MAX_BYTES = 2 * 1024 * 1024

_extra_never: dict[str, str] = {}


def configure_never_localize(domains) -> None:
    """Extend the never-localize list (from golive.yaml)."""
    for d in domains or []:
        _extra_never[str(d).lower()] = "配置文件 never_localize 指定"


def _never_map() -> dict:
    m = dict(_DEFAULT_NEVER)
    m.update(_extra_never)
    return m


def _is_never_localize(url: str) -> tuple[bool, str]:
    low = url.lower()
    for d, reason in _never_map().items():
        if d in low:
            return True, reason
    return False, ""


# ── external URL extraction patterns (http(s) and protocol-relative //) ─────
_PATTERNS = [
    (r'<script\b[^>]*\bsrc=(["\'])(?P<u>https?://[^"\']+|//[^"\']+)\1', "script"),
    (r'<link\b[^>]*\bhref=(["\'])(?P<u>https?://[^"\']+|//[^"\']+)\1', "link"),
    (r'<img\b[^>]*\bsrc=(["\'])(?P<u>https?://[^"\']+|//[^"\']+)\1', "img"),
    (r'<source\b[^>]*\bsrc=(["\'])(?P<u>https?://[^"\']+|//[^"\']+)\1', "source"),
    (r'@import\s+(?:url\()?(["\']?)(?P<u>https?://[^"\')]+|//[^"\')]+)\1\)?', "import"),
    (r'url\(\s*(["\']?)(?P<u>https?://[^"\')]+|//[^"\')]+)\1\s*\)', "css-url"),
]


def scan_external_resources(html: str) -> list[dict]:
    """Scan HTML for external resources; deduplicated by URL."""
    found: dict[str, dict] = {}
    for pat, kind in _PATTERNS:
        for m in re.finditer(pat, html, re.IGNORECASE):
            raw = m.group("u").strip()
            if not raw or raw in found:
                continue
            test_url = ("https:" + raw) if raw.startswith("//") else raw
            never, reason = _is_never_localize(test_url)
            found[raw] = {
                "url": raw,
                "test_url": test_url,
                "kind": kind,
                "never": never,
                "reason": reason,
            }
    return list(found.values())


# ── download helpers ─────────────────────────────────────────────────────────

def _guess_ext(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    suffix = Path(path).suffix
    return suffix if suffix and len(suffix) <= 6 else ".bin"


def _guess_mime(url: str) -> str:
    path = url.split("?")[0].split("#")[0]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _upload_bytes(data: bytes, ext: str, uploader):
    """uploader signature: uploader(local_path) -> cdn_url. Returns None on failure."""
    if uploader is None:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return uploader(tmp_path)
    except Exception:
        return None


# ── main flow ────────────────────────────────────────────────────────────────

def localize(
    html: str,
    do_download: bool = True,
    uploader=None,
    log=print,
) -> tuple[str, dict]:
    """Localize external resources.

    do_download: attempt runtime download when True.
    uploader:    optional callable(local_path)->url. When None, resources are
                 inlined as base64 data URIs (<= 2 MB each).
    Returns (new_html, stats dict).
    """
    resources = scan_external_resources(html)
    stats = {
        "total": len(resources),
        "uploaded": 0,
        "inlined": 0,
        "skipped_never": 0,
        "failed": 0,
        "details": [],
    }
    if not resources:
        return html, stats

    new_html = html
    for r in resources:
        url = r["url"]
        if r["never"]:
            stats["skipped_never"] += 1
            stats["details"].append(f"⏭️  跳过（{r['reason']}）：{url}")
            continue
        if not do_download:
            stats["failed"] += 1
            stats["details"].append(f"⏭️  未开启下载，保持原样：{url}")
            continue

        data, err = http_get_bytes(r["test_url"], timeout=30,
                                   max_bytes=_INLINE_MAX_BYTES if uploader is None else 0)
        if data is None:
            stats["failed"] += 1
            stats["details"].append(f"⚠️  下载失败（{err}），保持原样：{url}")
            continue

        if uploader is not None:
            cdn = _upload_bytes(data, _guess_ext(url), uploader)
            if cdn:
                new_html = new_html.replace(url, cdn)
                stats["uploaded"] += 1
                stats["details"].append(f"✅ 下载上传：{url} → {cdn}")
            else:
                stats["failed"] += 1
                stats["details"].append(f"⚠️  上传失败，保持原样：{url}")
        else:
            mime = _guess_mime(r["test_url"])
            b64 = base64.b64encode(data).decode("ascii")
            new_html = new_html.replace(url, f"data:{mime};base64,{b64}")
            stats["inlined"] += 1
            stats["details"].append(f"✅ 内联 base64：{url}（{len(data) // 1024} KB）")

    return new_html, stats


# ── CLI (debug) ──────────────────────────────────────────────────────────────

def main():
    import argparse
    import json

    ap = argparse.ArgumentParser(description="外链资源本地化调试")
    ap.add_argument("--file", required=True, help="HTML 文件")
    ap.add_argument("--scan", action="store_true", help="仅扫描，不替换")
    args = ap.parse_args()
    html = Path(args.file).read_text(encoding="utf-8")
    if args.scan:
        for r in scan_external_resources(html):
            tag = "🚫 白名单" if r["never"] else "🌐 外部"
            print(f"{tag} [{r['kind']}] {r['url']}")
        return
    new_html, stats = localize(html, do_download=False)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
