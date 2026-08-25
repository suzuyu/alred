"""Portable, manifest-selected evidence archives for offline consumers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import gzip
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any, Mapping

import yaml

from . import __version__
from .operation import (
    OperationWorkspace,
    atomic_update_relative_directory_symlink,
    atomic_write_bytes,
    list_live_operation_ids,
    load_operation_location,
    open_operation_workspace,
    remove_missing_live_operation_index,
)
from .inventory import load_inventory_data, load_inventory_map_from_list
from .parsing import (
    build_description_records,
    load_description_rules,
    load_mappings,
    load_roles,
    load_sites,
    merge_lldp_and_description_links,
    normalize_link_records,
    parse_lldp_file,
)
from .schema import (
    API_VERSION,
    DocumentValidationError,
    canonical_sha256,
    source_sha256,
    validate_document,
)
from .link_diagnostics import build_link_diagnostics
from .secret_scan import (
    CATALOG_SHA256,
    CATALOG_VERSION,
    SecretFinding,
    build_scan_result,
    is_secret_bearing_line,
    sanitize_text,
    scan_text,
)


class EvidencePackageError(ValueError):
    """Expected portable evidence validation or integrity failure."""

    code = "EVIDENCE_INVALID_SOURCE"


@dataclass(frozen=True)
class EvidenceCollectionSource:
    """One pinned Collection Manifest source selected before package creation."""

    collection_manifest: Path
    raw_root: Path
    selection: str
    change_id: str | None = None
    attempt_id: str | None = None
    completed_at: datetime | None = None


_IPV4_RE = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(/\d{1,2})?(?![\d.])")
_SOURCE_RANGE_FIELDS = (
    "start_line",
    "end_line",
    "output_start_line",
    "output_end_line",
)
_LINK_FIELDS = (
    "src_node", "src_if", "dst_node", "dst_if", "protocol", "confidence",
    "evidence", "remote_mgmt_ip", "rule_name", "warning",
)


def _canonical_link_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return stable link rows for package hashing and CSV serialization."""
    normalized = [
        {field: str(record.get(field, "")) for field in _LINK_FIELDS}
        for record in records
    ]
    return sorted(
        normalized,
        key=lambda record: (
            tuple(sorted(((record["src_node"], record["src_if"]), (record["dst_node"], record["dst_if"])))),
            record["protocol"],
            record["evidence"],
            record["warning"],
        ),
    )


def _links_csv_bytes(records: list[dict[str, str]]) -> bytes:
    import csv

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(_LINK_FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(_canonical_link_records(records))
    return stream.getvalue().encode()


def canonical_links_sha256(records: list[dict[str, str]]) -> str:
    """Hash link semantics independently from CSV line endings."""
    return canonical_sha256(_canonical_link_records(records))


def canonical_confirmed_links_sha256(records: list[dict[str, str]]) -> str:
    """Hash confirmed links independently from endpoint observation direction."""
    semantic_records: list[dict[str, str]] = []
    for record in records:
        endpoints = sorted(
            (
                (str(record.get("src_node", "")), str(record.get("src_if", ""))),
                (str(record.get("dst_node", "")), str(record.get("dst_if", ""))),
            )
        )
        semantic_records.append(
            {
                "endpoint_a_node": endpoints[0][0],
                "endpoint_a_if": endpoints[0][1],
                "endpoint_b_node": endpoints[1][0],
                "endpoint_b_if": endpoints[1][1],
                "protocol": str(record.get("protocol", "")),
                "confidence": str(record.get("confidence", "")),
                "evidence": str(record.get("evidence", "")),
                "rule_name": str(record.get("rule_name", "")),
                "warning": str(record.get("warning", "")),
            }
        )
    return canonical_sha256(
        sorted(
            semantic_records,
            key=lambda record: tuple(record.values()),
        )
    )


def _read_source_document(path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: missing or unsafe {kind}: {path}"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("document is not an object")
        validate_document(document, kind=kind)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        DocumentValidationError,
    ) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: invalid {kind}: {path}"
        ) from exc
    return document


def _path_has_suffix(value: str, expected: Path) -> bool:
    value_parts = Path(value).parts
    expected_parts = expected.parts
    return (
        len(value_parts) >= len(expected_parts)
        and value_parts[-len(expected_parts) :] == expected_parts
    )


def _read_current_before_pointer(
    workspace: OperationWorkspace,
) -> tuple[dict[str, Any], str, Path]:
    change_id = workspace.change_id
    phase_relative = Path("health") / "before"
    current_path = workspace.operation_root / phase_relative / "current.json"
    current = _read_source_document(current_path, "HealthPhaseCurrent")
    if current["change_id"] != change_id or current["phase"] != "before":
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: current before identity mismatch: {change_id}"
        )

    attempt_id = str(current["attempt_id"])
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", attempt_id)
        or ".." in attempt_id
    ):
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe before attempt ID: {attempt_id}"
        )
    attempt_relative = phase_relative / "attempts" / attempt_id
    if not _path_has_suffix(str(current["artifact_dir"]), attempt_relative):
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: current before artifact path mismatch: {change_id}"
        )
    return current, attempt_id, attempt_relative


def _resolve_current_before_source(
    operations_root: str | Path,
    change_id: str,
) -> EvidenceCollectionSource:
    remove_missing_live_operation_index(operations_root, change_id)
    workspace = open_operation_workspace(operations_root, change_id)
    current_path = workspace.operation_root / "health" / "before" / "current.json"
    if not current_path.exists():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: operation has no published current before attempt: {change_id}"
        )
    current, attempt_id, attempt_relative = _read_current_before_pointer(
        workspace
    )
    attempt_dir = workspace.operation_root / attempt_relative
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: missing or unsafe before attempt: {attempt_dir}"
        )
    snapshot_relative = attempt_relative / "snapshot.json"
    snapshot_path = attempt_dir / "snapshot.json"
    if (
        not _path_has_suffix(str(current["snapshot_path"]), snapshot_relative)
        or not snapshot_path.is_file()
        or snapshot_path.is_symlink()
        or source_sha256(snapshot_path) != current["snapshot_sha256"]
    ):
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: current before Snapshot mismatch: {change_id}"
        )

    attempt = _read_source_document(
        attempt_dir / "result.json", "HealthPhaseAttempt"
    )
    if (
        attempt["change_id"] != change_id
        or attempt["phase"] != "before"
        or attempt["attempt_id"] != attempt_id
        or attempt["status"] != "COMPLETED"
        or attempt.get("completed_at") != current["completed_at"]
    ):
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: before attempt is not the published completed attempt: {change_id}"
        )

    manifest_path = attempt_dir / "collection-manifest.yaml"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: missing Collection Manifest: {manifest_path}"
        )
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("document is not an object")
        validate_document(manifest, kind="CollectionManifest")
    except (
        OSError,
        UnicodeDecodeError,
        yaml.YAMLError,
        ValueError,
        DocumentValidationError,
    ) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: invalid Collection Manifest: {manifest_path}"
        ) from exc
    metadata = manifest["metadata"]
    if metadata.get("change_id") != change_id or metadata.get("phase") != "before":
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: Collection Manifest identity mismatch: {manifest_path}"
        )

    return EvidenceCollectionSource(
        collection_manifest=manifest_path,
        raw_root=attempt_dir,
        selection="operation-current-before",
        change_id=change_id,
        attempt_id=attempt_id,
        completed_at=datetime.fromisoformat(current["completed_at"]),
    )


