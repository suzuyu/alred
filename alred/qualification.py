"""Nexus 9000v initial lab qualification approval primitives."""

from __future__ import annotations

from datetime import datetime, timedelta
import getpass
import json
from pathlib import Path
import re
import secrets
import socket
from typing import Any, Callable, Mapping

import yaml

from .operation import (
    OperationInterruptGuard,
    OperationLock,
    OperationPathError,
    OperationStateError,
    OperationWorkspace,
    atomic_write_bytes,
    atomic_write_json,
    format_utc_offset,
    load_operation_metadata,
    now_in_timezone,
    transition_workflow,
)
from .managed_config import (
    build_execution_document,
    execute_save_session,
    execute_serial_devices,
    load_managed_config_commands,
)
from .health.evaluator import compare_snapshots
from .health.profile import load_resolved_profiles
from .health.report import render_health_summary
from .health.roles import load_resolved_roles
from .overlay_render import normalize_nxos_model
from .schema import (
    API_VERSION,
    canonical_sha256,
    source_sha256,
    validate_document,
)
from .rollback_verification import (
    build_device_verification,
    evaluate_rollback_health_gate,
    render_rollback_verification_checklist,
    rollback_snapshot_is_fresh,
    rollback_verification_passes,
)


MAX_QUALIFICATION_HOURS = 4
QUALIFICATION_MODEL = "N9K-C9300V"


class QualificationError(RuntimeError):
    """Raised when initial lab qualification cannot proceed safely."""

    code = "QUALIFICATION_INVALID"


class QualificationRequiredError(QualificationError):
    """Raised when the exact interactive phrase was not entered."""

    code = "APPROVAL_REQUIRED"


def _regular_file(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise OperationPathError(f"regular file is required: {candidate}")
    return candidate.resolve()


def _below_operation(workspace: OperationWorkspace, path: str | Path) -> Path:
    candidate = _regular_file(path)
    try:
        candidate.relative_to(workspace.operation_root.resolve())
    except ValueError as exc:
        raise OperationPathError(
            f"qualification artifact is outside operation root: {path}"
        ) from exc
    return candidate


def _load_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    raise QualificationError(f"JSON or YAML artifact is required: {path}")


def _running_config_diff_is_clean(output: str) -> bool:
    """Return whether NX-OS reports no running/startup configuration diff."""
    normalized = "\n".join(
        line.strip()
        for line in str(output).replace("\r", "").splitlines()
        if line.strip()
    )
    if not normalized:
        return True
    return normalized.lower() in {
        "no changes",
        "no differences",
        "running configuration is same as startup configuration",
        "running-config is same as startup-config",
    }


def _document_artifact(path: Path) -> tuple[dict[str, str], Any]:
    document = _load_document(path)
    if not isinstance(document, (dict, list)):
        raise QualificationError(
            f"artifact must contain an object or array: {path}"
        )
    return {
        "path": str(path),
        "sha256": canonical_sha256(document),
        "hash_mode": "canonical_json",
    }, document


def _source_artifact(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": source_sha256(path),
        "hash_mode": "source_bytes",
    }


def _plan_devices(plan: Mapping[str, Any]) -> list[str]:
    raw = plan.get("devices")
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, Mapping):
        return [
            host
            for host, value in raw.items()
            if value.get("status") == "PLANNED"
        ]
    raise QualificationError("execution plan devices are invalid")


