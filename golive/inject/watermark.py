"""golive.inject.watermark — front-end canvas watermark layer (M3).

Injects a <script id="watermark-layer"> that tiles a semi-transparent
diagonal text watermark over the page (canvas -> dataURL -> repeating
background). Adapted for OSS: no vendor endpoints, no forced telemetry.

Identity source (first hit wins):
  1. AuthProvider current user — the page fetches ``{auth_me_url}``
     (``/auth/me`` on the golive server) with credentials; the watermark
     shows the display name + email *prefix* (never the full address).
  2. Static text — ``watermark.text`` in golive.yaml or
     ``GOLIVE_WATERMARK_TEXT`` / the ``--watermark <text>`` CLI flag.
  3. Page meta tag — ``<meta name="golive-watermark" content="...">``.

Delivery: inline by default (~3 KB); set ``watermark.cdn_url`` to serve
the same JS from your own CDN instead.

Reporting: opt-in only. When ``watermark.report_webhook`` is set the
page POSTs ``{slug, user, ua, ts}`` JSON once per page view; without it
the watermark is render-only (no network calls beyond identity lookup).

Kill switch: ``GOLIVE_WATERMARK_OFF=1`` disables injection entirely.
"""

from __future__ import annotations

from golive.inject import layer_attrs

import os
import re
from datetime import datetime

from golive.inject._escape import _json_for_script, _safe_comment

WATERMARK_SCRIPT_ID = "watermark-layer"

_JS_TEMPLATE = r"""
/* golive watermark layer — generated {generated_at} */
(function () {{
  'use strict';

  var CFG = {{
    text          : {text_json},
    authMeUrl     : {auth_me_url_json},
    slug          : {slug_json},
    reportWebhook : {report_webhook_json},
    opacity       : {opacity_json},
    fontSize      : {font_size_json},
    rotation      : {rotation_json},
    color         : {color_json},
  }};

  /* ── identity resolution: auth user → static text → meta tag ── */
  function _fromMeta() {{
    var m = document.querySelector('meta[name="golive-watermark"]');
    return (m && m.getAttribute('content')) || '';
  }}

  function _resolveIdentity() {{
    if (CFG.authMeUrl) {{
      return fetch(CFG.authMeUrl, {{ credentials: 'include' }})
        .then(function (r) {{
          if (!r.ok) throw new Error('auth/me HTTP ' + r.status);
          return r.json();
        }})
        .then(function (u) {{
          var email = (u && u.email) || '';
          var name = (u && (u.name || u.sub)) || '';
          var prefix = email ? email.split('@')[0] : '';
          var label = [name, prefix].filter(Boolean).join('\n');
          if (label) return label;
          throw new Error('no identity in auth/me');
        }})
        .catch(function () {{
          return CFG.text || _fromMeta();
        }});
    }}
    return Promise.resolve(CFG.text || _fromMeta());
  }}

  /* ── canvas tile ── */
  function _createTile(label) {{
    var lines = String(label).split('\n').slice(0, 2);
    var canvas = document.createElement('canvas');
    var tileW = 250, tileH = 200;
    canvas.width = tileW;
    canvas.height = tileH;
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, tileW, tileH);
    ctx.font = CFG.fontSize + 'px system-ui, -apple-system, sans-serif';
    ctx.fillStyle = 'rgba(' + CFG.color + ',' + CFG.opacity + ')';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.save();
    ctx.translate(tileW / 2, tileH / 2);
    ctx.rotate(CFG.rotation * Math.PI / 180);
    if (lines.length === 1) {{
      ctx.fillText(lines[0], 0, 0);
    }} else {{
      ctx.fillText(lines[0], 0, -10);
      ctx.fillText(lines[1], 0, 14);
    }}
    ctx.restore();
    return canvas.toDataURL();
  }}

  function _render(label) {{
    var old = document.getElementById('__golive_watermark__');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var div = document.createElement('div');
    div.id = '__golive_watermark__';
    div.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'width:100%', 'height:100%',
      'z-index:9999', 'pointer-events:none',
      'background-image:url(' + _createTile(label) + ')',
      'background-repeat:repeat', 'background-size:250px 200px',
    ].join(';');
    if (document.body) {{
      document.body.appendChild(div);
    }} else {{
      document.addEventListener('DOMContentLoaded', function () {{
        document.body.appendChild(div);
      }});
    }}
  }}

  /* ── optional webhook report (opt-in, once per page view) ── */
  function _report(label) {{
    if (!CFG.reportWebhook) return;
    try {{
      fetch(CFG.reportWebhook, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          slug: CFG.slug,
          user: label,
          ua: navigator.userAgent,
          ts: Date.now(),
        }}),
      }}).catch(function () {{}});
    }} catch (e) {{}}
  }}

  function _init() {{
    _resolveIdentity().then(function (label) {{
      if (!label) {{
        console.warn('[golive-watermark] no identity source available — '
                     + 'set watermark.text, a meta tag, or an auth provider');
        return;
      }}
      _render(label);
      _report(label.replace('\n', ' '));
      var t = null;
      window.addEventListener('resize', function () {{
        clearTimeout(t);
        t = setTimeout(function () {{ _render(label); }}, 300);
      }});
    }});
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', _init);
  }} else {{
    _init();
  }}
}})();
"""


