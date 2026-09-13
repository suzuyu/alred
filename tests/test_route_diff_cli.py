"""Standalone CLI input resolution, source evidence, publication and exit contracts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest
import yaml

from alred.cli import build_parser
from alred.route_diff import cli
from alred.route_diff.comparator import compare_snapshots
from alred.route_diff.control import ProcessingControl, RouteProcessingCancelled
from alred.route_diff.domain import RouteInputError
from alred.route_diff.report import build_report_model
from alred.route_diff.review import review_catalog

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/nxos/route_diff/synthetic'


@pytest.fixture
def arguments(tmp_path):
    before,after=[FIXTURES/f'leaf01-{side}-route.txt' for side in ('before','after')]
    return ['route-diff-nxos','--before',str(before),'--after',str(after),'--input-format','nxos-transcript','--output-dir',str(tmp_path/'report'),'--no-progress']


def invoke(arguments):
    args=build_parser().parse_args(arguments)
    return args.func(args)


def read_result(arguments):
    out=Path(arguments[arguments.index('--output-dir')+1])
    return json.loads((out/'route-diff.json').read_text())


def test_two_file_cli_to_report_preserves_raw_snapshots_and_codes(arguments,capsys):
    assert invoke(arguments)==0
    result=read_result(arguments)
    assert result['evaluation']=='NOT_EVALUATED'
    assert result['summary']['modes']['route-ad-cost-nexthop']['MODIFIED']==7
    out=Path(arguments[arguments.index('--output-dir')+1])
    manifest=cli.verify_report(out,ProcessingControl())
    assert len(manifest['files'])==24
    inputs=json.loads((out/'evidence/resolved-input.json').read_text())
    for source in inputs['sources']:
        assert (out/source['stored_path']).read_bytes()==Path(source['path']).read_bytes()
    assert (out/'evidence/route-snapshot-before.json').exists()
    assert (out/'route-diff-review.json').exists()
    assert not list(out.parent.glob('.route-diff-*'))
    stdout,stderr=capsys.readouterr()
    assert 'Coverage: COMPLETE' in stdout and stderr==''


@pytest.mark.parametrize('extra',[['--host','other'],['--command-vrf','TENANT-A'],['--completeness','asserted'],['--vrf',''],['--source-map','missing.yaml']])
def test_invalid_option_combinations_do_not_publish(arguments,extra,capsys):
    assert invoke(arguments+extra)==2
    assert 'VALIDATION_ERROR:' in capsys.readouterr().err
    assert not Path(arguments[arguments.index('--output-dir')+1]).exists()


@pytest.mark.parametrize('missing',['--before','--after','--input-format'])
def test_missing_required_pair_option(arguments,missing,capsys):
    position=arguments.index(missing);del arguments[position:position+2]
    assert invoke(arguments)==2
    assert 'VALIDATION_ERROR:' in capsys.readouterr().err


def test_missing_input_no_traceback(arguments,capsys):
    arguments[arguments.index('--before')+1]='/no/such/route-input.log'
    assert invoke(arguments)==2
    error=capsys.readouterr().err
    assert 'INPUT_NOT_FOUND:' in error and 'Traceback' not in error


@pytest.mark.parametrize('extra,unknown',[(['--af','ipv6','--vrf','MISSING'],True),(['--vrf','TENANT-A','--af','ipv4'],False)])
def test_explicit_scope_selects_or_reports_missing(arguments,extra,unknown):
    assert invoke(arguments+extra)==(3 if unknown else 0)
    result=read_result(arguments)
    selected=[s for s in result['scopes'] if s['coverage']!='NOT_SELECTED']
    assert len(selected)==1
    assert selected[0]['coverage']==('UNKNOWN' if unknown else 'COMPLETE')
    if unknown:assert all(v is None for v in selected[0]['modes']['route-only'].values())


def test_source_map_resolves_relative_paths_from_yaml_directory(tmp_path,monkeypatch,capsys):
    directory=tmp_path/'input';directory.mkdir()
    hosts=[]
    for host in ('leaf01','leaf02','leaf03'):
        item=dict(host=host)
        for side in ('before','after'):
            name=f'{host}-{side}.log'
            (directory/name).write_bytes((FIXTURES/f'{host}-{side}-route.txt').read_bytes())
            item[side]=[dict(path=name,input_format='nxos-transcript')]
        hosts.append(item)
    mapping=dict(api_version='alred/v1',kind='RouteDiffSourceMap',metadata=dict(name='test'),spec=dict(hosts=hosts))
    path=directory/'map.yaml';path.write_text(yaml.safe_dump(mapping))
    monkeypatch.chdir(tmp_path)
    assert invoke(['route-diff-nxos','--source-map',str(path),'--no-progress'])==3
    out=tmp_path/'route_diff'
    result=json.loads((out/'route-diff.json').read_text())
    assert result['summary']['coverage']=='PARTIAL'
    assert result['summary']['unknown_scope_count']==1
    assert (out/'evidence/source-map.yaml').read_bytes()==path.read_bytes()
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('asserted',[False,True])
def test_body_only_default_and_specific_commands(tmp_path,asserted):
    body='IP Route Table for VRF "TENANT-A"\n192.0.2.0/24, ubest/mbest: 1/0\n *via 192.0.2.1, Ethernet1/1, [110/20], static\n'
    before=tmp_path/'before.log';after=tmp_path/'after.log'
    before.write_text(body);after.write_text(body.replace('[110/20]','[110/30]'))
    args=['route-diff-nxos','--before',str(before),'--after',str(after),'--input-format','nxos-route-text','--host','leaf01',
          '--command-id','route_ipv4_vrf','--command-vrf','TENANT-A','--output-dir',str(tmp_path/'report'),'--no-progress']
    if asserted:args+=['--completeness','asserted']
    assert invoke(args)==(0 if asserted else 3)
    d=read_result(args)
    if asserted:
        assert d['summary']['modes']['route-ad-cost']['MODIFIED']==1
        assert not d['scopes'][0]['before']['health_eligible']
    else:assert d['entries']==[]


def test_unknown_with_explicit_host_and_missing_af_is_not_empty_success(tmp_path):
    before=tmp_path/'before.log';after=tmp_path/'after.log'
    before.write_bytes(b'');after.write_bytes(b'')
    args=['route-diff-nxos','--before',str(before),'--after',str(after),'--input-format','nxos-transcript','--host','leaf01','--af','ipv6','--output-dir',str(tmp_path/'report'),'--no-progress']
    assert invoke(args)==3
    d=read_result(args)
    assert d['scopes'][0]['family']=='ipv6' and d['entries']==[]


def test_policy_warn_and_fail_exit_codes(arguments,tmp_path):
    policy=ROOT/'docs/design/network-ops/examples/route-diff-review/expected-changes.example.yaml'
    assert invoke(arguments+['--policy',str(policy),'--af','ipv4','--vrf','TENANT-A'])==1
    data=yaml.safe_load(policy.read_text())
    data['spec']['required_routes'][0]['min_paths']=50
    file=tmp_path/'fail.yaml';file.write_text(yaml.safe_dump(data))
    arguments[arguments.index('--output-dir')+1]=str(tmp_path/'failed-health')
    assert invoke(arguments+['--policy',str(file),'--af','ipv4','--vrf','TENANT-A'])==4
    assert read_result(arguments)['evaluation']=='FAIL'


def test_labels_do_not_change_fingerprint_and_review_restores(arguments,tmp_path):
    assert invoke(arguments)==0
    first=Path(arguments[arguments.index('--output-dir')+1])
    d=read_result(arguments)
    a,b=[json.loads((first/f'evidence/route-snapshot-{side}.json').read_text()) for side in ('before','after')]
    raw={(s['side'],s['id']):Path(s['path']).read_bytes() for s in d['sources']}
    model=build_report_model(a,b,d,raw)
    key,item=next(iter(review_catalog(model).items()))
    record=dict(schema_version=1,kind='RouteDiffReview',comparison_fingerprint=d['comparison_fingerprint'],
                entries=[dict(entry_key=key,**item,status='REVIEWED',comment='確認',reviewed_at='2026-09-13T01:02:03Z')])
    file=tmp_path/'review.json';file.write_text(json.dumps(record))
    arguments[arguments.index('--output-dir')+1]=str(tmp_path/'second')
    assert invoke(arguments+['--before-label','作業前','--after-label','作業途中','--review',str(file)])==0
    assert read_result(arguments)['comparison_fingerprint']==d['comparison_fingerprint']
    assert json.loads((tmp_path/'second/route-diff-review.json').read_text())==record
    assert '作業途中' in (tmp_path/'second/index.html').read_text()
    record['comparison_fingerprint']='sha256:'+'0'*64;file.write_text(json.dumps(record))
    arguments[arguments.index('--output-dir')+1]=str(tmp_path/'third')
    assert invoke(arguments+['--review',str(file)])==2
    assert not (tmp_path/'third').exists()
    assert (first/'report-manifest.json').exists()


@pytest.mark.parametrize('text',['a: 1\na: 2\n','a: &loop [*loop]\n','? [a, b]\n: c\n'])
def test_yaml_rejects_duplicate_cyclic_or_complex_keys(text):
    with pytest.raises(RouteInputError):cli.load_yaml(text.encode())


def test_hardlink_overlap_rejected(tmp_path):
    source=tmp_path/'source.log';source.write_bytes((FIXTURES/'leaf01-before-route.txt').read_bytes())
    alias=tmp_path/'alias.log';os.link(source,alias)
    entry=lambda p:dict(path=p,input_format='nxos-transcript')
    doc=dict(api_version='alred/v1',kind='RouteDiffSourceMap',metadata=dict(name='test'),spec=dict(hosts=[dict(host='leaf01',before=[entry('source.log'),entry('alias.log')],after=[entry('source.log')])]))
    mapping=tmp_path/'map.yaml';mapping.write_text(yaml.safe_dump(doc))
    assert invoke(['route-diff-nxos','--source-map',str(mapping),'--output-dir',str(tmp_path/'report'),'--no-progress'])==2
    assert not (tmp_path/'report').exists()


@pytest.mark.parametrize('kind',['file','nonempty','symlink','empty'])
def test_existing_outputs_are_preserved_or_empty_directory_published(arguments,kind,tmp_path):
    output=tmp_path/'report'
    if kind=='file':output.write_text('original')
    elif kind=='symlink':output.symlink_to(tmp_path/'missing')
    else:
        output.mkdir()
        if kind=='nonempty':(output/'original').write_text('keep')
    assert invoke(arguments)==(0 if kind=='empty' else 2)
    if kind=='file':assert output.read_text()=='original'
    if kind=='nonempty':assert (output/'original').read_text()=='keep'
    if kind=='symlink':assert output.is_symlink()
    if kind=='empty':assert (output/'report-manifest.json').exists()


@pytest.mark.parametrize('stage',['parse','render_files','publish_ready'])
def test_cancel_keeps_staging_and_old_success_then_retry(arguments,tmp_path,stage):
    old=tmp_path/'old';old.mkdir();(old/'current.json').write_text('previous success')
    cancelled=False
    def progress(e):
        nonlocal cancelled
        if e['stage']==stage:cancelled=True
    control=ProcessingControl(progress,lambda:cancelled)
    args=build_parser().parse_args(arguments)
    # Cancellation at the final checkpoint must be observed before rename too.
    with pytest.raises(RouteProcessingCancelled):cli.execute(args,control=control)
    assert not (tmp_path/'report').exists()
    partial=list(tmp_path.glob('.route-diff-stage-*'))
    assert partial and list(partial[0].rglob('resolved-input.json'))
    assert (old/'current.json').read_text()=='previous success'
    assert invoke(arguments)==0
    assert partial[0].exists()


def test_publish_never_overwrites_new_rival_directory(arguments,tmp_path,monkeypatch,capsys):
    original=cli.rename_no_replace
    def rival(source,target):
        target.mkdir()
        (target/'rival').write_text('preserve')
        original(source,target)
    monkeypatch.setattr(cli,'rename_no_replace',rival)
    assert invoke(arguments)==6
    assert (tmp_path/'report/rival').read_text()=='preserve'
    assert 'ROUTE_REPORT_FAILED' in capsys.readouterr().err


def test_corruption_before_publish_is_rejected(arguments,tmp_path,monkeypatch):
    original=cli.verify_report
    def corrupt(root,control):
        (root/'route-diff.csv').write_text('corrupt')
        return original(root,control)
    monkeypatch.setattr(cli,'verify_report',corrupt)
    assert invoke(arguments)==6
    assert not (tmp_path/'report').exists()


def test_sigint_maps_to_130_and_restores_handler(arguments,monkeypatch,capsys):
    previous=signal.getsignal(signal.SIGINT)
    def interrupted(args,control):
        signal.raise_signal(signal.SIGINT)
        control.checkpoint('parse',0,1)
    monkeypatch.setattr(cli,'execute',interrupted)
    assert invoke(arguments)==130
    assert signal.getsignal(signal.SIGINT)==previous
    assert 'COLLECTION_CANCELLED' in capsys.readouterr().err


def test_real_entrypoint_help_and_exit(arguments,tmp_path):
    help_result=subprocess.run([sys.executable,str(ROOT/'alred.py'),'route-diff-nxos','--help'],capture_output=True,text=True)
    assert help_result.returncode==0 and '--command-vrf' in help_result.stdout
    arguments.remove('--no-progress')
    result=subprocess.run([sys.executable,str(ROOT/'alred.py'),*arguments],capture_output=True,text=True)
    assert result.returncode==0 and '[publish]' in result.stderr and 'Output:' in result.stdout
    assert ' *via ' not in result.stderr


def test_no_replace_even_when_target_empty(tmp_path):
    source=tmp_path/'source';target=tmp_path/'target';source.mkdir();target.mkdir()
    (source/'data').write_text('source')
    with pytest.raises(FileExistsError):cli.rename_no_replace(source,target)
    assert (source/'data').exists() and list(target.iterdir())==[]


@pytest.mark.parametrize('corruption',['json','shape','symlink'])
def test_invalid_manifest_or_symlink_cannot_be_published(arguments,tmp_path,monkeypatch,corruption):
    original=cli.verify_report
    def corrupt(root,control):
        if corruption=='json':(root/'report-manifest.json').write_text('{')
        elif corruption=='shape':(root/'report-manifest.json').write_text('[]')
        else:(root/'outside').symlink_to(tmp_path,target_is_directory=True)
        return original(root,control)
    monkeypatch.setattr(cli,'verify_report',corrupt)
    assert invoke(arguments)==6
    assert not (tmp_path/'report').exists()
