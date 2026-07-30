"""golive.server.admin_ui — admin portal single-page app (M5).

``render_admin_page(identity)`` returns a self-contained HTML document:
no external frameworks, no CDN references — all CSS/JS inline (works on
airgapped intranets). Dynamic values are inlined via
golive.inject._escape.json_for_script (XSS-safe in <script> context).

The page is a thin shell over /api/admin/*: it holds no privileged data
itself; every API call re-checks the caller's role server-side. When the
server runs token auth the SPA asks for the token once and sends it as
``X-Golive-Token`` on every request (kept in sessionStorage only).
"""

from __future__ import annotations

from typing import Optional

from golive import __version__
from golive.inject._escape import json_for_script


DOCS_URL = "https://github.com/Songhonglei/html-golive/blob/main/docs/manual.md"


def _paths_for_boot() -> dict:
    """Best-effort real paths for the 'copy for your AI assistant' prompt.

    Never raises: the portal must render even when config resolution has
    problems. Missing values become "" and the UI falls back to a
    placeholder plus a "run golive doctor" note.
    """
    home = ""
    config_path = ""
    try:
        from golive.core.paths import get_home
        home = str(get_home())
    except Exception:
        home = ""
    try:
        from golive.config import get_config
        config_path = str(getattr(get_config(), "source_path", "") or "")
    except Exception:
        config_path = ""
    if not config_path and home:
        # no yaml loaded yet — this is where golive looks by default
        config_path = home.rstrip("/\\") + "/golive.yaml"
    return {"home": home, "config_path": config_path}


def render_admin_page(identity=None) -> str:
    """Build the portal HTML. ``identity`` may be None (token shell)."""
    paths = _paths_for_boot()
    boot = {
        "authenticated": identity is not None,
        "email": getattr(identity, "email", "") or "",
        "superadmin": bool(getattr(identity, "is_superadmin", False)),
        "version": __version__,
        "home": paths["home"],
        "config_path": paths["config_path"],
        "docs_url": DOCS_URL,
    }
    return _PAGE_TEMPLATE.replace("__GOLIVE_BOOT__", json_for_script(boot))


_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>golive · admin</title>
<script>
/* Applied before any paint so switching themes never flashes (no FOUC).
   Kept deliberately tiny and dependency-free. */
(function(){
  var THEME_KEY = "golive_admin_theme";   /* system | light | dark */
  var LANG_KEY  = "golive_admin_lang";    /* en | zh */
  var pref = "system", lang = null;
  try { pref = localStorage.getItem(THEME_KEY) || "system"; } catch (e) {}
  try { lang = localStorage.getItem(LANG_KEY); } catch (e) {}
  if (pref !== "light" && pref !== "dark" && pref !== "system") pref = "system";
  var resolved = pref;
  if (pref === "system"){
    resolved = (window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: light)").matches)
      ? "light" : "dark";
  }
  var root = document.documentElement;
  root.setAttribute("data-theme", resolved);
  root.setAttribute("data-theme-pref", pref);
  if (!lang){
    var nav = (navigator.language || navigator.userLanguage || "en");
    lang = /^zh/i.test(nav) ? "zh" : "en";
  }
  root.setAttribute("lang", lang === "zh" ? "zh-CN" : "en");
  root.setAttribute("data-lang", lang);
})();
</script>
<style>
/* dark is the default palette; [data-theme="light"] overrides it below.
   Every colour below is a variable so the two themes stay in sync. */
:root, :root[data-theme="dark"]{
  --bg:#0f1419;--panel:#171e26;--panel2:#1d2630;--line:#2a3542;
  --text:#dce3ea;--muted:#8296a8;--accent:#4da3ff;--accent2:#2a76d2;
  --ok:#3fb96f;--warn:#e0a63c;--danger:#e05c5c;--radius:10px;
  --on-accent:#ffffff;
  --btn-hover:#243040;
  --accent-soft:rgba(77,163,255,.08);
  --row-hover:rgba(77,163,255,.05);
  --danger-soft:rgba(224,92,92,.12);
  --mask:rgba(0,0,0,.55);
  --shadow:0 10px 40px rgba(0,0,0,.45);
  --code-bg:#1d2630;
}
:root[data-theme="light"]{
  --bg:#f4f6f9;--panel:#ffffff;--panel2:#eaeff5;--line:#d3dce6;
  --text:#16212e;--muted:#5b6b7c;--accent:#1263c4;--accent2:#0f56ac;
  --ok:#12784a;--warn:#8a5a00;--danger:#bf2f2f;--radius:10px;
  --on-accent:#ffffff;
  --btn-hover:#dde5ee;
  --accent-soft:rgba(18,99,196,.09);
  --row-hover:rgba(18,99,196,.055);
  --danger-soft:rgba(191,47,47,.10);
  --mask:rgba(22,33,46,.42);
  --shadow:0 10px 34px rgba(22,33,46,.16);
  --code-bg:#f0f4f9;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);
  font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}
button{font:inherit;cursor:pointer;border:1px solid var(--line);
  background:var(--panel2);color:var(--text);border-radius:6px;
  padding:6px 14px;transition:background .15s}
button:hover{background:var(--btn-hover)}
button.primary{background:var(--accent2);border-color:var(--accent2);
  color:var(--on-accent)}
button.primary:hover{background:var(--accent)}
button.danger{background:transparent;border-color:var(--danger);color:var(--danger)}
button.danger:hover{background:var(--danger-soft)}
/* disabled stays legible (contrast >= 5:1); it reads as inactive via the
   flat background and muted colour, not by fading into the page. */
button:disabled{cursor:not-allowed;color:var(--muted);
  background:transparent;border-style:dashed}
button:disabled:hover{background:transparent}
input,select{font:inherit;background:var(--bg);color:var(--text);
  border:1px solid var(--line);border-radius:6px;padding:6px 10px}
input:focus{outline:1px solid var(--accent)}
#layout{display:flex;min-height:100vh}
#sidebar{width:210px;flex:0 0 210px;background:var(--panel);
  border-right:1px solid var(--line);padding:20px 0;display:flex;
  flex-direction:column}
#logo{padding:0 20px 18px;font-size:17px;font-weight:700}
#logo small{display:block;color:var(--muted);font-weight:400;font-size:11px}
.nav-item{padding:10px 20px;color:var(--muted);cursor:pointer;
  border-left:3px solid transparent}
.nav-item:hover{color:var(--text)}
.nav-item.active{color:var(--text);border-left-color:var(--accent);
  background:var(--accent-soft)}
.nav-item.hidden{display:none}
#whoami{margin-top:auto;padding:14px 20px;font-size:12px;
  color:var(--muted);border-top:1px solid var(--line);word-break:break-all}
#main{flex:1;padding:26px 32px;min-width:0}
.view{display:none}
.view.active{display:block}
h2{font-size:18px;margin-bottom:16px}
.toolbar{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;
  align-items:center}
.toolbar .spacer{flex:1}
table{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);
  vertical-align:middle}
th{background:var(--panel2);color:var(--muted);font-weight:600;
  font-size:12px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--row-hover)}
td.actions{white-space:nowrap}
td.actions button{padding:3px 10px;font-size:12px;margin-right:6px}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;
  font-size:11px;border:1px solid var(--line);color:var(--muted)}
.badge.owner{border-color:var(--ok);color:var(--ok)}
.badge.superadmin{border-color:var(--warn);color:var(--warn)}
.badge.maintainer{border-color:var(--accent);color:var(--accent)}
.badge.on{border-color:var(--ok);color:var(--ok)}
.pager{display:flex;gap:8px;align-items:center;margin-top:12px;
  color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:14px;margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:16px 18px}
.card .num{font-size:26px;font-weight:700;margin-top:4px}
.card .lbl{color:var(--muted);font-size:12px}
#drawer-mask{position:fixed;inset:0;background:var(--mask);
  display:none;z-index:40}
#drawer{position:fixed;top:0;right:-560px;width:540px;max-width:94vw;
  height:100vh;background:var(--panel);border-left:1px solid var(--line);
  z-index:50;transition:right .2s ease;overflow-y:auto;padding:24px 26px}
#drawer.open{right:0}
#drawer-mask.open{display:block}
#drawer h3{font-size:16px;margin-bottom:4px;word-break:break-all}
#drawer .sub{color:var(--muted);font-size:12px;margin-bottom:18px;
  word-break:break-all}
.section{border-top:1px solid var(--line);padding:16px 0}
.section h4{font-size:13px;color:var(--muted);margin-bottom:10px;
  text-transform:uppercase;letter-spacing:.04em}
.frow{display:flex;gap:10px;margin-bottom:10px;align-items:center}
.frow label{width:86px;flex:0 0 86px;color:var(--muted);font-size:13px}
.frow input[type=text]{flex:1}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.tag{background:var(--panel2);border:1px solid var(--line);
  border-radius:999px;padding:2px 10px;font-size:12px;display:inline-flex;
  gap:6px;align-items:center}
.tag b{cursor:pointer;color:var(--danger);font-weight:700}
.snap-row{display:flex;justify-content:space-between;align-items:center;
  padding:6px 0;border-bottom:1px dashed var(--line);font-size:13px}
.snap-row:last-child{border-bottom:none}
.snap-row .ts{font-family:ui-monospace,monospace;color:var(--muted)}
#toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);
  background:var(--panel2);border:1px solid var(--line);color:var(--text);
  border-radius:8px;padding:10px 20px;display:none;z-index:99;
  max-width:70vw}
#toast.err{border-color:var(--danger);color:var(--danger)}
#login-gate{max-width:380px;margin:16vh auto;background:var(--panel);
  border:1px solid var(--line);border-radius:var(--radius);padding:28px}
#login-gate h2{margin-bottom:6px}
#login-gate p{color:var(--muted);font-size:13px;margin-bottom:14px}
#login-gate input{width:100%;margin-bottom:12px}
.empty{color:var(--muted);padding:26px;text-align:center}

