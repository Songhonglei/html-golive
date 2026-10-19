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
from golive.server.brand import ROCKET_MARK


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
    return _PAGE_TEMPLATE.replace("__GOLIVE_BOOT__", json_for_script(boot)).replace(
        "__GOLIVE_ROCKET__", ROCKET_MARK)


_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>golive · admin</title>
<link rel="icon" type="image/svg+xml" href="/admin/favicon.svg?v=rocket-1">
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
/* Quiet Console: warm neutrals, pine accents, and an 8px spacing rhythm. */
:root, :root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#141918;
  --panel:#1b211f;
  --panel2:#242c29;
  --line:#343f39;
  --text:#e8eeea;
  --muted:#a3b2a9;
  --accent:#9bd9ba;
  --accent2:#a5e0c3;
  --ok:#9bd9ba;
  --warn:#e8c58c;
  --danger:#f4a6a6;
  --radius:12px;
  --on-accent:#14271e;
  --btn-hover:#303a34;
  --accent-soft:#273e32;
  --row-hover:#222c26;
  --danger-soft:#3c2829;
  --mask:rgba(4,10,7,.66);
  --shadow:0 24px 80px rgba(0,0,0,.3);
  --code-bg:#141b17;
  --ok-soft:#273e32;
  --warn-soft:#3a3326;
  --sidebar:#171d1a;
  --subtle:#1f2722;
  --focus:#a5e0c3;
  --brand:#a5e0c3;
}
:root[data-theme="light"]{
  color-scheme:light;
  --bg:#f7f8f5;
  --panel:#ffffff;
  --panel2:#f0f3ef;
  --line:#dce2dc;
  --text:#202c25;
  --muted:#5f6f64;
  --accent:#2c6649;
  --accent2:#285c42;
  --ok:#286043;
  --warn:#8a611c;
  --danger:#ad3e3e;
  --radius:12px;
  --on-accent:#ffffff;
  --btn-hover:#e7ece6;
  --accent-soft:#e7f0e9;
  --row-hover:#f5f8f3;
  --danger-soft:#faeeee;
  --mask:rgba(22,35,26,.36);
  --shadow:0 24px 80px rgba(28,46,34,.13);
  --code-bg:#f1f4ef;
  --ok-soft:#e7f0e9;
  --warn-soft:#fbf3e4;
  --sidebar:#eef1eb;
  --subtle:#f9faf7;
  --focus:#2c6649;
  --brand:#285c42;
}
*{
  box-sizing:border-box;
  margin:0;
  padding:0
}
body{
  background:var(--bg);
  color:var(--text);
  font:14px/1.65 "Avenir Next","PingFang SC","Noto Sans CJK SC",sans-serif;
  -webkit-font-smoothing:antialiased
}
a{
  color:var(--accent);
  text-decoration:none
}
a:hover{
  text-decoration:underline;
  text-underline-offset:4px
}
button,input,select,textarea{
  font:inherit
}
button,a,input,select,textarea{
  -webkit-tap-highlight-color:transparent
}
button{
  cursor:pointer;
  border:1px solid var(--line);
  background:var(--panel);
  color:var(--text);
  border-radius:7px;
  min-height:44px;
  padding:9px 15px;
  transition:background .18s,border-color .18s,color .18s;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  font-weight:500;
  white-space:nowrap
}
button:hover{
  background:var(--btn-hover);
  border-color:var(--muted)
}
button.primary{
  background:var(--accent2);
  border-color:var(--accent2);
  color:var(--on-accent)
}
button.primary:hover{
  background:var(--accent);
  border-color:var(--accent)
}
button.danger{
  background:transparent;
  border-color:var(--line);
  color:var(--danger)
}
button.danger:hover{
  background:var(--danger-soft);
  border-color:var(--danger)
}
button:disabled{
  cursor:not-allowed;
  color:var(--muted);
  background:var(--panel2);
  border-color:var(--line)
}
button:disabled:hover{
  background:var(--panel2);
  border-color:var(--line)
}
:where(button,a,input,select,textarea,[role="button"]):focus-visible{
  outline:2px solid var(--focus);
  outline-offset:3px
}
input,select,textarea{
  background:var(--panel);
  color:var(--text);
  border:1px solid var(--line);
  border-radius:7px;
  padding:9px 12px;
  min-width:0;
  max-width:100%;
  min-height:44px
}
input::placeholder,textarea::placeholder{
  color:var(--muted)
}
input[type=checkbox]{
  accent-color:var(--accent);
  min-height:20px;
  width:18px;
  height:18px;
  cursor:pointer
}
textarea{
  line-height:1.65
}
select{
  cursor:pointer
}
svg.icon{
  width:19px;
  height:19px;
  flex:0 0 auto;
  stroke:currentColor;
  stroke-width:1.7;
  fill:none;
  stroke-linecap:round;
  stroke-linejoin:round
}
.sr-only{
  position:absolute;
  width:1px;
  height:1px;
  padding:0;
  margin:-1px;
  overflow:hidden;
  clip-path:inset(50%);
  white-space:nowrap;
  border:0
}
.skip-link{
  position:fixed;
  left:16px;
  top:-100px;
  z-index:100;
  background:var(--panel);
  padding:12px;
  border:1px solid var(--accent);
  border-radius:8px
}
.skip-link:focus{
  top:12px
}
#layout{
  display:flex;
  min-height:100vh
}
#sidebar{
  width:238px;
  flex:0 0 238px;
  background:var(--sidebar);
  border-right:1px solid var(--line);
  padding:28px 16px 16px;
  display:flex;
  flex-direction:column;
  position:sticky;
  top:0;
  height:100vh;
  overflow-y:auto
}
#logo{
  display:flex;
  align-items:center;
  gap:11px;
  padding:0 12px 30px;
  font:700 24px/1.2 "Avenir Next",sans-serif;
  letter-spacing:-1.2px;
  border-bottom:1px solid var(--line);
  margin-bottom:20px
}
.brand-mark{
  width:32px;
  height:34px;
  display:grid;
  place-items:center;
  color:var(--brand)
}
.brand-mark svg{
  width:32px;
  height:34px
}
#logo small{
  display:block;
  font:500 10px/1.5 "Avenir Next",sans-serif;
  color:var(--muted);
  letter-spacing:2.1px;
  margin-top:5px
}
.nav-group-label{
  font-size:10px;
  letter-spacing:1.8px;
  color:var(--muted);
  padding:0 14px;
  margin:20px 0 8px;
  font-weight:600;
  text-transform:uppercase
}
.nav-group-label:first-of-type{
  margin-top:0
}
.nav-item{
  display:flex;
  align-items:center;
  gap:12px;
  min-height:44px;
  padding:10px 13px;
  margin:3px 0;
  color:var(--muted);
  cursor:pointer;
  border-radius:7px;
  transition:background .18s,color .18s;
  position:relative;
  font-weight:500
}
.nav-item:hover{
  background:var(--btn-hover);
  color:var(--text)
}
.nav-item.active{
  color:var(--accent);
  background:var(--accent-soft)
}
.nav-item.active::after{
  content:"";
  width:5px;
  height:5px;
  background:var(--accent);
  border-radius:50%;
  margin-left:auto
}
.nav-item.hidden{
  display:none
}
.sidebar-bottom{
  margin-top:auto;
  padding-top:36px
}
.connection{
  display:flex;
  align-items:center;
  gap:8px;
  padding:10px 12px;
  color:var(--muted);
  font-size:11px
}
.connection::before{
  content:"";
  width:6px;
  height:6px;
  border-radius:50%;
  background:var(--ok)
}
#whoami{
  padding:13px 12px 5px;
  font-size:11px;
  color:var(--muted);
  border-top:1px solid var(--line);
  overflow-wrap:anywhere
}
#ver{
  padding:2px 12px;
  font:11px/1.8 "SFMono-Regular",Consolas,monospace;
  color:var(--muted)
}
#main{
  flex:1;
  min-width:0;
  padding:0 44px 40px;
  max-width:1800px
}
#topbar{
  height:78px;
  display:flex;
  align-items:center;
  gap:16px;
  border-bottom:1px solid var(--line);
  margin-bottom:38px
}
.breadcrumb{
  display:flex;
  align-items:center;
  gap:12px;
  color:var(--muted);
  font-size:12px
}
.breadcrumb strong{
  font-weight:500;
  color:var(--text)
}
.breadcrumb .slash{
  color:var(--muted)
}
.topbar-actions{
  margin-left:auto;
  display:flex;
  gap:16px;
  align-items:center
}
.switch{
  display:inline-flex;
  gap:2px;
  padding:3px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--panel2)
}
.switch button{
  min-width:44px;
  min-height:44px;
  padding:5px 9px;
  border:0;
  background:transparent;
  border-radius:5px;
  font-size:12px;
  color:var(--muted)
}
.switch button:hover{
  background:var(--btn-hover);
  color:var(--text)
}
.switch button[aria-pressed="true"]{
  background:var(--panel);
  color:var(--accent);
  box-shadow:0 1px 3px var(--line)
}
#mobile-menu,#nav-mask{
  display:none
}
.view{
  display:none
}
.view.active{
  display:block;
  animation:arrive .22s ease-out
}
@keyframes arrive{
  from{
    opacity:.4;
    transform:translateY(5px)
  }
  to{
    opacity:1;
    transform:translateY(0)
  }
}
h2{
  font-size:28px;
  letter-spacing:-.7px;
  line-height:1.3;
  font-weight:600;
  margin-bottom:26px
}
.view-description{
  color:var(--muted);
  font-size:13px;
  margin:-14px 0 28px;
  max-width:75ch
}
h3{
  font-size:17px;
  font-weight:600;
  letter-spacing:-.2px
}
.page-heading{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:20px;
  margin-bottom:30px
}
.page-heading h2{
  margin:6px 0 10px;
  font-size:30px
}
.eyebrow{
  font-size:10px;
  letter-spacing:2.1px;
  font-weight:600;
  color:var(--muted)
}
.page-description{
  font-size:13px;
  color:var(--muted);
  max-width:65ch
}
.overview{
  display:grid;
  grid-template-columns:repeat(4,1fr);
  border:1px solid var(--line);
  border-radius:10px;
  background:var(--panel);
  margin-bottom:30px
}
.overview-item{
  padding:20px 24px;
  border-right:1px solid var(--line)
}
.overview-item:last-child{
  border:0
}
.overview-item .lbl{
  font-size:11px;
  color:var(--muted)
}
.overview-item .num{
  font-size:26px;
  font-weight:500;
  letter-spacing:-.8px;
  margin-top:6px;
  font-variant-numeric:tabular-nums
}
.overview-item .metric-note{
  font-size:10px;
  color:var(--muted);
  margin-top:2px
}
.list-panel{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:10px;
  overflow:hidden
}
.list-panel .toolbar{
  padding:20px 20px 16px;
  margin:0
}
.list-panel .pager{
  padding:14px 20px;
  margin:0;
  border-top:1px solid var(--line)
}
.toolbar{
  display:flex;
  gap:10px;
  margin-bottom:20px;
  flex-wrap:wrap;
  align-items:center
}
.spacer{
  flex:1
}
.search-field{
  position:relative;
  display:flex;
  align-items:center
}
.search-field svg{
  position:absolute;
  left:13px;
  color:var(--muted);
  width:17px;
  height:17px
}
.search-field input{
  padding-left:40px;
  width:280px;
  background:var(--subtle)
}
.table-scroll{
  width:100%;
  overflow-x:auto;
  overscroll-behavior-x:contain;
  border:1px solid var(--line);
  border-radius:9px
}
.list-panel .table-scroll{
  border:0;
  border-radius:0
}
.table-scroll:focus-visible{
  outline:2px solid var(--focus);
  outline-offset:-2px
}
table{
  width:100%;
  border-collapse:collapse;
  background:var(--panel);
  font-variant-numeric:tabular-nums
}
th,td{
  padding:17px 20px;
  text-align:left;
  border-bottom:1px solid var(--line);
  vertical-align:middle;
  font-size:12px
}
th{
  background:var(--subtle);
  color:var(--muted);
  font-weight:500;
  font-size:10px;
  letter-spacing:.08em;
  white-space:nowrap
}
tr:last-child td{
  border-bottom:0
}
tbody tr{
  transition:background .15s
}
tbody tr:hover{
  background:var(--row-hover)
}
td.actions{
  white-space:nowrap
}
td.actions button{
  font-size:11px;
  min-height:44px;
  padding:5px 10px;
  margin-right:4px;
  background:transparent
}
td.actions button:hover{
  background:var(--btn-hover)
}
.site-name{
  display:flex;
  align-items:center;
  gap:12px;
  min-width:180px
}
.site-monogram{
  height:34px;
  width:30px;
  border:1px solid var(--line);
  border-radius:6px;
  display:grid;
  place-items:center;
  color:var(--accent);
  background:var(--subtle)
}
.site-name strong{
  font-size:12px;
  font-weight:600
}
.site-name small{
  display:block;
  color:var(--muted);
  font:10px/1.8 "SFMono-Regular",Consolas,monospace
}
.site-url{
  font:11px/1.5 "SFMono-Regular",Consolas,monospace;
  white-space:nowrap
}
.date-cell{
  white-space:nowrap;
  font-size:11px;
  color:var(--muted)
}
.badge{
  display:inline-flex;
  align-items:center;
  gap:5px;
  padding:3px 8px;
  border-radius:5px;
  font-size:10px;
  border:1px solid var(--line);
  color:var(--muted);
  line-height:1.5
}
.badge.owner,.badge.on{
  background:var(--ok-soft);
  border-color:var(--ok-soft);
  color:var(--ok)
}
.badge.superadmin,.badge.maintainer{
  border-color:var(--line);
  background:var(--panel2);
  color:var(--muted)
}
.pager{
  display:flex;
  gap:8px;
  align-items:center;
  margin-top:18px;
  color:var(--muted);
  font-size:11px
}
.pager button{
  min-height:44px;
  padding:5px 11px;
  font-size:11px
}
.pager #site-page{
  min-width:46px;
  text-align:center
}
.pager-note{
  margin-right:auto
}
.workspace-note{
  display:flex;
  gap:14px;
  padding:22px 2px;
  color:var(--muted);
  font-size:12px;
  align-items:flex-start
}
.workspace-note>svg{
  margin-top:2px
}
.workspace-note b{
  display:block;
  color:var(--text);
  font-size:12px;
  font-weight:500;
  margin-bottom:4px
}
.workspace-note button{
  margin-left:auto;
  background:transparent;
  border:0;
  padding:0;
  min-height:36px;
  font-size:11px;
  color:var(--accent)
}
.cards{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:16px;
  margin-bottom:28px
}
.card{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:22px 24px
}
.card .num{
  font-size:30px;
  font-weight:500;
  margin-top:8px;
  font-variant-numeric:tabular-nums
}
.card .lbl{
  color:var(--muted);
  font-size:12px
}
#drawer-mask{
  position:fixed;
  inset:0;
  background:var(--mask);
  display:none;
  z-index:40
}
#drawer-mask.open{
  display:block
}
#drawer{
  position:fixed;
  top:0;
  right:0;
  transform:translateX(100%);
  width:560px;
  max-width:94vw;
  height:100dvh;
  background:var(--panel);
  border-left:1px solid var(--line);
  box-shadow:var(--shadow);
  z-index:50;
  transition:transform .22s ease;
  overflow-y:auto;
  padding:30px
}
#drawer.open{
  transform:translateX(0)
}
#drawer h3{
  font-size:22px;
  margin:10px 48px 10px 0;
  overflow-wrap:anywhere
}
#drawer .sub{
  color:var(--muted);
  font-size:11px;
  margin-bottom:26px;
  overflow-wrap:anywhere
}
#drawer-close{
  position:absolute;
  right:20px;
  top:22px;
  background:transparent;
  width:44px;
  padding:0
}
.section{
  border-top:1px solid var(--line);
  padding:22px 0
}
.section h4{
  font-size:12px;
  font-weight:500;
  color:var(--muted);
  margin-bottom:16px;
  letter-spacing:.05em
}
.frow{
  display:flex;
  gap:12px;
  margin-bottom:12px;
  align-items:center
}
.frow label{
  width:86px;
  flex:0 0 86px;
  color:var(--muted);
  font-size:12px
}
.frow input[type=text]{
  flex:1
}
.tags{
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  margin-bottom:12px
}
.tag{
  background:var(--panel2);
  border:1px solid var(--line);
  border-radius:6px;
  padding:3px 10px;
  font-size:12px;
  display:inline-flex;
  gap:6px;
  align-items:center
}
.tag b{
  cursor:pointer;
  color:var(--danger);
  font-weight:500;
  min-width:28px;
  min-height:32px;
  display:grid;
  place-items:center
}
.snap-row{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  padding:10px 0;
  border-bottom:1px solid var(--line);
  font-size:12px
}
.snap-row:last-child{
  border-bottom:0
}
.snap-row .ts{
  font-family:"SFMono-Regular",Consolas,monospace;
  color:var(--muted)
}
#toast{
  position:fixed;
  bottom:24px;
  left:50%;
  transform:translateX(-50%);
  background:var(--panel);
  box-shadow:var(--shadow);
  border:1px solid var(--ok);
  color:var(--text);
  border-radius:9px;
  padding:13px 22px;
  display:none;
  z-index:99;
  max-width:min(560px,90vw);
  font-size:13px
}
#toast.err{
  border-color:var(--danger);
  color:var(--danger)
}
#login-gate{
  max-width:420px;
  margin:16vh auto;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:36px
}
#login-gate h2{
  margin-bottom:12px
}
#login-gate p{
  color:var(--muted);
  font-size:13px;
  margin-bottom:22px
}
#login-gate input{
  width:100%;
  margin-bottom:16px
}
.empty{
  color:var(--muted);
  padding:52px 24px;
  text-align:center;
  font-size:13px
}
.guide{
  text-align:left;
  color:var(--text);
  padding:0;
  max-width:820px
}
.guide h3{
  font-size:17px;
  margin-bottom:10px
}
.guide p{
  color:var(--muted);
  margin-bottom:16px
}
.guide .hint{
  background:var(--panel);
  border:1px solid var(--line);
  border-left:3px solid var(--accent);
  border-radius:8px;
  padding:16px 18px;
  margin-bottom:20px;
  color:var(--text)
}
.guide-actions{
  display:flex;
  gap:12px;
  flex-wrap:wrap;
  margin-bottom:22px
}
.codeblock{
  position:relative;
  margin-bottom:24px
}
.codeblock pre{
  background:var(--code-bg);
  border:1px solid var(--line);
  border-radius:8px;
  padding:52px 18px 18px;
  font:12px/1.8 "SFMono-Regular",Consolas,monospace;
  overflow-x:auto;
  color:var(--text)
}
.codeblock .cb-copy{
  position:absolute;
  top:8px;
  right:8px;
  font-size:11px;
  padding:5px 12px;
  min-height:36px;
  color:var(--muted)
}
.codeblock .cb-copy.ok{
  color:var(--ok);
  border-color:var(--ok)
}
.guide .cb-label{
  font-size:11px;
  color:var(--muted);
  margin-bottom:8px;
  letter-spacing:.05em
}
.guide .doclink{
  font-size:13px
}
.perm-block,.form-block{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:26px;
  margin-bottom:22px
}
.perm-block h3,.form-block h3{
  font-size:16px;
  margin-bottom:8px
}
.desc{
  color:var(--muted);
  font-size:12px;
  margin-bottom:22px;
  max-width:75ch
}
.perm-block table{
  margin-top:8px
}
.lock{
  display:inline-block;
  position:relative;
  width:11px;
  height:9px;
  border:1.5px solid var(--muted);
  border-radius:2px;
  margin-top:5px;
  cursor:help
}
.lock::before{
  content:"";
  position:absolute;
  left:50%;
  top:-6px;
  width:7px;
  height:6px;
  margin-left:-4.5px;
  border:1.5px solid var(--muted);
  border-bottom:0;
  border-radius:4px 4px 0 0
}
.chks{
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  max-height:240px;
  overflow-y:auto;
  border:1px solid var(--line);
  border-radius:8px;
  padding:12px;
  background:var(--bg);
  margin-bottom:16px
}
.chks label{
  display:inline-flex;
  gap:8px;
  align-items:center;
  font-size:12px;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:6px;
  padding:8px 12px;
  cursor:pointer;
  min-height:44px
}
.chks label input{
  margin:0;
  flex:0 0 auto
}
.mine dt{
  color:var(--muted);
  font-size:11px;
  letter-spacing:.05em;
  margin-top:14px
}
.mine dd{
  margin:5px 0 0;
  overflow-wrap:anywhere
}
.form-row{
  display:flex;
  gap:14px;
  margin-bottom:18px;
  align-items:center;
  flex-wrap:wrap
}
.form-row label{
  width:140px;
  flex:0 0 140px;
  color:var(--muted);
  font-size:12px
}
.form-row input,.form-row select{
  flex:1
}
.form-row input[type=checkbox]{
  flex:0 0 auto;
  margin:0
}
.form-row .hint{
  font-size:11px;
  color:var(--muted);
  margin-left:4px
}
.form-actions{
  display:flex;
  gap:10px;
  margin-top:22px;
  flex-wrap:wrap
}
.callback-box{
  background:var(--code-bg);
  border:1px solid var(--line);
  border-radius:8px;
  padding:16px;
  margin:12px 0;
  display:flex;
  align-items:center;
  gap:12px;
  font:12px/1.6 "SFMono-Regular",Consolas,monospace;
  overflow-wrap:anywhere
}
.callback-box .cb-btn{
  flex:0 0 auto
}
.status-pill{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:4px 10px;
  border-radius:6px;
  font-size:11px;
  font-weight:500
}
.status-pill.none{
  background:var(--danger-soft);
  color:var(--danger);
  border:1px solid var(--danger-soft)
}
.status-pill.token,.status-pill.proxy{
  background:var(--accent-soft);
  color:var(--accent);
  border:1px solid var(--accent-soft)
}
.status-pill.oidc{
  background:var(--ok-soft);
  color:var(--ok);
  border:1px solid var(--ok-soft)
}
.test-result{
  margin-top:16px;
  padding:16px;
  border-radius:8px;
  border:1px solid var(--line);
  font-size:13px;
  display:none
}
.test-result.ok{
  border-color:var(--ok);
  background:var(--ok-soft);
  color:var(--ok)
}
.test-result.fail{
  border-color:var(--danger);
  background:var(--danger-soft);
  color:var(--danger)
}
.test-result .endpoint{
  font-family:"SFMono-Regular",Consolas,monospace;
  font-size:12px;
  color:var(--muted);
  margin-top:6px
}
.rule-row{
  display:flex;
  align-items:flex-start;
  gap:14px;
  padding:16px 0;
  border-bottom:1px solid var(--line)
}
.rule-row:last-child{
  border:0
}
.rule-row .rule-name{
  flex:1;
  font-size:13px;
  min-width:0;
  overflow-wrap:anywhere
}
.rule-row .rule-name b{
  display:block;
  margin-bottom:4px;
  font-weight:500
}
.rule-row .rule-name .meta{
  color:var(--muted);
  font-size:11px
}
.rule-row .rule-actions{
  flex:0 0 auto;
  display:flex;
  gap:6px
}
.rule-row .lock{
  flex:0 0 auto;
  margin-top:6px
}
.src-badge,.scope-badge{
  font-size:10px;
  padding:3px 7px;
  border-radius:5px;
  border:1px solid var(--line);
  color:var(--muted);
  letter-spacing:.02em
}
.src-badge.file{
  color:var(--accent)
}
.src-badge.db,.scope-badge.restart{
  color:var(--warn)
}
.scope-badge.hot{
  color:var(--ok)
}
.warn-box{
  background:var(--danger-soft);
  border:1px solid var(--danger);
  border-radius:8px;
  padding:16px 18px;
  margin-bottom:18px;
  font-size:13px;
  color:var(--danger)
}
.warn-box b{
  display:block;
  margin-bottom:6px
}
.kv-row{display:flex;gap:12px;padding:8px 0;font-size:13px;border-bottom:1px solid var(--line)}
.kv-row:last-child{border-bottom:none}
.kv-k{color:var(--muted);min-width:120px;flex-shrink:0}
.kv-v{color:var(--text);overflow-wrap:anywhere}
.migrate-cmd-hint{margin-top:12px;padding:12px;background:var(--code-bg);border-radius:8px;font-family:var(--mono);font-size:13px;color:var(--text)}
.migrate-cmd-hint code{display:block;margin-top:6px;color:var(--text)}
.degraded-notice{
  background:var(--panel);
  border:1px solid var(--line);
  border-left:3px solid var(--warn);
  border-radius:8px;
  padding:16px 18px;
  margin-bottom:20px;
  color:var(--text);
  font-size:13px
}
.degraded-notice b{
  color:var(--warn)
}
#publish-guide{
  margin:auto;
  width:600px;
  max-width:calc(100vw - 32px);
  max-height:85dvh;
  overflow-y:auto;
  background:var(--panel);
  color:var(--text);
  border:1px solid var(--line);
  border-radius:14px;
  padding:32px;
  box-shadow:var(--shadow)
}
#publish-guide::backdrop{
  background:var(--mask)
}
.dialog-heading{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  margin-bottom:18px
}
.dialog-heading button{
  width:44px;
  padding:0
}
.dialog-description{
  color:var(--muted);
  font-size:13px;
  margin-bottom:20px
}
.step-label{
  color:var(--muted);
  font-size:11px;
  margin:20px 0 8px
}
#publish-command{
  display:block;
  background:var(--code-bg);
  border:1px solid var(--line);
  border-radius:8px;
  padding:18px;
  overflow-x:auto;
  font:12px/1.8 "SFMono-Regular",Consolas,monospace;
  white-space:pre-wrap;
  overflow-wrap:anywhere
}
.dialog-actions{
  display:flex;
  justify-content:flex-end;
  gap:12px;
  margin-top:22px
}
@media(min-width:1600px){
  #main{
    padding-left:60px;
    padding-right:60px
  }
}
@media(max-width:1100px){
  #sidebar{
    width:204px;
    flex-basis:204px;
    padding-left:12px;
    padding-right:12px
  }
  #main{
    padding-left:26px;
    padding-right:26px
  }
  .overview-item{
    padding:18px
  }
  th,td{
    padding:15px
  }
  .topbar-actions{
    gap:10px
  }
}
.degraded-notice{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:8px;padding:14px 16px;margin-bottom:16px;color:var(--text);font-size:13px}
.degraded-notice b{color:var(--warn)}
@media(max-width:760px){
  body{
    font-size:16px
  }
  #sidebar{
    position:fixed;
    left:0;
    top:0;
    z-index:30;
    width:260px;
    transform:translateX(-100%);
    transition:transform .2s;
    box-shadow:var(--shadow)
  }
  #sidebar.mobile-open{
    transform:translateX(0)
  }
  #nav-mask.open{
    display:block;
    position:fixed;
    inset:0;
    background:var(--mask);
    z-index:20;
    border:0;
    border-radius:0;
    width:100%;
    height:100%
  }
  #main{
    padding:0 20px 30px;
    width:100%
  }
  #topbar{
    height:72px;
    margin-bottom:28px;
    gap:10px
  }
  .breadcrumb>span:first-child,.breadcrumb .slash{
    display:none
  }
  .breadcrumb{
    font-size:12px
  }
  .topbar-actions{
    gap:8px
  }
  .switch button{
    min-height:44px;
    min-width:44px;
    padding:5px 7px
  }
  #mobile-menu{
    display:flex;
    width:44px;
    padding:0;
    background:transparent;
    border:0;
    flex:0 0 44px
  }
  .page-heading{
    align-items:flex-start;
    gap:12px;
    margin-bottom:24px
  }
  .page-heading h2{
    font-size:26px
  }
  .page-description{
    font-size:12px
  }
  .page-heading>button{
    font-size:12px;
    padding:9px 12px;
    margin-top:20px
  }
  .eyebrow{
    font-size:9px
  }
  .overview{
    grid-template-columns:repeat(2,1fr);
    margin-bottom:24px
  }
  .overview-item{
    padding:16px 18px
  }
  .overview-item:nth-child(2){
    border-right:0
  }
  .overview-item:nth-child(-n+2){
    border-bottom:1px solid var(--line)
  }
  .overview-item .num{
    font-size:24px
  }
  .overview-item .metric-note{
    display:none
  }
  .toolbar .spacer{
    display:none
  }
  .search-field{
    flex:1;
    min-width:150px
  }
  .search-field input{
    width:100%
  }
  input,textarea,select{
    font-size:16px
  }
  .list-panel .toolbar{
    padding:16px;
    gap:8px
  }
  .table-scroll table{
    min-width:680px
  }
  .list-panel .pager{
    padding:12px 16px
  }
  .pager-note{
    display:none
  }
  .pager{
    justify-content:flex-end
  }
  .workspace-note{
    font-size:12px;
    flex-wrap:wrap
  }
  .workspace-note button{
    margin-left:32px
  }
  .form-row{
    flex-direction:column;
    align-items:stretch;
    gap:8px
  }
  .form-row label{
    width:auto;
    flex:auto
  }
  .form-row input[type=checkbox]{
    align-self:flex-start
  }
  .form-block,.perm-block{
    padding:20px
  }
  .frow{
    flex-wrap:wrap
  }
  .frow input{
    max-width:100%
  }
  .frow label{
    flex:0 0 100%;
    width:auto
  }
  .callback-box{
    flex-wrap:wrap
  }
  #drawer{
    padding:24px;
    max-width:100vw
  }
  .dialog-heading h3{
    font-size:19px
  }
  #publish-guide{
    padding:24px
  }
  .cards{
    grid-template-columns:repeat(2,1fr)
  }
}
@media(max-width:480px){
  .breadcrumb{
    display:none
  }
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{
    animation:none!important;
    transition:none!important;
    scroll-behavior:auto!important
  }
}

