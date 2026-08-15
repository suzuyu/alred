"""Canonical EVPN control-plane model and diagram adapters."""

from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
from typing import Any, Callable, Mapping

from .health.overlay import (
    EVPN_CONTROL_PLANE_PARSER_VERSION,
    parse_evpn_control_plane_running_config,
)
from .health.parsers import NXOS_PARSER_VERSION, ParserError, parse_nxos_command
from .schema import API_VERSION


class EVPNDiagramError(ValueError):
    """Expected EVPN evidence parsing failure."""

    code = "PARSER_UNSUPPORTED"


def _pure_address(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_interface(value).ip)
    except ValueError:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return None


def _interface_addresses(config: Mapping[str, Any], interface: str | None) -> list[str]:
    if not interface:
        return []
    item = config.get("interfaces", {}).get(str(interface).lower(), {})
    return [
        address
        for value in item.get("addresses", [])
        if (address := _pure_address(str(value))) is not None
    ]


def _stable_session_id(endpoints: list[dict[str, Any]], relationship: str) -> str:
    material = "|".join(
        f"{item['node']}@{item.get('address') or ''}"
        for item in sorted(endpoints, key=lambda value: (value["node"], value.get("address") or ""))
    )
    digest = hashlib.sha256(f"{material}|{relationship}".encode()).hexdigest()[:16]
    return f"evpn-{digest}"


def _session_sort_key(session: Mapping[str, Any]) -> tuple[Any, ...]:
    endpoints = session.get("endpoints", [])
    return tuple(
        (str(item.get("node", "")), str(item.get("address", "")))
        for item in endpoints
    )


def _diagnostic(code: str, **context: Any) -> dict[str, Any]:
    return {"code": code, **context}