/* ── top bar: theme + language switchers ─────────────────────── */
#topbar{display:flex;align-items:center;gap:8px;justify-content:flex-end;
  margin-bottom:14px}
.switch{display:inline-flex;border:1px solid var(--line);border-radius:8px;
  overflow:hidden;background:var(--panel)}
.switch button{border:none;border-radius:0;background:transparent;
  padding:5px 11px;font-size:12.5px;color:var(--muted);line-height:1.5}
.switch button + button{border-left:1px solid var(--line)}
.switch button:hover{background:var(--btn-hover);color:var(--text)}
.switch button[aria-pressed="true"]{background:var(--accent-soft);
  color:var(--accent);font-weight:600}

/* ── sidebar brand separator (C) ─────────────────────────────── */
#logo{border-bottom:1px solid var(--line);margin-bottom:12px}

/* ── guide / empty-state blocks (C) ──────────────────────────── */
.guide{text-align:left;color:var(--text);padding:0;max-width:820px}
.guide h3{font-size:15px;margin-bottom:8px}
.guide p{color:var(--muted);margin-bottom:12px}
.guide .hint{background:var(--panel);border:1px solid var(--line);
  border-left:3px solid var(--accent);border-radius:8px;padding:12px 14px;
  margin-bottom:16px;color:var(--text)}
.guide-actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.codeblock{position:relative;margin-bottom:22px}
.codeblock pre{background:var(--code-bg);border:1px solid var(--line);
  border-radius:8px;padding:15px 18px;font:12px/1.75 ui-monospace,monospace;
  overflow-x:auto;color:var(--text)}
.codeblock .cb-copy{position:absolute;top:8px;right:8px;font-size:11.5px;
  padding:3px 9px;background:var(--panel);color:var(--muted)}
.codeblock .cb-copy:hover{color:var(--text)}
.codeblock .cb-copy.ok{color:var(--ok);border-color:var(--ok)}
.guide .cb-label{font-size:12px;color:var(--muted);margin-bottom:7px;
  text-transform:uppercase;letter-spacing:.04em}
.guide .doclink{font-size:13px}

/* ── permissions page (D) ────────────────────────────────────── */
.perm-block{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:18px 20px;margin-bottom:18px}
.perm-block h3{font-size:14px;margin-bottom:4px}
.perm-block .desc{color:var(--muted);font-size:12.5px;margin-bottom:12px}
.perm-block table{margin-top:4px}
/* A padlock drawn in CSS: the portal ships no fonts, and an emoji glyph
   renders as tofu wherever the system has no emoji font installed. */
.lock{display:inline-block;position:relative;width:11px;height:9px;
  border:1.5px solid var(--muted);border-radius:2px;margin-top:5px;
  cursor:help}
.lock::before{content:"";position:absolute;left:50%;top:-6px;
  width:7px;height:6px;margin-left:-4.5px;border:1.5px solid var(--muted);
  border-bottom:none;border-radius:4px 4px 0 0}
.chks{display:flex;flex-wrap:wrap;gap:8px;max-height:210px;overflow-y:auto;
  border:1px solid var(--line);border-radius:8px;padding:10px;
  background:var(--bg);margin-bottom:10px}
.chks label{display:inline-flex;gap:7px;align-items:center;font-size:13px;
  background:var(--panel2);border:1px solid var(--line);border-radius:999px;
  padding:4px 12px;cursor:pointer;line-height:1.4}
.chks label input{margin:0;flex:0 0 auto}
#perm-bulk .chks{margin-bottom:16px}
.mine dt{color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.04em;margin-top:10px}
.mine dd{margin:3px 0 0;word-break:break-all}
@media(max-width:760px){
  #layout{flex-direction:column}
  #sidebar{width:100%;flex-direction:row;align-items:center;
    padding:8px 4px;overflow-x:auto}
  #logo{padding:0 12px}
  .nav-item{border-left:none;white-space:nowrap}
  #whoami{display:none}
  #main{padding:16px}
}
</style>
</head>
<body>
<script>window.GOLIVE_BOOT = __GOLIVE_BOOT__;</script>

<div id="login-gate" style="display:none">
  <h2>golive admin</h2>
  <p data-i18n="gate.hint"></p>
  <input type="password" id="gate-token" placeholder="access token"
         autocomplete="off">
  <button class="primary" id="gate-enter" style="width:100%"
          data-i18n="gate.enter"></button>
</div>

<div id="layout" style="display:none">
  <div id="sidebar">
    <div id="logo">🚀 golive <small id="ver"></small></div>
    <div class="nav-item active" data-view="sites" data-i18n="nav.sites"></div>
    <div class="nav-item hidden" data-view="data" id="nav-data"
         data-i18n="nav.data"></div>
    <div class="nav-item hidden" data-view="perms" id="nav-perms"
         data-i18n="nav.perms"></div>
    <div class="nav-item hidden" data-view="stats" id="nav-stats"
         data-i18n="nav.stats"></div>
    <div class="nav-item hidden" data-view="audit" id="nav-audit"
         data-i18n="nav.audit"></div>
    <div id="whoami"></div>
  </div>

  <div id="main">
    <div id="topbar">
      <div class="switch" id="lang-switch" role="group"
           aria-label="Language">
        <button data-lang="en" type="button">EN</button>
        <button data-lang="zh" type="button">中文</button>
      </div>
      <div class="switch" id="theme-switch" role="group" aria-label="Theme">
        <button data-theme-set="system" type="button" title="System">🖥</button>
        <button data-theme-set="light" type="button" title="Light">☀</button>
        <button data-theme-set="dark" type="button" title="Dark">🌙</button>
      </div>
    </div>

    <!-- sites -->
    <div class="view active" id="view-sites">
      <h2 data-i18n="sites.title"></h2>
      <div class="toolbar">
        <input type="text" id="site-q" data-i18n-ph="sites.search"
               style="width:240px">
        <button id="site-search" data-i18n="btn.search"></button>
        <div class="spacer"></div>
        <span id="site-count" style="color:var(--muted);font-size:13px"></span>
      </div>
      <table>
        <thead><tr>
          <th data-i18n="th.name"></th><th data-i18n="th.slug"></th>
          <th data-i18n="th.owner"></th><th data-i18n="th.role"></th>
          <th data-i18n="th.size"></th><th data-i18n="th.updated"></th>
          <th data-i18n="th.actions"></th>
        </tr></thead>
        <tbody id="site-rows"></tbody>
      </table>
      <div class="pager">
        <button id="site-prev" data-i18n="btn.prev"></button>
        <span id="site-page"></span>
        <button id="site-next" data-i18n="btn.next"></button>
      </div>
    </div>

    <!-- data management (M6) -->
    <div class="view" id="view-data">
      <h2 data-i18n="data.title"></h2>
      <div id="data-nobackend" class="guide" style="display:none"></div>
      <div id="data-main" style="display:none">
        <div class="toolbar">
          <select id="data-model" style="min-width:180px"></select>
          <input type="text" id="data-q" data-i18n-ph="data.search"
                 style="width:220px">
          <button id="data-search" data-i18n="btn.search"></button>
          <div class="spacer"></div>
          <button class="primary" id="data-add" data-i18n="data.add"></button>
        </div>
        <table>
          <thead><tr>
            <th data-i18n="th.id"></th><th data-i18n="th.name"></th>
            <th data-i18n="th.summary"></th><th data-i18n="th.updated"></th>
            <th data-i18n="th.actions"></th>
          </tr></thead>
          <tbody id="data-rows"></tbody>
        </table>
        <div class="pager">
          <button id="data-prev" data-i18n="btn.prev"></button>
          <span id="data-page"></span>
          <button id="data-next" data-i18n="btn.next"></button>
          <span id="data-count" style="margin-left:8px"></span>
        </div>
      </div>
    </div>

    <!-- permissions (M7) -->
    <div class="view" id="view-perms">
      <h2 data-i18n="perms.title"></h2>
      <div id="perms-unavailable" class="guide" style="display:none"></div>
      <div id="perms-main" style="display:none">
        <div class="perm-block" id="perm-mine">
          <h3 data-i18n="perms.mine"></h3>
          <div class="desc" data-i18n="perms.mine.desc"></div>
          <dl class="mine" id="perm-mine-body"></dl>
        </div>

        <div class="perm-block" id="perm-admins">
          <h3 data-i18n="perms.admins"></h3>
          <div class="desc" data-i18n="perms.admins.desc"></div>
          <table>
            <thead><tr>
              <th data-i18n="th.email"></th><th data-i18n="th.source"></th>
              <th data-i18n="th.actions"></th>
            </tr></thead>
            <tbody id="perm-admin-rows"></tbody>
          </table>
          <div class="frow" style="margin-top:12px">
            <input type="text" id="perm-admin-email"
                   data-i18n-ph="perms.admins.ph" style="flex:1">
            <button class="primary" id="perm-admin-add"
                    data-i18n="perms.admins.add"></button>
          </div>
        </div>

        <div class="perm-block" id="perm-sites">
          <h3 data-i18n="perms.sites"></h3>
          <div class="desc" data-i18n="perms.sites.desc"></div>
          <div class="toolbar">
            <input type="text" id="perm-site-q" data-i18n-ph="perms.sites.search"
                   style="width:240px">
            <button id="perm-site-search" data-i18n="btn.search"></button>
          </div>
          <table>
            <thead><tr>
              <th data-i18n="th.name"></th><th data-i18n="th.slug"></th>
              <th data-i18n="th.owner"></th><th data-i18n="th.maintainers"></th>
            </tr></thead>
            <tbody id="perm-site-rows"></tbody>
          </table>
        </div>

        <div class="perm-block" id="perm-bulk">
          <h3 data-i18n="perms.bulk"></h3>
          <div class="desc" data-i18n="perms.bulk.desc"></div>
          <div class="frow">
            <label data-i18n="perms.bulk.email"></label>
            <input type="text" id="perm-bulk-email"
                   data-i18n-ph="perms.admins.ph" style="flex:1">
          </div>
          <div class="chks" id="perm-bulk-slugs"></div>
          <div class="frow">
            <button class="primary" id="perm-bulk-grant"
                    data-i18n="perms.bulk.grant"></button>
            <button class="danger" id="perm-bulk-revoke"
                    data-i18n="perms.bulk.revoke"></button>
            <span class="spacer"></span>
            <button id="perm-bulk-all" data-i18n="perms.bulk.all"></button>
            <button id="perm-bulk-none" data-i18n="perms.bulk.none"></button>
          </div>
        </div>
      </div>
    </div>

    <!-- stats -->
    <div class="view" id="view-stats">
      <h2 data-i18n="stats.title"></h2>
      <div class="cards" id="stat-cards"></div>
      <h2 style="font-size:15px" data-i18n="stats.top"></h2>
      <table>
        <thead><tr><th>#</th><th data-i18n="th.slug"></th>
          <th data-i18n="th.name"></th><th data-i18n="th.size"></th></tr></thead>
        <tbody id="stat-top"></tbody>
      </table>
    </div>

    <!-- audit -->
    <div class="view" id="view-audit">
      <h2 data-i18n="audit.title"></h2>
      <div class="toolbar">
        <input type="text" id="audit-slug" data-i18n-ph="audit.byslug"
               style="width:170px">
        <input type="text" id="audit-action" data-i18n-ph="audit.byaction"
               style="width:170px">
        <button id="audit-search" data-i18n="btn.filter"></button>
      </div>
      <table>
        <thead><tr><th data-i18n="th.time"></th><th data-i18n="th.who"></th>
          <th data-i18n="th.action"></th><th data-i18n="th.slug"></th>
          <th data-i18n="th.detail"></th></tr></thead>
        <tbody id="audit-rows"></tbody>
      </table>
      <div class="pager">
        <button id="audit-prev" data-i18n="btn.prev"></button>
        <span id="audit-page"></span>
        <button id="audit-next" data-i18n="btn.next"></button>
      </div>
    </div>
  </div>
