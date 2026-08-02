from copy import deepcopy
import csv
import io

from alred.health.vni_map import (
    build_overlay_state,
    compare_overlay_states,
    overlay_diff_csv,
    overlay_state_csv,
    render_overlay_diff_markdown,
    render_overlay_state_markdown,
)
from alred.cli import build_parser, cmd_health_check_compare, cmd_health_check_snapshot


def _snapshot(phase="before"):
    def host(vlan, name="TENANT-A-WEB"):
        return {
            "common": {},
            "profiles": {
                "nxos-overlay": {
                    "config": {
                        "vlans": {str(vlan): {"name": name, "vni": 10010}},
                        "svis": {
                            str(vlan): {
                                "vrf": "TENANT-A",
                                "mtu": 9216,
                                "ipv4_addresses": ["192.0.2.1/24"],
                                "ipv6_addresses": ["2001:db8:10::1/64"],
                                "ipv6_link_local": "fe80::1",
                                "anycast_gateway": True,
                            }
                        },
                        "vrfs": {
                            "TENANT-A": {
                                "l3vni": 50001,
                                "rd": "auto",
                                "address_families": {},
                            }
                        },
                        "nve": {
                            "configured": True,
                            "l2vnis": {"10010": {}},
                            "l3vnis": {"50001": {"associate_vrf": True}},
                        },
                        "bgp_processes": {
                            "65000": {
                                "vrfs": {
                                    "TENANT-A": {
                                        "address_families": {
                                            "ipv4": {
                                                "commands": [
                                                    "advertise l2vpn evpn"
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        },
                    },
                    "nve_vnis": {
                        "applicable": True,
                        "vnis": {
                            "10010": {
                                "type": "L2",
                                "state": "Up",
                                "replication": "UnicastBGP",
                            },
                            "50001": {"type": "L3", "state": "Up"},
                        },
                    },
                }
            },
            "sources": {
                "running_config": {
                    "command": "show running-config",
                    "file": f"/raw/{phase}/config/leaf{vlan}_run.txt",
                    "sha256": "a" * 64,
                    "parse_status": "parsed",
                },
                "nve_vni": {
                    "command": "show nve vni",
                    "file": f"/raw/{phase}/leaf{vlan}_shows.log",
                    "sha256": "b" * 64,
                    "parse_status": "parsed",
                },
            },
            "parse_warnings": [],
        }

    return {
        "schema_version": 1,
        "change_id": "CHG-1",
        "collection_id": f"CHG-1-{phase}",
        "phase": phase,
        "created_at": "2026-08-02T12:00:00+09:00",
        "timezone": "Asia/Tokyo",
        "parser_versions": {"nxos": "1.1"},
        "profile_sha256": "sha256:" + "c" * 64,
        "hosts": {"leaf01": host(10), "leaf02": host(110)},
    }


def test_build_overlay_state_and_render_vni_map_formats():
    state = build_overlay_state(_snapshot())

    assert state["kind"] == "OverlayState"
    assert state["spec"]["summary"] == {
        "l2vnis": 1,
        "l3vnis": 1,
        "conflicts": 0,
        "unknowns": 0,
    }
    l2 = state["spec"]["l2vnis"][0]
    assert l2["status"] == "DEVICE_VARIANT"
    assert l2["devices"]["leaf01"]["vlan"] == 10
    assert l2["devices"]["leaf02"]["vlan"] == 110

    markdown = render_overlay_state_markdown(state)
    assert "# VNI Mapping" in markdown
    assert "10010" in markdown
    assert "leaf01=10, leaf02=110" in markdown

    rows = list(csv.DictReader(io.StringIO(overlay_state_csv(state))))
    assert len(rows) == 4
    l2_rows = [row for row in rows if row["resource_type"] == "L2VNI"]
    assert {row["vlan"] for row in l2_rows} == {"10", "110"}
    assert all(row["l3vni"] == "50001" for row in l2_rows)


def test_compare_overlay_states_writes_field_level_changes_only():
    before = build_overlay_state(_snapshot())
    after_snapshot = _snapshot("after")
    profile = after_snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"]
    profile["config"]["svis"]["10"]["mtu"] = 9000
    profile["nve_vnis"]["vnis"]["10010"]["state"] = "Down"
    after = build_overlay_state(after_snapshot)

    diff = compare_overlay_states(before, after)

    assert diff["kind"] == "OverlayVniMapDiff"
    assert diff["summary"]["total_changes"] == 2
    fields = {change["field"] for change in diff["changes"]}
    assert fields == {"operational_state", "svi.mtu"}
    assert all(change["change_type"] == "MODIFIED" for change in diff["changes"])
    assert all(change["status"] == "OBSERVED" for change in diff["changes"])

    rows = list(csv.DictReader(io.StringIO(overlay_diff_csv(diff))))
    assert {row["field"] for row in rows} == fields
    assert all(row["evidence_before"] for row in rows)
    assert all(row["evidence_after"] for row in rows)
    markdown = render_overlay_diff_markdown(diff)
    assert "# VNI Mapping Diff" in markdown
    assert "svi.mtu" in markdown


def test_overlay_state_records_missing_config_as_unknown_without_guessing():
    snapshot = _snapshot()
    snapshot["hosts"]["leaf02"]["profiles"] = {}

    state = build_overlay_state(snapshot)

    assert state["spec"]["summary"]["unknowns"] == 1
    assert state["spec"]["unknowns"] == [
        {
            "host": "leaf02",
            "resource_type": "OVERLAY_STATE",
            "reason": "running_config_overlay_state_unavailable",
        }
    ]


def test_overlay_state_reports_missing_nve_membership_as_conflict():
    snapshot = _snapshot()
    del snapshot["hosts"]["leaf02"]["profiles"]["nxos-overlay"]["config"][
        "nve"
    ]["l3vnis"]["50001"]

    state = build_overlay_state(snapshot)

    assert state["spec"]["summary"]["conflicts"] == 1
    assert state["spec"]["l3vnis"][0]["status"] == "CONFLICT"
    assert state["spec"]["conflicts"] == [
        {
            "resource_type": "L3VNI",
            "vni": 50001,
            "reason": "nve_membership_missing",
            "devices": ["leaf02"],
        }
    ]


def test_overlay_diff_does_not_emit_unchanged_rows():
    before = build_overlay_state(_snapshot())
    after_snapshot = deepcopy(_snapshot("after"))
    after = build_overlay_state(after_snapshot)

    diff = compare_overlay_states(before, after)

    assert diff["summary"]["total_changes"] == 0
    assert diff["changes"] == []
    assert len(overlay_diff_csv(diff).splitlines()) == 1


def test_overlay_diff_emits_new_unknown_overlay_state():
    before = build_overlay_state(_snapshot())
    after_snapshot = _snapshot("after")
    after_snapshot["hosts"]["leaf02"]["profiles"] = {}
    after = build_overlay_state(after_snapshot)

    diff = compare_overlay_states(before, after)

    unknown = [
        change for change in diff["changes"] if change["change_type"] == "UNKNOWN"
    ]
    assert len(unknown) == 1
    assert unknown[0]["resource_type"] == "OVERLAY_STATE"
    assert unknown[0]["vni"] is None
    assert unknown[0]["device"] == "leaf02"
    assert unknown[0]["status"] == "UNKNOWN"


def _write_overlay_collect(root, *, vlan, vni, phase):
    config = root / "config" / "leaf01_run.txt"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"""hostname leaf01
feature bgp
nv overlay evpn
vlan {vlan}
  name TENANT-A-WEB
  vn-segment {vni}
vrf context TENANT-A
  vni 50001
interface Vlan{vlan}
  vrf member TENANT-A
  mtu 9216
  ip address 192.0.2.1/24
  fabric forwarding mode anycast-gateway
interface nve1
  global ingress-replication protocol bgp
  member vni {vni}
  member vni 50001 associate-vrf
router bgp 65000
  address-family l2vpn evpn
""",
        encoding="utf-8",
    )
    show = root / "show_lists" / "leaf01" / "leaf01_shows.log"
    show.parent.mkdir(parents=True)
    show.write_text(
        "\n".join(
            [
                "### COMMAND_LIST",
                "show nve vni",
                "",
                "### COMMAND: show nve vni",
                f"### COLLECTED_AT: 2026-08-02T12:00:00+09:00",
                "### STATUS: OK",
                "### TRANSPORT: ssh",
                "leaf01# show nve vni",
                f"nve1 {vni} UnicastBGP Up CP L2 [{vlan}]",
                "nve1 50001 n/a Up CP L3 [TENANT-A]",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_overlay_profile_cli_writes_phase_maps_and_compare_diff(tmp_path):
    operations = tmp_path / "operations"
    before_input = tmp_path / "before"
    after_input = tmp_path / "after"
    _write_overlay_collect(before_input, vlan=10, vni=10010, phase="before")
    _write_overlay_collect(after_input, vlan=20, vni=10020, phase="after")

    for phase, source in (("before", before_input), ("after", after_input)):
        args = build_parser().parse_args(
            [
                "health-check",
                "snapshot",
                "--input",
                str(source),
                "--input-format",
                "alred-collect",
                "--phase",
                phase,
                "--change-id",
                "CHG-MAP",
                "--profile",
                "nxos-overlay",
                "--operations-root",
                str(operations),
            ]
        )
        assert cmd_health_check_snapshot(args) in {0, 3, 4}
        phase_dir = operations / "CHG-MAP" / "health" / phase
        assert (phase_dir / "overlay-state.yaml").is_file()
        assert (phase_dir / "vni-map.md").is_file()
        assert (phase_dir / "vni-map.csv").is_file()

    compare_args = build_parser().parse_args(
        [
            "health-check",
            "compare",
            "--before",
            str(operations / "CHG-MAP/health/before/snapshot.json"),
            "--after",
            str(operations / "CHG-MAP/health/after/snapshot.json"),
            "--operations-root",
            str(operations),
        ]
    )
    assert cmd_health_check_compare(compare_args) in {0, 3, 4}
    report = operations / "CHG-MAP" / "health" / "report"
    assert (report / "vni-map-diff.json").is_file()
    assert (report / "vni-map-diff.md").is_file()
    diff_rows = list(
        csv.DictReader(
            io.StringIO((report / "vni-map-diff.csv").read_text(encoding="utf-8"))
        )
    )
    assert {row["change_type"] for row in diff_rows} == {"ADDED", "REMOVED"}
