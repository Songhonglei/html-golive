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

from golive.i18n import t as _t

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
            print(_t("scanner.ext_not_found", path=p), file=sys.stderr)
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
            print(_t("scanner.regex_failed", name=r.get('name'), error=e), file=sys.stderr)

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


#: What follows a credential keyword when it is documentation, not a secret:
#: ``password=***``, ``API_KEY=<your-key-here>``, ``token: {{ token }}``,
#: ``secret_key = "REPLACE_ME"``, ``pwd=$DB_PASSWORD``.
_PLACEHOLDER_VALUE_RE = re.compile(
    r'''\s*["'`]?\s*(
          [*x•.]{2,}                        # ***  xxx  ...
        | <[^>]{0,40}>                       # <your-key-here>
        | \{\{?[^}]{0,40}\}?\}               # {{ token }} / {KEY}
        | \$[A-Za-z_][A-Za-z0-9_]*           # $DB_PASSWORD
        | %[A-Za-z_][A-Za-z0-9_]*%           # %TOKEN%
        | (?:your|my|the)[\s_\-]?[a-z_\-]{0,20}
          (?:key|token|secret|password)(?:[\s_\-]?here)?
        | (?:xxx+|yyy+|zzz+|foo|bar|baz|todo|tbd|changeme|change_me)
        | replace[\s_\-]?me
        | (?:placeholder|example|sample|dummy|fake|redacted)[a-z_\-]{0,12}
        | \.\.\.
      )''',
    re.IGNORECASE | re.VERBOSE)


def _is_placeholder_at(content: str, idx: int, keyword: str) -> bool:
    """True when the keyword at ``idx`` is followed by a placeholder value.

    ``password=***`` in a setup guide is not a leaked password, and blocking
    it teaches people to publish with the scan waived — which is how a real
    secret gets through later. Only applies to assignment-shaped keywords
    (``password=``, ``api_key``): a bare mention was already only a weak hit.
    """
    tail = content[idx + len(keyword):idx + len(keyword) + 64]
    # Decode entities first: a guide written in HTML carries the placeholder
    # as `&lt;your-key-here&gt;`, and matching the raw text misses it.
    import html as _html
    tail = _html.unescape(tail)
    # Skip an "=" or ":" that is part of the value, not the keyword.
    tail = re.sub(r'^\s*[=:]\s*', '', tail, count=1)
    # Documentation often keeps the credential's *type* prefix and replaces
    # only the secret part: `API_KEY=sk-REPLACE_ME`, `token=Bearer <yours>`.
    # Skipping a known, short prefix lets those through. Deliberately a fixed
    # list and anchored: an arbitrary leading run would let a real secret
    # dress itself up as a prefix.
    tail = re.sub(r'^(?:sk-|pk-|Bearer\s+|Basic\s+|token\s+)', '', tail,
                  count=1, flags=re.IGNORECASE)
    match = _PLACEHOLDER_VALUE_RE.match(tail)
    if match:
        # The placeholder has to *be* the whole value, not merely start it.
        # Matching a prefix would hand out a bypass: `password=xxxRealSecret`
        # would read as a placeholder and publish the secret after it.
        rest = tail[match.end():]
        rest = rest.lstrip('"\'`')
        # Anything that continues the value (word characters, punctuation used
        # in secrets) means this was not a placeholder after all. A closing
        # tag, quote, whitespace or line end is fine.
        if not re.match(r'[A-Za-z0-9+/=@!$%^&*_\-.]', rest):
            return True
    # An empty value is a template too: `password=` at end of line.
    return not tail.strip() or tail.lstrip().startswith(("\n", "<"))


def _is_placeholder_match(m) -> bool:
    """True when a regex hit is documentation rather than a live credential.

    Works on the matched text itself, since a shape rule matches name *and*
    value in one go (``secret_key = "REPLACE_ME"``). Splits at the first
    ``=`` or ``:`` and reuses the value test, so the two paths cannot drift
    apart on what counts as a placeholder.
    """
    text = m.group(0)
    # Only assignment-shaped matches can carry a placeholder value. A private
    # key header or a bare AKIA key has no value part and is never exempt.
    parts = re.split(r'[=:]', text, maxsplit=1)
    if len(parts) != 2:
        return False
    name, value = parts
    if not re.search(r'[A-Za-z]', name):
        return False
    # Reuse the keyword-path logic by handing it a synthetic "key=value".
    probe = "password=" + value.strip().strip('"\'`')
    return _is_placeholder_at(probe, 0, "password=")


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


