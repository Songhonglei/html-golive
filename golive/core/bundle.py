#!/usr/bin/env python3
"""
bundle.py — 将多文件 Web 项目打包成单个自包含 HTML 文件。

功能：
  - 内联 CSS（含递归 @import）
  - 内联 JS
  - 图片上传到图床 → 替换为 CDN URL（或降级为 Base64）
  - 字体上传到图床 → 替换为 CDN URL
  - 处理 HTML/CSS 中的所有资源引用
  - 内联本地 JSON 数据文件（fetch / XHR 引用），注入 polyfill 拦截请求

用法（独立测试）：
  python3 bundle.py --dir ./my-project --name "我的项目"
  python3 bundle.py --dir ./my-project --no-image-upload  # 图片降级为 Base64
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

# 图片/字体扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif"}
FONT_EXTENSIONS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
BINARY_ASSET_EXTENSIONS = IMAGE_EXTENSIONS | FONT_EXTENSIONS

# JSON 内联阈值
JSON_INLINE_SILENT_LIMIT = 50 * 1024        # < 50KB：静默内联
JSON_INLINE_WARN_LIMIT   = 300 * 1024       # 50KB–300KB：内联 + 轻提示；> 300KB：交互确认

# 跳过处理的 URL 前缀（已是外链）
EXTERNAL_PREFIXES = ("http://", "https://", "data:", "//", "blob:", "mailto:", "#", "javascript:")

# 入口 HTML 候选文件名（按优先级）
HTML_ENTRY_CANDIDATES = ["index.html", "main.html", "app.html", "index.htm"]


def is_external(url: str) -> bool:
    """判断 URL 是否为外链（不需要处理）。"""
    url = url.strip()
    return any(url.startswith(p) for p in EXTERNAL_PREFIXES) or not url


def resolve_path(base_dir: Path, current_file: Path, relative_url: str) -> Path | None:
    """
    解析相对路径，返回绝对 Path（限制在 base_dir 内）。
    current_file：当前正在处理的文件路径。
    """
    url = relative_url.strip().split("?")[0].split("#")[0]  # 去掉 query string 和 anchor
    if not url:
        return None

    # 从 current_file 所在目录开始解析
    current_dir = current_file.parent
    candidate = (current_dir / url).resolve()

    # 安全检查：不能跑出 base_dir
    try:
        candidate.relative_to(base_dir.resolve())
    except ValueError:
        return None

    return candidate if candidate.exists() else None


def file_to_base64_data_uri(file_path: Path) -> str:
    """将文件转为 base64 data URI。"""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        ext = file_path.suffix.lower()
        mime_map = {
            ".svg": "image/svg+xml",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
            ".ttf": "font/ttf",
            ".otf": "font/otf",
            ".eot": "application/vnd.ms-fontobject",
            ".ico": "image/x-icon",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

    try:
        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"⚠️  资源文件读取失败，跳过内联 {file_path}: {e}", file=sys.stderr)
        raise
    return f"data:{mime_type};base64,{data}"


class Bundler:
    def __init__(
        self,
        base_dir: Path,
        uploader=None,       # ImageUploader 实例，None 则降级为 Base64
        use_image_upload: bool = True,
    ):
        self.base_dir = base_dir.resolve()
        self.uploader = uploader
        self.use_image_upload = use_image_upload
        self._processed_css: set[Path] = set()  # 防止 CSS @import 循环
        # JSON 内联相关：key=规范化引用路径, value=序列化后的 JS 安全字符串
        self._json_inline_map: dict[str, str] = {}
        # 轻提示队列（50KB-300KB 的文件，打包完成后统一输出）
        self._json_warn_list: list[tuple[str, int]] = []

    # ─── 资源处理 ────────────────────────────────────────────────────────────

    def _handle_asset(self, asset_path: Path) -> str:
        """
        处理单个资源文件（图片/字体）：
          - 有 uploader 且上传成功 → 返回 CDN URL
          - 否则 → 返回 base64 data URI
        """
        ext = asset_path.suffix.lower()
        is_binary = ext in BINARY_ASSET_EXTENSIONS

        if not is_binary:
            return ""  # 不处理非二进制资源

        # 尝试上传到图床
        if self.use_image_upload and self.uploader:
            try:
                with open(asset_path, "rb") as f:
                    image_bytes = f.read()
                cdn_url = self.uploader.upload(image_bytes, asset_path.name)
                if cdn_url:
                    print(f"  📤 上传图床: {asset_path.name} → {cdn_url}", file=sys.stderr)
                    return cdn_url
            except Exception as e:
                print(f"  ⚠️  上传失败，降级为 Base64 [{asset_path.name}]: {e}", file=sys.stderr)

        # 降级：Base64
        try:
            uri = file_to_base64_data_uri(asset_path)
            print(f"  🔒 Base64 内联: {asset_path.name}", file=sys.stderr)
            return uri
        except Exception as e:
            print(f"  ⚠️  无法读取资源文件 [{asset_path.name}]: {e}", file=sys.stderr)
            return ""

    # ─── CSS 处理 ────────────────────────────────────────────────────────────

    def _process_css_content(self, css_content: str, css_file: Path) -> str:
        """
        处理 CSS 内容：
          1. 递归内联 @import
          2. 替换 url(...) 中的本地资源引用
        """
        # 1. 递归内联 @import（处理 @import "xxx.css" 或 @import url("xxx.css")）
        def replace_import(m):
            raw = m.group(1) or m.group(2)
            url = raw.strip().strip("'\"")
            if is_external(url):
                return m.group(0)  # 保留外链
            imported_path = resolve_path(self.base_dir, css_file, url)
            if not imported_path or imported_path in self._processed_css:
                return ""  # 循环或不存在，跳过
            self._processed_css.add(imported_path)
            try:
                with open(imported_path, "r", encoding="utf-8", errors="replace") as f:
                    imported_css = f.read()
                print(f"  📎 内联 CSS @import: {imported_path.name}", file=sys.stderr)
                return self._process_css_content(imported_css, imported_path)
            except Exception as e:
                print(f"  ⚠️  无法读取 @import [{url}]: {e}", file=sys.stderr)
                return m.group(0)

        css_content = re.sub(
            r'@import\s+(?:url\(["\']?(.*?)["\']?\)|["\']([^"\']+)["\'])\s*;',
            replace_import,
            css_content,
            flags=re.IGNORECASE,
        )

        # 2. 替换 url(...) 资源引用
        def replace_url(m):
            url = (m.group(1) or m.group(2) or m.group(3)).strip()
            if is_external(url):
                return m.group(0)
            asset_path = resolve_path(self.base_dir, css_file, url)
            if not asset_path:
                return m.group(0)
            ext = asset_path.suffix.lower()
            if ext not in BINARY_ASSET_EXTENSIONS:
                return m.group(0)
            replacement = self._handle_asset(asset_path)
            if not replacement:
                return m.group(0)
            return f'url("{replacement}")'

        css_content = re.sub(
            r'url\(\s*(?:"([^"]+)"|\'([^\']+)\'|([^\s\'"()]+))\s*\)',
            replace_url,
            css_content,
            flags=re.IGNORECASE,
        )

        return css_content

    def _process_css_file(self, css_file: Path) -> str:
        """读取并处理 CSS 文件，返回处理后的内容。"""
        if css_file in self._processed_css:
            return ""
        self._processed_css.add(css_file)
        try:
            with open(css_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return self._process_css_content(content, css_file)
        except Exception as e:
            print(f"  ⚠️  无法读取 CSS 文件 [{css_file.name}]: {e}", file=sys.stderr)
            return ""

    # ─── JS 处理 ────────────────────────────────────────────────────────────

    def _process_js_file(self, js_file: Path) -> str:
        """读取 JS 文件内容（目前直接内联，不做深度分析）。"""
        try:
            with open(js_file, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            print(f"  ⚠️  无法读取 JS 文件 [{js_file.name}]: {e}", file=sys.stderr)
            return ""

    # ─── JSON 内联处理 ───────────────────────────────────────────────────────

    def _safe_json_to_js(self, file_path: Path) -> tuple[str, str | None]:
        """
        读取并验证 JSON 文件，返回 (js_safe_string, error_msg)。
        js_safe_string 已做以下安全处理：
          1. json.loads 验证格式正确性
          2. json.dumps 重新序列化（规范化 + 内置转义）
          3. </script> → <\\/script>（防止提前闭合 script 块）
          4. <!-- → <\\!--（防止 HTML 注释解析干扰）
        error_msg 不为 None 时表示失败。
        """
        try:
            raw = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            return "", f"文件编码错误（不是 UTF-8）：{e}"
        except OSError as e:
            return "", f"文件读取失败：{e}"

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            return "", (
                f"JSON 格式错误（第 {e.lineno} 行，第 {e.colno} 列）：{e.msg}\n"
                f"  → 请修复 {file_path.name} 后重新部署"
            )

        # 重新序列化（规范化 + Python 内置转义）
        safe = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        # 额外转义：防止 </script> 提前关闭 script 块
        safe = safe.replace("</script>", "<\\/script>")
        safe = safe.replace("<!--", "<\\!--")
        return safe, None

    def _scan_json_refs(self, js_source: str) -> list[str]:
        """
        扫描 JS/HTML 源码，提取所有本地 .json 文件引用。
        覆盖以下写法：
          fetch('data.json') / fetch("data.json") / fetch(`data.json`)
          .open('GET', 'data.json') — XMLHttpRequest
          axios.get('data.json') / $.getJSON('data.json') / $.get('data.json')
        只返回非外链、带 .json 后缀的路径（去重）。
        """
        patterns = [
            # fetch(...)
            r'''fetch\s*\(\s*['"`]([^'"`\s]+\.json[^'"`]*?)['"`]''',
            # XHR: .open('GET', 'data.json')
            r'''\.open\s*\(\s*['"`][A-Za-z]+['"`]\s*,\s*['"`]([^'"`\s]+\.json[^'"`]*?)['"`]''',
            # axios.get / $.getJSON / $.get
            r'''(?:axios\.get|\$\.getJSON|\$\.get)\s*\(\s*['"`]([^'"`\s]+\.json[^'"`]*?)['"`]''',
        ]
        found: list[str] = []
        seen: set[str] = set()
        for pat in patterns:
            for m in re.finditer(pat, js_source, re.IGNORECASE):
                url = m.group(1).strip()
                # 去除 query string / anchor
                url_clean = url.split("?")[0].split("#")[0]
                if is_external(url_clean):
                    continue
                if url_clean not in seen:
                    seen.add(url_clean)
                    found.append(url_clean)
        return found

    def _process_json_refs(self, html_content: str, js_sources: list[str], html_file: Path) -> None:
        """
        扫描 HTML + 已收集的 JS 源码，找出所有本地 JSON 引用，
        按大小分档处理，填充 self._json_inline_map 和 self._json_warn_list。

        大文件（> 300KB）会进行交互式确认：
          y → 强制内联（写入 _json_inline_map）
          n → 跳过（_json_inline_map 中不写入该文件）
          d → 打印数据线上化引导，取消本次部署（sys.exit(1)）
        """
        # 收集全部 JS 源（HTML 内联脚本 + 外部 JS 文件内容）
        all_js = html_content + "\n".join(js_sources)
        refs = self._scan_json_refs(all_js)

        if not refs:
            return

        # 去重：不同引用路径可能指向同一物理文件（如 data.json 和 ./data.json）
        # 先把所有 ref 解析为绝对路径，以绝对路径为 key 去重，保留第一个 ref 代表
        resolved_map: dict[Path, list[str]] = {}  # 物理路径 → [ref列表]
        for ref in refs:
            file_path = resolve_path(self.base_dir, html_file, ref)
            if file_path is None:
                print(
                    f"  ⚠️  JSON 引用未找到，跳过：{ref}",
                    file=sys.stderr,
                )
                continue
            if file_path not in resolved_map:
                resolved_map[file_path] = []
            resolved_map[file_path].append(ref)

        if not resolved_map:
            return

        # 分档处理（resolved_map: {物理路径 → [所有引用路径]}，每个物理文件只处理一次）
        large_files: list[tuple[Path, list[str], int]] = []  # 待交互确认的大文件

        for file_path, all_refs in resolved_map.items():
            size = file_path.stat().st_size

            if size > JSON_INLINE_WARN_LIMIT:
                # > 300KB：先收集，后面统一交互
                large_files.append((file_path, all_refs, size))
                continue

            # ≤ 300KB：直接内联
            safe_str, err = self._safe_json_to_js(file_path)
            if err:
                print(f"\n❌  {file_path.name} 无法内联：{err}", file=sys.stderr)
                print("本次部署已取消，请修复 JSON 文件后重新部署。", file=sys.stderr)
                sys.exit(1)

            # 注册所有等效 key：所有原始引用 + 相对路径 + 带./ + 文件名
            rel_path = str(file_path.relative_to(self.base_dir))
            keys = set(all_refs) | {rel_path, "./" + rel_path, file_path.name}
            for key in keys:
                self._json_inline_map[key] = safe_str

            if size >= 50 * 1024:
                # 50KB-300KB：轻提示
                self._json_warn_list.append((file_path.name, size))
            else:
                # < 50KB：静默
                print(f"  📋 内联 JSON: {file_path.name} ({size / 1024:.1f}KB)", file=sys.stderr)

        # 处理大文件（交互式）
        for file_path, all_refs, size in large_files:
            size_str = f"{size / 1024:.0f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
            print(
                f"\n⚠️  发现超大 JSON 文件：{file_path.name}（{size_str}）\n\n"
                f"直接内联会使页面体积增加 {size_str}，可能导致页面加载较慢。\n\n"
                f"是否仍要内联大数据 JSON，继续部署？\n"
                f"  y = 内联并继续部署（页面加载可能变慢）\n"
                f"  n = 跳过该文件，继续部署（页面中该数据将缺失）\n"
                f"  d = 引导我使用线上数据存储（推荐，数据独立管理）\n"
                f"请输入 (y/n/d)：",
                end="",
                file=sys.stderr,
            )
            try:
                choice = input().strip().lower()
            except EOFError:
                choice = "n"  # 非 TTY 环境默认跳过

            if choice == "y":
                safe_str, err = self._safe_json_to_js(file_path)
                if err:
                    print(f"\n❌  {file_path.name} 无法内联：{err}", file=sys.stderr)
                    print("本次部署已取消，请修复 JSON 文件后重新部署。", file=sys.stderr)
                    sys.exit(1)
                rel_path = str(file_path.relative_to(self.base_dir))
                keys = set(all_refs) | {rel_path, "./" + rel_path, file_path.name}
                for key in keys:
                    self._json_inline_map[key] = safe_str
                self._json_warn_list.append((file_path.name, size))
                print(f"  ✅ 已将 {file_path.name} 强制内联", file=sys.stderr)

            elif choice == "d":
                print(
                    f"\n📦 线上数据存储配置向导\n"
                    f"{'─' * 40}\n"
                    f"1. 为你的数据起一个模型名称（字母/数字/下划线，如 {file_path.stem}_v1）：\n"
                    f"   （模型名称用于在服务端标识你的数据集）\n\n"
                    f"2. 配置好后，使用以下命令重新部署：\n\n"
                    f"   python3 html_go_live.py --dir <你的项目目录> --name \"<应用名称>\" \\\n"
                    f"     --data-model {file_path.stem}_v1\n\n"
                    f"   部署完成后，页面可通过 window.TemplateAPI 读取数据，\n"
                    f"   数据更新无需重新部署页面。\n\n"
                    f"本次部署已取消，请按上方命令重新运行。",
                    file=sys.stderr,
                )
                sys.exit(0)

            else:
                # n 或其他输入 → 跳过
                print(
                    f"  ⏭️  已跳过 {file_path.name}，页面中该数据将缺失",
                    file=sys.stderr,
                )

    def _build_json_polyfill(self) -> str:
        """
        根据 self._json_inline_map 生成 fetch/XHR polyfill script 标签。
        若 _json_inline_map 为空则返回空字符串。
        注入位置：<head> 最前（由 bundle() 负责插入）。
        """
        if not self._json_inline_map:
            return ""

        # 去重：同一 JSON 内容可能被多个 key 引用（如 data.json / ./data.json）
        # 先按值内容分组，相同内容只声明一个变量，其余 key 引用该变量
        # value_str → var_name
        val_to_var: dict[str, str] = {}
        var_decls: list[str] = []     # var _v0 = {...};
        key_to_var: dict[str, str] = {}  # key → var_name

        for k, v in self._json_inline_map.items():
            if v not in val_to_var:
                var_name = f"_v{len(val_to_var)}"
                val_to_var[v] = var_name
                var_decls.append(f"var {var_name}={v};")
            key_to_var[k] = val_to_var[v]

        # _D 对象：key → 变量引用（不重复写入大值）
        entries = ",\n    ".join(
            f'{json.dumps(k, ensure_ascii=False)}: {var_name}'
            for k, var_name in key_to_var.items()
        )
        var_decls_str = "\n  ".join(var_decls)

        polyfill = f"""<script id="__go_live_json_inline__">
