from datetime import datetime
import json
import os
from pathlib import Path
import stat
import socket

import pytest
import yaml

from alred.operation import (
    OperationLock,
    OperationInterruptGuard,
    OperationLockedError,
    OperationPathError,
    OperationArchivedError,
    OperationStateError,
    assess_operation_lock,
    atomic_write_bytes,
    archive_operation_workspace,
    archived_operation_retention_candidates,
    create_operation_workspace,
    close_operation_workspace,
    delete_archived_operation,
    generate_attempt_id,
    generate_change_id,
    load_active_change,
    load_operation_execution,
    load_operation_metadata,
    load_operation_location,
    load_archived_operation_documents,
    publish_latest_operation_link,
    open_operation_workspace,
    preflight_operation_workspace,
    read_operation_lock,
    resolve_active_change_for_after,
    resolve_timezone_name,
    restore_operation_archive,
    save_active_change,
    transition_operation,
    transition_phase,
    transition_workflow,
    validate_change_id,
)


JST_NOW = datetime.fromisoformat("2026-08-01T10:02:03+09:00")


@pytest.mark.parametrize(
    "change_id",
    [
        "CHG-2026-00123",
        "a",
        "A_1.2-3",
    ],
)
def test_validate_change_id_accepts_safe_values(change_id):
    assert validate_change_id(change_id) == change_id


@pytest.mark.parametrize(
    "change_id",
    [
        "",
        ".starts-with-dot",
        "has space",
        "path/value",
        r"path\\value",
        "a..b",
        "a" * 129,
        "あ",
    ],
)
def test_validate_change_id_rejects_unsafe_values(change_id):
    with pytest.raises(ValueError):
        validate_change_id(change_id)


def test_timezone_resolution_precedence_and_invalid_values(monkeypatch):
    monkeypatch.setenv("ALRED_TIMEZONE", "Europe/London")
    assert resolve_timezone_name("Asia/Tokyo") == "Asia/Tokyo"
    assert resolve_timezone_name() == "Europe/London"

    monkeypatch.delenv("ALRED_TIMEZONE")
    assert resolve_timezone_name() == "Asia/Tokyo"
    with pytest.raises(ValueError):
        resolve_timezone_name("JST")
    with pytest.raises(ValueError):
        resolve_timezone_name("+09:00")
    with pytest.raises(ValueError):
        resolve_timezone_name("Not/A_Timezone")


def test_generated_ids_use_jst_offset_and_deterministic_token():
    assert generate_change_id(
        "Asia/Tokyo",
        now=JST_NOW,
        random_hex="a1b2c3",
    ) == "HC-20260801T100203-p0900-a1b2c3"
    assert generate_attempt_id(
        "before",
        "Asia/Tokyo",
        now=JST_NOW,
        random_hex="d4e5f6",
    ) == "before-20260801T100203-p0900-d4e5f6"


