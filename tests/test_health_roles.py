from __future__ import annotations

from pathlib import Path
from datetime import datetime
from copy import deepcopy

import pytest
import yaml

from alred.health.report import render_health_checklist
from alred.health.evaluator import (
    _build_type5_route_indexes,
    _evaluate_function_expectation,
    _evaluate_type5_prefix_propagation,
    evaluate_snapshot,
)
from alred.health.parsers import parse_nxos_command
from alred.health.profile import resolve_profiles
from alred.health.role_commands import build_role_command_groups
from alred.health.roles import (
    RoleResolutionError,
    load_role_config,
    overlay_profile_scope,
    resolve_role_policy,
)


def _write_roles(path: Path, document: dict) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _resolve(path: Path, hostnames: list[str]) -> dict:
    config, source = load_role_config(path)
    return resolve_role_policy(
        config,
        hostnames,
        change_id="chg-role-test",
        resolved_at="2026-08-08T12:00:00+09:00",
        timezone="Asia/Tokyo",
        source_path=source,
    )


def test_versionless_roles_preserve_legacy_scope(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {"role_detection": {"leaf": {"contains": ["lf"]}}},
    )

    resolved = _resolve(path, ["lf01", "unknown01"])

    assert resolved["spec"]["role_schema_version"] == 1
    assert resolved["spec"]["devices"]["lf01"]["status"] == "legacy"
    assert overlay_profile_scope(resolved, "unknown01")[0] is True


def test_v2_resolves_topology_role_and_nested_functions(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {
            "schema_version": 2,
            "role_detection": {
                "leaf": {
                    "contains": ["lf"],
                    "functions": {
                        "vtep": {"expectation": "required"},
                        "vpc": {"expectation": "optional"},
                    },
                }
            },
            "function_expectation_rules": {
                "vpc": {"required_when": {"contains": ["vpc"]}}
            },
        },
    )

    resolved = _resolve(path, ["lf-vpc01", "lf02"])

    first = resolved["spec"]["devices"]["lf-vpc01"]
    assert first["topology_role"] == "leaf"
    assert first["functions"]["vtep"]["expectation"] == "required"
    assert first["functions"]["vpc"] == {
        "expectation": "required",
        "source": "function_expectation_rule",
    }
    assert resolved["spec"]["devices"]["lf02"]["functions"]["vpc"][
        "expectation"
    ] == "optional"


def test_v2_marks_multiple_topology_matches_as_conflict(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {
            "schema_version": 2,
            "role_detection": {
                "leaf": {"contains": ["node"], "functions": {}},
                "spine": {"contains": ["node"], "functions": {}},
            },
        },
    )

    resolved = _resolve(path, ["node01"])

    device = resolved["spec"]["devices"]["node01"]
    assert device["status"] == "conflict"
    assert device["topology_role"] is None
    assert overlay_profile_scope(resolved, "node01") == (
        False,
        "UNKNOWN",
        "ROLE_CONFLICT",
    )


def test_v2_other_is_unknown_and_server_is_excluded(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {
            "schema_version": 2,
            "role_detection": {
                "server": {"contains": ["srv"], "functions": {}}
            },
        },
    )

    resolved = _resolve(path, ["srv01", "mystery01"])

    assert overlay_profile_scope(resolved, "srv01") == (
        False,
        "NOT_APPLICABLE",
        "PROFILE_ROLE_EXCLUDED",
    )
    assert overlay_profile_scope(resolved, "mystery01") == (
        False,
        "UNKNOWN",
        "TOPOLOGY_ROLE_UNRESOLVED",
    )


def test_unsupported_role_schema_version_is_rejected(tmp_path: Path) -> None:
    path = _write_roles(tmp_path / "roles.yaml", {"schema_version": 3})

    with pytest.raises(RoleResolutionError) as raised:
        load_role_config(path)

    assert raised.value.code == "SCHEMA_UNSUPPORTED"


def test_conflicting_function_expectations_are_rejected(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {
            "schema_version": 2,
            "role_detection": {
                "leaf": {
                    "contains": ["lf"],
                    "functions": {"vpc": {"expectation": "optional"}},
                }
            },
            "function_expectation_rules": {
                "vpc": {
                    "required_when": {"contains": ["lf"]},
                    "forbidden_when": {"contains": ["lf"]},
                }
            },
        },
    )

    with pytest.raises(RoleResolutionError) as raised:
        _resolve(path, ["lf01"])

    assert raised.value.code == "FUNCTION_EXPECTATION_CONFLICT"


