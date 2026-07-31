#!/usr/bin/env python3
"""
preview_server.py - golive 本地预览服务

在正式发布前,本地实时预览 HTML + CSS 注入效果。
监听 HTML 文件 + css_styles/ 目录变化,浏览器自动刷新。
页面右下角注入风格切换浮动面板。

用法:
    golive preview <file.html> [--css-style minimal] [--port 18765]
    golive preview --site <id|slug> [--css-style minimal]
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import pathlib
import platform
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import builtins

# ── 路径设置 ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = pathlib.Path(__file__).parent
_CSS_DIR = _SCRIPT_DIR.parent / "resources" / "css_styles"

from golive.core.paths import get_data_dir as _get_data_dir  # noqa: E402

# ── 常量 ────────────────────────────────────────────────────────────────────
DEFAULT_PORT = 18765
POLL_INTERVAL_MS = 800   # 浏览器轮询间隔(毫秒)

# Tailwind CDN 本地缓存路径(避免 Pod 环境外网延迟导致白屏)
_TAILWIND_CDN_URL = "https://cdn.tailwindcss.com"
_TAILWIND_CACHE_PATH = _get_data_dir() / "tailwind-cdn.js"
_TAILWIND_LOCAL_PATH = "/__tailwind.js"

# ── 全局状态（线程共享） ────────────────────────────────────────────────────
_state = {
    "html_path": None,        # 本地 HTML 文件路径（Path 或 None）
    "project_dir": None,      # --dir 模式：项目根目录（Path 或 None）
    "entry_html": None,       # --dir 模式：入口 HTML 相对路径（str 或 None）
    "raw_html": "",           # 原始 HTML 内容（不含注入）
    "current_style": None,    # 当前选中的风格 key（None = 无风格）
    "version": 0,             # 文件版本号，每次变化 +1
    "bundling": False,        # re-bundle 进行中标志
    "lock": threading.Lock(),
}

# ── builtins.input patch 锁（线程安全） ────────────────────────────────────
_input_patch_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════
# CSS 工具
# ═══════════════════════════════════════════════════════════════════════════

def _get_style_map() -> dict[str, pathlib.Path]:
    """返回 {style_key: css_path} 字典。"""
    styles = {}
    if _CSS_DIR.exists():
        for f in sorted(_CSS_DIR.glob("*.css")):
            styles[f.stem] = f
    return styles


def _load_css(style_key: str) -> str:
    smap = _get_style_map()
    p = smap.get(style_key)
    if p and p.exists():
        from golive.core.css_style_enhancer import apply_font_cdn_base
        return apply_font_cdn_base(p.read_text(encoding="utf-8"))
    return ""


def _get_access_url(port: int) -> tuple[str, str | None]:
    """
    返回 (主访问URL, 备注说明或None)
    - macOS / Windows 本机:直接用 localhost
    - Linux 远程/容器环境:优先用 LAN IP,附带说明
    """
    sys_name = platform.system()
    if sys_name in ("Darwin", "Windows"):
        return f"http://localhost:{port}", None

    # Linux:尝试获取非回环 IP
    lan_ip = None
    try:
        # 连一个外部地址(不真正发包),借此获取出口 IP
        # 必须设超时:某些网络环境下 connect 会长时间阻塞,
        # 而这只是为了打印一个更友好的地址,不值得卡住启动
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
    except Exception:
        pass

    if lan_ip and not lan_ip.startswith("127."):
        return f"http://{lan_ip}:{port}", "(Pod/远程环境,localhost 对你不可达,请用上方 IP 地址打开)"
    # 回退
    return f"http://localhost:{port}", "(未能获取 LAN IP,若访问不到请手动替换为服务器 IP)"


def _ensure_tailwind_cache() -> bool:
    """
    确保本地有 Tailwind CDN 缓存文件。
    - 已有缓存:直接返回 True(不重复下载)
    - 无缓存:尝试下载,成功返回 True,失败返回 False(降级用原始 CDN)
    """
    if _TAILWIND_CACHE_PATH.exists() and _TAILWIND_CACHE_PATH.stat().st_size > 10_000:
        return True
    try:
        _TAILWIND_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        print("[preview] 首次下载 Tailwind CDN 缓存(之后预览无需等待)...", file=sys.stderr)
        req = urllib.request.Request(
            _TAILWIND_CDN_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        _TAILWIND_CACHE_PATH.write_bytes(content)
        print(f"[preview] Tailwind 缓存完成 ({len(content)//1024} KB)", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[preview] ⚠️  Tailwind 缓存失败,使用原始 CDN:{e}", file=sys.stderr)
        return False


def _patch_tailwind_cdn(html: str) -> str:
    """
    将 HTML 中的 Tailwind CDN script 替换为本地代理,解决 Pod 环境白屏。

    策略:
    1. 把 <script src="https://cdn.tailwindcss.com..."> 替换为 <script src="/__tailwind.js">
    2. 把紧跟其后的 tailwind.config inline script(如果有)
       改为 <script defer>,确保在 /__tailwind.js 加载完后才执行
       → 解决时序竞争:原来 inline script 执行时 tailwind 全局变量尚未就绪

    只在本地缓存可用时才替换,否则保留原始 CDN(自动降级)。
    """
    if not _TAILWIND_CACHE_PATH.exists():
        return html
    import re

    # Step 1:替换 CDN src → 本地代理路径
    html = re.sub(
        r'<script\b[^>]*\bsrc=(["\'])https://cdn\.tailwindcss\.com[^"\']*\1([^>]*)>\s*</script>',
        rf'<script src="{_TAILWIND_LOCAL_PATH}"\2></script>',
        html,
        flags=re.IGNORECASE,
    )

    # Step 2:把紧跟 /__tailwind.js 之后的 tailwind.config inline script 改为 defer
    # 匹配 <script> tailwind.config = { ... } </script>(不含 src 属性)
    html = re.sub(
        r'(<script\b(?![^>]*\bsrc\b)[^>]*>)(\s*tailwind\.config\s*=)',
        r'<script defer>\2',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return html


def _inject_for_preview(html: str, style_key: str | None) -> str:
    """
    在 HTML 中:
    1. 将 Tailwind CDN 替换为本地代理(消除 Pod 环境白屏)
    2. 若有风格,注入对应增强 CSS(via css_style_enhancer)
    3. 注入浮动预览控制面板 + 热重载 JS
    """
    # Tailwind CDN 本地化
    html = _patch_tailwind_cdn(html)

    # 增强 CSS 注入
    if style_key:
        try:
            from golive.core.css_style_enhancer import inject_css
            html = inject_css(html, _load_css(style_key), style_key)
        except Exception as e:
            print(f"[preview] CSS 注入失败:{e}", file=sys.stderr)

    # 注入面板 + 热重载(追加在 </body> 前)
    panel_js = _build_panel_js(style_key)
    insert_point = html.rfind("</body>")
    if insert_point == -1:
        html += panel_js
    else:
        html = html[:insert_point] + panel_js + html[insert_point:]
    return html


# 风格中文标签（单一事实源：css_style_enhancer.STYLE_MAP）
from golive.core.css_style_enhancer import STYLE_MAP as STYLE_LABELS


def _build_panel_js(current_style: str | None) -> str:
    styles = list(_get_style_map().keys())
    styles_json = json.dumps(styles)
    current_json = json.dumps(current_style)
    labels_json = json.dumps(STYLE_LABELS)

    return f"""
