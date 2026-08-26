"""NX-OS parsers used to build the initial Canonical Health Snapshot."""

from __future__ import annotations

import hashlib
import ipaddress
from importlib import metadata as importlib_metadata
from pathlib import Path
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .overlay import parse_overlay_running_config
from ..logging_check import parse_nxos_log_records
from ..parsing import parse_lldp_file

try:
    import ntc_templates
    from ntc_templates.parse import ParsingException, parse_output

    NTC_TEMPLATES_IMPORT_ERROR: BaseException | None = None
except ImportError as exc:
    ntc_templates = None
    parse_output = None
    ParsingException = Exception
    NTC_TEMPLATES_IMPORT_ERROR = exc

NXOS_PARSER_VERSION = "1.19"
NTC_TEMPLATES_VERSION = (
    importlib_metadata.version("ntc-templates")
    if NTC_TEMPLATES_IMPORT_ERROR is None
    else "unavailable"
)
TEXTFSM_VERSION = (
    importlib_metadata.version("textfsm")
    if NTC_TEMPLATES_IMPORT_ERROR is None
    else "unavailable"
)
NTC_TEMPLATE_FILES = {
    "inventory": "cisco_nxos_show_inventory.textfsm",
    "license_usage": "cisco_nxos_show_license_usage.textfsm",
}
NTC_PARSER_IDENTIFIERS = frozenset(NTC_TEMPLATE_FILES)

_INTERFACE_STATUS_NAME_RE = re.compile(
    r"^(?:Eth|Ethernet|Po|port-channel|mgmt|Vlan|Lo|loopback)\S+",
    re.IGNORECASE,
)
_INTERFACE_STATUS_ALIASES = {
    "connected": "connected",
    "notconnect": "notconnect",
    "notconnec": "notconnect",
    "disabled": "disabled",
    "err-disabled": "err-disabled",
    "inactive": "inactive",
    "sfpabsent": "sfpAbsent",
    "xcvrabsen": "sfpAbsent",
    "xcvrabsent": "sfpAbsent",
    "down": "down",
}


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


