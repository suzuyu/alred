from copy import deepcopy
import csv
import io
import json
from pathlib import Path

import yaml

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
from alred.health.overlay import parse_overlay_running_config
from alred.cli import build_parser, cmd_health_check_compare, cmd_health_check_snapshot
from alred.operation import open_operation_workspace
from alred.schema import validate_document
from scripts.generate_single_site_network_ops_examples import generate


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
    assert "IPv6 link-local" in markdown
    assert "| fe80::1 |" in markdown

    rows = list(csv.DictReader(io.StringIO(overlay_state_csv(state))))
    assert len(rows) == 4
    l2_rows = [row for row in rows if row["resource_type"] == "L2VNI"]
    assert {row["vlan"] for row in l2_rows} == {"10", "110"}
    assert all(row["l3vni"] == "50001" for row in l2_rows)

    legacy_rows = list(
        csv.DictReader(io.StringIO(overlay_state_legacy_gateway_csv(state)))
    )
    assert len(legacy_rows) == 2
    assert list(legacy_rows[0]) == [
        "l3vni",
        "vrf",
        "l2vni",
        "gateway_ipv4",
        "gateway_ipv6",
        "device",
        "vlan",
        "vlan_name",
        "ipv6_link_local",
    ]
    assert {row["device"] for row in legacy_rows} == {"leaf01", "leaf02"}
    assert all(row["gateway_ipv4"] == "192.0.2.1/24" for row in legacy_rows)
    assert all(row["ipv6_link_local"] == "fe80::1" for row in legacy_rows)
    legacy_markdown = render_overlay_state_legacy_gateway_markdown(state)
    assert "# VNI / VRF / Gateway Map" in legacy_markdown
    assert "| 50001 | TENANT-A | 10010 |" in legacy_markdown
    assert "| ipv6_link_local |" in legacy_markdown
    assert "| fe80::1 |" in legacy_markdown

    l3_svi = deepcopy(state["spec"]["l2vnis"][0])
    l3_svi["vni"] = 50001
    state_with_l3_svi = deepcopy(state)
    state_with_l3_svi["spec"]["l2vnis"].append(l3_svi)
    assert len(
        list(
            csv.DictReader(
                io.StringIO(
                    overlay_state_legacy_gateway_csv(state_with_l3_svi)
                )
            )
        )
    ) == 2


def test_vni_map_reports_auto_and_device_variant_for_ipv6_link_local():
    snapshot = _snapshot()
    snapshot["hosts"]["leaf02"]["profiles"]["nxos-overlay"]["config"][
        "vlans"
    ] = {
        "10": {
            "name": "TENANT-A-WEB",
            "vni": 10010,
        }
    }
    config = snapshot["hosts"]["leaf02"]["profiles"]["nxos-overlay"][
        "config"
    ]
    config["svis"]["10"] = config["svis"].pop("110")
    config["svis"]["10"].pop("ipv6_link_local")

    state = build_overlay_state(snapshot)

    assert state["spec"]["l2vnis"][0]["status"] == "DEVICE_VARIANT"
    markdown = render_overlay_state_markdown(state)
    assert "leaf01=fe80::1, leaf02=auto" in markdown
    rows = list(csv.DictReader(io.StringIO(overlay_state_csv(state))))
    l2_rows = [row for row in rows if row["resource_type"] == "L2VNI"]
    assert {row["ipv6_link_local"] for row in l2_rows} == {"fe80::1", "auto"}
    legacy_rows = list(
        csv.DictReader(io.StringIO(overlay_state_legacy_gateway_csv(state)))
    )
    assert {row["ipv6_link_local"] for row in legacy_rows} == {
        "fe80::1",
        "auto",
    }


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
    assert "## L2VNI 10010 — VRF TENANT-A" in markdown
    assert "| MODIFIED | operational_state | leaf01 | Up | Down | OBSERVED |" in markdown
    assert "## Field Source List" in markdown
    assert "| operational_state | Operational command output | `show nve vni` |" in markdown
    assert "| svi.mtu | Running configuration | `show running-config` |" in markdown
    assert "## Evidence Files" in markdown
    assert "/raw/before/leaf10_shows.log" in markdown
    assert "/raw/after/config/leaf10_run.txt" in markdown


