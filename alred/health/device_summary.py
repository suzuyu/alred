"""Deterministic per-device Health Check inventory summaries."""

from __future__ import annotations

import csv
from datetime import datetime
import io
import re
from typing import Any, Mapping

from ..constants import DEFAULT_SITE_PRIORITY
from .evaluator import RESULT_ORDER
from ..schema import validate_document


DEVICE_SUMMARY_COLUMNS = (
    "hostname",
    "management_ip",
    "manufacturer",
    "model",
    "serial_number",
    "os_type",
    "os_version",
    "license_usage",
    "license_parse_status",
    "site",
    "topology_role",
    "functions",
    "health_result",
    "collection_status",
    "collected_at",
)

_MANUFACTURERS = {
    "nxos": "Cisco",
}


def _host_health_result(result: Mapping[str, Any], hostname: str) -> str:
    states = [
        str(check["result"])
        for check in result.get("checks", [])
        if str(check.get("host")) == hostname
    ]
    states.extend(
        str(item["profile_result"])
        for item in result.get("unexecuted_hosts", [])
        if str(item.get("host")) == hostname
    )
    known = [state for state in states if state in RESULT_ORDER]
    if not known:
        return "NOT_APPLICABLE"
    return max(known, key=lambda state: RESULT_ORDER[state])


def _component_serials(components: list[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(component.get("serial_number") or "").strip()
            for component in components
            if str(component.get("serial_number") or "").strip()
        }
    )


def _primary_serial(common: Mapping[str, Any]) -> str:
    inventory = common.get("inventory", {})
    raw_components = inventory.get("components", [])
    components = [
        component
        for component in raw_components
        if isinstance(component, Mapping)
    ]
    chassis = [
        component
        for component in components
        if str(component.get("name") or "").strip().casefold() == "chassis"
    ]
    serials = _component_serials(chassis)
    if len(serials) == 1:
        return serials[0]
    if len(serials) > 1:
        return "UNKNOWN"

    model = str(common.get("system", {}).get("model") or "").strip()
    model_key = re.sub(r"[^A-Z0-9]", "", model.upper())
    model_matches = [
        component
        for component in components
        if model_key
        and re.sub(
            r"[^A-Z0-9]",
            "",
            str(component.get("product_id") or "").upper(),
        )
        == model_key
    ]
    serials = _component_serials(model_matches)
    return serials[0] if len(serials) == 1 else "UNKNOWN"


def _license_parse_status(host_data: Mapping[str, Any]) -> str:
    source = host_data.get("sources", {}).get("license_usage")
    if not isinstance(source, Mapping):
        return "not_collected"
    parse_status = str(source.get("parse_status") or "unknown")
    if parse_status == "unsupported":
        return "unsupported"
    if parse_status != "parsed":
        return "unknown"
    license_data = host_data.get("common", {}).get("license")
    if not isinstance(license_data, Mapping):
        return "unknown"
    return "not_applicable" if license_data.get("applicable") is False else "parsed"


def _license_usage(host_data: Mapping[str, Any], parse_status: str) -> str:
    if parse_status == "not_applicable":
        return "NOT_APPLICABLE"
    if parse_status != "parsed":
        return "UNKNOWN"
    usage = host_data.get("common", {}).get("license", {}).get("usage", [])
    if not isinstance(usage, list):
        return "UNKNOWN"
    values = []
    for item in sorted(
        (entry for entry in usage if isinstance(entry, Mapping)),
        key=lambda entry: str(entry.get("feature") or "").casefold(),
    ):
        feature = str(item.get("feature") or "UNKNOWN")
        installed = "yes" if item.get("installed") is True else "no"
        count = item.get("license_count")
        expiry = item.get("expiry_date") or "-"
        values.append(
            f"{feature}(installed={installed},"
            f"status={item.get('usage_status') or 'unknown'},"
            f"count={count if count is not None else '-'},expiry={expiry})"
        )
    return "; ".join(values) if values else "UNKNOWN"


def _role_values(
    resolved_roles: Mapping[str, Any] | None,
    hostname: str,
) -> tuple[int, str, str]:
    if resolved_roles is None:
        return 99, "UNKNOWN", "-"
    device = resolved_roles.get("spec", {}).get("devices", {}).get(hostname)
    if not isinstance(device, Mapping):
        return 99, "UNKNOWN", "-"
    priority = int(device.get("priority", 99))
    topology_role = str(device.get("topology_role") or "UNKNOWN")
    functions = device.get("functions", {})
    if not isinstance(functions, Mapping):
        return priority, topology_role, "-"
    names = sorted(str(name) for name in functions)
    return priority, topology_role, "; ".join(names) if names else "-"


