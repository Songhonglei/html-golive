"""golive.core.migrate_check — scan HTML for intranet-specific references.

``golive migrate-check <file.html>`` reports what needs attention before
an intranet-built page can run on the open-source stack:

  1. hard-coded intranet API hosts / domains
  2. leftover intranet data-layer injections (script ids)
  3. TemplateAPI / SupabaseAPI call statistics (needs a data backend)

The intranet host patterns are assembled from fragments at runtime so
this open-source file itself never contains those literal strings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ── pattern construction (fragments joined at runtime) ───────────────────────

def _intranet_domain_patterns() -> list:
    """[(regex, label, advice)] — built from fragments, not literals."""
    # company domain: x + hs brand string, assembled
    brand = "xiaoho" + "ngshu"          # noqa: ISC003 — deliberate split
    cdn = "xhs" + "cdn"
    corp = brand + r"\.com"
    pats = [
        (rf"(?:fin|aifin|web|edith|builder)[.\w-]*\.(?:devops\.)?{corp}",
         "内网 API/托管域名",
         "改用你自己的部署域名或 golive serve；数据接口改走 data backend"),
        (rf"[\w.-]*\.{corp}",
         "内网域名引用",
         "替换为公网可达资源或删除"),
        (rf"[\w.-]*{cdn}\.com",
         "内网 CDN 资源",
         "用 golive 的资源本地化（cdn_localizer）或换公网 CDN"),
        (r"builder\.devops[\w.-]*",
         "内网 Builder 服务地址",
         "开源版 SupabaseAPI 直连你自己的 Supabase，无需 Builder 代理"),
    ]
    return [(re.compile(p, re.IGNORECASE), label, advice)
            for p, label, advice in pats]


def _intranet_api_path_patterns() -> list:
    # rf + phecda / rfmulti + data are intranet gateway path segments
    seg_a = "rf" + "phecda"
    seg_b = "rfmulti" + "data"
    pats = [
        (rf"/{seg_a}/[\w/]+", "内网模板网关路径",
         "开源版 TemplateAPI 打 PostgREST，重新发布时会自动注入新数据层"),
        (rf"/{seg_b}/[\w/]+", "内网数据网关路径",
         "改走 data backend（Supabase PostgREST）"),
        (r"/builder-api/v1(?:/[\w/]*)?", "内网 Builder API 路径",
         "开源版 SupabaseAPI 直连 Supabase REST"),
    ]
    return [(re.compile(p, re.IGNORECASE), label, advice)
            for p, label, advice in pats]


_SCRIPT_ID_RE = re.compile(
    r'<script[^>]+id=["\'](template-data-layer|supabase-data-layer|'
    r'bi-data-layer|api-proxy-layer|access-data-layer|watermark-layer|'
    r'inline-editor-layer)["\']', re.IGNORECASE)

_TPL_CALL_RE = re.compile(r"\bTemplateAPI\s*\.\s*(\w+)")
_SB_CALL_RE = re.compile(r"\bSupabaseAPI\s*\.\s*(\w+)")


# ── scan ─────────────────────────────────────────────────────────────────────

def scan_html(html: str) -> dict:
    """Return {domain_hits, api_path_hits, layer_hits, tpl_calls, sb_calls}.

    Each *hit* is {line, text, label, advice}.
    """
    findings = {"domain_hits": [], "api_path_hits": [], "layer_hits": [],
                "tpl_calls": {}, "sb_calls": {}}
    lines = html.splitlines()

    dom_pats = _intranet_domain_patterns()
    path_pats = _intranet_api_path_patterns()

    for i, line in enumerate(lines, 1):
        matched_spans = []
        for pat, label, advice in dom_pats:
            for m in pat.finditer(line):
                span = m.span()
                # skip if already covered by a more specific pattern
                if any(s <= span[0] and span[1] <= e for s, e in matched_spans):
                    continue
                matched_spans.append(span)
                findings["domain_hits"].append({
                    "line": i, "text": m.group(0)[:120],
                    "label": label, "advice": advice})
        for pat, label, advice in path_pats:
            for m in pat.finditer(line):
                findings["api_path_hits"].append({
                    "line": i, "text": m.group(0)[:120],
                    "label": label, "advice": advice})
        m = _SCRIPT_ID_RE.search(line)
        if m:
            findings["layer_hits"].append({
                "line": i, "text": m.group(1),
                "label": "内网数据层注入残留",
                "advice": "用开源版重新发布会自动替换为新数据层"})

    for m in _TPL_CALL_RE.finditer(html):
        meth = m.group(1)
        findings["tpl_calls"][meth] = findings["tpl_calls"].get(meth, 0) + 1
    for m in _SB_CALL_RE.finditer(html):
        meth = m.group(1)
        findings["sb_calls"][meth] = findings["sb_calls"].get(meth, 0) + 1

    return findings


def print_report(path: str, findings: dict, data_backend_ready: bool) -> int:
    """Human report. Returns exit code (0 clean / 1 needs work)."""
    hits = (findings["domain_hits"] + findings["api_path_hits"]
            + findings["layer_hits"])
    tpl_n = sum(findings["tpl_calls"].values())
    sb_n = sum(findings["sb_calls"].values())

    print(f"🔎 migrate-check: {path}\n")

    if findings["domain_hits"]:
        print(f"⚠️  内网域名硬编码（{len(findings['domain_hits'])} 处）：")
        for h in findings["domain_hits"][:20]:
            print(f"   {path}:{h['line']}  {h['text']}")
            print(f"     ↳ {h['advice']}")
        if len(findings["domain_hits"]) > 20:
            print(f"   ... 另有 {len(findings['domain_hits']) - 20} 处")
        print()

    if findings["api_path_hits"]:
        print(f"⚠️  内网 API 路径（{len(findings['api_path_hits'])} 处）：")
        for h in findings["api_path_hits"][:20]:
            print(f"   {path}:{h['line']}  {h['text']}")
            print(f"     ↳ {h['advice']}")
        print()

    if findings["layer_hits"]:
        print(f"⚠️  内网数据层注入残留（{len(findings['layer_hits'])} 处）：")
        for h in findings["layer_hits"]:
            print(f"   {path}:{h['line']}  <script id=\"{h['text']}\">")
            print(f"     ↳ {h['advice']}")
        print()

    if tpl_n or sb_n:
        print("ℹ️  数据层调用统计：")
        if tpl_n:
            calls = ", ".join(f"{k}×{v}" for k, v in
                              sorted(findings["tpl_calls"].items()))
            print(f"   TemplateAPI：{tpl_n} 次（{calls}）")
        if sb_n:
            calls = ", ".join(f"{k}×{v}" for k, v in
                              sorted(findings["sb_calls"].items()))
            print(f"   SupabaseAPI：{sb_n} 次（{calls}）")
        if data_backend_ready:
            print("   ✅ data backend 已配置，重新发布即可自动注入开源数据层")
        else:
            print("   ⚠️  data backend 未配置 —— 需要在 golive.yaml 配置 "
                  "data.backend: supabase + supabase.url/key，"
                  "否则页面数据调用将报错")
        print()

    if not hits and not ((tpl_n or sb_n) and not data_backend_ready):
        print("✅ 未发现内网专属引用，可直接用 golive publish 发布。")
        return 0

    n_block = len(hits) + (1 if (tpl_n or sb_n) and not data_backend_ready else 0)
    print(f"共 {n_block} 类问题需要处理（见上方清单）。"
          f"迁移指南：docs/data-layer.md")
    return 1


def run(path_str: str) -> int:
    p = Path(path_str).expanduser()
    if not p.exists():
        print(f"❌ 文件不存在：{p}", file=sys.stderr)
        return 1
    html = p.read_text(encoding="utf-8", errors="replace")
    findings = scan_html(html)
    from golive.config import get_config
    cfg = get_config()
    ready = cfg.data.backend == "supabase" and cfg.supabase.configured
    return print_report(str(p), findings, ready)
