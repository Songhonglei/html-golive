"""golive.inject.template_api — window.TemplateAPI injection (OSS).

Generates the JS data layer injected into published HTML. The public
API surface is signature-compatible with the intranet version:

  list(opts) / listAll(opts) / get(id) / create(tpl) / update(id, patch)
  / delete(id) / sort(id, sortIndex) / upsert(tpl) + _config

Semantics preserved:
  * multi modelCode: CFG.modelCodes array + CFG.modelCode compat field;
    every method accepts an optional modelCode (defaults to modelCodes[0])
  * list/listAll resolve to ``{total, list}``; rows carry the intranet
    field names (templateId / templateName / templateDesc /
    templateContent / templateContentVersion / modelCode / createTime /
    updateTime) so intranet-built pages run unchanged
  * create/update/upsert resolve to the templateId
  * placeholder modelCodes hard-block the whole API
  * ``templateapi:ready`` CustomEvent after mount

Backend difference (invisible to pages): the JS always speaks the
PostgREST wire format. With ``data.backend: sqlite`` (default) requests go
to the golive server's own ``/api/data/<table>`` endpoint, which is backed
by ``$GOLIVE_HOME/data.db`` — zero configuration, no API key. With
``data.backend: supabase`` requests go straight to the user's Supabase
PostgREST endpoint using the anon key — configure RLS accordingly
(see docs/data-layer.md).
"""

from __future__ import annotations

import json as _json
import re

from golive.inject import TEMPLATE_SCRIPT_ID