def test_checklist_renders_unexecuted_hosts() -> None:
    rendered = render_health_checklist(
        {
            "change_id": "chg-role-test",
            "phase": "before",
            "result": "UNKNOWN",
            "started_at": "2026-08-08T12:00:00+09:00",
            "completed_at": "2026-08-08T12:00:01+09:00",
            "profiles": ["nxos-overlay"],
            "checks": [],
            "unexecuted_hosts": [
                {
                    "host": "unknown01",
                    "platform": "nxos",
                    "topology_role": "other",
                    "profile": "nxos-overlay",
                    "profile_result": "UNKNOWN",
                    "reason_code": "TOPOLOGY_ROLE_UNRESOLVED",
                    "message": "Topology role could not be resolved safely.",
                }
            ],
        }
    )

    assert "## Unexecuted Hosts" in rendered
    assert "| unknown01 | nxos | other | nxos-overlay | UNKNOWN |" in rendered


def test_role_command_groups_collect_only_role_relevant_overlay_commands(
    tmp_path: Path,
) -> None:
    path = Path("alred/sample_configs/roles.example.yaml")
    config, _source = load_role_config(path)
    resolved_profiles = resolve_profiles(
        ["network-baseline-nxos", "nxos-overlay"],
        change_id="chg-role-test",
        resolved_at=datetime.fromisoformat("2026-08-08T12:00:00+09:00"),
        timezone="Asia/Tokyo",
    )

    groups = build_role_command_groups(
        resolved_profiles["spec"]["resolved"]["effective"], config
    )

    assert "show nve interface" in groups["leaf"]
    assert "show vlan brief" in groups["leaf"]
    assert "show vrf" in groups["leaf"]
    assert "show interface brief" in groups["leaf"]
    assert "show nve peers" in groups["border-gateway"]
    assert "show nve interface" not in groups["spine"]
    assert "show vlan brief" not in groups["spine"]
    assert "show bgp l2vpn evpn summary" in groups["spine"]
    assert "show bgp l2vpn evpn" in groups["super-spine"]
    assert groups["network-functions"] == []


def test_running_config_parser_structures_vpc_and_rr_functions() -> None:
    _common, profiles = parse_nxos_command(
        "running_config",
        """feature vpc
vpc domain 10
router bgp 65000
  cluster-id 192.0.2.10
  address-family l2vpn evpn
  neighbor 192.0.2.11
    remote-as 65000
    address-family l2vpn evpn
      route-reflector-client
  neighbor 192.0.2.12
    remote-as 65000
    address-family ipv4 unicast
      route-reflector-client
""",
    )

    config = profiles["nxos-overlay"]["config"]
    assert config["vpc"]["configured"] is True
    assert config["rr_config"]["evpn"]["configured"] is True
    assert config["rr_config"]["evpn"]["neighbors"]["192.0.2.11"][
        "address_families"
    ]["l2vpn-evpn"] == {
        "route_reflector_client": True,
        "source": "direct",
    }
    assert config["rr_config"]["underlay"]["configured"] is True
    assert config["rr_config"]["underlay"]["neighbors"]["192.0.2.12"][
        "address_families"
    ]["ipv4-unicast"] == {
        "route_reflector_client": True,
        "source": "direct",
    }


def test_running_config_parser_resolves_peer_template_dynamic_neighbor() -> None:
    _common, profiles = parse_nxos_command(
        "running_config",
        """router bgp 65001
  router-id 10.0.0.254
  address-family l2vpn evpn
    retain route-target all
  template peer leaf
    remote-as internal
    update-source loopback0
    address-family l2vpn evpn
      send-community
      send-community extended
      route-reflector-client
  neighbor 10.0.0.0/24
    inherit peer leaf
""",
    )

    rr = profiles["nxos-overlay"]["config"]["rr_config"]["evpn"]
    assert rr["configured"] is True
    assert rr["resolution_status"] == "resolved"
    assert rr["neighbors"]["10.0.0.0/24"] == {
        "inherited_peer_templates": ["leaf"],
        "address_families": {
            "l2vpn-evpn": {
                "route_reflector_client": True,
                "source": "template:leaf",
            }
        },
        "resolution_status": "resolved",
    }