def test_create_workspace_is_secure_valid_and_not_overwritten(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-2026-00123",
        timezone_name="Asia/Tokyo",
        now=JST_NOW,
    )

    assert stat.S_IMODE(workspace.operation_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(workspace.metadata_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(workspace.execution_path.stat().st_mode) == 0o600
    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    assert metadata["kind"] == "OperationMetadata"
    assert metadata["metadata"]["change_id_source"] == "specified"
    assert metadata["metadata"]["timezone"] == "Asia/Tokyo"
    assert metadata["metadata"]["utc_offset"] == "+09:00"
    assert metadata["spec"]["purpose"] == "change"
    assert metadata["spec"]["lifecycle"] == "created"
    assert execution["transitions"][0]["to"] == "created"
    assert workspace.operation_root == (
        tmp_path
        / "operations/live/2026/08/01/CHG-2026-00123"
    )
    location = load_operation_location(
        tmp_path / "operations", "CHG-2026-00123"
    )
    assert location["spec"]["state"] == "live"
    assert location["spec"]["layout"] == "dated-v1"

    with pytest.raises(OperationPathError, match="already exists"):
        create_operation_workspace(
            tmp_path / "operations",
            change_id="CHG-2026-00123",
            timezone_name="Asia/Tokyo",
            now=JST_NOW,
        )


def test_generated_workspace_retries_directory_collision(tmp_path):
    first = create_operation_workspace(
        tmp_path / "operations",
        timezone_name="Asia/Tokyo",
        now=JST_NOW,
        random_token_factory=lambda: "a1b2c3",
    )
    retry_tokens = iter(["a1b2c3", "d4e5f6"])
    second = create_operation_workspace(
        tmp_path / "operations",
        timezone_name="Asia/Tokyo",
        now=JST_NOW,
        random_token_factory=lambda: next(retry_tokens),
    )

    assert first.change_id.endswith("a1b2c3")
    assert second.change_id.endswith("d4e5f6")


def test_terminal_operation_archive_is_verified_and_readable(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVE-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    latest = publish_latest_operation_link(workspace)
    assert latest.resolve() == workspace.operation_root.resolve()

    preview = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=14,
        now=datetime.fromisoformat("2026-08-16T10:02:03+09:00"),
        dry_run=True,
    )
    assert preview["status"] == "eligible"
    assert workspace.operation_root.is_dir()

    result = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=14,
        now=datetime.fromisoformat("2026-08-16T10:02:03+09:00"),
    )

    assert result["status"] == "archived"
    assert result["archive"].is_file()
    assert result["checksum"].is_file()
    assert not workspace.operation_root.exists()
    assert not latest.exists()
    assert not latest.is_symlink()
    location = load_operation_location(operations_root, workspace.change_id)
    assert location["spec"]["state"] == "archived"
    metadata, execution, manifest = load_archived_operation_documents(
        operations_root, workspace.change_id
    )
    assert metadata["spec"]["lifecycle"] == "completed"
    assert execution["lifecycle"] == "completed"
    assert manifest["metadata"]["change_id"] == workspace.change_id
    assert manifest["spec"]["age_reference"] == "terminal_transition"
    assert manifest["spec"]["age_reference_at"] == JST_NOW.isoformat()
    assert ".operation.lock" not in {
        item["path"] for item in manifest["spec"]["files"]
    }
    with pytest.raises(OperationArchivedError):
        open_operation_workspace(operations_root, workspace.change_id)


def test_pre_apply_operation_can_be_closed_and_archived(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-CLOSE-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(
            workspace,
            "waiting_for_user",
            lock=lock,
            now=JST_NOW,
        )

    preview = close_operation_workspace(
        operations_root,
        workspace.change_id,
        reason="change was abandoned",
        now=JST_NOW,
        dry_run=True,
    )
    assert preview["status"] == "eligible"
    assert load_operation_metadata(workspace.operation_root)["spec"][
        "lifecycle"
    ] == "waiting_for_user"

    closed = close_operation_workspace(
        operations_root,
        workspace.change_id,
        reason="change was abandoned",
        now=JST_NOW,
    )
    assert closed["status"] == "cancelled"
    metadata = load_operation_metadata(workspace.operation_root)
    assert metadata["spec"]["lifecycle"] == "cancelled"
    assert metadata["spec"]["last_transition"]["reason"] == (
        "operator_closed:change was abandoned"
    )

    archived = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=0,
        now=JST_NOW,
    )
    assert archived["status"] == "archived"


def test_closed_stale_operation_uses_pre_close_activity_for_archive_age(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-CLOSE-STALE",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(
            workspace,
            "waiting_for_user",
            lock=lock,
            now=JST_NOW,
        )
    closed_at = datetime.fromisoformat("2026-08-22T11:23:45+09:00")
    close_operation_workspace(
        operations_root,
        workspace.change_id,
        reason="stale pre-apply operation",
        now=closed_at,
    )

    preview = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=14,
        now=closed_at,
        dry_run=True,
    )
    assert preview["closed_at"] == closed_at.isoformat()
    assert preview["age_reference_at"] == JST_NOW.isoformat()
    assert preview["age_reference"] == "pre_close_last_activity"

    archived = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=14,
        now=closed_at,
    )
    _metadata, _execution, manifest = load_archived_operation_documents(
        operations_root,
        workspace.change_id,
    )
    assert archived["age_reference"] == "pre_close_last_activity"
    assert manifest["spec"]["closed_at"] == closed_at.isoformat()
    assert manifest["spec"]["age_reference_at"] == JST_NOW.isoformat()


