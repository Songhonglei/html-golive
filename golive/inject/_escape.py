"""golive.inject._escape — shared XSS-safe inlining helpers.

Single source of truth for embedding config values inside injected
<script> blocks. Used by template_api / supabase_api / editor /
watermark — fix once, fixed everywhere.

Threat model: any config value (model codes, site names, user-supplied
watermark text, slugs …) is attacker-influenced. When pasted verbatim
into a <script> element it must never be able to:

  1. close the <script> element early (``</script>`` in any casing —
     the HTML parser does not care about JS string quoting);
  2. open an HTML comment (``<!--`` changes script-data parsing state);
  3. terminate a JS string with the raw line separators U+2028/U+2029
     (valid in JSON, invalid inside JS string literals pre-ES2019
     and still a classic breakage vector);
  4. escape a JS comment banner via ``*/`` or a raw newline.
"""

from __future__ import annotations

import json as _json
import re


def json_for_script(value) -> str:
    """JSON-encode a value for safe inlining inside an HTML <script> block.

    The HTML parser closes a <script> as soon as it sees the literal
    ``</script>`` (case-insensitive) regardless of JS quoting. Standard
    ``json.dumps`` does not escape this. We also escape ``<!--`` and
    the JS line terminators U+2028 / U+2029 which are valid JS but not
    JSON quoted by default.
    """
    s = _json.dumps(value, ensure_ascii=False)
    # HTML parser terminates a <script> as soon as it sees </script followed
    # by whitespace / '>' / '/' — we insert a backslash after "</" to break
    # the token without changing the string value at runtime.
    s = re.sub(r"</(script)", r"<\\/\1", s, flags=re.IGNORECASE)
    s = s.replace("<!--", "<\\!--")
    s = s.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return s


def safe_comment(s) -> str:
    """Neutralise a value pasted verbatim into a JS line comment / banner.

    Blocks three escapes:
      1. ``</script>`` (any case) closes the enclosing <script> element
      2. ``*/`` closes a block comment early
      3. newline/CR/LS/PS terminates the single-line comment, letting the
         next characters run as code
    We replace them with visually equivalent, harmless variants.
    """
    if s is None:
        return ""
    s = str(s)
    # 1. break the closing tag — HTML parser accepts </script...>, </SCRIPT  >,
    #    </Script foo>, etc. — so match </script followed by any tag body.
    s = re.sub(r"</\s*script\b[^>]*>?", "<\\/script>", s, flags=re.IGNORECASE)
    # 2. break block-comment terminator
    s = s.replace("*/", "* /")
    # 3. collapse line terminators (JS line terminators: \n \r \u2028 \u2029)
    s = s.replace("\r", " ").replace("\n", " ") \
         .replace("\u2028", " ").replace("\u2029", " ")
    return s


# Backwards-compatible aliases (template_api / supabase_api historically
# exposed these under underscore names).
_json_for_script = json_for_script
_safe_comment = safe_comment
