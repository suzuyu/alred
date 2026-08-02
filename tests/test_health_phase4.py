from datetime import datetime
import json

import yaml

from alred.cli import build_parser, cmd_overlay_check_discover
from alred.health.overlay import (
    discover_overlay_changes,
    parse_overlay_running_config,
)
from alred.operation import create_operation_workspace


JST_NOW = datetime.fromisoformat("2026-08-01T10:02:03+09:00")

BEFORE_CONFIG = """\
interface nve1
  no shutdown
  global ingress-replication protocol bgp
"""

AFTER_CONFIG = """\
vrf context TENANT-A
  vni 50001 l3
  rd auto
vlan 10
  name TENANT-A-WEB
  vn-segment 10010
interface Vlan10
  no shutdown
  vrf member TENANT-A
  mtu 9216
  ip address 192.0.2.1/24
  ipv6 address 2001:db8:10::1/64
  ipv6 address fe80::1
  ipv6 nd suppress-ra
  fabric forwarding mode anycast-gateway
interface nve1
  no shutdown
  global ingress-replication protocol bgp
  member vni 50001 associate-vrf
  member vni 10010
"""


def _snapshot(change_id, collection_id, phase, states):
    return {
        "schema_version": 1,
        "change_id": change_id,
        "collection_id": collection_id,
        "phase": phase,
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            host: {
                "common": {},
                "profiles": {"nxos-overlay": {"config": state}},
                "sources": {},
            }
            for host, state in states.items()
        },
    }


def test_overlay_running_config_parser_preserves_multi_af_svi_and_new_l3vni():
    state = parse_overlay_running_config(AFTER_CONFIG)

    assert state["vlans"]["10"] == {
        "name": "TENANT-A-WEB",
        "vni": 10010,
    }
    assert state["vrfs"]["TENANT-A"]["l3vni"] == 50001
    assert state["svis"]["10"]["ipv4_addresses"] == ["192.0.2.1/24"]
    assert state["svis"]["10"]["ipv6_addresses"] == ["2001:db8:10::1/64"]
    assert state["svis"]["10"]["ipv6_link_local"] == "fe80::1"
    assert state["svis"]["10"]["ipv6_nd_suppress_ra"] is True
    assert state["svis"]["10"]["mtu"] == 9216
    assert state["nve"]["configured"] is True
    assert state["nve"]["global_ingress_replication_protocol_bgp"] is True
    assert "50001" in state["nve"]["l3vnis"]
    assert "10010" in state["nve"]["l2vnis"]


def test_overlay_running_config_parser_detects_global_evpn_bgp_af():
    state = parse_overlay_running_config(
        """\
router bgp 65000
  address-family l2vpn evpn
    retain route-target all
"""
    )

    assert state["evpn_bgp_configured"] is True


def test_overlay_running_config_parser_records_ra_suppress_as_disabled_when_absent():
    state = parse_overlay_running_config(
        """\
interface Vlan10
  ipv6 address 2001:db8:10::1/64
"""
    )

    assert state["svis"]["10"]["ipv6_nd_suppress_ra"] is False
    assert state["nve"]["configured"] is False


def test_show_nve_vni_parser_preserves_type_context_and_state():
    from alred.health.parsers import parse_nxos_command

    output = """\
Interface VNI      Multicast-group   State Mode Type [BD/VRF]      Flags
nve1      10010    UnicastBGP        Up    CP   L2 [10]            SA
nve1      50001    n/a               Up    CP   L3 [TENANT-A]
"""
    _common, profiles = parse_nxos_command("nve_vni", output)

    vnis = profiles["nxos-overlay"]["nve_vnis"]["vnis"]
    assert vnis["10010"]["type"] == "L2"
    assert vnis["10010"]["context"] == "10"
    assert vnis["50001"]["type"] == "L3"
    assert vnis["50001"]["context"] == "TENANT-A"


def test_ingress_replication_parser_preserves_remote_vteps():
    from alred.health.parsers import parse_nxos_command

    output = """\
Interface VNI      Replication List  Source    Up Time
nve1      10010    10.0.0.12        BGP-IMET  00:46:55
nve1      10010    10.0.0.13        BGP-IMET  00:45:31
"""
    _common, profiles = parse_nxos_command(
        "nve_vni_ingress_replication", output
    )

    peers = profiles["nxos-overlay"]["ingress_replication"]["vnis"]["10010"]
    assert [peer["remote_vtep"] for peer in peers] == [
        "10.0.0.12",
        "10.0.0.13",
    ]