def test_running_config_parser_resolves_chained_peer_templates() -> None:
    _common, profiles = parse_nxos_command(
        "running_config",
        """router bgp 65001
  template peer rr-base
    address-family l2vpn evpn
      route-reflector-client
  template peer leaf
    inherit peer rr-base
  neighbor 10.0.0.0/24
    inherit peer leaf
""",
    )

    rr = profiles["nxos-overlay"]["config"]["rr_config"]["evpn"]
    assert rr["configured"] is True
    assert rr["neighbors"]["10.0.0.0/24"]["address_families"][
        "l2vpn-evpn"
    ]["source"] == "template:rr-base"


@pytest.mark.parametrize(
    "template_config,reason",
    [
        ("  neighbor 10.0.0.0/24\n    inherit peer missing\n", "not_found"),
        (
            "  template peer first\n"
            "    inherit peer second\n"
            "  template peer second\n"
            "    inherit peer first\n"
            "  neighbor 10.0.0.0/24\n"
            "    inherit peer first\n",
            "cycle",
        ),
    ],
)
def test_unresolved_peer_template_is_unknown(
    template_config: str, reason: str
) -> None:
    _common, profiles = parse_nxos_command(
        "running_config", "router bgp 65001\n" + template_config
    )
    config = profiles["nxos-overlay"]["config"]
    rr = config["rr_config"]["evpn"]
    assert rr["configured"] is False
    assert rr["resolution_status"] == "unresolved"
    assert any(error["reason"] == reason for error in rr["resolution_errors"])

    check = _evaluate_function_expectation(
        {
            "collection_id": "chg-role-test-before-001",
            "hosts": {
                "spsw0101": {
                    "profiles": {"nxos-overlay": {"config": config}},
                    "sources": {
                        "running_config": {
                            "status": "success",
                            "parse_status": "parsed",
                        }
                    },
                }
            }
        },
        "spsw0101",
        "evpn-route-reflector",
        {"expectation": "required", "source": "topology_role_default"},
    )
    assert check["result"] == "UNKNOWN"
    assert check["after"]["reason_code"] == "RR_TEMPLATE_UNRESOLVED"


def test_nve_peer_and_evpn_route_parsers() -> None:
    _common, peer_profiles = parse_nxos_command(
        "nve_peers",
        """Interface Peer-IP                                 State LearnType Uptime
nve1      192.0.2.21                              Up    CP        1d02h
nve1      192.0.2.22                              Down  CP        00:01:00
""",
    )
    _common, route_profiles = parse_nxos_command(
        "bgp_l2vpn_evpn",
        """Route Distinguisher: 192.0.2.1:32777
*>l[2]:[0]:[0]:[48]:[aabb.ccdd.eeff]:[0]:[0.0.0.0]/216
*>i[3]:[0]:[32]:[192.0.2.1]/88
*>i[5]:[0]:[0]:[24]:[198.51.100.0]/80
""",
    )

    peers = peer_profiles["nxos-overlay"]["nve_peers"]["peers"]
    assert peers["192.0.2.21"]["state"] == "Up"
    assert peers["192.0.2.22"]["state"] == "Down"
    routes = route_profiles["nxos-overlay"]["evpn_routes"]
    assert routes["route_count"] == 3
    assert routes["route_type_counts"] == {"2": 1, "3": 1, "5": 1}


