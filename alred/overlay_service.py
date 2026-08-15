"""Canonical Overlay Service model and diagram adapters."""

from __future__ import annotations

from collections import defaultdict, deque
import csv
import hashlib
import io
import re
from typing import Any, Mapping, Sequence

from .health.overlay import (
    EVPN_CONTROL_PLANE_PARSER_VERSION,
    OVERLAY_PARSER_VERSION,
    parse_evpn_control_plane_running_config,
    parse_overlay_running_config,
)
from .health.parsers import NXOS_PARSER_VERSION, ParserError, parse_nxos_command
from .schema import API_VERSION


OVERLAY_DETAIL_BINDING_EDGE_LIMIT = 40


class OverlayServiceError(ValueError):
    """Expected Overlay Service parsing or selector failure."""

    code = "VALIDATION_ERROR"


def _stable_id(prefix: str, *values: str) -> str:
    material = "|".join(values)
    digest = hashlib.sha256(material.encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _service_sort_key(service: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(service.get("site", "")),
        str(service.get("vrf") or ""),
        int(service.get("l3vni") or -1),
        str(service.get("service_id", "")),
    )


def _diagnostic(code: str, **context: Any) -> dict[str, Any]:
    return {"code": code, **context}


def _l2_binding(
    hostname: str,
    vlan: int,
    svi: Mapping[str, Any],
    *,
    nve_member: bool,
) -> dict[str, Any]:
    ipv4_addresses = sorted({str(value) for value in svi.get("ipv4_addresses", [])})
    ipv6_addresses = sorted({str(value) for value in svi.get("ipv6_addresses", [])})
    anycast_gateway = bool(svi.get("anycast_gateway"))
    return {
        "node": hostname,
        "vlan": vlan,
        "svi": f"Vlan{vlan}" if svi else None,
        "nve_member": nve_member,
        "gateway": bool(anycast_gateway or ipv4_addresses or ipv6_addresses),
        "gateway_mode": (
            "anycast" if anycast_gateway else
            "addressed" if ipv4_addresses or ipv6_addresses else
            "none"
        ),
        "ipv4_addresses": ipv4_addresses,
        "ipv6_addresses": ipv6_addresses,
        "ip_forward": bool(svi.get("ip_forward")),
    }


def _finalize_l2_service(item: dict[str, Any]) -> None:
    bindings = sorted(
        item.get("bindings", []),
        key=lambda value: str(value.get("node", "")),
    )
    item["bindings"] = bindings
    states = {bool(value.get("gateway")) for value in bindings}
    item["gateway_state"] = (
        "unknown" if not bindings else
        "mixed" if len(states) > 1 else
        "yes" if True in states else
        "no"
    )
    item["gateway_modes"] = sorted(
        {str(value["gateway_mode"]) for value in bindings}
    )
    item["ipv4_addresses"] = sorted(
        {
            str(address)
            for value in bindings
            for address in value.get("ipv4_addresses", [])
        }
    )
    item["ipv6_addresses"] = sorted(
        {
            str(address)
            for value in bindings
            for address in value.get("ipv6_addresses", [])
        }
    )
    vlans = {int(value["vlan"]) for value in bindings}
    svis = {str(value["svi"]) for value in bindings if value.get("svi")}
    item["vlan"] = next(iter(vlans)) if len(vlans) == 1 else None
    item["svi"] = next(iter(svis)) if len(svis) == 1 else None
    item["vlan_state"] = (
        "unknown" if not bindings else
        "common" if len(vlans) == 1 else
        "per-device"
    )


def _l3vni_binding(
    hostname: str,
    vrf: str,
    l3vni: int,
    config: Mapping[str, Any],
    *,
    nve_associate_vrf: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    mapped_vlans = sorted(
        int(vlan)
        for vlan, data in config.get("vlans", {}).items()
        if data.get("vni") == l3vni
    )
    valid = [
        vlan
        for vlan in mapped_vlans
        if config.get("svis", {}).get(str(vlan), {}).get("vrf") == vrf
        and config.get("svis", {}).get(str(vlan), {}).get("ip_forward")
    ]
    diagnostic: dict[str, Any] | None = None
    if not mapped_vlans:
        mode = "new_l3vni" if nve_associate_vrf else "unknown"
        vlan = None
        svi: Mapping[str, Any] = {}
    elif len(mapped_vlans) == 1 and len(valid) == 1:
        mode = "traditional_vlan_svi"
        vlan = valid[0]
        svi = config.get("svis", {}).get(str(vlan), {})
    else:
        mode = "unknown"
        vlan = mapped_vlans[0] if len(mapped_vlans) == 1 else None
        svi = config.get("svis", {}).get(str(vlan), {}) if vlan is not None else {}
        diagnostic = _diagnostic(
            "OVERLAY_L3VNI_MODE_AMBIGUOUS",
            node=hostname,
            vrf=vrf,
            l3vni=l3vni,
            mapped_vlans=mapped_vlans,
        )
    return (
        {
            "node": hostname,
            "mode": mode,
            "vlan": vlan,
            "svi": f"Vlan{vlan}" if vlan is not None else None,
            "svi_behavior": "ip-forward" if svi.get("ip_forward") else None,
            "nve_associate_vrf": nve_associate_vrf,
            "ipv4_addresses": sorted(
                {str(value) for value in svi.get("ipv4_addresses", [])}
            ),
            "ipv6_addresses": sorted(
                {str(value) for value in svi.get("ipv6_addresses", [])}
            ),
            "ipv6_use_link_local_only": bool(
                svi.get("ipv6_use_link_local_only")
            ),
        },
        diagnostic,
    )


def _finalize_l3vni_mode(service: dict[str, Any]) -> None:
    bindings = sorted(
        service.get("l3vni_bindings", []),
        key=lambda value: str(value.get("node", "")),
    )
    service["l3vni_bindings"] = bindings
    known_modes = {
        str(binding["mode"])
        for binding in bindings
        if binding.get("mode") in {"new_l3vni", "traditional_vlan_svi"}
    }
    has_unknown = any(binding.get("mode") == "unknown" for binding in bindings)
    if len(known_modes) > 1:
        service["l3vni_mode"] = "conflict"
        service["l3vni_mode_state"] = "conflict"
        service["conflicts"].append(
            {"field": "l3vni_mode", "values": sorted(known_modes)}
        )
    elif len(known_modes) == 1:
        service["l3vni_mode"] = next(iter(known_modes))
        service["l3vni_mode_state"] = "partial" if has_unknown else "consistent"
    else:
        service["l3vni_mode"] = "unknown"
        service["l3vni_mode_state"] = "unknown"


def _effective_site(hostname: str, node_sites: Mapping[str, str]) -> tuple[str, str]:
    site = str(node_sites.get(hostname, "")).strip()
    if site:
        return site, site
    # Do not merge same-named VRFs across devices when site evidence is missing.
    return "unresolved", f"unresolved:{hostname}"


def _rt_observations(
    config: Mapping[str, Any],
    *,
    hostname: str,
    vrf: str,
    l3vni: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    local_as_values = sorted(str(value) for value in config.get("bgp_processes", {}))
    for af, af_data in sorted(config.get("vrfs", {}).get(vrf, {}).get("address_families", {}).items()):
        for command in af_data.get("commands", []):
            match = re.fullmatch(
                r"route-target\s+(both|import|export)\s+(\S+)(?:\s+(evpn))?",
                str(command),
                re.IGNORECASE,
            )
            if not match:
                continue
            direction, configured_value, evpn = match.groups()
            scope = "evpn" if evpn else "vpn"
            directions = ("import", "export") if direction.lower() == "both" else (direction.lower(),)
            resolved_value: str | None = configured_value
            resolution = "explicit"
            if configured_value.lower() == "auto":
                if l3vni is not None and len(local_as_values) == 1 and local_as_values[0].isdigit():
                    resolved_value = f"{local_as_values[0]}:{l3vni}"
                    resolution = "nxos-asn-vni"
                else:
                    resolved_value = None
                    resolution = "unresolved"
                    diagnostics.append(
                        _diagnostic(
                            "OVERLAY_RT_UNRESOLVED",
                            node=hostname,
                            vrf=vrf,
                            address_family=af,
                            scope=scope,
                            configured_value=configured_value,
                        )
                    )
            for effective_direction in directions:
                observations.append(
                    {
                        "node": hostname,
                        "address_family": af,
                        "scope": scope,
                        "direction": effective_direction,
                        "configured_value": configured_value,
                        "resolved_value": resolved_value,
                        "resolution": resolution,
                        "evidence_ref": f"{hostname}:running_config",
                    }
                )
    observations.sort(
        key=lambda item: (
            item["node"],
            item["address_family"],
            item["scope"],
            item["direction"],
            str(item.get("resolved_value") or ""),
            item["configured_value"],
        )
    )
    return observations, diagnostics


def _parse_operational(
    command_texts: Mapping[str, Mapping[str, str]] | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    parsed: dict[str, dict[str, Any]] = defaultdict(dict)
    diagnostics: list[dict[str, Any]] = []
    for command_id, hosts in sorted((command_texts or {}).items()):
        for hostname, text in sorted(hosts.items()):
            try:
                _common, profiles = parse_nxos_command(command_id, text)
            except (KeyError, ParserError) as exc:
                diagnostics.append(
                    _diagnostic(
                        "OVERLAY_ROUTE_LEAK_EVIDENCE_INCOMPLETE",
                        node=hostname,
                        command_id=command_id,
                        reason=str(exc),
                    )
                )
                continue
            overlay = profiles.get("nxos-overlay", {})
            parsed[hostname][command_id] = overlay
    return dict(parsed), diagnostics


def _route_type_counts_for_service(
    service: Mapping[str, Any],
    operational: Mapping[str, Mapping[str, Any]],
) -> dict[str, int | None]:
    counts: dict[str, int | None] = {"type2": None, "type3": None, "type5": None}
    type5_keys: set[tuple[str, str]] = set()
    type2_count = 0
    type3_count = 0
    saw_routes = False
    l2_rds = {
        str(item["rd"])
        for item in service.get("l2_services", [])
        if item.get("rd")
    }
    for placement in service.get("placements", []):
        if placement.get("placement_type") == "service-edge":
            continue
        hostname = str(placement["node"])
        routes = operational.get(hostname, {}).get("bgp_l2vpn_evpn", {}).get("evpn_routes")
        if not isinstance(routes, Mapping):
            continue
        saw_routes = True
        for route in routes.get("routes", []):
            route_type = int(route.get("route_type", 0))
            if route_type == 5 and route.get("l3vni") == service.get("l3vni"):
                type5_keys.add((hostname, str(route.get("prefix") or route.get("route_key", ""))))
            elif route_type == 2 and str(route.get("rd")) in l2_rds:
                type2_count += 1
            elif route_type == 3 and str(route.get("rd")) in l2_rds:
                type3_count += 1
    if saw_routes:
        counts = {"type2": type2_count, "type3": type3_count, "type5": len(type5_keys)}
    return counts


def _service_status(
    service: Mapping[str, Any],
    operational: Mapping[str, Mapping[str, Any]],
) -> str:
    if service.get("conflicts"):
        return "conflict"
    if service.get("l3vni") is not None and service.get(
        "l3vni_mode_state"
    ) in {"partial", "unknown"}:
        return "unknown"
    if any(item.get("resolution") == "unresolved" for item in service.get("route_target_observations", [])):
        return "unknown"
    expected_by_node: dict[str, set[int]] = defaultdict(set)
    if service.get("l3vni") is not None:
        for placement in service.get("placements", []):
            if placement.get("nve_l3_member"):
                expected_by_node[str(placement["node"])].add(int(service["l3vni"]))
    for l2_service in service.get("l2_services", []):
        if not l2_service.get("nve_member"):
            continue
        for node in l2_service.get("nodes", []):
            expected_by_node[str(node)].add(int(l2_service["l2vni"]))
    if not expected_by_node:
        return "configured"
    observed_nodes: set[str] = set()
    for node, expected_vnis in expected_by_node.items():
        nve_vnis = operational.get(node, {}).get("nve_vni", {}).get("nve_vnis")
        if not isinstance(nve_vnis, Mapping):
            continue
        observed_nodes.add(node)
        if not nve_vnis.get("applicable", True):
            return "degraded"
        entries = nve_vnis.get("vnis", {})
        for vni in expected_vnis:
            entry = entries.get(str(vni))
            if not isinstance(entry, Mapping):
                return "degraded"
            if str(entry.get("state", "")).lower() not in {"up", "oper-up"}:
                return "degraded"
    if observed_nodes == set(expected_by_node):
        return "healthy"
    return "configured"


def build_overlay_service_model(
    running_configs: Mapping[str, str],
    *,
    node_sites: Mapping[str, str] | None = None,
    operational_command_texts: Mapping[str, Mapping[str, str]] | None = None,
    source: Mapping[str, str] | None = None,
    source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Build deterministic Overlay services and directed RT leak relations."""
    node_sites = node_sites or {}
    parsed_overlay: dict[str, dict[str, Any]] = {}
    parsed_evpn: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for hostname, text in sorted(running_configs.items()):
        parsed_overlay[hostname] = parse_overlay_running_config(text)
        parsed_evpn[hostname] = parse_evpn_control_plane_running_config(text)

    operational, operational_diagnostics = _parse_operational(operational_command_texts)
    diagnostics.extend(operational_diagnostics)
    service_map: dict[str, dict[str, Any]] = {}
    secondary_vtep_nodes: dict[str, set[str]] = defaultdict(set)
    for hostname, evpn_config in parsed_evpn.items():
        if not evpn_config.get("vpc_domain"):
            continue
        for interface_name in evpn_config.get("nve_source_interfaces", []):
            interface = evpn_config.get("interfaces", {}).get(interface_name, {})
            for value in interface.get("secondary_addresses", []):
                secondary_vtep_nodes[str(value).split("/", 1)[0]].add(hostname)
    shared_vtep_addresses = {
        address for address, nodes in secondary_vtep_nodes.items()
        if len(nodes) >= 2
    }

    def ensure_service(
        *,
        hostname: str,
        vrf: str | None,
        l3vni: int | None,
        l2vni: int | None = None,
    ) -> dict[str, Any]:
        site, identity_site = _effective_site(hostname, node_sites)
        identity = vrf if vrf is not None else f"l2vni:{l2vni}"
        service_id = f"{identity_site}/{identity}"
        service = service_map.setdefault(
            service_id,
            {
                "service_id": service_id,
                "site": site,
                "vrf": vrf,
                "l3vni": l3vni,
                "address_families": [],
                "route_distinguisher": None,
                "import_route_targets": [],
                "export_route_targets": [],
                "route_target_observations": [],
                "l2_services": [],
                "l3vni_mode": "unknown",
                "l3vni_mode_state": "unknown",
                "l3vni_bindings": [],
                "placements": [],
                "route_type_summary": {"type2": None, "type3": None, "type5": None},
                "status": "configured",
                "conflicts": [],
                "evidence_refs": [],
            },
        )
        if service.get("l3vni") is None and l3vni is not None:
            service["l3vni"] = l3vni
        elif (
            service.get("l3vni") is not None
            and l3vni is not None
            and service.get("l3vni") != l3vni
        ):
            service["conflicts"].append(
                {"field": "l3vni", "values": sorted({service.get("l3vni"), l3vni}, key=str)}
            )
            diagnostics.append(
                _diagnostic(
                    "OVERLAY_SERVICE_IDENTITY_CONFLICT",
                    service_id=service_id,
                    field="l3vni",
                )
            )
        return service

    for hostname, config in sorted(parsed_overlay.items()):
        evpn_config = parsed_evpn[hostname]
        vtep_addresses: set[str] = set()
        secondary_addresses: set[str] = set()
        for interface_name in evpn_config.get("nve_source_interfaces", []):
            interface = evpn_config.get("interfaces", {}).get(interface_name, {})
            for value in interface.get("addresses", []):
                address = str(value).split("/", 1)[0]
                vtep_addresses.add(address)
                if value in interface.get("secondary_addresses", []):
                    secondary_addresses.add(address)
        nve_l3 = {int(value) for value in config.get("nve", {}).get("l3vnis", {})}
        nve_l2 = {int(value) for value in config.get("nve", {}).get("l2vnis", {})}

        for vrf, vrf_data in sorted(config.get("vrfs", {}).items()):
            l3vni = vrf_data.get("l3vni")
            service = ensure_service(hostname=hostname, vrf=vrf, l3vni=l3vni)
            afs = sorted(vrf_data.get("address_families", {}))
            service["address_families"] = sorted(set(service["address_families"]) | set(afs))
            rd = vrf_data.get("rd")
            if rd:
                if service["route_distinguisher"] not in {None, rd}:
                    service["conflicts"].append(
                        {"field": "route_distinguisher", "values": sorted({service["route_distinguisher"], rd})}
                    )
                elif service["route_distinguisher"] is None:
                    service["route_distinguisher"] = rd
            observations, rt_diagnostics = _rt_observations(
                config, hostname=hostname, vrf=vrf, l3vni=l3vni
            )
            diagnostics.extend(rt_diagnostics)
            service["route_target_observations"].extend(observations)
            if l3vni is not None:
                l3_binding, l3_diagnostic = _l3vni_binding(
                    hostname,
                    vrf,
                    int(l3vni),
                    config,
                    nve_associate_vrf=int(l3vni) in nve_l3,
                )
                service["l3vni_bindings"].append(l3_binding)
                if l3_diagnostic:
                    diagnostics.append(l3_diagnostic)
            service["placements"].append(
                {
                    "node": hostname,
                    "placement_type": (
                        "evpn-vtep" if l3vni is not None else "service-edge"
                    ),
                    "vtep_addresses": sorted(vtep_addresses),
                    "vpc_domain": evpn_config.get("vpc_domain"),
                    "vpc_shared_vtep_addresses": sorted(
                        secondary_addresses & shared_vtep_addresses
                    ),
                    "nve_l3_member": bool(l3vni is not None and int(l3vni) in nve_l3),
                }
            )
            service["evidence_refs"].append(f"{hostname}:running_config")

        assigned_l2vnis: set[int] = set()
        configured_l3vnis = {
            int(value["l3vni"])
            for value in config.get("vrfs", {}).values()
            if value.get("l3vni") is not None
        }
        for vlan, vlan_data in sorted(config.get("vlans", {}).items(), key=lambda item: int(item[0])):
            if vlan_data.get("vni") is None:
                continue
            l2vni = int(vlan_data["vni"])
            assigned_l2vnis.add(l2vni)
            if l2vni in configured_l3vnis:
                continue
            svi = config.get("svis", {}).get(vlan, {})
            vrf = svi.get("vrf")
            l3vni = config.get("vrfs", {}).get(vrf, {}).get("l3vni") if vrf else None
            service = ensure_service(hostname=hostname, vrf=vrf, l3vni=l3vni, l2vni=l2vni)
            evpn_commands = config.get("evpn_l2vnis", {}).get(str(l2vni), {}).get("commands", [])
            l2_rd = next(
                (match.group(1) for command in evpn_commands if (match := re.fullmatch(r"rd\s+(\S+)", str(command)))),
                None,
            )
            item = {
                "l2vni": l2vni,
                "vlan": int(vlan),
                "svi": f"Vlan{vlan}" if svi else None,
                "rd": l2_rd,
                "nodes": [hostname],
                "nve_member": l2vni in nve_l2,
                "bindings": [
                    _l2_binding(
                        hostname,
                        int(vlan),
                        svi,
                        nve_member=l2vni in nve_l2,
                    )
                ],
            }
            existing = next((value for value in service["l2_services"] if value["l2vni"] == l2vni), None)
            if existing:
                existing["nodes"] = sorted(set(existing["nodes"]) | {hostname})
                existing["nve_member"] = bool(existing["nve_member"] and item["nve_member"])
                existing["bindings"].extend(item["bindings"])
            else:
                service["l2_services"].append(item)
            existing_placement = next(
                (
                    value
                    for value in service["placements"]
                    if value["node"] == hostname
                ),
                None,
            )
            if existing_placement is None:
                service["placements"].append(
                    {
                        "node": hostname,
                        "placement_type": "l2-only",
                        "vtep_addresses": sorted(vtep_addresses),
                        "vpc_domain": evpn_config.get("vpc_domain"),
                        "vpc_shared_vtep_addresses": sorted(
                            secondary_addresses & shared_vtep_addresses
                        ),
                        "nve_l3_member": False,
                    }
                )
            elif existing_placement["placement_type"] == "service-edge":
                existing_placement["placement_type"] = "l2-only"
            if f"{hostname}:running_config" not in service["evidence_refs"]:
                service["evidence_refs"].append(f"{hostname}:running_config")

        for raw_l2vni in sorted(config.get("evpn_l2vnis", {}), key=int):
            l2vni = int(raw_l2vni)
            if l2vni in assigned_l2vnis:
                continue
            service = ensure_service(hostname=hostname, vrf=None, l3vni=None, l2vni=l2vni)
            existing = next(
                (value for value in service["l2_services"] if value["l2vni"] == l2vni),
                None,
            )
            if existing:
                existing["nodes"] = sorted(set(existing["nodes"]) | {hostname})
                existing["nve_member"] = bool(
                    existing["nve_member"] and l2vni in nve_l2
                )
            else:
                service["l2_services"].append(
                    {
                        "l2vni": l2vni,
                        "vlan": None,
                        "svi": None,
                        "rd": None,
                        "nodes": [hostname],
                        "nve_member": l2vni in nve_l2,
                        "bindings": [],
                    }
                )
            if f"{hostname}:running_config" not in service["evidence_refs"]:
                service["evidence_refs"].append(f"{hostname}:running_config")

    services = sorted(
        (
            service for service in service_map.values()
            if service.get("l3vni") is not None
            or service.get("l2_services")
            or service.get("route_target_observations")
        ),
        key=_service_sort_key,
    )
    for service in services:
        service["placements"].sort(key=lambda item: item["node"])
        service["l2_services"].sort(key=lambda item: (item["l2vni"], item.get("vlan") or -1))
        for l2_service in service["l2_services"]:
            _finalize_l2_service(l2_service)
        _finalize_l3vni_mode(service)
        service["route_target_observations"].sort(
            key=lambda item: (
                item["node"], item["address_family"], item["scope"],
                item["direction"], str(item.get("resolved_value") or ""),
            )
        )
        service["import_route_targets"] = sorted(
            {
                str(item["resolved_value"])
                for item in service["route_target_observations"]
                if item["scope"] == "evpn" and item["direction"] == "import" and item.get("resolved_value")
            }
        )
        service["export_route_targets"] = sorted(
            {
                str(item["resolved_value"])
                for item in service["route_target_observations"]
                if item["scope"] == "evpn" and item["direction"] == "export" and item.get("resolved_value")
            }
        )
        service["route_type_summary"] = _route_type_counts_for_service(service, operational)
        service["evidence_refs"] = sorted(set(service["evidence_refs"]))
        service["status"] = _service_status(service, operational)

    route_leaks: list[dict[str, Any]] = []

    def rt_placement_nodes(service: Mapping[str, Any]) -> set[str]:
        observed_nodes = {
            str(item["node"])
            for item in service.get("route_target_observations", [])
            if item.get("scope") == "evpn"
        }
        nve_nodes = {
            str(item["node"])
            for item in service.get("placements", [])
            if item.get("nve_l3_member")
        }
        evpn_placement_nodes = {
            str(item["node"])
            for item in service.get("placements", [])
            if item.get("placement_type") != "service-edge"
        }
        return observed_nodes | nve_nodes or evpn_placement_nodes

    service_by_id = {service["service_id"]: service for service in services}
    rt_exports: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    rt_imports: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    for service in services:
        service_id = str(service["service_id"])
        for observation in service["route_target_observations"]:
            target = observation.get("resolved_value")
            if observation.get("scope") != "evpn" or not target:
                continue
            key = (
                str(observation["address_family"]),
                str(observation["scope"]),
                str(target),
            )
            index = rt_exports if observation["direction"] == "export" else rt_imports
            index.setdefault(key, {}).setdefault(service_id, set()).add(
                str(observation["node"])
            )

    for af, scope, target in sorted(set(rt_exports) & set(rt_imports)):
        key = (af, scope, target)
        for source_id, source_nodes in sorted(rt_exports[key].items()):
            source_service = service_by_id[source_id]
            for destination_id, destination_nodes in sorted(rt_imports[key].items()):
                if source_id == destination_id:
                    continue
                destination_service = service_by_id[destination_id]
                if af in destination_service["address_families"]:
                    source_placements = rt_placement_nodes(source_service)
                    destination_placements = rt_placement_nodes(destination_service)
                    full_policy = source_nodes == source_placements and destination_nodes == destination_placements
                    expected_prefixes: set[str] = set()
                    source_evidence_nodes: set[str] = set()
                    for node in source_placements:
                        routes = operational.get(node, {}).get("bgp_l2vpn_evpn", {}).get("evpn_routes")
                        if not isinstance(routes, Mapping):
                            continue
                        source_evidence_nodes.add(node)
                        for route in routes.get("routes", []):
                            prefix = route.get("prefix")
                            if route.get("route_type") == 5 and route.get("l3vni") == source_service.get("l3vni") and prefix:
                                expected_prefixes.add(str(prefix))
                    destination_evidence_nodes: set[str] = set()
                    received_by_node: dict[str, set[str]] = {}
                    command_id = "route_ipv6_all_vrfs" if af == "ipv6" else "route_ipv4_all_vrfs"
                    for node in destination_placements:
                        routes = operational.get(node, {}).get(command_id, {}).get("vrf_routes", {}).get(af)
                        if not isinstance(routes, Mapping):
                            continue
                        destination_evidence_nodes.add(node)
                        received_by_node[node] = {
                            str(route["prefix"])
                            for route in routes.get("routes", [])
                            if route.get("vrf") == destination_service.get("vrf")
                            and route.get("protocol") == "bgp"
                        }
                    full_evidence = source_evidence_nodes == source_placements and destination_evidence_nodes == destination_placements
                    if not expected_prefixes and full_evidence:
                        operational_state = "not-applicable"
                        received_count = 0
                    elif expected_prefixes and destination_evidence_nodes:
                        missing = {
                            (node, prefix)
                            for node, prefixes in received_by_node.items()
                            for prefix in expected_prefixes
                            if prefix not in prefixes
                        }
                        if missing:
                            operational_state = "degraded"
                        elif full_evidence:
                            operational_state = "verified"
                        else:
                            operational_state = "unknown"
                        received_count = len(
                            {
                                prefix for prefixes in received_by_node.values()
                                for prefix in expected_prefixes if prefix in prefixes
                            }
                        )
                    else:
                        operational_state = "unknown"
                        received_count = 0
                    verification_scope = (
                        "full" if full_evidence else
                        "partial" if source_evidence_nodes or destination_evidence_nodes else
                        "unknown"
                    )
                    route_leaks.append(
                        {
                            "leak_id": _stable_id(
                                "route-leak", source_service["service_id"],
                                destination_service["service_id"], af, scope, target,
                            ),
                            "source_service": source_service["service_id"],
                            "destination_service": destination_service["service_id"],
                            "address_families": [af],
                            "scope": scope,
                            "matched_route_targets": [target],
                            "policy_state": "configured" if full_policy else "unknown",
                            "policy_coverage": {
                                "source_observed": len(source_nodes),
                                "source_placements": len(source_placements),
                                "destination_observed": len(destination_nodes),
                                "destination_placements": len(destination_placements),
                            },
                            "operational_state": operational_state,
                            "verification_scope": verification_scope,
                            "prefix_summary": {
                                "expected": len(expected_prefixes),
                                "received": received_count,
                            },
                            "evidence_refs": sorted(
                                {f"{node}:running_config" for node in source_nodes | destination_nodes}
                            ),
                        }
                    )

    route_leaks.sort(
        key=lambda item: (
            item["source_service"], item["destination_service"],
            item["address_families"], item["matched_route_targets"],
        )
    )
    if not services:
        status = "insufficient-evidence"
    elif diagnostics or any(
        service["status"] in {"unknown", "degraded", "conflict"}
        for service in services
    ):
        status = "partial"
    else:
        status = "complete"
    metadata: dict[str, Any] = {"source": dict(source or {"type": "file", "value": "running-config"})}
    if source_manifest_sha256:
        metadata["source_manifest_sha256"] = source_manifest_sha256
    return {
        "api_version": API_VERSION,
        "kind": "OverlayServiceModel",
        "metadata": metadata,
        "spec": {
            "status": status,
            "parser_versions": {
                "running_config": OVERLAY_PARSER_VERSION,
                "evpn_control_plane": EVPN_CONTROL_PLANE_PARSER_VERSION,
                "operational": NXOS_PARSER_VERSION,
            },
            "services": services,
            "route_leaks": route_leaks,
            "diagnostics": sorted(
                diagnostics,
                key=lambda item: (
                    str(item.get("code", "")), str(item.get("node", "")),
                    str(item.get("service_id", "")), str(item.get("command_id", "")),
                ),
            ),
        },
    }


def select_overlay_service_ids(
    model: Mapping[str, Any],
    *,
    sites: Sequence[str] = (),
    vrfs: Sequence[str] = (),
    l2vnis: Sequence[int] = (),
    l3vnis: Sequence[int] = (),
    services: Sequence[str] = (),
) -> tuple[set[str], set[str]]:
    """Return selected and direct route-leak context service IDs."""
    records = list(model.get("spec", {}).get("services", []))
    selectors_present = bool(sites or vrfs or l2vnis or l3vnis or services)
    selected: set[str] = set()
    for item in records:
        service_id = str(item["service_id"])
        if not selectors_present:
            selected.add(service_id)
            continue
        if (
            str(item.get("site")) in sites
            or str(item.get("vrf")) in vrfs
            or item.get("l3vni") in l3vnis
            or any(value.get("l2vni") in l2vnis for value in item.get("l2_services", []))
            or service_id in services
        ):
            selected.add(service_id)
    if selectors_present and not selected:
        raise OverlayServiceError("overlay selector did not match any service")
    context: set[str] = set()
    for leak in model.get("spec", {}).get("route_leaks", []):
        source = str(leak["source_service"])
        destination = str(leak["destination_service"])
        if source in selected and destination not in selected:
            context.add(destination)
        if destination in selected and source not in selected:
            context.add(source)
    return selected, context


def overlay_model_to_render_context(
    model: Mapping[str, Any],
    *,
    selected_ids: set[str] | None = None,
    context_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Adapt an Overlay Service model to the common renderer contract."""
    all_services = {str(item["service_id"]): item for item in model.get("spec", {}).get("services", [])}
    selected_ids = set(all_services) if selected_ids is None else set(selected_ids)
    context_ids = set(context_ids or set())
    visible = selected_ids | context_ids
    inventory: dict[str, dict[str, Any]] = {}
    lines: dict[str, list[str]] = {}
    roles: dict[str, str] = {}
    sites: dict[str, str] = {}
    for service_id in sorted(visible):
        item = all_services[service_id]
        inventory[service_id] = {"hostname": service_id, "device_type": "nxos"}
        node_lines = []
        if item.get("vrf"):
            node_lines.append(f"VRF: {item['vrf']}")
        if item.get("l3vni") is not None:
            node_lines.append(f"L3VNI: {item['l3vni']}")
        if service_id in context_ids:
            node_lines.append("Context: direct route leak neighbor")
        else:
            evpn_placements = sum(
                placement.get("placement_type") != "service-edge"
                for placement in item.get("placements", [])
            )
            service_edges = sum(
                placement.get("placement_type") == "service-edge"
                for placement in item.get("placements", [])
            )
            node_lines.extend(
                [
                    f"L2VNI: {len(item.get('l2_services', []))}",
                    f"EVPN placements: {evpn_placements}",
                    f"Service edges: {service_edges}",
                    f"Status: {item.get('status', 'unknown')}",
                ]
            )
        lines[service_id] = node_lines
        roles[service_id] = "overlay-service"
        if item.get("site"):
            sites[service_id] = str(item["site"])

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for leak in model.get("spec", {}).get("route_leaks", []):
        source = str(leak["source_service"])
        destination = str(leak["destination_service"])
        if source in visible and destination in visible:
            grouped[(source, destination)].append(leak)

    adjacency: dict[str, set[str]] = {service_id: set() for service_id in visible}
    for source, destination in grouped:
        adjacency[source].add(destination)
        adjacency[destination].add(source)
    layout_ranks: dict[str, int] = {}
    remaining = set(visible)
    while remaining:
        seed = min(remaining)
        component: set[str] = set()
        queue = deque([seed])
        while queue:
            node = queue.popleft()
            if node in component:
                continue
            component.add(node)
            queue.extend(sorted(adjacency[node] - component))
        remaining -= component
        hub = min(component, key=lambda node: (-len(adjacency[node]), node))
        distances = {hub: 0}
        queue = deque([hub])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(adjacency[node]):
                if neighbor in distances:
                    continue
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
        layout_ranks.update(distances)
    confirmed: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    for (source, destination), relations in sorted(grouped.items()):
        parts = []
        states = set()
        for relation in relations:
            rt = ",".join(str(value) for value in relation.get("matched_route_targets", []))
            state = str(relation.get("operational_state", "unknown"))
            scope = str(relation.get("verification_scope", "unknown"))
            states.add(state)
            af = ",".join(str(value) for value in relation.get("address_families", []))
            parts.append(f"{af} RT {rt} / {state}/{scope}")
        label = "; ".join(parts)
        link = {
            "endpoints": [f"{source}:", f"{destination}:"],
            "evidence": "",
            "label": label,
            "directed": True,
            "state": (
                "conflict" if "conflict" in states else
                "degraded" if "degraded" in states else
                "verified" if "verified" in states else
                "unknown"
            ),
        }
        labels[f"{source}||{destination}|"] = label
        if states <= {"configured", "unknown", "conflict", "not-applicable"}:
            candidates.append(link)
        else:
            confirmed.append(link)
    if not inventory:
        node = "Overlay Service evidence unavailable"
        inventory[node] = {"hostname": node, "device_type": "nxos"}
        lines[node] = ["No VRF, VNI, or route-target evidence"]
        roles[node] = "diagnostic"
    return {
        "normalized_inventory_map": inventory,
        "normalized_mgmt_ip_map": {},
        "rendered_links": confirmed,
        "rendered_candidate_links": candidates,
        "node_address_map": None,
        "node_address_label_map": None,
        "node_address_lines_map": lines,
        "link_label_map": labels,
        "node_interface_label_map": None,
        "extra_node_names": sorted(inventory),
        "node_role_map": roles,
        "node_site_map": sites,
        "node_layout_rank_map": layout_ranks,
        "skipped_by_confidence": 0,
    }


def overlay_service_links_csv_lines(model: Mapping[str, Any]) -> list[str]:
    """Render stable route leak review CSV rows."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "leak_id", "source_service", "destination_service", "address_families",
            "scope", "matched_route_targets", "policy_state", "operational_state",
            "verification_scope", "expected_prefixes", "received_prefixes",
        ]
    )
    for leak in model.get("spec", {}).get("route_leaks", []):
        writer.writerow(
            [
                leak.get("leak_id", ""), leak.get("source_service", ""),
                leak.get("destination_service", ""), ",".join(leak.get("address_families", [])),
                leak.get("scope", ""), ",".join(leak.get("matched_route_targets", [])),
                leak.get("policy_state", ""), leak.get("operational_state", ""),
                leak.get("verification_scope", ""), leak.get("prefix_summary", {}).get("expected", 0),
                leak.get("prefix_summary", {}).get("received", 0),
            ]
        )
    return output.getvalue().rstrip("\n").splitlines()


def route_target_display_values(
    service: Mapping[str, Any],
    direction: str,
) -> list[str]:
    """Return effective EVPN RT values with an explicit auto-origin marker."""
    values = service.get(f"{direction}_route_targets", [])
    auto_values = {
        str(item["resolved_value"])
        for item in service.get("route_target_observations", [])
        if item.get("scope") == "evpn"
        and item.get("direction") == direction
        and str(item.get("configured_value", "")).casefold() == "auto"
        and item.get("resolved_value")
    }
    return [
        f"{value} (auto)" if str(value) in auto_values else str(value)
        for value in values
    ]


def _detail_route_leak_groups(
    service_id: str,
    route_leaks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate Detail relations by direction and direct peer service."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for leak in route_leaks:
        if leak.get("source_service") == service_id:
            direction = "outbound"
            peer = str(leak.get("destination_service"))
        elif leak.get("destination_service") == service_id:
            direction = "inbound"
            peer = str(leak.get("source_service"))
        else:
            continue
        group = groups.setdefault(
            (direction, peer),
            {
                "direction": direction,
                "peer": peer,
                "route_targets": set(),
                "address_families": set(),
                "states_by_af": defaultdict(set),
            },
        )
        group["route_targets"].update(
            str(value) for value in leak.get("matched_route_targets", [])
        )
        address_families = {
            str(value) for value in leak.get("address_families", [])
        } or {"unknown"}
        group["address_families"].update(address_families)
        state = str(leak.get("operational_state", "unknown"))
        for address_family in address_families:
            group["states_by_af"][address_family].add(state)

    output = []
    for _key, group in sorted(groups.items()):
        states_by_af = {
            address_family: sorted(states)
            for address_family, states in sorted(group["states_by_af"].items())
        }
        all_states = sorted(
            {
                state
                for states in states_by_af.values()
                for state in states
            }
        )
        state_display = (
            "unknown"
            if not all_states
            else all_states[0]
            if len(all_states) == 1
            else "; ".join(
                f"{address_family}={','.join(states)}"
                for address_family, states in states_by_af.items()
            )
        )
        state_priority = {
            "conflict": 0,
            "degraded": 1,
            "unknown": 2,
            "configured": 3,
            "not-applicable": 4,
            "verified": 5,
        }
        link_state = min(
            all_states or ["unknown"],
            key=lambda value: (state_priority.get(value, 99), value),
        )
        output.append(
            {
                "direction": group["direction"],
                "peer": group["peer"],
                "route_targets": sorted(group["route_targets"]),
                "address_families": sorted(group["address_families"]),
                "state_display": state_display,
                "link_state": link_state,
                "candidate": not all_states or any(
                    state not in {"verified", "degraded"}
                    for state in all_states
                ),
            }
        )
    return output


L3VNI_MODE_DISPLAY = {
    "new_l3vni": "New L3VNI (VLAN/SVI-less)",
    "traditional_vlan_svi": "Traditional VLAN/SVI",
    "conflict": "Conflict",
    "unknown": "Unknown",
}


def _binding_group_lines(
    bindings: Sequence[Mapping[str, Any]],
    *,
    l3vni: bool = False,
) -> list[str]:
    grouped: dict[tuple[Any, Any], list[str]] = defaultdict(list)
    for binding in bindings:
        grouped[(binding.get("vlan"), binding.get("svi"))].append(
            str(binding.get("node", ""))
        )
    lines = []
    for (vlan, svi), nodes in sorted(
        grouped.items(),
        key=lambda item: (
            int(item[0][0]) if item[0][0] is not None else -1,
            str(item[0][1] or ""),
        ),
    ):
        if vlan is None:
            mapping = "VLAN/SVI: not applicable"
        elif l3vni and svi:
            behavior = next(
                (
                    str(binding.get("svi_behavior"))
                    for binding in bindings
                    if binding.get("vlan") == vlan
                    and binding.get("svi") == svi
                    and binding.get("svi_behavior")
                ),
                None,
            )
            suffix = f": {behavior}" if behavior else ""
            mapping = f"VLAN {vlan} (L3VNI SVI{suffix})"
        elif l3vni:
            mapping = f"VLAN {vlan} (L3VNI SVI missing)"
        elif svi:
            mapping = f"VLAN {vlan} (SVI)"
        else:
            mapping = f"VLAN {vlan} (L2-only)"
        lines.append(f"{mapping}: {', '.join(sorted(nodes))}")
    return lines


def _vpc_placement_roles(
    placements: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, int]], list[str]]:
    """Resolve safe visual vPC groups while preserving every placement node."""
    candidates: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    for placement in placements:
        domain = str(placement.get("vpc_domain") or "").strip()
        shared_addresses = tuple(
            sorted(str(value) for value in placement.get("vpc_shared_vtep_addresses", []))
        )
        if domain and shared_addresses:
            candidates[(domain, shared_addresses)].append(str(placement.get("node")))

    node_roles: dict[str, str] = {}
    dynamic_roles: dict[str, dict[str, int]] = {}
    placement_roles: list[str] = []
    layout_order = 10
    for (domain, shared_addresses), raw_nodes in sorted(candidates.items()):
        nodes = sorted(set(raw_nodes))
        if len(nodes) != 2:
            continue
        role = (
            f"vPC Domain {domain} · shared VTEP "
            + ", ".join(shared_addresses)
        )
        dynamic_roles[role] = {
            "priority": 40,
            "layout_order": layout_order,
        }
        placement_roles.append(role)
        for node in nodes:
            node_roles[node] = role
        layout_order += 10

    for placement in placements:
        node = str(placement.get("node"))
        if node not in node_roles:
            node_roles[node] = "placement"
    if "placement" in node_roles.values():
        placement_roles.append("placement")
    return node_roles, dynamic_roles, placement_roles


def _rendered_binding_relation_count(
    relations: Sequence[tuple[str, str, str]],
    *,
    node_roles: Mapping[str, str],
    vpc_group_roles: set[str],
) -> int:
    """Count draw.io relations after complete vPC member sets are collapsed."""
    count = len(relations)
    members_by_role: dict[str, set[str]] = defaultdict(set)
    for node, role in node_roles.items():
        if role in vpc_group_roles:
            members_by_role[role].add(node)
    destinations = {destination for _source, destination, _label in relations}
    for members in members_by_role.values():
        if len(members) < 2:
            continue
        for destination in destinations:
            related_members = {
                source
                for source, target, _label in relations
                if target == destination and source in members
            }
            if related_members == members:
                count -= len(members) - 1
    return count


def overlay_service_detail_render_context(
    service: Mapping[str, Any],
    route_leaks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a common renderer context for one VRF/L2 service detail page."""
    service_id = str(service["service_id"])
    center = f"Service {service_id}"
    inventory: dict[str, dict[str, Any]] = {}
    lines: dict[str, list[str]] = {}
    node_roles: dict[str, str] = {}
    confirmed: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    roles = {
        "inbound": {"priority": 10, "layout_order": 10},
        "outbound": {"priority": 10, "layout_order": 20},
        "service": {"priority": 20, "layout_order": 10},
        "l3vni-interface": {"priority": 30, "layout_order": 10},
        "l2-service": {"priority": 30, "layout_order": 20},
        "service-edge": {"priority": 30, "layout_order": 30},
        "placement": {"priority": 40, "layout_order": 10},
    }
    placements = list(service.get("placements", []))
    evpn_placements = [
        placement
        for placement in placements
        if placement.get("placement_type") != "service-edge"
    ]
    service_edges = [
        placement
        for placement in placements
        if placement.get("placement_type") == "service-edge"
    ]
    placement_role_map, vpc_roles, placement_roles = _vpc_placement_roles(
        evpn_placements
    )
    roles.update(vpc_roles)

    def add_node(node: str, role: str, detail_lines: Sequence[str]) -> None:
        inventory[node] = {"hostname": node, "device_type": "unknown"}
        node_roles[node] = role
        lines[node] = [str(value) for value in detail_lines if str(value)]

    def add_link(
        source: str,
        destination: str,
        label: str,
        *,
        directed: bool,
        candidate: bool = False,
        state: str = "configured",
    ) -> None:
        link = {
            "endpoints": [f"{source}:", f"{destination}:"],
            "evidence": "",
            "label": label,
            "directed": directed,
            "state": state,
        }
        labels[f"{source}||{destination}|"] = label
        (candidates if candidate else confirmed).append(link)

    add_node(
        center,
        "service",
        [
            f"VRF: {service.get('vrf')}",
            f"L3VNI: {service.get('l3vni')}",
            "L3VNI Mode: "
            + L3VNI_MODE_DISPLAY.get(
                str(service.get("l3vni_mode", "unknown")), "Unknown"
            ),
            f"RD: {service.get('route_distinguisher')}",
            f"Status: {service.get('status')}",
        ],
    )
    placement_nodes: dict[str, str] = {}
    for placement in evpn_placements:
        node = f"Placement {placement.get('node')}"
        placement_nodes[str(placement.get("node"))] = node
        add_node(
            node,
            placement_role_map[str(placement.get("node"))],
            [
                f"VTEP: {', '.join(placement.get('vtep_addresses', [])) or '-'}",
                "vPC shared VTEP: "
                + (", ".join(placement.get("vpc_shared_vtep_addresses", [])) or "-"),
                f"NVE L3 member: {str(bool(placement.get('nve_l3_member'))).lower()}",
            ],
        )
    for placement in service_edges:
        node = f"Service Edge {placement.get('node')}"
        add_node(
            node,
            "service-edge",
            [
                "Type: VRF service edge",
                "Evidence: VRF present; EVPN binding absent",
            ],
        )
        add_link(center, node, "VRF attachment", directed=False)

    binding_relations: list[tuple[str, str, str]] = []
    bound_placement_nodes: set[str] = set()
    if service.get("l3vni") is not None:
        l3_node = f"L3VNI {service.get('l3vni')}"
        add_node(
            l3_node,
            "l3vni-interface",
            [
                "Mode: "
                + L3VNI_MODE_DISPLAY.get(
                    str(service.get("l3vni_mode", "unknown")), "Unknown"
                ),
                *_binding_group_lines(
                    service.get("l3vni_bindings", []), l3vni=True
                ),
            ],
        )
        add_link(center, l3_node, "L3VNI", directed=False)
        for binding in service.get("l3vni_bindings", []):
            placement_node = placement_nodes.get(str(binding.get("node")))
            if not placement_node:
                continue
            binding_relations.append((placement_node, l3_node, ""))
            bound_placement_nodes.add(placement_node)

    for l2_service in service.get("l2_services", []):
        l2vni = l2_service.get("l2vni")
        node = f"L2VNI {l2vni}"
        add_node(
            node,
            "l2-service",
            [
                *_binding_group_lines(l2_service.get("bindings", [])),
                f"Gateway: {l2_service.get('gateway_state', 'unknown')}",
                f"IPv4: {', '.join(l2_service.get('ipv4_addresses', [])) or '-'}",
                f"IPv6: {', '.join(l2_service.get('ipv6_addresses', [])) or '-'}",
                f"NVE member: {str(bool(l2_service.get('nve_member'))).lower()}",
            ],
        )
        add_link(center, node, "L2 service", directed=False)
        for binding in l2_service.get("bindings", []):
            placement_node = placement_nodes.get(str(binding.get("node")))
            if not placement_node:
                continue
            binding_relations.append(
                (
                    placement_node,
                    node,
                    "",
                )
            )
            bound_placement_nodes.add(placement_node)

    for placement_node in placement_nodes.values():
        if placement_node not in bound_placement_nodes:
            lines[placement_node].append("Component binding: unresolved")

    rendered_binding_count = _rendered_binding_relation_count(
        binding_relations,
        node_roles=node_roles,
        vpc_group_roles=set(vpc_roles),
    )
    if rendered_binding_count <= OVERLAY_DETAIL_BINDING_EDGE_LIMIT:
        for source, destination, label in binding_relations:
            add_link(source, destination, label, directed=False)
    elif binding_relations:
        lines[center].append(
            "Binding edges omitted: "
            f"{rendered_binding_count} grouped / {len(binding_relations)} node "
            "relations (see Markdown)"
        )

    route_leak_groups = _detail_route_leak_groups(service_id, route_leaks)
    matched_targets = {
        direction: {
            route_target
            for group in route_leak_groups
            if group["direction"] == direction
            for route_target in group["route_targets"]
        }
        for direction in ("inbound", "outbound")
    }
    for direction, role, leak_direction in (
        ("import", "inbound", "inbound"),
        ("export", "outbound", "outbound"),
    ):
        for display_value in route_target_display_values(service, direction):
            raw_value = display_value.removesuffix(" (auto)")
            is_same_vrf = display_value.endswith(" (auto)")
            if is_same_vrf:
                node = (
                    f"Same-VRF {direction.title()} RT "
                    f"{raw_value.replace(':', '-')}"
                )
                add_node(
                    node,
                    role,
                    [f"RT: {display_value}", "Purpose: EVPN service"],
                )
                edge_label = f"same-VRF {direction}"
            elif raw_value not in matched_targets[leak_direction]:
                node = (
                    f"Additional {direction.title()} RT "
                    f"{raw_value.replace(':', '-')}"
                )
                add_node(
                    node,
                    role,
                    [f"RT: {display_value}", "Peer: unresolved"],
                )
                edge_label = f"additional {direction}"
            else:
                continue
            if direction == "import":
                add_link(node, center, edge_label, directed=True)
            else:
                add_link(center, node, edge_label, directed=True)

    for group in route_leak_groups:
        direction = str(group["direction"])
        peer = str(group["peer"])
        node = f"{direction.title()} Route Leak {peer}"
        if direction == "outbound":
            role = "outbound"
            source, destination = center, node
            peer_line = f"To: {peer}"
        else:
            role = "inbound"
            source, destination = node, center
            peer_line = f"From: {peer}"
        add_node(
            node,
            role,
            [
                peer_line,
                f"RT: {', '.join(group['route_targets']) or '-'}",
                f"AF: {', '.join(group['address_families']) or '-'}",
                f"State: {group['state_display']}",
            ],
        )
        add_link(
            source,
            destination,
            "route leak",
            directed=True,
            candidate=bool(group["candidate"]),
            state=str(group["link_state"]),
        )

    detail_site = str(service.get("site") or "detail")
    return {
        "roles": roles,
        "sites": {detail_site: {"priority": 10}},
        "normalized_inventory_map": inventory,
        "normalized_mgmt_ip_map": {},
        "rendered_links": confirmed,
        "rendered_candidate_links": candidates,
        "node_address_map": None,
        "node_address_label_map": None,
        "node_address_lines_map": lines,
        "link_label_map": labels,
        "node_interface_label_map": None,
        "node_role_map": node_roles,
        "placement_roles": placement_roles,
        "vpc_group_roles": sorted(vpc_roles),
        "node_site_map": {node: detail_site for node in inventory},
        "title": f"Overlay Service Detail: {service_id}",
    }


def overlay_service_detail_markdown_lines(
    service: Mapping[str, Any],
    route_leaks: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Render one stable human-readable Overlay Service detail."""
    lines = [f"# Overlay Service: {service['service_id']}", ""]
    lines.extend(
        [
            f"- Site: `{service.get('site')}`",
            f"- VRF: `{service.get('vrf')}`",
            f"- L3VNI: `{service.get('l3vni')}`",
            "- L3VNI Mode: `"
            + L3VNI_MODE_DISPLAY.get(
                str(service.get("l3vni_mode", "unknown")), "Unknown"
            )
            + "`",
            f"- RD: `{service.get('route_distinguisher')}`",
            f"- Status: `{service.get('status')}`",
            "",
            "## Route Targets",
            "",
            f"- Import: `{', '.join(route_target_display_values(service, 'import'))}`",
            f"- Export: `{', '.join(route_target_display_values(service, 'export'))}`",
        ]
    )
    evpn_placements = [
        item
        for item in service.get("placements", [])
        if item.get("placement_type") != "service-edge"
    ]
    service_edges = [
        item
        for item in service.get("placements", [])
        if item.get("placement_type") == "service-edge"
    ]
    lines.extend(
        [
            "",
            "## EVPN Placements",
            "",
            "| Node | Type | VTEP | vPC shared VTEP | NVE L3 member |",
            "|---|---|---|---|---|",
        ]
    )
    for item in evpn_placements:
        lines.append(
            "| " + " | ".join(
                [
                    str(item.get("node", "")),
                    str(item.get("placement_type", "")),
                    ", ".join(item.get("vtep_addresses", [])),
                    ", ".join(item.get("vpc_shared_vtep_addresses", [])),
                    str(bool(item.get("nve_l3_member"))).lower(),
                ]
            ) + " |"
        )
    if service_edges:
        lines.extend(
            [
                "",
                "## Service Edge Attachments",
                "",
                "| Node | Type | Evidence |",
                "|---|---|---|",
            ]
        )
        for item in service_edges:
            lines.append(
                f"| {item.get('node', '')} | service-edge | "
                "VRF present; EVPN binding absent |"
            )
    lines.extend(
        [
            "", "## L3VNI Interfaces", "",
            "| Node | L3VNI | L3VNI Mode | VLAN | SVI | SVI behavior | NVE associate-vrf | IPv4 | IPv6 |",
            "|---|---:|---|---:|---|---|---|---|---|",
        ]
    )
    for binding in service.get("l3vni_bindings", []):
        ipv6 = list(binding.get("ipv6_addresses", []))
        if binding.get("ipv6_use_link_local_only"):
            ipv6.append("link-local-only")
        lines.append(
            "| " + " | ".join(
                [
                    str(binding.get("node", "")),
                    str(service.get("l3vni") or ""),
                    L3VNI_MODE_DISPLAY.get(
                        str(binding.get("mode", "unknown")), "Unknown"
                    ),
                    str(binding.get("vlan") or "-"),
                    str(binding.get("svi") or "-"),
                    str(binding.get("svi_behavior") or "-"),
                    str(bool(binding.get("nve_associate_vrf"))).lower(),
                    ", ".join(binding.get("ipv4_addresses", [])) or "-",
                    ", ".join(ipv6) or "-",
                ]
            ) + " |"
        )
    lines.extend(
        [
            "", "## L2 Services", "",
            "| L2VNI | Node | VLAN | SVI | Gateway | IPv4 SVI address | IPv6 SVI address | NVE member |",
            "|---:|---|---:|---|---|---|---|---|",
        ]
    )
    for item in service.get("l2_services", []):
        bindings = item.get("bindings", [])
        if not bindings:
            lines.append(
                f"| {item.get('l2vni', '')} | - | - | - | unknown | - | - | "
                f"{str(bool(item.get('nve_member'))).lower()} |"
            )
        for binding in bindings:
            lines.append(
                f"| {item.get('l2vni', '')} | {binding.get('node', '')} | "
                f"{binding.get('vlan', '')} | {binding.get('svi') or '-'} | "
                f"{'yes' if binding.get('gateway') else 'no'} | "
                f"{', '.join(binding.get('ipv4_addresses', [])) or '-'} | "
                f"{', '.join(binding.get('ipv6_addresses', [])) or '-'} | "
                f"{str(bool(binding.get('nve_member'))).lower()} |"
            )
    lines.extend(
        [
            "", "## Route Leaks", "",
            "| Direction | Peer Service | AF | RT | Policy | Operational | Scope |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    service_id = str(service["service_id"])
    for leak in route_leaks:
        if leak.get("source_service") == service_id:
            direction, peer = "outbound", leak.get("destination_service")
        elif leak.get("destination_service") == service_id:
            direction, peer = "inbound", leak.get("source_service")
        else:
            continue
        lines.append(
            "| " + " | ".join(
                [
                    direction, str(peer), ",".join(leak.get("address_families", [])),
                    ",".join(leak.get("matched_route_targets", [])),
                    str(leak.get("policy_state", "")), str(leak.get("operational_state", "")),
                    str(leak.get("verification_scope", "")),
                ]
            ) + " |"
        )
    return lines


def service_detail_filename(service_id: str, suffix: str = ".md") -> str:
    """Return a portable deterministic filename for one service identity."""
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", service_id).strip("._") or "service"
    digest = hashlib.sha256(service_id.encode()).hexdigest()[:8]
    return f"{normalized}-{digest}{suffix}"
