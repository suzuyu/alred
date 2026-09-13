"""Loss-aware UTF-8 terminal normalization, preserving original bytes and line ranges."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata

from .domain import RouteInputError
from .control import ProcessingControl

TERMINAL_ADAPTER_VERSION = "1.0"
SGR = re.compile(rb"\x1b\[[0-9;]*m")


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SourceLine:
    number: int
    start_byte: int
    end_byte: int
    text: str

    def evidence(self, source_id: str) -> dict:
        return dict(source_id=source_id, start_line=self.number, end_line=self.number,
                    start_byte=self.start_byte, end_byte=self.end_byte)


@dataclass(frozen=True)
class TerminalText:
    raw: bytes
    text: str
    lines: tuple[SourceLine, ...]
    operations: tuple[dict, ...]
    diagnostics: tuple[dict, ...]

    def manifest(self) -> dict:
        return dict(version=TERMINAL_ADAPTER_VERSION, raw_sha256=sha256(self.raw),
                    normalized_sha256=sha256(self.text.encode("utf-8")),
                    mapping=[dict(normalized_line=line.number, raw_start_line=line.number,
                                  raw_end_line=line.number, raw_start_byte=line.start_byte,
                                  raw_end_byte=line.end_byte) for line in self.lines],
                    operations=list(self.operations), diagnostics=list(self.diagnostics))


def normalize_terminal(raw: bytes, *, control: ProcessingControl | None = None) -> TerminalText:
    control = control or ProcessingControl()
    control.checkpoint("normalize", 0, None)
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RouteInputError("/source", f"invalid UTF-8 at byte {exc.start}") from exc
    lines, operations, diagnostics = [], [], []
    normalized = bytearray()
    offset = 0
    pieces = raw.split(b"\n")
    physical = [p + b"\n" for p in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])
    for number, physical_line in enumerate(physical, 1):
        if (number - 1) % 256 == 0:
            control.checkpoint("normalize", number - 1, len(physical))
        body = physical_line[:-1] if physical_line.endswith(b"\n") else physical_line
        ending = b"\n" if physical_line.endswith(b"\n") else b""
        if body.endswith(b"\r") and ending:
            operations.append(dict(kind="CRLF_TO_LF", raw_start_byte=offset + len(body) - 1,
                                   raw_end_byte=offset + len(physical_line)))
            body = body[:-1]
        index, output = 0, bytearray()
        while index < len(body):
            if offset + index == 0 and body.startswith(b"\xef\xbb\xbf"):
                operations.append(dict(kind="UTF8_BOM", raw_start_byte=0, raw_end_byte=3))
                index += 3
                continue
            match = SGR.match(body, index)
            if match:
                operations.append(dict(kind="SGR_REMOVED", raw_start_byte=offset + index,
                                       raw_end_byte=offset + match.end()))
                index = match.end()
                continue
            byte = body[index]
            width = 1 if byte < 128 else 2 if byte < 224 else 3 if byte < 240 else 4
            chunk = body[index:index + width]
            char = chunk.decode("utf-8")
            if (unicodedata.category(char) == "Cc" and char != "\t") or char == "\ufeff":
                diagnostics.append(dict(code="CONTROL_UNSUPPORTED", raw_start_line=number, raw_end_line=number,
                                        raw_start_byte=offset + index, raw_end_byte=offset + index + width))
            output.extend(chunk)
            index += width
        text = output.decode("utf-8")
        if "--More--" in text or "<--- More --->" in text:
            diagnostics.append(dict(code="PAGER_UNSUPPORTED", raw_start_line=number, raw_end_line=number,
                                    raw_start_byte=offset, raw_end_byte=offset + len(physical_line)))
        lines.append(SourceLine(number, offset, offset + len(physical_line), text))
        normalized.extend(output + ending)
        offset += len(physical_line)
    control.checkpoint("normalize", len(physical), len(physical))
    return TerminalText(raw, normalized.decode("utf-8"), tuple(lines), tuple(operations), tuple(diagnostics))