def test_discovery_builds_common_vlan_and_new_l3vni_mode():
    before_state = parse_overlay_running_config(BEFORE_CONFIG)
    after_state = parse_overlay_running_config(AFTER_CONFIG)
    before = _snapshot(
        "CHG-1",
        "before-001",
        "before",
        {"leaf01": before_state, "leaf02": before_state},
    )
    after = _snapshot(
        "CHG-1",
        "after-001",
        "after",
        {"leaf01": after_state, "leaf02": after_state},
    )

    discovered = discover_overlay_changes(
        before,
        after,
        generated_at=JST_NOW,
    )

    assert discovered["metadata"]["source"] == "discovered"
    assert discovered["spec"]["l3vnis"] == [
        {
            "vni": 50001,
            "vrf": "TENANT-A",
            "mode": "new_l3vni",
            "targets": {"devices": {"leaf01": {}, "leaf02": {}}},
        }
    ]
    l2vni = discovered["spec"]["l2vnis"][0]
    assert l2vni["vni"] == 10010
    assert l2vni["default_vlan"] == 10
    assert l2vni["vlan_name"] == "TENANT-A-WEB"
    assert l2vni["vrf"] == "TENANT-A"
    assert l2vni["l3vni"] == 50001
    assert l2vni["svi"] == {
        "mtu": 9216,
        "ipv4_addresses": ["192.0.2.1/24"],
        "ipv6_addresses": ["2001:db8:10::1/64"],
        "ipv6_link_local": "fe80::1",
        "ipv6_nd_suppress_ra": True,
        "gateway_mode": "anycast",
    }
    assert discovered["status"]["conflicts"] == []
    assert discovered["status"]["discovery"]["confidence"] == "medium"


def test_discovery_uses_device_vlan_override_and_reports_name_conflict():
    before_state = parse_overlay_running_config(BEFORE_CONFIG)
    leaf01 = parse_overlay_running_config(AFTER_CONFIG)
    leaf02 = parse_overlay_running_config(
        AFTER_CONFIG.replace("vlan 10", "vlan 20")
        .replace("Vlan10", "Vlan20")
        .replace("TENANT-A-WEB", "DIFFERENT-NAME")
    )
    before = _snapshot(
        "CHG-1",
        "before-001",
        "before",
        {"leaf01": before_state, "leaf02": before_state},
    )
    after = _snapshot(
        "CHG-1",
        "after-001",
        "after",
        {"leaf01": leaf01, "leaf02": leaf02},
    )

    discovered = discover_overlay_changes(
        before,
        after,
        generated_at=JST_NOW,
    )

    l2vni = discovered["spec"]["l2vnis"][0]
    assert "default_vlan" not in l2vni
    assert l2vni["targets"]["devices"] == {
        "leaf01": {"vlan": 10},
        "leaf02": {"vlan": 20},
    }
    assert discovered["status"]["conflicts"] == [
        {"resource": "l2vni/10010", "reason": "vlan_name_mismatch"}
    ]


def test_discovery_uses_unique_modal_vlan_and_exact_device_group():
    before_state = parse_overlay_running_config(BEFORE_CONFIG)
    states = {
        "leaf01": parse_overlay_running_config(AFTER_CONFIG),
        "leaf02": parse_overlay_running_config(AFTER_CONFIG),
        "leaf03": parse_overlay_running_config(
            AFTER_CONFIG.replace("vlan 10", "vlan 20").replace(
                "Vlan10", "Vlan20"
            )
        ),
    }
    before = _snapshot(
        "CHG-1",
        "before-001",
        "before",
        {host: before_state for host in states},
    )
    after = _snapshot("CHG-1", "after-001", "after", states)

    discovered = discover_overlay_changes(
        before,
        after,
        generated_at=JST_NOW,
        device_groups={"server-leafs": ["leaf01", "leaf02"]},
    )

    item = discovered["spec"]["l2vnis"][0]
    assert item["default_vlan"] == 10
    assert item["targets"] == {
        "groups": {"server-leafs": {}},
        "devices": {"leaf03": {"vlan": 20}},
    }


def test_overlay_discovery_cli_writes_changeset_without_device_access(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    before = _snapshot(
        "CHG-1",
        "before-001",
        "before",
        {"leaf01": parse_overlay_running_config(BEFORE_CONFIG)},
    )
    after = _snapshot(
        "CHG-1",
        "after-001",
        "after",
        {"leaf01": parse_overlay_running_config(AFTER_CONFIG)},
    )
    before_path = workspace.operation_root / "before.json"
    after_path = workspace.operation_root / "after.json"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    after_path.write_text(json.dumps(after), encoding="utf-8")
    before_path.chmod(0o600)
    after_path.chmod(0o600)
    args = build_parser().parse_args(
        [
            "overlay-check",
            "discover",
            "--before",
            str(before_path),
            "--after",
            str(after_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_overlay_check_discover(args)

    output_path = workspace.operation_root / "overlay" / "discovered-changes.yaml"
    document = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert document["spec"]["l2vnis"][0]["vni"] == 10010
    assert "OVERLAY DISCOVERY SUMMARY" in capsys.readouterr().out
