"""golive.inject.supabase_api — window.SupabaseAPI injection (OSS).

Signature-compatible with the intranet version:

  init() / getUser() / isReady() / onReady(cb) / logout()
  query(table, opts) / insert(table, rows) / update(table, filters, values)
  / delete(table, filters) + _config + _request

Semantics preserved:
  * query opts: {select, filters, order, limit, offset} (PostgREST syntax,
    limit cap 500, offset cap 10000) -> resolves {rows, count?}
  * insert accepts a row or an array -> resolves {rows} incl. generated ids
  * update/delete take PostgREST-style filters ({id: 'eq.1'})
  * ``supabaseapi:ready`` CustomEvent after init

OSS difference: the browser talks straight to the user's own Supabase
project (anon key). There is no OAuth broker — init() resolves
immediately with the statically configured identity (or null) and
logout() is a no-op with a console hint. ⚠️ The anon key is embedded in
the page; protect your tables with RLS policies (see docs/data-layer.md).
"""

from __future__ import annotations

import json as _json
import re

from golive.inject import SUPABASE_SCRIPT_ID, layer_attrs

_JS_TEMPLATE = r"""
/* ============================================================
   SYSTEM INJECTED CODE — DO NOT MODIFY!
   Modifying this block will break Supabase data functionality!!
   golive Supabase data layer (auto injected)
   project    : {project_display}
   generated  : {generated_at}
   ============================================================ */
(function () {{
  'use strict';

  /* ── config ── */
  var CFG = {{
    supabaseUrl : {supabase_url_json},
    restBase    : {rest_url_json},
    apiKey      : {anon_key_json},
    user        : {user_json},          // static identity or null
    tablePrefix : {table_prefix_json},  // optional logical-name prefix
  }};

  /* ── hard block when unconfigured ── */
  if (!CFG.restBase || !CFG.apiKey) {{
    var _blockedMsg = '[SupabaseAPI] not ready: no Supabase backend configured. ' +
      'Set supabase.url + anon key in golive.yaml (data.backend: supabase) and republish.';
    var _blockedFn = function() {{
      console.error(_blockedMsg);
      return Promise.reject(new Error(_blockedMsg));
    }};
    window.SupabaseAPI = {{
      init    : _blockedFn,
      getUser : function() {{ return null; }},
      isReady : function() {{ return false; }},
      onReady : function() {{ console.error(_blockedMsg); }},
      logout  : function() {{}},
      query   : _blockedFn,
      insert  : _blockedFn,
      update  : _blockedFn,
      delete  : _blockedFn,
      _config : CFG,
      _blocked: true,
    }};
    window.SUPABASE_CONFIG = CFG;
    console.error(_blockedMsg + ' Site: ' + location.href);
    return;
  }}

  var _user = CFG.user;
  var _ready = false;

  /* ── HTTP (PostgREST) ── */
  function _headers(extra) {{
    var h = {{
      'apikey'        : CFG.apiKey,
      'Authorization' : 'Bearer ' + CFG.apiKey,
      'Content-Type'  : 'application/json',
    }};
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }}

  function _tbl(table) {{
    return CFG.tablePrefix ? CFG.tablePrefix + table : table;
  }}

  function _request(method, path, body, opts) {{
    opts = opts || {{}};
    var url = CFG.restBase + (path.charAt(0) === '/' ? path : '/' + path);
    var init = {{ method: method, headers: _headers(opts.headers) }};
    if (body !== undefined && body !== null) {{
      init.body = (typeof body === 'string') ? body : JSON.stringify(body);
    }}
    return fetch(url, init).then(function (res) {{
      if (!res.ok) {{
        return res.text().then(function (t) {{
          var msg = t || res.statusText;
          try {{ var j = JSON.parse(t); msg = j.message || j.hint || msg; }} catch (e) {{}}
          throw new Error('HTTP ' + res.status + ': ' + msg);
        }});
      }}
      var total = null;
      var cr = res.headers.get('Content-Range');
      if (cr && cr.indexOf('/') !== -1) {{
        var tail = cr.split('/').pop();
        if (/^\d+$/.test(tail)) total = parseInt(tail, 10);
      }}
      if (res.status === 204) return {{ rows: [], count: total }};
      return res.json().then(function (data) {{
        var rows = Array.isArray(data) ? data : [data];
        var out = {{ rows: rows }};
        if (total !== null) out.count = total;
        return out;
      }});
    }});
  }}

  function _init() {{
    _ready = true;
    setTimeout(function () {{
      document.dispatchEvent(new CustomEvent('supabaseapi:ready', {{
        detail: {{ user: _user }}
      }}));
    }}, 0);
    return Promise.resolve(_user);
  }}

  /* ── public API ── */
  var SupabaseAPI = {{

    /** Kick off init (auto-called on page load; safe to call again).
     * @returns Promise<user|null>
     */
    init: _init,

    /** Current identity (static in OSS mode; null when not configured).
     * @returns object|null
     */
    getUser: function () {{ return _user; }},

    /** Whether init completed.
     * @returns boolean
     */
    isReady: function () {{ return _ready; }},

    /** Ready callback (fires immediately when already ready).
     * @param {{function}} cb  cb(user)
     */
    onReady: function (cb) {{
      if (typeof cb !== 'function') return;
      if (_ready) {{ try {{ cb(_user); }} catch (e) {{ console.error(e); }} return; }}
      document.addEventListener('supabaseapi:ready', function (e) {{
        try {{ cb(e.detail && e.detail.user); }} catch (er) {{ console.error(er); }}
      }}, {{once: true}});
    }},

    /** No-op in OSS mode (no OAuth broker). */
    logout: function () {{
      console.warn('[SupabaseAPI] logout() is a no-op in self-hosted mode.');
    }},

    /**
     * Query rows (PostgREST syntax).
     * @param {{string}} table
     * @param {{object}} opts  {{select, filters, order, limit, offset}}
     * @returns Promise<{{rows: Array, count?: number}}>
     */
    query: function (table, opts) {{
      opts = opts || {{}};
      var qs = [];
      function add(k, v) {{ qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); }}
      if (opts.select) add('select', opts.select);
      if (opts.order)  add('order', opts.order);
      if (opts.filters) for (var k in opts.filters) add(k, opts.filters[k]);
      var lim = Math.min(opts.limit !== undefined ? opts.limit : 20, 500);
      add('limit', String(lim));
      if (opts.offset !== undefined) add('offset', String(Math.min(opts.offset, 10000)));
      return _request('GET', '/' + _tbl(table) + (qs.length ? '?' + qs.join('&') : ''),
                      null, {{ headers: {{ 'Prefer': 'count=exact' }} }});
    }},

    /**
     * Insert rows.
     * @param {{string}} table
     * @param {{Array<object>|object}} rows
     * @returns Promise<{{rows: Array}}>  incl. generated ids
     */
    insert: function (table, rows) {{
      if (!Array.isArray(rows)) rows = [rows];
      return _request('POST', '/' + _tbl(table), rows,
                      {{ headers: {{ 'Prefer': 'return=representation' }} }});
    }},

    /**
     * Update rows.
     * @param {{string}} table
     * @param {{object}} filters  PostgREST syntax, e.g. {{id: 'eq.1'}}
     * @param {{object}} values
     * @returns Promise<{{rows: Array}}>
     */
    update: function (table, filters, values) {{
      var qs = [];
      for (var k in (filters || {{}})) {{
        qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(filters[k]));
      }}
      return _request('PATCH', '/' + _tbl(table) + (qs.length ? '?' + qs.join('&') : ''),
                      values, {{ headers: {{ 'Prefer': 'return=representation' }} }});
    }},

    /**
     * Delete rows.
     * @param {{string}} table
     * @param {{object}} filters  PostgREST syntax
     * @returns Promise<{{rows: Array}}>
     */
    delete: function (table, filters) {{
      var qs = [];
      for (var k in (filters || {{}})) {{
        qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(filters[k]));
      }}
      return _request('DELETE', '/' + _tbl(table) + (qs.length ? '?' + qs.join('&') : ''),
                      null, {{ headers: {{ 'Prefer': 'return=representation' }} }});
    }},

    /* ── debug / advanced ── */
    _config: CFG,
    _request: _request,
  }};

  window.SupabaseAPI = SupabaseAPI;
  window.SUPABASE_CONFIG = CFG;

  /* auto init after DOM ready */
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', function () {{ _init(); }});
  }} else {{
    setTimeout(function () {{ _init(); }}, 0);
  }}
}})();
"""