def resolve_evidence_collection_source(
    *,
    operations_root: str | Path,
    change_id: str | None = None,
    collection_manifest: str | Path | None = None,
    raw_root: str | Path | None = None,
) -> EvidenceCollectionSource:
    """Resolve an explicit source or the latest published live before attempt."""
    has_manifest = collection_manifest is not None
    has_raw_root = raw_root is not None
    if change_id is not None and (has_manifest or has_raw_root):
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: --change-id cannot be combined with "
            "--collection-manifest or --input"
        )
    if has_manifest != has_raw_root:
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: --collection-manifest and --input must be specified together"
        )
    if has_manifest and has_raw_root:
        return EvidenceCollectionSource(
            collection_manifest=Path(collection_manifest),
            raw_root=Path(raw_root),
            selection="explicit-collection-manifest",
        )
    if change_id is not None:
        return _resolve_current_before_source(operations_root, change_id)

    candidates: list[tuple[datetime, str]] = []
    for operation_id in list_live_operation_ids(operations_root):
        location = load_operation_location(operations_root, operation_id)
        if location is not None and remove_missing_live_operation_index(
            operations_root, operation_id
        ):
            continue
        if location is None:
            legacy_current = (
                Path(operations_root)
                / operation_id
                / "health"
                / "before"
                / "current.json"
            )
            if not legacy_current.exists() and not legacy_current.is_symlink():
                continue
        workspace = open_operation_workspace(operations_root, operation_id)
        if not (workspace.operation_root / "health" / "before" / "current.json").exists():
            continue
        current, _attempt_id, _attempt_relative = _read_current_before_pointer(
            workspace
        )
        candidates.append(
            (datetime.fromisoformat(current["completed_at"]), operation_id)
        )
    if not candidates:
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: no live operation has a published current before attempt"
        )

    latest_completed_at = max(item[0] for item in candidates)
    latest = [
        item for item in candidates if item[0] == latest_completed_at
    ]
    if len(latest) != 1:
        identifiers = ", ".join(sorted(item[1] for item in latest))
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: multiple current before attempts share the "
            f"latest completed_at ({identifiers}); specify --change-id"
        )
    return _resolve_current_before_source(operations_root, latest[0][1])


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_secret_bearing_line(line: str) -> bool:
    """Compatibility wrapper around the common scanner."""
    return is_secret_bearing_line(line)


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name and not path.is_absolute() and ".." not in path.parts and path.parts[0] == "alred-evidence")


def _resolve_source_file(raw_root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = raw_root / candidate
    if not candidate.is_file() or candidate.is_symlink():
        raise EvidencePackageError(f"EVIDENCE_INVALID_SOURCE: not a regular file: {candidate}")
    return candidate


def _command_output_bytes(
    source_bytes: bytes,
    command: Mapping[str, Any],
    *,
    source: Path,
) -> bytes:
    """Extract only the Manifest-pinned command output from a shared transcript."""
    has_start = "output_start_line" in command
    has_end = "output_end_line" in command
    if has_start != has_end:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: incomplete output line range: {source}"
        )
    if not has_start:
        return source_bytes
    try:
        text = source_bytes.decode("utf-8", errors="strict")
        start = int(command["output_start_line"])
        end = int(command["output_end_line"])
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: invalid command output range: {source}"
        ) from exc
    lines = text.splitlines()
    if start < 1 or end > len(lines):
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: command output range outside source: "
            f"{source}:{start}-{end}"
        )
    if start > end:
        return b""
    return ("\n".join(lines[start - 1 : end]) + "\n").encode("utf-8")


def load_collection_link_inputs(
    source: EvidenceCollectionSource,
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, bytes]]:
    """Load Manifest-selected running config and optional LLDP command bytes."""
    manifest = yaml.safe_load(source.collection_manifest.read_text(encoding="utf-8")) or {}
    validate_document(manifest, kind="CollectionManifest")
    inventory: dict[str, Any] = {"all": {"hosts": {}}}
    configs: dict[str, bytes] = {}
    lldp: dict[str, bytes] = {}
    for hostname, host in sorted(manifest["spec"]["hosts"].items()):
        inventory["all"]["hosts"][hostname] = {
            "ansible_host": host.get("address"),
            "device_type": host.get("device_type", host.get("platform", "nxos")),
        }
        for command_id in ("running_config", "lldp_neighbors_detail"):
            command = host.get("commands", {}).get(command_id)
            if not isinstance(command, Mapping) or command.get("status") != "success":
                continue
            path = _resolve_source_file(source.raw_root, str(command["file"]))
            content = path.read_bytes()
            expected = str(command["sha256"]).removeprefix("sha256:")
            if _sha256_bytes(content) != expected:
                raise EvidencePackageError(f"EVIDENCE_INVALID_SOURCE: hash mismatch: {path}")
            selected = _command_output_bytes(content, command, source=path)
            if command_id == "running_config":
                configs[hostname] = selected
            else:
                lldp[hostname] = selected
    if not configs:
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: no successful running config")
    return inventory, configs, lldp


def load_collection_command_inputs(
    source: EvidenceCollectionSource,
    command_ids: set[str],
) -> dict[str, dict[str, bytes]]:
    """Load successful command outputs selected by a Collection Manifest."""
    manifest = yaml.safe_load(source.collection_manifest.read_text(encoding="utf-8")) or {}
    validate_document(manifest, kind="CollectionManifest")
    outputs = {command_id: {} for command_id in sorted(command_ids)}
    for hostname, host in sorted(manifest["spec"]["hosts"].items()):
        for command_id in sorted(command_ids):
            command = host.get("commands", {}).get(command_id)
            if not isinstance(command, Mapping) or command.get("status") != "success":
                continue
            path = _resolve_source_file(source.raw_root, str(command["file"]))
            content = path.read_bytes()
            expected = str(command["sha256"]).removeprefix("sha256:")
            if _sha256_bytes(content) != expected:
                raise EvidencePackageError(
                    f"EVIDENCE_INVALID_SOURCE: hash mismatch: {path}"
                )
            outputs[command_id][hostname] = _command_output_bytes(
                content, command, source=path
            )
    return outputs


class _Pseudonyms:
    def __init__(self, hostnames: list[str]):
        self.hosts = {
            hostname: f"node-{index:03d}"
            for index, hostname in enumerate(sorted(set(hostnames)), start=1)
        }
        self.addresses: dict[str, str] = {}

    def address(self, value: str) -> str:
        if value not in self.addresses:
            index = len(self.addresses) + 1
            network = ipaddress.ip_network("198.18.0.0/15")
            if index >= network.num_addresses - 1:
                raise EvidencePackageError("EVIDENCE_TOO_LARGE: address pseudonym space exhausted")
            self.addresses[value] = str(network.network_address + index)
        return self.addresses[value]

    def text(self, content: str) -> str:
        output: list[str] = []
        hostname_patterns = sorted(self.hosts, key=len, reverse=True)
        for line in content.splitlines():
            transformed = line
            for hostname in hostname_patterns:
                transformed = re.sub(
                    rf"(?<![A-Za-z0-9_.-]){re.escape(hostname)}(?![A-Za-z0-9_.-])",
                    self.hosts[hostname],
                    transformed,
                    flags=re.IGNORECASE,
                )
            transformed = _IPV4_RE.sub(
                lambda match: self.address(match.group(1)) + (match.group(2) or ""),
                transformed,
            )
            output.append(transformed)
        return "\n".join(output).rstrip() + "\n"


def _sanitize_document(value: Any, pseudonyms: _Pseudonyms) -> Any:
    if isinstance(value, str):
        transformed = value
        for source, target in pseudonyms.hosts.items():
            if transformed.casefold() == source.casefold():
                return target
        if _IPV4_RE.fullmatch(transformed):
            match = _IPV4_RE.fullmatch(transformed)
            assert match is not None
            return pseudonyms.address(match.group(1)) + (match.group(2) or "")
        return transformed
    if isinstance(value, list):
        return [_sanitize_document(item, pseudonyms) for item in value]
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if str(key).lower() in {"password", "secret", "token", "credential", "credentials"}:
                continue
            target_key = pseudonyms.hosts.get(str(key), str(key))
            result[target_key] = _sanitize_document(item, pseudonyms)
        return result
    return value


def _protected_document(value: Any) -> Any:
    """Remove secret-valued fields while preserving device identity and addresses."""
    if isinstance(value, list):
        return [_protected_document(item) for item in value]
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if str(key).lower() in {
                "password",
                "secret",
                "token",
                "credential",
                "credentials",
            }:
                continue
            result[str(key)] = _protected_document(item)
        return result
    return value


def _protected_text(content: str) -> tuple[str, int]:
    """Remove secret-bearing material while preserving allowed identities and addresses."""
    protected, findings = sanitize_text(
        content,
        artifact_id="text",
        path="text",
        platform="nxos",
        content_type="running-config",
    )
    return protected, len(findings)


def _count_verbatim_secret_findings(content: str) -> int:
    return len(
        scan_text(
            content,
            artifact_id="text",
            path="text",
            platform="nxos",
            content_type="running-config",
        )
    )


