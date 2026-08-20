from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
from pathlib import Path

import pytest

from alred.health.device_summary import (
    DEVICE_SUMMARY_COLUMNS,
    build_device_summary_rows,
    render_device_summary_csv,
    render_device_summary_markdown,
)
from alred.health.parsers import ParserError, parse_nxos_command
from alred.health.snapshot import build_health_snapshot
from alred.inventory import load_inventory_data


NOW = datetime.fromisoformat("2026-08-17T10:00:00+09:00")
FIXTURES = Path(__file__).parent / "fixtures" / "nxos" / "device_summary"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ntc_inventory_and_license_usage_parsers_normalize_rows():
    inventory, _ = parse_nxos_command(
        "inventory",
        _fixture("show_inventory_n9k_c93180yc.txt"),
    )
    license_data, _ = parse_nxos_command(
        "license_usage",
        _fixture("show_license_usage_nxos10.txt"),
    )

    assert inventory["inventory"]["components"][0] == {
        "name": "Chassis",
        "description": "Nexus9000 C93180YC-EX Chassis",
        "product_id": "N9K-C93180YC-EX",
        "version_id": "V01",
        "serial_number": "SAL00000001",
    }
    assert len(inventory["inventory"]["components"]) == 3
    assert license_data == {
        "license": {
            "applicable": True,
            "usage": [
                {
                    "feature": "LAN_ENTERPRISE_SERVICES_PKG",
                    "installed": True,
                    "license_count": None,
                    "usage_status": "in_use",
                    "expiry_date": None,
                    "comments": None,
                },
                {
                    "feature": "VPN_FABRIC",
                    "installed": False,
                    "license_count": 0,
                    "usage_status": "unused",
                    "expiry_date": None,
                    "comments": None,
                },
            ],
        }
    }


def test_ntc_license_usage_parser_accepts_nxos9_style_fixture():
    license_data, _ = parse_nxos_command(
        "license_usage",
        _fixture("show_license_usage_nxos9.txt"),
    )

    assert [
        (item["feature"], item["installed"], item["usage_status"])
        for item in license_data["license"]["usage"]
    ] == [
        ("LAN_BASE_SERVICES_PKG", True, "in_use"),
        ("LAN_ENTERPRISE_SERVICES_PKG", False, "unused"),
    ]


def test_license_usage_parser_accepts_feature_block_format():
    license_data, _ = parse_nxos_command(
        "license_usage",
        _fixture("show_license_usage_block_nxos10.txt"),
    )

    assert license_data == {
        "license": {
            "applicable": True,
            "usage": [
                {
                    "feature": "LAN_ENTERPRISE_SERVICES_PKG",
                    "installed": True,
                    "license_count": 1,
                    "usage_status": "in_use",
                    "expiry_date": None,
                    "comments": None,
                },
                {
                    "feature": "VPN_FABRIC",
                    "installed": True,
                    "license_count": 1,
                    "usage_status": "unused",
                    "expiry_date": None,
                    "comments": None,
                },
            ],
        }
    }


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("Count: 1", "duplicate license usage block field"),
        ("Serial: redacted", "unrecognized license usage block line"),
        ("Count: unlimited", "unsupported license count"),
        ("Status: UNKNOWN", "unsupported license usage status"),
    ],
)
def test_license_usage_block_parser_fails_closed(replacement, message):
    output = _fixture("show_license_usage_block_nxos10.txt")
    if replacement == "Count: 1":
        output = output.replace("  Count: 1", "  Count: 1\n  Count: 1", 1)
    elif replacement == "Serial: redacted":
        output = output.replace(
            "  Version: 1.0",
            "  Version: 1.0\n  Serial: redacted",
            1,
        )
    elif replacement == "Count: unlimited":
        output = output.replace("  Count: 1", "  Count: unlimited", 1)
    else:
        output = output.replace("  Status: IN USE", "  Status: UNKNOWN", 1)

    with pytest.raises(ParserError, match=message):
        parse_nxos_command("license_usage", output)