def test_operation_close_rejects_workflow_after_apply_started(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-CLOSE-UNSAFE",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)

    with pytest.raises(OperationStateError, match="device mutation"):
        close_operation_workspace(
            operations_root,
            workspace.change_id,
            reason="unsafe close",
            now=JST_NOW,
        )


def test_archived_operation_can_be_verified_and_restored(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-RESTORE-1",
        now=JST_NOW,
    )
    artifact = workspace.operation_root / "health/checklist.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("verified evidence\n", encoding="utf-8")
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    archived = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=0,
        now=JST_NOW,
    )

    restored = restore_operation_archive(
        operations_root,
        workspace.change_id,
    )

    assert restored["status"] == "restored"
    assert restored["lifecycle"] == "completed"
    assert (restored["operation_root"] / "health/checklist.md").read_text(
        encoding="utf-8"
    ) == "verified evidence\n"
    assert not archived["archive"].exists()
    assert not archived["checksum"].exists()
    assert load_operation_location(operations_root, workspace.change_id)["spec"][
        "state"
    ] == "live"
    assert open_operation_workspace(
        operations_root, workspace.change_id
    ).operation_root == restored["operation_root"]


def test_operation_restore_rejects_invalid_external_checksum(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-RESTORE-CHECKSUM",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    archived = archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=0,
        now=JST_NOW,
    )
    archived["checksum"].write_text(
        f"{'0' * 64}  {archived['archive'].name}\n",
        encoding="utf-8",
    )

    with pytest.raises(OperationPathError, match="checksum file is invalid"):
        restore_operation_archive(operations_root, workspace.change_id)

    assert not workspace.operation_root.exists()
    assert archived["archive"].is_file()
    assert load_operation_location(operations_root, workspace.change_id)["spec"][
        "state"
    ] == "archived"


def test_operation_archive_retention_selects_age_or_latest_generations(tmp_path):
    operations_root = tmp_path / "operations"
    archive_times = (
        ("CHG-ARCHIVE-OLD", "2026-08-02T10:02:03+09:00"),
        ("CHG-ARCHIVE-MIDDLE", "2026-08-10T10:02:03+09:00"),
        ("CHG-ARCHIVE-NEW", "2026-08-20T10:02:03+09:00"),
    )
    for change_id, archived_at in archive_times:
        workspace = create_operation_workspace(
            operations_root,
            change_id=change_id,
            now=JST_NOW,
        )
        with OperationLock(workspace, "test", now=JST_NOW) as lock:
            transition_operation(workspace, "running", lock=lock, now=JST_NOW)
            transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
        archive_operation_workspace(
            operations_root,
            change_id,
            older_than_days=0,
            now=datetime.fromisoformat(archived_at),
        )

    by_age = archived_operation_retention_candidates(
        operations_root,
        older_than_days=14,
        now=datetime.fromisoformat("2026-09-01T10:02:03+09:00"),
    )
    by_generation = archived_operation_retention_candidates(
        operations_root,
        keep_latest=1,
    )

    expected = ["CHG-ARCHIVE-OLD", "CHG-ARCHIVE-MIDDLE"]
    assert [item["change_id"] for item in by_age] == expected
    assert [item["change_id"] for item in by_generation] == expected

    preview = delete_archived_operation(
        operations_root,
        "CHG-ARCHIVE-OLD",
        dry_run=True,
    )
    assert preview["status"] == "eligible"
    assert preview["archive"].is_file()

    deleted = delete_archived_operation(
        operations_root,
        "CHG-ARCHIVE-OLD",
    )
    assert deleted["status"] == "deleted"
    assert not deleted["archive"].exists()
    assert load_operation_location(
        operations_root, "CHG-ARCHIVE-OLD"
    ) is None


def test_operation_archive_rejects_nonterminal_and_too_recent(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVE-2",
        now=JST_NOW,
    )
    with pytest.raises(OperationStateError, match="not archivable"):
        archive_operation_workspace(
            operations_root,
            workspace.change_id,
            older_than_days=0,
            now=JST_NOW,
        )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    with pytest.raises(OperationStateError, match="newer than"):
        archive_operation_workspace(
            operations_root,
            workspace.change_id,
            older_than_days=14,
            now=datetime.fromisoformat("2026-08-02T10:02:03+09:00"),
        )