def _scan_package_members(
    files: Mapping[str, bytes],
    entries: list[dict[str, Any]],
) -> tuple[list[SecretFinding], int]:
    """Independently scan every content member before generated integrity metadata."""
    entries_by_path = {
        f"alred-evidence/{entry['path']}": entry
        for entry in entries
    }
    findings: list[SecretFinding] = []
    scanned = 0
    for name, content in sorted(files.items()):
        if name in {
            "alred-evidence/package-manifest.yaml",
            "alred-evidence/checksums.sha256",
        }:
            continue
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise EvidencePackageError(
                f"EVIDENCE_SCAN_FAILED: text member is not UTF-8: {name}"
            ) from exc
        entry = entries_by_path.get(name)
        relative = name.removeprefix("alred-evidence/")
        artifact_id = (
            str(entry["artifact_id"])
            if entry is not None
            else f"package:{relative}"
        )
        command_id = str(entry.get("command_id", "")) if entry else ""
        findings.extend(
            scan_text(
                text,
                artifact_id=artifact_id,
                path=relative,
                platform="nxos" if entry is not None else None,
                content_type=(
                    "running-config" if command_id == "running_config" else "cli-output"
                ),
            )
        )
        scanned += 1
    return findings, scanned


def _enforce_scan_result(
    findings: list[SecretFinding],
    entries: list[dict[str, Any]],
) -> None:
    """Allow high findings only in explicitly acknowledged verbatim members."""
    verbatim_paths = {
        str(entry["path"])
        for entry in entries
        if entry.get("disclosure") == "verbatim"
    }
    blocked = [
        finding
        for finding in findings
        if finding.confidence == "high" and finding.path not in verbatim_paths
    ]
    if blocked:
        first = blocked[0]
        raise EvidencePackageError(
            "EVIDENCE_BLOCKED_SECRET: high-confidence finding "
            f"{first.rule_id} at {first.path}:{first.line}"
        )


def _deterministic_archive(path: Path, files: Mapping[str, bytes]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name, content in sorted(files.items()):
                        if not _safe_member_name(name):
                            raise EvidencePackageError(f"EVIDENCE_UNSAFE_ARCHIVE: {name}")
                        info = tarfile.TarInfo(name)
                        info.size = len(content)
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 0o600
                        archive.addfile(info, io.BytesIO(content))
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_package_manifest(document: Any) -> bool:
    """Validate the current schema or the pre-secret-scan compatibility shape."""
    if not isinstance(document, Mapping):
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: package manifest is not an object"
        )
    spec = document.get("spec")
    if not isinstance(spec, Mapping):
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: package manifest spec is missing"
        )
    if "secret_scan" in spec:
        try:
            validate_document(document, kind="EvidencePackageManifest")
        except ValueError as exc:
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: invalid package manifest"
            ) from exc
        return True

    metadata = document.get("metadata")
    files = spec.get("files")
    required_spec = {
        "profile",
        "config_content",
        "contains_verbatim_config",
        "source",
        "disclosure",
        "files",
    }
    required_entry = {
        "artifact_id",
        "command_id",
        "device",
        "path",
        "source_sha256",
        "export_sha256",
        "disclosure",
    }
    if (
        document.get("api_version") != API_VERSION
        or document.get("kind") != "EvidencePackageManifest"
        or not isinstance(metadata, Mapping)
        or not {"package_id", "created_at", "tool_version"} <= set(metadata)
        or not required_spec <= set(spec)
        or not isinstance(files, list)
        or any(
            not isinstance(entry, Mapping) or not required_entry <= set(entry)
            for entry in files
        )
    ):
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: invalid legacy package manifest"
        )
    return False


