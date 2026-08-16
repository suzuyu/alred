from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import pytest
import yaml

from alred.cli import (
    build_parser,
    cmd_health_check_compare,
    cmd_health_check_snapshot,
)
from alred.health.evaluator import (
    HealthEvaluationError,
    assess_cpu_samples,
    compare_snapshots,
    evaluate_snapshot,
)
from alred.health.commands import command_id
from alred.health.profile import (
    ProfileResolutionError,
    resolve_profiles,
)
from alred.health.parsers import ParserError, parse_nxos_command
from alred.health.report import render_health_checklist
from alred.operation import open_operation_workspace


JST_NOW = datetime.fromisoformat("2026-08-02T10:02:03+09:00")


def test_health_checklist_groups_checks_by_device_then_profile():
    result = {
        "change_id": "CHG-1",
        "phase": "before",
        "started_at": "2026-08-02T10:00:00+09:00",
        "completed_at": "2026-08-02T10:02:03+09:00",
        "result": "WARN",
        "profiles": [
            "network-baseline-nxos",
            "logging-excludes-example",
            "nxos-overlay",
        ],
        "device_addresses": {
            "leaf01": "192.0.2.11",
            "leaf02": "2001:db8::12",
        },
        "checks": [
            {
                "host": "leaf02",
                "check_id": "cpu_utilization",
                "result": "WARN",
                "message": "CPU warning",
                "profile": "network-baseline-nxos",
            },
            {
                "host": "leaf01",
                "check_id": "system_identity",
                "result": "PASS",
                "message": "System is healthy",
                "profile": "network-baseline-nxos",
            },
            {
                "host": "leaf01",
                "check_id": "logging_health",
                "result": "PASS",
                "message": "No new logs",
                "profile": "nxos-overlay",
            },
        ],
    }

    checklist = render_health_checklist(result)
    lines = checklist.splitlines()

    assert lines[2] == "- Started at: 2026-08-02T10:00:00+09:00"
    assert lines[3] == "- Completed at: 2026-08-02T10:02:03+09:00"
    assert lines[4] == "- Duration: 00:02:03 (123 seconds)"
    assert "| network-baseline-nxos | 1 | 1 | 0 | 0 | 0 |" in checklist
    assert "| nxos-overlay | 1 | 0 | 0 | 0 | 0 |" in checklist
    assert "| logging-excludes-example |" not in checklist
    assert "#### Profile: `logging-excludes-example`" not in checklist
    assert "### Device: `leaf01` (192.0.2.11)" in checklist
    assert "### Device: `leaf02` (2001:db8::12)" in checklist
    assert checklist.index("### Device: `leaf01`") < checklist.index(
        "### Device: `leaf02`"
    )
    leaf01 = checklist.split("### Device: `leaf01`", 1)[1].split(
        "### Device: `leaf02`", 1
    )[0]
    assert "`system_identity`" in leaf01
    assert "`logging_health`" in leaf01
    assert leaf01.index("#### Profile: `network-baseline-nxos`") < leaf01.index(
        "#### Profile: `nxos-overlay`"
    )
    assert "leaf01 /" not in leaf01


NXOS_FIXTURES = Path(__file__).parent / "fixtures" / "nxos"
BASELINE_COMMAND_FIXTURES = {
    "show clock": (NXOS_FIXTURES / "show_clock" / "c9300v_10_5_4.txt"),
    "show ntp status": (
        NXOS_FIXTURES / "show_ntp_status" / "c9300v_10_5_4_synchronized.txt"
    ),
    "show ntp peers": (
        NXOS_FIXTURES / "show_ntp_peers" / "c9300v_10_5_4_selected.txt"
    ),
    "show ntp peer-status": (
        NXOS_FIXTURES
        / "show_ntp_peer_status"
        / "c9300v_10_5_4_selected.txt"
    ),
    "show interface status": (
        NXOS_FIXTURES / "show_interface_status" / "c9300v_10_5_4.txt"
    ),
    "show interface counters table": (
        NXOS_FIXTURES
        / "show_interface_counters_table"
        / "c9300v_10_5_4.txt"
    ),
    "show interface counters errors non-zero": (
        NXOS_FIXTURES / "show_interface_errors" / "c9300v_10_5_4_zero.txt"
    ),
    "show port-channel summary": (
        NXOS_FIXTURES
        / "show_port_channel_summary"
        / "c9300v_10_5_4_healthy.txt"
    ),
    "show version": (NXOS_FIXTURES / "show_version" / "c9300v_10_5_4.txt"),
    "show processes cpu": (NXOS_FIXTURES / "show_processes_cpu" / "c9300v_10_5_4.txt"),
    "show system resources": (
        NXOS_FIXTURES / "show_system_resources" / "c9300v_10_5_4.txt"
    ),
    "show environment": (
        NXOS_FIXTURES / "show_environment" / "c9300v_10_5_4_virtual.txt"
    ),
    "show system config reload-pending": (
        NXOS_FIXTURES / "show_reload_pending" / "c9300v_10_5_4_no_pending.txt"
    ),
    "show running-config diff unified": (
        NXOS_FIXTURES
        / "show_running_config_diff"
        / "c9300v_10_5_4_clean.txt"
    ),
    "show logging": (NXOS_FIXTURES / "show_logging" / "c9300v_10_5_4_healthy.txt"),
    "show ip route summary vrf all": (
        NXOS_FIXTURES / "show_route_summary_ipv4" / "c9300v_10_5_4.txt"
    ),
    "show running-config": (
        NXOS_FIXTURES / "show_running_config" / "c9300v_10_5_4_minimal.txt"
    ),
}


def _resolved(refs=None):
    return resolve_profiles(
        refs or ["network-baseline-nxos"],
        change_id="CHG-1",
        resolved_at=JST_NOW,
        timezone="Asia/Tokyo",
    )


def _sources(*identifiers):
    return {
        identifier: {
            "status": "success",
            "parse_status": "parsed",
            "command": identifier,
            "file": f"/fixtures/{identifier}.txt",
            "sha256": "a" * 64,
        }
        for identifier in identifiers
    }


def _logging_record(timestamp: str, severity: int, text: str) -> dict:
    return {
        "timestamp_text": timestamp,
        "timestamp": timestamp,
        "severity": severity,
        "fingerprint": f"{timestamp}|{text}",
        "text": text,
        "parse_warnings": [],
    }


