"""Collection Manifest construction for existing alred collect outputs."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .commands import command_id, normalize_command
from ..schema import API_VERSION, validate_document


COLLECT_ADAPTER_VERSION = "1.1"
_COMMAND_HEADER = re.compile(r"^### COMMAND:\s*(?P<command>.+?)\s*$")
_PROMPT_COMMAND = re.compile(
    r"^(?P<host>[A-Za-z0-9_.-]+)"
    r"(?:\([^\\r\\n]*\))*[#>]\s*(?P<command>.+?)\s*$"
)


class CollectionAdapterError(ValueError):
    """Raised when collect inputs cannot be mapped without guessing."""

    code = "COLLECTION_ERROR"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_input_files(
    inputs: Iterable[str | Path],
    *,
    suffixes: set[str] | None = None,
) -> list[Path]:
    """Resolve regular input files without following symlinks or archives."""
    allowed_suffixes = suffixes or {".log", ".txt"}
    found: dict[tuple[str, str], Path] = {}
    for raw_input in inputs:
        candidate = Path(raw_input)
        if candidate.is_symlink():
            raise CollectionAdapterError(
                f"symbolic link input is not allowed: {candidate}"
            )
        if candidate.is_file():
            candidates = [candidate]
        elif candidate.is_dir():
            candidates = sorted(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and "old" not in path.relative_to(candidate).parts
            )
        else:
            raise CollectionAdapterError(f"input not found: {candidate}")
        for path in candidates:
            if path.suffix.lower() not in allowed_suffixes:
                continue
            resolved = path.resolve()
            digest = _sha256(resolved)
            found[(str(resolved), digest)] = resolved
    if not found:
        raise CollectionAdapterError("no supported regular input files found")
    return [found[key] for key in sorted(found)]


def _parse_collect_sections(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_indexes = [
        index for index, line in enumerate(lines) if _COMMAND_HEADER.match(line)
    ]
    sections: list[dict[str, Any]] = []
    file_digest = _sha256(path)
    for position, header_index in enumerate(header_indexes):
        header_match = _COMMAND_HEADER.match(lines[header_index])
        assert header_match is not None
        next_header = (
            header_indexes[position + 1]
            if position + 1 < len(header_indexes)
            else len(lines)
        )
        metadata: dict[str, str] = {}
        prompt_index: int | None = None
        prompt_match = None
        for index in range(header_index + 1, next_header):
            line = lines[index]
            if line.startswith("### ") and ":" in line:
                key, value = line[4:].split(":", 1)
                metadata[key.strip().lower()] = value.strip()
                continue
            possible_prompt = _PROMPT_COMMAND.match(line)
            if possible_prompt:
                prompt_index = index
                prompt_match = possible_prompt
                break
        declared_command = header_match.group("command").strip()
        status = (
            "success"
            if metadata.get("status", "").upper() == "OK"
            else "failed"
        )
        if prompt_index is None or prompt_match is None:
            host = path.parent.name
            actual_command = declared_command
            status = "failed"
            error = "command prompt not found in collect section"
            output_start = header_index + 2
        else:
            host = prompt_match.group("host")
            actual_command = prompt_match.group("command").strip()
            error = None
            output_start = prompt_index + 2
        normalized_declared = normalize_command(declared_command)
        normalized_actual = normalize_command(actual_command)
        if normalized_declared != normalized_actual:
            status = "failed"
            error = (
                "declared command and prompt command differ: "
                f"{declared_command!r} != {actual_command!r}"
            )
        collected_at = metadata.get("collected_at")
        if not collected_at:
            status = "failed"
            error = error or "COLLECTED_AT is missing"
        sections.append(
            {
                "host": host,
                "command": actual_command,
                "normalized_command": normalized_actual,
                "command_id": command_id(actual_command),
                "status": status,
                "collected_at": collected_at,
                "file": str(path),
                "sha256": file_digest,
                "source": "alred_collect",
                "transport": metadata.get("transport", "unknown"),
                "start_line": header_index + 1,
                "end_line": max(next_header, header_index + 1),
                "output_start_line": output_start,
                "output_end_line": max(next_header, 1),
                "confidence": "high" if status == "success" else "low",
                "error": error,
            }
        )
    return sections


def _running_config_entries(paths: list[Path], collected_at: str) -> list[dict[str, Any]]:
    preferred: dict[str, Path] = {}
    for path in paths:
        match = re.fullmatch(r"(?P<host>.+)_run\.(?:txt|json)", path.name)
        if not match or "config" not in path.parts:
            continue
        host = match.group("host")
        current = preferred.get(host)
        # The Overlay running-config parser consumes CLI text. In auto
        # transport mode the collector intentionally retains both NX-API JSON
        # and SSH text for the same generation; this is not an ambiguous
        # duplicate. Keep JSON as a sidecar and pin text in the Manifest.
        if current is None or (
            path.suffix.lower() == ".txt"
            and current.suffix.lower() != ".txt"
        ):
            preferred[host] = path
    entries: list[dict[str, Any]] = []
    for host, path in sorted(preferred.items()):
        entries.append(
            {
                "host": host,
                "command": "show running-config",
                "normalized_command": "show running-config",
                "command_id": "running_config",
                "status": "success",
                "collected_at": collected_at,
                "file": str(path),
                "sha256": _sha256(path),
                "source": "running_config",
                "transport": "unknown",
                "confidence": "high",
                "error": None,
            }
        )
    return entries


def _lldp_entries(paths: list[Path], collected_at: str) -> list[dict[str, Any]]:
    """Select one dedicated LLDP neighbor artifact per host."""
    preferred: dict[str, Path] = {}
    for path in paths:
        match = re.fullmatch(r"(?P<host>.+)_lldp\.(?:txt|json)", path.name)
        if not match or "lldp" not in path.parts:
            continue
        host = match.group("host")
        current = preferred.get(host)
        if current is None or (
            path.suffix.lower() == ".txt"
            and current.suffix.lower() != ".txt"
        ):
            preferred[host] = path
    entries: list[dict[str, Any]] = []
    for host, path in sorted(preferred.items()):
        entries.append(
            {
                "host": host,
                "command": "show lldp neighbors detail",
                "normalized_command": "show lldp neighbors detail",
                "command_id": "lldp_neighbors_detail",
                "status": "success",
                "collected_at": collected_at,
                "file": str(path),
                "sha256": _sha256(path),
                "source": "lldp",
                "transport": "unknown",
                "confidence": "high",
                "error": None,
            }
        )
    return entries


def build_collection_manifest(
    sections: list[dict[str, Any]],
    *,
    collection_id: str,
    change_id: str,
    phase: str,
    profiles: list[str],
    started_at: datetime,
    completed_at: datetime,
    timezone: str,
    host_addresses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a strict manifest and reject duplicate host/command generations."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for section in sections:
        grouped.setdefault(section["host"], {}).setdefault(
            section["command_id"],
            [],
        ).append(section)

    hosts: dict[str, Any] = {}
    for host, command_groups in sorted(grouped.items()):
        commands: dict[str, Any] = {}
        host_partial = False
        host_failed = True
        for identifier, candidates in sorted(command_groups.items()):
            candidate = candidates[0]
            if len(candidates) > 1:
                host_partial = True
                command_record = {
                    "status": "failed",
                    "collected_at": candidate["collected_at"]
                    or started_at.isoformat(timespec="seconds"),
                    "file": candidate["file"],
                    "sha256": candidate["sha256"],
                    "command": candidate["command"],
                    "normalized_command": candidate["normalized_command"],
                    "source": candidate["source"],
                    "transport": candidate["transport"],
                    "confidence": "low",
                    "error": (
                        f"duplicate command generation is ambiguous: "
                        f"{len(candidates)} sections"
                    ),
                }
            else:
                command_record = {
                    key: value
                    for key, value in candidate.items()
                    if key
                    in {
                        "status",
                        "collected_at",
                        "file",
                        "sha256",
                        "command",
                        "normalized_command",
                        "source",
                        "transport",
                        "error",
                        "start_line",
                        "end_line",
                        "output_start_line",
                        "output_end_line",
                        "confidence",
                    }
                    and value is not None
                }
            if command_record["status"] == "success":
                host_failed = False
            else:
                host_partial = True
            commands[identifier] = command_record
        status = "failed" if host_failed else ("partial" if host_partial else "success")
        host_record: dict[str, Any] = {"status": status, "commands": commands}
        if host_addresses and host in host_addresses:
            host_record["address"] = host_addresses[host]
        hosts[host] = host_record

    document = {
        "api_version": API_VERSION,
        "kind": "CollectionManifest",
        "metadata": {
            "collection_id": collection_id,
            "change_id": change_id,
            "phase": phase,
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "profiles": list(profiles),
            "hosts": hosts,
        },
    }
    validate_document(document, kind="CollectionManifest")
    return document


def build_collect_manifest(
    inputs: Iterable[str | Path],
    *,
    collection_id: str,
    change_id: str,
    phase: str,
    profiles: list[str],
    started_at: datetime,
    completed_at: datetime,
    timezone: str,
    host_addresses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Adapt current alred collect files into one fixed collection generation."""
    files = discover_input_files(inputs, suffixes={".log", ".txt", ".json"})
    show_log_candidates = [
        path for path in files if path.name.endswith("_shows.log")
    ]
    nested_hosts = {
        path.name.removesuffix("_shows.log")
        for path in show_log_candidates
        if path.parent.name == path.name.removesuffix("_shows.log")
    }
    show_logs = [
        path
        for path in show_log_candidates
        if (
            path.parent.name == path.name.removesuffix("_shows.log")
            or path.name.removesuffix("_shows.log") not in nested_hosts
        )
    ]
    command_files = [
        path
        for path in files
        if path.parent.name == "commands" and path.suffix.lower() == ".txt"
    ]
    command_file_hosts = {
        path.parent.parent.name for path in command_files
    }
    sections: list[dict[str, Any]] = []
    for path in command_files:
        sections.extend(_parse_collect_sections(path))
    for path in show_logs:
        log_host = (
            path.parent.name
            if path.parent.name == path.name.removesuffix("_shows.log")
            else path.name.removesuffix("_shows.log")
        )
        if log_host in command_file_hosts:
            continue
        sections.extend(_parse_collect_sections(path))
    sections.extend(
        _lldp_entries(
            files,
            started_at.isoformat(timespec="seconds"),
        )
    )
    sections.extend(
        _running_config_entries(
            files,
            started_at.isoformat(timespec="seconds"),
        )
    )
    if not sections:
        raise CollectionAdapterError(
            "no alred collect command sections or running configs found"
        )
    return build_collection_manifest(
        sections,
        collection_id=collection_id,
        change_id=change_id,
        phase=phase,
        profiles=profiles,
        started_at=started_at,
        completed_at=completed_at,
        timezone=timezone,
        host_addresses=host_addresses,
    )