def build_qualification_summary(
    workspace: OperationWorkspace,
    *,
    plan_path: str | Path,
    rollback_plan_path: str | Path,
    before_snapshot_path: str | Path,
    before_health_result_path: str | Path,
    change_set_path: str | Path,
    render_manifest_path: str | Path,
    inventory_path: str | Path,
) -> dict[str, Any]:
    """Validate a PLAN_ONLY 9000v candidate and pin every input hash."""
    internal = {
        "execution_plan": _below_operation(workspace, plan_path),
        "rollback_plan": _below_operation(workspace, rollback_plan_path),
        "before_snapshot": _below_operation(workspace, before_snapshot_path),
        "before_health_result": _below_operation(
            workspace,
            before_health_result_path,
        ),
        "change_set": _below_operation(workspace, change_set_path),
        "render_manifest": _below_operation(workspace, render_manifest_path),
    }
    artifacts: dict[str, dict[str, str]] = {}
    documents: dict[str, Any] = {}
    for name, path in internal.items():
        artifacts[name], documents[name] = _document_artifact(path)
    inventory = _regular_file(inventory_path)
    artifacts["inventory"] = _source_artifact(inventory)

    plan = documents["execution_plan"]
    rollback = documents["rollback_plan"]
    snapshot = documents["before_snapshot"]
    health = documents["before_health_result"]
    change_set = documents["change_set"]
    render_manifest = documents["render_manifest"]
    for name, document, kind in (
        ("execution plan", plan, "ExecutionPlan"),
        ("rollback plan", rollback, "RollbackPlan"),
        ("before Snapshot", snapshot, "HealthSnapshot"),
        ("before HealthResult", health, "HealthResult"),
        ("ChangeSet", change_set, "OverlayChangeSet"),
        ("render manifest", render_manifest, "OverlayRenderManifest"),
    ):
        if not isinstance(document, dict):
            raise QualificationError(f"{name} must be an object")
        validate_document(document, kind=kind)
        if document.get("change_id") not in (None, workspace.change_id):
            raise QualificationError(f"{name} change_id mismatch")
        metadata_change_id = document.get("metadata", {}).get("change_id")
        if metadata_change_id not in (None, workspace.change_id):
            raise QualificationError(f"{name} change_id mismatch")

    if plan["capability_level"] != "PLAN_ONLY":
        raise QualificationError(
            "qualification requires a PLAN_ONLY execution plan"
        )
    if health["result"] != "PASS":
        raise QualificationError(
            "qualification requires before HealthResult PASS"
        )
    devices = _plan_devices(plan)
    if not 1 <= len(devices) <= 2:
        raise QualificationError(
            "qualification requires one or two PLANNED devices"
        )
    rollback_devices = rollback.get("devices", {})
    if set(devices) != set(rollback_devices):
        raise QualificationError(
            "execution and rollback plan device sets differ"
        )
    if change_set["metadata"]["source"] != "declared":
        raise QualificationError(
            "qualification requires metadata.source=declared"
        )

    plan_artifacts = plan.get("artifacts", {}).get(
        "approval_artifacts",
        {},
    )
    if not isinstance(plan_artifacts, Mapping):
        raise QualificationError(
            "execution plan approval_artifacts must be an object"
        )
    artifact_kinds = {
        "device_groups": "OverlayDeviceGroups",
        "input_manifest": "OverlayInputManifest",
        "resolved_targets": "OverlayResolvedTargets",
    }
    for name, raw_path in sorted(plan_artifacts.items()):
        if name in artifacts:
            continue
        if name not in artifact_kinds or not isinstance(raw_path, str):
            raise QualificationError(
                f"unsupported qualification input artifact: {name}"
            )
        path = _below_operation(workspace, raw_path)
        artifact, document = _document_artifact(path)
        if not isinstance(document, dict):
            raise QualificationError(f"{name} must be an object")
        validate_document(document, kind=artifact_kinds[name])
        artifacts[name] = artifact

    target_release: str | None = None
    for host in devices:
        host_snapshot = snapshot.get("hosts", {}).get(host)
        if not isinstance(host_snapshot, Mapping):
            raise QualificationError(
                f"target device is absent from before Snapshot: {host}"
            )
        system = host_snapshot.get("common", {}).get("system", {})
        if system.get("platform") != "nxos":
            raise QualificationError(f"{host}: NX-OS evidence is required")
        model = normalize_nxos_model(system.get("model"))
        if model != QUALIFICATION_MODEL:
            raise QualificationError(
                f"{host}: qualification supports only {QUALIFICATION_MODEL}"
            )
        release = str(system.get("version", ""))
        if target_release is None:
            target_release = release
        elif target_release != release:
            raise QualificationError(
                "qualification target releases must be identical"
            )
        vpc = host_snapshot.get("common", {}).get("vpc", {})
        overlay_config = (
            host_snapshot.get("profiles", {})
            .get("nxos-overlay", {})
            .get("config", {})
        )
        if (
            not vpc.get("applicable")
            or not overlay_config.get("nve", {}).get("configured")
        ):
            raise QualificationError(
                f"{host}: qualification requires a vPC VTEP leaf"
            )

        plan_device = plan["devices"][host]
        rollback_device = rollback_devices[host]
        forward = _below_operation(
            workspace,
            workspace.operation_root / plan_device["forward_config"],
        )
        reverse = _below_operation(
            workspace,
            workspace.operation_root / rollback_device["rollback_config"],
        )
        forward_artifact = _source_artifact(forward)
        rollback_artifact = _source_artifact(reverse)
        if forward_artifact["sha256"] != plan_device["forward_sha256"]:
            raise QualificationError(f"{host}: forward config hash mismatch")
        if rollback_artifact["sha256"] != rollback_device["rollback_sha256"]:
            raise QualificationError(f"{host}: rollback config hash mismatch")
        artifacts[f"forward_config_{host}"] = forward_artifact
        artifacts[f"rollback_config_{host}"] = rollback_artifact

    assert target_release is not None
    return {
        "change_id": workspace.change_id,
        "target": {
            "platform": "nxos",
            "model": QUALIFICATION_MODEL,
            "release": target_release,
            "role": "vtep_leaf",
            "devices": devices,
        },
        "artifacts": artifacts,
        "constraints": {
            "max_devices": 2,
            "serial": 1,
            "stop_on_first_error": True,
            "automatic_retry": False,
            "automatic_rollback": False,
            "save_on_initial_apply": False,
            "rollback_policy": "manual",
        },
    }


