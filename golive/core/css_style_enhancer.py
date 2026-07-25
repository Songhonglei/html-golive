#!/usr/bin/env python3
"""
css_style_enhancer.py — CSS 风格增强模块

功能：
  1. 将 19 种 CSS 风格注入到 HTML 文件，替换现有样式类 CSS
  2. 注入前自动备份原始 HTML（可恢复）
  3. 更新注册表 cssStyle 字段（JSON 格式）

用法（独立调用）：
  python3 css_style_enhancer.py --list
  python3 css_style_enhancer.py --list-backups [--source <label>]
  python3 css_style_enhancer.py --restore <backup_id> --target <path> [--yes]
  python3 css_style_enhancer.py --clean
"""

import argparse
import json
import os
import re
import sys

# data-role 自动标注模块（bs4 缺失时降级）
try:
    from golive.core.data_role_tagger import tag_html as _tag_html
except Exception:
    _tag_html = None
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

STYLES_DIR = Path(__file__).parent.parent / "resources" / "css_styles"
from golive.core.paths import get_data_dir as _get_data_dir
BACKUP_DIR = _get_data_dir() / "css_style_backup"
BACKUP_INDEX_FILE = BACKUP_DIR / "backup_index.json"

# ── 字体源（默认 Google Fonts，可用 GOLIVE_FONT_CDN_BASE 整体切换镜像）──────
GOOGLE_FONTS_HOST = "https://fonts.googleapis.com"

_GF = GOOGLE_FONTS_HOST + "/css2?"
_INTER = _GF + "family=Inter:wght@400;500;600;700&display=swap"

# ── 字体预加载映射（风格 → 字体 CSS URL）────────────────────────────────
FONT_PRELOADS: dict[str, str] = {
    "minimal": _INTER,
    "cowork": _INTER,
    "morandi": _INTER,
    "fresh": _INTER,
    "earthy": _INTER,
    "glass": _INTER,
    "dreamy": _INTER,
    "macaron": _INTER,
    "carbon": _INTER,
    "vivid": _INTER,
    "xhs": _GF + "family=Noto+Sans+SC:wght@400;500;700&display=swap",
    "xhs-fun": _GF + "family=Noto+Sans+SC:wght@400;500;700&display=swap",
    "newspaper": _GF + "family=Noto+Serif+SC:wght@400;600;700&family=Playfair+Display:ital,wght@0,700;0,900;1,400&display=swap",
    "ink": _GF + "family=Noto+Serif+SC:wght@400;600;700&family=ZCOOL+QingKe+HuangYou&display=swap",
    "steampunk": _GF + "family=Cinzel:wght@400;700&family=IM+Fell+English:ital@0;1&display=swap",
    "bloomberg": _GF + "family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap",
    "palace": _GF + "family=Ma+Shan+Zheng&family=ZCOOL+XiaoWei&display=swap",
    "cyberpunk": _GF + "family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap",
    # apple 用系统字体，不需要预加载
}


def apply_font_cdn_base(text: str, base: str | None = None) -> str:
    """将文本中的 Google Fonts 前缀替换为用户自定义字体 CDN。

    base 为 None 时读取环境变量 GOLIVE_FONT_CDN_BASE；空值时原样返回。
    纯函数（显式传 base 时无副作用），便于测试。
    """
    if base is None:
        base = os.environ.get("GOLIVE_FONT_CDN_BASE", "")
    base = base.strip().rstrip("/")
    if not base:
        return text
    return text.replace(GOOGLE_FONTS_HOST, base)


BACKUP_TTL_DAYS = 90

STYLE_MAP = {
    "minimal":    "极简优雅风",
    "apple":      "Apple 质感风",
    "cowork":     "轻科技协作风",
    "morandi":    "莫兰迪高级灰风",
    "fresh":      "清新自然绿风",
    "earthy":     "大地原木风",
    "glass":      "玻璃拟态风",
    "dreamy":     "优雅紫梦幻风",
    "macaron":    "马卡龙粉彩风",
    "carbon":     "暗色极简风",
    "vivid":      "活力渐变风",
    "newspaper":  "报纸杂志风",
    "bloomberg":  "Bloomberg 终端风",
    "ink":        "水墨卷轴风",
    "steampunk":  "蒸汽朋克风",
    "palace":     "故宫风",
    "cyberpunk":  "赛博科技风",
    "xhs":        "小红书简洁风",
    "xhs-fun":    "小红书趣味风",
}


def list_styles() -> None:
    """打印带编号的风格菜单。"""
    print("可用 CSS 风格：")
    for i, (key, name) in enumerate(STYLE_MAP.items(), 1):
        print(f"  {i:2d}. {key:<12}  {name}")


