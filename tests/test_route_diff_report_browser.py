"""Optional local Chromium acceptance tests: ALRED_TEST_ROUTE_BROWSER=1.

Requires Playwright and a locally installed browser. No network or device access.
"""
from copy import deepcopy
import json
import os
import re
from pathlib import Path

import pytest

if os.environ.get('ALRED_TEST_ROUTE_BROWSER') != '1':
    pytest.skip('Opt-in offline browser acceptance suite', allow_module_level=True)
playwright = pytest.importorskip('playwright.sync_api')

from alred.route_diff.comparator import compare_snapshots
from alred.route_diff.parser import parse_route_source
from alred.route_diff.report import build_report_model, render_html, write_route_report
from alred.route_diff.snapshot import build_snapshot
from test_route_diff_report import inputs, model  # shared production parser fixtures


@pytest.fixture(scope='module')
def report(inputs,tmp_path_factory):
    out=tmp_path_factory.mktemp('browser')/'route_diff'
    write_route_report(*inputs,out)
    return out


@pytest.fixture(scope='module')
def browser():
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser,report):
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors,external=[],[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(('file:','blob:')) else None)
    page.goto((report/'index.html').as_uri())
    yield page
    page.close()
    assert not errors,errors
    assert not external,external


def test_mode_cost_common_ecmp_and_summary_links(page):
    assert page.locator('.route-group').count()==9
    assert not page.is_checked('#show-unchanged')
    page.select_option('#host','leaf01');page.select_option('#af','ipv4')
    page.fill('#query','192.0.2.64/26')
    page.select_option('#mode','route-ad')
    assert page.locator('.route-group').count()==0
    page.select_option('#mode','route-ad-cost')
    assert 'Cost: 20' in page.locator('#routes').inner_text()
    assert 'Cost: 30' in page.locator('#routes').inner_text()
    assert page.locator('.pair').count()==2  # No NH inference in AD + Cost mode.
    page.select_option('#mode','route-ad-cost-nexthop')
    assert page.locator('.pair.attributes').count()==1
    page.fill('#query','198.51.100.128/25')
    assert page.locator('.pair').count()==1
    page.check('#show-unchanged')
    assert page.locator('.pair').count()==2
    page.click('[data-tab=summary]')
    assert page.locator('#scope-summary tbody tr').count()==25
    page.locator('#scope-summary tbody button').first.click()
    assert page.locator('[data-panel=compare]').is_visible()
    assert page.input_value('#change') in ['ADDED','REMOVED','MODIFIED']
    assert page.locator('.route-group').count()>0


def test_strict_prefix_search_and_unknown_stays_visible(page):
    page.check('#show-unchanged');page.select_option('#search-kind','cidr')
    page.fill('#query','192.0.2.0/24')
    assert page.locator('.route-group').count()==3
    page.fill('#query','192.0.2.1/24')
    assert 'host bit' in page.locator('#query-error').inner_text()
    assert page.locator('.route-group').count()==0
    page.fill('#query','2001:0db8:0001:0000:0000:0000:0000:0000/64')
    assert not page.locator('#query-error').inner_text()
    page.fill('#query','::ffff:192.0.2.0/120')
    assert not page.locator('#query-error').inner_text()
    page.fill('#query','::ffff:192.0.2.1/120')
    assert 'host bit' in page.locator('#query-error').inner_text()
    page.select_option('#reason','METRIC_CHANGED')
    assert 'UNKNOWN scope: 1' in page.locator('#quality').inner_text()


