"""Deterministic Health Check command groups derived from role policy."""

from __future__ import annotations

from typing import Any, Mapping


OVERLAY_COMMAND_IDS = {
    "nve_interface",
    "nve_peers",
    "nve_vni",
    "nve_vni_ingress_replication",
    "bgp_l2vpn_evpn_summary",
    "bgp_l2vpn_evpn",
    "route_ipv4_all_vrfs",
    "route_ipv6_all_vrfs",
    "vlan_brief",
    "vrf",
    "interface_brief",
}
VTEP_COMMAND_IDS = OVERLAY_COMMAND_IDS
EVPN_RR_COMMAND_IDS = {
    "bgp_l2vpn_evpn_summary",
    "bgp_l2vpn_evpn",
}


def build_role_command_groups(
    effective_profile: Mapping[str, Any],
    role_config: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    """Build collect groups while preserving v1/all-host compatibility."""
    commands = effective_profile["spec"].get("collectors", {}).get("nxos", {}).get(
        "commands", []
    )
    by_id = {
        str(item["id"]): str(item["command"])
        for item in commands
        if item["id"] != "running_config"
    }
    if role_config is None or int(role_config.get("schema_version", 1)) == 1:
        return {"device_type:nxos": [by_id[key] for key in sorted(by_id)]}

    groups: dict[str, list[str]] = {
        "device_type:nxos": [
            by_id[key]
            for key in sorted(by_id)
            if key not in OVERLAY_COMMAND_IDS
        ]
    }
    for role, rule in role_config.get("role_detection", {}).items():
        functions = rule.get("functions", {})
        selected: set[str] = set()
        if "vtep" in functions:
            selected.update(VTEP_COMMAND_IDS)
        if "evpn-route-reflector" in functions:
            selected.update(EVPN_RR_COMMAND_IDS)
        groups[str(role)] = [
            by_id[key] for key in sorted(selected) if key in by_id
        ]
    return groups


def render_role_command_groups(groups: Mapping[str, list[str]]) -> str:
    """Render a grouped show-commands file accepted by the shared collector."""
    lines: list[str] = []
    for group, commands in groups.items():
        lines.append(f"[{group}]")
        lines.extend(commands)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