def _site_priority(
    site: str,
    site_rules: Mapping[str, Any] | None,
) -> int:
    if site_rules is None:
        return DEFAULT_SITE_PRIORITY
    rule = site_rules.get(site)
    if not isinstance(rule, Mapping):
        return DEFAULT_SITE_PRIORITY
    return int(rule.get("priority", DEFAULT_SITE_PRIORITY))


def _display_collected_at(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip()
    if not text:
        return "UNKNOWN"
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=None).isoformat()


def build_device_summary_rows(
    snapshot: Mapping[str, Any],
    health_result: Mapping[str, Any],
    *,
    resolved_roles: Mapping[str, Any] | None = None,
    inventory_sites: Mapping[str, str] | None = None,
    site_rules: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build one deterministic, display-ready row for each Snapshot host."""
    validate_document(snapshot, kind="HealthSnapshot", allow_unknown_fields=True)
    validate_document(health_result, kind="HealthResult")
    if (
        snapshot.get("change_id") != health_result.get("change_id")
        or snapshot.get("phase") != health_result.get("phase")
    ):
        raise ValueError("Device Summary Snapshot and Health Result identity mismatch")
    if resolved_roles is not None:
        validate_document(resolved_roles, kind="ResolvedRoles")
        if resolved_roles.get("metadata", {}).get("change_id") != snapshot.get(
            "change_id"
        ):
            raise ValueError("Device Summary ResolvedRoles change_id mismatch")

    prioritized_rows: list[
        tuple[int, str, str, int, str, str, dict[str, str]]
    ] = []
    for hostname, host_data in snapshot["hosts"].items():
        common = host_data.get("common", {})
        system = common.get("system", {})
        platform = str(host_data.get("platform") or "unknown").strip().lower()
        license_status = _license_parse_status(host_data)
        priority, topology_role, functions = _role_values(
            resolved_roles, hostname
        )
        site = str((inventory_sites or {}).get(hostname) or "UNKNOWN")
        prioritized_rows.append(
            (
                _site_priority(site, site_rules),
                site.casefold(),
                site,
                priority,
                topology_role.casefold(),
                str(hostname),
                {
                    "hostname": str(hostname),
                    "management_ip": str(
                        host_data.get("address") or "UNKNOWN"
                    ),
                    "site": site,
                    "manufacturer": _MANUFACTURERS.get(platform, "UNKNOWN"),
                    "model": str(system.get("model") or "UNKNOWN"),
                    "serial_number": _primary_serial(common),
                    "os_type": platform or "unknown",
                    "os_version": str(system.get("version") or "UNKNOWN"),
                    "license_usage": _license_usage(host_data, license_status),
                    "license_parse_status": license_status,
                    "topology_role": topology_role,
                    "functions": functions,
                    "health_result": _host_health_result(
                        health_result, hostname
                    ),
                    "collection_status": str(
                        host_data.get("collection_status") or "UNKNOWN"
                    ),
                    "collected_at": _display_collected_at(
                        snapshot.get("created_at")
                    ),
                },
            )
        )
    prioritized_rows.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3],
            item[4],
            item[5].casefold(),
            item[5],
        )
    )
    return [row for *_sort_values, row in prioritized_rows]


def render_device_summary_markdown(rows: list[Mapping[str, Any]]) -> str:
    """Render a single Markdown table from canonical Device Summary rows."""

    def cell(value: Any) -> str:
        normalized = " ".join(str(value).splitlines())
        return normalized.replace("\\", "\\\\").replace("|", "\\|")

    lines = [
        "# Device Summary",
        "",
        "| " + " | ".join(DEVICE_SUMMARY_COLUMNS) + " |",
        "|" + "|".join("---" for _column in DEVICE_SUMMARY_COLUMNS) + "|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(cell(row.get(column, "")) for column in DEVICE_SUMMARY_COLUMNS)
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_device_summary_csv(rows: list[Mapping[str, Any]]) -> str:
    """Render RFC-compatible UTF-8 CSV with a fixed column order."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=DEVICE_SUMMARY_COLUMNS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in DEVICE_SUMMARY_COLUMNS})
    return stream.getvalue()
