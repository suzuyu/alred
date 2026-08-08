"""Canonical Overlay state and deterministic VNI mapping renderers."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping

from ..schema import API_VERSION, validate_document


VNI_MAP_VERSION = "1.0"
VNI_MAP_CSV_FIELDS = [
    "resource_type",
    "l3vni",
    "vrf",
    "l2vni",
    "gateway_ipv4",
    "gateway_ipv6",
    "device",
    "vlan",
    "vlan_name",
    "ipv6_link_local",
    "mtu",
    "anycast_gateway",
    "nve_member",
    "operational_state",
    "status",
]
VNI_DIFF_CSV_FIELDS = [
    "change_type",
    "resource_type",
    "vni",
    "vrf",
    "device",
    "field",
    "before",
    "after",
    "status",
    "evidence_before",
    "evidence_after",
]
VNI_DIFF_FIELD_SOURCES = {
    "running_config": {
        "label": "Running configuration",
        "command": "show running-config",
    },
    "nve_vni": {
        "label": "Operational command output",
        "command": "show nve vni",
    },
}


def overlay_profile_enabled(profile_names: list[str] | tuple[str, ...]) -> bool:
    """Return whether the resolved profile set requests Overlay artifacts."""
    return "nxos-overlay" in profile_names


def _evidence(host_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for identifier in ("running_config", "nve_vni"):
        source = host_data.get("sources", {}).get(identifier)
        if not isinstance(source, Mapping):
            continue
        item = {
            key: source[key]
            for key in ("command", "file", "sha256", "parse_status", "status")
            if key in source
        }
        item["source_id"] = identifier
        result.append(item)
    return result


def _operational_vnis(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    value = profile.get("nve_vnis", {})
    if not isinstance(value, Mapping) or not value.get("applicable", True):
        return {}
    vnis = value.get("vnis", {})
    return vnis if isinstance(vnis, Mapping) else {}


def _l3_device(config: Mapping[str, Any], profile: Mapping[str, Any], vrf: str, vni: int) -> dict[str, Any]:
    processes: dict[str, Any] = {}
    for local_as, process in sorted(config.get("bgp_processes", {}).items()):
        vrf_state = process.get("vrfs", {}).get(vrf)
        if vrf_state is not None:
            processes[str(local_as)] = deepcopy(vrf_state)
    operational = _operational_vnis(profile).get(str(vni), {})
    vrf_config = config.get("vrfs", {}).get(vrf, {})
    return {
        "local_as": sorted(processes),
        "bgp_processes": processes,
        "rd": vrf_config.get("rd"),
        "address_families": deepcopy(vrf_config.get("address_families", {})),
        "nve_associate_vrf": bool(
            config.get("nve", {}).get("l3vnis", {}).get(str(vni), {}).get(
                "associate_vrf"
            )
        ),
        "operational_state": operational.get("state"),
    }


def _l2_device(
    config: Mapping[str, Any],
    profile: Mapping[str, Any],
    vlan: str | None,
    vni: int,
) -> dict[str, Any]:
    vlan_config = config.get("vlans", {}).get(str(vlan), {}) if vlan else {}
    svi = config.get("svis", {}).get(str(vlan), {}) if vlan else {}
    operational = _operational_vnis(profile).get(str(vni), {})
    return {
        "vlan": int(vlan) if vlan is not None else None,
        "vlan_name": vlan_config.get("name"),
        "nve_member": str(vni) in config.get("nve", {}).get("l2vnis", {}),
        "operational_state": operational.get("state"),
        "replication": operational.get("replication"),
        "svi": deepcopy(svi) if svi else None,
    }


def _resource_status(resource: Mapping[str, Any]) -> str:
    devices = resource["devices"]
    if any(not item.get("nve_member", item.get("nve_associate_vrf", False)) for item in devices.values()):
        return "CONFLICT"
    if any(item.get("operational_state") is None for item in devices.values()):
        return "UNKNOWN"
    vlans = {item.get("vlan") for item in devices.values() if "vlan" in item}
    return "DEVICE_VARIANT" if len(vlans) > 1 else "CONSISTENT"


def build_overlay_state(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a phase-local Overlay State without performing device access."""
    l2: dict[tuple[int, str], dict[str, Any]] = {}
    l3: dict[tuple[int, str], dict[str, Any]] = {}
    evidence: dict[str, Any] = {}
    unknowns: list[dict[str, Any]] = []

    for host, host_data in sorted(snapshot["hosts"].items()):
        evidence[host] = _evidence(host_data)
        profile = host_data.get("profiles", {}).get("nxos-overlay", {})
        config = profile.get("config") if isinstance(profile, Mapping) else None
        if not isinstance(config, Mapping):
            unknowns.append(
                {
                    "host": host,
                    "resource_type": "OVERLAY_STATE",
                    "reason": "running_config_overlay_state_unavailable",
                }
            )
            continue

        host_l2_vnis: set[int] = set()
        for vlan, vlan_config in sorted(config.get("vlans", {}).items()):
            raw_vni = vlan_config.get("vni")
            if raw_vni is None:
                continue
            vni = int(raw_vni)
            host_l2_vnis.add(vni)
            svi = config.get("svis", {}).get(str(vlan), {})
            vrf = str(svi.get("vrf", ""))
            key = (vni, vrf)
            resource = l2.setdefault(
                key,
                {
                    "vni": vni,
                    "vrf": vrf or None,
                    "vlan_name": None,
                    "status": "CONSISTENT",
                    "devices": {},
                },
            )
            resource["devices"][host] = _l2_device(
                config, profile, str(vlan), vni
            )

        for raw_vni in sorted(config.get("nve", {}).get("l2vnis", {}), key=int):
            vni = int(raw_vni)
            if vni in host_l2_vnis:
                continue
            key = (vni, "")
            resource = l2.setdefault(
                key,
                {
                    "vni": vni,
                    "vrf": None,
                    "vlan_name": None,
                    "status": "UNKNOWN",
                    "devices": {},
                },
            )
            resource["devices"][host] = _l2_device(config, profile, None, vni)

        host_l3_vnis: set[int] = set()
        for vrf, vrf_config in sorted(config.get("vrfs", {}).items()):
            raw_vni = vrf_config.get("l3vni")
            if raw_vni is None:
                continue
            vni = int(raw_vni)
            host_l3_vnis.add(vni)
            key = (vni, str(vrf))
            resource = l3.setdefault(
                key,
                {
                    "vni": vni,
                    "vrf": str(vrf),
                    "status": "CONSISTENT",
                    "devices": {},
                },
            )
            resource["devices"][host] = _l3_device(
                config, profile, str(vrf), vni
            )

        for raw_vni in sorted(config.get("nve", {}).get("l3vnis", {}), key=int):
            vni = int(raw_vni)
            if vni in host_l3_vnis:
                continue
            key = (vni, "")
            resource = l3.setdefault(
                key,
                {
                    "vni": vni,
                    "vrf": None,
                    "status": "UNKNOWN",
                    "devices": {},
                },
            )
            resource["devices"][host] = _l3_device(config, profile, "", vni)

    conflicts: list[dict[str, Any]] = []
    for resource_type, resources in (("L2VNI", l2), ("L3VNI", l3)):
        by_vni: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for resource in resources.values():
            by_vni[resource["vni"]].append(resource)
        for vni, matches in sorted(by_vni.items()):
            vrfs = {item.get("vrf") for item in matches if item.get("vrf")}
            if len(vrfs) > 1:
                conflicts.append(
                    {
                        "resource_type": resource_type,
                        "vni": vni,
                        "reason": "vni_maps_to_multiple_vrfs",
                        "values": sorted(vrfs),
                    }
                )
                for item in matches:
                    item["status"] = "CONFLICT"
        for resource in resources.values():
            names = {
                item.get("vlan_name")
                for item in resource["devices"].values()
                if item.get("vlan_name")
            }
            if resource_type == "L2VNI" and len(names) == 1:
                resource["vlan_name"] = next(iter(names))
            elif resource_type == "L2VNI" and len(names) > 1:
                resource["status"] = "CONFLICT"
                conflicts.append(
                    {
                        "resource_type": resource_type,
                        "vni": resource["vni"],
                        "reason": "vlan_name_mismatch",
                        "values": sorted(names),
                    }
                )
            if resource["status"] != "CONFLICT":
                resource["status"] = _resource_status(resource)
                if resource["status"] == "CONFLICT":
                    membership_key = (
                        "nve_member"
                        if resource_type == "L2VNI"
                        else "nve_associate_vrf"
                    )
                    missing_hosts = sorted(
                        host
                        for host, device in resource["devices"].items()
                        if not device.get(membership_key, False)
                    )
                    conflicts.append(
                        {
                            "resource_type": resource_type,
                            "vni": resource["vni"],
                            "reason": "nve_membership_missing",
                            "devices": missing_hosts,
                        }
                    )
            if resource["status"] == "UNKNOWN":
                unknowns.append(
                    {
                        "resource_type": resource_type,
                        "vni": resource["vni"],
                        "vrf": resource.get("vrf"),
                        "reason": "operational_state_unavailable",
                    }
                )

    l2_values = sorted(l2.values(), key=lambda item: (item["vni"], item.get("vrf") or ""))
    l3_values = sorted(l3.values(), key=lambda item: (item["vni"], item.get("vrf") or ""))
    state = {
        "api_version": API_VERSION,
        "kind": "OverlayState",
        "metadata": {
            "change_id": snapshot["change_id"],
            "phase": snapshot["phase"],
            "generated_at": snapshot["created_at"],
            "timezone": snapshot.get("timezone", "Asia/Tokyo"),
            "profile_sha256": snapshot["profile_sha256"],
            "parser_versions": deepcopy(snapshot.get("parser_versions", {})),
            "generator_version": VNI_MAP_VERSION,
        },
        "spec": {
            "scope": {"included_hosts": sorted(snapshot["hosts"])},
            "summary": {
                "l2vnis": len(l2_values),
                "l3vnis": len(l3_values),
                "conflicts": len(conflicts),
                "unknowns": len(unknowns),
            },
            "l2vnis": l2_values,
            "l3vnis": l3_values,
            "conflicts": conflicts,
            "unknowns": unknowns,
            "evidence": evidence,
        },
    }
    validate_document(state, kind="OverlayState")
    return state


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def overlay_state_csv(state: Mapping[str, Any]) -> str:
    """Render device-local VNI rows while preserving legacy mapping columns."""
    l3_by_vrf = {
        item.get("vrf"): item["vni"]
        for item in state["spec"]["l3vnis"]
        if item.get("vrf")
    }
    rows: list[dict[str, Any]] = []
    for resource in state["spec"]["l2vnis"]:
        for host, device in sorted(resource["devices"].items()):
            svi = device.get("svi") or {}
            rows.append(
                {
                    "resource_type": "L2VNI",
                    "l3vni": l3_by_vrf.get(resource.get("vrf")),
                    "vrf": resource.get("vrf"),
                    "l2vni": resource["vni"],
                    "gateway_ipv4": svi.get("ipv4_addresses", []),
                    "gateway_ipv6": svi.get("ipv6_addresses", []),
                    "device": host,
                    "vlan": device.get("vlan"),
                    "vlan_name": device.get("vlan_name"),
                    "ipv6_link_local": svi.get("ipv6_link_local"),
                    "mtu": svi.get("mtu"),
                    "anycast_gateway": svi.get("anycast_gateway", False),
                    "nve_member": device.get("nve_member"),
                    "operational_state": device.get("operational_state"),
                    "status": resource["status"],
                }
            )
    for resource in state["spec"]["l3vnis"]:
        for host, device in sorted(resource["devices"].items()):
            rows.append(
                {
                    "resource_type": "L3VNI",
                    "l3vni": resource["vni"],
                    "vrf": resource.get("vrf"),
                    "l2vni": None,
                    "device": host,
                    "nve_member": device.get("nve_associate_vrf"),
                    "operational_state": device.get("operational_state"),
                    "status": resource["status"],
                }
            )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=VNI_MAP_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _json_cell(row.get(key)) for key in VNI_MAP_CSV_FIELDS})
    return stream.getvalue()


