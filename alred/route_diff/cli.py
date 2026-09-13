"""Standalone route comparison: explicit inputs, immutable evidence, atomic publish."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import sys
import tempfile
import time

import yaml

from ..schema import DocumentValidationError, UnsupportedSchemaError, canonical_sha256
from .comparator import compare_snapshots
from .control import ProcessingControl, RouteProcessingCancelled
from .domain import COMMAND_FAMILIES, RouteInputError, command_scope, validate_policy, validate_source_map
from .parser import parse_route_source
from .sections import prepare_sections, discovered_hosts
from .discovery import directory_mapping
from .report import write_route_report
from .snapshot import build_snapshot, identity


class RouteCLIError(Exception):
    def __init__(self, code, message, exit_code):
        self.code, self.exit_code = code, exit_code
        super().__init__(message)


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise RouteInputError('/yaml', 'mapping keys must be unique strings')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def read_bytes(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RouteInputError('/input', 'input must be a regular file')
            before = os.fstat(stream.fileno())
            raw = stream.read()
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != after.st_size:
                raise RouteInputError('/input', f'input changed while reading: {path}')
            return raw
    except OSError as error:
        raise RouteCLIError('INPUT_NOT_FOUND', f'{path}: {error.strerror}', 2) from error


def load_yaml(raw):
    try:
        document = yaml.load(raw.decode('utf-8-sig'), Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError) as error:
        raise RouteInputError('/yaml', 'invalid UTF-8 YAML input') from error
    # Reject cyclic aliases before schema traversal. Shared acyclic aliases are allowed.
    def visit(value, active):
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise RouteInputError('/yaml', 'cyclic aliases are not supported')
            active.add(id(value))
            for child in (value.values() if isinstance(value, dict) else value):
                visit(child, active)
            active.remove(id(value))
    visit(document, set())
    return document


def add_parser(subparsers):
    parser = subparsers.add_parser('route-diff-nxos', help='Compare saved NX-OS IPv4/IPv6 route logs offline',
                                  description='Compare saved route logs, directories or a source map; no device connection.', allow_abbrev=False)
    parser.add_argument('--before', help='Before log file or directory (requires --after and --input-format)')
    parser.add_argument('--after', help='After log file or directory')
    parser.add_argument('--input-format', choices=('nxos-transcript', 'nxos-route-text'), help='Explicit file/directory input format')
    parser.add_argument('--recursive', action='store_true', help='Include child directories (directory input only; default off)')
    parser.add_argument('--host', help='Device identity; required for body-only input')
    parser.add_argument('--source-map', help='Source Map YAML; paths are relative to this file')
    parser.add_argument('--command-id', choices=sorted(COMMAND_FAMILIES), help='Acquisition command; required for body-only input')
    parser.add_argument('--command-vrf', help='Acquisition VRF for a specific-VRF command ID')
    parser.add_argument('--completeness', choices=('asserted',), help='Assert body completeness (not sufficient for Health PASS)')
    parser.add_argument('--af', choices=('ipv4', 'ipv6', 'both'), default='both', help='Compared AF (default: both, observed union)')
    parser.add_argument('--vrf', action='append', help='Exact compared VRF; repeat to select multiple VRFs')
    parser.add_argument('--policy', help='Optional RouteDiffPolicy YAML; omitted means observation only')
    parser.add_argument('--review', help='Optional matching RouteDiffReview JSON to restore')
    parser.add_argument('--before-label', default='before', help='Before display label')
    parser.add_argument('--after-label', default='after', help='After display label')
    parser.add_argument('--output-dir', default='./route_diff', help='Final report directory (default: ./route_diff); never overwrite a nonempty directory')
    parser.add_argument('--no-progress', action='store_true', help='Suppress progress on stderr')
    parser.set_defaults(func=run)
    return parser


def resolve_inputs(args, control):
    control.checkpoint('resolve', 0, None, unit='sources')
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', v) for v in args.vrf or []):
        raise RouteInputError('/vrf', 'VRF filters must be nonempty exact NX-OS names')
    captured, cache, physical, prepared_cache = {}, {}, {}, {}

    def capture(path):
        path = Path(path).resolve()
        if path not in cache:
            try:
                info = path.stat()
            except OSError as error:
                raise RouteCLIError('INPUT_NOT_FOUND', f'{path}: {error.strerror}', 2) from error
            key = info.st_dev, info.st_ino
            if key not in physical:
                physical[key] = read_bytes(path)
            cache[path] = physical[key]
        return cache[path]

    def prepare(path):
        path = Path(path).resolve()
        raw = capture(path)
        key = id(raw)
        if key not in prepared_cache:
            prepared_cache[key] = prepare_sections(raw, control=control)
        return prepared_cache[key]

    directory_input = False
    if args.before and args.after:
        a, b = Path(args.before).is_dir(), Path(args.after).is_dir()
        if a != b:
            raise RouteInputError('/arguments', 'before/after must both be files or both be directories')
        directory_input = a and b
    if getattr(args, 'recursive', False) and (args.source_map or not directory_input):
        raise RouteInputError('/arguments', '--recursive requires directory input')

    if args.source_map:
        if any(getattr(args, key) is not None for key in ('before', 'after', 'input_format', 'host', 'command_id', 'command_vrf', 'completeness')):
            raise RouteInputError('/arguments', '--source-map cannot be combined with two-file input options')
        path = Path(args.source_map).resolve()
        captured['source-map.yaml'] = capture(path)
        mapping = validate_source_map(load_yaml(captured['source-map.yaml']), base_dir=path.parent)
        base = path.parent
    elif directory_input:
        mapping, discovery = directory_mapping(args, capture, prepare, control)
        captured['directory-discovery.json'] = (json.dumps(discovery, ensure_ascii=False, indent=2) + '\n').encode()
        base = Path.cwd()
        validate_source_map(mapping, base_dir=base)
    else:
        if not args.before or not args.after or not args.input_format:
            raise RouteInputError('/arguments', 'supply --before, --after and --input-format, or --source-map')
        if args.input_format == 'nxos-route-text' and (not args.host or not args.command_id):
            raise RouteInputError('/arguments', 'body-only input requires --host and --command-id')
        if args.command_id:
            command_scope(args.command_id, args.command_vrf)
        elif args.command_vrf:
            raise RouteInputError('/arguments', '--command-vrf requires --command-id')
        if args.completeness and args.input_format != 'nxos-route-text':
            raise RouteInputError('/arguments', '--completeness is only valid for body-only input')
        host = args.host
        if args.input_format == 'nxos-transcript':
            detected = set()
            for filename in (args.before, args.after):
                per_source = discovered_hosts(prepare(filename))
                if host is None and len(per_source) != 1:
                    raise RouteInputError('/host', 'cannot resolve one host from each transcript; specify --host or a source map')
                detected.update(per_source)
            if host is None:
                if len(detected) != 1:
                    raise RouteInputError('/host', 'before and after must belong to the same host')
                host = next(iter(detected))
            elif detected - {host}:
                raise RouteInputError('/host', 'prompt identity disagrees with --host')
        spec = dict(input_format=args.input_format)
        for option, field in (('command_id', 'command_id'), ('command_vrf', 'vrf'), ('completeness', 'completeness')):
            if getattr(args, option) is not None:
                spec[field] = getattr(args, option)
        mapping = dict(api_version='alred/v1', kind='RouteDiffSourceMap', metadata=dict(name='two-file-input'),
                       spec=dict(hosts=[dict(host=host, before=[dict(spec, path=str(Path(args.before).resolve()))],
                                            after=[dict(spec, path=str(Path(args.after).resolve()))])]))
        base = Path.cwd()
        validate_source_map(mapping, base_dir=base)
    requests, assigned = [], {}
    for host in mapping['spec']['hosts']:
        for side in ('before', 'after'):
            for source in host[side]:
                path = (base / source['path']).resolve()
                raw = capture(path)
                try:
                    st = path.stat()
                except OSError as error:
                    raise RouteCLIError('INPUT_NOT_FOUND', f'{path}: {error.strerror}', 2) from error
                key = (side, st.st_dev, st.st_ino)
                start, end = source.get('start_line', 1), source.get('end_line', float('inf'))
                if any(start <= b and a <= end for a, b in assigned.get(key, [])):
                    raise RouteInputError('/sources', 'overlapping intervals refer to the same physical file')
                assigned.setdefault(key, []).append((start, end))
                source_id = 'source-' + canonical_sha256(dict(host=host['host'], path=str(path), spec=source))[7:27]
                requests.append(dict(side=side, device=host['host'], source_id=source_id, path=str(path),
                                     options={k: v for k, v in source.items() if k != 'path'}, raw=raw,
                                     _prepared=prepare(path) if source['input_format'] == 'nxos-transcript' else None))
    policy = None
    if args.policy:
        captured['policy.yaml'] = capture(args.policy)
        policy = validate_policy(load_yaml(captured['policy.yaml']))
    review = None
    if args.review:
        captured['review-input.json'] = capture(args.review)
        try:
            def unique(pairs):
                out = {}
                for k, v in pairs:
                    if k in out:
                        raise RouteInputError('/review', 'duplicate JSON key')
                    out[k] = v
                return out
            review = json.loads(captured['review-input.json'].decode('utf-8-sig'), object_pairs_hook=unique)
        except (ValueError, UnicodeError) as error:
            raise RouteInputError('/review', 'invalid UTF-8 JSON review') from error
    return requests, policy, review, captured


def select_scopes(snapshots, af, vrfs):
    if af == 'both' and not vrfs:
        return None
    hosts, discovered = set(), set()
    for snapshot in snapshots:
        discovered.update(identity(s, scope=True) for s in snapshot['scopes'])
        for source in snapshot['sources']:
            hosts.add(source['device'])
            for cmd in source['commands']:
                if cmd['vrf'] is not None:
                    discovered.add((source['device'], cmd['vrf'], cmd['family']))
    selected = set()
    for host in hosts:
        local = {s for s in discovered if s[0] == host}
        selected_vrfs = set(vrfs or {s[1] for s in local} or {'default'})
        for vrf in selected_vrfs:
            families = {af} if af != 'both' else ({s[2] for s in local if s[1] == vrf} or {s[2] for s in local} or {'ipv4', 'ipv6'})
            selected.update((host, vrf, family) for family in families)
    return selected


def rename_no_replace(source, target):
    """Atomic publication without replacing even an empty directory created by a rival."""
    if os.name == 'nt':
        os.rename(source, target)
        return
    if sys.platform != 'linux':
        raise OSError(errno.ENOTSUP, 'atomic no-replace directory publication is unsupported on this OS')
    libc = ctypes.CDLL(None, use_errno=True)
    args = (ctypes.c_int(-100), ctypes.c_char_p(os.fsencode(source)), ctypes.c_int(-100), ctypes.c_char_p(os.fsencode(target)), ctypes.c_uint(1))
    if hasattr(libc, 'renameat2'):
        result = libc.renameat2(*args)
    else:
        number = {'x86_64': 316, 'aarch64': 276}.get(platform.machine())
        if number is None:
            raise OSError(errno.ENOTSUP, 'renameat2 syscall is unavailable on this architecture')
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(ctypes.c_long(number), *args)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def _empty_target(target):
    if not os.path.lexists(target):
        return None
    if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
        raise RouteInputError('/output_dir', 'output is a file, symlink or nonempty directory; use a new directory')
    info = target.stat()
    return info.st_dev, info.st_ino


def _dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify_report(root, control):
    try:
        manifest = json.loads((root / 'report-manifest.json').read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as error:
        raise RouteCLIError('ROUTE_REPORT_FAILED', 'invalid report manifest JSON', 6) from error
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
            or manifest.get('kind') != 'RouteDiffReportManifest' or not isinstance(manifest.get('files'), dict)
            or not isinstance(manifest.get('renderer_version'), str)
            or not isinstance(manifest.get('comparison_fingerprint'), str)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest['comparison_fingerprint'])):
        raise RouteCLIError('ROUTE_REPORT_FAILED', 'invalid report manifest structure', 6)
    members = list(root.rglob('*'))
    if any(p.is_symlink() for p in members):
        raise RouteCLIError('ROUTE_REPORT_FAILED', 'symlink in report artifacts', 6)
    paths = {p.relative_to(root).as_posix() for p in members if p.is_file()}
    if paths != set(manifest['files']) | {'report-manifest.json'}:
        raise RouteCLIError('ROUTE_REPORT_FAILED', 'report file inventory mismatch', 6)
    for i, (name, digest) in enumerate(manifest['files'].items()):
        control.checkpoint('publish', i, len(paths) - 1, unit='files')
        path = root / name
        if path.is_symlink() or Path(name).is_absolute() or '..' in Path(name).parts or 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RouteCLIError('ROUTE_REPORT_FAILED', 'report file hash or path mismatch', 6)
    return manifest


def execute(args, *, control=None):
    control = control or ProcessingControl()
    target = Path(args.output_dir).absolute()
    stage = None
    lock = None
    locked = False
    published = False
    try:
        initial_target = _empty_target(target)
        requests, policy, review, captured = resolve_inputs(args, control)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = target.parent / ('.route-diff-lock-' + hashlib.sha256(target.name.encode()).hexdigest()[:24])
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RouteInputError('/output_dir', f'output is locked: {lock}; confirm the previous process has ended before removing a stale lock') from error
        locked = True
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(f'pid={os.getpid()}\noutput={target}\n')
        stage = Path(tempfile.mkdtemp(prefix='.route-diff-stage-', dir=target.parent))
        evidence = stage / 'evidence'
        evidence.mkdir()
        for name, raw in captured.items():
            (evidence / name).write_bytes(raw)
        for request in requests:
            directory = evidence / 'raw' / request['side']
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (request['source_id'] + '.log')).write_bytes(request['raw'])
        resolved = dict(schema_version=1, kind='RouteDiffInput', af=args.af, vrfs=args.vrf,
                        labels=dict(before=args.before_label, after=args.after_label),
                        sources=[dict({k: v for k, v in r.items() if k not in ('raw', '_prepared')}, sha256='sha256:' + hashlib.sha256(r['raw']).hexdigest(),
                                      stored_path=f"evidence/raw/{r['side']}/{r['source_id']}.log") for r in requests])
        if 'directory-discovery.json' in captured:
            resolved['directory_discovery'] = json.loads(captured['directory-discovery.json'])
        _dump(evidence / 'resolved-input.json', resolved)
        snapshots, raw_sources = [], {}
        for side in ('before', 'after'):
            parsed, paths = [], {}
            for request in [r for r in requests if r['side'] == side]:
                control.checkpoint('parse', len(parsed), None, unit='sources', device=request['device'])
                parsed.append(parse_route_source(request['raw'], source_id=request['source_id'], device=request['device'], control=control, prepared=request['_prepared'], **request['options']))
                paths[request['source_id']] = request['path']
                raw_sources[side, request['source_id']] = request['raw']
            snapshot = build_snapshot(parsed, side=side, source_paths=paths, control=control)
            snapshots.append(snapshot)
            _dump(evidence / f'route-snapshot-{side}.json', snapshot)
        result = compare_snapshots(*snapshots, selected_scopes=select_scopes(snapshots, args.af, args.vrf), policy=policy, control=control)
        report = stage / 'report'
        manifest = write_route_report(*snapshots, result, raw_sources, report, control=control,
                                      labels=resolved['labels'], review=review)
        evidence.rename(report / 'evidence')
        for path in (report / 'evidence').rglob('*'):
            if path.is_file():
                manifest['files'][path.relative_to(report).as_posix()] = 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
        _dump(report / 'report-manifest.json', manifest)
        verify_report(report, control)
        control.checkpoint('publish_ready', 1, 1, unit='reports')
        control.checkpoint('publish', 0, 1, unit='reports')
        if initial_target is not None:
            if _empty_target(target) != initial_target:
                raise RouteInputError('/output_dir', 'output changed during comparison')
            target.rmdir()
        rename_no_replace(report, target)
        published = True
        try:
            stage.rmdir()
        except OSError:
            print(f'Published report; empty staging retained: {stage}', file=sys.stderr)
        print(f"Coverage: {result['summary']['coverage']} / Evaluation: {result['evaluation']}")
        for mode, counts in result['summary']['modes'].items():
            print(mode + ': ' + ' / '.join(f'{k}={counts[k] if counts[k] is not None else "null"}' for k in ('ADDED', 'REMOVED', 'MODIFIED', 'UNCHANGED')))
        print(f"UNKNOWN scopes: {result['summary']['unknown_scope_count']} / sources: {result['summary']['unknown_source_count']}")
        pairing = {}
        for source in result['sources']:
            pairing.setdefault(source['device'], set()).add(source['side'])
        print('Hosts: paired=' + str(sum(len(v) == 2 for v in pairing.values()))
              + ' / before-only=' + str(sum(v == {'before'} for v in pairing.values()))
              + ' / after-only=' + str(sum(v == {'after'} for v in pairing.values())))
        print(f'Output: {target}')
        return result['exit_code']
    except OSError as error:
        raise RouteCLIError('ROUTE_REPORT_FAILED', f'{error.strerror or str(error)}; output was not overwritten', 6) from error
    finally:
        if not published and stage is not None and stage.exists():
            print(f'Partial artifacts: {stage} (not a published report)', file=sys.stderr)
        if locked:
            try:
                lock.unlink()
            except OSError:
                print(f'Lock retained: {lock}; confirm the process has ended before removing it', file=sys.stderr)


def run(args):
    cancelled = False
    def interrupt(signum, frame):
        nonlocal cancelled
        cancelled = True
    last_stage, last_time = None, 0.0
    def progress(event):
        nonlocal last_stage, last_time
        now = time.monotonic()
        if not args.no_progress and (event['stage'] != last_stage or now - last_time >= 0.5):
            print(f"[{event['stage']}] {event['completed']}/{event['total'] if event['total'] is not None else '?'} {event['unit']}", file=sys.stderr)
            last_stage, last_time = event['stage'], now
    previous = signal.signal(signal.SIGINT, interrupt)
    try:
        return execute(args, control=ProcessingControl(progress, lambda: cancelled))
    except RouteProcessingCancelled:
        print('COLLECTION_CANCELLED: route comparison interrupted', file=sys.stderr)
        return 130
    except (RouteInputError, DocumentValidationError) as error:
        print(f'VALIDATION_ERROR: {error}', file=sys.stderr)
        return 2
    except UnsupportedSchemaError as error:
        print(f'SCHEMA_UNSUPPORTED: {error}', file=sys.stderr)
        return 3
    except RouteCLIError as error:
        print(f'{error.code}: {error}', file=sys.stderr)
        return error.exit_code
    finally:
        signal.signal(signal.SIGINT, previous)