def _snapshot(resolved, *, phase="before"):
    return {
        "schema_version": 1,
        "change_id": "CHG-1",
        "collection_id": f"CHG-1-{phase}-001",
        "phase": phase,
        "created_at": JST_NOW.isoformat(),
        "timezone": "Asia/Tokyo",
        "parser_versions": {"nxos": "1.0"},
        "profile_sha256": resolved["spec"]["resolved"]["effective_sha256"],
        "hosts": {
            "leaf01": {
                "collection_status": "success",
                "common": {
                    "system": {
                        "platform": "nxos",
                        "version": "10.5(4)",
                        "model": "Nexus9000 C9300v",
                        "reported_hostname": "leaf01",
                        "uptime_seconds": 100000,
                    },
                    "cpu": {
                        "five_seconds_percent": 20,
                        "interrupt_percent": 1,
                        "one_minute_percent": 30,
                        "five_minutes_percent": 25,
                    },
                    "resources": {
                        "memory": {
                            "used_percent": 50,
                        }
                    },
                    "environment": {
                        "applicable": False,
                        "healthy": True,
                        "alarms": [],
                    },
                    "clock": {"timestamp": JST_NOW.isoformat(), "timezone": "Asia/Tokyo"},
                    "ntp": {
                        "configured": True,
                        "synchronized": True,
                        "peers": {"192.0.2.123": {"selected": True, "marker": "*"}},
                    },
                    "interfaces": {
                        "Eth1/1": {"admin_state": "up", "operational_state": "up", "status": "connected"}
                    },
                    "interface_errors": {},
                    "interface_utilization": {
                        "interfaces": {
                            "Eth1/1": {
                                "input_mbps": 1000.0,
                                "input_percent": 10.0,
                                "output_mbps": 2000.0,
                                "output_percent": 20.0,
                                "load_interval_seconds": 30,
                            }
                        }
                    },
                    "routing_neighbor_config": {"processes": {}},
                    "port_channels": {"applicable": False, "channels": {}},
                    "reload_pending": {
                        "required": False,
                        "commands": [],
                    },
                    "running_config_diff": {
                        "different": False,
                        "line_count": 0,
                        "output_sha256": "0" * 64,
                    },
                    "logging": {
                        "records": [],
                        "parse_warnings": [],
                    },
                    "routes": {
                        "ipv4_summary": {
                            "vrfs": {
                                "default": {"routes": 36, "paths": 51},
                                "TENANT-A": {"routes": 16, "paths": 16},
                            }
                        }
                    },
                    "vpc": {"applicable": False},
                },
                "profiles": {},
                "sources": _sources(
                    "show_version",
                    "processes_cpu",
                    "system_resources",
                    "environment",
                    "clock",
                    "ntp_status",
                    "ntp_peers",
                    "interface_status",
                    "interface_counters_table",
                    "interface_errors",
                    "port_channel_summary",
                    "reload_pending",
                    "running_config_diff",
                    "show_logging",
                    "route_summary_ipv4",
                    "vpc_brief",
                    "running_config",
                ),
                "parse_warnings": [],
            }
        },
    }


def _write_collect(path, *, cpu_fixture=None, reload_output=None):
    fixtures = dict(BASELINE_COMMAND_FIXTURES)
    sections = ["### COMMAND_LIST", *fixtures, ""]
    for index, (command, fixture) in enumerate(fixtures.items()):
        if command == "show processes cpu" and cpu_fixture is not None:
            output = cpu_fixture
        elif (
            command == "show system config reload-pending" and reload_output is not None
        ):
            output = reload_output
        else:
            output = fixture.read_text(encoding="utf-8")
        if command == "show version":
            output = output.replace("Device name: leaf-fixture-01", "Device name: leaf01")
        sections.extend(
            [
                f"### COMMAND: {command}",
                (f"### COLLECTED_AT: 2026-08-02T10:02:{index:02d}+09:00"),
                "### STATUS: OK",
                "### TRANSPORT: ssh",
                f"leaf01# {command}",
                output.rstrip(),
                "",
            ]
        )
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(sections), encoding="utf-8")


def test_builtin_profiles_resolve_deterministically():
    first = _resolved(["network-baseline-nxos", "nxos-overlay"])
    second = _resolved(["network-baseline-nxos", "nxos-overlay"])

    assert (
        first["spec"]["resolved"]["effective_sha256"]
        == second["spec"]["resolved"]["effective_sha256"]
    )
    assert first["spec"]["resolved"]["profile_names"] == [
        "network-baseline-nxos",
        "nxos-overlay",
    ]
    commands = first["spec"]["resolved"]["effective"]["spec"]["collectors"]["nxos"][
        "commands"
    ]
    assert {command["id"] for command in commands} == {
        "show_version",
        "processes_cpu",
        "system_resources",
        "show_logging",
        "reload_pending",
        "vpc_brief",
        "environment",
        "route_summary_ipv4",
        "ospf_neighbors",
            "bgp_ipv4_summary",
            "bgp_ipv6_summary",
            "nve_interface",
            "nve_peers",
            "nve_vni",
        "nve_vni_ingress_replication",
            "bgp_l2vpn_evpn_summary",
                "bgp_l2vpn_evpn",
                "route_ipv4_all_vrfs",
                "route_ipv6_all_vrfs",
            "running_config",
            "running_config_diff",
            "clock",
            "ntp_status",
            "ntp_peers",
            "ntp_peer_status",
            "interface_status",
                "interface_counters_table",
                "interface_errors",
                "port_channel_summary",
                "vlan_brief",
                "vrf",
                "interface_brief",
        }


def test_explicit_profile_replaces_default_profile():
    resolved = _resolved(["nxos-overlay"])

    assert resolved["spec"]["resolved"]["profile_names"] == ["nxos-overlay"]
    assert resolved["spec"]["requested"][0]["resolution_source"] == "explicit"


