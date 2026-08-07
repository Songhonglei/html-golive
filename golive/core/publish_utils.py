#!/usr/bin/env python3
"""golive.core.publish_utils — shared publish helpers.

Extracted from the upstream orchestration layer: framework-project
detection, directory bundling, base64 image compression and size gates.
"""


from __future__ import annotations
import base64
import json
import re
import sys
from pathlib import Path

from golive.i18n import t

# size gates
IMAGE_SIZE_WARN_STRONG = 5 * 1024 * 1024    # 5 MB — strongly suggest compression
IMAGE_SIZE_BLOCK_BYTES = 10 * 1024 * 1024   # 10 MB — refuse without compression


# ── framework project detection ──────────────────────────────────────────────

def detect_framework_project(project_dir: Path):
    """Detect an un-built framework project; returns a hint string or None."""
    pkg_json = project_dir / "package.json"
    if not pkg_json.exists():
        return None

    has_output = any((project_dir / d).exists() for d in ("dist", "build", "out"))
    has_html = bool(list(project_dir.glob("*.html")))

    if not has_output and not has_html:
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            has_build_script = "build" in scripts or "compile" in scripts
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            frameworks = [k for k in deps if k in
                          ("react", "vue", "svelte", "@angular/core", "next", "nuxt", "vite")]
            if frameworks or has_build_script:
                framework_list = ", ".join(frameworks) if frameworks else "framework"
                return t("publish_utils.framework_detected",
                         framework=framework_list, dir=project_dir)
            return t("publish_utils.no_html", dir=project_dir)
        except Exception:
            pass
    return None


# ── directory bundling ───────────────────────────────────────────────────────

def bundle_project(project_dir: Path, entry_html=None) -> str:
    """Bundle a multi-file project directory into a single HTML string.

    When an image uploader is configured (env GOLIVE_UPLOADER_CMD),
    images are uploaded and referenced by URL; otherwise all assets are
    inlined (images as base64 data URIs)."""
    warning = detect_framework_project(project_dir)
    if warning:
        print(warning, file=sys.stderr)
        sys.exit(1)

    from golive.backends.images.command import get_uploader
    from golive.core.bundle import Bundler, find_entry_interactive

    uploader = get_uploader()
    if uploader is not None:
        print(t("publish_utils.uploader_enabled"), file=sys.stderr)

    bundler = Bundler(project_dir, uploader=uploader,
                      use_image_upload=uploader is not None)

    entry_path = None
    if entry_html:
        entry_path = (project_dir / entry_html).resolve()
        if not entry_path.exists():
            print(t("publish_utils.entry_not_found", path=entry_path), file=sys.stderr)
            sys.exit(1)
    else:
        entry_path = bundler.find_entry_html()
        if entry_path is None:
            try:
                entry_path = find_entry_interactive(project_dir)
            except Exception as e:  # noqa: BLE001
                print(t("publish_utils.bundle_error", error=e), file=sys.stderr)
                sys.exit(1)

    return bundler.bundle(entry_path)


# ── image compression ────────────────────────────────────────────────────────

def compress_base64_images(html_content: str, quality: int = 70) -> str:
    """Compress inline base64 images (JPEG/PNG → JPEG). Requires Pillow."""
    try:
        import io

        from PIL import Image
    except ImportError:
        print(t("publish_utils.compress_no_pillow"), file=sys.stderr)
        return html_content

    pattern = re.compile(
        r'(data:image/(?:png|jpeg|jpg|webp);base64,)([A-Za-z0-9+/=]+)',
        re.IGNORECASE)
    compressed_count = 0
    saved_bytes = 0

    def replace_image(m):
        nonlocal compressed_count, saved_bytes
        prefix, b64data = m.group(1), m.group(2)
        try:
            raw = base64.b64decode(b64data)
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            new_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            if len(new_b64) < len(b64data):
                saved_bytes += len(b64data) - len(new_b64)
                compressed_count += 1
                return f"data:image/jpeg;base64,{new_b64}"
        except Exception:
            pass
        return m.group(0)

    result = pattern.sub(replace_image, html_content)
    if compressed_count:
        print(t("publish_utils.compressed", count=compressed_count,
                kb=saved_bytes * 3 // 4 // 1024), file=sys.stderr)
    return result


# ── size gate ────────────────────────────────────────────────────────────────

def check_html_size(html: str, compress: bool = False) -> str:
    """Tiered size check: 5 MB warn, 10 MB block (unless compressed under).

    Returns possibly-compressed html; exits on hard block."""
    size = len(html.encode("utf-8"))
    if size < IMAGE_SIZE_WARN_STRONG:
        return html

    size_mb = size / 1024 / 1024

    if size >= IMAGE_SIZE_BLOCK_BYTES:
        if compress:
            for quality in (70, 50, 30):
                print(t("publish_utils.size_over_10mb_compress",
                        size_mb=size_mb, quality=quality), file=sys.stderr)
                compressed = compress_base64_images(html, quality=quality)
                new_size = len(compressed.encode("utf-8"))
                if new_size < IMAGE_SIZE_BLOCK_BYTES:
                    print(t("publish_utils.size_compressed_ok",
                            size_mb=new_size / 1024 / 1024, quality=quality),
                          file=sys.stderr)
                    return compressed
                print(t("publish_utils.size_still_over",
                        size_mb=new_size / 1024 / 1024), file=sys.stderr)
            print(t("publish_utils.size_block_fail"), file=sys.stderr)
            print(t("publish_utils.size_block_hint"), file=sys.stderr)
            sys.exit(1)
        print(t("publish_utils.size_block_no_compress",
                size_mb=size_mb), file=sys.stderr)
        print(t("publish_utils.size_block_no_compress_hint"), file=sys.stderr)
        sys.exit(1)

    # 5~10 MB
    if compress:
        print(t("publish_utils.size_warn_compress",
                size_mb=size_mb), file=sys.stderr)
        return compress_base64_images(html)
    print(t("publish_utils.size_warn",
            size_mb=size_mb), file=sys.stderr)
    return html


# ── misc pre-publish checks ──────────────────────────────────────────────────

def check_title_missing(html: str) -> None:
    """Warn (non-blocking) when <title> is missing."""
    if not re.search(r'<title[^>]*>[^<]', html, re.IGNORECASE):
        print(t("publish_utils.title_missing"), file=sys.stderr)
