#!/usr/bin/env python3
"""golive.security.scanner — rule-based sensitive-content scanner.

M1 edition: rules come from the built-in ``rules.yaml`` (plus optional user
extension files). No network, no LLM — pure deterministic matching.

Verdict model:
  strong hit  -> BLOCK  (publish refused unless --skip-scan)
  weak hit    -> WARN   (published with a warning; M3 adds optional AI review)

Public API:
  load_rules(extra_files=None) -> dict
  scan_html(html, rules=None) -> ScanResult
  run_scan(html, skip_scan=False) -> (ok: bool, result: ScanResult)
  ai_review(candidates, html) -> NotImplemented stub (M3)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_RULES_FILE = Path(__file__).parent / "rules.yaml"
_rules_cache = None


# ── rule loading ─────────────────────────────────────────────────────────────

def load_rules(extra_files=None) -> dict:
    """Load built-in rules.yaml, optionally merged with user files.

    v0.8.0: When the rules_store is available (database exists), rules
    are merged from both sources: built-in yaml (read-only) + database
    (user-managed). The database source takes precedence for
    enable/disable state.
    """
    global _rules_cache
    if _rules_cache is not None and not extra_files:
        return _rules_cache

    if yaml is None:
        raise RuntimeError("pyyaml is required for the security scanner "
                           "(pip install pyyaml)")

    # v0.8.0: try the rules store first (dual-source merge)
    try:
        from golive.backends.registry.rules_store import get_merged_rules_for_scanner
        merged = get_merged_rules_for_scanner()
        if merged["keyword_rules"] or merged["regex_rules"]:
            if not extra_files:
                _rules_cache = merged
            return merged
    except Exception:  # noqa: BLE001 — fall back to yaml-only
        pass

    # Fallback: yaml-only (pre-v0.8.0 behavior)
    data = yaml.safe_load(_RULES_FILE.read_text(encoding="utf-8")) or {}
    keyword_rules = list(data.get("keyword_rules") or [])
    regex_rules = list(data.get("regex_rules") or [])

    for f in extra_files or []:
        p = Path(f).expanduser()
        if not p.exists():
            print(f"⚠️  扩展规则文件不存在，跳过：{p}", file=sys.stderr)
            continue
        extra = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        keyword_rules.extend(extra.get("keyword_rules") or [])
        regex_rules.extend(extra.get("regex_rules") or [])

    compiled_regex = []
    for r in regex_rules:
        try:
            compiled_regex.append({
                "type": r.get("type", "unknown"),
                "name": r.get("name", "unnamed"),
                "strength": r.get("strength", "weak"),
                "pattern": re.compile(r["pattern"], re.IGNORECASE),
            })
        except (KeyError, re.error) as e:
            print(f"⚠️  规则编译失败，跳过 {r.get('name')}：{e}", file=sys.stderr)

    rules = {"keyword_rules": keyword_rules, "regex_rules": compiled_regex}
    if not extra_files:
        _rules_cache = rules
    return rules


# ── encoded-block stripping（避免 base64 流误报）────────────────────────────

def _strip_encoded_blocks(html: str) -> str:
    stripped = re.sub(
        r'data:[a-zA-Z0-9!#$&\-^_]+/[a-zA-Z0-9!#$&\-^_+.]+(?:;[^,]*)?;base64,'
        r'[A-Za-z0-9+/=\s]{20,}',
        'data:__STRIPPED_BASE64__', html, flags=re.IGNORECASE)
    stripped = re.sub(
        r'(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{60,}={0,2}(?![A-Za-z0-9+/=])',
        '__STRIPPED_BASE64_BLOB__', stripped)
    stripped = re.sub(r'(?:%[0-9A-Fa-f]{2}){8,}', '__STRIPPED_URL_ENCODED__', stripped)
    return stripped


def _extract_text_content(html: str) -> str:
    """Strip tags; keep visible text + script string literals for scanning."""
    clean_html = _strip_encoded_blocks(html)

    script_strings = []
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', clean_html,
                         re.DOTALL | re.IGNORECASE):
        for sv in re.finditer(r'["\']([^"\']{3,})["\']', m.group(1)):
            script_strings.append(sv.group(1))

    visible = re.sub(r'<script[^>]*>.*?</script>', ' ', clean_html,
                     flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r'<style[^>]*>.*?</style>', ' ', visible,
                     flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r'<[^>]+>', ' ', visible)
    visible = re.sub(r'\s+', ' ', visible)

    return clean_html + "\n" + visible + "\n" + "\n".join(script_strings)


# ── word-boundary aware keyword matching ─────────────────────────────────────

_CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
_CJK_STICKY_RIGHT = set("械户门口角落里间内外侧店铺业品具件车房屋楼层段板架")
_CJK_STICKY_LEFT = set("非反假伪准次副半")


def _is_ascii_alnum_word(kw: str) -> bool:
    return bool(kw) and all(c.isascii() and (c.isalnum() or c in "_-.") for c in kw)


def _contains_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def _find_keyword_hits(content: str, keyword: str) -> list:
    """Return character offsets where keyword truly matches (boundary-aware)."""
    if not keyword:
        return []
    text = content
    text_l = text.lower()
    kw_l = keyword.lower()
    kw_len = len(keyword)

    if _is_ascii_alnum_word(keyword):
        try:
            pat = re.compile(r'\b' + re.escape(kw_l) + r'\b', re.IGNORECASE)
            return [m.start() for m in pat.finditer(text_l)]
        except re.error:
            pass

    hits = []
    start = 0
    kw_has_cjk = _contains_cjk(keyword)
    while True:
        idx = text_l.find(kw_l, start)
        if idx < 0:
            break
        left_ch = text[idx - 1] if idx > 0 else ""
        right_ch = text[idx + kw_len] if idx + kw_len < len(text) else ""
        is_stuck = False
        if kw_has_cjk:
            if right_ch and _contains_cjk(right_ch) and right_ch in _CJK_STICKY_RIGHT:
                is_stuck = True
            if left_ch and _contains_cjk(left_ch) and left_ch in _CJK_STICKY_LEFT:
                is_stuck = True
        if not is_stuck:
            hits.append(idx)
        start = idx + max(1, kw_len)
    return hits


def _mask_context(text: str, keyword: str, window: int = 30,
                  at_idx=None) -> str:
    """Extract masked context around a hit (numbers & secrets partly hidden)."""
    if at_idx is not None and 0 <= at_idx < len(text):
        idx = at_idx
    else:
        idx = text.lower().find(keyword.lower())
    if idx == -1:
        return f"...{keyword}..."
    start = max(0, idx - window)
    end = min(len(text), idx + len(keyword) + window)
    snippet = text[start:end].strip()
    snippet = re.sub(r'(\d{2})\d{4,}(\d{2})', r'\1****\2', snippet)
    snippet = re.sub(
        r'((?:key|token|secret|password|passwd|pwd)\s*[=:]\s*["\']?)'
        r'([A-Za-z0-9+/]{4})[A-Za-z0-9+/=]{4,}',
        r'\1\2****', snippet, flags=re.IGNORECASE)
    return f"...{snippet}..."


# ── result model ─────────────────────────────────────────────────────────────

class ScanResult:
    def __init__(self):
        self.blocked: bool = False            # strong hit present
        self.has_sensitive: bool = False      # any hit present
        self.matched_details: list = []       # [{type,name,keyword,strength,context}]

    @property
    def strong_hits(self):
        return [d for d in self.matched_details if d["strength"] == "strong"]

    @property
    def weak_hits(self):
        return [d for d in self.matched_details if d["strength"] == "weak"]


# ── core scan ────────────────────────────────────────────────────────────────

def scan_html(html: str, rules: dict = None) -> ScanResult:
    if rules is None:
        rules = load_rules()
    result = ScanResult()
    content = _extract_text_content(html)
    seen = set()

    # keyword rules
    for rule in rules["keyword_rules"]:
        strength = rule.get("strength", "weak")
        for kw in rule.get("keywords") or []:
            kw = str(kw)
            hits = _find_keyword_hits(content, kw)
            if not hits:
                continue
            key = (rule.get("type"), kw.lower())
            if key in seen:
                continue
            seen.add(key)
            result.matched_details.append({
                "type": rule.get("type", "unknown"),
                "name": rule.get("name", ""),
                "keyword": kw,
                "strength": strength,
                "context": _mask_context(content, kw, at_idx=hits[0]),
            })

    # regex rules
    for rule in rules["regex_rules"]:
        m = rule["pattern"].search(content)
        if not m:
            continue
        key = ("re", rule["name"])
        if key in seen:
            continue
        seen.add(key)
        result.matched_details.append({
            "type": rule["type"],
            "name": rule["name"],
            "keyword": m.group(0)[:24],
            "strength": rule["strength"],
            "context": _mask_context(content, m.group(0), at_idx=m.start()),
        })

    result.has_sensitive = bool(result.matched_details)
    result.blocked = any(d["strength"] == "strong" for d in result.matched_details)
    return result


# ── publish gate ─────────────────────────────────────────────────────────────

def run_scan(html: str, skip_scan: bool = False,
             extra_rule_files=None, cfg=None) -> tuple:
    """Scan before publish. Returns (ok_to_publish, ScanResult|None).

    M3: when ``security.llm.base_url`` is configured, weak hits get a
    second-pass semantic review by the LLM (see ai_review.py). Strong
    hits always block — they are never sent to the LLM.
    """
    if skip_scan:
        print("⏭️  已跳过安全扫描（--skip-scan）", file=sys.stderr)
        return True, None

    # strict mode: user demands AI review; none configured -> refuse
    from golive.security.ai_review import review_hits, strict_mode_gate
    ok, msg = strict_mode_gate(cfg)
    if not ok:
        print(f"\n🚫 {msg}", file=sys.stderr)
        return False, None

    result = scan_html(html, load_rules(extra_rule_files))

    if result.blocked:
        print("\n🚫 安全扫描未通过 — 检测到疑似机密内容，发布已阻断：", file=sys.stderr)
        for d in result.strong_hits:
            print(f"   · [{d['name']}] {d['keyword']}", file=sys.stderr)
            print(f"     上下文: {d['context']}", file=sys.stderr)
        print("\n   请删除上述内容后重试；确认为误报可用 --skip-scan 跳过。",
              file=sys.stderr)
        return False, result

    weak = result.weak_hits
    if weak:
        review = review_hits(weak, cfg)
        if review.ai_used:
            print(f"🤖 {review.note}", file=sys.stderr)
            if review.dropped:
                dropped_keys = {(d["type"], d["keyword"]) for d in review.dropped}
                result.matched_details = [
                    d for d in result.matched_details
                    if not (d["strength"] == "weak"
                            and (d["type"], d["keyword"]) in dropped_keys)]
                result.has_sensitive = bool(result.matched_details)
            weak = [d for d in result.matched_details if d["strength"] == "weak"]
        elif review.note and "未配置" not in review.note:
            print(f"⚠️  {review.note}", file=sys.stderr)

    if weak:
        print("\n⚠️  安全扫描提示 — 检测到疑似敏感词（不阻断发布）：", file=sys.stderr)
        for d in weak[:10]:
            reason = (d.get("ai_review") or {}).get("reason", "")
            suffix = f"（AI: {reason}）" if reason else ""
            print(f"   · [{d['name']}] {d['keyword']}{suffix}", file=sys.stderr)
        print("   请确认页面不含真实敏感数据。", file=sys.stderr)

    return True, result


# ── AI review（M3 — golive/security/ai_review.py）───────────────────────────

def ai_review(candidates, html=None, cfg=None):
    """Compatibility shim — delegates to golive.security.ai_review."""
    from golive.security.ai_review import review_hits
    return review_hits(candidates, cfg)


# ── CLI (debug) ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="golive 安全扫描（调试用）")
    ap.add_argument("file", help="HTML 文件")
    args = ap.parse_args()
    html_text = Path(args.file).read_text(encoding="utf-8")
    ok, res = run_scan(html_text)
    if res is not None and not res.matched_details:
        print("✅ 未发现敏感内容")
    sys.exit(0 if ok else 1)
