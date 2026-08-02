"""Selection and provenance for offline Overlay preparation reference state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .operation import (
    OperationError,
    load_operation_metadata,
    open_operation_workspace,
)
from .schema import SCHEMA_VERSION, source_sha256, validate_document


class ReferenceStateError(ValueError):
    """Raised when no safe reference state can be selected."""

    code = "REFERENCE_STATE_NOT_FOUND"


class ReferenceStateStaleError(ReferenceStateError):
    """Raised when an otherwise valid reference exceeds the age policy."""

    code = "REFERENCE_STATE_STALE"


class ReferenceStateNotEligibleError(ReferenceStateError):
    """Raised when an explicit operation is not a safe reference source."""

    code = "REFERENCE_STATE_NOT_ELIGIBLE"


@dataclass(frozen=True)
class SelectedReferenceState:
    document: dict[str, Any]
    snapshot: dict[str, Any]


def _read_json(path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReferenceStateError(f"reference artifact is missing or unsafe: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ReferenceStateError(f"reference artifact is not a mapping: {path}")
    validate_document(document, kind=kind, allow_unknown_fields=True)
    return document


def _terminal_phase(workflow_state: str | None) -> str | None:
    if workflow_state == "completed":
        return "after"
    if workflow_state == "rolled_back_and_verified":
        return "rollback"
    return None


def _reference_phase(
    metadata: Mapping[str, Any],
    requested_phase: str | None = None,
) -> tuple[str, str]:
    workflow_state = metadata["spec"].get("workflow_state")
    terminal_phase = _terminal_phase(workflow_state)
    if terminal_phase is not None:
        if requested_phase is not None and requested_phase != terminal_phase:
            raise ReferenceStateNotEligibleError(
                f"terminal workflow {workflow_state} requires phase "
                f"{terminal_phase}, not {requested_phase}"
            )
        return terminal_phase, "overlay_terminal"
    if workflow_state is not None:
        raise ReferenceStateNotEligibleError(
            f"workflow state {workflow_state!r} is not a healthy terminal state"
        )
    if requested_phase not in (None, "after"):
        raise ReferenceStateNotEligibleError(
            "standalone health-check operations can reference only after"
        )
    after = metadata["spec"].get("phases", {}).get("after", {})
    if after.get("status") not in {"completed", "completed_with_warnings"}:
        raise ReferenceStateNotEligibleError(
            "standalone health-check after phase is not completed"
        )
    return "after", "standalone_health_after"


def _candidate(
    operation_root: Path,
    *,
    phase: str,
    source_type: str,
    target_hosts: set[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    metadata = load_operation_metadata(operation_root)
    snapshot_path = operation_root / "health" / phase / "snapshot.json"
    health_path = operation_root / "health" / phase / "health-result.json"
    snapshot = _read_json(snapshot_path, "HealthSnapshot")
    health = _read_json(health_path, "HealthResult")
    if health.get("result") != "PASS":
        raise ReferenceStateNotEligibleError(
            f"operation {operation_root.name} {phase} health result is "
            f"{health.get('result')!r}, not PASS"
        )
    comparison = None
    if source_type == "standalone_health_after":
        comparison_path = operation_root / "health" / "report" / "health-result.json"
        if comparison_path.exists():
            comparison = _read_json(comparison_path, "HealthResult")
            if comparison.get("result") != "PASS":
                raise ReferenceStateNotEligibleError(
                    f"operation {operation_root.name} compare result is "
                    f"{comparison.get('result')!r}, not PASS"
                )
    missing = target_hosts - set(snapshot.get("hosts", {}))
    if missing:
        raise ReferenceStateError(
            f"operation {operation_root.name} {phase} is missing target hosts: "
            + ", ".join(sorted(missing))
        )
    for host in sorted(target_hosts):
        record = snapshot["hosts"][host]
        config = record.get("profiles", {}).get("nxos-overlay", {}).get("config")
        source = record.get("sources", {}).get("running_config")
        if not isinstance(config, Mapping) or not isinstance(source, Mapping):
            raise ReferenceStateError(
                f"operation {operation_root.name} {phase} lacks Overlay "
                f"running-config evidence for {host}"
            )
    return metadata, snapshot, health, comparison


def _operation_directories(operations_root: Path) -> Iterable[Path]:
    if not operations_root.is_dir():
        return []
    return (
        path
        for path in sorted(operations_root.iterdir())
        if path.is_dir() and not path.is_symlink()
    )


def select_reference_state(
    operations_root: str | Path,
    *,
    current_change_id: str,
    target_hosts: Iterable[str],
    evaluated_at: datetime,
    max_age_days: int = 30,
    reference_state: str | None = None,
    reference_operation_id: str | None = None,
    reference_phase: str | None = None,
) -> SelectedReferenceState:
    """Select one terminal, healthy, target-complete Snapshot."""
    if max_age_days < 1:
        raise ReferenceStateError("--reference-max-age-days must be at least 1")
    if (reference_state is None) == (reference_operation_id is None):
        raise ReferenceStateError(
            "exactly one of --reference-state or --reference-operation-id is required"
        )
    if reference_state not in (None, "latest-known-good"):
        raise ReferenceStateError("unsupported --reference-state value")
    if reference_phase is not None and reference_operation_id is None:
        raise ReferenceStateError(
            "--reference-phase requires --reference-operation-id"
        )
    if reference_phase not in (None, "after", "rollback"):
        raise ReferenceStateError("--reference-phase must be after or rollback")

    root = Path(operations_root)
    targets = set(target_hosts)
    candidates: list[
        tuple[
            datetime,
            Path,
            str,
            str,
            dict[str, Any],
            dict[str, Any],
            dict[str, Any] | None,
        ]
    ] = []
    if reference_operation_id is not None:
        reference_workspace = open_operation_workspace(
            root,
            reference_operation_id,
        )
        operation_root = reference_workspace.operation_root
        if operation_root.name == current_change_id:
            raise ReferenceStateError("prepare-plan cannot reference its own operation")
        metadata = load_operation_metadata(operation_root)
        phase, source_type = _reference_phase(metadata, reference_phase)
        metadata, snapshot, health, comparison = _candidate(
            operation_root,
            phase=phase,
            source_type=source_type,
            target_hosts=targets,
        )
        created_at = datetime.fromisoformat(snapshot["created_at"])
        candidates.append(
            (
                created_at,
                operation_root,
                phase,
                source_type,
                snapshot,
                health,
                comparison,
            )
        )
        mode = "explicit"
    else:
        mode = "latest-known-good"
        for operation_root in _operation_directories(root):
            if operation_root.name == current_change_id:
                continue
            try:
                operation_root = open_operation_workspace(
                    root,
                    operation_root.name,
                ).operation_root
                metadata = load_operation_metadata(operation_root)
                phase, source_type = _reference_phase(metadata)
                _metadata, snapshot, health, comparison = _candidate(
                    operation_root,
                    phase=phase,
                    source_type=source_type,
                    target_hosts=targets,
                )
                created_at = datetime.fromisoformat(snapshot["created_at"])
                candidates.append(
                    (
                        created_at,
                        operation_root,
                        phase,
                        source_type,
                        snapshot,
                        health,
                        comparison,
                    )
                )
            except (
                ReferenceStateError,
                OperationError,
                ValueError,
                OSError,
                json.JSONDecodeError,
            ):
                continue
    if not candidates:
        raise ReferenceStateError(
            "no healthy terminal reference state contains every target device"
        )

    (
        created_at,
        operation_root,
        phase,
        source_type,
        snapshot,
        _health,
        comparison,
    ) = max(
        candidates, key=lambda item: item[0]
    )
    if created_at.tzinfo is None or evaluated_at.tzinfo is None:
        raise ReferenceStateError("reference and evaluation timestamps require timezone")
    age_seconds = max(0, int((evaluated_at - created_at).total_seconds()))
    if age_seconds > max_age_days * 86400:
        raise ReferenceStateStaleError(
            f"reference state is {age_seconds / 86400:.2f} days old "
            f"(maximum: {max_age_days})"
        )
    snapshot_path = operation_root / "health" / phase / "snapshot.json"
    health_path = operation_root / "health" / phase / "health-result.json"
    workflow_state = load_operation_metadata(operation_root)["spec"][
        "workflow_state"
    ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "change_id": current_change_id,
        "selection": {"mode": mode, "max_age_days": max_age_days},
        "source": {
            "operation_id": operation_root.name,
            "phase": phase,
            "source_type": source_type,
            "workflow_state": workflow_state,
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": source_sha256(snapshot_path),
            "snapshot_created_at": created_at.isoformat(timespec="seconds"),
            "health_result_path": str(health_path),
            "health_result_sha256": source_sha256(health_path),
        },
        "age": {
            "evaluated_at": evaluated_at.isoformat(timespec="seconds"),
            "seconds": age_seconds,
            "days": round(age_seconds / 86400, 6),
        },
        "targets": sorted(targets),
    }
    if comparison is not None:
        comparison_path = operation_root / "health" / "report" / "health-result.json"
        document["source"]["comparison"] = {
            "path": str(comparison_path),
            "sha256": source_sha256(comparison_path),
            "result": comparison["result"],
        }
    validate_document(document, kind="OverlayReferenceState")
    return SelectedReferenceState(document=document, snapshot=snapshot)
