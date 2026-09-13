"""Route input foundation: real parser/validation against synthetic, offline fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from alred.route_diff.domain import RouteInputError, validate_policy, validate_source_map
from alred.route_diff.parser import parse_route_source
from alred.route_diff.terminal import normalize_terminal
from alred.schema import DocumentValidationError, validate_document

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs/design/network-ops/examples/route-diff-review"
BODY = ('IP Route Table for VRF "TENANT-A"\n'
        '192.0.2.0/24, ubest/mbest: 1/0\n'
        '    *via 192.0.2.1, Eth1/1, [110/20], 00:01:00, ospf-UNDERLAY, intra\n')


def parse(body=BODY, **kwargs):
    raw = f'leaf01# show ip route vrf all\n{body}leaf01#\n'.encode()
    return parse_route_source(raw, device='leaf01', source_id='test', **kwargs).document


def policy():
    return yaml.safe_load((REVIEW / 'expected-changes.example.yaml').read_text())


def test_expected_policy_canonicalization_keeps_table_af_and_does_not_mutate():
    value = policy()
    original = deepcopy(value)
    normalized = validate_policy(value, selected_scopes={('leaf01','TENANT-A','ipv4')})
    assert value == original
    assert normalized['spec']['expected_changes'][0]['after']['paths'][0]['next_hop_table_family'] is None
    validate_document(normalized, kind='RouteDiffPolicy')


@pytest.mark.parametrize('change', ['af','prefix','link_local','duplicate_path','duplicate_rule','duplicate_id','unchanged','excluded','scope','kind','table_family'])
def test_policy_domain_errors(change):
    value = policy()
    rule = value['spec']['expected_changes'][0]
    path = rule['after']['paths'][0]
    if change == 'af': path['next_hop_family'] = 'ipv6'
    elif change == 'prefix': rule['prefix'] = '192.0.2.1/24'
    elif change == 'link_local': path.update(address='fe80::1',next_hop_family='ipv6',interface=None)
    elif change == 'duplicate_path': rule['after']['paths'].append(deepcopy(path))
    elif change == 'duplicate_rule': value['spec']['expected_changes'].append(deepcopy(rule))
    elif change == 'duplicate_id':
        copy = deepcopy(rule)
        copy['prefix'] = copy['before']['prefix'] = copy['after']['prefix'] = '198.51.100.0/24'
        value['spec']['expected_changes'].append(copy)
    elif change == 'unchanged': rule['after'] = deepcopy(rule['before'])
    elif change == 'excluded': value['spec']['exclusions'] = [{**{k:rule[k] for k in ('device','vrf','family','prefix')},'reason':'test'}]
    elif change == 'kind': path['kind'] = 'discard'
    elif change == 'table_family': path['next_hop_table_family'] = 'ipv5'
    scopes = set() if change == 'scope' else None
    with pytest.raises((RouteInputError, DocumentValidationError)):
        validate_policy(value, selected_scopes=scopes)


def test_source_map_overlap_is_checked_per_side_and_relative_path(tmp_path):
    value = yaml.safe_load((REVIEW / 'source-map.example.yaml').read_text())
    a = value['spec']['hosts'][0]['before'][0]
    a.update(start_line=1, end_line=10)
    b = deepcopy(a)
    b.update(path='inputs/leaf01/../leaf01/before-route.log',start_line=10,end_line=15)
    value['spec']['hosts'][0]['before'].append(b)
    with pytest.raises(RouteInputError,match='overlap'):
        validate_source_map(value, base_dir=tmp_path)
    b['start_line'] = 11
    validate_source_map(value, base_dir=tmp_path)
    value['spec']['hosts'][0]['after'] = [deepcopy(a)]
    validate_source_map(value, base_dir=tmp_path)
    b['end_line'] = 1
    with pytest.raises(RouteInputError): validate_source_map(value,base_dir=tmp_path)


@pytest.mark.parametrize('case', json.loads((REVIEW/'terminal-cases.example.json').read_text())['cases'], ids=lambda c:c['id'])
def test_terminal_and_parser_against_authored_expectations(case):
    raw = case['raw_text'].encode()
    result = normalize_terminal(raw)
    assert result.raw == raw
    assert result.manifest()['raw_sha256'] == case['raw_sha256']
    assert result.manifest()['mapping'] == case['expected_mapping'] or case['expected_normalized_text'] is None
    if case['expected_normalized_text'] is not None:
        assert result.text == case['expected_normalized_text']
    declaration = case['input_contract']
    parsed = parse_route_source(raw, device='leaf01',source_id='terminal',
        input_format=declaration['input_format'],command_id=declaration['command_id'],
        completeness='asserted' if declaration['completeness']=='asserted' else None).document
    scope = parsed['scopes'][0]
    assert scope['parse_status'] == case['parse_status']
    assert scope['health_eligible'] == case['health_eligible']
    assert all(0 <= m['raw_start_byte'] < m['raw_end_byte'] <= len(raw) for m in result.manifest()['mapping'])


@pytest.mark.parametrize('raw', [b'\xff',b'\xc3',b'\xe3\x28\x80'])
def test_invalid_utf8_is_not_replaced(raw):
    with pytest.raises(RouteInputError,match='UTF-8'): normalize_terminal(raw)


def test_single_cr_and_backspace_are_preserved_and_reported():
    raw = b'a\rb\bc\n'
    result = normalize_terminal(raw)
    assert result.text.encode() == raw
    assert len(result.lines) == 1
    assert len(result.diagnostics) == 2


def test_source_provenance_and_cost_ecmp_fields_from_mock_logs():
    raw = (ROOT/'tests/fixtures/nxos/route_diff/synthetic/leaf01-before-route.txt').read_bytes()
    doc = parse_route_source(raw,device='leaf01',source_id='leaf01-before').document
    assert [(s['family'],len(s['routes'])) for s in doc['scopes']] == [('ipv4',6),('ipv6',4)]
    assert all(s['coverage']=='COMPLETE' for s in doc['scopes'])
    route = next(r for s in doc['scopes'] for r in s['routes'] if r['prefix']=='198.51.100.128/25')
    assert len(route['paths'])==2
    for path in route['paths']:
        assert path['admin_distance']==110 and path['metric']==20
        ev=path['evidence']
        assert b'*via' in raw[ev['start_byte']:ev['end_byte']]
    assert doc['terminal']['raw_sha256']=='sha256:'+hashlib.sha256(raw).hexdigest()


def test_mapped_ipv6_preserves_address_family_and_reference_table():
    body=('IPv6 Routing Table for VRF "TENANT-A"\n2001:db8::/64, ubest/mbest: 1/0\n'
          '*via ::ffff:192.0.2.1%default:IPv4, [200/0], bgp-65001, internal\n')
    doc=parse_route_source(body.encode(), device='leaf01',source_id='body',input_format='nxos-route-text',
                           command_id='route_ipv6_all_vrfs',completeness='asserted').document
    s=doc['scopes'][0]
    p=s['routes'][0]['paths'][0]
    assert s['coverage']=='COMPLETE' and not s['health_eligible']
    assert p['address']=='::ffff:c000:201' and p['next_hop_family']=='ipv6'
    assert p['next_hop_table_family']=='ipv4' and p['next_hop_vrf']=='default'


@pytest.mark.parametrize('body', [BODY.replace('1/0','2/0'), BODY.replace('[110/20]','[110/?]'),
    BODY.replace('192.0.2.0/24','192.0.2.1/24'), BODY+'unknown text\n',
    BODY.replace('Eth1/1','not-an-interface'), BODY+BODY, BODY.replace('intra','unknown-attribute')])
def test_bad_routes_never_become_complete(body):
    scope=parse(body)['scopes'][0]
    assert scope['coverage']=='UNKNOWN' and not scope['health_eligible']
    assert scope['diagnostics']


def test_heading_alone_is_unknown_and_explicit_empty_is_complete():
    heading='IP Route Table for VRF "TENANT-A"\n'
    assert parse(heading)['scopes'][0]['coverage']=='UNKNOWN'
    scope=parse(heading+'No routes\n')['scopes'][0]
    assert scope['coverage']=='COMPLETE' and scope['parsed_prefix_count']==0
    assert parse(BODY+'No routes\n')['scopes'][0]['coverage']=='UNKNOWN'


def test_nonselected_paths_do_not_change_unicast_count():
    body=BODY+'    via 192.0.2.2, Eth1/2, [200/20], bgp-65001, internal\n'
    scope=parse(body)['scopes'][0]
    assert scope['coverage']=='COMPLETE'
    assert len(scope['routes'][0]['paths'])==1
    assert len(scope['routes'][0]['non_selected_paths'])==1


@pytest.mark.parametrize(('hop','protocol','kind'), [('Null0','static','discard'),('192.0.2.1, Eth1/1','direct','connected'),('Eth1/1','local','local')])
def test_special_next_hop_kinds(hop,protocol,kind):
    body='IP Route Table for VRF "TENANT-A"\n192.0.2.0/24, ubest/mbest: 1/0, attached\n'+f'*via {hop}, [0/0], {protocol}\n'
    s=parse(body)['scopes'][0]
    assert s['coverage']=='COMPLETE'
    assert s['routes'][0]['paths'][0]['kind']==kind


def test_duplicate_commands_require_interval_and_evidence_stays_in_original_coordinates():
    raw=(f'leaf01# show ip route vrf all\n{BODY}leaf01#\n'*2).encode()
    with pytest.raises(RouteInputError,match='duplicate route command'):
        parse_route_source(raw,device='leaf01',source_id='all')
    result=parse_route_source(raw,device='leaf01',source_id='slice',start_line=6,end_line=10)
    scope=result.document['scopes'][0]
    assert scope['coverage']=='COMPLETE'
    assert scope['routes'][0]['evidence']['start_line']==8


def test_eof_assertion_and_host_mismatch_are_not_silently_trusted():
    doc=parse_route_source(('leaf01# show ip route vrf all\n'+BODY).encode(),device='leaf01',source_id='eof').document
    s=doc['scopes'][0]
    assert s['parse_status']=='COMPLETE' and s['coverage']=='UNKNOWN'
    assert s['verification_reason']
    with pytest.raises(RouteInputError,match='identity'):
        parse_route_source(('other# show ip route vrf all\n'+BODY).encode(),device='leaf01',source_id='wrong')


@pytest.mark.parametrize(('value','expected'), [
    ('::','::'), ('::1','::1'), ('2001:0db8:0:0:1:0:0:1','2001:db8::1:0:0:1'),
    ('2001:db8:0:1:2:3:4:5','2001:db8:0:1:2:3:4:5'), ('::ffff:192.0.2.1','::ffff:c000:201'),
])
def test_ipv6_text_is_stable_across_python_rendering_changes(value,expected):
    import ipaddress
    from alred.route_diff.domain import canonical_address
    assert canonical_address(ipaddress.ip_address(value))==expected


@pytest.mark.parametrize(('host','side','counts','coverage'),[
    ('leaf01','before',[6,4],'COMPLETE'),('leaf01','after',[6,4],'COMPLETE'),
    ('leaf02','before',[1,1],'COMPLETE'),('leaf02','after',[1,1],'COMPLETE'),
    ('leaf03','before',[1],'COMPLETE'),('leaf03','after',[0],'UNKNOWN'),
])
def test_full_synthetic_fixture_expectations(host,side,counts,coverage):
    file=ROOT/f'tests/fixtures/nxos/route_diff/synthetic/{host}-{side}-route.txt'
    doc=parse_route_source(file.read_bytes(),device=host,source_id=side).document
    assert [s['parsed_prefix_count'] for s in doc['scopes']]==counts
    assert all(s['coverage']==coverage for s in doc['scopes'])


def test_cancellation_during_processing_does_not_modify_raw_or_return_partial_success():
    from alred.route_diff.control import ProcessingControl, RouteProcessingCancelled
    raw=('leaf01# show ip route vrf all\n'+BODY+'leaf01#\n').encode()
    events=[]
    cancelled=False
    def progress(event):
        nonlocal cancelled
        events.append(event)
        if event['stage']=='parse': cancelled=True
    with pytest.raises(RouteProcessingCancelled):
        parse_route_source(raw,device='leaf01',source_id='cancel',
            control=ProcessingControl(on_progress=progress,is_cancelled=lambda:cancelled))
    assert any(e['stage']=='parse' for e in events)
    assert raw==('leaf01# show ip route vrf all\n'+BODY+'leaf01#\n').encode()


def test_scoped_unknown_does_not_discard_other_vrf_routes():
    body=BODY+'IP Route Table for VRF "OTHER"\n198.51.100.0/24, ubest/mbest: 1/0\n*via 192.0.'
    scopes=parse(body+'\n')['scopes']
    assert scopes[0]['coverage']=='COMPLETE'
    assert scopes[1]['coverage']=='UNKNOWN'


def test_unowned_trailing_content_is_not_silently_ignored():
    raw=('leaf01# show ip route vrf all\n'+BODY+'leaf01#\nunknown trailing content\n').encode()
    doc=parse_route_source(raw,device='leaf01',source_id='trailing').document
    assert doc['diagnostics'][0]['code']=='UNRESOLVED_SEGMENT'
    assert doc['scopes'][0]['coverage']=='UNKNOWN'


def test_explicit_other_command_sections_do_not_contaminate_route_output():
    raw=('leaf01# show version\nnot route content\nleaf01# show ip route vrf all\n'+BODY+'leaf01#\n').encode()
    doc=parse_route_source(raw,device='leaf01',source_id='mixed').document
    assert doc['scopes'][0]['coverage']=='COMPLETE'


@pytest.mark.parametrize('body',[BODY.replace('[110/20]','[110/'+'9'*5000+']'),BODY.replace('1/0','9'*5000+'/0')])
def test_undecodable_integers_are_unknown_not_internal_exceptions(body):
    assert parse(body)['scopes'][0]['coverage']=='UNKNOWN'
