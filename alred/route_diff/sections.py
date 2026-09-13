"""Command boundaries shared by transcript discovery and Route Diff parsing."""
from dataclasses import dataclass
from datetime import datetime
import re

from .commands import resolve_route_command
from .control import ProcessingControl
from .domain import RouteInputError
from .terminal import TerminalText, normalize_terminal

SECTION_ADAPTER_VERSION = '1.0'
PROMPT = re.compile(r'^(?P<host>[A-Za-z0-9_.-]+)(?:\([^()\r\n]*\))*[>#]\s*(?P<command>.*)$')


@dataclass(frozen=True)
class Section:
    host: str
    command: str
    start: int
    prompt: int
    end: int
    metadata: dict
    completion: tuple[int, int] | None


@dataclass(frozen=True)
class SectionedSource:
    terminal: TerminalText
    container_format: str
    sections: tuple[Section, ...]
    diagnostics: tuple[dict, ...]
    notices: tuple[dict, ...]


def command_key(text):
    resolved = resolve_route_command(text)
    return (resolved['command_id'], resolved['vrf']) if resolved else ' '.join(text.split())


def interval(terminal, source_id, start, end):
    if start > end:
        return None
    return dict(terminal.lines[start-1].evidence(source_id), end_line=end,
                end_byte=terminal.lines[end-1].end_byte)


def prepare_sections(raw, *, control=None, terminal=None):
    control = control or ProcessingControl()
    terminal = terminal or normalize_terminal(raw, control=control)
    lines = terminal.lines
    markers = [i for i, line in enumerate(lines) if line.text.strip().startswith('### COMMAND:')]
    lists = [i for i, line in enumerate(lines) if line.text.strip() == '### COMMAND_LIST']
    collect = bool(markers or lists)
    sections, diagnostics, notices = [], [], []
    if collect:
        first = next((i for i, line in enumerate(lines) if line.text.strip()), None)
        if not markers or first not in (markers[0], lists[0] if lists else -1) or (lists and lists != [first]):
            raise RouteInputError('/sections', 'invalid collector envelope; select an explicit Source Map interval')
        planned = []
        if lists:
            planned = [line.text.strip() for line in lines[first+1:markers[0]] if line.text.strip()]
        elif any(line.text.strip() for line in lines[:markers[0]]):
            raise RouteInputError('/sections', 'unexpected content before collector header')
        for n, start in enumerate(markers):
            control.checkpoint('sections', n, len(markers), unit='commands')
            end = markers[n+1] if n+1 < len(markers) else len(lines)
            metadata, prompt = {}, None
            for i in range(start, end):
                text = lines[i].text.strip()
                match = PROMPT.fullmatch(text)
                if match:
                    prompt = (i, match)
                    break
                if not text:
                    continue
                match = re.fullmatch(r'### ([A-Z_]+):\s*(.*)', text)
                if not match or match[1] in metadata or match[1] not in {
                        'COMMAND', 'COLLECTED_AT', 'STATUS', 'TRANSPORT', 'OUTPUT_FORMAT', 'FALLBACK_FROM', 'ERROR'}:
                    raise RouteInputError('/sections', f'invalid or duplicate collector metadata at line {i+1}')
                metadata[match[1]] = match[2]
            if prompt is None or not all(metadata.get(k) for k in ('COMMAND', 'COLLECTED_AT', 'STATUS', 'TRANSPORT')):
                raise RouteInputError('/sections', f'incomplete collector header at line {start+1}')
            try:
                date = datetime.fromisoformat(metadata['COLLECTED_AT'].replace('Z', '+00:00'))
                if date.utcoffset() is None:
                    raise ValueError()
            except ValueError as error:
                raise RouteInputError('/sections', f'invalid collection timestamp at line {start+1}') from error
            i, match = prompt
            if metadata['STATUS'] not in ('OK', 'ERROR') or command_key(metadata['COMMAND']) != command_key(match['command']):
                raise RouteInputError('/sections', f'collector command/status disagrees at line {start+1}')
            if any(start+1 <= d['raw_start_line'] <= i+1 for d in terminal.diagnostics):
                raise RouteInputError('/sections', f'control characters in collector boundary at line {start+1}')
            sections.append(Section(match['host'], match['command'], start+1, i+1, end, metadata, None))
        sections = [Section(s.host, s.command, s.start, s.prompt, s.end, s.metadata,
                    (sections[i+1].start, sections[i+1].prompt) if i+1 < len(sections) else None)
                    for i, s in enumerate(sections)]
        if lists:
            executed = [command_key(s.command) for s in sections]
            planned_keys = [command_key(c) for c in planned]
            # A truncated collection can be an executed prefix of its plan.
            if executed != planned_keys[:len(executed)]:
                raise RouteInputError('/sections', 'COMMAND_LIST disagrees with executed command order')
            for command in planned[len(executed):]:
                selected = resolve_route_command(command)
                item = dict(code='COMMAND_NOT_COLLECTED', command=command)
                (diagnostics if selected else notices).append(dict(item, **(selected or {})))
    else:
        active = None
        for i, line in enumerate(lines):
            if i % 1024 == 0:
                control.checkpoint('sections', i, len(lines), unit='lines')
            match = PROMPT.fullmatch(line.text.strip())
            if match:
                if active:
                    sections.append(Section(*active, i, {}, (i+1, i+1)))
                active = (match['host'], match['command'], i+1, i+1) if match['command'].strip() else None
            elif active is None and line.text.strip():
                diagnostics.append(dict(code='UNRESOLVED_SEGMENT', line=i+1,
                                        message='content outside an explicit command section'))
        if active:
            sections.append(Section(*active, len(lines), {}, None))
    control.checkpoint('sections', len(sections), len(sections), unit='commands')
    return SectionedSource(terminal, 'alred-collect' if collect else 'plain-transcript',
                           tuple(sections), tuple(diagnostics), tuple(notices))


def discovered_hosts(prepared, *, start=None, end=None):
    if prepared.container_format == 'plain-transcript':
        return {match['host'] for line in prepared.terminal.lines
                if (start is None or line.number >= start) and (end is None or line.number <= end)
                and (match := PROMPT.fullmatch(line.text.strip()))}
    return {s.host for s in prepared.sections if (start is None or s.start >= start) and (end is None or s.prompt <= end)}


def acquisition_evidence(prepared, section, source_id):
    t = prepared.terminal
    collect = prepared.container_format == 'alred-collect'
    return dict(header=interval(t, source_id, section.start, section.prompt-1) if collect else None,
                prompt=interval(t, source_id, section.prompt, section.prompt),
                body=interval(t, source_id, section.prompt+1, section.end),
                block=interval(t, source_id, section.start, section.end),
                declared_status=section.metadata.get('STATUS'), collected_at=section.metadata.get('COLLECTED_AT'),
                transport=section.metadata.get('TRANSPORT'),
                completion_kind=('next_collect_header' if collect else 'next_prompt') if section.completion else 'eof_unverified',
                completion_evidence=interval(t, source_id, *section.completion) if section.completion else None,
                manifest_record_sha256=None)
