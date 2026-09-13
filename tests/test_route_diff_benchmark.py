"""Correctness of deterministic performance inputs and bounded CLI execution."""
import json
import subprocess
import sys

import pytest

if sys.platform != 'linux':
    pytest.skip('Benchmark uses Linux /proc and RLIMIT_AS', allow_module_level=True)

from scripts.benchmark_route_diff import ROOT, generate, expectation
from alred.route_diff.parser import parse_route_source
from alred.route_diff.snapshot import build_snapshot
from alred.route_diff.comparator import compare_snapshots


@pytest.mark.parametrize('paths', [1, 4])
@pytest.mark.parametrize('percent', [0, 1, 100])
def test_benchmark_expected_counts_are_independent_of_order(tmp_path, paths, percent):
    files = generate(tmp_path/'inputs', count=303, paths=paths, percent=percent, seed=17, hosts=2, vrfs=2, reverse=True)
    snapshots = []
    for side in ('before', 'after'):
        parsed = [parse_route_source((tmp_path/'inputs'/f'bench{i:02}-{side}.log').read_bytes(),
                    source_id=f'source{i}', device=f'bench{i:02}') for i in (1, 2)]
        snapshots.append(build_snapshot(parsed, side=side))
    result = compare_snapshots(*snapshots)
    assert result['exit_code'] == 0
    assert len(snapshots[0]['routes']) == len(snapshots[1]['routes']) == 303
    for mode, expected in expectation(303, percent, 17).items():
        assert all(result['summary']['modes'][mode][k] == v for k, v in expected.items())
    assert files == generate(tmp_path/'repeat', count=303, paths=paths, percent=percent, seed=17, hosts=2, vrfs=2, reverse=True)


def test_benchmark_runs_publication_and_rejects_overwrite(tmp_path):
    command = [sys.executable, str(ROOT/'scripts/benchmark_route_diff.py'), '--output', str(tmp_path/'run'),
               '--routes', '32', '--paths', '4', '--diff-percent', '100', '--timeout-seconds', '45']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads((tmp_path/'run/results.json').read_text())['results'][0]
    assert result['published'] and result['status'] == 'PASS'
    assert result['max_rss_mib'] > 0
    assert result['api_inclusive_seconds']['write_route_report'] > 0
    assert result['artifact_bytes']['route_diff/index.html'] > 0
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2


def test_benchmark_records_timeout_without_publishing(tmp_path):
    command = [sys.executable, str(ROOT/'scripts/benchmark_route_diff.py'), '--output', str(tmp_path/'run'),
               '--routes', '100', '--timeout-seconds', '0.001']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 1
    result = json.loads((tmp_path/'run/results.json').read_text())['results'][0]
    assert result['status'] == 'TIMEOUT'
    assert result['published'] is False
    assert result['process_returncode'] < 0


@pytest.mark.parametrize('limit', ['nan', 'inf'])
def test_benchmark_requires_finite_time_limit(tmp_path, limit):
    output = tmp_path/'run'
    completed = subprocess.run([sys.executable, str(ROOT/'scripts/benchmark_route_diff.py'),
                '--output', str(output), '--timeout-seconds', limit], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 2
    assert not output.exists()


def test_validation_reuse_rehashes_content_and_keeps_schema_checks(tmp_path, monkeypatch):
    from copy import deepcopy
    from alred.route_diff import snapshot as module
    from alred.route_diff.control import ProcessingControl

    generate(tmp_path/'inputs', count=16, paths=1, percent=0, seed=17, hosts=1, vrfs=1, reverse=False)
    parsed = parse_route_source((tmp_path/'inputs/bench01-before.log').read_bytes(), source_id='source', device='bench01')
    snapshot = build_snapshot([parsed], side='before')
    control = ProcessingControl()
    calls = []
    original = module.validate_document
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'validate_document', counted)
    module.validate_snapshot(snapshot, control=control)
    module.validate_snapshot(deepcopy(snapshot), control=control)
    assert len(calls) == 1
    # Mutating a document without changing its claimed ID cannot hit the cache.
    broken = deepcopy(snapshot)
    broken['routes'][0]['paths'][0]['metric'] = 99
    with pytest.raises(ValueError, match='hash mismatch'):
        module.validate_snapshot(broken, control=control)
    # Nor does recomputing the claimed ID make invalid schema valid.
    broken['routes'][0]['paths'][0].pop('metric')
    broken['snapshot_id'] = module.snapshot_hash(broken)
    with pytest.raises(ValueError):
        module.validate_snapshot(broken, control=control)
    # A tuple has the same JSON representation as a list, but fails JSON schema.
    broken = deepcopy(snapshot)
    broken['routes'] = tuple(broken['routes'])
    assert module.snapshot_hash(broken) == snapshot['snapshot_id']
    with pytest.raises(ValueError):
        module.validate_snapshot(broken, control=control)
    assert len(calls) == 4
    for i in range(20):
        control.remember_validated('test', str(i))
    assert len(control._validated) <= 8


def test_diff_validation_does_not_trust_only_comparison_fingerprint(tmp_path):
    from copy import deepcopy
    from alred.route_diff.control import ProcessingControl
    from alred.route_diff.comparator import validate_diff

    generate(tmp_path/'inputs', count=16, paths=1, percent=100, seed=0, hosts=1, vrfs=1, reverse=False)
    snapshots = [build_snapshot([parse_route_source((tmp_path/f'inputs/bench01-{side}.log').read_bytes(),
                 source_id='source', device='bench01')], side=side) for side in ('before', 'after')]
    control = ProcessingControl()
    result = compare_snapshots(*snapshots, control=control)
    validate_diff(result, control=control)
    broken = deepcopy(result)
    broken['summary']['modes']['route-ad-cost']['MODIFIED'] = 999
    assert broken['comparison_fingerprint'] == result['comparison_fingerprint']
    with pytest.raises(ValueError):
        validate_diff(broken, control=control)
