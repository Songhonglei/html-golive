"""
clone_patcher.py — HTML 克隆后处理补丁器
对克隆后的 HTML 做标准化修复：字体镜像替换、来源标记注入、属性清理、viewport 补全，
以及 golive 注入模块的敏感配置脱敏。
只依赖标准库，不需要 bs4。
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from golive.i18n import t as _t


# ── 字体 URL 替换表 ───────────────────────────────────────────────────────────

FONT_REPLACEMENTS: dict[str, str] = {
    "fonts.googleapis.com":         "fonts.loli.net",
    "fonts.gstatic.com":            "gstatic.loli.net",
    "ajax.googleapis.com":          "ajax.loli.net",
    "themes.googleusercontent.com": "themes.loli.net",
}


# ── 步骤1：字体 URL 替换 ───────────────────────────────────────────────────────

def _replace_fonts(html: str) -> tuple[str, int]:
    """
    将 Google Fonts / gstatic 等域名替换为国内镜像。

    Returns
    -------
    (patched_html, replace_count)
    """
    count = 0
    for original_host, mirror_host in FONT_REPLACEMENTS.items():
        pattern = re.compile(re.escape(original_host), re.IGNORECASE)
        new_html, n = pattern.subn(mirror_host, html)
        if n:
            print(
                _t("clone_patcher.font_replace", orig=original_host, mirror=mirror_host, count=n),
                file=sys.stderr,
            )
            count += n
            html = new_html
    return html, count


def _inject_font_comment(html: str, replaced: bool) -> str:
    """在 </head> 前注入字体替换说明注释（仅当有替换时）。"""
    if not replaced:
        return html
    comment = "<!-- golive: Google Fonts replaced with mirror source for better access -->\n"
    # 大小写不敏感匹配 </head>
    new_html, n = re.subn(
        r'(</head\s*>)',
        comment + r'\1',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if n:
        print(_t("clone_patcher.font_comment_injected"), file=sys.stderr)
    else:
        # 没有 </head> 标签时追加到开头
        print(_t("clone_patcher.font_comment_no_head"), file=sys.stderr)
        new_html = comment + html
    return new_html


# ── 步骤2：注入来源标记 ───────────────────────────────────────────────────────

def _inject_source_marker(html: str) -> str:
    """在 </body> 前注入克隆时间戳标记。"""
    iso_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    marker = f"<!-- cloned by golive clone at {iso_time} -->\n"
    new_html, n = re.subn(
        r'(</body\s*>)',
        marker + r'\1',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if n:
        print(_t("clone_patcher.source_marker_injected", time=iso_time), file=sys.stderr)
    else:
        # 没有 </body>，追加到末尾
        new_html = html + "\n" + marker
        print(
            _t("clone_patcher.source_marker_no_body", time=iso_time),
            file=sys.stderr,
        )
    return new_html


# ── 步骤3：清理问题属性 ───────────────────────────────────────────────────────

def _remove_integrity(html: str) -> tuple[str, int]:
    """移除所有 integrity="..." 属性，避免 SRI 校验失败。"""
    pattern = re.compile(
        r'\s+integrity\s*=\s*(?:"[^"]*"|\'[^\']*\')',
        re.IGNORECASE,
    )
    new_html, n = pattern.subn("", html)
    if n:
        print(_t("clone_patcher.integrity_removed", count=n), file=sys.stderr)
    return new_html, n


def _remove_crossorigin(html: str) -> tuple[str, int]:
    """移除所有 crossorigin="anonymous" 属性。"""
    # 匹配 crossorigin="anonymous" 或 crossorigin='anonymous' 或裸 crossorigin
    pattern = re.compile(
        r'''\s+crossorigin\s*=\s*(?:"anonymous"|'anonymous'|anonymous)''',
        re.IGNORECASE,
    )
    new_html, n = pattern.subn("", html)
    if n:
        print(_t("clone_patcher.crossorigin_removed", count=n), file=sys.stderr)
    return new_html, n


def _clean_attributes(html: str) -> str:
    """组合清理 integrity 和 crossorigin 属性。"""
    html, _ = _remove_integrity(html)
    html, _ = _remove_crossorigin(html)
    return html


# ── 步骤4：敏感配置脱敏（html-go-live 注入模块）────────────────────────────────

# BI 直连模块敏感字段：字段名 → 占位符说明
_BI_SENSITIVE_FIELDS: dict[str, str] = {
    "dataRef":        "__PLACEHOLDER_DATA_REF__",
    "storageUrl":     "__PLACEHOLDER_STORAGE_URL__",
    "datasetId":      "__PLACEHOLDER_DATASET_ID__",
    "datasetName":    "__PLACEHOLDER_DATASET_NAME__",
    "query":          "__PLACEHOLDER_QUERY__",
    "aimiBase":       "__PLACEHOLDER_AIMI_BASE__",
    "aimiServiceTag": "__PLACEHOLDER_AIMI_SERVICE_TAG__",
    "aimiProjectId":  "__PLACEHOLDER_AIMI_PROJECT_ID__",
    "analysisUrl":    "__PLACEHOLDER_ANALYSIS_URL__",
}

# 在线数据存储模块敏感字段
_TEMPLATE_SENSITIVE_FIELDS: dict[str, str] = {
    "modelCode": "__PLACEHOLDER_MODEL_CODE__",
    "version":   "__PLACEHOLDER_DATA_VERSION__",
    "userId":    "__PLACEHOLDER_USER_ID__",
    "baseUrl":   "__PLACEHOLDER_BASE_URL__",
}

# 字段说明（用于告知用户需要填什么）
_FIELD_DESCRIPTIONS: dict[str, str] = {
    "dataRef":        "数据凭证 data_ref",
    "storageUrl":     "对象存储地址",
    "datasetId":      "数据集 ID",
    "datasetName":    "数据集名称",
    "query":          "取数查询描述",
    "aimiBase":       "数据服务地址",
    "aimiServiceTag": "数据服务标识",
    "aimiProjectId":  "数据服务项目 ID",
    "analysisUrl":    "BI 分析页链接",
    "modelCode":      "在线数据存储 Model Code（业务模型标识符）",
    "version":        "数据版本号",
    "userId":         "用户 ID",
    "baseUrl":        "数据网关服务地址",
}


def _scrub_script_block(script_content: str, field_map: dict[str, str]) -> tuple[str, list[str]]:
    """
    对单个 <script> 块的文本内容做字段脱敏。
    支持两种值格式：
      - JSON 字符串值：  "dataRef": "..."
      - JS 单引号字符串：modelCode : 'ai_copilot_report'
      - JS 数字值：      aimiProjectId: 1

    返回 (脱敏后的 script 内容, 被清理的字段名列表)
    """
    scrubbed_fields: list[str] = []
    result = script_content

    for field, placeholder in field_map.items():
        # 匹配三种格式：双引号值 / 单引号值 / 数字值
        pattern = re.compile(
            r'(["\']?' + re.escape(field) + r'["\']?\s*[:]\s*)'  # key:
            r'('
            r'"[^"]*"'          # "双引号值"
            r"|'[^']*'"         # '单引号值'
            r'|[0-9]+'          # 数字
            r')',
            re.MULTILINE,
        )
        new_content, n = pattern.subn(
            lambda m, p=placeholder: m.group(1) + f'"{p}"',
            result,
        )
        if n:
            scrubbed_fields.append(field)
            result = new_content

    return result, scrubbed_fields


def _scrub_sensitive_configs(html: str) -> tuple[str, list[dict]]:
    """
    检测并脱敏 html-go-live 注入的两类数据模块：
      - <script id="bi-data-layer">    → BI 数据直连敏感字段
      - <script id="template-data-layer"> → 在线数据存储敏感字段

    返回：
      (脱敏后的 HTML, findings)
      findings 是列表，每项：
        {
          "module": "bi-data-layer" | "template-data-layer",
          "module_label": str,
          "scrubbed_fields": [{"name": str, "desc": str}, ...]
        }
    """
    findings: list[dict] = []

    modules = [
        {
            "script_id":   "bi-data-layer",
            "label":       "BI 数据直连模块（__BI_CONFIG__）",
            "field_map":   _BI_SENSITIVE_FIELDS,
        },
        {
            "script_id":   "template-data-layer",
            "label":       "在线数据存储模块（TemplateAPI）",
            "field_map":   _TEMPLATE_SENSITIVE_FIELDS,
        },
    ]

    for mod in modules:
        script_id = mod["script_id"]
        # 匹配完整的 <script id="..."> ... </script> 块（id 可含单/双引号）
        pattern = re.compile(
            r'(<script[^>]+id=["\']' + re.escape(script_id) + r'["\'][^>]*>)'
            r'(.*?)'
            r'(</script\s*>)',
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(html)
        if not match:
            continue  # 该模块不存在，跳过

        open_tag   = match.group(1)
        content    = match.group(2)
        close_tag  = match.group(3)

        scrubbed_content, scrubbed_fields = _scrub_script_block(content, mod["field_map"])

        if scrubbed_fields:
            # 在 script 块开头插入醒目注释
            warning_comment = (
                "\n// ⚠️  [html-go-live clone] 敏感配置已清除，发布前必须重新填写下列字段：\n"
                + "".join(
                    f"//   {f}  →  {_FIELD_DESCRIPTIONS.get(f, f)}\n"
                    for f in scrubbed_fields
                )
                + "//\n"
            )
            scrubbed_content = warning_comment + scrubbed_content

            new_block = open_tag + scrubbed_content + close_tag
            html = html[:match.start()] + new_block + html[match.end():]

            findings.append({
                "module":        script_id,
                "module_label":  mod["label"],
                "scrubbed_fields": [
                    {"name": f, "desc": _FIELD_DESCRIPTIONS.get(f, f)}
                    for f in scrubbed_fields
                ],
            })
            print(
                _t("clone_patcher.scrub_ok", script_id=script_id,
                   count=len(scrubbed_fields), fields=", ".join(scrubbed_fields)),
                file=sys.stderr,
            )
        else:
            print(
                _t("clone_patcher.scrub_no_match", script_id=script_id),
                file=sys.stderr,
            )

    return html, findings


# ── 步骤5：meta viewport 补全 ─────────────────────────────────────────────────

def _ensure_viewport(html: str) -> str:
    """如果 <head> 里没有 viewport meta，则自动注入。"""
    # 检测是否已存在 viewport
    viewport_pattern = re.compile(
        r'<meta[^>]+name\s*=\s*["\']viewport["\']',
        re.IGNORECASE,
    )
    if viewport_pattern.search(html):
        return html  # 已存在，不重复注入

    viewport_tag = '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'

    # 尝试注入到 <head> 标签之后
    new_html, n = re.subn(
        r'(<head[^>]*>)',
        r'\1\n' + viewport_tag,
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if n:
        print(_t("clone_patcher.viewport_injected_head"), file=sys.stderr)
        return new_html

    # 没有 <head>，尝试注入到 </head> 前
    new_html, n = re.subn(
        r'(</head\s*>)',
        viewport_tag + r'\1',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if n:
        print(_t("clone_patcher.viewport_injected_close"), file=sys.stderr)
        return new_html

    # 既无 <head> 也无 </head>，追加到文档开头
    print(_t("clone_patcher.viewport_no_head"), file=sys.stderr)
    return viewport_tag + html


# ── 步骤6：后端接口重写 ───────────────────────────────────────────────────────

def patch_backend_origin(html: str, backend_origin: str) -> tuple[str, dict]:
    """
    将 HTML 中两类"迁移后失效"的接口地址重写为 backend_origin。

    处理范围：
    1. 相对路径接口（字符串字面量中以 / 开头的 API 路径）：
       fetch('/api/xxx')      → fetch('http://origin/api/xxx')
       axios.post('/health')  → axios.post('http://origin/health')
       .open('GET', '/api/')  → .open('GET', 'http://origin/api/')
    2. localhost / 127.0.0.1 接口（任意端口）：
       fetch('http://localhost:18902/api/xxx') → fetch('http://origin/api/xxx')

    不处理：
    - 已有完整域名的 URL（http(s)://非localhost）
    - 静态资源路径（.js/.css/.png 等）
    - 注释行（// 开头）

    Parameters
    ----------
    html : str
        原始 HTML 字符串。
    backend_origin : str
        目标服务地址，形如 "http://10.40.85.213:19902"（末尾不含 /）。

    Returns
    -------
    (patched_html, summary)
        summary: {"relative_count": int, "localhost_count": int}
    """
    import re as _re

    origin = backend_origin.rstrip("/")

    # ── 静态资源后缀（不重写） ──
    _static_ext = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                   ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map")

    def _is_api_path(p: str) -> bool:
        clean = p.split("?")[0].split("#")[0]
        return not any(clean.lower().endswith(ext) for ext in _static_ext)

    relative_count = 0
    localhost_count = 0

    # ── 1. localhost / 127.0.0.1 → origin ────────────────────────────────────
    # 直接替换 URL 中的 scheme://host:port 部分，不依赖外层调用方式
    # 匹配：http://localhost:PORT 或 http://127.0.0.1:PORT（端口可选）
    _loc_pat = _re.compile(
        r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?"
    )

    def _replace_localhost(m):
        nonlocal localhost_count
        localhost_count += 1
        return origin

    html = _loc_pat.sub(_replace_localhost, html)

    # ── 2. 相对路径 → origin + path ──────────────────────────────────────────
    # 匹配 fetch('/path') / axios.get('/path') / axios.post('/path')
    # group(1)=调用前缀含开引号, group(2)=匹配用的引号字符, group(3)=路径, group(4)=闭引号
    _rel_fetch_pat = _re.compile(
        r"""((?:fetch|axios\.(?:get|post))\s*\(\s*)(['"])(\/[^'"?\s][^'"]*)(\2)"""
    )

    def _replace_relative_fetch(m):
        nonlocal relative_count
        call  = m.group(1)
        quote = m.group(2)
        path  = m.group(3)
        eq    = m.group(4)
        if not _is_api_path(path) or path.startswith("//"):
            return m.group(0)
        relative_count += 1
        return f"{call}{quote}{origin}{path}{eq}"

    html = _rel_fetch_pat.sub(_replace_relative_fetch, html)

    # 匹配 XHR: .open("GET", "/path")
    _rel_xhr_pat = _re.compile(
        r"""(\.open\s*\(\s*['"][A-Z]+['"]\s*,\s*)(['"])(\/[^'"?\s][^'"]*)(\2)"""
    )

    def _replace_relative_xhr(m):
        nonlocal relative_count
        call  = m.group(1)
        quote = m.group(2)
        path  = m.group(3)
        eq    = m.group(4)
        if not _is_api_path(path) or path.startswith("//"):
            return m.group(0)
        relative_count += 1
        return f"{call}{quote}{origin}{path}{eq}"

    html = _rel_xhr_pat.sub(_replace_relative_xhr, html)

    summary = {
        "relative_count": relative_count,
        "localhost_count": localhost_count,
    }

    if relative_count or localhost_count:
        print(
            _t("clone_patcher.backend_rewrite_summary",
               rel_count=relative_count, loc_count=localhost_count, origin=origin),
            file=sys.stderr,
        )
    else:
        print(_t("clone_patcher.backend_rewrite_none"), file=sys.stderr)

    return html, summary


# ── 主入口 ────────────────────────────────────────────────────────────────────

def patch(html: str, notes: list | None = None, backend_origin: str = "") -> tuple[str, list[dict], dict]:
    """
    对 HTML 做全套后处理，返回 (修复后的 HTML, sensitive_findings)。

    Parameters
    ----------
    html : str
        原始 HTML 字符串。
    notes : list, optional
        外部传入的备注列表（保留参数，供未来扩展）。
    backend_origin : str, optional
        原始服务地址（如 "http://10.40.85.213:19902"）。
        非空时自动重写相对路径接口和 localhost 接口。

    Returns
    -------
    (str, list[dict], dict)
        - str：处理后的 HTML
        - list[dict]：敏感配置清理报告，每项含 module / module_label / scrubbed_fields
          空列表表示未发现任何 html-go-live 注入模块。
        - dict：后端接口重写摘要 {"relative_count": int, "localhost_count": int}
          未执行重写时两个字段均为 0。
    """
    if notes is None:
        notes = []

    # 空内容直接返回
    if not html or not html.strip():
        return html, [], {}

    print(_t("clone_patcher.start"), file=sys.stderr)

    # 1. 字体替换
    html, font_replace_count = _replace_fonts(html)
    html = _inject_font_comment(html, replaced=(font_replace_count > 0))

    # 2. 来源标记
    html = _inject_source_marker(html)

    # 3. 清理问题属性
    html = _clean_attributes(html)

    # 4. 敏感配置脱敏（html-go-live 注入模块）
    html, sensitive_findings = _scrub_sensitive_configs(html)

    # 5. viewport 补全
    html = _ensure_viewport(html)

    # 6. 后端接口重写（有 backend_origin 时执行）
    backend_summary: dict = {"relative_count": 0, "localhost_count": 0}
    if backend_origin and backend_origin.strip():
        html, backend_summary = patch_backend_origin(html, backend_origin.strip())

    print(_t("clone_patcher.done"), file=sys.stderr)
    return html, sensitive_findings, backend_summary


# ── CLI 入口（方便调试）────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(_t("clone_patcher.usage"), file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else None

    try:
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            raw_html = f.read()
    except OSError as e:
        print(_t("clone_patcher.read_failed", path=input_path, error=e), file=sys.stderr)
        sys.exit(1)

    patched_html, findings = patch(raw_html)

    if findings:
        print(_t("clone_patcher.scrub_summary"), file=sys.stderr)
        for f in findings:
            fields = [x["name"] for x in f["scrubbed_fields"]]
            print(_t("clone_patcher.scrub_summary_item", label=f['module_label'], fields=", ".join(fields)), file=sys.stderr)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(patched_html)
            print(_t("clone_patcher.output_written", path=output_path), file=sys.stderr)
        except OSError as e:
            print(_t("clone_patcher.write_failed", path=output_path, error=e), file=sys.stderr)
            sys.exit(1)
    else:
        print(patched_html)
