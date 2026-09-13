"""Production comparison and policy tests using synthetic, offline route evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from alred.route_diff.comparator import compare_snapshots, validate_diff
from alred.route_diff.control import ProcessingControl, RouteProcessingCancelled
from alred.route_diff.domain import RouteInputError
from alred.route_diff.parser import parse_route_source
from alred.route_diff.semantics import MODES, PRIMARY_MODE
from alred.route_diff.snapshot import build_snapshot, snapshot_hash, validate_snapshot
from alred.schema import DocumentValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/nxos/route_diff/synthetic'
REVIEW = ROOT / 'docs/design/network-ops/examples/route-diff-review'
RESOURCE = dict(device='leaf01', vrf='TENANT-A', family='ipv4', prefix='192.0.2.64/26')


def path(address='192.0.2.1', ad=110, cost=20):
    return dict(kind='ip', address=address, next_hop_family='ipv4', interface='Ethernet1/1',
        next_hop_vrf='TENANT-A', next_hop_table_family=None, admin_distance=ad, metric=cost)


def route(paths=None, prefix=RESOURCE['prefix']):
    return dict(prefix=prefix, paths=paths if paths is not None else [path()])


def parsed(routes, *, source_id='source', device='leaf01', vrf='TENANT-A', family='ipv4', asserted=False, broken=False, command=None):
    heading = 'IP Route' if family == 'ipv4' else 'IPv6 Routing'
    lines = [f'{heading} Table for VRF "{vrf}"']
    if not routes: lines.append('No routes')
    for value in routes:
        lines.append(f'{value["prefix"]}, ubest/mbest: {len(value["paths"])}/0')
        for p in value['paths']:
            if p['address'] is not None:
                hop = p['address']
                if p['next_hop_vrf'] != vrf or p.get('next_hop_table_family'):
                    hop += '%' + p['next_hop_vrf']
                    if p.get('next_hop_table_family'): hop += ':' + p['next_hop_table_family'].replace('ipv', 'IPv')
                if p['interface']: hop += ', ' + p['interface']
            else: hop = p['interface']
            protocol = {'connected':'direct', 'local':'local'}.get(p['kind'], 'static')
            lines.append(f'    *via {hop}, [{p["admin_distance"]}/{p["metric"]}], {protocol}')
    if broken: lines.append('unknown trailing route data')
    body = '\n'.join(lines) + '\n'
    if asserted:
        return parse_route_source(body.encode(),source_id=source_id,device=device,input_format='nxos-route-text',command_id=f'route_{family}_all_vrfs',completeness='asserted')
    command = command or f"show {'ip' if family == 'ipv4' else 'ipv6'} route vrf all"
    return parse_route_source(f'{device}# {command}\n{body}{device}#\n'.encode(),source_id=source_id,device=device)


def snapshots(before, after, **kwargs):
    return tuple(build_snapshot([parsed(values, **kwargs)],side=side) for side,values in [('before',before),('after',after)])


def policy(**groups):
    return dict(api_version='alred/v1',kind='RouteDiffPolicy',metadata=dict(name='test'),spec=groups)


@pytest.fixture
def fixture_snapshots():
    return tuple(build_snapshot([parse_route_source((FIXTURES/f'{host}-{side}-route.txt').read_bytes(),source_id=host,device=host)
        for host in ('leaf01','leaf02','leaf03')],side=side) for side in ('before','after'))


def test_parser_to_snapshot_to_five_modes_matches_review(fixture_snapshots):
    originals=deepcopy(fixture_snapshots)
    result=compare_snapshots(*fixture_snapshots)
    assert fixture_snapshots == originals
    assert result['summary']['coverage'] == 'PARTIAL'
    assert (result['summary']['complete_scope_count'],result['summary']['unknown_scope_count']) == (4,1)
    for mode,modified in zip(MODES,(0,1,3,5,7)):
        c=result['summary']['modes'][mode]
        assert tuple(c[k] for k in ('before_count','after_count','ADDED','REMOVED','MODIFIED','UNCHANGED')) == (12,12,1,1,modified,11-modified)
    assert len(result['entries']) == 9 and result['exit_code'] == 3
    unknown=next(s for s in result['scopes'] if s['device']=='leaf03')
    assert all(all(v is None for v in c.values()) for c in unknown['modes'].values())
    assert not any(e['device']=='leaf03' for e in result['entries'])
    assert any(r['paths']==[] for r in fixture_snapshots[1]['routes'])
    validate_snapshot(json.loads(json.dumps(fixture_snapshots[0])))
    validate_diff(json.loads(json.dumps(result)))


@pytest.mark.parametrize('field,value,modified', [('admin_distance',200,(0,1,1,1,1)),('metric',30,(0,0,1,0,1)),
    ('address','192.0.2.2',(0,0,0,1,1)),('next_hop_table_family','ipv6',(0,0,0,1,1))])
def test_mode_field_selection(field,value,modified):
    old,new=route(),route(); new['paths'][0][field]=value
    result=compare_snapshots(*snapshots([old],[new]))
    assert tuple(result['summary']['modes'][m]['MODIFIED'] for m in MODES)==modified


@pytest.mark.parametrize('swap_ad', [False,True])
def test_tuple_association_not_independent_value_sets(swap_ad):
    a=route([path('192.0.2.1',ad=10 if swap_ad else 110,cost=20),path('192.0.2.2',ad=30 if swap_ad else 110,cost=40)])
    b=deepcopy(a); b['paths'][0]['metric'],b['paths'][1]['metric']=40,20
    result=compare_snapshots(*snapshots([a],[b]))
    mode='route-ad-cost' if swap_ad else PRIMARY_MODE
    assert result['entries'][0]['modes'][mode]['reason_codes']==['PATH_ASSOCIATION_CHANGED']
    if not swap_ad:
        assert [result['summary']['modes'][m]['MODIFIED'] for m in MODES]==[0,0,0,0,1]


def test_ecmp_order_and_ipv6_representation_are_ignored():
    a=route([path(),path('192.0.2.2')]); b=dict(a,paths=list(reversed(a['paths'])))
    result=compare_snapshots(*snapshots([a],[b]))
    assert result['entries']==[] and result['exit_code']==0
    p=path(); p.update(address='2001:0db8:0:0:0:0:0:1',next_hop_family='ipv6')
    q=dict(p,address='2001:db8::1')
    assert compare_snapshots(*snapshots([route([p])],[route([q])]))['entries']==[]


def test_ecmp_reduction_ignored_by_ad_cost_but_warns():
    result=compare_snapshots(*snapshots([route([path(),path('192.0.2.2')])],[route()]),policy=policy())
    assert result['summary']['modes']['route-ad-cost']['MODIFIED']==0
    assert 'PATH_COUNT_DECREASED' in result['entries'][0]['reason_codes']
    assert result['evaluation']=='WARN' and result['exit_code']==1


def test_prefix_length_change_is_add_and_remove():
    result=compare_snapshots(*snapshots([route()],[route(prefix='192.0.2.64/27')]))
    assert {e['change_type'] for e in result['entries']}=={'ADDED','REMOVED'}
    assert all(c['MODIFIED']==0 and c['ADDED']==c['REMOVED']==1 for c in result['summary']['modes'].values())


def test_complete_empty_and_broken_empty():
    result=compare_snapshots(*snapshots([],[]))
    assert result['summary']['coverage']=='COMPLETE' and result['exit_code']==0
    assert result['summary']['modes'][PRIMARY_MODE]['after_count']==0
    result=compare_snapshots(*snapshots([],[],broken=True))
    assert result['summary']['coverage']=='UNKNOWN' and result['exit_code']==3
    assert result['summary']['modes'][PRIMARY_MODE]['after_count'] is None


def test_all_vs_specific_preserves_missing_scope():
    before=build_snapshot([parsed([route()],source_id='tenant'),parsed([],source_id='default',vrf='default')],side='before')
    after=build_snapshot([parsed([route()],command='show ip route vrf TENANT-A')],side='after')
    result=compare_snapshots(before,after)
    assert result['entries']==[] and result['exit_code']==3
    assert next(s for s in result['scopes'] if s['vrf']=='default')['coverage']=='UNKNOWN'
    result=compare_snapshots(before,after,selected_scopes={('leaf01','TENANT-A','ipv4')})
    assert result['summary']['coverage']=='COMPLETE' and result['exit_code']==0
    assert next(s for s in result['scopes'] if s['vrf']=='default')['coverage']=='NOT_SELECTED'


def test_explicit_missing_scope_and_empty_selection():
    pair=snapshots([route()],[route()])
    result=compare_snapshots(*pair,selected_scopes={('leaf01','MISSING','ipv6')})
    assert result['exit_code']==3 and result['summary']['unknown_scope_count']==1
    with pytest.raises(RouteInputError,match='empty'): compare_snapshots(*pair,selected_scopes=set())


def test_unscoped_bad_source_is_not_successful_empty_comparison():
    source=parse_route_source(b'',source_id='bad',device='leaf01')
    pair=[build_snapshot([source],side=side) for side in ('before','after')]
    result=compare_snapshots(*pair,policy=policy())
    assert result['summary']['unknown_source_count']==2
    assert result['evaluation']=='UNKNOWN' and result['exit_code']==3


CASES=json.loads((REVIEW/'review-cases.example.json').read_text())['expectations']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_policy_authored_acceptance_cases(case):
    a,b=(case['observed'][side] for side in ('before','after'))
    pair=snapshots([a] if a else [],[b] if b else [],asserted=case['verification']=='user_asserted')
    result=compare_snapshots(*pair,policy=policy(**case['policy']))
    rule=result['policy_results']['expected_changes'][0]
    assert rule['expectation_status']==case['expectation_status']
    assert result['evaluation']==case['health_result']
    assert rule['mismatch_fields']==case['mismatch_fields']
    if case['observation']=='UNCHANGED': assert result['entries']==[]
    if case['id']=='required-fail': assert result['entries'][0]['evaluation']=='FAIL'


@pytest.mark.parametrize('minimum,expected',[(1,'PASS'),(2,'PASS'),(3,'FAIL')])
def test_required_path_boundary(minimum,expected):
    value=route([path(),path('192.0.2.2')])
    result=compare_snapshots(*snapshots([value],[value]),policy=policy(required_routes=[dict(RESOURCE,min_paths=minimum)]))
    assert result['evaluation']==expected
    assert result['policy_results']['required_routes'][0]['classification']==('pre_existing' if expected=='FAIL' else 'satisfied')


@pytest.mark.parametrize('match,expected',[('contains','PASS'),('exact','FAIL')])
def test_expected_hops_match(match,expected):
    value=route([path(),path('192.0.2.2')]); hop={k:v for k,v in path().items() if k not in ('admin_distance','metric')}
    rule=dict(RESOURCE,min_paths=1,expected_next_hops=dict(match=match,paths=[hop]))
    result=compare_snapshots(*snapshots([value],[value]),policy=policy(required_routes=[rule]))
    assert result['evaluation']==expected


def test_default_route_is_not_substitute_and_recovery_keeps_before_failure():
    result=compare_snapshots(*snapshots([route(prefix='0.0.0.0/0')],[route()]),policy=policy(required_routes=[dict(RESOURCE,min_paths=1)]))
    record=result['policy_results']['required_routes'][0]
    assert (record['before_result'],record['after_result'])==('FAIL','PASS')
    assert record['recovered'] and record['classification']=='pre_existing'
    assert result['evaluation']=='FAIL'


def test_asserted_observation_can_compare_but_not_pass_policy():
    pair=snapshots([route()],[route([path(cost=30)])],asserted=True)
    assert compare_snapshots(*pair)['exit_code']==0
    result=compare_snapshots(*pair,policy=policy())
    assert result['evaluation']=='UNKNOWN' and result['exit_code']==3
    assert result['summary']['modes'][PRIMARY_MODE]['MODIFIED']==1


def test_exclusions_keep_observation_and_unknown():
    excluded=policy(exclusions=[dict(RESOURCE,reason='planned exclusion')])
    result=compare_snapshots(*snapshots([route()],[]),policy=excluded)
    assert result['entries'][0]['evaluation']=='EXCLUDED' and result['entries'][0]['change_type']=='REMOVED'
    assert result['evaluation']=='PASS'
    assert compare_snapshots(*snapshots([route()],[],broken=True),policy=excluded)['evaluation']=='UNKNOWN'


def test_policy_outside_selection_rejected():
    with pytest.raises(RouteInputError,match='outside selected'):
        compare_snapshots(*snapshots([route()],[route()]),selected_scopes={('leaf01','default','ipv4')},policy=policy(required_routes=[dict(RESOURCE,min_paths=1)]))


def test_unknown_exit_keeps_independent_failures():
    before=build_snapshot([parsed([route()],source_id='good'),parsed([],source_id='bad',vrf='OTHER',broken=True)],side='before')
    after=build_snapshot([parsed([],source_id='good'),parsed([],source_id='bad',vrf='OTHER',broken=True)],side='after')
    result=compare_snapshots(before,after,policy=policy(required_routes=[dict(RESOURCE,min_paths=1)]))
    assert result['exit_code']==3 and result['evaluation']=='UNKNOWN'
    assert result['policy_results']['required_routes'][0]['result']=='FAIL'


def test_source_order_and_frozen_policy(fixture_snapshots):
    a,b=fixture_snapshots
    sources=[parse_route_source((FIXTURES/f'{host}-before-route.txt').read_bytes(),source_id=host,device=host) for host in ('leaf03','leaf02','leaf01')]
    assert build_snapshot(sources,side='before')==a
    selection={('leaf01','TENANT-A','ipv4')}; spec=policy(required_routes=[dict(RESOURCE,min_paths=1)])
    result=compare_snapshots(a,b,selected_scopes=selection,policy=spec)
    assert compare_snapshots(a,b,selected_scopes=selection,policy=spec,expected_policy_sha256=result['policy_sha256'])==result
    spec['spec']['required_routes'][0]['min_paths']=2
    with pytest.raises(RouteInputError,match='frozen'):
        compare_snapshots(a,b,selected_scopes=selection,policy=spec,expected_policy_sha256=result['policy_sha256'])


@pytest.mark.parametrize('change',['hash','duplicate','missing_metric','quality','evidence','side','version'])
def test_snapshot_corruption_rejected(change):
    a,b=snapshots([route()],[route()])
    if change=='hash': a['sources'][0]['path']='changed'
    elif change=='duplicate': a['routes'].append(deepcopy(a['routes'][0]))
    elif change=='missing_metric': del a['routes'][0]['paths'][0]['metric']
    elif change=='quality': a['scopes'][0]['health_eligible']=False
    elif change=='evidence': a['routes'][0]['evidence']['start_byte']+=1
    elif change=='side': a['side']='after'
    else: a['versions']['parser']='999'
    if change!='hash': a['snapshot_id']=snapshot_hash(a)
    with pytest.raises((RouteInputError,DocumentValidationError)): compare_snapshots(a,b)


def test_duplicate_scope_across_sources_rejected():
    with pytest.raises(RouteInputError,match='duplicate scope'):
        build_snapshot([parsed([route()],source_id='one'),parsed([route()],source_id='two')],side='before')


def test_result_counts_and_fingerprint_validation():
    result=compare_snapshots(*snapshots([route()],[]))
    bad=deepcopy(result); bad['summary']['modes'][PRIMARY_MODE]['REMOVED']=0
    with pytest.raises(RouteInputError,match='count'): validate_diff(bad)
    bad=deepcopy(result); bad['comparison_fingerprint']='sha256:'+'0'*64
    with pytest.raises(RouteInputError,match='fingerprint'): validate_diff(bad)


@pytest.mark.parametrize('stage',['compare','evaluate'])
def test_cancellation_does_not_return_partial_results(stage):
    pair=snapshots([route()],[route([path(cost=30)])]); seen=[]
    control=ProcessingControl(on_progress=seen.append,is_cancelled=lambda:bool(seen and seen[-1]['stage']==stage))
    with pytest.raises(RouteProcessingCancelled): compare_snapshots(*pair,policy=policy(),control=control)
    assert any(p['unit'] in ('scopes','routes','rules') for p in seen if p['stage']==stage)


def test_unselected_named_vrf_error_does_not_poison_selected_scope():
    bad=parse_route_source(b'leaf01# show ip route vrf OTHER\n% VRF missing\nleaf01#\n',source_id='bad',device='leaf01')
    pair=[build_snapshot([parsed([route()]),bad],side=side) for side in ('before','after')]
    assert compare_snapshots(*pair)['exit_code']==3
    result=compare_snapshots(*pair,selected_scopes={('leaf01','TENANT-A','ipv4')})
    assert result['exit_code']==0
    assert next(s for s in result['scopes'] if s['vrf']=='OTHER')['coverage']=='NOT_SELECTED'


def test_expected_addition_unapplied_when_both_sides_are_absent():
    rule=dict(RESOURCE,id='add',reason='planned addition',before=None,after=route())
    result=compare_snapshots(*snapshots([],[]),policy=policy(expected_changes=[rule]))
    assert result['entries']==[] and result['evaluation']=='WARN'
    assert result['policy_results']['expected_changes'][0]['expectation_status']=='NOT_APPLIED'


def test_policy_order_does_not_change_hash_and_snapshot_additive_fields_are_readable():
    a=route([path(),path('192.0.2.2')]); b=route([path(cost=30),path('192.0.2.2',cost=40)])
    pair=snapshots([a],[b]); spec=policy(expected_changes=[dict(RESOURCE,id='both',reason='planned',before=a,after=b)])
    result=compare_snapshots(*pair,policy=spec)
    for side in ('before','after'): spec['spec']['expected_changes'][0][side]['paths'].reverse()
    assert compare_snapshots(*pair,policy=spec)==result
    extended=deepcopy(pair[0]); extended['future_metadata']={'extra':'value'}; extended['snapshot_id']=snapshot_hash(extended)
    validate_snapshot(extended)
    assert compare_snapshots(extended,pair[1])['summary']==compare_snapshots(*pair)['summary']


@pytest.mark.parametrize('field',['coverage','complete_scope_count','unknown_scope_count','unknown_source_count'])
def test_result_summary_cannot_hide_unknown(field,fixture_snapshots):
    result=compare_snapshots(*fixture_snapshots)
    result['summary'][field]='COMPLETE' if field=='coverage' else 999
    with pytest.raises(RouteInputError,match='coverage'): validate_diff(result)


def test_same_path_attributes_reassigned_expected_change_is_reported():
    a=route([path('192.0.2.1',cost=20),path('192.0.2.2',cost=40)])
    b=route([path('192.0.2.1',cost=40),path('192.0.2.2',cost=20)])
    rule=dict(RESOURCE,id='change',reason='planned',before=a,after=route([path(cost=30)]))
    result=compare_snapshots(*snapshots([b],[rule['after']]),policy=policy(expected_changes=[rule]))
    assert result['policy_results']['expected_changes'][0]['mismatch_fields']==['before.paths.association']


def test_production_output_examples_validate():
    folder=ROOT/'docs/manual/network-ops/examples/route-diff-core'
    for side in ('before','after'):
        validate_snapshot(json.loads((folder/f'route-snapshot-{side}.json').read_text()))
    observed=json.loads((folder/'route-diff.json').read_text())
    evaluated=json.loads((folder/'route-diff-policy.json').read_text())
    validate_diff(observed); validate_diff(evaluated)
    assert observed['summary']['coverage']=='PARTIAL'
    assert evaluated['evaluation']=='WARN' and evaluated['exit_code']==1
    assert evaluated['policy_results']['expected_changes'][0]['expectation_status']=='MATCHED'


def test_selected_interval_changes_fingerprint_without_route_changes():
    source=parsed([route()]); raw=source.terminal.raw*2
    a=parse_route_source(raw,source_id='same',device='leaf01',start_line=1,end_line=5)
    b=parse_route_source(raw,source_id='same',device='leaf01',start_line=6,end_line=10)
    before=build_snapshot([a],side='before')
    first=compare_snapshots(before,build_snapshot([a],side='after'))
    second=compare_snapshots(before,build_snapshot([b],side='after'))
    assert first['entries']==second['entries']==[]
    assert first['comparison_fingerprint']!=second['comparison_fingerprint']


def test_protocol_and_age_changes_are_retained_but_not_compared():
    a=parsed([route()])
    raw=a.terminal.raw.replace(b'], static',b'], 00:30:00, ospf-1, intra')
    b=parse_route_source(raw,source_id='source',device='leaf01')
    pair=[build_snapshot([p],side=s) for p,s in [(a,'before'),(b,'after')]]
    assert pair[0]['routes'][0]['paths'][0]['protocol']=='static'
    assert pair[1]['routes'][0]['paths'][0]['protocol']=='ospf'
    assert compare_snapshots(*pair)['entries']==[]


def test_cancel_during_route_batch():
    values=[route(prefix=f'198.18.{n//256}.{n%256}/32') for n in range(300)]
    pair=snapshots(values,values); seen=[]; cancelled=False
    def progress(value):
        nonlocal cancelled
        seen.append(value)
        if value['stage']=='compare' and value['unit']=='routes' and value['completed']>=256: cancelled=True
    with pytest.raises(RouteProcessingCancelled):
        compare_snapshots(*pair,control=ProcessingControl(on_progress=progress,is_cancelled=lambda:cancelled))
    assert any(p['stage']=='compare' and p['completed']==256 for p in seen)
