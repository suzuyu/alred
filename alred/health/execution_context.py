"""Pinned, non-secret execution context for health-check phase reuse."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..operation import OperationStateError
from ..schema import API_VERSION, source_sha256, validate_document


CONTEXT_RELATIVE_PATH = Path("health") / "execution-context.yaml"


class HealthExecutionContextError(OperationStateError):
    """Raised when a saved health execution context cannot be reused safely."""

    code = "VALIDATION_ERROR"


def source_file_reference(path: str | Path) -> dict[str, str]:
    """Return a canonical path and content hash for a reusable source file."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise HealthExecutionContextError(
            f"execution context source file is missing or unsafe: {candidate}"
        )
    resolved = candidate.resolve()
    return {"path": str(resolved), "sha256": source_sha256(resolved)}


def build_health_execution_context(
    *,
    change_id: str,
    recorded_at: datetime,
    timezone: str,
    input_mode: str,
    inventory_path: str | Path | None,
    policy_path: str | Path | None,
    input_format: str | None,
    collection: Mapping[str, Any] | None,
    authentication: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and validate one context without storing credential secrets."""
    document = {
        "api_version": API_VERSION,
        "kind": "HealthCheckExecutionContext",
        "metadata": {
            "change_id": change_id,
            "recorded_at": recorded_at.isoformat(timespec="seconds"),
            "timezone": timezone,
        },
        "spec": {
            "input_mode": input_mode,
            "inventory": (
                source_file_reference(inventory_path)
                if inventory_path is not None
                else None
            ),
            "policy": (
                source_file_reference(policy_path) if policy_path is not None else None
            ),
            "input_format": input_format,
            "collection": dict(collection) if collection is not None else None,
            "authentication": dict(authentication),
        },
    }
    validate_document(document, kind="HealthCheckExecutionContext")
    return document


def load_health_execution_context(
    operation_root: str | Path,
) -> dict[str, Any] | None:
    """Load a context, returning None for operations created before it existed."""
    path = Path(operation_root) / CONTEXT_RELATIVE_PATH
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise HealthExecutionContextError(
            f"health execution context is missing or unsafe: {path}"
        )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise HealthExecutionContextError(
            f"health execution context is not a mapping: {path}"
        )
    validate_document(document, kind="HealthCheckExecutionContext")
    if document["metadata"]["change_id"] != Path(operation_root).name:
        raise HealthExecutionContextError(
            "health execution context change-id does not match operation"
        )
    return document


def verify_source_file(
    reference: Mapping[str, str],
    supplied_path: str | Path | None,
    *,
    label: str,
) -> str:
    """Resolve an inherited/explicit source and require its pinned hash."""
    candidate = Path(supplied_path or reference["path"])
    if not candidate.is_file() or candidate.is_symlink():
        raise HealthExecutionContextError(
            f"inherited {label} file is missing or unsafe: {candidate}"
        )
    resolved = candidate.resolve()
    if source_sha256(resolved) != reference["sha256"]:
        raise HealthExecutionContextError(
            f"inherited {label} hash does not match before: {resolved}"
        )
    return str(resolved)