def generate_js(supabase_url: str = "", anon_key: str = "",
                user: dict = None, table_prefix: str = "") -> str:
    """Build the injectable <script> tag.

    Empty url/key produce stub mode: every data method rejects with a
    clear configuration hint (publish is never blocked).
    """
    from datetime import datetime
    supabase_url = (supabase_url or "").rstrip("/")
    rest_url = supabase_url + "/rest/v1" if supabase_url else ""
    project_display = supabase_url.split("//")[-1] if supabase_url else "(unconfigured)"
    js_code = _JS_TEMPLATE.format(
        supabase_url_json=_json_for_script(supabase_url),
        rest_url_json=_json_for_script(rest_url),
        anon_key_json=_json_for_script(anon_key or ""),
        user_json=_json_for_script(user),
        table_prefix_json=_json_for_script(table_prefix or ""),
        project_display=_safe_comment(project_display),
        generated_at=_safe_comment(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return (f'<script id="{SUPABASE_SCRIPT_ID}" {layer_attrs("supabase")}>'
            f'\n{js_code}\n</script>')


# Shared escaping helpers — single source of truth in inject/_escape.py.
from golive.inject._escape import _json_for_script, _safe_comment  # noqa: E402


def generate_js_from_config(cfg=None) -> str:
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    user = None
    if cfg.data.user_id:
        user = {"name": cfg.data.user_id, "email": ""}
    return generate_js(cfg.supabase.url, cfg.supabase.anon_key, user=user)


def inject_into_html(html: str, cfg=None) -> str:
    """Idempotently inject window.SupabaseAPI into HTML."""
    script_tag = generate_js_from_config(cfg)
    html = remove_from_html(html)
    if re.search(r"</head>", html, re.IGNORECASE):
        return re.sub(r"</head>", lambda m: script_tag + "\n" + m.group(0),
                      html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body[^>]*>", html, re.IGNORECASE):
        return re.sub(r"<body[^>]*>", lambda m: m.group(0) + "\n" + script_tag,
                      html, count=1, flags=re.IGNORECASE)
    return script_tag + "\n" + html


def remove_from_html(html: str) -> str:
    return re.sub(
        r'\s*<script[^>]+id=["\']' + SUPABASE_SCRIPT_ID + r'["\'][^>]*>.*?</script>',
        "", html, flags=re.DOTALL | re.IGNORECASE)


def detect_usage(html: str) -> bool:
    """True when the page calls SupabaseAPI (outside our own injection)."""
    stripped = remove_from_html(html)
    return bool(re.search(r"\bSupabaseAPI\s*\.", stripped))
