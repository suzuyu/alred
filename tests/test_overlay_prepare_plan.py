from copy import deepcopy
from datetime import datetime
import json

import pytest
import yaml

from alred.cli import (
    build_parser,
    cmd_overlay_change_plan,
    cmd_overlay_change_prepare_plan,
)
from alred.health.overlay import parse_overlay_running_config
from alred.operation import (
    OperationLock,
    atomic_write_yaml,
    create_operation_workspace,
    load_operation_execution,
    load_operation_metadata,
    open_operation_workspace,
    transition_phase,
)
from alred.overlay_conflict import assess_overlay_conflicts
from alred.preparation import (
    ReferenceStateNotEligibleError,
    ReferenceStateStaleError,
    select_reference_state,
)
from alred.schema import source_sha256


REFERENCE_TIME = datetime.fromisoformat("2026-08-01T10:00:00+09:00")
FABRIC_CONFIG = """\
feature nv overlay
interface nve1
  global ingress-replication protocol bgp
router bgp 65000
route-map IPv4_REDISTRIBUTE_ALL permit 10
route-map IPv6_REDISTRIBUTE_ALL permit 10
"""


def _changeset(change_id="CHG-1"):
    return {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {"change_id": change_id, "source": "declared"},
        "spec": {
            "device_groups": {"server-leafs": {"devices": ["leaf01"]}},
            "l2vnis": [
                {
                    "vni": 10020,
                    "default_vlan": 20,
                    "vlan_name": "TENANT-A-APP",
                    "vrf": "TENANT-A",
                    "l3vni": 50001,
                    "svi": {
                        "ipv4_addresses": ["198.51.100.1/24"],
                        "ipv6_addresses": ["2001:db8:20::1/64"],
                    },
                    "targets": {"groups": {"server-leafs": {}}},
                }
            ],
            "l3vnis": [
                {
                    "vni": 50001,
                    "vrf": "TENANT-A",
                    "targets": {"groups": {"server-leafs": {}}},
                }
            ],
        },
    }


def _snapshot(change_id, phase, created_at, config=FABRIC_CONFIG):
    return {
        "schema_version": 1,
        "change_id": change_id,
        "collection_id": f"{change_id}-{phase}-001",
        "phase": phase,
        "created_at": created_at.isoformat(),
        "timezone": "Asia/Tokyo",
        "parser_versions": {"overlay": "1.0"},
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            "leaf01": {
                "collection_status": "success",
                "common": {
                    "system": {
                        "platform": "nxos",
                        "model": "N9K-C9300V",
                        "version": "10.5(4)",
                    }
                },
                "profiles": {
                    "nxos-overlay": {
                        "config": parse_overlay_running_config(config)
                    }
                },
                "sources": {
                    "running_config": {
                        "command": "show running-config",
                        "file": "raw/config/leaf01_run.txt",
                        "sha256": "sha256:" + "b" * 64,
                        "parse_status": "parsed",
                    }
                },
            }
        },
    }


def _health_result(change_id, phase, created_at):
    return {
        "schema_version": 1,
        "change_id": change_id,
        "phase": phase,
        "started_at": created_at.isoformat(),
        "completed_at": created_at.isoformat(),
        "profiles": ["network-baseline-nxos", "nxos-overlay"],
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


def _write_completed_before(workspace, snapshot, created_at=REFERENCE_TIME):
    phase_dir = workspace.operation_root / "health/before"
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "snapshot.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    (phase_dir / "health-result.json").write_text(
        json.dumps(_health_result(workspace.change_id, "before", created_at)),
        encoding="utf-8",
    )
    with OperationLock(workspace, "test-before", now=created_at) as lock:
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="legacy-before",
            now=created_at,
        )
        transition_phase(
            workspace,
            "before",
            "completed",
            lock=lock,
            now=created_at,
        )
    return phase_dir / "snapshot.json"


