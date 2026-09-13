"""Generate synthetic Health evidence and capture the real rollback report UI."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from alred.health.manifest import build_collect_manifest
from alred.health.profile import resolve_profiles
from alred.health.snapshot import build_health_snapshot
from alred.health.route_diff import (route_config, build_health_routes, store_health_routes,
                                     assess_routes, publish_route_report)
from alred.route_diff.parser import PROMPT


def main():
    output = Path(__file__).resolve().parent
    repository = output.parents[4]
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    resolved = resolve_profiles(['route-diff-nxos'], change_id='MANUAL-ROUTES', resolved_at=now, timezone='UTC')
    effective = resolved['spec']['resolved']['effective']
    config = route_config(effective['spec']['route_diff'])
    with TemporaryDirectory(prefix='alred-health-route-manual-') as temporary:
        root = Path(temporary)
        health, bundles = [], []
        for phase, label in [('before', 'before'), ('rollback', 'after')]:
            raw = (repository / f'tests/fixtures/nxos/route_diff/synthetic/leaf01-{label}-route.txt').read_text()
            sections = []
            for line in raw.splitlines():
                match = PROMPT.fullmatch(line.strip())
                if match:
                    if match['command']:
                        command = match['command']
                        sections.extend([f'### COMMAND: {command}', f'### COLLECTED_AT: {now.isoformat()}',
                                         '### STATUS: OK', '### TRANSPORT: ssh', line])
                else:
                    sections.append(line)
            source = root / phase / 'input/leaf01_shows.log'
            source.parent.mkdir(parents=True)
            source.write_text('\n'.join(sections) + '\n')
            manifest = build_collect_manifest([str(source)], collection_id=phase, change_id='MANUAL-ROUTES',
                phase=phase, profiles=['route-diff-nxos'], started_at=now, completed_at=now,
                timezone='UTC', host_platforms={'leaf01': 'nxos'})
            snapshot = build_health_snapshot(manifest, profile_refs=['route-diff-nxos'], created_at=now,
                timezone='UTC', profile_sha256=resolved['spec']['resolved']['effective_sha256'])
            bundle = build_health_routes(manifest, config, phase=phase)
            snapshot['route_diff'] = store_health_routes(bundle, config, operation_root=root, directory=root/phase)
            health.append(snapshot)
            bundles.append(bundle)
        assessment = assess_routes(*health, effective, bundles)
        artifacts = publish_route_report(assessment, bundles, operation_root=root, report_dir=root/'report')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith('file:') else None)
            page.goto(Path(artifacts['route_diff_index']).as_uri())
            page.evaluate('document.fonts.ready')
            assert page.locator('#health-result').inner_text() == 'Health Route 判定 (rollback): FAIL'
            page.select_option('#af', 'ipv4')
            page.fill('#query', '192.0.2.64/26')
            assert page.locator('.route-group').count() == 1
            assert 'Cost: 20' in page.locator('#routes').inner_text()
            assert 'Cost: 30' in page.locator('#routes').inner_text()
            page.screenshot(path=str(output / '05-health-rollback.png'))
            page.locator('#health-result').click()
            assert 'rollback_residual_entries' in page.locator('#health-checks').inner_text()
            assert not errors, errors
            assert not external, external
            browser.close()
    print('Captured the Health rollback report; restoration result and offline UI verified.')


if __name__ == '__main__':
    main()
