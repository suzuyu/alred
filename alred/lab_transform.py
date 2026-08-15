"""Policy-driven, platform-adapted config transformation for isolated labs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
import ipaddress
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import yaml

from .schema import API_VERSION, canonical_sha256, source_sha256, validate_document
from .transform import join_config_sections, split_config_sections


class LabTransformError(ValueError):
    """Base class for expected lab transform validation failures."""

    code = "VALIDATION_ERROR"


class LabTransformIncompleteSourceError(LabTransformError):
    code = "LAB_TRANSFORM_INCOMPLETE_SOURCE"


class LabTransformCardinalityError(LabTransformError):
    code = "LAB_TRANSFORM_PARAMETER_CARDINALITY"


class LabTransformBootstrapConflictError(LabTransformError):
    code = "LAB_TRANSFORM_BOOTSTRAP_USER_CONFLICT"


class UnsupportedLabPlatformError(LabTransformError):
    code = "UNSUPPORTED_PLATFORM"


@dataclass(frozen=True)
class LabTransformResult:
    """One platform adapter result without secret-bearing source values."""

    text: str
    stats: dict[str, int]
    warnings: tuple[dict[str, str], ...]
    risk_findings: tuple[dict[str, str], ...]
    primary_username: str | None
    post_apply_username: str
    post_apply_password_ref: str | None
    bootstrap_action: str


DEFAULT_SPEC: dict[str, Any] = {
    "services": {
        "ntp": {"action": "remove"},
        "logging": {"action": "remove"},
        "dns": {"action": "remove"},
        "aaa": {"action": "remove"},
        "snmp": {"action": "remove"},
    },
    "access_control": {"management_access_class": {"action": "remove"}},
    "credentials": {
        "certificates": {"action": "remove"},
        "private_keys": {"action": "remove"},
    },
    "source_local_users": {"action": "remove"},
    "lab_users": {"users": []},
    "bootstrap_user": {"action": "preserve"},
}


_USERNAME_RE = re.compile(r"^username\s+(\S+)\b", re.IGNORECASE)
_USERNAME_CREDENTIAL_RE = re.compile(
    r"^username\s+(\S+).*\b(?:password|secret)\b", re.IGNORECASE
)
_USERNAME_PASSPHRASE_RE = re.compile(
    r"^username\s+(\S+)\s+passphrase\b", re.IGNORECASE
)
_NTP_SERVER_RE = re.compile(r"^ntp\s+(?:server|peer)\s+(\S+)(?:\s+(.*))?$", re.IGNORECASE)
_NTP_CATEGORY_RE = re.compile(
    r"^ntp\s+(?:server|peer|authentication-key|trusted-key|access-group|source-interface)\b",
    re.IGNORECASE,
)
_REDACTED_NTP_RE = re.compile(r"^!\s*REDACTED\s+ntp(?:-server)?\b", re.IGNORECASE)
_AAA_RE = re.compile(
    r"^(?:aaa|radius-server|tacacs-server|radius\s+server|tacacs\s+server)\b",
    re.IGNORECASE,
)
_SNMP_RE = re.compile(r"^snmp-server\b", re.IGNORECASE)
_LOGGING_REMOTE_RE = re.compile(r"^logging\s+(?:server|source-interface)\b", re.IGNORECASE)
_DNS_RE = re.compile(
    r"^ip\s+(?:name-server|domain-name|domain-list|domain-lookup|domain-lookup source-interface)\b",
    re.IGNORECASE,
)
_CRYPTO_RE = re.compile(r"^(?:crypto\s+(?:key|ca)|key\s+chain)\b", re.IGNORECASE)
_LINE_VTY_RE = re.compile(r"^line\s+vty(?:\s+\d+(?:\s+\d+)?)?$", re.IGNORECASE)
_ACCESS_CLASS_RE = re.compile(r"^\s*(?:ipv6\s+)?access-class\b", re.IGNORECASE)
_ACCESS_CLASS_NAME_RE = re.compile(
    r"^\s*(?:ipv6\s+)?access-class\s+(\S+)\s+(?:in|out)\b", re.IGNORECASE
)
_IP_ACCESS_LIST_RE = re.compile(r"^ip\s+access-list\s+(\S+)\b", re.IGNORECASE)
_VALID_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MASK_MARKER_RE = re.compile(r"<masked(?::[^>]+)?>", re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----", re.IGNORECASE)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_lab_transform_parameters(path: str | Path | None) -> tuple[dict[str, Any], str | None]:
    """Load and validate parameters, returning resolved defaults and source hash."""
    if path is None:
        return deepcopy(DEFAULT_SPEC), None
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise LabTransformError(f"lab parameter must be a regular file: {candidate}")
    document = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise LabTransformError("LabTransformParameters must be a YAML mapping")
    validate_document(document, kind="LabTransformParameters")
    return _deep_merge(DEFAULT_SPEC, document["spec"]), source_sha256(candidate)


def resolve_device_spec(
    common_spec: Mapping[str, Any],
    *,
    platform: str,
    hostname: str,
) -> dict[str, Any]:
    """Resolve common, platform, then device overrides deterministically."""
    spec = deepcopy(dict(common_spec))
    platform_overrides = spec.pop("platform_overrides", {})
    device_overrides = spec.pop("device_overrides", {})
    if isinstance(platform_overrides, Mapping):
        selected = platform_overrides.get(platform, {})
        if not isinstance(selected, Mapping):
            raise LabTransformError(f"platform override must be a mapping: {platform}")
        spec = _deep_merge(spec, selected)
    if isinstance(device_overrides, Mapping):
        selected = device_overrides.get(hostname, {})
        if not isinstance(selected, Mapping):
            raise LabTransformError(f"device override must be a mapping: {hostname}")
        spec = _deep_merge(spec, selected)
    return spec


def environment_credential_resolver(reference: str) -> str:
    """Resolve a lab-only secret reference from the process environment."""
    value = os.environ.get(reference)
    if value is None or not value:
        raise LabTransformError(f"unresolved credential reference: {reference}")
    if any(character.isspace() for character in value):
        raise LabTransformError(
            f"credential reference contains unsupported whitespace: {reference}"
        )
    return value


def _action(spec: Mapping[str, Any], *path: str, default: str = "remove") -> str:
    current: Any = spec
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    if not isinstance(current, Mapping):
        return default
    return str(current.get("action", default))


def _parse_safe_ntp_options(option_text: str) -> tuple[dict[str, Any], list[str]]:
    tokens = option_text.split() if option_text else []
    parsed: dict[str, Any] = {}
    unknown: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if lowered == "prefer":
            parsed["prefer"] = True
            index += 1
            continue
        if lowered in {"use-vrf", "minpoll", "maxpoll"} and index + 1 < len(tokens):
            key = {"use-vrf": "use_vrf", "minpoll": "minpoll", "maxpoll": "maxpoll"}[lowered]
            value: Any = tokens[index + 1]
            if lowered in {"minpoll", "maxpoll"}:
                try:
                    value = int(value)
                except ValueError:
                    unknown.extend(tokens[index:index + 2])
                    index += 2
                    continue
            parsed[key] = value
            index += 2
            continue
        unknown.append(token)
        index += 1
    return parsed, unknown


def _normalize_ntp_server(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"address": value, "inherit_options": True}
    if not isinstance(value, Mapping):
        raise LabTransformError("NTP server entry must be a string or mapping")
    result = dict(value)
    result.setdefault("inherit_options", True)
    return result


def _render_ntp_line(server: Mapping[str, Any], inherited: Mapping[str, Any]) -> str:
    options = dict(inherited) if server.get("inherit_options", True) else {}
    for key in ("prefer", "use_vrf", "minpoll", "maxpoll"):
        if key in server:
            options[key] = server[key]
    parts = ["ntp", "server", str(server["address"])]
    if options.get("prefer"):
        parts.append("prefer")
    if options.get("use_vrf"):
        parts.extend(["use-vrf", str(options["use_vrf"])])
    if "minpoll" in options:
        parts.extend(["minpoll", str(options["minpoll"])])
    if "maxpoll" in options:
        parts.extend(["maxpoll", str(options["maxpoll"])])
    return " ".join(parts)


def _build_ntp_replacements(
    existing: list[dict[str, Any]],
    ntp_spec: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    action = str(ntp_spec.get("action", "remove"))
    if action == "remove":
        return [], []
    if action == "preserve":
        return [entry["line"] for entry in existing if entry.get("line")], []

    replacements = [_normalize_ntp_server(value) for value in ntp_spec.get("servers", [])]
    if not replacements:
        raise LabTransformError(f"NTP {action} requires at least one server")

    usable = [entry for entry in existing if entry.get("address")]
    explicit: dict[int, int] = {}
    used_existing: set[int] = set()
    for replacement_index, replacement in enumerate(replacements):
        source_address = replacement.get("source_address")
        if source_address is None:
            continue
        matches = [
            index for index, entry in enumerate(usable)
            if entry["address"] == source_address and index not in used_existing
        ]
        if len(matches) != 1:
            raise LabTransformCardinalityError(
                f"NTP source_address must match exactly one source server: {source_address}"
            )
        explicit[replacement_index] = matches[0]
        used_existing.add(matches[0])

    remaining_existing = [index for index in range(len(usable)) if index not in used_existing]
    remaining_replacements = [index for index in range(len(replacements)) if index not in explicit]
    if action == "replace" and len(remaining_replacements) > len(remaining_existing):
        fully_specified_without_source = not usable and all(
            replacement.get("inherit_options") is False
            for replacement in replacements
        )
        if not fully_specified_without_source:
            raise LabTransformCardinalityError(
                "NTP replacement count exceeds source server count; use inject or "
                "set inherit_options: false when generating without source semantics"
            )
    for replacement_index, existing_index in zip(remaining_replacements, remaining_existing):
        explicit[replacement_index] = existing_index

    warnings: list[dict[str, str]] = []
    rendered: list[str] = []
    for index, replacement in enumerate(replacements):
        existing_entry = usable[explicit[index]] if index in explicit else None
        inherited: dict[str, Any] = {}
        if existing_entry is not None and replacement.get("inherit_options", True):
            inherited = dict(existing_entry["safe_options"])
            if existing_entry["unknown_options"]:
                warnings.append({
                    "id": "NTP_OPTIONS_NOT_INHERITED",
                    "message": "NTP source contained options outside the safe inheritance allowlist.",
                })
        elif replacement.get("inherit_options", True):
            raise LabTransformIncompleteSourceError(
                "NTP option inheritance requested but source semantics are unavailable"
            )
        rendered.append(_render_ntp_line(replacement, inherited))
    return rendered, warnings


def _non_empty_list(spec: Mapping[str, Any], key: str, label: str) -> list[Any]:
    values = spec.get(key, [])
    if not isinstance(values, list) or not values:
        raise LabTransformError(f"{label} replace requires a non-empty {key} list")
    return values


def _valid_token(value: Any, label: str) -> str:
    token = str(value or "").strip()
    if not token or any(character.isspace() for character in token):
        raise LabTransformError(f"{label} must be a non-empty token")
    return token


def _render_logging(spec: Mapping[str, Any]) -> list[list[str]]:
    action = str(spec.get("action", "remove"))
    if action != "replace":
        return []
    rendered: list[list[str]] = []
    for item in _non_empty_list(spec, "servers", "logging"):
        server = {"address": item} if isinstance(item, str) else dict(item)
        parts = ["logging", "server", _valid_token(server.get("address"), "logging address")]
        if server.get("severity") is not None:
            parts.append(_valid_token(server["severity"], "logging severity"))
        if server.get("use_vrf"):
            parts.extend(["use-vrf", _valid_token(server["use_vrf"], "logging VRF")])
        if server.get("port") is not None:
            parts.extend(["port", str(int(server["port"]))])
        rendered.append([" ".join(parts)])
    if spec.get("source_interface"):
        rendered.append([
            "logging source-interface "
            + _valid_token(spec["source_interface"], "logging source interface")
        ])
    return rendered


def _render_dns(spec: Mapping[str, Any]) -> list[list[str]]:
    action = str(spec.get("action", "remove"))
    if action != "replace":
        return []
    rendered: list[list[str]] = []
    for item in _non_empty_list(spec, "name_servers", "DNS"):
        server = {"address": item} if isinstance(item, str) else dict(item)
        parts = ["ip", "name-server", _valid_token(server.get("address"), "DNS address")]
        if server.get("use_vrf"):
            parts.extend(["use-vrf", _valid_token(server["use_vrf"], "DNS VRF")])
        rendered.append([" ".join(parts)])
    if spec.get("domain_name"):
        rendered.append(["ip domain-name " + _valid_token(spec["domain_name"], "DNS domain")])
    if spec.get("lookup_vrf"):
        rendered.append(["ip domain-lookup use-vrf " + _valid_token(spec["lookup_vrf"], "DNS lookup VRF")])
    if spec.get("source_interface"):
        rendered.append([
            "ip domain-lookup source-interface "
            + _valid_token(spec["source_interface"], "DNS source interface")
        ])
    return rendered


def _render_aaa(
    spec: Mapping[str, Any],
    credential_resolver: Callable[[str], str],
) -> list[list[str]]:
    action = str(spec.get("action", "remove"))
    if action != "replace":
        return []
    servers = _non_empty_list(spec, "servers", "AAA")
    rendered: list[list[str]] = []
    names_by_protocol: dict[str, list[str]] = {"tacacs": [], "radius": []}
    for item in servers:
        if not isinstance(item, Mapping):
            raise LabTransformError("AAA server must be a mapping")
        protocol = str(item.get("protocol", "")).lower()
        if protocol not in names_by_protocol:
            raise LabTransformError(f"unsupported AAA protocol: {protocol}")
        address = _valid_token(item.get("address"), "AAA server address")
        reference = _valid_token(item.get("credential_ref"), "AAA credential_ref")
        secret = credential_resolver(reference)
        rendered.append([f"{protocol}-server host {address} key 0 {secret}"])
        names_by_protocol[protocol].append(address)
    for protocol in ("tacacs", "radius"):
        names = names_by_protocol[protocol]
        if not names:
            continue
        group = _valid_token(
            spec.get(f"{protocol}_group", f"LAB_{protocol.upper()}"),
            f"AAA {protocol} group",
        )
        nxos_protocol = "tacacs+" if protocol == "tacacs" else "radius"
        rendered.append([
            f"aaa group server {nxos_protocol} {group}",
            *[f"  server {name}" for name in names],
        ])
        if bool(spec.get("configure_default_login", True)):
            rendered.append([f"aaa authentication login default group {group} local"])
    return rendered


def _render_snmp(
    spec: Mapping[str, Any],
    credential_resolver: Callable[[str], str],
) -> list[list[str]]:
    action = str(spec.get("action", "remove"))
    if action != "replace":
        return []
    communities = spec.get("communities", [])
    trap_hosts = spec.get("trap_hosts", [])
    if not isinstance(communities, list) or not isinstance(trap_hosts, list):
        raise LabTransformError("SNMP communities and trap_hosts must be lists")
    if not communities and not trap_hosts:
        raise LabTransformError("SNMP replace requires a community or trap host")
    rendered: list[list[str]] = []
    for item in communities:
        if not isinstance(item, Mapping):
            raise LabTransformError("SNMP community must be a mapping")
        reference = _valid_token(item.get("credential_ref"), "SNMP credential_ref")
        group = _valid_token(item.get("group", "network-operator"), "SNMP group")
        rendered.append([
            f"snmp-server community {credential_resolver(reference)} group {group}"
        ])
    for item in trap_hosts:
        if not isinstance(item, Mapping):
            raise LabTransformError("SNMP trap host must be a mapping")
        address = _valid_token(item.get("address"), "SNMP trap address")
        reference = _valid_token(item.get("community_ref"), "SNMP community_ref")
        version = str(item.get("version", "2c"))
        if version not in {"1", "2c"}:
            raise LabTransformError(f"unsupported SNMP trap version: {version}")
        parts = [
            "snmp-server", "host", address, "traps", "version", version,
            credential_resolver(reference),
        ]
        rendered.append([" ".join(parts)])
        if item.get("use_vrf"):
            rendered.append([
                "snmp-server host " + address + " use-vrf "
                + _valid_token(item["use_vrf"], "SNMP VRF")
            ])
    if spec.get("source_interface"):
        rendered.append([
            "snmp-server source-interface traps "
            + _valid_token(spec["source_interface"], "SNMP source interface")
        ])
    return rendered


def _render_access_class(spec: Mapping[str, Any]) -> tuple[list[list[str]], str | None]:
    action = str(spec.get("action", "remove"))
    if action != "replace":
        return [], None
    name = _valid_token(spec.get("name"), "management access-list name")
    rules = _non_empty_list(spec, "rules", "management access class")
    body: list[str] = []
    for index, item in enumerate(rules, start=1):
        if not isinstance(item, Mapping):
            raise LabTransformError("management access-list rule must be a mapping")
        sequence = int(item.get("sequence", index * 10))
        decision = str(item.get("action", "")).lower()
        if decision not in {"permit", "deny"}:
            raise LabTransformError(f"invalid management access-list action: {decision}")
        source = _valid_token(item.get("source"), "management access-list source")
        body.append(f"  {sequence} {decision} ip {source} any")
    return [[f"ip access-list {name}", *body]], name


def scan_nxos_lab_config(
    text: str,
    *,
    bootstrap_action: str = "preserve",
    allowed_management_subnet: str | None = None,
    require_management_mapping: bool = False,
) -> list[dict[str, str]]:
    """Classify secret and connectivity risks without retaining source values."""
    active_lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("!", "#"))
    ]
    findings: list[dict[str, str]] = []

    def add(rule_id: str, level: str, summary: str) -> None:
        findings.append({"id": rule_id, "level": level, "summary": summary})

    if any(_MASK_MARKER_RE.search(line) for line in active_lines):
        add("LAB_MASK_PLACEHOLDER_ACTIVE", "BLOCK", "An active command contains a masked placeholder.")
    if _PRIVATE_KEY_RE.search(text):
        add("LAB_PRIVATE_KEY_PRESENT", "BLOCK", "Private key material remains in transformed config.")
    if any(_CRYPTO_RE.match(line) for line in active_lines):
        add("LAB_CRYPTO_CREDENTIAL_PRESENT", "BLOCK", "Credential-bearing crypto configuration remains.")
    credential_users = {
        match.group(1).casefold()
        for line in active_lines
        if (match := _USERNAME_CREDENTIAL_RE.match(line))
    }
    orphan_passphrase_users = {
        match.group(1).casefold()
        for line in active_lines
        if (match := _USERNAME_PASSPHRASE_RE.match(line))
        and match.group(1).casefold() not in credential_users
    }
    if orphan_passphrase_users:
        add(
            "LAB_ORPHAN_USERNAME_PASSPHRASE",
            "BLOCK",
            "A username passphrase policy remains without its credential command.",
        )
    management_addresses: list[str] = []
    for section in split_config_sections(text):
        if not section or section[0].strip().lower() != "interface mgmt0":
            continue
        for line in section[1:]:
            match = re.match(r"^\s*ip address\s+(\S+)", line, re.IGNORECASE)
            if match:
                management_addresses.append(match.group(1))
    if management_addresses and require_management_mapping and not allowed_management_subnet:
        add(
            "LAB_MANAGEMENT_SUBNET_UNVERIFIED",
            "BLOCK",
            "Management address exists but no lab management subnet was fixed.",
        )
    if management_addresses and allowed_management_subnet:
        try:
            management_network = ipaddress.ip_network(
                allowed_management_subnet, strict=False
            )
            outside = [
                value for value in management_addresses
                if ipaddress.ip_interface(value).ip not in management_network
            ]
        except ValueError:
            outside = list(management_addresses)
        if outside:
            add(
                "LAB_MANAGEMENT_ADDRESS_OUTSIDE_SUBNET",
                "BLOCK",
                "A management address is outside the fixed lab management subnet.",
            )

    categories = (
        ("LAB_MANAGEMENT_CHANGE", "WARN", ("interface mgmt0", "ip route ")),
        ("LAB_LOCAL_USER_CHANGE", "WARN", ("username ",)),
        ("LAB_AAA_CHANGE", "WARN", ("aaa ", "tacacs-server ", "radius-server ")),
        ("LAB_SNMP_CHANGE", "WARN", ("snmp-server ",)),
        ("LAB_VTY_ACCESS_CHANGE", "WARN", ("line vty", "access-class ", "ip access-list ")),
        ("LAB_NTP_CHANGE", "INFO", ("ntp server ",)),
        ("LAB_LOGGING_CHANGE", "INFO", ("logging server ",)),
        ("LAB_DNS_CHANGE", "INFO", ("ip name-server ", "ip domain-")),
        ("LAB_HOSTNAME_CHANGE", "INFO", ("hostname ",)),
    )
    for rule_id, level, prefixes in categories:
        if any(line.lower().startswith(prefix) for line in active_lines for prefix in prefixes):
            add(rule_id, level, "Transformed config changes this connectivity or service category.")
    add(
        {
            "preserve": "BOOTSTRAP_CREDENTIAL_PRESERVED",
            "replace-credential": "BOOTSTRAP_CREDENTIAL_REPLACEMENT",
            "remove-after-primary-ready": "BOOTSTRAP_CREDENTIAL_REMOVAL",
        }.get(bootstrap_action, "BOOTSTRAP_ACTION_UNKNOWN"),
        "WARN",
        "Bootstrap credential handling requires post-apply connectivity verification.",
    )
    return findings


def _lab_user_lines(
    spec: Mapping[str, Any],
    credential_resolver: Callable[[str], str],
) -> tuple[list[str], str | None, str | None, list[dict[str, str]]]:
    users = spec.get("lab_users", {}).get("users", [])
    if not isinstance(users, list):
        raise LabTransformError("lab_users.users must be a list")
    names: set[str] = set()
    primary: list[str] = []
    primary_password_ref: str | None = None
    lines: list[str] = []
    for user in users:
        if not isinstance(user, Mapping):
            raise LabTransformError("lab user must be a mapping")
        username = str(user.get("username", ""))
        if not _VALID_USERNAME_RE.fullmatch(username):
            raise LabTransformError(f"invalid lab username: {username}")
        folded = username.casefold()
        if folded in names:
            raise LabTransformError(f"duplicate lab username: {username}")
        names.add(folded)
        if user.get("primary") is True:
            primary.append(username)
        authentication = user.get("authentication", {})
        reference = str(authentication.get("password_ref", ""))
        if user.get("primary") is True:
            primary_password_ref = reference
        password = credential_resolver(reference)
        role = {
            "admin": "network-admin",
            "read-only": "network-operator",
        }.get(str(user.get("privilege")))
        if role is None:
            raise LabTransformError(f"unsupported NX-OS lab privilege: {user.get('privilege')}")
        lines.append(f"username {username} password 0 {password} role {role}")
    if users and len(primary) != 1:
        raise LabTransformError("lab_users requires exactly one primary user")

    bootstrap = spec.get("bootstrap_user", {})
    bootstrap_action = str(bootstrap.get("action", "preserve"))
    warnings: list[dict[str, str]] = []
    if bootstrap_action == "preserve":
        if "admin" in names:
            raise LabTransformBootstrapConflictError(
                "lab user admin conflicts with preserved bootstrap admin"
            )
        warnings.append({
            "id": "BOOTSTRAP_CREDENTIAL_PRESERVED",
            "message": "Containerlab bootstrap admin credential is preserved.",
        })
    elif bootstrap_action == "replace-credential":
        authentication = bootstrap.get("authentication", {})
        reference = str(authentication.get("password_ref", ""))
        password = credential_resolver(reference)
        lines = [line for line in lines if not line.lower().startswith("username admin ")]
        lines.append(f"username admin password 0 {password} role network-admin")
        warnings.append({
            "id": "BOOTSTRAP_CREDENTIAL_REPLACEMENT",
            "message": "Bootstrap admin credential replacement requires reconnect verification.",
        })
    elif bootstrap_action == "remove-after-primary-ready" and not primary:
        raise LabTransformError(
            "remove-after-primary-ready requires one primary lab user"
        )
    return lines, primary[0] if primary else None, primary_password_ref, warnings


def transform_nxos_lab_config(
    text: str,
    spec: Mapping[str, Any],
    *,
    credential_resolver: Callable[[str], str] = environment_credential_resolver,
) -> LabTransformResult:
    """Apply the NX-OS safety adapter after structural lab conversion."""
    for service in ("logging", "dns", "aaa", "snmp"):
        service_action = _action(spec, "services", service)
        if service_action not in {"remove", "replace", "preserve"}:
            raise LabTransformError(f"invalid NX-OS {service} action: {service_action}")
    access_action = _action(spec, "access_control", "management_access_class")
    if access_action not in {"remove", "replace", "preserve"}:
        raise LabTransformError(f"invalid NX-OS management access class action: {access_action}")
    sections = split_config_sections(text)
    ntp_entries: list[dict[str, Any]] = []
    first_indexes: dict[str, int] = {}
    removed = {name: 0 for name in ("ntp", "logging", "dns", "aaa", "snmp", "crypto", "users", "access_class")}

    for index, section in enumerate(sections):
        if not section:
            continue
        header = section[0].strip()
        match = _NTP_SERVER_RE.match(header)
        if match:
            safe_options, unknown_options = _parse_safe_ntp_options(match.group(2) or "")
            ntp_entries.append({
                "line": header,
                "address": match.group(1),
                "safe_options": safe_options,
                "unknown_options": unknown_options,
            })
        elif _REDACTED_NTP_RE.match(header):
            ntp_entries.append({
                "line": "",
                "address": None,
                "safe_options": {},
                "unknown_options": [],
            })

    ntp_spec = spec.get("services", {}).get("ntp", {"action": "remove"})
    ntp_lines, warnings = _build_ntp_replacements(ntp_entries, ntp_spec)
    user_lines, primary_username, primary_password_ref, user_warnings = _lab_user_lines(
        spec, credential_resolver
    )
    warnings.extend(user_warnings)

    service_specs = spec.get("services", {})
    replacement_sections = {
        "logging": _render_logging(service_specs.get("logging", {})),
        "dns": _render_dns(service_specs.get("dns", {})),
        "aaa": _render_aaa(service_specs.get("aaa", {}), credential_resolver),
        "snmp": _render_snmp(service_specs.get("snmp", {}), credential_resolver),
    }
    access_sections, access_name = _render_access_class(
        spec.get("access_control", {}).get("management_access_class", {})
    )
    source_access_lists: set[str] = set()
    if access_action != "preserve":
        for section in sections:
            if section and _LINE_VTY_RE.match(section[0].strip()):
                for line in section[1:]:
                    access_match = _ACCESS_CLASS_NAME_RE.match(line)
                    if access_match:
                        source_access_lists.add(access_match.group(1).casefold())

    output: list[list[str]] = []
    for section in sections:
        if not section:
            continue
        header = section[0].strip()
        category: str | None = None
        if _NTP_CATEGORY_RE.match(header) or _REDACTED_NTP_RE.match(header):
            category = "ntp"
        elif _AAA_RE.match(header):
            category = "aaa"
        elif _SNMP_RE.match(header):
            category = "snmp"
        elif _LOGGING_REMOTE_RE.match(header):
            category = "logging"
        elif _DNS_RE.match(header):
            category = "dns"
        elif _CRYPTO_RE.match(header):
            category = "crypto"
        elif _USERNAME_RE.match(header):
            category = "users"
        elif (
            access_action != "preserve"
            and (acl_match := _IP_ACCESS_LIST_RE.match(header))
            and acl_match.group(1).casefold() in source_access_lists
        ):
            category = "access_class"

        remove_category = False
        if category == "ntp":
            remove_category = str(ntp_spec.get("action", "remove")) != "preserve"
        elif category in {"aaa", "snmp", "logging", "dns"}:
            remove_category = _action(spec, "services", category) != "preserve"
        elif category == "crypto":
            remove_category = True
        elif category == "users":
            remove_category = _action(spec, "source_local_users") != "preserve"
        elif category == "access_class":
            remove_category = True

        if remove_category and category is not None:
            first_indexes.setdefault(category, len(output))
            removed[category] += 1
            continue

        if _LINE_VTY_RE.match(header) and _action(
            spec, "access_control", "management_access_class"
        ) != "preserve":
            filtered = [section[0]]
            for line in section[1:]:
                if _ACCESS_CLASS_RE.match(line):
                    removed["access_class"] += 1
                    continue
                filtered.append(line)
            section = filtered
            if access_action == "replace" and access_name:
                section.append(f"  access-class {access_name} in")
        output.append(section)

    generated: list[tuple[int, list[str]]] = []
    if ntp_lines:
        index = first_indexes.get("ntp", len(output))
        generated.extend((index + offset, [line]) for offset, line in enumerate(ntp_lines))
    if user_lines:
        index = first_indexes.get("users", len(output))
        generated.extend((index + offset, [line]) for offset, line in enumerate(user_lines))
    for category in ("logging", "dns", "aaa", "snmp"):
        sections_to_add = replacement_sections[category]
        if sections_to_add:
            index = first_indexes.get(category, len(output))
            generated.extend(
                (index + offset, section)
                for offset, section in enumerate(sections_to_add)
            )
    if access_sections:
        index = first_indexes.get("access_class", len(output))
        generated.extend(
            (index + offset, section)
            for offset, section in enumerate(access_sections)
        )
    for index, section in sorted(generated, key=lambda item: item[0], reverse=True):
        output.insert(min(index, len(output)), section)

    transformed = join_config_sections(output)
    if _NTP_CATEGORY_RE.search(transformed) and str(ntp_spec.get("action")) == "remove":
        raise LabTransformError("NTP removal validation failed")
    if _MASK_MARKER_RE.search("\n".join(
        line for line in transformed.splitlines()
        if line.lower().startswith(("ntp ", "username ", "aaa ", "snmp-server "))
    )):
        raise LabTransformIncompleteSourceError(
            "typed mask remains in a command that would be sent to NX-OS"
        )

    stats = {f"removed_{key}": value for key, value in removed.items()}
    stats["generated_ntp"] = len(ntp_lines)
    stats["generated_lab_users"] = len(user_lines)
    for category in ("logging", "dns", "aaa", "snmp"):
        stats[f"generated_{category}"] = len(replacement_sections[category])
    stats["generated_access_class"] = len(access_sections)
    stats["warning_count"] = len(warnings)
    bootstrap_action = str(spec.get("bootstrap_user", {}).get("action", "preserve"))
    risk_findings = scan_nxos_lab_config(
        transformed,
        bootstrap_action=bootstrap_action,
        allowed_management_subnet=spec.get("management", {}).get("ipv4_subnet"),
        require_management_mapping=True,
    )
    blocking = [finding for finding in risk_findings if finding["level"] == "BLOCK"]
    if blocking:
        raise LabTransformError(
            "lab transform risk scan blocked output: "
            + ", ".join(finding["id"] for finding in blocking)
        )
    if primary_username:
        post_apply_username = primary_username
        post_apply_password_ref = primary_password_ref
    elif bootstrap_action == "replace-credential":
        post_apply_username = "admin"
        post_apply_password_ref = str(
            spec.get("bootstrap_user", {}).get("authentication", {}).get("password_ref")
        )
    else:
        post_apply_username = "admin"
        post_apply_password_ref = None
    return LabTransformResult(
        text=transformed,
        stats=stats,
        warnings=tuple(warnings),
        risk_findings=tuple(risk_findings),
        primary_username=primary_username,
        post_apply_username=post_apply_username,
        post_apply_password_ref=post_apply_password_ref,
        bootstrap_action=bootstrap_action,
    )


LAB_TRANSFORM_ADAPTERS: dict[
    str, Callable[..., LabTransformResult]
] = {
    "nxos": transform_nxos_lab_config,
}


def transform_lab_config(
    text: str,
    spec: Mapping[str, Any],
    *,
    platform: str,
    credential_resolver: Callable[[str], str] = environment_credential_resolver,
) -> LabTransformResult:
    """Dispatch through the canonical platform adapter registry."""
    adapter = LAB_TRANSFORM_ADAPTERS.get(platform)
    if adapter is None:
        raise UnsupportedLabPlatformError(
            f"unsupported lab transform platform: {platform}"
        )
    return adapter(text, spec, credential_resolver=credential_resolver)


def build_lab_transform_manifest(
    *,
    parameter_source_sha256: str | None,
    parameter_spec: Mapping[str, Any],
    devices: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a secret-free provenance document for transformed config artifacts."""
    return {
        "api_version": API_VERSION,
        "kind": "LabTransformManifest",
        "spec": {
            "parameter_source_sha256": parameter_source_sha256,
            "resolved_parameter_sha256": canonical_sha256(parameter_spec),
            "devices": devices,
        },
    }


def resolve_lab_transform_manifest(
    path: str | Path,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Validate a transform Manifest and resolve only pinned regular config files."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise LabTransformError(f"lab transform Manifest must be a regular file: {candidate}")
    document = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise LabTransformError("LabTransformManifest must be a YAML mapping")
    validate_document(document, kind="LabTransformManifest")
    root = candidate.parent.resolve()
    resolved: dict[str, Path] = {}
    for device in document["spec"]["devices"]:
        hostname = str(device["hostname"])
        relative = Path(str(device["output_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise LabTransformError(f"unsafe lab config path in Manifest: {relative}")
        config_path = (root / relative).resolve()
        try:
            config_path.relative_to(root)
        except ValueError as exc:
            raise LabTransformError(f"lab config path escapes Manifest root: {relative}") from exc
        if not config_path.is_file() or config_path.is_symlink():
            raise LabTransformError(f"lab config must be a regular file: {config_path}")
        if source_sha256(config_path) != device["output_sha256"]:
            raise LabTransformError(f"lab config hash mismatch: {config_path}")
        if hostname in resolved:
            raise LabTransformError(f"duplicate hostname in LabTransformManifest: {hostname}")
        resolved[hostname] = config_path
    return resolved, document
