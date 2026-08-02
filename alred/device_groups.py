"""Overlay ChangeSet device-group loading, hierarchy expansion, and evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .operation import atomic_write_json, atomic_write_yaml
from .schema import canonical_sha256, source_sha256, validate_document


MAX_GROUP_DEPTH = 16


class DeviceGroupError(ValueError):
    """A device-group reference or hierarchy cannot be resolved safely."""

    code = "VALIDATION_ERROR"


@dataclass(frozen=True)
class DeviceGroupResolution:
    """Fully expanded groups and all contributing group chains."""

    groups: dict[str, dict[str, list[str]]]
    chains: dict[str, dict[str, list[list[str]]]]


@dataclass(frozen=True)
class LoadedOverlayChangeSet:
    """A validated ChangeSet with external groups materialized inline."""

    document: dict[str, Any]
    source_document: dict[str, Any]
    source_path: Path
    source_sha256: str
    source_canonical_sha256: str
    source_mode: str
    device_groups_document: dict[str, Any] | None
    device_groups_path: Path | None
    device_groups_source_sha256: str | None
    device_groups_canonical_sha256: str
    resolution: DeviceGroupResolution


def resolve_device_groups(
    definitions: Mapping[str, Mapping[str, Any]],
    *,
    max_depth: int = MAX_GROUP_DEPTH,
) -> DeviceGroupResolution:
    """Expand direct devices and child groups deterministically."""
    if not isinstance(definitions, Mapping):
        raise DeviceGroupError("device_groups must be a mapping")
    memo_devices: dict[str, list[str]] = {}
    memo_chains: dict[str, dict[str, list[list[str]]]] = {}

    def expand(name: str, stack: tuple[str, ...]) -> None:
        if name in memo_devices:
            return
        if name not in definitions:
            parent = stack[-1] if stack else "<root>"
            raise DeviceGroupError(
                f"unknown child device group {name!r} referenced by {parent!r}"
            )
        if name in stack:
            cycle = " -> ".join((*stack, name))
            raise DeviceGroupError(f"device group cycle detected: {cycle}")
        if len(stack) >= max_depth:
            chain = " -> ".join((*stack, name))
            raise DeviceGroupError(
                f"device group hierarchy exceeds {max_depth} levels: {chain}"
            )
        value = definitions[name]
        if not isinstance(value, Mapping):
            raise DeviceGroupError(f"device group {name!r} must be a mapping")
        next_stack = (*stack, name)
        chains: dict[str, list[list[str]]] = {}
        for host in value.get("devices", []):
            chains.setdefault(str(host), []).append([name])
        for child in value.get("groups", []):
            child_name = str(child)
            expand(child_name, next_stack)
            for host, child_chains in memo_chains[child_name].items():
                chains.setdefault(host, []).extend(
                    [[name, *chain] for chain in child_chains]
                )
        if not chains:
            raise DeviceGroupError(
                f"device group {name!r} expands to no devices"
            )
        normalized_chains = {
            host: sorted({tuple(chain) for chain in host_chains})
            for host, host_chains in sorted(chains.items())
        }
        memo_devices[name] = sorted(normalized_chains)
        memo_chains[name] = {
            host: [list(chain) for chain in host_chains]
            for host, host_chains in normalized_chains.items()
        }

    for group_name in sorted(definitions):
        expand(str(group_name), ())
    return DeviceGroupResolution(
        groups={
            name: {"devices": devices}
            for name, devices in sorted(memo_devices.items())
        },
        chains={name: memo_chains[name] for name in sorted(memo_chains)},
    )


def resolve_resource_targets(
    resource: Mapping[str, Any],
    resolution: DeviceGroupResolution,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Resolve one resource target and preserve its selection evidence."""
    resolved: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    target = resource["targets"]
    explicit_devices = target.get("devices", {})
    for group_name, override in target.get("groups", {}).items():
        if group_name not in resolution.groups:
            raise DeviceGroupError(f"unknown device group: {group_name}")
        for host in resolution.groups[group_name]["devices"]:
            normalized_override = dict(override)
            if (
                host in resolved
                and resolved[host] != normalized_override
                and host not in explicit_devices
            ):
                previous = ", ".join(evidence[host]["selected_by_groups"])
                raise DeviceGroupError(
                    f"conflicting group overrides for device {host}: "
                    f"{previous} and {group_name}"
                )
            resolved[host] = normalized_override
            host_evidence = evidence.setdefault(
                host,
                {
                    "selected_by_groups": [],
                    "group_chains": [],
                    "device_override": False,
                },
            )
            if group_name not in host_evidence["selected_by_groups"]:
                host_evidence["selected_by_groups"].append(group_name)
            host_evidence["group_chains"].extend(
                resolution.chains[group_name][host]
            )
    for host, override in explicit_devices.items():
        resolved[host] = dict(override)
        host_evidence = evidence.setdefault(
            host,
            {
                "selected_by_groups": [],
                "group_chains": [],
                "device_override": False,
            },
        )
        host_evidence["device_override"] = True
    if not resolved:
        raise DeviceGroupError(
            f"resource {resource.get('vni')} has no targets"
        )
    for value in evidence.values():
        value["selected_by_groups"].sort()
        value["group_chains"] = [
            list(chain)
            for chain in sorted(
                {tuple(chain) for chain in value["group_chains"]}
            )
        ]
    return dict(sorted(resolved.items())), dict(sorted(evidence.items()))