.settings-notice{padding:14px 18px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--muted);font-size:12px;margin-bottom:24px}
#settings-feedback{padding:14px 18px;border:1px solid var(--ok);border-radius:8px;background:var(--ok-soft);color:var(--ok);font-size:13px;margin-bottom:22px}
#settings-feedback.restart{border-color:var(--warn);color:var(--warn);background:var(--warn-soft)}
.settings-group{border:1px solid var(--line);border-radius:10px;background:var(--panel);margin-bottom:24px;overflow:hidden}
.settings-group h3{padding:17px 22px;margin:0;background:var(--subtle);border-bottom:1px solid var(--line);font-size:13px;color:var(--text)}
.setting-row{display:flex;align-items:center;flex-wrap:wrap;padding:20px 22px;margin:0;gap:18px;border-bottom:1px solid var(--line);font-size:12px}
.setting-row:last-child{border-bottom:0}
.setting-row .s-label{min-width:220px;flex:1 1 260px}
.setting-name{font-weight:500;color:var(--text)}
.setting-key{font:10px/1.8 "SFMono-Regular",Consolas,monospace;color:var(--muted);margin:3px 0 5px;overflow-wrap:anywhere}
.setting-description{font-size:11px;color:var(--muted);max-width:65ch;line-height:1.7}
.setting-row .s-value{font:11px/1.7 "SFMono-Regular",Consolas,monospace;color:var(--muted);max-width:240px;min-width:60px;overflow-wrap:anywhere;white-space:pre-wrap}
.setting-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.setting-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.setting-actions button{min-height:44px;font-size:12px;padding:8px 12px}
.setting-editor{flex:0 0 100%;min-width:0;border-top:1px dashed var(--line);padding-top:18px}
.setting-editor[hidden]{display:none}
.setting-editor input,.setting-editor select,.setting-editor textarea{width:100%;max-width:600px}
.setting-editor textarea{min-height:120px;font-family:"SFMono-Regular",Consolas,monospace}
.setting-editor-label{display:block;font-size:12px;margin-bottom:8px;color:var(--muted)}
.setting-editor-controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}
.setting-error{color:var(--danger);font-size:12px;margin-top:10px;overflow-wrap:anywhere}
.setting-edit-note{font-size:11px;color:var(--muted);margin-top:10px}
@media(max-width:760px){.setting-row{padding:18px;gap:14px}.setting-row .s-label{flex:0 0 100%;min-width:0}.setting-row .s-value{flex:1;max-width:100%}.setting-description{font-size:12px}.setting-editor input,.setting-editor select{font-size:16px}.settings-group h3{padding:16px 18px}}
</style>
</head>
<body>
<a class="skip-link" href="#main" data-i18n="workspace.skip"></a>
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
  <aside id="sidebar" aria-label="Workspace navigation">
    <div id="logo"><span class="brand-mark">__GOLIVE_ROCKET__</span><div>golive<small>WORKSPACE</small></div></div>
    <nav aria-label="Main navigation">
      <p class="nav-group-label" data-i18n="nav.workspace"></p>
      <div class="nav-item active" data-view="sites" role="button" tabindex="0" aria-controls="view-sites"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 9v12"/></svg><span data-i18n="nav.sites"></span></div>
      <div class="nav-item hidden" data-view="data" id="nav-data" role="button" tabindex="0" aria-controls="view-data"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7"/></svg><span data-i18n="nav.data"></span></div>
      <div class="nav-item hidden" data-view="stats" id="nav-stats" role="button" tabindex="0" aria-controls="view-stats"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V4M4 20h17M9 16v-4M14 16V8M19 16V5"/></svg><span data-i18n="nav.stats"></span></div>
      <div class="nav-item hidden" data-view="audit" id="nav-audit" role="button" tabindex="0" aria-controls="view-audit"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v3H9zM9 11h6M9 15h6"/></svg><span data-i18n="nav.audit"></span></div>
      <p class="nav-group-label" data-i18n="nav.system"></p>
      <div class="nav-item hidden" data-view="perms" id="nav-perms" role="button" tabindex="0" aria-controls="view-perms"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6zM9 12l2 2 4-4"/></svg><span data-i18n="nav.perms"></span></div>
      <div class="nav-item hidden" data-view="identity" id="nav-identity" role="button" tabindex="0" aria-controls="view-identity"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></svg><span data-i18n="nav.identity"></span></div>
      <div class="nav-item hidden" data-view="databackend" id="nav-databackend" role="button" tabindex="0" aria-controls="view-databackend"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M15 6.5h3M15 17.5h3"/></svg><span data-i18n="nav.databackend"></span></div>
      <div class="nav-item hidden" data-view="security" id="nav-security" role="button" tabindex="0" aria-controls="view-security"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m9 12 2 2 4-4"/></svg><span data-i18n="nav.security"></span></div>
      <div class="nav-item hidden" data-view="settings" id="nav-settings" role="button" tabindex="0" aria-controls="view-settings"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></svg><span data-i18n="nav.settings"></span></div>
    </nav>
    <div class="sidebar-bottom"><div class="connection" data-i18n="workspace.connected"></div><div id="whoami"></div><div id="ver"></div></div>
  </aside>
  <button id="nav-mask" tabindex="-1" aria-label="Close navigation"></button>
  <main id="main" tabindex="-1">
    <header id="topbar">
      <button id="mobile-menu" type="button" aria-label="Open navigation" aria-controls="sidebar" aria-expanded="false"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>
      <div class="breadcrumb"><span data-i18n="workspace.name"></span><span class="slash">/</span><strong id="current-view-label" data-i18n="nav.sites"></strong></div>
      <div class="topbar-actions">
        <div class="switch" id="theme-switch" role="group" aria-label="Theme">
          <button data-theme-set="system" type="button" title="System" aria-label="System"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg></button>
          <button data-theme-set="light" type="button" title="Light" aria-label="Light"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/></svg></button>
          <button data-theme-set="dark" type="button" title="Dark" aria-label="Dark"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z"/></svg></button>
        </div>
        <div class="switch" id="lang-switch" role="group" aria-label="Language">
          <button data-lang="en" type="button" aria-label="English">EN</button>
          <button data-lang="zh" type="button" aria-label="中文">中</button>
        </div>
      </div>
    </header>

    <!-- sites -->
    <div class="view active" id="view-sites">
      <div class="page-heading">
        <div><p class="eyebrow">PUBLISH · MANAGE · SHARE</p><h2 data-i18n="sites.title"></h2><p class="page-description" data-i18n="sites.description"></p></div>
        <button class="primary" id="publish-open" type="button"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span data-i18n="sites.publish"></span></button>
      </div>
      <div class="overview" id="site-overview" style="display:none" aria-label="Workspace overview">
        <div class="overview-item"><div class="lbl" data-i18n="stats.sites"></div><div class="num" id="overview-total_sites">—</div><div class="metric-note" data-i18n="metric.sites"></div></div>
        <div class="overview-item"><div class="lbl" data-i18n="stats.bytes"></div><div class="num" id="overview-total_bytes">—</div><div class="metric-note" data-i18n="metric.bytes"></div></div>
        <div class="overview-item"><div class="lbl" data-i18n="stats.recent"></div><div class="num" id="overview-updated_last_7d">—</div><div class="metric-note" data-i18n="metric.recent"></div></div>
        <div class="overview-item"><div class="lbl" data-i18n="stats.editable"></div><div class="num" id="overview-editable_sites">—</div><div class="metric-note" data-i18n="metric.editable"></div></div>
      </div>
      <section class="list-panel" aria-label="Sites">
      <div class="toolbar">
        <label class="search-field" for="site-q"><span class="sr-only" data-i18n="sites.search"></span><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><input type="search" id="site-q" data-i18n-ph="sites.search"></label>
        <button id="site-search" data-i18n="btn.search"></button>
        <button id="site-clear" style="display:none" data-i18n="sites.clear"></button>
        <div class="spacer"></div>
        <span id="site-count" style="color:var(--muted);font-size:12px" aria-live="polite"></span>
      </div>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
        <thead><tr>
          <th data-i18n="th.name"></th><th data-i18n="th.slug"></th>
          <th data-i18n="th.owner"></th><th data-i18n="th.role"></th>
          <th data-i18n="th.size"></th><th data-i18n="th.updated"></th>
          <th data-i18n="th.actions"></th>
        </tr></thead>
        <tbody id="site-rows"></tbody>
      </table></div>
      <div class="pager">
        <span class="pager-note" data-i18n="sites.pager.note"></span>
        <button id="site-prev" data-i18n="btn.prev"></button>
        <span id="site-page"></span>
        <button id="site-next" data-i18n="btn.next"></button>
      </div>
      </section>
      <div class="workspace-note"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/></svg><div><b data-i18n="sites.note.title"></b><span data-i18n="sites.note.body"></span></div><button id="publish-help" type="button"><span data-i18n="sites.guide"></span><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></button></div>
    </div>

    <!-- data management (M6) -->
    <div class="view" id="view-data">
      <h2 data-i18n="data.title"></h2>
      <p class="view-description" data-i18n="sites.description.data"></p>
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
        <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
          <thead><tr>
            <th data-i18n="th.id"></th><th data-i18n="th.name"></th>
            <th data-i18n="th.summary"></th><th data-i18n="th.updated"></th>
            <th data-i18n="th.actions"></th>
          </tr></thead>
          <tbody id="data-rows"></tbody>
        </table></div>
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
      <p class="view-description" data-i18n="sites.description.perms"></p>
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
          <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
            <thead><tr>
              <th data-i18n="th.email"></th><th data-i18n="th.source"></th>
              <th data-i18n="th.actions"></th>
            </tr></thead>
            <tbody id="perm-admin-rows"></tbody>
          </table></div>
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
          <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
            <thead><tr>
              <th data-i18n="th.name"></th><th data-i18n="th.slug"></th>
              <th data-i18n="th.owner"></th><th data-i18n="th.maintainers"></th>
            </tr></thead>
            <tbody id="perm-site-rows"></tbody>
          </table></div>
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
      <p class="view-description" data-i18n="sites.description.stats"></p>
      <div class="cards" id="stat-cards"></div>
      <h2 style="font-size:15px" data-i18n="stats.top"></h2>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
        <thead><tr><th>#</th><th data-i18n="th.slug"></th>
          <th data-i18n="th.name"></th><th data-i18n="th.size"></th></tr></thead>
        <tbody id="stat-top"></tbody>
      </table></div>
    </div>

    <!-- audit -->
    <div class="view" id="view-audit">
      <h2 data-i18n="audit.title"></h2>
      <p class="view-description" data-i18n="sites.description.audit"></p>
      <div class="toolbar">
        <input type="text" id="audit-slug" data-i18n-ph="audit.byslug"
               style="width:170px">
        <input type="text" id="audit-action" data-i18n-ph="audit.byaction"
               style="width:170px">
        <button id="audit-search" data-i18n="btn.filter"></button>
      </div>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
        <thead><tr><th data-i18n="th.time"></th><th data-i18n="th.who"></th>
          <th data-i18n="th.action"></th><th data-i18n="th.slug"></th>
          <th data-i18n="th.detail"></th></tr></thead>
        <tbody id="audit-rows"></tbody>
      </table></div>
      <div class="pager">
        <button id="audit-prev" data-i18n="btn.prev"></button>
        <span id="audit-page"></span>
        <button id="audit-next" data-i18n="btn.next"></button>
      </div>
    </div>

    <!-- identity / auth (v0.8.0) -->
    <div class="view" id="view-identity">
      <h2 data-i18n="identity.title"></h2>
      <p class="view-description" data-i18n="sites.description.identity"></p>
      <div id="identity-degraded" class="degraded-notice" style="display:none">
        <b>!</b> <span data-i18n="identity.degraded"></span>
      </div>
      <div id="identity-main">
        <div class="form-block">
          <h3 data-i18n="identity.current"></h3>
          <div class="desc" data-i18n="identity.current.desc"></div>
          <div class="form-row">
            <label data-i18n="identity.method"></label>
            <span id="id-method" class="status-pill none">none</span>
          </div>
        </div>

        <div class="form-block">
          <h3 data-i18n="identity.oidc.title"></h3>
          <div class="desc" data-i18n="identity.oidc.desc"></div>
          <div class="form-row">
            <label data-i18n="identity.oidc.preset"></label>
            <select id="idp-preset">
              <option value="">—</option>
              <option value="google">Google</option>
              <option value="auth0">Auth0</option>
              <option value="okta">Okta</option>
              <option value="azure">Azure AD</option>
              <option value="keycloak">Keycloak</option>
              <option value="authentik">Authentik</option>
              <option value="custom" data-i18n="identity.oidc.custom"></option>
            </select>
          </div>
          <div class="form-row">
            <label data-i18n="identity.oidc.issuer"></label>
            <input type="text" id="oidc-issuer" placeholder="https://idp.example.com">
          </div>
          <div class="form-row">
            <label data-i18n="identity.oidc.clientid"></label>
            <input type="text" id="oidc-client-id" placeholder="client_id">
          </div>
          <div class="form-row">
            <label data-i18n="identity.oidc.clientsecret"></label>
            <input type="password" id="oidc-client-secret"
                   data-i18n-ph="identity.oidc.secret.ph">
          </div>
          <div class="form-row">
            <label data-i18n="identity.oidc.domain"></label>
            <input type="text" id="oidc-domain"
                   placeholder="your-tenant.auth0.com">
          </div>
          <div class="form-row">
            <label data-i18n="identity.oidc.scopes"></label>
            <input type="text" id="oidc-scopes" value="openid email profile">
          </div>
          <div class="form-actions">
            <button class="primary" id="oidc-test"
                    data-i18n="identity.oidc.test"></button>
            <button id="oidc-save" data-i18n="btn.save"></button>
          </div>
          <div class="test-result" id="oidc-test-result"></div>
        </div>

        <div class="form-block">
          <h3 data-i18n="identity.callback.title"></h3>
          <div class="desc" data-i18n="identity.callback.desc"></div>
          <div class="callback-box">
            <span id="oidc-callback-url">https://&lt;your-domain&gt;/auth/callback</span>
            <button class="cb-btn" id="oidc-callback-copy"
                    data-i18n="btn.copy"></button>
          </div>
          <div class="form-actions">
            <button id="oidc-agent-copy"
                    data-i18n="identity.oidc.copyagent"></button>
          </div>
        </div>

        <div class="form-block">
          <h3 data-i18n="identity.proxy.title"></h3>
          <div class="desc" data-i18n="identity.proxy.desc"></div>
          <div class="form-row">
            <label data-i18n="identity.proxy.header"></label>
            <input type="text" id="proxy-header" placeholder="X-Forwarded-Email">
          </div>
          <div class="form-row">
            <label data-i18n="identity.proxy.ips"></label>
            <input type="text" id="proxy-ips"
                   placeholder="10.0.0.0/8, 192.168.1.0/24">
          </div>
          <div class="form-actions">
            <button id="proxy-save" data-i18n="btn.save"></button>
          </div>
        </div>
      </div>
    </div>

    <!-- data backend (v0.8.0) -->
    <div class="view" id="view-databackend">
      <h2 data-i18n="databackend.title"></h2>
      <p class="view-description" data-i18n="sites.description.databackend"></p>
      <div id="databackend-degraded" class="degraded-notice" style="display:none">
        <b>!</b> <span data-i18n="databackend.degraded"></span>
      </div>
      <div id="databackend-main">
        <div class="form-block">
          <h3 data-i18n="databackend.current"></h3>
          <div class="form-row">
            <label data-i18n="databackend.type"></label>
            <span id="db-type" class="status-pill none">none</span>
          </div>
          <div class="form-row" id="db-path-row">
            <label data-i18n="databackend.location"></label>
            <span id="db-location" class="s-value">—</span>
          </div>
          <div class="form-row" id="db-tables-row">
            <label data-i18n="databackend.tables"></label>
            <span id="db-tables" class="s-value">—</span>
          </div>
          <div class="form-row" id="db-rows-row">
            <label data-i18n="databackend.rows"></label>
            <span id="db-rows" class="s-value">—</span>
          </div>
        </div>

        <div class="form-block">
          <h3 data-i18n="databackend.switch.title"></h3>
          <div class="warn-box" id="db-migrate-warn">
            <b data-i18n="databackend.migrate.warn.title"></b>
            <span data-i18n="databackend.migrate.warn.body"></span>
            <div class="migrate-cmd-hint">
              <span data-i18n="databackend.migrate.hint"></span>
              <code id="migrate-cmd-preview"></code>
            </div>
          </div>
          <div class="form-row">
            <label data-i18n="databackend.newtype"></label>
            <select id="db-new-type">
              <option value="sqlite">sqlite</option>
              <option value="postgres">postgres</option>
              <option value="mysql">mysql</option>
              <option value="supabase">supabase</option>
              <option value="none">none</option>
            </select>
          </div>
          <div id="db-supabase-opts" style="display:none">
            <div class="form-row">
              <label data-i18n="databackend.sb.url"></label>
              <input type="text" id="db-sb-url"
                     placeholder="https://YOUR-PROJECT.supabase.co">
            </div>
            <div class="form-row">
              <label data-i18n="databackend.sb.key"></label>
              <input type="password" id="db-sb-key"
                     data-i18n-ph="databackend.sb.key.ph">
            </div>
          </div>
          <div class="form-actions">
            <button class="primary" id="db-test"
                    data-i18n="databackend.test"></button>
            <button id="db-switch" data-i18n="databackend.switch"></button>
          </div>
          <div class="test-result" id="db-test-result" role="status" aria-live="polite" aria-atomic="true"></div>
          <div style="margin-top:10px;font-size:12px;color:var(--muted)"
               data-i18n="databackend.restart.hint"></div>
        </div>
      </div>
    </div>

    <!-- security (v0.8.0) -->
    <div class="view" id="view-security">
      <h2 data-i18n="security.title"></h2>
      <p class="view-description" data-i18n="sites.description.security"></p>
      <div id="security-degraded" class="degraded-notice" style="display:none">
        <b>!</b> <span data-i18n="security.degraded"></span>
      </div>
      <div id="security-main">
        <div class="form-block">
          <h3 data-i18n="security.layers"></h3>
          <div class="form-row">
            <label data-i18n="security.layer.keyword"></label>
            <span id="sec-keyword-status" class="status-pill on">ON</span>
          </div>
          <div class="form-row">
            <label data-i18n="security.layer.regex"></label>
            <span id="sec-regex-status" class="status-pill on">ON</span>
          </div>
          <div class="form-row">
            <label data-i18n="security.layer.ai"></label>
            <span id="sec-ai-status" class="status-pill none">OFF</span>
          </div>
        </div>

        <div class="form-block">
          <h3 data-i18n="security.rules.title"></h3>
          <div class="desc" data-i18n="security.rules.desc"></div>
          <div id="sec-rules-list"></div>
          <div class="form-row" style="margin-top:12px">
            <label data-i18n="security.rules.add.type"></label>
            <select id="sec-new-type">
              <option value="keyword">keyword</option>
              <option value="regex">regex</option>
            </select>
          </div>
          <div class="form-row">
            <label data-i18n="security.rules.add.name"></label>
            <input type="text" id="sec-new-name" placeholder="rule name">
          </div>
          <div class="form-row">
            <label data-i18n="security.rules.add.pattern"></label>
            <input type="text" id="sec-new-pattern" placeholder="keyword or regex">
          </div>
          <div class="form-row">
            <label data-i18n="security.rules.add.strength"></label>
            <select id="sec-new-strength">
              <option value="weak" data-i18n="security.strength.weak"></option>
              <option value="strong" data-i18n="security.strength.strong"></option>
            </select>
          </div>
          <div class="form-actions">
            <button class="primary" id="sec-rule-add"
                    data-i18n="btn.add"></button>
          </div>
        </div>

        <div class="form-block">
          <h3 data-i18n="security.test.title"></h3>
          <div class="desc" data-i18n="security.test.desc"></div>
          <textarea id="sec-test-input" rows="4"
            style="width:100%;font:13px/1.5 monospace;background:var(--bg);
            color:var(--text);border:1px solid var(--line);border-radius:6px;
            padding:10px;resize:vertical"
            data-i18n-ph="security.test.ph"></textarea>
          <div class="form-actions">
            <button class="primary" id="sec-test-run"
                    data-i18n="security.test.run"></button>
          </div>
          <div class="test-result" id="sec-test-result"></div>
        </div>

        <div class="form-block">
          <h3 data-i18n="security.ai.title"></h3>
          <div class="desc" data-i18n="security.ai.desc"></div>
          <div class="form-row">
            <label data-i18n="security.ai.baseurl"></label>
            <input type="text" id="ai-base-url"
                   placeholder="https://api.openai.com/v1">
          </div>
          <div class="form-row">
            <label data-i18n="security.ai.model"></label>
            <input type="text" id="ai-model" placeholder="gpt-4o-mini">
          </div>
          <div class="form-row">
            <label data-i18n="security.ai.apikey"></label>
            <input type="password" id="ai-api-key"
                   data-i18n-ph="security.ai.key.ph">
          </div>
          <div class="form-row">
            <label data-i18n="security.ai.strict"></label>
            <input type="checkbox" id="ai-strict-mode">
          </div>
          <div class="form-actions">
            <button class="primary" id="ai-test"
                    data-i18n="security.ai.test"></button>
            <button id="ai-save" data-i18n="btn.save"></button>
          </div>
          <div class="test-result" id="ai-test-result"></div>
        </div>

        <div class="form-block">
          <h3 data-i18n="security.blocks"></h3>
          <div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>
            <thead><tr>
              <th data-i18n="th.time"></th>
              <th data-i18n="th.who"></th>
              <th data-i18n="security.rules.rule"></th>
            </tr></thead>
            <tbody id="sec-blocks-list"></tbody>
          </table></div>
        </div>
      </div>
    </div>

    <!-- global settings (v0.8.0) -->
    <div class="view" id="view-settings">
      <h2 data-i18n="settings.title"></h2>
      <p class="view-description" data-i18n="sites.description.settings"></p>
      <div id="settings-degraded" class="degraded-notice" style="display:none">
        <b>!</b> <span data-i18n="settings.degraded"></span>
      </div>
      <div id="settings-main">
        <div class="settings-notice" data-i18n="settings.help"></div>
        <div id="settings-feedback" role="status" aria-live="polite" hidden></div>
        <div id="settings-groups"></div>
      </div>
    </div>
  </main>