def _mask_secret_literal(s: str) -> str:
    """Redact the secret-bearing part of a literal, keeping it recognisable.

    Single source of truth for redaction: both the context snippet and the
    ``keyword`` field on a finding go through here. The finding is printed to
    stderr and may end up in CI logs, terminal scrollback or a screenshot
    attached to a bug report, so "truncate to N characters" is not enough —
    the first 24 characters of a DSN or an API key are the secret.
    """
    # scheme://user:password@host  → keep scheme and user, drop the password
    s = re.sub(
        r'(\b[a-z][a-z0-9+.\-]*://[^\s:/@]{1,64}:)[^\s@/]{2,}(@|$)',
        r'\1****\2', s, flags=re.IGNORECASE)
    # key=value / token: value. The value character class has to include the
    # punctuation people actually use in passwords (@!$%^&*…), or a strong
    # password is precisely the one that escapes redaction.
    # The kept prefix must accept the same characters as the redacted tail:
    # requiring [A-Za-z0-9] for the first two meant "P@ssw0rd…" — a password
    # with punctuation early on — skipped redaction entirely.
    _VALUE_CHAR = r'[A-Za-z0-9+/=@!$%^&*()_\-.,;:?~|]'
    # Two passes, because a finding's context is a window cut out of the page
    # and the keyword can arrive clipped: "password=" reaches us as "word=".
    # Enumerating the clipped forms would be a list to get wrong, so instead:
    #
    #   pass 1  an intact keyword anywhere in the string
    #   pass 2  any "<letters>=<value>" *at the very start* of the string,
    #           where a clip can occur — a leading fragment followed by
    #           "=secret" is treated as a clipped keyword
    #
    # Pass 2 is deliberately narrow: only at position 0, and only when the
    # value looks secret-shaped (long, mixed). Mid-string assignments are
    # left to pass 1 so ordinary text like "id=12345" is not mangled.
    _ASSIGN = r'\s*[=:]\s*["\']?'
    s = re.sub(
        r'((?:key|token|secret|password|passwd|pwd)' + _ASSIGN + r')'
        r'(' + _VALUE_CHAR + r'{2})' + _VALUE_CHAR + r'{4,}',
        r'\1\2****', s, flags=re.IGNORECASE)
    s = re.sub(
        r'^((?:\.\.\.)?[A-Za-z]{2,}' + _ASSIGN + r')'
        r'(' + _VALUE_CHAR + r'{2})' + _VALUE_CHAR + r'{6,}',
        r'\1\2****', s, flags=re.IGNORECASE)
    # Recognisable credential prefixes standing alone
    s = re.sub(
        r'\b(sk-|pk-|AKIA|ASIA|LTAI|AKID|AIza|ghp_|gho_|ghs_|github_pat_'
        r'|pypi-|xox[abposr]-|eyJ)([A-Za-z0-9\-_/+=]{8,})',
        lambda m: f"{m.group(1)}{m.group(2)[:4]}****", s)
    # Long digit runs are themselves the sensitive value — a national ID,
    # phone or card number has no "key=" in front of it, so every pass above
    # missed it and the report printed all 18 digits. Keep enough head and
    # tail to recognise the finding without reproducing it.
    s = re.sub(r'\b(\d{2})\d{5,}(\d{2})\b',
               lambda m: f"{m.group(1)}****{m.group(2)}", s)
    # Bearer <jwt-or-opaque>
    s = re.sub(r'\b(Bearer\s+)([A-Za-z0-9\-_.=]{6,})',
               lambda m: f"{m.group(1)}{m.group(2)[:4]}****", s,
               flags=re.IGNORECASE)
    return s


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
    # Long digit runs (ID numbers, card numbers) — context-only, since the
    # keyword field for these rules is the pattern name, not the value.
    snippet = re.sub(r'(\d{2})\d{4,}(\d{2})', r'\1****\2', snippet)
    snippet = _mask_secret_literal(snippet)
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
            # A strong credential keyword followed only by placeholders is
            # documentation. Filtered here rather than in the rule so the
            # rule stays a plain keyword list.
            if hits and strength == "strong" \
                    and rule.get("type") == "credential":
                hits = [i for i in hits
                        if not _is_placeholder_at(content, i, kw)]
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
        m = None
        for cand in rule["pattern"].finditer(content):
            # Shape-matching rules see `secret_key = "REPLACE_ME"` as a
            # credential assignment, because the shape is exactly right — it
            # is the *value* that is a placeholder. Documentation has to stay
            # publishable here too, so the same exemption the keyword path
            # uses applies. Keep scanning: a page may document a placeholder
            # and also leak a real key, and the real one must still be found.
            if (rule.get("strength") == "strong"
                    and rule.get("type") == "credential"
                    and _is_placeholder_match(cand)):
                continue
            m = cand
            break
        if not m:
            continue
        key = ("re", rule["name"])
        if key in seen:
            continue
        seen.add(key)
        result.matched_details.append({
            "type": rule["type"],
            "name": rule["name"],
            # Truncating at 24 chars is not redaction: a DSN password or an
            # API key is mostly readable in its first 24 characters, and this
            # value is printed on the BLOCK line.
            "keyword": _mask_secret_literal(m.group(0)[:48]),
            "strength": rule["strength"],
            "context": _mask_context(content, m.group(0), at_idx=m.start()),
        })

    result.has_sensitive = bool(result.matched_details)
    result.blocked = any(d["strength"] == "strong" for d in result.matched_details)
    return result