def test_long_evidence_is_collapsed_and_unknown_link_opens_only_target(page):
    original = page.evaluate('R.summary')
    page.click('[data-tab=summary]')
    root = page.locator('#evidence-panels')
    assert root.locator('details[open]').count() == 0
    assert root.locator('pre').count() == 0  # JSON is not rendered until opened.
    unknown = page.locator('#quality-details > details').filter(has_text='leaf03')
    assert 'UNKNOWN：after: 取得が不完全' in unknown.inner_text()
    assert page.locator('#quality-details > pre').count() == 0
    assert '6 入力' in page.locator('#sources-summary').inner_text()
    page.locator('#scope-summary button').filter(has_text='UNKNOWN').first.click()
    playwright.expect(unknown).to_have_attribute('open', '')
    playwright.expect(unknown.locator('pre')).to_be_visible()
    assert root.locator('details[open]').count() == 1
    assert json.loads(unknown.locator('pre').inner_text())['diagnostics'][0]['code'] == 'SCOPE_INCOMPLETE'
    assert unknown.locator('pre').evaluate('(e)=>e.clientHeight <= 340')
    # Native summary works with the keyboard, and closing does not lose evidence.
    unknown.locator('summary').focus()
    page.keyboard.press('Enter')
    playwright.expect(unknown.locator('pre')).to_be_hidden()
    page.click('#sources-summary')
    children = page.locator('#sources-details > details')
    playwright.expect(children).to_have_count(6)
    assert children.locator('pre').count() == 0
    children.first.locator('summary').click()
    playwright.expect(children.first.locator('pre')).to_be_visible()
    assert json.loads(children.first.locator('pre').inner_text()) == page.evaluate('D.sources[0].meta')
    page.locator('#comparison-details > summary').click()
    playwright.expect(page.locator('#source-details')).to_be_visible()
    assert json.loads(page.locator('#source-details').inner_text())['comparison_fingerprint'] == page.evaluate('R.comparison_fingerprint')
    page.click('#policy-summary')
    playwright.expect(page.locator('#policy-results')).to_be_visible()
    assert json.loads(page.locator('#policy-results').inner_text()) == page.evaluate('R.policy_results')
    assert page.evaluate('R.summary') == original


def test_unscoped_evidence_and_policy_counts_remain_visible(page,model,tmp_path):
    data=deepcopy(model)
    diagnostic=dict(device='unscoped-host',side='after',code='UNSCOPED_SOURCE',diagnostics=['<script>never execute</script>'])
    data['result']['diagnostics'].append(diagnostic)
    data['result']['policy_results']['required_routes']=[dict(result='FAIL',reason='missing')]
    out=tmp_path/'unscoped.html';out.write_text(render_html(data))
    page.goto(out.as_uri());page.click('[data-tab=summary]')
    detail=page.locator('#quality-details > details').filter(has_text='unscoped-host')
    assert 'UNKNOWN：after: 取得範囲を特定できない入力' in detail.inner_text()
    assert detail.locator('pre').count()==0
    assert 'FAIL 1' in page.locator('#policy-summary').inner_text()
    detail.locator('summary').click()
    playwright.expect(detail.locator('pre')).to_be_visible()
    assert json.loads(detail.locator('pre').inner_text())==diagnostic


def test_evidence_jump_both_sides_and_return_preserves_filters(page):
    page.fill('#query','192.0.2.64/26');page.select_option('#mode','route-ad-cost')
    page.locator('.route-footer button').first.click()
    assert page.locator('[data-panel=raw]').is_visible()
    assert not page.is_checked('#raw-sync')
    assert page.locator('#raw-before .evidence-hit').count()==2
    assert page.locator('#raw-after .evidence-hit').count()==2
    assert page.locator('#raw-before .evidence-hit').first.get_attribute('data-line')=='18'
    assert page.locator('#raw-after .evidence-hit').first.get_attribute('data-line')=='17'
    page.click('#return-compare')
    assert page.input_value('#query')=='192.0.2.64/26'
    assert page.input_value('#mode')=='route-ad-cost'
    assert page.locator('.route-group').count()==1


def test_raw_literal_search_and_download_preserve_original(page,inputs):
    page.click('[data-tab=raw]');page.fill('#raw-query','[110/30]')
    assert '一致 1 行' in page.locator('#raw-hits').inner_text()
    assert page.locator('#raw-before .raw-line').count()==36
    page.click('#next-hit');assert not page.is_checked('#raw-sync')
    page.select_option('#raw-color','literal')
    playwright.expect(page.locator('#raw-progress')).to_have_text(re.compile('^文字列 diff 完了'))
    assert page.is_disabled('#raw-mode')
    assert page.locator('#raw-before .removed').count()>0
    page.select_option('#raw-color','semantic')
    assert not page.is_disabled('#raw-mode')
    with page.expect_download() as download:
        page.locator('#meta-before button').click()
    assert Path(download.value.path()).read_bytes()==inputs[3]['before','leaf01']