</div>

<!-- drawer -->
<div id="drawer-mask"></div>
<div id="drawer" role="dialog" aria-modal="true" aria-labelledby="d-title" tabindex="-1" inert>
  <button id="drawer-close" type="button" aria-label="Close details"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
  <p class="eyebrow" data-i18n="sites.detail"></p>
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
    <h4 data-i18n="d.manifest"></h4>
    <div id="d-manifest"></div>
  </div>

  <div class="section">
    <h4 data-i18n="d.scans"></h4>
    <div id="d-scans"></div>
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
<div id="dm" role="dialog" aria-modal="true" aria-labelledby="dm-title" tabindex="-1" style="position:fixed;top:8vh;left:50%;transform:translateX(-50%);
  width:640px;max-width:94vw;max-height:82vh;overflow-y:auto;
  background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:22px 24px;display:none;z-index:61">
  <h3 id="dm-title" style="font-size:16px;margin-bottom:12px"></h3>
  <div class="frow" id="dm-model-row"><label>model</label>
    <input type="text" id="dm-model" maxlength="200" style="flex:1"></div>
  <div class="frow"><label data-i18n="d.name"></label>
    <input type="text" id="dm-name" maxlength="200" style="flex:1"></div>
  <label for="dm-json" class="sr-only" data-i18n="data.content"></label>
  <textarea id="dm-json" spellcheck="false"
    style="width:100%;height:300px;font:12px/1.6 ui-monospace,monospace;
    background:var(--bg);color:var(--text);border:1px solid var(--line);
    border-radius:6px;padding:10px;resize:vertical"></textarea>
  <div id="dm-err" role="alert" style="color:var(--danger);font-size:12px;
    margin-top:6px;display:none"></div>
  <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">
    <button id="dm-cancel" data-i18n="btn.cancel"></button>
    <button class="primary" id="dm-save" style="display:none"
            data-i18n="btn.save"></button>
  </div>
</div>

<dialog id="publish-guide" aria-labelledby="publish-title">
  <div class="dialog-heading"><h3 id="publish-title" data-i18n="publish.title"></h3><button id="publish-close" type="button" aria-label="Close publishing guide"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>
  <p class="dialog-description" data-i18n="publish.description"></p>
  <p class="step-label" data-i18n="publish.step"></p>
  <code id="publish-command">golive publish ./index.html --name "My site" --slug my-site</code>
  <p class="step-label" data-i18n="publish.after"></p>
  <div class="dialog-actions"><button id="publish-copy" type="button" data-i18n="publish.copy"></button><button id="publish-done" class="primary" type="button" data-i18n="publish.done"></button></div>
</dialog>
<div id="toast" role="status" aria-live="polite" aria-atomic="true"></div>