def render_overlay_state_markdown(state: Mapping[str, Any]) -> str:
    """Render a compact operator-facing VNI mapping."""
    metadata = state["metadata"]
    summary = state["spec"]["summary"]
    lines = [
        "# VNI Mapping",
        "",
        f"- Change ID: {metadata['change_id']}",
        f"- Phase: {metadata['phase']}",
        f"- Generated at: {metadata['generated_at']}",
        f"- L2VNIs: {summary['l2vnis']}",
        f"- L3VNIs: {summary['l3vnis']}",
        f"- Conflicts: {summary['conflicts']}",
        f"- Unknowns: {summary['unknowns']}",
        "",
        "## L3VNI",
        "",
        "| L3VNI | VRF | Devices | NVE states | Status |",
        "|---:|---|---|---|---|",
    ]
    for resource in state["spec"]["l3vnis"]:
        devices = ", ".join(sorted(resource["devices"]))
        states = ", ".join(
            f"{host}={device.get('operational_state') or 'UNKNOWN'}"
            for host, device in sorted(resource["devices"].items())
        )
        lines.append(
            f"| {resource['vni']} | {resource.get('vrf') or '-'} | {devices} | {states} | {resource['status']} |"
        )
    if not state["spec"]["l3vnis"]:
        lines.append("| - | - | - | - | NOT_APPLICABLE |")
    lines.extend(
        [
            "",
            "## L2VNI",
            "",
            "| L2VNI | VRF | VLAN name | Devices / VLANs | Gateway IPv4 | Gateway IPv6 | NVE states | Status |",
            "|---:|---|---|---|---|---|---|---|",
        ]
    )
    for resource in state["spec"]["l2vnis"]:
        device_vlans = ", ".join(
            f"{host}={device.get('vlan') if device.get('vlan') is not None else '-'}"
            for host, device in sorted(resource["devices"].items())
        )
        ipv4 = sorted(
            {address for device in resource["devices"].values() for address in (device.get("svi") or {}).get("ipv4_addresses", [])}
        )
        ipv6 = sorted(
            {address for device in resource["devices"].values() for address in (device.get("svi") or {}).get("ipv6_addresses", [])}
        )
        states = ", ".join(
            f"{host}={device.get('operational_state') or 'UNKNOWN'}"
            for host, device in sorted(resource["devices"].items())
        )
        lines.append(
            f"| {resource['vni']} | {resource.get('vrf') or '-'} | {resource.get('vlan_name') or '-'} | "
            f"{device_vlans} | {_json_cell(ipv4)} | {_json_cell(ipv6)} | {states} | {resource['status']} |"
        )
    if not state["spec"]["l2vnis"]:
        lines.append("| - | - | - | - | - | - | - | NOT_APPLICABLE |")
    if state["spec"]["conflicts"]:
        lines.extend(["", "## Conflicts", ""])
        for item in state["spec"]["conflicts"]:
            lines.append(f"- {item['resource_type']} {item['vni']}: {item['reason']}")
    if state["spec"]["unknowns"]:
        lines.extend(["", "## Unknowns", ""])
        for item in state["spec"]["unknowns"]:
            target = item.get("host") or f"{item.get('resource_type')} {item.get('vni', '')}".strip()
            lines.append(f"- {target}: {item['reason']}")
    return "\n".join(lines) + "\n"


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
        return result
    return {prefix or "value": value}