_JS_TEMPLATE = r"""
/* ============================================================
   SYSTEM INJECTED CODE — DO NOT MODIFY!
   Modifying this block will break template data functionality!!
   golive data layer (auto injected)
   modelCodes : {model_codes_display}
   version    : {data_version}
   generated  : {generated_at}
   ============================================================ */
(function () {{
  'use strict';

  /* ── config ── */
  var CFG = {{
    modelCodes : {model_codes_json},
    modelCode  : {first_model_code_json},   // compat field: first modelCode
    version    : '{data_version}',
    userId     : {user_id_json},
    mode       : {mode_json},               // 'local' (golive serve) | 'supabase'
    baseUrl    : {rest_url_json},
    apiKey     : {anon_key_json},
    table      : {table_json},
  }};

  /* ── placeholder hard block ── */
  var _placeholderFound = CFG.modelCodes.find(function (c) {{
    return c.indexOf('__PLACEHOLDER__') !== -1 || c === '__PLACEHOLDER_MODEL_CODE__';
  }});
  /* 'local' mode (sqlite/postgres) is served by golive itself over
     /api/data — no API key involved. Only supabase needs a key. */
  var _noBackend = !CFG.baseUrl || (CFG.mode === 'supabase' && !CFG.apiKey);
  if (_placeholderFound || _noBackend) {{
    var _blockedMsg = _placeholderFound
      ? '[TemplateAPI] not ready: modelCode contains placeholder ' + _placeholderFound
      : '[TemplateAPI] not ready: no data backend configured. Set data.backend: sqlite (default, zero-config) or supabase + supabase.url/key in golive.yaml and republish.';
    var _blockedFn = function() {{
      console.error(_blockedMsg);
      return Promise.reject(new Error(_blockedMsg));
    }};
    window.TemplateAPI = {{
      list    : _blockedFn,
      listAll : _blockedFn,
      get     : _blockedFn,
      create  : _blockedFn,
      update  : _blockedFn,
      delete  : _blockedFn,
      sort    : _blockedFn,
      upsert  : _blockedFn,
      _config : CFG,
      _blocked: true,
    }};
    window.TEMPLATE_CONFIG = CFG;
    console.error(_blockedMsg + ' Site: ' + location.href);
    return;
  }}

  /* ── HTTP (PostgREST wire format) ── */
  function _headers(extra) {{
    var h = {{ 'Content-Type': 'application/json' }};
    if (CFG.mode === 'supabase') {{
      h['apikey'] = CFG.apiKey;
      h['Authorization'] = 'Bearer ' + CFG.apiKey;
    }}
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }}

  function request(method, params, body, extraHeaders) {{
    var qs = [];
    for (var k in (params || {{}})) {{
      qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
    }}
    var url = CFG.baseUrl + '/' + CFG.table + (qs.length ? '?' + qs.join('&') : '');
    var init = {{ method: method, headers: _headers(extraHeaders) }};
    if (body !== undefined && body !== null) init.body = JSON.stringify(body);
    return fetch(url, init).then(function (res) {{
      if (!res.ok) {{
        return res.text().then(function (t) {{
          var msg = t;
          try {{ var j = JSON.parse(t); msg = j.message || j.hint || t; }} catch (e) {{}}
          throw new Error('HTTP ' + res.status + ': ' + msg);
        }});
      }}
      var total = null;
      var cr = res.headers.get('Content-Range');
      if (cr && cr.indexOf('/') !== -1) {{
        var tail = cr.split('/').pop();
        if (/^\d+$/.test(tail)) total = parseInt(tail, 10);
      }}
      if (res.status === 204) return {{ rows: [], total: total }};
      return res.json().then(function (rows) {{
        return {{ rows: rows, total: total }};
      }});
    }});
  }}

  /* row (DB columns) → intranet-shaped template object */
  function toTemplate(row) {{
    if (!row) return null;
    var content = row.content;
    if (content !== null && typeof content === 'object') {{
      content = JSON.stringify(content);
    }}
    return {{
      templateId             : row.id,
      templateName           : row.name,
      templateDesc           : row.description || '',
      templateContent        : content,
      templateContentVersion : row.version,
      modelCode              : row.model_code,
      userId                 : row.user_id || '',
      sortIndex              : row.sort_index || 0,
      createTime             : row.created_at,
      updateTime             : row.updated_at,
    }};
  }}

  function toContentJson(content) {{
    if (content === undefined || content === null) return {{}};
    if (typeof content === 'string') {{
      try {{ return JSON.parse(content); }} catch (e) {{ return {{ raw: content }}; }}
    }}
    return content;
  }}

  /* ── multi modelCode resolution (same semantics as intranet) ── */
  var _warnedMissingMc = false;
  function resolveModelCode(explicitMc, methodName) {{
    if (explicitMc) {{
      if (CFG.modelCodes.indexOf(explicitMc) === -1) {{
        console.warn('[TemplateAPI] modelCode "' + explicitMc + '" is not in the injected modelCodes list ' +
                     JSON.stringify(CFG.modelCodes) + ' — check the spelling, or add it at deploy time via ' +
                     '--data-model "a,b,' + explicitMc + '"');
      }}
      return explicitMc;
    }}
    if (CFG.modelCodes.length > 1 && !_warnedMissingMc) {{
      _warnedMissingMc = true;
      console.warn('[TemplateAPI] ' + methodName + '() called without an explicit modelCode; defaulting to "' +
                   CFG.modelCodes[0] + '". With multiple modelCodes, pass {{modelCode: "xxx"}} to avoid ambiguity.');
    }}
    return CFG.modelCodes[0];
  }}

  function _listQuery(opts, mc, mineOnly) {{
    var params = {{
      model_code : 'eq.' + mc,
      order      : 'sort_index.desc,created_at.desc',
      limit      : String(opts.pageSize || 20),
      offset     : String(((opts.pageNo || 1) - 1) * (opts.pageSize || 20)),
    }};
    if (opts.templateName) params.name = 'like.' + opts.templateName + '*';
    if (mineOnly) {{
      var uid = (opts.userId !== undefined) ? opts.userId : CFG.userId;
      if (uid !== undefined && uid !== null && uid !== '') params.user_id = 'eq.' + uid;
    }} else if (opts && opts.userId !== undefined) {{
      /* listAll ignores userId, same as intranet */
    }}
    return params;
  }}

  /* ── public API ── */
  var TemplateAPI = {{

    /**
     * List current user's templates.
     * @param {{object}} opts  {{modelCode, pageNo, pageSize, templateName, versions, userId}}
     * @returns Promise<{{total: number, list: Template[]}}>
     */
    list: function (opts) {{
      opts = opts || {{}};
      var mc = resolveModelCode(opts.modelCode, 'list');
      return request('GET', _listQuery(opts, mc, true), null,
                     {{ 'Prefer': 'count=exact' }}).then(function (r) {{
        return {{ total: (r.total !== null ? r.total : r.rows.length),
                 list: r.rows.map(toTemplate) }};
      }});
    }},

    /**
     * List all users' templates (no user isolation).
     * @param {{object}} opts  same as list; userId is ignored
     * @returns Promise<{{total: number, list: Template[]}}>
     */
    listAll: function (opts) {{
      opts = opts || {{}};
      var mc = resolveModelCode(opts.modelCode, 'listAll');
      return request('GET', _listQuery(opts, mc, false), null,
                     {{ 'Prefer': 'count=exact' }}).then(function (r) {{
        return {{ total: (r.total !== null ? r.total : r.rows.length),
                 list: r.rows.map(toTemplate) }};
      }});
    }},

    /**
     * Template detail by id (no modelCode needed).
     * @param {{string|number}} templateId
     * @returns Promise<Template>
     */
    get: function (templateId) {{
      return request('GET', {{ id: 'eq.' + templateId, limit: '1' }})
        .then(function (r) {{ return toTemplate(r.rows[0] || null); }});
    }},

    /**
     * Create a template.
     * @param {{object}} tpl  {{modelCode, name, content, desc, version}} — name required
     * @returns Promise<templateId>
     */
    create: function (tpl) {{
      if (!tpl || !tpl.name) return Promise.reject(new Error('name required'));
      var mc = resolveModelCode(tpl.modelCode, 'create');
      var row = {{
        model_code  : mc,
        name        : tpl.name,
        description : tpl.desc || '',
        content     : toContentJson(tpl.content),
        version     : tpl.version || CFG.version,
        user_id     : CFG.userId || '',
      }};
      return request('POST', null, [row],
                     {{ 'Prefer': 'return=representation' }})
        .then(function (r) {{ return r.rows[0] ? r.rows[0].id : null; }});
    }},

    /**
     * Update a template (patch semantics — unspecified fields kept).
     * @param {{string|number}} templateId
     * @param {{object}} patch  supports name / desc / content / version / modelCode
     * @returns Promise<templateId>
     */
    update: function (templateId, patch) {{
      patch = patch || {{}};
      var values = {{ updated_at: new Date().toISOString() }};
      if (patch.name !== undefined)    values.name = patch.name;
      if (patch.desc !== undefined)    values.description = patch.desc;
      if (patch.version !== undefined) values.version = patch.version;
      if (patch.modelCode !== undefined) values.model_code = patch.modelCode;
      if (patch.content !== undefined) values.content = toContentJson(patch.content);
      return request('PATCH', {{ id: 'eq.' + templateId }}, values,
                     {{ 'Prefer': 'return=representation' }})
        .then(function (r) {{
          if (!r.rows.length) throw new Error('template not found: ' + templateId);
          return r.rows[0].id;
        }});
    }},

    /**
     * Delete a template by id.
     * @returns Promise<null>
     */
    delete: function (templateId) {{
      return request('DELETE', {{ id: 'eq.' + templateId }})
        .then(function () {{ return null; }});
    }},

    /**
     * Adjust sort index.
     * @returns Promise<null>
     */
    sort: function (templateId, sortIndex) {{
      return request('PATCH', {{ id: 'eq.' + templateId }},
                     {{ sort_index: sortIndex }})
        .then(function () {{ return null; }});
    }},

    /**
     * upsert: find by exact name; update when found, create otherwise.
     * @param {{object}} tpl  same as create; name required; modelCode honored
     * @returns Promise<templateId>
     */
    upsert: function (tpl) {{
      if (!tpl || !tpl.name) return Promise.reject(new Error('name required'));
      var mc = resolveModelCode(tpl.modelCode, 'upsert');
      /* exact-match query (PostgREST eq. — no prefix-collision issue) */
      var params = {{ model_code: 'eq.' + mc, name: 'eq.' + tpl.name, limit: '1' }};
      if (CFG.userId) params.user_id = 'eq.' + CFG.userId;
      return request('GET', params).then(function (r) {{
        var existing = r.rows[0];
        if (existing) return TemplateAPI.update(existing.id, tpl);
        return TemplateAPI.create(tpl);
      }});
    }},

    /* ── debug ── */
    _config: CFG,
  }};

  window.TemplateAPI = TemplateAPI;
  window.TEMPLATE_CONFIG = CFG;

  /* mount event — deferred so inline listeners register first */
  setTimeout(function() {{
    document.dispatchEvent(new CustomEvent('templateapi:ready', {{ detail: CFG }}));
  }}, 0);
}})();
"""


