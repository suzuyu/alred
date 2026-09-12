"""Join explicit physical-interface state without modifying Snapshot evidence."""

from collections import Counter
from copy import deepcopy
import re
from typing import Any, Mapping


INTERFACE_STATE_VERSION = "1.0"
ABSENT_STATUSES = frozenset({"sfpabsent", "xcvrabsen", "xcvrabsent"})


def physical_interface_identity(name: str) -> str | None:
    match = re.fullmatch(r"(?:Ethernet|Eth)(\d+/\d+(?:/\d+)?)", name.strip(), re.I)
    return "Ethernet" + match[1] if match else None


def _detail_problem(record: Any, source: Mapping[str, Any]) -> str | None:
    if not isinstance(record, Mapping):
        return "detail port is missing or is not an object"
    if record.get("parse_status") != "parsed":
        return str(record.get("parse_warning") or "detail port could not be parsed")
    if any(
        record.get(key) not in ("up", "down")
        for key in ("admin_state", "operational_state")
    ):
        return "detail state is invalid"
    if record.get("down_reason") is not None and not isinstance(
        record["down_reason"], str
    ):
        return "detail down reason is invalid"
    if record.get("parse_warning") is not None:
        return "detail has a parse warning"
    start, end = record.get("line_start"), record.get("line_end")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        return "detail line range is invalid"
    for key, value, lower in (
        ("output_start_line", start, True),
        ("output_end_line", end, False),
    ):
        bound = source.get(key)
        if bound is not None and (
            type(bound) is not int or (value < bound if lower else value > bound)
        ):
            return "detail line range is outside command output"
    return None


def interface_state_view(host: Mapping[str, Any]) -> dict[str, Any]:
    """Build a view from a parsed primary table and optional, trusted detail."""
    interfaces = deepcopy(host["common"]["interfaces"])
    details = host["common"].get("interface_details", {})
    source = host["sources"].get("interface_detail", {})
    trusted = (
        isinstance(source, Mapping)
        and source.get("status") == "success"
        and (
            source.get("parse_status") == "parsed"
            or (
                source.get("parse_status") == "unknown"
                and source.get("partial_records") is True
            )
        )
    )
    identities = Counter(physical_interface_identity(name) for name in interfaces)
    detail_names: dict[str, list[str]] = {}
    if trusted and isinstance(details, Mapping):
        for name in details:
            identity = (
                physical_interface_identity(name) if isinstance(name, str) else None
            )
            if identity:
                detail_names.setdefault(identity, []).append(name)
    provenance, conflicts = {}, {}
    for name, item in interfaces.items():
        status = str(item.get("status", "")).casefold()
        if status in ABSENT_STATUSES:
            item["admin_state"] = "unknown"
        origin = {
            "admin_state": "unknown"
            if item.get("admin_state") == "unknown"
            else "interface_status",
            "operational_state": "interface_status",
        }
        provenance[name] = origin
        identity = physical_interface_identity(name)
        if not identity:
            origin["reason"] = "outside physical Ethernet detail scope"
            continue
        matches = detail_names.get(identity, [])
        if identities[identity] > 1 or len(matches) > 1:
            conflicts[name] = "ambiguous interface identity"
            item.update(admin_state="unknown", operational_state="unknown")
            origin.update(
                admin_state="unknown",
                operational_state="unknown",
                reason=conflicts[name],
            )
            continue
        if not trusted:
            origin["reason"] = "detail source is missing, failed or unparseable"
            continue
        record = details[matches[0]] if matches else None
        problem = _detail_problem(record, source)
        if problem:
            origin["reason"] = problem
            if problem == "duplicate interface identity":
                conflicts[name] = problem
                item.update(admin_state="unknown", operational_state="unknown")
                origin.update(admin_state="unknown", operational_state="unknown")
            continue
        origin.update(
            line_start=record["line_start"],
            line_end=record["line_end"],
            command_id="interface_detail",
        )
        reasons = []
        if item.get("operational_state") != record["operational_state"]:
            reasons.append("operational state conflicts between status and detail")
            item["operational_state"] = "unknown"
            origin["operational_state"] = "unknown"
        if record["admin_state"] == "down" and record["operational_state"] == "up":
            reasons.append("detail reports admin-down and operational-up")
            item["operational_state"] = "unknown"
            origin["operational_state"] = "unknown"
        if (status == "connected" and record["admin_state"] != "up") or (
            status == "disabled" and record["admin_state"] != "down"
        ):
            reasons.append("administrative state conflicts between status and detail")
        if reasons:
            conflicts[name] = "; ".join(reasons)
            item["admin_state"] = "unknown"
            origin.update(admin_state="unknown", reason=conflicts[name])
        else:
            item["admin_state"] = record["admin_state"]
            origin["admin_state"] = "interface_detail"
    return {
        "interfaces": interfaces,
        "interface_state_sources": provenance,
        "interface_state_conflicts": conflicts,
        "unmatched_interface_details": sorted(
            name
            for identity, names in detail_names.items()
            if identity not in identities
            for name in names
        ),
    }
