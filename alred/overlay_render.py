"""Canonical Overlay ChangeSet resolution and deterministic NX-OS rendering."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from ipaddress import ip_address, ip_interface
from pathlib import Path
import re
from typing import Any, Mapping

from .operation import atomic_write_bytes, atomic_write_json
from .schema import canonical_sha256, validate_document
from .device_groups import (
    DeviceGroupError,
    DeviceGroupResolution,
    resolve_device_groups,
    resolve_resource_targets,
)
from .templates import render_named_template_lines


RENDERER_VERSION = "1.0"
FORWARD_TEMPLATE = "nxos_overlay_forward_config.j2"
ROLLBACK_TEMPLATE = "nxos_overlay_rollback_config.j2"
SUPPORTED_MODELS = {
    "N9K-C9300V",
    "N9K-C9336C-FX2",
    "N9K-C93180YC-FX3",
    "N9K-C9348GC-FX3",
    "N9K-C9364C-H1",
}


def normalize_nxos_model(value: Any) -> str:
    """Normalize known show-version and inventory spellings."""
    model = " ".join(str(value or "").upper().split())
    if model.startswith("NEXUS9000 C"):
        model = "N9K-" + model.removeprefix("NEXUS9000 ")
    return model


class OverlayRenderError(ValueError):
    """Raised when a ChangeSet cannot be rendered safely."""

    code = "PLAN_ERROR"


@dataclass(frozen=True)
class RenderedDevice:
    """One immutable device rendering result."""

    device: str
    model: dict[str, Any]
    forward_config: str
    rollback_config: str
    forward_sha256: str
    rollback_sha256: str
    model_sha256: str
    actions: tuple[dict[str, Any], ...]


def _legacy_record_sort(record: Mapping[str, str]) -> tuple[Any, ...]:
    def numeric(value: str) -> tuple[int, Any]:
        return (0, int(value)) if value.isdigit() else (1, value)

    return (
        record.get("device", ""),
        numeric(record.get("vlan", "")),
        numeric(record.get("l2vni", "")),
        record.get("vrf", ""),
    )


def adapt_legacy_vni_add_records(
    records: list[dict[str, str]],
    existing_before_records: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Adapt the stable CSV contract to the shared renderer boundary."""
    sorted_records = sorted(records, key=_legacy_record_sort)
    existing = existing_before_records or []
    existing_l3 = {
        (item.get("vrf", ""), item.get("l3vni", "")) for item in existing
    }
    existing_l2 = {item.get("l2vni", "") for item in existing}
    l3vnis = []
    nve_l3vnis = []
    emitted_l3: set[tuple[str, str]] = set()
    for item in sorted_records:
        key = (item.get("vrf", ""), item.get("l3vni", ""))
        if all(key) and key not in existing_l3 and key not in emitted_l3:
            l3vnis.append({"vrf": key[0], "l3vni": key[1]})
            nve_l3vnis.append(key[1])
            emitted_l3.add(key)
    evpn_l2vnis = []
    emitted_l2: set[str] = set()
    for item in sorted_records:
        vni = item.get("l2vni", "")
        if vni and vni not in existing_l2 and vni not in emitted_l2:
            evpn_l2vnis.append(vni)
            emitted_l2.add(vni)
    return {
        "adapter": "vni_gateway_csv",
        "rendering_policy": "legacy_compatible",
        "template": "vni_add_config.j2",
        "context": {
            "l3vnis": l3vnis,
            "evpn_l2vnis": evpn_l2vnis,
            "vlans": sorted_records,
            "svis": sorted_records,
            "nve_members": [
                item.get("l2vni", "")
                for item in sorted_records
                if item.get("l2vni", "")
            ],
            "nve_l3vnis": nve_l3vnis,
        },
    }