def load_css(style_key: str) -> str:
    """读取指定风格的 CSS 内容（应用 GOLIVE_FONT_CDN_BASE 字体源替换）。"""
    css_file = STYLES_DIR / f"{style_key}.css"
    if not css_file.exists():
        raise ValueError(
            f"CSS 风格文件不存在：{css_file}\n"
            f"可用风格：{', '.join(STYLE_MAP.keys())}"
        )
    return apply_font_cdn_base(css_file.read_text(encoding="utf-8"))


# ── 备份索引 I/O ──

def _load_backup_index() -> list:
    """读取备份索引，文件不存在返回 []。"""
    if not BACKUP_INDEX_FILE.exists():
        return []
    try:
        data = json.loads(BACKUP_INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_backup_index(entries: list) -> None:
    """写入备份索引。"""
    BACKUP_INDEX_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_backup(original_html: str, source_label: str, style_key: str) -> Path:
    """
    保存原始 HTML 备份，返回备份文件路径。
    失败时 raise RuntimeError。
    """
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # 路径安全处理
        safe_chars = re.sub(r'[/\\:*?"<>|]', '_', source_label)
        source_label_safe = safe_chars[:40]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"{source_label_safe}_{style_key}_{ts}"
        backup_file = BACKUP_DIR / f"{backup_id}_original.html"

        backup_file.write_text(original_html, encoding="utf-8")

        entries = _load_backup_index()
        entries.append(
            {
                "backup_id": backup_id,
                "backup_file": str(backup_file),
                "source_label": source_label,
                "style_key": style_key,
                "created_at": datetime.now(tz=timezone(timedelta(hours=8))).isoformat(),
            }
        )
        _save_backup_index(entries)
        return backup_file

    except Exception as exc:
        raise RuntimeError(f"备份失败：{exc}") from exc


def restore_backup(backup_id: str, target_path: Path, yes: bool = False) -> bool:
    """
    从备份恢复 HTML 到 target_path。
    返回 True 表示已恢复，False 表示取消或失败。
    """
    entries = _load_backup_index()
    record = next((e for e in entries if e.get("backup_id") == backup_id), None)

    if record is None:
        print(f"❌ 未找到备份记录：{backup_id}", file=sys.stderr)
        return False

    backup_file = Path(record["backup_file"])
    if not backup_file.exists():
        print(f"❌ 备份文件不存在：{backup_file}", file=sys.stderr)
        return False

    print(f"\n📂 备份信息：", file=sys.stderr)
    print(f"   时间  : {record.get('created_at', '未知')[:19]}", file=sys.stderr)
    print(f"   风格  : {record.get('style_key', '未知')}", file=sys.stderr)
    print(f"   来源  : {record.get('source_label', '未知')}", file=sys.stderr)
    print(f"   目标  : {target_path}", file=sys.stderr)

    if not yes:
        print(f"\n确认将备份恢复到 {target_path}？(y/N) ", end="", flush=True)
        try:
            choice = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return False
        if choice.lower() != "y":
            return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def list_backups(source_label: str | None = None) -> list:
    """
    返回备份列表，可按 source_label 精确过滤，按 created_at 倒序。
    """
    entries = _load_backup_index()
    if source_label is not None:
        entries = [e for e in entries if e.get("source_label") == source_label]
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return entries


def clean_expired_backups() -> int:
    """删除超过 BACKUP_TTL_DAYS 天的备份，返回清理数量。"""
    entries = _load_backup_index()
    cutoff = datetime.now(tz=timezone(timedelta(hours=8))) - timedelta(days=BACKUP_TTL_DAYS)
    kept = []
    removed = 0

    for entry in entries:
        created_at_str = entry.get("created_at", "")
        try:
            # 兼容带时区和不带时区的 ISO 格式
            if created_at_str.endswith("Z"):
                created_at_str = created_at_str[:-1] + "+00:00"
            created_at = datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            kept.append(entry)
            continue

        if created_at < cutoff:
            backup_file = Path(entry.get("backup_file", ""))
            if backup_file.exists():
                try:
                    backup_file.unlink()
                except OSError:
                    pass
            removed += 1
        else:
            kept.append(entry)

    if removed:
        _save_backup_index(kept)

    return removed


# ── CSS 注入核心逻辑 ──

def _extract_original_layout(html: str) -> str:
    """
    从原始 HTML 的 <style> 块中提取需要保护的属性，
    在增强 CSS 注入后追加为高优先级规则，防止增强 CSS 破坏原始页面的功能性结构。

    保护策略：
    - 扫描原始 <style> 中 **所有选择器** 的布局/尺寸/排版/交互属性
    - 将这些属性以高优先级规则追加在增强 CSS 末尾（覆盖增强 CSS 对结构的破坏）
    - 不保护视觉属性（color / background / font / border / shadow 等）

    保护属性分三类：
    A. 布局结构（完整保护）
       display / align-items / justify-content / align-content /
       flex-direction / flex-wrap / flex / gap / column-gap / row-gap /
       grid-template-columns / grid-template-rows / grid-template-areas /
       width / height / min-width / min-height / max-width / max-height /
       overflow / overflow-x / overflow-y / position / top/right/bottom/left /
       z-index / flex-shrink / flex-grow / flex-basis / order

    B. 文字排版结构（条件保护：只保护非默认值）
       writing-mode / direction / unicode-bidi / white-space /
       word-break / overflow-wrap / word-wrap

    C. 交互行为（条件保护：只保护非默认值）
       pointer-events / user-select / cursor
    """
    # ── A. 布局结构：完整保护 ──
    LAYOUT_PROPS = [
        "display", "align-items", "justify-content", "align-content",
        "flex-direction", "flex-wrap", "flex", "flex-shrink", "flex-grow", "flex-basis", "order",
        "gap", "column-gap", "row-gap",
        "grid-template-columns", "grid-template-rows", "grid-template-areas",
        "width", "height", "min-width", "min-height", "max-width", "max-height",
        "overflow", "overflow-x", "overflow-y",
        "position", "top", "right", "bottom", "left", "z-index",
        "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
        "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
        "box-sizing",
    ]

    # ── B. 文字排版结构：只保护非默认值 ──
    TYPOGRAPHY_DEFAULTS = {
        "writing-mode":   "horizontal-tb",
        "direction":      "ltr",
        "unicode-bidi":   "normal",
        "white-space":    "normal",
        "word-break":     "normal",
        "overflow-wrap":  "normal",
        "word-wrap":      "normal",
    }

    # ── C. 交互行为：只保护非默认值 ──
    INTERACTION_DEFAULTS = {
        "pointer-events": "auto",
        "user-select":    "auto",
        "cursor":         {"auto", "default"},
    }

    def _is_default(prop: str, val: str) -> bool:
        val = val.strip().lower()
        if prop in TYPOGRAPHY_DEFAULTS:
            return val == TYPOGRAPHY_DEFAULTS[prop]
        if prop in INTERACTION_DEFAULTS:
            d = INTERACTION_DEFAULTS[prop]
            if isinstance(d, set):
                return val in d
            return val == d
        return False

    # 收集原始 <style> 块（排除受保护的）
    style_blocks = re.findall(
        r'<style\b(?![^>]*data-go-live-layer)(?![^>]*id=["\'])[^>]*>(.*?)</style>',
        html, flags=re.DOTALL | re.IGNORECASE
    )

    # selector -> {prop: value}
    protected: dict[str, dict[str, str]] = {}
    all_cond_props = list(TYPOGRAPHY_DEFAULTS) + list(INTERACTION_DEFAULTS)

    for block in style_blocks:
        # 提取所有 selector { declarations } 块（简单非嵌套规则）
        for m in re.finditer(r'([^{}/]+)\{([^}]*)\}', block):
            selector = m.group(1).strip()
            declarations = m.group(2)

            # 跳过 @media / @keyframes 等 at-rule
            if selector.startswith('@'):
                continue

            if selector not in protected:
                protected[selector] = {}
            sel_props = protected[selector]

            # A: 布局属性——完整保护
            for prop in LAYOUT_PROPS:
                if prop in sel_props:
                    continue
                pm = re.search(
                    rf'(?<![a-z-]){re.escape(prop)}\s*:\s*([^;]+)',
                    declarations, re.IGNORECASE
                )
                if pm:
                    sel_props[prop] = pm.group(1).strip().rstrip(';')

            # B+C: 排版/交互——只保护非默认值
            for prop in all_cond_props:
                if prop in sel_props:
                    continue
                pm = re.search(
                    rf'(?<![a-z-]){re.escape(prop)}\s*:\s*([^;]+)',
                    declarations, re.IGNORECASE
                )
                if pm:
                    val = pm.group(1).strip().rstrip(';')
                    if not _is_default(prop, val):
                        sel_props[prop] = val

    # 过滤掉没有命中任何属性的选择器
    protected = {sel: props for sel, props in protected.items() if props}

    if not protected:
        return ""

    lines = ["\n/* ── 保留原始布局属性（防止增强CSS破坏页面结构） ── */"]
    for selector, props in protected.items():
        decls = ";\n    ".join(f"{k}: {v} !important" for k, v in props.items())
        lines.append(f"{selector} {{\n    {decls};\n}}")

    return "\n".join(lines)


def _strip_layout_from_css(css: str) -> str:
    """
    从增强 CSS 中删除所有布局/尺寸/盒模型属性，只保留视觉属性。
    这样增强 CSS 追加在原始 <style> 后面时，不会破坏原始页面的结构。

    删除的属性（布局/结构类）：
      display / position / top/right/bottom/left / z-index /
      width / height / min-* / max-* /
      margin / padding / box-sizing /
      flex* / align-* / justify-* / order / gap / column-gap / row-gap /
      grid-* / float / clear / overflow* /
      white-space / word-break / overflow-wrap / word-wrap
    """
    LAYOUT_PROP_PATTERN = re.compile(
        r'(?<![a-z-])('
        r'display|position|top|right|bottom|left|z-index'
        r'|width|height|min-width|min-height|max-width|max-height'
        r'|margin|margin-top|margin-right|margin-bottom|margin-left'
        r'|padding|padding-top|padding-right|padding-bottom|padding-left'
        r'|box-sizing|float|clear'
        r'|flex|flex-direction|flex-wrap|flex-grow|flex-shrink|flex-basis|flex-flow'
        r'|align-items|align-content|align-self'
        r'|justify-content|justify-items|justify-self'
        r'|order|gap|column-gap|row-gap'
        r'|grid-template-columns|grid-template-rows|grid-template-areas'
        r'|grid-column|grid-row|grid-area|grid'
        r'|overflow|overflow-x|overflow-y'
        r'|white-space|word-break|overflow-wrap|word-wrap'
        r')\s*:[^;}\n]+[;]?',
        re.IGNORECASE,
    )

    def process_rule(m: re.Match) -> str:
        """处理一个 selector { declarations } 块，删除布局属性"""
        selector = m.group(1)
        declarations = m.group(2)
        # 删除布局属性声明
        cleaned = LAYOUT_PROP_PATTERN.sub('', declarations)
        # 清理多余空行
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        # 如果声明全空了，整个规则删掉
        if not re.search(r'[a-z-]+\s*:', cleaned, re.IGNORECASE):
            return ''
        return f'{selector}{{{cleaned}}}'

    # 处理普通规则块（排除 @keyframes 内部）
    result = re.sub(
        r'([^{@][^{]*)\{([^{}]*)\}',
        process_rule,
        css,
    )
    return result


def inject_css(html: str, css: str, style_key: str) -> str:
    """
    将增强 CSS 注入到 HTML。

    策略（方案B）：
    - 保留原始 <style> 标签（不删除），原始布局/结构属性完整保留
    - 对增强 CSS 做视觉属性过滤（删除布局/尺寸属性），只追加视觉风格
    - 增强 CSS 追加在原始 <style> 之后，视觉属性后来者居上
    - 保留 <link rel="stylesheet"> 外部引用
    - 保留 <script> 标签
    - 保留行内 style="" 属性
    - 已有 <style data-css-style-enhanced> 则替换，无则插入
    - 插入位置：</head> 前 > <body 前 > 文档末尾
    """
    # Step 1: 自动标注 data-role（如果尚未标注）
    if _tag_html and 'data-role=' not in html:
        html, tagged_count = _tag_html(html)

    # Step 2: 构建增强 style 块
    enhanced_tag = (
        f'<style data-css-style-enhanced="true">\n'
        f'/* CSS风格：{style_key} */\n'
        f'{css}'
        f'</style>'
    )

    # Step 2.5: 字体预加载（幂等：已有 preload 则跳过；应用自定义字体 CDN 前缀）
    _preload_url = apply_font_cdn_base(FONT_PRELOADS.get(style_key or "", ""))
    if _preload_url and 'rel="preload"' not in html:
        _preload_tag = (
            f'<link rel="preload" href="{_preload_url}" '
            f'as="style" onload="this.onload=null;this.rel=\'stylesheet\'">\n'
            f'<noscript><link rel="stylesheet" href="{_preload_url}"></noscript>\n'
        )
        _head_open = re.search(r'<head\b[^>]*>', html, re.IGNORECASE)
        _head_close = re.search(r'</head\s*>', html, re.IGNORECASE)
        _body_open = re.search(r'<body\b', html, re.IGNORECASE)
        if _head_open:
            # 插到 <head> 开标签后
            _insert = _head_open.end()
            html = html[:_insert] + "\n" + _preload_tag + html[_insert:]
        elif _head_close:
            # 插到 </head> 前
            html = html[:_head_close.start()] + _preload_tag + html[_head_close.start():]
        elif _body_open:
            # 没有 head，插到 <body> 前
            html = html[:_body_open.start()] + _preload_tag + html[_body_open.start():]
        else:
            # 兜底：插到文档开头
            html = _preload_tag + html

    # Step 3: 检查是否已有 enhanced 标签，有则替换
    existing_pattern = re.compile(
        r'<style\s+data-css-style-enhanced[^>]*>.*?</style>',
        re.DOTALL | re.IGNORECASE,
    )
    if existing_pattern.search(html):
        html = existing_pattern.sub(lambda _: enhanced_tag, html, count=1)
        return html

    # Step 4: 插入位置：</head> 前 > <body 前 > 末尾
    head_close = re.search(r'</head\s*>', html, re.IGNORECASE)
    if head_close:
        pos = head_close.start()
        return html[:pos] + enhanced_tag + "\n" + html[pos:]

    body_open = re.search(r'<body\b', html, re.IGNORECASE)
    if body_open:
        pos = body_open.start()
        return html[:pos] + enhanced_tag + "\n" + html[pos:]

    return html + "\n" + enhanced_tag


def strip_inline_styles(html: str) -> str:
    """移除所有行内 style="" 属性。"""
    # 处理双引号
    html = re.sub(r'\s+style="[^"]*"', '', html)
    # 处理单引号
    html = re.sub(r"\s+style='[^']*'", '', html)
    return html


def build_css_style_json(style_key: str) -> str:
    """构建 cssStyle JSON 字符串。"""
    CST = timezone(timedelta(hours=8))
    return json.dumps(
        {
            "enhanced": True,
            "style": style_key,
            "updatedAt": datetime.now(tz=CST).isoformat(),
        },
        ensure_ascii=False,
    )


def enhance(
    html: str,
    style_key: str,
    source_label: str,
    strip_inline: bool = False,
) -> tuple:
    """
    完整增强流程：备份 → 注入 CSS → 可选清除行内样式。
    返回 (增强后html, 备份路径)。
    """
    # 1. 保存备份（失败时 raise RuntimeError）
    backup_path = save_backup(html, source_label, style_key)

    # 2. 加载 CSS
    css = load_css(style_key)

    # 3. 注入 CSS
    enhanced_html = inject_css(html, css, style_key)

    # 4. 可选：清除行内样式
    if strip_inline:
        enhanced_html = strip_inline_styles(enhanced_html)

    return enhanced_html, backup_path


# ── CLI 入口 ──

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CSS 风格增强工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用 CSS 风格",
    )
    group.add_argument(
        "--list-backups",
        action="store_true",
        dest="list_backups",
        help="列出备份记录",
    )
    group.add_argument(
        "--restore",
        metavar="BACKUP_ID",
        help="从备份恢复 HTML（需同时指定 --target）",
    )
    group.add_argument(
        "--clean",
        action="store_true",
        help=f"清理超过 {BACKUP_TTL_DAYS} 天的过期备份",
    )

    parser.add_argument(
        "--source",
        metavar="LABEL",
        help="配合 --list-backups，按 source_label 精确过滤",
    )
    parser.add_argument(
        "--target",
        metavar="PATH",
        help="配合 --restore，指定目标文件路径",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="配合 --restore，跳过确认提示",
    )

    args = parser.parse_args()

    if args.list:
        list_styles()
        return

    if args.list_backups:
        source = getattr(args, "source", None)
        backups = list_backups(source_label=source)
        if not backups:
            print("📂 暂无备份记录。")
            return
        print(f"\n📂 CSS 增强备份列表（共 {len(backups)} 条）：\n")
        for i, b in enumerate(backups, 1):
            print(f"  {i}. [{b['created_at'][:19]}] 来源: {b['source_label']}  风格: {b['style_key']}")
            print(f"     backup_id: {b['backup_id']}")
        return

    if args.restore:
        if not args.target:
            parser.error("--restore 需要同时指定 --target <路径>")
        target_path = Path(args.target).resolve()
        ok = restore_backup(args.restore, target_path, yes=args.yes)
        if ok:
            print(f"✅ 已恢复到：{target_path}")
        else:
            print("ℹ️  已取消恢复。")
        return

    if args.clean:
        count = clean_expired_backups()
        print(f"✅ 已清理 {count} 条过期备份。")
        return


if __name__ == "__main__":
    main()