def build_evpn_control_plane_model(
    running_configs: Mapping[str, str],
    *,
    operational_summaries: Mapping[str, str] | None = None,
    node_roles: Mapping[str, str] | None = None,
    node_functions: Mapping[str, list[str]] | None = None,
    node_sites: Mapping[str, str] | None = None,
    source: Mapping[str, str] | None = None,
    source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic EVPN model from verified NX-OS evidence."""
    parsed: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for hostname, text in sorted(running_configs.items()):
        parsed[hostname] = parse_evpn_control_plane_running_config(text)

    address_nodes: dict[str, set[str]] = {}
    for hostname, config in parsed.items():
        for interface in config.get("interfaces", {}).values():
            for value in interface.get("addresses", []):
                address = _pure_address(str(value))
                if address:
                    address_nodes.setdefault(address, set()).add(hostname)
        for process in config.get("processes", {}).values():
            address = _pure_address(process.get("router_id"))
            if address:
                address_nodes.setdefault(address, set()).add(hostname)

    secondary_vtep_nodes: dict[str, set[str]] = {}
    for hostname, config in parsed.items():
        if not config.get("vpc_domain"):
            continue
        for interface in config.get("nve_source_interfaces", []):
            item = config.get("interfaces", {}).get(str(interface).lower(), {})
            for value in item.get("secondary_addresses", []):
                address = _pure_address(str(value))
                if address:
                    secondary_vtep_nodes.setdefault(address, set()).add(hostname)
    vpc_shared_vtep_addresses = {
        address
        for address, hostnames in secondary_vtep_nodes.items()
        if len(hostnames) >= 2
    }

    def resolve_node(address: str, observer: str) -> str | None:
        matches = sorted(address_nodes.get(address, set()) - {observer})
        if len(matches) == 1:
            return matches[0]
        code = "EVPN_PEER_UNRESOLVED" if not matches else "EVPN_PEER_AMBIGUOUS"
        diagnostics.append(
            _diagnostic(code, observer=observer, peer_address=address, matches=matches)
        )
        return None

    nodes: dict[str, dict[str, Any]] = {}
    node_records: dict[str, dict[str, Any]] = {}
    ranges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    configured_observations: list[dict[str, Any]] = []
    for hostname, config in parsed.items():
        router_ids = sorted(
            {
                address
                for process in config.get("processes", {}).values()
                if (address := _pure_address(process.get("router_id")))
            }
        )
        update_addresses: set[str] = set()
        observed_rr = False
        for local_as, process in sorted(config.get("processes", {}).items()):
            for peer, values in sorted(process.get("neighbors", {}).items()):
                address_families = values.get("address_families", {})
                af = address_families.get("l2vpn-evpn", {})
                if (
                    "l2vpn-evpn" not in address_families
                    and values.get("resolution_status") != "unresolved"
                ):
                    continue
                if values.get("resolution_status", "resolved") != "resolved":
                    unresolved.append(
                        {
                            "observer": hostname,
                            "peer_address": peer,
                            "reason": "peer-template-resolution",
                        }
                    )
                    continue
                local_addresses = _interface_addresses(config, values.get("update_source"))
                update_addresses.update(local_addresses)
                if not local_addresses and process.get("router_id"):
                    local_addresses = [str(process["router_id"])]
                try:
                    network = ipaddress.ip_network(peer, strict=False)
                except ValueError:
                    unresolved.append(
                        {
                            "observer": hostname,
                            "peer_address": peer,
                            "reason": "invalid-address",
                        }
                    )
                    diagnostics.append(
                        _diagnostic(
                            "EVPN_PEER_UNRESOLVED",
                            observer=hostname,
                            peer_address=peer,
                            reason="invalid-address",
                        )
                    )
                    continue
                rr_client = bool(af.get("route_reflector_client"))
                if network.prefixlen != network.max_prefixlen:
                    ranges.append(
                        {
                            "node": hostname,
                            "prefix": str(network),
                            "local_as": str(local_as),
                            "remote_as": str(values.get("remote_as", "")),
                            "update_source": values.get("update_source"),
                            "route_reflector_client": rr_client,
                            "resolution_status": values.get("resolution_status", "resolved"),
                        }
                    )
                    observed_rr = observed_rr or rr_client
                    continue
                peer_address = str(network.network_address)
                target = resolve_node(peer_address, hostname)
                observation = {
                    "observer": hostname,
                    "peer_node": target,
                    "peer_address": peer_address,
                    "local_address": local_addresses[0] if local_addresses else None,
                    "local_as": str(local_as),
                    "remote_as": str(values.get("remote_as", "")),
                    "configured": True,
                    "route_reflector_client": rr_client,
                    "source": af.get("source", "direct"),
                }
                if target is None:
                    unresolved.append(
                        {
                            "observer": hostname,
                            "peer_address": peer_address,
                            "reason": "node-resolution",
                        }
                    )
                else:
                    configured_observations.append(observation)
                observed_rr = observed_rr or rr_client
            for error in process.get("resolution_errors", []):
                diagnostics.append(
                    _diagnostic(
                        "EVPN_PEER_TEMPLATE_UNRESOLVED",
                        node=hostname,
                        local_as=str(local_as),
                        detail=error,
                    )
                )

        vtep_addresses: set[str] = set()
        for interface in config.get("nve_source_interfaces", []):
            vtep_addresses.update(_interface_addresses(config, interface))
        expected_functions = set((node_functions or {}).get(hostname, []))
        observed_functions = set()
        if observed_rr:
            observed_functions.add("evpn-route-reflector")
        if vtep_addresses:
            observed_functions.add("vtep")
        for function in sorted(observed_functions - expected_functions):
            diagnostics.append(
                _diagnostic(
                    "EVPN_ROLE_FUNCTION_MISMATCH",
                    node=hostname,
                    function=function,
                    expected=False,
                    observed=True,
                )
            )
        for function in sorted(expected_functions - observed_functions):
            diagnostics.append(
                _diagnostic(
                    "EVPN_ROLE_FUNCTION_MISMATCH",
                    node=hostname,
                    function=function,
                    expected=True,
                    observed=False,
                )
            )
        node_record = {
            "topology_role": (node_roles or {}).get(hostname, "other"),
            "site": (node_sites or {}).get(hostname),
            "functions": sorted(expected_functions),
            "observed_functions": sorted(observed_functions),
            "router_id": router_ids[0] if router_ids else None,
            "update_source_addresses": sorted(update_addresses),
            "vtep_addresses": sorted(vtep_addresses),
            "vpc_domain": config.get("vpc_domain"),
            "vpc_shared_vtep_addresses": sorted(
                vtep_addresses.intersection(vpc_shared_vtep_addresses)
            ),
            "cluster_ids": sorted(
                {
                    str(process["cluster_id"])
                    for process in config.get("processes", {}).values()
                    if process.get("cluster_id") is not None
                }
            ),
            "evidence_refs": [f"{hostname}:running_config"],
        }
        node_records[hostname] = node_record
        if (
            not config.get("processes")
            and not vtep_addresses
            and not expected_functions
        ):
            continue
        nodes[hostname] = node_record

    operational_by_observer: dict[str, dict[str, Any]] = {}
    for hostname, text in sorted((operational_summaries or {}).items()):
        try:
            _common, profiles = parse_nxos_command("bgp_l2vpn_evpn_summary", text)
            operational_by_observer[hostname] = profiles["nxos-overlay"]["evpn_bgp"]
        except (KeyError, ParserError) as exc:
            raise EVPNDiagramError(
                "EVPN operational evidence could not be parsed: "
                f"{hostname}:bgp_l2vpn_evpn_summary: {exc}"
            ) from exc

    session_map: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def session_for(
        observer: str,
        target: str,
        local_address: str | None,
        peer_address: str,
    ) -> dict[str, Any]:
        ordered = sorted(
            [(observer, local_address or ""), (target, peer_address)],
            key=lambda item: (item[0], item[1]),
        )
        key = (ordered[0][0], ordered[0][1], ordered[1][0], ordered[1][1])
        return session_map.setdefault(
            key,
            {
                "endpoints": [
                    {"node": node, "address": address or None, "local_as": None}
                    for node, address in ordered
                ],
                "relationship": "unknown",
                "rr_node": None,
                "client_node": None,
                "state": "configured",
                "resolution_status": "confirmed",
                "observations": [],
                "evidence_refs": [],
            },
        )

    for observation in configured_observations:
        observer = str(observation["observer"])
        target = str(observation["peer_node"])
        session = session_for(
            observer,
            target,
            observation.get("local_address"),
            str(observation["peer_address"]),
        )
        session["observations"].append(observation)
        session["evidence_refs"].append(f"{observer}:running_config")
        for endpoint in session["endpoints"]:
            if endpoint["node"] == observer:
                endpoint["local_as"] = observation["local_as"]
        if observation["route_reflector_client"]:
            session["relationship"] = "rr-client"
            session["rr_node"] = observer
            session["client_node"] = target

    for session in session_map.values():
        endpoint_by_node = {item["node"]: item for item in session["endpoints"]}
        for observation in session["observations"]:
            observer = str(observation["observer"])
            peer = str(observation["peer_node"])
            local_address = endpoint_by_node[observer].get("address")
            matching_ranges = []
            if local_address:
                for item in ranges:
                    if item["node"] != peer or not item["route_reflector_client"]:
                        continue
                    if ipaddress.ip_address(local_address) in ipaddress.ip_network(item["prefix"]):
                        matching_ranges.append(item)
            if len(matching_ranges) == 1:
                if session["rr_node"] not in {None, peer}:
                    session["state"] = "conflict"
                    diagnostics.append(
                        _diagnostic(
                            "EVPN_SESSION_STATE_CONFLICT",
                            nodes=sorted(endpoint_by_node),
                            reason="multiple-rr-directions",
                        )
                    )
                else:
                    session["relationship"] = "rr-client"
                    session["rr_node"] = peer
                    session["client_node"] = observer
                    endpoint_by_node[peer]["local_as"] = matching_ranges[0][
                        "local_as"
                    ]
            elif len(matching_ranges) > 1:
                session["resolution_status"] = "conflict"
                diagnostics.append(
                    _diagnostic(
                        "EVPN_PEER_AMBIGUOUS",
                        observer=observer,
                        peer_node=peer,
                        peer_address=local_address,
                        matches=[item["prefix"] for item in matching_ranges],
                    )
                )
        if session["relationship"] == "unknown":
            local_as_values = {
                str(item.get("local_as"))
                for item in session["endpoints"]
                if item.get("local_as")
            }
            if len(local_as_values) == 1:
                session["relationship"] = "ibgp-peer"
            elif len(local_as_values) > 1:
                session["relationship"] = "ebgp-peer"

    for observer, operational in sorted(operational_by_observer.items()):
        for peer_address, peer_data in sorted(operational.get("neighbors", {}).items()):
            address = _pure_address(peer_address)
            if address is None:
                continue
            target = resolve_node(address, observer)
            if target is None:
                unresolved.append(
                    {
                        "observer": observer,
                        "peer_address": peer_address,
                        "reason": "operational-node-resolution",
                    }
                )
                continue
            local_address = None
            observer_node = nodes.get(observer, {})
            candidates = observer_node.get("update_source_addresses", []) or [
                observer_node.get("router_id")
            ]
            if candidates and candidates[0]:
                local_address = str(candidates[0])
            session = session_for(observer, target, local_address, address)
            state_value = str(peer_data.get("state", "Unknown"))
            state = "established" if state_value.lower() == "established" else "down"
            session["observations"].append(
                {
                    "observer": observer,
                    "peer_node": target,
                    "peer_address": address,
                    "configured": False,
                    "state": state_value,
                    "prefixes_received": peer_data.get("prefixes_received"),
                    "remote_as": peer_data.get("remote_as"),
                }
            )
            session["evidence_refs"].append(
                f"{observer}:bgp_l2vpn_evpn_summary"
            )
            operational_states = {
                str(item.get("state", "")).lower()
                for item in session["observations"]
                if not item.get("configured") and item.get("state")
            }
            normalized_states = {
                "established" if value == "established" else "down"
                for value in operational_states
            }
            if len(normalized_states) > 1:
                session["state"] = "conflict"
                diagnostics.append(
                    _diagnostic(
                        "EVPN_SESSION_STATE_CONFLICT",
                        nodes=sorted(item["node"] for item in session["endpoints"]),
                        states=sorted(operational_states),
                    )
                )
            else:
                session["state"] = state

    def ensure_model_node(hostname: str) -> None:
        if hostname in nodes:
            return
        if hostname in node_records:
            nodes[hostname] = node_records[hostname]
            return
        nodes[hostname] = {
            "topology_role": (node_roles or {}).get(hostname, "other"),
            "site": (node_sites or {}).get(hostname),
            "functions": sorted((node_functions or {}).get(hostname, [])),
            "observed_functions": [],
            "router_id": None,
            "update_source_addresses": [],
            "vtep_addresses": [],
            "vpc_domain": None,
            "vpc_shared_vtep_addresses": [],
            "cluster_ids": [],
            "evidence_refs": [],
        }

    for hostname in sorted(operational_by_observer):
        ensure_model_node(hostname)
        nodes[hostname]["evidence_refs"] = sorted(
            set(nodes[hostname]["evidence_refs"])
            | {f"{hostname}:bgp_l2vpn_evpn_summary"}
        )
    for session in session_map.values():
        for endpoint in session["endpoints"]:
            ensure_model_node(str(endpoint["node"]))

    for session in session_map.values():
        observers = {
            str(item["observer"])
            for item in session["observations"]
            if item.get("configured")
        }
        operational_observers = {
            str(item["observer"])
            for item in session["observations"]
            if not item.get("configured")
        }
        if not operational_observers and observers.intersection(operational_by_observer):
            session["state"] = "unknown"
        session["evidence_refs"] = sorted(set(session["evidence_refs"]))
        session["observations"].sort(
            key=lambda item: (
                str(item.get("observer", "")),
                str(item.get("peer_address", "")),
                bool(item.get("configured")),
            )
        )
        session["session_id"] = _stable_session_id(
            session["endpoints"], str(session["relationship"])
        )

    sessions = sorted(session_map.values(), key=_session_sort_key)
    has_evidence = bool(
        any(config.get("processes") for config in parsed.values())
        or operational_by_observer
    )
    if not has_evidence:
        status = "insufficient-evidence"
    elif unresolved or any(
        session["resolution_status"] == "conflict" for session in sessions
    ):
        status = "partial"
    else:
        status = "complete"

    metadata: dict[str, Any] = {"source": dict(source or {"type": "file", "value": "running-config"})}
    if source_manifest_sha256:
        metadata["source_manifest_sha256"] = source_manifest_sha256
    return {
        "api_version": API_VERSION,
        "kind": "EVPNControlPlaneModel",
        "metadata": metadata,
        "spec": {
            "status": status,
            "parser_versions": {
                "running_config": EVPN_CONTROL_PLANE_PARSER_VERSION,
                "bgp_l2vpn_evpn_summary": NXOS_PARSER_VERSION,
            },
            "nodes": {name: nodes[name] for name in sorted(nodes)},
            "sessions": sessions,
            "peer_ranges": sorted(
                ranges, key=lambda item: (str(item["node"]), str(item["prefix"]))
            ),
            "unresolved_peers": sorted(
                unresolved,
                key=lambda item: (
                    str(item.get("observer", "")),
                    str(item.get("peer_address", "")),
                    str(item.get("reason", "")),
                ),
            ),
            "diagnostics": sorted(
                diagnostics,
                key=lambda item: (
                    str(item.get("code", "")),
                    str(item.get("node", item.get("observer", ""))),
                    str(item.get("peer_address", "")),
                ),
            ),
        },
    }


def evpn_model_to_render_context(
    model: Mapping[str, Any],
    *,
    inventory_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Adapt an EVPN model to the common diagram renderer input contract."""
    nodes = model.get("spec", {}).get("nodes", {})
    annotation_node = "EVPN evidence unavailable"
    normalized_inventory = {
        name: {
            **dict((inventory_map or {}).get(name, {})),
            "hostname": name,
            "device_type": str(
                (inventory_map or {}).get(name, {}).get("device_type", "nxos")
            ),
        }
        for name in nodes
    }
    node_lines: dict[str, list[str]] = {}
    node_roles: dict[str, str] = {}
    node_sites: dict[str, str] = {}
    for name, item in nodes.items():
        lines: list[str] = []
        observed = set(item.get("observed_functions", []))
        if "evpn-route-reflector" in observed:
            lines.append("EVPN RR")
        if item.get("router_id"):
            lines.append(f"Router ID: {item['router_id']}")
        for address in item.get("vtep_addresses", []):
            if address in set(item.get("vpc_shared_vtep_addresses", [])):
                lines.append(f"VTEP (vPC shared): {address}")
            else:
                lines.append(f"VTEP: {address}")
        node_lines[name] = lines
        node_roles[name] = str(item.get("topology_role") or "other")
        if item.get("site"):
            node_sites[name] = str(item["site"])
    if not nodes:
        normalized_inventory[annotation_node] = {
            "hostname": annotation_node,
            "device_type": "nxos",
        }
        node_lines[annotation_node] = [
            "No EVPN configuration or operational evidence"
        ]
        node_roles[annotation_node] = "diagnostic"
    elif (
        model.get("spec", {}).get("status") == "partial"
        or model.get("spec", {}).get("diagnostics")
    ):
        diagnostic_node = "EVPN diagnostics"
        diagnostics = model.get("spec", {}).get("diagnostics", [])
        diagnostic_counts: dict[str, int] = {}
        for item in diagnostics:
            code = str(item.get("code", "UNKNOWN"))
            diagnostic_counts[code] = diagnostic_counts.get(code, 0) + 1
        normalized_inventory[diagnostic_node] = {
            "hostname": diagnostic_node,
            "device_type": "nxos",
        }
        node_lines[diagnostic_node] = [
            f"Status: {model.get('spec', {}).get('status', 'unknown')}",
            "Unresolved peers: "
            f"{len(model.get('spec', {}).get('unresolved_peers', []))}",
            *[
                f"{code}: {count}"
                for code, count in sorted(diagnostic_counts.items())
            ],
        ]
        node_roles[diagnostic_node] = "diagnostic"

    rendered: list[dict[str, Any]] = []
    candidate: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    for session in model.get("spec", {}).get("sessions", []):
        endpoints = session.get("endpoints", [])
        if len(endpoints) != 2:
            continue
        relationship = str(session.get("relationship", "unknown"))
        rr_node = str(session.get("rr_node") or "")
        if relationship == "rr-client" and rr_node:
            display_endpoints = sorted(
                endpoints,
                key=lambda item: (
                    str(item.get("node")) != rr_node,
                    str(item.get("node", "")),
                    str(item.get("address") or ""),
                ),
            )
        else:
            display_endpoints = endpoints
        left, right = display_endpoints
        link = {
            "endpoints": [f"{left['node']}:", f"{right['node']}:"],
            "evidence": "",
        }
        state = str(session.get("state", "unknown"))
        label = f"{relationship} / {state}"
        link["label"] = label
        labels[f"{left['node']}||{right['node']}|"] = label
        if (
            state in {"configured", "unknown", "conflict"}
            or session.get("resolution_status") == "conflict"
        ):
            candidate.append(link)
        else:
            rendered.append(link)
    rendered.sort(
        key=lambda item: tuple(str(value) for value in item["endpoints"])
    )
    candidate.sort(
        key=lambda item: tuple(str(value) for value in item["endpoints"])
    )
    return {
        "normalized_inventory_map": normalized_inventory,
        "normalized_mgmt_ip_map": {},
        "rendered_links": rendered,
        "rendered_candidate_links": candidate,
        "node_address_map": None,
        "node_address_label_map": None,
        "node_address_lines_map": node_lines,
        "link_label_map": labels,
        "node_interface_label_map": None,
        "extra_node_names": sorted(normalized_inventory),
        "node_role_map": node_roles,
        "node_site_map": node_sites,
        "skipped_by_confidence": 0,
    }


def evpn_sessions_csv_lines(model: Mapping[str, Any]) -> list[str]:
    """Render stable review CSV rows for EVPN sessions."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "session_id",
            "left_node",
            "left_address",
            "right_node",
            "right_address",
            "relationship",
            "state",
            "resolution_status",
            "rr_node",
            "client_node",
        ]
    )
    for session in model.get("spec", {}).get("sessions", []):
        endpoints = session.get("endpoints", [{}, {}])
        left = endpoints[0] if len(endpoints) > 0 else {}
        right = endpoints[1] if len(endpoints) > 1 else {}
        values = [
            session.get("session_id", ""),
            left.get("node", ""),
            left.get("address", "") or "",
            right.get("node", ""),
            right.get("address", "") or "",
            session.get("relationship", ""),
            session.get("state", ""),
            session.get("resolution_status", ""),
            session.get("rr_node", "") or "",
            session.get("client_node", "") or "",
        ]
        writer.writerow(values)
    return output.getvalue().rstrip("\n").splitlines()
