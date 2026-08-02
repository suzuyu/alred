from datetime import datetime
import json

import yaml

from alred.cli import (
    build_parser,
    cmd_overlay_check_converge,
    cmd_overlay_check_evaluate,
)
from alred.health.overlay import parse_overlay_running_config
from alred.health.overlay_evaluator import (
    assess_overlay_convergence,
    evaluate_overlay_change,
)
from alred.health.report import render_overlay_summary
from alred.operation import (
    OperationLock,
    create_operation_workspace,
    load_operation_metadata,
    transition_workflow,
)


NOW = datetime.fromisoformat("2026-08-01T13:00:00+09:00")

BEFORE_CONFIG = """\
interface nve1
  global ingress-replication protocol bgp
router bgp 65000
route-map IPv4_REDISTRIBUTE_ALL permit 10
"""

AFTER_CONFIG = BEFORE_CONFIG + """\
vrf context TENANT-A
  vni 50001 l3
vlan 10
  name TENANT-A-WEB
  vn-segment 10010
interface Vlan10
  mtu 9216
  vrf member TENANT-A
  ip address 192.0.2.1/24
  fabric forwarding mode anycast-gateway
interface nve1
  global ingress-replication protocol bgp
  member vni 50001 associate-vrf
  member vni 10010
"""


def _change_set(source="declared"):
    return {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {"change_id": "CHG-1", "source": source},
        "spec": {
            "device_groups": {},
            "l2vnis": [
                {
                    "vni": 10010,
                    "default_vlan": 10,
                    "vlan_name": "TENANT-A-WEB",
                    "vrf": "TENANT-A",
                    "l3vni": 50001,
                    "svi": {
                        "mtu": 9216,
                        "ipv4_addresses": ["192.0.2.1/24"],
                        "gateway_mode": "anycast",
                    },
                    "targets": {"devices": {"leaf01": {}}},
                }
            ],
            "l3vnis": [
                {
                    "vni": 50001,
                    "vrf": "TENANT-A",
                    "mode": "new_l3vni",
                    "targets": {"devices": {"leaf01": {}}},
                }
            ],
        },
    }


def _snapshot(phase, config, *, l2_state="Up", peers=True, include_nve_vnis=True):
    overlay = {
        "config": parse_overlay_running_config(config),
        "nve_interface": {
            "applicable": True,
            "name": "nve1",
            "state": "Up",
        },
        "evpn_bgp": {
            "applicable": True,
            "configured_peers": 1,
            "capable_peers": 1 if peers else 0,
            "neighbors": {
                "192.0.2.2": {
                    "state": "Established" if peers else "Idle"
                }
            },
        },
    }
    if include_nve_vnis:
        overlay["nve_vnis"] = {
            "applicable": True,
            "vnis": {
                "10010": {
                    "type": "L2",
                    "context": "10",
                    "state": l2_state,
                },
                "50001": {
                    "type": "L3",
                    "context": "TENANT-A",
                    "state": "Up",
                },
            },
        }
    return {
        "schema_version": 1,
        "change_id": "CHG-1",
        "collection_id": f"{phase}-001",
        "phase": phase,
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            "leaf01": {
                "common": {},
                "profiles": {"nxos-overlay": overlay},
                "sources": {
                    command_id: {
                        "command": command,
                        "file": f"raw/{command_id}.txt",
                        "sha256": "sha256:" + "b" * 64,
                        "parse_status": "parsed",
                    }
                    for command_id, command in {
                        "running_config": "show running-config",
                        "nve_vni": "show nve vni",
                        "nve_interface": "show nve interface",
                        "bgp_l2vpn_evpn_summary": "show bgp l2vpn evpn summary",
                    }.items()
                },
            }
        },
    }


def _evaluate(after, source="declared"):
    return evaluate_overlay_change(
        _snapshot("before", BEFORE_CONFIG),
        after,
        _change_set(source),
        started_at=NOW,
        completed_at=NOW,
    )


def test_declared_change_is_verified_across_three_sections():
    result = _evaluate(_snapshot("after", AFTER_CONFIG))

    assert result["result"] == "VERIFIED"
    assert result["sections"] == {
        "configuration": "PASS",
        "operational": "PASS",
        "impact": "PASS",
    }
    assert result["counts"]["pass"] == 6
    summary = render_overlay_summary(result)
    assert "| CONFIGURATION | PASS |" in summary
    assert "l2vni/10010" in summary


def test_discovered_change_can_only_be_observed_healthy():
    result = _evaluate(_snapshot("after", AFTER_CONFIG), source="discovered")

    assert result["result"] == "OBSERVED_HEALTHY"


def test_down_vni_and_lost_existing_peer_are_failures():
    result = _evaluate(
        _snapshot("after", AFTER_CONFIG, l2_state="Down", peers=False)
    )

    assert result["result"] == "FAIL"
    assert result["sections"]["operational"] == "FAIL"
    assert result["sections"]["impact"] == "FAIL"


def test_missing_operational_evidence_is_unknown():
    result = _evaluate(
        _snapshot("after", AFTER_CONFIG, include_nve_vnis=False)
    )

    assert result["result"] == "UNKNOWN"
    assert result["sections"]["operational"] == "UNKNOWN"