def adapt_legacy_vni_delete_records(
    records: list[dict[str, str]],
    remaining_after_records: list[dict[str, str]],
) -> dict[str, Any]:
    """Adapt legacy delete records without changing their output contract."""
    sorted_records = sorted(records, key=_legacy_record_sort)
    remaining_l3 = {
        (item.get("vrf", ""), item.get("l3vni", ""))
        for item in remaining_after_records
    }
    remaining_l2 = {
        item.get("l2vni", "")
        for item in remaining_after_records
        if item.get("l2vni", "")
    }
    l3vnis = []
    emitted_l3: set[tuple[str, str]] = set()
    evpn_l2vnis = []
    emitted_l2: set[str] = set()
    for item in sorted_records:
        vni = item.get("l2vni", "")
        if vni and vni not in remaining_l2 and vni not in emitted_l2:
            evpn_l2vnis.append(vni)
            emitted_l2.add(vni)
    for item in sorted_records:
        key = (item.get("vrf", ""), item.get("l3vni", ""))
        if all(key) and key not in remaining_l3 and key not in emitted_l3:
            l3vnis.append({"vrf": key[0], "l3vni": key[1]})
            emitted_l3.add(key)
    return {
        "adapter": "vni_gateway_csv",
        "rendering_policy": "legacy_compatible",
        "template": "vni_delete_config.j2",
        "context": {
            "nve_members": [
                item.get("l2vni", "")
                for item in sorted_records
                if item.get("l2vni", "")
            ],
            "evpn_l2vnis": evpn_l2vnis,
            "vlans": [
                item.get("vlan", "")
                for item in sorted_records
                if item.get("vlan", "")
            ],
            "l3vnis": l3vnis,
        },
    }


def render_canonical_overlay_model(model: Mapping[str, Any]) -> list[str]:
    """Render any supported adapter model through the package template loader."""
    return render_named_template_lines(model["template"], model["context"])


def _targets(
    resource: Mapping[str, Any],
    groups: DeviceGroupResolution,
) -> dict[str, dict[str, Any]]:
    try:
        resolved, _evidence = resolve_resource_targets(resource, groups)
        return resolved
    except DeviceGroupError as exc:
        raise OverlayRenderError(str(exc)) from exc


def _resolved_af(
    l3: Mapping[str, Any],
    related_l2: list[Mapping[str, Any]],
) -> dict[str, Any]:
    requested = deepcopy(l3.get("address_families", {}))
    if not requested:
        if any(item.get("svi", {}).get("ipv4_addresses") for item in related_l2):
            requested["ipv4"] = {}
        if any(item.get("svi", {}).get("ipv6_addresses") for item in related_l2):
            requested["ipv6"] = {}
    if not requested:
        raise OverlayRenderError(
            f"L3VNI {l3['vni']} address families cannot be derived"
        )
    result: dict[str, Any] = {}
    for af, values in requested.items():
        direct = values.get("redistribute_direct", {})
        static = values.get("redistribute_static", {})
        if (
            values.get("advertise_l2vpn_evpn", True) is not True
            or direct.get("enabled", True) is not True
            or static.get("enabled", True) is not True
        ):
            raise OverlayRenderError(
                f"L3VNI {l3['vni']} disabling BGP advertisement is unsupported"
            )
        default_map = (
            "IPv4_REDISTRIBUTE_ALL"
            if af == "ipv4"
            else "IPv6_REDISTRIBUTE_ALL"
        )
        result[af] = {
            "advertise_l2vpn_evpn": True,
            "redistribute_direct_route_map": direct.get(
                "route_map", default_map
            ),
            "redistribute_static_route_map": static.get(
                "route_map", default_map
            ),
            "maximum_paths_ibgp": values.get("maximum_paths_ibgp", 4),
        }
    return result


