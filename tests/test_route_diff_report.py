"""Offline report invariants: shared counts, evidence, escaping and review identity."""
from copy import deepcopy
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import re

import pytest

from alred.route_diff.comparator import compare_snapshots, validate_diff
from alred.route_diff.control import ProcessingControl, RouteProcessingCancelled
from alred.route_diff.domain import RouteInputError
from alred.route_diff.parser import parse_route_source
from alred.route_diff.report import (build_report_model, pair_paths, render_checklist, render_csv,
                                    render_html, render_markdown, safe_component, write_route_report)
from alred.route_diff.review import review_catalog, validate_review
from alred.route_diff.semantics import MODES, PRIMARY_MODE
from alred.route_diff.snapshot import build_snapshot
from alred.schema import DocumentValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/nxos/route_diff/synthetic'


@pytest.fixture(scope='module')
def inputs():
    snapshots, raw = [], {}
    for side in ('before', 'after'):
        parsed, paths = [], {}
        for host in ('leaf01', 'leaf02', 'leaf03'):
            filename = f'{host}-{side}-route.txt'
            raw[side,host] = (FIXTURES / filename).read_bytes()
            parsed.append(parse_route_source(raw[side,host],source_id=host,device=host))
            paths[host] = filename
        snapshots.append(build_snapshot(parsed,side=side,source_paths=paths))
    return *snapshots, compare_snapshots(*snapshots), raw


@pytest.fixture(scope='module')
def model(inputs):
    return build_report_model(*inputs)


def embedded(document):
    return json.loads(re.search(r'<script id="route-data" type="application/json">(.*?)</script>',document,re.S)[1])


def test_all_formats_share_counts_and_unknown(model):
    validate_diff(model['result'])
    data=embedded(render_html(model))
    assert data['result']['summary']==model['result']['summary']
    for mode,modified in zip(MODES,[0,1,3,5,7]):
        rows=[r for r in data['rows'] if r['modes'][mode]['change_type']!='UNCHANGED']
        assert len(rows)==modified+2
        assert f'MODIFIED={modified}' in render_checklist(model)
        md=render_markdown(model,mode=mode)
        assert md.count('```diff')==len(rows)
        assert 'UNKNOWN' in md
    csv_rows=list(csv.DictReader(StringIO(render_csv(model))))
    assert len(csv_rows)==10
    unknown=next(r for r in csv_rows if r['status']=='UNKNOWN')
    assert unknown['device']=='leaf03' and unknown['prefix']==''
    for row in csv_rows:
        if row['prefix']:
            assert json.loads(row['reason_codes'])
            assert json.loads(row['evidence_after'])['source_id']
    assert model['result']['versions']['renderer']=='1.1'


def test_raw_provenance_mode_colors_and_original_lines(model,inputs):
    a=next(s for s in model['sources'] if s['meta']['id']=='leaf01' and s['meta']['side']=='before')
    route=next(r for r in model['rows'] if r['resource']['prefix']=='192.0.2.64/26')
    line=str(route['before']['paths'][0]['evidence']['start_line'])
    assert a['colors']['route-ad'][line]=='≈'
    assert a['colors']['route-ad-cost'][line]=='−'
    assert a['lines']==inputs[3]['before','leaf01'].decode().splitlines()
    unknown=[s for s in model['sources'] if s['meta']['id']=='leaf03']
    assert all('−' not in s['colors'][PRIMARY_MODE].values() and '+' not in s['colors'][PRIMARY_MODE].values() for s in unknown)
    assert all('?' in s['colors'][PRIMARY_MODE].values() for s in unknown)


