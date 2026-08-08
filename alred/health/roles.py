"""Versioned topology-role and function policy resolution for Health Check."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml

from ..schema import API_VERSION, canonical_sha256, source_sha256, validate_document


ROLE_RESOLVER_VERSION = "1.0"
SUPPORTED_ROLE_SCHEMA_VERSIONS = {1, 2}
OVERLAY_TOPOLOGY_ROLES = {
    "leaf",
    "border-gateway",
    "spine",
    "super-spine",
}
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MATCHER_KEYS = {"position_matches", "startswith", "endswith", "contains"}
_EXPECTATIONS = {"required", "optional", "forbidden"}


class RoleResolutionError(ValueError):
    """Raised when roles.yaml cannot be resolved safely."""

    code = "ROLE_INPUT_ERROR"


def load_resolved_roles(path: str | Path) -> dict[str, Any]:
    """Load and validate an immutable ResolvedRoles operation artifact."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise RoleResolutionError(
            f"resolved roles file is missing or unsafe: {candidate}"
        )
    document = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RoleResolutionError(
            f"resolved roles is not a mapping: {candidate}"
        )
    validate_document(document, kind="ResolvedRoles")
    return document


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RoleResolutionError(f"{label} must be a mapping")
    return value


def _validate_name(value: Any, label: str) -> str:
    name = str(value)
    if not _NAME.fullmatch(name):
        raise RoleResolutionError(
            f"{label} must use lowercase kebab-case: {name!r}"
        )
    return name


def _validate_matchers(rule: Mapping[str, Any], label: str) -> None:
    for key in _MATCHER_KEYS:
        if key not in rule:
            continue
        values = rule[key]
        if not isinstance(values, list):
            raise RoleResolutionError(f"{label}.{key} must be a list")
        if key == "position_matches":
            for index, item in enumerate(values):
                entry = _mapping(item, f"{label}.{key}[{index}]")
                if set(entry) != {"pos", "value"}:
                    raise RoleResolutionError(
                        f"{label}.{key}[{index}] requires pos and value"
                    )
                if not isinstance(entry["pos"], int) or entry["pos"] < 0:
                    raise RoleResolutionError(
                        f"{label}.{key}[{index}].pos must be >= 0"
                    )
                if not str(entry["value"]):
                    raise RoleResolutionError(
                        f"{label}.{key}[{index}].value must not be empty"
                    )
        elif any(not str(item) for item in values):
            raise RoleResolutionError(f"{label}.{key} contains an empty value")


def _validate_function(
    name: str,
    value: Any,
    label: str,
) -> dict[str, str]:
    _validate_name(name, f"{label} name")
    definition = _mapping(value, label)
    unknown = set(definition) - {"expectation"}
    if unknown:
        raise RoleResolutionError(
            f"{label} has unsupported fields: {', '.join(sorted(unknown))}"
        )
    expectation = str(definition.get("expectation", "optional"))
    if expectation not in _EXPECTATIONS:
        raise RoleResolutionError(
            f"{label}.expectation must be required, optional, or forbidden"
        )
    return {"expectation": expectation}