def test_license_usage_parser_recognizes_explicit_not_applicable_output():
    license_data, _ = parse_nxos_command(
        "license_usage",
        "No licenses are installed\n",
    )

    assert license_data == {"license": {"applicable": False, "usage": []}}


@pytest.mark.parametrize(
    ("identifier", "output", "message"),
    [
        ("inventory", "", "command output is empty"),
        ("inventory", "NAME: Chassis", "inventory NAME/PID anchors"),
        (
            "license_usage",
            "Feature Status\nLAN_BASE in-use\n",
            "license usage heading",
        ),
        (
            "license_usage",
            "Feature Ins Lic Status Expiry Date Comments\n    Count\n",
            "license usage rows",
        ),
        (
            "license_usage",
            "License Authorization:\n  Status: Not Applicable\n",
            "license usage heading",
        ),
    ],
)
def test_ntc_device_summary_parsers_fail_closed(identifier, output, message):
    with pytest.raises(ParserError, match=message):
        parse_nxos_command(identifier, output)


def test_license_usage_parser_rejects_duplicate_features():
    output = _fixture("show_license_usage_nxos10.txt")
    output += "VPN_FABRIC                       Yes  1     In use             -\n"

    with pytest.raises(ParserError, match="duplicate license usage feature"):
        parse_nxos_command("license_usage", output)


def test_snapshot_records_device_summary_parser_provenance():
    inventory = FIXTURES / "show_inventory_n9k_c93180yc.txt"
    license_usage = FIXTURES / "show_license_usage_block_nxos10.txt"
    commands = {}
    for identifier, command, path in (
        ("inventory", "show inventory", inventory),
        ("license_usage", "show license usage", license_usage),
    ):
        commands[identifier] = {
            "status": "success",
            "collected_at": NOW.isoformat(),
            "file": str(path),
            "sha256": _sha256(path),
            "command": command,
            "normalized_command": command,
            "source": "alred_collect",
            "transport": "ssh",
        }
    manifest = {
        "api_version": "alred/v1",
        "kind": "CollectionManifest",
        "metadata": {
            "collection_id": "collection-001",
            "change_id": "CHG-DEVICE-SUMMARY",
            "phase": "before",
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "timezone": "Asia/Tokyo",
        },
        "spec": {
            "profiles": ["network-baseline-nxos"],
            "hosts": {
                "leaf01": {
                    "status": "success",
                    "address": "192.0.2.11",
                    "platform": "nxos",
                    "commands": commands,
                }
            },
        },
    }

    snapshot = build_health_snapshot(
        manifest,
        profile_refs=["network-baseline-nxos"],
        created_at=NOW,
        timezone="Asia/Tokyo",
    )

    assert snapshot["parser_versions"]["ntc_templates"]
    assert snapshot["parser_versions"]["textfsm"]
    for identifier in ("inventory", "license_usage"):
        source = snapshot["hosts"]["leaf01"]["sources"][identifier]
        assert source["parse_status"] == "parsed"
        assert source["parser_template"].endswith(".textfsm")
        assert source["parser_template_sha256"].startswith("sha256:")
    assert (
        snapshot["hosts"]["leaf01"]["sources"]["inventory"]["parser"]
        == "ntc_templates.inventory"
    )
    assert (
        snapshot["hosts"]["leaf01"]["sources"]["license_usage"]["parser"]
        == "nxos.license_usage"
    )