def qualification_confirmation_phrase(summary: Mapping[str, Any]) -> str:
    target = summary["target"]
    return (
        f"QUALIFY {summary['change_id']} "
        f"{target['model']} {target['release']}"
    )


def create_qualification_record(
    workspace: OperationWorkspace,
    summary: Mapping[str, Any],
    *,
    lock: OperationLock,
    confirm: Callable[[str], str],
    approval_hours: int = MAX_QUALIFICATION_HOURS,
    now: datetime | None = None,
    random_hex: str | None = None,
) -> Path:
    """Persist a distinct, immutable initial-lab approval record."""
    lock.assert_held()
    if not 1 <= approval_hours <= MAX_QUALIFICATION_HOURS:
        raise QualificationError(
            "qualification validity must be between 1 and 4 hours"
        )
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"]["workflow_state"] != "plan_ready":
        raise OperationStateError(
            "workflow must be plan_ready before qualification approval"
        )
    if summary.get("change_id") != workspace.change_id:
        raise QualificationError("qualification change_id mismatch")
    phrase = qualification_confirmation_phrase(summary)
    if confirm(phrase) != phrase:
        raise QualificationRequiredError(
            "exact qualification confirmation phrase was not provided"
        )

    approved_at = now_in_timezone(workspace.timezone, now=now)
    expires_at = approved_at + timedelta(hours=approval_hours)
    _offset, offset_token = format_utc_offset(approved_at)
    token = random_hex or secrets.token_hex(3)
    if len(token) != 6 or any(char not in "0123456789abcdef" for char in token):
        raise QualificationError(
            "qualification random token must be six lowercase hexadecimal characters"
        )
    qualification_id = (
        f"QLF-{approved_at.strftime('%Y%m%dT%H%M%S')}-"
        f"{offset_token}-{token}"
    )
    document = {
        "api_version": API_VERSION,
        "kind": "QualificationRecord",
        "metadata": {
            "qualification_id": qualification_id,
            "change_id": workspace.change_id,
            "purpose": "initial_lab_qualification",
            "approved_at": approved_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "approval_method": "interactive",
            "approver": {
                "os_user": getpass.getuser(),
                "hostname": socket.gethostname(),
            },
            "confirmation_phrase": phrase,
        },
        "target": dict(summary["target"]),
        "artifacts": dict(summary["artifacts"]),
        "constraints": dict(summary["constraints"]),
    }
    validate_document(document, kind="QualificationRecord")
    output_path = (
        workspace.operation_root
        / "qualification"
        / "qualification-record.json"
    )
    if output_path.exists():
        raise QualificationError(
            f"qualification record already exists: {output_path}"
        )
    atomic_write_json(
        workspace.operation_root,
        output_path,
        document,
        kind="QualificationRecord",
    )
    transition_workflow(
        workspace,
        "approved",
        lock=lock,
        reason="initial_lab_qualification_approved",
        now=approved_at,
    )
    return output_path


def load_qualification_record(path: str | Path) -> dict[str, Any]:
    candidate = _regular_file(path)
    document = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise QualificationError("qualification record must be an object")
    validate_document(document, kind="QualificationRecord")
    return document


def validate_qualification_record(
    record: Mapping[str, Any],
    *,
    expected_change_id: str,
    now: datetime,
    allow_expired: bool = False,
) -> None:
    """Rehash all pinned files and validate expiry before device access."""
    validate_document(record, kind="QualificationRecord")
    metadata = record["metadata"]
    if metadata["change_id"] != expected_change_id:
        raise QualificationError("qualification change_id mismatch")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if (
        not allow_expired
        and now >= datetime.fromisoformat(metadata["expires_at"])
    ):
        raise QualificationError("qualification record has expired")
    for name, artifact in record["artifacts"].items():
        path = _regular_file(artifact["path"])
        if artifact["hash_mode"] == "source_bytes":
            digest = source_sha256(path)
        else:
            document = _load_document(path)
            digest = canonical_sha256(document)
        if digest != artifact["sha256"]:
            raise QualificationError(
                f"qualification artifact hash mismatch: {name}"
            )


