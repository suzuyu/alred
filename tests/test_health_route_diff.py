"""Offline Health integration; synthetic routes never connect to a device."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import yaml

from alred.health.profile import resolve_profiles
from alred.health.manifest import build_collect_manifest
from alred.health.snapshot import build_health_snapshot
from alred.health.evaluator import evaluate_snapshot, compare_snapshots
from alred.health.route_diff import (route_config, build_health_routes, store_health_routes,
    load_health_routes, assess_routes, route_check, publish_route_report)
from alred.route_diff.domain import RouteInputError
from alred.schema import canonical_sha256

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def profile(tmp_path, config=None):
    refs = ["route-diff-nxos"]
    if config:
        path = tmp_path / 'extra.yaml'
        path.write_text(yaml.safe_dump(dict(api_version='alred/v1', kind='HealthCheckProfile',
            metadata=dict(name='site-routes', version='1'), spec=dict(platforms=['nxos'], route_diff=config))))
        refs.append(str(path))
    return resolve_profiles(refs, change_id='CHG-ROUTE', resolved_at=NOW, timezone='UTC')


def collect(path, *, cost=20, status='OK', empty=False, omit_v6=False, extra=''):
    sections = []
    for family, command, heading, prefix, hop in [
        ('ipv4', 'show ip route vrf all', 'IP Route', '192.0.2.0/24', '198.51.100.1'),
        ('ipv6', 'show ipv6 route vrf all', 'IPv6 Routing', '2001:db8::/64', 'fe80::1')]:
        if family == 'ipv6' and omit_v6:
            continue
        body = 'No routes\n' if empty else f'{prefix}, ubest/mbest: 1/0\n    *via {hop}, Ethernet1/1, [110/{cost}], 00:01:02, ospf-1, intra\n'
        sections.append(f'### COMMAND: {command}\n### COLLECTED_AT: {NOW.isoformat()}\n### STATUS: {status}\n### TRANSPORT: ssh\nleaf01# {command}\n{heading} Table for VRF "default"\n{body}{extra}\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(sections))


def build(tmp_path, resolved, phase='before', **kwargs):
    directory = tmp_path / phase
    source = tmp_path / ('input-' + phase) / 'leaf01_shows.log'
    collect(source, **kwargs)
    manifest = build_collect_manifest([str(source)], collection_id=phase, change_id='CHG-ROUTE', phase=phase,
        profiles=['route-diff-nxos'], started_at=NOW, completed_at=NOW, timezone='UTC', host_platforms={'leaf01': 'nxos'})
    effective = resolved['spec']['resolved']['effective']
    config = route_config(effective['spec']['route_diff'])
    bundle = build_health_routes(manifest, config, phase=phase)
    health = build_health_snapshot(manifest, profile_refs=['route-diff-nxos'], created_at=NOW, timezone='UTC',
                                   profile_sha256=resolved['spec']['resolved']['effective_sha256'])
    health['route_diff'] = store_health_routes(bundle, config, operation_root=tmp_path, directory=directory)
    (directory / 'snapshot.json').write_text(json.dumps(health))
    return health, bundle, directory


def test_profile_is_explicit_and_deduplicates_commands(tmp_path):
    baseline = resolve_profiles(['network-baseline-nxos'], change_id='CHG-ROUTE', resolved_at=NOW, timezone='UTC')
    assert 'route_diff' not in baseline['spec']['resolved']['effective']['spec']
    combined = resolve_profiles(['network-baseline-nxos', 'nxos-overlay', 'route-diff-nxos'], change_id='CHG-ROUTE', resolved_at=NOW, timezone='UTC')
    commands = combined['spec']['resolved']['effective']['spec']['collectors']['nxos']['commands']
    for identifier in ['route_ipv4_all_vrfs', 'route_ipv6_all_vrfs']:
        assert len([c for c in commands if c['id'] == identifier]) == 1
        assert next(c for c in commands if c['id'] == identifier)['required'] is True


def test_collected_evidence_is_verified_and_retained(tmp_path):
    resolved = profile(tmp_path)
    health, bundle, directory = build(tmp_path, resolved)
    assert all(s['health_eligible'] for s in bundle['snapshot']['scopes'])
    assert {s['input_format'] for s in bundle['snapshot']['sources']} == {'alred-collect'}
    assert load_health_routes(health, directory / 'snapshot.json') == bundle
    result = evaluate_snapshot(health, resolved, started_at=NOW, completed_at=NOW, route_bundle=bundle)
    assert result['result'] == 'PASS'
    assert len(bundle['snapshot']['routes']) == 2
    assert bundle['snapshot']['routes'][0]['paths'][0]['metric'] == 20


@pytest.mark.parametrize('kwargs', [dict(status='ERROR'), dict(omit_v6=True), dict(extra='--More--'), dict(extra='unknown output row')])
def test_incomplete_input_is_unknown_not_removed(tmp_path, kwargs):
    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    after, b, _ = build(tmp_path, resolved, 'after', **kwargs)
    result = compare_snapshots(before, after, resolved, started_at=NOW, completed_at=NOW, route_bundles=(a, b))
    assert result['result'] == 'UNKNOWN'
    assessment = assess_routes(before, after, resolved['spec']['resolved']['effective'], (a, b))
    assert not any(e['change_type'] == 'REMOVED' for e in assessment['diff']['entries'])


def test_legacy_snapshot_only_disables_new_check(tmp_path):
    resolved = profile(tmp_path)
    health, _, _ = build(tmp_path, resolved)
    health.pop('route_diff')
    assert evaluate_snapshot(health, resolved, started_at=NOW, completed_at=NOW)['result'] == 'UNKNOWN'


@pytest.mark.parametrize('target', ['snapshot', 'raw', 'missing', 'symlink', 'escape', 'version', 'config'])
def test_tampered_or_partial_artifacts_are_rejected(tmp_path, target):
    resolved = profile(tmp_path)
    health, bundle, directory = build(tmp_path, resolved)
    file = directory / bundle['snapshot']['sources'][0]['path']
    if target == 'snapshot':
        (directory / 'route-snapshot.json').write_text('{}')
    elif target == 'raw':
        file.write_bytes(b'changed')
    elif target == 'missing':
        file.unlink()
    elif target == 'symlink':
        file.unlink()
        file.symlink_to(directory / 'snapshot.json')
    elif target == 'escape':
        health['route_diff']['path'] = '../route-snapshot.json'
    elif target == 'version':
        health['route_diff']['adapter_version'] = '999'
    elif target == 'config':
        health['route_diff']['config_sha256'] = 'sha256:' + '0' * 64
        with pytest.raises(RouteInputError, match='frozen Health context'):
            assess_routes(health, health, resolved['spec']['resolved']['effective'], (bundle, bundle), single=True)
        return
    with pytest.raises(ValueError):
        load_health_routes(health, directory / 'snapshot.json')


def test_cost_comparison_and_rollback_restoration(tmp_path):
    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    after, b, _ = build(tmp_path, resolved, 'after', cost=30)
    effective = resolved['spec']['resolved']['effective']
    result = compare_snapshots(before, after, resolved, started_at=NOW, completed_at=NOW, route_bundles=(a, b))
    assert result['result'] == 'PASS'  # observed Cost changes are informational
    assessment = assess_routes(before, after, effective, (a, b))
    assert all(e['modes']['route-ad-cost']['change_type'] == 'MODIFIED' for e in assessment['diff']['entries'])
    rollback = deepcopy(after)
    rollback['phase'] = 'rollback'
    result = compare_snapshots(before, rollback, resolved, started_at=NOW, completed_at=NOW, route_bundles=(a, b))
    assert result['result'] == 'FAIL'
    restored, c, _ = build(tmp_path, resolved, 'rollback')
    assert compare_snapshots(before, restored, resolved, started_at=NOW, completed_at=NOW, route_bundles=(a, c))['result'] == 'PASS'


@pytest.mark.parametrize('field,old,new,reason', [
    ('segid', '19001', '19002', 'SEGMENT_ID_CHANGED'),
    ('tunnelid', '0xcb007101', '0xcb007102', 'TUNNEL_ID_CHANGED'),
])
def test_vxlan_attribute_must_be_restored_on_rollback(tmp_path, monkeypatch, field, old, new, reason):
    original = collect
    def vxlan_collect(path, **kwargs):
        original(path, **kwargs)
        suffix = 'bgp-65001, internal, segid: 19001 tunnelid: 0xcb007101 encap: VXLAN'
        if path.parent.name == 'input-after':
            suffix = suffix.replace(f'{field}: {old}', f'{field}: {new}')
        path.write_text(path.read_text().replace('ospf-1, intra', suffix))
    monkeypatch.setattr(f'{__name__}.collect', vxlan_collect)
    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    after, b, _ = build(tmp_path, resolved, 'after')
    effective = resolved['spec']['resolved']['effective']
    diff = assess_routes(before, after, effective, (a, b))['diff']
    assert diff['summary']['modes']['route-ad-cost']['MODIFIED'] == 0
    assert all(reason in entry['reason_codes'] for entry in diff['entries'])
    rollback = deepcopy(after)
    rollback['phase'] = 'rollback'
    assert compare_snapshots(before, rollback, resolved, started_at=NOW, completed_at=NOW,
                             route_bundles=(a, b))['result'] == 'FAIL'
    restored, c, _ = build(tmp_path, resolved, 'rollback')
    assert compare_snapshots(before, restored, resolved, started_at=NOW, completed_at=NOW,
                             route_bundles=(a, c))['result'] == 'PASS'


def test_required_route_and_pending_expectation(tmp_path):
    # Use canonical full path fields from a verified observation as the policy input.
    initial = profile(tmp_path)
    _, bundle, _ = build(tmp_path / 'initial', initial)
    observed = bundle['snapshot']['routes'][0]
    desired = dict(prefix=observed['prefix'], paths=[{k: v for k, v in p.items() if k in (
        'kind', 'next_hop_family', 'address', 'interface', 'next_hop_vrf', 'next_hop_table_family', 'admin_distance', 'metric')} for p in observed['paths']])
    changed = deepcopy(desired)
    changed['paths'][0]['metric'] = 30
    resource = {k: observed[k] for k in ('device', 'vrf', 'family', 'prefix')}
    policy = dict(api_version='alred/v1', kind='RouteDiffPolicy', metadata=dict(name='site'), spec=dict(
        required_routes=[dict(resource, min_paths=1)],
        expected_changes=[dict(resource, id='cost-change', before=desired, after=changed, reason='maintenance')]))
    resolved = profile(tmp_path, {'policy': policy})
    before, a, _ = build(tmp_path, resolved)
    assert evaluate_snapshot(before, resolved, started_at=NOW, completed_at=NOW, route_bundle=a)['result'] == 'PASS'
    after, b, _ = build(tmp_path, resolved, 'after', cost=30)
    result = compare_snapshots(before, after, resolved, started_at=NOW, completed_at=NOW, route_bundles=(a, b))
    assert result['result'] == 'PASS'
    assert result['checks'][0]['after']['policy_results']['expected_changes'][0]['expectation_status'] == 'MATCHED'
    bad, c, _ = build(tmp_path / 'bad', resolved, empty=True)
    assert evaluate_snapshot(bad, resolved, started_at=NOW, completed_at=NOW, route_bundle=c)['result'] == 'FAIL'


def test_report_failure_preserves_last_success(tmp_path, monkeypatch):
    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    after, b, _ = build(tmp_path, resolved, 'after', cost=30)
    assessment = assess_routes(before, after, resolved['spec']['resolved']['effective'], (a, b))
    report = tmp_path / 'report'
    artifacts = publish_route_report(assessment, (a, b), operation_root=tmp_path, report_dir=report)
    assert Path(artifacts['route_diff_index']).is_file()
    previous = (report / 'route_diff').resolve()
    original = (previous / 'report-manifest.json').read_bytes()
    def broken(*args, **kwargs):
        partial = Path(args[4])
        partial.mkdir(parents=True)
        (partial / 'index.html').write_text('interrupted')
        raise OSError('simulated renderer interruption')
    monkeypatch.setattr('alred.route_diff.report.write_route_report', broken)
    with pytest.raises(ValueError, match='interruption'):
        publish_route_report(assessment, (a, b), operation_root=tmp_path, report_dir=report)
    assert (report / 'route_diff').resolve() == previous
    assert (previous / 'report-manifest.json').read_bytes() == original
    assert len(list((report / 'route-diff-attempts').iterdir())) == 2


def test_health_phase_cli_publishes_routes_and_inherits_profile(tmp_path, monkeypatch):
    from alred import cli
    from alred.operation import open_operation_workspace

    monkeypatch.chdir(tmp_path)
    hosts = tmp_path / 'hosts.yaml'
    hosts.write_text('all:\n  hosts:\n    leaf01:\n      device_type: nxos\n')
    operations = tmp_path / 'operations'
    calls = []
    def fake_collect(args, logger, old_generation_id=None):
        calls.append(args)
        collect(Path(args.output) / 'leaf01_shows.log', cost=20 if len(calls) == 1 else 30)
    monkeypatch.setattr(cli, 'run_collect', fake_collect)
    def run(phase):
        argv = ['health-check', phase, '--collect', '--change-id', 'CHG-CLI-ROUTE',
                '--operations-root', str(operations)]
        if phase == 'before':
            argv += ['--hosts', str(hosts), '--profile', 'route-diff-nxos']
        return cli.cmd_health_check_phase(cli.build_parser().parse_args(argv))
    assert run('before') == 0
    assert run('after') == 0
    root = open_operation_workspace(operations, 'CHG-CLI-ROUTE').operation_root
    assert (root / 'health/report/route_diff/index.html').is_file()
    assert (root / 'health/report/route_diff').is_symlink()
    for phase in ('before', 'after'):
        directory = root / 'health' / phase
        health = json.loads((directory / 'snapshot.json').read_text())
        bundle = load_health_routes(health, directory / 'snapshot.json')
        assert len(bundle['snapshot']['routes']) == 2
        if phase == 'before':
            current = json.loads((directory / 'current.json').read_text())
            saved = json.loads(Path(current['snapshot_path']).read_text())
            assert load_health_routes(saved, current['snapshot_path']) == bundle
    result = json.loads((root / 'health/report/health-result.json').read_text())
    assert result['checks'][0]['result'] == 'PASS'
    assert result['artifacts']['route_diff_index'].endswith('route_diff/index.html')


@pytest.mark.parametrize('ending, extra, expected', [('leaf01#\n', '', True), ('', '', False), ('leaf01#\n', '--More--\n', False)])
def test_transcript_uses_raw_completion_and_controls(tmp_path, ending, extra, expected):
    from alred.health.transcript import import_nxos_transcripts

    source = tmp_path / 'transcript.log'
    source.write_text('leaf01# show ip route\nIP Route Table for VRF "default"\n'
        '192.0.2.0/24, ubest/mbest: 1/0\n'
        '    *via 198.51.100.1, Ethernet1/1, [110/20], 00:01:02, ospf-1, intra\n' + extra + ending)
    hosts = tmp_path / 'hosts.yaml'
    hosts.write_text('all:\n  hosts:\n    leaf01:\n      device_type: nxos\n')
    _, manifest = import_nxos_transcripts([str(source)], hosts_path=hosts, collection_id='routes',
        change_id='CHG-ROUTE', phase='before', profiles=['route-diff-nxos'], imported_at=NOW, timezone='UTC')
    bundle = build_health_routes(manifest, route_config({'families': ['ipv4']}), phase='before')
    assert bundle['snapshot']['scopes'][0]['health_eligible'] is expected
    assert next(iter(bundle['raw'].values())) == source.read_bytes()


def test_policy_scope_is_fixed_and_validated(tmp_path):
    first = profile(tmp_path)
    changed = profile(tmp_path, {'families': ['ipv4'], 'vrfs': ['default']})
    assert first['spec']['resolved']['effective_sha256'] != changed['spec']['resolved']['effective_sha256']
    policy = dict(api_version='alred/v1', kind='RouteDiffPolicy', metadata=dict(name='site'), spec=dict(
        required_routes=[dict(device='leaf01', family='ipv6', vrf='default', prefix='2001:db8::/64', min_paths=1)]))
    with pytest.raises(RouteInputError, match='outside selected'):
        profile(tmp_path, {'families': ['ipv4'], 'policy': policy})


@pytest.mark.parametrize('family', ['ipv4', 'ipv6'])
@pytest.mark.parametrize('vrf', [None, 'TENANT-A', 'all'])
def test_health_collect_accepts_default_specific_and_all_commands(tmp_path, family, vrf):
    from alred.health.route_diff import _parse_record
    from alred.route_diff.commands import resolve_route_command
    from alred.route_diff.terminal import sha256

    command = 'show ' + ('ip' if family == 'ipv4' else 'ipv6') + ' route' + (f' vrf {vrf}' if vrf else '')
    heading = 'IP Route' if family == 'ipv4' else 'IPv6 Routing'
    table = vrf if vrf and vrf != 'all' else 'default'
    raw = (f'### COMMAND: {command}\n### STATUS: OK\n### COLLECTED_AT: {NOW.isoformat()}\n'
           f'### TRANSPORT: ssh\nleaf01# {command}\n{heading} Table for VRF "{table}"\nNo routes\n').encode()
    record = dict(status='success', confidence='high', source='alred_collect', command=command,
                  start_line=1, end_line=7, output_start_line=6, output_end_line=7,
                  collected_at=NOW.isoformat(), sha256=sha256(raw)[7:])
    parsed = _parse_record(raw, record, source_id='source', device='leaf01', command=resolve_route_command(command))
    assert parsed.document['scopes'][0]['health_eligible'] is True
    assert parsed.document['scopes'][0]['vrf'] == table


def test_health_command_ids_preserve_vrf_case():
    from alred.health.commands import command_id

    assert command_id('show ip route') == 'route_ipv4_default_vrf'
    assert command_id('show ipv6 route') == 'route_ipv6_default_vrf'
    assert command_id('show ip route vrf all') == 'route_ipv4_all_vrfs'
    assert command_id('show ip route vrf TENANT-A') != command_id('show ip route vrf tenant-a')
    assert command_id('show ip route vrf TENANT-A') == command_id('terminal length 0 ; show ip route vrf TENANT-A | no-more')
    assert command_id('show ip route | include 192.0.2.0').startswith('unsupported_')


def test_bad_report_hash_preserves_publication_and_has_health_error_code(tmp_path, monkeypatch):
    from alred.health.route_diff import HealthRouteReportError
    from alred.route_diff import report as renderer
    from alred.cli import _operation_cli_error

    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    after, b, _ = build(tmp_path, resolved, 'after', cost=30)
    assessment = assess_routes(before, after, resolved['spec']['resolved']['effective'], (a, b))
    output = tmp_path / 'report'
    publish_route_report(assessment, (a, b), operation_root=tmp_path, report_dir=output)
    previous = (output / 'route_diff').resolve()
    original = renderer.write_route_report
    def corrupted(*args, **kwargs):
        original(*args, **kwargs)
        (Path(args[4]) / 'index.html').write_text('changed after rendering')
    monkeypatch.setattr(renderer, 'write_route_report', corrupted)
    with pytest.raises(HealthRouteReportError) as error:
        publish_route_report(assessment, (a, b), operation_root=tmp_path, report_dir=output)
    assert error.value.code == 'ROUTE_REPORT_FAILED'
    assert (output / 'route_diff').resolve() == previous
    with pytest.raises(SystemExit) as exit_error:
        _operation_cli_error(error.value)
    assert exit_error.value.code == 2


def test_rollback_compatibility_link_points_to_immutable_attempt(tmp_path):
    from types import SimpleNamespace
    from alred.cli import _copy_attempt_artifacts

    resolved = profile(tmp_path)
    before, a, _ = build(tmp_path, resolved)
    rollback, b, _ = build(tmp_path, resolved, 'rollback', cost=30)
    assessment = assess_routes(before, rollback, resolved['spec']['resolved']['effective'], (a, b))
    attempt = tmp_path / 'rollback-report/attempts/test'
    publish_route_report(assessment, (a, b), operation_root=tmp_path, report_dir=attempt)
    root = tmp_path / 'rollback-report'
    _copy_attempt_artifacts(SimpleNamespace(operation_root=tmp_path), attempt, root, excluded=set())
    assert (root / 'route_diff').is_symlink()
    assert (root / 'route_diff').resolve() == (attempt / 'route_diff').resolve()
    assert not (root / 'route-diff-attempts').exists()
    context = json.loads((root / 'route_diff/health-assessment.json').read_text())
    assert context['result'] == 'FAIL'
