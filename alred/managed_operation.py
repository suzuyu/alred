"""Normal approved Overlay apply execution."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .approval import (
    ApprovalRequiredError,
    calculate_approval_artifact_hashes,
    validate_approval,
)
from .health.evaluator import compare_snapshots
from .health.profile import load_resolved_profiles
from .health.report import render_health_summary
from .health.roles import load_resolved_roles
from .managed_config import (
    build_execution_document,
    execute_save_session,
    execute_serial_devices,
    load_managed_config_commands,
)
from .operation import (
    OperationInterruptGuard,
    OperationLock,
    OperationStateError,
    OperationWorkspace,
    atomic_write_bytes,
    atomic_write_json,
    load_operation_metadata,
    transition_operation,
    transition_workflow,
)
from .qualification import (
    QualificationError,
    _expected_running_configs,
    _normalized_running_config,
    _rollback_residual_references,
    _running_config_diff_is_clean,
)
from .rollback_verification import (
    build_device_verification,
    evaluate_rollback_health_gate,
    render_rollback_verification_checklist,
    rollback_snapshot_is_fresh,
    rollback_verification_passes,
)
from .schema import API_VERSION, source_sha256, validate_document


class RollbackStateWarnAcceptanceError(QualificationError):
    """Raised when rollback state WARN cannot be explicitly accepted."""

    code = "VALIDATION_ERROR"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"managed artifact not found: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"managed artifact must be an object: {path}")
    return value


def rollback_state_warn_confirmation_phrase(change_id: str) -> str:
    """Return the exact phrase required to accept rollback state WARN."""
    return f"ACCEPT ROLLBACK STATE WARN {change_id}"


def _rollback_verification_root(workspace: OperationWorkspace) -> Path:
    qualification = (
        workspace.operation_root
        / "qualification/qualification-record.json"
    ).is_file()
    return (
        workspace.operation_root / "qualification/rollback"
        if qualification
        else workspace.operation_root / "rollback"
    )


def _operation_artifact_path(
    workspace: OperationWorkspace,
    value: str | Path,
) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve()
    operation_root = workspace.operation_root.resolve()
    if not resolved.is_relative_to(operation_root) and not candidate.is_absolute():
        resolved = (operation_root / candidate).resolve()
    if not resolved.is_relative_to(operation_root):
        raise RollbackStateWarnAcceptanceError(
            f"rollback acceptance artifact is outside operation root: {value}"
        )
    if not resolved.is_file() or resolved.is_symlink():
        raise RollbackStateWarnAcceptanceError(
            f"rollback acceptance artifact is not a regular file: {value}"
        )
    return resolved


def build_rollback_state_warn_acceptance_summary(
    workspace: OperationWorkspace,
) -> dict[str, Any]:
    """Validate and summarize the latest eligible rollback WARN evidence."""
    workflow_state = load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ]
    if workflow_state not in {
        "rollback_health_failed",
        "rolled_back_and_verified",
    }:
        raise OperationStateError(
            "rollback state WARN acceptance requires rollback_health_failed "
            "or a legacy WARN-based rolled_back_and_verified "
            f"workflow state (current workflow state: {workflow_state})"
        )
    verification_root = _rollback_verification_root(workspace)
    acceptance_path = verification_root / "state-warn-acceptance.json"
    if acceptance_path.exists():
        raise RollbackStateWarnAcceptanceError(
            f"rollback state WARN acceptance already exists: {acceptance_path}"
        )
    current_path = verification_root / "verification-current.json"
    current = _load_json(current_path)
    validate_document(current, kind="RollbackVerificationCurrent")
    if current["change_id"] != workspace.change_id:
        raise RollbackStateWarnAcceptanceError(
            "rollback verification current change_id mismatch"
        )
    verification_path = _operation_artifact_path(
        workspace,
        current["verification_path"],
    )
    health_result_path = _operation_artifact_path(
        workspace,
        current["health_report_path"],
    )
    verification = _load_json(verification_path)
    verification_kind = verification.get("kind")
    if verification_kind not in {
        "ManagedRollbackVerification",
        "QualificationRollbackVerification",
    }:
        raise RollbackStateWarnAcceptanceError(
            "rollback verification kind is not eligible for state WARN acceptance"
        )
    validate_document(verification, kind=verification_kind)
    health_result = _load_json(health_result_path)
    validate_document(health_result, kind="HealthResult")
    if (
        verification["metadata"]["change_id"] != workspace.change_id
        or health_result["change_id"] != workspace.change_id
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback acceptance evidence change_id mismatch"
        )
    if _operation_artifact_path(
        workspace,
        verification["artifacts"]["health_result"],
    ) != health_result_path:
        raise RollbackStateWarnAcceptanceError(
            "rollback verification HealthResult path mismatch"
        )
    status = verification["status"]
    health_gate = evaluate_rollback_health_gate(health_result)
    recorded_health_gate = status.get("health_gate")
    if (
        recorded_health_gate is not None
        and "state_warn_eligible" in recorded_health_gate
        and recorded_health_gate != health_gate
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback verification health gate does not match HealthResult"
        )
    normal_warn_candidate = (
        workflow_state == "rollback_health_failed"
        and current["result"] == "ROLLBACK_HEALTH_FAILED"
        and status.get("result") == "ROLLBACK_HEALTH_FAILED"
    )
    legacy_warn_candidate = (
        workflow_state == "rolled_back_and_verified"
        and current["result"] == "ROLLED_BACK_AND_VERIFIED"
        and status.get("result") == "ROLLED_BACK_AND_VERIFIED"
        and bool(recorded_health_gate)
        and recorded_health_gate.get("allow_state_warn") is True
        and recorded_health_gate.get("warn_allowed") is True
    )
    if (
        not (normal_warn_candidate or legacy_warn_candidate)
        or status.get("health_result") != "WARN"
        or health_result.get("result") != "WARN"
        or not health_gate["state_warn_eligible"]
        or not status.get("snapshot_fresh")
        or not status.get("raw_config_equal")
        or not status.get("semantic_config_equal")
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback state WARN is not eligible for acceptance"
        )
    before_snapshot_path = _operation_artifact_path(
        workspace,
        verification["artifacts"]["before_snapshot"],
    )
    rollback_snapshot_path = _operation_artifact_path(
        workspace,
        verification["artifacts"]["rollback_snapshot"],
    )
    rollback_current_path = workspace.operation_root / "health/rollback/current.json"
    rollback_current = _load_json(rollback_current_path)
    validate_document(rollback_current, kind="HealthPhaseCurrent")
    if (
        rollback_current["attempt_id"] != current["attempt_id"]
        or _operation_artifact_path(
            workspace,
            rollback_current["snapshot_path"],
        )
        != rollback_snapshot_path
        or rollback_current["snapshot_sha256"]
        != source_sha256(rollback_snapshot_path)
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback current Snapshot does not match verification attempt"
        )
    warnings = [
        {
            "host": str(check.get("host", "global")),
            "check_id": str(check.get("check_id", "unknown")),
            "classification": str(check.get("classification", "unclassified")),
            "message": str(check.get("message", "")),
        }
        for check in health_result["checks"]
        if check.get("result") == "WARN"
    ]
    return {
        "change_id": workspace.change_id,
        "source_workflow_state": workflow_state,
        "attempt_id": current["attempt_id"],
        "confirmation_phrase": rollback_state_warn_confirmation_phrase(
            workspace.change_id
        ),
        "verification_kind": verification_kind,
        "verification_path": str(verification_path),
        "verification_sha256": source_sha256(verification_path),
        "health_result_path": str(health_result_path),
        "health_result_sha256": source_sha256(health_result_path),
        "before_snapshot_path": str(before_snapshot_path),
        "before_snapshot_sha256": source_sha256(before_snapshot_path),
        "rollback_snapshot_path": str(rollback_snapshot_path),
        "rollback_snapshot_sha256": source_sha256(rollback_snapshot_path),
        "warning_count": health_gate["warning_count"],
        "warning_classifications": health_gate["warning_classifications"],
        "gates": {
            "snapshot_fresh": status["snapshot_fresh"],
            "raw_config_equal": status["raw_config_equal"],
            "semantic_config_equal": status["semantic_config_equal"],
        },
        "warnings": warnings,
        "acceptance_path": str(
            acceptance_path
        ),
    }


def accept_rollback_state_warn(
    workspace: OperationWorkspace,
    *,
    confirm: Callable[[Mapping[str, Any]], bool],
    lock: OperationLock,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """Accept an eligible published rollback WARN without mutating evidence."""
    lock.assert_held()
    summary = build_rollback_state_warn_acceptance_summary(workspace)
    if not confirm(summary):
        raise ApprovalRequiredError(
            "exact rollback state WARN acceptance phrase was not provided"
        )
    accepted_at = now()
    document = {
        "api_version": API_VERSION,
        "kind": "RollbackStateWarnAcceptance",
        "metadata": {
            "change_id": workspace.change_id,
            "accepted_at": accepted_at.isoformat(timespec="seconds"),
            "timezone": workspace.timezone,
        },
        "spec": {
            "attempt_id": summary["attempt_id"],
            "source_workflow_state": summary["source_workflow_state"],
            "confirmation_phrase": summary["confirmation_phrase"],
            "verification_kind": summary["verification_kind"],
            "verification_path": summary["verification_path"],
            "verification_sha256": summary["verification_sha256"],
            "health_result_path": summary["health_result_path"],
            "health_result_sha256": summary["health_result_sha256"],
            "before_snapshot_path": summary["before_snapshot_path"],
            "before_snapshot_sha256": summary["before_snapshot_sha256"],
            "rollback_snapshot_path": summary["rollback_snapshot_path"],
            "rollback_snapshot_sha256": summary[
                "rollback_snapshot_sha256"
            ],
            "warning_count": summary["warning_count"],
            "warning_classifications": summary[
                "warning_classifications"
            ],
        },
        "status": {"result": "ACCEPTED"},
    }
    acceptance_path = Path(summary["acceptance_path"])
    atomic_write_json(
        workspace.operation_root,
        acceptance_path,
        document,
        kind="RollbackStateWarnAcceptance",
    )
    if summary["source_workflow_state"] == "rollback_health_failed":
        transition_workflow(
            workspace,
            "rolled_back_and_verified",
            lock=lock,
            reason="rollback_state_warn_accepted",
            now=accepted_at,
        )
    return document


def validate_rollback_state_warn_acceptance(
    workspace: OperationWorkspace,
    verification: Mapping[str, Any],
) -> tuple[str, str, str]:
    acceptance_path = (
        workspace.operation_root / "rollback/state-warn-acceptance.json"
    )
    if not acceptance_path.is_file() or acceptance_path.is_symlink():
        raise RollbackStateWarnAcceptanceError(
            "rollback WARN save requires "
            "overlay-change accept-rollback-state-warn first"
        )
    acceptance = _load_json(acceptance_path)
    validate_document(acceptance, kind="RollbackStateWarnAcceptance")
    if (
        acceptance["metadata"]["change_id"] != workspace.change_id
        or acceptance["status"]["result"] != "ACCEPTED"
        or acceptance["spec"]["verification_kind"]
        != "ManagedRollbackVerification"
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback state WARN acceptance does not match managed operation"
        )
    spec = acceptance["spec"]
    artifacts = (
        ("verification_path", "verification_sha256"),
        ("health_result_path", "health_result_sha256"),
        ("before_snapshot_path", "before_snapshot_sha256"),
        ("rollback_snapshot_path", "rollback_snapshot_sha256"),
    )
    for path_key, hash_key in artifacts:
        artifact = _operation_artifact_path(workspace, spec[path_key])
        if source_sha256(artifact) != spec[hash_key]:
            raise RollbackStateWarnAcceptanceError(
                f"rollback state WARN acceptance artifact changed: {path_key}"
            )
    canonical_verification = (
        workspace.operation_root / "rollback/verification.json"
    )
    if (
        source_sha256(canonical_verification)
        != spec["verification_sha256"]
        or verification["status"].get("health_result") != "WARN"
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback state WARN acceptance no longer matches verification"
        )
    return (
        str(acceptance_path),
        source_sha256(acceptance_path),
        spec["rollback_snapshot_sha256"],
    )


def _write_evidence(
    workspace: OperationWorkspace,
    result: Mapping[str, Any],
    *,
    mode: str = "apply",
) -> None:
    for host, device in result["devices"].items():
        root = workspace.operation_root / mode / "devices" / host
        atomic_write_bytes(
            workspace.operation_root,
            root / "command-results.json",
            (
                json.dumps(device, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode(),
        )
        lines = [f"host: {host}", f"status: {device['status']}", ""]
        for command in device["commands"]:
            lines.extend(
                [
                    f"[{command['index']}] {command['status']} "
                    f"{command['command']}",
                    f"error: {command['error'] or '-'}",
                    "response:",
                    command["response"],
                    "",
                ]
            )
        atomic_write_bytes(
            workspace.operation_root,
            root / "commands.log",
            ("\n".join(lines).rstrip() + "\n").encode(),
        )


def execute_approved_apply(
    workspace: OperationWorkspace,
    approval: Mapping[str, Any],
    *,
    plan_path: str | Path,
    rollback_plan_path: str | Path,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
) -> dict[str, Any]:
    """Apply an exact approved plan with same-session running-config drift checks."""
    lock.assert_held()
    started_at = now()
    plan_file = Path(plan_path).resolve()
    rollback_file = Path(rollback_plan_path).resolve()
    plan = _load_json(plan_file)
    rollback = _load_json(rollback_file)
    expected_hashes = calculate_approval_artifact_hashes(
        workspace,
        plan,
        rollback,
    )
    validate_approval(
        approval,
        expected_change_id=workspace.change_id,
        expected_artifacts=expected_hashes,
        now=started_at,
    )
    if plan.get("capability_level") != "APPLY_VERIFIED":
        raise QualificationError("approved plan is not APPLY_VERIFIED")
    if load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ] != "approved":
        raise OperationStateError("workflow must be approved before apply")
    devices = [
        host
        for host, item in plan["devices"].items()
        if item["status"] == "PLANNED"
    ]
    if set(devices) - set(inventory_hosts):
        raise QualificationError("plan target is absent from pinned inventory")
    inventory_path = Path(plan["artifacts"]["inventory"])
    if source_sha256(inventory_path) != plan["artifacts"]["inventory_sha256"]:
        raise QualificationError("pinned inventory hash mismatch")
    before = _load_json(Path(plan["artifacts"]["before_snapshot"]))
    expected_configs = _expected_running_configs(before, devices)
    pre_apply_diffs: dict[str, str | None] = {
        host: None for host in devices
    }
    commands = {}
    configs = {}
    for host in devices:
        config_path = workspace.operation_root / plan["devices"][host][
            "forward_config"
        ]
        if source_sha256(config_path) != plan["devices"][host]["forward_sha256"]:
            raise QualificationError(f"{host}: forward config hash mismatch")
        commands[host] = load_managed_config_commands(config_path)
        configs[host] = {
            "path": str(config_path),
            "sha256": source_sha256(config_path),
        }

    def precheck(host: str, connection: Any) -> tuple[bool, str, str]:
        try:
            current = str(
                connection.send_command(
                    "show running-config",
                    read_timeout=120,
                    strip_prompt=True,
                    strip_command=True,
                )
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}", "UNKNOWN"
        if _normalized_running_config(current) != expected_configs[host]:
            return False, "running-config drift from approved before", "FAILED"
        if approval["constraints"]["save_on_success"]:
            try:
                diff = str(
                    connection.send_command(
                        "show running-config diff",
                        read_timeout=120,
                        strip_prompt=True,
                        strip_command=True,
                    )
                )
            except Exception as exc:
                return False, f"{type(exc).__name__}: {exc}", "UNKNOWN"
            pre_apply_diffs[host] = diff
            if not _running_config_diff_is_clean(diff):
                return (
                    False,
                    "running-config already differs from startup-config; "
                    "save-on-success would persist unrelated changes",
                    "FAILED",
                )
        return True, "running-config matches approved before", "FAILED"

    started = False

    def before_commands(_host: str) -> None:
        nonlocal started
        if not started:
            transition_workflow(
                workspace,
                "apply_running",
                lock=lock,
                reason="approved_overlay_apply_started",
                now=now(),
            )
            started = True
        if interrupt_guard:
            interrupt_guard.mark_device_commands_started()

    serial = execute_serial_devices(
        devices,
        commands,
        connect=connect,
        disconnect=disconnect,
        precheck=precheck,
        before_commands=before_commands,
        now=now,
    )
    completed_at = now()
    if not started:
        transition_workflow(
            workspace,
            "apply_running",
            lock=lock,
            reason=(
                "approved_overlay_apply_no_changes"
                if not devices
                else "approved_apply_precheck_failed"
            ),
            now=completed_at,
        )
    execution = build_execution_document(
        change_id=workspace.change_id,
        mode="apply",
        started_at=started_at,
        completed_at=completed_at,
        timezone_name=workspace.timezone,
        execution_plan_sha256=expected_hashes["execution_plan"],
        rollback_plan_sha256=expected_hashes["rollback_plan"],
        approval_id=approval["approval_id"],
        serial_result=serial,
        config_artifacts=configs,
    )
    for host, diff in pre_apply_diffs.items():
        execution["status"]["devices"][host]["pre_apply_diff"] = diff
    validate_document(execution, kind="OverlayConfigExecution")
    _write_evidence(workspace, serial)
    atomic_write_json(
        workspace.operation_root,
        workspace.operation_root / "apply" / "execution.json",
        execution,
        kind="OverlayConfigExecution",
    )
    transition_workflow(
        workspace,
        "apply_completed" if serial["status"] == "SUCCESS" else "apply_failed",
        lock=lock,
        reason="approved_overlay_apply_finished",
        now=completed_at,
    )
    if serial["status"] != "SUCCESS":
        transition_workflow(
            workspace,
            "rollback_required",
            lock=lock,
            reason="manual_rollback_decision_required",
            now=completed_at,
        )
    return execution


def execute_approved_save(
    workspace: OperationWorkspace,
    approval: Mapping[str, Any],
    *,
    plan_path: str | Path,
    rollback_plan_path: str | Path,
    after_snapshot_path: str | Path,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    save_command: str,
    success_marker: str | None,
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
    save_mode: str = "apply",
) -> dict[str, Any]:
    """Save a verified approved apply serially, without automatic retry."""
    lock.assert_held()
    if save_mode not in {"apply", "rollback"}:
        raise ValueError(f"unsupported approved save mode: {save_mode}")
    started_at = now()
    plan = _load_json(Path(plan_path).resolve())
    rollback = _load_json(Path(rollback_plan_path).resolve())
    hashes = calculate_approval_artifact_hashes(workspace, plan, rollback)
    if save_mode == "apply":
        validate_approval(
            approval,
            expected_change_id=workspace.change_id,
            expected_artifacts=hashes,
            now=started_at,
        )
    else:
        # A verified rollback may need its startup-config restored after the
        # original approval expires. Keep artifact/policy validation, but do
        # not block this safety action on time alone.
        validate_document(
            approval,
            kind="ApprovalRecord",
            allow_unknown_fields=True,
        )
        if approval["change_id"] != workspace.change_id or dict(
            approval["artifacts"]
        ) != hashes:
            raise QualificationError(
                "rollback save approval artifact mismatch"
            )
    if not approval["constraints"]["save_on_success"]:
        raise QualificationError(
            "approval record does not authorize save_on_success"
        )
    required_state = (
        "after_completed"
        if save_mode == "apply"
        else "rolled_back_and_verified"
    )
    workflow_state = load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ]
    if workflow_state != required_state:
        state_details = [f"current workflow state: {workflow_state}"]
        if save_mode == "rollback":
            verification_path = (
                workspace.operation_root / "rollback/verification.json"
            )
            if verification_path.is_file() and not verification_path.is_symlink():
                verification = _load_json(verification_path)
                status = verification.get("status", {})
                state_details.append(
                    "verification result: "
                    f"{status.get('result', 'UNKNOWN')}"
                )
                if status.get("health_gate", {}).get(
                    "state_warn_eligible"
                ):
                    state_details.append(
                        "next action: overlay-change "
                        "accept-rollback-state-warn"
                    )
                state_details.append(
                    "health result: "
                    f"{status.get('health_result', 'UNKNOWN')}"
                )
        raise OperationStateError(
            f"approved {save_mode} save requires {required_state} "
            f"workflow state ({'; '.join(state_details)})"
        )
    if plan.get("capability_level") != "APPLY_VERIFIED":
        raise QualificationError("approved plan is not APPLY_VERIFIED")

    apply_path = workspace.operation_root / "apply/execution.json"
    apply_execution = _load_json(apply_path)
    validate_document(apply_execution, kind="OverlayConfigExecution")
    state_warn_acceptance: tuple[str, str, str] | None = None
    if save_mode == "apply":
        if apply_execution["status"]["result"] != "APPLIED_PENDING_HEALTH":
            raise QualificationError(
                "apply execution is not pending a verified save"
            )
        common_health = _load_json(
            workspace.operation_root / "health/report/health-result.json"
        )
        overlay_health = _load_json(
            workspace.operation_root / "overlay/health-result.json"
        )
        validate_document(common_health, kind="HealthResult")
        validate_document(overlay_health, kind="OverlayHealthResult")
        if common_health["result"] not in {"PASS", "WARN"} or overlay_health[
            "result"
        ] not in {
            "VERIFIED",
            "OBSERVED_HEALTHY",
        }:
            raise QualificationError(
                "approved save requires PASS or WARN common health and "
                "verified Overlay"
            )
        execution_path = apply_path
        config_execution = apply_execution
        expected_phase = "after"
        output_root = workspace.operation_root / "apply"
    else:
        verification = _load_json(
            workspace.operation_root / "rollback/verification.json"
        )
        validate_document(
            verification,
            kind="ManagedRollbackVerification",
        )
        if (
            verification["status"]["result"]
            != "ROLLED_BACK_AND_VERIFIED"
            or verification["status"].get("health_result") == "WARN"
        ):
            state_warn_acceptance = validate_rollback_state_warn_acceptance(
                workspace,
                verification,
            )
        execution_path = (
            workspace.operation_root / "rollback/execution.json"
        )
        config_execution = _load_json(execution_path)
        validate_document(
            config_execution,
            kind="OverlayConfigExecution",
        )
        if config_execution["status"]["result"] not in {
            "ROLLED_BACK_PENDING_HEALTH",
            "ROLLED_BACK_AND_VERIFIED",
        }:
            raise QualificationError(
                "rollback execution is not verified for save"
            )
        expected_phase = "rollback"
        output_root = workspace.operation_root / "rollback"

    devices = [
        host
        for host, item in plan["devices"].items()
        if item["status"] == "PLANNED"
    ]
    if set(devices) - set(inventory_hosts):
        raise QualificationError("save target is absent from pinned inventory")
    for host in devices:
        if inventory_hosts[host].get("device_type") != "nxos":
            raise QualificationError(f"{host}: device_type must be nxos")
        if not _running_config_diff_is_clean(
            apply_execution["status"]["devices"][host].get(
                "pre_apply_diff"
            )
            or ""
        ):
            raise QualificationError(
                f"{host}: pre-apply running/startup diff was not clean"
            )

    snapshot = _load_json(Path(after_snapshot_path))
    if (
        state_warn_acceptance is not None
        and source_sha256(Path(after_snapshot_path))
        != state_warn_acceptance[2]
    ):
        raise RollbackStateWarnAcceptanceError(
            "rollback Snapshot changed after state WARN acceptance"
        )
    if snapshot.get("phase") != expected_phase:
        raise QualificationError(
            f"approved {save_mode} save requires a "
            f"{expected_phase} Snapshot"
        )
    expected_configs = _expected_running_configs(snapshot, devices)
    device_results: dict[str, dict[str, Any]] = {
        host: {
            "status": "NOT_STARTED",
            "running_config_equal": None,
            "pre_save_diff": None,
            "save": None,
            "post_save_diff": None,
        }
        for host in devices
    }
    first_failure: dict[str, str] | None = None

    def inspect_after(
        host: str,
        connection: Any,
    ) -> str:
        running = str(
            connection.send_command(
                "show running-config",
                read_timeout=120,
                strip_prompt=True,
                strip_command=True,
            )
        )
        if _normalized_running_config(running) != expected_configs[host]:
            raise QualificationError(
                "running-config drift from verified after Snapshot"
            )
        diff = str(
            connection.send_command(
                "show running-config diff",
                read_timeout=120,
                strip_prompt=True,
                strip_command=True,
            )
        )
        return diff

    transition_workflow(
        workspace,
        "save_running",
        lock=lock,
        reason="approved_overlay_save_preflight_started",
        now=started_at,
    )

    # Inspect every target before saving the first device.
    for host in devices:
        connection = None
        try:
            connection = connect(host)
            diff = inspect_after(host, connection)
            device_results[host]["running_config_equal"] = True
            device_results[host]["pre_save_diff"] = diff
        except Exception as exc:
            device_results[host]["status"] = (
                "FAILED"
                if isinstance(exc, QualificationError)
                else "UNKNOWN"
            )
            first_failure = {
                "host": host,
                "stage": (
                    "connect"
                    if connection is None
                    else "pre_save_diff"
                ),
                "message": f"{type(exc).__name__}: {exc}",
            }
            break
        finally:
            if connection is not None:
                try:
                    disconnect(connection)
                except Exception:
                    pass

    if first_failure is None:
        for host in devices:
            connection = None
            try:
                connection = connect(host)
                diff = inspect_after(host, connection)
                device_results[host]["running_config_equal"] = True
                device_results[host]["pre_save_diff"] = diff
                if interrupt_guard is not None:
                    interrupt_guard.mark_device_commands_started()
                save = execute_save_session(
                    connection,
                    command=save_command,
                    success_marker=success_marker,
                    now=now,
                )
                device_results[host]["save"] = save
                if save["status"] != "SUCCESS":
                    device_results[host]["status"] = save["status"]
                    first_failure = {
                        "host": host,
                        "stage": "save",
                        "message": save["error"] or "save command failed",
                    }
                    break
                post_diff = str(
                    connection.send_command(
                        "show running-config diff",
                        read_timeout=120,
                        strip_prompt=True,
                        strip_command=True,
                    )
                )
                device_results[host]["post_save_diff"] = post_diff
                if not _running_config_diff_is_clean(post_diff):
                    device_results[host]["status"] = "FAILED"
                    first_failure = {
                        "host": host,
                        "stage": "post_save_diff",
                        "message": (
                            "running-config differs from startup-config "
                            "after save"
                        ),
                    }
                    break
                device_results[host]["status"] = "SUCCESS"
            except Exception as exc:
                device_results[host]["status"] = "UNKNOWN"
                first_failure = {
                    "host": host,
                    "stage": (
                        "connect"
                        if connection is None
                        else "running_config"
                    ),
                    "message": f"{type(exc).__name__}: {exc}",
                }
                break
            finally:
                if connection is not None:
                    try:
                        disconnect(connection)
                    except Exception:
                        pass

    completed_at = now()
    succeeded = first_failure is None
    document = {
        "api_version": API_VERSION,
        "kind": "OverlaySaveExecution",
        "metadata": {
            "change_id": workspace.change_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "timezone": workspace.timezone,
        },
        "spec": {
            "approval_id": approval["approval_id"],
            "execution_plan_sha256": hashes["execution_plan"],
            "rollback_plan_sha256": hashes["rollback_plan"],
            "mode": (
                "after_verified_apply"
                if save_mode == "apply"
                else "after_verified_rollback"
            ),
            "serial": 1,
            "stop_on_first_error": True,
            "automatic_retry": False,
            "precheck_commands": [
                "show running-config",
                "show running-config diff",
            ],
            "save_command": save_command,
            "success_marker": success_marker,
            "state_warn_acceptance_path": (
                state_warn_acceptance[0]
                if save_mode == "rollback" and state_warn_acceptance
                else None
            ),
            "state_warn_acceptance_sha256": (
                state_warn_acceptance[1]
                if save_mode == "rollback" and state_warn_acceptance
                else None
            ),
        },
        "status": {
            "result": (
                (
                    "APPLIED_AND_VERIFIED"
                    if save_mode == "apply"
                    else "ROLLED_BACK_AND_SAVED"
                )
                if succeeded
                else "SAVE_FAILED"
            ),
            "devices": device_results,
            "first_failure": first_failure,
        },
    }
    atomic_write_json(
        workspace.operation_root,
        output_root / "save-execution.json",
        document,
        kind="OverlaySaveExecution",
    )
    for host, result in device_results.items():
        device_root = output_root / "devices" / host
        atomic_write_bytes(
            workspace.operation_root,
            device_root / "save-result.json",
            (
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode(),
        )
        lines = [
            f"host: {host}",
            f"status: {result['status']}",
            "pre_save_diff:",
            result["pre_save_diff"] or "",
            "save_response:",
            (result["save"] or {}).get("response", ""),
            "post_save_diff:",
            result["post_save_diff"] or "",
        ]
        atomic_write_bytes(
            workspace.operation_root,
            device_root / "save.log",
            ("\n".join(lines).rstrip() + "\n").encode(),
        )

    for host, result in device_results.items():
        config_execution["status"]["devices"][host]["save"] = result["save"]
    config_execution["status"]["result"] = (
        (
            "APPLIED_AND_VERIFIED"
            if save_mode == "apply"
            else "ROLLED_BACK_AND_VERIFIED"
        )
        if succeeded
        else "SAVE_FAILED"
    )
    config_execution["status"]["first_failure"] = (
        {
            "host": first_failure["host"],
            "stage": "save",
            "message": first_failure["message"],
        }
        if first_failure is not None
        else None
    )
    validate_document(config_execution, kind="OverlayConfigExecution")
    atomic_write_json(
        workspace.operation_root,
        execution_path,
        config_execution,
        kind="OverlayConfigExecution",
    )
    transition_workflow(
        workspace,
        "completed" if succeeded else "save_failed",
        lock=lock,
        reason=(
            "approved_overlay_save_verified"
            if succeeded
            else "approved_overlay_save_failed"
        ),
        now=completed_at,
    )
    if succeeded:
        lifecycle = load_operation_metadata(workspace.operation_root)["spec"][
            "lifecycle"
        ]
        if lifecycle == "running":
            transition_operation(
                workspace,
                "completed",
                lock=lock,
                reason="approved_overlay_save_completed",
                now=completed_at,
            )
    return document


def execute_approved_rollback_save(
    workspace: OperationWorkspace,
    approval: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Restore startup-config after a fully verified approved rollback."""
    return execute_approved_save(
        workspace,
        approval,
        save_mode="rollback",
        **kwargs,
    )


