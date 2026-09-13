"""Generate a multi-host report from synthetic collection envelopes, without device access."""
import argparse
from pathlib import Path

from alred.route_diff.comparator import compare_snapshots
from alred.route_diff.parser import parse_route_source
from alred.route_diff.report import write_route_report
from alred.route_diff.snapshot import build_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    cases = root/'docs/design/network-ops/examples/route-diff-input-fix/directory-case'
    sources = {'before': [('leaf01','device-a.log'),('leaf02','device-b.log'),('leaf03','device-c.log')],
               'after': [('leaf01','post-leaf01.txt'),('leaf02','device-b-renamed.log')]}
    snapshots, raw = [], {}
    for side, members in sources.items():
        parsed, paths = [], {}
        for host, name in members:
            path = cases/side/name
            content = path.read_bytes()
            raw[side,host] = content
            paths[host] = path.relative_to(root).as_posix()
            parsed.append(parse_route_source(content, source_id=host, device=host))
        snapshots.append(build_snapshot(parsed, side=side, source_paths=paths))
    result = compare_snapshots(*snapshots)
    assert result['summary']['complete_scope_count'] == 4
    assert result['summary']['unknown_scope_count'] == 2
    assert result['summary']['modes']['route-ad-cost-nexthop']['MODIFIED'] == 1
    write_route_report(*snapshots, result, raw, args.report_dir)
    print('Generated collection report: 2 paired hosts, 1 missing after, 1 modified prefix.')


if __name__ == '__main__':
    main()