def test_operation_archive_publish_failure_keeps_live_workspace_retryable(
    tmp_path, monkeypatch
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVE-RETRY",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)

    def fail_publish(*_args, **_kwargs):
        raise OSError("simulated index publish failure")

    monkeypatch.setattr(
        "alred.operation._write_operation_location",
        fail_publish,
    )
    with pytest.raises(OSError, match="simulated index publish failure"):
        archive_operation_workspace(
            operations_root,
            workspace.change_id,
            older_than_days=0,
            now=JST_NOW,
        )

    archive_path = (
        operations_root
        / "archive/2026/08/01/CHG-ARCHIVE-RETRY.tar.gz"
    )
    assert workspace.operation_root.is_dir()
    assert not workspace.lock_path.exists()
    assert not archive_path.exists()
    assert not archive_path.with_suffix(".gz.sha256").exists()


def test_atomic_write_rejects_path_escape_and_symlink(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    with pytest.raises(OperationPathError, match="escapes"):
        atomic_write_bytes(
            workspace.operation_root,
            workspace.operation_root / ".." / "outside.txt",
            b"unsafe",
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.operation_root / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OperationPathError, match="symlink"):
        atomic_write_bytes(
            workspace.operation_root,
            link / "file.txt",
            b"unsafe",
        )


def test_lock_is_exclusive_and_never_auto_removes_conflict(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    first = OperationLock(workspace, "plan", now=JST_NOW).acquire()
    try:
        lock_document, warning = read_operation_lock(workspace.operation_root)
        assert warning is None
        assert lock_document["operation"] == "plan"
        with pytest.raises(OperationLockedError):
            OperationLock(workspace, "apply", now=JST_NOW).acquire()
        assert workspace.lock_path.exists()
    finally:
        first.release()

    assert not workspace.lock_path.exists()


def test_corrupt_lock_is_reported_without_removal(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    workspace.lock_path.write_text("{not-json", encoding="utf-8")
    workspace.lock_path.chmod(0o600)

    lock_document, warning = read_operation_lock(workspace.operation_root)

    assert lock_document is None
    assert "invalid" in warning
    assert workspace.lock_path.exists()


def test_lock_assessment_marks_missing_pid_without_removal(monkeypatch):
    document = {
        "hostname": socket.gethostname(),
        "pid": 999999,
    }

    def missing_pid(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", missing_pid)

    assert "stale candidate" in assess_operation_lock(document)[0]


@pytest.mark.parametrize("state", ["completed", "completed_with_warnings", "failed"])
@pytest.mark.parametrize("purpose,allow", [("inspection", True), ("inspection", False), ("change", True)])
def test_completed_operation_reopens_only_for_explicit_inspection_retry(tmp_path, state, purpose, allow):
    workspace = create_operation_workspace(tmp_path / "operations", change_id="RETRY", purpose=purpose, now=JST_NOW)
    with OperationLock(workspace, "retry", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, state, lock=lock, now=JST_NOW)
        if purpose == "inspection" and allow and state != "failed":
            transition_operation(workspace, "running", lock=lock, now=JST_NOW, allow_inspection_retry=allow)
            assert load_operation_metadata(workspace.operation_root)["spec"]["lifecycle"] == "running"
        else:
            with pytest.raises(OperationStateError, match="invalid operation transition"):
                transition_operation(workspace, "running", lock=lock, now=JST_NOW, allow_inspection_retry=allow)


def test_operation_phase_and_workflow_transitions_require_lock(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    unlocked = OperationLock(workspace, "plan", now=JST_NOW)
    with pytest.raises(OperationLockedError):
        transition_operation(workspace, "running", lock=unlocked)

    with OperationLock(workspace, "plan", now=JST_NOW) as lock:
        transition_operation(
            workspace,
            "running",
            lock=lock,
            reason="test_start",
            now=JST_NOW,
        )
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="before-attempt-001",
            now=JST_NOW,
        )
        transition_phase(
            workspace,
            "before",
            "completed",
            lock=lock,
            now=JST_NOW,
        )
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
        ):
            transition_workflow(
                workspace,
                state,
                lock=lock,
                now=JST_NOW,
            )
        with pytest.raises(OperationStateError):
            transition_phase(
                workspace,
                "before",
                "running",
                lock=lock,
                now=JST_NOW,
            )

    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    assert metadata["spec"]["lifecycle"] == "running"
    assert metadata["spec"]["phases"]["before"] == {
        "current_attempt": "before-attempt-001",
        "status": "completed",
    }
    assert metadata["spec"]["workflow_state"] == "plan_ready"
    assert len(execution["transitions"]) == 8


def test_interrupt_before_device_commands_records_cancelled(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "before", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="before-attempt-001",
            now=JST_NOW,
        )
        guard = OperationInterruptGuard(workspace, lock, phase="before")
        with pytest.raises(KeyboardInterrupt):
            guard._handle(2, None)

    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    assert metadata["spec"]["lifecycle"] == "cancelled"
    assert metadata["spec"]["phases"]["before"]["status"] == "cancelled"
    assert execution["errors"][-1]["code"] == "CANCELLED_BEFORE_APPLY"


def test_interrupt_during_apply_records_unknown_device_state(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
        guard = OperationInterruptGuard(workspace, lock, phase="apply")
        guard.mark_device_commands_started()
        with pytest.raises(KeyboardInterrupt):
            guard._handle(15, None)

    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    assert metadata["spec"]["lifecycle"] == "state_unknown"
    assert metadata["spec"]["workflow_state"] == "device_state_unknown"
    assert execution["errors"][-1]["code"] == "DEVICE_STATE_UNKNOWN"


def test_rollback_health_failed_can_be_reverified_without_reapplying(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )
    with OperationLock(workspace, "rollback-health", now=JST_NOW) as lock:
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
            "rollback_health_failed",
            "rolled_back_and_verified",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)

    assert load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ] == "rolled_back_and_verified"


def test_preflight_reports_device_limit(tmp_path):
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-1",
        now=JST_NOW,
    )

    result = preflight_operation_workspace(
        workspace,
        device_count=51,
        for_apply=True,
    )

    assert result.ok is False
    assert any(
        issue.code == "PLAN_CONFLICT" and "51" in issue.message
        for issue in result.issues
    )


def test_active_change_is_atomic_and_schema_validated(tmp_path):
    operations_root = tmp_path / "operations"
    document = {
        "api_version": "alred/v1",
        "kind": "ActiveHealthCheckChange",
        "metadata": {
            "updated_at": "2026-08-01T10:05:31+09:00",
            "timezone": "Asia/Tokyo",
        },
        "spec": {
            "change_id": "HC-20260801T100203-p0900-a1b2c3",
            "change_id_source": "generated",
            "state": "before_completed",
            "output_root": "operations/HC-20260801T100203-p0900-a1b2c3",
            "before": {
                "completed_at": "2026-08-01T10:05:31+09:00",
                "metadata_path": "operations/example/metadata.yaml",
                "snapshot_path": "operations/example/health/before/snapshot.json",
                "inventory_sha256": "a" * 64,
                "profile_sha256": "b" * 64,
            },
            "after": {
                "status": "not_started",
            },
        },
    }

    output_path = save_active_change(operations_root, document)

    assert output_path == operations_root / ".state" / "active-change.yaml"
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert load_active_change(operations_root) == document


def test_after_resolves_only_valid_recorded_active_change(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        timezone_name="Asia/Tokyo",
        now=JST_NOW,
        random_token_factory=lambda: "a1b2c3",
    )
    snapshot_path = workspace.operation_root / "health" / "before" / "snapshot.json"
    atomic_write_bytes(
        workspace.operation_root,
        snapshot_path,
        b'{"schema_version":1}\n',
    )
    with OperationLock(workspace, "before", now=JST_NOW) as lock:
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="before-attempt-001",
            now=JST_NOW,
        )
        transition_phase(
            workspace,
            "before",
            "completed",
            lock=lock,
            now=JST_NOW,
        )
    state = {
        "api_version": "alred/v1",
        "kind": "ActiveHealthCheckChange",
        "metadata": {
            "updated_at": "2026-08-01T10:05:31+09:00",
            "timezone": "Asia/Tokyo",
        },
        "spec": {
            "change_id": workspace.change_id,
            "change_id_source": "generated",
            "state": "before_completed",
            "output_root": str(workspace.operation_root),
            "before": {
                "completed_at": "2026-08-01T10:05:31+09:00",
                "metadata_path": str(workspace.metadata_path),
                "snapshot_path": str(snapshot_path),
                "inventory_sha256": "a" * 64,
                "profile_sha256": "b" * 64,
            },
            "after": {"status": "not_started"},
        },
    }
    save_active_change(operations_root, state)

    resolved = resolve_active_change_for_after(
        operations_root,
        inventory_sha256="a" * 64,
        profile_sha256="b" * 64,
    )

    assert resolved.change_id == workspace.change_id
    with pytest.raises(OperationStateError, match="inventory hash"):
        resolve_active_change_for_after(
            operations_root,
            inventory_sha256="c" * 64,
            profile_sha256="b" * 64,
        )


def test_open_workspace_rejects_metadata_change_id_conflict(tmp_path):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    metadata = yaml.safe_load(workspace.metadata_path.read_text(encoding="utf-8"))
    metadata["metadata"]["change_id"] = "CHG-2"
    workspace.metadata_path.write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )
    workspace.metadata_path.chmod(0o600)

    with pytest.raises(OperationPathError, match="does not match"):
        open_operation_workspace(operations_root, "CHG-1")
