"""Safe, manifest-pinned support bundle creation and verification."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .operation import atomic_write_bytes
from .schema import (
    API_VERSION,
    canonical_sha256,
    validate_document,
)


class SupportBundleError(ValueError):
    """Raised when a support bundle cannot be created safely."""

    code = "BUNDLE_CREATE_FAILED"


TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".cfg",
    ".conf",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".csv",
}
FORBIDDEN_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    "credentials.yaml",
}
DEFAULT_MASK_KEYS = ("password", "secret", "community", "token")
PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)
IP_ADDRESS = re.compile(
    r"(?<![0-9A-Fa-f:.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?"
)
HOME_PATH = re.compile(r"(?<!\S)/(?:home|Users)/[^\s\"']+")
VRF_DECLARATION = re.compile(
    r"(?im)^\s*(?:vrf\s+(?:context|member)|vrf)\s+([A-Za-z0-9_.:-]+)\s*$"
)


@dataclass(frozen=True)
class BundleSource:
    """One source artifact, optionally sliced from manifest-pinned raw."""

    source: Path
    destination: PurePosixPath
    phase: str
    devices: tuple[str, ...]
    source_sha256: str
    content: bytes


@dataclass(frozen=True)
class RedactionPolicy:
    """Resolved built-in and site-specific redaction behavior."""

    document: Mapping[str, Any]
    mask_keys: tuple[str, ...]
    patterns: tuple[tuple[str, re.Pattern[str], str], ...]
    pseudonymize_hostnames: bool
    pseudonymize_ips: bool
    pseudonymize_vrfs: bool


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_safe_relative(path: PurePosixPath) -> bool:
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and all(part not in {"", "."} for part in path.parts)
    )


def _phase_roots(
    phase: str,
    *,
    include_generated_config: bool = True,
    include_rollback_config: bool = True,
) -> tuple[str, ...]:
    common = (
        "metadata.yaml",
        "health/resolved-profiles.yaml",
        "health/execution-context.yaml",
    )
    generated = ("generated-config",) if include_generated_config else ()
    rollback_config = ("rollback-config",) if include_rollback_config else ()
    if phase == "before":
        return (*common, "health/before", "overlay")
    if phase == "after":
        return (
            *common,
            "health/before",
            "health/after",
            "health/report",
            "plan",
            *generated,
            "apply",
            "qualification",
            "overlay",
        )
    if phase == "rollback":
        return (
            *common,
            "health/before",
            "plan",
            *rollback_config,
            "rollback",
            "rollback-health",
            "qualification",
            "overlay",
        )
    if phase == "all":
        return (
            *common,
            "health",
            "plan",
            *generated,
            *rollback_config,
            "apply",
            "rollback",
            "rollback-health",
            "qualification",
            "overlay",
        )
    raise SupportBundleError(f"unsupported phase: {phase}")


def _artifact_phase(relative: PurePosixPath) -> str:
    parts = relative.parts
    if len(parts) >= 2 and parts[:2] == ("health", "before"):
        return "before"
    if len(parts) >= 2 and parts[:2] == ("health", "after"):
        return "after"
    if len(parts) >= 2 and parts[:2] == ("health", "report"):
        return "after"
    if parts and parts[0] in {"generated-config", "apply"}:
        return "after"
    if parts and parts[0] in {
        "rollback-config",
        "rollback",
        "rollback-health",
    }:
        return "rollback"
    if len(parts) >= 2 and parts[:2] == ("qualification", "apply"):
        return "after"
    if len(parts) >= 2 and parts[0] == "qualification":
        return "rollback"
    return "common"


def _safe_source(path: Path, *, operation_root: Path | None = None) -> Path:
    if path.is_symlink():
        raise SupportBundleError(
            f"BUNDLE_INVALID_SOURCE: symlink is forbidden: {path}"
        )
    if not path.is_file():
        raise SupportBundleError(
            f"BUNDLE_INCOMPLETE: source file is missing: {path}"
        )
    if path.name in FORBIDDEN_NAMES or path.suffix.lower() not in TEXT_SUFFIXES:
        raise SupportBundleError(
            f"BUNDLE_INVALID_SOURCE: forbidden source type: {path.name}"
        )
    resolved = path.resolve()
    if operation_root is not None and not resolved.is_relative_to(operation_root):
        raise SupportBundleError(
            f"BUNDLE_INVALID_SOURCE: path escapes operation: {path}"
        )
    return resolved


def _path_devices(
    relative: PurePosixPath,
    hostnames: Iterable[str],
) -> tuple[str, ...]:
    value = relative.as_posix()
    matched = []
    for hostname in sorted(set(hostnames)):
        pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(hostname)}(?![A-Za-z0-9_.-])"
        if hostname in relative.parts or re.search(pattern, value):
            matched.append(hostname)
    return tuple(matched)


def _load_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        document = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.suffix.lower() == ".json"
            else yaml.safe_load(path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return document if isinstance(document, Mapping) else None


def _hostnames_from_files(
    files: Iterable[tuple[Path, PurePosixPath]],
) -> set[str]:
    hosts: set[str] = set()
    for source, _destination in files:
        if source.name not in {
            "collection-manifest.yaml",
            "snapshot.json",
        }:
            continue
        document = _load_mapping(source)
        if document is None:
            continue
        mapping = document.get("hosts") or document.get("spec", {}).get("hosts") or {}
        if isinstance(mapping, Mapping):
            hosts.update(str(value) for value in mapping)
    return hosts


def select_operation_files(
    operation_root: str | Path,
    *,
    phase: str,
    include_generated_config: bool = True,
    include_rollback_config: bool = True,
) -> list[tuple[Path, PurePosixPath]]:
    """Select regular allowlisted operation artifacts without following links."""
    root = Path(operation_root).resolve()
    selected: dict[str, tuple[Path, PurePosixPath]] = {}
    for relative_name in _phase_roots(
        phase,
        include_generated_config=include_generated_config,
        include_rollback_config=include_rollback_config,
    ):
        relative = PurePosixPath(relative_name)
        candidate = root.joinpath(*relative.parts)
        if not candidate.exists():
            continue
        candidates: Iterable[Path] = (
            [candidate] if candidate.is_file() else candidate.rglob("*")
        )
        for source in candidates:
            if source.is_symlink():
                raise SupportBundleError(
                    f"BUNDLE_INVALID_SOURCE: symlink is forbidden: {source}"
                )
            if not source.is_file():
                continue
            resolved = source.resolve()
            if not resolved.is_relative_to(root):
                raise SupportBundleError(
                    f"BUNDLE_INVALID_SOURCE: path escapes operation: {source}"
                )
            rel = PurePosixPath(resolved.relative_to(root).as_posix())
            if (
                source.name in FORBIDDEN_NAMES
                or source.suffix.lower() not in TEXT_SUFFIXES
                or any(part.startswith(".") for part in rel.parts)
            ):
                continue
            # Raw content is selected exclusively through Collection Manifest.
            if "raw" in rel.parts:
                continue
            bundle_path = PurePosixPath("support-bundle") / rel
            selected[str(bundle_path)] = (source, bundle_path)
    return [selected[key] for key in sorted(selected)]


def _manifest_raw_sources(
    selected_files: Sequence[tuple[Path, PurePosixPath]],
    *,
    change_id: str,
    requested_devices: set[str] | None,
    include_raw_logging: bool,
) -> list[BundleSource]:
    sources: dict[str, BundleSource] = {}
    for manifest_path, _destination in selected_files:
        if manifest_path.name != "collection-manifest.yaml":
            continue
        manifest = _load_mapping(manifest_path)
        if manifest is None:
            raise SupportBundleError(
                f"BUNDLE_INCOMPLETE: invalid Collection Manifest: {manifest_path}"
            )
        validate_document(
            manifest,
            kind="CollectionManifest",
            allow_unknown_fields=True,
        )
        metadata = manifest["metadata"]
        if metadata["change_id"] != change_id:
            raise SupportBundleError(
                "BUNDLE_INVALID_SOURCE: Collection Manifest change-id mismatch"
            )
        source_phase = str(metadata["phase"])
        for hostname, host in sorted(manifest["spec"]["hosts"].items()):
            if requested_devices is not None and hostname not in requested_devices:
                continue
            for command_id, record in sorted(host["commands"].items()):
                if record["status"] != "success":
                    continue
                normalized = str(
                    record.get("normalized_command")
                    or record.get("command")
                    or ""
                ).lower()
                if not include_raw_logging and normalized.startswith("show logging"):
                    continue
                raw_path = _safe_source(Path(record["file"]))
                actual_hash = _sha256_file(raw_path).removeprefix("sha256:")
                if actual_hash != record["sha256"]:
                    raise SupportBundleError(
                        "BUNDLE_INVALID_SOURCE: manifest source hash mismatch "
                        f"for {hostname}/{command_id}"
                    )
                raw = raw_path.read_bytes()
                try:
                    lines = raw.decode("utf-8").splitlines()
                except UnicodeDecodeError as exc:
                    raise SupportBundleError(
                        f"BUNDLE_INVALID_SOURCE: non-text raw source: {raw_path}"
                    ) from exc
                start = record.get("start_line")
                end = record.get("end_line")
                if start is not None or end is not None:
                    if not isinstance(start, int) or not isinstance(end, int):
                        raise SupportBundleError(
                            "BUNDLE_INVALID_SOURCE: incomplete raw line range"
                        )
                    if start < 1 or end < start or end > len(lines):
                        raise SupportBundleError(
                            "BUNDLE_INVALID_SOURCE: raw line range is outside source"
                        )
                    raw = ("\n".join(lines[start - 1 : end]) + "\n").encode()
                suffix = raw_path.suffix.lower()
                destination = PurePosixPath(
                    "support-bundle",
                    "raw",
                    source_phase,
                    hostname,
                    f"{command_id}{suffix}",
                )
                key = destination.as_posix()
                candidate = BundleSource(
                    source=raw_path,
                    destination=destination,
                    phase=source_phase,
                    devices=(hostname,),
                    source_sha256="sha256:" + actual_hash,
                    content=raw,
                )
                previous = sources.get(key)
                if previous is not None and previous.content != candidate.content:
                    raise SupportBundleError(
                        f"BUNDLE_INVALID_SOURCE: raw destination collision: {key}"
                    )
                sources[key] = candidate
    return [sources[key] for key in sorted(sources)]


def _all_sources(
    operation_root: Path,
    *,
    change_id: str,
    phase: str,
    requested_devices: set[str] | None,
    include_generated_config: bool,
    include_rollback_config: bool,
    include_raw_logging: bool,
) -> tuple[list[BundleSource], set[str]]:
    selected = select_operation_files(
        operation_root,
        phase=phase,
        include_generated_config=include_generated_config,
        include_rollback_config=include_rollback_config,
    )
    if not any(destination.name == "metadata.yaml" for _, destination in selected):
        raise SupportBundleError("BUNDLE_INCOMPLETE: metadata.yaml is missing")
    known_devices = _hostnames_from_files(selected)
    if requested_devices is not None:
        unknown = sorted(requested_devices - known_devices)
        if unknown:
            raise SupportBundleError(
                "BUNDLE_INVALID_SOURCE: unknown requested devices: "
                + ", ".join(unknown)
            )
    sources: list[BundleSource] = []
    for source, destination in selected:
        rel = PurePosixPath(source.resolve().relative_to(operation_root).as_posix())
        devices = _path_devices(rel, known_devices)
        if (
            requested_devices is not None
            and devices
            and not requested_devices.intersection(devices)
        ):
            continue
        sources.append(
            BundleSource(
                source=source,
                destination=destination,
                phase=_artifact_phase(rel),
                devices=devices,
                source_sha256=_sha256_file(source),
                content=source.read_bytes(),
            )
        )
    sources.extend(
        _manifest_raw_sources(
            selected,
            change_id=change_id,
            requested_devices=requested_devices,
            include_raw_logging=include_raw_logging,
        )
    )
    return sources, known_devices


def _default_policy_document() -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "kind": "SupportBundleRedactionPolicy",
        "metadata": {"name": "builtin"},
        "spec": {
            "mask_keys": list(DEFAULT_MASK_KEYS),
            "mask_patterns": [],
            "pseudonymize": {
                "hostnames": True,
                "ip_addresses": True,
                "vrf_names": True,
            },
            "preserve": ["vni", "vlan", "interface_name", "command_name"],
        },
    }


def load_redaction_policy(path: str | Path | None) -> RedactionPolicy:
    """Load and validate a redaction policy, or return the built-in policy."""
    document = _default_policy_document()
    if path is not None:
        policy_path = _safe_source(Path(path))
        loaded = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise SupportBundleError("invalid redaction policy document")
        document = dict(loaded)
    validate_document(document, kind="SupportBundleRedactionPolicy")
    spec = document["spec"]
    patterns = []
    for item in spec.get("mask_patterns", []):
        try:
            compiled = re.compile(item["pattern"], re.MULTILINE)
        except re.error as exc:
            raise SupportBundleError(
                f"invalid redaction pattern {item['id']}: {exc}"
            ) from exc
        patterns.append(
            (
                item["id"],
                compiled,
                item.get("replacement", "***REDACTED***"),
            )
        )
    pseudonymize = spec["pseudonymize"]
    return RedactionPolicy(
        document=document,
        mask_keys=tuple(spec["mask_keys"]),
        patterns=tuple(patterns),
        pseudonymize_hostnames=bool(pseudonymize["hostnames"]),
        pseudonymize_ips=bool(pseudonymize["ip_addresses"]),
        pseudonymize_vrfs=bool(pseudonymize["vrf_names"]),
    )


class _Pseudonyms:
    def __init__(
        self,
        hostnames: Iterable[str],
        vrf_names: Iterable[str],
        *,
        hostnames_enabled: bool,
        ips_enabled: bool,
        vrfs_enabled: bool,
    ):
        self.hostnames = (
            {
                value: f"DEVICE-{index:03d}"
                for index, value in enumerate(sorted(set(hostnames)), start=1)
                if value
            }
            if hostnames_enabled
            else {}
        )
        self.vrfs = (
            {
                value: f"VRF-{index:03d}"
                for index, value in enumerate(sorted(set(vrf_names)), start=1)
                if value and value.lower() not in {"default", "management"}
            }
            if vrfs_enabled
            else {}
        )
        self.ips_enabled = ips_enabled
        self.ips: dict[str, str] = {}

    @staticmethod
    def _substitute_tokens(text: str, values: Mapping[str, str]) -> str:
        for source, replacement in values.items():
            text = re.sub(
                rf"(?<![A-Za-z0-9_.:-]){re.escape(source)}"
                rf"(?![A-Za-z0-9_.:-])",
                replacement,
                text,
            )
        return text

    def redact(self, text: str, policy: RedactionPolicy) -> str:
        text = PRIVATE_KEY.sub("***REDACTED_PRIVATE_KEY***", text)
        if policy.mask_keys:
            keys = "|".join(re.escape(value) for value in policy.mask_keys)
            secret_line = re.compile(
                rf"(?im)^(\s*(?:{keys})\s+)(\S+)(.*)$"
            )
            text = secret_line.sub(r"\1***REDACTED***\3", text)
        for _rule_id, pattern, replacement in policy.patterns:
            text = pattern.sub(replacement, text)
        text = HOME_PATH.sub("PATH-REDACTED", text)
        text = self._substitute_tokens(text, self.hostnames)
        text = self._substitute_tokens(text, self.vrfs)
        if not self.ips_enabled:
            return text

        def replace_ip(match: re.Match[str]) -> str:
            value = match.group(0)
            address, separator, prefix = value.partition("/")
            if address not in self.ips:
                self.ips[address] = f"IP-{len(self.ips) + 1:03d}"
            return self.ips[address] + (separator + prefix if separator else "")

        return IP_ADDRESS.sub(replace_ip, text)

    def path(self, path: PurePosixPath) -> PurePosixPath:
        parts = [
            self.hostnames.get(part, self.vrfs.get(part, part))
            for part in path.parts
        ]
        return PurePosixPath(*parts)

    def devices(self, devices: Iterable[str]) -> list[str]:
        return sorted(self.hostnames.get(value, value) for value in devices)


def _vrf_names(sources: Iterable[BundleSource]) -> set[str]:
    names: set[str] = set()
    for source in sources:
        try:
            text = source.content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        names.update(match.group(1) for match in VRF_DECLARATION.finditer(text))
    return names


def _filter_device_document(
    value: Any,
    *,
    selected: set[str] | None,
    known_devices: set[str],
) -> Any:
    if selected is None:
        return value
    if isinstance(value, Mapping):
        filtered = {}
        for key, item in value.items():
            if key == "hosts" and isinstance(item, Mapping):
                filtered[key] = {
                    host: _filter_device_document(
                        record,
                        selected=selected,
                        known_devices=known_devices,
                    )
                    for host, record in item.items()
                    if host in selected
                }
            else:
                filtered[key] = _filter_device_document(
                    item,
                    selected=selected,
                    known_devices=known_devices,
                )
        return filtered
    if isinstance(value, list):
        if value and all(
            isinstance(item, str) and item in known_devices for item in value
        ):
            return [item for item in value if item in selected]
        return [
            _filter_device_document(
                item,
                selected=selected,
                known_devices=known_devices,
            )
            for item in value
        ]
    return value


def _content_for_devices(
    source: BundleSource,
    *,
    selected: set[str] | None,
    known_devices: set[str],
) -> bytes:
    if selected is None:
        return source.content
    if source.source.suffix.lower() not in {".json", ".yaml", ".yml"}:
        try:
            lines = source.content.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return source.content
        excluded = known_devices - selected
        filtered_lines = []
        for line in lines:
            if any(
                re.search(
                    rf"(?<![A-Za-z0-9_.-]){re.escape(hostname)}"
                    rf"(?![A-Za-z0-9_.-])",
                    line,
                )
                for hostname in excluded
            ):
                continue
            filtered_lines.append(line)
        return ("\n".join(filtered_lines) + "\n").encode()
    try:
        text = source.content.decode("utf-8")
        document = (
            json.loads(text)
            if source.source.suffix.lower() == ".json"
            else yaml.safe_load(text)
        )
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
        return source.content
    filtered = _filter_device_document(
        document,
        selected=selected,
        known_devices=known_devices,
    )
    if source.source.suffix.lower() == ".json":
        return (json.dumps(filtered, indent=2, ensure_ascii=False) + "\n").encode()
    return yaml.safe_dump(
        filtered,
        sort_keys=False,
        allow_unicode=True,
    ).encode()


def _scan_secrets(content: str, policy: RedactionPolicy) -> bool:
    keys = "|".join(re.escape(value) for value in policy.mask_keys)
    key_pattern = (
        re.compile(
            rf"(?im)^\s*(?:{keys})\s+(?!\*{{3}}REDACTED)"
        )
        if keys
        else None
    )
    return bool(
        PRIVATE_KEY.search(content)
        or (key_pattern is not None and key_pattern.search(content))
    )


def _prompt(
    *,
    change_id: str,
    phase: str,
    timezone: str,
    symptom: str | None,
    questions: list[str] | None,
    language: str,
) -> str:
    if language == "en":
        title = "# AI Investigation Prompt"
        default_question = {
            "before": "Assess pre-existing findings and whether work should start.",
            "after": "Separate regressions from pre-existing findings and assess rollback need.",
            "rollback": "Assess restoration to before state and remaining differences.",
            "all": "Build an evidence-based incident timeline.",
        }[phase]
        instructions = [
            "Separate facts, inferences, and additional checks.",
            "Cite relative bundle paths and evidence locations.",
            "Separate pre-existing findings from new regressions.",
            "Do not treat missing evidence as healthy; report UNKNOWN.",
            "Do not assert facts that are absent from the evidence.",
            "Do not reproduce suspected secrets.",
            "Interpret timestamps using the manifest timezone.",
            "For additional collection, state device, command, and purpose.",
        ]
    else:
        title = "# AI解析依頼"
        default_question = {
            "before": "作業前異常の事実と影響、作業開始可否、追加取得を整理してください。",
            "after": "beforeからのregressionと既存異常を分離し、rollback要否を整理してください。",
            "rollback": "beforeへの復元状況、残存・消失設定、追加操作を整理してください。",
            "all": "証跡に基づく事象タイムラインと原因候補を整理してください。",
        }[phase]
        instructions = [
            "事実、推測、追加確認事項を分離してください。",
            "各判断にbundle内の相対pathと根拠箇所を付けてください。",
            "beforeからの既存異常と新規regressionを分離してください。",
            "証跡不足を正常とみなさずUNKNOWNとしてください。",
            "ログにない事実を確定しないでください。",
            "secretらしい値を回答へ転載しないでください。",
            "時刻はManifestのtimezoneで解釈してください。",
            "追加取得には対象device、command、目的を示してください。",
        ]
    lines = [
        title,
        "",
        f"- Change ID: {change_id}",
        f"- Phase: {phase}",
        f"- Timezone: {timezone}",
        f"- Symptom: {symptom or '(not provided)'}",
        "",
        "## Questions",
        "",
    ]
    lines.extend(f"- {question}" for question in questions or [default_question])
    lines.extend(["", "## Instructions", ""])
    lines.extend(f"{index}. {value}" for index, value in enumerate(instructions, 1))
    return "\n".join(lines) + "\n"


def _deterministic_archive(
    output_path: Path,
    files: Mapping[str, bytes],
) -> None:
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name in sorted(files):
                        path = PurePosixPath(name)
                        if not _is_safe_relative(path):
                            raise SupportBundleError(
                                f"unsafe archive path: {name}"
                            )
                        content = files[name]
                        info = tarfile.TarInfo(name)
                        info.size = len(content)
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mode = 0o600
                        archive.addfile(info, io.BytesIO(content))
        temporary.replace(output_path)
        output_path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_part(
    *,
    sources: Sequence[BundleSource],
    output: Path,
    operation_root: Path,
    change_id: str,
    requested_phase: str,
    part_phase: str,
    split: str,
    part_id: str,
    archive_name: str,
    created_at: datetime,
    timezone: str,
    symptom: str | None,
    questions: list[str] | None,
    prompt_language: str,
    max_size_mib: int,
    policy: RedactionPolicy,
    policy_hash: str,
    pseudonyms: _Pseudonyms,
    selected_devices: set[str] | None,
    known_devices: set[str],
) -> tuple[dict[str, Path], dict[str, Any]]:
    archive_files: dict[str, bytes] = {}
    entries = []
    for source in sources:
        raw = _content_for_devices(
            source,
            selected=selected_devices,
            known_devices=known_devices,
        )
        try:
            redacted_text = pseudonyms.redact(raw.decode("utf-8"), policy)
        except UnicodeDecodeError as exc:
            raise SupportBundleError(
                f"BUNDLE_INVALID_SOURCE: non-text allowlisted file: {source.source}"
            ) from exc
        if _scan_secrets(redacted_text, policy):
            raise SupportBundleError(
                "BUNDLE_BLOCKED_SECRET: high-confidence secret in "
                f"{source.destination}"
            )
        redacted = redacted_text.encode("utf-8")
        destination = pseudonyms.path(source.destination)
        destination_name = destination.as_posix()
        previous = archive_files.get(destination_name)
        if previous is not None and previous != redacted:
            raise SupportBundleError(
                f"BUNDLE_INVALID_SOURCE: destination collision: {destination}"
            )
        archive_files[destination_name] = redacted
        entries.append(
            {
                "bundle_path": destination_name,
                "source_sha256": source.source_sha256,
                "redacted_sha256": _sha256_bytes(redacted),
                "phase": source.phase,
                "devices": pseudonyms.devices(source.devices),
            }
        )
    prompt_text = _prompt(
        change_id=change_id,
        phase=part_phase,
        timezone=timezone,
        symptom=symptom,
        questions=questions,
        language=prompt_language,
    )
    archive_files["support-bundle/prompt.md"] = prompt_text.encode()
    readme = (
        "# Support Bundle\n\n"
        "This archive is redacted but not encrypted. Restrict storage and transfer access.\n"
    )
    archive_files["support-bundle/README.md"] = readme.encode()
    exposed_devices = pseudonyms.devices(selected_devices or ())
    manifest = {
        "api_version": API_VERSION,
        "kind": "SupportBundleManifest",
        "metadata": {
            "change_id": change_id,
            "phase": part_phase,
            "created_at": created_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "source_operation": f"operations/{change_id}",
            "split": split,
            "archive_name": archive_name,
            "part_id": part_id,
            "devices": exposed_devices,
            "redaction_policy_sha256": policy_hash,
            "files": entries,
            "prompt_language": prompt_language,
        },
        "status": {
            "result": "COMPLETE",
            "files_included": len(entries),
            "files_excluded": 0,
            "source_missing": [],
            "secret_scan": {"high_confidence": 0, "low_confidence": 0},
            "analysis_limitations": [
                "Configured identifiers are pseudonymized; mapping is not included"
            ],
        },
    }
    validate_document(manifest, kind="SupportBundleManifest")
    archive_files["support-bundle/manifest.yaml"] = yaml.safe_dump(
        manifest,
        sort_keys=False,
        allow_unicode=True,
    ).encode()
    checksums = "\n".join(
        f"{_sha256_bytes(content).removeprefix('sha256:')}  {name}"
        for name, content in sorted(archive_files.items())
    ) + "\n"
    archive_files["support-bundle/checksums.sha256"] = checksums.encode()
    estimated = sum(len(value) for value in archive_files.values())
    if estimated > max_size_mib * 1024 * 1024:
        raise SupportBundleError(
            "BUNDLE_TOO_LARGE: use --split device or raise the explicit limit"
        )
    archive_path = output / archive_name
    if archive_path.exists():
        raise SupportBundleError(f"bundle already exists: {archive_path}")
    _deterministic_archive(archive_path, archive_files)
    archive_sha = _sha256_bytes(archive_path.read_bytes())
    external = deepcopy(manifest)
    external["spec"]["archive_sha256"] = archive_sha
    stem = archive_name.removesuffix(".tar.gz")
    manifest_path = output / f"{stem}.manifest.yaml"
    sha_path = output / f"{stem}.sha256"
    prompt_path = output / f"{stem}-prompt.md"
    atomic_write_bytes(
        output,
        manifest_path,
        yaml.safe_dump(external, sort_keys=False, allow_unicode=True).encode(),
    )
    atomic_write_bytes(
        output,
        sha_path,
        f"{archive_sha.removeprefix('sha256:')}  {archive_name}\n".encode(),
    )
    atomic_write_bytes(output, prompt_path, prompt_text.encode())
    return (
        {
            "archive": archive_path,
            "manifest": manifest_path,
            "sha256": sha_path,
            "prompt": prompt_path,
        },
        {
            "part_id": part_id,
            "phase": part_phase,
            "archive_name": archive_name,
            "manifest_name": manifest_path.name,
            "archive_sha256": archive_sha,
            "devices": exposed_devices,
        },
    )


def create_support_bundle(
    operation_root: str | Path,
    *,
    change_id: str,
    phase: str,
    output_dir: str | Path,
    created_at: datetime,
    timezone: str,
    symptom: str | None = None,
    questions: list[str] | None = None,
    prompt_language: str = "ja",
    max_size_mib: int = 100,
    split: str = "none",
    devices: Sequence[str] | None = None,
    redaction_profile: str | Path | None = None,
    include_generated_config: bool = True,
    include_rollback_config: bool = True,
    include_raw_logging: bool = True,
) -> dict[str, Path]:
    """Create redacted support bundle archive(s) and optional part index."""
    if split not in {"none", "phase", "device"}:
        raise SupportBundleError(f"unsupported split: {split}")
    if max_size_mib < 1:
        raise SupportBundleError("max bundle size must be at least 1 MiB")
    root = Path(operation_root).resolve()
    requested_devices = set(devices) if devices else None
    sources, known_devices = _all_sources(
        root,
        change_id=change_id,
        phase=phase,
        requested_devices=requested_devices,
        include_generated_config=include_generated_config,
        include_rollback_config=include_rollback_config,
        include_raw_logging=include_raw_logging,
    )
    policy = load_redaction_policy(redaction_profile)
    policy_hash = canonical_sha256(policy.document)
    pseudonyms = _Pseudonyms(
        known_devices,
        _vrf_names(sources),
        hostnames_enabled=policy.pseudonymize_hostnames,
        ips_enabled=policy.pseudonymize_ips,
        vrfs_enabled=policy.pseudonymize_vrfs,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    part_specs: list[tuple[str, str, str, list[BundleSource], set[str] | None]] = []
    if split == "none":
        part_specs.append(
            (
                "all",
                phase,
                f"{change_id}-{phase}.tar.gz",
                sources,
                requested_devices,
            )
        )
    elif split == "phase":
        phases = (
            ["before", "after", "rollback"]
            if phase == "all"
            else [phase]
        )
        for item_phase in phases:
            if not any(source.phase == item_phase for source in sources):
                continue
            part_sources = [
                source
                for source in sources
                if source.phase in {"common", item_phase}
            ]
            part_specs.append(
                (
                    item_phase,
                    item_phase,
                    f"{change_id}-{item_phase}-phase.tar.gz",
                    part_sources,
                    requested_devices,
                )
            )
    else:
        selected = sorted(requested_devices or known_devices)
        common = [source for source in sources if not source.devices]
        part_specs.append(
            (
                "common",
                phase,
                f"{change_id}-{phase}-common.tar.gz",
                common,
                set(selected),
            )
        )
        for hostname in selected:
            device_sources = [
                source for source in sources if hostname in source.devices
            ]
            part_specs.append(
                (
                    pseudonyms.hostnames.get(hostname, hostname),
                    phase,
                    (
                        f"{change_id}-{phase}-"
                        f"{pseudonyms.hostnames.get(hostname, hostname)}.tar.gz"
                    ),
                    device_sources,
                    {hostname},
                )
            )
    outputs: dict[str, Path] = {}
    index_parts = []
    for part_id, part_phase, archive_name, part_sources, part_devices in part_specs:
        paths, index_part = _build_part(
            sources=part_sources,
            output=output,
            operation_root=root,
            change_id=change_id,
            requested_phase=phase,
            part_phase=part_phase,
            split=split,
            part_id=part_id,
            archive_name=archive_name,
            created_at=created_at,
            timezone=timezone,
            symptom=symptom,
            questions=questions,
            prompt_language=prompt_language,
            max_size_mib=max_size_mib,
            policy=policy,
            policy_hash=policy_hash,
            pseudonyms=pseudonyms,
            selected_devices=part_devices,
            known_devices=known_devices,
        )
        index_parts.append(index_part)
        if split == "none":
            outputs.update(paths)
        else:
            for name, path in paths.items():
                outputs[f"{name}_{part_id}"] = path
    if split != "none":
        index = {
            "api_version": API_VERSION,
            "kind": "SupportBundleIndex",
            "metadata": {
                "change_id": change_id,
                "phase": phase,
                "created_at": created_at.isoformat(timespec="seconds"),
                "timezone": timezone,
            },
            "spec": {"split": split, "parts": index_parts},
        }
        validate_document(index, kind="SupportBundleIndex")
        index_path = output / f"{change_id}-{phase}.index.yaml"
        atomic_write_bytes(
            output,
            index_path,
            yaml.safe_dump(index, sort_keys=False, allow_unicode=True).encode(),
        )
        outputs["index"] = index_path
    return outputs


def inspect_support_bundle(path: str | Path) -> dict[str, Any]:
    """Inspect member metadata without extracting the archive."""
    archive_path = Path(path)
    members = []
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if not _is_safe_relative(pure) or member.issym() or member.islnk():
                raise SupportBundleError(
                    f"BUNDLE_INVALID_SOURCE: unsafe archive member {member.name}"
                )
            if not member.isfile():
                raise SupportBundleError(
                    f"BUNDLE_INVALID_SOURCE: non-file member {member.name}"
                )
            members.append({"name": member.name, "size": member.size})
    return {"archive": str(archive_path), "members": members}


def verify_support_bundle_manifest(path: str | Path) -> dict[str, Any]:
    """Verify external manifest schema, archive hash, and internal checksums."""
    manifest_path = Path(path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    validate_document(manifest, kind="SupportBundleManifest")
    archive_path = manifest_path.parent / manifest["spec"]["archive_name"]
    actual = _sha256_bytes(archive_path.read_bytes())
    expected = manifest["spec"].get("archive_sha256")
    if actual != expected:
        raise SupportBundleError("archive SHA-256 mismatch")
    inspection = inspect_support_bundle(archive_path)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        checksum_member = archive.extractfile(
            "support-bundle/checksums.sha256"
        )
        if checksum_member is None:
            raise SupportBundleError("internal checksums are missing")
        checksum_lines = checksum_member.read().decode().splitlines()
        for line in checksum_lines:
            digest, name = line.split("  ", 1)
            member = archive.extractfile(name)
            if member is None or hashlib.sha256(member.read()).hexdigest() != digest:
                raise SupportBundleError(
                    f"internal checksum mismatch: {name}"
                )
    return {
        "archive": str(archive_path),
        "archive_sha256": actual,
        "files": len(inspection["members"]),
        "verified": True,
    }