def create_evidence_package(
    *,
    collection_manifest: str | Path,
    raw_root: str | Path,
    profile: str,
    output_dir: str | Path,
    disclosure_preset: str | None = None,
    config_content: str = "sanitized",
    acknowledge_sensitive_config: bool = False,
    created_at: datetime,
) -> dict[str, Any]:
    """Create the initial legacy-collection portable package implementation."""
    if profile not in {"digital-twin", "ai-analysis"}:
        raise EvidencePackageError(
            f"EVIDENCE_INCOMPLETE: Collection Manifest source does not support profile: {profile}"
        )
    resolved_disclosure_preset = disclosure_preset or (
        "protected-preserve" if profile == "digital-twin" else "pseudonymized"
    )
    verbatim = config_content == "verbatim"
    if verbatim and (
        resolved_disclosure_preset != "protected-preserve"
        or not acknowledge_sensitive_config
    ):
        raise EvidencePackageError(
            "EVIDENCE_SENSITIVE_CONFIG_NOT_ACKNOWLEDGED: verbatim requires "
            "protected-preserve and --acknowledge-sensitive-config"
        )
    if not verbatim and resolved_disclosure_preset not in {
        "protected-preserve",
        "pseudonymized",
    }:
        raise EvidencePackageError(
            "EVIDENCE_INCOMPLETE: sanitized supports protected-preserve or "
            "pseudonymized disclosure"
        )
    if config_content not in {"sanitized", "verbatim"}:
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: exclude config is not supported for digital-twin")
    manifest_path = Path(collection_manifest)
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise EvidencePackageError(f"EVIDENCE_INVALID_SOURCE: {manifest_path}")
    source_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    validate_document(source_manifest, kind="CollectionManifest")
    raw_path = Path(raw_root)
    hosts = source_manifest["spec"]["hosts"]
    pseudonyms = _Pseudonyms(list(hosts))
    preserve_identity = resolved_disclosure_preset == "protected-preserve"
    exposed_names = (
        {hostname: hostname for hostname in hosts}
        if preserve_identity
        else pseudonyms.hosts
    )
    files: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    exported_commands: dict[str, dict[str, bytes]] = {}
    resolved_manifest = deepcopy(source_manifest)
    resolved_manifest["spec"]["hosts"] = {}
    required_by_host = {"running_config"} if profile == "digital-twin" else set()

    for hostname in sorted(hosts):
        host_record = hosts[hostname]
        exposed_hostname = exposed_names[hostname]
        resolved_host = (
            _protected_document(host_record)
            if preserve_identity
            else _sanitize_document(host_record, pseudonyms)
        )
        resolved_host["commands"] = {}
        successful_ids: set[str] = set()
        for command_id, command in sorted(host_record.get("commands", {}).items()):
            if command.get("status") != "success":
                continue
            source = _resolve_source_file(raw_path, str(command["file"]))
            expected = str(command["sha256"]).removeprefix("sha256:")
            source_bytes = source.read_bytes()
            actual = _sha256_bytes(source_bytes)
            if actual != expected:
                raise EvidencePackageError(f"EVIDENCE_INVALID_SOURCE: hash mismatch: {source}")
            successful_ids.add(command_id)
            command_bytes = _command_output_bytes(
                source_bytes,
                command,
                source=source,
            )
            try:
                source_text = command_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise EvidencePackageError(
                    f"EVIDENCE_SCAN_FAILED: command output is not UTF-8: {source}"
                ) from exc
            is_verbatim_config = verbatim and command_id == "running_config"
            relative_destination = (
                f"raw/{'verbatim' if is_verbatim_config else 'sanitized'}/"
                f"{exposed_hostname}/{command_id}.txt"
            )
            artifact_id = f"{exposed_hostname}:{command_id}"
            if is_verbatim_config:
                exported = command_bytes
                destination_category = "verbatim"
                disclosure = "verbatim"
                source_findings = scan_text(
                    source_text,
                    artifact_id=artifact_id,
                    path=relative_destination,
                    platform="nxos",
                    content_type=(
                        "running-config"
                        if command_id == "running_config"
                        else "cli-output"
                    ),
                )
            elif preserve_identity:
                protected, source_findings = sanitize_text(
                    source_text,
                    artifact_id=artifact_id,
                    path=relative_destination,
                    platform="nxos",
                    content_type=(
                        "running-config"
                        if command_id == "running_config"
                        else "cli-output"
                    ),
                )
                exported = protected.encode()
                destination_category = "sanitized"
                disclosure = "protected-preserve"
            else:
                protected, source_findings = sanitize_text(
                    source_text,
                    artifact_id=artifact_id,
                    path=relative_destination,
                    platform="nxos",
                    content_type=(
                        "running-config"
                        if command_id == "running_config"
                        else "cli-output"
                    ),
                )
                exported = pseudonyms.text(protected).encode()
                destination_category = "sanitized"
                disclosure = "sanitized"
            destination = (
                f"alred-evidence/raw/{destination_category}/"
                f"{exposed_hostname}/{command_id}.txt"
            )
            files[destination] = exported
            exported_commands.setdefault(exposed_hostname, {})[command_id] = exported
            resolved_command = (
                _protected_document(command)
                if preserve_identity
                else _sanitize_document(command, pseudonyms)
            )
            resolved_command["file"] = destination.removeprefix("alred-evidence/")
            resolved_command["sha256"] = _sha256_bytes(exported)
            source_range = {
                key: command[key]
                for key in _SOURCE_RANGE_FIELDS
                if key in command
            }
            for key in _SOURCE_RANGE_FIELDS:
                resolved_command.pop(key, None)
            resolved_host["commands"][command_id] = resolved_command
            entry = {
                "artifact_id": artifact_id,
                "command_id": command_id,
                "device": exposed_hostname,
                "path": destination.removeprefix("alred-evidence/"),
                "source_sha256": actual,
                "export_sha256": _sha256_bytes(exported),
                "disclosure": disclosure,
                "redaction_count": (
                    0
                    if is_verbatim_config
                    else sum(
                        finding.confidence == "high"
                        for finding in source_findings
                    )
                ),
            }
            if source_range:
                entry["source_range"] = source_range
            entries.append(entry)
        missing = required_by_host - successful_ids
        if missing:
            raise EvidencePackageError(
                f"EVIDENCE_INCOMPLETE: {hostname} missing {','.join(sorted(missing))}"
            )
        resolved_manifest["spec"]["hosts"][exposed_hostname] = resolved_host

    collection_id = str(source_manifest["metadata"]["collection_id"])
    package_id = f"{profile}-{created_at.strftime('%Y%m%dT%H%M%S%z')}-{collection_id}"
    inventory = {
        "all": {
            "hosts": {
                exposed_names[hostname]: {
                    "ansible_host": (
                        str(record.get("address"))
                        if preserve_identity and record.get("address")
                        else pseudonyms.address(str(record.get("address")))
                        if record.get("address") else None
                    ),
                    "device_type": "nxos",
                }
                for hostname, record in sorted(hosts.items())
            }
        }
    }
    files["alred-evidence/README.md"] = (
        "# alred Evidence Package\n\n"
        "Manifest-selected sanitized evidence for offline analysis and lab generation.\n"
    ).encode()
    if profile == "ai-analysis":
        files["alred-evidence/analysis/STRUCTURE.md"] = (
            "# Evidence structure\n\n"
            "- `package-manifest.yaml`: authoritative file selection, hashes, and disclosure mode.\n"
            "- `collection-manifest.yaml`: collection status and command provenance.\n"
            "- `inventory/hosts.resolved.yaml`: policy-transformed device inventory.\n"
            "- `raw/sanitized/<device>/<command-id>.txt`: successful command output.\n"
            "- `raw/verbatim/<device>/running_config.txt`: explicitly approved original config, when present.\n"
            "- `checksums.sha256`: integrity list for every other package member.\n"
        ).encode()
        files["alred-evidence/analysis/prompt.md"] = (
            "# Analysis request\n\n"
            "Analyze the included network evidence using `package-manifest.yaml` as the allowlist "
            "and `collection-manifest.yaml` as command provenance. Correlate findings across devices, "
            "distinguish observed facts from inferences, cite device and command IDs, and report missing "
            "or failed collection as limitations. Do not reproduce credentials or other secret values.\n"
        ).encode()
    files["alred-evidence/collection-manifest.yaml"] = yaml.safe_dump(
        resolved_manifest, sort_keys=False, allow_unicode=True
    ).encode()
    files["alred-evidence/inventory/hosts.resolved.yaml"] = yaml.safe_dump(
        inventory, sort_keys=False, allow_unicode=True
    ).encode()
    mappings = load_mappings(None)
    description_rules = load_description_rules(None)
    roles = load_roles(None)
    sites = load_sites(None)
    policy_resources = {
        "policy/mappings.resolved.yaml": mappings,
        "policy/description-rules.resolved.yaml": {
            "description_rules": description_rules,
        },
        "policy/roles.resolved.yaml": {"role_detection": roles},
        "policy/sites.resolved.yaml": {"site_detection": sites},
    }
    for relative, document in policy_resources.items():
        files[f"alred-evidence/{relative}"] = yaml.safe_dump(
            document, sort_keys=False, allow_unicode=True
        ).encode()

    inventory_map = load_inventory_map_from_list(load_inventory_data(inventory))
    lldp_records: list[dict[str, str]] = []
    description_records: list[dict[str, str]] = []
    description_ambiguities: list[dict[str, Any]] = []
    for hostname, command_outputs in sorted(exported_commands.items()):
        device_type = str(inventory_map.get(hostname, {}).get("device_type", "nxos"))
        if "lldp_neighbors_detail" in command_outputs:
            lldp_records.extend(
                parse_lldp_file(
                    command_outputs["lldp_neighbors_detail"].decode("utf-8"),
                    hostname,
                    device_type,
                    mappings,
                )
            )
        running_config = command_outputs.get("running_config")
        if running_config is not None:
            description_records.extend(
                build_description_records(
                    hostname,
                    running_config.decode("utf-8"),
                    mappings,
                    description_rules,
                    ambiguity_records=description_ambiguities,
                )
            )
    lldp_records = normalize_link_records(lldp_records, mappings, inventory_map)
    description_records = normalize_link_records(
        description_records, mappings, inventory_map
    )
    confirmed_links, candidate_links = merge_lldp_and_description_links(
        lldp_records, description_records
    )
    link_diagnostics = build_link_diagnostics(
        lldp_records=lldp_records,
        description_records=description_records,
        confirmed_links=confirmed_links,
        candidate_links=candidate_links,
        inventory_hosts=inventory_map,
        running_config_hosts={
            hostname
            for hostname, outputs in exported_commands.items()
            if "running_config" in outputs
        },
        lldp_hosts={
            hostname
            for hostname, outputs in exported_commands.items()
            if "lldp_neighbors_detail" in outputs
        },
        normalizer_version=__version__,
        source="evidence-package",
        policy_hashes={
            "mappings": canonical_sha256(mappings),
            "description_rules": canonical_sha256(description_rules),
        },
        description_ambiguities=description_ambiguities,
    )
    canonical_files = {
        "canonical/links_confirmed.csv": confirmed_links,
        "canonical/links_candidates.csv": candidate_links,
    }
    for relative, records in canonical_files.items():
        files[f"alred-evidence/{relative}"] = _links_csv_bytes(records)
    files["alred-evidence/canonical/link-diagnostics.yaml"] = yaml.safe_dump(
        link_diagnostics, sort_keys=False, allow_unicode=True
    ).encode()

    resource_ids = {
        "inventory/hosts.resolved.yaml": "resolved_inventory",
        "policy/mappings.resolved.yaml": "resolved_mappings",
        "policy/description-rules.resolved.yaml": "resolved_description_rules",
        "policy/roles.resolved.yaml": "resolved_roles",
        "policy/sites.resolved.yaml": "resolved_sites",
        "canonical/links_confirmed.csv": "canonical_links_confirmed",
        "canonical/links_candidates.csv": "canonical_links_candidates",
        "canonical/link-diagnostics.yaml": "canonical_link_diagnostics",
    }
    semantic_hashes = {
        "canonical/links_confirmed.csv": canonical_confirmed_links_sha256(
            confirmed_links
        ),
        "canonical/links_candidates.csv": canonical_links_sha256(candidate_links),
        "canonical/link-diagnostics.yaml": canonical_sha256(link_diagnostics),
    }
    resources = []
    for relative, resource_id in resource_ids.items():
        resource = {
            "resource_id": resource_id,
            "path": relative,
            "sha256": _sha256_bytes(files[f"alred-evidence/{relative}"]),
        }
        if relative in semantic_hashes:
            resource["semantic_sha256"] = semantic_hashes[relative]
            resource["semantic_version"] = (
                1 if relative == "canonical/link-diagnostics.yaml" else 2
            )
        resources.append(resource)
    scan_findings, files_scanned = _scan_package_members(files, entries)
    _enforce_scan_result(scan_findings, entries)
    scan_result = build_scan_result(
        scan_findings,
        files_scanned=files_scanned,
        acknowledged_sensitive=verbatim,
    )
    finding_counts: dict[str, int] = {}
    for finding in scan_findings:
        finding_counts[finding.artifact_id] = (
            finding_counts.get(finding.artifact_id, 0) + 1
        )
    for entry in entries:
        entry["secret_scan_finding_count"] = finding_counts.get(
            str(entry["artifact_id"]), 0
        )
    package_manifest = {
        "api_version": API_VERSION,
        "kind": "EvidencePackageManifest",
        "metadata": {
            "package_id": package_id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "tool_version": __version__,
        },
        "spec": {
            "profile": profile,
            "config_content": config_content,
            "contains_verbatim_config": verbatim,
            "source": {
                "type": "collection_manifest",
                "id": collection_id,
                "manifest_sha256": source_sha256(manifest_path),
            },
            "disclosure": {
                "preset": resolved_disclosure_preset,
                "policy_sha256": canonical_sha256(
                    {"preset": resolved_disclosure_preset}
                ),
            },
            "secret_scan": scan_result,
            "files": entries,
            "resources": resources,
            "analysis_limitations": (
                ["Verbatim running config may contain production secrets and identities."]
                if verbatim
                else [
                    "Device identities and addresses are retained; secret-bearing "
                    "material is removed."
                ]
                if preserve_identity
                else [
                    "Identifiers and addresses are pseudonymized; reverse mapping is not included."
                ]
            ),
        },
    }
    validate_document(package_manifest, kind="EvidencePackageManifest")
    files["alred-evidence/package-manifest.yaml"] = yaml.safe_dump(
        package_manifest, sort_keys=False, allow_unicode=True
    ).encode()
    checksums = "".join(
        f"{_sha256_bytes(content)}  {name.removeprefix('alred-evidence/')}\n"
        for name, content in sorted(files.items())
    )
    files["alred-evidence/checksums.sha256"] = checksums.encode()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    archive_suffix = ".sensitive.tar.gz" if verbatim else ".tar.gz"
    archive = output / f"{package_id}{archive_suffix}"
    if archive.exists():
        raise EvidencePackageError(f"evidence package already exists: {archive}")
    _deterministic_archive(archive, files)
    archive_sha256 = _sha256_bytes(archive.read_bytes())
    checksum = output / f"{package_id}.sha256"
    atomic_write_bytes(output, checksum, f"{archive_sha256}  {archive.name}\n".encode())
    return {
        "package_id": package_id,
        "archive": archive,
        "checksum": checksum,
        "archive_sha256": archive_sha256,
        "profile": profile,
        "secret_scan_status": scan_result["status"],
        "secret_scan_high_confidence": scan_result["high_confidence"],
        "secret_scan_low_confidence": scan_result["low_confidence"],
    }


