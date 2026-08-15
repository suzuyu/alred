"""Immutable import of externally collected running configurations."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Mapping

import yaml

from . import __version__
from .inventory import load_inventory_data
from .schema import API_VERSION, source_sha256, validate_document


class ExternalConfigImportError(ValueError):
    """Expected validation failure for an external running-config import."""

    code = "EXTERNAL_CONFIG_INPUT_INVALID"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ExternalConfigImportError(f"unsafe or missing YAML file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ExternalConfigImportError(f"YAML root must be a mapping: {path}")
    return data


def _inventory_identity(data: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    hosts = {
        str(item["hostname"]): item
        for item in load_inventory_data(dict(data))
    }
    aliases: dict[str, str] = {}
    raw_hosts = data.get("all", {}).get("hosts", {})
    if not isinstance(raw_hosts, Mapping) or not hosts:
        raise ExternalConfigImportError("inventory contains no hosts")
    for hostname in hosts:
        values = {hostname}
        attrs = raw_hosts.get(hostname, {})
        if isinstance(attrs, Mapping):
            raw_aliases = attrs.get("aliases", [])
            if isinstance(raw_aliases, str):
                values.add(raw_aliases)
            elif isinstance(raw_aliases, list):
                values.update(str(value) for value in raw_aliases)
        for value in values:
            key = value.casefold()
            previous = aliases.get(key)
            if previous is not None and previous != hostname:
                raise ExternalConfigImportError(f"ambiguous inventory alias: {value}")
            aliases[key] = hostname
    return hosts, aliases


def _canonical_host(value: str, aliases: Mapping[str, str]) -> str | None:
    return aliases.get(value.strip().casefold())


def _source_map(path: str | Path | None, aliases: Mapping[str, str]) -> dict[str, str]:
    if path is None:
        return {}
    data = _load_yaml_mapping(Path(path))
    rows = data.get("spec", {}).get("files", [])
    if not isinstance(rows, list):
        raise ExternalConfigImportError("source map spec.files must be a list")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ExternalConfigImportError("source map entry must be a mapping")
        relative = str(row.get("path", ""))
        pure = PurePosixPath(relative)
        if not relative or pure.is_absolute() or ".." in pure.parts:
            raise ExternalConfigImportError(f"unsafe source map path: {relative}")
        hostname = _canonical_host(str(row.get("hostname", "")), aliases)
        if hostname is None:
            raise ExternalConfigImportError(f"source map hostname is not in inventory: {row.get('hostname')}")
        if relative in result:
            raise ExternalConfigImportError(f"duplicate source map path: {relative}")
        result[relative] = hostname
    return result


def _text_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise ExternalConfigImportError(f"input directory is missing or unsafe: {root}")
    result: list[Path] = []
    for path in sorted(root.rglob("*.txt")):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file() or any(part.startswith(".") for part in relative.parts):
            raise ExternalConfigImportError(f"unsafe input file: {path}")
        result.append(path)
    if not result:
        raise ExternalConfigImportError(f"no .txt files found: {root}")
    return result


def _embedded_hostname(text: str) -> str | None:
    values = {
        match.group(1)
        for line in text.splitlines()
        if (match := re.match(r"^hostname\s+([A-Za-z0-9_.-]+)\s*$", line.strip()))
    }
    if len(values) > 1:
        raise ExternalConfigImportError("EXTERNAL_CONFIG_IDENTITY_CONFLICT: multiple hostname commands")
    return next(iter(values), None)


def _resolve_file_identity(
    *,
    path: Path,
    root: Path,
    text: str,
    source_map: Mapping[str, str],
    aliases: Mapping[str, str],
    collect_format: bool,
) -> tuple[str, str]:
    relative = path.relative_to(root).as_posix()
    candidates: list[tuple[str, str]] = []
    if relative in source_map:
        candidates.append((source_map[relative], "source-map"))
    stem = path.stem
    filename_name = stem[:-4] if stem.endswith("_run") else stem
    filename_host = _canonical_host(filename_name, aliases)
    if filename_host is not None and (collect_format or stem.endswith("_run") or filename_name == stem):
        candidates.append((filename_host, "filename"))
    embedded = _embedded_hostname(text)
    if embedded:
        canonical = _canonical_host(embedded, aliases)
        if canonical is None:
            raise ExternalConfigImportError(
                f"EXTERNAL_CONFIG_IDENTITY_UNRESOLVED: hostname {embedded} in {relative}"
            )
        candidates.append((canonical, "hostname-command"))
    identities = {item[0] for item in candidates}
    if len(identities) > 1:
        raise ExternalConfigImportError(
            f"EXTERNAL_CONFIG_IDENTITY_CONFLICT: {relative}: {sorted(identities)}"
        )
    if not candidates:
        raise ExternalConfigImportError(f"EXTERNAL_CONFIG_IDENTITY_UNRESOLVED: {relative}")
    return candidates[0][0], "+".join(item[1] for item in candidates)


_PROMPT_COMMAND_RE = re.compile(
    r"^(?P<host>[A-Za-z0-9_.-]+)[#>]\s*(?P<command>show\s+running-config(?:\s+.*)?)\s*$",
    re.IGNORECASE,
)
_PROMPT_RE = re.compile(r"^(?P<host>[A-Za-z0-9_.-]+)[#>]\s*(?:.*)?$")


def _transcript_sections(path: Path, aliases: Mapping[str, str]) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="strict")
    lines = text.splitlines()
    sections: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        match = _PROMPT_COMMAND_RE.match(lines[index].strip())
        if not match:
            index += 1
            continue
        hostname = _canonical_host(match.group("host"), aliases)
        if hostname is None:
            raise ExternalConfigImportError(
                f"EXTERNAL_CONFIG_IDENTITY_UNRESOLVED: transcript prompt {match.group('host')}"
            )
        start = index + 1
        end = start
        while end < len(lines) and not _PROMPT_RE.match(lines[end].strip()):
            end += 1
        content = "\n".join(lines[start:end]).rstrip() + "\n"
        if not content.strip():
            raise ExternalConfigImportError(f"EXTERNAL_CONFIG_INCOMPLETE: empty transcript section for {hostname}")
        embedded = _embedded_hostname(content)
        if embedded and _canonical_host(embedded, aliases) != hostname:
            raise ExternalConfigImportError(
                f"EXTERNAL_CONFIG_IDENTITY_CONFLICT: prompt and config hostname differ for {hostname}"
            )
        sections.append(
            {
                "hostname": hostname,
                "content": content.encode(),
                "source": path,
                "start_line": start + 1,
                "end_line": end,
                "identity_source": "prompt",
            }
        )
        index = end
    if not sections:
        raise ExternalConfigImportError(f"EXTERNAL_CONFIG_INCOMPLETE: no show running-config section: {path}")
    return sections


def _match_optional_lldp(root: Path, aliases: Mapping[str, str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in _text_files(root):
        stem = path.stem
        candidate = stem[:-5] if stem.endswith("_lldp") else stem
        hostname = _canonical_host(candidate, aliases)
        if hostname is None:
            raise ExternalConfigImportError(f"EXTERNAL_CONFIG_IDENTITY_UNRESOLVED: LLDP {path.name}")
        if hostname in result:
            raise ExternalConfigImportError(f"EXTERNAL_CONFIG_DUPLICATE_HOST: LLDP {hostname}")
        result[hostname] = path
    return result


def import_running_configs(
    *,
    input_dir: str | Path,
    input_format: str,
    hosts_path: str | Path,
    output_dir: str | Path,
    imported_at: datetime,
    source_map_path: str | Path | None = None,
    lldp_input: str | Path | None = None,
) -> dict[str, Any]:
    """Import external config files and publish one immutable successful attempt."""
    if input_format not in {"alred-collect", "running-config-directory", "nxos-transcript"}:
        raise ExternalConfigImportError(f"unsupported input format: {input_format}")
    source_root = Path(input_dir)
    inventory_path = Path(hosts_path)
    inventory = _load_yaml_mapping(inventory_path)
    inventory_hosts, aliases = _inventory_identity(inventory)
    mapped = _source_map(source_map_path, aliases)
    sections: list[dict[str, Any]] = []
    if input_format == "nxos-transcript":
        for path in _text_files(source_root):
            sections.extend(_transcript_sections(path, aliases))
    else:
        config_root = source_root / "config" if input_format == "alred-collect" and (source_root / "config").is_dir() else source_root
        for path in _text_files(config_root):
            content = path.read_bytes()
            try:
                text = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ExternalConfigImportError(f"non-UTF-8 input: {path}") from exc
            if not text.strip():
                raise ExternalConfigImportError(f"EXTERNAL_CONFIG_INCOMPLETE: empty file: {path}")
            hostname, identity_source = _resolve_file_identity(
                path=path,
                root=config_root,
                text=text,
                source_map=mapped,
                aliases=aliases,
                collect_format=input_format == "alred-collect",
            )
            sections.append(
                {
                    "hostname": hostname,
                    "content": content,
                    "source": path,
                    "start_line": 1,
                    "end_line": len(text.splitlines()),
                    "identity_source": identity_source,
                }
            )
    by_host: dict[str, dict[str, Any]] = {}
    for section in sections:
        hostname = section["hostname"]
        if hostname in by_host:
            raise ExternalConfigImportError(f"EXTERNAL_CONFIG_DUPLICATE_HOST: {hostname}")
        by_host[hostname] = section
    missing_hosts = set(inventory_hosts) - set(by_host)
    if missing_hosts:
        raise ExternalConfigImportError(
            "EXTERNAL_CONFIG_INCOMPLETE: missing inventory hosts: "
            + ",".join(sorted(missing_hosts))
        )
    lldp_paths = _match_optional_lldp(Path(lldp_input), aliases) if lldp_input else {}

    output = Path(output_dir)
    attempts = output / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    input_fingerprint = _digest(
        "".join(f"{host}:{_digest(item['content'])}\n" for host, item in sorted(by_host.items())).encode()
    )
    attempt_id = f"RCI-{imported_at.strftime('%Y%m%dT%H%M%S%z-%f')}-{input_fingerprint[:8]}"
    target = attempts / attempt_id
    if target.exists():
        raise ExternalConfigImportError(f"import attempt already exists: {target}")
    staging = Path(tempfile.mkdtemp(prefix=f".{attempt_id}.", dir=attempts))
    try:
        (staging / "config").mkdir()
        (staging / "inventory").mkdir()
        if lldp_paths:
            (staging / "lldp").mkdir()
        inventory_bytes = yaml.safe_dump(inventory, sort_keys=False, allow_unicode=True).encode()
        (staging / "inventory" / "hosts.resolved.yaml").write_bytes(inventory_bytes)
        manifest_hosts: dict[str, Any] = {}
        checksums: list[tuple[str, str]] = []
        checksums.append((_digest(inventory_bytes), "inventory/hosts.resolved.yaml"))
        for hostname, section in sorted(by_host.items()):
            config_relative = f"config/{hostname}_run.txt"
            (staging / config_relative).write_bytes(section["content"])
            checksums.append((_digest(section["content"]), config_relative))
            entry: dict[str, Any] = {
                "source_path": str(section["source"]),
                "source_sha256": source_sha256(section["source"]),
                "source_size": section["source"].stat().st_size,
                "source_range": {"start_line": section["start_line"], "end_line": section["end_line"]},
                "identity_source": section["identity_source"],
                "config_path": config_relative,
                "config_sha256": _digest(section["content"]),
            }
            if hostname in lldp_paths:
                lldp_content = lldp_paths[hostname].read_bytes()
                lldp_relative = f"lldp/{hostname}_lldp.txt"
                (staging / lldp_relative).write_bytes(lldp_content)
                checksums.append((_digest(lldp_content), lldp_relative))
                entry["lldp_path"] = lldp_relative
                entry["lldp_sha256"] = _digest(lldp_content)
            manifest_hosts[hostname] = entry
        manifest = {
            "api_version": API_VERSION,
            "kind": "RunningConfigImportManifest",
            "metadata": {
                "attempt_id": attempt_id,
                "imported_at": imported_at.isoformat(timespec="seconds"),
                "tool_version": __version__,
            },
            "spec": {
                "input_format": input_format,
                "input_fingerprint": input_fingerprint,
                "inventory": {
                    "path": "inventory/hosts.resolved.yaml",
                    "sha256": _digest(inventory_bytes),
                },
                "lldp": "provided" if lldp_paths else "not_provided",
                "hosts": manifest_hosts,
            },
        }
        validate_document(manifest, kind="RunningConfigImportManifest")
        manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).encode()
        (staging / "running-config-import-manifest.yaml").write_bytes(manifest_bytes)
        checksums.append((_digest(manifest_bytes), "running-config-import-manifest.yaml"))
        (staging / "unresolved-segments.yaml").write_text("unresolved_segments: []\n", encoding="utf-8")
        checksums.append((_digest((staging / "unresolved-segments.yaml").read_bytes()), "unresolved-segments.yaml"))
        (staging / "checksums.sha256").write_text(
            "".join(f"{digest}  {relative}\n" for digest, relative in sorted(checksums)),
            encoding="utf-8",
        )
        os.replace(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    current = {
        "schema_version": 1,
        "attempt_id": attempt_id,
        "artifact_dir": str(target),
        "manifest_sha256": source_sha256(target / "running-config-import-manifest.yaml"),
        "input_fingerprint": input_fingerprint,
        "completed_at": imported_at.isoformat(timespec="seconds"),
    }
    temporary = output / ".current.json.tmp"
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output / "current.json")
    return {"attempt_id": attempt_id, "attempt_dir": target, "manifest": target / "running-config-import-manifest.yaml"}


def resolve_running_config_import(
    source: str | Path,
) -> tuple[Path, dict[str, Path], dict[str, Path], dict[str, Any]]:
    """Resolve and verify a successful import root, attempt, or Manifest."""
    path = Path(source)
    if path.is_file():
        attempt = path.parent
        manifest_path = path
    elif (path / "running-config-import-manifest.yaml").is_file():
        attempt = path
        manifest_path = path / "running-config-import-manifest.yaml"
    elif (path / "current.json").is_file():
        current = json.loads((path / "current.json").read_text(encoding="utf-8"))
        attempt = Path(str(current["artifact_dir"]))
        manifest_path = attempt / "running-config-import-manifest.yaml"
        if source_sha256(manifest_path) != current.get("manifest_sha256"):
            raise ExternalConfigImportError("current import Manifest hash mismatch")
    else:
        raise ExternalConfigImportError(f"cannot resolve running config import: {path}")
    manifest = _load_yaml_mapping(manifest_path)
    validate_document(manifest, kind="RunningConfigImportManifest")
    inventory_entry = manifest["spec"]["inventory"]
    inventory_path = attempt / inventory_entry["path"]
    if source_sha256(inventory_path).removeprefix("sha256:") != inventory_entry["sha256"]:
        raise ExternalConfigImportError("resolved inventory hash mismatch")
    configs: dict[str, Path] = {}
    lldp: dict[str, Path] = {}
    for hostname, entry in manifest["spec"]["hosts"].items():
        config = attempt / entry["config_path"]
        if source_sha256(config).removeprefix("sha256:") != entry["config_sha256"]:
            raise ExternalConfigImportError(f"config hash mismatch: {hostname}")
        configs[hostname] = config
        if entry.get("lldp_path"):
            lldp_path = attempt / entry["lldp_path"]
            if source_sha256(lldp_path).removeprefix("sha256:") != entry["lldp_sha256"]:
                raise ExternalConfigImportError(f"LLDP hash mismatch: {hostname}")
            lldp[hostname] = lldp_path
    return inventory_path, configs, lldp, manifest
