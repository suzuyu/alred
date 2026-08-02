"""Health Check Profile loading, composition, and immutable resolution."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..resources import get_resource_dir
from ..schema import API_VERSION, canonical_sha256, validate_document


BUILTIN_PROFILES = {
    "network-baseline-nxos": "network-baseline-nxos.yaml",
    "nxos-overlay": "nxos-overlay.yaml",
}
DEFAULT_HEALTH_PROFILE = "network-baseline-nxos"


class ProfileResolutionError(ValueError):
    """Raised for unresolved, conflicting, or incompatible profiles."""

    code = "VALIDATION_ERROR"


def _source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_profile(ref: str) -> tuple[dict[str, Any], str, str, str]:
    if ref in BUILTIN_PROFILES:
        path = get_resource_dir("health") / "profiles" / BUILTIN_PROFILES[ref]
        profile_type = "builtin"
        source = f"builtin://{ref}"
    else:
        path = Path(ref)
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise ProfileResolutionError(
                f"unknown builtin profile or unsupported profile path: {ref}"
            )
        if not path.is_file() or path.is_symlink():
            raise ProfileResolutionError(f"profile file not found: {path}")
        profile_type = "file"
        source = str(path)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProfileResolutionError(f"profile is not a mapping: {ref}")
    validate_document(document, kind="HealthCheckProfile")
    return document, profile_type, source, _source_digest(path)


def _merge_thresholds(
    target: dict[str, Any],
    update: Mapping[str, Any],
    *,
    source: str,
    overrides: list[dict[str, Any]],
    path: str = "spec.thresholds",
) -> None:
    for key, value in update.items():
        current_path = f"{path}.{key}"
        if (
            key in target
            and isinstance(target[key], dict)
            and isinstance(value, Mapping)
        ):
            _merge_thresholds(
                target[key],
                value,
                source=source,
                overrides=overrides,
                path=current_path,
            )
        else:
            if key in target and target[key] != value:
                overrides.append(
                    {
                        "path": current_path,
                        "previous_value": target[key],
                        "effective_value": value,
                        "effective_source": source,
                    }
                )
            target[key] = deepcopy(value)


def resolve_profiles(
    refs: list[str],
    *,
    change_id: str,
    resolved_at: datetime,
    timezone: str,
    resolution_source: str = "explicit",
) -> dict[str, Any]:
    """Resolve ordered builtin/file profiles into one deterministic profile."""
    if not refs:
        raise ProfileResolutionError("at least one profile is required")
    loaded = [_load_profile(ref) for ref in refs]
    requested: list[dict[str, Any]] = []
    profile_names: list[str] = []
    platforms: list[str] = []
    commands: dict[str, dict[str, dict[str, Any]]] = {}
    checks: list[dict[str, Any]] = []
    check_ids: set[str] = set()
    thresholds: dict[str, Any] = {}
    overrides: list[dict[str, Any]] = []
    effective_optional: dict[str, Any] = {}

    for order, (profile, profile_type, source, digest) in enumerate(
        loaded,
        start=1,
    ):
        metadata = profile["metadata"]
        spec = profile["spec"]
        requested.append(
            {
                "order": order,
                "ref": refs[order - 1],
                "type": profile_type,
                "name": metadata["name"],
                "version": metadata["version"],
                "source": source,
                "source_sha256": digest,
                "resolution_source": resolution_source,
            }
        )
        profile_names.append(metadata["name"])
        for platform in spec["platforms"]:
            if platform not in platforms:
                platforms.append(platform)
        for platform, collector in spec.get("collectors", {}).items():
            platform_commands = commands.setdefault(platform, {})
            for command in collector["commands"]:
                identifier = command["id"]
                existing = platform_commands.get(identifier)
                if existing is not None:
                    if existing["command"] != command["command"]:
                        raise ProfileResolutionError(
                            f"conflicting command definition for {platform}/"
                            f"{identifier}"
                        )
                    if existing.get("when") != command.get("when"):
                        raise ProfileResolutionError(
                            f"conflicting command condition for {platform}/{identifier}"
                        )
                    existing["required"] = bool(
                        existing["required"] or command["required"]
                    )
                else:
                    platform_commands[identifier] = deepcopy(command)
        for check in spec.get("checks", []):
            identifier = check["id"]
            if identifier in check_ids:
                raise ProfileResolutionError(
                    f"check ID must be unique across profiles: {identifier}"
                )
            check_ids.add(identifier)
            copied = deepcopy(check)
            copied["profile"] = metadata["name"]
            checks.append(copied)
        _merge_thresholds(
            thresholds,
            spec.get("thresholds", {}),
            source=metadata["name"],
            overrides=overrides,
        )
        for key in (
            "convergence",
            "operation_gate",
            "report",
        ):
            if key in spec:
                current = effective_optional.setdefault(key, {})
                _merge_thresholds(
                    current,
                    spec[key],
                    source=metadata["name"],
                    overrides=overrides,
                    path=f"spec.{key}",
                )

    if not checks:
        raise ProfileResolutionError(
            "resolved profiles must define at least one health check"
        )
    collectors = {
        platform: {"commands": [command_map[key] for key in sorted(command_map)]}
        for platform, command_map in sorted(commands.items())
    }
    effective_spec: dict[str, Any] = {
        "platforms": platforms,
        "collectors": collectors,
        "checks": checks,
    }
    if thresholds:
        effective_spec["thresholds"] = thresholds
    effective_spec.update(effective_optional)
    effective = {
        "api_version": API_VERSION,
        "kind": "HealthCheckProfile",
        "metadata": {
            "name": "+".join(profile_names),
            "version": "resolved-v1",
            "description": "Resolved ordered Health Check Profiles",
        },
        "spec": effective_spec,
    }
    # ``profile`` is resolution provenance, not part of input Profile schema.
    validation_effective = deepcopy(effective)
    for check in validation_effective["spec"]["checks"]:
        check.pop("profile")
    validate_document(validation_effective, kind="HealthCheckProfile")
    effective_sha256 = canonical_sha256(effective)
    document = {
        "api_version": API_VERSION,
        "kind": "ResolvedHealthCheckProfiles",
        "metadata": {
            "change_id": change_id,
            "resolved_at": resolved_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "requested": requested,
            "resolved": {
                "profile_names": profile_names,
                "effective_sha256": effective_sha256,
                "effective": effective,
                "overrides": overrides,
            },
        },
    }
    validate_document(document, kind="ResolvedHealthCheckProfiles")
    return document


def apply_logging_time_range_override(
    document: Mapping[str, Any],
    time_range: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a resolved profile with a hash-pinned CLI logging range."""
    candidate = deepcopy(document)
    resolved = candidate["spec"]["resolved"]
    effective = resolved["effective"]
    logging = (
        effective["spec"]
        .setdefault("thresholds", {})
        .setdefault(
            "logging",
            {},
        )
    )
    previous = deepcopy(
        logging.get(
            "time_range",
            {"lookback_seconds": logging.get("lookback_seconds", 604800)},
        )
    )
    logging["time_range"] = deepcopy(dict(time_range))

    validation_effective = deepcopy(effective)
    for check in validation_effective["spec"]["checks"]:
        check.pop("profile", None)
    validate_document(validation_effective, kind="HealthCheckProfile")

    resolved["effective_sha256"] = canonical_sha256(effective)
    resolved["overrides"].append(
        {
            "path": "spec.thresholds.logging.time_range",
            "previous_value": previous,
            "effective_value": deepcopy(dict(time_range)),
            "effective_source": "cli",
        }
    )
    validate_document(candidate, kind="ResolvedHealthCheckProfiles")
    return candidate


def load_resolved_profiles(path: str | Path) -> dict[str, Any]:
    """Load and verify the canonical hash of a resolved profile artifact."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise ProfileResolutionError(
            f"resolved profile artifact not found: {candidate}"
        )
    document = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProfileResolutionError(
            f"resolved profile artifact is not a mapping: {candidate}"
        )
    validate_document(
        document,
        kind="ResolvedHealthCheckProfiles",
        allow_unknown_fields=True,
    )
    resolved = document["spec"]["resolved"]
    actual_hash = canonical_sha256(resolved["effective"])
    if actual_hash != resolved["effective_sha256"]:
        raise ProfileResolutionError("resolved profile effective hash mismatch")
    return document