def _read_archive(path: str | Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    archive_path = Path(path)
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not _safe_member_name(member.name) or member.name in files:
                    raise EvidencePackageError(f"EVIDENCE_UNSAFE_ARCHIVE: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {member.name}")
                files[member.name] = stream.read()
    except EvidencePackageError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INTEGRITY_FAILED: cannot read archive: {archive_path}"
        ) from exc
    manifest_name = "alred-evidence/package-manifest.yaml"
    checksum_name = "alred-evidence/checksums.sha256"
    if manifest_name not in files or checksum_name not in files:
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: package manifest or checksums missing")
    try:
        manifest = yaml.safe_load(files[manifest_name].decode("utf-8", errors="strict")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: invalid package manifest encoding or YAML"
        ) from exc
    _validate_package_manifest(manifest)
    expected: dict[str, str] = {}
    try:
        checksum_lines = files[checksum_name].decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: invalid checksum encoding"
        ) from exc
    for line in checksum_lines:
        digest, separator, relative = line.partition("  ")
        if not separator:
            raise EvidencePackageError("EVIDENCE_INTEGRITY_FAILED: invalid checksum line")
        expected[f"alred-evidence/{relative}"] = digest
    checked_names = set(files) - {checksum_name}
    if set(expected) != checked_names:
        raise EvidencePackageError("EVIDENCE_INTEGRITY_FAILED: checksum member set mismatch")
    for name in checked_names:
        if _sha256_bytes(files[name]) != expected[name]:
            raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {name}")
    declared_paths: set[str] = set()
    for entry in manifest["spec"]["files"]:
        relative = str(entry["path"])
        if relative in declared_paths:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: duplicate Manifest path: {relative}"
            )
        declared_paths.add(relative)
        member_name = f"alred-evidence/{relative}"
        if member_name not in files:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: Manifest member missing: {relative}"
            )
        if _sha256_bytes(files[member_name]) != entry["export_sha256"]:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: Manifest export hash mismatch: {relative}"
            )
    resource_paths: set[str] = set()
    for resource in manifest["spec"].get("resources", []):
        relative = str(resource["path"])
        if relative in resource_paths or relative in declared_paths:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: duplicate resource path: {relative}"
            )
        resource_paths.add(relative)
        member_name = f"alred-evidence/{relative}"
        if member_name not in files:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: resource member missing: {relative}"
            )
        if _sha256_bytes(files[member_name]) != resource["sha256"]:
            raise EvidencePackageError(
                f"EVIDENCE_INTEGRITY_FAILED: resource hash mismatch: {relative}"
            )
    return files, manifest


def _verify_declared_secret_scan(
    files: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    entries = list(manifest["spec"]["files"])
    findings, files_scanned = _scan_package_members(files, entries)
    _enforce_scan_result(findings, entries)
    declared_scan = manifest["spec"].get("secret_scan")
    calculated_scan = build_scan_result(
        findings,
        files_scanned=files_scanned,
        acknowledged_sensitive=bool(
            manifest["spec"]["contains_verbatim_config"]
        ),
    )
    if declared_scan is None:
        return calculated_scan, False, False
    if declared_scan.get("catalog_version") != CATALOG_VERSION:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: unsupported secret scan catalog version"
        )
    if declared_scan.get("catalog_sha256") != CATALOG_SHA256:
        return calculated_scan, True, False
    if calculated_scan != declared_scan:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: secret scan result mismatch"
        )
    return declared_scan, True, True


def verify_evidence_package(
    bundle: str | Path,
    *,
    checksum_file: str | Path | None = None,
) -> dict[str, Any]:
    """Verify an inferred or explicit external hash and every member checksum."""
    archive = Path(bundle)
    try:
        archive_sha256 = _sha256_bytes(archive.read_bytes())
    except OSError as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: cannot read archive: {archive}"
        ) from exc
    resolved_checksum: Path | None = None
    checksum_selection = "not-found"
    if checksum_file is not None:
        resolved_checksum = Path(checksum_file)
        checksum_selection = "explicit"
    else:
        archive_name = archive.name
        for suffix in (".sensitive.tar.gz", ".tar.gz"):
            if archive_name.endswith(suffix):
                candidate = archive.with_name(
                    f"{archive_name.removesuffix(suffix)}.sha256"
                )
                if candidate.exists():
                    resolved_checksum = candidate
                    checksum_selection = "inferred"
                break
    external_verified = False
    if resolved_checksum is not None:
        try:
            checksum_tokens = resolved_checksum.read_text(
                encoding="utf-8"
            ).split()
        except (OSError, UnicodeDecodeError) as exc:
            raise EvidencePackageError(
                f"EVIDENCE_INVALID_SOURCE: cannot read checksum: {resolved_checksum}"
            ) from exc
        if not checksum_tokens:
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: external checksum is empty"
            )
        expected = checksum_tokens[0]
        if archive_sha256 != expected:
            raise EvidencePackageError("EVIDENCE_INTEGRITY_FAILED: archive checksum mismatch")
        external_verified = True
    files, manifest = _read_archive(archive)
    declared_scan, scan_declared, catalog_match = _verify_declared_secret_scan(
        files, manifest
    )
    return {
        "verified": True,
        "external_checksum_verified": external_verified,
        "external_checksum_selection": checksum_selection,
        "external_checksum_file": (
            str(resolved_checksum) if resolved_checksum is not None else None
        ),
        "archive_sha256": archive_sha256,
        "package_id": manifest["metadata"]["package_id"],
        "created_at": manifest["metadata"]["created_at"],
        "profile": manifest["spec"]["profile"],
        "members": len(files),
        "secret_scan_status": declared_scan["status"],
        "secret_scan_high_confidence": declared_scan["high_confidence"],
        "secret_scan_low_confidence": declared_scan["low_confidence"],
        "secret_scan_declared": scan_declared,
        "secret_scan_catalog_match": catalog_match,
        "secret_scan_catalog_sha256": CATALOG_SHA256,
        "secret_scan_catalog_version": CATALOG_VERSION,
    }