def generate_js(model_code: str, data_version: str = "1.0.0",
                rest_url: str = "", anon_key: str = "",
                table: str = "golive_templates", user_id: str = "",
                mode: str = "supabase") -> str:
    """Build the injectable <script> tag.

    Args:
      model_code: modelCode namespace(s); comma-separated for multi.
      data_version: version string stamped on created rows.
      rest_url: PostgREST base. Supabase mode:
        ``https://<proj>.supabase.co/rest/v1``. Local mode: the golive
        server's ``/api/data`` base (empty -> stub mode).
      anon_key: Supabase anon key (ignored in local mode).
      table: templates table name.
      user_id: identity stamped on created rows ('' = anonymous).
      mode: ``local`` (sqlite/postgres, served by golive itself, no key)
        or ``supabase`` (page talks to Supabase directly with an anon key).
    """
    if not model_code or not model_code.strip():
        raise ValueError(
            "modelCode must not be empty — pass --data-model <modelCode>.")
    if "__PLACEHOLDER__" in model_code or model_code.startswith("__PLACEHOLDER"):
        raise ValueError(
            f"modelCode is a placeholder ({model_code}) — refusing to inject. "
            f"Pass a real modelCode via --data-model.")

    from datetime import datetime
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    codes = [c.strip() for c in model_code.split(",") if c.strip()]
    if not codes:
        raise ValueError("modelCode list is empty after splitting")

    # Anything embedded verbatim into the JS body (not inside a JSON string)
    # MUST be neutralised so it cannot close the <script> element or open
    # a JS block-comment early. This covers modelCodes / data_version /
    # generated_at, which appear in the leading banner comment.
    js_code = _JS_TEMPLATE.format(
        model_codes_json=_json_for_script(codes),
        first_model_code_json=_json_for_script(codes[0]),
        model_codes_display=_safe_comment(",".join(codes)),
        data_version=_safe_comment(data_version),
        generated_at=_safe_comment(generated_at),
        rest_url_json=_json_for_script(rest_url.rstrip("/")),
        anon_key_json=_json_for_script(anon_key),
        table_json=_json_for_script(table),
        user_id_json=_json_for_script(user_id),
        mode_json=_json_for_script(mode or "supabase"),
    )
    return f'<script id="{TEMPLATE_SCRIPT_ID}">\n{js_code}\n</script>'


