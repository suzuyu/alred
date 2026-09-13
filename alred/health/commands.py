"""Health command normalization and stable command identifiers."""

from __future__ import annotations

import re
import hashlib


COMMAND_IDS = {
    "show running-config": "running_config",
    "show running-config diff": "running_config_diff",
    "show running-config diff unified": "running_config_diff",
    "show version": "show_version",
    "show inventory": "inventory",
    "show license usage": "license_usage",
    "show processes cpu": "processes_cpu",
    "show system resources": "system_resources",
    "show environment": "environment",
    "show clock": "clock",
    "show ntp status": "ntp_status",
    "show ntp peers": "ntp_peers",
    "show ntp peer-status": "ntp_peer_status",
    "show interface": "interface_detail",
    "show interface status": "interface_status",
    "show interface counters table": "interface_counters_table",
    "show interface brief": "interface_brief",
    "show interface counters errors non-zero": "interface_errors",
    "show port-channel summary": "port_channel_summary",
    "show lldp neighbors detail": "lldp_neighbors_detail",
    "show system config reload-pending": "reload_pending",
    "show logging": "show_logging",
    "show ip route summary vrf all": "route_summary_ipv4",
    "show ip route vrf all": "route_ipv4_all_vrfs",
    "show ipv6 route vrf all": "route_ipv6_all_vrfs",
    "show ip ospf neighbors": "ospf_neighbors",
    "show bgp ipv4 unicast summary vrf all": "bgp_ipv4_summary",
    "show bgp ipv6 unicast summary vrf all": "bgp_ipv6_summary",
    "show vpc brief": "vpc_brief",
    "show nve interface": "nve_interface",
    "show nve peers": "nve_peers",
    "show nve vni": "nve_vni",
    "show nve vni ingress-replication": "nve_vni_ingress_replication",
    "show vlan brief": "vlan_brief",
    "show vrf": "vrf",
    "show bgp l2vpn evpn summary": "bgp_l2vpn_evpn_summary",
    "show bgp l2vpn evpn": "bgp_l2vpn_evpn",
}


def normalize_command(command: str) -> str:
    """Normalize only syntax known not to change NX-OS command output."""
    normalized = re.sub(r"\s+", " ", command.strip())
    while True:
        match = re.match(
            r"^(?:terminal\s+(?:length|width)\s+\d+)\s*;\s*(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if not match:
            break
        normalized = match.group(1).strip()
    normalized = re.sub(
        r"\s*\|\s*no-more\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized.lower()


def command_id(command: str) -> str:
    """Return a known command ID or a deterministic unsupported ID."""
    normalized = normalize_command(command)
    known = COMMAND_IDS.get(normalized)
    if known:
        return known
    from ..route_diff.commands import resolve_route_command

    route = resolve_route_command(command)
    if route is not None:
        identifier = route["command_id"]
        if identifier in {"route_ipv4_vrf", "route_ipv6_vrf"}:
            # VRF names are case-sensitive even though legacy command matching is not.
            identifier += "_" + hashlib.sha256(route["vrf"].encode()).hexdigest()[:16]
        return identifier
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return f"unsupported_{slug}" if slug else "unsupported_empty"
