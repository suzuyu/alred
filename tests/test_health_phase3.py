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
from alred.health.profile import (
    ProfileResolutionError,
    resolve_profiles,
)
from alred.health.parsers import parse_nxos_command
from alred.health.report import render_health_checklist


JST_NOW = datetime.fromisoformat("2026-08-02T10:02:03+09:00")


def test_health_checklist_starts_with_times_and_groups_checks_by_device():
    result = {
        "change_id": "CHG-1",
        "phase": "before",
        "started_at": "2026-08-02T10:00:00+09:00",
        "completed_at": "2026-08-02T10:02:03+09:00",
        "result": "WARN",
        "checks": [
            {
                "host": "leaf02",
                "check_id": "cpu_utilization",
                "result": "WARN",
                "message": "CPU warning",
            },
            {
                "host": "leaf01",
                "check_id": "system_identity",
                "result": "PASS",
                "message": "System is healthy",
            },
            {
                "host": "leaf01",
                "check_id": "logging_health",
                "result": "PASS",
                "message": "No new logs",
            },
        ],
    }

    checklist = render_health_checklist(result)
    lines = checklist.splitlines()

    assert lines[2] == "- Started at: 2026-08-02T10:00:00+09:00"
    assert lines[3] == "- Completed at: 2026-08-02T10:02:03+09:00"
    assert checklist.index("### Device: `leaf01`") < checklist.index(
        "### Device: `leaf02`"
    )
    leaf01 = checklist.split("### Device: `leaf01`", 1)[1].split(
        "### Device: `leaf02`", 1
    )[0]
    assert "`system_identity`" in leaf01
    assert "`logging_health`" in leaf01
    assert "leaf01 /" not in leaf01


NXOS_FIXTURES = Path(__file__).parent / "fixtures" / "nxos"
BASELINE_COMMAND_FIXTURES = {
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
    "show logging": (NXOS_FIXTURES / "show_logging" / "c9300v_10_5_4_healthy.txt"),
    "show ip route summary vrf all": (
        NXOS_FIXTURES / "show_route_summary_ipv4" / "c9300v_10_5_4.txt"
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
                    "reload_pending": {
                        "required": False,
                        "commands": [],
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
                    "reload_pending",
                    "show_logging",
                    "route_summary_ipv4",
                    "vpc_brief",
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
        "nve_interface",
        "nve_vni",
        "nve_vni_ingress_replication",
        "bgp_l2vpn_evpn_summary",
        "running_config",
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
        "pass": 7,
        "warn": 0,
        "fail": 0,
        "unknown": 0,
        "not_applicable": 4,
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
    assert "observed IPv4 BGP peers" in finding["message"]


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

    resolved_document = yaml.safe_load(
        (operations_root / "CHG-1" / "health" / "resolved-profiles.yaml").read_text()
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
        operations_root / "CHG-1" / "health" / "before-recheck" / "health-result.json"
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

    before_snapshot = operations_root / "CHG-1" / "health" / "before" / "snapshot.json"
    after_snapshot = operations_root / "CHG-1" / "health" / "after" / "snapshot.json"
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

    report_dir = operations_root / "CHG-1" / "health" / "report"
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
        operations_root / "CHG-1" / "health" / "report-recheck" / "health-result.json"
    ).is_file()