# ── publish gate ─────────────────────────────────────────────────────────────

def run_scan(html: str, skip_scan: bool = False,
             extra_rule_files=None, cfg=None,
             skip_content: bool = False) -> tuple:
    """Scan before publish. Returns (ok_to_publish, ScanResult|None).

    Two kinds of finding, and only one of them is ever skippable:

    * **strong** — a literal secret: a private key, a database DSN, an
      ``AKIA…`` key, an 18-digit national ID. These block the publish and
      **no flag can wave them through**. A page carrying a live credential
      is not a false positive worth arguing about, and skipping it puts the
      secret on a URL someone can fetch.
    * **weak** — nouns that merely *suggest* sensitive content ("salary",
      "token"), which legitimately appear in documentation. These warn, and
      ``skip_content=True`` silences them.

    ``skip_scan`` is the pre-v0.8.2 flag that skipped *everything*. It is
    accepted for compatibility and now means the same as ``skip_content``:
    the caller is telling us about business content, not asking to publish
    a private key. See ``cli.py`` for the deprecation notice.

    When ``security.llm.base_url`` is configured, weak hits get a
    second-pass semantic review (see ai_review.py). Strong hits are never
    sent to the LLM — they are not a judgement call.
    """
    # Legacy --skip-scan degrades to "skip the content warnings", never to
    # "skip the credential scan".
    skip_content = skip_content or skip_scan

    # strict mode: user demands AI review; none configured -> refuse
    from golive.security.ai_review import review_hits, strict_mode_gate
    ok, msg = strict_mode_gate(cfg)
    if not ok:
        print(f"\n🚫 {msg}", file=sys.stderr)
        return False, None

    result = scan_html(html, load_rules(extra_rule_files))

    if result.blocked:
        print(_t("scanner.block_title"), file=sys.stderr)
        for d in result.strong_hits:
            print(_t("scanner.block_item", name=d['name'], keyword=d['keyword']), file=sys.stderr)
            print(_t("scanner.block_context", context=d['context']), file=sys.stderr)
        print(_t("scanner.block_hint"), file=sys.stderr)
        return False, result

    weak = result.weak_hits
    if weak and skip_content:
        # Content warnings waived. The scan still ran, and the result is
        # still returned so callers (and the audit log) see what was found.
        print(_t("scanner.skip_content", count=len(weak)), file=sys.stderr)
        return True, result

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
        print(_t("scanner.warn_title"), file=sys.stderr)
        for d in weak[:10]:
            reason = (d.get("ai_review") or {}).get("reason", "")
            suffix = f"（AI: {reason}）" if reason else ""
            print(_t("scanner.warn_item", name=d['name'], keyword=d['keyword'], suffix=suffix), file=sys.stderr)
        print(_t("scanner.warn_hint"), file=sys.stderr)

    return True, result


# ── AI review（M3 — golive/security/ai_review.py）───────────────────────────

def ai_review(candidates, html=None, cfg=None):
    """Compatibility shim — delegates to golive.security.ai_review."""
    from golive.security.ai_review import review_hits
    return review_hits(candidates, cfg)


# ── CLI (debug) ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=_t("scanner.cli_desc"))
    ap.add_argument("file", help=_t("scanner.cli_arg_file"))
    args = ap.parse_args()
    html_text = Path(args.file).read_text(encoding="utf-8")
    ok, res = run_scan(html_text)
    if res is not None and not res.matched_details:
        print(_t("scanner.no_sensitive"))
    sys.exit(0 if ok else 1)
