"""Canonical Health Snapshot construction from a fixed Collection Manifest."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .interface_state import INTERFACE_STATE_VERSION
from .ntp_state import NTP_STATE_VERSION
from .parsers import (
    NTC_PARSER_IDENTIFIERS,
    NTC_TEMPLATES_VERSION,
    NXOS_PARSER_VERSION,
    ParserError,
    TEXTFSM_VERSION,
    parser_provenance,
    parse_nxos_command,
)
from ..schema import SCHEMA_VERSION, canonical_sha256, validate_document


SNAPSHOT_BUILDER_VERSION = "1.4"


class SnapshotBuildError(ValueError):
    """Raised when manifest provenance cannot be verified."""

    code = "PARSER_ERROR"


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest_command_output(record: Mapping[str, Any]) -> str:
    """Read and hash-verify one full or line-ranged manifest command output."""
    path = Path(record["file"])
    if not path.is_file() or path.is_symlink():
        raise SnapshotBuildError(f"manifest source is missing or unsafe: {path}")
    actual_digest = _source_sha256(path)
    if actual_digest != record["sha256"]:
        raise SnapshotBuildError(f"manifest source hash mismatch: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "output_start_line" not in record:
        return text
    lines = text.splitlines()
    start = int(record["output_start_line"])
    end = int(record["output_end_line"])
    if start > end:
        return ""
    if start < 1 or end > len(lines):
        raise SnapshotBuildError(
            f"manifest line range is outside source file: {path}:{start}-{end}"
        )
    return "\n".join(lines[start - 1 : end])


def _merge(target: dict[str, Any], update: Mapping[str, Any], path: str = "") -> None:
    for key, value in update.items():
        current_path = f"{path}/{key}"
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, Mapping):
            _merge(target[key], value, current_path)
        elif target[key] != value:
            raise SnapshotBuildError(f"parser output collision at {current_path}")


def build_health_snapshot(
    manifest: Mapping[str, Any],
    *,
    profile_refs: list[str],
    created_at: datetime,
    timezone: str,
    profile_sha256: str | None = None,
    link_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse only manifest-pinned command outputs into a v1 Snapshot."""
    validate_document(
        manifest,
        kind="CollectionManifest",
        allow_unknown_fields=True,
    )
    metadata = manifest["metadata"]
    profile_hash = profile_sha256 or canonical_sha256({"profiles": profile_refs})
    hosts: dict[str, Any] = {}
    for hostname, host_record in sorted(manifest["spec"]["hosts"].items()):
        source_platform = str(host_record.get("platform") or "nxos").strip().lower()
        common: dict[str, Any] = {}
        profiles: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        warnings: list[str] = []
        parsed_count = 0
        failed_count = 0
        for identifier, record in sorted(host_record["commands"].items()):
            source = {
                key: record[key]
                for key in (
                    "status",
                    "collected_at",
                    "file",
                    "sha256",
                    "command",
                    "normalized_command",
                    "source",
                    "transport",
                    "start_line",
                    "end_line",
                    "output_start_line",
                    "output_end_line",
                    "confidence",
                    "error",
                )
                if key in record
            }
            source.update(
                parser_provenance(
                    identifier,
                    device_type=source_platform,
                )
            )
            if record["status"] != "success":
                source["parse_status"] = "unknown"
                failed_count += 1
                warnings.append(
                    f"{identifier}: collection status is {record['status']}"
                )
                sources[identifier] = source
                continue
            try:
                output = read_manifest_command_output(record)
                common_update, profile_update = parse_nxos_command(
                    identifier,
                    output,
                    timezone=timezone,
                    device_type=source_platform,
                )
            except KeyError:
                source["parse_status"] = "unsupported"
            except ParserError as exc:
                source["parse_status"] = "unknown"
                source["parse_warning"] = str(exc)
                failed_count += 1
                warnings.append(f"{identifier}: {exc}")
            else:
                if identifier == "ntp_peer_status":
                    offset = int(record.get("output_start_line", 1)) - 1
                    for peer in common_update["ntp"]["peer_status"]["peers"].values():
                        peer["line_start"] += offset
                        peer["line_end"] += offset
                if identifier == "interface_detail":
                    detail_warnings = []
                    offset = int(record.get("output_start_line", 1)) - 1
                    for name, detail in common_update["interface_details"].items():
                        detail["line_start"] += offset
                        detail["line_end"] += offset
                        if detail["parse_status"] != "parsed":
                            detail_warnings.append(f"{name}: {detail['parse_warning']}")
                    if detail_warnings:
                        # Only port-level parse failures allow using other
                        # records. Collection/global parse failures never do.
                        source["partial_records"] = True
                        source["parse_warning"] = "; ".join(detail_warnings)
                        warnings.append(f"{identifier}: {source['parse_warning']}")
                _merge(common, common_update, f"/hosts/{hostname}/common")
                _merge(
                    profiles,
                    profile_update,
                    f"/hosts/{hostname}/profiles",
                )
                source["parse_status"] = "unknown" if source.get("partial_records") else "parsed"
                parsed_count += 1
            sources[identifier] = source
        if failed_count and not parsed_count:
            collection_status = "failed"
        elif failed_count or warnings or host_record["status"] != "success":
            collection_status = "partial"
        else:
            collection_status = "success"
        hosts[hostname] = {
            "collection_status": collection_status,
            "common": common,
            "profiles": profiles,
            "sources": sources,
            "parse_warnings": warnings,
        }
        if "address" in host_record:
            hosts[hostname]["address"] = host_record["address"]
        platform = str(
            host_record.get("platform")
            or common.get("system", {}).get("platform")
            or "unknown"
        ).strip().lower()
        hosts[hostname]["platform"] = platform or "unknown"

    parser_versions = {
        "snapshot_builder": SNAPSHOT_BUILDER_VERSION,
        "nxos": NXOS_PARSER_VERSION,
        "interface_state": INTERFACE_STATE_VERSION,
        "ntp_state": NTP_STATE_VERSION,
    }
    if any(
        identifier in NTC_PARSER_IDENTIFIERS
        for host_record in manifest["spec"]["hosts"].values()
        for identifier in host_record["commands"]
    ):
        parser_versions.update(
            {
                "ntc_templates": NTC_TEMPLATES_VERSION,
                "textfsm": TEXTFSM_VERSION,
            }
        )
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "change_id": metadata["change_id"],
        "collection_id": metadata["collection_id"],
        "phase": metadata["phase"],
        "created_at": created_at.isoformat(timespec="seconds"),
        "timezone": timezone,
        "parser_versions": parser_versions,
        "profile_sha256": profile_hash,
        "hosts": hosts,
    }
    if link_evidence is not None:
        snapshot["link_evidence"] = dict(link_evidence)
        parser_versions["link_normalizer"] = str(
            link_evidence["normalizer_version"]
        )
    validate_document(snapshot, kind="HealthSnapshot")
    return snapshot
