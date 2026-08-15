#!/usr/bin/env python3
"""Regenerate single-site Network Operations and Overlay ChangeSet examples."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from alred.health.evaluator import evaluate_snapshot
from alred.health.overlay import parse_overlay_running_config
from alred.health.profile import resolve_profiles
from alred.health.report import render_health_checklist
from alred.health.roles import (
    load_role_config,
    resolve_role_policy,
)
from alred.health.vni_map import (
    build_overlay_state,
    compare_overlay_states,
    overlay_diff_csv,
    overlay_state_csv,
    overlay_state_legacy_gateway_csv,
    render_overlay_diff_markdown,
    render_overlay_state_legacy_gateway_markdown,
    render_overlay_state_markdown,
)
from alred.overlay_render import render_changeset
from alred.schema import canonical_sha256, validate_document


CHANGE_ID = "CHG-2026-00123"
BEFORE_TIME = datetime.fromisoformat("2026-08-16T10:00:00+09:00")
AFTER_TIME = datetime.fromisoformat("2026-08-16T10:15:00+09:00")
L2VNI = 10100


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    validate_document(value, kind=str(value["kind"]))
    _write_text(
        path,
        yaml.safe_dump(
            dict(value),
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        ),
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _groups() -> dict[str, dict[str, list[str]]]:
    return {
        "adc-vpc-pair-01": {
            "devices": ["adc-lfsw0101", "adc-lfsw0102"],
        },
        "adc-vpc-pair-02": {
            "devices": ["adc-lfsw0103", "adc-lfsw0104"],
        },
        "adc-all-vtep-leafs": {
            "groups": ["adc-vpc-pair-01", "adc-vpc-pair-02"],
        },
    }


def _l2vni(*, minimal: bool) -> dict[str, Any]:
    svi: dict[str, Any] = {
        "ipv4_addresses": ["172.16.0.254/24"],
        "ipv6_addresses": ["fd21:0:0:1::1/64"],
    }
    if not minimal:
        svi.update(
            {
                "mtu": 9216,
                "ipv6_link_local": "fe80::1",
                "ipv6_nd_suppress_ra": True,
                "gateway_mode": "anycast",
            }
        )
    return {
        "vni": L2VNI,
        "default_vlan": 100,
        "vlan_name": "tenant1-vpc1-server-seg1",
        "vrf": "tenant1-vpc1",
        "l3vni": 19001,
        "svi": svi,
        "targets": {
            "groups": {
                "adc-vpc-pair-01": {},
                "adc-vpc-pair-02": {"vlan": 10},
            }
        },
    }


def _changeset(*, inline: bool, minimal: bool = False) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "l2vnis": [_l2vni(minimal=minimal)],
        "l3vnis": [],
    }
    if inline:
        spec["device_groups"] = _groups()
    else:
        spec["device_groups_ref"] = {"path": "./device-groups.fabric.yaml"}
    return {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {"change_id": CHANGE_ID, "source": "declared"},
        "spec": spec,
    }


def _group_document() -> dict[str, Any]:
    return {
        "api_version": "alred/v1",
        "kind": "OverlayDeviceGroups",
        "metadata": {"name": "adc-single-site-fabric"},
        "spec": {"device_groups": _groups()},
    }


def _remove_l2vni(config: dict[str, Any]) -> None:
    for vlan in [
        vlan
        for vlan, value in config.get("vlans", {}).items()
        if value.get("vni") == L2VNI
    ]:
        config["vlans"].pop(vlan, None)
        config.get("svis", {}).pop(vlan, None)
    config.get("nve", {}).get("l2vnis", {}).pop(str(L2VNI), None)


def _all_prefixes(configs: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for config in configs.values():
        l3_vrfs = {
            name
            for name, value in config.get("vrfs", {}).items()
            if value.get("l3vni") is not None
        }
        for svi in config.get("svis", {}).values():
            vrf = str(svi.get("vrf", ""))
            if vrf not in l3_vrfs:
                continue
            for address in [
                *svi.get("ipv4_addresses", []),
                *svi.get("ipv6_addresses", []),
            ]:
                values.add(
                    (vrf, str(ipaddress.ip_interface(address).network))
                )
    return sorted(values)


def _common(host: str, created_at: datetime) -> dict[str, Any]:
    is_leaf = "-lfsw" in host
    return {
        "system": {
            "platform": "nxos",
            "version": "10.5(4)",
            "model": "Nexus9000 C9300v",
            "uptime_seconds": 864000,
        },
        "cpu": {
            "five_seconds_percent": 18,
            "interrupt_percent": 1,
            "one_minute_percent": 24,
            "five_minutes_percent": 22,
        },
        "resources": {"memory": {"used_percent": 44}},
        "environment": {
            "applicable": False,
            "healthy": True,
            "alarms": [],
        },
        "clock": {
            "timestamp": created_at.isoformat(),
            "timezone": "Asia/Tokyo",
        },
        "ntp": {
            "configured": True,
            "synchronized": True,
            "peers": {"192.168.129.254": {"selected": True, "marker": "*"}},
        },
        "interfaces": {
            "mgmt0": {
                "admin_state": "up",
                "operational_state": "up",
                "status": "connected",
            },
            "Eth1/1": {
                "admin_state": "up",
                "operational_state": "up",
                "status": "connected",
            },
        },
        "interface_errors": {},
        "port_channels": (
            {
                "applicable": True,
                "channels": {
                    "Po1": {
                        "up": True,
                        "bundled_members": ["Eth1/1"],
                        "member_check_applicable": True,
                    }
                },
            }
            if is_leaf
            else {"applicable": False, "channels": {}}
        ),
        "reload_pending": {"required": False, "commands": []},
        "running_config_diff": {
            "different": False,
            "line_count": 0,
            "output_sha256": "0" * 64,
        },
        "logging": {"records": [], "parse_warnings": []},
        "routes": {
            "ipv4_summary": {
                "vrfs": {
                    "default": {"routes": 24, "paths": 24},
                    "tenant1-vpc1": {"routes": 12, "paths": 12},
                    "tenant2-vpc1": {"routes": 8, "paths": 8},
                }
            }
        },
        "routing_neighbors": {
            "ospf": {
                "applicable": True,
                "processes": {
                    "UNDERLAY@default": {
                        "neighbors": {
                            "10.0.0.1": {"state": "FULL"},
                        }
                    }
                },
            },
            "bgp_ipv4": {
                "applicable": True,
                "vrfs": {
                    "default": {
                        "configured_peers": 1,
                        "neighbors": {
                            "10.0.0.1": {"state": "Established"},
                        },
                    }
                },
            },
        },
        "vpc": (
            {"applicable": True, "healthy": True}
            if is_leaf
            else {"applicable": False}
        ),
    }


def _nve_identity(host: str) -> tuple[str, str]:
    number = int(host[-2:])
    pair = 1 if number <= 2 else 2
    return f"10.0.1.{number}", f"10.0.2.{pair}"


def _overlay_profile(
    host: str,
    config: Mapping[str, Any],
    prefixes: list[tuple[str, str]],
) -> dict[str, Any]:
    value: dict[str, Any] = {"config": deepcopy(dict(config))}
    is_leaf = "-lfsw" in host
    is_spine = "-spsw" in host
    if not (is_leaf or is_spine):
        return value

    routes = [
        {
            "route_type": 5,
            "prefix": prefix,
            "local": is_leaf,
            "next_hop": "10.0.2.1",
        }
        for _vrf, prefix in prefixes
    ]
    value["evpn_bgp"] = {
        "applicable": True,
        "neighbors": {
            (
                f"10.0.0.{index}"
                if is_leaf
                else f"10.0.1.{index}"
            ): {"state": "Established"}
            for index in (1, 2)
        },
    }
    value["evpn_routes"] = {
        "applicable": True,
        "route_count": len(routes),
        "routes": routes,
    }
    value["vrf_routes"] = {
        family: {
            "routes": [
                {"vrf": vrf, "prefix": prefix}
                for vrf, prefix in prefixes
                if (":" in prefix) == (family == "ipv6")
            ]
        }
        for family in ("ipv4", "ipv6")
    }
    if not is_leaf:
        return value

    primary, secondary = _nve_identity(host)
    value.update(
        {
            "nve_interface": {
                "applicable": True,
                "name": "nve1",
                "state": "Up",
                "primary_address": primary,
                "secondary_address": secondary,
            },
            "nve_peers": {
                "applicable": True,
                "peers": {
                    "10.0.2.1": {"state": "Up"},
                    "10.0.2.2": {"state": "Up"},
                },
            },
            "nve_vnis": {
                "applicable": True,
                "vnis": {
                    **{
                        str(vni): {
                            "type": "L2",
                            "state": "Up",
                            "replication": "UnicastBGP",
                        }
                        for vni in config.get("nve", {}).get("l2vnis", {})
                    },
                    **{
                        str(vni): {"type": "L3", "state": "Up"}
                        for vni in config.get("nve", {}).get("l3vnis", {})
                    },
                },
            },
            "vlans": {
                "vlans": {
                    str(vlan): {"status": "active"}
                    for vlan in config.get("vlans", {})
                }
            },
            "vrfs": {
                "vrfs": {
                    str(vrf): {"state": "Up"}
                    for vrf in config.get("vrfs", {})
                }
            },
            "svis": {
                "interfaces": {
                    f"Vlan{vlan}": {
                        "admin_state": "up",
                        "operational_state": "up",
                    }
                    for vlan in config.get("svis", {})
                }
            },
        }
    )
    return value


def _sources(
    resolved: Mapping[str, Any],
    host: str,
    phase: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    commands = resolved["spec"]["resolved"]["effective"]["spec"]["collectors"][
        "nxos"
    ]["commands"]
    result: dict[str, Any] = {}
    config_hash = canonical_sha256(config).removeprefix("sha256:")
    for item in commands:
        identifier = str(item["id"])
        result[identifier] = {
            "status": "success",
            "parse_status": "parsed",
            "command": item["command"],
            "file": (
                f"synthetic/{phase}/{host}/running_config.txt"
                if identifier == "running_config"
                else f"synthetic/{phase}/{host}/{identifier}.txt"
            ),
            "sha256": (
                config_hash
                if identifier == "running_config"
                else _digest(f"{phase}:{host}:{identifier}")
            ),
        }
    return result


def _snapshot(
    *,
    phase: str,
    created_at: datetime,
    resolved: Mapping[str, Any],
    configs: Mapping[str, Mapping[str, Any]],
    addresses: Mapping[str, str],
) -> dict[str, Any]:
    prefixes = _all_prefixes(configs)
    return {
        "schema_version": 1,
        "change_id": CHANGE_ID,
        "collection_id": f"{CHANGE_ID}-{phase}",
        "phase": phase,
        "created_at": created_at.isoformat(),
        "timezone": "Asia/Tokyo",
        "parser_versions": {"nxos": "1.1"},
        "profile_sha256": resolved["spec"]["resolved"]["effective_sha256"],
        "hosts": {
            host: {
                "address": addresses[host],
                "collection_status": "success",
                "common": _common(host, created_at),
                "profiles": {
                    "nxos-overlay": _overlay_profile(
                        host,
                        configs[host],
                        prefixes,
                    )
                },
                "sources": _sources(
                    resolved,
                    host,
                    phase,
                    configs[host],
                ),
                "parse_warnings": [],
            }
            for host in sorted(configs)
        },
    }


def _load_inputs(repo_root: Path) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    Path,
]:
    sample = (
        repo_root
        / "docs/manual/containerlab/examples/single-site-fabric"
    )
    configs = {
        path.stem.removesuffix("_run"): parse_overlay_running_config(
            path.read_text(encoding="utf-8")
        )
        for path in sorted((sample / "labconfig").glob("*_run.txt"))
    }
    inventory = yaml.safe_load(
        (sample / "hosts.lab.example.yaml").read_text(encoding="utf-8")
    )
    addresses = {
        host: str(values["ansible_host"])
        for host, values in inventory["all"]["hosts"].items()
    }
    return configs, addresses, sample / "roles.example.yaml"


def generate(
    repo_root: Path,
    *,
    network_output: Path | None = None,
    changeset_output: Path | None = None,
) -> list[Path]:
    repo_root = repo_root.resolve()
    network_output = network_output or (
        repo_root / "docs/manual/network-ops/examples/nxos-overlay"
    )
    changeset_output = changeset_output or (
        repo_root / "docs/manual/network-ops/examples/overlay-changeset"
    )
    configs_after, addresses, roles_path = _load_inputs(repo_root)
    configs_before = deepcopy(configs_after)
    for host in configs_before:
        if "-lfsw" in host:
            _remove_l2vni(configs_before[host])

    resolved = resolve_profiles(
        ["network-baseline-nxos", "nxos-overlay"],
        change_id=CHANGE_ID,
        resolved_at=BEFORE_TIME,
        timezone="Asia/Tokyo",
    )
    role_config, role_source = load_role_config(roles_path)
    roles = resolve_role_policy(
        role_config,
        configs_after,
        change_id=CHANGE_ID,
        resolved_at=BEFORE_TIME.isoformat(),
        timezone="Asia/Tokyo",
        source_path=role_source,
    )
    before = _snapshot(
        phase="before",
        created_at=BEFORE_TIME,
        resolved=resolved,
        configs=configs_before,
        addresses=addresses,
    )
    after = _snapshot(
        phase="after",
        created_at=AFTER_TIME,
        resolved=resolved,
        configs=configs_after,
        addresses=addresses,
    )
    before_result = evaluate_snapshot(
        before,
        resolved,
        started_at=BEFORE_TIME,
        completed_at=BEFORE_TIME + timedelta(seconds=31),
        resolved_roles=roles,
    )
    after_result = evaluate_snapshot(
        after,
        resolved,
        started_at=AFTER_TIME,
        completed_at=AFTER_TIME + timedelta(seconds=31),
        resolved_roles=roles,
    )
    before_state = build_overlay_state(before)
    after_state = build_overlay_state(after)
    diff = compare_overlay_states(before_state, after_state)

    generated: list[Path] = []

    def write(path: Path, value: str) -> None:
        _write_text(path, value)
        generated.append(path)

    write(
        network_output / "before-checklist.md",
        render_health_checklist(before_result),
    )
    write(
        network_output / "after-checklist.md",
        render_health_checklist(after_result),
    )
    for phase, state in (("before", before_state), ("after", after_state)):
        path = network_output / f"{phase}-overlay-state.yaml"
        _write_yaml(path, state)
        generated.append(path)
        write(
            network_output / f"{phase}-vni-map.md",
            render_overlay_state_markdown(state),
        )
        write(
            network_output / f"{phase}-vni-map.csv",
            overlay_state_csv(state),
        )
        write(
            network_output / f"{phase}-vni_gateway_map.md",
            render_overlay_state_legacy_gateway_markdown(state),
        )
        write(
            network_output / f"{phase}-vni_gateway_map.csv",
            overlay_state_legacy_gateway_csv(state),
        )
    path = network_output / "vni-map-diff.json"
    _write_json(path, diff)
    generated.append(path)
    write(
        network_output / "vni-map-diff.md",
        render_overlay_diff_markdown(diff),
    )
    write(network_output / "vni-map-diff.csv", overlay_diff_csv(diff))

    standard = _changeset(inline=False)
    minimal = _changeset(inline=False, minimal=True)
    inline = _changeset(inline=True)
    groups = _group_document()
    for name, document in (
        ("desired-changes.yaml", standard),
        ("desired-changes.minimal.yaml", minimal),
        ("desired-changes.inline.yaml", inline),
        ("device-groups.fabric.yaml", groups),
    ):
        path = changeset_output / name
        _write_yaml(path, document)
        generated.append(path)
    rendered = render_changeset(inline, before)
    for host in ("adc-lfsw0101", "adc-lfsw0103"):
        write(changeset_output / f"{host}.cfg", rendered[host].forward_config)
        write(
            changeset_output / f"{host}-rollback.cfg",
            rendered[host].rollback_config,
        )
    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    for path in generate(args.repo_root):
        print(path.relative_to(args.repo_root.resolve()))


if __name__ == "__main__":
    main()
