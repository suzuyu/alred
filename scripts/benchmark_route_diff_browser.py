#!/usr/bin/env python3
"""Measure the real offline HTML with optional locally installed Playwright."""
import argparse
import json
from pathlib import Path
import time
import traceback

from benchmark_route_diff import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or args.repeats < 1:
        parser.error('use a new output file and a positive repeat count')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import expect, sync_playwright
    report = args.report.resolve()/'index.html'
    manifest = json.loads((report.parent/'report-manifest.json').read_text())
    assert digest(report) == manifest['files']['index.html']
    result = dict(schema_version=1, kind='RouteDiffBrowserBenchmark', html_sha256=digest(report),
                  html_bytes=report.stat().st_size, comparison_fingerprint=manifest['comparison_fingerprint'], runs=[])
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            result['browser'] = browser.version
            for _ in range(args.repeats):
                context = browser.new_context(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
                page = context.new_page()
                errors, external, metrics = [], [], {}
                result['runs'].append(metrics)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith(('file:', 'blob:')) else None)
                def measure(name, action):
                    start = time.perf_counter()
                    action()
                    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
                    metrics[name] = (time.perf_counter() - start) * 1000
                measure('initial_display_ms', lambda: page.goto(report.as_uri(), timeout=60000))
                assert not page.is_checked('#show-unchanged')
                original = page.evaluate('R.summary.modes')
                assert page.locator('.route-group').count() <= 100
                measure('mode_switch_ms', lambda: page.select_option('#mode', 'route-ad-cost'))
                measure('show_common_ms', lambda: page.check('#show-unchanged'))
                assert page.locator('.route-group').count() <= 100
                prefix = page.evaluate('(D.rows.findLast(r => r.modes[R.comparison.primary_mode].change_type !== "UNCHANGED") || D.rows[D.rows.length-1]).resource.prefix')
                measure('prefix_search_ms', lambda: page.fill('#query', prefix))
                assert page.locator('.route-group').count() == 1
                measure('evidence_jump_ms', lambda: page.locator('.route-footer button').first.click())
                assert page.locator('.evidence-hit').count() > 0
                measure('raw_search_ms', lambda: page.fill('#raw-query', '[110/20]'))
                assert page.input_value('#raw-scope') == 'routes'
                measure('raw_show_all_ms', lambda: page.select_option('#raw-scope', 'all'))
                def scroll_end():
                    last_line = page.evaluate("source('before').lines.length")
                    page.evaluate("document.getElementById('raw-before').scrollTop=document.getElementById('raw-before').scrollHeight")
                    expect(page.locator(f'#raw-before [data-line="{last_line}"]')).to_have_count(1)
                measure('raw_scroll_end_ms', scroll_end)
                assert page.locator('#raw-before .raw-line').count() < 250
                start = time.perf_counter()
                page.select_option('#raw-color', 'literal')
                expect(page.locator('#raw-progress')).to_contain_text('文字列 diff 完了', timeout=60000)
                metrics['literal_diff_ms'] = (time.perf_counter() - start) * 1000
                assert page.evaluate('R.summary.modes') == original
                session = context.new_cdp_session(page)
                session.send('Performance.enable')
                stats = {m['name']: m['value'] for m in session.send('Performance.getMetrics')['metrics']}
                metrics['js_heap_used_mib'] = stats['JSHeapUsedSize'] / (1024 * 1024)
                metrics['dom_nodes'] = stats['Nodes']
                assert not errors, errors
                assert not external, external
                page.click('#return-compare')
                page.select_option('#mode', 'route-ad-cost-nexthop')
                check = page.locator('.review input[type=checkbox]:enabled')
                if check.count():
                    check.first.check()
                start = time.perf_counter()
                with page.expect_download() as saved:
                    page.click('#export-review')
                review_path = args.output.parent / f'{args.output.stem}-review-{len(result["runs"])}.json'
                saved.value.save_as(review_path)
                if check.count():
                    check.first.uncheck()
                    assert not check.first.is_checked()
                page.set_input_files('#import-review', review_path)
                expect(page.locator('#review-state')).to_contain_text('復元')
                metrics['review_roundtrip_ms'] = (time.perf_counter() - start) * 1000
                assert page.evaluate('R.summary.modes') == original
                if check.count():
                    assert check.first.is_checked()
                assert not errors, errors
                assert not external, external
                context.close()
            browser.close()
        result['status'] = 'PASS'
    except Exception:
        result.update(status='ERROR', error=traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