def build_resolved_targets(
    change_set: Mapping[str, Any],
    resolution: DeviceGroupResolution,
    *,
    source_mode: str,
) -> dict[str, Any]:
    """Build the immutable, human-reviewable target expansion artifact."""
    resources: list[dict[str, Any]] = []
    for resource_type, key in (("l2vni", "l2vnis"), ("l3vni", "l3vnis")):
        for resource in change_set["spec"][key]:
            overrides, evidence = resolve_resource_targets(resource, resolution)
            resources.append(
                {
                    "type": resource_type,
                    "vni": resource["vni"],
                    "devices": {
                        host: {
                            "override": overrides[host],
                            **evidence[host],
                        }
                        for host in overrides
                    },
                }
            )
    resources.sort(key=lambda item: (item["type"], item["vni"]))
    document = {
        "api_version": "alred/v1",
        "kind": "OverlayResolvedTargets",
        "metadata": {
            "change_id": change_set["metadata"]["change_id"],
            "source_mode": source_mode,
        },
        "spec": {
            "groups": {
                name: {
                    "devices": resolution.groups[name]["devices"],
                    "chains": resolution.chains[name],
                }
                for name in resolution.groups
            },
            "resources": resources,
        },
    }
    validate_document(document, kind="OverlayResolvedTargets")
    return document


