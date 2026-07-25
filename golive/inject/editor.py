"""golive.inject.editor — online inline-editor layer (M3).

Injects a <script id="golive-inline-editor"> into published HTML when a
site has editing enabled (``golive publish --enable-editor``). The UI
follows the classic inline-editor pattern:

  * floating ✏️ button (bottom-right) enters edit mode
  * all text nodes become contenteditable with dashed highlight
  * toolbar (top-right): 💾 save / ✕ cancel; Esc exits
  * status toast for progress / errors
  * unsaved-changes guard on page unload

Save channel (OSS — replaces the intranet relay chain):
  PUT {serve_base}/api/sites/<slug>/content
  Headers: Authorization: Bearer <editor_token>
           X-Editor-User: <email>
Credentials come from URL params ``?editor_token=xxx&editor_user=you@x.com``
(kept in sessionStorage so they survive the post-save reload) or from an
OIDC session cookie when the server runs with auth.provider=oidc.

Image upload: POST {serve_base}/api/sites/<slug>/upload (only when the
server has an ImageUploader configured; otherwise images stay inline).

Single-writer model: no CRDT. The server snapshots the previous version
before every save (rollback covers conflicts).
"""

from __future__ import annotations

import re
from datetime import datetime

from golive.inject._escape import _json_for_script, _safe_comment

EDITOR_SCRIPT_ID = "golive-inline-editor"

