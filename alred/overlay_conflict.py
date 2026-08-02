"""Shared Overlay ChangeSet conflict assessment for preparation and apply plans."""

from __future__ import annotations

from ipaddress import ip_interface
from typing import Any, Mapping

from .overlay_render import resolve_changeset
from .schema import SCHEMA_VERSION


class OverlayConflictError(ValueError):
    """Raised when a plan cannot safely continue after conflict assessment."""

    code = "PLAN_CONFLICT"


def _check(
    host: str,
    resource: str,
    result: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "host": host,
        "resource": resource,
        "result": result,
        "code": code,
        "message": message,
    }


def _parsed_interface(value: str):
    try:
        return ip_interface(value)
    except ValueError:
        return None


def assess_overlay_conflicts(
    document: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Return all deterministic ChangeSet and observed-state conflicts."""
    resolved = resolve_changeset(document)
    checks: list[dict[str, str]] = []

    for host, desired in resolved.items():
        record = snapshot.get("hosts", {}).get(host)
        state = (
            record.get("profiles", {}).get("nxos-overlay", {}).get("config")
            if isinstance(record, Mapping)
            else None
        )
        if not isinstance(state, Mapping):
            checks.append(
                _check(
                    host,
                    "running-config",
                    "UNKNOWN",
                    "OVERLAY_EVIDENCE_MISSING",
                    "Target device has no parsed nxos-overlay running-config state",
                )
            )
            continue

        host_checks: list[dict[str, str]] = []
        desired_vlans: dict[int, int] = {}
        desired_l2vnis: dict[int, int] = {}
        desired_vrfs: dict[str, int] = {}
        desired_l3vnis: dict[int, str] = {}
        desired_svis: list[tuple[int, str, Mapping[str, Any]]] = []

        for l2 in desired["l2vnis"]:
            vlan = l2["vlan"]
            vni = l2["vni"]
            if vlan in desired_vlans:
                host_checks.append(
                    _check(
                        host,
                        f"vlan/{vlan}",
                        "CONFLICT",
                        "DUPLICATE_DESIRED_VLAN",
                        f"VLAN {vlan} is declared by more than one L2VNI resource",
                    )
                )
            if vni in desired_l2vnis:
                host_checks.append(
                    _check(
                        host,
                        f"l2vni/{vni}",
                        "CONFLICT",
                        "DUPLICATE_DESIRED_L2VNI",
                        f"L2VNI {vni} is declared more than once for the device",
                    )
                )
            desired_vlans[vlan] = vni
            desired_l2vnis[vni] = vlan
            if l2.get("svi") and l2.get("vrf"):
                desired_svis.append((vlan, l2["vrf"], l2["svi"]))

            existing_vlan = state.get("vlans", {}).get(str(vlan))
            if existing_vlan and existing_vlan.get("vni") not in (None, vni):
                host_checks.append(
                    _check(
                        host,
                        f"vlan/{vlan}",
                        "CONFLICT",
                        "VLAN_MAPPED_TO_OTHER_L2VNI",
                        f"VLAN {vlan} is already mapped to L2VNI {existing_vlan.get('vni')}",
                    )
                )
            for current_vlan, values in state.get("vlans", {}).items():
                if values.get("vni") == vni and int(current_vlan) != vlan:
                    host_checks.append(
                        _check(
                            host,
                            f"l2vni/{vni}",
                            "CONFLICT",
                            "L2VNI_MAPPED_TO_OTHER_VLAN",
                            f"L2VNI {vni} is already mapped to VLAN {current_vlan}",
                        )
                    )

            existing_svi = state.get("svis", {}).get(str(vlan))
            if existing_svi is not None and l2.get("svi") is not None:
                expected = {
                    "mtu": l2["svi"]["mtu"],
                    "ipv4_addresses": l2["svi"].get("ipv4_addresses", []),
                    "ipv6_addresses": l2["svi"].get("ipv6_addresses", []),
                    "anycast_gateway": True,
                }
                if l2["svi"].get("ipv6_addresses"):
                    expected.update(
                        {
                            "ipv6_link_local": l2["svi"]["ipv6_link_local"],
                            "ipv6_nd_suppress_ra": l2["svi"][
                                "ipv6_nd_suppress_ra"
                            ],
                        }
                    )
                if l2.get("vrf"):
                    expected["vrf"] = l2["vrf"]
                mismatched = sorted(
                    key
                    for key, value in expected.items()
                    if existing_svi.get(key) != value
                )
                if mismatched:
                    host_checks.append(
                        _check(
                            host,
                            f"svi/Vlan{vlan}",
                            "CONFLICT",
                            "SVI_ATTRIBUTE_CONFLICT",
                            "Existing SVI differs in: " + ", ".join(mismatched),
                        )
                    )

        for l3 in desired["l3vnis"]:
            vrf = l3["vrf"]
            vni = l3["vni"]
            if vrf in desired_vrfs:
                host_checks.append(
                    _check(
                        host,
                        f"vrf/{vrf}",
                        "CONFLICT",
                        "DUPLICATE_DESIRED_VRF",
                        f"VRF {vrf} is declared by more than one L3VNI resource",
                    )
                )
            if vni in desired_l3vnis:
                host_checks.append(
                    _check(
                        host,
                        f"l3vni/{vni}",
                        "CONFLICT",
                        "DUPLICATE_DESIRED_L3VNI",
                        f"L3VNI {vni} is declared more than once for the device",
                    )
                )
            desired_vrfs[vrf] = vni
            desired_l3vnis[vni] = vrf
            existing_vrf = state.get("vrfs", {}).get(vrf)
            if existing_vrf and existing_vrf.get("l3vni") not in (None, vni):
                host_checks.append(
                    _check(
                        host,
                        f"vrf/{vrf}",
                        "CONFLICT",
                        "VRF_MAPPED_TO_OTHER_L3VNI",
                        f"VRF {vrf} is already mapped to L3VNI {existing_vrf.get('l3vni')}",
                    )
                )
            for current_vrf, values in state.get("vrfs", {}).items():
                if values.get("l3vni") == vni and current_vrf != vrf:
                    host_checks.append(
                        _check(
                            host,
                            f"l3vni/{vni}",
                            "CONFLICT",
                            "L3VNI_MAPPED_TO_OTHER_VRF",
                            f"L3VNI {vni} is already mapped to VRF {current_vrf}",
                        )
                    )

        for index, (vlan, vrf, svi) in enumerate(desired_svis):
            desired_addresses = [
                *svi.get("ipv4_addresses", []),
                *svi.get("ipv6_addresses", []),
            ]
            for other_vlan, other_vrf, other_svi in desired_svis[index + 1 :]:
                if other_vrf != vrf or other_vlan == vlan:
                    continue
                other_addresses = [
                    *other_svi.get("ipv4_addresses", []),
                    *other_svi.get("ipv6_addresses", []),
                ]
                for address in desired_addresses:
                    left = _parsed_interface(address)
                    for other in other_addresses:
                        right = _parsed_interface(other)
                        if left and right and left.version == right.version and left.network.overlaps(right.network):
                            host_checks.append(
                                _check(
                                    host,
                                    f"svi/Vlan{vlan}",
                                    "CONFLICT",
                                    "DESIRED_SVI_PREFIX_OVERLAP",
                                    f"{address} overlaps Vlan{other_vlan} {other} in VRF {vrf}",
                                )
                            )
            for interface_name, current_interface in state.get(
                "interfaces", {}
            ).items():
                if (
                    interface_name.lower() == f"vlan{vlan}".lower()
                    or current_interface.get("vrf", "default") != vrf
                ):
                    continue
                current_addresses = [
                    *current_interface.get("ipv4_addresses", []),
                    *current_interface.get("ipv6_addresses", []),
                ]
                for address in desired_addresses:
                    left = _parsed_interface(address)
                    for current_address in current_addresses:
                        right = _parsed_interface(current_address)
                        if left and right and left.version == right.version and left.network.overlaps(right.network):
                            host_checks.append(
                                _check(
                                    host,
                                    f"svi/Vlan{vlan}",
                                    "CONFLICT",
                                    "EXISTING_INTERFACE_PREFIX_OVERLAP",
                                    f"{address} overlaps existing {interface_name} {current_address} in VRF {vrf}",
                                )
                            )

        if host_checks:
            checks.extend(host_checks)
        else:
            checks.append(
                _check(
                    host,
                    "overlay",
                    "PASS",
                    "NO_CONFLICT",
                    "No VLAN, VNI, VRF, or SVI address conflict was found",
                )
            )

    counts = {
        name.lower(): sum(item["result"] == name for item in checks)
        for name in ("PASS", "CONFLICT", "UNKNOWN")
    }
    result = (
        "CONFLICT"
        if counts["conflict"]
        else "UNKNOWN" if counts["unknown"] else "PASS"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": document["metadata"]["change_id"],
        "snapshot_change_id": str(snapshot.get("change_id", "unknown")),
        "result": result,
        "counts": counts,
        "checks": checks,
    }


def render_conflict_report_markdown(report: Mapping[str, Any]) -> str:
    """Render one concise operator-facing conflict report."""
    lines = [
        "# Overlay Conflict Report",
        "",
        f"- Change ID: {report['change_id']}",
        f"- Snapshot Change ID: {report['snapshot_change_id']}",
        f"- Result: {report['result']}",
        "",
        "| Device | Resource | Result | Code | Message |",
        "|---|---|---|---|---|",
    ]
    for item in report["checks"]:
        lines.append(
            f"| {item['host'] or '-'} | {item['resource']} | {item['result']} | "
            f"{item['code']} | {item['message']} |"
        )
    return "\n".join(lines) + "\n"


def require_conflict_free(report: Mapping[str, Any]) -> None:
    """Fail closed after a report has been persisted by the caller."""
    if report["result"] != "PASS":
        raise OverlayConflictError(
            "overlay conflict assessment is "
            f"{report['result']} (conflict={report['counts']['conflict']}, "
            f"unknown={report['counts']['unknown']})"
        )
