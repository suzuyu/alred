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


TRANSCRIPT_IMPORTER_VERSION = "1.1"
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_COLLECT_COMMAND_HEADER = re.compile(r"^### COMMAND:\s*")
_OPTIONAL_COLLECT_METADATA = re.compile(
    r"^### (?:COMMAND|COLLECTED_AT|STATUS|TRANSPORT):\s*",
    re.IGNORECASE,
)
_PROMPT_COMMAND = re.compile(
    r"^(?P<prompt>[A-Za-z0-9_.-]+)"
    r"(?:\([^\\r\\n]*\))*[#>]\s*(?P<command>.+?)\s*$"
)
_FILENAME_TIMESTAMP = re.compile(
    r"(?<!\d)(?P<date>\d{8})(?:T|_|-)?(?P<time>\d{6})(?!\d)",
    re.IGNORECASE,
)
_PHASE_RANK = {"before": 1, "work": 2, "after": 3}


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


def _normalized_output_sha256(lines: list[str]) -> str:
    normalized = "\n".join(line.rstrip() for line in lines).strip("\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _filename_order_metadata(path: Path) -> tuple[str | None, str | None]:
    names = [path.name, *(parent.name for parent in list(path.parents)[:3])]
    tokens = {
        token
        for name in names
        for token in re.split(r"[^a-z0-9]+", name.lower())
        if token
    }
    phases = [phase for phase in _PHASE_RANK if phase in tokens]
    phase = max(phases, key=_PHASE_RANK.__getitem__) if phases else None
    timestamp: str | None = None
    for name in names:
        match = _FILENAME_TIMESTAMP.search(name)
        if not match:
            continue
        raw = f"{match.group('date')}{match.group('time')}"
        try:
            datetime.strptime(raw, "%Y%m%d%H%M%S")
        except ValueError:
            continue
        timestamp = raw
        break
    return phase, timestamp


def _candidate_evidence(section: Mapping[str, Any]) -> dict[str, Any]:
    evidence = {
        "source_file": section["file"],
        "start_line": section["start_line"],
        "end_line": section["end_line"],
        "output_sha256": section["output_sha256"],
        "mtime_ns": section["mtime_ns"],
        "selected": bool(section.get("selected", False)),
    }
    if section.get("filename_phase") is not None:
        evidence["filename_phase"] = section["filename_phase"]
    if section.get("filename_timestamp") is not None:
        evidence["filename_timestamp"] = section["filename_timestamp"]
    return evidence


def _select_duplicate(
    candidates: list[dict[str, Any]],
    *,
    duplicate_policy: str,
    file_order: str,
) -> tuple[dict[str, Any] | None, str]:
    if duplicate_policy == "reject":
        return None, "reject"

    output_hashes = {candidate["output_sha256"] for candidate in candidates}
    if len(output_hashes) == 1:
        return max(
            candidates,
            key=lambda candidate: (candidate["file"], candidate["start_line"]),
        ), "identical-output"

    paths = {candidate["file"] for candidate in candidates}
    if len(paths) == 1:
        return (
            max(candidates, key=lambda candidate: candidate["start_line"]),
            "later-line",
        )

    latest_in_file: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        current = latest_in_file.get(candidate["file"])
        if current is None or candidate["start_line"] > current["start_line"]:
            latest_in_file[candidate["file"]] = candidate
    file_candidates = list(latest_in_file.values())

    if file_order == "mtime":
        latest_mtime = max(candidate["mtime_ns"] for candidate in file_candidates)
        newest = [
            candidate
            for candidate in file_candidates
            if candidate["mtime_ns"] == latest_mtime
        ]
        if len(newest) == 1:
            return newest[0], "file-mtime"
        return None, "file-mtime-tie"

    if file_order == "filename":
        highest_phase = max(
            _PHASE_RANK.get(candidate.get("filename_phase"), 0)
            for candidate in file_candidates
        )
        phase_candidates = [
            candidate
            for candidate in file_candidates
            if _PHASE_RANK.get(candidate.get("filename_phase"), 0)
            == highest_phase
        ]
        if len(phase_candidates) == 1 and highest_phase > 0:
            return phase_candidates[0], "filename-phase"
        if any(
            candidate.get("filename_timestamp") is None
            for candidate in phase_candidates
        ):
            return None, "filename-timestamp-missing"
        latest_timestamp = max(
            candidate["filename_timestamp"] for candidate in phase_candidates
        )
        newest = [
            candidate
            for candidate in phase_candidates
            if candidate["filename_timestamp"] == latest_timestamp
        ]
        if len(newest) == 1:
            return newest[0], "filename-timestamp"
        return None, "filename-timestamp-tie"

    return None, "file-order-reject"


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
    duplicate_policy: str = "safe-latest",
    file_order: str = "reject",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import high-confidence prompt/command segments without guessing."""
    if duplicate_policy not in {"reject", "safe-latest"}:
        raise TranscriptImportError(
            f"unsupported transcript duplicate policy: {duplicate_policy}"
        )
    if file_order not in {"reject", "mtime", "filename"}:
        raise TranscriptImportError(
            f"unsupported transcript file order: {file_order}"
        )
    files = discover_input_files(inputs, suffixes={".log", ".txt"})
    aliases, match_reasons = load_inventory_aliases(hosts_path)
    host_data: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = []

    for path in files:
        digest = _sha256(path)
        mtime_ns = path.stat().st_mtime_ns
        filename_phase, filename_timestamp = _filename_order_metadata(path)
        input_records.append(
            {"path": str(path), "sha256": digest, "mtime_ns": mtime_ns}
        )
        lines = _clean_transcript(
            path.read_text(encoding="utf-8", errors="replace")
        ).splitlines()
        detected: list[tuple[int, re.Match[str]]] = []
        for index, line in enumerate(lines):
            match = _PROMPT_COMMAND.match(line)
            if match and _looks_like_command(match.group("command")):
                detected.append((index, match))

        first_command_line = detected[0][0] if detected else len(lines)
        preamble = lines[:first_command_line]
        if any(
            line.strip() and not _OPTIONAL_COLLECT_METADATA.match(line)
            for line in preamble
        ):
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
            output_end_index = next_index
            for index in range(start_index + 1, next_index):
                if _COLLECT_COMMAND_HEADER.match(lines[index]):
                    output_end_index = index
                    break
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
                        "end_line": max(output_end_index, start_index + 1),
                        "reason": "hostname_not_in_inventory",
                        "confidence": "low",
                        "detected_prompt": prompt,
                        "command": raw_command,
                    }
                )
                continue
            normalized = normalize_command(raw_command)
            identifier = command_id(raw_command)
            output_sha256 = _normalized_output_sha256(
                lines[start_index + 1 : output_end_index]
            )
            segment = {
                "command": raw_command,
                "normalized_command": normalized,
                "command_id": identifier,
                "source_file": str(path),
                "start_line": start_index + 1,
                "end_line": max(output_end_index, start_index + 1),
                "output_start_line": start_index + 2,
                "output_end_line": max(output_end_index, 1),
                "output_sha256": output_sha256,
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
                    "end_line": max(output_end_index, start_index + 1),
                    "output_start_line": start_index + 2,
                    "output_end_line": max(output_end_index, 1),
                    "output_sha256": output_sha256,
                    "mtime_ns": mtime_ns,
                    "filename_phase": filename_phase,
                    "filename_timestamp": filename_timestamp,
                    "_segment": segment,
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
    duplicate_groups: list[dict[str, Any]] = []
    resolved_sections: list[dict[str, Any]] = []
    for (hostname, identifier), candidates in duplicates.items():
        if len(candidates) < 2:
            candidates[0]["selected"] = True
            candidates[0]["_segment"]["selected"] = True
            resolved_sections.append(candidates[0])
            continue
        selected, selection_basis = _select_duplicate(
            candidates,
            duplicate_policy=duplicate_policy,
            file_order=file_order,
        )
        if selected is None:
            ambiguous_count += len(candidates)
            for section in candidates:
                section["selected"] = False
                section["confidence"] = "low"
                section["status"] = "failed"
                section["error"] = "duplicate command generation is ambiguous"
                section["_segment"]["selected"] = False
                section["_segment"]["confidence"] = "low"
                section["_segment"]["ambiguous"] = True
            resolved_sections.extend(candidates)
            resolution = "ambiguous"
        else:
            for section in candidates:
                is_selected = section is selected
                section["selected"] = is_selected
                section["_segment"]["selected"] = is_selected
                if is_selected:
                    resolved_sections.append(section)
            resolution = "selected"
        duplicate_groups.append(
            {
                "host": hostname,
                "command_id": identifier,
                "resolution": resolution,
                "selection_basis": selection_basis,
                "candidates": [
                    _candidate_evidence(candidate)
                    for candidate in sorted(
                        candidates,
                        key=lambda item: (item["file"], item["start_line"]),
                    )
                ],
            }
        )

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
            "importer_version": TRANSCRIPT_IMPORTER_VERSION,
            "imported_at": imported_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "input_format": "nxos-transcript",
            "duplicate_policy": duplicate_policy,
            "file_order": file_order,
            "inputs": input_records,
            "hosts": serializable_hosts,
            "unresolved_segments": unresolved,
            "duplicate_groups": duplicate_groups,
            "summary": {
                "files_scanned": len(files),
                "hosts_detected": len(serializable_hosts),
                "commands_detected": len(all_sections),
                "unresolved_segments": len(unresolved),
                "ambiguous_segments": ambiguous_count,
                "duplicate_groups": len(duplicate_groups),
                "resolved_duplicate_groups": sum(
                    group["resolution"] == "selected"
                    for group in duplicate_groups
                ),
                "ambiguous_duplicate_groups": sum(
                    group["resolution"] == "ambiguous"
                    for group in duplicate_groups
                ),
            },
        },
    }
    validate_document(
        import_manifest,
        kind="TranscriptImportManifest",
    )
    collection_manifest = build_collection_manifest(
        resolved_sections,
        collection_id=collection_id,
        change_id=change_id,
        phase=phase,
        profiles=profiles,
        started_at=imported_at,
        completed_at=imported_at,
        timezone=timezone,
    )
    return import_manifest, collection_manifest
