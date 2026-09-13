"""Validation and canonical values shared by route inputs and policy consumers."""
from __future__ import annotations

from copy import deepcopy
import ipaddress
from pathlib import Path
import re
from typing import Any

from ..parsing import normalize_interface_name
from ..schema import validate_document

FORWARDING_FIELDS = ("encapsulation", "segment_id", "tunnel_id", "asymmetric")
PATH_FIELDS = ("kind", "next_hop_family", "address", "interface", "next_hop_vrf",
               "next_hop_table_family", *FORWARDING_FIELDS, "admin_distance", "metric")
HOP_FIELDS = PATH_FIELDS[:-2]
COMMAND_FAMILIES = {f"route_{family}_{scope}": family
                    for family in ("ipv4", "ipv6") for scope in ("all_vrfs", "default_vrf", "vrf")}


class RouteInputError(ValueError):
    """Expected input error; callers translate this to the common exit code 2."""
    code = "VALIDATION_ERROR"

    def __init__(self, pointer: str, message: str):
        self.pointer = pointer
        super().__init__(f"{pointer}: {message}")


def command_scope(command_id: str, vrf: str | None = None) -> dict:
    """Validate a declared acquisition scope without inferring it from output."""
    if command_id not in COMMAND_FAMILIES:
        raise RouteInputError("/command_id", "unsupported route command id")
    specific = command_id in ("route_ipv4_vrf", "route_ipv6_vrf")
    if specific:
        if not isinstance(vrf, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", vrf) or vrf.lower() == "all":
            raise RouteInputError("/vrf", "specific VRF command requires a VRF name other than all")
    elif vrf is not None:
        raise RouteInputError("/vrf", "vrf is only allowed for a specific VRF command id")
    return dict(command_id=command_id, family=COMMAND_FAMILIES[command_id],
                vrf=vrf if specific else "default" if command_id.endswith("default_vrf") else None)


def canonical_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Stable lowercase hexadecimal IPv6, including mapped addresses, across Python versions."""
    if ip.version == 4:
        return str(ip)
    groups = [f"{(int(ip) >> shift) & 0xffff:x}" for shift in range(112, -1, -16)]
    best_start, best_length, index = 0, 0, 0
    while index < len(groups):
        start = index
        while index < len(groups) and groups[index] == "0":
            index += 1
        if index - start > best_length:
            best_start, best_length = start, index - start
        index += 1
    if best_length < 2:
        return ":".join(groups)
    return ":".join(groups[:best_start]) + "::" + ":".join(groups[best_start + best_length:])


def canonical_prefix(value: str, family: str, pointer: str = "/prefix") -> str:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise RouteInputError(pointer, "expected a valid network address and prefix length") from exc
    if family != f"ipv{network.version}":
        raise RouteInputError(pointer, "prefix and address family disagree")
    return f"{canonical_address(network.network_address)}/{network.prefixlen}"


def canonical_interface(value: str) -> str:
    # Reuse shared aliases; restrict accepted syntax before removing whitespace.
    if not re.fullmatch(r"(?:Eth(?:ernet)?\d+(?:/\d+){0,2}(?:\.\d+)?|[Vv]lan\d+|[Ll]o(?:opback)?\d+|[Pp]o(?:rt-channel)?\d+|[Mm]gmt\d+|Null0|[Nn]ve\d+)", value):
        raise RouteInputError("/interface", "unsupported interface syntax")
    return normalize_interface_name(value, {}, device_type="nxos")


def canonical_path(value: dict[str, Any], *, attributes: bool = True) -> dict[str, Any]:
    path = deepcopy(value)
    path.setdefault("next_hop_table_family", None)
    for field in FORWARDING_FIELDS:
        path.setdefault(field, None)
    if any(path[k] is not None for k in FORWARDING_FIELDS):
        if (path['encapsulation'] != 'vxlan' or type(path['segment_id']) is not int
                or not 1 <= path['segment_id'] <= 16777215 or path['asymmetric'] is not None and path['asymmetric'] is not True):
            raise RouteInputError('/path', 'invalid VXLAN forwarding attributes')
        if path['tunnel_id'] is not None:
            if not isinstance(path['tunnel_id'], str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{1,8}', path['tunnel_id']):
                raise RouteInputError('/tunnel_id', 'expected a 1 to 8 digit hexadecimal tunnel identifier')
            path['tunnel_id'] = hex(int(path['tunnel_id'], 16))
    address = path["address"]
    family = path["next_hop_family"]
    if address is None:
        if family is not None or path["kind"] == "ip":
            raise RouteInputError("/address", "IP next-hop requires address and its family")
    else:
        if "%" in address:
            raise RouteInputError("/address", "scope and reference VRF must be separate fields")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise RouteInputError("/address", "invalid next-hop address") from exc
        if family != f"ipv{ip.version}":
            raise RouteInputError("/next_hop_family", "address family disagrees with next-hop address")
        if ip.version == 6 and ip.is_link_local and not path["interface"]:
            raise RouteInputError("/interface", "IPv6 link-local next-hop requires interface")
        path["address"] = canonical_address(ip)
    if path["interface"] is not None:
        path["interface"] = canonical_interface(path["interface"])
    if path["kind"] == "discard" and (address is not None or path["interface"] != "Null0"):
        raise RouteInputError("/kind", "discard requires address null and interface Null0")
    if path["kind"] in ("connected", "local") and path["interface"] is None:
        raise RouteInputError("/interface", "connected/local requires an interface")
    if path["interface"] == "Null0" and path["kind"] != "discard":
        raise RouteInputError("/kind", "Null0 must be a discard next-hop")
    for field in ("admin_distance", "metric") if attributes else ():
        if type(path[field]) is not int or path[field] < 0:
            raise RouteInputError("/" + field, "expected a non-negative integer")
    return path


def path_key(path: dict[str, Any], *, attributes: bool = True) -> tuple:
    return tuple(path.get(k) for k in (PATH_FIELDS if attributes else HOP_FIELDS))


def _paths(values, *, attributes=True):
    normalized, seen = [], set()
    for value in values:
        path = canonical_path(value, attributes=attributes)
        key = path_key(path, attributes=attributes)
        if key in seen:
            raise RouteInputError("/paths", "duplicate canonical path")
        seen.add(key)
        normalized.append(path)
    return normalized


def validate_policy(document: dict[str, Any], *, selected_scopes: set[tuple] | None = None) -> dict[str, Any]:
    validate_document(document, kind="RouteDiffPolicy")
    result = deepcopy(document)
    resource_sets: dict[str, set] = {}
    rule_ids = set()
    for group in ("required_routes", "exclusions", "expected_changes"):
        seen = resource_sets[group] = set()
        for rule in result["spec"].get(group, []):
            rule["prefix"] = canonical_prefix(rule["prefix"], rule["family"])
            identity = tuple(rule[k] for k in ("device", "vrf", "family", "prefix"))
            if identity in seen:
                raise RouteInputError("/spec/" + group, "duplicate resource")
            seen.add(identity)
            if selected_scopes is not None and identity[:3] not in selected_scopes:
                raise RouteInputError("/spec/" + group, "resource is outside selected scopes")
            if "expected_next_hops" in rule:
                hops = rule["expected_next_hops"]
                hops["paths"] = _paths(hops["paths"], attributes=False)
            if group != "expected_changes":
                continue
            if rule["id"] in rule_ids:
                raise RouteInputError("/spec/expected_changes", "duplicate rule id")
            rule_ids.add(rule["id"])
            for side in ("before", "after"):
                value = rule[side]
                if value is not None:
                    value["prefix"] = canonical_prefix(value["prefix"], rule["family"])
                    if value["prefix"] != rule["prefix"]:
                        raise RouteInputError("/spec/expected_changes/" + side, "route prefix disagrees with resource")
                    value["paths"] = _paths(value["paths"])
            def projected(side):
                return None if rule[side] is None else {path_key(p) for p in rule[side]["paths"]}
            if projected("before") == projected("after"):
                raise RouteInputError("/spec/expected_changes", "expected change has no change")
    if resource_sets["exclusions"] & (resource_sets["required_routes"] | resource_sets["expected_changes"]):
        raise RouteInputError("/spec/exclusions", "excluded resource is also required or expected")
    return result


def validate_source_map(document: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    validate_document(document, kind="RouteDiffSourceMap")
    result = deepcopy(document)
    hosts, assigned = set(), {}
    for host in result["spec"]["hosts"]:
        if host["host"] in hosts:
            raise RouteInputError("/spec/hosts", "duplicate host")
        hosts.add(host["host"])
        for side in ("before", "after"):
            for source in host[side]:
                if "command_id" in source:
                    command_scope(source["command_id"], source.get("vrf"))
                start, end = source.get("start_line", 1), source.get("end_line", float("inf"))
                if start > end:
                    raise RouteInputError("/spec/hosts", "start_line is greater than end_line")
                resolved = (base_dir / source["path"]).resolve()
                key = (side, resolved)
                if any(start <= b and a <= end for a, b in assigned.get(key, [])):
                    raise RouteInputError("/spec/hosts", "source intervals overlap within a comparison side")
                assigned.setdefault(key, []).append((start, end))
    return result
