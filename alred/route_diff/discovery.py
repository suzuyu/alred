"""Deterministic, read-only directory discovery for standalone comparison."""
from pathlib import Path
import stat

from .commands import resolve_route_command
from .domain import RouteInputError
from .sections import discovered_hosts


def directory_mapping(args, capture, prepare, control):
    roots = {side: Path(getattr(args, side)).absolute() for side in ('before', 'after')}
    if args.input_format != 'nxos-transcript' or any(getattr(args, k, None) is not None for k in ('host', 'command_id', 'command_vrf', 'completeness')):
        raise RouteInputError('/arguments', 'directory input requires nxos-transcript without per-file host/command options')
    output = Path(args.output_dir).resolve()
    for root in roots.values():
        if root.is_symlink() or output == root.resolve() or root.resolve() in output.parents:
            raise RouteInputError('/arguments', 'input directories must not be symlinks or contain the output directory')
    hosts, inventory = {}, []
    recursive = bool(getattr(args, 'recursive', False))
    for side, root in roots.items():
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name)
            except OSError as error:
                raise RouteInputError('/input', f'cannot list input directory: {directory}') from error
            for path in entries:
                control.checkpoint('discover', len(inventory), None, unit='files')
                item = dict(side=side, path=path.relative_to(root).as_posix())
                inventory.append(item)
                try:
                    info = path.lstat()
                except OSError as error:
                    raise RouteInputError('/input', f'cannot inspect input: {path}') from error
                if path.name.startswith('.'):
                    item.update(status='excluded', reason='hidden')
                elif stat.S_ISLNK(info.st_mode):
                    item.update(status='excluded', reason='symlink')
                elif stat.S_ISDIR(info.st_mode):
                    item.update(status='directory', reason='recursive' if recursive else 'not_recursive')
                    if recursive:
                        pending.append(path)
                elif path.suffix.lower() not in ('.log', '.txt'):
                    item.update(status='excluded', reason='extension')
                elif not stat.S_ISREG(info.st_mode):
                    raise RouteInputError('/input', f'log input must be a regular file: {path}')
                else:
                    raw = capture(path)
                    prepared = prepare(path)
                    identities = discovered_hosts(prepared)
                    if not raw or len(identities) != 1:
                        raise RouteInputError('/host', f'cannot resolve exactly one host in {path}; use a Source Map')
                    host = next(iter(identities))
                    item.update(status='selected', host=host)
                    record = hosts.setdefault(host, dict(host=host, before=[], after=[]))
                    record[side].append(dict(path=str(path.resolve()), input_format='nxos-transcript'))
    if not any(resolve_route_command(s.command) for host in hosts.values() for side in ('before', 'after')
               for source in host[side] for s in prepare(source['path']).sections):
        raise RouteInputError('/input', 'directories contain no supported route commands')
    for host in hosts.values():
        for side in ('before', 'after'):
            host[side].sort(key=lambda s: s['path'])
    discovery = dict(schema_version=1, kind='RouteDiffDirectoryDiscovery', resolver_version='1.0',
        roots={k:str(v) for k,v in roots.items()}, recursive=recursive, extensions=['.log','.txt'],
        inventory=sorted(inventory, key=lambda r:(r['side'],r['path'])),
        hosts=[dict(host=k, before_count=len(v['before']), after_count=len(v['after'])) for k,v in sorted(hosts.items())])
    return dict(api_version='alred/v1', kind='RouteDiffSourceMap', metadata=dict(name='directory-input'),
                spec=dict(hosts=[hosts[k] for k in sorted(hosts)])), discovery