def _parse_lldp_neighbors_detail(
    output: str,
    *,
    device_type: str = "nxos",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate LLDP detail while canonical link parsing remains shared."""
    stripped = _require_output(output)
    records = parse_lldp_file(
        stripped,
        "__health_local__",
        device_type,
        {},
    )
    nxos_empty_observation = re.search(
        r"(?:total\s+entries\s+displayed\s*:\s*0|no\s+lldp\s+neighbors?)",
        stripped,
        flags=re.IGNORECASE,
    )
    eos_counts = [
        int(value)
        for value in re.findall(
            r"^Interface\s+\S+\s+detected\s+(\d+)\s+LLDP\s+neighbors?:",
            stripped,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    ]
    empty_observation = bool(nxos_empty_observation) or (
        bool(eos_counts) and not any(eos_counts)
    )
    if not records and not empty_observation:
        raise ParserError("LLDP detail output has no complete neighbor stanza")
    return {
        "lldp": {
            "neighbor_count": len(records),
            "empty_observation": not records,
        }
    }, {}


def _ntc_template_path(identifier: str) -> Path:
    if ntc_templates is None:
        raise ParserError(
            "NTC Templates is unavailable: "
            + str(NTC_TEMPLATES_IMPORT_ERROR or "import failed")
        )
    path = (
        Path(ntc_templates.__file__).resolve().parent
        / "templates"
        / NTC_TEMPLATE_FILES[identifier]
    )
    if not path.is_file() or path.is_symlink():
        raise ParserError(f"NTC template is missing or unsafe: {path.name}")
    return path


def parser_provenance(
    identifier: str,
    *,
    device_type: str = "nxos",
) -> dict[str, Any]:
    """Return deterministic parser provenance for a supported command ID."""
    if identifier == "license_usage":
        provenance = {
            "parser": "nxos.license_usage",
            "parser_version": NXOS_PARSER_VERSION,
            "parser_template": NTC_TEMPLATE_FILES[identifier],
        }
        try:
            path = _ntc_template_path(identifier)
        except ParserError:
            return provenance
        provenance["parser_template_sha256"] = "sha256:" + hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        return provenance
    if identifier in NTC_PARSER_IDENTIFIERS:
        provenance = {
            "parser": f"ntc_templates.{identifier}",
            "parser_version": NTC_TEMPLATES_VERSION,
            "parser_template": NTC_TEMPLATE_FILES[identifier],
        }
        try:
            path = _ntc_template_path(identifier)
        except ParserError:
            return provenance
        provenance["parser_template_sha256"] = "sha256:" + hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        return provenance
    if identifier in PARSERS or identifier in {"clock", "show_logging"}:
        return {
            "parser": (
                f"{device_type}.lldp_neighbors_detail"
                if identifier == "lldp_neighbors_detail"
                else f"nxos.{identifier}"
            ),
            "parser_version": NXOS_PARSER_VERSION,
        }
    return {"parser": None, "parser_version": None}


def _parse_ntc_rows(
    identifier: str,
    command: str,
    text: str,
) -> list[dict[str, str]]:
    if parse_output is None:
        raise ParserError(
            "NTC Templates is unavailable: "
            + str(NTC_TEMPLATES_IMPORT_ERROR or "import failed")
        )
    template_path = _ntc_template_path(identifier)
    try:
        rows = parse_output(
            platform="cisco_nxos",
            command=command,
            data=text,
            template_dir=str(template_path.parent),
        )
    except ParsingException as exc:
        raise ParserError(
            f"NTC Templates could not parse {command}: {exc}"
        ) from exc
    except Exception as exc:
        raise ParserError(
            f"NTC Templates failed while parsing {command}: {exc}"
        ) from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ParserError(f"NTC Templates returned invalid rows for {command}")
    return [{str(key): str(value) for key, value in row.items()} for row in rows]


def _parse_inventory(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if not re.search(r"^NAME:\s*", text, re.MULTILINE | re.IGNORECASE) or not re.search(
        r"^(?:PID|SN):\s*", text, re.MULTILINE | re.IGNORECASE
    ):
        raise ParserError("inventory NAME/PID anchors were not recognized")
    rows = _parse_ntc_rows("inventory", "show inventory", text)
    if not rows:
        raise ParserError("inventory rows were not recognized")
    components = []
    for row in rows:
        components.append(
            {
                "name": row.get("name", "").strip() or None,
                "description": row.get("descr", "").strip() or None,
                "product_id": row.get("pid", "").strip() or None,
                "version_id": row.get("vid", "").strip() or None,
                "serial_number": row.get("sn", "").strip() or None,
            }
        )
    return {"inventory": {"components": components}}, {}


_LICENSE_BLOCK_HEADING_RE = re.compile(
    r"^\((?P<feature>[^()\r\n]+)\):\s*$",
    re.MULTILINE,
)
_LICENSE_BLOCK_FIELD_RE = re.compile(
    r"^\s{2}(?P<name>"
    r"Description|Count|Version|Status|Enforcement Type|License Type"
    r"):\s*(?P<value>.*?)\s*$"
)


def _parse_license_usage_blocks(text: str) -> dict[str, Any] | None:
    matches = list(_LICENSE_BLOCK_HEADING_RE.finditer(text))
    if not matches:
        return None

    preamble = text[: matches[0].start()].strip()
    if not re.fullmatch(
        r"License Authorization:\s*\n\s{2}Status:\s*\S(?:.*\S)?",
        preamble,
        re.IGNORECASE,
    ):
        raise ParserError("license usage block preamble was not recognized")

    usage = []
    features: set[str] = set()
    for index, match in enumerate(matches):
        feature = match.group("feature").strip()
        if not feature:
            raise ParserError("license usage block has no feature name")
        feature_key = feature.casefold()
        if feature_key in features:
            raise ParserError(f"duplicate license usage feature: {feature}")
        features.add(feature_key)

        block_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        fields: dict[str, str] = {}
        for raw_line in text[match.end() : block_end].splitlines():
            if not raw_line.strip():
                continue
            field_match = _LICENSE_BLOCK_FIELD_RE.fullmatch(raw_line)
            if field_match is None:
                raise ParserError(
                    f"unrecognized license usage block line for {feature}"
                )
            name = field_match.group("name").casefold().replace(" ", "_")
            if name in fields:
                raise ParserError(
                    f"duplicate license usage block field for {feature}: {name}"
                )
            fields[name] = field_match.group("value").strip()

        count_text = fields.get("count", "")
        if not count_text.isdigit():
            raise ParserError(
                f"unsupported license count: {count_text or '<empty>'}"
            )
        status_text = " ".join(fields.get("status", "").split()).lower()
        if status_text not in {"in use", "unused"}:
            raise ParserError(
                f"unsupported license usage status: {status_text or '<empty>'}"
            )
        usage.append(
            {
                "feature": feature,
                "installed": True,
                "license_count": int(count_text),
                "usage_status": status_text.replace(" ", "_"),
                "expiry_date": None,
                "comments": None,
            }
        )
    return {"license": {"applicable": True, "usage": usage}}


def _parse_license_usage(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    explicitly_not_applicable = bool(
        re.search(
            r"\bno\s+(?:feature\s+)?licenses?\s+(?:are\s+)?"
            r"(?:installed|in\s+use|required)\b",
            text,
            re.IGNORECASE,
        )
    )
    heading = re.search(
        r"^Feature\s+Ins\s+Lic\s+Status\s+Expiry\s+Date\s+Comments\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if not heading:
        block_data = _parse_license_usage_blocks(text)
        if block_data is not None:
            return block_data, {}
        if explicitly_not_applicable:
            return {"license": {"applicable": False, "usage": []}}, {}
        raise ParserError("license usage heading was not recognized")
    rows = _parse_ntc_rows("license_usage", "show license usage", text)
    if not rows:
        if explicitly_not_applicable:
            return {"license": {"applicable": False, "usage": []}}, {}
        raise ParserError("license usage rows were not recognized")
    usage = []
    features: set[str] = set()
    for row in rows:
        feature = row.get("feature", "").strip()
        if not feature:
            raise ParserError("license usage row has no feature name")
        feature_key = feature.casefold()
        if feature_key in features:
            raise ParserError(f"duplicate license usage feature: {feature}")
        features.add(feature_key)
        installed_text = row.get("installed", "").strip().lower()
        if installed_text not in {"yes", "no"}:
            raise ParserError(
                f"unsupported license installed state: {installed_text or '<empty>'}"
            )
        count_text = row.get("license_count", "").strip()
        if count_text in {"", "-"}:
            license_count = None
        elif count_text.isdigit():
            license_count = int(count_text)
        else:
            raise ParserError(f"unsupported license count: {count_text}")
        status_text = " ".join(row.get("status", "").split()).lower()
        if status_text not in {"in use", "unused"}:
            raise ParserError(
                f"unsupported license usage status: {status_text or '<empty>'}"
            )
        expiry = row.get("expiry_date", "").strip()
        comments = row.get("comments", "").strip()
        usage.append(
            {
                "feature": feature,
                "installed": installed_text == "yes",
                "license_count": license_count,
                "usage_status": status_text.replace(" ", "_"),
                "expiry_date": None if expiry in {"", "-"} else expiry,
                "comments": None if comments in {"", "-"} else comments,
            }
        )
    return {"license": {"applicable": True, "usage": usage}}, {}


def _parse_running_config(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    config = parse_overlay_running_config(text)
    return {
        "routing_neighbor_config": config.get("bgp_neighbor_config", {})
    }, {"nxos-overlay": {"config": config}}


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


def _parse_running_config_diff(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify the device-native running/startup configuration diff."""
    stripped = output.strip()
    if not stripped:
        return {
            "running_config_diff": {
                "different": False,
                "line_count": 0,
                "output_sha256": hashlib.sha256(b"").hexdigest(),
            }
        }, {}
    text = _require_output(output)
    no_difference_markers = {
        "no changes",
        "no differences",
        "running configuration is same as startup configuration",
        "running-config is same as startup-config",
    }
    normalized = " ".join(text.lower().split())
    different = normalized not in no_difference_markers
    return {
        "running_config_diff": {
            "different": different,
            "line_count": (
                sum(1 for line in text.splitlines() if line.strip())
                if different
                else 0
            ),
            "output_sha256": hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
        }
    }, {}


def _parse_clock(output: str, *, timezone: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    match = re.search(
        r"(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s+\S+\s+"
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
        r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4})",
        text,
    )
    if not match:
        raise ParserError("device clock was not recognized")
    try:
        zone = ZoneInfo(timezone)
        parsed = datetime.strptime(
            f"{match.group(4)} {match.group(2)} {match.group(3)} {match.group(1)}",
            "%Y %b %d %H:%M:%S.%f" if "." in match.group(1) else "%Y %b %d %H:%M:%S",
        ).replace(tzinfo=zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ParserError("device clock or timezone was not recognized") from exc
    clock = {"timestamp": parsed.isoformat(), "timezone": timezone}
    time_source = re.search(
        r"^Time source is\s+(.+)$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if time_source:
        clock["time_source"] = time_source.group(1).strip()
    return {"clock": clock}, {}


def _parse_ntp_status(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    lowered = text.lower()
    if "ntp is not configured" in lowered or "no ntp" in lowered:
        return {"ntp": {"configured": False, "synchronized": False}}, {}
    if (
        "distribution : disabled" in lowered
        or "last operational state: no session" in lowered
    ):
        operational_state = re.search(
            r"Last operational state:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE
        )
        return {
            "ntp": {
                "synchronized": False,
                "operational_state": (
                    operational_state.group(1).strip()
                    if operational_state
                    else None
                ),
            }
        }, {}
    synchronized = "clock is synchronized" in lowered
    unsynchronized = "clock is unsynchronized" in lowered
    if not synchronized and not unsynchronized:
        raise ParserError("NTP synchronization status was not recognized")
    stratum = re.search(r"stratum\s+(\d+)", text, re.IGNORECASE)
    reference = re.search(r"reference is\s+(\S+)", text, re.IGNORECASE)
    return {
        "ntp": {
            "configured": True,
            "synchronized": synchronized,
            "stratum": int(stratum.group(1)) if stratum else None,
            "reference": reference.group(1).rstrip(",") if reference else None,
        }
    }, {}


def _parse_ntp_peers(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = output.strip()
    if not text:
        return {"ntp": {"peers": {}}}, {}
    text = _require_output(text)
    if "no ntp" in text.lower() or "not configured" in text.lower():
        return {"ntp": {"peers": {}}}, {}
    peers: dict[str, Any] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([*+x#~-]?)\s*([0-9A-Fa-f:.]+)\s+", line)
        if not match:
            continue
        marker, address = match.groups()
        peers[address] = {"selected": marker == "*", "marker": marker or None}
    if not peers:
        raise ParserError("NTP peer rows were not recognized")
    return {"ntp": {"peers": peers}}, {}


def _parse_ntp_peer_status(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    total_match = re.search(r"Total peers\s*:\s*(\d+)", text, re.IGNORECASE)
    total = int(total_match.group(1)) if total_match else None
    peers: dict[str, Any] = {}
    markers = {"*", "+", "-", "="}
    modes = {
        "*": "selected",
        "+": "active",
        "-": "passive",
        "=": "client",
    }
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        marker = ""
        remote = fields[0]
        if remote in markers:
            if len(fields) < 7:
                continue
            marker = remote
            remote = fields[1]
            fields = fields[1:]
        elif remote[0] in markers:
            marker = remote[0]
            remote = remote[1:]
        if not remote or not re.fullmatch(r"[0-9A-Fa-f:.]+", remote):
            continue
        try:
            local = fields[1]
            stratum = int(fields[2])
            poll = int(fields[3])
            reach = int(fields[4])
            delay = float(fields[5])
        except (IndexError, ValueError):
            continue
        peers[remote] = {
            "selected": marker == "*",
            "mode": modes.get(marker, "unspecified"),
            "marker": marker or None,
            "local": local,
            "stratum": stratum,
            "poll": poll,
            "reach": reach,
            "delay": delay,
            "vrf": fields[6] if len(fields) > 6 else None,
        }
    if total == 0:
        return {
            "ntp": {
                "peer_status": {
                    "applicable": False,
                    "total_peers": 0,
                    "peers": {},
                }
            }
        }, {}
    if not peers:
        raise ParserError("NTP peer-status rows were not recognized")
    return {
        "ntp": {
            "peer_status": {
                "applicable": True,
                "total_peers": total if total is not None else len(peers),
                "peers": peers,
            }
        }
    }, {}


def _parse_interface_status(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    interfaces: dict[str, Any] = {}
    unsupported: list[tuple[str, str]] = []
    table_header_seen = False
    for line in text.splitlines():
        header = re.match(
            r"^\s*Port\s+Name\s+Status\s+Vlan\b",
            line,
            re.IGNORECASE,
        )
        if header:
            table_header_seen = True
            continue
        fields = line.split()
        if len(fields) < 2 or not _INTERFACE_STATUS_NAME_RE.match(fields[0]):
            continue

        raw_status = ""
        if table_header_seen and len(fields) >= 6:
            # Name may contain spaces, while Vlan, Duplex, Speed, and Type are
            # the four stable columns following Status.
            raw_status = fields[-5]
        if not raw_status:
            raw_status = next(
                (
                    value
                    for value in fields[1:]
                    if value.casefold() in _INTERFACE_STATUS_ALIASES
                ),
                "",
            )
        status = _INTERFACE_STATUS_ALIASES.get(raw_status.casefold())
        if status is None:
            unsupported.append((fields[0], raw_status or "<missing>"))
            continue

        if status == "down" and fields[0].casefold().startswith("vlan"):
            # The Status column alone cannot distinguish an administratively
            # down SVI. ``show interface brief`` owns that classification.
            continue
        admin_up = status != "disabled"
        operational_up = status == "connected"
        interfaces[fields[0]] = {
            "admin_state": "up" if admin_up else "down",
            "operational_state": "up" if operational_up else "down",
            "status": status,
        }
    if unsupported:
        details = ", ".join(
            f"{interface}={status}" for interface, status in unsupported
        )
        raise ParserError(f"unsupported interface status row(s): {details}")
    if not interfaces:
        raise ParserError("interface status rows were not recognized")
    return {"interfaces": interfaces}, {}


def _parse_interface_counters_table(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    column_starts: list[int] | None = None
    interfaces: dict[str, Any] = {}
    for line in text.splitlines():
        header_matches = [
            re.search(r"\bPort\b", line, re.IGNORECASE),
            re.search(r"\bDescription\b", line, re.IGNORECASE),
            re.search(r"\b(?:Interval|Intvl)\b", line, re.IGNORECASE),
            re.search(r"(?:InRate\s*\(Mbps\)|\bRx\s+Mbps\b)", line, re.IGNORECASE),
            re.search(r"(?:InRate\s*\(%\)|\bRx\s+%+)", line, re.IGNORECASE),
            re.search(r"(?:OutRate\s*\(Mbps\)|\bTx\s+Mbps\b)", line, re.IGNORECASE),
            re.search(r"(?:OutRate\s*\(%\)|\bTx\s+%+)", line, re.IGNORECASE),
        ]
        if all(match is not None for match in header_matches):
            starts = [match.start() for match in header_matches if match is not None]
            if starts == sorted(starts):
                column_starts = starts
            continue
        if column_starts is None:
            continue
        fields = [
            line[start:end].strip()
            for start, end in zip(column_starts, column_starts[1:])
        ]
        fields.append(line[column_starts[-1] :].strip())
        interface = fields[0]
        if not _INTERFACE_STATUS_NAME_RE.match(interface):
            continue
        interval_parts = fields[2].split("/")
        if len(interval_parts) == 1:
            interval_parts *= 2
        if len(interval_parts) != 2:
            raise ParserError(f"invalid interface counter interval: {interface}")
        try:
            input_interval_seconds, output_interval_seconds = (
                int(float(value)) for value in interval_parts
            )
            input_mbps, input_percent, output_mbps, output_percent = (
                float(value.rstrip("%")) for value in fields[3:]
            )
        except ValueError as exc:
            raise ParserError(
                f"interface counter rate row contains a non-numeric value: {interface}"
            ) from exc
        entry = {
            "description": fields[1] if fields[1] not in {"--", "N/A"} else None,
            "input_mbps": input_mbps,
            "input_percent": input_percent,
            "output_mbps": output_mbps,
            "output_percent": output_percent,
            "input_load_interval_seconds": input_interval_seconds,
            "output_load_interval_seconds": output_interval_seconds,
        }
        if input_interval_seconds == output_interval_seconds:
            entry["load_interval_seconds"] = input_interval_seconds
        interfaces[interface] = entry
    if column_starts is None:
        raise ParserError("interface counter rate table header was not recognized")
    if not interfaces:
        raise ParserError("interface counter rate rows were not recognized")
    return {"interface_utilization": {"interfaces": interfaces}}, {}


def _parse_interface_brief(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse the SVI Status and Reason columns in ``show interface brief``."""
    text = _require_output(output)
    svis: dict[str, Any] = {}
    common_svis: dict[str, Any] = {}
    for line in text.splitlines():
        match = re.match(
            r"^\s*(Vlan\d+)\s+\S+\s+(up|down)\s*(.*?)\s*$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        name = "Vlan" + re.search(r"\d+", match.group(1)).group()
        status = match.group(2).lower()
        reason = match.group(3).strip()
        svis[name] = {
            "admin_state": (
                "down"
                if "administratively down" in reason.lower()
                else "up"
            ),
            "operational_state": status,
            "status": status,
            "reason": reason or None,
        }
        common_svis[name] = {
            "admin_state": svis[name]["admin_state"],
            "operational_state": status,
            "status": (
                "connected"
                if status == "up"
                else "disabled"
                if svis[name]["admin_state"] == "down"
                else "down"
            ),
            "reason": reason or None,
        }
    if not svis:
        raise ParserError("SVI rows in interface brief were not recognized")
    return {"interfaces": common_svis}, {
        "nxos-overlay": {"svis": {"interfaces": svis}}
    }


def _parse_vlan_brief(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    vlans: dict[str, Any] = {}
    row = re.compile(
        r"^\s*(\d+)\s+(.+?)\s+(active|act/lshut|sus/lshut|suspended)"
        r"(?:[ \t]+.*)?$",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in row.finditer(text):
        vlan, name, status = match.groups()
        vlans[vlan] = {"name": name.strip(), "status": status.lower()}
    if not vlans:
        raise ParserError("VLAN brief rows were not recognized")
    return {}, {"nxos-overlay": {"vlans": {"vlans": vlans}}}


def _parse_vrf(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    vrfs: dict[str, Any] = {}
    row = re.compile(
        r"^[ \t]*(\S+)[ \t]+(\d+)[ \t]+(Up|Down)(?:[ \t]+(.*?))?[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in row.finditer(text):
        name, vrf_id, state, reason = match.groups()
        vrfs[name] = {
            "vrf_id": int(vrf_id),
            "state": state,
            "reason": reason or None,
        }
    if not vrfs:
        raise ParserError("VRF rows were not recognized")
    return {}, {"nxos-overlay": {"vrfs": {"vrfs": vrfs}}}


def _parse_interface_errors(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    lines = [line.split() for line in text.splitlines() if line.strip()]
    header = next((fields for fields in lines if fields and fields[0].lower() == "port"), None)
    if not header:
        raise ParserError("interface error counter header was not recognized")
    counters: dict[str, Any] = {}
    for fields in lines[lines.index(header) + 1 :]:
        if len(fields) != len(header) or not re.match(r"^(?:Eth|Ethernet|Po|port-channel|mgmt)\S+", fields[0], re.IGNORECASE):
            continue
        try:
            counters[fields[0]] = {
                name: int(value.replace(",", ""))
                for name, value in zip(header[1:], fields[1:])
            }
        except ValueError:
            continue
    return {"interface_errors": counters}, {}


def _parse_port_channel_summary(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = output.strip()
    if not text:
        return {"port_channels": {"applicable": False, "channels": {}}}, {}
    text = _require_output(text)
    if "no port-channel" in text.lower() or "not configured" in text.lower():
        return {"port_channels": {"applicable": False, "channels": {}}}, {}
    channels: dict[str, Any] = {}
    row = re.compile(
        r"^\s*\d+\s+(Po\d+)\(([A-Za-z]+)\)\s+\S+\s+(\S+)\s*(.*)$",
        re.MULTILINE,
    )
    for match in row.finditer(text):
        name, flags, protocol, remainder = match.groups()
        members = {
            member: member_flags
            for member, member_flags in re.findall(r"(\S+?)\(([A-Za-z]+)\)", remainder)
        }
        channels[name] = {
            "flags": flags,
            "up": "U" in flags,
            "protocol": protocol,
            "member_check_applicable": protocol.upper() not in {"NONE", "--"},
            "members": members,
            "bundled_members": sorted(member for member, value in members.items() if "P" in value),
        }
    if not channels:
        raise ParserError("port-channel summary rows were not recognized")
    return {"port_channels": {"applicable": True, "channels": channels}}, {}


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
        if re.match(r"^\s*Neighbor\s+V\s+AS\b", line):
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


def _parse_bgp_unicast_summary(
    output: str,
    *,
    afi: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    family_label = "IPv4" if afi == "ipv4" else "IPv6"
    headings = list(
        re.finditer(
            r"^BGP summary information for VRF (.+?), "
            rf"address family {family_label} Unicast\s*$",
            text,
            re.MULTILINE,
        )
    )
    if not headings:
        if "bgp" in text.lower() and "not configured" in text.lower():
            return {
                "routing_neighbors": {
                    f"bgp_{afi}": {"applicable": False, "vrfs": {}}
                }
            }, {}
        raise ParserError(f"{family_label} BGP VRF headings were not recognized")
    vrfs: dict[str, Any] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end() : end]
        peer_summary = re.search(
            rf"{family_label} Unicast config peers\s+(\d+),\s+capable peers\s+(\d+)",
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
    return {
        "routing_neighbors": {
            f"bgp_{afi}": {"applicable": True, "vrfs": vrfs}
        }
    }, {}


def _parse_bgp_ipv4_summary(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _parse_bgp_unicast_summary(output, afi="ipv4")


def _parse_bgp_ipv6_summary(
    output: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _parse_bgp_unicast_summary(output, afi="ipv6")


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


def _parse_nve_peers(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if "nve interface is not configured" in text.lower():
        return {}, {"nxos-overlay": {"nve_peers": {"applicable": False, "peers": {}}}}
    peers: dict[str, Any] = {}
    row = re.compile(
        r"^\s*(nve\d+)\s+([0-9A-Fa-f:.]+)\s+(Up|Down)\s+"
        r"(\S+)(?:\s+(\S+))?.*$",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in row.finditer(text):
        interface, address, state, learn_type, uptime = match.groups()
        peers[address] = {
            "interface": interface,
            "state": state,
            "learn_type": learn_type,
            "uptime": uptime,
        }
    if not peers:
        raise ParserError("NVE peer table rows were not recognized")
    return {}, {"nxos-overlay": {"nve_peers": {"applicable": True, "peers": peers}}}


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


def _parse_bgp_evpn_routes(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    if "bgp" in text.lower() and "not configured" in text.lower():
        return {}, {"nxos-overlay": {"evpn_routes": {"applicable": False}}}
    routes: set[str] = set()
    entries: list[dict[str, Any]] = []
    counts: dict[str, int] = {"2": 0, "3": 0, "5": 0}
    current_rd: str | None = None
    current_l3vni: int | None = None
    pending: dict[str, Any] | None = None
    pending_status = ""

    def add_path(entry: dict[str, Any], status: str, next_hop: str) -> None:
        normalized_status = re.sub(r"\s+", "", status).lower()
        path = {
            "next_hop": next_hop,
            "best": ">" in normalized_status,
            "local": "l" in normalized_status,
            "status": normalized_status,
        }
        if path not in entry["paths"]:
            entry["paths"].append(path)
        entry.setdefault("next_hop", next_hop)
        entry["best"] = bool(entry.get("best") or path["best"])
        entry["local"] = bool(entry.get("local") or path["local"])

    for line in text.splitlines():
        rd_match = re.match(
            r"^Route Distinguisher:\s+(\S+)(?:\s+\(L3VNI\s+(\d+)\))?",
            line,
            re.IGNORECASE,
        )
        if rd_match:
            current_rd = rd_match.group(1)
            current_l3vni = int(rd_match.group(2)) if rd_match.group(2) else None
            pending = None
            pending_status = ""
            continue
        match = re.search(r"\[(2|3|5)\]:(.+)$", line)
        if not match:
            if pending is not None:
                direct = re.match(r"^\s*([0-9A-Fa-f:.]+)\s+", line)
                continued = re.match(
                    r"^\s*([*><a-zA-Z ]*[*><a-zA-Z])\s+"
                    r"([0-9A-Fa-f:.]+)\s+",
                    line,
                )
                if direct:
                    add_path(pending, pending_status, direct.group(1))
                    pending_status = ""
                elif continued:
                    add_path(pending, continued.group(1), continued.group(2))
            continue
        if not re.search(r"(?:\*>|\*|>)", line[: match.start()]):
            continue
        route_type = match.group(1)
        normalized = re.sub(r"\s+", " ", match.group(0).strip())
        key = f"type-{route_type}:{normalized}"
        if key not in routes:
            routes.add(key)
            counts[route_type] += 1
        status = line[: match.start()]
        entry: dict[str, Any] = {
            "route_type": int(route_type),
            "route_key": key,
            "rd": current_rd,
            "l3vni": current_l3vni,
            "best": ">" in status,
            "local": "l" in status.lower(),
            "paths": [],
        }
        if route_type == "5":
            prefix_match = re.search(
                r"\[5\]:\[\d+\]:\[\d+\]:\[(\d+)\]:\[([^\]]+)\]",
                match.group(0),
            )
            if prefix_match:
                entry["prefix"] = str(
                    ipaddress.ip_network(
                        f"{prefix_match.group(2)}/{prefix_match.group(1)}",
                        strict=False,
                    )
                )
        entries.append(entry)
        pending = entry
        pending_status = status
    if not routes:
        # A valid empty table still carries the standard route distinguisher header.
        if "route distinguisher" not in text.lower() and "network" not in text.lower():
            raise ParserError("EVPN route table was not recognized")
    return {}, {
        "nxos-overlay": {
            "evpn_routes": {
                "applicable": True,
                "route_count": len(routes),
                "route_type_counts": counts,
                "route_keys": sorted(routes),
                "routes": entries,
            }
        }
    }


def _parse_vrf_routes(
    output: str, *, family: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = _require_output(output)
    routes: list[dict[str, Any]] = []
    current_vrf: str | None = None
    pending: dict[str, Any] | None = None
    for line in text.splitlines():
        vrf_match = re.search(
            r"(?:IP Route|IPv6 Routing) Table for VRF [\"']?([^\"'\s]+)",
            line,
            re.IGNORECASE,
        )
        if vrf_match:
            current_vrf = vrf_match.group(1)
            pending = None
            continue
        prefix_match = re.match(
            r"^\s*([0-9A-Fa-f:.]+/\d+)(?:,|\s)", line
        )
        if prefix_match and current_vrf:
            try:
                prefix = str(ipaddress.ip_network(prefix_match.group(1), strict=False))
            except ValueError:
                pending = None
                continue
            pending = {"vrf": current_vrf, "family": family, "prefix": prefix}
            routes.append(pending)
            continue
        if pending is not None and (via := re.match(r"^\s*\*?via\s+(\S+)", line)):
            pending["next_hop"] = via.group(1).rstrip(",")
            lowered = line.lower()
            if "bgp" in lowered:
                pending["protocol"] = "bgp"
            elif "attached" in lowered or "direct" in lowered:
                pending["protocol"] = "connected"
    if not routes:
        if "route not found" in text.lower() or "no routes" in text.lower():
            return {}, {"nxos-overlay": {"vrf_routes": {family: {"routes": []}}}}
        raise ParserError(f"{family} VRF route table was not recognized")
    return {}, {"nxos-overlay": {"vrf_routes": {family: {"routes": routes}}}}


def _parse_ipv4_vrf_routes(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return _parse_vrf_routes(output, family="ipv4")


def _parse_ipv6_vrf_routes(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return _parse_vrf_routes(output, family="ipv6")


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
    "inventory": _parse_inventory,
    "license_usage": _parse_license_usage,
    "processes_cpu": _parse_processes_cpu,
    "system_resources": _parse_system_resources,
    "environment": _parse_environment,
    "running_config_diff": _parse_running_config_diff,
    "reload_pending": _parse_reload_pending,
    "ntp_status": _parse_ntp_status,
    "ntp_peers": _parse_ntp_peers,
    "ntp_peer_status": _parse_ntp_peer_status,
    "interface_status": _parse_interface_status,
    "interface_counters_table": _parse_interface_counters_table,
    "interface_brief": _parse_interface_brief,
    "interface_errors": _parse_interface_errors,
    "port_channel_summary": _parse_port_channel_summary,
    "lldp_neighbors_detail": _parse_lldp_neighbors_detail,
    "route_summary_ipv4": _parse_route_summary_ipv4,
    "ospf_neighbors": _parse_ospf_neighbors,
    "bgp_ipv4_summary": _parse_bgp_ipv4_summary,
    "bgp_ipv6_summary": _parse_bgp_ipv6_summary,
    "vpc_brief": _parse_vpc_brief,
    "nve_interface": _parse_nve_interface,
    "nve_peers": _parse_nve_peers,
    "nve_vni": _parse_nve_vni,
    "nve_vni_ingress_replication": _parse_nve_vni_ingress_replication,
    "vlan_brief": _parse_vlan_brief,
    "vrf": _parse_vrf,
    "bgp_l2vpn_evpn_summary": _parse_bgp_evpn_summary,
    "bgp_l2vpn_evpn": _parse_bgp_evpn_routes,
    "route_ipv4_all_vrfs": _parse_ipv4_vrf_routes,
    "route_ipv6_all_vrfs": _parse_ipv6_vrf_routes,
}


def parse_nxos_command(
    identifier: str,
    output: str,
    *,
    timezone: str = "Asia/Tokyo",
    device_type: str = "nxos",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse one supported NX-OS command into common/profile state."""
    parser = PARSERS.get(identifier)
    if identifier == "show_logging":
        return _parse_show_logging(output, timezone=timezone)
    if identifier == "clock":
        return _parse_clock(output, timezone=timezone)
    if identifier == "lldp_neighbors_detail":
        return _parse_lldp_neighbors_detail(
            output,
            device_type=device_type,
        )
    if parser is None:
        raise KeyError(identifier)
    return parser(output)