def _write_current_before(workspace, snapshot, created_at=REFERENCE_TIME):
    phase_dir = workspace.operation_root / "health/before"
    attempt_id = "before-20260801T100000-test"
    attempt_dir = phase_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True)
    health = _health_result(workspace.change_id, "before", created_at)
    snapshot_text = json.dumps(snapshot)
    health_text = json.dumps(health)
    (attempt_dir / "snapshot.json").write_text(
        snapshot_text, encoding="utf-8"
    )
    (attempt_dir / "health-result.json").write_text(
        health_text, encoding="utf-8"
    )
    (attempt_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": workspace.change_id,
                "phase": "before",
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "health_result": "PASS",
                "started_at": created_at.isoformat(),
                "completed_at": created_at.isoformat(),
                "artifact_dir": str(attempt_dir),
                "profile_sha256": snapshot["profile_sha256"],
            }
        ),
        encoding="utf-8",
    )
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "snapshot.json").write_text(snapshot_text, encoding="utf-8")
    (phase_dir / "health-result.json").write_text(
        health_text, encoding="utf-8"
    )
    (phase_dir / "current.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": workspace.change_id,
                "phase": "before",
                "attempt_id": attempt_id,
                "artifact_dir": str(attempt_dir),
                "snapshot_path": str(attempt_dir / "snapshot.json"),
                "snapshot_sha256": source_sha256(attempt_dir / "snapshot.json"),
                "profile_sha256": snapshot["profile_sha256"],
                "health_result": "PASS",
                "completed_at": created_at.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    with OperationLock(workspace, "test-current-before", now=created_at) as lock:
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id=attempt_id,
            now=created_at,
        )
        transition_phase(
            workspace,
            "before",
            "completed",
            lock=lock,
            now=created_at,
        )
    return attempt_id


def _write_reference(
    operations_root,
    operation_id="REF-1",
    *,
    workflow_state="completed",
    phase="after",
    config=FABRIC_CONFIG,
    created_at=REFERENCE_TIME,
    compare_result="PASS",
):
    workspace = create_operation_workspace(
        operations_root,
        change_id=operation_id,
        now=created_at,
    )
    metadata = load_operation_metadata(workspace.operation_root)
    metadata["spec"]["workflow_state"] = workflow_state
    if workflow_state is None:
        metadata["spec"]["phases"]["after"] = {
            "current_attempt": "after-001",
            "status": "completed_with_warnings",
        }
    atomic_write_yaml(
        workspace.operation_root,
        workspace.metadata_path,
        metadata,
        kind="OperationMetadata",
    )
    phase_dir = workspace.operation_root / "health" / phase
    phase_dir.mkdir(parents=True)
    (phase_dir / "snapshot.json").write_text(
        json.dumps(_snapshot(operation_id, phase, created_at, config)),
        encoding="utf-8",
    )
    (phase_dir / "health-result.json").write_text(
        json.dumps(_health_result(operation_id, phase, created_at)),
        encoding="utf-8",
    )
    if workflow_state is None and compare_result is not None:
        report_dir = workspace.operation_root / "health" / "report"
        report_dir.mkdir(parents=True)
        comparison = _health_result(operation_id, "compare", created_at)
        comparison["result"] = compare_result
        (report_dir / "health-result.json").write_text(
            json.dumps(comparison),
            encoding="utf-8",
        )
    return workspace


def _write_changeset(path, change_id="CHG-1"):
    path.write_text(yaml.safe_dump(_changeset(change_id)), encoding="utf-8")
    return path


def _current_preparation_dir(operation_root):
    current = json.loads(
        (operation_root / "preparation/current.json").read_text()
    )
    return operation_root / "preparation" / "attempts" / current["attempt_id"]