def test_review_export_restore_rejects_fingerprint_and_invalid_date_atomically(page):
    page.fill('#query','192.0.2.64/26')
    page.locator('.review input[type=checkbox]').check()
    page.locator('.review input:not([type=checkbox])').fill('Cost を確認')
    assert '未保存' in page.locator('#review-state').inner_text()
    with page.expect_download() as download:page.click('#export-review')
    record=json.loads(Path(download.value.path()).read_text())
    assert record['entries'][0]['comment']=='Cost を確認'
    page.reload()
    def upload(doc):page.set_input_files('#import-review',{'name':'review.json','mimeType':'application/json','buffer':json.dumps(doc).encode()})
    upload(record)
    playwright.expect(page.locator('#review-state')).to_contain_text('復元')
    page.fill('#query','192.0.2.64/26')
    assert page.is_checked('.review input[type=checkbox]')
    for mutation in ['fingerprint','key','bad_date','duplicate']:
        bad=deepcopy(record)
        if mutation=='fingerprint':bad['comparison_fingerprint']='sha256:'+'0'*64
        elif mutation=='key':bad['entries'][0]['entry_key']='sha256:'+'0'*64
        elif mutation=='bad_date':bad['entries'][0]['reviewed_at']='2026-02-30T00:00:00Z'
        else:bad['entries'].append(deepcopy(bad['entries'][0]))
        upload(bad)
        playwright.expect(page.locator('#review-error')).not_to_be_empty()
        assert page.is_checked('.review input[type=checkbox]')
        assert page.input_value('.review input:not([type=checkbox])')=='Cost を確認'


def test_host_html_entry_defaults(page,report):
    for name,raw in [('route-diff.html',False),('route-diff-diffonly.html',False),('route-diff-raw.html',True)]:
        page.goto((report/'hosts/leaf02'/name).as_uri())
        assert page.input_value('#host')=='leaf02'
        assert not page.is_checked('#show-unchanged')
        assert page.locator('[data-panel=raw]').is_visible()==raw


def test_untrusted_raw_text_is_never_html(page,model,tmp_path):
    unsafe=deepcopy(model)
    next(s for s in unsafe['sources'] if s['meta']['device']=='leaf01' and s['meta']['side']=='before')['lines'][0]='</script><img src="https://example.invalid/" onerror="window.injected=true">'
    out=tmp_path/'injection.html';out.write_text(render_html(unsafe))
    page.goto(out.as_uri());page.click('[data-tab=raw]')
    assert '<img' in page.locator('#raw-before').inner_text()
    assert page.locator('img').count()==0
    assert page.evaluate('window.injected===undefined')


@pytest.fixture(scope='module')
def large_report(tmp_path_factory):
    snapshots,raw=[],{}
    for side,cost in [('before',20),('after',30)]:
        lines=['leaf01# show ip route','IP Route Table for VRF "default"']
        for i in range(601):
            lines += [f'10.{i//256}.{i%256}.0/24, ubest/mbest: 1/0',f' *via 192.0.2.1, Ethernet1/1, [110/{cost}], static']
        lines += ['leaf01#']
        data=('\n'.join(lines)+'\n').encode();raw[side,'s']=data
        parsed=parse_route_source(data,source_id='s',device='leaf01')
        snapshots.append(build_snapshot([parsed],side=side))
    model=build_report_model(*snapshots,compare_snapshots(*snapshots),raw)
    out=tmp_path_factory.mktemp('large')/'index.html';out.write_text(render_html(model))
    return out