def _resource_index(state: Mapping[str, Any]) -> dict[tuple[str, int, str, str], dict[str, Any]]:
    result: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for resource_type, key in (("L2VNI", "l2vnis"), ("L3VNI", "l3vnis")):
        for resource in state["spec"][key]:
            for host, device in resource["devices"].items():
                identity = (
                    resource_type,
                    int(resource["vni"]),
                    str(resource.get("vrf") or ""),
                    str(host),
                )
                result[identity] = {
                    "value": device,
                    "status": resource["status"],
                }
    return result


def compare_overlay_states(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic field-level VNI changes for CSV/JSON rendering."""
    if before["metadata"]["change_id"] != after["metadata"]["change_id"]:
        raise ValueError("Overlay State change_id mismatch")
    before_index = _resource_index(before)
    after_index = _resource_index(after)
    changes: list[dict[str, Any]] = []
    before_evidence = before["spec"].get("evidence", {})
    after_evidence = after["spec"].get("evidence", {})
    for identity in sorted(set(before_index) | set(after_index)):
        resource_type, vni, vrf, host = identity
        old = before_index.get(identity)
        new = after_index.get(identity)
        old_flat = _flatten(old["value"]) if old else {}
        new_flat = _flatten(new["value"]) if new else {}
        for field in sorted(set(old_flat) | set(new_flat)):
            old_value = old_flat.get(field)
            new_value = new_flat.get(field)
            if old is not None and new is not None and old_value == new_value:
                continue
            change_type = "ADDED" if old is None else "REMOVED" if new is None else "MODIFIED"
            resource_status = (new or old or {}).get("status")
            status = resource_status if resource_status in {"CONFLICT", "UNKNOWN"} else "OBSERVED"
            changes.append(
                {
                    "change_type": change_type,
                    "resource_type": resource_type,
                    "vni": vni,
                    "vrf": vrf or None,
                    "device": host,
                    "field": field,
                    "before": old_value,
                    "after": new_value,
                    "status": status,
                    "evidence_before": deepcopy(before_evidence.get(host, [])),
                    "evidence_after": deepcopy(after_evidence.get(host, [])),
                }
            )
    for key, change_type in (("conflicts", "CONFLICT"), ("unknowns", "UNKNOWN")):
        before_values = {
            json.dumps(item, ensure_ascii=False, sort_keys=True): item
            for item in before["spec"].get(key, [])
        }
        after_values = {
            json.dumps(item, ensure_ascii=False, sort_keys=True): item
            for item in after["spec"].get(key, [])
        }
        for serialized in sorted(set(after_values) - set(before_values)):
            item = after_values[serialized]
            host = str(item.get("host") or ",".join(item.get("devices", [])) or "-")
            changes.append(
                {
                    "change_type": change_type,
                    "resource_type": item.get("resource_type", "OVERLAY_STATE"),
                    "vni": item.get("vni"),
                    "vrf": item.get("vrf"),
                    "device": host,
                    "field": str(item.get("reason", key)),
                    "before": None,
                    "after": deepcopy(item),
                    "status": change_type,
                    "evidence_before": deepcopy(before_evidence.get(host, [])),
                    "evidence_after": deepcopy(after_evidence.get(host, [])),
                }
            )
    changes.sort(
        key=lambda item: (
            item.get("vni") is None,
            item.get("vni") or 0,
            item["resource_type"],
            item.get("vrf") or "",
            item["device"],
            item["field"],
            item["change_type"],
        )
    )
    counts = {key: 0 for key in ("ADDED", "REMOVED", "MODIFIED", "CONFLICT", "UNKNOWN")}
    for change in changes:
        counts[change["change_type"]] += 1
        if (
            change["status"] in {"CONFLICT", "UNKNOWN"}
            and change["status"] != change["change_type"]
        ):
            counts[change["status"]] += 1
    document = {
        "api_version": API_VERSION,
        "kind": "OverlayVniMapDiff",
        "metadata": {
            "change_id": before["metadata"]["change_id"],
            "before_phase": before["metadata"]["phase"],
            "after_phase": after["metadata"]["phase"],
            "generated_at": after["metadata"]["generated_at"],
            "generator_version": VNI_MAP_VERSION,
        },
        "summary": {"total_changes": len(changes), **{key.lower(): value for key, value in counts.items()}},
        "changes": changes,
    }
    validate_document(document, kind="OverlayVniMapDiff")
    return document


def overlay_diff_csv(diff: Mapping[str, Any]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=VNI_DIFF_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for change in diff["changes"]:
        row = dict(change)
        row["evidence_before"] = ";".join(
            str(item.get("file", "")) for item in change.get("evidence_before", []) if item.get("file")
        )
        row["evidence_after"] = ";".join(
            str(item.get("file", "")) for item in change.get("evidence_after", []) if item.get("file")
        )
        writer.writerow({key: _json_cell(row.get(key)) for key in VNI_DIFF_CSV_FIELDS})
    return stream.getvalue()


def _diff_field_source_ids(change: Mapping[str, Any]) -> tuple[str, ...]:
    field = str(change["field"])
    if field in {"operational_state", "replication"}:
        return ("nve_vni",)
    if field in {
        "nve_member",
        "nve_associate_vrf",
        "local_as",
        "rd",
        "vlan",
        "vlan_name",
    } or field.startswith(("svi.", "bgp_processes.", "address_families.")):
        return ("running_config",)
    source_ids = {
        str(item["source_id"])
        for phase in ("evidence_before", "evidence_after")
        for item in change.get(phase, [])
        if item.get("source_id")
    }
    return tuple(sorted(source_ids))


def render_overlay_diff_markdown(diff: Mapping[str, Any]) -> str:
    grouped: list[dict[str, Any]] = []
    group_index: dict[tuple[Any, ...], dict[str, Any]] = {}
    for change in diff["changes"]:
        key = (
            change["resource_type"],
            change.get("vni"),
            change.get("vrf"),
            change["change_type"],
            change["field"],
            json.dumps(change.get("before"), ensure_ascii=False, sort_keys=True),
            json.dumps(change.get("after"), ensure_ascii=False, sort_keys=True),
            change["status"],
        )
        item = group_index.get(key)
        if item is None:
            item = {**change, "devices": []}
            group_index[key] = item
            grouped.append(item)
        if change["device"] not in item["devices"]:
            item["devices"].append(change["device"])
    grouped.sort(
        key=lambda item: (
            item.get("vni") is None,
            item.get("vni") or 0,
            item["resource_type"],
            item.get("vrf") or "",
            item["field"],
            item["devices"][0],
            item["change_type"],
        )
    )

    lines = [
        "# VNI Mapping Diff",
        "",
        f"- Change ID: {diff['metadata']['change_id']}",
        f"- Before phase: {diff['metadata']['before_phase']}",
        f"- After phase: {diff['metadata']['after_phase']}",
        f"- Field changes: {diff['summary']['total_changes']}",
        f"- Display rows: {len(grouped)}",
    ]
    current_resource: tuple[str, int | None, str | None] | None = None
    for change in grouped:
        resource = (
            change["resource_type"],
            change.get("vni"),
            change.get("vrf"),
        )
        if resource != current_resource:
            resource_type, vni, vrf = resource
            heading = (
                "Overlay State"
                if vni is None
                else f"{resource_type} {vni} — VRF {vrf or '-'}"
            )
            lines.extend(
                [
                    "",
                    f"## {heading}",
                    "",
                    "| Change | Field | Devices | Before | After | Status |",
                    "|---|---|---|---|---|---|",
                ]
            )
            current_resource = resource
        values = {
            key: _json_cell(change.get(key)).replace("|", "\\|")
            for key in ("before", "after")
        }
        lines.append(
            f"| {change['change_type']} | {change['field']} | {', '.join(change['devices'])} | "
            f"{values['before'] or '-'} | {values['after'] or '-'} | {change['status']} |"
        )
    if not grouped:
        lines.extend(["", "No VNI mapping changes were observed."])
        return "\n".join(lines) + "\n"

    source_fields: dict[str, set[str]] = defaultdict(set)
    evidence_by_source: dict[str, dict[str, dict[str, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for change in diff["changes"]:
        source_ids = _diff_field_source_ids(change)
        for source_id in source_ids:
            source_fields[source_id].add(str(change["field"]))
        for phase in ("before", "after"):
            for item in change.get(f"evidence_{phase}", []):
                source_id = str(item.get("source_id") or "")
                if source_id not in source_ids or not item.get("file"):
                    continue
                evidence_by_source[source_id][change["device"]][phase] = str(
                    item["file"]
                )

    lines.extend(
        [
            "",
            "## Field Source List",
            "",
            "| Fields | Source | Verification command |",
            "|---|---|---|",
        ]
    )
    for source_id in sorted(source_fields):
        source = VNI_DIFF_FIELD_SOURCES.get(source_id)
        label = source["label"] if source else source_id
        command = source["command"] if source else "-"
        lines.append(
            f"| {', '.join(sorted(source_fields[source_id]))} | {label} | `{command}` |"
        )

    lines.extend(
        [
            "",
            "## Evidence Files",
            "",
            "| Command | Device | Before evidence | After evidence |",
            "|---|---|---|---|",
        ]
    )
    evidence_rows = 0
    for source_id in sorted(evidence_by_source):
        source = VNI_DIFF_FIELD_SOURCES.get(source_id)
        command = source["command"] if source else source_id
        for device, phases in sorted(evidence_by_source[source_id].items()):
            lines.append(
                f"| `{command}` | {device} | {phases.get('before', '-')} | "
                f"{phases.get('after', '-')} |"
            )
            evidence_rows += 1
    if not evidence_rows:
        lines.append("| - | - | - | - |")
    return "\n".join(lines) + "\n"