def test_overlay_diff_groups_changes_by_vni_across_resource_types():
    before = build_overlay_state(_snapshot())
    after_snapshot = _snapshot("after")
    profile = after_snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"]
    profile["config"]["svis"]["10"]["mtu"] = 9000
    profile["nve_vnis"]["vnis"]["50001"]["state"] = "Down"
    after = build_overlay_state(after_snapshot)

    diff = compare_overlay_states(before, after)

    assert [change["vni"] for change in diff["changes"]] == [10010, 50001]
    assert [change["resource_type"] for change in diff["changes"]] == [
        "L2VNI",
        "L3VNI",
    ]


def test_overlay_diff_markdown_groups_devices_with_the_same_result():
    before = build_overlay_state(_snapshot())
    after_snapshot = _snapshot("after")
    for host in ("leaf01", "leaf02"):
        profile = after_snapshot["hosts"][host]["profiles"]["nxos-overlay"]
        vlan = "10" if host == "leaf01" else "110"
        profile["config"]["svis"][vlan]["mtu"] = 9000
    after = build_overlay_state(after_snapshot)

    markdown = render_overlay_diff_markdown(compare_overlay_states(before, after))

    assert "- Field changes: 2" in markdown
    assert "- Display rows: 1" in markdown
    assert "| MODIFIED | svi.mtu | leaf01, leaf02 | 9216 | 9000 | OBSERVED |" in markdown


def test_documented_overlay_state_and_diff_samples_match_schemas(tmp_path):
    samples = (
        Path(__file__).parents[1]
        / "docs"
        / "manual"
        / "network-ops"
        / "examples"
        / "nxos-overlay"
    )
    states = []
    for name in ("before-overlay-state.yaml", "after-overlay-state.yaml"):
        document = yaml.safe_load((samples / name).read_text(encoding="utf-8"))
        validate_document(document, kind="OverlayState")
        states.append(document)

    diff = json.loads((samples / "vni-map-diff.json").read_text(encoding="utf-8"))
    validate_document(diff, kind="OverlayVniMapDiff")
    assert len(diff["changes"]) == diff["summary"]["total_changes"]
    assert render_overlay_diff_markdown(diff) == (
        samples / "vni-map-diff.md"
    ).read_text(encoding="utf-8")
    generated = compare_overlay_states(*states)
    fields = (
        "change_type",
        "resource_type",
        "vni",
        "vrf",
        "device",
        "field",
        "before",
        "after",
        "status",
    )
    assert [tuple(item[key] for key in fields) for item in diff["changes"]] == [
        tuple(item[key] for key in fields) for item in generated["changes"]
    ]

    for phase in ("before", "after"):
        checklist = (samples / f"{phase}-checklist.md").read_text(encoding="utf-8")
        assert checklist.startswith("# Health Check Checklist\n")
        assert f"- Phase: {phase}" in checklist
        assert "- Result: PASS" in checklist
        assert "## Result by Profile" in checklist
        assert "| network-baseline-nxos | 144 | 0 | 0 | 0 | 32 |" in checklist
        assert "| nxos-overlay | 50 | 0 | 0 | 0 | 2 |" in checklist
        assert "`vlan_operational_health`: PASS" in checklist
        assert "`vrf_operational_health`: PASS" in checklist
        assert "`svi_operational_health`: PASS" in checklist
        assert "`lldp_evidence_completeness`: PASS" in checklist
        assert "`lldp_description_consistency`: NOT_APPLICABLE" in checklist
        assert "`type5_prefix_propagation`" in checklist
        assert checklist.count("### Device: `") == 8
        assert checklist.index("### Device: `adc-lfsw0101`") < checklist.index(
            "### Device: `adc-lfsw0104`"
        ) < checklist.index("### Device: `adc-spsw0101`")
        assert checklist.count("#### Profile: `network-baseline-nxos`") == 8
        assert checklist.count("#### Profile: `nxos-overlay`") == 6
        assert sum(line.startswith("- [") for line in checklist.splitlines()) == 228
        assert "## Unexecuted Hosts" in checklist
        assert "adc-bgrt0101" in checklist
        assert "adc-bgrt0102" in checklist

        gateway_markdown = (
            samples / f"{phase}-vni_gateway_map.md"
        ).read_text(encoding="utf-8")
        gateway_csv = (
            samples / f"{phase}-vni_gateway_map.csv"
        ).read_text(encoding="utf-8")
        assert gateway_markdown.startswith("# VNI / VRF / Gateway Map\n")
        assert gateway_csv.startswith("l3vni,vrf,l2vni,")

    assert states[0]["spec"]["summary"]["l2vnis"] == 5
    assert states[1]["spec"]["summary"]["l2vnis"] == 6
    assert states[0]["spec"]["summary"]["l3vnis"] == 3
    assert states[1]["spec"]["summary"]["l3vnis"] == 3
    assert {item["vni"] for item in states[1]["spec"]["l3vnis"]} == {
        9001,
        19001,
        29001,
    }

    generated_network = tmp_path / "nxos-overlay"
    generated_changeset = tmp_path / "overlay-changeset"
    generated_paths = generate(
        Path(__file__).parents[1],
        network_output=generated_network,
        changeset_output=generated_changeset,
    )
    for actual in generated_paths:
        expected_root = (
            samples
            if actual.is_relative_to(generated_network)
            else samples.parent / "overlay-changeset"
        )
        assert actual.read_bytes() == (expected_root / actual.name).read_bytes()


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


