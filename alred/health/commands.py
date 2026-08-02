"""Health command normalization and stable command identifiers."""

from __future__ import annotations

import re


COMMAND_IDS = {
    "show running-config": "running_config",
    "show version": "show_version",
    "show processes cpu": "processes_cpu",
    "show system resources": "system_resources",
    "show environment": "environment",
    "show system config reload-pending": "reload_pending",
    "show logging": "show_logging",
    "show ip route summary vrf all": "route_summary_ipv4",
    "show ip ospf neighbors": "ospf_neighbors",
    "show bgp ipv4 unicast summary vrf all": "bgp_ipv4_summary",
    "show vpc brief": "vpc_brief",
    "show nve interface": "nve_interface",
    "show nve vni": "nve_vni",
    "show nve vni ingress-replication": "nve_vni_ingress_replication",
    "show bgp l2vpn evpn summary": "bgp_l2vpn_evpn_summary",
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
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return f"unsupported_{slug}" if slug else "unsupported_empty"