def _validate_svi(svi: Mapping[str, Any], vni: int) -> dict[str, Any]:
    result = deepcopy(dict(svi))
    ipv4 = result.get("ipv4_addresses", [])
    ipv6 = result.get("ipv6_addresses", [])
    if not ipv4 and not ipv6:
        raise OverlayRenderError(f"L2VNI {vni} SVI requires IPv4 or IPv6")
    for field, addresses, version in (
        ("ipv4_addresses", ipv4, 4),
        ("ipv6_addresses", ipv6, 6),
    ):
        for value in addresses:
            try:
                address = ip_interface(value)
            except ValueError as exc:
                raise OverlayRenderError(
                    f"L2VNI {vni} has invalid {field} value {value!r}"
                ) from exc
            if address.version != version:
                raise OverlayRenderError(
                    f"L2VNI {vni} {field} has the wrong address family"
                )
    result["mtu"] = result.get("mtu", 9216)
    if ipv6:
        link_local = result.get("ipv6_link_local", "fe80::1")
        try:
            address = ip_address(link_local)
        except ValueError as exc:
            raise OverlayRenderError(
                f"L2VNI {vni} has invalid IPv6 link-local address"
            ) from exc
        if address.version != 6 or not address.is_link_local:
            raise OverlayRenderError(
                f"L2VNI {vni} IPv6 link-local must be in fe80::/10"
            )
        result["ipv6_link_local"] = link_local
        result["ipv6_nd_suppress_ra"] = result.get(
            "ipv6_nd_suppress_ra", True
        )
    elif any(
        key in result
        for key in ("ipv6_link_local", "ipv6_nd_suppress_ra")
    ):
        raise OverlayRenderError(
            f"L2VNI {vni} IPv4-only SVI cannot set IPv6-specific options"
        )
    result["gateway_mode"] = result.get("gateway_mode", "anycast")
    return result


def resolve_changeset(
    document: Mapping[str, Any],
    *,
    allow_discovered: bool = False,
    require_bgp_address_families: bool = True,
) -> dict[str, dict[str, Any]]:
    """Resolve group/default/device values into a per-device render model."""
    validate_document(document, kind="OverlayChangeSet")
    if document["metadata"]["source"] == "discovered" and not allow_discovered:
        raise OverlayRenderError(
            "discovered ChangeSet must be reviewed and promoted before rendering"
        )
    spec = document["spec"]
    try:
        groups = resolve_device_groups(spec["device_groups"])
    except DeviceGroupError as exc:
        raise OverlayRenderError(str(exc)) from exc
    devices: dict[str, dict[str, Any]] = {}

    def model(host: str) -> dict[str, Any]:
        return devices.setdefault(
            host,
            {"device": host, "l2vnis": [], "l3vnis": []},
        )

    for l2 in spec["l2vnis"]:
        for host, override in _targets(l2, groups).items():
            vlan = override.get("vlan", l2.get("default_vlan"))
            if vlan is None:
                raise OverlayRenderError(
                    f"L2VNI {l2['vni']} has no VLAN for {host}"
                )
            item = {
                key: deepcopy(value)
                for key, value in l2.items()
                if key not in {"default_vlan", "targets", "svi"}
            }
            item["vlan"] = vlan
            if "svi" in l2 and override.get("svi", True):
                item["svi"] = _validate_svi(l2["svi"], l2["vni"])
            model(host)["l2vnis"].append(item)

    for l3 in spec["l3vnis"]:
        mode = l3.get("mode", "new_l3vni")
        for host, override in _targets(l3, groups).items():
            item = deepcopy(dict(l3))
            item.pop("targets", None)
            item["mode"] = mode
            if mode == "new_l3vni":
                if "default_vlan" in item or "vlan" in override or "svi" in item:
                    raise OverlayRenderError(
                        f"new_l3vni {l3['vni']} cannot define VLAN or SVI"
                    )
            else:
                vlan = override.get("vlan", item.pop("default_vlan", None))
                if vlan is None:
                    raise OverlayRenderError(
                        f"traditional L3VNI {l3['vni']} has no VLAN for {host}"
                    )
                item["vlan"] = vlan
                item.setdefault("svi", {})["mtu"] = item.get("svi", {}).get(
                    "mtu", 9216
                )
            related = [
                value
                for value in model(host)["l2vnis"]
                if value.get("l3vni") == l3["vni"]
            ]
            try:
                item["address_families"] = _resolved_af(item, related)
            except OverlayRenderError:
                if require_bgp_address_families:
                    raise
                item["address_families"] = {}
            model(host)["l3vnis"].append(item)

    for host, value in devices.items():
        value["l2vnis"].sort(key=lambda item: (item["vlan"], item["vni"]))
        value["l3vnis"].sort(key=lambda item: (item["vrf"], item["vni"]))
    return dict(sorted(devices.items()))