def test_site_profile_overrides_threshold_and_records_provenance(tmp_path):
    site = tmp_path / "site.yaml"
    site.write_text(
        yaml.safe_dump(
            {
                "api_version": "alred/v1",
                "kind": "HealthCheckProfile",
                "metadata": {"name": "site", "version": "1"},
                "spec": {
                    "platforms": ["nxos"],
                    "checks": [
                        {
                            "id": "site-note",
                            "evaluator": "site-note",
                            "severity": "info",
                        }
                    ],
                    "thresholds": {"cpu": {"warn_percent": 70}},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resolved = _resolved(["network-baseline-nxos", str(site)])

    assert (
        resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"]["cpu"][
            "warn_percent"
        ]
        == 70
    )
    assert resolved["spec"]["resolved"]["overrides"][0]["path"] == (
        "spec.thresholds.cpu.warn_percent"
    )


def test_generate_sample_config_writes_logging_exclude_profile(tmp_path):
    output_dir = tmp_path / "samples"
    args = build_parser().parse_args(
        [
            "generate-sample-config",
            "--output-dir",
            str(output_dir),
            "--log-file",
            str(tmp_path / "generate-sample-config.log"),
        ]
    )
    assert args.func(args) is None

    sample = output_dir / "health-check-profile.logging-excludes.example.yaml"
    assert sample.is_file()

    resolved = _resolved(["network-baseline-nxos", str(sample)])
    effective = resolved["spec"]["resolved"]["effective"]["spec"]

    assert (
        "PAM adding faulty module: /lib64/security/pam_pwquality.so"
        in effective["thresholds"]["logging"]["exclude_patterns"]
    )
    assert any(check["id"] == "logging_health" for check in effective["checks"])


def test_profile_rejects_duplicate_check_ids(tmp_path):
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        yaml.safe_dump(
            {
                "api_version": "alred/v1",
                "kind": "HealthCheckProfile",
                "metadata": {"name": "duplicate", "version": "1"},
                "spec": {
                    "platforms": ["nxos"],
                    "checks": [
                        {
                            "id": "cpu_utilization",
                            "evaluator": "cpu_utilization",
                            "severity": "warn",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileResolutionError, match="unique"):
        _resolved(["network-baseline-nxos", str(duplicate)])


def test_interface_utilization_threshold_order_is_validated(tmp_path):
    override = tmp_path / "invalid-interface-utilization.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "api_version": "alred/v1",
                "kind": "HealthCheckProfile",
                "metadata": {"name": "invalid-utilization", "version": "1"},
                "spec": {
                    "platforms": ["nxos"],
                    "thresholds": {
                        "interface_utilization": {
                            "info_percent": 70,
                            "warn_percent": 60,
                            "fail_percent": 90,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileResolutionError, match="info_percent"):
        _resolved(["network-baseline-nxos", str(override)])


def test_phase3_nxos_parsers_normalize_environment_routes_and_neighbors():
    environment, _profiles = parse_nxos_command(
        "environment",
        (NXOS_FIXTURES / "show_environment" / "c9300v_10_5_4_virtual.txt").read_text(
            encoding="utf-8"
        ),
    )
    routes, _profiles = parse_nxos_command(
        "route_summary_ipv4",
        (NXOS_FIXTURES / "show_route_summary_ipv4" / "c9300v_10_5_4.txt").read_text(
            encoding="utf-8"
        ),
    )
    ospf, _profiles = parse_nxos_command(
        "ospf_neighbors",
        (NXOS_FIXTURES / "show_ospf_neighbors" / "c9300v_10_5_4_full.txt").read_text(
            encoding="utf-8"
        ),
    )
    bgp, _profiles = parse_nxos_command(
        "bgp_ipv4_summary",
        (NXOS_FIXTURES / "show_bgp_ipv4_summary" / "c9300v_10_5_4_idle.txt").read_text(
            encoding="utf-8"
        ),
    )

    assert environment["environment"]["applicable"] is False
    assert routes["routes"]["ipv4_summary"]["vrfs"]["default"]["routes"] == 36
    process = ospf["routing_neighbors"]["ospf"]["processes"]["UNDERLAY@default"]
    assert process["reported_total"] == 2
    assert all(
        neighbor["state"] == "FULL" for neighbor in process["neighbors"].values()
    )
    bgp_default = bgp["routing_neighbors"]["bgp_ipv4"]["vrfs"]["default"]
    assert bgp_default["configured_peers"] == 1
    assert bgp_default["neighbors"]["192.0.2.254"]["state"] == "Idle"


def test_interface_utilization_parser_and_threshold_boundaries():
    parsed, _profiles = parse_nxos_command(
        "interface_counters_table",
        (
            NXOS_FIXTURES
            / "show_interface_counters_table"
            / "c9300v_10_5_4.txt"
        ).read_text(encoding="utf-8"),
    )
    eth11 = parsed["interface_utilization"]["interfaces"]["Ethernet1/1"]
    assert eth11 == {
        "description": "uplink",
        "input_mbps": 5000.0,
        "input_percent": 50.0,
        "output_mbps": 2500.0,
        "output_percent": 25.0,
        "input_load_interval_seconds": 30,
        "output_load_interval_seconds": 30,
        "load_interval_seconds": 30,
    }
    assert parsed["interface_utilization"]["interfaces"]["Ethernet1/2"][
        "description"
    ] is None
    assert parsed["interface_utilization"]["interfaces"]["Ethernet1/3"] == {
        "description": "edge-node-001",
        "input_mbps": 1.0,
        "input_percent": 0.1,
        "output_mbps": 2.0,
        "output_percent": 0.2,
        "input_load_interval_seconds": 30,
        "output_load_interval_seconds": 30,
        "load_interval_seconds": 30,
    }

    legacy, _profiles = parse_nxos_command(
        "interface_counters_table",
        (
            NXOS_FIXTURES
            / "show_interface_counters_table"
            / "legacy_inrate_columns.txt"
        ).read_text(encoding="utf-8"),
    )
    assert legacy["interface_utilization"]["interfaces"]["Eth1/1"][
        "input_percent"
    ] == 50.0

    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["interface_utilization"] = parsed[
        "interface_utilization"
    ]
    evaluated = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    finding = next(
        check
        for check in evaluated["checks"]
        if check["check_id"] == "interface_utilization"
    )
    assert finding["result"] == "PASS"
    assert finding["display_severity"] == "INFO"
    assert finding["after"]["peak_interface"] == "Ethernet1/1"

    snapshot = _snapshot(resolved)
    rates = snapshot["hosts"]["leaf01"]["common"]["interface_utilization"][
        "interfaces"
    ]["Eth1/1"]
    for percent, expected, display in (
        (49.99, "PASS", None),
        (50, "PASS", "INFO"),
        (69.99, "PASS", "INFO"),
        (70, "WARN", None),
        (89.99, "WARN", None),
        (90, "FAIL", None),
    ):
        rates["input_percent"] = percent
        result = evaluate_snapshot(
            snapshot,
            resolved,
            started_at=JST_NOW,
            completed_at=JST_NOW,
        )
        finding = next(
            check
            for check in result["checks"]
            if check["check_id"] == "interface_utilization"
        )
        assert finding["result"] == expected
        assert finding.get("display_severity") == display

    with pytest.raises(ParserError, match="non-numeric"):
        parse_nxos_command(
            "interface_counters_table",
            "Port      Description  Interval  InRate(Mbps)  InRate(%)  "
            "OutRate(Mbps)  OutRate(%)\n"
            "Eth1/1    uplink       30        unavailable   10.0       "
            "20.0           30.0\n",
        )


def test_dynamic_bgp_ranges_warn_when_empty_and_fail_on_regression():
    config_text = """\
router bgp 65001
  neighbor 172.16.3.0/24
    remote-as 65002
    address-family ipv4 unicast
  neighbor fd21:0:0:3::/64
    remote-as 65002
    address-family ipv6 unicast
"""
    config, _profiles = parse_nxos_command("running_config", config_text)
    assert {
        address
        for address in config["routing_neighbor_config"]["processes"]["65001"][
            "vrfs"
        ]["default"]["neighbors"]
    } == {"172.16.3.0/24", "fd21:0:0:3::/64"}

    resolved = _resolved()
    after = _snapshot(resolved, phase="after")
    common = after["hosts"]["leaf01"]["common"]
    common.update(config)
    common["routing_neighbors"] = {
        "bgp_ipv4": {
            "applicable": True,
            "vrfs": {
                "default": {
                    "configured_peers": 1,
                    "capable_peers": 0,
                    "neighbors": {},
                }
            },
        },
        "bgp_ipv6": {
            "applicable": True,
            "vrfs": {
                "default": {
                    "configured_peers": 1,
                    "capable_peers": 1,
                    "neighbors": {
                        "fd21:0:0:3::10": {"state": "Established"}
                    },
                }
            },
        },
    }
    after["hosts"]["leaf01"]["sources"].update(
        _sources("running_config", "bgp_ipv4_summary", "bgp_ipv6_summary")
    )
    evaluated = evaluate_snapshot(
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    finding = next(
        check
        for check in evaluated["checks"]
        if check["check_id"] == "bgp_dynamic_neighbor_health"
    )
    assert finding["result"] == "WARN"
    assert finding["after"]["ranges"][0]["matched_neighbors"] == []

    before = deepcopy(after)
    before["phase"] = "before"
    before["hosts"]["leaf01"]["common"]["routing_neighbors"]["bgp_ipv4"][
        "vrfs"
    ]["default"]["neighbors"] = {
        "172.16.3.10": {"state": "Established"}
    }
    compared = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    finding = next(
        check
        for check in compared["checks"]
        if check["check_id"] == "bgp_dynamic_neighbor_health"
    )
    assert finding["result"] == "FAIL"
    assert finding["classification"] == "regression"


def test_running_config_diff_parser_and_health_check_warn_on_unsaved_config():
    clean, _profiles = parse_nxos_command("running_config_diff", "")
    changed, _profiles = parse_nxos_command(
        "running_config_diff",
        "interface Ethernet1/1\n  description unsaved",
    )

    assert clean["running_config_diff"]["different"] is False
    assert changed["running_config_diff"] == {
        "different": True,
        "line_count": 2,
        "output_sha256": changed["running_config_diff"]["output_sha256"],
    }

    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["running_config_diff"] = changed[
        "running_config_diff"
    ]
    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    finding = next(
        check
        for check in result["checks"]
        if check["check_id"] == "running_config_diff"
    )
    assert finding["result"] == "WARN"
    assert "2 non-empty output lines" in finding["message"]


def test_single_snapshot_evaluates_baseline_and_cpu_threshold_inclusively():
    resolved = _resolved()
    snapshot = _snapshot(resolved)

    healthy = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    assert healthy["result"] == "PASS"
    assert healthy["counts"] == {
        "pass": 14,
        "warn": 0,
        "fail": 0,
        "unknown": 0,
        "not_applicable": 6,
    }


def test_nxos_profile_is_not_executed_for_eos_host():
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["platform"] = "eos"
    snapshot["hosts"]["leaf01"]["common"]["system"]["platform"] = "eos"

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    assert result["checks"] == []
    assert result["result"] == "NOT_APPLICABLE"
    assert result["unexecuted_hosts"] == [
        {
            "host": "leaf01",
            "platform": "eos",
            "topology_role": None,
            "profile": "network-baseline-nxos",
            "profile_result": "NOT_APPLICABLE",
            "reason_code": "PROFILE_PLATFORM_EXCLUDED",
            "message": "Host platform is outside the profile scope.",
        }
    ]


def test_health_hostname_identity_requires_exact_inventory_match():
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["system"][
        "reported_hostname"
    ] = "leaf02"

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    finding = next(
        check
        for check in result["checks"]
        if check["check_id"] == "hostname_identity"
    )
    assert finding["result"] == "FAIL"
    assert finding["after"] == {
        "expected_hostname": "leaf01",
        "reported_hostname": "leaf02",
    }

    snapshot["hosts"]["leaf01"]["common"]["cpu"]["one_minute_percent"] = 80
    warning = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    cpu = next(
        check for check in warning["checks"] if check["check_id"] == "cpu_utilization"
    )
    assert cpu["result"] == "WARN"
    assert cpu["classification"] == "pre_existing"
    assert warning["operation_gate"]["required"] is False

    snapshot["hosts"]["leaf01"]["common"]["cpu"]["samples"] = [82, 85, 84]
    sustained = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    assert sustained["operation_gate"]["required"] is True
    assert sustained["operation_gate"]["reasons"][0]["code"] == ("SUSTAINED_HIGH_CPU")


def test_additional_baseline_parsers_and_evaluators_cover_device_health():
    clock, _ = parse_nxos_command(
        "clock",
        "10:02:03.000 JST Sun Aug 2 2026",
        timezone="Asia/Tokyo",
    )
    ntp, _ = parse_nxos_command(
        "ntp_status",
        "Clock is synchronized, stratum 3, reference is 192.0.2.123",
    )
    peers, _ = parse_nxos_command(
        "ntp_peers",
        "*192.0.2.123  .GPS.  1 u 20 64 377 0.123 0.100 0.050",
    )
    interfaces, _ = parse_nxos_command(
        "interface_status",
        "Eth1/1 uplink connected trunk full 10G\nEth1/2 server notconnect 10 full 10G",
    )
    errors, _ = parse_nxos_command(
        "interface_errors",
        "Port Align-Err FCS-Err Xmit-Err Rcv-Err\nEth1/1 0 0 0 0",
    )
    channels, _ = parse_nxos_command(
        "port_channel_summary",
        "1 Po1(SU) Eth LACP Eth1/1(P) Eth1/2(P)",
    )
    ntp_disabled, _ = parse_nxos_command(
        "ntp_status",
        "Distribution : Disabled\nLast operational state: No session",
    )
    ntp_clock, _ = parse_nxos_command(
        "clock",
        "10:02:03.000 JST Sun Aug 2 2026\nTime source is NTP",
        timezone="Asia/Tokyo",
    )
    no_peers, _ = parse_nxos_command("ntp_peers", "")
    peer_status, _ = parse_nxos_command(
        "ntp_peer_status",
        (
            NXOS_FIXTURES
            / "show_ntp_peer_status"
            / "c9300v_10_5_4_selected.txt"
        ).read_text(encoding="utf-8"),
    )
    virtual_peer_link, _ = parse_nxos_command(
        "port_channel_summary",
        "1 Po1(SU) Eth NONE --",
    )
    no_channels, _ = parse_nxos_command("port_channel_summary", "")

    assert clock["clock"]["timestamp"] == JST_NOW.isoformat()
    assert ntp["ntp"]["synchronized"] is True
    assert peers["ntp"]["peers"]["192.0.2.123"]["selected"] is True
    assert interfaces["interfaces"]["Eth1/2"]["operational_state"] == "down"
    assert errors["interface_errors"]["Eth1/1"]["FCS-Err"] == 0
    assert channels["port_channels"]["channels"]["Po1"]["bundled_members"] == [
        "Eth1/1",
        "Eth1/2",
    ]
    assert ntp_disabled["ntp"] == {
        "synchronized": False,
        "operational_state": "No session",
    }
    assert ntp_clock["clock"]["time_source"] == "NTP"
    assert no_peers["ntp"]["peers"] == {}
    assert peer_status["ntp"]["peer_status"]["peers"][
        "192.168.129.254"
    ] == {
        "selected": True,
        "mode": "selected",
        "marker": "*",
        "local": "192.168.129.81",
        "stratum": 3,
        "poll": 64,
        "reach": 377,
        "delay": 0.123,
        "vrf": "management",
    }
    assert virtual_peer_link["port_channels"]["channels"]["Po1"] == {
        "flags": "SU",
        "up": True,
        "protocol": "NONE",
        "member_check_applicable": False,
        "members": {},
        "bundled_members": [],
    }
    assert no_channels["port_channels"] == {
        "applicable": False,
        "channels": {},
    }

    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"].update(
        {
            **clock,
            **ntp,
            "ntp": {
                **ntp["ntp"],
                **peers["ntp"],
                **peer_status["ntp"],
            },
            **interfaces,
            **errors,
            **channels,
        }
    )
    result = evaluate_snapshot(snapshot, resolved, started_at=JST_NOW, completed_at=JST_NOW)
    findings = {item["check_id"]: item for item in result["checks"]}
    assert findings["clock_health"]["result"] == "PASS"
    assert findings["ntp_health"]["result"] == "PASS"
    assert findings["interface_health"]["result"] == "FAIL"
    assert findings["interface_error_health"]["result"] == "PASS"
    assert findings["port_channel_health"]["result"] == "PASS"

    configured_no_session = _snapshot(resolved)
    configured_host = configured_no_session["hosts"]["leaf01"]
    configured_host["common"]["ntp"] = {
        **ntp_disabled["ntp"],
        "peers": {
            "192.168.129.254": {"selected": False, "marker": None}
        },
    }
    configured_host["common"]["clock"] = ntp_clock["clock"]
    configured_result = evaluate_snapshot(
        configured_no_session,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    configured_check = next(
        check
        for check in configured_result["checks"]
        if check["check_id"] == "ntp_health"
    )
    assert configured_check["result"] == "WARN"
    assert configured_check["after"]["configured"] is True
    assert configured_check["after"]["clock_time_source"] == "NTP"
    assert configured_check["message"] == (
        "NTP is configured but unsynchronized "
        "(operational state: No session; no selected peer; clock time source: NTP)"
    )


def test_interface_status_normalizes_nxos_truncated_not_connected_state():
    interfaces, _ = parse_nxos_command(
        "interface_status",
        (
            NXOS_FIXTURES
            / "show_interface_status"
            / "c9300v_10_5_4_not_connected.txt"
        ).read_text(encoding="utf-8"),
    )

    assert interfaces["interfaces"]["Eth1/49"] == {
        "admin_state": "up",
        "operational_state": "down",
        "status": "notconnect",
    }
    assert interfaces["interfaces"]["Eth1/50"] == {
        "admin_state": "down",
        "operational_state": "down",
        "status": "disabled",
    }

    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"].update(interfaces)
    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    check = next(
        item for item in result["checks"] if item["check_id"] == "interface_health"
    )

    assert check["result"] == "FAIL"
    assert check["classification"] == "target_not_ready"
    assert check["after"]["admin_up_oper_down"] == ["Eth1/49"]
    assert check["message"] == "Admin-up interfaces are down: Eth1/49"


def test_interface_status_rejects_unknown_state_instead_of_partial_pass():
    output = """\
Port                Name               Status    Vlan      Duplex  Speed   Type
Eth1/1              uplink             connected trunk     full    1000    10g
Eth1/2              --                 mystery   1         auto    auto    10g
"""

    with pytest.raises(
        ParserError,
        match=r"unsupported interface status row\(s\): Eth1/2=mystery",
    ):
        parse_nxos_command("interface_status", output)

    resolved = _resolved()
    snapshot = _snapshot(resolved)
    host = snapshot["hosts"]["leaf01"]
    host["common"]["interfaces"] = {
        "Vlan10": {
            "admin_state": "up",
            "operational_state": "up",
            "status": "connected",
        }
    }
    host["sources"]["interface_status"].update(
        parse_status="unknown",
        parse_warning="unsupported interface status row(s): Eth1/2=mystery",
    )
    host["sources"]["interface_brief"] = {
        "status": "success",
        "parse_status": "parsed",
        "command": "show interface brief",
        "file": "/fixtures/interface_brief.txt",
        "sha256": "b" * 64,
    }
    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    check = next(
        item for item in result["checks"] if item["check_id"] == "interface_health"
    )

    assert check["result"] == "UNKNOWN"
    assert check["classification"] == "collection_error"
    assert check["message"] == "Interface status could not be parsed"


def test_baseline_command_ids_connect_collected_health_outputs() -> None:
    assert {
        command: command_id(command)
        for command in (
            "show clock",
            "show ntp status",
            "show ntp peers",
            "show ntp peer-status",
            "show interface status",
            "show interface counters errors non-zero",
            "show port-channel summary",
            "show running-config diff",
            "show running-config diff unified",
        )
    } == {
        "show clock": "clock",
        "show ntp status": "ntp_status",
        "show ntp peers": "ntp_peers",
        "show ntp peer-status": "ntp_peer_status",
        "show interface status": "interface_status",
        "show interface counters errors non-zero": "interface_errors",
        "show port-channel summary": "port_channel_summary",
        "show running-config diff": "running_config_diff",
        "show running-config diff unified": "running_config_diff",
    }


def test_uncollected_baseline_health_evidence_is_unknown() -> None:
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    host = snapshot["hosts"]["leaf01"]
    for field in (
        "clock",
        "ntp",
        "interfaces",
        "interface_errors",
        "port_channels",
    ):
        host["common"].pop(field, None)
    for identifier in (
        "clock",
        "ntp_status",
        "ntp_peers",
        "ntp_peer_status",
        "interface_status",
        "interface_errors",
        "port_channel_summary",
    ):
        host["sources"].pop(identifier, None)

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    checks = {check["check_id"]: check for check in result["checks"]}

    for check_id in (
        "clock_health",
        "ntp_health",
        "interface_health",
        "interface_error_health",
        "port_channel_health",
    ):
        assert checks[check_id]["result"] == "UNKNOWN"
        assert checks[check_id]["classification"] == "collection_error"


def test_ntp_peer_status_unsupported_falls_back_to_primary_evidence() -> None:
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["sources"]["ntp_peer_status"] = {
        "status": "success",
        "parse_status": "unknown",
        "parse_warning": "NX-OS command returned an error",
    }

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    check = next(
        item for item in result["checks"] if item["check_id"] == "ntp_health"
    )

    assert check["result"] == "PASS"
    assert check["message"] == "NTP is synchronized to 192.0.2.123"


def test_additional_baseline_compare_detects_device_health_regressions():
    resolved = _resolved()
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    after["collection_id"] = "CHG-1-after-001"
    before_common = before["hosts"]["leaf01"]["common"]
    after_common = after["hosts"]["leaf01"]["common"]
    before_common["port_channels"] = {
        "applicable": True,
        "channels": {"Po1": {"up": True, "bundled_members": ["Eth1/1", "Eth1/2"]}},
    }
    before_common["interface_errors"] = {"Eth1/1": {"FCS-Err": 0}}
    after_common["interfaces"]["Eth1/1"]["operational_state"] = "down"
    after_common["ntp"]["synchronized"] = False
    after_common["interface_errors"] = {"Eth1/1": {"FCS-Err": 100}}
    after_common["port_channels"] = {
        "applicable": True,
        "channels": {"Po1": {"up": True, "bundled_members": ["Eth1/1"]}},
    }

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )
    findings = {item["check_id"]: item for item in result["checks"]}
    for check_id in (
        "interface_health",
        "ntp_health",
        "interface_error_health",
        "port_channel_health",
    ):
        assert findings[check_id]["result"] == "FAIL"
        assert findings[check_id]["classification"] == "regression"

def test_logging_before_warns_and_honors_include_exclude_patterns():
    resolved = _resolved()
    settings = resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"][
        "logging"
    ]
    settings["severity_threshold"] = 3
    settings["include_patterns"] = ["special-event"]
    settings["exclude_patterns"] = ["expected-noise"]
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["logging"]["records"] = [
        _logging_record(
            "2026-08-02T09:50:00+09:00",
            6,
            "%APP-6-INFO: special-event observed",
        ),
        _logging_record(
            "2026-08-02T09:51:00+09:00",
            2,
            "%APP-2-CRITICAL: expected-noise",
        ),
    ]

    result = evaluate_snapshot(
        snapshot, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "logging_health"
    )
    assert (finding["result"], finding["classification"]) == (
        "WARN",
        "pre_existing",
    )
    assert finding["after"]["matched_records"] == 1
    assert finding["after"]["matches"][0]["match_reasons"] == [
        "include-pattern:special-event"
    ]


def test_show_logging_accepts_hyphenated_facility_and_unstructured_records():
    common, _profiles = parse_nxos_command(
        "show_logging",
        """\
2026 Aug 02 16:02:21 leaf01 %USER-SLOT1-5-SYSTEM_MSG: LC_ONLINE
2026 Aug 02 16:02:22 leaf01 %ASCII-CFG-2-CONF_CONTROL: System ready
2026 Aug 02 16:02:33 leaf01 nve: Warning: Advertise-pip is recommended.
""",
    )

    logging = common["logging"]
    assert logging["parse_warnings"] == []
    assert [record["severity"] for record in logging["records"]] == [5, 2, None]
    assert all(record["parse_warnings"] == [] for record in logging["records"])


def test_unstructured_logging_record_can_be_selected_by_include_pattern():
    resolved = _resolved()
    settings = resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"][
        "logging"
    ]
    settings["include_patterns"] = ["warning:"]
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["logging"]["records"] = [
        {
            **_logging_record(
                "2026-08-02T09:50:00+09:00",
                6,
                "2026 Aug 02 09:50:00 leaf01 nve: Warning: check configuration",
            ),
            "severity": None,
        }
    ]

    result = evaluate_snapshot(
        snapshot, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "logging_health"
    )
    assert finding["result"] == "WARN"
    assert finding["after"]["matches"][0]["match_reasons"] == [
        "include-pattern:warning:"
    ]


@pytest.mark.parametrize(
    ("time_range", "expected_matches"),
    [
        ({"mode": "all"}, 3),
        ({"mode": "days", "days": 2}, 2),
        (
            {
                "mode": "start-time",
                "start_time": "2026-08-02T00:00:00+09:00",
            },
            1,
        ),
    ],
)
def test_logging_time_range_modes(time_range, expected_matches):
    resolved = _resolved()
    settings = resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"][
        "logging"
    ]
    settings["severity_threshold"] = 4
    settings["time_range"] = time_range
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["logging"]["records"] = [
        _logging_record(
            "2026-07-20T09:50:00+09:00",
            3,
            "%APP-3-ERROR: old",
        ),
        _logging_record(
            "2026-08-01T09:50:00+09:00",
            3,
            "%APP-3-ERROR: recent",
        ),
        _logging_record(
            "2026-08-02T09:50:00+09:00",
            3,
            "%APP-3-ERROR: current",
        ),
    ]

    result = evaluate_snapshot(
        snapshot, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "logging_health"
    )
    assert finding["after"]["matched_records"] == expected_matches
    assert finding["after"]["time_range"] == time_range


def test_logging_start_time_rejects_future_boundary():
    resolved = _resolved()
    resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"]["logging"][
        "time_range"
    ] = {
        "mode": "start-time",
        "start_time": "2026-08-02T23:59:59+09:00",
    }

    with pytest.raises(HealthEvaluationError, match="later than"):
        evaluate_snapshot(
            _snapshot(resolved),
            resolved,
            started_at=JST_NOW,
            completed_at=JST_NOW,
        )


def test_logging_compare_warns_only_for_new_operation_window_records():
    resolved = _resolved()
    before = _snapshot(resolved)
    baseline = _logging_record(
        "2026-08-02T09:30:00+09:00",
        4,
        "%APP-4-WARNING: existing baseline",
    )
    before["hosts"]["leaf01"]["common"]["logging"]["records"] = [baseline]
    after = deepcopy(before)
    after["phase"] = "after"
    after["collection_id"] = "CHG-1-after-001"
    after["created_at"] = "2026-08-02T10:05:00+09:00"

    unchanged = compare_snapshots(
        before, after, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )
    unchanged_finding = next(
        check for check in unchanged["checks"] if check["check_id"] == "logging_health"
    )
    assert (
        unchanged_finding["result"],
        unchanged_finding["classification"],
    ) == ("PASS", "pre_existing")

    after["hosts"]["leaf01"]["common"]["logging"]["records"].append(
        _logging_record(
            "2026-08-02T10:03:00+09:00",
            3,
            "%APP-3-ERROR: new operation failure",
        )
    )
    changed = compare_snapshots(
        before, after, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )
    changed_finding = next(
        check for check in changed["checks"] if check["check_id"] == "logging_health"
    )
    assert (changed_finding["result"], changed_finding["classification"]) == (
        "WARN",
        "regression",
    )
    assert changed_finding["after"]["matched_records"] == 1


def test_logging_parse_warning_is_unknown():
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["logging"]["parse_warnings"] = [
        "severity not found"
    ]

    result = evaluate_snapshot(
        snapshot, resolved, started_at=JST_NOW, completed_at=JST_NOW
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "logging_health"
    )
    assert finding["result"] == "UNKNOWN"
    assert finding["classification"] == "collection_error"


def test_cpu_consecutive_assessment_resets_below_threshold():
    assessment = assess_cpu_samples(
        [82, 85, 79, 84],
        threshold=80,
        required_consecutive=3,
    )

    assert assessment["threshold_exceeded"] is True
    assert assessment["longest_consecutive"] == 2
    assert assessment["sustained"] is False


def test_missing_required_parser_is_unknown_not_pass():
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    del snapshot["hosts"]["leaf01"]["sources"]["processes_cpu"]
    del snapshot["hosts"]["leaf01"]["common"]["cpu"]

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    assert result["result"] == "UNKNOWN"
    collection = next(
        check
        for check in result["checks"]
        if check["check_id"] == "collection_complete"
    )
    assert collection["result"] == "UNKNOWN"
    assert "processes_cpu" in collection["message"]


def test_overlay_optional_commands_use_running_config_for_applicability():
    resolved = _resolved(["network-baseline-nxos", "nxos-overlay"])
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
        "config": {
            "nve": {"configured": False},
            "evpn_bgp_configured": False,
        }
    }
    snapshot["hosts"]["leaf01"]["sources"].update(_sources("running_config"))

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    findings = {check["check_id"]: check for check in result["checks"]}
    assert findings["collection_complete"]["result"] == "PASS"
    assert findings["nve_interface_health"]["result"] == "NOT_APPLICABLE"
    assert findings["evpn_bgp_health"]["result"] == "NOT_APPLICABLE"


def test_overlay_configured_but_unobserved_state_is_unknown():
    resolved = _resolved(["network-baseline-nxos", "nxos-overlay"])
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
        "config": {
            "nve": {"configured": True},
            "evpn_bgp_configured": True,
        }
    }
    snapshot["hosts"]["leaf01"]["sources"].update(_sources("running_config"))

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    findings = {check["check_id"]: check for check in result["checks"]}
    assert findings["nve_interface_health"]["result"] == "UNKNOWN"
    assert findings["evpn_bgp_health"]["result"] == "UNKNOWN"


def test_bgp_capable_count_is_metadata_when_observed_peers_are_established():
    resolved = _resolved()
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["common"]["routing_neighbors"] = {
        "bgp_ipv4": {
            "applicable": True,
            "vrfs": {
                "TENANT-A": {
                    "configured_peers": 2,
                    "capable_peers": 1,
                    "neighbors": {
                        "192.0.2.1": {"state": "Established"},
                    },
                }
            },
        }
    }
    snapshot["hosts"]["leaf01"]["common"]["routing_neighbor_config"] = {
        "processes": {
            "65001": {
                "vrfs": {
                    "TENANT-A": {
                        "neighbors": {
                            "192.0.2.1": {
                                "address_families": {"ipv4-unicast": {}},
                                "resolution_status": "resolved",
                            }
                        }
                    }
                }
            }
        }
    }
    snapshot["hosts"]["leaf01"]["sources"].update(_sources("bgp_ipv4_summary"))

    result = evaluate_snapshot(
        snapshot,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "bgp_ipv4_health"
    )
    assert finding["result"] == "PASS"
    assert "statically configured IPv4 BGP peers" in finding["message"]
    assert json.loads(json.dumps(result))["result"] == result["result"]


def test_compare_classifies_cpu_and_reload_regressions():
    resolved = _resolved()
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    after["collection_id"] = "CHG-1-after-001"
    after["hosts"]["leaf01"]["common"]["cpu"]["one_minute_percent"] = 90
    after["hosts"]["leaf01"]["common"]["reload_pending"] = {
        "required": True,
        "commands": ["hardware profile example"],
    }

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    assert result["result"] == "FAIL"
    cpu = next(
        check for check in result["checks"] if check["check_id"] == "cpu_utilization"
    )
    reload_check = next(
        check for check in result["checks"] if check["check_id"] == "reload_pending"
    )
    assert (cpu["result"], cpu["classification"]) == ("WARN", "regression")
    assert (reload_check["result"], reload_check["classification"]) == (
        "FAIL",
        "regression",
    )


def test_compare_detects_route_ospf_and_bgp_neighbor_regressions():
    resolved = _resolved()
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    before_routing = before["hosts"]["leaf01"]["common"].setdefault(
        "routing_neighbors",
        {},
    )
    after_routing = after["hosts"]["leaf01"]["common"].setdefault(
        "routing_neighbors",
        {},
    )
    before_routing["ospf"] = {
        "applicable": True,
        "processes": {
            "UNDERLAY@default": {
                "process_id": "UNDERLAY",
                "vrf": "default",
                "reported_total": 1,
                "neighbors": {
                    "192.0.2.253": {
                        "state": "FULL",
                        "uptime": "00:10:00",
                        "address": "192.0.2.1",
                        "interface": "Eth1/1",
                    }
                },
            }
        },
    }
    after_routing["ospf"] = {
        "applicable": True,
        "processes": {
            "UNDERLAY@default": {
                "process_id": "UNDERLAY",
                "vrf": "default",
                "reported_total": 1,
                "neighbors": {
                    "192.0.2.253": {
                        "state": "DOWN",
                        "uptime": "00:00:01",
                        "address": "192.0.2.1",
                        "interface": "Eth1/1",
                    }
                },
            }
        },
    }
    before_routing["bgp_ipv4"] = {
        "applicable": True,
        "vrfs": {
            "default": {
                "configured_peers": 1,
                "capable_peers": 1,
                "neighbors": {
                    "192.0.2.254": {
                        "state": "Established",
                        "prefixes_received": 10,
                    }
                },
            }
        },
    }
    after_routing["bgp_ipv4"] = {
        "applicable": True,
        "vrfs": {
            "default": {
                "configured_peers": 1,
                "capable_peers": 0,
                "neighbors": {
                    "192.0.2.254": {
                        "state": "Idle",
                        "prefixes_received": None,
                    }
                },
            }
        },
    }
    before["hosts"]["leaf01"]["sources"].update(
        _sources("ospf_neighbors", "bgp_ipv4_summary")
    )
    after["hosts"]["leaf01"]["sources"].update(
        _sources("ospf_neighbors", "bgp_ipv4_summary")
    )
    after["hosts"]["leaf01"]["common"]["routes"]["ipv4_summary"]["vrfs"]["default"][
        "routes"
    ] = 20

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    findings = {check["check_id"]: check for check in result["checks"]}
    assert findings["ipv4_route_count"]["result"] == "FAIL"
    assert findings["ospf_neighbor_health"]["classification"] == "regression"
    assert findings["bgp_ipv4_health"]["classification"] == "regression"


def test_compare_accepts_added_vrf_and_preserves_existing_route_counts():
    resolved = _resolved()
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    after["hosts"]["leaf01"]["common"]["routes"]["ipv4_summary"]["vrfs"]["NEW-VRF"] = {
        "routes": 7,
        "paths": 7,
    }

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    finding = next(
        check for check in result["checks"] if check["check_id"] == "ipv4_route_count"
    )
    assert finding["result"] == "PASS"
    assert "added VRFs: NEW-VRF" in finding["message"]


def test_compare_treats_unconfigured_nve_as_not_applicable():
    resolved = _resolved(["network-baseline-nxos", "nxos-overlay"])
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    for snapshot in (before, after):
        snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
            "config": {
                "nve": {"configured": False},
                "evpn_bgp_configured": True,
            }
        }

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    finding = next(
        check
        for check in result["checks"]
        if check["check_id"] == "nve_interface_health"
    )
    assert finding["result"] == "NOT_APPLICABLE"


def test_compare_treats_unconfigured_evpn_as_not_applicable():
    resolved = _resolved(["network-baseline-nxos", "nxos-overlay"])
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    for snapshot in (before, after):
        snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
            "config": {
                "nve": {"configured": False},
                "evpn_bgp_configured": False,
            }
        }
        snapshot["hosts"]["leaf01"]["sources"].update(
            _sources("running_config")
        )

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    finding = next(
        check
        for check in result["checks"]
        if check["check_id"] == "evpn_bgp_health"
    )
    assert finding["result"] == "NOT_APPLICABLE"
    assert finding["classification"] == "normal"
    assert finding["message"] == "EVPN BGP is not configured"


def test_compare_keeps_missing_evpn_state_unknown_when_only_one_side_is_configured():
    resolved = _resolved(["network-baseline-nxos", "nxos-overlay"])
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    before["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
        "config": {
            "nve": {"configured": False},
            "evpn_bgp_configured": False,
        }
    }
    after["hosts"]["leaf01"]["profiles"]["nxos-overlay"] = {
        "config": {
            "nve": {"configured": True},
            "evpn_bgp_configured": True,
        }
    }

    result = compare_snapshots(
        before,
        after,
        resolved,
        started_at=JST_NOW,
        completed_at=JST_NOW,
    )

    finding = next(
        check
        for check in result["checks"]
        if check["check_id"] == "evpn_bgp_health"
    )
    assert finding["result"] == "UNKNOWN"


def test_compare_rejects_profile_and_host_mismatch():
    resolved = _resolved()
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    after["profile_sha256"] = "sha256:" + "0" * 64

    with pytest.raises(HealthEvaluationError, match="profile hash"):
        compare_snapshots(
            before,
            after,
            resolved,
            started_at=JST_NOW,
            completed_at=JST_NOW,
        )

    after = deepcopy(before)
    after["phase"] = "after"
    after["hosts"]["leaf02"] = after["hosts"].pop("leaf01")
    with pytest.raises(HealthEvaluationError, match="host set"):
        compare_snapshots(
            before,
            after,
            resolved,
            started_at=JST_NOW,
            completed_at=JST_NOW,
        )


def test_snapshot_and_compare_cli_write_reports_and_return_health_exit_codes(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    before_input = tmp_path / "before" / "show_lists" / "leaf01" / "leaf01_shows.log"
    after_input = tmp_path / "after" / "show_lists" / "leaf01" / "leaf01_shows.log"
    _write_collect(before_input)
    high_cpu = (
        BASELINE_COMMAND_FIXTURES["show processes cpu"]
        .read_text(encoding="utf-8")
        .replace("one minute: 50%", "one minute: 90%")
    )
    pending = (
        "Following config commands require copy r s + reload :\n"
        "======================================================\n"
        "0 hardware profile example\n"
        "======================================================\n"
    )
    _write_collect(after_input, cpu_fixture=high_cpu, reload_output=pending)

    before_args = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(tmp_path / "before"),
            "--input-format",
            "alred-collect",
            "--phase",
            "before",
            "--change-id",
            "CHG-1",
            "--profile",
            "network-baseline-nxos",
            "--logging-days",
            "2",
            "--operations-root",
            str(operations_root),
        ]
    )
    assert cmd_health_check_snapshot(before_args) == 0
    latest = operations_root / "live" / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == open_operation_workspace(
        operations_root, "CHG-1"
    ).operation_root.resolve()
    operation_root = open_operation_workspace(
        operations_root, "CHG-1"
    ).operation_root

    resolved_document = yaml.safe_load(
        (operation_root / "health" / "resolved-profiles.yaml").read_text()
    )
    logging = resolved_document["spec"]["resolved"]["effective"]["spec"]["thresholds"][
        "logging"
    ]
    assert logging["time_range"] == {"mode": "days", "days": 2}
    before_recheck_args = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(tmp_path / "before"),
            "--input-format",
            "alred-collect",
            "--phase",
            "before",
            "--change-id",
            "CHG-1",
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
            "--recheck",
        ]
    )
    assert cmd_health_check_snapshot(before_recheck_args) == 0
    assert (
        operation_root / "health" / "before-recheck" / "health-result.json"
    ).is_file()
    after_args = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(tmp_path / "after"),
            "--input-format",
            "alred-collect",
            "--phase",
            "after",
            "--change-id",
            "CHG-1",
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
        ]
    )
    assert cmd_health_check_snapshot(after_args) == 1

    before_snapshot = operation_root / "health" / "before" / "snapshot.json"
    after_snapshot = operation_root / "health" / "after" / "snapshot.json"
    compare_args = build_parser().parse_args(
        [
            "health-check",
            "compare",
            "--before",
            str(before_snapshot),
            "--after",
            str(after_snapshot),
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
        ]
    )
    assert cmd_health_check_compare(compare_args) == 4

    report_dir = operation_root / "health" / "report"
    result = json.loads((report_dir / "health-result.json").read_text(encoding="utf-8"))
    assert result["result"] == "FAIL"
    assert (report_dir / "summary.md").is_file()
    assert "HEALTH CHECK COMPARE" in capsys.readouterr().out

    recheck_args = build_parser().parse_args(
        [
            "health-check",
            "compare",
            "--before",
            str(before_snapshot),
            "--after",
            str(after_snapshot),
            "--operations-root",
            str(operations_root),
            "--recheck",
        ]
    )
    assert cmd_health_check_compare(recheck_args) == 4
    assert (
        operation_root / "health" / "report-recheck" / "health-result.json"
    ).is_file()