</div>

<!-- drawer -->
<div id="drawer-mask"></div>
<div id="drawer">
  <h3 id="d-title"></h3>
  <div class="sub" id="d-sub"></div>

  <div class="section">
    <h4 data-i18n="d.basic"></h4>
    <div class="frow"><label data-i18n="d.name"></label>
      <input type="text" id="d-name" maxlength="200"></div>
    <div class="frow"><label data-i18n="d.notes"></label>
      <input type="text" id="d-notes" maxlength="2000"></div>
    <div class="frow"><label data-i18n="d.editable"></label>
      <input type="checkbox" id="d-editable"></div>
    <button class="primary" id="d-save" data-i18n="btn.save"></button>
  </div>

  <div class="section" id="sec-maint">
    <h4>Maintainers</h4>
    <div class="tags" id="d-maints"></div>
    <div class="frow">
      <input type="text" id="d-maint-email" placeholder="email@example.com"
             style="flex:1">
      <button id="d-maint-add" data-i18n="btn.add"></button>
    </div>
  </div>

  <div class="section" id="sec-transfer">
    <h4 data-i18n="d.transfer"></h4>
    <div class="frow">
      <input type="text" id="d-transfer-to" data-i18n-ph="d.transfer.ph"
             style="flex:1">
      <button id="d-transfer" data-i18n="btn.transfer"></button>
    </div>
  </div>

  <div class="section">
    <h4 data-i18n="d.snaps"></h4>
    <div id="d-snaps"></div>
  </div>

  <div class="section" id="sec-delete">
    <h4 style="color:var(--danger)" data-i18n="d.delete"></h4>
    <div class="frow">
      <input type="text" id="d-del-confirm" data-i18n-ph="d.delete.ph"
             style="flex:1">
      <button class="danger" id="d-delete" data-i18n="btn.delete"></button>
    </div>
  </div>
</div>

<!-- data row modal (M6) -->
<div id="dm-mask" style="position:fixed;inset:0;background:var(--mask);
  display:none;z-index:60"></div>
<div id="dm" style="position:fixed;top:8vh;left:50%;transform:translateX(-50%);
  width:640px;max-width:94vw;max-height:82vh;overflow-y:auto;
  background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:22px 24px;display:none;z-index:61">
  <h3 id="dm-title" style="font-size:16px;margin-bottom:12px"></h3>
  <div class="frow" id="dm-model-row"><label>model</label>
    <input type="text" id="dm-model" maxlength="200" style="flex:1"></div>
  <div class="frow"><label data-i18n="d.name"></label>
    <input type="text" id="dm-name" maxlength="200" style="flex:1"></div>
  <textarea id="dm-json" spellcheck="false"
    style="width:100%;height:300px;font:12px/1.6 ui-monospace,monospace;
    background:var(--bg);color:var(--text);border:1px solid var(--line);
    border-radius:6px;padding:10px;resize:vertical"></textarea>
  <div id="dm-err" style="color:var(--danger);font-size:12px;
    margin-top:6px;display:none"></div>
  <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">
    <button id="dm-cancel" data-i18n="btn.cancel"></button>
    <button class="primary" id="dm-save" style="display:none"
            data-i18n="btn.save"></button>
  </div>
</div>

<div id="toast"></div>