def _snapshot():
    return {
        "schema_version": 1,
        "change_id": "CHG-DEVICE-SUMMARY",
        "collection_id": "collection-001",
        "phase": "before",
        "created_at": NOW.isoformat(),
        "timezone": "Asia/Tokyo",
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            "leaf02": {
                "address": "192.0.2.12",
                "platform": "nxos",
                "collection_status": "partial",
                "common": {
                    "system": {
                        "model": "N9K-C93180YC-EX",
                        "version": "10.5(4)",
                    }
                },
                "profiles": {},
                "sources": {
                    "license_usage": {
                        "status": "failed",
                        "parse_status": "unknown",
                    }
                },
            },
            "leaf01": {
                "address": "192.0.2.11",
                "platform": "nxos",
                "collection_status": "success",
                "common": {
                    "system": {
                        "model": "N9K-C93180YC-EX | lab, row",
                        "version": "10.5(4)",
                    },
                    "inventory": {
                        "components": [
                            {
                                "name": "Chassis",
                                "product_id": "N9K-C93180YC-EX",
                                "serial_number": "SAL00000001",
                            },
                            {
                                "name": "Power Supply 1",
                                "serial_number": "DTM00000001",
                            },
                        ]
                    },
                    "license": {
                        "applicable": True,
                        "usage": [
                            {
                                "feature": "VPN_FABRIC",
                                "installed": False,
                                "license_count": 0,
                                "usage_status": "unused",
                                "expiry_date": None,
                            },
                            {
                                "feature": "LAN_ENTERPRISE_SERVICES_PKG",
                                "installed": True,
                                "license_count": None,
                                "usage_status": "in_use",
                                "expiry_date": None,
                            },
                        ],
                    },
                },
                "profiles": {},
                "sources": {
                    "license_usage": {
                        "status": "success",
                        "parse_status": "parsed",
                    }
                },
            },
        },
    }


