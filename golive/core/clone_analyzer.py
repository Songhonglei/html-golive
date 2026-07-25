"""
clone_analyzer.py — HTML 克隆迁移可行性分析器
扫描 HTML 源码中的 API 依赖、字体问题、凭证泄露等，返回结构化分析报告。
"""

import re
from html.parser import HTMLParser
from urllib.parse import urlparse


# ── 常量 ──────────────────────────────────────────────────────────────────────

STATIC_SUFFIXES = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".otf", ".map",
)

CDN_HOSTS = (
    "unpkg.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
)

FONT_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "ajax.googleapis.com",
    "themes.googleusercontent.com",
)

PATTERNS = {
    "fetch":      r'fetch\s*\(\s*["\']([^"\']+)["\']',
    "axios_get":  r'axios\.get\s*\(\s*["\']([^"\']+)["\']',
    "axios_post": r'axios\.post\s*\(\s*["\']([^"\']+)["\']',
    "xhr":        r'\.open\s*\(\s*["\'](\w+)["\'],\s*["\']([^"\']+)["\']',
    "websocket":  r'new\s+WebSocket\s*\(\s*["\']([^"\']+)["\']',
    "api_key":    r'(?:(?:api[_-]?key|apikey|bearer|Authorization)\s*[:=]\s*["\']([A-Za-z0-9\-_\.]{20,})["\']|\bsk-[A-Za-z0-9\-]{20,})',
}


# ── 内联 Script 提取 ──────────────────────────────────────────────────────────

class _ScriptExtractor(HTMLParser):
    """提取所有内联 <script> 块及其位置序号。"""

    def __init__(self):
        super().__init__()
        self._in_script = False
        self._current = []
        self.scripts = []   # list of (index, text)
        self._index = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            # 跳过外链 script（有 src 属性）
            attr_dict = dict(attrs)
            if "src" not in attr_dict:
                self._in_script = True
                self._current = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._in_script:
            self._index += 1
            self.scripts.append((self._index, "".join(self._current)))
            self._in_script = False
            self._current = []

    def handle_data(self, data):
        if self._in_script:
            self._current.append(data)


def _extract_inline_scripts(html: str) -> list[tuple[int, str]]:
    """返回 [(序号, 脚本文本), ...]，序号从1开始。"""
    extractor = _ScriptExtractor()
    extractor.feed(html)
    return extractor.scripts


# ── 过滤规则 ──────────────────────────────────────────────────────────────────

def _should_skip_url(url: str) -> bool:
    """如果 URL 属于静态资源、CDN 或本地地址，返回 True（跳过）。"""
    if not url.startswith("http"):
        return True  # 相对路径（由 backend_rewrite 专门处理，此处跳过）

    # 本地地址（由 backend_rewrite 专门处理，此处跳过）
    if "localhost" in url or "127.0.0.1" in url:
        return True

    # 常见 CDN
    for cdn in CDN_HOSTS:
        if cdn in url:
            return True

    # 静态资源后缀（去掉查询参数后判断）
    path = url.split("?")[0].split("#")[0]
    if any(path.lower().endswith(s) for s in STATIC_SUFFIXES):
        return True

    return False


# ── 用途推测 ──────────────────────────────────────────────────────────────────

def _guess_purpose(url: str, ptype: str) -> str:
    u = url.lower()

    if ptype == "websocket" or u.startswith("wss://") or u.startswith("ws://"):
        return "实时推送（迁移后失效）"

    ai_providers = ["openai", "qwen", "kimi", "claude", "glm"]
    if any(p in u for p in ai_providers):
        return "AI模型接口（需替换API Key）"

    if any(k in u for k in ["/chat", "/completion", "/message"]):
        return "AI对话接口（需要API Key）"

    if any(k in u for k in ["/auth", "/login", "/token"]):
        return "鉴权接口"

    if any(k in u for k in ["/api/data", "/fetch", "/query"]):
        return "数据获取接口"

    return "外部接口（具体用途未知）"