<script>
(function(){
"use strict";
var BOOT = window.GOLIVE_BOOT || {};
var TOKEN_KEY = "golive_admin_token";
var THEME_KEY = "golive_admin_theme";
var LANG_KEY = "golive_admin_lang";
var siteRequest = 0;
var overview = null;
var lastActionButton = null;
var overlayReturnFocus = null;
var overlayId = null;
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
  "dbcheck.admin_unauthorized": "The admin session is no longer authenticated. Sign in again, then retry.",
  "dbcheck.admin_forbidden": "Administrator privileges are required to test backend connections.",
  "dbcheck.endpoint_unavailable": "The local server does not provide the diagnostic endpoint. Check the running server version.",
  "dbcheck.running": "Checking…",
  "dbcheck.configuration": "Complete the connection configuration",
  "dbcheck.failed": "Connection check failed",
  "dbcheck.sql_ok": "Database read/write check passed.",
  "dbcheck.sql_note": "The probe row was rolled back. Application data was preserved.",
  "dbcheck.sql_config_required": "Configure GOLIVE_PG_DSN (PostgreSQL) or GOLIVE_MYSQL_DSN (MySQL) in the server environment and restart. No connection was attempted.",
  "dbcheck.sql_driver_missing": "Install html-golive[postgres] or html-golive[mysql] in the server environment.",
  "dbcheck.sql_config_invalid": "Check the server-side DSN format, table name and TLS options.",
  "dbcheck.sql_auth_failed": "Database authentication failed. Check the server-side user and password.",
  "dbcheck.sql_permission_denied": "Database permissions are insufficient. Check table creation and read/write privileges.",
  "dbcheck.sql_connection_failed": "Cannot connect to the database. Check the server host, port, database name, network and TLS settings.",
  "dbcheck.sql_probe_failed": "The read/write probe failed. Check the configured table schema and permissions.",
  "dbcheck.sqlite_ok": "SQLite read/write and integrity checks passed.",
  "dbcheck.sqlite_note": "Probe writes were rolled back; existing application data was not changed.",
  "dbcheck.supabase_ok": "The Supabase Data API responded successfully.",
  "dbcheck.supabase_note": "This checks Data API reachability and visible schema metadata, not table write permissions or RLS policies.",
  "dbcheck.required": "Provide {fields}. No remote connection test has been started.",
  "dbcheck.key": "API key",
  "dbcheck.location": "Database location",
  "dbcheck.latency": "Elapsed time",
  "dbcheck.http": "HTTP status",
  "dbcheck.backend_disabled": "The data layer is disabled; there is no connection to test.",
  "dbcheck.sqlite_locked": "SQLite is busy or locked. Wait for other writes to finish, then retry.",
  "dbcheck.sqlite_readonly": "SQLite is read-only. Check write permissions on both the file and its parent directory.",
  "dbcheck.sqlite_corrupt": "The database file is invalid or failed the integrity check. Back up and inspect or restore it.",
  "dbcheck.sqlite_open_failed": "The database file cannot be opened. Check that its parent directory exists and is accessible to the server.",
  "dbcheck.sqlite_io_error": "SQLite read/write check failed. Check local disk space, filesystem health and permissions.",
  "dbcheck.supabase_url_invalid": "Enter the project root URL (http/https), without credentials, query parameters or /rest/v1. No remote request was made.",
  "dbcheck.supabase_url_placeholder": "Replace the example URL with your actual Supabase project URL. No remote request was made.",
  "dbcheck.supabase_key_invalid": "The API key contains spaces or newlines. Paste the complete key without whitespace. No remote request was made.",
  "dbcheck.supabase_unauthorized": "Supabase rejected the API key. Check that it is active and belongs to this project.",
  "dbcheck.supabase_forbidden": "The Data API denied access. Check schema exposure and the API role permissions.",
  "dbcheck.supabase_not_found": "The Data API endpoint was not found. Check the project URL and whether the Data API is enabled.",
  "dbcheck.supabase_rate_limited": "Supabase rate limited the request. Wait before retrying.",
  "dbcheck.supabase_redirect": "The URL returned a redirect. Use the final project root URL; the key is not forwarded through redirects.",
  "dbcheck.supabase_unavailable": "The endpoint responded but the service is unavailable. Check project status and gateway health.",
  "dbcheck.supabase_http_error": "The Data API returned an unexpected HTTP status. Check the project URL and API configuration.",
  "dbcheck.supabase_invalid_response": "The endpoint did not return a Data API schema document. The URL may point to a dashboard or login page.",
  "dbcheck.supabase_tls_error": "TLS certificate verification failed. Check the hostname, certificate and trusted CA configuration.",
  "dbcheck.supabase_timeout": "No response was received within 15 seconds. Check the network and whether the project is paused or unavailable.",
  "dbcheck.supabase_network_error": "The server could not reach the endpoint. Check DNS, network, proxy and firewall. This does not establish that the key is invalid.",
  "dbcheck.supabase_request_error": "The request could not be completed. Check the project URL, key format and server network.",
  "dbcheck.backend_unsupported": "Connection testing is not supported for this backend. Select SQLite or Supabase.",
  "dbcheck.backend_internal_error": "An internal diagnostic error prevented the test from completing. Retry or inspect server logs.",
  "dbcheck.request_failed": "The diagnostic request did not complete. Check the local service and retry.",
  "settings.description.server.host": "Bind address for the HTTP server",
  "settings.description.server.port": "HTTP server port",
  "settings.description.server.public_base": "Public base URL for publish links",
  "settings.description.data.backend": "Data layer backend: sqlite | postgres | mysql | supabase | none",
  "settings.description.auth.provider": "Authentication provider: none | token | oidc | proxy",
  "settings.description.auth.oidc.issuer": "OIDC IdP issuer URL",
  "settings.description.auth.oidc.client_id": "OIDC client ID",
  "settings.description.auth.oidc.verify_signature": "Verify id_token signatures (disable = security risk)",
  "settings.description.watermark.enabled": "Enable front-end canvas watermark",
  "settings.description.watermark.text": "Watermark text (empty = use identity)",
  "settings.description.watermark.opacity": "Watermark opacity (0.0\u20131.0)",
  "settings.description.watermark.font_size": "Watermark font size (px)",
  "settings.description.watermark.rotation": "Watermark rotation (degrees)",
  "settings.description.watermark.color": "Watermark color (R,G,B triplet)",
  "settings.description.security.llm.base_url": "LLM API base URL for AI security review",
  "settings.description.security.llm.model": "LLM model name for AI security review",
  "settings.description.security.llm.strict_mode": "Refuse publish when LLM is not configured",
  "settings.description.security.ai_review_enabled": "Enable AI second-pass review for weak hits",
  "settings.description.admin.audit_max_bytes": "Audit log max size before rotation (bytes, 0 = off)",
  "settings.description.admin.audit_keep": "Number of archived audit logs to keep",
  "settings.help": "Changes are saved as database overrides. Environment variables and explicit startup arguments take priority.",
  "settings.edit": "Edit",
  "settings.reset": "Restore inherited value",
  "settings.reset.confirm": "Remove the saved override for {key} and use the file/default value?",
  "settings.saved.hot": "Saved. Live configuration has been updated.",
  "settings.saved.restart": "Saved. Restart the server to apply this change.",
  "settings.reset.hot": "Override removed. Live configuration has been restored.",
  "settings.reset.restart": "Override removed. Restart the server to apply the inherited value.",
  "settings.source.environment": "environment",
  "settings.environment": "Controlled by an environment variable. Update the deployment configuration to change it.",
  "settings.inherited": "Saving creates a database override; the configuration file stays intact.",
  "settings.value.label": "Value for {key}",
  "settings.empty": "Not set",
  "settings.enabled": "Enabled",
  "settings.disabled": "Disabled",
  "settings.invalid.number": "Enter a valid number.",
  "settings.invalid.int": "Enter a whole number.",
  "settings.invalid.json": "Enter valid JSON.",
  "settings.saving": "Saving…",
  "settings.group.watermark": "Watermark",
  "settings.group.general": "General",
  "settings.group.registry": "Registry",
  "settings.label.server.host": "Bind address",
  "settings.label.server.port": "HTTP port",
  "settings.label.server.public_base": "Public URL",
  "settings.label.data.backend": "Data backend",
  "settings.label.auth.provider": "Sign-in provider",
  "settings.label.auth.oidc.issuer": "OIDC issuer",
  "settings.label.auth.oidc.client_id": "OIDC client ID",
  "settings.label.auth.oidc.verify_signature": "Verify token signatures",
  "settings.label.watermark.enabled": "Canvas watermark",
  "settings.label.watermark.text": "Watermark text",
  "settings.label.watermark.opacity": "Watermark opacity",
  "settings.label.watermark.font_size": "Watermark font size",
  "settings.label.watermark.rotation": "Watermark rotation",
  "settings.label.watermark.color": "Watermark color",
  "settings.label.security.llm.base_url": "AI review endpoint",
  "settings.label.security.llm.model": "AI review model",
  "settings.label.security.llm.strict_mode": "Require AI review",
  "settings.label.security.ai_review_enabled": "AI second-pass review",
  "settings.label.admin.audit_max_bytes": "Audit log size limit",
  "settings.label.admin.audit_keep": "Retained audit archives",
  "workspace.name": "Workspace",
  "workspace.connected": "Service connected",
  "workspace.skip": "Skip to main content",
  "nav.workspace": "Workspace",
  "nav.system": "Administration",
  "sites.description": "A quiet home for everything you publish. Manage your sites, access and content in one place.",
  "sites.publish": "Publish site",
  "sites.pager.note": "All your published work, in one place.",
  "sites.note.title": "From a file to a shared destination",
  "sites.note.body": "Publish an HTML file, a folder or an archive with a single command.",
  "sites.guide": "Publishing guide",
  "sites.detail": "SITE DETAILS",
  "metric.sites": "Across this workspace",
  "metric.bytes": "Published content",
  "metric.recent": "Active in the last 7 days",
  "metric.editable": "With inline editing enabled",
  "publish.title": "Publish your next idea",
  "publish.description": "Run this command in the terminal connected to this golive instance. Replace the file path and site name with your own.",
  "publish.step": "01  /  PUBLISH FROM YOUR TERMINAL",
  "publish.after": "02  /  Refresh this list after publishing. Open your site using its slug.",
  "publish.copy": "Copy command",
  "publish.done": "Got it",
  "btn.close": "Close",
  "sites.noresults": "No matching sites",
  "sites.noresults.hint": "Try a different name or slug, or clear your search.",
  "sites.none.hint": "Publish your first HTML page to see it here.",
  "sites.clear": "Clear search",
  "sites.loading": "Loading sites…",
  "role.superadmin": "Admin",
  "role.owner": "Owner",
  "role.maintainer": "Maintainer",
  "sites.description.data": "Browse, search and maintain the records behind your published pages.",
  "sites.description.perms": "Keep ownership and collaboration clear, with access granted intentionally.",
  "sites.description.stats": "A concise view of your published content and recent activity.",
  "sites.description.audit": "Follow changes across your workspace with a traceable activity record.",
  "sites.description.identity": "Configure how people sign in to your workspace.",
  "sites.description.databackend": "Choose where your application data lives and verify the connection.",
  "sites.description.security": "Review publishing checks and manage the rules that protect your content.",
  "sites.description.settings": "Review and edit workspace configuration, with clear sources and activation rules.",
  "who.local": "Admin session",
  "theme.system": "Follow system",
  "theme.light": "Light theme",
  "theme.dark": "Dark theme",
  "nav.open": "Open navigation",
  "nav.close": "Close navigation",
  "data.content": "JSON content",
  "data.model.label": "Data model",
  "sites.loadfailed": "Could not load sites. Try searching again.",
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
  "d.manifest": "Last publish",
  "d.manifest.none": "No manifest yet — one is written on the next publish",
  "d.manifest.published": "Published",
  "d.manifest.source": "Source",
  "d.manifest.layers": "Injected layers",
  "d.manifest.layers.none": "none",
  "d.manifest.models": "Data model",
  "d.manifest.hash": "Content hash",
  "d.policy.watermark": "Policy: watermark",
  "d.policy.wmtext": "Watermark text",
  "d.policy.visibility": "Policy: visibility",
  "d.scans": "Security scans",
  "d.scans.none": "No scans recorded",
  "d.scans.blocked": "blocked",
  "d.scans.warned": "warned",
  "d.scans.passed": "passed",
  "d.scans.findings": "{n} finding(s)",
  "word.on": "on",
  "word.off": "off",
  "word.unset": "(not set)",
  "word.role": "role",
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
  "perms.bulk.failed": "{n} site(s) could not be updated",
  "nav.identity": "Identity",
  "nav.databackend": "Data backend",
  "nav.security": "Security",
  "nav.settings": "Settings",
  "identity.title": "Identity & Auth",
  "identity.degraded": "The identity management API requires golive 0.8.0 or newer. Update and restart to use this page.",
  "identity.current": "Current authentication",
  "identity.current.desc": "The auth method currently in effect for this server.",
  "identity.method": "Method",
  "identity.oidc.title": "OIDC configuration",
  "identity.oidc.desc": "Configure an OpenID Connect provider so users log in with their corporate account.",
  "identity.oidc.preset": "IdP preset",
  "identity.oidc.custom": "Custom",
  "identity.oidc.issuer": "Issuer URL",
  "identity.oidc.clientid": "Client ID",
  "identity.oidc.clientsecret": "Client secret",
  "identity.oidc.secret.ph": "leave empty to keep existing",
  "identity.oidc.domain": "Domain / tenant",
  "identity.oidc.scopes": "Scopes",
  "identity.oidc.test": "Test connection",
  "identity.oidc.copyagent": "📋 Copy for your AI assistant",
  "identity.callback.title": "Callback URL",
  "identity.callback.desc": "Register this URL in your IdP as the allowed redirect URI. It must be reachable from the user's browser.",
  "identity.proxy.title": "Trusted reverse proxy",
  "identity.proxy.desc": "When golive runs behind a reverse proxy that injects the user email as a header, configure it here.",
  "identity.proxy.header": "Header name",
  "identity.proxy.ips": "Trusted IPs",
  "identity.test.ok": "Connection successful. Discovery document retrieved.",
  "identity.test.ok.endpoints": "Endpoints discovered:",
  "identity.test.ok.algos": "Signing algorithms:",
  "identity.test.fail": "Connection failed.",
  "identity.test.fail.hint": "Check that the issuer URL is correct and reachable from the server. If using a self-signed certificate, make sure the CA is trusted.",
  "identity.test.fail.issuer": "The issuer URL is empty. Set it first or pick a preset.",
  "identity.copyagent.prompt": "OIDC setup task description copied.",
  "databackend.title": "Data backend",
  "databackend.degraded": "The data backend management API requires golive 0.8.0 or newer. Update and restart to use this page.",
  "databackend.current": "Current backend",
  "databackend.type": "Type",
  "databackend.location": "Location",
  "databackend.tables": "Tables",
  "databackend.rows": "Total rows",
  "databackend.switch.title": "Switch backend",
  "databackend.newtype": "New type",
  "databackend.sb.url": "Supabase URL",
  "databackend.sb.key": "API key",
  "databackend.sb.key.ph": "Used for this test only; leave blank to use the matching server configuration",
  "databackend.test": "Test connection",
  "databackend.switch": "Save backend",
  "databackend.configure.supabase": "Configure supabase.url in golive.yaml and GOLIVE_SUPABASE_ANON_KEY (public key) on the server; add GOLIVE_SUPABASE_SERVICE_KEY for server operations if needed, then select Supabase in Global settings and restart. Test inputs are never saved.",
  "databackend.migrate.warn.title": "Data will not be migrated.",
  "databackend.migrate.warn.body": "Switching backends does not copy existing data. Use the command below to migrate data to the new backend. Source data is not deleted.",
  "databackend.migrate.hint": "Run this command to migrate:",
  "databackend.restart.hint": "Backend changes require a server restart to take effect.",
  "databackend.test.ok": "Connection successful. Backend is reachable.",
  "databackend.test.ok.tables": "Visible tables: {n}",
  "databackend.test.fail": "Connection failed.",
  "security.title": "Security scan",
  "security.degraded": "The security management API requires golive 0.8.0 or newer. Update and restart to use this page.",
  "security.layers": "Scan layers",
  "security.layer.keyword": "Keyword scanner",
  "security.layer.regex": "Regex scanner",
  "security.layer.ai": "AI review",
  "security.rules.title": "Rules",
  "security.rules.desc": "Built-in rules are locked but can be disabled. User rules can be added, edited and deleted.",
  "security.rules.rule": "Rule",
  "security.rules.add.type": "Type",
  "security.rules.add.name": "Name",
  "security.rules.add.pattern": "Keyword / pattern",
  "security.rules.add.strength": "Strength",
  "security.strength.weak": "Weak (warn)",
  "security.strength.strong": "Strong (block)",
  "security.test.title": "Rule test run",
  "security.test.desc": "Paste a text sample to see which rules it triggers.",
  "security.test.ph": "Paste text to scan…",
  "security.test.run": "Test",
  "security.test.result.block": "BLOCK",
  "security.test.result.warn": "WARN",
  "security.test.result.clean": "No hits — the text is clean.",
  "security.test.result.hits": "Hits:",
  "security.ai.title": "AI review",
  "security.ai.desc": "Optional LLM second-pass review for weak hits. Uses any OpenAI-compatible endpoint.",
  "security.ai.baseurl": "Base URL",
  "security.ai.model": "Model",
  "security.ai.apikey": "API key",
  "security.ai.key.ph": "leave empty to keep existing",
  "security.ai.strict": "Strict mode",
  "security.ai.test": "Test connection",
  "security.ai.test.ok": "LLM connection successful.",
  "security.ai.test.fail": "LLM connection failed.",
  "security.blocks": "Recent blocks",
  "security.blocks.none": "No recent blocks",
  "settings.title": "Global settings",
  "settings.degraded": "The settings API requires golive 0.8.0 or newer. Update and restart to use this page.",
  "settings.group.server": "Server",
  "settings.group.auth": "Authentication",
  "settings.group.storage": "Storage",
  "settings.group.data": "Data layer",
  "settings.group.security": "Security",
  "settings.group.admin": "Admin",
  "settings.source.file": "file",
  "settings.source.yaml": "file",
  "settings.source.db": "database",
  "settings.source.database": "database",
  "settings.source.default": "default",
  "settings.scope.hot": "hot",
  "settings.scope.restart": "restart",
  "settings.scope.yaml": "yaml",
  "settings.readonly": "Defined in golive.yaml — edit the file to change.",
  "settings.restart.needed": "Restart required — changes take effect after restart.",
  "settings.delete.confirm": "Remove this database override and fall back to the file/default value?",
  "settings.restart": "Restart server"
},
zh: {
  "dbcheck.admin_unauthorized": "管理会话未认证或已失效，请重新认证后再测试。",
  "dbcheck.admin_forbidden": "当前账号没有连接诊断权限，需要超级管理员身份。",
  "dbcheck.endpoint_unavailable": "当前本地服务没有提供连接诊断接口，请检查运行中的服务版本。",
  "dbcheck.running": "正在检查…",
  "dbcheck.configuration": "请完善连接配置",
  "dbcheck.failed": "连接检查未通过",
  "dbcheck.sql_ok": "数据库读写检查通过。",
  "dbcheck.sql_note": "探测记录已回滚，已有业务数据未修改。",
  "dbcheck.sql_config_required": "请在服务端设置 GOLIVE_PG_DSN（PostgreSQL）或 GOLIVE_MYSQL_DSN（MySQL）后重启。尚未发起数据库连接。",
  "dbcheck.sql_driver_missing": "请在服务端安装 html-golive[postgres] 或 html-golive[mysql]。",
  "dbcheck.sql_config_invalid": "请检查服务端连接串格式、表名及 TLS 配置。",
  "dbcheck.sql_auth_failed": "数据库认证失败，请检查服务端配置的账号与密码。",
  "dbcheck.sql_permission_denied": "数据库权限不足，请检查建表及业务表读写权限。",
  "dbcheck.sql_connection_failed": "无法连接数据库，请检查地址、端口、数据库名、网络及 TLS 配置。",
  "dbcheck.sql_probe_failed": "数据库读写探测失败，请检查业务表结构及访问权限。",
  "dbcheck.sqlite_ok": "SQLite 本地读写与完整性检查通过。",
  "dbcheck.sqlite_note": "测试写入已回滚，未修改现有应用数据。",
  "dbcheck.supabase_ok": "Supabase Data API 已正常响应。",
  "dbcheck.supabase_note": "本次检查接口可达性与可见表元数据，不代表各表写入权限或 RLS 策略已通过验证。",
  "dbcheck.required": "请填写{fields}；尚未发起远程连接测试。",
  "dbcheck.key": "API 密钥",
  "dbcheck.location": "数据库位置",
  "dbcheck.latency": "检查耗时",
  "dbcheck.http": "HTTP 状态",
  "dbcheck.backend_disabled": "数据层已禁用，无需进行连接测试。",
  "dbcheck.sqlite_locked": "SQLite 正忙或被其他进程锁定。请等待其他写入完成后重试。",
  "dbcheck.sqlite_readonly": "SQLite 当前不可写。请检查数据库文件及其父目录的写入权限。",
  "dbcheck.sqlite_corrupt": "数据库文件格式无效或未通过完整性检查。请先备份，再检查或恢复数据库。",
  "dbcheck.sqlite_open_failed": "无法打开数据库文件。请检查父目录是否存在，以及服务进程是否具有访问权限。",
  "dbcheck.sqlite_io_error": "SQLite 本地读写检查失败。请检查磁盘空间、文件系统状态及权限。",
  "dbcheck.supabase_url_invalid": "请填写完整的 HTTP(S) 项目根地址，不要包含账号密码、查询参数或 /rest/v1 路径。尚未发起远程请求。",
  "dbcheck.supabase_url_placeholder": "当前仍是示例地址，请替换为真实 Supabase 项目地址。尚未发起远程请求。",
  "dbcheck.supabase_key_invalid": "API 密钥中含空格或换行，请重新粘贴完整密钥。尚未发起远程请求。",
  "dbcheck.supabase_unauthorized": "Supabase 拒绝了此 API 密钥。请确认密钥有效，且属于所填写的项目。",
  "dbcheck.supabase_forbidden": "Data API 拒绝访问。请检查 Schema 暴露设置及当前密钥对应角色的访问权限。",
  "dbcheck.supabase_not_found": "未找到 Data API 接口。请检查项目根地址，以及项目是否已启用 Data API。",
  "dbcheck.supabase_rate_limited": "Supabase 对请求进行了限流，请稍后重试。",
  "dbcheck.supabase_redirect": "该地址返回了重定向，请填写最终项目根地址。为保护密钥，测试不会自动跳转。",
  "dbcheck.supabase_unavailable": "接口已响应，但服务暂不可用。请检查项目状态及网关服务。",
  "dbcheck.supabase_http_error": "Data API 返回了非预期 HTTP 状态，请检查项目地址与接口配置。",
  "dbcheck.supabase_invalid_response": "响应内容不是 Data API 元数据，可能误填了控制台、登录页或其他服务地址。",
  "dbcheck.supabase_tls_error": "TLS 证书验证失败，请检查域名、证书及服务端信任的 CA 配置。",
  "dbcheck.supabase_timeout": "15 秒内未收到响应。请检查网络，以及项目是否暂停或暂不可用。",
  "dbcheck.supabase_network_error": "服务端无法连接该地址。请检查 DNS、网络、代理和防火墙；此错误不能说明密钥无效。",
  "dbcheck.supabase_request_error": "无法完成请求，请检查项目地址、密钥格式和服务端网络配置。",
  "dbcheck.backend_unsupported": "此后端暂不支持连接测试，请选择 SQLite 或 Supabase。",
  "dbcheck.backend_internal_error": "内部诊断异常导致测试未完成，请重试或检查服务日志。",
  "dbcheck.request_failed": "诊断请求未完成，请检查本地服务状态后重试。",
  "settings.help": "修改将保存为数据库覆盖值；环境变量、启动命令中的显式参数优先。",
  "settings.edit": "修改",
  "settings.reset": "恢复继承值",
  "settings.reset.confirm": "移除 {key} 的数据库覆盖值，恢复为文件或默认配置？",
  "settings.saved.hot": "已保存，运行配置已更新。",
  "settings.saved.restart": "已保存，重启服务后生效。",
  "settings.reset.hot": "已移除覆盖值，运行配置已恢复。",
  "settings.reset.restart": "已移除覆盖值，重启后使用继承配置。",
  "settings.source.environment": "环境变量",
  "settings.environment": "由环境变量控制，请在部署环境中修改。",
  "settings.inherited": "保存会创建数据库覆盖值，配置文件保持原样。",
  "settings.value.label": "{key} 的参数值",
  "settings.empty": "未设置",
  "settings.enabled": "开启",
  "settings.disabled": "关闭",
  "settings.invalid.number": "请输入有效数字。",
  "settings.invalid.int": "请输入整数。",
  "settings.invalid.json": "请输入有效 JSON。",
  "settings.saving": "正在保存…",
  "settings.group.watermark": "页面水印",
  "settings.group.general": "通用",
  "settings.group.registry": "站点登记",
  "settings.label.server.host": "监听地址",
  "settings.description.server.host": "服务监听的主机名或 IP 地址。",
  "settings.label.server.port": "服务端口",
  "settings.description.server.port": "有效范围为 1–65535，重启后生效。",
  "settings.label.server.public_base": "公开访问地址",
  "settings.description.server.public_base": "用于生成发布链接的完整 HTTP(S) 地址，可留空。",
  "settings.label.data.backend": "数据后端",
  "settings.description.data.backend": "为页面应用选择数据存储后端。",
  "settings.label.auth.provider": "身份认证方式",
  "settings.description.auth.provider": "选择无认证、令牌、OIDC 或可信反向代理认证。",
  "settings.label.auth.oidc.issuer": "OIDC 签发者地址",
  "settings.description.auth.oidc.issuer": "身份提供方的完整 HTTP(S) 地址。",
  "settings.label.auth.oidc.client_id": "OIDC 客户端标识",
  "settings.description.auth.oidc.client_id": "身份提供方分配给此应用的公开客户端 ID。",
  "settings.label.auth.oidc.verify_signature": "验证令牌签名",
  "settings.description.auth.oidc.verify_signature": "验证 OIDC 登录令牌的签名。",
  "settings.label.watermark.enabled": "页面水印",
  "settings.description.watermark.enabled": "控制后续发布页面的前端画布水印。",
  "settings.label.watermark.text": "水印文字",
  "settings.description.watermark.text": "留空时使用身份信息作为水印文字。",
  "settings.label.watermark.opacity": "水印透明度",
  "settings.description.watermark.opacity": "取值 0–1，例如 0.15 表示 15% 不透明度。",
  "settings.label.watermark.font_size": "水印字号",
  "settings.description.watermark.font_size": "水印文字的像素大小，范围为 1–256。",
  "settings.label.watermark.rotation": "水印旋转角度",
  "settings.description.watermark.rotation": "水印的旋转角度，范围为 -360–360。",
  "settings.label.watermark.color": "水印颜色",
  "settings.description.watermark.color": "RGB 三通道值，如 150,150,150；每个通道为 0–255。",
  "settings.label.security.llm.base_url": "AI 审核服务地址",
  "settings.description.security.llm.base_url": "用于安全复审的服务地址，留空表示未配置。",
  "settings.label.security.llm.model": "AI 审核模型",
  "settings.description.security.llm.model": "用于安全复审的模型名称。",
  "settings.label.security.llm.strict_mode": "强制 AI 审核",
  "settings.description.security.llm.strict_mode": "启用后，AI 审核服务未配置时会拒绝发布。",
  "settings.label.security.ai_review_enabled": "AI 二次审核",
  "settings.description.security.ai_review_enabled": "对弱规则命中进行 AI 复审；强制审核模式优先。",
  "settings.label.admin.audit_max_bytes": "审计日志大小上限",
  "settings.description.admin.audit_max_bytes": "单个日志文件的字节数上限，0 表示关闭轮转。",
  "settings.label.admin.audit_keep": "审计归档保留数",
  "settings.description.admin.audit_keep": "轮转时保留的历史日志数量，范围为 1–100。",
  "workspace.name": "工作空间",
  "workspace.connected": "服务已连接",
  "workspace.skip": "跳至主要内容",
  "nav.workspace": "工作空间",
  "nav.system": "管理设置",
  "sites.description": "让每一次发布井然有序。在这里管理站点、内容与访问权限。",
  "sites.publish": "发布站点",
  "sites.pager.note": "已发布的内容，尽在此处。",
  "sites.note.title": "从一个文件，到一个可分享的页面",
  "sites.note.body": "一条命令发布 HTML、项目目录或压缩包，让想法即刻可见。",
  "sites.guide": "查看发布指南",
  "sites.detail": "站点详情",
  "metric.sites": "当前工作空间内",
  "metric.bytes": "已发布内容占用",
  "metric.recent": "过去 7 天内有更新",
  "metric.editable": "已启用在线编辑",
  "publish.title": "发布你的下一个想法",
  "publish.description": "在运行此 golive 实例的终端执行命令，将文件路径、名称和短链接替换为你的内容。",
  "publish.step": "01  /  在终端发布页面",
  "publish.after": "02  /  发布完成后刷新列表，通过站点短链接访问页面。",
  "publish.copy": "复制命令",
  "publish.done": "明白了",
  "btn.close": "关闭",
  "sites.noresults": "没有找到匹配的站点",
  "sites.noresults.hint": "换一个名称或短链接试试，也可以清除搜索。",
  "sites.none.hint": "发布你的第一个 HTML 页面，它就会出现在这里。",
  "sites.clear": "清除搜索",
  "sites.loading": "正在加载站点…",
  "role.superadmin": "管理员",
  "role.owner": "所有者",
  "role.maintainer": "协作者",
  "sites.description.data": "查看、搜索和维护已发布页面背后的应用数据。",
  "sites.description.perms": "明确内容归属与协作边界，让每一份权限恰到好处。",
  "sites.description.stats": "简洁了解已发布内容、存储占用与近期动态。",
  "sites.description.audit": "追溯工作空间内的操作，让每一次变更有迹可循。",
  "sites.description.identity": "配置成员登录工作空间的方式。",
  "sites.description.databackend": "选择应用数据的存储位置，并验证连接状态。",
  "sites.description.security": "查看发布检查，管理保护内容安全的扫描规则。",
  "sites.description.settings": "查看与修改全局配置，明确每项参数的来源和生效方式。",
  "who.local": "管理会话",
  "theme.system": "跟随系统",
  "theme.light": "浅色主题",
  "theme.dark": "深色主题",
  "nav.open": "打开导航",
  "nav.close": "关闭导航",
  "data.content": "JSON 内容",
  "data.model.label": "数据模型",
  "sites.loadfailed": "站点加载失败，请重新搜索再试。",
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
  "th.owner": "所有者",
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
  "stats.bytes": "存储用量",
  "stats.recent": "近 7 天有更新",
  "stats.editable": "可在线编辑",
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
  "d.manifest": "上次发布",
  "d.manifest.none": "还没有 manifest —— 下次发布时会写入",
  "d.manifest.published": "发布于",
  "d.manifest.source": "来源",
  "d.manifest.layers": "注入层",
  "d.manifest.layers.none": "无",
  "d.manifest.models": "数据模型",
  "d.manifest.hash": "内容哈希",
  "d.policy.watermark": "policy：水印",
  "d.policy.wmtext": "水印文本",
  "d.policy.visibility": "policy：可见性",
  "d.scans": "安全扫描",
  "d.scans.none": "没有扫描记录",
  "d.scans.blocked": "已拦截",
  "d.scans.warned": "有警告",
  "d.scans.passed": "通过",
  "d.scans.findings": "{n} 项发现",
  "word.on": "开",
  "word.off": "关",
  "word.unset": "（未设置）",
  "word.role": "角色",
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
  "perms.bulk.failed": "{n} 个站点更新失败",
  "nav.identity": "身份认证",
  "nav.databackend": "数据后端",
  "nav.security": "安全扫描",
  "nav.settings": "全局参数",
  "identity.title": "身份与认证",
  "identity.degraded": "身份管理接口需要 golive 0.8.0 及以上版本。升级并重启后可用。",
  "identity.current": "当前认证方式",
  "identity.current.desc": "当前服务端生效的认证方式。",
  "identity.method": "方式",
  "identity.oidc.title": "OIDC 配置",
  "identity.oidc.desc": "配置 OpenID Connect 提供商，让用户用企业账号登录。",
  "identity.oidc.preset": "IdP 预设",
  "identity.oidc.custom": "自定义",
  "identity.oidc.issuer": "Issuer URL",
  "identity.oidc.clientid": "Client ID",
  "identity.oidc.clientsecret": "Client Secret",
  "identity.oidc.secret.ph": "留空表示不修改",
  "identity.oidc.domain": "域名 / 租户",
  "identity.oidc.scopes": "Scopes",
  "identity.oidc.test": "测试连接",
  "identity.oidc.copyagent": "📋 复制给 AI 助手",
  "identity.callback.title": "回调地址",
  "identity.callback.desc": "将此 URL 在 IdP 后台注册为允许的回调地址。必须能从用户浏览器访问到。",
  "identity.proxy.title": "受信任反向代理",
  "identity.proxy.desc": "当 golive 运行在反向代理后面、由代理注入用户邮箱 header 时，在此配置。",
  "identity.proxy.header": "Header 名",
  "identity.proxy.ips": "可信 IP",
  "identity.test.ok": "连接成功。已获取 Discovery 文档。",
  "identity.test.ok.endpoints": "发现的端点：",
  "identity.test.ok.algos": "签名算法：",
  "identity.test.fail": "连接失败。",
  "identity.test.fail.hint": "请检查 Issuer URL 是否正确、服务端能否访问。如使用自签证书，请确保 CA 已被信任。",
  "identity.test.fail.issuer": "Issuer URL 为空。请先填写或选择一个预设。",
  "identity.copyagent.prompt": "OIDC 接入任务描述已复制。",
  "databackend.title": "数据后端",
  "databackend.degraded": "数据后端管理接口需要 golive 0.8.0 及以上版本。升级并重启后可用。",
  "databackend.current": "当前后端",
  "databackend.type": "类型",
  "databackend.location": "位置",
  "databackend.tables": "表数",
  "databackend.rows": "总行数",
  "databackend.switch.title": "切换后端",
  "databackend.newtype": "新类型",
  "databackend.sb.url": "Supabase URL",
  "databackend.sb.key": "API 密钥",
  "databackend.sb.key.ph": "仅用于本次测试；同一项目可留空使用服务端已有密钥",
  "databackend.test": "测试连接",
  "databackend.switch": "保存后端类型",
  "databackend.configure.supabase": "请先在 golive.yaml 配置 supabase.url，并在服务端设置公开密钥 GOLIVE_SUPABASE_ANON_KEY（需要服务端权限时另配 GOLIVE_SUPABASE_SERVICE_KEY）；再到全局参数选择 Supabase 后重启。连接测试中的 URL 和密钥不会保存。",
  "databackend.migrate.warn.title": "数据不会自动迁移。",
  "databackend.migrate.warn.body": "切换后端不会复制已有数据。使用下方命令将数据迁移到新后端。源数据不会被删除。",
  "databackend.migrate.hint": "运行此命令进行迁移：",
  "databackend.restart.hint": "后端变更需要重启服务才能生效。",
  "databackend.test.ok": "连接成功。后端可达。",
  "databackend.test.ok.tables": "可见表：{n} 个",
  "databackend.test.fail": "连接失败。",
  "security.title": "安全扫描",
  "security.degraded": "安全管理接口需要 golive 0.8.0 及以上版本。升级并重启后可用。",
  "security.layers": "扫描层级",
  "security.layer.keyword": "关键词扫描",
  "security.layer.regex": "正则扫描",
  "security.layer.ai": "AI 复核",
  "security.rules.title": "规则列表",
  "security.rules.desc": "内置规则带锁标识不可删除（可停用），用户规则可增删改。",
  "security.rules.rule": "规则",
  "security.rules.add.type": "类型",
  "security.rules.add.name": "名称",
  "security.rules.add.pattern": "关键词 / 正则",
  "security.rules.add.strength": "强度",
  "security.strength.weak": "弱（警告）",
  "security.strength.strong": "强（阻断）",
  "security.test.title": "规则试跑",
  "security.test.desc": "粘贴一段文本，查看命中了哪些规则。",
  "security.test.ph": "粘贴要扫描的文本…",
  "security.test.run": "试跑",
  "security.test.result.block": "阻断",
  "security.test.result.warn": "警告",
  "security.test.result.clean": "未命中任何规则——文本是干净的。",
  "security.test.result.hits": "命中：",
  "security.ai.title": "AI 复核",
  "security.ai.desc": "可选的 LLM 二次复核，用于弱命中。支持任何 OpenAI 兼容端点。",
  "security.ai.baseurl": "Base URL",
  "security.ai.model": "模型",
  "security.ai.apikey": "API Key",
  "security.ai.key.ph": "留空表示不修改",
  "security.ai.strict": "严格模式",
  "security.ai.test": "测试连接",
  "security.ai.test.ok": "LLM 连接成功。",
  "security.ai.test.fail": "LLM 连接失败。",
  "security.blocks": "最近拦截",
  "security.blocks.none": "暂无拦截记录",
  "settings.title": "全局参数",
  "settings.degraded": "参数管理接口需要 golive 0.8.0 及以上版本。升级并重启后可用。",
  "settings.group.server": "服务",
  "settings.group.auth": "认证",
  "settings.group.storage": "存储",
  "settings.group.data": "数据层",
  "settings.group.security": "安全",
  "settings.group.admin": "管理",
  "settings.source.file": "文件",
  "settings.source.yaml": "文件",
  "settings.source.db": "数据库",
  "settings.source.database": "数据库",
  "settings.source.default": "默认",
  "settings.scope.hot": "热更新",
  "settings.scope.restart": "需重启",
  "settings.scope.yaml": "yaml",
  "settings.readonly": "由 golive.yaml 定义——请编辑该文件来修改。",
  "settings.restart.needed": "需要重启——修改在重启后生效。",
  "settings.delete.confirm": "删除此数据库覆盖值并回落到文件/默认值？",
  "settings.restart": "重启服务"
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
  updateChrome();
  rerender();
}
function rerender(){
  // Re-paint anything drawn from JS strings after a language switch.
  if (!state.me) return;
  var who = state.me.identity || {};
  $("whoami").textContent = (who.email || t("who.local")) +
    (who.superadmin ? " · " + t("who.superadmin") : "");
  var active = document.querySelector(".nav-item.active");
  var view = active ? active.dataset.view : "sites";
  if (view === "sites") loadSites();
  else if (view === "data") initData();
  else if (view === "perms") loadPerms();
  else if (view === "stats") loadStats();
  else if (view === "audit") loadAudit();
  else if (view === "identity") loadIdentity();
  else if (view === "databackend") loadDataBackend();
  else if (view === "security") loadSecurity();
  else if (view === "settings") loadSettings();
}

// Shared workspace chrome and accessible controls.
function updateChrome(){
  var active = document.querySelector(".nav-item.active");
  var view = active ? active.dataset.view : "sites";
  $("current-view-label").textContent = t("nav." + view);
  document.title = "golive · " + t("nav." + view);
  document.querySelectorAll(".nav-item").forEach(function(el){
    if (el === active) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-theme-set]").forEach(function(el){
    el.title = t("theme." + el.dataset.themeSet);
    el.setAttribute("aria-label", el.title);
  });
  $("drawer-close").setAttribute("aria-label", t("btn.close"));
  $("publish-close").setAttribute("aria-label", t("btn.close"));
  $("mobile-menu").setAttribute("aria-label", t("nav.open"));
  $("nav-mask").setAttribute("aria-label", t("nav.close"));
  enhanceControls();
  renderOverview();
}
function enhanceControls(){
  document.querySelectorAll("input,select,textarea").forEach(function(input){
    if (input.id){
      var row = input.closest(".form-row,.frow");
      var label = row && row.querySelector("label");
      if (label && !label.querySelector("input")) label.htmlFor = input.id;
    }
    if (!input.labels || !input.labels.length){
      var name = input.getAttribute("placeholder") || input.id.replace(/-/g, " ");
      if (input.id === "dm-json") name = t("data.content");
      if (input.id === "data-model") name = t("data.model.label");
      input.setAttribute("aria-label", name);
    }
  });
  document.querySelectorAll(".table-scroll").forEach(function(el){
    var heading = el.closest(".view");
    if (heading){
      var title = heading.querySelector("h2");
      if (title) el.setAttribute("aria-label", title.textContent);
    }
  });
  document.querySelectorAll(".tag b").forEach(function(el){
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    el.setAttribute("aria-label", t("btn.remove") + " " + el.parentElement.textContent.replace("×", "").trim());
  });
}
var enhanceQueued = false;
new MutationObserver(function(){
  if (enhanceQueued) return;
  enhanceQueued = true;
  requestAnimationFrame(function(){ enhanceQueued = false; enhanceControls(); });
}).observe($("layout"), {childList:true, subtree:true});
function renderOverview(){
  if (!overview) return;
  $("site-overview").style.display = "grid";
  ["total_sites", "total_bytes", "updated_last_7d", "editable_sites"].forEach(function(key){
    $("overview-" + key).textContent = key === "total_bytes" ? fmtBytes(overview[key]) : overview[key];
  });
}
function loadOverview(){
  if (!(state.me && state.me.identity && state.me.identity.superadmin)) return;
  api("GET", "/api/admin/stats").then(function(data){ overview = data; renderOverview(); })
    .catch(function(){ $("site-overview").style.display = "none"; });
}
function setMobileNav(open){
  $("sidebar").classList.toggle("mobile-open", open);
  $("nav-mask").classList.toggle("open", open);
  $("mobile-menu").setAttribute("aria-expanded", String(open));
  var mobile = window.matchMedia("(max-width:760px)").matches;
  $("sidebar").inert = mobile && !open;
  if (mobile) $("main").inert = open;
  document.body.style.overflow = (open || overlayId) ? "hidden" : "";
  if (open) document.querySelector(".nav-item.active").focus();
}
$("mobile-menu").addEventListener("click", function(){ setMobileNav(true); });
$("nav-mask").addEventListener("click", function(){ setMobileNav(false); $("mobile-menu").focus(); });
window.addEventListener("resize", function(){
  if (!window.matchMedia("(max-width:760px)").matches) setMobileNav(false);
  else if (!$("sidebar").classList.contains("mobile-open")) $("sidebar").inert = true;
});
function focusOverlay(id){
  overlayReturnFocus = document.activeElement;
  overlayId = id;
  $("layout").inert = true;
  $(id).inert = false;
  document.body.style.overflow = "hidden";
  $(id).focus();
  enhanceControls();
}
function releaseOverlay(id){
  if (overlayId !== id) return;
  $("layout").inert = false;
  overlayId = null;
  document.body.style.overflow = "";
  if (overlayReturnFocus && overlayReturnFocus.isConnected) overlayReturnFocus.focus();
}
document.addEventListener("keydown", function(ev){
  var mobileNav = $("sidebar").classList.contains("mobile-open");
  if (ev.key === "Escape"){
    if (overlayId === "drawer") closeDrawer();
    else if (overlayId === "dm") closeRowModal();
    else if (mobileNav){ setMobileNav(false); $("mobile-menu").focus(); }
  }
  var panel = overlayId ? $(overlayId) : mobileNav ? $("sidebar") : null;
  if (ev.key === "Tab" && panel){
    var items = Array.prototype.filter.call(panel.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]'), function(el){ return el.getClientRects().length; });
    var first = items[0], last = items[items.length-1];
    if (!first){ ev.preventDefault(); return; }
    if (ev.shiftKey && (document.activeElement === first || document.activeElement === panel)) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && (document.activeElement === last || document.activeElement === panel)){ ev.preventDefault(); first.focus(); }
  }
  var target = ev.target.closest('[role="button"]');
  if (target && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); target.click(); }
});
$("drawer-close").addEventListener("click", closeDrawer);
["publish-open", "publish-help"].forEach(function(id){
  $(id).addEventListener("click", function(){ $("publish-guide").showModal(); });
});
["publish-close", "publish-done"].forEach(function(id){
  $(id).addEventListener("click", function(){ $("publish-guide").close(); });
});
$("publish-guide").addEventListener("click", function(ev){
  if (ev.target === this){ var r = this.getBoundingClientRect(); if (ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom) this.close(); }
});
$("publish-copy").addEventListener("click", function(){ copyText($("publish-command").textContent, this); });
document.addEventListener("click", function(ev){
  lastActionButton = ev.target.closest("button");
  var captured = lastActionButton;
  setTimeout(function(){ if (lastActionButton === captured) lastActionButton = null; }, 0);
}, true);

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
    var host = $("publish-guide").open ? $("publish-guide") : document.body;
    host.appendChild(ta);
    ta.select();
    var done = false;
    try { done = document.execCommand("copy"); } catch (e) { done = false; }
    host.removeChild(ta);
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
  var button = method !== "GET" ? lastActionButton : null;
  var wasDisabled = button ? button.disabled : false;
  if (button){ button.disabled = true; button.setAttribute("aria-busy", "true"); }
  return fetch(path, opt).then(function(r){
    return r.json().catch(function(){ return {}; }).then(function(j){
      if (!r.ok){
        var e = new Error(j.error || ("HTTP " + r.status));
        e.status = r.status;
        e.code = j.code;
        e.hint = j.hint;
        e.fields = j.fields;
        e.http_status = j.http_status;
        throw e;
      }
      return j;
    });
  }).finally(function(){
    if (button){ button.disabled = wasDisabled; button.removeAttribute("aria-busy"); }
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
    $("whoami").textContent = (who.email || t("who.local")) +
      (who.superadmin ? " · " + t("who.superadmin") : "");
    document.querySelector('[data-i18n="nav.system"]').hidden = !who.superadmin;
    if (who.superadmin){
      $("nav-data").classList.remove("hidden");
      $("nav-perms").classList.remove("hidden");
      $("nav-stats").classList.remove("hidden");
      $("nav-audit").classList.remove("hidden");
      $("nav-identity").classList.remove("hidden");
      $("nav-databackend").classList.remove("hidden");
      $("nav-security").classList.remove("hidden");
      $("nav-settings").classList.remove("hidden");
    }
    updateChrome();
    setMobileNav(false);
    if (who.superadmin) $("site-overview").style.display = "grid";
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
    setMobileNav(false);
    updateChrome();
    if (el.dataset.view === "sites") loadSites();
    if (el.dataset.view === "data") initData();
    if (el.dataset.view === "perms") loadPerms();
    if (el.dataset.view === "stats") loadStats();
    if (el.dataset.view === "audit") loadAudit();
    if (el.dataset.view === "identity") loadIdentity();
    if (el.dataset.view === "databackend") loadDataBackend();
    if (el.dataset.view === "security") loadSecurity();
    if (el.dataset.view === "settings") loadSettings();
  });
});

