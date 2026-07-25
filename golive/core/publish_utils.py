#!/usr/bin/env python3
"""golive.core.publish_utils — shared publish helpers.

Extracted from the upstream orchestration layer: framework-project
detection, directory bundling, base64 image compression and size gates.
"""

import base64
import json
import re
import sys
from pathlib import Path

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
                framework_list = "、".join(frameworks) if frameworks else "框架"
                return (
                    f"⚠️  检测到 {framework_list} 项目，但没有找到 build 产物（dist/ 或 build/ 目录）。\n"
                    f"   请先执行以下命令后重试：\n"
                    f"   cd {project_dir}\n"
                    f"   npm install && npm run build\n"
                    f"   然后使用 golive publish {project_dir}/dist 重新运行。"
                )
            return (
                f"⚠️  检测到 package.json，但目录中没有 HTML 文件，也没有 dist/ 或 build/ 产物目录。\n"
                f"   golive 只支持静态 HTML 项目。\n"
                f"   • 前端项目：请先 npm run build，再 publish 产物目录\n"
                f"   • Node.js 后端项目：golive 不支持此类型"
            )
        except Exception:
            pass
    return None


# ── directory bundling ───────────────────────────────────────────────────────

def bundle_project(project_dir: Path, entry_html=None) -> str:
    """Bundle a multi-file project directory into a single HTML string.

    All assets are inlined (images as base64 data URIs)."""
    warning = detect_framework_project(project_dir)
    if warning:
        print(warning, file=sys.stderr)
        sys.exit(1)

    from golive.core.bundle import Bundler, find_entry_interactive

    bundler = Bundler(project_dir, uploader=None, use_image_upload=False)

    entry_path = None
    if entry_html:
        entry_path = (project_dir / entry_html).resolve()
        if not entry_path.exists():
            print(f"错误：指定入口文件不存在：{entry_path}", file=sys.stderr)
            sys.exit(1)
    else:
        entry_path = bundler.find_entry_html()
        if entry_path is None:
            try:
                entry_path = find_entry_interactive(project_dir)
            except Exception as e:  # noqa: BLE001
                print(f"错误：{e}", file=sys.stderr)
                sys.exit(1)

    return bundler.bundle(entry_path)


# ── image compression ────────────────────────────────────────────────────────

def compress_base64_images(html_content: str, quality: int = 70) -> str:
    """Compress inline base64 images (JPEG/PNG → JPEG). Requires Pillow."""
    try:
        import io

        from PIL import Image
    except ImportError:
        print("⚠️  压缩图片需要 Pillow（pip install 'html-golive[image]'），跳过压缩。",
              file=sys.stderr)
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
        print(f"🗜️  压缩了 {compressed_count} 张图片，节省约 "
              f"{saved_bytes * 3 // 4 // 1024} KB", file=sys.stderr)
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
                print(f"⚠️  HTML 大小 {size_mb:.1f}MB（超过 10MB），尝试质量 {quality} 压缩...",
                      file=sys.stderr)
                compressed = compress_base64_images(html, quality=quality)
                new_size = len(compressed.encode("utf-8"))
                if new_size < IMAGE_SIZE_BLOCK_BYTES:
                    print(f"   ✅ 压缩后: {new_size / 1024 / 1024:.1f}MB（质量 {quality}）",
                          file=sys.stderr)
                    return compressed
                print(f"   仍有 {new_size / 1024 / 1024:.1f}MB，继续降级...", file=sys.stderr)
            print("\n❌ 压缩到质量 30 后体积仍然超过 10MB，无法发布。", file=sys.stderr)
            print("   建议手动删除部分大图后重试。", file=sys.stderr)
            sys.exit(1)
        print(f"\n❌ HTML 大小 {size_mb:.1f}MB，超过 10MB 上限，发布已阻断。", file=sys.stderr)
        print("   请压缩图片后重新发布：传入 --compress 参数", file=sys.stderr)
        sys.exit(1)

    # 5~10 MB
    if compress:
        print(f"⚠️  HTML 大小 {size_mb:.1f}MB（超过 5MB），--compress 已启用，自动压缩。",
              file=sys.stderr)
        return compress_base64_images(html)
    print(f"⚠️  HTML 大小 {size_mb:.1f}MB（超过 5MB），建议加 --compress 压缩内联图片。",
          file=sys.stderr)
    return html


# ── misc pre-publish checks ──────────────────────────────────────────────────

def check_title_missing(html: str) -> None:
    """Warn (non-blocking) when <title> is missing."""
    if not re.search(r'<title[^>]*>[^<]', html, re.IGNORECASE):
        print("⚠️  未检测到 <title> 标签，建议补充页面标题（影响站点列表展示名称）",
              file=sys.stderr)
