"""Overlay change checks and offline convergence assessment."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..overlay_render import OverlayRenderError, resolve_changeset
from ..schema import SCHEMA_VERSION, validate_document


class OverlayEvaluationError(ValueError):
    """Raised when Overlay evaluation inputs are incompatible."""

    code = "VALIDATION_ERROR"


ORDER = {
    "NOT_APPLICABLE": 0,
    "PASS": 1,
    "WARN": 2,
    "UNKNOWN": 3,
    "FAIL": 4,
    "PLAN_ERROR": 5,
}


def _evidence(snapshot: Mapping[str, Any], host: str, command_id: str) -> list[dict[str, Any]]:
    source = snapshot["hosts"][host].get("sources", {}).get(command_id)
    if not source:
        return []
    return [
        {
            "collection_id": snapshot["collection_id"],
            "command": source.get("command"),
            "file": source.get("file"),
            "sha256": source.get("sha256"),
            "parse_status": source.get("parse_status"),
        }
    ]


def _check(
    section: str,
    host: str,
    resource: str,
    result: str,
    message: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "check_id": f"overlay_{section}",
        "section": section,
        "host": host,
        "resource": resource,
        "result": result,
        "message": message,
        "evidence": evidence,
    }


def _result(checks: Sequence[Mapping[str, Any]]) -> str:
    if not checks:
        return "NOT_APPLICABLE"
    return max((item["result"] for item in checks), key=lambda value: ORDER[value])


def _svi_matches(current: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    expected = {
        "mtu": desired["mtu"],
        "ipv4_addresses": desired.get("ipv4_addresses", []),
        "ipv6_addresses": desired.get("ipv6_addresses", []),
        "anycast_gateway": desired.get("gateway_mode", "anycast") == "anycast",
    }
    if desired.get("ipv6_addresses"):
        expected["ipv6_link_local"] = desired["ipv6_link_local"]
        expected["ipv6_nd_suppress_ra"] = desired[
            "ipv6_nd_suppress_ra"
        ]
    return all(current.get(key) == value for key, value in expected.items())


def _impact_checks(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    before_profile = before["hosts"][host]["profiles"].get("nxos-overlay", {})
    after_profile = after["hosts"][host]["profiles"].get("nxos-overlay", {})
    before_nve = before_profile.get("nve_interface")
    after_nve = after_profile.get("nve_interface")
    nve_evidence = [
        *_evidence(before, host, "nve_interface"),
        *_evidence(after, host, "nve_interface"),
    ]
    if before_nve is None or after_nve is None:
        checks.append(
            _check(
                "impact",
                host,
                "nve/interface",
                "UNKNOWN",
                "NVE interface evidence is incomplete",
                nve_evidence,
            )
        )
    else:
        before_up = before_nve.get("state", "").lower() == "up"
        after_up = after_nve.get("state", "").lower() == "up"
        checks.append(
            _check(
                "impact",
                host,
                "nve/interface",
                "FAIL" if before_up and not after_up else ("PASS" if after_up else "WARN"),
                "Existing NVE interface state was preserved"
                if after_up
                else "NVE interface is not Up after the change",
                nve_evidence,
            )
        )
    before_bgp = before_profile.get("evpn_bgp")
    after_bgp = after_profile.get("evpn_bgp")
    bgp_evidence = [
        *_evidence(before, host, "bgp_l2vpn_evpn_summary"),
        *_evidence(after, host, "bgp_l2vpn_evpn_summary"),
    ]
    if before_bgp is None or after_bgp is None:
        checks.append(
            _check(
                "impact",
                host,
                "bgp/evpn",
                "UNKNOWN",
                "EVPN BGP evidence is incomplete",
                bgp_evidence,
            )
        )
    else:
        before_established = {
            peer
            for peer, value in before_bgp.get("neighbors", {}).items()
            if value.get("state") == "Established"
        }
        after_established = {
            peer
            for peer, value in after_bgp.get("neighbors", {}).items()
            if value.get("state") == "Established"
        }
        lost = sorted(before_established - after_established)
        checks.append(
            _check(
                "impact",
                host,
                "bgp/evpn",
                "FAIL" if lost else "PASS",
                (
                    "Existing EVPN BGP peers were preserved"
                    if not lost
                    else "Established EVPN BGP peers were lost: " + ", ".join(lost)
                ),
                bgp_evidence,
            )
        )
    return checks


def evaluate_overlay_change(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    change_set: Mapping[str, Any],
    *,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    """Evaluate configuration, operational state, and existing Fabric impact."""
    validate_document(before, kind="HealthSnapshot", allow_unknown_fields=True)
    validate_document(after, kind="HealthSnapshot", allow_unknown_fields=True)
    validate_document(change_set, kind="OverlayChangeSet")
    if before["change_id"] != after["change_id"] or before["change_id"] != change_set["metadata"]["change_id"]:
        raise OverlayEvaluationError("before/after/ChangeSet change_id mismatch")
    if set(before["hosts"]) != set(after["hosts"]):
        raise OverlayEvaluationError("before/after host set mismatch")
    try:
        desired = resolve_changeset(
            change_set,
            allow_discovered=True,
            require_bgp_address_families=False,
        )
    except OverlayRenderError as exc:
        raise OverlayEvaluationError(str(exc)) from exc

    checks: list[dict[str, Any]] = []
    l2_placements: dict[int, int] = {}
    l2_target_hosts: dict[int, list[str]] = {}
    for resources in desired.values():
        for l2 in resources["l2vnis"]:
            l2_placements[l2["vni"]] = l2_placements.get(l2["vni"], 0) + 1
    for target_host, resources in desired.items():
        for l2 in resources["l2vnis"]:
            l2_target_hosts.setdefault(l2["vni"], []).append(target_host)
    for host, resources in desired.items():
        if host not in after["hosts"]:
            checks.append(
                _check(
                    "configuration",
                    host,
                    "device",
                    "PLAN_ERROR",
                    "Target device is absent from after Snapshot",
                    [],
                )
            )
            continue
        profile = after["hosts"][host]["profiles"].get("nxos-overlay", {})
        config = profile.get("config")
        if config is None:
            checks.append(
                _check(
                    "configuration",
                    host,
                    "running-config",
                    "UNKNOWN",
                    "Overlay running-config evidence is unavailable",
                    _evidence(after, host, "running_config"),
                )
            )
            continue
        operational = profile.get("nve_vnis", {}).get("vnis", {})
        for l2 in resources["l2vnis"]:
            vlan = config["vlans"].get(str(l2["vlan"]))
            config_ok = bool(
                vlan
                and vlan.get("vni") == l2["vni"]
                and (
                    not l2.get("vlan_name")
                    or vlan.get("name") == l2["vlan_name"]
                )
                and str(l2["vni"]) in config["nve"]["l2vnis"]
            )
            if config_ok and l2.get("svi"):
                observed_svi = config["svis"].get(str(l2["vlan"]), {})
                config_ok = (
                    observed_svi.get("vrf") == l2.get("vrf")
                    and _svi_matches(observed_svi, l2["svi"])
                )
            checks.append(
                _check(
                    "configuration",
                    host,
                    f"l2vni/{l2['vni']}",
                    "PASS" if config_ok else "FAIL",
                    "L2VNI configuration matches the ChangeSet"
                    if config_ok
                    else "L2VNI configuration is missing or inconsistent",
                    _evidence(after, host, "running_config"),
                )
            )
            observed = operational.get(str(l2["vni"]))
            op_ok = bool(
                observed
                and observed.get("type") == "L2"
                and observed.get("context") == str(l2["vlan"])
                and observed.get("state", "").lower() == "up"
            )
            checks.append(
                _check(
                    "operational",
                    host,
                    f"l2vni/{l2['vni']}",
                    "PASS" if op_ok else ("UNKNOWN" if observed is None else "FAIL"),
                    "L2VNI is operationally Up with the expected BD"
                    if op_ok
                    else "L2VNI operational state is unavailable or inconsistent",
                    _evidence(after, host, "nve_vni"),
                )
            )
            if l2_placements[l2["vni"]] > 1:
                replication = (
                    profile.get("ingress_replication", {})
                    .get("vnis", {})
                    .get(str(l2["vni"]))
                )
                secondary_addresses = [
                    after["hosts"][target_host]
                    .get("profiles", {})
                    .get("nxos-overlay", {})
                    .get("nve_interface", {})
                    .get("secondary_address")
                    for target_host in l2_target_hosts[l2["vni"]]
                ]
                shared_vpc_vtep = bool(
                    secondary_addresses
                    and all(secondary_addresses)
                    and len(set(secondary_addresses)) == 1
                )
                checks.append(
                    _check(
                        "operational",
                        host,
                        f"l2vni/{l2['vni']}/remote-vtep",
                        (
                            "PASS"
                            if replication or shared_vpc_vtep
                            else "UNKNOWN"
                        ),
                        (
                            "Remote VTEP replication evidence was observed"
                            if replication
                            else (
                                "Target pair shares one vPC secondary VTEP; "
                                "remote replication between peers is not "
                                "required"
                                if shared_vpc_vtep
                                else "Remote VTEP evidence is required for "
                                "a multi-VTEP L2VNI"
                            )
                        ),
                        _evidence(
                            after,
                            host,
                            "nve_vni_ingress_replication",
                        ),
                    )
                )
        for l3 in resources["l3vnis"]:
            vrf = config["vrfs"].get(l3["vrf"])
            config_ok = bool(
                vrf
                and vrf.get("l3vni") == l3["vni"]
                and str(l3["vni"]) in config["nve"]["l3vnis"]
            )
            checks.append(
                _check(
                    "configuration",
                    host,
                    f"l3vni/{l3['vni']}",
                    "PASS" if config_ok else "FAIL",
                    "L3VNI configuration matches the ChangeSet"
                    if config_ok
                    else "L3VNI configuration is missing or inconsistent",
                    _evidence(after, host, "running_config"),
                )
            )
            observed = operational.get(str(l3["vni"]))
            op_ok = bool(
                observed
                and observed.get("type") == "L3"
                and observed.get("context") == l3["vrf"]
                and observed.get("state", "").lower() == "up"
            )
            checks.append(
                _check(
                    "operational",
                    host,
                    f"l3vni/{l3['vni']}",
                    "PASS" if op_ok else ("UNKNOWN" if observed is None else "FAIL"),
                    "L3VNI is operationally Up with the expected VRF"
                    if op_ok
                    else "L3VNI operational state is unavailable or inconsistent",
                    _evidence(after, host, "nve_vni"),
                )
            )
        checks.extend(_impact_checks(before, after, host))

    sections = {
        section: _result([item for item in checks if item["section"] == section])
        for section in ("configuration", "operational", "impact")
    }
    common_result = _result(checks)
    warnings = list(change_set.get("status", {}).get("warnings", []))
    conflicts = list(change_set.get("status", {}).get("conflicts", []))
    source = change_set["metadata"]["source"]
    if conflicts:
        overall = "PLAN_ERROR"
    elif common_result in {"FAIL", "PLAN_ERROR"}:
        overall = "FAIL"
    elif common_result == "UNKNOWN":
        overall = "UNKNOWN"
    elif common_result == "WARN" or warnings:
        overall = "WARN"
    else:
        overall = "OBSERVED_HEALTHY" if source == "discovered" else "VERIFIED"
    result = {
        "schema_version": SCHEMA_VERSION,
        "change_id": before["change_id"],
        "source": source,
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "result": overall,
        "sections": sections,
        "counts": {
            value.lower(): sum(1 for item in checks if item["result"] == value)
            for value in ("PASS", "WARN", "FAIL", "UNKNOWN", "NOT_APPLICABLE", "PLAN_ERROR")
        },
        "checks": checks,
        "warnings": warnings,
        "conflicts": conflicts,
        "convergence": None,
    }
    validate_document(result, kind="OverlayHealthResult")
    return result


def assess_overlay_convergence(
    attempts: Sequence[Mapping[str, Any]],
    *,
    consecutive_passes: int = 2,
) -> dict[str, Any]:
    """Assess saved attempts without sleeping or collecting from devices."""
    if consecutive_passes < 1:
        raise ValueError("consecutive_passes must be at least 1")
    consecutive = 0
    achieved_at: int | None = None
    records = []
    for index, result in enumerate(attempts, start=1):
        healthy = result["result"] in {"VERIFIED", "OBSERVED_HEALTHY"}
        consecutive = consecutive + 1 if healthy else 0
        records.append(
            {
                "attempt": index,
                "result": result["result"],
                "consecutive_passes": consecutive,
            }
        )
        if consecutive >= consecutive_passes and achieved_at is None:
            achieved_at = index
    return {
        "required_consecutive_passes": consecutive_passes,
        "converged": achieved_at is not None,
        "converged_at_attempt": achieved_at,
        "attempts": records,
    }
