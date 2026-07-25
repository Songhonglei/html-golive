"""
clone_fetcher.py — 抓取引擎
为 golive 提供 URL 分类和站点抓取功能。

核心函数：
  classify_url(url) -> str
  fetch_site(url, url_type, use_headless=False) -> dict
"""

import base64
import mimetypes
import os
import re
import subprocess
import time
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10          # 秒，通用超时
LOCAL_TIMEOUT = 5             # 秒，本地地址超时
MAX_IMAGE_BYTES = 2 * 1024 * 1024    # 2 MB，图片内联上限
MAX_ZIP_BYTES  = 100 * 1024 * 1024  # 100 MB，ZIP 下载上限（防 OOM）
INLINE_BUDGET = 30            # 秒，inline_resources 总耗时上限
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# AI 平台域名关键词（用于 AI_GENERATED 分类）
AI_PLATFORM_DOMAINS = [
    "chat.qwen.ai",
    "kimi.ai",
    "kimi.moonshot.cn",
    "minimax.chat",
    "claude.ai",
    "claude.site",
    "glm.cn",
    "chatglm.cn",
    "tongyi.aliyun.com",
    "yuanbao.tencent.com",
    "hailuoai.com",
    "doubao.com",
    "tiangong.cn",
    "wenxin.baidu.com",
    "yiyan.baidu.com",
]

# AI 平台 URL 路径关键词
AI_PATH_PATTERNS = [
    "/s/deploy/",
    "/share/",
    "/artifacts/",
    "/preview/",
    "/deploy/",
    "/sandbox/",
]

# 静态托管平台后缀
STATIC_HOST_SUFFIXES = [
    ".vercel.app",
    ".github.io",
    ".netlify.app",
    ".pages.dev",
]

# Chromium 可执行文件候选列表（按优先级）
CHROME_CANDIDATES = [
    "google-chrome-stable",
    "google-chrome",
    "chromium-browser",
    "chromium",
]


# ---------------------------------------------------------------------------
# 0. 编码修正工具
# ---------------------------------------------------------------------------

def _fix_encoding(resp: "requests.Response") -> str:
    """
    从 HTTP 响应中安全解码文本。
    优先顺序：① Content-Type header 中的 charset → ② HTML <meta charset> → ③ UTF-8 → ④ resp.text 兜底
    """
    import re as _re

    # ① 先用 apparent_encoding 或 header 里的 charset 尝试
    ct = resp.headers.get("Content-Type", "")
    m = _re.search(r"charset\s*=\s*([\w\-]+)", ct, _re.IGNORECASE)
    if m:
        try:
            return resp.content.decode(m.group(1))
        except (UnicodeDecodeError, LookupError):
            pass

    # ② 从 HTML meta 标签检测
    raw = resp.content
    meta_m = _re.search(
        rb'<meta[^>]+charset\s*=\s*["\']?([\w\-]+)',
        raw[:4096], _re.IGNORECASE
    )
    if meta_m:
        try:
            return raw.decode(meta_m.group(1).decode("ascii"))
        except (UnicodeDecodeError, LookupError):
            pass

    # ③ UTF-8 直接尝试
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # ④ 兜底：requests 自己的 text（可能有误，但总比崩溃好）
    return resp.text


# ---------------------------------------------------------------------------
# 1. classify_url
# ---------------------------------------------------------------------------