def is_disabled() -> bool:
    """Global kill switch (debugging): GOLIVE_WATERMARK_OFF=1."""
    return os.environ.get("GOLIVE_WATERMARK_OFF", "").strip() == "1"


def generate_js(text: str = "", slug: str = "", auth_me_url: str = "",
                cfg=None) -> str:
    """Build the <script> tag (inline JS)."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    wm = cfg.watermark
    js_code = _JS_TEMPLATE.format(
        generated_at=_safe_comment(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        text_json=_json_for_script(text or wm.text or ""),
        auth_me_url_json=_json_for_script(auth_me_url or ""),
        slug_json=_json_for_script(slug or ""),
        report_webhook_json=_json_for_script(wm.report_webhook or ""),
        opacity_json=_json_for_script(float(wm.opacity)),
        font_size_json=_json_for_script(int(wm.font_size)),
        rotation_json=_json_for_script(int(wm.rotation)),
        color_json=_json_for_script(str(wm.color)),
    )
    return (f'<script id="{WATERMARK_SCRIPT_ID}" {layer_attrs("watermark")}>'
            f'\n{js_code}\n</script>')


def remove_from_html(html: str) -> str:
    """Strip any previous watermark script (idempotent injection)."""
    html = re.sub(
        r'\s*<script[^>]+id=["\']' + re.escape(WATERMARK_SCRIPT_ID)
        + r'["\'][^>]*>.*?</script>',
        "", html, flags=re.DOTALL | re.IGNORECASE)
    # CDN form: <script id=... src=...></script>
    return re.sub(
        r'\s*<script[^>]+id=["\']' + re.escape(WATERMARK_SCRIPT_ID)
        + r'["\'][^>]*/?>(?:</script>)?',
        "", html, flags=re.IGNORECASE)


def has_watermark(html: str) -> bool:
    return bool(re.search(
        r'<script[^>]+id=["\']' + re.escape(WATERMARK_SCRIPT_ID) + r'["\']',
        html, re.IGNORECASE))


def inject_into_html(html: str, text: str = "", slug: str = "",
                     auth_me_url: str = "", cfg=None) -> str:
    """Idempotently inject the watermark before </body>.

    Honors GOLIVE_WATERMARK_OFF=1 (returns html unchanged, stripping any
    previously injected watermark so the switch also disables old pages
    on republish).
    """
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    html = remove_from_html(html)
    if is_disabled():
        return html

    if cfg.watermark.cdn_url:
        import html as _html_mod
        src = _html_mod.escape(cfg.watermark.cdn_url, quote=True)
        script_tag = (f'<script id="{WATERMARK_SCRIPT_ID}" '
                      f'{layer_attrs("watermark")} src="{src}"></script>')
    else:
        script_tag = generate_js(text=text, slug=slug,
                                 auth_me_url=auth_me_url, cfg=cfg)

    if re.search(r"</body>", html, re.IGNORECASE):
        return re.sub(r"</body>", lambda m: script_tag + "\n" + m.group(0),
                      html, count=1, flags=re.IGNORECASE)
    return html + "\n" + script_tag
