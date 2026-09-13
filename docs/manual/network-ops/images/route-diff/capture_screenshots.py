"""Capture the production offline report; requires optional Playwright + Chromium."""
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    output = Path(__file__).resolve().parent
    root = output.parents[4]
    report = root / "docs/manual/network-ops/examples/route-diff-core/route_diff/index.html"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url) if not request.url.startswith("file:") else None)
        page.goto(report.as_uri())
        page.evaluate("document.fonts.ready")
        page.select_option("#host", "leaf01")
        page.select_option("#af", "ipv4")
        page.select_option("#mode", "route-ad-cost")
        page.fill("#query", "192.0.2.64/26")
        assert not page.is_checked("#show-unchanged")
        assert page.locator(".route-group:visible").count() == 1
        page.locator('[data-panel="compare"]').screenshot(path=str(output / "01-cost-diff.png"))

        page.select_option("#mode", "route-ad-cost-nexthop")
        page.fill("#query", "198.51.100.128/25")
        assert page.locator(".pair:visible").count() == 1
        page.check("#show-unchanged")
        assert page.locator(".pair:visible").count() == 2
        page.locator('[data-panel="compare"]').screenshot(path=str(output / "02-common-ecmp.png"))

        page.click('[data-tab="raw"]')
        page.select_option("#raw-host", "leaf01")
        page.fill("#raw-query", "[110/30]")
        assert page.locator('.raw-pane .search-hit').count() == 1
        page.locator('[data-panel="raw"]').screenshot(path=str(output / "03-full-log.png"))

        page.click('[data-tab="summary"]')
        assert page.locator("#scope-summary tbody tr").count() == 25
        assert "UNKNOWN" in page.locator("#scope-summary").inner_text()
        page.locator("#scope-summary").screenshot(path=str(output / "04-summary.png"))
        assert page.locator('#evidence-panels details[open]').count() == 0
        assert 'leaf03 / TENANT-A / ipv4 — UNKNOWN：after: 取得が不完全' in page.locator('#quality-details').inner_text()
        page.locator('#evidence-panels').screenshot(path=str(output / '06-collapsed-evidence.png'))
        collection = root / 'docs/manual/network-ops/examples/route-diff-collection/route_diff/index.html'
        page.goto(collection.as_uri())
        page.click('[data-tab="raw"]')
        assert page.input_value('#raw-scope') == 'routes'
        assert '表示 26 / 全 45 行' in page.locator('#meta-before').inner_text()
        page.fill('#raw-query', 'segid:')
        page.locator('[data-panel="raw"]').screenshot(path=str(output / '07-route-sections.png'))
        page.select_option('#raw-scope', 'all')
        assert page.locator('#raw-before [data-line]').count() == 45
        page.click('[data-tab="summary"]')
        assert '両側取得済み 2 ホスト / before のみ 1' in page.locator('#overall').inner_text()
        page.locator('[data-panel="summary"]').screenshot(path=str(output / '08-directory-hosts.png'))
        assert not errors, errors
        assert not external, external
        browser.close()
    print("Captured seven production renderer screenshots; UI assertions and no-network checks passed.")


if __name__ == "__main__":
    main()
