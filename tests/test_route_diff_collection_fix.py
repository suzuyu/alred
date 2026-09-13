"""Collection envelope, forwarding attributes and directory input regression cases."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alred.route_diff.cli import execute, resolve_inputs, verify_report
from alred.route_diff.commands import resolve_route_command
from alred.route_diff.comparator import compare_snapshots
from alred.route_diff.control import ProcessingControl, RouteProcessingCancelled
from alred.route_diff.domain import RouteInputError
from alred.route_diff.parser import parse_route_source
from alred.route_diff.sections import prepare_sections
from alred.route_diff.snapshot import build_snapshot, snapshot_hash, validate_snapshot
from alred.health.route_diff import _parse_record
from alred.schema import canonical_sha256

CASES = Path(__file__).resolve().parents[1] / 'docs/design/network-ops/examples/route-diff-input-fix'


def parse(name='before.txt', raw=None):
    return parse_route_source(raw if raw is not None else (CASES/name).read_bytes(), source_id='source', device='leaf01')


def args(tmp_path, **changes):
    value = dict(before=str(CASES/'directory-case/before'), after=str(CASES/'directory-case/after'),
        input_format='nxos-transcript', source_map=None, host=None, command_id=None, command_vrf=None,
        completeness=None, af='both', vrf=None, policy=None, review=None, recursive=False,
        before_label='before', after_label='after', output_dir=str(tmp_path/'result'), no_progress=True)
    value.update(changes)
    return SimpleNamespace(**value)


def pair(left, right):
    return [build_snapshot([p], side=side) for p,side in zip((left,right),('before','after'))]


def test_collection_matches_independent_design_expectations():
    expected=json.loads((CASES/'expected.json').read_text())
    left,right=pair(parse(),parse('after.txt'))
    result=compare_snapshots(left,right)
    assert result['summary']['coverage']==expected['coverage']
    for mode, counts in expected['modes'].items():
        assert all(result['summary']['modes'][mode][k]==v for k,v in counts.items())
    assert result['entries'][0]['reason_codes']==expected['reason_codes']
    assert left['routes'][0]['paths'][0]['protocol']=='hmm'
    empty=next(s for s in left['scopes'] if s['family']=='ipv6')
    assert empty['empty_basis']=='closed_section' and not empty['explicit_empty']
    assert left['sources'][0]['container_format']=='alred-collect'
    assert len(left['sources'][0]['notices'])==2
    result=compare_snapshots(*pair(parse(),parse('after-incomplete.txt')))
    assert result['exit_code']==3 and result['summary']['coverage']=='PARTIAL'
    assert result['summary']['unknown_scope_count']==1
    assert not any(e['change_type']=='REMOVED' for e in result['entries'])


@pytest.mark.parametrize('change',[
    lambda s:s.replace('### TRANSPORT: ssh\n','',1),
    lambda s:s.replace('### STATUS: OK','### STATUS: OK\n### STATUS: OK',1),
    lambda s:s.replace('2026-09-13T10:00:00+09:00','invalid',1),
    lambda s:s.replace('2026-09-13T10:00:00+09:00','2026-09-13T10:00:00',1),
    lambda s:s.replace('leaf01# show version','leaf01# show interface brief',1),
    lambda s:s.replace('### TRANSPORT: ssh','### UNEXPECTED: ssh',1),
    lambda s:'unknown banner\n'+s,
])
def test_bad_envelope_is_not_silently_stripped(change):
    with pytest.raises(RouteInputError):
        parse(raw=change((CASES/'before.txt').read_text()).encode())


def test_nonroute_pager_and_prompt_text_do_not_poison_routes():
    raw=(CASES/'before.txt').read_text().replace('Synthetic device output for design review',
        '--More--\n\x1b[2J\nother-device# show ip route\nexample output')
    doc=parse(raw=raw.encode()).document
    assert all(s['coverage']=='COMPLETE' for s in doc['scopes'])
    assert any(n.get('diagnostics') for n in doc['notices'])
    assert not doc['diagnostics']
    assert {s.host for s in prepare_sections(raw.encode()).sections}=={'leaf01'}


@pytest.mark.parametrize('extra',['--More--','\x1b[2J','unrecognized line'])
def test_route_body_failure_stays_in_its_command(extra):
    raw=(CASES/'before.txt').read_text().replace('IP Route Table',extra+'\nIP Route Table',1)
    doc=parse(raw=raw.encode()).document
    v4,v6=doc['scopes']
    assert v4['coverage']=='UNKNOWN'
    assert v6['coverage']=='COMPLETE'


@pytest.mark.parametrize('attribute,old,new,reason',[
    ('segment_id','19001','19002','SEGMENT_ID_CHANGED'),
    ('tunnel_id','0xcb007101','0xcb007102','TUNNEL_ID_CHANGED'),
    ('asymmetric',' (Asymmetric)','','ASYMMETRIC_CHANGED'),
])
def test_forwarding_changes_only_affect_next_hop_modes(attribute,old,new,reason):
    raw=(CASES/'before.txt').read_bytes()
    a,b=pair(parse(raw=raw),parse(raw=raw.replace(old.encode(),new.encode())))
    result=compare_snapshots(a,b)
    assert reason in result['entries'][0]['reason_codes']
    for mode,counts in result['summary']['modes'].items():
        assert counts['MODIFIED']==int('nexthop' in mode)


def test_ipv6_mapped_next_hop_and_colonless_segid_are_preserved():
    raw=b'''leaf01# show ipv6 route
IPv6 Routing Table for VRF "default"
2001:db8::/64, ubest/mbest: 1/0
 *via ::ffff:203.0.113.1%default:IPv4, [200/0], 1w5d, bgp-65001, internal, tag 65001, segid 19001 (Asymmetric) tunnelid: 0x00ABCDEF encap: VXLAN
leaf01#
'''
    a,b=pair(parse(raw=raw),parse(raw=raw.replace(b'0x00ABCDEF',b'0xabcdef').replace(b'segid ',b'segid: ')))
    p=a['routes'][0]['paths'][0]
    assert p['next_hop_family']=='ipv6' and p['next_hop_table_family']=='ipv4'
    assert p['address']=='::ffff:cb00:7101' and p['tunnel_id']=='0xabcdef'
    assert compare_snapshots(a,b)['summary']['modes']['route-ad-cost-nexthop']['MODIFIED']==0


@pytest.mark.parametrize('replacement',[b'segid: 0',b'segid: 16777216',b'segid: -1',
    b'segid: 19001 unknown',b'segid: 19001 encap: VXLAN segid: 19002'])
def test_bad_forwarding_attributes_remain_unknown(replacement):
    value=parse(raw=(CASES/'before.txt').read_bytes().replace(b'segid: 19001',replacement))
    assert value.document['scopes'][0]['coverage']=='UNKNOWN'
    assert any(d['code']=='UNSUPPORTED_PATH' for d in value.document['scopes'][0]['diagnostics'])


@pytest.mark.parametrize('family',['ipv4','ipv6'])
@pytest.mark.parametrize('vrf',['default','BLUE','all'])
def test_closed_empty_six_commands_require_legends_and_command_end(family,vrf):
    command='show '+('ip' if family=='ipv4' else 'ipv6')+' route'+('' if vrf=='default' else ' vrf '+vrf)
    table='BLUE' if vrf=='all' else vrf
    heading='IP Route' if family=='ipv4' else 'IPv6 Routing'
    legends="'*' denotes best ucast next-hop\n'**' denotes best mcast next-hop\n'[x/y]' denotes [preference/metric]\n"
    if family=='ipv4':legends+="'%<string>' in via output denotes VRF <string>\n"
    raw=f'leaf01# {command}\n{heading} Table for VRF "{table}"\n{legends}'
    assert parse(raw=(raw+'leaf01#\n').encode()).document['scopes'][0]['coverage']=='COMPLETE'
    assert parse(raw=raw.encode()).document['scopes'][0]['coverage']=='UNKNOWN'
    assert parse(raw=(raw.replace(legends,'')+'leaf01#\n').encode()).document['scopes'][0]['coverage']=='UNKNOWN'


def test_tampered_completion_and_old_version_are_rejected():
    snapshot=build_snapshot([parse()],side='before')
    for mutate in (
        lambda d:d['versions'].update(parser='1.1'),
        lambda d:d['sources'][0]['commands'][0]['acquisition_evidence']['completion_evidence'].update(start_line=1),
        lambda d:next(s for s in d['scopes'] if s['empty_evidence'])['empty_evidence'].update(legends=[]),
    ):
        changed=deepcopy(snapshot);mutate(changed);changed['snapshot_id']=snapshot_hash(changed)
        with pytest.raises(RouteInputError):validate_snapshot(changed)


def test_health_and_standalone_use_same_closed_empty_evidence():
    prepared=prepare_sections((CASES/'before.txt').read_bytes())
    section=next(s for s in prepared.sections if s.command=='show ipv6 route vrf all')
    record=dict(status='success',confidence='high',source='alred_collect',command=section.command,
        start_line=section.start,end_line=section.end,output_start_line=section.prompt+1,output_end_line=section.end,
        collected_at=section.metadata['COLLECTED_AT'])
    p=_parse_record(prepared.terminal.raw,record,source_id='source',device='leaf01',command=resolve_route_command(section.command),prepared=prepared)
    assert p.document['scopes'][0]['empty_basis']=='closed_section'
    validate_snapshot(build_snapshot([p],side='before'))


def test_directory_pairing_expected_output_and_atomic_manifest(tmp_path):
    expected=json.loads((CASES/'directory-case/expected.json').read_text())
    a=args(tmp_path)
    assert execute(a)==expected['exit_code']
    result=json.loads((Path(a.output_dir)/'route-diff.json').read_text())
    assert result['summary']['coverage']==expected['coverage']
    assert result['summary']['complete_scope_count']==4 and result['summary']['unknown_scope_count']==2
    assert result['summary']['modes']['route-ad-cost-nexthop']['MODIFIED']==1
    resolved=json.loads((Path(a.output_dir)/'evidence/resolved-input.json').read_text())
    assert len(resolved['directory_discovery']['hosts'])==3
    verify_report(Path(a.output_dir),ProcessingControl())
    original=(Path(a.output_dir)/'report-manifest.json').read_bytes()
    with pytest.raises(RouteInputError):execute(a)
    assert (Path(a.output_dir)/'report-manifest.json').read_bytes()==original


def test_directory_empty_side_and_nested_discovery(tmp_path):
    before,after=tmp_path/'before',tmp_path/'after'
    (before/'nested').mkdir(parents=True);after.mkdir()
    (before/'nested/device.LOG').write_bytes((CASES/'before.txt').read_bytes())
    (before/'notes.json').write_text('{}')
    (before/'.hidden.log').write_bytes(b'bad')
    (before/'link.log').symlink_to(before/'nested/device.LOG')
    with pytest.raises(RouteInputError,match='no supported route'):resolve_inputs(args(tmp_path,before=str(before),after=str(after)),ProcessingControl())
    a=args(tmp_path,before=str(before),after=str(after),recursive=True)
    assert execute(a)==3
    result=json.loads((Path(a.output_dir)/'route-diff.json').read_text())
    assert result['summary']['unknown_scope_count']==2
    assert not result['entries']
    assert all(s['after'] is None for s in result['scopes'])


def test_directory_duplicate_and_unresolvable_host_are_not_skipped(tmp_path):
    before,after=tmp_path/'before',tmp_path/'after';before.mkdir();after.mkdir()
    for name in ('a.log','b.log'):(before/name).write_bytes((CASES/'before.txt').read_bytes())
    (after/'c.log').write_bytes((CASES/'after.txt').read_bytes())
    with pytest.raises(RouteInputError,match='duplicate scope'):execute(args(tmp_path,before=str(before),after=str(after)))
    (before/'b.log').write_text('no prompt')
    with pytest.raises(RouteInputError,match='one host'):execute(args(tmp_path,before=str(before),after=str(after)))


def test_directory_cancellation_does_not_publish(tmp_path):
    stop=False
    def progress(event):
        nonlocal stop
        if event['stage']=='publish_ready':stop=True
    with pytest.raises(RouteProcessingCancelled):
        execute(args(tmp_path),control=ProcessingControl(progress,lambda:stop))
    assert not (tmp_path/'result').exists()
    assert list(tmp_path.glob('.route-diff-stage-*'))


def test_section_detection_runs_once_per_source(tmp_path, monkeypatch):
    import alred.route_diff.cli as cli
    original=cli.prepare_sections
    seen=[]
    def capture(raw,**kwargs):
        seen.append(canonical_sha256({'raw':raw.hex()}))
        return original(raw,**kwargs)
    monkeypatch.setattr(cli,'prepare_sections',capture)
    assert execute(args(tmp_path))==3
    assert len(seen)==5  # One scan for each input file, reused for host discovery and parsing.


def test_missing_planned_route_is_unknown_but_explicit_other_af_can_complete():
    from alred.route_diff.cli import select_scopes
    raw=(CASES/'before.txt').read_text()
    raw=raw[:raw.index('### COMMAND: show ipv6 route vrf all')]
    # Close IPv4 using an idle prompt; a collect block still needs a validated next block.
    # Instead retain a nonroute block before the missing planned IPv6 command.
    raw=raw.replace('show ipv6 route vrf all\nshow interface brief\n', 'show interface brief\nshow ipv6 route vrf all\n',1)
    raw+='### COMMAND: show interface brief\n### COLLECTED_AT: 2026-09-13T10:00:00+09:00\n### STATUS: OK\n### TRANSPORT: ssh\nleaf01# show interface brief\nno interfaces\n'
    snapshots=pair(parse(raw=raw.encode()),parse(raw=raw.encode()))
    assert compare_snapshots(*snapshots)['summary']['coverage']=='PARTIAL'
    result=compare_snapshots(*snapshots,selected_scopes=select_scopes(snapshots,'ipv4',None))
    assert result['summary']['coverage']=='COMPLETE'


def test_ecmp_forwarding_associations_and_exact_policy():
    from alred.route_diff.domain import PATH_FIELDS, HOP_FIELDS
    raw=(CASES/'before.txt').read_text()
    line=next(s for s in raw.splitlines() if 'segid:' in s)
    second=line.replace('203.0.113.1','203.0.113.2').replace('19001','19002')
    old=raw.replace('198.51.100.0/24, ubest/mbest: 1/0','198.51.100.0/24, ubest/mbest: 2/0').replace(line,line+'\n'+second)
    same=old.replace(line+'\n'+second,second+'\n'+line)
    a,b=pair(parse(raw=old.encode()),parse(raw=same.encode()))
    assert compare_snapshots(a,b)['summary']['modes']['route-ad-cost-nexthop']['MODIFIED']==0
    swapped=old.replace(line,line.replace('19001','19002')).replace(second,second.replace('19002','19001'))
    a,b=pair(parse(raw=old.encode()),parse(raw=swapped.encode()))
    result=compare_snapshots(a,b)
    assert 'PATH_ASSOCIATION_CHANGED' in result['entries'][0]['reason_codes']
    route=next(r for r in a['routes'] if r['prefix']=='198.51.100.0/24')
    identity={k:route[k] for k in ('device','vrf','family','prefix')}
    policy=dict(api_version='alred/v1',kind='RouteDiffPolicy',metadata=dict(name='forwarding'),spec=dict(
        required_routes=[dict(identity,min_paths=2,expected_next_hops=dict(match='exact',paths=[{k:p[k] for k in HOP_FIELDS} for p in route['paths']]))]))
    assert compare_snapshots(a,b,policy=policy)['evaluation']=='FAIL'
    policy['spec']['required_routes'][0]['expected_next_hops']['paths']=[{k:p[k] for k in HOP_FIELDS} for p in next(r for r in b['routes'] if r['prefix']==route['prefix'])['paths']]
    decision=compare_snapshots(a,b,policy=policy)['policy_results']['required_routes'][0]
    assert decision['before_result']=='FAIL' and decision['after_result']=='PASS' and decision['recovered']
    expected=dict(prefix=route['prefix'],paths=[{k:p[k] for k in PATH_FIELDS} for p in route['paths']])
    assert expected['paths'][0]['segment_id'] in (19001,19002)


def test_invalid_tunnel_and_unknown_encapsulation_are_not_ignored():
    for old,new in ((b'0xcb007101',b'0x123456789'),(b'encap: VXLAN',b'encap: OTHER'),
                    (b'encap: VXLAN',b'encap: VXLAN extra'),(b'hmm',b'unknown-protocol')):
        doc=parse(raw=(CASES/'before.txt').read_bytes().replace(old,new)).document
        assert doc['scopes'][0]['coverage']=='UNKNOWN'


def test_markerless_empty_at_health_eof_remains_unknown():
    raw=(CASES/'before.txt').read_bytes()
    prepared=prepare_sections(raw)
    section=next(s for s in prepared.sections if s.command=='show ipv6 route vrf all')
    raw=raw[:prepared.terminal.lines[section.end-1].end_byte]
    prepared=prepare_sections(raw)
    section=prepared.sections[-1]
    record=dict(status='success',confidence='high',source='alred_collect',command=section.command,
        start_line=section.start,end_line=section.end,output_start_line=section.prompt+1,output_end_line=section.end,
        collected_at=section.metadata['COLLECTED_AT'])
    parsed=_parse_record(raw,record,source_id='source',device='leaf01',command=resolve_route_command(section.command))
    assert parsed.document['scopes'][0]['coverage']=='UNKNOWN'
    assert parsed.document['scopes'][0]['empty_basis'] is None
    validate_snapshot(build_snapshot([parsed],side='before'))


def test_directory_can_merge_disjoint_af_files(tmp_path):
    before,after=tmp_path/'before',tmp_path/'after';before.mkdir();after.mkdir()
    commands=[]
    for family in ('ip','ipv6'):
        heading='IP Route' if family=='ip' else 'IPv6 Routing'
        command=f'leaf01# show {family} route\n{heading} Table for VRF "default"\nNo routes\n'
        commands.append(command)
        (before/f'{family}.log').write_text(command+'leaf01#\n')
    (after/'combined.txt').write_text(''.join(commands)+'leaf01#\n')
    assert execute(args(tmp_path,before=str(before),after=str(after)))==0


def test_output_inside_directory_and_mixed_input_are_rejected(tmp_path):
    from alred.route_diff.cli import resolve_inputs
    with pytest.raises(RouteInputError,match='contain the output'):
        resolve_inputs(args(tmp_path,output_dir=str(CASES/'directory-case/before/output')),ProcessingControl())
    with pytest.raises(RouteInputError,match='both be files'):
        resolve_inputs(args(tmp_path,after=str(CASES/'after.txt')),ProcessingControl())
    with pytest.raises(RouteInputError,match='recursive'):
        resolve_inputs(args(tmp_path,before=str(CASES/'before.txt'),after=str(CASES/'after.txt'),recursive=True),ProcessingControl())


def test_idle_terminator_cannot_change_device_identity():
    from alred.route_diff.sections import discovered_hosts
    raw=b'leaf01# show ip route\nIP Route Table for VRF "default"\nNo routes\nleaf02#\n'
    assert discovered_hosts(prepare_sections(raw))=={'leaf01','leaf02'}
    with pytest.raises(RouteInputError,match='terminating prompt'):
        parse(raw=raw)


def test_input_modified_during_read_is_rejected(tmp_path, monkeypatch):
    import os
    from alred.route_diff.cli import read_bytes
    path=tmp_path/'changing.log';path.write_text('initial')
    original=os.fstat
    calls=0
    def changed(fd):
        nonlocal calls
        calls+=1
        if calls==3:
            with path.open('a') as stream:stream.write(' appended')
        return original(fd)
    monkeypatch.setattr(os,'fstat',changed)
    with pytest.raises(RouteInputError,match='changed while reading'):
        read_bytes(path)
