import argparse
from datetime import datetime
import hashlib
import json

import pytest

from alred.cli import (
    build_parser,
    cmd_operation_archive,
    cmd_operation_inspect,
    cmd_operation_status,
    cmd_overlay_change_approve,
    cmd_overlay_change_accept_rollback_state_warn,
    cmd_overlay_change_qualify,
    cmd_overlay_change_qualify_approve,
    cmd_overlay_change_qualify_rollback,
    cmd_overlay_change_save,
)
from alred.operation import (
    OperationLock,
    archive_operation_workspace,
    create_operation_workspace,
    load_operation_location,
    transition_operation,
    transition_workflow,
)


JST_NOW = datetime.fromisoformat("2026-08-01T10:02:03+09:00")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_operation_status_is_read_only_and_concise(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    before_hashes = (
        _sha256(workspace.metadata_path),
        _sha256(workspace.execution_path),
    )

    cmd_operation_status(
        argparse.Namespace(
            operations_root=str(operations_root),
            change_id="CHG-1",
        )
    )

    output = capsys.readouterr().out
    assert "=== OPERATION STATUS ===" in output
    assert "Lifecycle      : created" in output
    assert "Lock           : not held" in output
    assert (
        _sha256(workspace.metadata_path),
        _sha256(workspace.execution_path),
    ) == before_hashes


def test_operation_inspect_is_read_only_and_shows_hashes(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    before_hashes = (
        _sha256(workspace.metadata_path),
        _sha256(workspace.execution_path),
    )

    cmd_operation_inspect(
        argparse.Namespace(
            operations_root=str(operations_root),
            change_id="CHG-1",
        )
    )

    output = capsys.readouterr().out
    assert "=== OPERATION INSPECT ===" in output
    assert "Metadata SHA-256: sha256:" in output
    assert "Transitions:" in output
    assert (
        _sha256(workspace.metadata_path),
        _sha256(workspace.execution_path),
    ) == before_hashes


@pytest.mark.parametrize(
    "arguments, expected_function",
    [
        (
            [
                "operation",
                "status",
                "--change-id",
                "CHG-1",
            ],
            cmd_operation_status,
        ),
        (
            [
                "operation",
                "inspect",
                "--change-id",
                "CHG-1",
            ],
            cmd_operation_inspect,
        ),
        (
            [
                "operation",
                "archive",
                "--change-id",
                "CHG-1",
                "--dry-run",
            ],
            cmd_operation_archive,
        ),
    ],
)
def test_operation_cli_dispatch(arguments, expected_function):
    args = build_parser().parse_args(arguments)

    assert args.func is expected_function
    assert args.operations_root == "operations"


def test_operation_archive_help_exposes_explicit_retention_modes(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["operation", "archive", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--delete-older-than-days DAYS" in output
    assert "--keep-latest-archives COUNT" in output

    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "operation",
            "archive",
            "--delete-older-than-days",
            "30",
            "--keep-latest-archives",
            "10",
        ])


def test_operation_status_reads_verified_archive_without_extracting(
    tmp_path, capsys
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVED",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=0,
        now=JST_NOW,
    )

    cmd_operation_status(
        argparse.Namespace(
            operations_root=str(operations_root),
            change_id=workspace.change_id,
        )
    )

    output = capsys.readouterr().out
    assert "Storage        : archived" in output
    assert "Archive files :" in output
    assert "checksum verified" in output


def test_operation_archive_rejects_an_already_archived_id_without_traceback(
    tmp_path, capsys
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVED",
        now=JST_NOW,
    )
    with OperationLock(workspace, "test", now=JST_NOW) as lock:
        transition_operation(workspace, "running", lock=lock, now=JST_NOW)
        transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    archive_operation_workspace(
        operations_root,
        workspace.change_id,
        older_than_days=0,
        now=JST_NOW,
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_operation_archive(
            argparse.Namespace(
                operations_root=str(operations_root),
                change_id=workspace.change_id,
                older_than_days=0,
                dry_run=False,
            )
        )

    assert exc_info.value.code == 2
    assert "OPERATION_ARCHIVED" in capsys.readouterr().err


def test_operation_archive_retention_mode_does_not_archive_live_operations(
    tmp_path, capsys
):
    operations_root = tmp_path / "operations"
    archived = create_operation_workspace(
        operations_root,
        change_id="CHG-ARCHIVED",
        now=JST_NOW,
    )
    live = create_operation_workspace(
        operations_root,
        change_id="CHG-LIVE",
        now=JST_NOW,
    )
    for workspace in (archived, live):
        with OperationLock(workspace, "test", now=JST_NOW) as lock:
            transition_operation(workspace, "running", lock=lock, now=JST_NOW)
            transition_operation(workspace, "completed", lock=lock, now=JST_NOW)
    archive_operation_workspace(
        operations_root,
        archived.change_id,
        older_than_days=0,
        now=JST_NOW,
    )

    cmd_operation_archive(argparse.Namespace(
        operations_root=str(operations_root),
        change_id=None,
        older_than_days=0,
        dry_run=False,
        delete_older_than_days=None,
        keep_latest_archives=0,
    ))

    assert "Archive creation skipped in archive retention mode." in (
        capsys.readouterr().out
    )
    assert load_operation_location(
        operations_root, archived.change_id
    ) is None
    assert load_operation_location(
        operations_root, live.change_id
    )["spec"]["state"] == "live"


def test_overlay_approve_help_documents_initial_safety_options(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["overlay-change", "approve", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--approval-hours" in output
    assert "--rollback-policy {manual}" in output
    assert "--no-save-on-success" in output
    assert "default: <operation>/plan/execution-plan.json" in " ".join(
        output.split()
    )


def test_overlay_approve_accepts_change_id_only():
    args = build_parser().parse_args(
        ["overlay-change", "approve", "--change-id", "CHG-1"]
    )

    assert args.func is cmd_overlay_change_approve
    assert args.plan is None
    assert args.rollback_plan is None
    assert args.operations_root == "operations"
    assert args.save_on_success is True
    assert args.rollback_policy == "manual"


def test_overlay_qualify_approve_help_documents_lab_safety(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            ["overlay-change", "qualify-approve", "--help"]
        )

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--approval-hours" in output
    assert "--hosts" in output
    assert "PLAN_ONLY Nexus 9000v" in output


def test_overlay_qualify_approve_cli_dispatch():
    args = build_parser().parse_args(
        [
            "overlay-change",
            "qualify-approve",
            "--change-id",
            "CHG-1",
            "--hosts",
            "hosts.lab.yaml",
        ]
    )

    assert args.func is cmd_overlay_change_qualify_approve
    assert args.approval_hours == 4


def test_overlay_qualify_help_documents_no_save_and_serial(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["overlay-change", "qualify", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "serial=1" in output
    assert "no automatic rollback" in output
    assert "no save" in output


def test_overlay_qualify_cli_dispatch():
    args = build_parser().parse_args(
        [
            "overlay-change",
            "qualify",
            "--change-id",
            "CHG-1",
            "--hosts",
            "hosts.lab.yaml",
        ]
    )

    assert args.func is cmd_overlay_change_qualify


def test_overlay_qualify_rollback_help_documents_safety(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["overlay-change", "qualify-rollback", "--help"]
        )
    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "reverse device order" in normalized
    assert "No retry or save" in normalized


def test_overlay_qualify_rollback_cli_dispatch():
    args = build_parser().parse_args(
        [
            "overlay-change",
            "qualify-rollback",
            "--change-id",
            "CHG-1",
            "--hosts",
            "hosts.lab.yaml",
        ]
    )
    assert args.func is cmd_overlay_change_qualify_rollback
    assert args.qualification_record is None


def test_overlay_save_help_and_cli_dispatch(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["overlay-change", "save", "--help"])

    assert exc_info.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "after Snapshot" in output
    assert "without retry" in output

    args = build_parser().parse_args(
        ["overlay-change", "save", "--change-id", "CHG-1"]
    )
    assert args.func is cmd_overlay_change_save
    assert args.after_snapshot is None

    rollback_args = build_parser().parse_args(
        ["overlay-change", "save-rollback", "--change-id", "CHG-1"]
    )
    assert rollback_args.func is cmd_overlay_change_save
    assert rollback_args.save_mode == "rollback"

    acceptance_args = build_parser().parse_args(
        [
            "overlay-change",
            "accept-rollback-state-warn",
            "--change-id",
            "CHG-1",
        ]
    )
    assert (
        acceptance_args.func
        is cmd_overlay_change_accept_rollback_state_warn
    )


def test_accept_rollback_state_warn_cli_displays_evidence_and_exact_phrase(
    tmp_path,
    monkeypatch,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-WARN-1",
        now=JST_NOW,
    )
    phrase = "ACCEPT ROLLBACK STATE WARN CHG-WARN-1"
    monkeypatch.setattr("alred.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("alred.cli.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: phrase)

    def fake_accept(operation, *, confirm, lock, now):
        summary = {
            "change_id": operation.change_id,
            "attempt_id": "rollback-1",
            "warning_count": 1,
            "warning_classifications": {"pre_existing": 1},
            "gates": {
                "snapshot_fresh": True,
                "raw_config_equal": True,
                "semantic_config_equal": True,
            },
            "warnings": [
                {
                    "host": "leaf01",
                    "check_id": "ntp_health",
                    "classification": "pre_existing",
                    "message": "NTP is not synchronized",
                }
            ],
            "verification_path": "verification.json",
            "verification_sha256": "sha256:" + "a" * 64,
            "health_result_path": "health-result.json",
            "health_result_sha256": "sha256:" + "b" * 64,
            "confirmation_phrase": phrase,
        }
        assert confirm(summary)
        return {
            "spec": {
                "verification_kind": "ManagedRollbackVerification"
            }
        }

    monkeypatch.setattr("alred.cli.accept_rollback_state_warn", fake_accept)
    args = build_parser().parse_args(
        [
            "overlay-change",
            "accept-rollback-state-warn",
            "--change-id",
            workspace.change_id,
            "--operations-root",
            str(operations_root),
        ]
    )

    assert cmd_overlay_change_accept_rollback_state_warn(args) == 0
    output = capsys.readouterr().out
    assert "leaf01/ntp_health: pre_existing" in output
    assert phrase in output
    assert "Workflow    : rolled_back_and_verified" in output


def test_overlay_approve_rejects_non_tty_before_creating_record(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    plan_dir = workspace.operation_root / "plan"
    plan_dir.mkdir(mode=0o700)
    plan_path = plan_dir / "execution-plan.json"
    rollback_path = plan_dir / "rollback-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": "CHG-1",
                "capability_level": "APPLY_VERIFIED",
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
    rollback_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": "CHG-1",
                "policy": "manual",
                "devices": [],
            }
        ),
        encoding="utf-8",
    )
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

    args = build_parser().parse_args(
        [
            "overlay-change",
            "approve",
            "--change-id",
            "CHG-1",
            "--operations-root",
            str(operations_root),
        ]
    )
    with pytest.raises(SystemExit) as exc_info:
        cmd_overlay_change_approve(args)

    assert exc_info.value.code == 2
    assert "APPROVAL_REQUIRED" in capsys.readouterr().err
    assert not (workspace.operation_root / "approval").exists()