def _health_result():
    return {
        "schema_version": 1,
        "change_id": "CHG-DEVICE-SUMMARY",
        "phase": "before",
        "started_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
        "profiles": ["network-baseline-nxos"],
        "result": "UNKNOWN",
        "counts": {
            "pass": 1,
            "warn": 1,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [
            {
                "check_id": "system_identity",
                "profile": "network-baseline-nxos",
                "host": "leaf01",
                "result": "PASS",
                "classification": "normal",
                "message": "ok",
                "evidence": [],
            },
            {
                "check_id": "memory_utilization",
                "profile": "network-baseline-nxos",
                "host": "leaf01",
                "result": "WARN",
                "classification": "pre_existing",
                "message": "warning",
                "evidence": [],
            },
        ],
        "unexecuted_hosts": [
            {
                "host": "leaf02",
                "platform": "nxos",
                "topology_role": "other",
                "profile": "network-baseline-nxos",
                "profile_result": "UNKNOWN",
                "reason_code": "COLLECTION_FAILED",
                "message": "collection failed",
            }
        ],
    }


def _resolved_roles():
    return {
        "api_version": "alred/v1",
        "kind": "ResolvedRoles",
        "metadata": {
            "change_id": "CHG-DEVICE-SUMMARY",
            "resolved_at": NOW.isoformat(),
            "timezone": "Asia/Tokyo",
            "resolver_version": "1.0",
        },
        "spec": {
            "role_schema_version": 2,
            "source": {
                "path": "/sanitized/roles.yaml",
                "sha256": "sha256:" + "b" * 64,
            },
            "policy_sha256": "sha256:" + "c" * 64,
            "devices": {
                "leaf01": {
                    "status": "resolved",
                    "priority": 0,
                    "detected_topology_roles": ["leaf"],
                    "topology_role": "leaf",
                    "functions": {
                        "vtep": {
                            "expectation": "required",
                            "source": "topology_role_default",
                        },
                        "evpn-route-reflector": {
                            "expectation": "optional",
                            "source": "topology_role_default",
                        },
                    },
                },
                "leaf02": {
                    "status": "fallback",
                    "priority": 99,
                    "detected_topology_roles": [],
                    "topology_role": "other",
                    "functions": {},
                },
            },
        },
    }


def test_device_summary_uses_one_sorted_row_model_for_markdown_and_csv():
    rows = build_device_summary_rows(
        _snapshot(),
        _health_result(),
        resolved_roles=_resolved_roles(),
        inventory_sites={"leaf01": "site-a"},
    )

    assert [row["hostname"] for row in rows] == ["leaf01", "leaf02"]
    assert rows[0]["serial_number"] == "SAL00000001"
    assert rows[0]["site"] == "site-a"
    assert rows[0]["license_parse_status"] == "parsed"
    assert rows[0]["license_usage"].startswith(
        "LAN_ENTERPRISE_SERVICES_PKG(installed=yes,status=in_use"
    )
    assert rows[0]["functions"] == "evpn-route-reflector; vtep"
    assert rows[0]["health_result"] == "WARN"
    assert rows[0]["collected_at"] == "2026-08-17T10:00:00"
    assert rows[1]["serial_number"] == "UNKNOWN"
    assert rows[1]["site"] == "UNKNOWN"
    assert rows[1]["license_usage"] == "UNKNOWN"
    assert rows[1]["license_parse_status"] == "unknown"
    assert rows[1]["health_result"] == "UNKNOWN"

    markdown = render_device_summary_markdown(rows)
    assert markdown.count("\n| ") == 3
    assert "N9K-C93180YC-EX \\| lab, row" in markdown
    assert "2026-08-17T10:00:00+09:00" not in markdown

    csv_rows = list(csv.DictReader(io.StringIO(render_device_summary_csv(rows))))
    assert tuple(csv_rows[0]) == DEVICE_SUMMARY_COLUMNS
    assert DEVICE_SUMMARY_COLUMNS.index("site") == (
        DEVICE_SUMMARY_COLUMNS.index("license_parse_status") + 1
    )
    assert DEVICE_SUMMARY_COLUMNS.index("topology_role") == (
        DEVICE_SUMMARY_COLUMNS.index("site") + 1
    )
    assert csv_rows == rows


def test_device_summary_sorts_lower_numeric_role_priority_first():
    resolved_roles = _resolved_roles()
    resolved_roles["spec"]["devices"]["leaf01"]["priority"] = 10
    resolved_roles["spec"]["devices"]["leaf02"]["priority"] = 1

    rows = build_device_summary_rows(
        _snapshot(),
        _health_result(),
        resolved_roles=resolved_roles,
    )

    assert [row["hostname"] for row in rows] == ["leaf02", "leaf01"]


def test_device_summary_sorts_site_priority_before_role_priority():
    resolved_roles = _resolved_roles()
    resolved_roles["spec"]["devices"]["leaf01"]["priority"] = 10
    resolved_roles["spec"]["devices"]["leaf02"]["priority"] = 1

    rows = build_device_summary_rows(
        _snapshot(),
        _health_result(),
        resolved_roles=resolved_roles,
        inventory_sites={"leaf01": "site-a", "leaf02": "site-b"},
        site_rules={
            "site-a": {"priority": 1},
            "site-b": {"priority": 100},
        },
    )

    assert [row["hostname"] for row in rows] == ["leaf01", "leaf02"]


def test_device_summary_uses_1000_for_missing_site_priority():
    rows = build_device_summary_rows(
        _snapshot(),
        _health_result(),
        resolved_roles=_resolved_roles(),
        inventory_sites={"leaf01": "implicit", "leaf02": "explicit"},
        site_rules={
            "implicit": {},
            "explicit": {"priority": 999},
        },
    )

    assert [row["hostname"] for row in rows] == ["leaf02", "leaf01"]


def test_inventory_site_prefers_explicit_value_then_metadata():
    inventory = load_inventory_data({
        "all": {
            "hosts": {
                "leaf01": {
                    "site": "site-a",
                    "metadata": {"site": "ignored"},
                },
                "leaf02": {"metadata": {"site": "site-b"}},
            }
        }
    })

    assert {item["hostname"]: item["site"] for item in inventory} == {
        "leaf01": "site-a",
        "leaf02": "site-b",
    }


def test_device_summary_rejects_mismatched_operation_identity():
    result = _health_result()
    result["change_id"] = "CHG-OTHER"

    with pytest.raises(ValueError, match="identity mismatch"):
        build_device_summary_rows(_snapshot(), result)