def _make_suggestion(guess: str, url: str) -> str:
    if "AI模型接口" in guess or "AI对话接口" in guess:
        return f"需替换 API Key，并确认目标环境可访问 {url}"
    if "实时推送" in guess:
        return f"WebSocket 在纯静态托管环境下无法直接使用，考虑改用轮询或后端代理"
    if "鉴权接口" in guess:
        return f"鉴权接口需要后端支持，迁移后请确认跨域配置"
    if "数据获取接口" in guess:
        return f"请确认 {url} 在目标环境可访问，并正确处理 CORS"
    return f"请确认 {url} 在目标环境中可正常访问"


# ── 字体分析 ──────────────────────────────────────────────────────────────────

def _analyze_fonts(html: str) -> list[dict]:
    issues = []
    # 查找所有引用字体相关域名的 URL
    font_pattern = re.compile(
        r'(?:href|src|url)\s*[=\(]\s*["\']?(https?://[^\s"\'>\)]+)["\']?',
        re.IGNORECASE,
    )
    for m in font_pattern.finditer(html):
        url = m.group(1)
        for host in FONT_HOSTS:
            if host in url:
                # Google Fonts / gstatic 系列可替换为 loli.net 镜像
                replaceable = host in (
                    "fonts.googleapis.com",
                    "fonts.gstatic.com",
                    "ajax.googleapis.com",
                    "themes.googleusercontent.com",
                )
                issues.append({"original": url, "replaceable": replaceable})
                break
    return issues


# ── localStorage 检测 ─────────────────────────────────────────────────────────

def _has_localstorage(scripts: list[tuple[int, str]]) -> bool:
    pattern = re.compile(r'localStorage\s*[\.\[]', re.IGNORECASE)
    return any(pattern.search(text) for _, text in scripts)


# ── 核心分析 ──────────────────────────────────────────────────────────────────