def test_pairing_preserves_common_ecmp_and_does_not_invent_nh_links(model):
    row=next(r for r in model['rows'] if r['resource']['prefix']=='198.51.100.128/25')
    assert [p['kind'] for p in row['modes'][PRIMARY_MODE]['pairs']]==['common','removed']
    a=deepcopy(row['before']); b=deepcopy(a)
    for p in b['paths']:p['address']='192.0.2.200';p['metric']+=10
    assert {p['kind'] for p in pair_paths(a,b,PRIMARY_MODE)}=={'removed','added'}
    b=deepcopy(a);b['paths'][0]['metric']+=10
    assert [p['kind'] for p in pair_paths(a,b,PRIMARY_MODE)]==['common','attributes']
    b=deepcopy(a)
    for p in b['paths']:p['next_hop_table_family']='ipv6'
    assert {p['kind'] for p in pair_paths(a,b,PRIMARY_MODE)}=={'removed','added'}


def test_ambiguous_same_next_hop_is_unpaired(model):
    row=next(r for r in model['rows'] if r['resource']['prefix']=='192.0.2.64/26')
    a=deepcopy(row['before']);b=deepcopy(a)
    for r in (a,b):r['paths'].append(deepcopy(r['paths'][0]))
    a['paths'][1]['metric']=40
    b['paths'][0]['metric']=30;b['paths'][1]['metric']=50
    pairs=pair_paths(a,b,PRIMARY_MODE)
    assert [p['kind'] for p in pairs]==['removed','removed','added','added']


def test_no_unknown_scope_is_synthesized_as_removed(model):
    assert all(r['resource']['device']!='leaf03' for r in model['rows'])
    assert 'UNKNOWN / 未観測' in render_markdown(model,host='leaf03',family='ipv6')
    assert '[ ] leaf03' in render_checklist(model)


@pytest.mark.parametrize('which',['raw','result','snapshot','missing_raw'])
def test_reject_evidence_mismatch_without_creating_files(inputs,tmp_path,which):
    a,b,d,raw=deepcopy(inputs)
    if which=='raw':raw['before','leaf01']+=b'\n'
    elif which=='result':d['sources'][0]['path']='other'
    elif which=='snapshot':a['routes'][0]['prefix']='192.0.0.0/16'
    else:raw.pop(('before','leaf01'))
    out=tmp_path/'route_diff'
    with pytest.raises((RouteInputError,DocumentValidationError)):
        write_route_report(a,b,d,raw,out)
    assert not out.exists()


def test_output_layout_manifest_hashes_and_no_overwrite(inputs,tmp_path):
    out=tmp_path/'route_diff'
    manifest=write_route_report(*inputs,out)
    assert len(manifest['files'])==44
    for name,digest in manifest['files'].items():
        assert digest=='sha256:'+hashlib.sha256((out/name).read_bytes()).hexdigest()
    assert len(list((out/'hosts/leaf01').glob('*.md')))==10
    assert (out/'hosts/leaf01/route-diff-v4-route-ad-cost_leaf01-before-route.txt_leaf01-after-route.txt.md').exists()
    assert embedded((out/'hosts/leaf01/route-diff-raw.html').read_text())['initial_raw']
    assert not embedded((out/'hosts/leaf01/route-diff-diffonly.html').read_text())['initial_raw']
    assert json.loads((out/'report-manifest.json').read_text())==manifest
    with pytest.raises(RouteInputError,match='already exists'):
        write_route_report(*inputs,out)
    assert json.loads((out/'report-manifest.json').read_text())==manifest


def test_interrupted_output_has_no_success_manifest_and_retry_uses_new_directory(inputs,tmp_path):
    cancelled=False
    def progress(event):
        nonlocal cancelled
        if event['stage']=='render_files' and event['completed']==2:cancelled=True
    control=ProcessingControl(progress,lambda:cancelled)
    out=tmp_path/'partial'
    with pytest.raises(RouteProcessingCancelled):write_route_report(*inputs,out,control=control)
    assert out.exists() and (out/'route-diff.json').exists()
    assert not (out/'report-manifest.json').exists()
    write_route_report(*inputs,tmp_path/'retry')
    assert (tmp_path/'retry/report-manifest.json').exists()