# Shared escaping helpers — single source of truth in inject/_escape.py.
from golive.inject._escape import _json_for_script, _safe_comment  # noqa: E402


def generate_js_from_config(model_code: str, data_version: str = "1.0.0",
                            cfg=None) -> str:
    """Build the script tag using the current golive Config.

    ``data.backend: sqlite`` (default) points the page at the golive
    server's own ``/api/data`` endpoint — same wire format, no API key.
    ``data.api_base`` overrides the base when the site is served from a
    different origin than the golive server (reverse proxy, CDN).
    """
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    from golive.backends.factory import is_server_proxied_data
    if is_server_proxied_data(cfg):
        # Server-proxied backends (sqlite, postgres): the page calls the local
        # /api/data endpoint and the server owns the connection, so no
        # credentials (and no Postgres DSN) ever reach the browser. Relative
        # base unless the operator says otherwise via data.api_base.
        return generate_js(model_code, data_version,
                           rest_url=cfg.data.api_base or "/api/data",
                           anon_key="",
                           table=cfg.data.templates_table,
                           user_id=cfg.data.user_id,
                           mode="local")
    rest_url = cfg.supabase.url.rstrip("/") + "/rest/v1" if cfg.supabase.url else ""
    return generate_js(model_code, data_version,
                       rest_url=rest_url,
                       anon_key=cfg.supabase.anon_key,
                       table=cfg.data.templates_table,
                       user_id=cfg.data.user_id,
                       mode="supabase")


def inject_into_html(html: str, model_code: str, data_version: str = "1.0.0",
                     cfg=None) -> str:
    """Idempotently inject the data layer into HTML (<head> end preferred)."""
    script_tag = generate_js_from_config(model_code, data_version, cfg)
    html = remove_from_html(html)
    if re.search(r"</head>", html, re.IGNORECASE):
        return re.sub(r"</head>", lambda m: script_tag + "\n" + m.group(0),
                      html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body[^>]*>", html, re.IGNORECASE):
        return re.sub(r"<body[^>]*>", lambda m: m.group(0) + "\n" + script_tag,
                      html, count=1, flags=re.IGNORECASE)
    return script_tag + "\n" + html


def remove_from_html(html: str) -> str:
    """Strip any previous template-data-layer script."""
    return re.sub(
        r'\s*<script[^>]+id=["\']' + TEMPLATE_SCRIPT_ID + r'["\'][^>]*>.*?</script>',
        "", html, flags=re.DOTALL | re.IGNORECASE)


def extract_model_code_from_html(html: str):
    """Extract the injected modelCode list (for --update reuse)."""
    m = re.search(
        r'<script[^>]+id=["\']' + TEMPLATE_SCRIPT_ID + r'["\'][^>]*>.*?'
        r"modelCodes\s*[=:]\s*(\[[^\]]+\])",
        html, re.DOTALL)
    if m:
        try:
            codes = _json.loads(m.group(1))
            return ",".join(codes) if isinstance(codes, list) else None
        except _json.JSONDecodeError:
            pass
    return None


def detect_usage(html: str) -> bool:
    """True when the page calls TemplateAPI (outside our own injection)."""
    stripped = remove_from_html(html)
    return bool(re.search(r"\bTemplateAPI\s*\.", stripped))
