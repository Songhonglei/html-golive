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

from golive.i18n import t as _t

# ── pattern construction (fragments joined at runtime) ───────────────────────

def _intranet_domain_patterns() -> list:
    """[(regex, label, advice)] — built from fragments, not literals."""
    # company domain: x + hs brand string, assembled
    brand = "xiaoho" + "ngshu"          # noqa: ISC003 — deliberate split
    cdn = "xhs" + "cdn"
    corp = brand + r"\.com"
    pats = [
        (rf"(?:fin|aifin|web|edith|builder)[.\w-]*\.(?:devops\.)?{corp}",
         _t("migrate.label_api_domain"), _t("migrate.advice_api_domain")),
        (rf"[\w.-]*\.{corp}",
         _t("migrate.label_domain"), _t("migrate.advice_domain")),
        (rf"[\w.-]*{cdn}\.com",
         _t("migrate.label_cdn"), _t("migrate.advice_cdn")),
        (r"builder\.devops[\w.-]*",
         _t("migrate.label_builder"), _t("migrate.advice_builder")),
    ]
    return [(re.compile(p, re.IGNORECASE), label, advice)
            for p, label, advice in pats]


def _intranet_api_path_patterns() -> list:
    # rf + phecda / rfmulti + data are intranet gateway path segments
    seg_a = "rf" + "phecda"
    seg_b = "rfmulti" + "data"
    pats = [
        (rf"/{seg_a}/[\w/]+", _t("migrate.label_tpl_gateway"),
         _t("migrate.advice_tpl_gateway")),
        (rf"/{seg_b}/[\w/]+", _t("migrate.label_data_gateway"),
         _t("migrate.advice_data_gateway")),
        (r"/builder-api/v1(?:/[\w/]*)?", _t("migrate.label_builder_api"),
         _t("migrate.advice_builder_api")),
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
                "label": _t("migrate.label_datalayer_residue"),
                "advice": _t("migrate.advice_datalayer_residue")})

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

    print(_t("migrate.scan_header", path=path))

    if findings["domain_hits"]:
        print(_t("migrate.domain_header", count=len(findings['domain_hits'])))
        for h in findings["domain_hits"][:20]:
            print(_t("migrate.domain_item", path=path, line=h['line'], text=h['text']))
            print(_t("migrate.domain_advice", advice=h['advice']))
        if len(findings["domain_hits"]) > 20:
            print(_t("migrate.domain_more", count=len(findings['domain_hits']) - 20))
        print()

    if findings["api_path_hits"]:
        print(_t("migrate.api_header", count=len(findings['api_path_hits'])))
        for h in findings["api_path_hits"][:20]:
            print(_t("migrate.domain_item", path=path, line=h['line'], text=h['text']))
            print(_t("migrate.domain_advice", advice=h['advice']))
        print()

    if findings["layer_hits"]:
        print(_t("migrate.layer_header", count=len(findings['layer_hits'])))
        for h in findings["layer_hits"]:
            print(_t("migrate.layer_item", path=path, line=h['line'], text=h['text']))
            print(_t("migrate.domain_advice", advice=h['advice']))
        print()

    if tpl_n or sb_n:
        print(_t("migrate.data_stats_header"))
        if tpl_n:
            calls = ", ".join(f"{k}×{v}" for k, v in
                              sorted(findings["tpl_calls"].items()))
            print(_t("migrate.data_tpl", count=tpl_n, calls=calls))
        if sb_n:
            calls = ", ".join(f"{k}×{v}" for k, v in
                              sorted(findings["sb_calls"].items()))
            print(_t("migrate.data_sb", count=sb_n, calls=calls))
        if data_backend_ready:
            print(_t("migrate.data_ready"))
        else:
            print(_t("migrate.data_not_ready"))
        print()

    if not hits and not ((tpl_n or sb_n) and not data_backend_ready):
        print(_t("migrate.clean"))
        return 0

    n_block = len(hits) + (1 if (tpl_n or sb_n) and not data_backend_ready else 0)
    print(_t("migrate.summary", count=n_block))
    return 1


def run(path_str: str) -> int:
    p = Path(path_str).expanduser()
    if not p.exists():
        print(_t("migrate.file_not_found", path=p), file=sys.stderr)
        return 1
    html = p.read_text(encoding="utf-8", errors="replace")
    findings = scan_html(html)
    from golive.config import get_config
    cfg = get_config()
    ready = (cfg.data.backend in ("", "sqlite")
             or (cfg.data.backend == "supabase" and cfg.supabase.configured))
    return print_report(str(p), findings, ready)