def inspect_evidence_package(bundle: str | Path) -> dict[str, Any]:
    """Return trusted metadata only after internal integrity verification."""
    files, manifest = _read_archive(bundle)
    declared_scan, scan_declared, catalog_match = _verify_declared_secret_scan(
        files, manifest
    )
    return {
        "package_id": manifest["metadata"]["package_id"],
        "created_at": manifest["metadata"]["created_at"],
        "profile": manifest["spec"]["profile"],
        "config_content": manifest["spec"]["config_content"],
        "contains_verbatim_config": manifest["spec"]["contains_verbatim_config"],
        "members": len(files),
        "secret_scan_status": declared_scan["status"],
        "secret_scan_high_confidence": declared_scan["high_confidence"],
        "secret_scan_low_confidence": declared_scan["low_confidence"],
        "secret_scan_declared": scan_declared,
        "secret_scan_catalog_match": catalog_match,
        "secret_scan_catalog_sha256": CATALOG_SHA256,
        "secret_scan_catalog_version": CATALOG_VERSION,
        "analysis_limitations": manifest["spec"].get("analysis_limitations", []),
    }


def _evidence_archive_package_id(path: Path) -> tuple[str, bool] | None:
    for suffix, sensitive in (
        (".sensitive.tar.gz", True),
        (".tar.gz", False),
    ):
        if path.name.endswith(suffix):
            return path.name.removesuffix(suffix), sensitive
    return None


def _verified_evidence_package_records(
    output: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], set[Path]]:
    """Return verified package/checksum pairs and rejected archive candidates."""
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    managed_paths: set[Path] = set()
    for archive in sorted(output.glob("*.tar.gz")):
        identity = _evidence_archive_package_id(archive)
        if identity is None:
            continue
        filename_package_id, sensitive = identity
        checksum = output / f"{filename_package_id}.sha256"
        managed_paths.update({archive, checksum})
        if (
            not archive.is_file()
            or archive.is_symlink()
            or not checksum.is_file()
            or checksum.is_symlink()
        ):
            skipped.append(
                {
                    "archive": str(archive),
                    "reason": "archive/checksum pair is missing or unsafe",
                }
            )
            continue
        try:
            checksum_tokens = checksum.read_text(encoding="utf-8").split()
            if len(checksum_tokens) != 2 or checksum_tokens[1] != archive.name:
                raise EvidencePackageError(
                    "EVIDENCE_INTEGRITY_FAILED: external checksum filename mismatch"
                )
            verification = verify_evidence_package(
                archive,
                checksum_file=checksum,
            )
            if verification["package_id"] != filename_package_id:
                raise EvidencePackageError(
                    "EVIDENCE_INTEGRITY_FAILED: package ID does not match filename"
                )
            created_at = datetime.fromisoformat(str(verification["created_at"]))
            if created_at.tzinfo is None:
                raise EvidencePackageError(
                    "EVIDENCE_INTEGRITY_FAILED: package created_at has no timezone"
                )
        except (EvidencePackageError, OSError, UnicodeDecodeError, ValueError) as exc:
            skipped.append({"archive": str(archive), "reason": str(exc)})
            continue
        records.append(
            {
                "package_id": filename_package_id,
                "profile": str(verification["profile"]),
                "sensitive": sensitive,
                "created_at": created_at,
                "archive": archive,
                "checksum": checksum,
                "archive_sha256": str(verification["archive_sha256"]),
                "size": archive.stat().st_size + checksum.stat().st_size,
            }
        )
    return records, skipped, managed_paths


def resolve_latest_evidence_package(
    input_dir: str | Path = "evidence-packages",
) -> dict[str, Path]:
    """Resolve the newest fully verified package/checksum pair."""
    directory = Path(input_dir)
    if not directory.is_dir() or directory.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: evidence package directory is missing or unsafe: {directory}"
        )
    records, skipped, _managed_paths = _verified_evidence_package_records(directory)
    if skipped:
        first = skipped[0]
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: automatic bundle selection found an invalid "
            f"archive: {first['archive']}: {first['reason']}"
        )
    if not records:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: no verified Evidence Package found: {directory}"
        )
    selected = max(
        records,
        key=lambda item: (item["created_at"], item["package_id"]),
    )
    return {
        "archive": selected["archive"],
        "checksum": selected["checksum"],
    }