def classify_url(url: str) -> str:
    """
    对 URL 进行分类，返回以下字符串之一：
      LOCAL | ZIP_URL | PERPLEXITY | AI_GENERATED | STATIC_HOST | WEB_GENERIC
    """
    if not url or not isinstance(url, str):
        return "WEB_GENERIC"

    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path or ""
    path_lower = path.lower()
    url_lower = url.lower()

    # --- ZIP_URL（优先级高于 LOCAL，本地 zip server 也应走 zip 路径）---
    clean_path = path_lower.split("?")[0].split("#")[0]
    if clean_path.endswith(".zip") or clean_path.endswith(".tar.gz"):
        return "ZIP_URL"

    # --- LOCAL ---
    if _is_local(hostname):
        return "LOCAL"

    # --- PERPLEXITY ---
    if "perplexity.ai" in hostname and "computer" in url_lower:
        return "PERPLEXITY"
    if hostname == "perplexity.ai" or hostname.endswith(".perplexity.ai"):
        # 通用 perplexity 页面也归入此类
        return "PERPLEXITY"

    # --- AI_GENERATED ---
    # 明确匹配 AI 平台域名
    for ai_domain in AI_PLATFORM_DOMAINS:
        if hostname == ai_domain or hostname.endswith("." + ai_domain):
            return "AI_GENERATED"

    # 含特征路径的泛 AI 平台（hostname 含常见 AI 关键词）
    ai_host_keywords = ["ai", "gpt", "llm", "chat", "copilot", "bot"]
    host_looks_ai = any(kw in hostname for kw in ai_host_keywords)
    if host_looks_ai:
        for pat in AI_PATH_PATTERNS:
            if pat in path_lower or pat in url_lower:
                return "AI_GENERATED"

    # --- STATIC_HOST ---
    for suffix in STATIC_HOST_SUFFIXES:
        if hostname.endswith(suffix):
            return "STATIC_HOST"

    # --- WEB_GENERIC ---
    return "WEB_GENERIC"


def build_clone_info(url: str) -> dict | None:
    """
    根据克隆来源 URL 生成 cloneInfo dict，供写入注册表。

    返回结构示例：
      {"cloneType": "LAN_URL",      "cloneValue": "http://192.168.1.10:8080/"}
      {"cloneType": "EXTERNAL_URL", "cloneValue": "https://example.com/"}

    本地文件（非 URL 克隆）返回 None。
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""

    if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
        return None

    # ── LAN_URL：私有网段地址 ────────────────────────────────────────────────
    if _is_local(hostname):
        return {
            "cloneType": "LAN_URL",
            "cloneValue": url,
        }

    # ── EXTERNAL_URL：公网站点 ───────────────────────────────────────────────
    return {
        "cloneType": "EXTERNAL_URL",
        "cloneValue": url,
    }


def _is_local(hostname: str) -> bool:
    """判断 hostname 是否为本地/内网地址。"""
    if not hostname:
        return False
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    # 10.x.x.x
    if re.match(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname):
        return True
    # 192.168.x.x
    if re.match(r"^192\.168\.\d{1,3}\.\d{1,3}$", hostname):
        return True
    # 172.16.x.x - 172.31.x.x
    m = re.match(r"^172\.(\d{1,3})\.\d{1,3}\.\d{1,3}$", hostname)
    if m and 16 <= int(m.group(1)) <= 31:
        return True
    return False


# ---------------------------------------------------------------------------
# 2. fetch_site
# ---------------------------------------------------------------------------

def fetch_site(
    url: str,
    url_type: str,
    use_headless: bool = False,
    skip_inline: bool = False,
) -> dict:
    """
    根据 url_type 抓取站点，返回：
      {
        "html": str,
        "strategy_used": str,
        "notes": list[str],
        "source_zip": str | None,
      }

    Parameters
    ----------
    skip_inline : bool
        True 时跳过资源内联（如 --analyze-only 模式，节省时间）。
    """
    result = {
        "html": "",
        "strategy_used": "",
        "notes": [],
        "source_zip": None,
        "url_type": url_type,
    }

    if url_type == "LOCAL":
        _fetch_local(url, result)

    elif url_type == "ZIP_URL":
        _fetch_zip(url, result)

    elif url_type == "PERPLEXITY":
        _fetch_perplexity(url, result)

    elif url_type == "AI_GENERATED":
        _fetch_ai_generated(url, result)

    elif url_type in ("STATIC_HOST", "WEB_GENERIC"):
        _fetch_static_or_generic(url, result, use_headless)

    else:
        # 未知类型，回退到通用抓取
        _fetch_static_or_generic(url, result, use_headless)
        result["notes"].append(f"未知 URL 类型 '{url_type}'，已使用通用抓取策略。")

    # 资源内联（仅当拿到 HTML 且不是 ZIP，且未要求跳过时）
    if result["html"] and not result["source_zip"] and not skip_inline:
        inlined_html, inline_notes = inline_resources(result["html"], url)
        result["html"] = inlined_html
        result["notes"].extend(inline_notes)
    elif skip_inline and result["html"]:
        result["notes"].append("ℹ️ 已跳过资源内联（analyze-only 模式）")

    return result


# ---------------------------------------------------------------------------
# Firecrawl 降级抓取
# ---------------------------------------------------------------------------

def _fetch_via_firecrawl(url: str) -> str:
    """
    通过 Firecrawl API 抓取页面原始 HTML。
    用于 requests 直连失败时的降级路径（如境外托管站点 vercel.app / github.io 等）。
    返回 HTML 字符串，失败返回空字符串。
    """
    if not FIRECRAWL_API_KEY:
        return ""
    try:
        resp = requests.post(
            FIRECRAWL_ENDPOINT,
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"url": url, "formats": ["rawHtml"]},
            timeout=30,
            proxies={},   # 绕过本地代理，Firecrawl 自己有出口
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("rawHtml", "") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 抓取策略实现
# ---------------------------------------------------------------------------

def _fetch_local(url: str, result: dict) -> None:
    """LOCAL 类型：直接 requests 访问（超时5秒）。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=LOCAL_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        result["html"] = _fix_encoding(resp)
        result["strategy_used"] = "requests (本地直连)"
    except Exception as e:
        result["html"] = ""
        result["strategy_used"] = "requests (失败)"
        result["notes"].append(f"⚠️ 无法访问本地地址 {url}：{e}")


