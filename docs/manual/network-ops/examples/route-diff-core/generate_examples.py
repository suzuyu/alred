"""Regenerate examples through the production parser/comparator, using synthetic logs."""
import argparse
import json
from pathlib import Path

import yaml

from alred.route_diff.comparator import compare_snapshots
from alred.route_diff.parser import parse_route_source
from alred.route_diff.snapshot import build_snapshot
from alred.route_diff.report import write_route_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, help="new directory for the offline report")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    root = output.parents[4]
    fixtures = root / "tests/fixtures/nxos/route_diff/synthetic"
    snapshots, raw_sources = [], {}
    for side in ("before", "after"):
        sources, paths = [], {}
        for host in ("leaf01", "leaf02", "leaf03"):
            file = fixtures / f"{host}-{side}-route.txt"
            raw_sources[side, host] = file.read_bytes()
            sources.append(parse_route_source(raw_sources[side, host], source_id=host, device=host))
            paths[host] = file.relative_to(root).as_posix()
        snapshot = build_snapshot(sources, side=side, source_paths=paths)
        snapshots.append(snapshot)
        (output / f"route-snapshot-{side}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    result = compare_snapshots(*snapshots)
    (output / "route-diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.report_dir is not None:
        write_route_report(*snapshots, result, raw_sources, args.report_dir)
    policy = yaml.safe_load((root / "docs/design/network-ops/examples/route-diff-review/expected-changes.example.yaml").read_text())
    result = compare_snapshots(*snapshots, selected_scopes={("leaf01", "TENANT-A", "ipv4")}, policy=policy)
    (output / "route-diff-policy.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Generated validated snapshots, five-mode comparison and policy results from synthetic logs.")


if __name__ == "__main__":
    main()