def execute_approved_rollback(
    workspace: OperationWorkspace,
    approval: Mapping[str, Any],
    *,
    plan_path: str | Path,
    rollback_plan_path: str | Path,
    current_snapshot_path: str | Path,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
) -> dict[str, Any]:
    """Execute the approved inverse config after a pinned after Snapshot."""
    lock.assert_held()
    started_at = now()
    plan = _load_json(Path(plan_path).resolve())
    rollback = _load_json(Path(rollback_plan_path).resolve())
    hashes = calculate_approval_artifact_hashes(workspace, plan, rollback)
    validate_document(approval, kind="ApprovalRecord", allow_unknown_fields=True)
    if approval["change_id"] != workspace.change_id or dict(
        approval["artifacts"]
    ) != hashes:
        raise QualificationError("rollback approval artifact mismatch")
    state = load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ]
    if state not in {"after_completed", "completed", "rollback_required"}:
        raise OperationStateError(
            "approved rollback requires after_completed, completed, "
            "or rollback_required"
        )
    snapshot = _load_json(Path(current_snapshot_path))
    if snapshot.get("phase") != "after":
        raise QualificationError("rollback requires an after Snapshot")
    devices = list(
        reversed(
            [
                host
                for host, item in rollback["devices"].items()
                if item["status"] == "PLANNED"
            ]
        )
    )
    expected = _expected_running_configs(snapshot, devices)
    commands = {}
    configs = {}
    for host in devices:
        path = workspace.operation_root / rollback["devices"][host][
            "rollback_config"
        ]
        digest = source_sha256(path)
        if digest != rollback["devices"][host]["rollback_sha256"]:
            raise QualificationError(f"{host}: rollback config hash mismatch")
        commands[host] = load_managed_config_commands(path)
        residual = _rollback_residual_references(
            expected[host], commands[host]
        )
        if residual:
            raise QualificationError(
                f"{host}: rollback residual references detected: "
                + "; ".join(residual[:5])
            )
        configs[host] = {"path": str(path), "sha256": digest}

    def precheck(host: str, connection: Any) -> tuple[bool, str, str]:
        try:
            current = str(
                connection.send_command(
                    "show running-config",
                    read_timeout=120,
                    strip_prompt=True,
                    strip_command=True,
                )
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}", "UNKNOWN"
        if _normalized_running_config(current) != expected[host]:
            return False, "running-config drift from after Snapshot", "FAILED"
        return True, "running-config matches after Snapshot", "FAILED"

    if state in {"after_completed", "completed"}:
        transition_workflow(
            workspace,
            "rollback_required",
            lock=lock,
            reason="approved_manual_rollback_requested",
            now=started_at,
        )
    started = False

    def before_commands(_host: str) -> None:
        nonlocal started
        if not started:
            transition_workflow(
                workspace,
                "rollback_running",
                lock=lock,
                reason="approved_overlay_rollback_started",
                now=now(),
            )
            started = True
        if interrupt_guard:
            interrupt_guard.mark_device_commands_started()

    serial = execute_serial_devices(
        devices,
        commands,
        connect=connect,
        disconnect=disconnect,
        precheck=precheck,
        before_commands=before_commands,
        now=now,
    )
    completed_at = now()
    if not started:
        transition_workflow(
            workspace,
            "rollback_running",
            lock=lock,
            reason="approved_rollback_precheck_failed",
            now=completed_at,
        )
    execution = build_execution_document(
        change_id=workspace.change_id,
        mode="rollback",
        started_at=started_at,
        completed_at=completed_at,
        timezone_name=workspace.timezone,
        execution_plan_sha256=hashes["execution_plan"],
        rollback_plan_sha256=hashes["rollback_plan"],
        approval_id=approval["approval_id"],
        serial_result=serial,
        config_artifacts=configs,
    )
    _write_evidence(workspace, serial, mode="rollback")
    atomic_write_json(
        workspace.operation_root,
        workspace.operation_root / "rollback" / "execution.json",
        execution,
        kind="OverlayConfigExecution",
    )
    transition_workflow(
        workspace,
        "rolled_back" if serial["status"] == "SUCCESS" else "rollback_failed",
        lock=lock,
        reason="approved_overlay_rollback_finished",
        now=completed_at,
    )
    return execution