def test_prepare_plan_uses_latest_terminal_state_without_advancing_workflow(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    _write_reference(operations_root)
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "prepare-plan",
            "--change-set",
            str(change_set_path),
            "--reference-state",
            "latest-known-good",
            "--reference-max-age-days",
            "36500",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_overlay_change_prepare_plan(args)

    operation_root = operations_root / "CHG-1"
    preparation_dir = _current_preparation_dir(operation_root)
    execution = json.loads(
        (preparation_dir / "execution-plan.json").read_text()
    )
    reference = json.loads(
        (preparation_dir / "reference-state.json").read_text()
    )
    metadata = load_operation_metadata(operation_root)
    assert execution["preparation_only"] is True
    assert execution["capability_level"] == "PLAN_ONLY"
    assert reference["source"]["operation_id"] == "REF-1"
    assert reference["source"]["phase"] == "after"
    assert metadata["spec"]["workflow_state"] is None
    assert metadata["spec"]["phases"]["prepare_plan"]["status"] == "completed"
    assert (preparation_dir / "generated-config/leaf01.cfg").is_file()
    assert "Apply            : BLOCKED" in capsys.readouterr().out

    workspace = open_operation_workspace(operations_root, "CHG-1")
    before_path = _write_completed_before(
        workspace,
        _snapshot("CHG-1", "before", REFERENCE_TIME),
    )
    normal_args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(change_set_path),
            "--before",
            str(before_path),
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_overlay_change_plan(normal_args)

    metadata = load_operation_metadata(operation_root)
    assert (operation_root / "plan/conflict-report.json").is_file()
    assert (operation_root / "plan/execution-plan.json").is_file()
    assert metadata["spec"]["workflow_state"] == "plan_ready"


def test_prepare_plan_rejects_conflict_and_keeps_report(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    conflicting = FABRIC_CONFIG + """\
vlan 20
  vn-segment 99999
"""
    _write_reference(operations_root, config=conflicting)
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "prepare-plan",
            "--change-set",
            str(change_set_path),
            "--reference-operation-id",
            "REF-1",
            "--reference-max-age-days",
            "36500",
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_prepare_plan(args)

    operation_root = operations_root / "CHG-1"
    attempt_id = load_operation_metadata(operation_root)["spec"]["phases"][
        "prepare_plan"
    ]["current_attempt"]
    preparation_dir = operation_root / "preparation/attempts" / attempt_id
    report = json.loads(
        (preparation_dir / "conflict-report.json").read_text()
    )
    metadata = load_operation_metadata(operation_root)
    assert report["result"] == "CONFLICT"
    assert metadata["spec"]["phases"]["prepare_plan"]["status"] == "failed"
    assert not (preparation_dir / "execution-plan.json").exists()
    attempt = json.loads((preparation_dir / "result.json").read_text())
    operation_execution = load_operation_execution(operation_root)
    assert attempt["status"] == "FAILED"
    assert attempt["error"]["code"] == "PLAN_CONFLICT"
    assert operation_execution["errors"][-1]["attempt_id"] == attempt_id
    assert exc_info.value.code == 2
    assert "PLAN_CONFLICT" in capsys.readouterr().err


def test_normal_plan_repeats_conflict_check_against_fresh_before(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=REFERENCE_TIME,
    )
    conflicting = FABRIC_CONFIG + """\
vlan 20
  vn-segment 99999
"""
    before_path = _write_completed_before(
        workspace,
        _snapshot("CHG-1", "before", REFERENCE_TIME, conflicting),
    )
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(change_set_path),
            "--before",
            str(before_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_plan(args)

    report = json.loads(
        (workspace.operation_root / "plan/conflict-report.json").read_text()
    )
    assert report["result"] == "CONFLICT"
    assert not (workspace.operation_root / "plan/execution-plan.json").exists()
    assert exc_info.value.code == 2
    assert "PLAN_CONFLICT" in capsys.readouterr().err


def test_normal_plan_infers_current_before_from_changeset_change_id(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=REFERENCE_TIME,
    )
    attempt_id = _write_current_before(
        workspace,
        _snapshot("CHG-1", "before", REFERENCE_TIME),
    )
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(change_set_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_overlay_change_plan(args)

    output = capsys.readouterr().out
    assert "Before source   : inferred from ChangeSet change_id" in output
    assert f"Before attempt  : {attempt_id}" in output
    assert "Before result   : PASS" in output
    plan = json.loads(
        (workspace.operation_root / "plan/execution-plan.json").read_text()
    )
    assert plan["artifacts"]["before_snapshot"] == str(
        workspace.operation_root / "health/before/snapshot.json"
    )


def test_normal_plan_rejects_failed_latest_before_retry(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=REFERENCE_TIME,
    )
    first_attempt = _write_current_before(
        workspace,
        _snapshot("CHG-1", "before", REFERENCE_TIME),
    )
    with OperationLock(workspace, "test-failed-retry", now=REFERENCE_TIME) as lock:
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="before-failed-retry",
            now=REFERENCE_TIME,
            allow_retry=True,
        )
        transition_phase(
            workspace,
            "before",
            "failed",
            lock=lock,
            now=REFERENCE_TIME,
        )
    current = json.loads(
        (workspace.operation_root / "health/before/current.json").read_text()
    )
    assert current["attempt_id"] == first_attempt
    args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(_write_changeset(tmp_path / "desired.yaml")),
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_plan(args)

    assert exc_info.value.code == 2
    assert "latest before phase is not completed: failed" in capsys.readouterr().err
    assert not (workspace.operation_root / "plan/execution-plan.json").exists()


def test_normal_plan_rejects_modified_published_before(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=REFERENCE_TIME,
    )
    _write_current_before(
        workspace,
        _snapshot("CHG-1", "before", REFERENCE_TIME),
    )
    published = workspace.operation_root / "health/before/snapshot.json"
    modified = json.loads(published.read_text())
    modified["collection_id"] = "modified-after-publication"
    published.write_text(json.dumps(modified), encoding="utf-8")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(_write_changeset(tmp_path / "desired.yaml")),
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_plan(args)

    assert exc_info.value.code == 2
    assert "Snapshot hash does not match" in capsys.readouterr().err
    assert not (workspace.operation_root / "plan/execution-plan.json").exists()


def test_reference_age_limit_is_fail_closed(tmp_path):
    operations_root = tmp_path / "operations"
    _write_reference(operations_root)

    with pytest.raises(ReferenceStateStaleError):
        select_reference_state(
            operations_root,
            current_change_id="CHG-1",
            target_hosts=["leaf01"],
            evaluated_at=datetime.fromisoformat("2026-09-15T10:00:00+09:00"),
            max_age_days=30,
            reference_operation_id="REF-1",
        )


def test_latest_known_good_uses_rollback_for_rolled_back_operation(tmp_path):
    operations_root = tmp_path / "operations"
    _write_reference(
        operations_root,
        workflow_state="rolled_back_and_verified",
        phase="rollback",
    )

    selected = select_reference_state(
        operations_root,
        current_change_id="CHG-1",
        target_hosts=["leaf01"],
        evaluated_at=REFERENCE_TIME,
        reference_state="latest-known-good",
    )

    assert selected.document["source"]["phase"] == "rollback"


def test_explicit_standalone_health_after_is_eligible(tmp_path):
    operations_root = tmp_path / "operations"
    _write_reference(operations_root, workflow_state=None)

    selected = select_reference_state(
        operations_root,
        current_change_id="CHG-1",
        target_hosts=["leaf01"],
        evaluated_at=REFERENCE_TIME,
        reference_operation_id="REF-1",
    )

    assert selected.document["source"]["phase"] == "after"
    assert selected.document["source"]["source_type"] == "standalone_health_after"
    assert selected.document["source"]["workflow_state"] is None
    assert selected.document["source"]["comparison"]["result"] == "PASS"


def test_standalone_health_after_rejects_failed_comparison(tmp_path):
    operations_root = tmp_path / "operations"
    _write_reference(
        operations_root,
        workflow_state=None,
        compare_result="FAIL",
    )

    with pytest.raises(ReferenceStateNotEligibleError):
        select_reference_state(
            operations_root,
            current_change_id="CHG-1",
            target_hosts=["leaf01"],
            evaluated_at=REFERENCE_TIME,
            reference_operation_id="REF-1",
        )


def test_failed_prepare_plan_can_retry_without_overwriting_attempt(tmp_path):
    operations_root = tmp_path / "operations"
    conflicting = FABRIC_CONFIG + """\
vlan 20
  vn-segment 99999
"""
    _write_reference(operations_root, "REF-BAD", config=conflicting)
    _write_reference(operations_root, "REF-GOOD")
    change_set_path = _write_changeset(tmp_path / "desired.yaml")

    def args(reference):
        return build_parser().parse_args(
            [
                "overlay-change",
                "prepare-plan",
                "--change-set",
                str(change_set_path),
                "--reference-operation-id",
                reference,
                "--reference-max-age-days",
                "36500",
                "--operations-root",
                str(operations_root),
            ]
        )

    with pytest.raises(SystemExit):
        cmd_overlay_change_prepare_plan(args("REF-BAD"))
    operation_root = operations_root / "CHG-1"
    failed_attempt = load_operation_metadata(operation_root)["spec"]["phases"][
        "prepare_plan"
    ]["current_attempt"]

    cmd_overlay_change_prepare_plan(args("REF-GOOD"))

    completed_attempt = load_operation_metadata(operation_root)["spec"]["phases"][
        "prepare_plan"
    ]["current_attempt"]
    assert completed_attempt != failed_attempt
    assert json.loads(
        (
            operation_root
            / "preparation/attempts"
            / failed_attempt
            / "result.json"
        ).read_text()
    )["status"] == "FAILED"
    assert json.loads(
        (
            operation_root
            / "preparation/attempts"
            / completed_attempt
            / "result.json"
        ).read_text()
    )["status"] == "PASS"
    assert json.loads(
        (operation_root / "preparation/current.json").read_text()
    )["attempt_id"] == completed_attempt


def test_completed_prepare_plan_is_not_overwritten(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    _write_reference(operations_root)
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    args = build_parser().parse_args(
        [
            "overlay-change",
            "prepare-plan",
            "--change-set",
            str(change_set_path),
            "--reference-operation-id",
            "REF-1",
            "--reference-max-age-days",
            "36500",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_overlay_change_prepare_plan(args)

    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_prepare_plan(args)

    assert exc_info.value.code == 2
    assert "completed prepare-plan already exists" in capsys.readouterr().err


def test_legacy_failed_phase_without_artifacts_can_retry(tmp_path):
    operations_root = tmp_path / "operations"
    _write_reference(operations_root)
    change_set_path = _write_changeset(tmp_path / "desired.yaml")
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=REFERENCE_TIME,
    )
    with OperationLock(workspace, "test-legacy-failed") as lock:
        transition_phase(
            workspace,
            "prepare_plan",
            "running",
            lock=lock,
            attempt_id="legacy-attempt",
            now=REFERENCE_TIME,
        )
        transition_phase(
            workspace,
            "prepare_plan",
            "failed",
            lock=lock,
            now=REFERENCE_TIME,
        )
    args = build_parser().parse_args(
        [
            "overlay-change",
            "prepare-plan",
            "--change-set",
            str(change_set_path),
            "--reference-operation-id",
            "REF-1",
            "--reference-max-age-days",
            "36500",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_overlay_change_prepare_plan(args)

    metadata = load_operation_metadata(workspace.operation_root)
    assert metadata["spec"]["phases"]["prepare_plan"]["status"] == "completed"
    assert (
        metadata["spec"]["phases"]["prepare_plan"]["current_attempt"]
        != "legacy-attempt"
    )


def test_conflict_check_detects_same_vrf_svi_prefix_overlap():
    existing = FABRIC_CONFIG + """\
interface Ethernet1/1
  vrf member TENANT-A
  ip address 198.51.100.254/24
"""
    report = assess_overlay_conflicts(
        _changeset(),
        _snapshot("CHG-1", "before", REFERENCE_TIME, existing),
    )

    assert report["result"] == "CONFLICT"
    assert any(
        item["code"] == "EXISTING_INTERFACE_PREFIX_OVERLAP"
        for item in report["checks"]
    )


def test_conflict_check_allows_same_anycast_gateway_across_devices():
    document = _changeset()
    document["spec"]["device_groups"]["server-leafs"]["devices"].append(
        "leaf02"
    )
    snapshot = _snapshot("CHG-1", "before", REFERENCE_TIME)
    snapshot["hosts"]["leaf02"] = deepcopy(snapshot["hosts"]["leaf01"])

    report = assess_overlay_conflicts(document, snapshot)

    assert report["result"] == "PASS"
    assert {item["host"] for item in report["checks"]} == {
        "leaf01",
        "leaf02",
    }


def test_prepare_plan_cli_exposes_clear_reference_options(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            ["overlay-change", "prepare-plan", "--help"]
        )

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--reference-state {latest-known-good}" in output
    assert "--reference-operation-id" in output
    assert "--reference-phase {after,rollback}" in output
    assert "--reference-max-age-days" in output