_JS_TEMPLATE = r"""
/* golive inline editor — generated {generated_at} */
(function () {{
  'use strict';

  var CFG = {{
    slug      : {slug_json},
    siteName  : {site_name_json},
    apiBase   : {api_base_json},   /* '' = same origin */
  }};

  var TOKEN_KEY = '__golive_editor_token__';
  var USER_KEY  = '__golive_editor_user__';

  /* pick up ?editor_token= & ?editor_user= once, stash in sessionStorage */
  (function _grabParams() {{
    try {{
      var p = new URLSearchParams(location.search);
      var t = p.get('editor_token');
      var u = p.get('editor_user');
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      if (u) sessionStorage.setItem(USER_KEY, u);
      if (t || u) {{
        p.delete('editor_token'); p.delete('editor_user');
        var qs = p.toString();
        history.replaceState(null, '',
          location.pathname + (qs ? '?' + qs : '') + location.hash);
      }}
    }} catch (e) {{}}
  }})();

  function _token() {{ try {{ return sessionStorage.getItem(TOKEN_KEY) || ''; }} catch (e) {{ return ''; }} }}
  function _user()  {{ try {{ return sessionStorage.getItem(USER_KEY)  || ''; }} catch (e) {{ return ''; }} }}

  var _editableEls = [];
  var _dirty = false;
  var _saving = false;

  /* ── styles ── */
  var _css = [
    '#__golive_editor_fab__{{position:fixed;bottom:24px;right:24px;z-index:99998;',
    'width:44px;height:44px;border-radius:50%;border:none;cursor:pointer;',
    'background:#1f6feb;color:#fff;font-size:20px;line-height:44px;text-align:center;',
    'box-shadow:0 4px 12px rgba(31,111,235,.4);padding:0}}',
    '#__golive_editor_toolbar__{{position:fixed;top:24px;right:24px;z-index:99998;',
    'display:none;gap:8px;align-items:center}}',
    '.golive-editor-btn{{height:36px;padding:0 16px;border-radius:18px;border:none;',
    'cursor:pointer;font-size:13px;font-weight:500;white-space:nowrap;',
    'font-family:system-ui,sans-serif;transition:opacity .15s}}',
    '.golive-editor-btn:hover{{opacity:.85}}',
    '.golive-editor-btn:disabled{{opacity:.6;cursor:not-allowed}}',
    '#__golive_editor_save__{{background:#1f6feb;color:#fff;',
    'box-shadow:0 4px 12px rgba(31,111,235,.4)}}',
    '#__golive_editor_cancel__{{background:#fff;color:#555;',
    'box-shadow:0 2px 8px rgba(0,0,0,.15)}}',
    '#__golive_editor_status__{{position:fixed;top:72px;left:50%;',
    'transform:translateX(-50%);max-width:min(520px,calc(100vw - 48px));',
    'z-index:99999;padding:8px 14px;border-radius:8px;font-size:13px;',
    'font-family:system-ui,sans-serif;pointer-events:none;opacity:0;',
    'transition:opacity .2s;line-height:1.5;text-align:center;',
    'box-shadow:0 4px 16px rgba(0,0,0,.25);white-space:pre-wrap}}',
    '#__golive_editor_status__.ok{{background:rgba(22,163,74,.92);color:#fff}}',
    '#__golive_editor_status__.err{{background:rgba(220,38,38,.92);color:#fff}}',
    '#__golive_editor_status__.info{{background:rgba(30,30,30,.88);color:#fff}}',
    'body.golive-edit-mode [contenteditable="true"]{{',
    'outline:1.5px dashed rgba(31,111,235,.45)!important;border-radius:3px;cursor:text}}',
    'body.golive-edit-mode [contenteditable="true"]:focus{{',
    'outline:2px solid #1f6feb!important;background:rgba(31,111,235,.05)!important}}',
  ].join('');

  var EDITOR_IDS = ['__golive_editor_fab__', '__golive_editor_toolbar__',
                    '__golive_editor_status__', '__golive_editor_style__'];

  /* ── UI construction ── */
  function _buildUI() {{
    if (document.getElementById('__golive_editor_fab__')) return;
    var style = document.createElement('style');
    style.id = '__golive_editor_style__';
    style.textContent = _css;
    document.head.appendChild(style);

    var fab = document.createElement('button');
    fab.id = '__golive_editor_fab__';
    fab.title = 'Edit this page';
    fab.textContent = '✏️';
    fab.onclick = _enterEditMode;
    document.body.appendChild(fab);

    var bar = document.createElement('div');
    bar.id = '__golive_editor_toolbar__';
    var cancel = document.createElement('button');
    cancel.id = '__golive_editor_cancel__';
    cancel.className = 'golive-editor-btn';
    cancel.textContent = '✕ 取消';
    cancel.onclick = _exitEditMode;
    var save = document.createElement('button');
    save.id = '__golive_editor_save__';
    save.className = 'golive-editor-btn';
    save.textContent = '💾 保存';
    save.onclick = _save;
    bar.appendChild(cancel);
    bar.appendChild(save);
    document.body.appendChild(bar);

    var status = document.createElement('div');
    status.id = '__golive_editor_status__';
    document.body.appendChild(status);
  }}

  function _showStatus(msg, kind, ms) {{
    var el = document.getElementById('__golive_editor_status__');
    if (!el) return;
    el.textContent = msg;
    el.className = kind || 'info';
    el.style.opacity = '1';
    clearTimeout(el.__t);
    if (ms) el.__t = setTimeout(function () {{ el.style.opacity = '0'; }}, ms);
  }}

  /* ── editable collection ── */
  var TEXT_TAGS = 'h1,h2,h3,h4,h5,h6,p,li,td,th,span,a,button,label,figcaption,blockquote,dt,dd,caption,small,strong,em,b,i';
  function _collectEditables() {{
    _editableEls = [];
    var nodes = document.querySelectorAll(TEXT_TAGS);
    for (var i = 0; i < nodes.length; i++) {{
      var el = nodes[i];
      if (EDITOR_IDS.indexOf(el.id) !== -1) continue;
      if (el.closest && el.closest('#__golive_editor_toolbar__')) continue;
      /* leaf-ish nodes with direct text only */
      var hasText = false;
      for (var j = 0; j < el.childNodes.length; j++) {{
        var n = el.childNodes[j];
        if (n.nodeType === 3 && n.textContent.trim()) {{ hasText = true; break; }}
      }}
      if (hasText) _editableEls.push(el);
    }}
  }}

  function _enterEditMode() {{
    _buildUI();
    document.getElementById('__golive_editor_fab__').style.display = 'none';
    document.getElementById('__golive_editor_toolbar__').style.display = 'flex';
    document.body.classList.add('golive-edit-mode');
    _collectEditables();
    _editableEls.forEach(function (el) {{
      el.setAttribute('contenteditable', 'true');
      el.setAttribute('spellcheck', 'false');
      el.addEventListener('input', _markDirty);
    }});
    document.addEventListener('keydown', _onKey);
    window.addEventListener('beforeunload', _unloadGuard);
    _showStatus('✏️ 编辑模式已开启，点击文字即可修改', 'info', 3000);
  }}

  function _markDirty() {{ _dirty = true; }}

  function _unloadGuard(e) {{
    if (_dirty && !_saving) {{
      e.preventDefault();
      e.returnValue = '有未保存的修改，确定离开？';
      return e.returnValue;
    }}
  }}

  function _onKey(e) {{ if (e.key === 'Escape') _exitEditMode(); }}

  function _exitEditMode() {{
    if (_dirty && !confirm('有未保存的修改，确定退出编辑？')) return;
    document.body.classList.remove('golive-edit-mode');
    _editableEls.forEach(function (el) {{
      el.removeAttribute('contenteditable');
      el.removeAttribute('spellcheck');
      el.removeEventListener('input', _markDirty);
    }});
    _editableEls = [];
    _dirty = false;
    var bar = document.getElementById('__golive_editor_toolbar__');
    if (bar) bar.style.display = 'none';
    var fab = document.getElementById('__golive_editor_fab__');
    if (fab) fab.style.display = '';
    document.removeEventListener('keydown', _onKey);
    window.removeEventListener('beforeunload', _unloadGuard);
  }}

  /* ── serialization: strip editor artifacts ── */
  function _getCleanHTML() {{
    var clone = document.documentElement.cloneNode(true);
    ['contenteditable', 'spellcheck'].forEach(function (attr) {{
      var els = clone.querySelectorAll('[' + attr + ']');
      for (var i = 0; i < els.length; i++) els[i].removeAttribute(attr);
    }});
    EDITOR_IDS.forEach(function (id) {{
      var el = clone.querySelector('#' + id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    }});
    var wm = clone.querySelector('#__golive_watermark__');
    if (wm && wm.parentNode) wm.parentNode.removeChild(wm);
    var body = clone.querySelector('body');
    if (body) body.classList.remove('golive-edit-mode');
    return '<!DOCTYPE html>\n' + clone.outerHTML;
  }}

  /* ── save ── */
  function _save() {{
    if (_saving) return;
    var token = _token();
    var user = _user();
    if (!token) {{
      _showStatus('❌ 缺少编辑令牌：请通过 ?editor_token=xxx&editor_user=you@example.com 打开页面',
                  'err', 6000);
      return;
    }}
    _saving = true;
    var btn = document.getElementById('__golive_editor_save__');
    btn.disabled = true;
    btn.textContent = '⏳ 保存中…';
    _showStatus('⏳ 正在保存…', 'info', 0);

    var html = _getCleanHTML();
    var url = (CFG.apiBase || '') + '/api/sites/'
              + encodeURIComponent(CFG.slug) + '/content';
    fetch(url, {{
      method: 'PUT',
      credentials: 'include',
      headers: {{
        'Content-Type': 'text/html; charset=utf-8',
        'Authorization': 'Bearer ' + token,
        'X-Editor-User': user,
      }},
      body: html,
    }})
    .then(function (r) {{
      return r.json().catch(function () {{ return {{}}; }}).then(function (j) {{
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      }});
    }})
    .then(function (j) {{
      _dirty = false;
      _showStatus('✅ 已保存（快照 ' + (j.snapshot_id || '-') + '），即将刷新…', 'ok', 2000);
      setTimeout(function () {{ location.reload(); }}, 1200);
    }})
    .catch(function (e) {{
      _saving = false;
      btn.disabled = false;
      btn.textContent = '💾 保存';
      _showStatus('❌ 保存失败：' + e.message, 'err', 8000);
    }});
  }}

  /* ── boot ── */
  function _init() {{
    _buildUI();
    try {{
      if (new URLSearchParams(location.search).get('edit') === '1') _enterEditMode();
    }} catch (e) {{}}
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', _init);
  }} else {{
    _init();
  }}
}})();
"""