def verify_approved_rollback(
    workspace: OperationWorkspace,
    *,
    rollback_snapshot_path: str | Path,
    plan_path: str | Path,
    report_dir: str | Path | None = None,
    verification_dir: str | Path | None = None,
    update_workflow: bool = True,
    lock: OperationLock,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """Verify common health plus raw and semantic restoration."""
    lock.assert_held()
    verified_at = now()
    workflow_state = load_operation_metadata(workspace.operation_root)["spec"][
        "workflow_state"
    ]
    if workflow_state not in {"rolled_back", "rollback_health_failed"}:
        raise OperationStateError(
            "rollback verification requires rolled_back or "
            "rollback_health_failed"
        )
    plan = _load_json(Path(plan_path))
    before_path = Path(plan["artifacts"]["before_snapshot"])
    before = _load_json(before_path)
    rollback_path = Path(rollback_snapshot_path)
    rollback = _load_json(rollback_path)
    if rollback.get("phase") != "rollback":
        raise QualificationError("verification Snapshot must be rollback")
    rollback_execution = _load_json(
        workspace.operation_root / "rollback/execution.json"
    )
    snapshot_fresh = rollback_snapshot_is_fresh(
        rollback,
        rollback_execution,
    )
    profiles = load_resolved_profiles(
        workspace.operation_root / "health/resolved-profiles.yaml"
    )
    roles_path = workspace.operation_root / "health/resolved-roles.yaml"
    resolved_roles = load_resolved_roles(roles_path) if roles_path.is_file() else None
    health = compare_snapshots(
        before,
        rollback,
        profiles,
        started_at=verified_at,
        completed_at=verified_at,
        resolved_roles=resolved_roles,
    )
    health["phase"] = "rollback"
    report = Path(report_dir) if report_dir else (
        workspace.operation_root / "health/rollback-report"
    )
    verification_root = Path(verification_dir) if verification_dir else (
        workspace.operation_root / "rollback"
    )
    verification_path = verification_root / "verification.json"
    checklist_path = verification_root / "verification-checklist.md"
    health["artifacts"] = {
        "before_snapshot": str(before_path),
        "after_snapshot": str(rollback_path),
        "summary": str(report / "summary.md"),
    }
    atomic_write_json(
        workspace.operation_root,
        report / "health-result.json",
        health,
        kind="HealthResult",
    )
    atomic_write_bytes(
        workspace.operation_root,
        report / "summary.md",
        render_health_summary(health).encode(),
    )
    targets = [
        host
        for host, item in plan["devices"].items()
        if item["status"] == "PLANNED"
    ]
    before_configs = _expected_running_configs(before, targets)
    rollback_configs = _expected_running_configs(rollback, targets)
    devices = {}
    for host in targets:
        before_semantic = (
            before["hosts"][host]
            .get("profiles", {})
            .get("nxos-overlay", {})
            .get("config")
        )
        rollback_semantic = (
            rollback["hosts"][host]
            .get("profiles", {})
            .get("nxos-overlay", {})
            .get("config")
        )
        devices[host] = build_device_verification(
            before_configs[host],
            rollback_configs[host],
            before_semantic,
            rollback_semantic,
        )
    raw_equal = all(item["raw_config_equal"] for item in devices.values())
    semantic_equal = all(
        item["semantic_config_equal"] for item in devices.values()
    )
    health_gate = evaluate_rollback_health_gate(health)
    verified = rollback_verification_passes(
        snapshot_fresh=snapshot_fresh,
        health_result=health["result"],
        raw_config_equal=raw_equal,
        semantic_config_equal=semantic_equal,
    )
    document = {
        "api_version": API_VERSION,
        "kind": "ManagedRollbackVerification",
        "metadata": {
            "change_id": workspace.change_id,
            "verified_at": verified_at.isoformat(timespec="seconds"),
            "timezone": workspace.timezone,
        },
        "status": {
            "result": (
                "ROLLED_BACK_AND_VERIFIED"
                if verified
                else "ROLLBACK_HEALTH_FAILED"
            ),
            "health_result": health["result"],
            "health_gate": health_gate,
            "snapshot_fresh": snapshot_fresh,
            "raw_config_equal": raw_equal,
            "semantic_config_equal": semantic_equal,
        },
        "devices": devices,
        "artifacts": {
            "before_snapshot": str(before_path),
            "rollback_snapshot": str(rollback_path),
            "health_result": str(report / "health-result.json"),
            "verification_json": str(
                verification_path
            ),
            "verification_checklist": str(checklist_path),
        },
    }
    atomic_write_json(
        workspace.operation_root,
        verification_path,
        document,
        kind="ManagedRollbackVerification",
    )
    atomic_write_bytes(
        workspace.operation_root,
        checklist_path,
        render_rollback_verification_checklist(document, health).encode(
            "utf-8"
        ),
    )
    if update_workflow:
        transition_workflow(
            workspace,
            (
                "rolled_back_and_verified"
                if verified
                else "rollback_health_failed"
            ),
            lock=lock,
            reason=(
                "approved_rollback_verified"
                if verified
                else "approved_rollback_verification_failed"
            ),
            now=verified_at,
        )
    return document
