"""NX-OS external CLI transcript importer."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml

from .commands import command_id, normalize_command
from .manifest import (
    CollectionAdapterError,
    build_collection_manifest,
    discover_input_files,
)
from ..schema import API_VERSION, validate_document


TRANSCRIPT_IMPORTER_VERSION = "1.0"
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_PROMPT_COMMAND = re.compile(
    r"^(?P<prompt>[A-Za-z0-9_.-]+)"
    r"(?:\([^\\r\\n]*\))*[#>]\s*(?P<command>.+?)\s*$"
)


class TranscriptImportError(CollectionAdapterError):
    """Raised when transcript identity cannot be resolved safely."""

    code = "COLLECTION_ERROR"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _clean_transcript(text: str) -> str:
    cleaned = _ANSI_ESCAPE.sub("", text)
    characters: list[str] = []
    for character in cleaned:
        if character == "\b":
            if characters:
                characters.pop()
            continue
        characters.append(character)
    return "".join(characters).replace("--More--", "")


def load_inventory_aliases(
    hosts_path: str | Path | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build a collision-checked alias map and match reason map."""
    if hosts_path is None:
        return {}, {}
    path = Path(hosts_path)
    if not path.is_file() or path.is_symlink():
        raise TranscriptImportError(f"hosts inventory not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        hosts = document["all"]["hosts"]
    except (KeyError, TypeError) as exc:
        raise TranscriptImportError(
            "hosts inventory must contain all.hosts"
        ) from exc
    if not isinstance(hosts, Mapping):
        raise TranscriptImportError("all.hosts must be a mapping")

    candidates: dict[str, list[tuple[str, str]]] = {}
    for hostname, attributes in hosts.items():
        if not isinstance(hostname, str) or not hostname:
            raise TranscriptImportError("inventory hostname must be a string")
        keys = [(hostname, "hostname")]
        short_name = hostname.split(".", 1)[0]
        if short_name != hostname:
            keys.append((short_name, "short_name"))
        if isinstance(attributes, Mapping):
            raw_aliases = attributes.get("aliases", [])
            if isinstance(raw_aliases, str):
                raw_aliases = [raw_aliases]
            if not isinstance(raw_aliases, list):
                raise TranscriptImportError(
                    f"aliases for {hostname} must be a string or list"
                )
            keys.extend((str(alias), "alias") for alias in raw_aliases)
        for key, reason in keys:
            candidates.setdefault(key.lower(), []).append((hostname, reason))

    aliases: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for key, matches in sorted(candidates.items()):
        unique_hosts = {hostname for hostname, _reason in matches}
        if len(unique_hosts) > 1:
            raise TranscriptImportError(
                f"inventory alias is ambiguous: {key} -> "
                f"{', '.join(sorted(unique_hosts))}"
            )
        aliases[key] = matches[0][0]
        reasons[key] = matches[0][1]
    return aliases, reasons


def _looks_like_command(command: str) -> bool:
    normalized = normalize_command(command)
    return normalized.startswith("show ")


def _resolve_prompt(
    prompt: str,
    aliases: Mapping[str, str],
    reasons: Mapping[str, str],
) -> tuple[str | None, str | None]:
    if not aliases:
        return prompt, "detected"
    lowered = prompt.lower()
    if lowered in aliases:
        return aliases[lowered], reasons[lowered]
    short = lowered.split(".", 1)[0]
    if short in aliases:
        return aliases[short], reasons[short]
    return None, None


def import_nxos_transcripts(
    inputs: Iterable[str | Path],
    *,
    collection_id: str,
    change_id: str,
    phase: str,
    profiles: list[str],
    imported_at: datetime,
    timezone: str,
    hosts_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import high-confidence prompt/command segments without guessing."""
    files = discover_input_files(inputs, suffixes={".log", ".txt"})
    aliases, match_reasons = load_inventory_aliases(hosts_path)
    host_data: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    input_records: list[dict[str, str]] = []

    for path in files:
        digest = _sha256(path)
        input_records.append({"path": str(path), "sha256": digest})
        lines = _clean_transcript(
            path.read_text(encoding="utf-8", errors="replace")
        ).splitlines()
        detected: list[tuple[int, re.Match[str]]] = []
        for index, line in enumerate(lines):
            match = _PROMPT_COMMAND.match(line)
            if match and _looks_like_command(match.group("command")):
                detected.append((index, match))

        first_command_line = detected[0][0] if detected else len(lines)
        if any(line.strip() for line in lines[:first_command_line]):
            unresolved.append(
                {
                    "source_file": str(path),
                    "start_line": 1,
                    "end_line": max(first_command_line, 1),
                    "reason": "command_prompt_not_detected",
                    "confidence": "low",
                }
            )
        if not detected and lines:
            continue

        for position, (start_index, match) in enumerate(detected):
            next_index = (
                detected[position + 1][0]
                if position + 1 < len(detected)
                else len(lines)
            )
            prompt = match.group("prompt")
            raw_command = match.group("command").strip()
            inventory_name, matched_by = _resolve_prompt(
                prompt,
                aliases,
                match_reasons,
            )
            if inventory_name is None:
                unresolved.append(
                    {
                        "source_file": str(path),
                        "start_line": start_index + 1,
                        "end_line": max(next_index, start_index + 1),
                        "reason": "hostname_not_in_inventory",
                        "confidence": "low",
                        "detected_prompt": prompt,
                        "command": raw_command,
                    }
                )
                continue
            normalized = normalize_command(raw_command)
            identifier = command_id(raw_command)
            segment = {
                "command": raw_command,
                "normalized_command": normalized,
                "command_id": identifier,
                "source_file": str(path),
                "start_line": start_index + 1,
                "end_line": max(next_index, start_index + 1),
                "output_start_line": start_index + 2,
                "output_end_line": max(next_index, 1),
                "confidence": "high",
            }
            host = host_data.setdefault(
                inventory_name,
                {
                    "detected_prompts": set(),
                    "inventory_name": inventory_name,
                    "matched_by": matched_by,
                    "platform": "nxos",
                    "segments": [],
                },
            )
            host["detected_prompts"].add(prompt)
            host["segments"].append(segment)
            all_sections.append(
                {
                    "host": inventory_name,
                    "command": raw_command,
                    "normalized_command": normalized,
                    "command_id": identifier,
                    "status": "success",
                    "collected_at": imported_at.isoformat(timespec="seconds"),
                    "file": str(path),
                    "sha256": digest,
                    "source": "external_transcript",
                    "transport": "external",
                    "start_line": start_index + 1,
                    "end_line": max(next_index, start_index + 1),
                    "output_start_line": start_index + 2,
                    "output_end_line": max(next_index, 1),
                    "confidence": "high",
                    "error": None,
                }
            )

    duplicates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for section in all_sections:
        duplicates.setdefault(
            (section["host"], section["command_id"]),
            [],
        ).append(section)
    ambiguous_count = 0
    for (hostname, identifier), candidates in duplicates.items():
        if len(candidates) < 2:
            continue
        ambiguous_count += len(candidates)
        for section in candidates:
            section["confidence"] = "low"
            section["status"] = "failed"
            section["error"] = "duplicate command generation is ambiguous"
        for segment in host_data[hostname]["segments"]:
            if segment["command_id"] == identifier:
                segment["confidence"] = "low"
                segment["ambiguous"] = True

    serializable_hosts: dict[str, Any] = {}
    for hostname, data in sorted(host_data.items()):
        serializable_hosts[hostname] = {
            **data,
            "detected_prompts": sorted(data["detected_prompts"]),
            "segments": sorted(
                data["segments"],
                key=lambda item: (
                    item["source_file"],
                    item["start_line"],
                ),
            ),
        }
    import_manifest = {
        "api_version": API_VERSION,
        "kind": "TranscriptImportManifest",
        "metadata": {
            "change_id": change_id,
            "phase": phase,
            "source": "external_transcript",
            "imported_at": imported_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "input_format": "nxos-transcript",
            "inputs": input_records,
            "hosts": serializable_hosts,
            "unresolved_segments": unresolved,
            "summary": {
                "files_scanned": len(files),
                "hosts_detected": len(serializable_hosts),
                "commands_detected": len(all_sections),
                "unresolved_segments": len(unresolved),
                "ambiguous_segments": ambiguous_count,
            },
        },
    }
    validate_document(
        import_manifest,
        kind="TranscriptImportManifest",
    )
    collection_manifest = build_collection_manifest(
        all_sections,
        collection_id=collection_id,
        change_id=change_id,
        phase=phase,
        profiles=profiles,
        started_at=imported_at,
        completed_at=imported_at,
        timezone=timezone,
    )
    return import_manifest, collection_manifest
