#!/usr/bin/env python3
"""Bounded, reproducible offline Route Diff CLI benchmark (synthetic data only)."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import ipaddress
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MODES = ('route-only', 'route-ad', 'route-ad-cost', 'nexthop-include', 'route-ad-cost-nexthop')


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return 'sha256:' + value.hexdigest()


def expectation(count, percent, seed):
    kinds = defaultdict(int)
    for index in range(count):
        if (index + seed) % 100 < percent:
            kinds[('cost', 'hop', 'replace')[(index // 100 + seed) % 3]] += 1
    result = {}
    for mode in MODES:
        modified = (kinds['cost'] if mode in ('route-ad-cost', 'route-ad-cost-nexthop') else 0)
        modified += kinds['hop'] if mode in ('nexthop-include', 'route-ad-cost-nexthop') else 0
        result[mode] = dict(before_count=count, after_count=count, ADDED=kinds['replace'],
                            REMOVED=kinds['replace'], MODIFIED=modified,
                            UNCHANGED=count - kinds['replace'] - modified)
    return result


def generate(directory, *, count, paths, percent, seed, hosts, vrfs, reverse):
    """Stream input files; never allocate a million-route Python fixture model."""
    directory.mkdir(parents=True, exist_ok=False)
    host_records, files = [], []
    scope_count = hosts * vrfs * 2
    for host_index in range(hosts):
        host = f'bench{host_index + 1:02}'
        host_record = dict(host=host)
        for side in ('before', 'after'):
            file = directory / f'{host}-{side}.log'
            with file.open('w') as stream:
                for af_index, family in enumerate(('ipv4', 'ipv6')):
                    command = 'show ip route vrf all' if family == 'ipv4' else 'show ipv6 route vrf all'
                    stream.write(f'{host}# {command}\n')
                    for vrf_index in range(vrfs):
                        name = f'VRF-{vrf_index + 1}'
                        heading = 'IP Route' if family == 'ipv4' else 'IPv6 Routing'
                        stream.write(f'{heading} Table for VRF "{name}"\n')
                        scope = (host_index * 2 + af_index) * vrfs + vrf_index
                        indices = range(scope, count, scope_count)
                        for index in reversed(indices) if side == 'after' and reverse else indices:
                            changed = side == 'after' and (index + seed) % 100 < percent
                            kind = ('cost', 'hop', 'replace')[(index // 100 + seed) % 3] if changed else None
                            number = index + (count if kind == 'replace' else 0)
                            prefix = (str(ipaddress.IPv4Address(0x0A000000 + number)) + '/32' if family == 'ipv4' else
                                      str(ipaddress.IPv6Address(int(ipaddress.IPv6Address('2001:db8::')) + number)) + '/128')
                            stream.write(f'{prefix}, ubest/mbest: {paths}/0\n')
                            for hop in reversed(range(paths)) if side == 'after' and reverse else range(paths):
                                value = 9 if kind == 'hop' and hop == 0 else hop + 1
                                address = f'192.0.2.{value}' if family == 'ipv4' else f'fe80::{value}'
                                metric = 30 if kind == 'cost' and hop == 0 else 20
                                age = '00:01:02' if side == 'before' else '00:02:03'
                                stream.write(f'    *via {address}, Ethernet1/{value}, [110/{metric}], {age}, ospf-1, intra\n')
                        if not indices:
                            stream.write('No routes\n')
                stream.write(f'{host}#\n')
            files.append(dict(path=file.name, bytes=file.stat().st_size, sha256=digest(file)))
            host_record[side] = [dict(path=file.name, input_format='nxos-transcript')]
        host_records.append(host_record)
    # JSON is a YAML subset; the production Source Map loader is exercised as-is.
    mapping = dict(api_version='alred/v1', kind='RouteDiffSourceMap', metadata=dict(name='benchmark'), spec=dict(hosts=host_records))
    dump(directory / 'source-map.yaml', mapping)
    return files


def environment():
    files = sorted((ROOT / 'alred').rglob('*.py')) + sorted((ROOT / 'alred/schemas').rglob('*.json')) + [ROOT/'alred/j2/route_diff.html.j2', Path(__file__).resolve(), ROOT/'pyproject.toml', ROOT/'uv.lock']
    fingerprints = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=False)
    cpu = next((s.split(':', 1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines() if s.startswith('model name')), platform.processor())
    return dict(os=platform.platform(), python=sys.version, cpu=cpu, logical_cpus=os.cpu_count(),
                memory=Path('/proc/meminfo').read_text().splitlines()[:3],
                dependencies={name: version(name) for name in ('jsonschema', 'PyYAML', 'netmiko', 'ntc-templates')},
                commit=commit.stdout.strip(), source_sha256=hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest(),
                source_files=fingerprints)


def worker(case, memory_mib):
    limit = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    sys.path.insert(0, str(ROOT))
    from alred import cli
    from alred.route_diff import cli as route_cli
    from alred.route_diff.control import ProcessingControl

    timing = defaultdict(float)
    for name in ('resolve_inputs', 'parse_route_source', 'build_snapshot', 'compare_snapshots', 'write_route_report', 'verify_report'):
        original = getattr(route_cli, name)
        def measured(*args, _function=original, _name=name, **kwargs):
            start = time.perf_counter()
            try:
                return _function(*args, **kwargs)
            finally:
                timing[_name] += time.perf_counter() - start
        setattr(route_cli, name, measured)
    last = [None, 0.0]
    def progress(event):
        now = time.monotonic()
        if event['stage'] != last[0] or now - last[1] > 1:
            last[:] = [event['stage'], now]
            with (case / 'progress.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(event, elapsed_seconds=now - started)) + '\n')
    args = cli.build_parser().parse_args(['route-diff-nxos', '--source-map', str(case/'inputs/source-map.yaml'),
        '--output-dir', str(case/'route_diff'), '--no-progress'])
    started = time.monotonic()
    result = {}
    try:
        result['exit_code'] = route_cli.execute(args, control=ProcessingControl(progress))
        diff = json.loads((case/'route_diff/route-diff.json').read_text())
        result.update(status='PASS', counts=diff['summary']['modes'], coverage=diff['summary']['coverage'],
                      fingerprint=diff['comparison_fingerprint'], versions=diff['versions'])
        expected = json.loads((case/'case.json').read_text())['expected']
        if result['exit_code'] != 0 or result['coverage'] != 'COMPLETE' or any(
                result['counts'][mode][key] != value for mode, fields in expected.items() for key, value in fields.items()):
            result['status'] = 'COUNT_MISMATCH'
    except MemoryError:
        result = dict(status='MEMORY_LIMIT')
    finally:
        result.update(elapsed_seconds=time.monotonic() - started, api_inclusive_seconds=dict(timing),
                      max_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        dump(case/'worker-result.json', result)
    return 0 if result['status'] == 'PASS' else 1


def run_case(root, args, count):
    case = root / f'routes-{count}-paths-{args.paths}-diff-{args.diff_percent}'
    case.mkdir()
    files = generate(case/'inputs', count=count, paths=args.paths, percent=args.diff_percent, seed=args.seed,
                     hosts=args.hosts, vrfs=args.vrfs, reverse=args.reverse_after)
    spec = dict(count_per_side=count, paths=args.paths, diff_percent=args.diff_percent, seed=args.seed,
                hosts=args.hosts, vrfs=args.vrfs, families=['ipv4', 'ipv6'], reverse_after=args.reverse_after,
                expected=expectation(count, args.diff_percent, args.seed), inputs=files)
    dump(case/'case.json', spec)
    start = time.monotonic()
    sampled_peak = 0
    with (case/'stdout.log').open('w') as stdout, (case/'stderr.log').open('w') as stderr:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(case), '--memory-mib', str(args.memory_mib)], stdout=stdout, stderr=stderr)
        timed_out = False
        try:
            while process.poll() is None:
                try:
                    status = Path(f'/proc/{process.pid}/status').read_text()
                    peak = next(int(s.split()[1]) for s in status.splitlines() if s.startswith('VmHWM:'))
                    sampled_peak = max(sampled_peak, peak / 1024)
                except (OSError, StopIteration):
                    pass
                if time.monotonic() - start > args.timeout_seconds:
                    timed_out = True
                    process.kill()
                    break
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    result_path = case/'worker-result.json'
    try:
        result = json.loads(result_path.read_text()) if result_path.is_file() else dict(status='ERROR')
    except (OSError, ValueError):
        result = dict(status='ERROR', reason='worker result was incomplete')
    if timed_out:
        result['status'] = 'TIMEOUT'
    elif process.returncode != 0 and result.get('status') == 'PASS':
        result['status'] = 'ERROR'
    result.update(case=case.name, count_per_side=count, process_returncode=process.returncode,
                  wall_seconds=time.monotonic() - start, sampled_peak_rss_mib=sampled_peak,
                  limits=dict(timeout_seconds=args.timeout_seconds, address_space_mib=args.memory_mib),
                  artifact_bytes={p.relative_to(case).as_posix(): p.stat().st_size for p in case.rglob('*') if p.is_file()},
                  published=(case/'route_diff/report-manifest.json').is_file())
    dump(case/'result.json', result)
    print(json.dumps({k: result[k] for k in ('case', 'status', 'wall_seconds', 'sampled_peak_rss_mib', 'published')}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--routes', type=int, nargs='+', default=[10000])
    parser.add_argument('--paths', type=int, choices=[1, 4], default=1)
    parser.add_argument('--diff-percent', type=int, choices=[0, 1, 100], default=1)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--hosts', type=int, default=2)
    parser.add_argument('--vrfs', type=int, default=2)
    parser.add_argument('--reverse-after', action='store_true')
    parser.add_argument('--timeout-seconds', type=float, default=300)
    parser.add_argument('--memory-mib', type=int, default=4096)
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.memory_mib)
    if (args.output is None or args.output.exists() or args.output.is_symlink() or min(args.routes) < 1
            or max(args.routes) > 1000000 or len(set(args.routes)) != len(args.routes)
            or args.hosts < 1 or args.vrfs < 1 or not math.isfinite(args.timeout_seconds)
            or args.timeout_seconds <= 0 or args.memory_mib < 128):
        parser.error('use a new output directory, unique route counts in 1..1000000 and positive limits')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    dump(args.output/'environment.json', environment())
    results = [run_case(args.output, args, count) for count in args.routes]
    dump(args.output/'results.json', dict(schema_version=1, kind='RouteDiffBenchmark', results=results))
    return 0 if all(r['status'] == 'PASS' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
