#!/usr/bin/env python3
"""Exercise installed/source/native Route Diff and Health CLIs without device access."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command', nargs='+', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('output must be a new directory')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    calls = []
    def run(argv, expected=0):
        command = args.command + argv
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        calls.append(dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        (args.output/'calls.json').write_text(json.dumps(calls, indent=2) + '\n')
        assert result.returncode == expected, result.stderr + result.stdout
        return result.stdout
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    assert version in run(['--version'])
    assert 'route-diff-nxos' in run(['--help'])
    fixture = ROOT/'tests/fixtures/nxos/route_diff/synthetic'
    before, after = (fixture/f'leaf01-{side}-route.txt' for side in ('before', 'after'))
    run(['route-diff-nxos', '--before', str(before), '--after', str(after), '--input-format', 'nxos-transcript',
         '--output-dir', str(args.output/'standalone'), '--no-progress'])
    diff = json.loads((args.output/'standalone/route-diff.json').read_text())
    assert diff['summary']['coverage'] == 'COMPLETE'
    for mode, modified in [('route-only', 0), ('route-ad', 1), ('route-ad-cost', 3), ('nexthop-include', 5), ('route-ad-cost-nexthop', 7)]:
        counts = diff['summary']['modes'][mode]
        assert counts['ADDED'] == counts['REMOVED'] == 1
        assert counts['MODIFIED'] == modified
    hosts = args.output/'hosts.yaml'
    hosts.write_text('all:\n  hosts:\n    leaf01:\n      device_type: nxos\n')
    for phase, source in [('before', before), ('after', after)]:
        run(['health-check', 'snapshot', '--input', str(source), '--input-format', 'nxos-transcript', '--hosts', str(hosts),
             '--phase', phase, '--change-id', 'ROUTE-PACKAGE-SMOKE', '--profile', 'route-diff-nxos',
             '--operations-root', str(args.output/'operations')])
    snapshots = [next((args.output/'operations').glob(f'**/health/{side}/snapshot.json')) for side in ('before', 'after')]
    run(['health-check', 'compare', '--before', str(snapshots[0]), '--after', str(snapshots[1]),
         '--operations-root', str(args.output/'operations')], expected=1)
    report = snapshots[0].parents[1]/'report/route_diff'
    health = json.loads((report/'route-diff.json').read_text())
    assert health['summary']['modes'] == diff['summary']['modes']
    assert json.loads((report/'health-assessment.json').read_text())['result'] == 'WARN'
    cases = ROOT/'docs/design/network-ops/examples/route-diff-input-fix'
    run(['route-diff-nxos', '--before', str(cases/'directory-case/before'), '--after', str(cases/'directory-case/after'),
         '--input-format', 'nxos-transcript', '--output-dir', str(args.output/'directory'), '--no-progress'], expected=3)
    multi = json.loads((args.output/'directory/route-diff.json').read_text())
    assert multi['summary']['complete_scope_count'] == 4 and multi['summary']['unknown_scope_count'] == 2
    assert multi['summary']['modes']['route-ad-cost-nexthop']['MODIFIED'] == 1
    assert 'id="raw-scope"' in (args.output/'directory/index.html').read_text()
    for side in ('before', 'after'):
        source = args.output/('collect-'+side)/'leaf01_shows.log'
        source.parent.mkdir()
        source.write_bytes((cases/(side+'.txt')).read_bytes())
        run(['health-check', 'snapshot', '--input', str(source), '--input-format', 'alred-collect', '--hosts', str(hosts),
             '--phase', side, '--change-id', 'ROUTE-COLLECT-SMOKE', '--profile', 'route-diff-nxos',
             '--operations-root', str(args.output/'collect-operations')])
    collected = [next((args.output/'collect-operations').glob(f'**/health/{side}/snapshot.json')) for side in ('before', 'after')]
    run(['health-check', 'compare', '--before', str(collected[0]), '--after', str(collected[1]),
         '--operations-root', str(args.output/'collect-operations')], expected=1)
    collect_report = collected[0].parents[1]/'report/route_diff'
    detail = json.loads((collect_report/'route-diff.json').read_text())
    assert detail['summary']['coverage'] == 'COMPLETE'
    assert detail['summary']['modes']['route-ad-cost-nexthop']['MODIFIED'] == 1
    assert 'SEGMENT_ID_CHANGED' in detail['entries'][0]['reason_codes']
    for directory in (args.output/'standalone', report, args.output/'directory', collect_report):
        manifest = json.loads((directory/'report-manifest.json').read_text())
        for name, value in manifest['files'].items():
            path = directory/name
            assert not path.is_symlink()
            assert 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() == value
    (args.output/'result.json').write_text(json.dumps(dict(status='PASS', version=version, calls=len(calls),
        cases=['standalone', 'health-profile', 'before-after', 'directory', 'collect-health', 'report-hashes']), indent=2) + '\n')
    print(f'PASS: version={version}; standalone and Health counts agree; report hashes verified')


if __name__ == '__main__':
    main()