def _fetch_zip(url: str, result: dict) -> None:
    """ZIP_URL 类型：下载 zip 文件到 /tmp，限制大小不超过 MAX_ZIP_BYTES。"""
    timestamp = int(time.time() * 1000)
    parsed_path = urllib.parse.urlparse(url).path.lower()
    ext = ".tar.gz" if parsed_path.endswith(".tar.gz") else ".zip"
    dest = f"/tmp/clone_{timestamp}{ext}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, stream=True)
        resp.raise_for_status()

        # 预检 Content-Length
        try:
            _cl_int = int(resp.headers.get("Content-Length") or 0)
        except (ValueError, TypeError):
            _cl_int = 0
        if _cl_int > MAX_ZIP_BYTES:
            size_mb = _cl_int // (1024 * 1024)
            result["html"] = ""
            result["strategy_used"] = "ZIP 下载中止（超限）"
            result["notes"].append(
                f"⚠️ ZIP 文件过大（{size_mb} MB > {MAX_ZIP_BYTES // 1024 // 1024} MB 限制），已中止下载。"
                "建议手动下载后通过 --file 参数上传发布。"
            )
            return

        # 流式下载，中途超限则中止并清理
        _exceeded = False
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                downloaded += len(chunk)
                if downloaded > MAX_ZIP_BYTES:
                    _exceeded = True
                    break
                f.write(chunk)

        if _exceeded:
            try:
                os.unlink(dest)
            except OSError:
                pass
            result["html"] = ""
            result["strategy_used"] = "ZIP 下载中止（超限）"
            result["notes"].append(
                f"⚠️ ZIP 文件超过 {MAX_ZIP_BYTES // 1024 // 1024} MB 限制，已中止下载并清理临时文件。"
                "建议手动下载后通过 --file 参数上传发布。"
            )
            return

        result["source_zip"] = dest
        result["html"] = ""
        result["strategy_used"] = f"直接下载 ZIP → {dest}"
        result["notes"].append(f"ZIP 文件已下载至：{dest}")
    except Exception as e:
        # 清理可能已创建的临时文件
        try:
            if os.path.exists(dest):
                os.unlink(dest)
        except OSError:
            pass
        result["html"] = ""
        result["strategy_used"] = "ZIP 下载失败"
        result["notes"].append(f"⚠️ ZIP 下载失败 ({url})：{e}")