def _validate_v2(document: Mapping[str, Any]) -> dict[str, Any]:
    allowed_top = {
        "schema_version",
        "role_detection",
        "function_expectation_rules",
    }
    unknown_top = set(document) - allowed_top
    if unknown_top:
        raise RoleResolutionError(
            "roles.yaml has unsupported top-level fields: "
            + ", ".join(sorted(unknown_top))
        )
    raw_roles = _mapping(document.get("role_detection"), "role_detection")
    roles: dict[str, Any] = {}
    for raw_name, raw_rule in raw_roles.items():
        name = _validate_name(raw_name, "topology role")
        rule = _mapping(raw_rule, f"role_detection.{name}")
        unknown = set(rule) - (_MATCHER_KEYS | {"priority", "functions"})
        if unknown:
            raise RoleResolutionError(
                f"role_detection.{name} has unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        _validate_matchers(rule, f"role_detection.{name}")
        try:
            priority = int(rule.get("priority", 99))
        except (TypeError, ValueError) as exc:
            raise RoleResolutionError(
                f"role_detection.{name}.priority must be an integer"
            ) from exc
        functions: dict[str, Any] = {}
        for function_name, function in _mapping(
            rule.get("functions", {}),
            f"role_detection.{name}.functions",
        ).items():
            functions[str(function_name)] = _validate_function(
                str(function_name),
                function,
                f"role_detection.{name}.functions.{function_name}",
            )
        roles[name] = {
            "priority": priority,
            **{
                key: deepcopy(rule[key])
                for key in _MATCHER_KEYS
                if key in rule
            },
            "functions": functions,
        }

    rules: dict[str, Any] = {}
    for function_name, raw_rule in _mapping(
        document.get("function_expectation_rules", {}),
        "function_expectation_rules",
    ).items():
        name = _validate_name(function_name, "function expectation rule")
        rule = _mapping(raw_rule, f"function_expectation_rules.{name}")
        allowed = {f"{value}_when" for value in _EXPECTATIONS}
        unknown = set(rule) - allowed
        if unknown or not rule:
            raise RoleResolutionError(
                f"function_expectation_rules.{name} requires only one or more "
                "required_when, optional_when, forbidden_when rules"
            )
        normalized: dict[str, Any] = {}
        for key, matcher in rule.items():
            matcher_map = _mapping(
                matcher,
                f"function_expectation_rules.{name}.{key}",
            )
            unknown_matchers = set(matcher_map) - _MATCHER_KEYS
            if unknown_matchers:
                raise RoleResolutionError(
                    f"function_expectation_rules.{name}.{key} has unsupported "
                    f"fields: {', '.join(sorted(unknown_matchers))}"
                )
            _validate_matchers(
                matcher_map,
                f"function_expectation_rules.{name}.{key}",
            )
            normalized[key] = deepcopy(dict(matcher_map))
        rules[name] = normalized
    return {
        "schema_version": 2,
        "role_detection": roles,
        "function_expectation_rules": rules,
    }


def load_role_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    """Load and validate a versioned roles.yaml without following symlinks."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise RoleResolutionError(f"roles file is missing or unsafe: {candidate}")
    loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    document = dict(_mapping(loaded, "roles.yaml"))
    raw_version = document.get("schema_version", 1)
    if not isinstance(raw_version, int):
        raise RoleResolutionError("roles.yaml schema_version must be an integer")
    if raw_version not in SUPPORTED_ROLE_SCHEMA_VERSIONS:
        error = RoleResolutionError(
            f"unsupported roles.yaml schema_version: {raw_version}"
        )
        error.code = "SCHEMA_UNSUPPORTED"
        raise error
    if raw_version == 1:
        _mapping(document.get("role_detection", {}), "role_detection")
        return {
            "schema_version": 1,
            "role_detection": deepcopy(document.get("role_detection", {})),
            "function_expectation_rules": {},
        }, candidate.resolve()
    return _validate_v2(document), candidate.resolve()


def _matches(hostname: str, rule: Mapping[str, Any]) -> bool:
    value = hostname.lower()
    for item in rule.get("position_matches", []):
        position = int(item["pos"])
        expected = str(item["value"]).lower()
        if value[position : position + len(expected)] == expected:
            return True
    if any(value.startswith(str(item).lower()) for item in rule.get("startswith", [])):
        return True
    if any(value.endswith(str(item).lower()) for item in rule.get("endswith", [])):
        return True
    return any(str(item).lower() in value for item in rule.get("contains", []))


def _function_expectation(
    hostname: str,
    function_name: str,
    default: str,
    rules: Mapping[str, Any],
) -> tuple[str, str]:
    matches: list[str] = []
    for key, matcher in rules.get(function_name, {}).items():
        if _matches(hostname, matcher):
            matches.append(key.removesuffix("_when"))
    distinct = sorted(set(matches))
    if len(distinct) > 1:
        error = RoleResolutionError(
            f"conflicting function expectations for {hostname}/{function_name}: "
            + ", ".join(distinct)
        )
        error.code = "FUNCTION_EXPECTATION_CONFLICT"
        raise error
    if distinct:
        return distinct[0], "function_expectation_rule"
    return default, "topology_role_default"


def resolve_role_policy(
    config: Mapping[str, Any],
    hostnames: Iterable[str],
    *,
    change_id: str,
    resolved_at: str,
    timezone: str,
    source_path: Path,
) -> dict[str, Any]:
    """Resolve deterministic topology-role and function policy per host."""
    schema_version = int(config["schema_version"])
    devices: dict[str, Any] = {}
    for hostname in sorted(set(hostnames)):
        if schema_version == 1:
            devices[hostname] = {
                "status": "legacy",
                "detected_topology_roles": [],
                "topology_role": None,
                "functions": {},
            }
            continue
        matched = [
            role
            for role, rule in config["role_detection"].items()
            if _matches(hostname, rule)
        ]
        if len(matched) > 1:
            status = "conflict"
            topology_role = None
        elif matched:
            status = "resolved"
            topology_role = matched[0]
        else:
            status = "fallback"
            topology_role = "other"
        functions: dict[str, Any] = {}
        if topology_role not in {None, "other"}:
            role_rule = config["role_detection"][topology_role]
            for function_name, definition in role_rule["functions"].items():
                expectation, source = _function_expectation(
                    hostname,
                    function_name,
                    definition["expectation"],
                    config["function_expectation_rules"],
                )
                functions[function_name] = {
                    "expectation": expectation,
                    "source": source,
                }
        devices[hostname] = {
            "status": status,
            "detected_topology_roles": matched,
            "topology_role": topology_role,
            "functions": functions,
        }
    document = {
        "api_version": API_VERSION,
        "kind": "ResolvedRoles",
        "metadata": {
            "change_id": change_id,
            "resolved_at": resolved_at,
            "timezone": timezone,
            "resolver_version": ROLE_RESOLVER_VERSION,
        },
        "spec": {
            "role_schema_version": schema_version,
            "source": {
                "path": str(source_path),
                "sha256": source_sha256(source_path),
            },
            "policy_sha256": canonical_sha256(config),
            "devices": devices,
        },
    }
    validate_document(document, kind="ResolvedRoles")
    return document


def overlay_profile_scope(
    resolved_roles: Mapping[str, Any],
    hostname: str,
) -> tuple[bool, str, str]:
    """Return (execute, profile_result, reason_code) for nxos-overlay."""
    if resolved_roles["spec"]["role_schema_version"] == 1:
        return True, "NOT_APPLICABLE", "LEGACY_ROLE_SCOPE"
    device = resolved_roles["spec"]["devices"][hostname]
    if device["status"] == "conflict":
        return False, "UNKNOWN", "ROLE_CONFLICT"
    role = device["topology_role"]
    if role == "other":
        return False, "UNKNOWN", "TOPOLOGY_ROLE_UNRESOLVED"
    if role not in OVERLAY_TOPOLOGY_ROLES:
        return False, "NOT_APPLICABLE", "PROFILE_ROLE_EXCLUDED"
    return True, "NOT_APPLICABLE", "IN_SCOPE"