def _current_states(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    states = {}
    for host, record in snapshot["hosts"].items():
        state = record["profiles"].get("nxos-overlay", {}).get("config")
        if state is not None:
            states[host] = state
    return states


def _validate_capability(host: str, record: Mapping[str, Any]) -> None:
    system = record.get("common", {}).get("system", {})
    if system.get("platform") != "nxos":
        raise OverlayRenderError(f"{host}: NX-OS platform evidence is required")
    model = normalize_nxos_model(system.get("model"))
    if model not in SUPPORTED_MODELS:
        raise OverlayRenderError(f"{host}: unsupported NX-OS model {model!r}")
    version = str(system.get("version", ""))
    match = re.match(r"^(\d+)\.(\d+)\((\d+)\)", version)
    if not match:
        raise OverlayRenderError(
            f"{host}: unrecognized NX-OS version {version!r}"
        )
    if tuple(int(value) for value in match.groups()) < (10, 4, 5):
        raise OverlayRenderError(
            f"{host}: NX-OS {version} is below minimum 10.4(5)M"
        )


def _config_text(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def _text_sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def render_changeset(
    document: Mapping[str, Any],
    before_snapshot: Mapping[str, Any],
) -> dict[str, RenderedDevice]:
    """Render deterministic forward and scoped rollback configuration."""
    if document["metadata"]["change_id"] != before_snapshot["change_id"]:
        raise OverlayRenderError("ChangeSet and before Snapshot change_id mismatch")
    resolved = resolve_changeset(document)
    current_states = _current_states(before_snapshot)
    if set(resolved) - set(current_states):
        missing = ", ".join(sorted(set(resolved) - set(current_states)))
        raise OverlayRenderError(f"before running-config missing for: {missing}")
    results: dict[str, RenderedDevice] = {}
    for host, desired in resolved.items():
        _validate_capability(host, before_snapshot["hosts"][host])
        current = current_states[host]
        if not current["nve"]["global_ingress_replication_protocol_bgp"]:
            raise OverlayRenderError(
                f"{host}: global ingress-replication protocol bgp is missing"
            )
        bgp_processes = current.get("bgp_processes", {})
        if len(bgp_processes) != 1:
            raise OverlayRenderError(
                f"{host}: exactly one existing BGP process is required"
            )
        local_as = next(iter(bgp_processes))
        required_maps = {
            values[key]
            for l3 in desired["l3vnis"]
            for values in l3["address_families"].values()
            for key in (
                "redistribute_direct_route_map",
                "redistribute_static_route_map",
            )
        }
        missing_maps = required_maps - set(current.get("route_maps", []))
        if missing_maps:
            raise OverlayRenderError(
                f"{host}: route-map prerequisites missing: "
                + ", ".join(sorted(missing_maps))
            )

        actions: list[dict[str, Any]] = []
        for l2 in desired["l2vnis"]:
            existing_vlan = current["vlans"].get(str(l2["vlan"]))
            existing_vni_vlans = [
                vlan
                for vlan, data in current["vlans"].items()
                if data.get("vni") == l2["vni"]
            ]
            if existing_vni_vlans and str(l2["vlan"]) not in existing_vni_vlans:
                raise OverlayRenderError(
                    f"{host}: L2VNI {l2['vni']} is mapped to another VLAN"
                )
            if existing_vlan and existing_vlan.get("vni") not in (None, l2["vni"]):
                raise OverlayRenderError(
                    f"{host}: VLAN {l2['vlan']} has a conflicting VNI"
                )
            if (
                existing_vlan
                and l2.get("vlan_name")
                and existing_vlan.get("name") not in (None, l2["vlan_name"])
            ):
                raise OverlayRenderError(
                    f"{host}: VLAN {l2['vlan']} has a conflicting name"
                )
            desired_svi = l2.get("svi")
            existing_svi = current["svis"].get(str(l2["vlan"]))
            if existing_svi is not None and desired_svi is not None:
                expected = {
                    "mtu": desired_svi["mtu"],
                    "ipv4_addresses": desired_svi.get("ipv4_addresses", []),
                    "ipv6_addresses": desired_svi.get("ipv6_addresses", []),
                    "anycast_gateway": True,
                }
                if desired_svi.get("ipv6_addresses"):
                    expected["ipv6_link_local"] = desired_svi["ipv6_link_local"]
                    expected["ipv6_nd_suppress_ra"] = desired_svi[
                        "ipv6_nd_suppress_ra"
                    ]
                if l2.get("vrf"):
                    expected["vrf"] = l2["vrf"]
                if any(existing_svi.get(key) != value for key, value in expected.items()):
                    raise OverlayRenderError(
                        f"{host}: existing SVI Vlan{l2['vlan']} is only "
                        "partially compatible"
                    )
            l2["_ownership"] = {
                "vlan_new": existing_vlan is None,
                "vlan_mapping_new": bool(
                    existing_vlan is not None
                    and existing_vlan.get("vni") is None
                ),
                "vlan_name_new": bool(
                    existing_vlan is not None
                    and l2.get("vlan_name")
                    and existing_vlan.get("name") is None
                ),
                "svi_new": existing_svi is None and desired_svi is not None,
                "nve_new": str(l2["vni"]) not in current["nve"]["l2vnis"],
                "evpn_new": str(l2["vni"]) not in current.get(
                    "evpn_l2vnis", {}
                ),
            }
            actions.append(
                {
                    "resource": f"l2vni/{l2['vni']}",
                    "action": (
                        "create"
                        if any(l2["_ownership"].values())
                        else "preserve"
                    ),
                }
            )
        for l3 in desired["l3vnis"]:
            existing_vrf = current["vrfs"].get(l3["vrf"])
            if existing_vrf and existing_vrf.get("l3vni") not in (
                None,
                l3["vni"],
            ):
                raise OverlayRenderError(
                    f"{host}: VRF {l3['vrf']} has a conflicting L3VNI"
                )
            bgp_vrfs = bgp_processes[local_as]["vrfs"]
            vrf_af_added: dict[str, list[str]] = {}
            for af in l3["address_families"]:
                desired_rt = [
                    "route-target both auto",
                    "route-target both auto evpn",
                ]
                existing_rt = (
                    (existing_vrf or {})
                    .get("address_families", {})
                    .get(af, {})
                    .get("commands", [])
                )
                vrf_af_added[af] = [
                    command for command in desired_rt if command not in existing_rt
                ]
            current_bgp_vrf = bgp_vrfs.get(l3["vrf"], {})
            bgp_added: dict[str, list[str]] = {}
            for af, values in l3["address_families"].items():
                desired_commands = [
                    "advertise l2vpn evpn",
                    "redistribute direct route-map "
                    + values["redistribute_direct_route_map"],
                    "redistribute static route-map "
                    + values["redistribute_static_route_map"],
                    f"maximum-paths ibgp {values['maximum_paths_ibgp']}",
                ]
                existing_commands = (
                    current_bgp_vrf.get("address_families", {})
                    .get(af, {})
                    .get("commands", [])
                )
                conflicting = [
                    command
                    for command in existing_commands
                    if (
                        command.startswith("redistribute direct ")
                        or command.startswith("redistribute static ")
                        or command.startswith("maximum-paths ibgp ")
                    )
                    and command not in desired_commands
                ]
                if conflicting:
                    raise OverlayRenderError(
                        f"{host}: BGP VRF {l3['vrf']} {af} conflicts with "
                        + ", ".join(conflicting)
                    )
                bgp_added[af] = [
                    command
                    for command in desired_commands
                    if command not in existing_commands
                ]
            l3["_ownership"] = {
                "vrf_new": existing_vrf is None,
                "nve_new": str(l3["vni"]) not in current["nve"]["l3vnis"],
                "bgp_vrf_new": l3["vrf"] not in bgp_vrfs,
                "bgp_added": bgp_added,
                "vrf_af_added": vrf_af_added,
            }
            if l3["mode"] == "traditional_vlan_svi":
                existing_vlan = current["vlans"].get(str(l3["vlan"]))
                if existing_vlan and existing_vlan.get("vni") not in (
                    None,
                    l3["vni"],
                ):
                    raise OverlayRenderError(
                        f"{host}: traditional L3VNI VLAN {l3['vlan']} conflicts"
                    )
                existing_svi = current["svis"].get(str(l3["vlan"]))
                if existing_svi and not (
                    existing_svi.get("ip_forward")
                    and existing_svi.get("vrf") == l3["vrf"]
                    and existing_svi.get("mtu") == l3["svi"]["mtu"]
                ):
                    raise OverlayRenderError(
                        f"{host}: traditional L3VNI SVI Vlan{l3['vlan']} conflicts"
                    )
                l3["_ownership"].update(
                    {
                        "vlan_new": existing_vlan is None,
                        "vlan_mapping_new": bool(
                            existing_vlan is not None
                            and existing_vlan.get("vni") is None
                        ),
                        "svi_new": existing_svi is None,
                    }
                )
            actions.append(
                {
                    "resource": f"l3vni/{l3['vni']}",
                    "action": (
                        "create"
                        if (
                            l3["_ownership"]["vrf_new"]
                            or l3["_ownership"]["nve_new"]
                            or l3["_ownership"]["bgp_vrf_new"]
                            or any(bgp_added.values())
                            or any(vrf_af_added.values())
                            or any(
                                l3["_ownership"].get(key, False)
                                for key in (
                                    "vlan_new",
                                    "vlan_mapping_new",
                                    "svi_new",
                                )
                            )
                        )
                        else "preserve"
                    ),
                }
            )
        render_model = {
            "change_id": document["metadata"]["change_id"],
            "source": document["metadata"]["source"],
            "device": host,
            "nve_interface": "nve1",
            "local_as": local_as,
            "l2vnis": desired["l2vnis"],
            "l3vnis": desired["l3vnis"],
        }
        no_change = all(action["action"] == "preserve" for action in actions)
        forward_lines = (
            []
            if no_change
            else render_named_template_lines(FORWARD_TEMPLATE, render_model)
        )
        rollback_lines = (
            []
            if no_change
            else render_named_template_lines(ROLLBACK_TEMPLATE, render_model)
        )
        forward = _config_text(forward_lines)
        rollback = _config_text(rollback_lines)
        results[host] = RenderedDevice(
            device=host,
            model=render_model,
            forward_config=forward,
            rollback_config=rollback,
            forward_sha256=_text_sha256(forward),
            rollback_sha256=_text_sha256(rollback),
            model_sha256=canonical_sha256(render_model),
            actions=tuple(actions),
        )
    return results


def write_rendered_configs(
    operation_root: str | Path,
    change_id: str,
    rendered: Mapping[str, RenderedDevice],
    *,
    input_hashes: Mapping[str, str] | None = None,
    artifact_dir: str = "plan",
    config_dir: str = "generated-config",
    rollback_dir: str = "rollback-config",
) -> dict[str, Any]:
    """Atomically save configs and a validated hash/provenance manifest."""
    root = Path(operation_root)
    devices: dict[str, Any] = {}
    for host, result in sorted(rendered.items()):
        forward_relative = f"{config_dir}/{host}.cfg"
        rollback_relative = f"{rollback_dir}/{host}.cfg"
        if result.forward_config:
            atomic_write_bytes(
                root,
                root / forward_relative,
                result.forward_config.encode("utf-8"),
            )
        if result.rollback_config:
            atomic_write_bytes(
                root,
                root / rollback_relative,
                result.rollback_config.encode("utf-8"),
            )
        devices[host] = {
            "forward_config": forward_relative if result.forward_config else "",
            "rollback_config": rollback_relative if result.rollback_config else "",
            "forward_sha256": result.forward_sha256,
            "rollback_sha256": result.rollback_sha256,
            "model_sha256": result.model_sha256,
            "actions": list(result.actions),
        }
    manifest = {
        "schema_version": 1,
        "change_id": change_id,
        "renderer": f"nxos-overlay@{RENDERER_VERSION}",
        "templates": {
            "forward": f"alred/j2/{FORWARD_TEMPLATE}",
            "rollback": f"alred/j2/{ROLLBACK_TEMPLATE}",
        },
        "inputs": dict(sorted((input_hashes or {}).items())),
        "devices": devices,
    }
    atomic_write_json(
        root,
        root / artifact_dir / "render-manifest.json",
        manifest,
        kind="OverlayRenderManifest",
    )
    return manifest