<script>
(function(){
"use strict";
var BOOT = window.GOLIVE_BOOT || {};
var TOKEN_KEY = "golive_admin_token";
var THEME_KEY = "golive_admin_theme";
var LANG_KEY = "golive_admin_lang";
var state = {
  me: null, page: 1, size: 20, q: "",
  auditPage: 1, current: null,
  dataModel: "", dataQ: "", dataPage: 1, dataSize: 20,
  dataInit: false, dmRow: null,
  lang: "en", themePref: "system",
  perms: null, permQ: ""
};

// ── i18n ───────────────────────────────────────────────────────
// Interface chrome only. Data returned by the API (site names, audit
// action names, emails) is never translated.
var I18N = {
en: {
  "gate.hint": "This server requires token auth. Enter the access token (GOLIVE_TOKEN). It is kept in this browser's sessionStorage only.",
  "gate.enter": "Enter portal",
  "nav.sites": "Sites",
  "nav.data": "Data",
  "nav.perms": "Permissions",
  "nav.stats": "Stats",
  "nav.audit": "Audit log",
  "who.superadmin": "superadmin",
  "sites.title": "Sites",
  "sites.search": "Search slug / name…",
  "sites.count": "{n} sites",
  "sites.none": "No sites yet",
  "sites.unnamed": "(unnamed)",
  "sites.noslug": "none",
  "btn.search": "Search",
  "btn.filter": "Filter",
  "btn.prev": "‹ Prev",
  "btn.next": "Next ›",
  "btn.save": "Save",
  "btn.add": "Add",
  "btn.remove": "Remove",
  "btn.delete": "Delete",
  "btn.cancel": "Cancel",
  "btn.transfer": "Transfer",
  "btn.detail": "Details",
  "btn.view": "View",
  "btn.edit": "Edit",
  "btn.rollback": "Roll back",
  "btn.copy": "Copy",
  "btn.copied": "Copied",
  "th.name": "Name",
  "th.slug": "Slug",
  "th.owner": "Owner",
  "th.role": "Role",
  "th.size": "Size",
  "th.updated": "Updated",
  "th.actions": "Actions",
  "th.id": "ID",
  "th.summary": "Content preview",
  "th.time": "Time",
  "th.who": "Actor",
  "th.action": "Action",
  "th.detail": "Detail",
  "th.email": "Email",
  "th.source": "Source",
  "th.maintainers": "Maintainers",
  "data.title": "Data",
  "data.search": "Search JSON content…",
  "data.add": "+ New row",
  "data.none": "No rows",
  "data.count": "{n} rows",
  "data.nomodels": "No models in the data backend yet — create one with golive data create or the \"New row\" button.",
  "data.modal.create": "New data row",
  "data.modal.edit": "Edit data row",
  "data.modal.view": "View data row",
  "data.err.json": "JSON parse failed: ",
  "data.err.object": "Content must be a JSON object ({...})",
  "data.err.model": "model must not be empty",
  "stats.title": "Stats",
  "stats.top": "Top 10 sites (by size)",
  "stats.sites": "Sites",
  "stats.bytes": "Total size",
  "stats.recent": "Updated in 7 days",
  "stats.editable": "Inline editing on",
  "stats.none": "No data",
  "audit.title": "Audit log",
  "audit.byslug": "filter by slug",
  "audit.byaction": "filter by action",
  "audit.none": "No entries",
  "d.basic": "Basics",
  "d.name": "Name",
  "d.notes": "Notes",
  "d.editable": "Inline edit",
  "d.transfer": "Transfer owner",
  "d.transfer.ph": "new owner email",
  "d.snaps": "Snapshots / rollback",
  "d.snaps.none": "No snapshots",
  "d.delete": "Delete site",
  "d.delete.ph": "type the slug to confirm",
  "d.nomaint": "No maintainers",
  "msg.saved": "Saved",
  "msg.added": "Added",
  "msg.removed": "Removed",
  "msg.deleted": "Deleted",
  "msg.rolledback": "Rolled back",
  "msg.transferred": "Transferred to ",
  "msg.copied": "Copied to clipboard",
  "msg.copyfail": "Copy failed — select the text and copy manually",
  "msg.confirmdel": "Type {ref} to confirm deletion",
  "confirm.transfer": "Transfer this site to {to}? You may lose admin rights afterwards.",
  "confirm.rollback": "Roll back to snapshot {ts}? The current version is snapshotted first.",
  "confirm.delrow": "Delete row {name}?",
  "confirm.deladmin": "Remove {email} from the superadmin list?",
  "confirm.revoke": "Revoke maintainer rights for {email} on {n} site(s)?",
  "guide.data.title": "No data backend configured",
  "guide.data.what": "The data page manages TemplateAPI rows (the golive_templates table). It needs a data backend — sqlite for a single machine, Supabase / PostgREST when several people share it.",
  "guide.sqlite": "Quickest path: the built-in sqlite backend",
  "guide.data.hint": "Short on time? Hand the button below to your AI assistant — it produces a full task description with your real paths, the config to write and how to verify it.",
  "guide.copyagent": "📋 Copy for your AI assistant",
  "guide.cfg": "Or a shared backend (golive.yaml)",
  "guide.env": "Set the key as an environment variable (never in the file)",
  "guide.verify": "Then create the table and restart",
  "guide.docs": "Read the full documentation →",
  "guide.pathnote": "Paths could not be resolved automatically — run golive doctor to confirm them.",
  "perms.title": "Permissions",
  "perms.unavailable": "The permissions API is not available on this server (it needs golive 0.7.0 or newer).",
  "perms.mine": "My permissions",
  "perms.mine.desc": "What this account can do right now, and where that comes from.",
  "perms.mine.identity": "Signed in as",
  "perms.mine.role": "Role",
  "perms.mine.source": "Source",
  "perms.mine.owned": "Owner of",
  "perms.mine.maintained": "Maintainer of",
  "perms.src.builtin": "config file / environment variable",
  "perms.src.db": "managed list (database)",
  "perms.src.token": "shared access token",
  "perms.src.user": "regular user",
  "perms.admins": "Superadmins",
  "perms.admins.desc": "Built-in superadmins come from the config file or GOLIVE_ADMINS and cannot be removed here. Managed superadmins can be added and removed.",
  "perms.admins.ph": "email@example.com",
  "perms.admins.add": "Add superadmin",
  "perms.admins.builtin": "built-in",
  "perms.admins.managed": "managed",
  "perms.admins.locktip": "Defined in the config file or the GOLIVE_ADMINS environment variable — edit it there.",
  "perms.admins.none": "No superadmins configured",
  "perms.sites": "Site permissions",
  "perms.sites.desc": "Owner and maintainers for every site.",
  "perms.sites.search": "Search slug / name / email…",
  "perms.sites.none": "No sites match",
  "perms.bulk": "Bulk grant / revoke",
  "perms.bulk.desc": "Grant or revoke maintainer rights for one account across several sites at once.",
  "perms.bulk.email": "Email",
  "perms.bulk.grant": "Grant maintainer",
  "perms.bulk.revoke": "Revoke maintainer",
  "perms.bulk.all": "Select all",
  "perms.bulk.none": "Clear selection",
  "perms.bulk.needemail": "Enter an email first",
  "perms.bulk.needsites": "Select at least one site",
  "perms.bulk.done": "Updated {n} site(s)",
  "perms.bulk.failed": "{n} site(s) could not be updated"
},
zh: {
  "gate.hint": "该服务启用了 Token 认证，请输入访问令牌（GOLIVE_TOKEN）。令牌仅保存在本浏览器的 sessionStorage。",
  "gate.enter": "进入门户",
  "nav.sites": "站点管理",
  "nav.data": "数据管理",
  "nav.perms": "权限管理",
  "nav.stats": "统计",
  "nav.audit": "审计日志",
  "who.superadmin": "超管",
  "sites.title": "站点管理",
  "sites.search": "搜索 slug / 名称…",
  "sites.count": "共 {n} 个站点",
  "sites.none": "没有站点",
  "sites.unnamed": "(未命名)",
  "sites.noslug": "无",
  "btn.search": "搜索",
  "btn.filter": "过滤",
  "btn.prev": "‹ 上一页",
  "btn.next": "下一页 ›",
  "btn.save": "保存",
  "btn.add": "添加",
  "btn.remove": "移除",
  "btn.delete": "删除",
  "btn.cancel": "取消",
  "btn.transfer": "移交",
  "btn.detail": "详情",
  "btn.view": "查看",
  "btn.edit": "编辑",
  "btn.rollback": "回滚",
  "btn.copy": "复制",
  "btn.copied": "已复制",
  "th.name": "名称",
  "th.slug": "slug",
  "th.owner": "owner",
  "th.role": "角色",
  "th.size": "大小",
  "th.updated": "更新时间",
  "th.actions": "操作",
  "th.id": "ID",
  "th.summary": "内容摘要",
  "th.time": "时间",
  "th.who": "操作人",
  "th.action": "action",
  "th.detail": "详情",
  "th.email": "邮箱",
  "th.source": "来源",
  "th.maintainers": "maintainers",
  "data.title": "数据管理",
  "data.search": "搜索 JSON 内容…",
  "data.add": "+ 新增行",
  "data.none": "没有数据行",
  "data.count": "共 {n} 行",
  "data.nomodels": "data backend 里还没有模型数据（可用 golive data create 或右上角“新增行”创建）。",
  "data.modal.create": "新增数据行",
  "data.modal.edit": "编辑数据行",
  "data.modal.view": "查看数据行",
  "data.err.json": "JSON 解析失败：",
  "data.err.object": "内容必须是 JSON 对象（{...}）",
  "data.err.model": "model 不能为空",
  "stats.title": "统计",
  "stats.top": "Top 10 站点（按大小）",
  "stats.sites": "站点总数",
  "stats.bytes": "总大小",
  "stats.recent": "近 7 天有更新",
  "stats.editable": "开启在线编辑",
  "stats.none": "暂无数据",
  "audit.title": "审计日志",
  "audit.byslug": "按 slug 过滤",
  "audit.byaction": "按 action 过滤",
  "audit.none": "暂无记录",
  "d.basic": "基本信息",
  "d.name": "名称",
  "d.notes": "备注",
  "d.editable": "在线编辑",
  "d.transfer": "移交 Owner",
  "d.transfer.ph": "新 owner 邮箱",
  "d.snaps": "快照 / 回滚",
  "d.snaps.none": "暂无快照",
  "d.delete": "删除站点",
  "d.delete.ph": "输入 slug 以确认",
  "d.nomaint": "暂无 maintainer",
  "msg.saved": "已保存",
  "msg.added": "已添加",
  "msg.removed": "已移除",
  "msg.deleted": "已删除",
  "msg.rolledback": "已回滚",
  "msg.transferred": "已移交给 ",
  "msg.copied": "已复制到剪贴板",
  "msg.copyfail": "复制失败，请手动选中文本复制",
  "msg.confirmdel": "请输入 {ref} 以确认删除",
  "confirm.transfer": "确认将站点移交给 {to}？移交后你可能失去管理权限。",
  "confirm.rollback": "回滚到快照 {ts}？当前版本会先自动存为新快照。",
  "confirm.delrow": "删除行 {name}？",
  "confirm.deladmin": "把 {email} 从超管名单里移除？",
  "confirm.revoke": "撤销 {email} 在 {n} 个站点上的 maintainer 权限？",
  "guide.data.title": "未配置数据后端",
  "guide.data.what": "数据管理页管理 TemplateAPI 模板行（golive_templates 表），需要一个数据后端——本机自用选 sqlite，多人共享选 Supabase / PostgREST。",
  "guide.sqlite": "最快的方式：用内置的 sqlite 后端",
  "guide.data.hint": "不想自己动手？点下面的按钮，把生成的任务描述丢给你的 AI 助手——里面已经带上了你机器上的真实路径、要写的配置和验证方式。",
  "guide.copyagent": "📋 复制给 AI 助手",
  "guide.cfg": "或者用共享后端（golive.yaml）",
  "guide.env": "密钥走环境变量，不要写进配置文件",
  "guide.verify": "然后建表并重启",
  "guide.docs": "查看完整文档 →",
  "guide.pathnote": "路径未能自动识别，请先运行 golive doctor 确认。",
  "perms.title": "权限管理",
  "perms.unavailable": "该服务未提供权限管理接口（需要 golive 0.7.0 及以上版本）。",
  "perms.mine": "我的权限",
  "perms.mine.desc": "当前账号能做什么，以及权限从哪里来。",
  "perms.mine.identity": "当前身份",
  "perms.mine.role": "角色",
  "perms.mine.source": "来源",
  "perms.mine.owned": "拥有的站点",
  "perms.mine.maintained": "维护的站点",
  "perms.src.builtin": "配置文件 / 环境变量",
  "perms.src.db": "可管理名单（数据库）",
  "perms.src.token": "共享访问令牌",
  "perms.src.user": "普通用户",
  "perms.admins": "超管名单",
  "perms.admins.desc": "内置超管来自配置文件或 GOLIVE_ADMINS 环境变量，无法在此删除；可管理超管可以随时增删。",
  "perms.admins.ph": "email@example.com",
  "perms.admins.add": "添加超管",
  "perms.admins.builtin": "内置",
  "perms.admins.managed": "可管理",
  "perms.admins.locktip": "来自配置文件或 GOLIVE_ADMINS 环境变量，请到那里修改。",
  "perms.admins.none": "尚未配置超管",
  "perms.sites": "站点权限总览",
  "perms.sites.desc": "每个站点的 owner 和 maintainers。",
  "perms.sites.search": "搜索 slug / 名称 / 邮箱…",
  "perms.sites.none": "没有匹配的站点",
  "perms.bulk": "批量授权",
  "perms.bulk.desc": "一次性给某个账号授予或撤销多个站点的 maintainer 权限。",
  "perms.bulk.email": "邮箱",
  "perms.bulk.grant": "授予 maintainer",
  "perms.bulk.revoke": "撤销 maintainer",
  "perms.bulk.all": "全选",
  "perms.bulk.none": "清空选择",
  "perms.bulk.needemail": "请先填写邮箱",
  "perms.bulk.needsites": "请至少选择一个站点",
  "perms.bulk.done": "已更新 {n} 个站点",
  "perms.bulk.failed": "{n} 个站点更新失败"
}
};

function t(key, vars){
  var dict = I18N[state.lang] || I18N.en;
  var s = dict[key];
  if (s == null) s = (I18N.en[key] == null ? key : I18N.en[key]);
  if (vars){
    Object.keys(vars).forEach(function(k){
      s = s.split("{" + k + "}").join(String(vars[k]));
    });
  }
  return s;
}

function $(id){ return document.getElementById(id); }
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
function fmtBytes(n){
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n/1024).toFixed(1) + " KB";
  return (n/1048576).toFixed(2) + " MB";
}
function toast(msg, isErr){
  var el = $("toast");
  el.textContent = msg;
  el.className = isErr ? "err" : "";
  el.style.display = "block";
  clearTimeout(el._h);
  el._h = setTimeout(function(){ el.style.display = "none"; }, 3200);
}

// ── theme ──────────────────────────────────────────────────────
function resolveTheme(pref){
  if (pref === "light" || pref === "dark") return pref;
  return (window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: light)").matches)
    ? "light" : "dark";
}
function applyTheme(pref, persist){
  if (pref !== "light" && pref !== "dark") pref = "system";
  state.themePref = pref;
  var root = document.documentElement;
  root.setAttribute("data-theme", resolveTheme(pref));
  root.setAttribute("data-theme-pref", pref);
  if (persist){
    try { localStorage.setItem(THEME_KEY, pref); } catch (e) {}
  }
  Array.prototype.forEach.call(
      document.querySelectorAll("#theme-switch button"), function(b){
    b.setAttribute("aria-pressed",
      b.dataset.themeSet === pref ? "true" : "false");
  });
}
if (window.matchMedia){
  var mq = window.matchMedia("(prefers-color-scheme: light)");
  var onSys = function(){
    if (state.themePref === "system") applyTheme("system", false);
  };
  if (mq.addEventListener) mq.addEventListener("change", onSys);
  else if (mq.addListener) mq.addListener(onSys);
}

// ── language ───────────────────────────────────────────────────
function applyLang(lang, persist){
  state.lang = (lang === "zh") ? "zh" : "en";
  var root = document.documentElement;
  root.setAttribute("lang", state.lang === "zh" ? "zh-CN" : "en");
  root.setAttribute("data-lang", state.lang);
  if (persist){
    try { localStorage.setItem(LANG_KEY, state.lang); } catch (e) {}
  }
  Array.prototype.forEach.call(
      document.querySelectorAll("[data-i18n]"), function(el){
    el.textContent = t(el.dataset.i18n);
  });
  Array.prototype.forEach.call(
      document.querySelectorAll("[data-i18n-ph]"), function(el){
    el.setAttribute("placeholder", t(el.dataset.i18nPh));
  });
  Array.prototype.forEach.call(
      document.querySelectorAll("#lang-switch button"), function(b){
    b.setAttribute("aria-pressed",
      b.dataset.lang === state.lang ? "true" : "false");
  });
  document.title = "golive · " + t("nav.sites").toLowerCase();
  rerender();
}
function rerender(){
  // Re-paint anything drawn from JS strings after a language switch.
  if (!state.me) return;
  var who = state.me.identity || {};
  $("whoami").textContent = (who.email || "(token)") +
    (who.superadmin ? " · " + t("who.superadmin") : "");
  var active = document.querySelector(".nav-item.active");
  var view = active ? active.dataset.view : "sites";
  if (view === "sites") loadSites();
  else if (view === "data") initData();
  else if (view === "perms") loadPerms();
  else if (view === "stats") loadStats();
  else if (view === "audit") loadAudit();
}

// ── clipboard ──────────────────────────────────────────────────
function copyText(text, btn){
  var ok = function(){
    if (btn){
      var old = btn.textContent;
      btn.textContent = t("btn.copied");
      btn.classList.add("ok");
      setTimeout(function(){
        btn.textContent = old; btn.classList.remove("ok");
      }, 1600);
    }
    toast(t("msg.copied"));
  };
  var fallback = function(){
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var done = false;
    try { done = document.execCommand("copy"); } catch (e) { done = false; }
    document.body.removeChild(ta);
    if (done) ok(); else toast(t("msg.copyfail"), true);
  };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(ok, fallback);
  } else {
    fallback();
  }
}

