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


def render_admin_page(identity=None) -> str:
    """Build the portal HTML. ``identity`` may be None (token shell)."""
    boot = {
        "authenticated": identity is not None,
        "email": getattr(identity, "email", "") or "",
        "superadmin": bool(getattr(identity, "is_superadmin", False)),
        "version": __version__,
    }
    return _PAGE_TEMPLATE.replace("__GOLIVE_BOOT__", json_for_script(boot))


_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>golive · admin</title>
<style>
:root{
  --bg:#0f1419;--panel:#171e26;--panel2:#1d2630;--line:#2a3542;
  --text:#dce3ea;--muted:#8296a8;--accent:#4da3ff;--accent2:#2f80e0;
  --ok:#3fb96f;--warn:#e0a63c;--danger:#e05c5c;--radius:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);
  font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}
button{font:inherit;cursor:pointer;border:1px solid var(--line);
  background:var(--panel2);color:var(--text);border-radius:6px;
  padding:6px 14px;transition:background .15s}
button:hover{background:#243040}
button.primary{background:var(--accent2);border-color:var(--accent2);color:#fff}
button.primary:hover{background:var(--accent)}
button.danger{background:transparent;border-color:var(--danger);color:var(--danger)}
button.danger:hover{background:rgba(224,92,92,.12)}
button:disabled{opacity:.45;cursor:not-allowed}
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
  background:rgba(77,163,255,.08)}
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
tbody tr:hover{background:rgba(77,163,255,.05)}
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
#drawer-mask{position:fixed;inset:0;background:rgba(0,0,0,.5);
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
  <p>该服务启用了 Token 认证，请输入访问令牌（GOLIVE_TOKEN）。令牌仅保存在本浏览器的 sessionStorage。</p>
  <input type="password" id="gate-token" placeholder="access token"
         autocomplete="off">
  <button class="primary" id="gate-enter" style="width:100%">进入门户</button>
</div>

<div id="layout" style="display:none">
  <div id="sidebar">
    <div id="logo">🚀 golive <small id="ver"></small></div>
    <div class="nav-item active" data-view="sites">站点管理</div>
    <div class="nav-item hidden" data-view="stats" id="nav-stats">统计</div>
    <div class="nav-item hidden" data-view="audit" id="nav-audit">审计日志</div>
    <div id="whoami"></div>
  </div>

  <div id="main">
    <!-- sites -->
    <div class="view active" id="view-sites">
      <h2>站点管理</h2>
      <div class="toolbar">
        <input type="text" id="site-q" placeholder="搜索 slug / 名称…"
               style="width:240px">
        <button id="site-search">搜索</button>
        <div class="spacer"></div>
        <span id="site-count" style="color:var(--muted);font-size:13px"></span>
      </div>
      <table>
        <thead><tr>
          <th>名称</th><th>slug</th><th>owner</th><th>角色</th>
          <th>大小</th><th>更新时间</th><th>操作</th>
        </tr></thead>
        <tbody id="site-rows"></tbody>
      </table>
      <div class="pager">
        <button id="site-prev">‹ 上一页</button>
        <span id="site-page"></span>
        <button id="site-next">下一页 ›</button>
      </div>
    </div>

    <!-- stats -->
    <div class="view" id="view-stats">
      <h2>统计</h2>
      <div class="cards" id="stat-cards"></div>
      <h2 style="font-size:15px">Top 10 站点（按大小）</h2>
      <table>
        <thead><tr><th>#</th><th>slug</th><th>名称</th><th>大小</th></tr></thead>
        <tbody id="stat-top"></tbody>
      </table>
    </div>

    <!-- audit -->
    <div class="view" id="view-audit">
      <h2>审计日志</h2>
      <div class="toolbar">
        <input type="text" id="audit-slug" placeholder="按 slug 过滤" style="width:170px">
        <input type="text" id="audit-action" placeholder="按 action 过滤" style="width:170px">
        <button id="audit-search">过滤</button>
      </div>
      <table>
        <thead><tr><th>时间</th><th>操作人</th><th>action</th><th>slug</th><th>详情</th></tr></thead>
        <tbody id="audit-rows"></tbody>
      </table>
      <div class="pager">
        <button id="audit-prev">‹ 上一页</button>
        <span id="audit-page"></span>
        <button id="audit-next">下一页 ›</button>
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
    <h4>基本信息</h4>
    <div class="frow"><label>名称</label>
      <input type="text" id="d-name" maxlength="200"></div>
    <div class="frow"><label>备注</label>
      <input type="text" id="d-notes" maxlength="2000"></div>
    <div class="frow"><label>在线编辑</label>
      <input type="checkbox" id="d-editable"></div>
    <button class="primary" id="d-save">保存</button>
  </div>

  <div class="section" id="sec-maint">
    <h4>Maintainers</h4>
    <div class="tags" id="d-maints"></div>
    <div class="frow">
      <input type="text" id="d-maint-email" placeholder="email@example.com"
             style="flex:1">
      <button id="d-maint-add">添加</button>
    </div>
  </div>

  <div class="section" id="sec-transfer">
    <h4>移交 Owner</h4>
    <div class="frow">
      <input type="text" id="d-transfer-to" placeholder="新 owner 邮箱"
             style="flex:1">
      <button id="d-transfer">移交</button>
    </div>
  </div>

  <div class="section">
    <h4>快照 / 回滚</h4>
    <div id="d-snaps"></div>
  </div>

  <div class="section" id="sec-delete">
    <h4 style="color:var(--danger)">删除站点</h4>
    <div class="frow">
      <input type="text" id="d-del-confirm" placeholder="输入 slug 以确认"
             style="flex:1">
      <button class="danger" id="d-delete">删除</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
(function(){
"use strict";
var BOOT = window.GOLIVE_BOOT || {};
var TOKEN_KEY = "golive_admin_token";
var state = {
  me: null, page: 1, size: 20, q: "",
  auditPage: 1, current: null
};

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
  var t = $("toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  t.style.display = "block";
  clearTimeout(t._h);
  t._h = setTimeout(function(){ t.style.display = "none"; }, 3200);
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
function start(){
  api("GET", "/api/admin/me").then(function(me){
    state.me = me;
    $("login-gate").style.display = "none";
    $("layout").style.display = "flex";
    $("ver").textContent = "v" + (BOOT.version || "");
    var who = me.identity || {};
    $("whoami").textContent = (who.email || "(token)") +
      (who.superadmin ? " · 超管" : "");
    if (who.superadmin){
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
      tb.innerHTML = '<tr><td colspan="7" class="empty">没有站点</td></tr>';
    }
    d.sites.forEach(function(s){
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + esc(s.name || "(未命名)") + "</td>" +
        "<td>" + (s.slug ? '<a href="/' + esc(s.slug) +
                  '" target="_blank" rel="noopener">' + esc(s.slug) +
                  "</a>" : '<span class="badge">无</span>') + "</td>" +
        "<td>" + esc(s.owner || "—") + "</td>" +
        '<td><span class="badge ' + esc(s.role) + '">' +
          esc(s.role || "—") + "</span></td>" +
        "<td>" + fmtBytes(s.size) + "</td>" +
        "<td>" + esc((s.updated_at || "").replace("T", " ")) + "</td>" +
        '<td class="actions"><button data-act="open">详情</button></td>';
      tr.querySelector('[data-act="open"]').addEventListener(
        "click", function(){ openDrawer(s.slug || s.site_id); });
      tb.appendChild(tr);
    });
    $("site-count").textContent = "共 " + d.total + " 个站点";
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
    toast("已保存");
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

function renderMaints(list){
  var box = $("d-maints");
  box.innerHTML = list.length ? "" :
    '<span style="color:var(--muted);font-size:12px">暂无 maintainer</span>';
  list.forEach(function(m){
    var t = document.createElement("span");
    t.className = "tag";
    t.innerHTML = esc(m) + " <b title='移除'>×</b>";
    t.querySelector("b").addEventListener("click", function(){
      api("DELETE", "/api/admin/sites/" + curRef() + "/maintainers",
          {email: m})
      .then(function(d){ renderMaints(d.maintainers); toast("已移除"); })
      .catch(function(e){ toast(e.message, true); });
    });
    box.appendChild(t);
  });
}
$("d-maint-add").addEventListener("click", function(){
  var email = $("d-maint-email").value.trim();
  if (!email) return;
  api("POST", "/api/admin/sites/" + curRef() + "/maintainers", {email: email})
  .then(function(d){
    $("d-maint-email").value = "";
    renderMaints(d.maintainers);
    toast("已添加");
  }).catch(function(e){ toast(e.message, true); });
});

$("d-transfer").addEventListener("click", function(){
  var to = $("d-transfer-to").value.trim();
  if (!to) return;
  if (!window.confirm("确认将站点移交给 " + to +
      " ？移交后你可能失去管理权限。")) return;
  api("POST", "/api/admin/sites/" + curRef() + "/transfer", {to: to})
  .then(function(){
    toast("已移交给 " + to);
    closeDrawer();
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

function renderSnaps(snaps){
  var box = $("d-snaps");
  box.innerHTML = snaps.length ? "" :
    '<div style="color:var(--muted);font-size:12px">暂无快照</div>';
  snaps.forEach(function(sn){
    var row = document.createElement("div");
    row.className = "snap-row";
    row.innerHTML = '<span class="ts">' + esc(sn.ts) + "</span>" +
      "<span>" + fmtBytes(sn.size) + "</span>" +
      "<button data-a='rb'>回滚</button>";
    row.querySelector("[data-a='rb']").addEventListener("click", function(){
      if (!window.confirm("回滚到快照 " + sn.ts +
          " ？当前版本会先自动存为新快照。")) return;
      api("POST", "/api/admin/sites/" + curRef() + "/rollback",
          {snapshot: sn.ts})
      .then(function(){
        toast("已回滚");
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
    toast("请输入 " + ref + " 以确认删除", true);
    return;
  }
  api("DELETE", "/api/admin/sites/" + curRef(), {confirm: ref})
  .then(function(){
    toast("已删除 " + ref);
    closeDrawer();
    loadSites();
  }).catch(function(e){ toast(e.message, true); });
});

// ── stats ──────────────────────────────────────────────────────
function loadStats(){
  api("GET", "/api/admin/stats").then(function(d){
    var cards = [
      ["站点总数", d.total_sites],
      ["总大小", fmtBytes(d.total_bytes)],
      ["近7天有更新", d.updated_last_7d],
      ["开启在线编辑", d.editable_sites]
    ];
    $("stat-cards").innerHTML = cards.map(function(c){
      return '<div class="card"><div class="lbl">' + esc(c[0]) +
             '</div><div class="num">' + esc(c[1]) + "</div></div>";
    }).join("");
    $("stat-top").innerHTML = (d.top_sites || []).map(function(t, i){
      return "<tr><td>" + (i+1) + "</td><td>" + esc(t.slug) + "</td><td>" +
        esc(t.name) + "</td><td>" + fmtBytes(t.size) + "</td></tr>";
    }).join("") || '<tr><td colspan="4" class="empty">暂无数据</td></tr>';
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
    }).join("") || '<tr><td colspan="5" class="empty">暂无记录</td></tr>';
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

start();
})();
</script>
</body>
</html>
"""
