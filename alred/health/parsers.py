"""NX-OS parsers used to build the initial Canonical Health Snapshot."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .overlay import parse_overlay_running_config
from ..logging_check import parse_nxos_log_records

NXOS_PARSER_VERSION = "1.2"


class ParserError(ValueError):
    """Raised when a supported command output is empty or unrecognized."""


def _require_output(output: str) -> str:
    stripped = output.strip()
    if not stripped:
        raise ParserError("command output is empty")
    error_markers = (
        "% invalid command",
        "% incomplete command",
        "% ambiguous command",
        "error:",
    )
    lowered = stripped.lower()
    if any(marker in lowered for marker in error_markers):
        raise ParserError("NX-OS command returned an error")
    return stripped


def _parse_running_config(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    return {}, {"nxos-overlay": {"config": parse_overlay_running_config(text)}}


def _parse_show_version(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    version = re.search(r"^\s*NXOS:\s+version\s+(\S+)", text, re.MULTILINE)
    model = re.search(
        r"^\s*cisco\s+(.+?)\s+Chassis\s*$", text, re.MULTILINE | re.IGNORECASE
    )
    hostname = re.search(r"^\s*Device name:\s*(\S+)", text, re.MULTILINE)
    uptime = re.search(
        r"Kernel uptime is\s+"
        r"(?:(\d+)\s+day\(s\),\s+)?"
        r"(?:(\d+)\s+hour\(s\),\s+)?"
        r"(?:(\d+)\s+minute\(s\),\s+)?"
        r"(\d+)\s+second\(s\)",
        text,
    )
    if not version or not model:
        raise ParserError("NX-OS version or model was not recognized")
    system: dict[str, Any] = {
        "platform": "nxos",
        "version": version.group(1),
        "model": model.group(1).strip(),
    }
    if hostname:
        system["reported_hostname"] = hostname.group(1)
    if uptime:
        days, hours, minutes, seconds = (int(value or 0) for value in uptime.groups())
        system["uptime_seconds"] = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return {"system": system}, {}


def _parse_processes_cpu(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    match = re.search(
        r"CPU utilization for five seconds:\s*"
        r"(\d+(?:\.\d+)?)%/(\d+(?:\.\d+)?)%;\s*"
        r"one minute:\s*(\d+(?:\.\d+)?)%;\s*"
        r"five minutes:\s*(\d+(?:\.\d+)?)%",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ParserError("CPU utilization summary was not recognized")
    five_seconds, interrupt, one_minute, five_minutes = (
        float(value) for value in match.groups()
    )
    return {
        "cpu": {
            "five_seconds_percent": five_seconds,
            "interrupt_percent": interrupt,
            "one_minute_percent": one_minute,
            "five_minutes_percent": five_minutes,
        }
    }, {}


def _parse_system_resources(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    load = re.search(
        r"Load average:\s+1 minute:\s*([\d.]+)\s+"
        r"5 minutes:\s*([\d.]+)\s+15 minutes:\s*([\d.]+)",
        text,
    )
    memory = re.search(
        r"Memory usage:\s*(\d+)K total,\s*(\d+)K used,\s*(\d+)K free",
        text,
    )
    if not load or not memory:
        raise ParserError("system resource summary was not recognized")
    total, used, free = (int(value) for value in memory.groups())
    common = {
        "resources": {
            "load_average": {
                "one_minute": float(load.group(1)),
                "five_minutes": float(load.group(2)),
                "fifteen_minutes": float(load.group(3)),
            },
            "memory": {
                "total_kib": total,
                "used_kib": used,
                "free_kib": free,
                "used_percent": round((used / total) * 100, 2) if total else None,
            },
        }
    }
    status = re.search(
        r"Current memory status:\s*(\S+)",
        text,
        re.IGNORECASE,
    )
    if status:
        common["resources"]["memory"]["status"] = status.group(1).upper()
    return common, {}


def _parse_environment(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    alarm_lines = [
        line.strip()
        for line in text.splitlines()
        if re.search(
            r"\b(?:fail(?:ed)?|alarm|critical|shutdown)\b",
            line,
            re.IGNORECASE,
        )
    ]
    virtual_unavailable = "no power info" in text.lower() and not re.search(
        r"\b(?:ok|normal)\s*$", text, re.MULTILINE | re.IGNORECASE
    )
    return {
        "environment": {
            "applicable": not virtual_unavailable,
            "healthy": not alarm_lines,
            "alarms": alarm_lines,
        }
    }, {}


def _parse_reload_pending(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    heading = "Following config commands require copy r s + reload"
    if heading.lower() not in text.lower():
        raise ParserError("reload-pending heading was not recognized")
    commands = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and heading.lower() not in line.lower()
        and not set(line.strip()) <= {"="}
    ]
    return {
        "reload_pending": {
            "required": bool(commands),
            "commands": commands,
        }
    }, {}


def _parse_route_summary_ipv4(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    headings = list(
        re.finditer(
            r'^IP Route Table for VRF "([^"]+)"\s*$',
            text,
            re.MULTILINE,
        )
    )
    if not headings:
        raise ParserError("IPv4 route summary VRF headings were not recognized")
    vrfs: dict[str, Any] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end() : end]
        routes = re.search(r"Total number of routes:\s*(\d+)", block)
        paths = re.search(r"Total number of paths:\s*(\d+)", block)
        if not routes or not paths:
            raise ParserError(f"route/path count missing for VRF {heading.group(1)}")
        vrfs[heading.group(1)] = {
            "routes": int(routes.group(1)),
            "paths": int(paths.group(1)),
        }
    return {"routes": {"ipv4_summary": {"vrfs": vrfs}}}, {}


def _parse_ospf_neighbors(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    headings = list(
        re.finditer(
            r"^\s*OSPF Process ID\s+(\S+)\s+VRF\s+(\S+)\s*$",
            text,
            re.MULTILINE,
        )
    )
    if not headings:
        if "ospf" in text.lower() and "not enabled" in text.lower():
            return {
                "routing_neighbors": {"ospf": {"applicable": False, "processes": {}}}
            }, {}
        raise ParserError("OSPF process heading was not recognized")
    processes: dict[str, Any] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end() : end]
        total_match = re.search(
            r"Total number of neighbors:\s*(\d+)",
            block,
        )
        neighbors: dict[str, Any] = {}
        for line in block.splitlines():
            fields = line.split()
            if len(fields) < 7:
                continue
            if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", fields[0]):
                continue
            state = fields[2].split("/", 1)[0].upper()
            neighbors[fields[0]] = {
                "state": state,
                "uptime": fields[-3],
                "address": fields[-2],
                "interface": fields[-1],
            }
        key = f"{heading.group(1)}@{heading.group(2)}"
        processes[key] = {
            "process_id": heading.group(1),
            "vrf": heading.group(2),
            "reported_total": (
                int(total_match.group(1)) if total_match else len(neighbors)
            ),
            "neighbors": neighbors,
        }
    return {
        "routing_neighbors": {"ospf": {"applicable": True, "processes": processes}}
    }, {}


def _parse_bgp_table(block: str) -> dict[str, Any]:
    neighbors: dict[str, Any] = {}
    in_table = False
    for line in block.splitlines():
        if re.match(r"^Neighbor\s+V\s+AS\b", line):
            in_table = True
            continue
        if not in_table or not line.strip():
            continue
        fields = line.split()
        if len(fields) < 10:
            continue
        address = fields[0]
        if not re.fullmatch(r"[0-9A-Fa-f:.]+", address):
            continue
        state_value = fields[-1]
        established = state_value.isdigit()
        neighbors[address] = {
            "state": "Established" if established else state_value,
            "prefixes_received": int(state_value) if established else None,
            "remote_as": int(fields[2]) if fields[2].isdigit() else fields[2],
            "uptime": fields[-2],
        }
    return neighbors


def _parse_bgp_ipv4_summary(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    headings = list(
        re.finditer(
            r"^BGP summary information for VRF (.+?), "
            r"address family IPv4 Unicast\s*$",
            text,
            re.MULTILINE,
        )
    )
    if not headings:
        if "bgp" in text.lower() and "not configured" in text.lower():
            return {
                "routing_neighbors": {"bgp_ipv4": {"applicable": False, "vrfs": {}}}
            }, {}
        raise ParserError("IPv4 BGP VRF headings were not recognized")
    vrfs: dict[str, Any] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end() : end]
        peer_summary = re.search(
            r"IPv4 Unicast config peers\s+(\d+),\s+capable peers\s+(\d+)",
            block,
            re.IGNORECASE,
        )
        configured, capable = (
            (int(value) for value in peer_summary.groups()) if peer_summary else (0, 0)
        )
        vrfs[heading.group(1)] = {
            "configured_peers": configured,
            "capable_peers": capable,
            "neighbors": _parse_bgp_table(block),
        }
    return {"routing_neighbors": {"bgp_ipv4": {"applicable": True, "vrfs": vrfs}}}, {}


def _field(text: str, label: str) -> str | None:
    match = re.search(
        rf"^{re.escape(label)}\s*:\s*(.+?)\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _parse_vpc_brief(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if "vpc feature is not enabled" in text.lower():
        return {"vpc": {"applicable": False}}, {}
    peer = _field(text, "Peer status")
    keepalive = _field(text, "vPC keep-alive status")
    consistency = _field(text, "Configuration consistency status")
    domain = _field(text, "vPC domain id")
    if not peer or not consistency:
        raise ParserError("vPC summary fields were not recognized")
    return {
        "vpc": {
            "applicable": True,
            "domain_id": int(domain) if domain and domain.isdigit() else domain,
            "peer_status": peer,
            "keepalive_status": keepalive,
            "consistency_status": consistency,
            "healthy": (
                "formed ok" in peer.lower()
                and consistency.lower() == "success"
                and (keepalive is None or "alive" in keepalive.lower())
            ),
        }
    }, {}


def _parse_nve_interface(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if "nve interface is not configured" in text.lower():
        return {}, {"nxos-overlay": {"nve_interface": {"applicable": False}}}
    match = re.search(
        r"Interface:\s*(\S+),\s*State:\s*(\S+),\s*encapsulation:\s*(\S+)",
        text,
        re.IGNORECASE,
    )
    source = re.search(
        r"Source-Interface:\s*(\S+)\s+\(primary:\s*([^,\s)]+)"
        r"(?:,\s*secondary:\s*([^\s)]+))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ParserError("NVE interface summary was not recognized")
    nve: dict[str, Any] = {
        "applicable": True,
        "name": match.group(1),
        "state": match.group(2),
        "encapsulation": match.group(3),
    }
    if source:
        nve["source_interface"] = source.group(1)
        nve["primary_address"] = source.group(2)
        if source.group(3):
            nve["secondary_address"] = source.group(3)
    return {}, {"nxos-overlay": {"nve_interface": nve}}


def _parse_nve_vni(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if "nve interface is not configured" in text.lower():
        return {}, {"nxos-overlay": {"nve_vnis": {"applicable": False, "vnis": {}}}}
    entries: dict[str, Any] = {}
    row = re.compile(
        r"^[ \t]*(nve\d+)[ \t]+(\d+)[ \t]+(\S+)[ \t]+(\S+)[ \t]+"
        r"(\S+)[ \t]+(L[23])[ \t]+\[([^\]]+)\]"
        r"(?:[ \t]+(.*?))?[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in row.finditer(text):
        interface, vni, replication, state, mode, vni_type, context, flags = (
            match.groups()
        )
        entries[vni] = {
            "interface": interface,
            "replication": replication,
            "state": state,
            "mode": mode,
            "type": vni_type.upper(),
            "context": context,
            "flags": flags.split() if flags else [],
        }
    if not entries:
        raise ParserError("NVE VNI table rows were not recognized")
    return {}, {"nxos-overlay": {"nve_vnis": {"applicable": True, "vnis": entries}}}


def _parse_nve_vni_ingress_replication(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    vnis: dict[str, list[dict[str, Any]]] = {}
    row = re.compile(
        r"^[ \t]*(nve\d+)[ \t]+(\d+)[ \t]+(\S+)[ \t]+"
        r"(\S+)[ \t]+(\S+)[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in row.finditer(text):
        interface, vni, remote, source, uptime = match.groups()
        vnis.setdefault(vni, []).append(
            {
                "interface": interface,
                "remote_vtep": remote,
                "source": source,
                "uptime": uptime,
            }
        )
    if not vnis:
        raise ParserError("NVE ingress replication table rows were not recognized")
    return {}, {"nxos-overlay": {"ingress_replication": {"vnis": vnis}}}


def _parse_bgp_evpn_summary(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    summary = re.search(
        r"L2VPN EVPN config peers\s+(\d+),\s+capable peers\s+(\d+)",
        text,
        re.IGNORECASE,
    )
    if not summary:
        if "not configured" in text.lower():
            return {}, {"nxos-overlay": {"evpn_bgp": {"applicable": False}}}
        raise ParserError("EVPN BGP summary was not recognized")
    neighbors = _parse_bgp_table(text)
    configured, capable = (int(value) for value in summary.groups())
    return {
        "routing_neighbors": {
            "bgp_evpn": {
                "configured_peers": configured,
                "capable_peers": capable,
                "neighbors": neighbors,
            }
        }
    }, {
        "nxos-overlay": {
            "evpn_bgp": {
                "applicable": True,
                "configured_peers": configured,
                "capable_peers": capable,
                "neighbors": neighbors,
            }
        }
    }


def _parse_show_logging(
    output: str,
    *,
    timezone: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = output.strip()
    if not text:
        raise ParserError("command output is empty")
    lowered = text.lower()
    command_errors = (
        "% invalid command",
        "% incomplete command",
        "% ambiguous command",
    )
    if any(marker in lowered for marker in command_errors) or (
        lowered.startswith("error:")
    ):
        raise ParserError("NX-OS command returned an error")
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ParserError(f"unknown logging timezone: {timezone}") from exc
    records, warnings = parse_nxos_log_records(
        "snapshot",
        text,
        "show logging",
        tzinfo,
    )
    warning_messages = [warning.message for warning in warnings]
    if not records and re.search(
        r"%[A-Z0-9_-]+-[0-7]-[A-Z0-9_-]+:",
        text,
        re.IGNORECASE,
    ):
        warning_messages.append(
            "syslog records were present but timestamps were not recognized"
        )
    normalized = [
        {
            "timestamp_text": record.timestamp_text,
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
            "severity": record.severity,
            "fingerprint": hashlib.sha256(
                record.normalized_text.encode("utf-8")
            ).hexdigest(),
            "text": record.normalized_text,
            "parse_warnings": record.parse_warning_messages,
        }
        for record in records
    ]
    return {
        "logging": {
            "records": normalized,
            "parse_warnings": warning_messages,
        }
    }, {}


PARSERS = {
    "running_config": _parse_running_config,
    "show_version": _parse_show_version,
    "processes_cpu": _parse_processes_cpu,
    "system_resources": _parse_system_resources,
    "environment": _parse_environment,
    "reload_pending": _parse_reload_pending,
    "route_summary_ipv4": _parse_route_summary_ipv4,
    "ospf_neighbors": _parse_ospf_neighbors,
    "bgp_ipv4_summary": _parse_bgp_ipv4_summary,
    "vpc_brief": _parse_vpc_brief,
    "nve_interface": _parse_nve_interface,
    "nve_vni": _parse_nve_vni,
    "nve_vni_ingress_replication": _parse_nve_vni_ingress_replication,
    "bgp_l2vpn_evpn_summary": _parse_bgp_evpn_summary,
}


def parse_nxos_command(
    identifier: str,
    output: str,
    *,
    timezone: str = "Asia/Tokyo",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse one supported NX-OS command into common/profile state."""
    parser = PARSERS.get(identifier)
    if identifier == "show_logging":
        return _parse_show_logging(output, timezone=timezone)
    if parser is None:
        raise KeyError(identifier)
    return parser(output)
