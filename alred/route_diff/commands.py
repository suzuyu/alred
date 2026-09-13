"""Route acquisition commands, preserving case-sensitive VRF names."""
from __future__ import annotations

import re

from .domain import command_scope


ROUTE_COMMAND = re.compile(
    r"(?:terminal\s+(?:length|width)\s+\d+\s*;\s*)*"
    r"show\s+(ip|ipv6)\s+route(?:\s+vrf\s+([A-Za-z0-9_.-]+))?"
    r"(?:\s*\|\s*no-more)?", re.IGNORECASE,
)


def resolve_route_command(command: str) -> dict | None:
    """Recognize full route table requests; never broaden filtered commands."""
    match = ROUTE_COMMAND.fullmatch(command.strip())
    if not match:
        return None
    family = "ipv4" if match[1].lower() == "ip" else "ipv6"
    vrf = match[2]
    suffix = "default_vrf" if vrf is None else "all_vrfs" if vrf.lower() == "all" else "vrf"
    scope = command_scope(f"route_{family}_{suffix}", vrf if suffix == "vrf" else None)
    return dict(scope, command=command)