def test_safe_filenames_and_html_csv_markdown_injection(model):
    assert safe_component('before-route.log')=='before-route.log'
    for name in ('../../escape','a\\b','a/b','a'*1000,'<script>','..','a\x00b'):
        cleaned=safe_component(name)
        assert '/' not in cleaned and '\\' not in cleaned and len(cleaned)<=64 and cleaned not in ('','.','..')
    assert safe_component('a/b')!=safe_component('a\\b')
    unsafe=deepcopy(model)
    payload='</script><img src="https://invalid.test" onerror="alert(1)">'
    unsafe['sources'][0]['meta']['path']=payload
    text=render_html(unsafe)
    assert payload not in text and embedded(text)['sources'][0]['meta']['path']==payload
    unsafe['result']['sources'][0]['path']=payload
    assert '<img' not in render_markdown(unsafe)
    unsafe['result']['entries'][0]['device']='=HYPERLINK("bad")'
    row=next(csv.DictReader(StringIO(render_csv(unsafe))))
    assert row['device'].startswith("'=")


def test_terminal_controls_are_visible_but_original_bytes_are_available():
    import base64
    raw=b'leaf01# show ip route\r\nIP Route Table for VRF "default"\r\nNo routes\x1b[31m\r\nleaf01#\r\n'
    p=parse_route_source(raw,source_id='s',device='leaf01')
    a,b=[build_snapshot([p],side=s) for s in ('before','after')]
    model=build_report_model(a,b,compare_snapshots(a,b),{('before','s'):raw,('after','s'):raw})
    source=model['sources'][0]
    assert source['lines'][2]=='No routes\\x1b[31m'
    assert base64.b64decode(source['bytes'])==raw


def review_record(model):
    key,target=next(iter(review_catalog(model).items()))
    return dict(schema_version=1,kind='RouteDiffReview',comparison_fingerprint=model['result']['comparison_fingerprint'],
                entries=[dict(entry_key=key,**target,status='REVIEWED',comment='Cost を確認',reviewed_at='2026-09-13T12:34:56Z')])


def test_review_roundtrip_is_separate_and_mode_scoped(model):
    original=deepcopy(model)
    record=review_record(model)
    assert validate_review(record,model)==record
    assert model==original
    assert len(review_catalog(model))==2+3+5+7+9


@pytest.mark.parametrize('field',['fingerprint','key','resource','mode','duplicate','timestamp','bad_date','extra'])
def test_review_rejects_all_invalid_entries_atomically(model,field):
    record=review_record(model);e=record['entries'][0]
    if field=='fingerprint':record['comparison_fingerprint']='sha256:'+'0'*64
    elif field=='key':e['entry_key']='sha256:'+'0'*64
    elif field=='resource':e['resource']=dict(e['resource'],vrf='OTHER')
    elif field=='mode':e['mode']=PRIMARY_MODE
    elif field=='duplicate':record['entries'].append(deepcopy(e))
    elif field=='timestamp':e['reviewed_at']=None
    elif field=='bad_date':e['reviewed_at']='2026-02-30T00:00:00Z'
    else:record['entries'].append({})
    with pytest.raises((RouteInputError,DocumentValidationError)):validate_review(record,model)


@pytest.mark.parametrize('include_complete',[False,True])
def test_unscoped_unknown_source_report_remains_available(include_complete):
    sources=[parse_route_source(b'unknown terminal output\n',source_id='bad',device='leaf03')]
    raw={('before','bad'):b'unknown terminal output\n',('after','bad'):b'unknown terminal output\n'}
    if include_complete:
        data=(FIXTURES/'leaf01-before-route.txt').read_bytes()
        sources.append(parse_route_source(data,source_id='good',device='leaf01'))
        raw.update({('before','good'):data,('after','good'):data})
    a,b=[build_snapshot(sources,side=s) for s in ('before','after')]
    d=compare_snapshots(a,b)
    model=build_report_model(a,b,d,raw)
    assert model['result']['summary']['unknown_source_count']==2
    unknown=[s for s in model['sources'] if s['meta']['id']=='bad']
    assert all(set(s['colors'][PRIMARY_MODE].values())=={'?'} for s in unknown)
    assert render_csv(model).count('UNSCOPED_SOURCE')==2