def _detect_mpa_links(html: str, base_url: str = "") -> list[str]:
    """
    检测页面是否是多页应用（MPA）：
    扫描所有 <a href="..."> 中跳转到其他 .html 页面的链接。

    兼容两种来源：
    - requests 直连：href 保留相对路径（points_detail.html）
    - Firecrawl 渲染：href 被补全为绝对 URL（https://host/points_detail.html）

    对绝对 URL：提取 path 部分判断是否以 .html 结尾，
    同时排除与当前页相同的 URL（即自链）。
    返回去重后的链接列表（保留原始 href 值）。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # bs4 未安装时跳过多页检测，不中断主流程
        # 安装方式：pip install beautifulsoup4
        return []
    import urllib.parse as _up
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()

    # 提取当前页路径，用于排除自链
    current_path = _up.urlparse(base_url).path if base_url else ""

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href:
            continue
        # 跳过无意义链接
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        if href.startswith(("http://", "https://", "//")):
            # 绝对 URL：提取 path 判断是否为 .html 页面
            parsed = _up.urlparse(href)
            path_part = parsed.path.split("?")[0].split("#")[0]
            if not path_part.endswith(".html"):
                continue
            # 排除自链（与 base_url 相同路径）
            if current_path and parsed.path == current_path:
                continue
            # 用 path 部分去重（不同查询参数视为同一页面）
            dedup_key = path_part
        else:
            # 相对路径
            path_part = href.split("?")[0].split("#")[0]
            if not path_part.endswith(".html"):
                continue
            dedup_key = path_part

        if dedup_key not in seen:
            seen.add(dedup_key)
            found.append(href)

    return found


def _detect_backend_issues(scripts: list[tuple[int, str]], base_url: str = "") -> dict:
    """
    检测两类需要重写的后端接口：
    1. 相对路径接口：fetch('/api/xxx')、fetch('/health') 等以 / 开头的路径
    2. localhost/127.0.0.1 接口：fetch('http://localhost:PORT/xxx')

    同时尝试从 base_url 推断原始服务地址：
    - base_url 为非 localhost 地址 → 直接用其 scheme+host+port
    - base_url 为 localhost/127.0.0.1 → 无法推断，需用户提供

    Returns
    -------
    dict:
        {
          "relative":  ["/api/fetch-oa", "/api/report", ...],   # 去重列表
          "localhost": ["http://localhost:18902/api/xxx", ...],  # 去重列表
          "inferred_origin": "http://10.40.85.213:19902",        # 推断出的服务地址，空串表示无法推断
        }
    """
    # 匹配相对路径接口（以 / 开头，排除 // 开头的 protocol-relative URL）
    # 针对 fetch / axios.get / axios.post / xhr.open / WebSocket 五种调用
    relative_pattern = re.compile(
        r'''(?:fetch|axios\.(?:get|post)|\.open\s*\(\s*['"]\w+['"],)\s*\(\s*['"](\/(?!\/)[\w\-/?.=&%#]+)['"]'''
        r'''|['"](\/(?!\/)[\w\-/?.=&%#]+)['"]''',
    )
    # 更精准：只匹配 fetch/axios/xhr 里第一个字符串参数是相对路径的情况
    fetch_relative = re.compile(
        r'''(?:fetch|axios\.get|axios\.post)\s*\(\s*['"](\\/(?!\\/)[\w\-/?.=&%#]+)['"]'''
    )
    # 简化版：直接扫 fetch('/xxx') 和 axios.xxx('/xxx')
    api_relative_pattern = re.compile(
        r'''(?:fetch|axios\.get|axios\.post)\s*\(\s*['"](\\/[^'"]+)['"]'''
    )

    # 重新用更稳健的写法
    _rel_pat = re.compile(
        r'''(?:fetch|axios\.(?:get|post))\s*\(\s*['"](\/[^'"?\s][^'"]*?)['"]'''
    )
    _loc_pat = re.compile(
        r'''(?:fetch|axios\.(?:get|post))\s*\(\s*['"]'''
        r'''(https?://(?:localhost|127\.0\.0\.1)(?::\d+)?[^'"]*?)['"]'''
    )
    # 也扫 XHR: .open("GET", "/api/xxx")
    _xhr_rel_pat = re.compile(
        r'''\.open\s*\(\s*['"][A-Z]+['"]\s*,\s*['"](\/[^'"?\s][^'"]*?)['"]'''
    )
    _xhr_loc_pat = re.compile(
        r'''\.open\s*\(\s*['"][A-Z]+['"]\s*,\s*['"]'''
        r'''(https?://(?:localhost|127\.0\.0\.1)(?::\d+)?[^'"]*?)['"]'''
    )

    relative_set: set[str] = set()
    localhost_set: set[str] = set()

    for _, script_text in scripts:
        for m in _rel_pat.finditer(script_text):
            path = m.group(1)
            # 排除协议相对 URL (//) 和纯锚点 (/#xxx)
            if not path.startswith("//"):
                relative_set.add(path)
        for m in _xhr_rel_pat.finditer(script_text):
            path = m.group(1)
            if not path.startswith("//"):
                relative_set.add(path)
        for m in _loc_pat.finditer(script_text):
            localhost_set.add(m.group(1))
        for m in _xhr_loc_pat.finditer(script_text):
            localhost_set.add(m.group(1))

    # 过滤：排除静态资源后缀（图片、字体等不是 API）
    _static_ext = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                   ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map")
    def _is_api_path(p: str) -> bool:
        clean = p.split("?")[0].split("#")[0]
        return not any(clean.lower().endswith(ext) for ext in _static_ext)

    relative_list = sorted(p for p in relative_set if _is_api_path(p))
    localhost_list = sorted(localhost_set)

    # 推断原始服务地址
    inferred_origin = ""
    if base_url:
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
        # 排除 localhost / 127.0.0.1（无法推断）
        if host and host not in ("localhost", "127.0.0.1"):
            scheme = parsed.scheme or "http"
            port_part = f":{parsed.port}" if parsed.port else ""
            inferred_origin = f"{scheme}://{host}{port_part}"

    return {
        "relative": relative_list,
        "localhost": localhost_list,
        "inferred_origin": inferred_origin,
    }


def analyze(html_content: str, base_url: str = "") -> dict:
    """
    扫描 HTML 源码，返回迁移可行性分析报告。

    Parameters
    ----------
    html_content : str
        完整的 HTML 字符串。

    Returns
    -------
    dict
        包含 api_deps、font_issues、score、warnings 等字段的结构化报告。
    """
    scripts = _extract_inline_scripts(html_content)

    api_deps: list[dict] = []
    has_credentials = False
    warnings: list[str] = []

    for script_idx, script_text in scripts:
        location = f"内联script第{script_idx}段"

        # credentials / api key 扫描（先做，避免误入 api_deps）
        for m in re.finditer(PATTERNS["api_key"], script_text, re.IGNORECASE):
            has_credentials = True
            warnings.append(
                f"{location} 中发现疑似 API Key 或 Bearer Token，请勿将凭证硬编码在前端代码中"
            )

        # fetch
        for m in re.finditer(PATTERNS["fetch"], script_text):
            url = m.group(1)
            if _should_skip_url(url):
                continue
            guess = _guess_purpose(url, "fetch")
            api_deps.append({
                "type": "fetch",
                "url": url,
                "method": "GET",
                "location": location,
                "guess": guess,
                "suggestion": _make_suggestion(guess, url),
            })

        # axios.get
        for m in re.finditer(PATTERNS["axios_get"], script_text):
            url = m.group(1)
            if _should_skip_url(url):
                continue
            guess = _guess_purpose(url, "axios")
            api_deps.append({
                "type": "axios",
                "url": url,
                "method": "GET",
                "location": location,
                "guess": guess,
                "suggestion": _make_suggestion(guess, url),
            })

        # axios.post
        for m in re.finditer(PATTERNS["axios_post"], script_text):
            url = m.group(1)
            if _should_skip_url(url):
                continue
            guess = _guess_purpose(url, "axios")
            api_deps.append({
                "type": "axios",
                "url": url,
                "method": "POST",
                "location": location,
                "guess": guess,
                "suggestion": _make_suggestion(guess, url),
            })

        # XHR: .open("METHOD", "url")
        for m in re.finditer(PATTERNS["xhr"], script_text):
            method = m.group(1).upper()
            url = m.group(2)
            if _should_skip_url(url):
                continue
            guess = _guess_purpose(url, "xhr")
            api_deps.append({
                "type": "xhr",
                "url": url,
                "method": method,
                "location": location,
                "guess": guess,
                "suggestion": _make_suggestion(guess, url),
            })

        # WebSocket
        for m in re.finditer(PATTERNS["websocket"], script_text):
            url = m.group(1)
            # WebSocket 不走 _should_skip_url（wss:// 不以 http 开头）
            if url.startswith("//"):
                url = "wss:" + url
            guess = _guess_purpose(url, "websocket")
            api_deps.append({
                "type": "websocket",
                "url": url,
                "method": "未知",
                "location": location,
                "guess": guess,
                "suggestion": _make_suggestion(guess, url),
            })

    # 字体分析
    font_issues = _analyze_fonts(html_content)
    unreplaceable_fonts = [f for f in font_issues if not f["replaceable"]]

    # localStorage
    localstorage_usage = _has_localstorage(scripts)

    # 多页应用检测：页面内是否有跳转到其他 .html 的内链（兼容相对路径和 Firecrawl 补全的绝对 URL）
    mpa_links = _detect_mpa_links(html_content, base_url=base_url)

    # ── 后端接口依赖检测（相对路径 + localhost/127.0.0.1）──────────────────────
    backend_issues = _detect_backend_issues(scripts, base_url=base_url)

    # 去重 api_deps（相同 type+url+method）
    seen = set()
    deduped_deps = []
    for dep in api_deps:
        key = (dep["type"], dep["url"], dep["method"])
        if key not in seen:
            seen.add(key)
            deduped_deps.append(dep)
    api_deps = deduped_deps

    external_apis_count = len(api_deps)

    # ── 评分 ──
    score = 100
    score -= min(external_apis_count * 10, 40)
    if has_credentials:
        score -= 20
    if localstorage_usage:
        score -= 5
    if unreplaceable_fonts:
        score -= 5
    if mpa_links:
        score -= 15   # 多页应用：内链失效，体验损失明显
    # 后端接口：已能自动修复时不扣分；无法推断需用户干预时扣15分
    if backend_issues.get("relative") or backend_issues.get("localhost"):
        if not backend_issues.get("inferred_origin"):
            score -= 15
    score = max(score, 0)

    # ── 汇总警告 ──
    if localstorage_usage:
        warnings.append("检测到 localStorage 使用，迁移后数据持久化依赖用户浏览器，跨域访问可能受限")
    if font_issues:
        replaceable_count = sum(1 for f in font_issues if f["replaceable"])
        if replaceable_count:
            warnings.append(
                f"发现 {replaceable_count} 处 Google Fonts 外链，建议替换为国内镜像（clone_patcher 会自动处理）"
            )
        if unreplaceable_fonts:
            warnings.append(
                f"发现 {len(unreplaceable_fonts)} 处无法自动替换的字体外链，可能影响加载速度"
            )
    if external_apis_count > 0:
        warnings.append(
            f"共发现 {external_apis_count} 个外部 API 依赖，迁移后请逐一确认可访问性和跨域配置"
        )
    # 后端接口警告
    rel_count = len(backend_issues.get("relative", []))
    loc_count = len(backend_issues.get("localhost", []))
    if rel_count or loc_count:
        inferred = backend_issues.get("inferred_origin", "")
        if inferred:
            warnings.append(
                f"发现 {rel_count} 处相对路径接口 + {loc_count} 处 localhost 接口，"
                f"已推断原始服务地址为 {inferred}，将在修补阶段自动重写"
            )
        else:
            warnings.append(
                f"发现 {rel_count} 处相对路径接口 + {loc_count} 处 localhost 接口，"
                f"无法自动推断原始服务地址，需通过 --backend-origin 指定"
            )
    if mpa_links:
        warnings.append(
            f"⚠️  检测到多页应用（MPA）：发现 {len(mpa_links)} 个内链跳转其他 HTML 页面"
            f"（如 {mpa_links[0]!r}{'等' if len(mpa_links) > 1 else ''}），"
            "克隆单页后这些链接会失效（404）。"
            "建议：仅将此页作为展示用，或手动补齐所有子页面后打包上传。"
        )

    # ── 一句话总结 ──
    if score >= 90:
        summary = "可迁移度极高，几乎无需改动即可上线"
    elif score >= 70:
        summary = f"基本可迁移，存在 {external_apis_count} 个 API 依赖需确认"
    elif score >= 50:
        summary = f"迁移需要一定改造，建议逐项处理 API 依赖和安全问题"
    else:
        summary = f"迁移复杂度较高（评分 {score}），存在凭证泄露或大量外部依赖，建议先做代码清理"

    return {
        "api_deps": api_deps,
        "font_issues": font_issues,
        "localstorage_usage": localstorage_usage,
        "external_apis_count": external_apis_count,
        "has_credentials": has_credentials,
        "mpa_links": mpa_links,
        "backend_issues": backend_issues,
        "score": score,
        "warnings": warnings,
        "summary": summary,
    }


# ── CLI 入口（方便调试）────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python clone_analyzer.py <html_file>", file=sys.stderr)
        sys.exit(1)

    try:
        with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        print(f"[clone_analyzer] 读取文件失败: {sys.argv[1]} — {e}", file=sys.stderr)
        sys.exit(1)

    result = analyze(content)
    print(json.dumps(result, ensure_ascii=False, indent=2))