def _normalized_running_config(text: str) -> list[str]:
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("!")
    ]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _expected_running_configs(
    snapshot: Mapping[str, Any],
    devices: list[str],
) -> dict[str, list[str]]:
    expected: dict[str, list[str]] = {}
    for host in devices:
        source = snapshot["hosts"][host]["sources"].get("running_config")
        if not source or source.get("parse_status") != "parsed":
            raise QualificationError(
                f"{host}: parsed before running-config evidence is required"
            )
        path = _regular_file(source["file"])
        digest = source_sha256(path).removeprefix("sha256:")
        if digest != source["sha256"]:
            raise QualificationError(
                f"{host}: before running-config source hash mismatch"
            )
        expected[host] = _normalized_running_config(
            path.read_text(encoding="utf-8", errors="replace")
        )
    return expected


def _rollback_residual_references(
    current_lines: list[str],
    rollback_commands: list[str],
) -> list[str]:
    """Find references that make deleting a new VRF/VLAN unsafe."""
    deleted_vrfs = {
        match.group(1)
        for command in rollback_commands
        if (
            match := re.fullmatch(
                r"no vrf context (\S+)",
                command,
                flags=re.IGNORECASE,
            )
        )
    }
    deleted_vlans = {
        match.group(1)
        for command in rollback_commands
        if (
            match := re.fullmatch(
                r"no vlan (\d+)",
                command,
                flags=re.IGNORECASE,
            )
        )
    }
    findings: list[str] = []
    for line in current_lines:
        command = line.strip()
        lowered = command.lower()
        for vrf in deleted_vrfs:
            if not re.search(
                rf"(?<![\w.-]){re.escape(vrf)}(?![\w.-])",
                command,
                flags=re.IGNORECASE,
            ):
                continue
            allowed = {
                f"vrf context {vrf}".lower(),
                f"vrf {vrf}".lower(),
                f"vrf member {vrf}".lower(),
            }
            if lowered not in allowed:
                findings.append(f"VRF {vrf}: {command}")
        for vlan in deleted_vlans:
            if not (
                re.search(
                    (
                        rf"(?i)(?<!\w)vlan(?:\s+(?:add|remove|except))?"
                        rf"\s+\S*(?<!\d){re.escape(vlan)}(?!\d)"
                    ),
                    command,
                )
                or re.search(
                    rf"(?i)(?<!\w)Vlan{re.escape(vlan)}(?!\d)",
                    command,
                )
            ):
                continue
            allowed = {
                f"vlan {vlan}".lower(),
                f"interface vlan{vlan}".lower(),
            }
            if lowered not in allowed and not lowered.startswith("vlan "):
                findings.append(f"VLAN {vlan}: {command}")
    return findings