def prune_evidence_packages(
    output_dir: str | Path,
    *,
    keep_latest: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune verified package/checksum pairs by profile and sensitivity."""
    if keep_latest < 0:
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: keep_latest must be zero or greater"
        )
    output = Path(output_dir)
    if not output.exists():
        return {
            "keep_latest": keep_latest,
            "dry_run": dry_run,
            "verified": 0,
            "deleted": [],
            "skipped": [],
            "released_bytes": 0,
        }
    if not output.is_dir() or output.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe evidence output directory: {output}"
        )

    records, skipped, managed_paths = _verified_evidence_package_records(output)
    groups: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(
            (record["profile"], bool(record["sensitive"])), []
        ).append(record)

    for path in sorted(output.iterdir()):
        if path.name.startswith(".") or path in managed_paths:
            continue
        skipped.append(
            {
                "archive": str(path),
                "reason": "unrecognized file is not managed by Evidence retention",
            }
        )

    candidates: list[dict[str, Any]] = []
    if keep_latest > 0:
        for records in groups.values():
            records.sort(
                key=lambda item: (item["created_at"], item["package_id"]),
                reverse=True,
            )
            candidates.extend(records[keep_latest:])
    candidates.sort(key=lambda item: (item["created_at"], item["package_id"]))

    deleted: list[dict[str, Any]] = []
    released_bytes = 0
    for candidate in candidates:
        archive = candidate["archive"]
        checksum = candidate["checksum"]
        if not dry_run:
            verification = verify_evidence_package(
                archive,
                checksum_file=checksum,
            )
            if verification["archive_sha256"] != candidate["archive_sha256"]:
                raise EvidencePackageError(
                    f"EVIDENCE_INTEGRITY_FAILED: package changed before retention: {archive}"
                )
            try:
                archive.unlink()
                checksum.unlink()
            except OSError as exc:
                raise EvidencePackageError(
                    f"EVIDENCE_INVALID_SOURCE: package retention deletion failed: {archive}"
                ) from exc
        released_bytes += int(candidate["size"])
        deleted.append(
            {
                "package_id": candidate["package_id"],
                "profile": candidate["profile"],
                "sensitive": candidate["sensitive"],
                "created_at": candidate["created_at"].isoformat(),
                "archive": str(archive),
                "checksum": str(checksum),
                "bytes": candidate["size"],
            }
        )
    return {
        "keep_latest": keep_latest,
        "dry_run": dry_run,
        "verified": sum(len(records) for records in groups.values()),
        "deleted": deleted,
        "skipped": skipped,
        "released_bytes": released_bytes,
    }


def import_evidence_package(
    bundle: str | Path,
    *,
    output_dir: str | Path,
    checksum_file: str | Path | None = None,
    acknowledge_sensitive_config: bool = False,
    imported_at: datetime,
) -> dict[str, Any]:
    """Verify, safely materialize regular files, then atomically publish."""
    verification = verify_evidence_package(bundle, checksum_file=checksum_file)
    files, manifest = _read_archive(bundle)
    if (
        manifest.get("spec", {}).get("contains_verbatim_config") is True
        and not acknowledge_sensitive_config
    ):
        raise EvidencePackageError(
            "EVIDENCE_SENSITIVE_CONFIG_NOT_ACKNOWLEDGED: import requires "
            "--acknowledge-sensitive-config"
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    target = output / verification["package_id"]
    if target.exists():
        raise EvidencePackageError(f"import destination already exists: {target}")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=output))
    try:
        staging.chmod(0o700)
        for name, content in files.items():
            relative = PurePosixPath(name).relative_to("alred-evidence")
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.chmod(0o700)
            destination.write_bytes(content)
            destination.chmod(0o600)
        record = {
            "api_version": API_VERSION,
            "kind": "EvidenceImportRecord",
            "metadata": {
                "package_id": verification["package_id"],
                "imported_at": imported_at.isoformat(timespec="seconds"),
                "tool_version": __version__,
            },
            "spec": {
                "archive_sha256": verification["archive_sha256"],
                "external_checksum_verified": verification["external_checksum_verified"],
                "external_checksum_selection": verification[
                    "external_checksum_selection"
                ],
                "package_manifest_sha256": _sha256_bytes(files["alred-evidence/package-manifest.yaml"]),
                "secret_scan_catalog_match": verification[
                    "secret_scan_catalog_match"
                ],
                "secret_scan_catalog_sha256": verification[
                    "secret_scan_catalog_sha256"
                ],
                "secret_scan_catalog_version": verification[
                    "secret_scan_catalog_version"
                ],
            },
        }
        (staging / "import-record.yaml").write_text(
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        (staging / "import-record.yaml").chmod(0o600)
        os.replace(staging, target)
        atomic_update_relative_directory_symlink(
            output,
            output / "latest",
            target,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "package_id": verification["package_id"],
        "import_dir": target,
        "external_checksum_verified": verification["external_checksum_verified"],
        "external_checksum_selection": verification["external_checksum_selection"],
        "external_checksum_file": verification["external_checksum_file"],
        "secret_scan_catalog_match": verification["secret_scan_catalog_match"],
        "secret_scan_catalog_sha256": verification[
            "secret_scan_catalog_sha256"
        ],
        "secret_scan_catalog_version": verification[
            "secret_scan_catalog_version"
        ],
    }


def _inspect_imported_evidence_directory(import_dir: Path) -> dict[str, Any]:
    """Verify a published import directory and return retention metadata."""
    if not import_dir.is_dir() or import_dir.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe imported Evidence directory: {import_dir}"
        )
    manifest_path = import_dir / "package-manifest.yaml"
    checksums_path = import_dir / "checksums.sha256"
    record_path = import_dir / "import-record.yaml"
    for required in (manifest_path, checksums_path, record_path):
        if not required.is_file() or required.is_symlink():
            raise EvidencePackageError(
                f"EVIDENCE_INCOMPLETE: imported Evidence file missing or unsafe: {required}"
            )
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = yaml.safe_load(manifest_bytes.decode("utf-8", errors="strict")) or {}
        record = yaml.safe_load(record_path.read_text(encoding="utf-8")) or {}
        checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INTEGRITY_FAILED: invalid imported Evidence metadata: {import_dir}"
        ) from exc
    _validate_package_manifest(manifest)
    package_id = str(manifest["metadata"]["package_id"])
    if package_id != import_dir.name:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: imported package ID does not match directory name"
        )
    if record.get("kind") != "EvidenceImportRecord":
        raise EvidencePackageError("EVIDENCE_INTEGRITY_FAILED: invalid import record kind")
    record_metadata = record.get("metadata", {})
    record_spec = record.get("spec", {})
    if record_metadata.get("package_id") != package_id:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: import record package ID mismatch"
        )
    if record_spec.get("package_manifest_sha256") != _sha256_bytes(manifest_bytes):
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: imported package Manifest hash mismatch"
        )
    try:
        imported_at = datetime.fromisoformat(str(record_metadata["imported_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: invalid import timestamp"
        ) from exc
    if imported_at.tzinfo is None:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: import timestamp has no timezone"
        )

    expected: dict[Path, str] = {}
    for line in checksum_lines:
        digest, separator, relative_text = line.partition("  ")
        relative = PurePosixPath(relative_text)
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
        ):
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: invalid imported checksum line"
            )
        path = import_dir.joinpath(*relative.parts)
        if path in expected:
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: duplicate imported checksum path"
            )
        expected[path] = digest

    actual: set[Path] = set()
    try:
        for path in import_dir.rglob("*"):
            if path.is_symlink():
                raise EvidencePackageError(
                    f"EVIDENCE_INVALID_SOURCE: imported Evidence contains symlink: {path}"
                )
            if path.is_file():
                actual.add(path)
            elif not path.is_dir():
                raise EvidencePackageError(
                    f"EVIDENCE_INVALID_SOURCE: imported Evidence contains unsafe entry: {path}"
                )
    except OSError as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: cannot inspect imported Evidence: {import_dir}"
        ) from exc
    allowed = set(expected) | {checksums_path, record_path}
    if actual != allowed:
        raise EvidencePackageError(
            "EVIDENCE_INTEGRITY_FAILED: imported Evidence member set mismatch"
        )
    try:
        for path, digest in expected.items():
            if (
                not path.is_file()
                or path.is_symlink()
                or _sha256_bytes(path.read_bytes()) != digest
            ):
                raise EvidencePackageError(
                    f"EVIDENCE_INTEGRITY_FAILED: imported Evidence member hash mismatch: {path}"
                )
        size = sum(path.stat().st_size for path in actual)
    except OSError as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: cannot verify imported Evidence: {import_dir}"
        ) from exc
    return {
        "package_id": package_id,
        "profile": str(manifest["spec"]["profile"]),
        "sensitive": bool(manifest["spec"]["contains_verbatim_config"]),
        "imported_at": imported_at,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "size": size,
    }


def prune_imported_evidence(
    output_dir: str | Path,
    *,
    keep_latest: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune verified imported directories by profile and sensitivity."""
    if keep_latest < 0:
        raise EvidencePackageError(
            "EVIDENCE_INVALID_SOURCE: keep_latest must be zero or greater"
        )
    output = Path(output_dir)
    if not output.exists():
        return {
            "keep_latest": keep_latest,
            "dry_run": dry_run,
            "verified": 0,
            "deleted": [],
            "skipped": [],
            "released_bytes": 0,
        }
    if not output.is_dir() or output.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe Evidence import root: {output}"
        )

    latest_target: Path | None = None
    latest = output / "latest"
    if latest.is_symlink():
        try:
            resolved = latest.resolve(strict=True)
            if resolved.parent != output.resolve() or not resolved.is_dir():
                raise ValueError
            latest_target = resolved
        except (OSError, ValueError):
            latest_target = None

    groups: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    skipped: list[dict[str, str]] = []
    if latest.exists() and not latest.is_symlink():
        skipped.append(
            {
                "import_dir": str(latest),
                "reason": "latest is not a managed symbolic link",
            }
        )
    elif latest.is_symlink() and latest_target is None:
        skipped.append(
            {
                "import_dir": str(latest),
                "reason": "latest symbolic link is broken or unsafe",
            }
        )
    for path in sorted(output.iterdir()):
        if path.name.startswith(".") or path == latest:
            continue
        try:
            metadata = _inspect_imported_evidence_directory(path)
        except EvidencePackageError as exc:
            skipped.append({"import_dir": str(path), "reason": str(exc)})
            continue
        metadata["import_dir"] = path
        metadata["protected"] = latest_target is not None and path.resolve() == latest_target
        groups.setdefault((metadata["profile"], metadata["sensitive"]), []).append(metadata)

    candidates: list[dict[str, Any]] = []
    if keep_latest > 0:
        for records in groups.values():
            records.sort(
                key=lambda item: (item["imported_at"], item["package_id"]),
                reverse=True,
            )
            for record in records[keep_latest:]:
                if record["protected"]:
                    skipped.append(
                        {
                            "import_dir": str(record["import_dir"]),
                            "reason": "latest import target is protected",
                        }
                    )
                else:
                    candidates.append(record)
    candidates.sort(key=lambda item: (item["imported_at"], item["package_id"]))

    deleted: list[dict[str, Any]] = []
    released_bytes = 0
    for candidate in candidates:
        import_dir = candidate["import_dir"]
        if not dry_run:
            current = _inspect_imported_evidence_directory(import_dir)
            if current["manifest_sha256"] != candidate["manifest_sha256"]:
                raise EvidencePackageError(
                    f"EVIDENCE_INTEGRITY_FAILED: import changed before retention: {import_dir}"
                )
            try:
                shutil.rmtree(import_dir)
            except OSError as exc:
                raise EvidencePackageError(
                    f"EVIDENCE_INVALID_SOURCE: import retention deletion failed: {import_dir}"
                ) from exc
        released_bytes += int(candidate["size"])
        deleted.append(
            {
                "package_id": candidate["package_id"],
                "profile": candidate["profile"],
                "sensitive": candidate["sensitive"],
                "imported_at": candidate["imported_at"].isoformat(),
                "import_dir": str(import_dir),
                "bytes": candidate["size"],
            }
        )
    return {
        "keep_latest": keep_latest,
        "dry_run": dry_run,
        "verified": sum(len(records) for records in groups.values()),
        "deleted": deleted,
        "skipped": skipped,
        "released_bytes": released_bytes,
    }


