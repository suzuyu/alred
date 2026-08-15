from datetime import datetime
import json

import pytest

from alred.approval import ApprovalRequiredError
from alred.managed_operation import (
    RollbackStateWarnAcceptanceError,
    accept_rollback_state_warn,
    build_rollback_state_warn_acceptance_summary,
    rollback_state_warn_confirmation_phrase,
    validate_rollback_state_warn_acceptance,
)
from alred.operation import (
    OperationLock,
    create_operation_workspace,
    load_operation_metadata,
    transition_workflow,
)
from alred.schema import source_sha256, validate_document


JST_NOW = datetime.fromisoformat("2026-08-16T04:00:00+09:00")


def _write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _eligible_workspace(
    tmp_path,
    *,
    classification="pre_existing",
    qualification=False,
):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-WARN-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
            "apply_completed",
            "after_running",
            "after_completed",
            "rollback_required",
            "rollback_running",
            "rolled_back",
            "rollback_health_failed",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)

    root = workspace.operation_root
    verification_root = (
        root / "qualification/rollback"
        if qualification
        else root / "rollback"
    )
    if qualification:
        _write_json(root / "qualification/qualification-record.json", {})
    attempt_id = "rollback-20260816T040000-p0900-abcdef"
    before_snapshot = _write_json(
        root / "health/before/snapshot.json",
        {"source": "before"},
    )
    rollback_snapshot = _write_json(
        root / f"health/rollback/attempts/{attempt_id}/snapshot.json",
        {"source": "rollback"},
    )
    health_result = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "rollback",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["network-baseline-nxos"],
        "result": "WARN",
        "counts": {
            "pass": 0,
            "warn": 1,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [
            {
                "check_id": "ntp_health",
                "profile": "network-baseline-nxos",
                "host": "leaf01",
                "resource": "system/ntp",
                "result": "WARN",
                "classification": classification,
                "message": "NTP is not synchronized",
                "evidence": [],
            }
        ],
    }
    health_result_path = _write_json(
        root
        / f"health/rollback-report/attempts/{attempt_id}/health-result.json",
        health_result,
    )
    health_gate = {
        "result": "WARN",
        "passed": False,
        "state_warn_eligible": classification == "pre_existing",
        "warning_count": 1,
        "warning_count_complete": True,
        "warning_classifications": {classification: 1},
    }
    verification = {
        "api_version": "alred/v1",
        "kind": (
            "QualificationRollbackVerification"
            if qualification
            else "ManagedRollbackVerification"
        ),
        "metadata": {
            "change_id": workspace.change_id,
            "verified_at": JST_NOW.isoformat(),
            "timezone": "Asia/Tokyo",
        },
        "status": {
            "result": "ROLLBACK_HEALTH_FAILED",
            "health_result": "WARN",
            "health_gate": health_gate,
            "snapshot_fresh": True,
            "raw_config_equal": True,
            "semantic_config_equal": True,
        },
        "devices": {
            "leaf01": {
                "raw_config_equal": True,
                "semantic_config_equal": True,
            }
        },
        "artifacts": {
            "before_snapshot": str(before_snapshot),
            "rollback_snapshot": str(rollback_snapshot),
            "health_result": str(health_result_path),
        },
    }
    verification_path = _write_json(
        verification_root
        / f"verification-attempts/{attempt_id}/verification.json",
        verification,
    )
    _write_json(
        verification_root / "verification.json",
        verification,
    )
    _write_json(
        verification_root / "verification-current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "attempt_id": attempt_id,
            "result": "ROLLBACK_HEALTH_FAILED",
            "verification_path": str(verification_path),
            "checklist_path": str(
                verification_path.with_name("verification-checklist.md")
            ),
            "health_report_path": str(health_result_path),
            "completed_at": JST_NOW.isoformat(),
        },
    )
    _write_json(
        root / "health/rollback/current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "rollback",
            "attempt_id": attempt_id,
            "artifact_dir": str(rollback_snapshot.parent),
            "snapshot_path": str(rollback_snapshot),
            "snapshot_sha256": source_sha256(rollback_snapshot),
            "profile_sha256": "sha256:" + "a" * 64,
            "health_result": "WARN",
            "completed_at": JST_NOW.isoformat(),
        },
    )
    return workspace, health_result_path