def test_convergence_requires_consecutive_healthy_attempts_and_resets():
    healthy = {"result": "VERIFIED"}
    unhealthy = {"result": "FAIL"}

    convergence = assess_overlay_convergence(
        [healthy, unhealthy, healthy, healthy],
        consecutive_passes=2,
    )

    assert convergence["converged"] is True
    assert convergence["converged_at_attempt"] == 4
    assert [
        item["consecutive_passes"] for item in convergence["attempts"]
    ] == [1, 0, 1, 2]


def test_overlay_evaluate_cli_writes_json_and_markdown(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=NOW,
    )
    before_path = workspace.operation_root / "before.json"
    after_path = workspace.operation_root / "after.json"
    change_set_path = workspace.operation_root / "expected.yaml"
    before_path.write_text(
        json.dumps(_snapshot("before", BEFORE_CONFIG)),
        encoding="utf-8",
    )
    after_path.write_text(
        json.dumps(_snapshot("after", AFTER_CONFIG)),
        encoding="utf-8",
    )
    change_set_path.write_text(
        yaml.safe_dump(_change_set(), sort_keys=False),
        encoding="utf-8",
    )
    for path in (before_path, after_path, change_set_path):
        path.chmod(0o600)
    args = build_parser().parse_args(
        [
            "overlay-check",
            "evaluate",
            "--before",
            str(before_path),
            "--after",
            str(after_path),
            "--change-set",
            str(change_set_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    exit_code = cmd_overlay_check_evaluate(args)

    assert exit_code == 0
    assert (workspace.operation_root / "overlay" / "health-result.json").is_file()
    assert (workspace.operation_root / "overlay" / "overlay-summary.md").is_file()
    assert "Result        : VERIFIED" in capsys.readouterr().out


def test_overlay_evaluate_resolves_operation_inputs_from_change_id(
    tmp_path, capsys
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=NOW,
    )
    before_path = (
        workspace.operation_root / "health" / "before" / "snapshot.json"
    )
    after_path = (
        workspace.operation_root / "health" / "after" / "snapshot.json"
    )
    change_set_path = workspace.operation_root / "inputs" / "change-set.yaml"
    before_path.parent.mkdir(parents=True)
    after_path.parent.mkdir(parents=True)
    change_set_path.parent.mkdir(parents=True)
    before_path.write_text(
        json.dumps(_snapshot("before", BEFORE_CONFIG)),
        encoding="utf-8",
    )
    after_path.write_text(
        json.dumps(_snapshot("after", AFTER_CONFIG)),
        encoding="utf-8",
    )
    change_set_path.write_text(
        yaml.safe_dump(_change_set(), sort_keys=False),
        encoding="utf-8",
    )
    for path in (before_path, after_path, change_set_path):
        path.chmod(0o600)

    exit_code = cmd_overlay_check_evaluate(
        build_parser().parse_args(
            [
                "overlay-check",
                "evaluate",
                "--change-id",
                "CHG-1",
                "--operations-root",
                str(operations_root),
            ]
        )
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"Before        : {before_path}" in output
    assert f"After         : {after_path}" in output
    assert f"ChangeSet     : {change_set_path}" in output


def test_overlay_evaluate_completes_apply_after_workflow(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=NOW,
    )
    with OperationLock(workspace, "state", now=NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
            "apply_completed",
        ):
            transition_workflow(workspace, state, lock=lock, now=NOW)
    before_path = workspace.operation_root / "before.json"
    after_path = workspace.operation_root / "after.json"
    change_set_path = workspace.operation_root / "expected.yaml"
    before_path.write_text(
        json.dumps(_snapshot("before", BEFORE_CONFIG)),
        encoding="utf-8",
    )
    after_path.write_text(
        json.dumps(_snapshot("after", AFTER_CONFIG)),
        encoding="utf-8",
    )
    change_set_path.write_text(
        yaml.safe_dump(_change_set(), sort_keys=False),
        encoding="utf-8",
    )
    common_path = (
        workspace.operation_root / "health/report/health-result.json"
    )
    common_path.parent.mkdir(parents=True)
    common_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": "CHG-1",
                "phase": "compare",
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
                "profiles": ["nxos-overlay"],
                "result": "PASS",
                "counts": {
                    "pass": 1,
                    "warn": 0,
                    "fail": 0,
                    "unknown": 0,
                    "not_applicable": 0,
                },
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    for path in (before_path, after_path, change_set_path, common_path):
        path.chmod(0o600)

    exit_code = cmd_overlay_check_evaluate(
        build_parser().parse_args(
            [
                "overlay-check",
                "evaluate",
                "--before",
                str(before_path),
                "--after",
                str(after_path),
                "--change-set",
                str(change_set_path),
                "--operations-root",
                str(operations_root),
            ]
        )
    )

    assert exit_code == 0
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "after_completed"


def test_overlay_converge_cli_uses_ordered_saved_results(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=NOW,
    )
    result = _evaluate(_snapshot("after", AFTER_CONFIG))
    paths = []
    for index in range(2):
        path = workspace.operation_root / f"attempt-{index + 1}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        path.chmod(0o600)
        paths.append(path)
    args = build_parser().parse_args(
        [
            "overlay-check",
            "converge",
            "--result",
            str(paths[0]),
            "--result",
            str(paths[1]),
            "--operations-root",
            str(operations_root),
        ]
    )

    exit_code = cmd_overlay_check_converge(args)

    assert exit_code == 0
    convergence = json.loads(
        (
            workspace.operation_root / "overlay" / "convergence.json"
        ).read_text(encoding="utf-8")
    )
    assert convergence["converged_at_attempt"] == 2