def test_type5_route_and_vrf_route_parsers_preserve_prefix_context() -> None:
    _common, route_profiles = parse_nxos_command(
        "bgp_l2vpn_evpn",
        """Route Distinguisher: 10.0.0.11:50001    (L3VNI 50001)
*>i[5]:[0]:[0]:[24]:[198.51.100.0]/224
                      10.0.0.21                           0        100 i
""",
    )
    route = route_profiles["nxos-overlay"]["evpn_routes"]["routes"][0]
    assert route["prefix"] == "198.51.100.0/24"
    assert route["rd"] == "10.0.0.11:50001"
    assert route["l3vni"] == 50001
    assert route["next_hop"] == "10.0.0.21"
    assert route["paths"] == [
        {
            "next_hop": "10.0.0.21",
            "best": True,
            "local": False,
            "status": "*>i",
        }
    ]

    _common, multipath_profiles = parse_nxos_command(
        "bgp_l2vpn_evpn",
        """Route Distinguisher: 10.0.0.3:5
* i[5]:[0]:[0]:[24]:[172.16.0.0]/224
                      10.0.1.2                 0        100          0 ?
* i                   10.0.1.1                 0        100          0 ?
*>l                   10.0.2.2                 0        100      32768 ?
""",
    )
    multipath = multipath_profiles["nxos-overlay"]["evpn_routes"]["routes"][0]
    assert multipath["local"] is True
    assert [path["next_hop"] for path in multipath["paths"]] == [
        "10.0.1.2",
        "10.0.1.1",
        "10.0.2.2",
    ]
    assert multipath["paths"][-1]["local"] is True

    _common, vrf_profiles = parse_nxos_command(
        "route_ipv4_all_vrfs",
        """IP Route Table for VRF \"TENANT-A\"
198.51.100.0/24, ubest/mbest: 1/0
    *via 10.0.0.21, [200/0], 00:00:20, bgp-65001, external
""",
    )
    vrf_route = vrf_profiles["nxos-overlay"]["vrf_routes"]["ipv4"]["routes"][0]
    assert vrf_route == {
        "vrf": "TENANT-A",
        "family": "ipv4",
        "prefix": "198.51.100.0/24",
        "next_hop": "10.0.0.21",
        "protocol": "bgp",
    }

    _common, ipv6_profiles = parse_nxos_command(
        "route_ipv6_all_vrfs",
        """IPv6 Routing Table for VRF \"TENANT-A\"
fd21:0:0:1::/64, ubest/mbest: 1/0
    *via ::ffff:10.0.1.1%default:IPv4, [200/0], bgp-65001, internal
""",
    )
    ipv6_route = ipv6_profiles["nxos-overlay"]["vrf_routes"]["ipv6"]["routes"][0]
    assert ipv6_route["vrf"] == "TENANT-A"
    assert ipv6_route["prefix"] == "fd21:0:0:1::/64"
    assert ipv6_route["protocol"] == "bgp"


