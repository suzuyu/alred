"""
Interactive approval record creation and validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import getpass
import json
from pathlib import Path
import secrets
import socket
from typing import Any, Callable, Mapping

import yaml

from .operation import (
    OperationLock,
    OperationPathError,
    OperationWorkspace,
    atomic_write_json,
    format_utc_offset,
    load_operation_metadata,
    now_in_timezone,
    transition_workflow,
)
from .schema import SCHEMA_VERSION, canonical_sha256, validate_document


DEFAULT_APPROVAL_HOURS = 24
MAX_APPROVAL_HOURS = 24


class ApprovalError(RuntimeError):
    """Base class for approval failures."""

    code = "APPROVAL_INVALID"


class ApprovalRequiredError(ApprovalError):
    """Raised when an explicit interactive confirmation is absent."""

    code = "APPROVAL_REQUIRED"


def _load_artifact(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(
            f"approval artifact must be a regular file: {path}"
        )
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    raise ApprovalError(
        f"approval artifact must be JSON or YAML: {path}"
    )


def _artifact_hash(
    workspace: OperationWorkspace,
    path: str | Path,
) -> tuple[Path, str, Any]:
    candidate = Path(path)
    resolved_root = workspace.operation_root.resolve()
    resolved_path = candidate.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise OperationPathError(
            f"approval artifact is outside operation root: {candidate}"
        ) from exc
    document = _load_artifact(resolved_path)
    if not isinstance(document, (dict, list)):
        raise ApprovalError(
            f"approval artifact must contain an object or array: {candidate}"
        )
    if isinstance(document, dict):
        artifact_change_id = document.get("change_id")
        if (
            artifact_change_id is not None
            and artifact_change_id != workspace.change_id
        ):
            raise ApprovalError(
                f"artifact change_id mismatch: {candidate}"
            )
    return resolved_path, canonical_sha256(document), document


def _plan_approval_artifact_paths(
    execution_plan: Mapping[str, Any],
) -> dict[str, str]:
    artifacts = execution_plan.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        raise ApprovalError("execution plan artifacts must be an object")
    raw = artifacts.get("approval_artifacts", {})
    if not isinstance(raw, Mapping):
        raise ApprovalError(
            "execution plan approval_artifacts must be an object"
        )
    paths: dict[str, str] = {}
    for name, path in raw.items():
        if not isinstance(name, str) or not isinstance(path, str) or not path:
            raise ApprovalError(
                "execution plan approval artifact names and paths must be strings"
            )
        paths[name] = path
    return paths


def calculate_approval_artifact_hashes(
    workspace: OperationWorkspace,
    execution_plan: Mapping[str, Any],
    rollback_plan: Mapping[str, Any],
) -> dict[str, str]:
    """Recalculate every mandatory and plan-declared approval hash."""
    hashes = {
        "execution_plan": canonical_sha256(execution_plan),
        "rollback_plan": canonical_sha256(rollback_plan),
    }
    for name, path in sorted(
        _plan_approval_artifact_paths(execution_plan).items()
    ):
        if name in hashes:
            raise ApprovalError(f"duplicate approval artifact name: {name}")
        _resolved_path, digest, _document = _artifact_hash(workspace, path)
        hashes[name] = digest
    return hashes


def build_approval_summary(
    workspace: OperationWorkspace,
    *,
    plan_path: str | Path,
    rollback_plan_path: str | Path,
    artifacts: Mapping[str, str] | None = None,
    max_devices: int = 50,
    save_on_success: bool = True,
    rollback_policy: str = "manual",
) -> dict[str, Any]:
    """Resolve and hash the exact artifacts shown for approval."""
    if not 1 <= max_devices <= 50:
        raise ApprovalError("max_devices must be between 1 and 50")
    if rollback_policy != "manual":
        raise ApprovalError(
            "only rollback_policy=manual is supported initially"
        )
    resolved: dict[str, str] = {}
    paths: dict[str, str] = {}
    required = {
        "execution_plan": plan_path,
        "rollback_plan": rollback_plan_path,
    }
    loaded_documents: dict[str, Any] = {}
    for name, raw_path in required.items():
        resolved_path, digest, document = _artifact_hash(workspace, raw_path)
        resolved[name] = digest
        paths[name] = str(resolved_path)
        loaded_documents[name] = document
    for name, raw_path in sorted((artifacts or {}).items()):
        if name in resolved:
            raise ApprovalError(f"duplicate approval artifact name: {name}")
        resolved_path, digest, _document = _artifact_hash(workspace, raw_path)
        resolved[name] = digest
        paths[name] = str(resolved_path)

    execution_plan = loaded_documents["execution_plan"]
    rollback_plan = loaded_documents["rollback_plan"]
    if not isinstance(execution_plan, dict) or not isinstance(
        rollback_plan,
        dict,
    ):
        raise ApprovalError("execution and rollback plans must be JSON objects")
    validate_document(execution_plan, kind="ExecutionPlan")
    validate_document(rollback_plan, kind="RollbackPlan")
    for name, document in (
        ("execution plan", execution_plan),
        ("rollback plan", rollback_plan),
    ):
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ApprovalError(f"{name} requires schema_version=1")
        if document.get("change_id") != workspace.change_id:
            raise ApprovalError(f"{name} change_id mismatch")

    for name, raw_path in sorted(
        _plan_approval_artifact_paths(execution_plan).items()
    ):
        if name in resolved:
            raise ApprovalError(f"duplicate approval artifact name: {name}")
        resolved_path, digest, _document = _artifact_hash(
            workspace,
            raw_path,
        )
        resolved[name] = digest
        paths[name] = str(resolved_path)

    capability_level = execution_plan.get("capability_level")
    if capability_level != "APPLY_VERIFIED":
        raise ApprovalError(
            "execution plan capability_level must be APPLY_VERIFIED"
        )
    devices = execution_plan.get("devices", [])
    if not isinstance(devices, (list, dict)):
        raise ApprovalError("execution plan devices must be an array or object")
    device_count = len(devices)
    if device_count > max_devices or device_count > 50:
        raise ApprovalError(
            f"execution plan device count {device_count} exceeds "
            f"approved maximum {min(max_devices, 50)}"
        )
    return {
        "change_id": workspace.change_id,
        "paths": paths,
        "artifacts": resolved,
        "device_count": device_count,
        "capability_level": capability_level,
        "constraints": {
            "max_devices": max_devices,
            "save_on_success": save_on_success,
            "rollback_policy": rollback_policy,
        },
    }


def create_approval_record(
    workspace: OperationWorkspace,
    summary: Mapping[str, Any],
    *,
    lock: OperationLock,
    confirm: Callable[[Mapping[str, Any]], bool],
    approval_hours: int = DEFAULT_APPROVAL_HOURS,
    now: datetime | None = None,
    random_hex: str | None = None,
) -> Path:
    """Create an immutable approval record after explicit confirmation."""
    lock.assert_held()
    if not 1 <= approval_hours <= MAX_APPROVAL_HOURS:
        raise ApprovalError(
            "approval validity must be between 1 and 24 hours"
        )
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"]["workflow_state"] != "plan_ready":
        raise ApprovalError(
            "workflow must be plan_ready before approval"
        )
    if summary.get("change_id") != workspace.change_id:
        raise ApprovalError("approval summary change_id mismatch")
    if not confirm(summary):
        raise ApprovalRequiredError(
            "explicit interactive approval was not provided"
        )

    approved_at = now_in_timezone(workspace.timezone, now=now)
    expires_at = approved_at + timedelta(hours=approval_hours)
    _iso_offset, offset_token = format_utc_offset(approved_at)
    token = random_hex or secrets.token_hex(3)
    if len(token) != 6 or any(char not in "0123456789abcdef" for char in token):
        raise ApprovalError(
            "approval random token must be six lowercase hexadecimal characters"
        )
    approval_id = (
        f"APR-{approved_at.strftime('%Y%m%dT%H%M%S')}-"
        f"{offset_token}-{token}"
    )
    document = {
        "schema_version": SCHEMA_VERSION,
        "approval_id": approval_id,
        "change_id": workspace.change_id,
        "approved_at": approved_at.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "approval_method": "interactive",
        "approver": {
            "os_user": getpass.getuser(),
            "hostname": socket.gethostname(),
        },
        "artifacts": dict(summary["artifacts"]),
        "constraints": dict(summary["constraints"]),
    }
    validate_document(document, kind="ApprovalRecord")
    approval_dir = workspace.operation_root / "approval"
    primary_path = approval_dir / "approval-record.json"
    if primary_path.exists():
        output_path = approval_dir / f"approval-record.{approval_id}.json"
    else:
        output_path = primary_path
    if output_path.exists():
        raise ApprovalError(
            f"approval record already exists and will not be overwritten: "
            f"{output_path}"
        )
    atomic_write_json(
        workspace.operation_root,
        output_path,
        document,
        kind="ApprovalRecord",
    )
    transition_workflow(
        workspace,
        "approved",
        lock=lock,
        reason=f"approval_record_created:{output_path.name}",
        now=approved_at,
    )
    return output_path


def load_approval_record(path: str | Path) -> dict[str, Any]:
    """Load and schema-validate an approval record."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise ApprovalError(f"approval record not found: {candidate}")
    document = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ApprovalError("approval record must be a JSON object")
    validate_document(
        document,
        kind="ApprovalRecord",
        allow_unknown_fields=True,
    )
    return document


def validate_approval(
    record: Mapping[str, Any],
    *,
    expected_change_id: str,
    expected_artifacts: Mapping[str, str],
    now: datetime,
) -> None:
    """Validate expiry, identity, and all approved artifact hashes."""
    validate_document(
        record,
        kind="ApprovalRecord",
        allow_unknown_fields=True,
    )
    if record["change_id"] != expected_change_id:
        raise ApprovalError("approval change_id mismatch")
    expires_at = datetime.fromisoformat(record["expires_at"])
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if now >= expires_at:
        raise ApprovalError("approval has expired")
    if dict(record["artifacts"]) != dict(expected_artifacts):
        raise ApprovalError("approval artifact hash mismatch")
