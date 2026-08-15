from copy import deepcopy
from datetime import datetime
from pathlib import Path

from alred.health.evaluator import compare_snapshots, evaluate_snapshot
from alred.health.parsers import parse_nxos_command
from alred.health.profile import resolve_profiles


NOW = datetime.fromisoformat("2026-08-08T12:00:00+09:00")
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nxos"


def test_overlay_operational_fixtures_parse_expected_resources() -> None:
    parsed = {}
    common_interfaces = {}
    for identifier, directory in (
        ("vlan_brief", "show_vlan_brief"),
        ("vrf", "show_vrf"),
        ("interface_brief", "show_interface_brief"),
    ):
        output = (FIXTURE_ROOT / directory / "documented_sample.txt").read_text(encoding="utf-8")
        common, profile = parse_nxos_command(identifier, output)
        common_interfaces.update(common.get("interfaces", {}))
        parsed.update(profile["nxos-overlay"])

    assert parsed["vlans"]["vlans"]["10"]["status"] == "active"
    assert parsed["vrfs"]["vrfs"]["TENANT-A"]["state"] == "Up"
    assert parsed["svis"]["interfaces"]["Vlan10"] == {
        "admin_state": "up",
        "operational_state": "up",
        "status": "up",
        "reason": "--",
    }
    assert parsed["svis"]["interfaces"]["Vlan1"]["admin_state"] == "down"
    assert common_interfaces["Vlan10"]["status"] == "connected"
    assert common_interfaces["Vlan1"] == {
        "admin_state": "down",
        "operational_state": "down",
        "status": "disabled",
        "reason": "Administratively down",
    }


def _snapshot(resolved: dict) -> dict:
    config_text = """vlan 10
  name TENANT-A-WEB
  vn-segment 10010
vlan 3001
  name TENANT-A-L3VNI
  vn-segment 50001
vrf context TENANT-A
  vni 50001
interface Vlan10
  vrf member TENANT-A
  ip address 192.0.2.1/24
interface Vlan3001
  vrf member TENANT-A
  ip forward
"""
    _, config_profile = parse_nxos_command("running_config", config_text)
    _, vlan_profile = parse_nxos_command(
        "vlan_brief",
        """VLAN Name                             Status    Ports
---- -------------------------------- --------- ----------------
1    default                          active
10   TENANT-A-WEB                     active
3001 TENANT-A-L3VNI                   active
""",
    )
    _, vrf_profile = parse_nxos_command(
        "vrf",
        """VRF-Name                           VRF-ID State   Reason
default                                 1 Up      --
TENANT-A                                3 Up      --
""",
    )
    _, svi_profile = parse_nxos_command(
        "interface_brief",
        """Interface Secondary VLAN(Type)                    Status Reason
Vlan1      --                                      down   Administratively down
Vlan10     --                                      up     --
Vlan3001   --                                      up     --
""",
    )
    profile = {}
    for update in (config_profile, vlan_profile, vrf_profile, svi_profile):
        profile.update(update["nxos-overlay"])
    return {
        "schema_version": 1,
        "change_id": "overlay-operational",
        "collection_id": "overlay-operational-before-001",
        "phase": "before",
        "created_at": NOW.isoformat(),
        "timezone": "Asia/Tokyo",
        "parser_versions": {"nxos": "1.11"},
        "profile_sha256": resolved["spec"]["resolved"]["effective_sha256"],
        "hosts": {
            "leaf01": {
                "collection_status": "success",
                "common": {},
                "profiles": {"nxos-overlay": profile},
                "sources": {
                    identifier: {"status": "success", "parse_status": "parsed"}
                    for identifier in ("running_config", "vlan_brief", "vrf", "interface_brief")
                },
                "parse_warnings": [],
            }
        },
    }


def test_overlay_operational_parsers_and_checks_pass() -> None:
    resolved = resolve_profiles(
        ["nxos-overlay"], change_id="overlay-operational", resolved_at=NOW, timezone="Asia/Tokyo"
    )
    result = evaluate_snapshot(
        _snapshot(resolved), resolved, started_at=NOW, completed_at=NOW
    )
    checks = {item["check_id"]: item for item in result["checks"]}

    for check_id in (
        "vlan_operational_health",
        "vrf_operational_health",
        "svi_operational_health",
    ):
        assert checks[check_id]["result"] == "PASS", checks[check_id]


def test_overlay_operational_missing_evidence_is_unknown() -> None:
    resolved = resolve_profiles(
        ["nxos-overlay"], change_id="overlay-operational", resolved_at=NOW, timezone="Asia/Tokyo"
    )
    snapshot = _snapshot(resolved)
    snapshot["hosts"]["leaf01"]["profiles"]["nxos-overlay"].pop("svis")
    snapshot["hosts"]["leaf01"]["sources"].pop("interface_brief")

    result = evaluate_snapshot(snapshot, resolved, started_at=NOW, completed_at=NOW)
    check = next(item for item in result["checks"] if item["check_id"] == "svi_operational_health")
    assert check["result"] == "UNKNOWN"
    assert check["classification"] == "collection_error"


def test_overlay_operational_compare_marks_state_loss_as_regression() -> None:
    resolved = resolve_profiles(
        ["nxos-overlay"], change_id="overlay-operational", resolved_at=NOW, timezone="Asia/Tokyo"
    )
    before = _snapshot(resolved)
    after = deepcopy(before)
    after["phase"] = "after"
    after["collection_id"] = "overlay-operational-after-001"
    after["hosts"]["leaf01"]["profiles"]["nxos-overlay"]["svis"]["interfaces"]["Vlan10"]["operational_state"] = "down"

    result = compare_snapshots(before, after, resolved, started_at=NOW, completed_at=NOW)
    check = next(item for item in result["checks"] if item["check_id"] == "svi_operational_health")
    assert check["result"] == "FAIL"
    assert check["classification"] == "regression"
    assert "Vlan10=up/down" in check["message"]