def test_traditional_vlan_svi_l3vni_is_not_duplicated_as_l2vni():
    snapshot = _snapshot()
    config_text = """\
vlan 10
  name TENANT-A-WEB
  vn-segment 10010
vlan 3000
  name TENANT-A-L3VNI
  vn-segment 50001
vrf context TENANT-A
  vni 50001
interface Vlan10
  vrf member TENANT-A
  ip address 192.0.2.1/24
interface Vlan3000
  vrf member TENANT-A
  ip forward
interface nve1
  member vni 10010
    ingress-replication protocol bgp
  member vni 50001 associate-vrf
"""
    for host_data in snapshot["hosts"].values():
        host_data["profiles"]["nxos-overlay"]["config"] = (
            parse_overlay_running_config(config_text)
        )

    state = build_overlay_state(snapshot)

    assert state["spec"]["summary"] == {
        "l2vnis": 1,
        "l3vnis": 1,
        "conflicts": 0,
        "unknowns": 0,
    }
    assert [item["vni"] for item in state["spec"]["l2vnis"]] == [10010]
    assert [item["vni"] for item in state["spec"]["l3vnis"]] == [50001]


def test_traditional_l3vni_missing_associate_vrf_is_only_l3_conflict():
    snapshot = _snapshot()
    config_text = """\
vlan 3000
  vn-segment 50001
vrf context TENANT-A
  vni 50001
interface Vlan3000
  vrf member TENANT-A
  ip forward
interface nve1
"""
    for host_data in snapshot["hosts"].values():
        host_data["profiles"]["nxos-overlay"]["config"] = (
            parse_overlay_running_config(config_text)
        )

    state = build_overlay_state(snapshot)

    assert state["spec"]["l2vnis"] == []
    assert state["spec"]["l3vnis"][0]["status"] == "CONFLICT"
    assert state["spec"]["conflicts"] == [
        {
            "resource_type": "L3VNI",
            "vni": 50001,
            "reason": "nve_membership_missing",
            "devices": ["leaf01", "leaf02"],
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


def test_overlay_profile_cli_writes_phase_maps_and_compare_diff(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
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
        phase_dir = (
            open_operation_workspace(operations, "CHG-MAP").operation_root
            / "health"
            / phase
        )
        assert (phase_dir / "overlay-state.yaml").is_file()
        assert (phase_dir / "vni-map.md").is_file()
        assert (phase_dir / "vni-map.csv").is_file()
        assert (phase_dir / "vni_gateway_map.md").is_file()
        assert (phase_dir / "vni_gateway_map.csv").is_file()

    output = capsys.readouterr().out
    assert "VNI GW Map:" in output
    assert "VNI GW CSV:" in output
    assert "Legacy Map:" not in output
    assert "Legacy CSV:" not in output

    operation_root = open_operation_workspace(
        operations, "CHG-MAP"
    ).operation_root
    compare_args = build_parser().parse_args(
        [
            "health-check",
            "compare",
            "--before",
            str(operation_root / "health/before/snapshot.json"),
            "--after",
            str(operation_root / "health/after/snapshot.json"),
            "--operations-root",
            str(operations),
        ]
    )
    assert cmd_health_check_compare(compare_args) in {0, 3, 4}
    report = operation_root / "health" / "report"
    assert (report / "vni-map-diff.json").is_file()
    assert (report / "vni-map-diff.md").is_file()
    diff_rows = list(
        csv.DictReader(
            io.StringIO((report / "vni-map-diff.csv").read_text(encoding="utf-8"))
        )
    )
    assert {row["change_type"] for row in diff_rows} == {"ADDED", "REMOVED"}