// ── sites list ─────────────────────────────────────────────────
function loadSites(){
  var requestId = ++siteRequest;
  $("site-search").disabled = true;
  $("site-rows").setAttribute("aria-busy", "true");
  if (!$("site-rows").children.length) $("site-rows").innerHTML = '<tr><td colspan="7" class="empty">' + esc(t("sites.loading")) + '</td></tr>';
  $("site-clear").style.display = state.q ? "" : "none";
  var qs = "?page=" + state.page + "&size=" + state.size +
           "&q=" + encodeURIComponent(state.q);
  api("GET", "/api/admin/sites" + qs).then(function(d){
    if (requestId !== siteRequest) return;
    var tb = $("site-rows");
    tb.innerHTML = "";
    if (!d.sites.length){
      tb.innerHTML = '<tr><td colspan="7" class="empty">' +
        "<strong>" + esc(t(state.q ? "sites.noresults" : "sites.none")) + "</strong><br>" + esc(t(state.q ? "sites.noresults.hint" : "sites.none.hint")) + "</td></tr>";
    }
    d.sites.forEach(function(s){
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td><div class="site-name"><span class="site-monogram" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h4"/></svg></span><div><strong>' + esc(s.name || t("sites.unnamed")) + '</strong><small>' + esc((s.site_id || "").slice(0,8)) + '</small></div></div></td>' +
        "<td>" + (s.slug ?  '<a class="site-url" href="/' + esc(s.slug) +
                  '" target="_blank" rel="noopener">' + esc(s.slug) +
                  "</a>" : '<span class="badge">' + esc(t("sites.noslug")) +
                  "</span>") + "</td>" +
        "<td>" + esc(s.owner || "—") + "</td>" +
        '<td><span class="badge ' + esc(s.role) + '">' +
          esc(s.role ? t("role." + s.role) : "—") + "</span></td>" +
        "<td>" + fmtBytes(s.size) + "</td>" +
        '<td class="date-cell">' + esc((s.updated_at || "").replace("T", " ").slice(0,19)) + "</td>" +
        '<td class="actions"><button data-act="open">' +
          esc(t("btn.detail")) + "</button></td>";
      tr.querySelector('[data-act="open"]').addEventListener(
        "click", function(){ openDrawer(s.slug || s.site_id); });
      tb.appendChild(tr);
    });
    $("site-count").textContent = t("sites.count", {n: d.total});
    loadOverview();
    var pages = Math.max(1, Math.ceil(d.total / state.size));
    $("site-page").textContent = state.page + " / " + pages;
    $("site-prev").disabled = state.page <= 1;
    $("site-next").disabled = state.page >= pages;
  }).catch(function(e){
    if (requestId !== siteRequest) return;
    $("site-rows").innerHTML = '<tr><td colspan="7" class="empty">' + esc(t("sites.loadfailed")) + '</td></tr>';
    toast(e.message, true);
  }).finally(function(){
    if (requestId === siteRequest){ $("site-search").disabled = false; $("site-rows").removeAttribute("aria-busy"); }
  });
}
$("site-clear").addEventListener("click", function(){ $("site-q").value = ""; state.q = ""; state.page = 1; loadSites(); });
$("site-q").addEventListener("search", function(){ if (!this.value) $("site-clear").click(); });
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
    // These three read through t() rather than being inline Chinese, which
    // is what they were: the drawer subtitle was missed when the portal was
    // translated, so an English session still saw 角色 here.
    $("d-sub").textContent = "slug: " + (s.slug || t("word.unset")) +
      " · id: " + s.site_id +
      " · owner: " + (s.owner || t("word.unset")) +
      " · " + t("word.role") + ": " + s.role;
    $("d-name").value = s.name || "";
    $("d-notes").value = s.notes || "";
    $("d-editable").checked = !!s.editable;
    var canMeta = (s.role === "owner" || s.role === "superadmin");
    $("d-save").disabled = !canMeta;
    $("sec-maint").style.display = canMeta ? "" : "none";
    $("sec-transfer").style.display = canMeta ? "" : "none";
    $("sec-delete").style.display = canMeta ? "" : "none";
    renderMaints(s.maintainers || []);
    renderManifest(s.manifest, s.policy);
    renderScans(s.scans || []);
    renderSnaps(s.snapshots || []);
    $("d-del-confirm").value = "";
    $("drawer").classList.add("open");
    $("drawer-mask").classList.add("open");
    focusOverlay("drawer");
  }).catch(function(e){ toast(e.message, true); });
}
function closeDrawer(){
  releaseOverlay("drawer");
  $("drawer").inert = true;
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

function kvRow(label, value){
  return '<div class="kv-row"><span class="kv-k">' + esc(label) +
         '</span><span class="kv-v">' + esc(value) + "</span></div>";
}

function renderManifest(m, policy){
  var box = $("d-manifest");
  var html = "";
  if (!m){
    // Not a fault: sites published before 0.9.0 have no manifest, and one
    // appears on the next publish. Say that rather than showing an error.
    html += '<div style="color:var(--muted);font-size:12px">' +
            esc(t("d.manifest.none")) + "</div>";
  } else {
    html += kvRow(t("d.manifest.published"),
                  (m.published_at || "") +
                  (m.published_with ? "  ·  golive " + m.published_with : ""));
    html += kvRow(t("d.manifest.source"), m.source_type || "unknown");
    html += kvRow(t("d.manifest.layers"),
                  (m.injections && m.injections.length)
                    ? m.injections.join(", ") : t("d.manifest.layers.none"));
    if (m.data_models && m.data_models.length){
      html += kvRow(t("d.manifest.models"), m.data_models.join(", "));
    }
    html += kvRow(t("d.manifest.hash"),
                  (m.content_sha256 || "").slice(0, 16) + "…");
  }
  if (policy){
    html += kvRow(t("d.policy.watermark"),
                  policy.watermark_enabled ? t("word.on") : t("word.off"));
    if (policy.watermark_enabled && policy.watermark_config &&
        policy.watermark_config.text){
      html += kvRow(t("d.policy.wmtext"), policy.watermark_config.text);
    }
    html += kvRow(t("d.policy.visibility"), policy.visibility || "public");
  }
  box.innerHTML = html;
}

function renderScans(scans){
  var box = $("d-scans");
  if (!scans || !scans.length){
    box.innerHTML = '<div style="color:var(--muted);font-size:12px">' +
                    esc(t("d.scans.none")) + "</div>";
    return;
  }
  var html = "";
  scans.forEach(function(sc){
    // Findings are stored already redacted, but they are still the part of
    // this view most likely to carry something sensitive, so only the counts
    // and the verdict are shown here.
    // finding_count, not findings.length: the API stopped sending the
    // findings themselves in 0.9.1. Falls back to counting an array so a
    // portal served by a newer golive against an older record still works.
    var n = (sc.finding_count != null) ? sc.finding_count
          : (sc.findings || []).length;
    // The column is "verdict", not "blocked" — reading the latter gave every
    // scan a passing label, including the ones that stopped a publish.
    // Three verdicts, not two: collapsing "warn" into passed would hide
    // that a page tripped a content rule and was published anyway.
    // Written as whole keys rather than "d.scans." + suffix so the i18n
    // completeness test can still see which keys this file uses; the test
    // caught the concatenated version as a missing key "d.scans.".
    var verdict = (sc.verdict === "block") ? t("d.scans.blocked")
                : (sc.verdict === "warn") ? t("d.scans.warned")
                : t("d.scans.passed");
    html += '<div class="snap-row"><span class="ts">' +
            esc(sc.created_at || "") + "</span>" +
            "<span>" + esc(verdict) + "</span>" +
            "<span>" + esc(t("d.scans.findings", {n: n})) + "</span></div>";
  });
  box.innerHTML = html;
}

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
  $("dm-json").removeAttribute("aria-invalid");
  $("dm-save").style.display = isView ? "none" : "";
  $("dm-mask").style.display = "block";
  $("dm").style.display = "block";
  focusOverlay("dm");
}
function closeRowModal(){
  releaseOverlay("dm");
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
    $("dm-json").setAttribute("aria-invalid", "true");
    $("dm-json").focus();
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
    if (state.dmMode === "create"){
      state.dataModel = $("dm-model").value.trim();
      state.dataPage = 1;
      state.dataQ = "";
      $("data-q").value = "";
      initData();
    } else loadDataRows();
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
    "  anon_key_env: GOLIVE_SUPABASE_ANON_KEY",
    "  service_key_env: GOLIVE_SUPABASE_SERVICE_KEY"
  ].join("\n"),
  env: [
    "export GOLIVE_SUPABASE_ANON_KEY='your-publishable-or-anon-key'",
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
    "  anon_key_env: GOLIVE_SUPABASE_ANON_KEY",
    "  service_key_env: GOLIVE_SUPABASE_SERVICE_KEY"
  ].join("\n"),
  env: [
    "export GOLIVE_SUPABASE_ANON_KEY='你的 publishable 或 anon key'",
    "export GOLIVE_SUPABASE_SERVICE_KEY='仅服务器使用的 service key'",
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
      "选择 SQLite、PostgreSQL、MySQL 8.4+ 或 Supabase，再往下做：",
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
      "【方案 C / D：PostgreSQL / MySQL 8.4+】",
      "安装 html-golive[postgres] 或 html-golive[mysql]，通过服务器环境变量 GOLIVE_PG_DSN 或 GOLIVE_MYSQL_DSN 设置连接。",
      "配置 registry.backend 与 data.backend 为 postgres 或 mysql，运行 golive db init、golive doctor、golive verify，再重启并重新发布页面。",
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
    "Choose SQLite, PostgreSQL, MySQL 8.4+ or Supabase, then proceed:",
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
    "[Option C / D: PostgreSQL / MySQL 8.4+]",
    "Install html-golive[postgres] or html-golive[mysql]; set GOLIVE_PG_DSN or GOLIVE_MYSQL_DSN in the server environment.",
    "Set registry.backend and data.backend to postgres or mysql. Run golive db init, doctor and verify, restart and republish.",
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

// ── identity / auth page (v0.8.0) ─────────────────────────────
var IDP_PRESETS = {
  google: {issuer: "https://accounts.google.com", scopes: "openid email profile"},
  auth0: {issuer: "https://{domain}", scopes: "openid email profile"},
  okta: {issuer: "https://{domain}", scopes: "openid email profile"},
  azure: {issuer: "https://login.microsoftonline.com/{tenant}/v2.0", scopes: "openid email profile"},
  keycloak: {scopes: "openid email profile"},
  authentik: {scopes: "openid email profile"}
};

function showDegraded(pageName) {
  $(pageName + "-degraded").style.display = "block";
  $(pageName + "-main").style.display = "none";
}

function loadIdentity() {
  // Try the v0.8.0 settings API; if it doesn't exist, show degraded notice
  api("GET", "/api/admin/settings").then(function(d) {
    $("identity-degraded").style.display = "none";
    $("identity-main").style.display = "";
    // A group's API returns {settings: {group: [{key,value,...}]}, total: N}
    var settings = d.settings || {};
    var flatSettings = [];
    if (Array.isArray(settings)) {
      flatSettings = settings;
    } else if (typeof settings === "object") {
      Object.keys(settings).forEach(function(g) {
        flatSettings = flatSettings.concat(settings[g] || []);
      });
    }
    // Find auth method from settings
    var authMethod = "none";
    for (var i = 0; i < flatSettings.length; i++) {
      var s = flatSettings[i];
      if (s.key === "auth.provider" || s.key === "auth") {
        authMethod = s.value || "none";
        break;
      }
    }
    var pill = $("id-method");
    pill.className = "status-pill " + (authMethod === "none" ? "none" : authMethod);
    pill.textContent = authMethod;
    // Fill form from settings if available
    flatSettings.forEach(function(s) {
      if (s.key === "auth.oidc.issuer") $("oidc-issuer").value = s.value || "";
      if (s.key === "auth.oidc.client_id") $("oidc-client-id").value = s.value || "";
      if (s.key === "auth.oidc.scopes") $("oidc-scopes").value = s.value || "";
      if (s.key === "auth.oidc.redirect_uri") $("oidc-callback-url").textContent = s.value || "";
      if (s.key === "auth.proxy.header") $("proxy-header").value = s.value || "";
      if (s.key === "auth.proxy.trusted_ips") $("proxy-ips").value = s.value || "";
    });
    // Always show callback URL (computed or config)
    var base = window.location.origin;
    if (!$("oidc-callback-url").textContent || $("oidc-callback-url").textContent === "https://<your-domain>/auth/callback") {
      $("oidc-callback-url").textContent = base + "/auth/callback";
    }
  }).catch(function(e) {
    if (e.status === 404 || e.status === 501) {
      // Fallback: read what we can from /api/admin/me
      $("identity-degraded").style.display = "none";
      $("identity-main").style.display = "";
      var me = state.me || {};
      var who = me.identity || {};
      var method = who.via_token ? "token" : (who.email ? "oidc" : "none");
      var pill = $("id-method");
      pill.className = "status-pill " + method;
      pill.textContent = method;
      $("oidc-callback-url").textContent = window.location.origin + "/auth/callback";
    } else {
      showDegraded("identity");
    }
  });
}

// IdP preset change -> auto-fill issuer + scopes
$("idp-preset").addEventListener("change", function() {
  var preset = this.value;
  if (!preset) return;
  var spec = IDP_PRESETS[preset];
  if (!spec) return;
  if (preset === "custom") return;
  if (spec.issuer) $("oidc-issuer").value = spec.issuer;
  if (spec.scopes) $("oidc-scopes").value = spec.scopes;
  // Show/hide domain field hint
  if (preset === "auth0" || preset === "okta") {
    $("oidc-domain").placeholder = "your-tenant." + preset + ".com";
  } else if (preset === "azure") {
    $("oidc-domain").placeholder = "tenant-id or organizations";
  }
});

$("oidc-test").addEventListener("click", function() {
  var issuer = $("oidc-issuer").value.trim();
  if (!issuer) {
    var res = $("oidc-test-result");
    res.style.display = "block";
    res.className = "test-result fail";
    res.innerHTML = "<b>" + esc(t("identity.test.fail")) + "</b><br>" +
      esc(t("identity.test.fail.issuer"));
    return;
  }
  var btn = $("oidc-test");
  btn.disabled = true;
  btn.textContent = "...";
  var body = {
    issuer: issuer,
    client_id: $("oidc-client-id").value.trim(),
    redirect_uri: $("oidc-callback-url").textContent
  };
  // Don't send secret unless user typed one
  var secret = $("oidc-client-secret").value;
  if (secret) body.client_secret = secret;
  api("POST", "/api/admin/test/oidc", body).then(function(d) {
    btn.disabled = false;
    btn.textContent = t("identity.oidc.test");
    var res = $("oidc-test-result");
    res.style.display = "block";
    // A group's API returns {ok: true/false, step, error, hint, findings}
    if (d.ok === false) {
      res.className = "test-result fail";
      var html = "<b>" + esc(t("identity.test.fail")) + "</b><br>" +
        esc(d.error || d.step || "unknown error");
      if (d.hint) html += "<br><br>" + esc(d.hint);
      res.innerHTML = html;
      return;
    }
    res.className = "test-result ok";
    var html = "<b>" + esc(t("identity.test.ok")) + "</b>";
    // Handle findings.discovery shape from A group's API
    var disc = d.findings && d.findings.discovery;
    if (disc) {
      if (disc.issuer) html += '<div class="endpoint">issuer: ' + esc(disc.issuer) + "</div>";
      html += "<br>" + esc(t("identity.test.ok.endpoints")) + "<br>";
      ["authorization_endpoint", "token_endpoint", "userinfo_endpoint",
       "jwks_uri"].forEach(function(k) {
        if (disc[k]) html += '<div class="endpoint">' + esc(k) + ": " +
          esc(disc[k]) + "</div>";
      });
    }
    // Also handle flat shape (d.endpoints, d.algorithms) for compat
    if (d.endpoints) {
      html += "<br>" + esc(t("identity.test.ok.endpoints")) + "<br>";
      Object.keys(d.endpoints).forEach(function(k) {
        html += '<div class="endpoint">' + esc(k) + ": " + esc(d.endpoints[k]) + "</div>";
      });
    }
    if (d.algorithms && d.algorithms.length) {
      html += "<br>" + esc(t("identity.test.ok.algos")) + " " +
        d.algorithms.map(esc).join(", ");
    }
    res.innerHTML = html;
  }).catch(function(e) {
    btn.disabled = false;
    btn.textContent = t("identity.oidc.test");
    var res = $("oidc-test-result");
    res.style.display = "block";
    res.className = "test-result fail";
    res.innerHTML = "<b>" + esc(t("identity.test.fail")) + "</b><br>" +
      esc(e.message) + "<br><br>" + esc(t("identity.test.fail.hint"));
  });
});

$("oidc-callback-copy").addEventListener("click", function() {
  copyText($("oidc-callback-url").textContent, this);
});

$("oidc-agent-copy").addEventListener("click", function() {
  var callback = $("oidc-callback-url").textContent;
  var issuer = $("oidc-issuer").value.trim();
  var clientId = $("oidc-client-id").value.trim();
  var ver = BOOT.version || "unknown";
  var prompt;
  if (state.lang === "zh") {
    prompt = [
      "我在用 html-golive（版本 v" + ver + "，CLI: golive）。",
      "请帮我配置 OIDC 单点登录。",
      "",
      "回调地址（需在 IdP 后台注册）：",
      callback,
      "",
      "Issuer URL：" + (issuer || "<请填写你的 IdP Issuer URL>"),
      "Client ID：" + (clientId || "<拿到后填入 admin 界面>"),
      "Client Secret：<拿到后填入 admin 界面，不要告诉我>",
      "",
      "步骤：",
      "1. 在 IdP 后台创建一个 OIDC 应用，回调地址填上面的 URL。",
      "2. 拿到 client_id 和 client_secret。",
      "3. 在 golive admin 界面（/admin -> 身份认证）填入 issuer、client_id、secret。",
      "4. 点「测试连接」验证。",
      "5. 重启 golive serve 生效。",
      "",
      "如果失败请把报错原文贴给我。"
    ].join("\n");
  } else {
    prompt = [
      "I'm using html-golive (version v" + ver + ", CLI: golive).",
      "Please help me configure OIDC single sign-on.",
      "",
      "Callback URL (register this in your IdP):",
      callback,
      "",
      "Issuer URL: " + (issuer || "<fill in your IdP Issuer URL>"),
      "Client ID: " + (clientId || "<get it from IdP, then fill in admin UI>"),
      "Client Secret: <get it from IdP, then fill in admin UI — don't share it with me>",
      "",
      "Steps:",
      "1. Create an OIDC application in your IdP, set the callback URL to the one above.",
      "2. Obtain the client_id and client_secret.",
      "3. In the golive admin UI (/admin -> Identity), fill in issuer, client_id, secret.",
      "4. Click 'Test connection' to verify.",
      "5. Restart golive serve for changes to take effect.",
      "",
      "If any step fails, paste the exact error back to me."
    ].join("\n");
  }
  copyText(prompt, this);
  toast(t("identity.copyagent.prompt"));
});

$("oidc-save").addEventListener("click", function() {
  var body = {
    "auth.oidc.issuer": $("oidc-issuer").value.trim(),
    "auth.oidc.client_id": $("oidc-client-id").value.trim(),
    "auth.oidc.scopes": $("oidc-scopes").value.trim(),
    "auth.oidc.redirect_uri": $("oidc-callback-url").textContent
  };
  var secret = $("oidc-client-secret").value;
  if (secret) body["auth.oidc.client_secret"] = secret;
  api("PUT", "/api/admin/settings", body).then(function() {
    toast(t("msg.saved"));
    $("oidc-client-secret").value = "";
  }).catch(function(e) {
    toast(e.message, true);
  });
});

$("proxy-save").addEventListener("click", function() {
  var body = {
    "auth.proxy.header": $("proxy-header").value.trim(),
    "auth.proxy.trusted_ips": $("proxy-ips").value.trim()
  };
  api("PUT", "/api/admin/settings", body).then(function() {
    toast(t("msg.saved"));
  }).catch(function(e) {
    toast(e.message, true);
  });
});

// ── data backend page (v0.8.0) ────────────────────────────────
function loadDataBackend() {
  // Try the v0.8.0 settings API first; fallback to M6 data endpoint
  api("GET", "/api/admin/settings").then(function(d) {
    $("databackend-degraded").style.display = "none";
    $("databackend-main").style.display = "";
    // Extract data backend info from settings
    var settings = d.settings || {};
    var flatSettings = [];
    if (Array.isArray(settings)) {
      flatSettings = settings;
    } else if (typeof settings === "object") {
      Object.keys(settings).forEach(function(g) {
        flatSettings = flatSettings.concat(settings[g] || []);
      });
    }
    var dbType = "none";
    var dbLocation = "—";
    flatSettings.forEach(function(s) {
      if (s.key === "data.backend") dbType = s.value || "none";
      if (s.key === "data.sqlite_path") dbLocation = s.value || "—";
      if (s.key === "supabase.url") dbLocation = s.value || "—";
    });
    var pill = $("db-type");
    pill.className = "status-pill " + (dbType === "none" ? "none" : "token");
    pill.textContent = dbType;
    $("db-location").textContent = dbLocation;
    // Try to get table/row counts from M6 data API
    api("GET", "/api/admin/data/models").then(function(d2) {
      var models = d2.models || [];
      $("db-tables").textContent = models.length;
      var totalRows = 0;
      models.forEach(function(m) { totalRows += (m.count || 0); });
      $("db-rows").textContent = totalRows;
    }).catch(function() {
      $("db-tables").textContent = "—";
      $("db-rows").textContent = "—";
    });
  }).catch(function(e) {
    if (e.status === 404 || e.status === 501) {
      // Fallback: use M6 data API to detect backend
      api("GET", "/api/admin/data/models").then(function(d) {
        $("databackend-degraded").style.display = "none";
        $("databackend-main").style.display = "";
        $("db-type").className = "status-pill token";
        $("db-type").textContent = "sqlite";
        var models = d.models || [];
        $("db-tables").textContent = models.length;
        var totalRows = 0;
        models.forEach(function(m) { totalRows += (m.count || 0); });
        $("db-rows").textContent = totalRows;
      }).catch(function(e2) {
        if (e2.status === 400) {
          // No data backend configured
          $("databackend-degraded").style.display = "none";
          $("databackend-main").style.display = "";
          $("db-type").className = "status-pill none";
          $("db-type").textContent = "none";
          $("db-tables").textContent = "—";
          $("db-rows").textContent = "—";
        } else {
          showDegraded("databackend");
        }
      });
    } else {
      showDegraded("databackend");
    }
  });
}

function clearBackendErrors(){
  ["db-sb-url", "db-sb-key"].forEach(function(id){
    $(id).removeAttribute("aria-invalid");
    $(id).removeAttribute("aria-describedby");
  });
}
$("db-new-type").addEventListener("change", function() {
  $("db-supabase-opts").style.display = this.value === "supabase" ? "" : "none";
  $("db-test-result").style.display = "none";
  clearBackendErrors();
  $("migrate-cmd-preview").textContent = this.value === "none" ? "" : "golive migrate data --to " + this.value + " --dry-run";
});
function renderBackendCheck(d){
  var res = $("db-test-result");
  res.style.display = "block";
  res.removeAttribute("aria-busy");
  var code = d.code || "";
  var key = "dbcheck." + code;
  var dict = I18N[state.lang] || I18N.en;
  var message = dict[key] || I18N.en[key] || d.error || t("dbcheck.request_failed");
  if (code === "backend_disabled"){
    res.className = "test-result";
    res.textContent = message;
    return;
  }
  if (d.ok === true){
    res.className = "test-result ok";
    var html = "<b>" + esc(message) + "</b>";
    if (d.table_count != null) html += "<br>" + esc(t("databackend.test.ok.tables", {n:d.table_count}));
    if (d.location) html += '<div class="endpoint">' + esc(t("dbcheck.location")) + ": " + esc(d.location) + "</div>";
    if (d.latency_ms != null) html += '<div class="endpoint">' + esc(t("dbcheck.latency")) + ": " + esc(d.latency_ms) + " ms</div>";
    html += "<br>" + esc(t(code === "sqlite_ok" ? "dbcheck.sqlite_note" : code === "sql_ok" ? "dbcheck.sql_note" : "dbcheck.supabase_note"));
    res.innerHTML = html;
    return;
  }
  var fields = d.fields || [];
  if (code === "supabase_config_required"){
    var labels = fields.map(function(field){ return field === "url" ? "Supabase URL" : t("dbcheck.key"); });
    message = t("dbcheck.required", {fields:labels.join(state.lang === "zh" ? "、" : ", ")});
  }
  res.className = "test-result fail";
  res.innerHTML = "<b>" + esc(t(fields.length ? "dbcheck.configuration" : "dbcheck.failed")) + "</b><br>" + esc(message) +
    (d.http_status ? '<div class="endpoint">' + esc(t("dbcheck.http")) + ": " + esc(d.http_status) + "</div>" : "");
  fields.forEach(function(field){
    var input = field === "url" ? $("db-sb-url") : field === "key" ? $("db-sb-key") : null;
    if (input){ input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", "db-test-result"); }
  });
  if (fields.length){ var first = fields[0] === "url" ? $("db-sb-url") : $("db-sb-key"); first.focus(); }
}
$("db-test").addEventListener("click", function() {
  var newType = $("db-new-type").value;
  var body = {backend: newType};
  if (newType === "supabase") {
    body.url = $("db-sb-url").value.trim();
    var key = $("db-sb-key").value;
    if (key) body.service_key = key;
  }
  clearBackendErrors();
  var btn = $("db-test");
  var controls = [btn, $("db-switch"), $("db-new-type"), $("db-sb-url"), $("db-sb-key")];
  controls.forEach(function(control){ control.disabled = true; });
  btn.textContent = t("dbcheck.running");
  var res = $("db-test-result");
  res.style.display = "block";
  res.className = "test-result";
  res.setAttribute("aria-busy", "true");
  res.textContent = t("dbcheck.running");
  api("POST", "/api/admin/test/data-backend", body).then(renderBackendCheck)
  .catch(function(e){
    var code = e.code || (e.status === 401 ? "admin_unauthorized" : e.status === 403 ? "admin_forbidden" : e.status === 404 ? "endpoint_unavailable" : "request_failed");
    renderBackendCheck({ok:false, code:code, error:e.message,
      fields:e.fields, hint:e.hint, http_status:e.http_status});
  }).finally(function(){
    controls.forEach(function(control){ control.disabled = false; });
    btn.textContent = t("databackend.test");
    var invalid = document.querySelector('#db-supabase-opts [aria-invalid="true"]');
    if (invalid) invalid.focus();
  });
});

$("db-switch").addEventListener("click", function() {
  var newType = $("db-new-type").value;
  var body = {"data.backend": newType};
  if (newType === "supabase") {
    toast(t("databackend.configure.supabase"), true);
    return;
  }
  api("PUT", "/api/admin/settings", body).then(function() {
    toast(t("msg.saved"));
    toast(t("databackend.restart.hint"));
  }).catch(function(e) {
    toast(e.message, true);
  });
});

// ── security page (v0.8.0) ────────────────────────────────────
function loadSecurity() {
  // Try the v0.8.0 security API; fallback to showing degraded
  api("GET", "/api/admin/security/rules").then(function(d) {
    $("security-degraded").style.display = "none";
    $("security-main").style.display = "";
    renderSecurityRules(d.rules || []);
    // AI status
    var aiOn = d.ai_enabled || false;
    var aiPill = $("sec-ai-status");
    aiPill.className = "status-pill " + (aiOn ? "oidc" : "none");
    aiPill.textContent = aiOn ? "ON" : "OFF";
    // Fill AI config
    if (d.ai_config) {
      $("ai-base-url").value = d.ai_config.base_url || "";
      $("ai-model").value = d.ai_config.model || "";
      $("ai-strict-mode").checked = !!d.ai_config.strict_mode;
    }
    // Recent blocks
    renderSecurityBlocks(d.recent_blocks || []);
  }).catch(function(e) {
    if (e.status === 404 || e.status === 501) {
      // Fallback: try settings API for AI config
      api("GET", "/api/admin/settings").then(function(d2) {
        $("security-degraded").style.display = "none";
        $("security-main").style.display = "";
        // Render built-in rules from the page's knowledge
        renderSecurityRulesFromConfig(d2);
        renderSecurityBlocks([]);
      }).catch(function() {
        showDegraded("security");
      });
    } else {
      showDegraded("security");
    }
  });
}

function renderSecurityRules(rules) {
  var box = $("sec-rules-list");
  box.innerHTML = "";
  if (!rules.length) {
    box.innerHTML = '<span style="color:var(--muted);font-size:12px">' +
      esc(t("security.blocks.none")) + "</span>";
    return;
  }
  rules.forEach(function(r) {
    var row = document.createElement("div");
    row.className = "rule-row";
    var isBuiltin = r.builtin || r.source === "builtin";
    var strengthClass = r.strength === "strong" ? "danger" : "warn";
    row.innerHTML =
      (isBuiltin ? '<span class="lock" title="' + esc(t("perms.admins.locktip")) +
        '"></span>' : '<span style="width:11px;flex:0 0 11px"></span>') +
      '<div class="rule-name"><b>' + esc(r.name || r.type || "unnamed") + "</b>" +
        '<div class="meta">' + esc(r.type || "keyword") + " · " +
        esc(r.strength || "weak") +
        (r.keywords ? " · " + r.keywords.map(esc).join(", ").slice(0, 60) : "") +
        "</div></div>" +
      '<div class="rule-actions">' +
        (isBuiltin ? "" : '<button class="danger" data-act="del">' +
          esc(t("btn.delete")) + "</button>") +
      "</div>";
    if (!isBuiltin) {
      row.querySelector('[data-act="del"]').addEventListener("click", function() {
        api("DELETE", "/api/admin/security/rules", {name: r.name})
          .then(function() { toast(t("msg.deleted")); loadSecurity(); })
          .catch(function(e) { toast(e.message, true); });
      });
    }
    box.appendChild(row);
  });
}

function renderSecurityRulesFromConfig(settingsData) {
  // When the security/rules endpoint is not available, show a static
  // message that rules come from rules.yaml
  var box = $("sec-rules-list");
  box.innerHTML = '<div style="color:var(--muted);font-size:12px">' +
    esc(t("security.degraded")) + "</div>";
}

function renderSecurityBlocks(blocks) {
  var tb = $("sec-blocks-list");
  tb.innerHTML = blocks.length ? blocks.map(function(b) {
    return "<tr><td>" + esc((b.ts || "").replace("T", " ")) + "</td>" +
      "<td>" + esc(b.who || "—") + "</td>" +
      "<td>" + esc(b.rule || b.name || "—") + "</td></tr>";
  }).join("") : '<tr><td colspan="3" class="empty">' +
    esc(t("security.blocks.none")) + "</td></tr>";
}

$("sec-rule-add").addEventListener("click", function() {
  var body = {
    type: $("sec-new-type").value,
    name: $("sec-new-name").value.trim(),
    strength: $("sec-new-strength").value
  };
  var pattern = $("sec-new-pattern").value.trim();
  if (!body.name || !pattern) {
    toast(t("security.rules.add.name"), true);
    return;
  }
  if (body.type === "keyword") {
    body.keywords = [pattern];
  } else {
    body.pattern = pattern;
  }
  api("POST", "/api/admin/security/rules", body).then(function() {
    toast(t("msg.added"));
    $("sec-new-name").value = "";
    $("sec-new-pattern").value = "";
    loadSecurity();
  }).catch(function(e) {
    toast(e.message, true);
  });
});

$("sec-test-run").addEventListener("click", function() {
  var text = $("sec-test-input").value.trim();
  if (!text) return;
  var btn = $("sec-test-run");
  btn.disabled = true;
  btn.textContent = "...";
  api("POST", "/api/admin/security/test", {text: text}).then(function(d) {
    btn.disabled = false;
    btn.textContent = t("security.test.run");
    var res = $("sec-test-result");
    res.style.display = "block";
    // A group's API returns {verdict: "block"/"warn"/"pass", hits: [...]}
    var hits = d.hits || d.matched_details || [];
    var verdict = d.verdict || (hits.length ? (hits.some(function(h) {
      return h.strength === "strong";
    }) ? "block" : "warn") : "pass");
    if (!hits.length || verdict === "pass") {
      res.className = "test-result ok";
      res.innerHTML = "<b>" + esc(t("security.test.result.clean")) + "</b>";
    } else {
      var blocked = verdict === "block";
      res.className = "test-result " + (blocked ? "fail" : "");
      res.style.borderColor = blocked ? "var(--danger)" : "var(--warn)";
      var html = "<b>" + esc(blocked ? t("security.test.result.block") :
        t("security.test.result.warn")) + "</b><br>" +
        esc(t("security.test.result.hits")) + "<br>";
      hits.forEach(function(h) {
        html += '<div class="endpoint">· [' + esc(h.rule_name || h.name || h.type || "?") +
          "] " + esc(h.keyword || h.pattern || "") + " (" +
          esc(h.strength || "?") + ")</div>";
      });
      if (d.total_rules_checked) {
        html += '<div class="endpoint">checked ' + d.total_rules_checked +
          " rules, " + (d.total_hits || hits.length) + " hits</div>";
      }
      res.innerHTML = html;
    }
  }).catch(function(e) {
    btn.disabled = false;
    btn.textContent = t("security.test.run");
    var res = $("sec-test-result");
    res.style.display = "block";
    res.className = "test-result fail";
    res.innerHTML = "<b>" + esc(t("security.degraded")) + "</b>";
  });
});

$("ai-test").addEventListener("click", function() {
  var body = {
    base_url: $("ai-base-url").value.trim(),
    model: $("ai-model").value.trim()
  };
  var key = $("ai-api-key").value;
  if (key) body.api_key = key;
  var btn = $("ai-test");
  btn.disabled = true;
  btn.textContent = "...";
  api("POST", "/api/admin/test/llm", body).then(function(d) {
    btn.disabled = false;
    btn.textContent = t("security.ai.test");
    var res = $("ai-test-result");
    res.style.display = "block";
    if (d.ok === false) {
      res.className = "test-result fail";
      res.innerHTML = "<b>" + esc(t("security.ai.test.fail")) + "</b><br>" +
        esc(d.error || "unknown error") +
        (d.hint ? "<br><br>" + esc(d.hint) : "");
      return;
    }
    res.className = "test-result ok";
    var html = "<b>" + esc(t("security.ai.test.ok")) + "</b>";
    if (d.model) {
      html += '<div class="endpoint">model: ' + esc(d.model) + "</div>";
    }
    if (d.latency_ms) {
      html += '<div class="endpoint">latency: ' + d.latency_ms + "ms</div>";
    }
    res.innerHTML = html;
  }).catch(function(e) {
    btn.disabled = false;
    btn.textContent = t("security.ai.test");
    var res = $("ai-test-result");
    res.style.display = "block";
    res.className = "test-result fail";
    res.innerHTML = "<b>" + esc(t("security.ai.test.fail")) + "</b><br>" +
      esc(e.message);
  });
});

$("ai-save").addEventListener("click", function() {
  var body = {
    "security.llm.base_url": $("ai-base-url").value.trim(),
    "security.llm.model": $("ai-model").value.trim(),
    "security.llm.strict_mode": $("ai-strict-mode").checked
  };
  var key = $("ai-api-key").value;
  if (key) body["security.llm.api_key"] = key;
  api("PUT", "/api/admin/settings", body).then(function() {
    toast(t("msg.saved"));
    $("ai-api-key").value = "";
  }).catch(function(e) {
    toast(e.message, true);
  });
});

// ── global settings page (v0.8.0) ─────────────────────────────
function loadSettings() {
  return api("GET", "/api/admin/settings").then(function(d) {
    $("settings-degraded").style.display = "none";
    $("settings-main").style.display = "";
    renderSettings(d);
  }).catch(function(e) {
    if (e.status === 404 || e.status === 501) {
      showDegraded("settings");
    } else {
      toast(e.message, true);
    }
  });
}

function settingText(prefix, key, fallback){
  var name = prefix + key;
  return (I18N[state.lang] || {})[name] || I18N.en[name] || fallback;
}
function settingMessage(key, restart){
  var el = $("settings-feedback");
  el.textContent = t(key);
  el.className = restart ? "restart" : "";
  el.hidden = false;
}
function settingValue(s){
  if (s.secret && s.value) return "••••••••";
  if (s.type === "bool") return t(s.value ? "settings.enabled" : "settings.disabled");
  if (s.value == null || s.value === "") return t("settings.empty");
  return typeof s.value === "object" ? JSON.stringify(s.value) : String(s.value);
}
function makeSettingRow(s){
  var row = document.createElement("div");
  row.className = "setting-row";
  row.dataset.key = s.key;
  var label = settingText("settings.label.", s.key, s.label || s.key);
  var description = settingText("settings.description.", s.key, s.description || "");
  var source = s.source || "default";
  var fromDatabase = source === "database" || source === "db";
  var readOnly = !!s.readonly || source === "environment";
  var sourceClass = fromDatabase ? "db" : (source === "yaml" || source === "file") ? "file" : "default";
  row.innerHTML = '<div class="s-label"><div class="setting-name">' + esc(label) + '</div>' +
    '<div class="setting-key">' + esc(s.key) + '</div>' +
    '<div class="setting-description">' + esc(description) + '</div>' +
    '<div class="setting-meta"><span class="src-badge ' + sourceClass + '">' +
      esc(settingText("settings.source.", source, source)) + '</span>' +
    (s.scope ? '<span class="scope-badge ' + esc(s.scope) + '">' +
      esc(settingText("settings.scope.", s.scope, s.scope)) + '</span>' : '') + '</div></div>' +
    '<div class="s-value">' + esc(settingValue(s)) + '</div>';
  var actions = document.createElement("div");
  actions.className = "setting-actions";
  row.appendChild(actions);
  if (readOnly){
    var lockNote = document.createElement("span");
    lockNote.className = "setting-description";
    lockNote.textContent = t(source === "environment" ? "settings.environment" : "settings.readonly");
    actions.appendChild(lockNote);
    return row;
  }
  var edit = document.createElement("button");
  edit.type = "button";
  edit.className = "setting-edit";
  edit.textContent = t("settings.edit");
  edit.setAttribute("aria-label", t("settings.edit") + " " + label);
  edit.setAttribute("aria-expanded", "false");
  actions.appendChild(edit);
  var editor = document.createElement("form");
  editor.className = "setting-editor";
  editor.hidden = true;
  var input = document.createElement(s.type === "bool" || s.options ? "select" : s.type === "json" ? "textarea" : "input");
  input.id = "setting-" + s.key.replace(/[^a-z0-9-]/gi, "-");
  input.name = s.key;
  input.setAttribute("aria-label", t("settings.value.label", {key:label}));
  edit.setAttribute("aria-controls", input.id + "-editor");
  editor.id = input.id + "-editor";
  if (input.tagName === "SELECT"){
    var options = s.type === "bool" ? [true, false] : s.options;
    options.forEach(function(value){
      var option = document.createElement("option");
      option.value = String(value);
      option.textContent = s.type === "bool" ? t(value ? "settings.enabled" : "settings.disabled") : value;
      input.appendChild(option);
    });
  } else if (input.tagName === "INPUT"){
    input.type = s.type === "int" || s.type === "float" ? "number" : s.secret ? "password" : "text";
    input.maxLength = 4096;
    if (s.type === "int" || s.type === "float"){
      input.required = true;
      input.step = s.step != null ? String(s.step) : s.type === "int" ? "1" : "any";
      if (s.min != null) input.min = String(s.min);
      if (s.max != null) input.max = String(s.max);
    }
    if (s.key === "server.host") input.required = true;
    input.autocomplete = "off";
  }
  var inputLabel = document.createElement("label");
  inputLabel.className = "setting-editor-label";
  inputLabel.htmlFor = input.id;
  inputLabel.textContent = label;
  editor.appendChild(inputLabel);
  editor.appendChild(input);
  var note = document.createElement("p");
  note.className = "setting-edit-note";
  note.textContent = t(s.scope === "restart" ? "settings.restart.needed" : "settings.inherited");
  editor.appendChild(note);
  var error = document.createElement("p");
  error.className = "setting-error";
  error.id = input.id + "-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  input.setAttribute("aria-describedby", error.id);
  editor.appendChild(error);
  input.addEventListener("invalid", function(ev){
    ev.preventDefault();
    error.textContent = input.validationMessage;
    error.hidden = false;
    input.setAttribute("aria-invalid", "true");
    input.focus();
  });
  input.addEventListener("input", function(){ error.hidden = true; input.removeAttribute("aria-invalid"); });
  var controls = document.createElement("div");
  controls.className = "setting-editor-controls";
  var save = document.createElement("button");
  save.type = "submit";
  save.className = "primary";
  save.textContent = t("btn.save");
  var cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = t("btn.cancel");
  controls.appendChild(save);
  controls.appendChild(cancel);
  editor.appendChild(controls);
  row.appendChild(editor);
  function closeEditor(){ editor.hidden = true; edit.setAttribute("aria-expanded", "false"); edit.focus(); }
  edit.addEventListener("click", function(){
    editor.hidden = !editor.hidden;
    edit.setAttribute("aria-expanded", String(!editor.hidden));
    if (!editor.hidden){
      input.value = s.secret ? "" : s.type === "json" ? JSON.stringify(s.value, null, 2) : String(s.value == null ? "" : s.value);
      error.hidden = true;
      input.removeAttribute("aria-invalid");
      input.focus();
    }
  });
  cancel.addEventListener("click", closeEditor);
  editor.addEventListener("keydown", function(ev){ if (ev.key === "Escape" && !save.disabled){ ev.stopPropagation(); closeEditor(); } });
  editor.addEventListener("submit", function(ev){
    ev.preventDefault();
    if (save.disabled || !editor.reportValidity()) return;
    var value = input.value;
    try {
      if (s.type === "bool") value = value === "true";
      else if (s.type === "int" || s.type === "float"){
        value = Number(value);
        if (!Number.isFinite(value)) throw new Error(t("settings.invalid.number"));
        if (s.type === "int" && !Number.isSafeInteger(value)) throw new Error(t("settings.invalid.int"));
      } else if (s.type === "json"){
        try { value = JSON.parse(value); } catch (e){ throw new Error(t("settings.invalid.json")); }
      }
    } catch (e){ error.textContent = e.message; error.hidden = false; input.setAttribute("aria-invalid", "true"); input.focus(); return; }
    var payload = {};
    payload[s.key] = value;
    // Lock before dispatch so keyboard submission has the same protection as a click.
    save.disabled = true;
    cancel.disabled = true;
    edit.disabled = true;
    input.disabled = true;
    save.textContent = t("settings.saving");
    save.setAttribute("aria-busy", "true");
    api("PUT", "/api/admin/settings", payload).then(function(result){
      var restart = (result.needs_restart || []).length > 0;
      settingMessage(restart ? "settings.saved.restart" : "settings.saved.hot", restart);
      return loadSettings();
    }).catch(function(e){
      error.textContent = e.message;
      error.hidden = false;
      input.setAttribute("aria-invalid", "true");
    }).finally(function(){
      save.disabled = cancel.disabled = edit.disabled = input.disabled = false;
      save.textContent = t("btn.save");
      save.removeAttribute("aria-busy");
      if (row.isConnected) input.focus();
      else focusSetting(s.key);
    });
  });
  if (fromDatabase){
    var reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = t("settings.reset");
    reset.className = "setting-reset";
    reset.addEventListener("click", function(){
      if (!window.confirm(t("settings.reset.confirm", {key:label}))) return;
      reset.disabled = true;
      edit.disabled = true;
      api("DELETE", "/api/admin/settings/" + encodeURIComponent(s.key)).then(function(){
        var restart = s.scope === "restart";
        settingMessage(restart ? "settings.reset.restart" : "settings.reset.hot", restart);
        return loadSettings();
      }).catch(function(e){ toast(e.message, true); })
        .finally(function(){ reset.disabled = edit.disabled = false; focusSetting(s.key); });
    });
    actions.appendChild(reset);
  }
  return row;
}
function focusSetting(key){
  var rows = document.querySelectorAll(".setting-row");
  Array.prototype.some.call(rows, function(row){
    if (row.dataset.key !== key) return false;
    var button = row.querySelector(".setting-edit");
    if (button) button.focus();
    return true;
  });
}
function renderSettings(data) {
  var grouped = {};
  var settings = data.settings || data.groups || {};
  if (Array.isArray(settings)){
    settings.forEach(function(s){
      var group = s.group || s.section || s.category || "general";
      (grouped[group] || (grouped[group] = [])).push(s);
    });
  } else grouped = settings;
  var order = ["server", "auth", "storage", "registry", "data", "watermark", "security", "admin", "general"];
  Object.keys(grouped).forEach(function(group){ if (order.indexOf(group) < 0) order.push(group); });
  var box = $("settings-groups");
  box.innerHTML = "";
  order.forEach(function(group){
    if (!Array.isArray(grouped[group]) || !grouped[group].length) return;
    var section = document.createElement("section");
    section.className = "settings-group";
    var heading = document.createElement("h3");
    heading.textContent = settingText("settings.group.", group, group);
    section.appendChild(heading);
    grouped[group].forEach(function(s){ section.appendChild(makeSettingRow(s)); });
    box.appendChild(section);
  });
  enhanceControls();
}

initPrefs();
start();
})();
</script>
</body>
</html>
"""