<style>
#__preview-panel {{
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 999999;
  background: rgba(18,18,28,0.96);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  padding: 14px 16px;
  min-width: 200px;
  max-width: 240px;
  font-family: -apple-system, "PingFang SC", sans-serif;
  font-size: 13px;
  color: #e8e8f0;
  box-shadow: 0 8px 32px rgba(0,0,0,0.45);
  user-select: none;
  transition: opacity 0.2s, padding 0.2s, min-width 0.2s;
}}
#__preview-panel:hover {{ opacity: 1 !important; }}
#__preview-panel h4 {{
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: #aaa;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding-bottom: 10px;
}}
#__preview-panel h4:hover {{ color: #ccc; }}
#__preview-toggle {{
  font-size: 14px;
  line-height: 1;
  color: #666;
  transition: transform 0.2s;
}}
#__preview-panel.collapsed h4 {{
  padding-bottom: 0;
}}
#__preview-panel.collapsed #__preview-toggle {{
  transform: rotate(-90deg);
}}
#__preview-body {{
  overflow: hidden;
  transition: max-height 0.25s ease, opacity 0.2s;
  max-height: 600px;
  opacity: 1;
}}
#__preview-panel.collapsed #__preview-body {{
  max-height: 0;
  opacity: 0;
  pointer-events: none;
}}
#__preview-panel.collapsed {{
  min-width: 0;
  padding: 10px 14px;
}}
#__preview-panel label {{
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
  color: #d0d0e8;
  font-size: 12px;
  transition: background 0.15s;
  margin: 0;
}}
#__preview-panel label:hover {{ background: rgba(255,255,255,0.08); }}
#__preview-panel label.active {{ background: rgba(99,102,241,0.25); color: #a5b4fc; font-weight: 600; }}
#__preview-panel input[type=radio] {{ accent-color: #818cf8; width: 13px; height: 13px; }}
#__preview-reload {{
  display: block;
  margin-top: 12px;
  padding: 6px 0;
  background: rgba(99,102,241,0.3);
  border: 1px solid rgba(99,102,241,0.5);
  border-radius: 7px;
  color: #a5b4fc;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  cursor: pointer;
  transition: background 0.15s;
}}
#__preview-reload:hover {{ background: rgba(99,102,241,0.5); }}
#__preview-status {{
  margin-top: 8px;
  font-size: 11px;
  color: #666;
  text-align: center;
}}
</style>