function api(method, path, body){
  var headers = {"Accept": "application/json"};
  var tok = sessionStorage.getItem(TOKEN_KEY);
  if (tok) headers["X-Golive-Token"] = tok;
  var opt = {method: method, headers: headers};
  if (body !== undefined){
    headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  return fetch(path, opt).then(function(r){
    return r.json().catch(function(){ return {}; }).then(function(j){
      if (!r.ok){
        var e = new Error(j.error || ("HTTP " + r.status));
        e.status = r.status;
        throw e;
      }
      return j;
    });
  });
}

// ── boot / gate ────────────────────────────────────────────────
Array.prototype.forEach.call(
    document.querySelectorAll("#theme-switch button"), function(b){
  b.addEventListener("click", function(){
    applyTheme(b.dataset.themeSet, true);
  });
});
Array.prototype.forEach.call(
    document.querySelectorAll("#lang-switch button"), function(b){
  b.addEventListener("click", function(){
    applyLang(b.dataset.lang, true);
  });
});

function initPrefs(){
  var pref = "system", lang = null;
  try { pref = localStorage.getItem(THEME_KEY) || "system"; } catch (e) {}
  try { lang = localStorage.getItem(LANG_KEY); } catch (e) {}
  if (!lang){
    var nav = (navigator.language || navigator.userLanguage || "en");
    lang = /^zh/i.test(nav) ? "zh" : "en";
  }
  applyTheme(pref, false);
  state.lang = (lang === "zh") ? "zh" : "en";
  applyLang(state.lang, false);
}

function start(){
  api("GET", "/api/admin/me").then(function(me){
    state.me = me;
    $("login-gate").style.display = "none";
    $("layout").style.display = "flex";
    $("ver").textContent = "v" + (BOOT.version || "");
    var who = me.identity || {};
    $("whoami").textContent = (who.email || "(token)") +
      (who.superadmin ? " · " + t("who.superadmin") : "");
    if (who.superadmin){
      $("nav-data").classList.remove("hidden");
      $("nav-perms").classList.remove("hidden");
      $("nav-stats").classList.remove("hidden");
      $("nav-audit").classList.remove("hidden");
    }
    loadSites();
  }).catch(function(e){
    if (e.status === 401){
      sessionStorage.removeItem(TOKEN_KEY);
      $("layout").style.display = "none";
      $("login-gate").style.display = "block";
    } else {
      toast(e.message, true);
    }
  });
}
$("gate-enter").addEventListener("click", function(){
  var v = $("gate-token").value.trim();
  if (!v) return;
  sessionStorage.setItem(TOKEN_KEY, v);
  start();
});
$("gate-token").addEventListener("keydown", function(ev){
  if (ev.key === "Enter") $("gate-enter").click();
});

// ── nav ────────────────────────────────────────────────────────
Array.prototype.forEach.call(
    document.querySelectorAll(".nav-item"), function(el){
  el.addEventListener("click", function(){
    Array.prototype.forEach.call(
      document.querySelectorAll(".nav-item"), function(n){
        n.classList.remove("active"); });
    el.classList.add("active");
    Array.prototype.forEach.call(
      document.querySelectorAll(".view"), function(v){
        v.classList.remove("active"); });
    $("view-" + el.dataset.view).classList.add("active");
    if (el.dataset.view === "sites") loadSites();
    if (el.dataset.view === "data") initData();
    if (el.dataset.view === "perms") loadPerms();
    if (el.dataset.view === "stats") loadStats();
    if (el.dataset.view === "audit") loadAudit();
  });
});

// ── sites list ─────────────────────────────────────────────────
function loadSites(){
  var qs = "?page=" + state.page + "&size=" + state.size +
           "&q=" + encodeURIComponent(state.q);
  api("GET", "/api/admin/sites" + qs).then(function(d){
    var tb = $("site-rows");
    tb.innerHTML = "";
    if (!d.sites.length){
      tb.innerHTML = '<tr><td colspan="7" class="empty">' +
        esc(t("sites.none")) + "</td></tr>";
    }
    d.sites.forEach(function(s){
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + esc(s.name || t("sites.unnamed")) + "</td>" +
        "<td>" + (s.slug ? '<a href="/' + esc(s.slug) +
                  '" target="_blank" rel="noopener">' + esc(s.slug) +
                  "</a>" : '<span class="badge">' + esc(t("sites.noslug")) +
                  "</span>") + "</td>" +
        "<td>" + esc(s.owner || "—") + "</td>" +
        '<td><span class="badge ' + esc(s.role) + '">' +
          esc(s.role || "—") + "</span></td>" +
        "<td>" + fmtBytes(s.size) + "</td>" +
        "<td>" + esc((s.updated_at || "").replace("T", " ")) + "</td>" +
        '<td class="actions"><button data-act="open">' +
          esc(t("btn.detail")) + "</button></td>";
      tr.querySelector('[data-act="open"]').addEventListener(
        "click", function(){ openDrawer(s.slug || s.site_id); });
      tb.appendChild(tr);
    });
    $("site-count").textContent = t("sites.count", {n: d.total});
    var pages = Math.max(1, Math.ceil(d.total / state.size));
    $("site-page").textContent = state.page + " / " + pages;
    $("site-prev").disabled = state.page <= 1;
    $("site-next").disabled = state.page >= pages;
  }).catch(function(e){ toast(e.message, true); });
}
$("site-search").addEventListener("click", function(){
  state.q = $("site-q").value.trim();
  state.page = 1;
  loadSites();
});
$("site-q").addEventListener("keydown", function(ev){
  if (ev.key === "Enter") $("site-search").click();
});
$("site-prev").addEventListener("click", function(){
  if (state.page > 1){ state.page--; loadSites(); }
});
$("site-next").addEventListener("click", function(){
  state.page++; loadSites();
});

// ── drawer ─────────────────────────────────────────────────────
function openDrawer(ref){
  api("GET", "/api/admin/sites/" + encodeURIComponent(ref))
  .then(function(s){
    state.current = s;
    $("d-title").textContent = s.name || s.slug || s.site_id;
    $("d-sub").textContent = "slug: " + (s.slug || "(无)") +
      " · id: " + s.site_id + " · owner: " + (s.owner || "(未设置)") +
      " · 角色: " + s.role;
    $("d-name").value = s.name || "";
    $("d-notes").value = s.notes || "";
    $("d-editable").checked = !!s.editable;
    var canMeta = (s.role === "owner" || s.role === "superadmin");
    $("d-save").disabled = !canMeta;
    $("sec-maint").style.display = canMeta ? "" : "none";
    $("sec-transfer").style.display = canMeta ? "" : "none";
    $("sec-delete").style.display = canMeta ? "" : "none";
    renderMaints(s.maintainers || []);
    renderSnaps(s.snapshots || []);
    $("d-del-confirm").value = "";
    $("drawer").classList.add("open");
    $("drawer-mask").classList.add("open");
  }).catch(function(e){ toast(e.message, true); });
}
function closeDrawer(){
  $("drawer").classList.remove("open");
  $("drawer-mask").classList.remove("open");
  state.current = null;
}
$("drawer-mask").addEventListener("click", closeDrawer);

function curRef(){
  var s = state.current;
  return encodeURIComponent(s.slug || s.site_id);
}

$("d-save").addEventListener("click", function(){
  api("PATCH", "/api/admin/sites/" + curRef(), {
    name: $("d-name").value,
    notes: $("d-notes").value,
    editable: $("d-editable").checked
  }).then(function(){
    toast(t("msg.saved"));
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

function renderMaints(list){
  var box = $("d-maints");
  box.innerHTML = list.length ? "" :
    '<span style="color:var(--muted);font-size:12px">' +
    esc(t("d.nomaint")) + "</span>";
  list.forEach(function(m){
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.innerHTML = esc(m) + ' <b title="' + esc(t("btn.remove")) +
      '">\u00d7</b>';
    tag.querySelector("b").addEventListener("click", function(){
      api("DELETE", "/api/admin/sites/" + curRef() + "/maintainers",
          {email: m})
      .then(function(d){
        renderMaints(d.maintainers);
        toast(t("msg.removed"));
      })
      .catch(function(e){ toast(e.message, true); });
    });
    box.appendChild(tag);
  });
}
$("d-maint-add").addEventListener("click", function(){
  var email = $("d-maint-email").value.trim();
  if (!email) return;
  api("POST", "/api/admin/sites/" + curRef() + "/maintainers", {email: email})
  .then(function(d){
    $("d-maint-email").value = "";
    renderMaints(d.maintainers);
    toast(t("msg.added"));
  }).catch(function(e){ toast(e.message, true); });
});

$("d-transfer").addEventListener("click", function(){
  var to = $("d-transfer-to").value.trim();
  if (!to) return;
  if (!window.confirm(t("confirm.transfer", {to: to}))) return;
  api("POST", "/api/admin/sites/" + curRef() + "/transfer", {to: to})
  .then(function(){
    toast(t("msg.transferred") + to);
    closeDrawer();
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

function renderSnaps(snaps){
  var box = $("d-snaps");
  box.innerHTML = snaps.length ? "" :
    '<div style="color:var(--muted);font-size:12px">' +
    esc(t("d.snaps.none")) + "</div>";
  snaps.forEach(function(sn){
    var row = document.createElement("div");
    row.className = "snap-row";
    row.innerHTML = '<span class="ts">' + esc(sn.ts) + "</span>" +
      "<span>" + fmtBytes(sn.size) + "</span>" +
      "<button data-a='rb'>" + esc(t("btn.rollback")) + "</button>";
    row.querySelector("[data-a='rb']").addEventListener("click", function(){
      if (!window.confirm(t("confirm.rollback", {ts: sn.ts}))) return;
      api("POST", "/api/admin/sites/" + curRef() + "/rollback",
          {snapshot: sn.ts})
      .then(function(){
        toast(t("msg.rolledback"));
        openDrawer(state.current.slug || state.current.site_id);
      }).catch(function(e){ toast(e.message, true); });
    });
    box.appendChild(row);
  });
}

$("d-delete").addEventListener("click", function(){
  var s = state.current;
  var ref = s.slug || s.site_id;
  if ($("d-del-confirm").value.trim() !== ref){
    toast(t("msg.confirmdel", {ref: ref}), true);
    return;
  }
  api("DELETE", "/api/admin/sites/" + curRef(), {confirm: ref})
  .then(function(){
    toast(t("msg.deleted") + " " + ref);
    closeDrawer();
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

// ── data management (M6) ──────────────────────────────────────
function initData(){
  api("GET", "/api/admin/data/models").then(function(d){
    $("data-nobackend").style.display = "none";
    $("data-main").style.display = "";
    var sel = $("data-model");
    sel.innerHTML = "";
    (d.models || []).forEach(function(m){
      var o = document.createElement("option");
      o.value = m.model_code;
      o.textContent = m.model_code + " (" + m.count + ")";
      sel.appendChild(o);
    });
    if (!(d.models || []).length){
      $("data-rows").innerHTML =
        '<tr><td colspan="5" class="empty">' +
        esc(t("data.nomodels")) + "</td></tr>";
      $("data-count").textContent = "";
      $("data-page").textContent = "";
      state.dataModel = "";
      return;
    }
    if (!state.dataModel ||
        !(d.models || []).some(function(m){
          return m.model_code === state.dataModel; })){
      state.dataModel = d.models[0].model_code;
    }
    sel.value = state.dataModel;
    loadDataRows();
  }).catch(function(e){
    if (e.status === 400){
      $("data-main").style.display = "none";
      renderDataGuide();
      $("data-nobackend").style.display = "block";
    } else {
      toast(e.message, true);
    }
  });
}
function jsonSummary(v){
  var s = "";
  try { s = JSON.stringify(v); } catch (_e){ s = String(v); }
  if (s == null) s = "";
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}
function loadDataRows(){
  if (!state.dataModel) return;
  var qs = "?model=" + encodeURIComponent(state.dataModel) +
    "&page=" + state.dataPage + "&size=" + state.dataSize +
    "&q=" + encodeURIComponent(state.dataQ);
  api("GET", "/api/admin/data/rows" + qs).then(function(d){
    var tb = $("data-rows");
    tb.innerHTML = "";
    if (!(d.rows || []).length){
      tb.innerHTML = '<tr><td colspan="5" class="empty">' +
        esc(t("data.none")) + "</td></tr>";
    }
    (d.rows || []).forEach(function(r){
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td style="font-family:ui-monospace,monospace;font-size:12px">' +
          esc(String(r.id || "").slice(0, 8)) + "</td>" +
        "<td>" + esc(r.name || "") + "</td>" +
        '<td style="font-size:12px;color:var(--muted)">' +
          esc(jsonSummary(r.content)) + "</td>" +
        "<td>" + esc(String(r.updated_at || r.created_at || "")
                     .replace("T", " ").slice(0, 19)) + "</td>" +
        '<td class="actions">' +
          '<button data-act="view">' + esc(t("btn.view")) + "</button>" +
          '<button data-act="edit">' + esc(t("btn.edit")) + "</button>" +
          '<button class="danger" data-act="del">' + esc(t("btn.delete")) +
          "</button></td>";
      tr.querySelector('[data-act="view"]').addEventListener(
        "click", function(){ openRowModal(r, "view"); });
      tr.querySelector('[data-act="edit"]').addEventListener(
        "click", function(){ openRowModal(r, "edit"); });
      tr.querySelector('[data-act="del"]').addEventListener(
        "click", function(){
          if (!window.confirm(
              t("confirm.delrow", {name: r.name || r.id}))) return;
          api("DELETE", "/api/admin/data/rows/" +
              encodeURIComponent(r.id))
          .then(function(){ toast(t("msg.deleted")); loadDataRows(); })
          .catch(function(e){ toast(e.message, true); });
        });
      tb.appendChild(tr);
    });
    var pages = Math.max(1, Math.ceil((d.total || 0) / state.dataSize));
    $("data-page").textContent = state.dataPage + " / " + pages;
    $("data-count").textContent = t("data.count", {n: d.total || 0});
    $("data-prev").disabled = state.dataPage <= 1;
    $("data-next").disabled = state.dataPage >= pages;
  }).catch(function(e){ toast(e.message, true); });
}
$("data-model").addEventListener("change", function(){
  state.dataModel = this.value;
  state.dataPage = 1;
  loadDataRows();
});
$("data-search").addEventListener("click", function(){
  state.dataQ = $("data-q").value.trim();
  state.dataPage = 1;
  loadDataRows();
});
$("data-q").addEventListener("keydown", function(ev){
  if (ev.key === "Enter") $("data-search").click();
});
$("data-prev").addEventListener("click", function(){
  if (state.dataPage > 1){ state.dataPage--; loadDataRows(); }
});
$("data-next").addEventListener("click", function(){
  state.dataPage++; loadDataRows();
});
$("data-add").addEventListener("click", function(){
  openRowModal(null, "create");
});

function openRowModal(row, mode){
  state.dmRow = row;
  state.dmMode = mode;
  var isView = mode === "view";
  var isCreate = mode === "create";
  $("dm-title").textContent = isCreate ? t("data.modal.create") :
    (isView ? t("data.modal.view") : t("data.modal.edit"));
  $("dm-model-row").style.display = isCreate ? "" : "none";
  $("dm-model").value = state.dataModel || "";
  $("dm-name").value = row ? (row.name || "") : "";
  $("dm-name").readOnly = isView;
  var content = row ? row.content : {};
  try {
    $("dm-json").value = JSON.stringify(
      content == null ? {} : content, null, 2);
  } catch (_e){ $("dm-json").value = String(content); }
  $("dm-json").readOnly = isView;
  $("dm-err").style.display = "none";
  $("dm-save").style.display = isView ? "none" : "";
  $("dm-mask").style.display = "block";
  $("dm").style.display = "block";
}
function closeRowModal(){
  $("dm-mask").style.display = "none";
  $("dm").style.display = "none";
  state.dmRow = null;
}
$("dm-mask").addEventListener("click", closeRowModal);
$("dm-cancel").addEventListener("click", closeRowModal);
$("dm-save").addEventListener("click", function(){
  var parsed;
  try {
    parsed = JSON.parse($("dm-json").value || "{}");
  } catch (e){
    $("dm-err").textContent = t("data.err.json") + e.message;
    $("dm-err").style.display = "block";
    return;
  }
  if (parsed === null || typeof parsed !== "object" ||
      Array.isArray(parsed)){
    $("dm-err").textContent = t("data.err.object");
    $("dm-err").style.display = "block";
    return;
  }
  var name = $("dm-name").value.trim();
  var done = function(){
    toast(t("msg.saved"));
    closeRowModal();
    if (state.dmMode === "create") initData(); else loadDataRows();
  };
  var fail = function(e){
    $("dm-err").textContent = e.message;
    $("dm-err").style.display = "block";
  };
  if (state.dmMode === "create"){
    var model = $("dm-model").value.trim();
    if (!model){
      $("dm-err").textContent = t("data.err.model");
      $("dm-err").style.display = "block";
      return;
    }
    api("POST", "/api/admin/data/rows",
        {model: model, name: name, data: parsed}).then(done).catch(fail);
  } else {
    api("PATCH", "/api/admin/data/rows/" +
        encodeURIComponent(state.dmRow.id),
        {name: name, data: parsed}).then(done).catch(fail);
  }
});

// ── stats ──────────────────────────────────────────────────────
function loadStats(){
  api("GET", "/api/admin/stats").then(function(d){
    var cards = [
      [t("stats.sites"), d.total_sites],
      [t("stats.bytes"), fmtBytes(d.total_bytes)],
      [t("stats.recent"), d.updated_last_7d],
      [t("stats.editable"), d.editable_sites]
    ];
    $("stat-cards").innerHTML = cards.map(function(c){
      return '<div class="card"><div class="lbl">' + esc(c[0]) +
             '</div><div class="num">' + esc(c[1]) + "</div></div>";
    }).join("");
    $("stat-top").innerHTML = (d.top_sites || []).map(function(row, i){
      return "<tr><td>" + (i+1) + "</td><td>" + esc(row.slug) + "</td><td>" +
        esc(row.name) + "</td><td>" + fmtBytes(row.size) + "</td></tr>";
    }).join("") || '<tr><td colspan="4" class="empty">' +
      esc(t("stats.none")) + "</td></tr>";
  }).catch(function(e){ toast(e.message, true); });
}

// ── audit ──────────────────────────────────────────────────────
function loadAudit(){
  var qs = "?page=" + state.auditPage + "&size=50" +
    "&slug=" + encodeURIComponent($("audit-slug").value.trim()) +
    "&action=" + encodeURIComponent($("audit-action").value.trim());
  api("GET", "/api/admin/audit" + qs).then(function(d){
    $("audit-rows").innerHTML = (d.entries || []).map(function(e){
      return "<tr><td>" + esc((e.ts || "").replace("T", " ")) + "</td><td>" +
        esc(e.who) + "</td><td>" + esc(e.action) + "</td><td>" +
        esc(e.slug) + "</td><td style='font-size:12px;color:var(--muted)'>" +
        esc(e.detail ? JSON.stringify(e.detail) : "") + "</td></tr>";
    }).join("") || '<tr><td colspan="5" class="empty">' +
      esc(t("audit.none")) + "</td></tr>";
    var pages = Math.max(1, Math.ceil((d.total || 0) / 50));
    $("audit-page").textContent = state.auditPage + " / " + pages;
    $("audit-prev").disabled = state.auditPage <= 1;
    $("audit-next").disabled = state.auditPage >= pages;
  }).catch(function(e){ toast(e.message, true); });
}
$("audit-search").addEventListener("click", function(){
  state.auditPage = 1; loadAudit();
});
$("audit-prev").addEventListener("click", function(){
  if (state.auditPage > 1){ state.auditPage--; loadAudit(); }
});
$("audit-next").addEventListener("click", function(){
  state.auditPage++; loadAudit();
});

// ── guided empty states (agent-friendly) ───────────────────────
// Every "X is not configured" screen offers two paths: read the config
// snippet yourself, or hand a ready-made task description to whatever AI
// assistant you already use.
function golivePaths(){
  var home = BOOT.home || "";
  var cfg = BOOT.config_path || "";
  return {
    home: home || "<GOLIVE_HOME, e.g. ~/.golive>",
    config: cfg || "<GOLIVE_HOME>/golive.yaml",
    resolved: !!(home && cfg)
  };
}

var DATA_SNIPPETS = {
en: {
  sqlite: [
    "data:",
    "  backend: sqlite      # zero-config: a file inside GOLIVE_HOME"
  ].join("\n"),
  yaml: [
    "data:",
    "  backend: supabase",
    "supabase:",
    "  url: https://YOUR-PROJECT.supabase.co",
    "  # the key itself never goes in this file — see the env step below",
    "  service_key_env: GOLIVE_SUPABASE_SERVICE_KEY"
  ].join("\n"),
  env: [
    "export GOLIVE_SUPABASE_SERVICE_KEY='your-service-role-key'",
    "# make it permanent: append the line to ~/.bashrc or ~/.zshrc,",
    "# or put it in the environment of whatever supervises golive."
  ].join("\n"),
  verify: [
    "golive db init --sql   # print the CREATE TABLE statement",
    "golive doctor          # confirm the data backend is reachable",
    "golive serve           # restart, then open /admin -> Data"
  ].join("\n")
},
zh: {
  sqlite: [
    "data:",
    "  backend: sqlite      # 零配置：数据存在 GOLIVE_HOME 下的一个文件里"
  ].join("\n"),
  yaml: [
    "data:",
    "  backend: supabase",
    "supabase:",
    "  url: https://YOUR-PROJECT.supabase.co",
    "  # 密钥本身不要写在这个文件里，见下面的环境变量步骤",
    "  service_key_env: GOLIVE_SUPABASE_SERVICE_KEY"
  ].join("\n"),
  env: [
    "export GOLIVE_SUPABASE_SERVICE_KEY='你的 service role key'",
    "# 想长期生效：把这行追加到 ~/.bashrc 或 ~/.zshrc，",
    "# 或者写进托管 golive 的那个进程的环境变量里。"
  ].join("\n"),
  verify: [
    "golive db init --sql   # 打印建表 SQL",
    "golive doctor          # 确认数据后端连通",
    "golive serve           # 重启，然后打开 /admin -> 数据管理"
  ].join("\n")
}
};

function snip(name){
  var pack = DATA_SNIPPETS[state.lang] || DATA_SNIPPETS.en;
  return pack[name];
}

function dataAgentPrompt(){
  var p = golivePaths();
  var ver = BOOT.version || "unknown";
  var docs = BOOT.docs_url || "";
  if (state.lang === "zh"){
    return [
      "我在用 html-golive（一个自部署的 HTML 发布工具，当前版本 v" + ver +
        "，命令行入口是 golive）。",
      "请帮我把它的数据后端配置好，让管理门户的「数据管理」页可用。",
      "",
      "我的环境：",
      "- GOLIVE_HOME：" + p.home,
      "- 配置文件：" + p.config + "（如果不存在就新建）",
      (p.resolved ? "" :
        "- 注意：上面的路径没能自动识别，请先运行 `golive doctor` 确认真实路径。"),
      "",
      "先问我一句想用哪种后端，再往下做：",
      "",
      "【方案 A：sqlite，零配置，本机自用推荐】",
      "1. 编辑（或创建）上面的配置文件，加入：",
      snip("sqlite"),
      "2. 重启 `golive serve`，打开 /admin 的「数据管理」页确认。",
      "",
      "【方案 B：Supabase / PostgREST，多人共享时用】",
      "1. 编辑配置文件，加入：",
      snip("yaml"),
      "2. 密钥不要写进配置文件，用环境变量传入：",
      snip("env"),
      "3. 建表：运行 `golive db init --sql` 拿到建表 SQL，在 Supabase 的 " +
        "SQL editor 里执行。",
      "4. 验证：",
      snip("verify"),
      "",
      "参考文档：" + docs,
      "如果哪一步失败，请把报错原文贴给我，不要跳过。"
    ].filter(function(x){ return x !== ""; }).join("\n");
  }
  return [
    "I'm using html-golive (a self-hosted HTML deployment tool, version v" +
      ver + ", CLI entry point: golive).",
    "Please configure its data backend so the \"Data\" page in the admin " +
      "portal works.",
    "",
    "My environment:",
    "- GOLIVE_HOME: " + p.home,
    "- Config file: " + p.config + " (create it if it doesn't exist)",
    (p.resolved ? "" :
      "- Note: those paths could not be detected automatically — run " +
      "`golive doctor` first to confirm the real ones."),
    "",
    "Ask me which backend I want, then proceed:",
    "",
    "[Option A: sqlite — zero config, best for a single machine]",
    "1. Edit (or create) the config file above and add:",
    snip("sqlite"),
    "2. Restart `golive serve` and check /admin -> Data.",
    "",
    "[Option B: Supabase / PostgREST — when several people share it]",
    "1. Edit the config file and add:",
    snip("yaml"),
    "2. Never put the key in the file — pass it through the environment:",
    snip("env"),
    "3. Create the table: run `golive db init --sql` to print the SQL and " +
      "execute it in the Supabase SQL editor.",
    "4. Verify:",
    snip("verify"),
    "",
    "Reference docs: " + docs,
    "If any step fails, paste the exact error back to me instead of skipping it."
  ].filter(function(x){ return x !== ""; }).join("\n");
}

function codeBlock(label, code){
  return '<div class="cb-label">' + esc(label) + "</div>" +
    '<div class="codeblock"><pre>' + esc(code) + "</pre>" +
    '<button class="cb-copy" type="button" data-copy="' + esc(code) + '">' +
    esc(t("btn.copy")) + "</button></div>";
}

function wireCopyButtons(root){
  Array.prototype.forEach.call(
      root.querySelectorAll("[data-copy]"), function(btn){
    btn.addEventListener("click", function(){
      copyText(btn.getAttribute("data-copy") || "", btn);
    });
  });
}

function renderDataGuide(){
  var box = $("data-nobackend");
  var p = golivePaths();
  var docs = BOOT.docs_url || "";
  var html =
    "<h3>" + esc(t("guide.data.title")) + "</h3>" +
    "<p>" + esc(t("guide.data.what")) + "</p>" +
    '<div class="hint">' + esc(t("guide.data.hint")) +
      (p.resolved ? "" : "<br>" + esc(t("guide.pathnote"))) + "</div>" +
    '<div class="guide-actions">' +
      '<button class="primary" id="data-agent-copy" type="button">' +
      esc(t("guide.copyagent")) + "</button>" +
      (docs ? '<a class="doclink" href="' + esc(docs) +
        '" target="_blank" rel="noopener noreferrer">' +
        esc(t("guide.docs")) + "</a>" : "") +
    "</div>" +
    codeBlock(t("guide.sqlite"), snip("sqlite")) +
    codeBlock(t("guide.cfg"), snip("yaml")) +
    codeBlock(t("guide.env"), snip("env")) +
    codeBlock(t("guide.verify"), snip("verify"));
  box.innerHTML = html;
  wireCopyButtons(box);
  var agentBtn = $("data-agent-copy");
  if (agentBtn){
    agentBtn.addEventListener("click", function(){
      copyText(dataAgentPrompt(), agentBtn);
    });
  }
}

// ── permissions (M7) ───────────────────────────────────────────
// The API may return admins either as plain email strings or as objects
// carrying provenance ({email, added_by, added_at}); both are accepted.
function adminEmail(entry){
  if (entry && typeof entry === "object") return entry.email || "";
  return String(entry == null ? "" : entry);
}
function adminEmails(list){
  return (list || []).map(adminEmail).filter(function(e){ return !!e; });
}
function adminMeta(entry){
  if (!entry || typeof entry !== "object") return "";
  var by = entry.added_by || "";
  var at = String(entry.added_at || "").replace("T", " ").slice(0, 19);
  if (!by && !at) return "";
  return (by ? by : "?") + (at ? " · " + at : "");
}

function loadPerms(){
  api("GET", "/api/admin/permissions").then(function(d){
    state.perms = d;
    $("perms-unavailable").style.display = "none";
    $("perms-main").style.display = "";
    renderPermMine();
    renderPermAdmins();
    renderPermSites();
    renderPermBulkSlugs();
  }).catch(function(e){
    if (e.status === 404 || e.status === 501){
      $("perms-main").style.display = "none";
      var box = $("perms-unavailable");
      box.style.display = "block";
      box.innerHTML = '<div class="hint">' +
        esc(t("perms.unavailable")) + "</div>";
    } else {
      toast(e.message, true);
    }
  });
}

function permSourceLabel(){
  var me = state.me || {};
  var who = me.identity || {};
  var d = state.perms || {};
  var email = (who.email || "").toLowerCase();
  if (who.superadmin){
    var builtin = adminEmails(d.builtin_admins).map(function(x){
      return x.toLowerCase(); });
    if (email && builtin.indexOf(email) >= 0) return t("perms.src.builtin");
    var managed = adminEmails(d.managed_admins).map(function(x){
      return x.toLowerCase(); });
    if (email && managed.indexOf(email) >= 0) return t("perms.src.db");
    return t("perms.src.token");
  }
  return who.via_token ? t("perms.src.token") : t("perms.src.user");
}

function renderPermMine(){
  var me = state.me || {};
  var who = me.identity || {};
  var rows = [
    [t("perms.mine.identity"), who.email || "(token)"],
    [t("perms.mine.role"), who.superadmin ? t("who.superadmin") : (me.role || "user")],
    [t("perms.mine.source"), permSourceLabel()],
    [t("perms.mine.owned"), (me.owned || []).join(", ") || "—"],
    [t("perms.mine.maintained"), (me.maintained || []).join(", ") || "—"]
  ];
  $("perm-mine-body").innerHTML = rows.map(function(r){
    return "<dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd>";
  }).join("");
}

function renderPermAdmins(){
  var d = state.perms || {};
  var tb = $("perm-admin-rows");
  var out = [];
  (d.builtin_admins || []).forEach(function(entry){
    var em = adminEmail(entry);
    if (!em) return;
    out.push("<tr><td>" + esc(em) + "</td><td>" +
      '<span class="badge">' + esc(t("perms.admins.builtin")) +
      "</span></td>" +
      '<td class="actions"><span class="lock" title="' +
      esc(t("perms.admins.locktip")) + '" aria-label="' +
      esc(t("perms.admins.builtin")) + '"></span></td></tr>');
  });
  (d.managed_admins || []).forEach(function(entry){
    var em = adminEmail(entry);
    if (!em) return;
    var meta = adminMeta(entry);
    out.push('<tr data-admin="' + esc(em) + '"><td>' + esc(em) +
      (meta ? '<div style="color:var(--muted);font-size:11.5px">' +
        esc(meta) + "</div>" : "") +
      '</td><td><span class="badge maintainer">' + esc(t("perms.admins.managed")) +
      "</span></td>" +
      '<td class="actions"><button class="danger" data-act="rm">' +
      esc(t("btn.remove")) + "</button></td></tr>");
  });
  tb.innerHTML = out.join("") ||
    '<tr><td colspan="3" class="empty">' + esc(t("perms.admins.none")) +
    "</td></tr>";
  Array.prototype.forEach.call(
      tb.querySelectorAll('[data-act="rm"]'), function(btn){
    btn.addEventListener("click", function(){
      var em = btn.closest("tr").getAttribute("data-admin");
      if (!window.confirm(t("confirm.deladmin", {email: em}))) return;
      api("DELETE", "/api/admin/permissions/admins", {email: em})
        .then(function(){ toast(t("msg.removed")); loadPerms(); })
        .catch(function(e){ toast(e.message, true); });
    });
  });
}

$("perm-admin-add").addEventListener("click", function(){
  var em = $("perm-admin-email").value.trim();
  if (!em) return;
  api("POST", "/api/admin/permissions/admins", {email: em})
    .then(function(){
      $("perm-admin-email").value = "";
      toast(t("msg.added"));
      loadPerms();
    }).catch(function(e){ toast(e.message, true); });
});
$("perm-admin-email").addEventListener("keydown", function(ev){
  if (ev.key === "Enter") $("perm-admin-add").click();
});

function permSiteList(){
  var acl = (state.perms || {}).sites_acl || [];
  var q = state.permQ.toLowerCase();
  if (!q) return acl;
  return acl.filter(function(s){
    var hay = [s.slug, s.name, s.owner].concat(s.maintainers || [])
      .join(" ").toLowerCase();
    return hay.indexOf(q) >= 0;
  });
}

function renderPermSites(){
  var rows = permSiteList();
  $("perm-site-rows").innerHTML = rows.map(function(s){
    var maints = (s.maintainers || []).length
      ? (s.maintainers || []).map(function(m){
          return '<span class="badge maintainer">' + esc(m) + "</span>";
        }).join(" ")
      : '<span style="color:var(--muted)">—</span>';
    return "<tr><td>" + esc(s.name || t("sites.unnamed")) + "</td><td>" +
      esc(s.slug || "—") + "</td><td>" + esc(s.owner || "—") + "</td><td>" +
      maints + "</td></tr>";
  }).join("") || '<tr><td colspan="4" class="empty">' +
    esc(t("perms.sites.none")) + "</td></tr>";
}
$("perm-site-search").addEventListener("click", function(){
  state.permQ = $("perm-site-q").value.trim();
  renderPermSites();
});
$("perm-site-q").addEventListener("keydown", function(ev){
  if (ev.key === "Enter") $("perm-site-search").click();
});

function renderPermBulkSlugs(){
  var acl = (state.perms || {}).sites_acl || [];
  $("perm-bulk-slugs").innerHTML = acl.map(function(s){
    var slug = s.slug || "";
    if (!slug) return "";
    return '<label><input type="checkbox" value="' + esc(slug) + '">' +
      esc(slug) + "</label>";
  }).join("") || '<span style="color:var(--muted);font-size:12px">' +
    esc(t("perms.sites.none")) + "</span>";
}
function bulkSelected(){
  return Array.prototype.map.call(
    $("perm-bulk-slugs").querySelectorAll("input:checked"),
    function(i){ return i.value; });
}
function bulkSetAll(on){
  Array.prototype.forEach.call(
    $("perm-bulk-slugs").querySelectorAll("input"),
    function(i){ i.checked = on; });
}
$("perm-bulk-all").addEventListener("click", function(){ bulkSetAll(true); });
$("perm-bulk-none").addEventListener("click", function(){ bulkSetAll(false); });

function bulkApply(action){
  var em = $("perm-bulk-email").value.trim();
  if (!em){ toast(t("perms.bulk.needemail"), true); return; }
  var slugs = bulkSelected();
  if (!slugs.length){ toast(t("perms.bulk.needsites"), true); return; }
  if (action === "revoke" &&
      !window.confirm(t("confirm.revoke", {email: em, n: slugs.length}))){
    return;
  }
  api("POST", "/api/admin/permissions/bulk", {
    email: em, role: "maintainer", slugs: slugs, action: action
  }).then(function(r){
    r = r || {};
    var n = slugs.length;
    if (Array.isArray(r.applied)) n = r.applied.length;
    else if (typeof r.changed === "number") n = r.changed;
    toast(t("perms.bulk.done", {n: n}));
    var failed = Array.isArray(r.failed) ? r.failed : [];
    if (failed.length){
      toast(t("perms.bulk.failed", {n: failed.length}), true);
    }
    bulkSetAll(false);
    loadPerms();
  }).catch(function(e){ toast(e.message, true); });
}
$("perm-bulk-grant").addEventListener("click", function(){
  bulkApply("grant");
});
$("perm-bulk-revoke").addEventListener("click", function(){
  bulkApply("revoke");
});

initPrefs();
start();
})();
</script>
</body>
</html>
"""