/* html-go-live: JSON 数据内联 polyfill */
(function(){{
  {var_decls_str}
  var _D = {{
    {entries}
  }};
  function _norm(u) {{
    return String(typeof u === 'string' ? u : (u && u.url) || '').split('?')[0].split('#')[0];
  }}
  /* patch fetch */
  if (typeof window !== 'undefined' && typeof window.fetch === 'function') {{
    var _origFetch = window.fetch.bind(window);
    window.fetch = function(input, init) {{
      var key = _norm(input);
      if (Object.prototype.hasOwnProperty.call(_D, key)) {{
        var body = JSON.stringify(_D[key]);
        return Promise.resolve(new Response(body, {{
          status: 200,
          headers: {{'Content-Type': 'application/json'}}
        }}));
      }}
      return _origFetch(input, init);
    }};
  }}
  /* patch XMLHttpRequest */
  if (typeof XMLHttpRequest !== 'undefined') {{
    var _NativeXHR = XMLHttpRequest;
    function _PatchedXHR() {{
      var _xhr = new _NativeXHR();
      var _inlineKey = null;
      var _self = this;
      /* 透传所有属性访问到底层 XHR */
      ['timeout','withCredentials','upload','responseType','onreadystatechange',
       'onload','onerror','onabort','ontimeout','onprogress','onloadstart','onloadend']
        .forEach(function(p) {{
          Object.defineProperty(_self, p, {{
            get: function() {{ return _xhr[p]; }},
            set: function(v) {{ _xhr[p] = v; }},
            enumerable: true
          }});
        }});
      ['readyState','status','statusText','response','responseText','responseXML',
       'responseURL']
        .forEach(function(p) {{
          Object.defineProperty(_self, p, {{
            get: function() {{ return _inlineKey ? _self['__inline_' + p] : _xhr[p]; }},
            enumerable: true
          }});
        }});
      _self.open = function(method, url) {{
        var key = _norm(url);
        if (Object.prototype.hasOwnProperty.call(_D, key)) {{
          _inlineKey = key;
          return;
        }}
        _inlineKey = null;
        return _xhr.open.apply(_xhr, arguments);
      }};
      _self.send = function(body) {{
        if (_inlineKey) {{
          var data = _D[_inlineKey];
          var text = JSON.stringify(data);
          _self.__inline_readyState   = 4;
          _self.__inline_status       = 200;
          _self.__inline_statusText   = 'OK';
          _self.__inline_response     = data;
          _self.__inline_responseText = text;
          _self.__inline_responseXML  = null;
          _self.__inline_responseURL  = '';
          setTimeout(function() {{
            if (typeof _xhr.onload === 'function') _xhr.onload.call(_self);
            if (typeof _xhr.onreadystatechange === 'function') _xhr.onreadystatechange.call(_self);
          }}, 0);
          return;
        }}
        /* 转发事件到外部监听器 */
        ['onload','onerror','onabort','ontimeout','onprogress',
         'onreadystatechange','onloadend']
          .forEach(function(ev) {{
            if (_self[ev]) _xhr[ev] = _self[ev];
          }});
        return _xhr.send.apply(_xhr, arguments);
      }};
      _self.abort          = function() {{ return _xhr.abort(); }};
      _self.setRequestHeader = function() {{ if (!_inlineKey) _xhr.setRequestHeader.apply(_xhr, arguments); }};
      _self.getResponseHeader = function(h) {{ return _inlineKey ? null : _xhr.getResponseHeader(h); }};
      _self.getAllResponseHeaders = function() {{ return _inlineKey ? '' : _xhr.getAllResponseHeaders(); }};
      _self.overrideMimeType = function() {{ if (!_inlineKey) _xhr.overrideMimeType.apply(_xhr, arguments); }};
      _self.addEventListener = function() {{ _xhr.addEventListener.apply(_xhr, arguments); }};
      _self.removeEventListener = function() {{ _xhr.removeEventListener.apply(_xhr, arguments); }};
      return _self;
    }}
    _PatchedXHR.prototype = _NativeXHR.prototype;
    window.XMLHttpRequest = _PatchedXHR;
  }}
  /* 调试用：列出所有已内联的 JSON 文件 */
  window.__GO_LIVE_INLINE__ = Object.keys(_D);
}})();
</script>"""
        return polyfill

    # ─── HTML 处理 ────────────────────────────────────────────────────────────

    def _process_html(self, html_content: str, html_file: Path) -> str:
        """
        处理 HTML 内容：
          1. <link rel="stylesheet" href="..."> → <style>内联</style>
          2. <script src="..."> → <script>内联</script>（同时收集 JS 源码用于 JSON 扫描）
          3. <img src="..."> → CDN URL 或 Base64
          4. style 属性 / 内联 <style> 中的 url(...) → 替换
          5. srcset 属性 → 替换每个候选
          6. JSON 数据文件内联（fetch/XHR 引用扫描 → polyfill 注入到 <head> 最前）
        """
        # 用于收集所有 JS 源码（外链 + 内联），供后续 JSON 引用扫描
        _collected_js_sources: list[str] = []

        # 1. 内联外部 CSS（<link rel="stylesheet">）
        # 使用单套健壮正则，匹配任意属性顺序的 <link> 标签，避免双重替换冲突。
        def replace_link_tag(m):
            tag = m.group(0)
            if 'stylesheet' not in tag.lower():
                return tag
            href_match = re.search(r'href=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not href_match:
                return tag
            href = href_match.group(1)
            if is_external(href):
                return tag
            css_path = resolve_path(self.base_dir, html_file, href)
            if not css_path:
                return tag
            print(f"  📎 内联 CSS: {css_path.name}", file=sys.stderr)
            css_content = self._process_css_file(css_path)
            return f"<style>\n{css_content}\n</style>"

        html_content = re.sub(
            r'<link\b[^>]+>',
            replace_link_tag,
            html_content,
            flags=re.IGNORECASE,
        )

        # 2. 内联外部 JS（<script src="...">）+ 收集内联脚本源码供 JSON 扫描
        def replace_script_tag(m):
            tag_open = m.group(1)  # 不含末尾 >，纯属性部分
            inline_body = m.group(2)  # script 标签内原有内容（外链时为空）

            src_match = re.search(r'src=["\']([^"\']+)["\']', tag_open, re.IGNORECASE)
            if not src_match:
                # 内联脚本：收集源码
                if inline_body and inline_body.strip():
                    _collected_js_sources.append(inline_body)
                return m.group(0)
            src = src_match.group(1)
            if is_external(src):
                return m.group(0)
            js_path = resolve_path(self.base_dir, html_file, src)
            if not js_path:
                return m.group(0)
            print(f"  📎 内联 JS: {js_path.name}", file=sys.stderr)
            js_content = self._process_js_file(js_path)
            # 收集外链 JS 源码
            _collected_js_sources.append(js_content)
            # 保留除 src 之外的属性（如 type 等），defer/async 对内联 script 无意义
            attrs = re.sub(r'\s*src=["\'][^"\']+["\']', '', tag_open, flags=re.IGNORECASE)
            attrs = re.sub(r'\s*(defer|async)\b', '', attrs, flags=re.IGNORECASE)
            return f"{attrs}>\n{js_content}\n</script>"

        html_content = re.sub(
            r'(<script\b[^>]*)>(.*?)</script>',  # group(1) 不含 >
            replace_script_tag,
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 2b. JSON 数据文件扫描 & 内联（在 CSS/JS 处理完成后，图片处理之前）
        # 此时 _collected_js_sources 已包含所有 JS 内容，html_content 含内联脚本
        self._process_json_refs(html_content, _collected_js_sources, html_file)

        # 3. 替换 <img src="..."> 和 <img srcset="...">
        def replace_img_src(m):
            tag = m.group(0)

            # src 属性
            def replace_src(sm):
                src = sm.group(1) or sm.group(2)
                if is_external(src):
                    return sm.group(0)
                asset_path = resolve_path(self.base_dir, html_file, src)
                if not asset_path:
                    return sm.group(0)
                ext = asset_path.suffix.lower()
                if ext not in IMAGE_EXTENSIONS:
                    return sm.group(0)
                replacement = self._handle_asset(asset_path)
                if not replacement:
                    return sm.group(0)
                quote = '"' if sm.group(1) else "'"
                return f'src={quote}{replacement}{quote}'

            tag = re.sub(r'src="([^"]+)"|src=\'([^\']+)\'', replace_src, tag, flags=re.IGNORECASE)

            # srcset 属性（格式："url 1x, url2 2x"）
            def replace_srcset(sm):
                srcset_val = sm.group(1) or sm.group(2)
                parts = srcset_val.split(",")
                new_parts = []
                for part in parts:
                    part = part.strip()
                    tokens = part.split()
                    if not tokens:
                        continue
                    src_url = tokens[0]
                    descriptor = " ".join(tokens[1:])  # 如 "1x" 或 "320w"
                    if not is_external(src_url):
                        asset_path = resolve_path(self.base_dir, html_file, src_url)
                        if asset_path and asset_path.suffix.lower() in IMAGE_EXTENSIONS:
                            replacement = self._handle_asset(asset_path)
                            if replacement:
                                src_url = replacement
                    new_parts.append(f"{src_url} {descriptor}".strip())
                new_srcset = ", ".join(new_parts)
                quote = '"' if sm.group(1) else "'"
                return f'srcset={quote}{new_srcset}{quote}'

            tag = re.sub(
                r'srcset="([^"]+)"|srcset=\'([^\']+)\'',
                replace_srcset, tag, flags=re.IGNORECASE
            )
            return tag

        html_content = re.sub(
            r'<img\b[^>]+>',
            replace_img_src,
            html_content,
            flags=re.IGNORECASE,
        )

        # 4. 处理其他带 src 的标签（<source>, <video poster>, <audio src>）
        def replace_generic_src(m):
            tag = m.group(0)

            def replace_src_attr(sm):
                src = sm.group(1) or sm.group(2)
                if is_external(src):
                    return sm.group(0)
                asset_path = resolve_path(self.base_dir, html_file, src)
                if not asset_path:
                    return sm.group(0)
                ext = asset_path.suffix.lower()
                if ext not in IMAGE_EXTENSIONS:
                    return sm.group(0)
                replacement = self._handle_asset(asset_path)
                if not replacement:
                    return sm.group(0)
                quote = '"' if sm.group(1) else "'"
                return f'src={quote}{replacement}{quote}'

            return re.sub(r'src="([^"]+)"|src=\'([^\']+)\'', replace_src_attr, tag, flags=re.IGNORECASE)

        html_content = re.sub(
            r'<(?:source|video|audio)\b[^>]+>',
            replace_generic_src,
            html_content,
            flags=re.IGNORECASE,
        )

        # 5. 处理 style 属性（inline style）中的 url(...)
        def replace_style_attr(m):
            style_val = m.group(1)

            def replace_url_in_style(um):
                url = (um.group(1) or um.group(2) or um.group(3)).strip()
                if is_external(url):
                    return um.group(0)
                asset_path = resolve_path(self.base_dir, html_file, url)
                if not asset_path:
                    return um.group(0)
                ext = asset_path.suffix.lower()
                if ext not in BINARY_ASSET_EXTENSIONS:
                    return um.group(0)
                replacement = self._handle_asset(asset_path)
                if not replacement:
                    return um.group(0)
                return f'url("{replacement}")'

            new_style = re.sub(
                r'url\(\s*(?:"([^"]+)"|\'([^\']+)\'|([^\s\'"()]+))\s*\)',
                replace_url_in_style,
                style_val,
                flags=re.IGNORECASE,
            )
            return f'style="{new_style}"'

        html_content = re.sub(
            r'style="([^"]+)"',
            replace_style_attr,
            html_content,
            flags=re.IGNORECASE,
        )

        # 6. 处理内联 <style> 块中的 url(...)
        def replace_style_block(m):
            style_content = m.group(1)
            processed = self._process_css_content(style_content, html_file)
            return f"<style>{processed}</style>"

        html_content = re.sub(
            r'<style[^>]*>(.*?)</style>',
            replace_style_block,
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 7. 处理 background 属性（某些旧写法）
        def replace_background_attr(m):
            url = m.group(1)
            if is_external(url):
                return m.group(0)
            asset_path = resolve_path(self.base_dir, html_file, url)
            if not asset_path or asset_path.suffix.lower() not in IMAGE_EXTENSIONS:
                return m.group(0)
            replacement = self._handle_asset(asset_path)
            if not replacement:
                return m.group(0)
            return f'background="{replacement}"'

        html_content = re.sub(
            r'background="([^"]+)"',
            replace_background_attr,
            html_content,
            flags=re.IGNORECASE,
        )

        # 8. 注入 JSON polyfill（紧跟 <head> 之后，在所有用户脚本之前）
        polyfill = self._build_json_polyfill()
        if polyfill:
            # 找 <head> 标签（含属性），插入到其后
            head_match = re.search(r'<head\b[^>]*>', html_content, re.IGNORECASE)
            if head_match:
                insert_pos = head_match.end()
                html_content = (
                    html_content[:insert_pos]
                    + "\n" + polyfill + "\n"
                    + html_content[insert_pos:]
                )
            else:
                # 没有 <head>，插入到 <html> 后或文档最前
                html_match = re.search(r'<html\b[^>]*>', html_content, re.IGNORECASE)
                insert_pos = html_match.end() if html_match else 0
                html_content = (
                    html_content[:insert_pos]
                    + "\n" + polyfill + "\n"
                    + html_content[insert_pos:]
                )

            # 输出轻提示（50KB-300KB 文件）
            for fname, fsize in self._json_warn_list:
                size_str = f"{fsize / 1024:.0f}KB"
                print(
                    f"\n  ℹ️  已内联 JSON 数据：{fname}（{size_str}）\n"
                    f"     数据已写入 HTML，更新数据需重新部署。\n"
                    f"     如需动态更新，可改用 --data-model（线上存储）。",
                    file=sys.stderr,
                )

        return html_content

    # ─── 主入口 ──────────────────────────────────────────────────────────────

    def find_entry_html(self) -> Path | None:
        """在 base_dir 中找入口 HTML 文件。"""
        # 按优先级找候选
        for candidate in HTML_ENTRY_CANDIDATES:
            p = self.base_dir / candidate
            if p.exists():
                return p

        # 找所有 HTML 文件
        html_files = list(self.base_dir.glob("*.html")) + list(self.base_dir.glob("*.htm"))
        if len(html_files) == 1:
            return html_files[0]

        return None  # 多个或没有，由调用方处理

    def bundle(self, entry_html: Path | None = None) -> str:
        """
        打包指定入口 HTML 文件，返回单个自包含 HTML 字符串。
        entry_html 为 None 时自动查找入口。
        """
        if entry_html is None:
            entry_html = self.find_entry_html()
            if entry_html is None:
                raise FileNotFoundError(
                    f"在 {self.base_dir} 中未找到入口 HTML 文件，"
                    f"请确认目录中存在 index.html 或其他 HTML 文件。"
                )

        print(f"🔍 入口文件: {entry_html.name}", file=sys.stderr)

        try:
            with open(entry_html, "r", encoding="utf-8", errors="replace") as f:
                html_content = f.read()
        except (PermissionError, OSError) as e:
            raise OSError(f"无法读取入口 HTML 文件 {entry_html}: {e}") from e

        print("⚙️  开始打包...", file=sys.stderr)
        result = self._process_html(html_content, entry_html)
        print("✅ 打包完成", file=sys.stderr)
        return result


def find_entry_interactive(base_dir: Path) -> Path:
    """当有多个 HTML 文件时，交互式让用户选择入口。"""
    html_files = (
        list(base_dir.glob("*.html")) +
        list(base_dir.glob("*.htm")) +
        list(base_dir.rglob("*.html"))
    )
    # 去重，优先根目录
    seen = set()
    unique_files = []
    for f in html_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    if not unique_files:
        raise FileNotFoundError(f"在 {base_dir} 中未找到任何 HTML 文件")

    if len(unique_files) == 1:
        return unique_files[0]

    print("⚠️  找到多个 HTML 文件，请选择入口：", file=sys.stderr)
    for i, f in enumerate(unique_files, 1):
        rel = f.relative_to(base_dir)
        print(f"  {i}. {rel}", file=sys.stderr)
    print("请输入序号：", file=sys.stderr, end=" ")
    choice = input().strip()
    try:
        idx = int(choice) - 1
        return unique_files[idx]
    except (ValueError, IndexError):
        raise ValueError(f"无效序号：{choice}")


# ── 独立测试入口 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将多文件项目打包为单 HTML")
    parser.add_argument("--dir", "-d", required=True, help="项目文件夹路径")
    parser.add_argument("--entry", "-e", help="指定入口 HTML 文件（相对于 --dir）")
    parser.add_argument("--no-image-upload", action="store_true", help="禁用图床上传，图片降级为 Base64")
    parser.add_argument("--output", "-o", help="输出文件路径（默认输出到 stdout）")
    args = parser.parse_args()

    base_dir = Path(args.dir).resolve()
    if not base_dir.is_dir():
        print(f"错误：不是有效目录：{args.dir}", file=sys.stderr)
        sys.exit(1)

    # 图床上传：M1 不提供（ImageUploader backend 在 M2 引入），图片一律 Base64 内联
    uploader = None

    bundler = Bundler(base_dir, uploader=uploader, use_image_upload=not args.no_image_upload)

    entry = None
    if args.entry:
        entry = (base_dir / args.entry).resolve()
        if not entry.exists():
            print(f"错误：入口文件不存在：{entry}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            entry = bundler.find_entry_html()
            if entry is None:
                entry = find_entry_interactive(base_dir)
        except Exception as e:
            print(f"错误：{e}", file=sys.stderr)
            sys.exit(1)

    try:
        result = bundler.bundle(entry)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result)
            size_kb = len(result.encode("utf-8")) / 1024
            print(f"💾 已写入: {args.output} ({size_kb:.1f} KB)", file=sys.stderr)
        else:
            print(result)
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