def _resolve_import_directory_path(import_dir: str | Path) -> Path:
    """Resolve only the managed latest symlink and reject arbitrary links."""
    candidate = Path(import_dir)
    if not candidate.is_symlink():
        if not candidate.is_dir():
            raise EvidencePackageError(
                f"EVIDENCE_INVALID_SOURCE: import directory: {candidate}"
            )
        return candidate
    if candidate.name != "latest":
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: import directory symlink: {candidate}"
        )
    try:
        parent = candidate.parent.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(parent)
    except (OSError, ValueError) as exc:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe latest import link: {candidate}"
        ) from exc
    if not resolved.is_dir() or resolved.parent != parent:
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: unsafe latest import target: {resolved}"
        )
    import_record = resolved / "import-record.yaml"
    if not import_record.is_file() or import_record.is_symlink():
        raise EvidencePackageError(
            f"EVIDENCE_INCOMPLETE: latest import has no import record: {resolved}"
        )
    return resolved


def resolve_imported_digital_twin(
    import_dir: str | Path,
    *,
    acknowledge_sensitive_config: bool = False,
) -> tuple[Path, dict[str, Path], dict[str, Any]]:
    """Resolve inventory and running configs strictly from an imported Manifest."""
    root = _resolve_import_directory_path(import_dir)
    manifest_path = root / "package-manifest.yaml"
    inventory_path = root / "inventory" / "hosts.resolved.yaml"
    if not manifest_path.is_file() or not inventory_path.is_file():
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: imported Manifest or inventory missing")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    current_manifest = _validate_package_manifest(manifest)
    if manifest.get("spec", {}).get("profile") != "digital-twin":
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: package is not digital-twin")
    config_content = manifest.get("spec", {}).get("config_content")
    if config_content not in {"sanitized", "verbatim"}:
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: package has no usable config")
    if config_content == "verbatim" and not acknowledge_sensitive_config:
        raise EvidencePackageError(
            "EVIDENCE_SENSITIVE_CONFIG_NOT_ACKNOWLEDGED: verbatim transform requires "
            "--acknowledge-sensitive-config"
        )
    if (
        current_manifest
        and manifest["spec"]["secret_scan"]["catalog_sha256"]
        != CATALOG_SHA256
    ):
        record_path = root / "import-record.yaml"
        try:
            import_record = yaml.safe_load(
                record_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: invalid import record"
            ) from exc
        record_spec = import_record.get("spec", {})
        if (
            record_spec.get("secret_scan_catalog_match") is not False
            or record_spec.get("secret_scan_catalog_sha256") != CATALOG_SHA256
            or record_spec.get("secret_scan_catalog_version") != CATALOG_VERSION
        ):
            raise EvidencePackageError(
                "EVIDENCE_INTEGRITY_FAILED: old secret scan catalog was not "
                "revalidated during import"
            )
    resolved: dict[str, Path] = {}
    for entry in manifest.get("spec", {}).get("files", []):
        if entry.get("command_id") != "running_config":
            continue
        hostname = str(entry.get("device", ""))
        relative = PurePosixPath(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise EvidencePackageError(f"EVIDENCE_UNSAFE_ARCHIVE: {relative}")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise EvidencePackageError(f"EVIDENCE_INCOMPLETE: {relative}")
        content = path.read_bytes()
        expected = str(entry.get("export_sha256", "")).removeprefix("sha256:")
        if _sha256_bytes(content) != expected:
            raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {relative}")
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise EvidencePackageError(
                f"EVIDENCE_SCAN_FAILED: imported config is not UTF-8: {relative}"
            ) from exc
        findings = scan_text(
            text,
            artifact_id=str(entry["artifact_id"]),
            path=str(relative),
            platform="nxos",
            content_type="running-config",
        )
        if entry.get("disclosure") != "verbatim":
            high = [item for item in findings if item.confidence == "high"]
            if high:
                first = high[0]
                raise EvidencePackageError(
                    "EVIDENCE_BLOCKED_SECRET: high-confidence finding "
                    f"{first.rule_id} at {relative}:{first.line}"
                )
        if hostname in resolved:
            raise EvidencePackageError(f"EVIDENCE_INCOMPLETE: duplicate running config: {hostname}")
        resolved[hostname] = path
    inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
    inventory_hosts = inventory.get("all", {}).get("hosts", {})
    if not isinstance(inventory_hosts, Mapping) or set(inventory_hosts) != set(resolved):
        raise EvidencePackageError(
            "EVIDENCE_INCOMPLETE: inventory and running config device sets differ"
        )
    return inventory_path, resolved, manifest


def resolve_imported_command_paths(
    import_dir: str | Path,
    command_ids: set[str],
) -> dict[str, dict[str, Path]]:
    """Resolve verified command files from an imported Digital Twin package."""
    root = _resolve_import_directory_path(import_dir)
    manifest_path = root / "package-manifest.yaml"
    if not manifest_path.is_file():
        raise EvidencePackageError(
            f"EVIDENCE_INVALID_SOURCE: import directory: {root}"
        )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    _validate_package_manifest(manifest)
    if manifest.get("spec", {}).get("profile") != "digital-twin":
        raise EvidencePackageError("EVIDENCE_INCOMPLETE: package is not digital-twin")
    resolved = {command_id: {} for command_id in sorted(command_ids)}
    for entry in manifest.get("spec", {}).get("files", []):
        command_id = str(entry.get("command_id", ""))
        if command_id not in command_ids:
            continue
        relative = PurePosixPath(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise EvidencePackageError(f"EVIDENCE_UNSAFE_ARCHIVE: {relative}")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise EvidencePackageError(f"EVIDENCE_INCOMPLETE: {relative}")
        if _sha256_bytes(path.read_bytes()) != str(entry.get("export_sha256", "")):
            raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {relative}")
        resolved[command_id][str(entry.get("device", ""))] = path
    return resolved


def resolve_imported_evidence_links(
    import_dir: str | Path,
    *,
    acknowledge_sensitive_config: bool = False,
) -> tuple[
    Path,
    dict[str, Path],
    dict[str, Path],
    Path,
    Path,
    Path,
    Path,
    dict[str, Any],
]:
    """Resolve all Manifest-pinned inputs needed to regenerate canonical links."""
    root = _resolve_import_directory_path(import_dir)
    inventory_path, configs, manifest = resolve_imported_digital_twin(
        root,
        acknowledge_sensitive_config=acknowledge_sensitive_config,
    )
    resource_by_id = {
        str(resource["resource_id"]): resource
        for resource in manifest.get("spec", {}).get("resources", [])
    }
    required = {
        "resolved_mappings",
        "resolved_description_rules",
        "canonical_links_confirmed",
        "canonical_links_candidates",
    }
    missing = required - set(resource_by_id)
    if missing:
        raise EvidencePackageError(
            f"EVIDENCE_INCOMPLETE: missing link resources: {','.join(sorted(missing))}"
        )

    def resource_path(resource_id: str) -> Path:
        resource = resource_by_id[resource_id]
        relative = PurePosixPath(str(resource["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise EvidencePackageError(f"EVIDENCE_UNSAFE_ARCHIVE: {relative}")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise EvidencePackageError(f"EVIDENCE_INCOMPLETE: {relative}")
        if _sha256_bytes(path.read_bytes()) != resource["sha256"]:
            raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {relative}")
        return path

    lldp: dict[str, Path] = {}
    for entry in manifest.get("spec", {}).get("files", []):
        if entry.get("command_id") != "lldp_neighbors_detail":
            continue
        relative = PurePosixPath(str(entry["path"]))
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise EvidencePackageError(f"EVIDENCE_INCOMPLETE: {relative}")
        if _sha256_bytes(path.read_bytes()) != entry["export_sha256"]:
            raise EvidencePackageError(f"EVIDENCE_INTEGRITY_FAILED: {relative}")
        lldp[str(entry["device"])] = path
    return (
        inventory_path,
        configs,
        lldp,
        resource_path("resolved_mappings"),
        resource_path("resolved_description_rules"),
        resource_path("canonical_links_confirmed"),
        resource_path("canonical_links_candidates"),
        manifest,
    )
