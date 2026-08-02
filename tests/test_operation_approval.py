from datetime import datetime, timedelta
import json
from pathlib import Path
import stat

import pytest

from alred.approval import (
    ApprovalError,
    ApprovalRequiredError,
    build_approval_summary,
    create_approval_record,
    load_approval_record,
    validate_approval,
)
from alred.operation import (
    OperationLock,
    create_operation_workspace,
    load_operation_metadata,
    transition_workflow,
)


JST_NOW = datetime.fromisoformat("2026-08-01T10:02:03+09:00")


def _ready_workspace(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-2026-00123",
        now=JST_NOW,
    )
    plan_dir = workspace.operation_root / "plan"
    plan_dir.mkdir(mode=0o700)
    plan = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "capability_level": "APPLY_VERIFIED",
        "devices": ["leaf01", "leaf02"],
    }
    rollback = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "policy": "manual",
        "devices": ["leaf01", "leaf02"],
    }
    plan_path = plan_dir / "execution-plan.json"
    rollback_path = plan_dir / "rollback-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    rollback_path.write_text(json.dumps(rollback), encoding="utf-8")
    plan_path.chmod(0o600)
    rollback_path.chmod(0o600)
    with OperationLock(workspace, "plan", now=JST_NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
    return workspace, plan_path, rollback_path


def test_approval_requires_explicit_confirmation(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
    )

    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        with pytest.raises(ApprovalRequiredError):
            create_approval_record(
                workspace,
                summary,
                lock=lock,
                confirm=lambda _summary: False,
                now=JST_NOW,
                random_hex="a1b2c3",
            )

    assert not (workspace.operation_root / "approval").exists()


def test_approval_records_exact_hashes_expiry_and_workflow(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
        max_devices=50,
        save_on_success=True,
        rollback_policy="manual",
    )

    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            approval_hours=24,
            now=JST_NOW,
            random_hex="a1b2c3",
        )

    record = load_approval_record(approval_path)
    assert approval_path.name == "approval-record.json"
    assert stat.S_IMODE(approval_path.stat().st_mode) == 0o600
    assert record["approval_id"] == "APR-20260801T100203-p0900-a1b2c3"
    assert record["artifacts"] == summary["artifacts"]
    assert record["expires_at"] == "2026-08-02T10:02:03+09:00"
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "approved"

    validate_approval(
        record,
        expected_change_id=workspace.change_id,
        expected_artifacts=summary["artifacts"],
        now=JST_NOW + timedelta(hours=23),
    )
    with pytest.raises(ApprovalError, match="expired"):
        validate_approval(
            record,
            expected_change_id=workspace.change_id,
            expected_artifacts=summary["artifacts"],
            now=JST_NOW + timedelta(hours=24),
        )
    with pytest.raises(ApprovalError, match="hash mismatch"):
        validate_approval(
            record,
            expected_change_id=workspace.change_id,
            expected_artifacts={
                **summary["artifacts"],
                "execution_plan": "sha256:" + "0" * 64,
            },
            now=JST_NOW,
        )


def test_approval_automatically_pins_plan_input_artifacts(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    input_manifest = workspace.operation_root / "plan/input-manifest.json"
    resolved_targets = workspace.operation_root / "plan/resolved-targets.yaml"
    input_manifest.write_text('{"schema_version": 1}', encoding="utf-8")
    resolved_targets.write_text("kind: resolved\n", encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["artifacts"] = {
        "approval_artifacts": {
            "input_manifest": str(input_manifest),
            "resolved_targets": str(resolved_targets),
        }
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
    )

    assert set(summary["artifacts"]) == {
        "execution_plan",
        "rollback_plan",
        "input_manifest",
        "resolved_targets",
    }
    resolved_targets.write_text("kind: modified\n", encoding="utf-8")
    changed = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
    )
    assert (
        changed["artifacts"]["resolved_targets"]
        != summary["artifacts"]["resolved_targets"]
    )


def test_approval_rejects_artifact_outside_operation(tmp_path):
    workspace, _plan_path, rollback_path = _ready_workspace(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(Exception, match="outside operation root"):
        build_approval_summary(
            workspace,
            plan_path=outside,
            rollback_plan_path=rollback_path,
        )


def test_approval_fails_closed_without_apply_verified_capability(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["capability_level"] = "PLAN_ONLY"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ApprovalError, match="APPLY_VERIFIED"):
        build_approval_summary(
            workspace,
            plan_path=plan_path,
            rollback_plan_path=rollback_path,
        )


def test_approval_rejects_device_count_over_constraint(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["devices"] = [f"leaf{index:02d}" for index in range(3)]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ApprovalError, match="device count 3"):
        build_approval_summary(
            workspace,
            plan_path=plan_path,
            rollback_plan_path=rollback_path,
            max_devices=2,
        )


@pytest.mark.parametrize("hours", [0, 25])
def test_approval_validity_cannot_exceed_initial_policy(tmp_path, hours):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
    )

    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        with pytest.raises(ApprovalError, match="between 1 and 24"):
            create_approval_record(
                workspace,
                summary,
                lock=lock,
                confirm=lambda _summary: True,
                approval_hours=hours,
                now=JST_NOW,
            )


def test_approval_never_overwrites_same_approval_id(tmp_path):
    workspace, plan_path, rollback_path = _ready_workspace(tmp_path)
    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=rollback_path,
    )
    approval_dir = workspace.operation_root / "approval"
    approval_dir.mkdir(mode=0o700)
    (approval_dir / "approval-record.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    collision_path = (
        approval_dir
        / "approval-record.APR-20260801T100203-p0900-a1b2c3.json"
    )
    collision_path.write_text("preserve\n", encoding="utf-8")

    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        with pytest.raises(ApprovalError, match="will not be overwritten"):
            create_approval_record(
                workspace,
                summary,
                lock=lock,
                confirm=lambda _summary: True,
                now=JST_NOW,
                random_hex="a1b2c3",
            )

    assert collision_path.read_text(encoding="utf-8") == "preserve\n"