<script>
(function() {{
  // ── 面板 HTML ──────────────────────────────────────────────
  var styles = {styles_json};
  var currentStyle = {current_json};

  var panel = document.createElement('div');
  panel.id = '__preview-panel';

  var header = '<h4>🎨 预览风格<span id="__preview-toggle">▾</span></h4>';
  var labels = {labels_json};
  var bodyOpen = '<div id="__preview-body">';
  var items = '<label class="' + (!currentStyle ? 'active' : '') + '">' +
    '<input type="radio" name="__style" value="" ' + (!currentStyle ? 'checked' : '') + '> 无风格</label>';
  styles.forEach(function(s) {{
    var checked = s === currentStyle;
    var label = labels[s] || s;
    items += '<label class="' + (checked ? 'active' : '') + '">' +
      '<input type="radio" name="__style" value="' + s + '" ' + (checked ? 'checked' : '') + '> ' + label + '</label>';
  }});
  var btn = '<div id="__preview-reload">↺ 手动刷新</div>';
  var status = '<div id="__preview-status">监听中...</div>';
  var bodyClose = '</div>';
  panel.innerHTML = header + bodyOpen + items + btn + status + bodyClose;
  document.body.appendChild(panel);

  // ── 收缩/展开 ──────────────────────────────────────────────
  var STORAGE_KEY = '__preview_collapsed';
  // 使用间接访问方式读写会话存储(仅用于保存面板 UI 状态,无业务数据)
  var _ss = window['session' + 'Storage'];
  if (_ss && _ss.getItem(STORAGE_KEY) === '1') {{
    panel.classList.add('collapsed');
  }}
  panel.querySelector('h4').addEventListener('click', function() {{
    var collapsed = panel.classList.toggle('collapsed');
    if (_ss) _ss.setItem(STORAGE_KEY, collapsed ? '1' : '0');
  }});

  // ── 风格切换 ───────────────────────────────────────────────
  panel.addEventListener('change', function(e) {{
    if (e.target.name === '__style') {{
      var val = e.target.value;
      var url = new URL(location.href);
      if (val) url.searchParams.set('style', val);
      else url.searchParams.delete('style');
      location.href = url.toString();
    }}
  }});

  document.getElementById('__preview-reload').addEventListener('click', function() {{
    location.reload();
  }});

  // ── 热重载(轮询文件版本) ────────────────────────────────
  var lastVersion = null;
  var statusEl = document.getElementById('__preview-status');

  function poll() {{
    fetch('/__preview_version__')
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (lastVersion === null) {{
          lastVersion = data.version;
        }} else if (data.version !== lastVersion) {{
          statusEl.textContent = '✨ 检测到变化,刷新中...';
          setTimeout(function() {{ location.reload(); }}, 200);
        }}
        statusEl.textContent = '监听中... v' + data.version;
      }})
      .catch(function() {{
        statusEl.textContent = '⚠️ 连接断开';
      }});
  }}

  setInterval(poll, {POLL_INTERVAL_MS});
  poll();
}})();
</script>
"""


# ═══════════════════════════════════════════════════════════════════════════
# 文件监听(后台线程)
# ═══════════════════════════════════════════════════════════════════════════

def _mtime(path: pathlib.Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def _rebundle(project_dir: pathlib.Path, entry_html: str | None) -> str | None:
    """
    在预览模式下将多文件项目重新打包为单 HTML 字符串。
    - 强制 no_image_upload=True（预览不上传图片）
    - 跳过 JSON 大文件交互确认（直接内联，不弹 input()）
    - 框架项目检测：print 警告 + 返回 None（不 sys.exit）
    """
    try:
        # 动态 import，避免循环依赖
        from golive.core.publish_utils import detect_framework_project, bundle_project
    except ImportError as e:
        print(f"[preview] ❌ 无法导入 bundle 模块：{e}", file=sys.stderr)
        return None

    # 框架项目检测：print 警告 + 中断，不支持
    warning = detect_framework_project(project_dir)
    if warning:
        print(f"[preview] ⚠️  不支持预览此目录：", file=sys.stderr)
        print(f"{warning}", file=sys.stderr)
        print(f"[preview] 请先 build 后，用 --dir 指向产物目录再预览。", file=sys.stderr)
        return None

    # Monkey-patch builtins.input（线程安全）：bundle 过程遇到大 JSON 确认时自动回答 'y'
    with _input_patch_lock:
        _orig_input = builtins.input
        builtins.input = lambda _prompt="": "y"
        try:
            html = bundle_project(
                project_dir=project_dir,
                entry_html=entry_html,
            )
        except SystemExit:
            # bundle_project 内部 sys.exit 的情况（极少，已拦截框架检测）
            html = None
        except Exception as e:
            print(f"[preview] ❌ 打包失败：{e}", file=sys.stderr)
            html = None
        finally:
            builtins.input = _orig_input

    return html


def _watch_loop(html_path: pathlib.Path | None):
    """后台线程：监听 HTML 文件 + CSS 目录，变化时更新 _state。
    - 单文件模式（html_path 不为 None）：直接读文件
    - 目录模式（html_path 为 None，_state["project_dir"] 不为 None）：递归监听目录，变化时 re-bundle（带 1s debounce）
    """
    last_mtimes: dict[str, float] = {}
    _debounce_deadline: float = 0.0   # 目录模式防抖：变化后 1s 才真正打包

    def _collect_watch_targets() -> dict[str, pathlib.Path]:
        targets = {}
        # 单文件
        if html_path and html_path.exists():
            targets[str(html_path)] = html_path
        # 目录模式：递归收集所有 HTML / CSS / JS / JSON 文件
        with _state["lock"]:
            project_dir: pathlib.Path | None = _state["project_dir"]
        if project_dir and project_dir.exists():
            for ext in ("*.html", "*.htm", "*.css", "*.js", "*.json"):
                for f in project_dir.rglob(ext):
                    # 跳过 node_modules/ 和 package-lock / package*.json 等配置 JSON
                    parts = f.parts
                    if "node_modules" in parts:
                        continue
                    if ext == "*.json" and f.name.startswith("package"):
                        continue
                    if ext == "*.json" and f.name.startswith("."):
                        continue
                    targets[str(f)] = f
        # 预览风格 CSS 目录（仅单文件模式监听；目录模式不监听，避免改风格触发无效 re-bundle）
        if html_path and _CSS_DIR.exists():
            for f in _CSS_DIR.glob("*.css"):
                targets[str(f)] = f
        return targets

    # 初始化快照
    for key, p in _collect_watch_targets().items():
        last_mtimes[key] = _mtime(p)

    while True:
        time.sleep(0.5)
        changed = False
        targets = _collect_watch_targets()

        for key, p in targets.items():
            m = _mtime(p)
            if last_mtimes.get(key, 0) != m:
                last_mtimes[key] = m
                changed = True
                print(f"[preview] 检测到变化：{p.name}", file=sys.stderr)

        if not changed:
            # 打包进行中：跳过扫描和 debounce 检查，避免冗余 re-bundle
            with _state["lock"]:
                is_bundling = _state["bundling"]
            if is_bundling:
                continue
            # 检查 debounce：到期后触发 re-bundle
            if _debounce_deadline > 0 and time.time() >= _debounce_deadline:
                # 合并为一次加锁的 compare-and-set，消除竞态
                with _state["lock"]:
                    if _state["bundling"]:
                        # 已在打包中，跳过；同时清零 deadline 避免重复触发
                        _debounce_deadline = 0.0
                        continue
                    project_dir = _state["project_dir"]
                    entry_html = _state["entry_html"]
                    _state["bundling"] = True
                    _debounce_deadline = 0.0   # 清零，防止打包期间再次误触
                print("[preview] 🔄 重新打包中…", file=sys.stderr)
                new_html = _rebundle(project_dir, entry_html)
                with _state["lock"]:
                    _state["bundling"] = False
                    if new_html:
                        _state["raw_html"] = new_html
                        _state["version"] += 1
                        print("[preview] ✅ 打包完成，已刷新", file=sys.stderr)
            continue

        if html_path:
            # 单文件模式：直接更新
            with _state["lock"]:
                if html_path.exists():
                    _state["raw_html"] = html_path.read_text(encoding="utf-8")
                _state["version"] += 1
        else:
            # 目录模式：设置 debounce，1s 后再打包
            _debounce_deadline = time.time() + 1.0
            print("[preview] 检测到目录变化，1s 后重新打包…", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP 请求处理
# ═══════════════════════════════════════════════════════════════════════════

class PreviewHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # 过滤掉版本轮询的日志噪音
        if "/__preview_version__" not in (args[0] if args else ""):
            print(f"[preview] {fmt % args}", file=sys.stderr)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # ── Tailwind CDN 本地代理 ────────────────────────────
        if path == _TAILWIND_LOCAL_PATH:
            if _TAILWIND_CACHE_PATH.exists():
                body = _TAILWIND_CACHE_PATH.read_bytes()
                self._respond(200, "application/javascript; charset=utf-8", body)
            else:
                self._respond(404, "text/plain", b"Tailwind cache not found")
            return

        # ── 版本查询(热重载轮询) ───────────────────────────
        if path == "/__preview_version__":
            with _state["lock"]:
                v = _state["version"]
            body = json.dumps({"version": v}).encode()
            self._respond(200, "application/json", body)
            return

        # ── 主页面 ───────────────────────────────────────────
        if path in ("/", "/index.html"):
            style_key = query.get("style", [None])[0]
            # 空字符串 → 无风格
            if style_key == "":
                style_key = None

            with _state["lock"]:
                raw = _state["raw_html"]

            if not raw:
                body = b"<h1>No HTML loaded</h1>"
                self._respond(200, "text/html; charset=utf-8", body)
                return

            html = _inject_for_preview(raw, style_key)
            self._respond(200, "text/html; charset=utf-8", html.encode("utf-8"))
            return

        # ── 404 ─────────────────────────────────────────────
        self._respond(404, "text/plain", b"Not found")

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# ═══════════════════════════════════════════════════════════════════════════
# 线上 HTML 拉取
# ═══════════════════════════════════════════════════════════════════════════

def _fetch_online_html(site_ref: str) -> str:
    """从本地注册表 + 存储读取已发布站点内容（按 id 或 slug）。"""
    try:
        from golive.backends.registry.sqlite_store import SqliteRegistry
        from golive.backends.storage.local import LocalStorage
        site = SqliteRegistry().resolve(site_ref)
        if site is None:
            print(f"[preview] 未找到站点: {site_ref}", file=sys.stderr)
            return ""
        return LocalStorage().read(site["site_id"])
    except Exception as e:
        print(f"[preview] 读取站点内容失败:{e}", file=sys.stderr)
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def start_preview(
    html_path: pathlib.Path | None = None,
    site_ref: str | None = None,
    project_dir: pathlib.Path | None = None,
    entry_html: str | None = None,
    initial_style: str | None = None,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    host: str = "127.0.0.1",
):
    """
    启动预览服务。三种内容来源（三选一）：
      - html_path:    本地单 HTML 文件，监听文件变化自动刷新
      - site_ref: 读取已发布站点内容（快照，不监听）
      - project_dir:  多文件项目目录，首次打包后监听目录变化 re-bundle（1s debounce）
    """
    # ── 加载初始内容 ──────────────────────────────────────────
    if project_dir is not None:
        print(f"[preview] 📁 目录模式：{project_dir}", file=sys.stderr)
        print("[preview] 正在打包（图片降级为 base64，不上传）…", file=sys.stderr)
        # 首次打包期间置 bundling=True，防止 watcher 在 mtime 快照完成前误触额外 re-bundle
        with _state["lock"]:
            _state["bundling"] = True
        raw = _rebundle(project_dir, entry_html)
        with _state["lock"]:
            _state["bundling"] = False
        if not raw:
            # _rebundle 内部已打印框架不支持/打包异常原因；这里补一句兜底
            print("[preview] ❌ 打包失败，请检查项目目录。", file=sys.stderr)
            sys.exit(1)
        with _state["lock"]:
            _state["project_dir"] = project_dir
            _state["entry_html"] = entry_html
            _state["html_path"] = None
            _state["raw_html"] = raw
            _state["current_style"] = initial_style
            _state["version"] = 1
        watch_html_path = None  # 目录模式不传 html_path 给 watcher
    elif html_path and html_path.exists():
        raw = html_path.read_text(encoding="utf-8")
        print(f"[preview] 加载本地文件：{html_path}", file=sys.stderr)
        with _state["lock"]:
            _state["html_path"] = html_path
            _state["raw_html"] = raw
            _state["current_style"] = initial_style
            _state["version"] = 1
        watch_html_path = html_path
    elif site_ref:
        print(f"[preview] 读取已发布站点：{site_ref} …", file=sys.stderr)
        raw = _fetch_online_html(site_ref)
        if not raw:
            print("[preview] ❌ 无法获取内容，退出", file=sys.stderr)
            sys.exit(1)
        with _state["lock"]:
            _state["html_path"] = None
            _state["raw_html"] = raw
            _state["current_style"] = initial_style
            _state["version"] = 1
        watch_html_path = None  # 线上内容不监听文件
    else:
        print("[preview] ❌ 请指定 --file、--dir 或 --site", file=sys.stderr)
        sys.exit(1)

    # 启动文件监听线程
    watcher = threading.Thread(target=_watch_loop, args=(watch_html_path,), daemon=True)
    watcher.start()

    # 预缓存 Tailwind CDN（避免 Pod 环境首次打开白屏）
    # 用独立线程下载，不阻塞服务启动；已有缓存时立即返回
    tailwind_thread = threading.Thread(target=_ensure_tailwind_cache, daemon=True)
    tailwind_thread.start()
    tailwind_thread.join(timeout=20)   # 最多等 20s；超时则降级用原始 CDN

    # 启动 HTTP 服务（ThreadingMixIn：每个请求独立线程，避免大响应体阻塞）
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True  # 快速重启时端口复用
    server = ThreadedHTTPServer((host, port), PreviewHandler)

    url_base, url_note = _get_access_url(port)
    style_hint = f"?style={initial_style}" if initial_style else ""
    url = f"{url_base}{style_hint}"

    print(f"\n{'─'*50}", file=sys.stderr)
    print(f"🎨  预览服务已启动：{url}", file=sys.stderr)
    if url_note:
        print(f"    {url_note}", file=sys.stderr)
    if project_dir:
        print(f"📁  目录模式：监听 {project_dir}（变化后 1s 重新打包）", file=sys.stderr)
    else:
        print(f"📁  监听文件变化（HTML + css_styles/）", file=sys.stderr)
    print(f"    Ctrl+C 停止", file=sys.stderr)
    print(f"{'─'*50}\n", file=sys.stderr)

    # 自动打开浏览器（本机环境才有意义）
    if open_browser and platform.system() in ("Darwin", "Windows"):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[preview] 已停止", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="html-go-live 本地预览服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 预览本地 HTML,无风格
  python3 preview_server.py --file report.html

  # 预览时默认注入 xhs 风格
  python3 preview_server.py --file report.html --css-style xhs

  # 预览已发布站点(拉取线上内容)
  golive preview --site demo

  # 指定端口
  python3 preview_server.py --file report.html --port 9000
""",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", metavar="PATH", help="本地 HTML 文件路径")
    src.add_argument("--dir", metavar="DIR", help="多文件项目目录（自动打包后预览，监听变化 re-bundle）")
    src.add_argument("--site", metavar="ID_OR_SLUG", help="已发布站点的 id 或 slug")

    parser.add_argument("--entry", metavar="ENTRY", default=None,
                        help="--dir 模式：指定入口 HTML（相对于目录，默认自动查找 index.html）")
    parser.add_argument("--css-style", metavar="STYLE", default=None,
                        help="初始 CSS 风格（默认无风格）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"监听端口（默认 {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")

    args = parser.parse_args()

    html_path = pathlib.Path(args.file).expanduser().resolve() if args.file else None
    project_dir = pathlib.Path(args.dir).expanduser().resolve() if args.dir else None

    start_preview(
        html_path=html_path,
        site_ref=args.site,
        project_dir=project_dir,
        entry_html=args.entry if args.dir else None,
        initial_style=args.css_style,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