def _write_device_evidence(
    workspace: OperationWorkspace,
    serial_result: Mapping[str, Any],
    *,
    mode: str,
) -> None:
    for host, result in serial_result["devices"].items():
        device_dir = (
            workspace.operation_root
            / "qualification"
            / mode
            / "devices"
            / host
        )
        result_path = device_dir / "command-results.json"
        result_bytes = (
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        atomic_write_bytes(
            workspace.operation_root,
            result_path,
            result_bytes,
        )
        log_lines = [f"host: {host}", f"status: {result['status']}", ""]
        for command in result["commands"]:
            log_lines.extend(
                [
                    (
                        f"[{command['index']}] {command['status']} "
                        f"{command['command']}"
                    ),
                    f"started_at: {command['started_at']}",
                    f"completed_at: {command['completed_at']}",
                    f"error: {command['error'] or '-'}",
                    "response:",
                    command["response"],
                    "",
                ]
            )
        atomic_write_bytes(
            workspace.operation_root,
            device_dir / "commands.log",
            ("\n".join(log_lines).rstrip() + "\n").encode("utf-8"),
        )


def execute_qualification_apply(
    workspace: OperationWorkspace,
    record: Mapping[str, Any],
    *,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
) -> dict[str, Any]:
    """Execute an approved 9000v candidate without save or automatic retry."""
    lock.assert_held()
    started_at = now()
    validate_qualification_record(
        record,
        expected_change_id=workspace.change_id,
        now=started_at,
    )
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"]["workflow_state"] != "approved":
        raise OperationStateError(
            "workflow must be approved before qualification apply"
        )
    devices = list(record["target"]["devices"])
    if set(devices) - set(inventory_hosts):
        raise QualificationError(
            "qualification target is absent from pinned inventory"
        )
    for host in devices:
        if inventory_hosts[host].get("device_type") != "nxos":
            raise QualificationError(f"{host}: device_type must be nxos")

    plan_artifact = record["artifacts"]["execution_plan"]
    rollback_artifact = record["artifacts"]["rollback_plan"]
    snapshot_artifact = record["artifacts"]["before_snapshot"]
    plan = _load_document(_regular_file(plan_artifact["path"]))
    snapshot = _load_document(_regular_file(snapshot_artifact["path"]))
    expected_configs = _expected_running_configs(snapshot, devices)
    commands: dict[str, list[str]] = {}
    config_artifacts: dict[str, dict[str, str]] = {}
    for host in devices:
        artifact = record["artifacts"][f"forward_config_{host}"]
        commands[host] = load_managed_config_commands(artifact["path"])
        config_artifacts[host] = {
            "path": artifact["path"],
            "sha256": artifact["sha256"],
        }
        if plan["devices"][host]["status"] != "PLANNED":
            raise QualificationError(f"{host}: plan status must be PLANNED")

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
        return True, "running-config matches approved before", "FAILED"

    commands_started = False

    def before_commands(_host: str) -> None:
        nonlocal commands_started
        if not commands_started:
            transition_workflow(
                workspace,
                "apply_running",
                lock=lock,
                reason="initial_lab_qualification_apply_started",
                now=now(),
            )
            commands_started = True
        if interrupt_guard is not None:
            interrupt_guard.mark_device_commands_started()

    serial_result = execute_serial_devices(
        devices,
        commands,
        connect=connect,
        disconnect=disconnect,
        precheck=precheck,
        before_commands=before_commands,
        now=now,
    )
    completed_at = now()
    if not commands_started:
        transition_workflow(
            workspace,
            "apply_running",
            lock=lock,
            reason="qualification_apply_precheck_failed",
            now=completed_at,
        )
    execution = build_execution_document(
        change_id=workspace.change_id,
        mode="apply",
        started_at=started_at,
        completed_at=completed_at,
        timezone_name=workspace.timezone,
        execution_plan_sha256=plan_artifact["sha256"],
        rollback_plan_sha256=rollback_artifact["sha256"],
        approval_id=record["metadata"]["qualification_id"],
        serial_result=serial_result,
        config_artifacts=config_artifacts,
    )
    _write_device_evidence(workspace, serial_result, mode="apply")
    atomic_write_json(
        workspace.operation_root,
        workspace.operation_root
        / "qualification"
        / "apply"
        / "execution.json",
        execution,
        kind="OverlayConfigExecution",
    )
    if serial_result["status"] == "SUCCESS":
        transition_workflow(
            workspace,
            "apply_completed",
            lock=lock,
            reason="qualification_config_applied_pending_health",
            now=completed_at,
        )
    else:
        failed_state = (
            "device_state_unknown"
            if serial_result["status"] == "UNKNOWN"
            else "apply_failed"
        )
        transition_workflow(
            workspace,
            failed_state,
            lock=lock,
            reason="qualification_config_apply_failed",
            now=completed_at,
        )
        transition_workflow(
            workspace,
            "rollback_required",
            lock=lock,
            reason="manual_rollback_decision_required",
            now=completed_at,
        )
    return execution


def execute_qualification_rollback(
    workspace: OperationWorkspace,
    record: Mapping[str, Any],
    *,
    current_snapshot_path: str | Path,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
) -> dict[str, Any]:
    """Run the pinned qualification rollback without saving.

    The latest collected running configuration is pinned by the caller and is
    compared again in the same device session immediately before rollback.
    An expired qualification approval never prevents a safety rollback, but
    all pinned artifact hashes remain mandatory.
    """
    lock.assert_held()
    started_at = now()
    validate_qualification_record(
        record,
        expected_change_id=workspace.change_id,
        now=started_at,
        allow_expired=True,
    )
    metadata = load_operation_metadata(workspace.operation_root)
    workflow_state = metadata["spec"]["workflow_state"]
    if workflow_state not in {"after_completed", "rollback_required"}:
        raise OperationStateError(
            "qualification rollback requires after_completed or "
            "rollback_required workflow state"
        )

    devices = list(reversed(record["target"]["devices"]))
    if set(devices) - set(inventory_hosts):
        raise QualificationError(
            "qualification rollback target is absent from pinned inventory"
        )
    for host in devices:
        if inventory_hosts[host].get("device_type") != "nxos":
            raise QualificationError(f"{host}: device_type must be nxos")

    snapshot_path = _below_operation(workspace, current_snapshot_path)
    snapshot = _load_document(snapshot_path)
    if snapshot.get("change_id") != workspace.change_id:
        raise QualificationError("current snapshot change_id mismatch")
    if snapshot.get("phase") != "after":
        raise QualificationError(
            "rollback current snapshot phase must be after"
        )
    apply_execution_path = (
        workspace.operation_root / "qualification" / "apply" / "execution.json"
    )
    apply_execution = _load_document(_below_operation(
        workspace,
        apply_execution_path,
    ))
    validate_document(apply_execution, kind="OverlayConfigExecution")
    if (
        apply_execution["metadata"]["change_id"] != workspace.change_id
        or apply_execution["metadata"]["mode"] != "apply"
    ):
        raise QualificationError("qualification apply evidence mismatch")
    snapshot_created_at = snapshot.get("created_at")
    if not snapshot_created_at:
        raise QualificationError(
            "current rollback snapshot must include created_at"
        )
    if datetime.fromisoformat(snapshot_created_at) < datetime.fromisoformat(
        apply_execution["metadata"]["completed_at"]
    ):
        raise QualificationError(
            "current rollback snapshot predates qualification apply"
        )
    expected_configs = _expected_running_configs(snapshot, devices)

    plan_artifact = record["artifacts"]["execution_plan"]
    rollback_artifact = record["artifacts"]["rollback_plan"]
    rollback_plan = _load_document(_regular_file(rollback_artifact["path"]))
    commands: dict[str, list[str]] = {}
    config_artifacts: dict[str, dict[str, str]] = {}
    for host in devices:
        artifact = record["artifacts"][f"rollback_config_{host}"]
        commands[host] = load_managed_config_commands(artifact["path"])
        config_artifacts[host] = {
            "path": artifact["path"],
            "sha256": artifact["sha256"],
        }
        if rollback_plan["devices"][host]["status"] != "PLANNED":
            raise QualificationError(
                f"{host}: rollback plan status must be PLANNED"
            )
        residual = _rollback_residual_references(
            expected_configs[host],
            commands[host],
        )
        if residual:
            raise QualificationError(
                f"{host}: rollback residual references detected: "
                + "; ".join(residual[:5])
            )

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
            return (
                False,
                "running-config drift from current rollback snapshot",
                "FAILED",
            )
        return True, "running-config matches current rollback snapshot", "FAILED"

    if workflow_state == "after_completed":
        transition_workflow(
            workspace,
            "rollback_required",
            lock=lock,
            reason="qualification_test_rollback_requested",
            now=started_at,
        )

    commands_started = False

    def before_commands(_host: str) -> None:
        nonlocal commands_started
        if not commands_started:
            transition_workflow(
                workspace,
                "rollback_running",
                lock=lock,
                reason="qualification_rollback_started",
                now=now(),
            )
            commands_started = True
        if interrupt_guard is not None:
            interrupt_guard.mark_device_commands_started()

    serial_result = execute_serial_devices(
        devices,
        commands,
        connect=connect,
        disconnect=disconnect,
        precheck=precheck,
        before_commands=before_commands,
        now=now,
    )
    completed_at = now()
    execution = build_execution_document(
        change_id=workspace.change_id,
        mode="rollback",
        started_at=started_at,
        completed_at=completed_at,
        timezone_name=workspace.timezone,
        execution_plan_sha256=plan_artifact["sha256"],
        rollback_plan_sha256=rollback_artifact["sha256"],
        approval_id=record["metadata"]["qualification_id"],
        serial_result=serial_result,
        config_artifacts=config_artifacts,
    )
    _write_device_evidence(workspace, serial_result, mode="rollback")
    atomic_write_json(
        workspace.operation_root,
        workspace.operation_root
        / "qualification"
        / "rollback"
        / "execution.json",
        execution,
        kind="OverlayConfigExecution",
    )
    if serial_result["status"] == "SUCCESS":
        transition_workflow(
            workspace,
            "rolled_back",
            lock=lock,
            reason="qualification_rollback_pending_health",
            now=completed_at,
        )
    elif commands_started:
        transition_workflow(
            workspace,
            "rollback_failed",
            lock=lock,
            reason="qualification_rollback_failed",
            now=completed_at,
        )
    return execution


def execute_qualification_baseline_save(
    workspace: OperationWorkspace,
    record: Mapping[str, Any],
    *,
    inventory_hosts: Mapping[str, Mapping[str, Any]],
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    save_command: str,
    success_marker: str | None,
    lock: OperationLock,
    now: Callable[[], datetime],
    interrupt_guard: OperationInterruptGuard | None = None,
) -> dict[str, Any]:
    """Verify the restored baseline and qualify NX-OS config save."""
    lock.assert_held()
    started_at = now()
    validate_qualification_record(
        record,
        expected_change_id=workspace.change_id,
        now=started_at,
    )
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"]["workflow_state"] != "rolled_back_and_verified":
        raise OperationStateError(
            "baseline save qualification requires "
            "rolled_back_and_verified workflow state"
        )
    verification = _load_document(
        _below_operation(
            workspace,
            workspace.operation_root
            / "qualification"
            / "rollback"
            / "verification.json",
        )
    )
    validate_document(
        verification,
        kind="QualificationRollbackVerification",
    )
    if (
        verification["metadata"]["change_id"] != workspace.change_id
        or verification["status"]["result"]
        != "ROLLED_BACK_AND_VERIFIED"
    ):
        raise QualificationError(
            "rollback verification does not permit baseline save"
        )

    devices = list(record["target"]["devices"])
    if set(devices) - set(inventory_hosts):
        raise QualificationError(
            "qualification save target is absent from pinned inventory"
        )
    for host in devices:
        if inventory_hosts[host].get("device_type") != "nxos":
            raise QualificationError(f"{host}: device_type must be nxos")
    before = _load_document(
        _below_operation(
            workspace,
            record["artifacts"]["before_snapshot"]["path"],
        )
    )
    expected_configs = _expected_running_configs(before, devices)
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

    def inspect_baseline(
        host: str,
        connection: Any,
    ) -> tuple[str, str]:
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
                "running-config drift from approved before"
            )
        diff = str(
            connection.send_command(
                "show running-config diff",
                read_timeout=120,
                strip_prompt=True,
                strip_command=True,
            )
        )
        if not _running_config_diff_is_clean(diff):
            raise QualificationError(
                "running-config differs from startup-config"
            )
        return running, diff

    # Read-only all-device preflight prevents saving the first device when a
    # known baseline/diff problem already exists on a later device.
    for host in devices:
        connection = None
        try:
            connection = connect(host)
            _running, diff = inspect_baseline(host, connection)
            device_results[host]["running_config_equal"] = True
            device_results[host]["pre_save_diff"] = diff
        except Exception as exc:
            stage = (
                "connect"
                if connection is None
                else "pre_save_diff"
            )
            device_results[host]["status"] = (
                "UNKNOWN"
                if not isinstance(exc, QualificationError)
                else "FAILED"
            )
            first_failure = {
                "host": host,
                "stage": stage,
                "message": f"{type(exc).__name__}: {exc}",
            }
            break
        finally:
            if connection is not None:
                try:
                    disconnect(connection)
                except Exception:
                    pass

    save_started = False
    if first_failure is None:
        for host in devices:
            connection = None
            try:
                connection = connect(host)
                _running, diff = inspect_baseline(host, connection)
                device_results[host]["running_config_equal"] = True
                device_results[host]["pre_save_diff"] = diff
                if not save_started:
                    transition_workflow(
                        workspace,
                        "qualification_save_running",
                        lock=lock,
                        reason="qualification_baseline_save_started",
                        now=now(),
                    )
                    save_started = True
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
        "kind": "QualificationSaveExecution",
        "metadata": {
            "change_id": workspace.change_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "timezone": workspace.timezone,
        },
        "spec": {
            "qualification_id": record["metadata"]["qualification_id"],
            "mode": "baseline_after_verified_rollback",
            "serial": 1,
            "stop_on_first_error": True,
            "automatic_retry": False,
            "precheck_commands": [
                "show running-config",
                "show running-config diff",
            ],
            "save_command": save_command,
            "success_marker": success_marker,
        },
        "status": {
            "result": (
                "QUALIFICATION_SAVE_SUCCEEDED"
                if succeeded
                else "QUALIFICATION_SAVE_FAILED"
            ),
            "devices": device_results,
            "first_failure": first_failure,
        },
    }
    output_root = workspace.operation_root / "qualification" / "save"
    atomic_write_json(
        workspace.operation_root,
        output_root / "execution.json",
        document,
        kind="QualificationSaveExecution",
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
            ).encode("utf-8"),
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
            ("\n".join(lines).rstrip() + "\n").encode("utf-8"),
        )
    if save_started:
        transition_workflow(
            workspace,
            (
                "qualification_completed"
                if succeeded
                else "qualification_save_failed"
            ),
            lock=lock,
            reason=(
                "qualification_baseline_save_verified"
                if succeeded
                else "qualification_baseline_save_failed"
            ),
            now=completed_at,
        )
    return document