def _fetch_perplexity(url: str, result: dict) -> None:
    """
    PERPLEXITY 类型：
    1. 先 requests fetch，检查下载按钮
    2. 找到 zip/tar 链接则下载
    3. 否则 headless browser 渲染
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        html_text = _fix_encoding(resp)
    except Exception as e:
        html_text = ""
        result["notes"].append(f"⚠️ Perplexity 页面初步抓取失败：{e}")

    # 检查下载按钮
    if html_text:
        zip_url = _find_download_link(html_text, url)
        if zip_url:
            result["notes"].append("Perplexity 页面已检测到下载包，正在下载…")
            timestamp = int(time.time() * 1000)
            # 根据实际链接后缀推断扩展名，避免 .tar.gz 被存为 .zip
            zip_path_lower = urllib.parse.urlparse(zip_url).path.lower()
            ext = ".tar.gz" if zip_path_lower.endswith(".tar.gz") else ".zip"
            dest = f"/tmp/clone_{timestamp}{ext}"
            try:
                r2 = requests.get(zip_url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, stream=True)
                r2.raise_for_status()

                # 预检 Content-Length
                try:
                    _cl = int(r2.headers.get("Content-Length") or 0)
                except (ValueError, TypeError):
                    _cl = 0
                if _cl > MAX_ZIP_BYTES:
                    result["notes"].append(
                        f"⚠️ Perplexity ZIP 文件过大（{_cl // 1024 // 1024} MB），已跳过下载。"
                    )
                    raise RuntimeError("ZIP 超限，跳过")

                _exceeded = False
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in r2.iter_content(chunk_size=65536):
                        downloaded += len(chunk)
                        if downloaded > MAX_ZIP_BYTES:
                            _exceeded = True
                            break
                        f.write(chunk)

                if _exceeded:
                    try:
                        os.unlink(dest)
                    except OSError:
                        pass
                    result["notes"].append(
                        f"⚠️ Perplexity ZIP 超过 {MAX_ZIP_BYTES // 1024 // 1024} MB 限制，已中止。"
                    )
                    raise RuntimeError("ZIP 超限，跳过")

                result["source_zip"] = dest
                result["html"] = ""
                result["strategy_used"] = f"Perplexity 下载按钮 → {dest}"
                return
            except Exception as e2:
                result["notes"].append(f"⚠️ 下载包获取失败：{e2}，回退至浏览器快照")

    # 无下载包 → headless
    result["notes"].append("使用浏览器快照方式（Perplexity headless 渲染）")
    headless_html = _fetch_headless(url)
    if headless_html:
        result["html"] = headless_html
        result["strategy_used"] = "Perplexity headless browser"
    else:
        # headless 也失败，用已有的 requests 结果兜底
        result["html"] = html_text
        result["strategy_used"] = "Perplexity requests fallback"
        if not html_text:
            result["notes"].append("⚠️ Perplexity 页面抓取失败（headless 和 requests 均失败）")
            result["notes"].append("💡 建议：在浏览器打开页面，找页面内「下载/Export」按钮下载 ZIP，再用 golive publish <zip> 发布")


def _fetch_ai_generated(url: str, result: dict) -> None:
    """
    AI_GENERATED 类型：
    1. 检查 Chrome 是否可用
    2. 有 Chrome → headless 渲染；内容不足则 requests 兜底
    3. 无 Chrome → 直接 requests fetch，并告知安装方法
    """
    chrome_bin = _find_chrome()

    if not chrome_bin:
        # 明确告知用户 Chrome 不可用
        result["notes"].append(
            "⚠️ 未检测到 Chrome/Chromium，无法使用 headless 渲染。"
            "AI 生成页通常需要渲染才能完整抓取，建议安装：\n"
            "  Ubuntu/Debian: sudo apt-get install -y google-chrome-stable\n"
            "  或下载：https://www.google.com/chrome/"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            result["html"] = _fix_encoding(resp)
            result["strategy_used"] = "AI 生成页 requests fallback（无 Chrome）"
        except Exception as e:
            result["html"] = ""
            result["strategy_used"] = "AI 生成页抓取失败"
            result["notes"].append(f"⚠️ 直接抓取也失败：{e}")
    else:
        headless_html = _fetch_headless(url)
        if headless_html and len(headless_html) >= 500:
            result["html"] = headless_html
            result["strategy_used"] = "AI 生成页 headless browser"
        else:
            if headless_html:
                result["notes"].append(
                    "⚠️ headless 渲染内容过少（< 500字符），页面可能需要登录或 JS 执行超时，回退至直接抓取"
                )
            else:
                result["notes"].append(
                    "⚠️ headless 渲染失败（页面可能需要登录或超时），回退至直接抓取"
                )
            try:
                resp = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
                resp.raise_for_status()
                result["html"] = _fix_encoding(resp)
                result["strategy_used"] = "AI 生成页 requests fallback"
            except Exception as e:
                result["html"] = headless_html or ""
                result["strategy_used"] = "AI 生成页抓取失败"
                result["notes"].append(f"⚠️ 直接抓取也失败：{e}")

    if result["html"]:
        result["notes"].append("⚠️ AI生成页已快照，动态交互功能需重新接入")


def _fetch_static_or_generic(url: str, result: dict, use_headless: bool) -> None:
    """
    STATIC_HOST / WEB_GENERIC 类型：
    1. requests 直接 fetch
    2. 若 body < 500字符（SPA 壳）且 use_headless=True，降级 headless
    """
    html_text = ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        html_text = _fix_encoding(resp)
        result["strategy_used"] = "requests 直接抓取"
        result["notes"].append("使用 requests 直接抓取页面")
    except Exception as e:
        result["notes"].append(f"⚠️ requests 抓取失败：{e}")
        result["strategy_used"] = "requests 失败"
        # 降级：尝试 Firecrawl（处理境外托管站点如 vercel.app / github.io）
        if FIRECRAWL_API_KEY:
            result["notes"].append("🔄 尝试 Firecrawl 降级抓取...")
            fc_html = _fetch_via_firecrawl(url)
            if fc_html:
                html_text = fc_html
                result["strategy_used"] = "Firecrawl 抓取"
                result["notes"].append("✅ Firecrawl 抓取成功")
            else:
                result["notes"].append("⚠️ Firecrawl 抓取也失败")

    # 检查是否是 SPA 壳（内容过少）
    body_text = _extract_body_text(html_text)
    if len(body_text) < 500:
        if use_headless:
            result["notes"].append(f"页面内容较少（{len(body_text)}字符），疑似 SPA，降级使用 headless 渲染")
            headless_html = _fetch_headless(url)
            if headless_html and len(headless_html) > len(html_text):
                html_text = headless_html
                result["strategy_used"] = "headless browser（SPA 降级）"
                result["notes"].append("已使用 headless browser 渲染 SPA 页面")
            else:
                result["notes"].append("⚠️ headless 渲染结果不优于直接抓取，保留原始内容")
        else:
            result["notes"].append(
                f"⚠️ 页面内容较少（{len(body_text)}字符），疑似 SPA（JavaScript 渲染）。"
                "💡 建议加上 --headless 参数重试以获取完整内容。"
            )

    result["html"] = html_text


# ---------------------------------------------------------------------------
# _fetch_headless — 内部函数
# ---------------------------------------------------------------------------

def _fetch_headless(url: str) -> str:
    """
    用 Chromium headless 命令行渲染页面，返回 DOM 字符串。
    失败或超时返回空字符串。
    """
    chrome_bin = _find_chrome()
    if not chrome_bin:
        return ""

    cmd = [
        chrome_bin,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--dump-dom",
        "--virtual-time-budget=5000",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.stdout or ""
    except subprocess.TimeoutExpired:
        return ""
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def _find_chrome() -> Optional[str]:
    """在系统中查找可用的 Chrome/Chromium 可执行文件。"""
    for candidate in CHROME_CANDIDATES:
        try:
            result = subprocess.run(
                ["which", candidate],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return candidate
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# inline_resources — 资源内联
# ---------------------------------------------------------------------------

def inline_resources(html: str, base_url: str) -> tuple:
    """
    将 HTML 中的外部资源内联：
      - <link rel="stylesheet"> → <style>
      - <script src="..."> → <script>内联</script>
      - <img src="..."> → base64 data URI

    总耗时超过 INLINE_BUDGET 秒后自动停止，已内联的部分保留。
    返回：(处理后的HTML字符串, notes列表)
    """
    notes = []
    if not html:
        return html, notes

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        notes.append(f"⚠️ HTML 解析失败，跳过资源内联：{e}")
        return html, notes

    session = requests.Session()
    session.headers.update(HEADERS)
    _inline_deadline = time.time() + INLINE_BUDGET  # 总耗时保护
    _timeout_noted = False  # 超时提示去重 flag（只打一条）

    def _note_timeout(msg: str):
        nonlocal _timeout_noted
        if not _timeout_noted:
            notes.append(msg)
            _timeout_noted = True

    # --- favicon：将相对路径转为绝对 URL，不内联为 base64 ---
    # 保留原始 http URL，供发布时直接传给 extendInfo.favIcon
    FAVICON_RELS = {"icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed"}
    for tag in soup.find_all("link", href=True):
        rel_vals = {r.lower() for r in tag.get("rel", [])}
        if not rel_vals & FAVICON_RELS:
            continue
        href = tag.get("href", "")
        if not href or href.startswith("data:"):
            continue
        abs_href = _to_absolute(href, base_url)
        if abs_href and abs_href.startswith("http"):
            tag["href"] = abs_href

    # --- 内联 CSS ---
    for tag in soup.find_all("link", rel=lambda r: r and "stylesheet" in r):
        if time.time() > _inline_deadline:
            _note_timeout("⚠️ 资源内联超时（30s），剩余外链保留原链接")
            break
        href = tag.get("href", "")
        if not href or href.startswith("data:"):
            continue
        abs_href = _to_absolute(href, base_url)
        if not abs_href:
            continue
        try:
            resp = session.get(abs_href, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            css_content = resp.text
            # 处理 CSS 内的 url(...)
            css_content, css_notes = _inline_css_urls(css_content, abs_href, session)
            notes.extend(css_notes)
            # 替换 <link> 为 <style>
            new_tag = soup.new_tag("style")
            new_tag.string = css_content
            tag.replace_with(new_tag)
        except Exception as e:
            notes.append(f"⚠️ CSS 内联失败，保留原链接 ({abs_href})：{e}")

    # --- 内联 JS ---
    for tag in soup.find_all("script", src=True):
        if time.time() > _inline_deadline:
            _note_timeout("⚠️ 资源内联超时（30s），剩余外链保留原链接")
            break
        src = tag.get("src", "")
        if not src or src.startswith("data:"):
            continue
        abs_src = _to_absolute(src, base_url)
        if not abs_src:
            continue
        try:
            resp = session.get(abs_src, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            js_content = resp.text
            new_tag = soup.new_tag("script")
            new_tag.string = js_content
            if tag.get("type"):
                new_tag["type"] = tag["type"]
            tag.replace_with(new_tag)
        except Exception as e:
            notes.append(f"⚠️ JS 内联失败，保留原链接 ({abs_src})：{e}")

    # --- 内联图片 ---
    for tag in soup.find_all("img", src=True):
        if time.time() > _inline_deadline:
            _note_timeout("⚠️ 资源内联超时（30s），剩余图片保留原链接")
            break
        src = tag.get("src", "")
        if not src or src.startswith("data:"):
            continue
        abs_src = _to_absolute(src, base_url)
        if not abs_src:
            continue
        try:
            resp = session.get(abs_src, timeout=DEFAULT_TIMEOUT, stream=True)
            resp.raise_for_status()
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                notes.append(f"⚠️ 图片超过 2MB，跳过内联，保留原链接：{abs_src}")
                continue
            img_bytes = resp.content
            if len(img_bytes) > MAX_IMAGE_BYTES:
                notes.append(f"⚠️ 图片超过 2MB，跳过内联，保留原链接：{abs_src}")
                continue
            mime = _guess_mime(abs_src, resp.headers.get("Content-Type", ""))
            b64 = base64.b64encode(img_bytes).decode("ascii")
            tag["src"] = f"data:{mime};base64,{b64}"
        except Exception as e:
            notes.append(f"⚠️ 图片内联失败，保留原链接 ({abs_src})：{e}")

    return str(soup), notes


def _inline_css_urls(css: str, css_base_url: str, session: requests.Session) -> tuple:
    """
    处理 CSS 内的 url(...) 引用，将图片/字体转为 base64。
    返回：(处理后的CSS, notes列表)
    """
    notes = []

    def replace_url(match):
        raw = match.group(1).strip().strip("'\"")
        if not raw or raw.startswith("data:") or raw.startswith("#"):
            return match.group(0)
        abs_url = _to_absolute(raw, css_base_url)
        if not abs_url:
            return match.group(0)
        try:
            resp = session.get(abs_url, timeout=DEFAULT_TIMEOUT, stream=True)
            resp.raise_for_status()
            data = resp.content
            if len(data) > MAX_IMAGE_BYTES:
                notes.append(f"⚠️ CSS 资源超过 2MB，跳过内联：{abs_url}")
                return match.group(0)
            mime = _guess_mime(abs_url, resp.headers.get("Content-Type", ""))
            b64 = base64.b64encode(data).decode("ascii")
            return f"url(data:{mime};base64,{b64})"
        except Exception as e:
            notes.append(f"⚠️ CSS 资源内联失败，保留原引用 ({abs_url})：{e}")
            return match.group(0)

    processed = re.sub(r"url\(([^)]+)\)", replace_url, css)
    return processed, notes


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _to_absolute(href: str, base_url: str) -> Optional[str]:
    """将相对 URL 转为绝对 URL。"""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme}:{href}"
    try:
        return urllib.parse.urljoin(base_url, href)
    except Exception:
        return None


def _guess_mime(url: str, content_type: str) -> str:
    """猜测资源 MIME 类型。"""
    # 优先用 Content-Type（去掉参数部分）
    if content_type:
        mime = content_type.split(";")[0].strip()
        if mime and "/" in mime and mime != "application/octet-stream":
            return mime
    # 根据扩展名猜
    path = urllib.parse.urlparse(url).path
    guessed, _ = mimetypes.guess_type(path)
    if guessed:
        return guessed
    return "application/octet-stream"


def _extract_body_text(html: str) -> str:
    """提取 HTML body 的可见文本，用于判断内容是否充分。"""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if body:
            return body.get_text(strip=True)
        return soup.get_text(strip=True)
    except Exception:
        # 退化：直接去除 HTML 标签
        return re.sub(r"<[^>]+>", "", html)


def _find_download_link(html: str, base_url: str) -> Optional[str]:
    """
    在 HTML 中查找下载按钮：
    <a> 标签文字含 download/export/下载，且 href 是 zip/tar 文件。
    返回绝对 URL 或 None。
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    download_keywords = re.compile(r"download|export|下载", re.IGNORECASE)
    zip_pattern = re.compile(r"\.(zip|tar\.gz|tgz)(\?.*)?$", re.IGNORECASE)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        title = a.get("title", "")
        aria_label = a.get("aria-label", "")

        is_download_text = bool(
            download_keywords.search(text)
            or download_keywords.search(title)
            or download_keywords.search(aria_label)
        )
        href_path = urllib.parse.urlparse(href).path
        is_zip_href = bool(zip_pattern.search(href_path))

        if is_download_text or is_zip_href:
            abs_url = _to_absolute(href, base_url)
            if abs_url:
                return abs_url

    return None


# ---------------------------------------------------------------------------
# 模块自测（直接运行时）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_urls = [
        ("http://localhost:3000/", "LOCAL"),
        ("https://example.com/project.zip", "ZIP_URL"),
        ("https://www.perplexity.ai/computer/abc123", "PERPLEXITY"),
        ("https://claude.ai/artifacts/xyz", "AI_GENERATED"),
        ("https://my-app.vercel.app/", "STATIC_HOST"),
        ("https://example.com/", "WEB_GENERIC"),
    ]
    for url, expected in test_urls:
        got = classify_url(url)
        status = "✅" if got == expected else "❌"
        print(f"{status} classify_url({url!r}) = {got!r}  (expected {expected!r})")