def test_paging_navigation_and_raw_dom_bound(page,large_report):
    page.goto(large_report.as_uri())
    assert page.locator('.route-group').count()==100
    assert 'MODIFIED 601' in page.locator('#counts').inner_text()
    page.select_option('#page-size','50')
    assert page.locator('.route-group').count()==50
    # Navigate across a page boundary using the same controls as a reader.
    for _ in range(51):page.click('#next-diff')
    assert '2 / 13' in page.locator('#page-position').inner_text()
    assert '51 / 601' in page.locator('#diff-position').inner_text()
    assert page.locator('.focused').count()==1
    page.select_option('#page-size','500')
    assert page.locator('.route-group').count()==500
    page.click('#next-page')
    assert page.locator('.route-group').count()==101
    assert page.is_disabled('#next-page')
    page.click('[data-tab=raw]')
    for side in ['before','after']:
        assert page.locator('#raw-'+side+' .raw-line').count()<=226
    page.select_option('#raw-scope','all')  # This case verifies the complete input including the idle prompt.
    page.locator('#raw-before').evaluate('(e)=>e.scrollTop=e.scrollHeight')
    playwright.expect(page.locator('#raw-before .raw-line').last).to_have_attribute('data-line','1205')
    playwright.expect(page.locator('#raw-after .raw-line').last).to_have_attribute('data-line','1205')
    assert page.locator('#raw-before .raw-line').count()<=226
    assert page.locator('#raw-before .raw-line').last.inner_text().endswith('leaf01#')
    # Cancel in the first cooperative yield; no partial color result is published.
    page.evaluate("document.getElementById('raw-color').value='literal';document.getElementById('raw-color').dispatchEvent(new Event('change'));document.getElementById('cancel-literal').click()")
    assert '計算を中止' in page.locator('#raw-progress').inner_text()
    assert page.locator('#raw-before .removed').count()==0


def test_cli_labels_and_restored_review(page,tmp_path):
    from alred.cli import build_parser
    root=Path(__file__).resolve().parents[1]
    base=['route-diff-nxos','--before',str(root/'tests/fixtures/nxos/route_diff/synthetic/leaf01-before-route.txt'),
          '--after',str(root/'tests/fixtures/nxos/route_diff/synthetic/leaf01-after-route.txt'),'--input-format','nxos-transcript','--no-progress']
    args=build_parser().parse_args(base+['--output-dir',str(tmp_path/'first')]);assert args.func(args)==0
    d=json.loads((tmp_path/'first/route-diff.json').read_text())
    entry=next(e for e in d['entries'] if e['prefix']=='192.0.2.64/26')
    record=dict(schema_version=1,kind='RouteDiffReview',comparison_fingerprint=d['comparison_fingerprint'],entries=[dict(entry_key=entry['entry_key'],
                resource={k:entry[k] for k in ('device','vrf','family','prefix')},mode=entry['mode'],status='REVIEWED',comment='CLI 復元',reviewed_at='2026-09-13T01:02:03Z')])
    file=tmp_path/'review.json';file.write_text(json.dumps(record))
    args=build_parser().parse_args(base+['--output-dir',str(tmp_path/'second'),'--before-label','作業前','--after-label','作業途中','--review',str(file)])
    assert args.func(args)==0
    page.goto((tmp_path/'second/index.html').as_uri());page.fill('#query','192.0.2.64/26')
    assert '作業前' in page.locator('.columns').inner_text() and '作業途中' in page.locator('.columns').inner_text()
    assert page.is_checked('.review input[type=checkbox]')
    assert page.input_value('.review input:not([type=checkbox])')=='CLI 復元'
    page.click('[data-tab=raw]')
    assert page.locator('.raw-title strong').first.inner_text()=='作業前'


def test_health_rollback_banner_retains_restoration_failure(browser, tmp_path):
    from test_health_route_diff import profile, build
    from alred.health.route_diff import assess_routes, publish_route_report

    resolved = profile(tmp_path)
    before, left, _ = build(tmp_path, resolved)
    rollback, right, _ = build(tmp_path, resolved, 'rollback', cost=30)
    assessment = assess_routes(before, rollback, resolved['spec']['resolved']['effective'], (left, right))
    artifacts = publish_route_report(assessment, (left, right), operation_root=tmp_path, report_dir=tmp_path/'report')
    page = browser.new_page()
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith('file:') else None)
    page.goto(Path(artifacts['route_diff_index']).as_uri())
    assert page.locator('#health-result').inner_text() == 'Health Route 判定 (rollback): FAIL'
    page.select_option('#mode', 'route-ad')
    assert page.locator('.route-group').count() == 0
    assert 'FAIL' in page.locator('#health-result').inner_text()
    page.locator('#health-result').click()
    assert 'rollback_residual_entries' in page.locator('#health-checks').inner_text()
    page.close()
    assert not errors
    assert not external


