"""Opt-in real browser: missing totals must fail rather than fabricate counts."""
import os
import pytest


def test_browser_requires_exact_count_and_stable_order():
    channel=os.environ.get('GOLIVE_TEST_BROWSER_CHANNEL')
    if not channel:pytest.skip('explicit browser channel not configured')
    from playwright.sync_api import sync_playwright
    from golive.inject.template_api import generate_js
    script=generate_js('large',mode='local',rest_url='http://127.0.0.1:9999/api/data')
    with sync_playwright() as p:
        browser=p.chromium.launch(**({} if channel=='chromium' else {'channel':channel}),headless=True)
        try:
            page=browser.new_page();page.set_content('<html><body>count contract</body></html>')
            page.evaluate("""() => {
              window.seen=[];
              window.fetch=async (url,init) => {window.seen.push(url);return new Response('[]',{status:200,headers:{'Content-Type':'application/json'}})};
            }""")
            page.add_script_tag(content=script[script.index('>')+1:script.rindex('</script>')])
            error=page.evaluate("async () => {try {await TemplateAPI.listAll({});return null;} catch(e){return e.message;}}")
            assert 'Exact row count unavailable' in error
            assert 'id.asc' in page.evaluate('decodeURIComponent(window.seen[0])')
            page.evaluate("() => {window.fetch=async()=>new Response('[]',{status:200,headers:{'Content-Range':'0-0/12050'}})}")
            assert page.evaluate('async()=> (await TemplateAPI.listAll({})).total')==12050
        finally:browser.close()
