"""Conservative NX-OS route source parser with per-scope quality and raw evidence."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re

from .commands import resolve_route_command
from .domain import (RouteInputError, canonical_interface,
                     canonical_path, canonical_prefix, command_scope, path_key)
from .terminal import SourceLine, TerminalText, normalize_terminal
from .sections import (PROMPT, SECTION_ADAPTER_VERSION, acquisition_evidence, interval, prepare_sections)
from .control import ProcessingControl

ROUTE_PARSER_VERSION = "1.2"
NORMALIZER_VERSION = "1.1"
HEADING = re.compile(r'^(IP Route|IPv6 Routing) Table for VRF ["\']([^"\']+)["\']\s*$')
PREFIX = re.compile(r"^(\S+/\d+),\s*ubest/mbest:\s*(\d+)/(\d+)(.*)$")
VIA = re.compile(r"^(\*\*|\*)?via\s+(.+?),\s*\[(\d+)/(\d+)\],\s*(.+)$")
AGE = re.compile(r"(?:\d+:\d{2}:\d{2}|(?:\d+[ywdhms])+)")
PROTOCOL = re.compile(r"(ospfv3|ospf|bgp)(?:-(\S+))?$")
LEGENDS = {
    "'*' denotes best ucast next-hop", "'**' denotes best mcast next-hop",
    "'[x/y]' denotes [preference/metric]", "'%<string>' in via output denotes VRF <string>",
}


@dataclass(frozen=True)
class ParsedRouteSource:
    terminal: TerminalText
    document: dict


def _unsigned(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise RouteInputError("/number", "integer cannot be decoded") from exc


def _parse_path(text: str, vrf: str) -> tuple[dict, bool]:
    match = VIA.fullmatch(text)
    if not match:
        raise RouteInputError("/path", "unsupported or incomplete via line")
    flag, nexthop, ad, metric, tail = match.groups()
    fields = [v.strip() for v in tail.split(",")]
    if fields and AGE.fullmatch(fields[0]):
        age = fields.pop(0)
    else:
        age = None
    if not fields:
        raise RouteInputError("/protocol", "missing route protocol")
    raw_protocol = fields.pop(0)
    protocol_match = PROTOCOL.fullmatch(raw_protocol)
    if raw_protocol in ("direct", "local", "static", "hmm"):
        protocol, instance = raw_protocol, None
    elif protocol_match:
        protocol, instance = protocol_match.groups()
    else:
        raise RouteInputError("/protocol", "unsupported protocol")
    route_type, tag = None, None
    forwarding = {}
    for field in fields:
        if field in ("intra", "inter", "internal", "external", "type-1", "type-2") and route_type is None:
            route_type = field
        elif re.fullmatch(r"tag \d+", field) and tag is None:
            tag = _unsigned(field[4:])
        elif field.startswith(('segid:', 'segid ')) and protocol == 'bgp' and not forwarding:
            suffix = re.fullmatch(r'segid:?\s+(\d+)(?:\s+(\(Asymmetric\)))?(?:\s+tunnelid:\s+(0[xX][0-9a-fA-F]{1,8}))?\s+encap:\s+VXLAN', field)
            if not suffix:
                raise RouteInputError('/path', 'unsupported VXLAN suffix')
            forwarding = dict(encapsulation='vxlan', segment_id=_unsigned(suffix[1]),
                              asymmetric=True if suffix[2] else None, tunnel_id=suffix[3])
        else:
            raise RouteInputError("/path", "unsupported path attribute")
    components = [v.strip() for v in nexthop.split(",")]
    if not 1 <= len(components) <= 2 or not all(components):
        raise RouteInputError("/next_hop", "unsupported next-hop fields")
    hop = components[0]
    interface = canonical_interface(components[1]) if len(components) == 2 else None
    referenced_vrf, table_family = vrf, None
    if "%" in hop:
        reference = re.fullmatch(r"([^%]+)%([A-Za-z0-9_.-]+)(?::(IPv4|IPv6))?", hop)
        if not reference:
            raise RouteInputError("/next_hop_vrf", "unsupported VRF/table reference")
        hop, referenced_vrf, table = reference.groups()
        table_family = table.lower() if table else None
    try:
        address = ipaddress.ip_address(hop)
    except ValueError:
        address = None
        if interface is not None:
            raise RouteInputError("/next_hop", "interface-only hop has an extra interface")
        interface = canonical_interface(hop)
    kind = "discard" if interface == "Null0" else "connected" if protocol == "direct" else "local" if protocol == "local" else "ip"
    value = canonical_path(dict(kind=kind, address=str(address) if address is not None else None,
        next_hop_family=f"ipv{address.version}" if address is not None else None,
        interface=interface, next_hop_vrf=referenced_vrf, next_hop_table_family=table_family,
        admin_distance=_unsigned(ad), metric=_unsigned(metric), protocol=protocol, protocol_instance=instance,
        route_type=route_type, tag=tag, raw_protocol=raw_protocol, age=age, **forwarding))
    return value, flag == "*"


def _parse_section(lines: list[SourceLine], *, source_id: str, device: str,
                   acquisition: dict, verification: str, control: ProcessingControl) -> tuple[list[dict], list[dict]]:
    scopes, diagnostics, seen = [], [], {}
    prefix_sets = {}
    scope, pending = None, None
    command_id = acquisition["command_id"]
    expected_family = acquisition["family"]

    def diagnostic(code, line, message, *, route_issue=False):
        value = dict(code=code, message=message, **line.evidence(source_id))
        (scope["diagnostics"] if scope is not None else diagnostics).append(value)
        if route_issue and pending is not None:
            pending["parse_status"] = "UNKNOWN"

    def finish_route():
        if pending is None:
            return
        if pending["ubest"] != len(pending["paths"]) or not pending["paths"]:
            pending["parse_status"] = "UNKNOWN"
            scope["diagnostics"].append(dict(code="PATH_COUNT_MISMATCH", message="selected unicast path count does not match ubest",
                                             **pending["evidence"]))

    for index, line in enumerate(lines):
        if index % 256 == 0:
            control.checkpoint("parse", index, len(lines), source_id=source_id, device=device, command_id=command_id)
        text = line.text.strip()
        if not text:
            continue
        heading = HEADING.fullmatch(text)
        if heading:
            finish_route()
            pending = None
            family = "ipv4" if heading[1] == "IP Route" else "ipv6"
            vrf = heading[2]
            key = (vrf, family)
            if key in seen:
                scope = seen[key]
                diagnostic("DUPLICATE_VRF_SECTION", line, "VRF heading occurs more than once")
            else:
                scope = dict(device=device, vrf=vrf, family=family, verification=verification,
                    command_scope=acquisition,
                    routes=[], diagnostics=[], observed_prefix_count=0, explicit_empty=False,
                    empty_basis=None, empty_evidence=None, _legends=[],
                    evidence=dict(**line.evidence(source_id), command_id=command_id))
                seen[key] = scope
                prefix_sets[key] = set()
                scopes.append(scope)
            if family != expected_family:
                diagnostic("AF_COMMAND_MISMATCH", line, "VRF heading disagrees with command family")
            if acquisition["vrf"] is not None and vrf != acquisition["vrf"]:
                diagnostic("VRF_COMMAND_MISMATCH", line, "VRF heading disagrees with command VRF")
            continue
        if scope is not None:
            scope['evidence']['end_line'] = line.number
            scope['evidence']['end_byte'] = line.end_byte
        if text in LEGENDS:
            if scope is not None:
                scope['_legends'].append(dict(text=text, evidence=line.evidence(source_id)))
            continue
        if scope is None:
            diagnostic("UNRESOLVED_LINE", line, "no VRF heading for this line")
            continue
        scope["evidence"]["end_line"] = line.number
        scope["evidence"]["end_byte"] = line.end_byte
        if text.lower() == "no routes":
            finish_route()
            pending = None
            scope["explicit_empty"] = True
            scope['empty_basis'] = 'explicit_marker'
            scope['empty_evidence'] = dict(marker=line.evidence(source_id))
            continue
        prefix_match = PREFIX.fullmatch(text)
        if prefix_match:
            finish_route()
            pending = None
            scope["observed_prefix_count"] += 1
            try:
                prefix = canonical_prefix(prefix_match[1], scope["family"])
                ubest, mbest = _unsigned(prefix_match[2]), _unsigned(prefix_match[3])
            except RouteInputError:
                diagnostic("INVALID_PREFIX", line, "invalid canonical route prefix")
                continue
            suffix = prefix_match[4].strip()
            if suffix and suffix != ", attached":
                diagnostic("UNSUPPORTED_PREFIX_ATTRIBUTE", line, "unknown prefix heading attributes")
            prefixes = prefix_sets[(scope["vrf"], scope["family"])]
            if prefix in prefixes:
                diagnostic("DUPLICATE_PREFIX", line, "duplicate prefix in the same VRF")
            prefixes.add(prefix)
            pending = dict(prefix=prefix, ubest=ubest, mbest=mbest,
                paths=[], non_selected_paths=[], parse_status="COMPLETE", evidence=dict(**line.evidence(source_id), command_id=command_id))
            scope["routes"].append(pending)
            continue
        if "via" in text[:8] and pending is not None:
            pending["evidence"]["end_line"] = line.number
            pending["evidence"]["end_byte"] = line.end_byte
            try:
                path, selected = _parse_path(text, scope["vrf"])
            except RouteInputError:
                diagnostic("UNSUPPORTED_PATH", line, "incomplete or unsupported path syntax", route_issue=True)
                continue
            path["evidence"] = dict(**line.evidence(source_id), command_id=command_id)
            if selected:
                if any(path_key(p) == path_key(path) for p in pending["paths"]):
                    diagnostic("DUPLICATE_PATH", line, "duplicate selected path", route_issue=True)
                pending["paths"].append(path)
            else:
                pending["non_selected_paths"].append(path)
            continue
        diagnostic("UNRESOLVED_LINE", line, "unknown route output line", route_issue=True)
    finish_route()
    control.checkpoint("parse", len(lines), len(lines), source_id=source_id, device=device, command_id=command_id)
    for scope_index, scope in enumerate(scopes):
        legends = scope.pop('_legends')
        required = LEGENDS if scope['family'] == 'ipv4' else {v for v in LEGENDS if not v.startswith("'%")}
        proof = acquisition.get('acquisition_evidence', {})
        if (not scope['routes'] and not scope['explicit_empty'] and not scope['diagnostics']
                and verification == 'verified' and required <= {v['text'] for v in legends}
                and proof.get('completion_kind') in ('next_prompt', 'next_collect_header')):
            scope['empty_basis'] = 'closed_section'
            scope['empty_evidence'] = dict(heading=dict(scope['evidence'], end_line=scope['evidence']['start_line'],
                end_byte=next(line.end_byte for line in lines if line.number == scope['evidence']['start_line'])),
                legends=legends, command_end=proof['completion_evidence'],
                vrf_end=scopes[scope_index+1]['evidence'] if scope_index+1 < len(scopes) else proof['completion_evidence'])
        if scope["explicit_empty"] and scope["routes"]:
            scope["diagnostics"].append(dict(code="EMPTY_TABLE_CONFLICT", message="empty marker and routes both present", **scope["evidence"]))
        if not scope["routes"] and scope["empty_basis"] is None:
            scope["diagnostics"].append(dict(code="EMPTY_UNCONFIRMED", message="heading alone does not prove an empty table", **scope["evidence"]))
    return scopes, diagnostics


def parse_route_source(raw: bytes, *, source_id: str, device: str, input_format: str = "nxos-transcript",
                       command_id: str | None = None, vrf: str | None = None, completeness: str | None = None,
                       start_line: int | None = None, end_line: int | None = None,
                       control: ProcessingControl | None = None, prepared=None) -> ParsedRouteSource:
    """Parse one explicit host source without device access or file mutation.

    The caller owns immutable raw storage. This result retains raw bytes in terminal.raw.
    Unsupported content produces UNKNOWN diagnostics, not an empty route table.
    """
    if not source_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", device):
        raise RouteInputError("/source", "source id and an explicit device identity are required")
    if input_format not in ("nxos-transcript", "nxos-route-text"):
        raise RouteInputError("/input_format", "unsupported route input format")
    selection = command_scope(command_id, vrf) if command_id is not None else None
    if command_id is None and vrf is not None:
        raise RouteInputError("/vrf", "vrf requires a specific VRF command id")
    if completeness not in (None, "asserted"):
        raise RouteInputError("/completeness", "only an explicit asserted value is allowed")
    if (start_line is None) != (end_line is None):
        raise RouteInputError("/range", "start_line and end_line must be specified together")
    control = control or ProcessingControl()
    if prepared is not None and prepared.terminal.raw != raw:
        raise RouteInputError('/source', 'prepared source bytes disagree')
    if input_format == 'nxos-transcript':
        prepared = prepared or prepare_sections(raw, control=control)
        terminal = prepared.terminal
    else:
        terminal = prepared.terminal if prepared else normalize_terminal(raw, control=control)
    start, end = (1, len(terminal.lines)) if start_line is None else (start_line, end_line)
    if start_line is not None and (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(terminal.lines)):
        raise RouteInputError('/range', 'source line range is invalid')
    lines = list(terminal.lines[start-1:end])
    diagnostics, notices, sections, section_issues = [], [], [], []
    container_format = 'route-text'
    if input_format == 'nxos-route-text':
        if command_id is None:
            raise RouteInputError('/command_id', 'body-only source requires command id')
        acquisition = dict(selection, command=None, evidence=None, acquisition_evidence=dict(
            header=None, prompt=None, body=interval(terminal, source_id, start, end),
            block=interval(terminal, source_id, start, end), declared_status=None, collected_at=None, transport=None,
            completion_kind='eof_unverified', completion_evidence=None, manifest_record_sha256=None))
        sections.append((acquisition, lines, 'user_asserted' if completeness == 'asserted' else 'unknown'))
        section_issues.append([])
        diagnostics.extend(dict(d, source_id=source_id) for d in terminal.diagnostics if start <= d['raw_start_line'] <= end)
    else:
        if completeness is not None:
            raise RouteInputError('/completeness', 'asserted completeness is for body-only input')
        container_format = prepared.container_format
        notices.extend(prepared.notices)
        for issue in prepared.diagnostics:
            if 'line' in issue and not start <= issue['line'] <= end:
                continue
            if selection is not None and 'command_id' in issue and any(issue.get(k) != selection[k] for k in selection):
                notices.append(issue)
            else:
                diagnostics.append(dict(issue, source_id=source_id))
        seen_commands = set()
        for section in prepared.sections:
            if section.prompt < start or section.start > end:
                continue
            if section.start < start:
                raise RouteInputError('/range', 'range starts inside a command block')
            if section.host != device:
                raise RouteInputError('/device', 'prompt identity disagrees with selected device')
            selected = resolve_route_command(section.command)
            adopted = selected is not None and (selection is None or all(selected[k] == selection[k] for k in selection))
            issues = [dict(d, source_id=source_id) for d in terminal.diagnostics
                      if section.start <= d['raw_start_line'] <= min(section.end, end)]
            if not adopted:
                notices.append(dict(code='COMMAND_NOT_SELECTED', command=section.command,
                    evidence=interval(terminal, source_id, section.start, min(section.end, end)),
                    diagnostics=issues, status=section.metadata.get('STATUS')))
                continue
            key = (selected['command_id'], selected['vrf'])
            if key in seen_commands:
                raise RouteInputError('/source', 'duplicate route command; select an explicit interval in a Source Map')
            seen_commands.add(key)
            proof = acquisition_evidence(prepared, section, source_id)
            if container_format == 'plain-transcript' and section.completion:
                boundary = PROMPT.fullmatch(terminal.lines[section.completion[1]-1].text.strip())
                if boundary is None or boundary['host'] != device:
                    raise RouteInputError('/device', 'terminating prompt identity disagrees with selected device')
            if end < section.end:
                proof.update(body=interval(terminal, source_id, section.prompt+1, end),
                             block=interval(terminal, source_id, section.start, end),
                             completion_kind='eof_unverified', completion_evidence=None)
            if container_format == 'alred-collect' and (section.metadata.get('STATUS') != 'OK'
                    or section.metadata.get('ERROR') or section.metadata.get('OUTPUT_FORMAT', 'text') != 'text'):
                issues.append(dict(code='COLLECTION_FAILED', message='collector status/error/output format is not successful text',
                                   **terminal.lines[section.start-1].evidence(source_id)))
            acquisition = dict(selected, evidence=terminal.lines[section.prompt-1].evidence(source_id), acquisition_evidence=proof)
            verified = proof['completion_kind'] != 'eof_unverified' and not issues
            sections.append((acquisition, list(terminal.lines[section.prompt:min(section.end, end)]),
                             'verified' if verified else 'unknown'))
            section_issues.append(issues)
    scopes, scope_keys = [], set()
    for (acquisition, body, verification), command_issues in zip(sections, section_issues):
        parsed, issues = _parse_section(body, source_id=source_id, device=device, acquisition=acquisition, verification=verification, control=control)
        for scope in parsed:
            scope["diagnostics"].extend(command_issues)
            scope["diagnostics"].extend(issues)
            key = (scope["vrf"], scope["family"])
            if key in scope_keys:
                raise RouteInputError("/source", "overlapping route commands; select an explicit interval")
            scope_keys.add(key)
        scopes.extend(parsed)
        if not parsed:
            diagnostics.extend(dict(issue, command_id=acquisition['command_id'], family=acquisition['family'], vrf=acquisition['vrf'])
                               for issue in issues + command_issues)
        if not parsed:
            diagnostics.append(dict(code="VRF_HEADING_MISSING", command_id=acquisition["command_id"],
                                    family=acquisition['family'], vrf=acquisition['vrf'], source_id=source_id))
    if not sections:
        diagnostics.append(dict(code="ROUTE_COMMAND_MISSING", source_id=source_id))
    for scope in scopes:
        syntax_complete = not any('command_id' not in d for d in diagnostics) and not scope["diagnostics"]
        scope["parse_status"] = "COMPLETE" if syntax_complete else "UNKNOWN"
        scope["coverage"] = "COMPLETE" if syntax_complete and scope["verification"] != "unknown" else "UNKNOWN"
        scope["verification_reason"] = "SOURCE_TERMINATOR_OR_ASSERTION_MISSING" if scope["verification"] == "unknown" else None
        scope["health_eligible"] = scope["coverage"] == "COMPLETE" and scope["verification"] == "verified"
        scope["parsed_prefix_count"] = sum(r["parse_status"] == "COMPLETE" for r in scope["routes"])
        scope["parsed_path_count"] = sum(len(r["paths"]) for r in scope["routes"])
    return ParsedRouteSource(terminal, dict(schema_version=1, kind="RouteSourceParse", source_id=source_id, device=device,
        input_format=input_format, versions=dict(terminal_adapter="1.0", parser=ROUTE_PARSER_VERSION, normalizer=NORMALIZER_VERSION, section_adapter=SECTION_ADAPTER_VERSION),
        selected_range=dict(start_line=start, end_line=end) if lines else None,
        container_format=container_format, notices=notices, terminal=terminal.manifest(), commands=[a for a, _, _ in sections], scopes=scopes, diagnostics=diagnostics))
