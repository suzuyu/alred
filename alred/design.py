"""Inputs and validation for table-driven containerlab topologies."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import ipaddress
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .constants import DEVICE_TYPE_TO_KIND
from .parsing import (
    get_inventory_device_type,
    is_excluded_interface,
    normalize_hostname,
    normalize_interface_name,
)


REQUIRED_CABLE_COLUMNS = ("src_node", "src_if", "dst_node", "dst_if")
OPTIONAL_CABLE_COLUMNS = ("enabled", "description")


@dataclass(frozen=True)
class ValidationIssue:
    """One design validation result."""

    severity: str
    message: str
    row: int | None = None


def _parse_enabled(value: str, path: str, row: int) -> bool:
    raw = value.strip().lower()
    if not raw:
        return True
    if raw in {"true", "yes", "1", "on"}:
        return True
    if raw in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"{path}:{row}: invalid enabled value: {value}")


def read_cable_table(path: str) -> Tuple[List[Dict[str, Any]], List[ValidationIssue]]:
    """Read a cable CSV and return rows plus non-fatal schema warnings."""
    records: List[Dict[str, Any]] = []
    issues: List[ValidationIssue] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        missing = [name for name in REQUIRED_CABLE_COLUMNS if name not in headers]
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")

        known = set(REQUIRED_CABLE_COLUMNS + OPTIONAL_CABLE_COLUMNS)
        unknown = [name for name in headers if name not in known]
        if unknown:
            issues.append(ValidationIssue("warning", f"Unknown CSV columns are ignored: {', '.join(unknown)}"))

        for row_number, raw in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in raw.values()):
                continue
            record: Dict[str, Any] = {
                name: str(raw.get(name) or "").strip()
                for name in REQUIRED_CABLE_COLUMNS + ("description",)
            }
            record["enabled"] = _parse_enabled(str(raw.get("enabled") or ""), path, row_number)
            record["row"] = row_number
            records.append(record)
    return records, issues


def normalize_and_validate_cables(
    records: List[Dict[str, Any]],
    inventory_map: Dict[str, Dict[str, Any]],
    mappings: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[ValidationIssue]]:
    """Normalize design cable endpoints and validate enabled links."""
    normalized_inventory: Dict[str, Dict[str, Any]] = {}
    for name, attrs in inventory_map.items():
        normalized_inventory[normalize_hostname(name, mappings)] = attrs

    normalized: List[Dict[str, Any]] = []
    issues: List[ValidationIssue] = []
    used_endpoints: Dict[Tuple[str, str], int] = {}
    seen_links: Dict[Tuple[Tuple[str, str], Tuple[str, str]], int] = {}

    for record in records:
        row = int(record["row"])
        src_raw = str(record["src_node"])
        dst_raw = str(record["dst_node"])
        src_node = normalize_hostname(src_raw, mappings)
        dst_node = normalize_hostname(dst_raw, mappings)
        src_type = get_inventory_device_type(src_raw, inventory_map, mappings)
        dst_type = get_inventory_device_type(dst_raw, inventory_map, mappings)
        src_if = normalize_interface_name(str(record["src_if"]), mappings, src_type)
        dst_if = normalize_interface_name(str(record["dst_if"]), mappings, dst_type)

        item = {
            "src_node_raw": src_raw,
            "src_node": src_node,
            "src_if_raw": str(record["src_if"]),
            "src_if": src_if,
            "dst_node_raw": dst_raw,
            "dst_node": dst_node,
            "dst_if_raw": str(record["dst_if"]),
            "dst_if": dst_if,
            "enabled": bool(record["enabled"]),
            "description": str(record.get("description", "")),
            "row": row,
        }
        normalized.append(item)

        for field in REQUIRED_CABLE_COLUMNS:
            if not str(record[field]).strip():
                issues.append(ValidationIssue("error", f"Required value is empty: {field}", row))
        if not item["enabled"]:
            continue

        if src_node not in normalized_inventory:
            issues.append(ValidationIssue("error", f"Unknown node: {src_raw}", row))
        if dst_node not in normalized_inventory:
            issues.append(ValidationIssue("error", f"Unknown node: {dst_raw}", row))
        if src_node and src_node == dst_node:
            issues.append(ValidationIssue("error", f"Self-link is not allowed: {src_node}", row))

        for device_type, ifname, endpoint in (
            (src_type, src_if, (src_node, src_if)),
            (dst_type, dst_if, (dst_node, dst_if)),
        ):
            if device_type == "linux" and ifname == "eth0":
                issues.append(ValidationIssue("error", f"Linux data link cannot use management interface {endpoint[0]}:eth0", row))
            previous = used_endpoints.get(endpoint)
            if endpoint[0] and endpoint[1] and previous is not None:
                issues.append(ValidationIssue("error", f"Endpoint {endpoint[0]}:{endpoint[1]} is already used at row {previous}", row))
            elif endpoint[0] and endpoint[1]:
                used_endpoints[endpoint] = row
            if ifname and is_excluded_interface(ifname, mappings):
                issues.append(ValidationIssue("warning", f"Excluded interface will not be rendered: {endpoint[0]}:{ifname}", row))

        link_key = tuple(sorted(((src_node, src_if), (dst_node, dst_if))))
        previous_link = seen_links.get(link_key)
        if previous_link is not None:
            issues.append(ValidationIssue("error", f"Duplicate link after normalization; first defined at row {previous_link}", row))
        else:
            seen_links[link_key] = row

    return normalized, issues


def validate_inventory(
    inventory_map: Dict[str, Dict[str, Any]],
    normalized_cables: List[Dict[str, Any]],
    mappings: Dict[str, Any],
    clab_env: Dict[str, Any],
) -> List[ValidationIssue]:
    """Validate device types, disconnected nodes, and management addresses."""
    issues: List[ValidationIssue] = []
    connected = {
        str(record[key])
        for record in normalized_cables
        if record["enabled"]
        for key in ("src_node", "dst_node")
    }

    mgmt = clab_env.get("mgmt", {})
    if not isinstance(mgmt, dict):
        return [ValidationIssue("error", "clab env mgmt must be a mapping")]
    subnet = None
    if mgmt.get("ipv4-subnet"):
        try:
            parsed_subnet = ipaddress.ip_network(str(mgmt["ipv4-subnet"]), strict=False)
        except ValueError:
            issues.append(ValidationIssue("error", f"Invalid mgmt.ipv4-subnet: {mgmt['ipv4-subnet']}"))
        else:
            if isinstance(parsed_subnet, ipaddress.IPv4Network):
                subnet = parsed_subnet
            else:
                issues.append(ValidationIssue("error", "mgmt.ipv4-subnet must be IPv4"))
    dynamic_range = None
    if mgmt.get("ipv4-range"):
        try:
            parsed_range = ipaddress.ip_network(str(mgmt["ipv4-range"]), strict=False)
        except ValueError:
            issues.append(ValidationIssue("error", f"Invalid mgmt.ipv4-range: {mgmt['ipv4-range']}"))
        else:
            if isinstance(parsed_range, ipaddress.IPv4Network):
                dynamic_range = parsed_range
            else:
                issues.append(ValidationIssue("error", "mgmt.ipv4-range must be IPv4"))
        if subnet and dynamic_range and not dynamic_range.subnet_of(subnet):
            issues.append(ValidationIssue("error", f"mgmt.ipv4-range {dynamic_range} is outside {subnet}"))

    seen_ips: Dict[ipaddress.IPv4Address, str] = {}
    seen_nodes: Dict[str, str] = {}
    for original_name, attrs in inventory_map.items():
        node_name = normalize_hostname(original_name, mappings)
        previous_node = seen_nodes.get(node_name)
        if previous_node:
            issues.append(ValidationIssue("error", f"Node name {node_name} is duplicated after normalization: {previous_node}, {original_name}"))
        else:
            seen_nodes[node_name] = original_name
        device_type = str(attrs.get("device_type", "unknown"))
        if device_type not in DEVICE_TYPE_TO_KIND or device_type == "unknown":
            issues.append(ValidationIssue("warning", f"Unsupported or unknown device_type for {node_name}: {device_type}"))
        if node_name not in connected:
            issues.append(ValidationIssue("warning", f"Node has no cable connections: {node_name}"))

        raw_ip = str(attrs.get("ip", "") or "").strip()
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            issues.append(ValidationIssue("error", f"Invalid management IPv4 address for {node_name}: {raw_ip}"))
            continue
        if not isinstance(address, ipaddress.IPv4Address):
            issues.append(ValidationIssue("error", f"Management address must be IPv4 for {node_name}: {raw_ip}"))
            continue
        if subnet and address not in subnet:
            issues.append(ValidationIssue("error", f"Management IP {address} for {node_name} is outside {subnet}"))
        if subnet and address in {subnet.network_address, subnet.broadcast_address}:
            issues.append(ValidationIssue("error", f"Management IP {address} for {node_name} is a network/broadcast address"))
        previous = seen_ips.get(address)
        if previous:
            issues.append(ValidationIssue("error", f"Management IP {address} is duplicated by {previous} and {node_name}"))
        else:
            seen_ips[address] = node_name
        if dynamic_range and address in dynamic_range:
            issues.append(ValidationIssue("warning", f"Static management IP {address} for {node_name} overlaps dynamic range {dynamic_range}"))

    return issues


def write_normalized_cables(path: str, records: List[Dict[str, Any]]) -> None:
    """Write design cables with raw and normalized endpoint names."""
    fields = (
        "src_node_raw", "src_node", "src_if_raw", "src_if",
        "dst_node_raw", "dst_node", "dst_if_raw", "dst_if",
        "enabled", "description",
    )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({name: record.get(name, "") for name in fields})


def render_validation_report(issues: List[ValidationIssue]) -> List[str]:
    """Render a concise Markdown validation report."""
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    lines = [
        "# init-clab validation",
        "",
        f"- errors: {len(errors)}",
        f"- warnings: {len(warnings)}",
    ]
    for title, selected in (("Errors", errors), ("Warnings", warnings)):
        lines.extend(["", f"## {title}", ""])
        if not selected:
            lines.append("None")
            continue
        for issue in selected:
            location = f"row {issue.row}: " if issue.row is not None else ""
            lines.append(f"- {location}{issue.message}")
    return lines