def test_type5_propagation_checks_origin_rr_and_all_receivers() -> None:
    leaf_config_text = """vrf context TENANT-A
  vni 50001
interface Vlan10
  vrf member TENANT-A
  ip address 198.51.100.1/24
router bgp 65001
  vrf TENANT-A
    address-family ipv4 unicast
      redistribute direct route-map HOST-SVI
route-map HOST-SVI permit 10
"""
    _common, leaf_profiles = parse_nxos_command("running_config", leaf_config_text)
    leaf_config = leaf_profiles["nxos-overlay"]["config"]
    receiver_config_text = """vrf context TENANT-A
  vni 50001
interface nve1
  member vni 50001 associate-vrf
"""
    _common, receiver_profiles = parse_nxos_command(
        "running_config", receiver_config_text
    )
    receiver_config = receiver_profiles["nxos-overlay"]["config"]
    route = {
        "applicable": True,
        "routes": [
            {
                "route_type": 5,
                "prefix": "198.51.100.0/24",
                "next_hop": "10.0.1.2",
                "local": False,
            }
        ],
    }

    def host(
        config: dict,
        *,
        primary: str | None = None,
        secondary: str | None = None,
        with_vrf_route: bool = False,
    ) -> dict:
        profile = {"config": config, "evpn_routes": route}
        if primary:
            profile["nve_interface"] = {
                "applicable": True,
                "primary_address": primary,
                "secondary_address": secondary,
            }
        if with_vrf_route:
            profile["vrf_routes"] = {
                "ipv4": {
                    "routes": [
                        {
                            "vrf": "TENANT-A",
                            "family": "ipv4",
                            "prefix": "198.51.100.0/24",
                        }
                    ]
                }
            }
        return {
            "profiles": {"nxos-overlay": profile},
            "sources": {
                "running_config": {"parse_status": "parsed"},
                "bgp_l2vpn_evpn": {"parse_status": "parsed"},
            },
        }

    snapshot = {
        "collection_id": "type5-before-001",
        "hosts": {
            "leaf01": host(
                leaf_config, primary="10.0.1.1", secondary="10.0.2.1"
            ),
            "rr01": host({}),
            "leaf01b": host(
                receiver_config, primary="10.0.1.2", secondary="10.0.2.1"
            ),
            "leaf02": host(
                receiver_config, primary="10.0.1.3", with_vrf_route=True
            ),
            "leaf03": host(
                receiver_config, primary="10.0.1.4", with_vrf_route=True
            ),
        },
    }
    roles = {
        "spec": {
            "devices": {
                "leaf01": {"topology_role": "leaf", "functions": {"vtep": {}}},
                "leaf02": {"topology_role": "leaf", "functions": {"vtep": {}}},
                "leaf03": {"topology_role": "leaf", "functions": {"vtep": {}}},
                "leaf01b": {"topology_role": "leaf", "functions": {"vtep": {}}},
                "rr01": {
                    "topology_role": "spine",
                    "functions": {"evpn-route-reflector": {}},
                },
            }
        }
    }
    definition = {
        "id": "type5_prefix_propagation",
        "profile": "nxos-overlay",
    }
    check = _evaluate_type5_prefix_propagation(
        snapshot, "leaf01", definition, roles
    )
    assert check["result"] == "PASS"
    assert check["after"]["stage_summary"] == {
        "prefixes": {"passed": 1, "total": 1},
        "receiver_evidence": {"covered": 2, "total": 2},
    }
    assert "prefixes" not in check["after"]
    assert check["after"]["failures"] == []
    assert check["after"]["unknowns"] == []
    assert check["message"] == (
        "Type-5 propagation: 1/1 prefix(es) passed; "
        "receiver evidence 2/2"
    )

    class IterationForbidden:
        def __iter__(self):
            raise AssertionError("route lists must not be rescanned after indexing")

    indexed_snapshot = deepcopy(snapshot)
    route_indexes = _build_type5_route_indexes(indexed_snapshot)
    for host_data in indexed_snapshot["hosts"].values():
        overlay = host_data["profiles"]["nxos-overlay"]
        overlay["evpn_routes"]["routes"] = IterationForbidden()
        for family_data in overlay.get("vrf_routes", {}).values():
            family_data["routes"] = IterationForbidden()
    indexed_check = _evaluate_type5_prefix_propagation(
        indexed_snapshot, "leaf01", definition, roles, route_indexes
    )
    assert indexed_check["result"] == "PASS"

    no_receiver_snapshot = deepcopy(snapshot)
    del no_receiver_snapshot["hosts"]["leaf02"]
    del no_receiver_snapshot["hosts"]["leaf03"]
    no_receiver_roles = deepcopy(roles)
    del no_receiver_roles["spec"]["devices"]["leaf02"]
    del no_receiver_roles["spec"]["devices"]["leaf03"]
    no_receiver = _evaluate_type5_prefix_propagation(
        no_receiver_snapshot, "leaf01", definition, no_receiver_roles
    )
    assert no_receiver["result"] == "PASS"
    assert "receiver stage NOT_APPLICABLE (0 targets)" in no_receiver["message"]

    snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"]["evpn_routes"] = {
        "applicable": True,
        "routes": [
            {
                "route_type": 5,
                "prefix": "198.51.100.0/24",
                "next_hop": "10.0.9.9",
                "local": False,
            }
        ],
    }
    wrong_origin = _evaluate_type5_prefix_propagation(
        snapshot, "leaf01", definition, roles
    )
    assert wrong_origin["result"] == "FAIL"

    snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"]["evpn_routes"] = route
    snapshot["hosts"]["leaf03"]["profiles"]["nxos-overlay"]["evpn_routes"] = {
        "applicable": True,
        "routes": [],
    }
    failed = _evaluate_type5_prefix_propagation(
        snapshot, "leaf01", definition, roles
    )
    assert failed["result"] == "FAIL"
    assert "RECEIVER_TYPE5" in failed["message"]
    assert "prefixes" not in failed["after"]
    assert failed["after"]["failures"] == [
        {
            "vrf": "TENANT-A",
            "prefix": "198.51.100.0/24",
            "stage": "RECEIVER_TYPE5",
            "devices": ["leaf03"],
            "reason": "Type-5 route is missing",
        }
    ]