def generate_js(slug: str, site_name: str = "", api_base: str = "") -> str:
    """Build the injectable editor <script> tag."""
    js_code = _JS_TEMPLATE.format(
        generated_at=_safe_comment(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        slug_json=_json_for_script(slug),
        site_name_json=_json_for_script(site_name or ""),
        api_base_json=_json_for_script(api_base.rstrip("/") if api_base else ""),
    )
    return f'<script id="{EDITOR_SCRIPT_ID}">\n{js_code}\n</script>'


def remove_from_html(html: str) -> str:
    """Strip any previous editor script (idempotent injection)."""
    return re.sub(
        r'\s*<script[^>]+id=["\']' + re.escape(EDITOR_SCRIPT_ID)
        + r'["\'][^>]*>.*?</script>',
        "", html, flags=re.DOTALL | re.IGNORECASE)


def has_editor(html: str) -> bool:
    return bool(re.search(
        r'<script[^>]+id=["\']' + re.escape(EDITOR_SCRIPT_ID) + r'["\']',
        html, re.IGNORECASE))


def inject_into_html(html: str, slug: str, site_name: str = "",
                     api_base: str = "") -> str:
    """Idempotently inject the editor layer before </body>."""
    script_tag = generate_js(slug, site_name=site_name, api_base=api_base)
    html = remove_from_html(html)
    if re.search(r"</body>", html, re.IGNORECASE):
        return re.sub(r"</body>", lambda m: script_tag + "\n" + m.group(0),
                      html, count=1, flags=re.IGNORECASE)
    return html + "\n" + script_tag
