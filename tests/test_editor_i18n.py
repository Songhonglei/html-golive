"""Execute the generated editor, including its 409/draft flow, in Node."""

import json
import re
import shutil
import subprocess

import pytest

from golive.inject.editor import generate_js


_HARNESS = r"""
const vm = require('node:vm');
const cfg = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = new Map();
class Element {
  constructor(tag) { this.tagName=tag;this.children=[];this.style={};this.attrs={};this.listeners={};
    this.classList={add(){},remove(){}};this.textContent='';this.value=''; }
  appendChild(node) { this.children.push(node);if(node.id)nodes.set(node.id,node);node.parentNode=this;return node; }
  setAttribute(k,v) { this.attrs[k]=v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k,v) { this.listeners[k]=v; }
  removeEventListener(k) { delete this.listeners[k]; }
  remove() { nodes.delete(this.id); }
  showModal() { this.open=true; }
  close() { this.open=false; }
  focus() {}
  closest() { return null; }
}
const editable = new Element('h1');editable.childNodes=[{nodeType:3,textContent:'Draft'}];
const root = new Element('html');root.getAttribute=()=>cfg.pageLang;
root.cloneNode=()=>({querySelectorAll:()=>[],querySelector:()=>null,outerHTML:'<html><body>LOCAL DRAFT</body></html>'});
const document={documentElement:root,head:new Element('head'),body:new Element('body'),readyState:'complete',
  createElement:tag=>new Element(tag),getElementById:id=>nodes.get(id)||null,
  querySelectorAll:()=>[editable],addEventListener(){},removeEventListener(){}};
if(!cfg.missingRevision) nodes.set('__golive_revision__',{content:'a'.repeat(64)});
const listeners={};let reloads=0;let requests=[];let confirmations=[];
const context={document,navigator:{language:cfg.browserLang},URLSearchParams,
  location:{search:'?edit=1',pathname:'/demo',hash:'',reload(){reloads++;}},history:{replaceState(){}},
  sessionStorage:{getItem:()=>'',setItem(){}},
  localStorage:{getItem(){if(cfg.storageBlocked)throw new Error('blocked');return cfg.preference;}},
  confirm(message){confirmations.push(message);return false;},
  setTimeout:()=>1,clearTimeout(){},
  DOMParser:class {parseFromString(){return {getElementById:()=>null,documentElement:{outerHTML:'SERVER CONTENT'}};}},
  fetch(url,options){requests.push({url,method:options.method||'GET',revision:(options.headers||{})['If-Match']});
    if(options.method==='PUT')return Promise.resolve({ok:false,status:409,json:()=>Promise.resolve({code:'edit_conflict',error:'server conflict'})});
    return Promise.resolve({ok:!cfg.readFailure,status:cfg.readFailure?503:200,json:()=>Promise.resolve({html:'SERVER CONTENT'})});},
};
context.window=context;context.addEventListener=(key,fn)=>{listeners[key]=fn;};context.removeEventListener=key=>{delete listeners[key];};
vm.runInNewContext(cfg.script,context);
editable.listeners.input();
nodes.get('__golive_editor_save__').onclick();
(async()=>{
  await new Promise(setImmediate);await new Promise(setImmediate);
  const panel=nodes.get('__golive_editor_compare__');
  let result={save:nodes.get('__golive_editor_save__').textContent,cancel:nodes.get('__golive_editor_cancel__').textContent,
    image:nodes.get('__golive_editor_img__').textContent,status:nodes.get('__golive_editor_status__').textContent};
  if(panel){
    const areas=panel.children.filter(x=>x.tagName==='textarea');const buttons=panel.children.filter(x=>x.tagName==='button');
    Object.assign(result,{title:panel.children[0].textContent,labels:areas.map(a=>a.attrs['aria-label']),values:areas.map(a=>a.value),
      buttons:buttons.map(b=>b.textContent)});
    buttons[1].onclick();buttons[0].onclick();result.closed=!panel.open;
  }
  let guarded=false;listeners.beforeunload({preventDefault(){guarded=true;}});
  Object.assign(result,{requests,confirmations,reloads,guarded});console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


def run_editor(**kwargs):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    script = re.search(r'<script[^>]*>(.*?)</script>', generate_js('demo'), re.S).group(1)
    config = dict(script=script, pageLang='en', browserLang='en', preference=None)
    config.update(kwargs)
    result = subprocess.run([node, '-e', _HARNESS], input=json.dumps(config),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('page,preference,browser,blocked,language', [
    ('en', None, 'zh-CN', False, 'en'),
    ('zh-Hans', None, 'en-US', False, 'zh'),
    ('', None, 'zh-TW', False, 'zh'),
    ('', None, 'en-GB', False, 'en'),
    ('fr', None, 'zh', False, 'en'),
    ('en', 'zh', 'en', False, 'zh'),
    ('zh', 'en', 'zh', False, 'en'),
    ('en', None, 'zh', True, 'en'),
    ('zh', 'invalid', 'en', False, 'zh'),
])
def test_conflict_localizes_labels_controls_confirmation_and_preserves_draft(page, preference, browser, blocked, language):
    result = run_editor(pageLang=page, preference=preference, browserLang=browser, storageBlocked=blocked)
    if language == 'en':
        assert result['title'] == 'Someone else updated this page. Your draft is not saved.'
        assert result['labels'] == ['Local draft (copy to keep)', 'Latest server content']
        assert result['buttons'] == ['Keep my draft', 'Discard draft and reload']
        assert result['save'] == '💾 Save' and result['cancel'] == '✕ Cancel' and result['image'] == '🖼 Image'
        assert result['confirmations'] == ['Discard your local draft? Copy any changes you want to keep first.']
        assert 'Compare the latest version' in result['status']
    else:
        assert result['title'] == '内容已被其他编辑者更新，草稿尚未保存'
        assert result['labels'] == ['本地草稿（可复制保留）', '服务器最新内容']
        assert result['buttons'] == ['继续保留草稿', '放弃草稿并重新加载']
        assert result['save'] == '💾 保存' and result['cancel'] == '✕ 取消' and result['image'] == '🖼 图片'
        assert result['confirmations'] == ['确定放弃本地草稿？请先复制需要保留的内容。']
        assert '内容已变更' in result['status']
    assert 'LOCAL DRAFT' in result['values'][0] and 'SERVER CONTENT' in result['values'][1]
    assert result['closed'] and result['guarded'] and result['reloads'] == 0
    assert [r['method'] for r in result['requests']] == ['PUT', 'GET']
    assert result['requests'][0]['revision'] == '"' + 'a'*64 + '"'


@pytest.mark.parametrize('language,error', [('en','Could not read the latest content: HTTP 503'), ('zh','读取失败：HTTP 503')])
def test_conflict_latest_read_failure_is_localized_and_draft_stays(language, error):
    result = run_editor(pageLang=language, readFailure=True)
    assert result['values'][1] == error
    assert 'LOCAL DRAFT' in result['values'][0] and result['guarded'] and not result['reloads']


@pytest.mark.parametrize('language,message', [('en','Content revision missing'), ('zh','缺少内容版本')])
def test_missing_revision_keeps_draft_with_localized_guidance(language, message):
    result = run_editor(pageLang=language, missingRevision=True)
    assert message in result['status']
    assert result['requests'] == [] and result['guarded']