def verify_qualification_rollback(
    workspace: OperationWorkspace,
    record: Mapping[str, Any],
    *,
    rollback_snapshot_path: str | Path,
    report_dir: str | Path | None = None,
    verification_dir: str | Path | None = None,
    update_workflow: bool = True,
    lock: OperationLock,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """Verify health plus normalized raw and semantic config restoration."""
    lock.assert_held()
    verified_at = now()
    validate_qualification_record(
        record,
        expected_change_id=workspace.change_id,
        now=verified_at,
        allow_expired=True,
    )
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"]["workflow_state"] not in {
        "rolled_back",
        "rollback_health_failed",
    }:
        raise OperationStateError(
            "qualification rollback verification requires rolled_back or "
            "rollback_health_failed state"
        )
    before_path = _below_operation(
        workspace,
        record["artifacts"]["before_snapshot"]["path"],
    )
    rollback_path = _below_operation(workspace, rollback_snapshot_path)
    before = _load_document(before_path)
    rollback = _load_document(rollback_path)
    if rollback.get("phase") != "rollback":
        raise QualificationError(
            "rollback verification Snapshot phase must be rollback"
        )
    rollback_execution = _load_document(
        _below_operation(
            workspace,
            workspace.operation_root
            / "qualification"
            / "rollback"
            / "execution.json",
        )
    )
    snapshot_fresh = rollback_snapshot_is_fresh(
        rollback,
        rollback_execution,
    )
    resolved_profiles = load_resolved_profiles(
        workspace.operation_root / "health" / "resolved-profiles.yaml"
    )
    roles_path = workspace.operation_root / "health" / "resolved-roles.yaml"
    resolved_roles = load_resolved_roles(roles_path) if roles_path.is_file() else None
    health_result = compare_snapshots(
        before,
        rollback,
        resolved_profiles,
        started_at=verified_at,
        completed_at=verified_at,
        resolved_roles=resolved_roles,
    )
    health_result["phase"] = "rollback"
    report_dir = Path(report_dir) if report_dir else (
        workspace.operation_root / "health" / "rollback-report"
    )
    verification_dir = Path(verification_dir) if verification_dir else (
        workspace.operation_root / "qualification" / "rollback"
    )
    verification_path = verification_dir / "verification.json"
    checklist_path = verification_dir / "verification-checklist.md"
    health_result["artifacts"] = {
        "before_snapshot": str(before_path),
        "after_snapshot": str(rollback_path),
        "summary": str(report_dir / "summary.md"),
    }
    validate_document(health_result, kind="HealthResult")
    health_result_path = report_dir / "health-result.json"
    atomic_write_json(
        workspace.operation_root,
        health_result_path,
        health_result,
        kind="HealthResult",
    )
    atomic_write_bytes(
        workspace.operation_root,
        report_dir / "summary.md",
        render_health_summary(health_result).encode("utf-8"),
    )

    devices: dict[str, dict[str, bool]] = {}
    before_configs = _expected_running_configs(
        before,
        list(record["target"]["devices"]),
    )
    rollback_configs = _expected_running_configs(
        rollback,
        list(record["target"]["devices"]),
    )
    for host in record["target"]["devices"]:
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
    raw_equal = all(value["raw_config_equal"] for value in devices.values())
    semantic_equal = all(
        value["semantic_config_equal"] for value in devices.values()
    )
    health_gate = evaluate_rollback_health_gate(health_result)
    verified = rollback_verification_passes(
        snapshot_fresh=snapshot_fresh,
        health_result=health_result["result"],
        raw_config_equal=raw_equal,
        semantic_config_equal=semantic_equal,
    )
    document = {
        "api_version": API_VERSION,
        "kind": "QualificationRollbackVerification",
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
            "health_result": health_result["result"],
            "health_gate": health_gate,
            "snapshot_fresh": snapshot_fresh,
            "raw_config_equal": raw_equal,
            "semantic_config_equal": semantic_equal,
        },
        "devices": devices,
        "artifacts": {
            "before_snapshot": str(before_path),
            "rollback_snapshot": str(rollback_path),
            "health_result": str(health_result_path),
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
        kind="QualificationRollbackVerification",
    )
    atomic_write_bytes(
        workspace.operation_root,
        checklist_path,
        render_rollback_verification_checklist(
            document,
            health_result,
        ).encode("utf-8"),
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
                "qualification_rollback_verified"
                if verified
                else "qualification_rollback_verification_failed"
            ),
            now=verified_at,
        )
    return document
