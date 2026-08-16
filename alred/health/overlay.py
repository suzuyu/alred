"""Canonical NX-OS Overlay configuration parser and change discovery."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import ipaddress
import re
from typing import Any, Mapping

from ..schema import API_VERSION, validate_document


OVERLAY_PARSER_VERSION = "1.0"
EVPN_CONTROL_PLANE_PARSER_VERSION = "1.0"


class OverlayDiscoveryError(ValueError):
    """Raised when Overlay state cannot be compared safely."""

    code = "PARSER_ERROR"


def _blocks(lines: list[str], pattern: str) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []
    compiled = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = compiled.match(line)
        if match:
            if current_name is not None:
                result.append((current_name, current_lines))
            current_name = match.group(1)
            current_lines = []
        elif current_name is not None:
            if line and not line.startswith(" "):
                result.append((current_name, current_lines))
                current_name = None
                current_lines = []
            else:
                current_lines.append(line)
    if current_name is not None:
        result.append((current_name, current_lines))
    return result


def parse_bgp_peer_config(body: list[str]) -> dict[str, Any]:
    """Resolve BGP peer templates and neighbors without inferring missing values."""
    templates: dict[str, Any] = {}
    neighbors: dict[str, Any] = {}
    cluster_id: str | None = None
    current_kind: str | None = None
    current_name: str | None = None
    current_af: str | None = None

    def entry(container: dict[str, Any], name: str) -> dict[str, Any]:
        return container.setdefault(
            name, {"inherited_peer_templates": [], "address_families": {}}
        )

    for line in body:
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 2 and (match := re.match(r"cluster-id\s+(\S+)$", stripped)):
            cluster_id = match.group(1)
            continue
        if indent == 2 and (match := re.match(r"template peer\s+(\S+)$", stripped)):
            current_kind, current_name, current_af = "template", match.group(1), None
            entry(templates, current_name)
            continue
        if indent == 2 and (
            match := re.match(r"neighbor\s+(\S+)(?:\s+inherit peer\s+(\S+))?$", stripped)
        ):
            current_kind, current_name, current_af = "neighbor", match.group(1), None
            item = entry(neighbors, current_name)
            if match.group(2) and match.group(2) not in item["inherited_peer_templates"]:
                item["inherited_peer_templates"].append(match.group(2))
            continue
        if current_kind is None or current_name is None:
            continue
        container = templates if current_kind == "template" else neighbors
        item = entry(container, current_name)
        if indent == 4 and (match := re.match(r"inherit peer\s+(\S+)$", stripped)):
            if match.group(1) not in item["inherited_peer_templates"]:
                item["inherited_peer_templates"].append(match.group(1))
            current_af = None
        elif indent == 4 and (
            match := re.match(r"remote-as\s+(\S+)$", stripped)
        ):
            item["remote_as"] = match.group(1)
            current_af = None
        elif indent == 4 and (
            match := re.match(r"update-source\s+(\S+)$", stripped)
        ):
            item["update_source"] = match.group(1)
            current_af = None
        elif indent == 4 and (
            match := re.match(
                r"address-family\s+(l2vpn\s+evpn|ipv[46]\s+unicast)$",
                stripped,
            )
        ):
            current_af = match.group(1).lower().replace(" ", "-")
            item["address_families"].setdefault(current_af, {})
        elif indent == 6 and current_af and stripped == "route-reflector-client":
            item["address_families"].setdefault(current_af, {})[
                "route_reflector_client"
            ] = True

    errors: list[dict[str, Any]] = []
    resolved_templates: dict[str, Any] = {}

    def resolve_template(name: str, chain: tuple[str, ...] = ()) -> dict[str, Any] | None:
        if name in resolved_templates:
            return resolved_templates[name]
        if name in chain:
            errors.append(
                {"code": "RR_TEMPLATE_UNRESOLVED", "template": name, "path": [*chain, name], "reason": "cycle"}
            )
            return None
        raw = templates.get(name)
        if raw is None:
            errors.append(
                {"code": "RR_TEMPLATE_UNRESOLVED", "template": name, "path": [*chain, name], "reason": "not_found"}
            )
            return None
        effective: dict[str, Any] = {"address_families": {}}
        for parent in raw["inherited_peer_templates"]:
            inherited = resolve_template(parent, (*chain, name))
            if inherited is None:
                return None
            for key in ("remote_as", "update_source"):
                if key in inherited:
                    effective[key] = inherited[key]
            for af, values in inherited["address_families"].items():
                effective["address_families"][af] = dict(values)
        for key in ("remote_as", "update_source"):
            if key in raw:
                effective[key] = raw[key]
        for af, values in raw["address_families"].items():
            effective["address_families"].setdefault(af, {}).update(values)
            if values.get("route_reflector_client"):
                effective["address_families"][af]["source"] = f"template:{name}"
        resolved_templates[name] = effective
        return effective

    effective_neighbors: dict[str, Any] = {}
    for neighbor, raw in neighbors.items():
        effective = {
            "inherited_peer_templates": list(raw["inherited_peer_templates"]),
            "address_families": {},
        }
        unresolved = False
        for template in raw["inherited_peer_templates"]:
            inherited = resolve_template(template)
            if inherited is None:
                unresolved = True
                continue
            for key in ("remote_as", "update_source"):
                if key in inherited:
                    effective[key] = inherited[key]
            for af, values in inherited["address_families"].items():
                effective["address_families"][af] = dict(values)
        for key in ("remote_as", "update_source"):
            if key in raw:
                effective[key] = raw[key]
        for af, values in raw["address_families"].items():
            effective["address_families"].setdefault(af, {}).update(values)
            if values.get("route_reflector_client"):
                effective["address_families"][af]["source"] = "direct"
        if unresolved:
            effective["resolution_status"] = "unresolved"
        else:
            effective["resolution_status"] = "resolved"
        effective_neighbors[neighbor] = effective

    return {
        "cluster_id": cluster_id,
        "resolution_status": "unresolved" if errors else "resolved",
        "resolution_errors": list(errors),
        "peer_templates": {
            name: {
                "inherited_peer_templates": list(raw["inherited_peer_templates"]),
                **(resolved_templates.get(name) or {"address_families": {}}),
            }
            for name, raw in templates.items()
        },
        "neighbors": effective_neighbors,
    }


def _parse_bgp_rr_config(body: list[str]) -> dict[str, Any]:
    """Resolve direct and peer-template BGP RR client configuration."""
    peer_config = parse_bgp_peer_config(body)
    cluster_id = peer_config["cluster_id"]
    errors = peer_config["resolution_errors"]
    effective_neighbors = peer_config["neighbors"]

    families: dict[str, Any] = {}
    for family, af_names in {
        "evpn": {"l2vpn-evpn"},
        "underlay": {"ipv4-unicast", "ipv6-unicast"},
    }.items():
        family_neighbors: dict[str, Any] = {}
        for neighbor, values in effective_neighbors.items():
            selected = {
                af: dict(item)
                for af, item in values["address_families"].items()
                if af in af_names and item.get("route_reflector_client")
            }
            if selected or values["resolution_status"] == "unresolved":
                family_neighbors[neighbor] = {
                    "inherited_peer_templates": list(
                        values["inherited_peer_templates"]
                    ),
                    "address_families": selected,
                    "resolution_status": values["resolution_status"],
                }
        families[family] = {
            "configured": any(
                values["address_families"] for values in family_neighbors.values()
            ),
            "cluster_id": cluster_id,
            "resolution_status": "unresolved" if errors else "resolved",
            "resolution_errors": list(errors),
            "peer_templates": {
                name: {
                    "inherited_peer_templates": list(values["inherited_peer_templates"]),
                    "address_families": dict(values["address_families"]),
                }
                for name, values in peer_config["peer_templates"].items()
            },
            "neighbors": family_neighbors,
        }
    return families


def _parse_bgp_neighbor_scopes(body: list[str]) -> dict[str, Any]:
    """Resolve global and per-VRF BGP neighbor definitions."""
    global_body: list[str] = []
    global_template_body: list[str] = []
    vrf_bodies: dict[str, list[str]] = {}
    current_vrf: str | None = None
    current_global_template = False
    for line in body:
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 2 and (match := re.match(r"vrf\s+(\S+)$", stripped)):
            current_vrf = match.group(1)
            current_global_template = False
            vrf_bodies.setdefault(current_vrf, [])
            continue
        if indent == 2:
            current_vrf = None
            current_global_template = bool(
                re.match(r"template peer\s+\S+$", stripped)
            )
        if current_vrf is not None:
            if indent >= 4:
                vrf_bodies[current_vrf].append(line[2:])
            continue
        global_body.append(line)
        if current_global_template:
            global_template_body.append(line)

    scopes: dict[str, Any] = {
        "default": parse_bgp_peer_config(global_body),
    }
    for vrf, vrf_body in sorted(vrf_bodies.items()):
        scopes[vrf] = parse_bgp_peer_config(
            [*global_template_body, *vrf_body]
        )
    return scopes


def parse_evpn_control_plane_running_config(text: str) -> dict[str, Any]:
    """Parse NX-OS EVPN peer and address evidence from running config."""
    lines = text.splitlines()
    interfaces: dict[str, dict[str, Any]] = {}
    for interface, body in _blocks(lines, r"^interface\s+(\S+)\s*$"):
        addresses: list[str] = []
        secondary_addresses: list[str] = []
        source_interface: str | None = None
        for line in body:
            stripped = line.strip()
            if match := re.match(
                r"ip address\s+(\S+)(\s+secondary)?\s*$", stripped
            ):
                try:
                    address = str(ipaddress.ip_interface(match.group(1)))
                    addresses.append(address)
                    if match.group(2):
                        secondary_addresses.append(address)
                except ValueError:
                    continue
            elif match := re.match(r"source-interface\s+(\S+)\s*$", stripped):
                source_interface = match.group(1)
        if addresses or source_interface:
            interfaces[interface.lower()] = {
                "name": interface,
                "addresses": addresses,
                "secondary_addresses": secondary_addresses,
                "source_interface": source_interface,
            }

    vpc_domain = None
    for line in lines:
        if match := re.match(r"^vpc domain\s+(\S+)\s*$", line):
            vpc_domain = match.group(1)
            break

    processes: dict[str, Any] = {}
    for local_as, body in _blocks(lines, r"^router bgp\s+(\S+)\s*$"):
        peer_config = parse_bgp_peer_config(body)
        router_id: str | None = None
        evpn_enabled = False
        for line in body:
            if match := re.match(r"^\s{2}router-id\s+(\S+)\s*$", line):
                router_id = match.group(1)
            elif re.match(r"^\s{2}address-family\s+l2vpn\s+evpn\s*$", line):
                evpn_enabled = True
        evpn_neighbors = {
            neighbor: values
            for neighbor, values in peer_config["neighbors"].items()
            if "l2vpn-evpn" in values.get("address_families", {})
            or values.get("resolution_status") == "unresolved"
        }
        if not evpn_enabled and not evpn_neighbors:
            continue
        processes[local_as] = {
            "evpn_enabled": evpn_enabled,
            "router_id": router_id,
            "cluster_id": peer_config["cluster_id"],
            "resolution_status": peer_config["resolution_status"],
            "resolution_errors": peer_config["resolution_errors"],
            "peer_templates": peer_config["peer_templates"],
            "neighbors": evpn_neighbors,
        }

    nve_source_interfaces = sorted(
        {
            str(values["source_interface"]).lower()
            for name, values in interfaces.items()
            if name.startswith("nve") and values.get("source_interface")
        }
    )
    return {
        "parser_version": EVPN_CONTROL_PLANE_PARSER_VERSION,
        "interfaces": interfaces,
        "nve_source_interfaces": nve_source_interfaces,
        "vpc_domain": vpc_domain,
        "processes": processes,
    }


def parse_overlay_running_config(text: str) -> dict[str, Any]:
    """Parse only explicit Overlay resources; never infer absent configuration."""
    lines = text.splitlines()
    vlans: dict[str, Any] = {}
    for vlan, body in _blocks(lines, r"^vlan\s+(\d+)\s*$"):
        item: dict[str, Any] = {}
        for line in body:
            if match := re.match(r"^\s+name\s+(.+?)\s*$", line):
                item["name"] = match.group(1)
            elif match := re.match(r"^\s+vn-segment\s+(\d+)\s*$", line):
                item["vni"] = int(match.group(1))
        vlans[vlan] = item

    vrfs: dict[str, Any] = {}
    for vrf, body in _blocks(lines, r"^vrf context\s+(\S+)\s*$"):
        item: dict[str, Any] = {"address_families": {}}
        current_af: str | None = None
        for line in body:
            if match := re.match(r"^\s+vni\s+(\d+)(?:\s+l3)?\s*$", line):
                item["l3vni"] = int(match.group(1))
            elif match := re.match(r"^\s+rd\s+(.+?)\s*$", line):
                item["rd"] = match.group(1)
            elif match := re.match(
                r"^\s{2}address-family\s+(ipv[46])\s+unicast\s*$",
                line,
            ):
                current_af = match.group(1)
                item["address_families"][current_af] = {"commands": []}
            elif current_af and re.match(r"^\s{4}\S", line):
                item["address_families"][current_af]["commands"].append(
                    line.strip()
                )
        vrfs[vrf] = item

    svis: dict[str, Any] = {}
    for vlan, body in _blocks(lines, r"^interface\s+Vlan(\d+)\s*$"):
        item: dict[str, Any] = {
            "ipv4_addresses": [],
            "ipv6_addresses": [],
            "ipv6_nd_suppress_ra": False,
            "admin_enabled": True,
        }
        for line in body:
            if match := re.match(r"^\s+vrf member\s+(\S+)\s*$", line):
                item["vrf"] = match.group(1)
            elif match := re.match(r"^\s+mtu\s+(\d+)\s*$", line):
                item["mtu"] = int(match.group(1))
            elif match := re.match(
                r"^\s+ip address\s+(\S+)(?:\s+secondary)?\s*$",
                line,
            ):
                item["ipv4_addresses"].append(match.group(1))
            elif match := re.match(r"^\s+ipv6 address\s+(\S+)\s*$", line):
                address = match.group(1)
                if address.lower().startswith("fe80:"):
                    item["ipv6_link_local"] = address
                elif address == "use-link-local-only":
                    item["ipv6_use_link_local_only"] = True
                else:
                    item["ipv6_addresses"].append(address)
            elif match := re.match(r"^\s+ipv6 link-local\s+(\S+)\s*$", line):
                item["ipv6_link_local"] = match.group(1)
            elif re.match(r"^\s+ipv6 nd suppress-ra\s*$", line):
                item["ipv6_nd_suppress_ra"] = True
            elif re.match(r"^\s+ip forward\s*$", line):
                item["ip_forward"] = True
            elif re.match(r"^\s+fabric forwarding mode anycast-gateway\s*$", line):
                item["anycast_gateway"] = True
            elif re.match(r"^\s+shutdown\s*$", line):
                item["admin_enabled"] = False
            elif re.match(r"^\s+no shutdown\s*$", line):
                item["admin_enabled"] = True
        svis[vlan] = item

    interfaces: dict[str, Any] = {}
    for name, body in _blocks(lines, r"^interface\s+(\S+)\s*$"):
        item: dict[str, Any] = {
            "vrf": "default",
            "ipv4_addresses": [],
            "ipv6_addresses": [],
        }
        for line in body:
            if match := re.match(r"^\s+vrf member\s+(\S+)\s*$", line):
                item["vrf"] = match.group(1)
            elif match := re.match(
                r"^\s+ip address\s+(\S+)(?:\s+secondary)?\s*$",
                line,
            ):
                item["ipv4_addresses"].append(match.group(1))
            elif match := re.match(r"^\s+ipv6 address\s+(\S+)\s*$", line):
                address = match.group(1)
                if not address.lower().startswith("fe80:") and address != "use-link-local-only":
                    item["ipv6_addresses"].append(address)
        if item["ipv4_addresses"] or item["ipv6_addresses"]:
            interfaces[name] = item

    nve: dict[str, Any] = {
        "configured": False,
        "global_ingress_replication_protocol_bgp": False,
        "l2vnis": {},
        "l3vnis": {},
    }
    for _name, body in _blocks(lines, r"^interface\s+(nve\d+)\s*$"):
        nve["configured"] = True
        current_vni: str | None = None
        for line in body:
            if re.match(
                r"^\s+global ingress-replication protocol bgp\s*$",
                line,
            ):
                nve["global_ingress_replication_protocol_bgp"] = True
                current_vni = None
            elif match := re.match(
                r"^\s+member vni\s+(\d+)\s+associate-vrf\s*$",
                line,
            ):
                current_vni = match.group(1)
                nve["l3vnis"][current_vni] = {"associate_vrf": True}
            elif match := re.match(r"^\s+member vni\s+(\d+)\s*$", line):
                current_vni = match.group(1)
                nve["l2vnis"][current_vni] = {}
            elif current_vni in nve["l2vnis"]:
                if match := re.match(
                    r"^\s+ingress-replication protocol\s+(\S+)\s*$",
                    line,
                ):
                    nve["l2vnis"][current_vni][
                        "ingress_replication_protocol"
                    ] = match.group(1)
                elif match := re.match(r"^\s+mcast-group\s+(\S+)\s*$", line):
                    nve["l2vnis"][current_vni]["mcast_group"] = match.group(1)

    bgp_processes: dict[str, Any] = {}
    bgp_neighbor_config: dict[str, Any] = {"processes": {}}
    evpn_bgp_configured = False
    rr_config: dict[str, Any] = {
        "evpn": {"configured": False, "cluster_id": None, "resolution_status": "resolved", "resolution_errors": [], "peer_templates": {}, "neighbors": {}, "processes": {}},
        "underlay": {"configured": False, "cluster_id": None, "resolution_status": "resolved", "resolution_errors": [], "peer_templates": {}, "neighbors": {}, "processes": {}},
    }
    for local_as, body in _blocks(lines, r"^router bgp\s+(\S+)\s*$"):
        bgp_processes[local_as] = {"vrfs": {}}
        bgp_neighbor_config["processes"][local_as] = {
            "vrfs": _parse_bgp_neighbor_scopes(body)
        }
        process_rr = _parse_bgp_rr_config(body)
        for family in ("evpn", "underlay"):
            rr_config[family]["processes"][local_as] = process_rr[family]
            rr_config[family]["configured"] = bool(
                rr_config[family]["configured"] or process_rr[family]["configured"]
            )
            if process_rr[family]["cluster_id"] is not None:
                rr_config[family]["cluster_id"] = process_rr[family]["cluster_id"]
            if process_rr[family]["resolution_status"] == "unresolved":
                rr_config[family]["resolution_status"] = "unresolved"
            rr_config[family]["resolution_errors"].extend(
                process_rr[family]["resolution_errors"]
            )
            rr_config[family]["peer_templates"].update(
                process_rr[family]["peer_templates"]
            )
            rr_config[family]["neighbors"].update(
                process_rr[family]["neighbors"]
            )
        current_vrf: str | None = None
        current_af: str | None = None
        for line in body:
            if re.match(r"^\s{2}address-family\s+l2vpn\s+evpn\s*$", line):
                evpn_bgp_configured = True
                current_vrf = None
                current_af = None
            elif match := re.match(r"^\s{2}vrf\s+(\S+)\s*$", line):
                current_vrf = match.group(1)
                current_af = None
                bgp_processes[local_as]["vrfs"][current_vrf] = {
                    "address_families": {}
                }
            elif current_vrf and (
                match := re.match(
                    r"^\s{4}address-family\s+(ipv[46])\s+unicast\s*$",
                    line,
                )
            ):
                current_af = match.group(1)
                bgp_processes[local_as]["vrfs"][current_vrf][
                    "address_families"
                ][current_af] = {"commands": []}
            elif current_vrf and current_af and re.match(r"^\s{6}\S", line):
                bgp_processes[local_as]["vrfs"][current_vrf][
                    "address_families"
                ][current_af]["commands"].append(line.strip())

    route_maps = sorted(
        {
            match.group(1)
            for line in lines
            if (match := re.match(r"^route-map\s+(\S+)\s+", line))
        }
    )
    prefix_lists: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        match = re.match(
            r"^(?:ip|ipv6) prefix-list\s+(\S+)(?:\s+seq\s+(\d+))?\s+"
            r"(permit|deny)\s+(\S+)(?:\s+(ge|le)\s+(\d+))?"
            r"(?:\s+(ge|le)\s+(\d+))?\s*$",
            line,
        )
        if not match:
            continue
        name, sequence, action, prefix, op1, value1, op2, value2 = match.groups()
        entry: dict[str, Any] = {
            "sequence": int(sequence or 10),
            "action": action,
            "prefix": str(ipaddress.ip_network(prefix, strict=False)),
        }
        for operator, value in ((op1, value1), (op2, value2)):
            if operator and value:
                entry[operator] = int(value)
        prefix_lists[name].append(entry)
    for entries in prefix_lists.values():
        entries.sort(key=lambda item: item["sequence"])

    route_map_policies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    current_route_map: dict[str, Any] | None = None
    for line in lines:
        match = re.match(r"^route-map\s+(\S+)\s+(permit|deny)(?:\s+(\d+))?\s*$", line)
        if match:
            name, action, sequence = match.groups()
            current_route_map = {
                "sequence": int(sequence or 10),
                "action": action,
                "match_ip_prefix_lists": [],
                "unsupported_matches": [],
            }
            route_map_policies[name].append(current_route_map)
            continue
        if current_route_map is None:
            continue
        if line and not line.startswith(" "):
            current_route_map = None
            continue
        stripped = line.strip()
        if match := re.match(
            r"match (?:ip|ipv6) address prefix-list\s+(.+)$", stripped
        ):
            current_route_map["match_ip_prefix_lists"].extend(match.group(1).split())
        elif stripped.startswith("match "):
            current_route_map["unsupported_matches"].append(stripped)
    for entries in route_map_policies.values():
        entries.sort(key=lambda item: item["sequence"])
    evpn_l2vnis: dict[str, Any] = {}
    for _evpn, body in _blocks(lines, r"^(evpn)\s*$"):
        current_vni: str | None = None
        for line in body:
            if match := re.match(r"^\s{2}vni\s+(\d+)\s+l2\s*$", line):
                current_vni = match.group(1)
                evpn_l2vnis[current_vni] = {"commands": []}
            elif current_vni and re.match(r"^\s{4}\S", line):
                evpn_l2vnis[current_vni]["commands"].append(line.strip())
    return {
        "vlans": vlans,
        "vrfs": vrfs,
        "svis": svis,
        "interfaces": interfaces,
        "nve": nve,
        "bgp_processes": bgp_processes,
        "bgp_neighbor_config": bgp_neighbor_config,
        "evpn_bgp_configured": evpn_bgp_configured,
        "vpc": {
            "configured": bool(
                re.search(r"^vpc domain\s+\S+\s*$", text, re.MULTILINE)
            )
        },
        "rr_config": rr_config,
        "route_maps": route_maps,
        "route_map_policies": dict(route_map_policies),
        "prefix_lists": dict(prefix_lists),
        "evpn_l2vnis": evpn_l2vnis,
    }


def _overlay_states(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    states: dict[str, Mapping[str, Any]] = {}
    for host, data in snapshot["hosts"].items():
        state = data["profiles"].get("nxos-overlay", {}).get("config")
        if state is not None:
            states[host] = state
    return states


def _normalized_svi(state: Mapping[str, Any], vlan: str) -> dict[str, Any] | None:
    raw = state["svis"].get(vlan)
    if raw is None:
        return None
    svi: dict[str, Any] = {}
    for key in (
        "mtu",
        "ipv4_addresses",
        "ipv6_addresses",
        "ipv6_link_local",
    ):
        value = raw.get(key)
        if value not in (None, []):
            svi[key] = value
    if raw.get("ipv6_addresses"):
        svi["ipv6_nd_suppress_ra"] = raw.get(
            "ipv6_nd_suppress_ra", False
        )
    if raw.get("anycast_gateway"):
        svi["gateway_mode"] = "anycast"
    return svi


def _target_map(
    device_values: Mapping[str, Mapping[str, Any]],
    device_groups: Mapping[str, list[str]],
) -> dict[str, Any]:
    """Compress exact, non-overlapping group membership and preserve overrides."""
    remaining = set(device_values)
    groups: dict[str, Any] = {}
    for group, members in sorted(device_groups.items()):
        selected = set(members)
        if not selected or not selected <= remaining:
            continue
        values = {repr(sorted(device_values[host].items())) for host in selected}
        if len(values) != 1:
            continue
        sample = dict(device_values[next(iter(selected))])
        groups[group] = sample
        remaining -= selected
    targets: dict[str, Any] = {}
    if groups:
        targets["groups"] = groups
    if remaining:
        targets["devices"] = {
            host: dict(device_values[host]) for host in sorted(remaining)
        }
    return targets


def _compress_vlans(
    placements: list[tuple[str, str, Mapping[str, Any]]],
) -> tuple[int | None, dict[str, dict[str, Any]]]:
    counts: dict[int, int] = defaultdict(int)
    by_host: dict[str, int] = {}
    for host, vlan, _data in placements:
        value = int(vlan)
        counts[value] += 1
        by_host[host] = value
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    default: int | None = None
    if len(ordered) == 1 or (
        ordered[0][1] >= 2
        and (len(ordered) == 1 or ordered[0][1] > ordered[1][1])
    ):
        default = ordered[0][0]
    overrides = {
        host: ({} if vlan == default else {"vlan": vlan})
        for host, vlan in by_host.items()
    }
    return default, overrides


def discover_overlay_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    generated_at: datetime,
    device_groups: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Discover newly added L2/L3 VNI resources across observed devices."""
    if before["change_id"] != after["change_id"]:
        raise OverlayDiscoveryError("before/after change_id mismatch")
    if set(before["hosts"]) != set(after["hosts"]):
        raise OverlayDiscoveryError("before/after host set mismatch")
    before_states = _overlay_states(before)
    after_states = _overlay_states(after)
    if set(before_states) != set(after_states):
        raise OverlayDiscoveryError("before/after Overlay evidence set mismatch")

    l2_devices: dict[int, list[tuple[str, str, Mapping[str, Any]]]] = defaultdict(list)
    l3_devices: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for host, after_state in after_states.items():
        before_state = before_states[host]
        before_l2 = {
            int(vni)
            for vni in before_state["nve"]["l2vnis"]
        }
        for vlan, vlan_data in after_state["vlans"].items():
            vni = vlan_data.get("vni")
            if vni is None or vni in before_l2:
                continue
            if str(vni) in after_state["nve"]["l2vnis"]:
                l2_devices[vni].append((host, vlan, vlan_data))
        before_l3 = {
            int(vni)
            for vni in before_state["nve"]["l3vnis"]
        }
        for vrf, vrf_data in after_state["vrfs"].items():
            vni = vrf_data.get("l3vni")
            if (
                vni is not None
                and vni not in before_l3
                and str(vni) in after_state["nve"]["l3vnis"]
            ):
                l3_devices[vni].append((host, vrf))

    conflicts: list[dict[str, Any]] = []
    normalized_groups = {
        name: sorted(set(members))
        for name, members in (device_groups or {}).items()
    }
    l3vnis: list[dict[str, Any]] = []
    for vni, placements in sorted(l3_devices.items()):
        vrfs = {vrf for _host, vrf in placements}
        if len(vrfs) != 1:
            conflicts.append(
                {"resource": f"l3vni/{vni}", "reason": "vrf_mismatch"}
            )
            continue
        vrf = next(iter(vrfs))
        traditional_states: list[bool] = []
        ambiguous_traditional = False
        for host, _vrf in placements:
            state = after_states[host]
            mapped = [
                vlan
                for vlan, data in state["vlans"].items()
                if data.get("vni") == vni
            ]
            if not mapped:
                traditional_states.append(False)
                continue
            valid = any(
                state["svis"].get(vlan, {}).get("ip_forward")
                and state["svis"].get(vlan, {}).get("vrf") == vrf
                for vlan in mapped
            )
            traditional_states.append(valid)
            ambiguous_traditional |= not valid
        if ambiguous_traditional or len(set(traditional_states)) > 1:
            conflicts.append(
                {
                    "resource": f"l3vni/{vni}",
                    "reason": "l3vni_mode_ambiguous",
                }
            )
            continue
        traditional = all(traditional_states)
        target_values = {host: {} for host, _vrf in placements}
        l3vnis.append(
            {
                "vni": vni,
                "vrf": vrf,
                "mode": "traditional_vlan_svi" if traditional else "new_l3vni",
                "targets": _target_map(target_values, normalized_groups),
            }
        )

    l2vnis: list[dict[str, Any]] = []
    l3_by_vrf = {item["vrf"]: item["vni"] for item in l3vnis}
    for vni, placements in sorted(l2_devices.items()):
        names = {data.get("name") for _host, _vlan, data in placements}
        item: dict[str, Any] = {"vni": vni}
        default_vlan, target_values = _compress_vlans(placements)
        if default_vlan is not None:
            item["default_vlan"] = default_vlan
        if len(names) == 1 and None not in names:
            item["vlan_name"] = next(iter(names))
        elif len(names) > 1:
            conflicts.append(
                {"resource": f"l2vni/{vni}", "reason": "vlan_name_mismatch"}
            )
        observed_vrfs = {
            after_states[host]["svis"].get(vlan, {}).get("vrf")
            for host, vlan, _data in placements
        } - {None}
        if len(observed_vrfs) == 1:
            vrf = next(iter(observed_vrfs))
            item["vrf"] = vrf
            if vrf in l3_by_vrf:
                item["l3vni"] = l3_by_vrf[vrf]
        svis = {
            host: _normalized_svi(after_states[host], vlan)
            for host, vlan, _data in placements
        }
        present_svis = {host: svi for host, svi in svis.items() if svi is not None}
        distinct_svis = {repr(sorted(svi.items())) for svi in present_svis.values()}
        if len(distinct_svis) == 1 and present_svis:
            common_svi = dict(next(iter(present_svis.values())))
            if (
                common_svi.get("ipv4_addresses")
                or common_svi.get("ipv6_addresses")
            ):
                item["svi"] = common_svi
                for host, svi in svis.items():
                    if svi is None:
                        target_values[host]["svi"] = False
            else:
                conflicts.append(
                    {
                        "resource": f"l2vni/{vni}",
                        "reason": "svi_has_no_gateway_address",
                    }
                )
        elif len(distinct_svis) > 1:
            conflicts.append(
                {
                    "resource": f"l2vni/{vni}",
                    "reason": "svi_common_attributes_mismatch",
                    "observed": present_svis,
                }
            )
        item["targets"] = _target_map(target_values, normalized_groups)
        l2vnis.append(item)

    observed: list[dict[str, Any]] = []
    missing_operational = False
    for vni, placements in sorted(l2_devices.items()):
        for host, vlan, _data in placements:
            nve_state = (
                after["hosts"][host]["profiles"]
                .get("nxos-overlay", {})
                .get("nve_vnis")
            )
            entry = nve_state.get("vnis", {}).get(str(vni)) if nve_state else None
            if entry is None:
                missing_operational = True
                continue
            observed.append(
                {
                    "device": host,
                    "resource": f"l2vni/{vni}",
                    "state": entry["state"],
                    "type": entry["type"],
                    "context": entry["context"],
                }
            )
            if entry["type"] != "L2" or entry["context"] != vlan:
                conflicts.append(
                    {
                        "resource": f"l2vni/{vni}",
                        "device": host,
                        "reason": "nve_vni_operational_mismatch",
                    }
                )
    for vni, placements in sorted(l3_devices.items()):
        for host, vrf in placements:
            nve_state = (
                after["hosts"][host]["profiles"]
                .get("nxos-overlay", {})
                .get("nve_vnis")
            )
            entry = nve_state.get("vnis", {}).get(str(vni)) if nve_state else None
            if entry is None:
                missing_operational = True
                continue
            observed.append(
                {
                    "device": host,
                    "resource": f"l3vni/{vni}",
                    "state": entry["state"],
                    "type": entry["type"],
                    "context": entry["context"],
                }
            )
            if entry["type"] != "L3" or entry["context"] != vrf:
                conflicts.append(
                    {
                        "resource": f"l3vni/{vni}",
                        "device": host,
                        "reason": "nve_vni_operational_mismatch",
                    }
                )
    warnings = []
    if missing_operational:
        warnings.append(
            {
                "reason": "operational_evidence_incomplete",
                "message": (
                    "show nve vni evidence is missing for one or more discovered "
                    "resources; configuration was discovered but state is not verified"
                ),
            }
        )
    confidence = (
        "low"
        if conflicts
        else ("medium" if missing_operational else "high")
    )
    document = {
        "api_version": API_VERSION,
        "kind": "OverlayChangeSet",
        "metadata": {
            "change_id": before["change_id"],
            "source": "discovered",
            "generated_at": generated_at.isoformat(timespec="seconds"),
        },
        "spec": {
            "device_groups": {
                name: {"devices": members}
                for name, members in normalized_groups.items()
            },
            "l2vnis": l2vnis,
            "l3vnis": l3vnis,
        },
        "status": {
            "discovery": {
                "before_snapshot": before["collection_id"],
                "after_snapshot": after["collection_id"],
                "confidence": confidence,
            },
            "observed": observed,
            "conflicts": conflicts,
            "warnings": warnings,
        },
    }
    validate_document(document, kind="OverlayChangeSet")
    return document