@pytest.fixture(scope='module')
def collection_report(tmp_path_factory):
    from test_route_diff_collection_fix import CASES, args
    from alred.route_diff.cli import execute
    root = tmp_path_factory.mktemp('collection-browser')
    options = args(root, before=str(CASES/'before.txt'), after=str(CASES/'after.txt'))
    assert execute(options) == 0
    return Path(options.output_dir)


def test_collection_raw_scope_search_and_original_line_numbers(page, collection_report):
    page.goto((collection_report/'index.html').as_uri())
    original = page.evaluate('R.summary')
    page.click('[data-tab=raw]')
    assert page.input_value('#raw-scope') == 'routes'
    assert page.locator('#raw-before [data-line="14"]').count() == 1
    assert page.locator('#raw-before [data-line="1"]').count() == 0
    assert '対象外 L1–L13 を省略' in page.locator('#raw-before').inner_text()
    assert '表示 26 / 全 45 行' in page.locator('#meta-before').inner_text()
    page.fill('#raw-query', 'Synthetic device')
    assert '一致 0 行' in page.locator('#raw-hits').inner_text()
    page.select_option('#raw-scope', 'all')
    assert page.locator('#raw-before [data-line]').count() == 45
    assert '一致 2 行' in page.locator('#raw-hits').inner_text()
    page.select_option('#raw-scope', 'routes')
    page.fill('#raw-query', 'segid:')
    page.select_option('#raw-color', 'literal')
    playwright.expect(page.locator('#raw-progress')).to_have_text(re.compile('^文字列 diff 完了'))
    assert page.locator('#raw-before [data-line="28"].removed').count() == 1
    assert page.locator('#raw-after [data-line="28"].added').count() == 1
    page.click('[data-tab=compare]');page.click('[data-tab=raw]')
    assert page.input_value('#raw-scope') == 'routes'
    assert page.evaluate('R.summary') == original


def test_completion_evidence_outside_route_range_switches_with_notice(page, collection_report):
    page.goto((collection_report/'index.html').as_uri())
    page.click('[data-tab=summary]')
    detail = page.locator('#quality-details > details').filter(has_text='EMPTY-VRF')
    assert '正常空' in detail.inner_text()
    detail.locator('summary').click()
    detail.get_by_role('button', name='before command 終端の元ログ').click()
    assert page.input_value('#raw-scope') == 'all'
    assert '表示範囲外' in page.locator('#raw-scope-status').inner_text()
    assert page.locator('#raw-before [data-line="40"].evidence-hit').count() == 1
    assert page.locator('#raw-before [data-line="44"].evidence-hit').count() == 1


def test_directory_missing_host_retains_unknown_and_source_selection(page, tmp_path):
    from test_route_diff_collection_fix import args
    from alred.route_diff.cli import execute
    options=args(tmp_path)
    assert execute(options)==3
    page.goto((Path(options.output_dir)/'index.html').as_uri())
    original=page.evaluate('R.summary')
    page.click('[data-tab=summary]')
    assert '両側取得済み 2 ホスト / before のみ 1' in page.locator('#overall').inner_text()
    page.click('[data-tab=raw]')
    page.select_option('#raw-host','leaf03')
    assert '未取得' in page.locator('#meta-after').inner_text()
    assert page.locator('#raw-after [data-line]').count()==0
    assert page.locator('#raw-before [data-line]').count()>0
    for scope in ('all','routes'):
        page.select_option('#raw-scope',scope)
        assert 'UNKNOWN scope: 2' in page.locator('#quality').inner_text()
        assert page.evaluate('R.summary')==original