def test_type5_route_indexes_preserve_missing_and_empty_evidence() -> None:
    snapshot = {
        "hosts": {
            "missing": {"profiles": {"nxos-overlay": {}}},
            "empty": {
                "profiles": {
                    "nxos-overlay": {
                        "evpn_routes": {"applicable": True, "routes": []},
                        "vrf_routes": {"ipv4": {"routes": []}},
                    }
                }
            },
            "present": {
                "profiles": {
                    "nxos-overlay": {
                        "evpn_routes": {
                            "applicable": True,
                            "routes": [
                                {
                                    "route_type": 5,
                                    "prefix": "192.0.2.0/24",
                                    "next_hop": "10.0.0.1",
                                },
                                {"route_type": 2, "prefix": "ignored"},
                            ],
                        },
                        "vrf_routes": {
                            "ipv4": {
                                "routes": [
                                    {"vrf": "tenant-a", "prefix": "192.0.2.0/24"}
                                ]
                            }
                        },
                    }
                }
            },
        }
    }

    indexes = _build_type5_route_indexes(snapshot)

    assert indexes["evpn"]["missing"] is None
    assert indexes["vrf"]["missing"] is None
    assert indexes["evpn"]["empty"] == {}
    assert indexes["vrf"]["empty"] == {"ipv4": set()}
    assert list(indexes["evpn"]["present"]) == ["192.0.2.0/24"]
    assert indexes["vrf"]["present"]["ipv4"] == {
        ("tenant-a", "192.0.2.0/24")
    }


def test_role_aware_evaluator_adds_function_and_vtep_checks(tmp_path: Path) -> None:
    path = _write_roles(
        tmp_path / "roles.yaml",
        {
            "schema_version": 2,
            "role_detection": {
                "leaf": {
                    "contains": ["leaf"],
                    "functions": {
                        "vtep": {"expectation": "required"},
                        "vpc": {"expectation": "optional"},
                    },
                }
            },
        },
    )
    resolved_roles = _resolve(path, ["leaf01"])
    now = datetime.fromisoformat("2026-08-08T12:00:00+09:00")
    resolved_profiles = resolve_profiles(
        ["nxos-overlay"],
        change_id="chg-role-test",
        resolved_at=now,
        timezone="Asia/Tokyo",
    )
    snapshot = {
        "schema_version": 1,
        "change_id": "chg-role-test",
        "collection_id": "chg-role-test-before-001",
        "phase": "before",
        "created_at": now.isoformat(),
        "timezone": "Asia/Tokyo",
        "parser_versions": {"nxos": "1.4"},
        "profile_sha256": resolved_profiles["spec"]["resolved"]["effective_sha256"],
        "hosts": {
            "leaf01": {
                "collection_status": "success",
                "common": {},
                "profiles": {
                    "nxos-overlay": {
                        "config": {
                            "nve": {"configured": True},
                            "vpc": {"configured": False},
                            "evpn_bgp_configured": False,
                            "rr_config": {},
                        },
                        "nve_interface": {"applicable": True, "name": "nve1", "state": "Up"},
                        "nve_peers": {"applicable": True, "peers": {"192.0.2.2": {"state": "Up"}}},
                        "nve_vnis": {"applicable": True, "vnis": {"10001": {"state": "Up"}}},
                        "evpn_bgp": {"applicable": False},
                        "evpn_routes": {"applicable": False},
                    }
                },
                "sources": {
                    identifier: {"status": "success", "parse_status": "parsed"}
                    for identifier in (
                        "running_config",
                        "nve_interface",
                        "nve_peers",
                        "nve_vni",
                        "bgp_l2vpn_evpn_summary",
                        "bgp_l2vpn_evpn",
                    )
                },
                "parse_warnings": [],
            }
        },
    }

    result = evaluate_snapshot(
        snapshot,
        resolved_profiles,
        started_at=now,
        completed_at=now,
        resolved_roles=resolved_roles,
    )

    checks = {check["check_id"]: check for check in result["checks"]}
    assert checks["vtep_function_expectation"]["result"] == "PASS"
    assert checks["vpc_function_expectation"]["result"] == "NOT_APPLICABLE"
    assert checks["nve_interface_health"]["result"] == "PASS"
    assert checks["nve_peer_regression"]["result"] == "PASS"
    assert checks["nve_vni_health"]["result"] == "PASS"