@pytest.mark.parametrize("qualification", [False, True])
def test_accept_rollback_state_warn_pins_evidence_and_transitions(
    tmp_path,
    qualification,
):
    workspace, health_result_path = _eligible_workspace(
        tmp_path,
        qualification=qualification,
    )
    phrase = rollback_state_warn_confirmation_phrase(workspace.change_id)
    observed = {}

    def confirm(summary):
        observed.update(summary)
        return summary["confirmation_phrase"] == phrase

    with OperationLock(workspace, "accept", now=JST_NOW) as lock:
        acceptance = accept_rollback_state_warn(
            workspace,
            confirm=confirm,
            lock=lock,
            now=lambda: JST_NOW,
        )

    validate_document(acceptance, kind="RollbackStateWarnAcceptance")
    assert observed["warning_classifications"] == {"pre_existing": 1}
    assert acceptance["status"]["result"] == "ACCEPTED"
    assert acceptance["spec"]["health_result_sha256"] == source_sha256(
        health_result_path
    )
    assert load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ] == "rolled_back_and_verified"
    acceptance_path = (
        workspace.operation_root
        / (
            "qualification/rollback/state-warn-acceptance.json"
            if qualification
            else "rollback/state-warn-acceptance.json"
        )
    )
    assert acceptance_path.is_file()
    if not qualification:
        assert validate_rollback_state_warn_acceptance(
            workspace,
            json.loads(
                (
                    workspace.operation_root / "rollback/verification.json"
                ).read_text()
            ),
        )[0] == str(acceptance_path)


def test_accept_rollback_state_warn_requires_exact_confirmation(tmp_path):
    workspace, _health_result_path = _eligible_workspace(tmp_path)

    with OperationLock(workspace, "accept", now=JST_NOW) as lock:
        with pytest.raises(ApprovalRequiredError):
            accept_rollback_state_warn(
                workspace,
                confirm=lambda _summary: False,
                lock=lock,
                now=lambda: JST_NOW,
            )

    assert not (
        workspace.operation_root / "rollback/state-warn-acceptance.json"
    ).exists()
    assert load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ] == "rollback_health_failed"


def test_accept_rollback_state_warn_rejects_regression(tmp_path):
    workspace, _health_result_path = _eligible_workspace(
        tmp_path,
        classification="regression",
    )

    with pytest.raises(RollbackStateWarnAcceptanceError):
        build_rollback_state_warn_acceptance_summary(workspace)


def test_accept_rollback_state_warn_migrates_legacy_allowed_operation(
    tmp_path,
):
    workspace, _health_result_path = _eligible_workspace(tmp_path)
    with OperationLock(workspace, "legacy-state", now=JST_NOW) as lock:
        transition_workflow(
            workspace,
            "rolled_back_and_verified",
            lock=lock,
            now=JST_NOW,
        )
    current_path = workspace.operation_root / "rollback/verification-current.json"
    current = json.loads(current_path.read_text())
    current["result"] = "ROLLED_BACK_AND_VERIFIED"
    _write_json(current_path, current)
    for verification_path in (
        workspace.operation_root / "rollback/verification.json",
        next(
            (
                workspace.operation_root / "rollback/verification-attempts"
            ).glob("*/verification.json")
        ),
    ):
        verification = json.loads(verification_path.read_text())
        verification["status"]["result"] = "ROLLED_BACK_AND_VERIFIED"
        verification["status"]["health_gate"] = {
            "result": "WARN",
            "allow_state_warn": True,
            "accepted": True,
            "warn_allowed": True,
            "warning_count": 1,
            "warning_count_complete": True,
            "warning_classifications": {"pre_existing": 1},
        }
        _write_json(verification_path, verification)

    with OperationLock(workspace, "accept", now=JST_NOW) as lock:
        acceptance = accept_rollback_state_warn(
            workspace,
            confirm=lambda _summary: True,
            lock=lock,
            now=lambda: JST_NOW,
        )

    assert acceptance["spec"]["source_workflow_state"] == (
        "rolled_back_and_verified"
    )
    assert load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ] == "rolled_back_and_verified"


def test_accepted_rollback_warn_rejects_later_artifact_change(tmp_path):
    workspace, health_result_path = _eligible_workspace(tmp_path)
    with OperationLock(workspace, "accept", now=JST_NOW) as lock:
        accept_rollback_state_warn(
            workspace,
            confirm=lambda _summary: True,
            lock=lock,
            now=lambda: JST_NOW,
        )
    verification = json.loads(
        (workspace.operation_root / "rollback/verification.json").read_text()
    )
    health_result_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RollbackStateWarnAcceptanceError):
        validate_rollback_state_warn_acceptance(workspace, verification)