def _regular_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DeviceGroupError(f"{label} must be a regular file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise DeviceGroupError(f"{label} must contain a YAML mapping: {path}")
    return loaded


def _reject_symlink_components(base: Path, reference: Path) -> None:
    current = base
    for part in reference.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise DeviceGroupError(
                f"device_groups_ref.path contains a symlink: {current}"
            )


def load_overlay_change_set(path: str | Path) -> LoadedOverlayChangeSet:
    """Load a ChangeSet and materialize its inline or referenced groups."""
    source_path = Path(path)
    source = _regular_yaml_mapping(source_path, "Overlay ChangeSet")
    validate_document(source, kind="OverlayChangeSet")
    spec = source["spec"]
    groups_document: dict[str, Any] | None = None
    groups_path: Path | None = None
    groups_source_hash: str | None = None
    if "device_groups_ref" in spec:
        reference = Path(spec["device_groups_ref"]["path"])
        if reference.is_absolute():
            raise DeviceGroupError(
                "device_groups_ref.path must be relative to the ChangeSet"
            )
        _reject_symlink_components(source_path.parent, reference)
        groups_path = source_path.parent / reference
        groups_document = _regular_yaml_mapping(
            groups_path,
            "OverlayDeviceGroups",
        )
        validate_document(groups_document, kind="OverlayDeviceGroups")
        definitions = groups_document["spec"]["device_groups"]
        groups_source_hash = source_sha256(groups_path)
        groups_canonical_hash = canonical_sha256(groups_document)
        source_mode = "external"
    else:
        definitions = spec["device_groups"]
        groups_canonical_hash = canonical_sha256(definitions)
        source_mode = "inline"
    resolution = resolve_device_groups(definitions)
    materialized = deepcopy(source)
    materialized["spec"].pop("device_groups_ref", None)
    materialized["spec"]["device_groups"] = deepcopy(definitions)
    validate_document(materialized, kind="OverlayChangeSet")
    return LoadedOverlayChangeSet(
        document=materialized,
        source_document=source,
        source_path=source_path,
        source_sha256=source_sha256(source_path),
        source_canonical_sha256=canonical_sha256(source),
        source_mode=source_mode,
        device_groups_document=groups_document,
        device_groups_path=groups_path,
        device_groups_source_sha256=groups_source_hash,
        device_groups_canonical_sha256=groups_canonical_hash,
        resolution=resolution,
    )


def load_device_groups_file(
    path: str | Path,
    *,
    allow_legacy: bool = False,
) -> tuple[dict[str, Any], DeviceGroupResolution]:
    """Load the standard Kind or a backward-compatible discovery mapping."""
    candidate = Path(path)
    document = _regular_yaml_mapping(candidate, "device groups")
    if document.get("kind") == "OverlayDeviceGroups":
        validate_document(document, kind="OverlayDeviceGroups")
        definitions = document["spec"]["device_groups"]
        return document, resolve_device_groups(definitions)
    if not allow_legacy:
        raise DeviceGroupError(
            "device groups file requires kind: OverlayDeviceGroups"
        )
    raw_definitions = document.get("device_groups", document)
    if not isinstance(raw_definitions, Mapping):
        raise DeviceGroupError("legacy device groups must be a mapping")
    definitions: dict[str, dict[str, Any]] = {}
    for name, value in raw_definitions.items():
        if isinstance(value, list):
            definitions[str(name)] = {"devices": value}
        elif isinstance(value, Mapping):
            definitions[str(name)] = dict(value)
        else:
            raise DeviceGroupError(
                f"invalid legacy device group definition: {name!r}"
            )
    wrapped = {
        "api_version": "alred/v1",
        "kind": "OverlayDeviceGroups",
        "metadata": {"name": candidate.stem},
        "spec": {"device_groups": definitions},
    }
    validate_document(wrapped, kind="OverlayDeviceGroups")
    return wrapped, resolve_device_groups(definitions)


def write_overlay_plan_inputs(
    operation_root: str | Path,
    loaded: LoadedOverlayChangeSet,
    *,
    artifact_dir: str = "plan",
    inputs_dir: str = "inputs",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pin materialized inputs and their resolved target evidence."""
    root = Path(operation_root)
    pinned_change_set = root / inputs_dir / "change-set.yaml"
    atomic_write_yaml(
        root,
        pinned_change_set,
        loaded.document,
        kind="OverlayChangeSet",
    )
    pinned_groups: Path | None = None
    if loaded.device_groups_document is not None:
        pinned_groups = root / inputs_dir / "device-groups.yaml"
        atomic_write_yaml(
            root,
            pinned_groups,
            loaded.device_groups_document,
            kind="OverlayDeviceGroups",
        )
    resolved_document = build_resolved_targets(
        loaded.document,
        loaded.resolution,
        source_mode=loaded.source_mode,
    )
    resolved_path = root / artifact_dir / "resolved-targets.yaml"
    atomic_write_yaml(
        root,
        resolved_path,
        resolved_document,
        kind="OverlayResolvedTargets",
    )
    relative_change_set = str(pinned_change_set.relative_to(root))
    relative_resolved = str(resolved_path.relative_to(root))
    groups_manifest: dict[str, Any] = {
        "mode": loaded.source_mode,
        "resolved_canonical_sha256": canonical_sha256(
            {
                "groups": loaded.resolution.groups,
                "chains": loaded.resolution.chains,
            }
        ),
    }
    if pinned_groups is not None and loaded.device_groups_path is not None:
        groups_manifest.update(
            {
                "source_path": str(loaded.device_groups_path.resolve()),
                "pinned_path": str(pinned_groups.relative_to(root)),
                "source_sha256": loaded.device_groups_source_sha256,
                "source_canonical_sha256": canonical_sha256(
                    loaded.device_groups_document
                ),
                "pinned_sha256": source_sha256(pinned_groups),
            }
        )
    manifest = {
        "schema_version": 1,
        "change_id": loaded.document["metadata"]["change_id"],
        "change_set": {
            "source_path": str(loaded.source_path.resolve()),
            "pinned_path": relative_change_set,
            "source_sha256": loaded.source_sha256,
            "source_canonical_sha256": loaded.source_canonical_sha256,
            "pinned_sha256": source_sha256(pinned_change_set),
            "resolved_canonical_sha256": canonical_sha256(loaded.document),
        },
        "device_groups": groups_manifest,
        "resolved_targets": {
            "pinned_path": relative_resolved,
            "pinned_sha256": source_sha256(resolved_path),
            "canonical_sha256": canonical_sha256(resolved_document),
        },
    }
    manifest_path = root / artifact_dir / "input-manifest.json"
    atomic_write_json(
        root,
        manifest_path,
        manifest,
        kind="OverlayInputManifest",
    )
    return manifest, resolved_document
