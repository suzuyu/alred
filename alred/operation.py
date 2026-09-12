"""
Common operation workspace, state, lock, and active-change primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import gzip
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import tempfile
import tarfile
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from . import __version__
from .schema import API_VERSION, SCHEMA_VERSION, validate_document


DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_OPERATIONS_ROOT = "operations"
MAX_CHANGE_ID_LENGTH = 128
MIN_FREE_SPACE_BYTES = 1024**3

OPERATION_STATES = {
    "created",
    "running",
    "waiting_for_user",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "state_unknown",
}
PHASE_STATES = {
    "not_started",
    "running",
    "waiting_for_user",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "unknown",
}
OPERATION_TRANSITIONS = {
    "created": {"running", "cancelled", "failed"},
    "running": {
        "waiting_for_user",
        "completed",
        "completed_with_warnings",
        "failed",
        "cancelled",
        "state_unknown",
    },
    "waiting_for_user": {"running", "failed", "cancelled"},
    "completed": set(),
    "completed_with_warnings": set(),
    "failed": set(),
    "cancelled": set(),
    "state_unknown": set(),
}
PHASE_TRANSITIONS = {
    "not_started": {"running", "cancelled"},
    "running": {
        "waiting_for_user",
        "completed",
        "completed_with_warnings",
        "failed",
        "cancelled",
        "unknown",
    },
    "waiting_for_user": {"running", "failed", "cancelled"},
    "completed": set(),
    "completed_with_warnings": set(),
    "failed": set(),
    "cancelled": set(),
    "unknown": set(),
}
WORKFLOW_TRANSITIONS = {
    None: {"planned"},
    "planned": {"before_running"},
    "before_running": {"before_failed", "before_completed"},
    "before_failed": set(),
    "before_completed": {"plan_ready"},
    "plan_ready": {"approved"},
    "approved": {"apply_running"},
    "apply_running": {
        "apply_failed",
        "device_state_unknown",
        "apply_completed",
    },
    "apply_completed": {"after_running"},
    "after_running": {"health_failed", "after_completed"},
    "after_completed": {"save_running", "completed", "rollback_required"},
    "save_running": {"save_failed", "completed"},
    "apply_failed": {"rollback_required"},
    "device_state_unknown": {"rollback_required"},
    "health_failed": {"rollback_required"},
    "save_failed": {"rollback_required"},
    "rollback_required": {"after_running", "rollback_running"},
    "rollback_running": {
        "rollback_failed",
        "rollback_required",
        "rolled_back",
    },
    "rollback_failed": set(),
    "rolled_back": {
        "rollback_health_failed",
        "rolled_back_and_verified",
    },
    "rollback_health_failed": {
        "rollback_health_failed",
        "rolled_back_and_verified",
    },
    "rolled_back_and_verified": {
        "save_running",
        "qualification_save_running",
    },
    "qualification_save_running": {
        "qualification_save_failed",
        "qualification_completed",
    },
    "qualification_save_failed": set(),
    "qualification_completed": set(),
    "completed": {"rollback_required"},
}


class OperationError(RuntimeError):
    """Base class for common operation failures."""

    code = "VALIDATION_ERROR"


class OperationLockedError(OperationError):
    """Raised when a mutating operation cannot acquire its lock."""

    code = "OPERATION_LOCKED"


class OperationStateError(OperationError):
    """Raised for an invalid lifecycle or phase transition."""

    code = "VALIDATION_ERROR"


class OperationPathError(OperationError):
    """Raised when a workspace path violates the protection policy."""

    code = "VALIDATION_ERROR"


class OperationArchivedError(OperationPathError):
    """Raised when a live-only command targets an archived operation."""

    code = "OPERATION_ARCHIVED"


ARCHIVABLE_OPERATION_STATES = {
    "completed",
    "completed_with_warnings",
    "cancelled",
}

PRE_APPLY_CLOSABLE_WORKFLOW_STATES = {
    None,
    "planned",
    "before_running",
    "before_completed",
    "plan_ready",
    "approved",
}


@dataclass(frozen=True)
class OperationWorkspace:
    """Resolved operation paths and initial metadata."""

    operations_root: Path
    operation_root: Path
    change_id: str
    change_id_source: str
    timezone: str
    created_at: datetime

    @property
    def metadata_path(self) -> Path:
        return self.operation_root / "metadata.yaml"

    @property
    def execution_path(self) -> Path:
        return self.operation_root / "execution.json"

    @property
    def lock_path(self) -> Path:
        return self.operation_root / ".operation.lock"


@dataclass(frozen=True)
class PreflightIssue:
    """One deterministic operation preflight finding."""

    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """Operation preflight result."""

    issues: tuple[PreflightIssue, ...]
    free_bytes: int
    required_bytes: int
    filesystem_type: str | None

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)


def validate_change_id(change_id: str) -> str:
    """Validate a user-specified change ID without normalizing it."""
    import re

    if not isinstance(change_id, str):
        raise ValueError("change-id must be a string")
    if not 1 <= len(change_id) <= MAX_CHANGE_ID_LENGTH:
        raise ValueError("change-id must be between 1 and 128 characters")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", change_id):
        raise ValueError(
            "change-id must start with an ASCII alphanumeric and contain "
            "only ASCII alphanumeric, '.', '_', or '-'"
        )
    if ".." in change_id:
        raise ValueError("change-id must not contain '..'")
    return change_id


def resolve_timezone_name(explicit: str | None = None) -> str:
    """Resolve CLI, environment, and default timezone precedence."""
    timezone_name = explicit or os.environ.get("ALRED_TIMEZONE") or DEFAULT_TIMEZONE
    if timezone_name == "JST" or timezone_name.startswith(("+", "-")):
        raise ValueError(
            "timezone must be an IANA name such as Asia/Tokyo; "
            "fixed offsets and JST are not accepted"
        )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc
    return timezone_name


def now_in_timezone(
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> datetime:
    """Return an offset-aware datetime in the resolved timezone."""
    timezone = ZoneInfo(timezone_name)
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone)


def format_utc_offset(value: datetime) -> tuple[str, str]:
    """Return ISO offset and path-safe offset token."""
    raw = value.strftime("%z")
    if len(raw) != 5:
        raise ValueError("datetime does not have a valid UTC offset")
    iso_offset = f"{raw[:3]}:{raw[3:]}"
    prefix = "p" if raw.startswith("+") else "m"
    return iso_offset, prefix + raw[1:]


def generate_change_id(
    timezone_name: str,
    *,
    now: datetime | None = None,
    random_hex: str | None = None,
    prefix: str = "HC",
) -> str:
    """Generate a path-safe change ID using configured local time."""
    current = now_in_timezone(timezone_name, now=now)
    _iso_offset, offset_token = format_utc_offset(current)
    token = random_hex or secrets.token_hex(3)
    if len(token) != 6 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("random_hex must be six lowercase hexadecimal characters")
    generated = (
        f"{prefix}-{current.strftime('%Y%m%dT%H%M%S')}-"
        f"{offset_token}-{token}"
    )
    return validate_change_id(generated)


def generate_attempt_id(
    phase: str,
    timezone_name: str,
    *,
    now: datetime | None = None,
    random_hex: str | None = None,
) -> str:
    """Generate a stable attempt ID independent from collection IDs."""
    if not phase or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in phase):
        raise ValueError("phase must use lowercase letters, digits, '_' or '-'")
    current = now_in_timezone(timezone_name, now=now)
    _iso_offset, offset_token = format_utc_offset(current)
    token = random_hex or secrets.token_hex(3)
    if len(token) != 6 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("random_hex must be six lowercase hexadecimal characters")
    return (
        f"{phase}-{current.strftime('%Y%m%dT%H%M%S')}-"
        f"{offset_token}-{token}"
    )


def _ensure_directory(path: Path, mode: int = 0o700) -> None:
    if path.exists() and path.is_symlink():
        raise OperationPathError(f"symlink directory is not allowed: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise OperationPathError(f"regular directory is required: {path}")
    path.chmod(mode)


def _assert_below_root(root: Path, path: Path) -> None:
    root_absolute = root.absolute()
    path_absolute = path.absolute()
    try:
        lexical_relative = path_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise OperationPathError(
            f"path escapes operation root: {path}"
        ) from exc

    current = root_absolute
    for part in lexical_relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise OperationPathError(f"symlink path is not allowed: {current}")

    root_resolved = root.resolve()
    path_resolved = path.resolve(strict=False)
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise OperationPathError(
            f"path escapes operation root: {path}"
        ) from exc


def atomic_write_bytes(
    operation_root: str | Path,
    path: str | Path,
    content: bytes,
    *,
    file_mode: int = 0o600,
) -> Path:
    """Atomically write a regular file below an operation root."""
    root = Path(operation_root)
    target = Path(path)
    _assert_below_root(root, target)
    _ensure_directory(target.parent)
    if target.exists() and (
        target.is_symlink() or not stat.S_ISREG(target.stat().st_mode)
    ):
        raise OperationPathError(
            f"operation output must be a regular file: {target}"
        )

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, file_mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        target.chmod(file_mode)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return target
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(
    operation_root: str | Path,
    path: str | Path,
    document: Mapping[str, Any],
    *,
    kind: str | None = None,
) -> Path:
    """Validate and atomically write formatted JSON."""
    validate_document(document, kind=kind)
    content = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    return atomic_write_bytes(operation_root, path, content)


def atomic_write_yaml(
    operation_root: str | Path,
    path: str | Path,
    document: Mapping[str, Any],
    *,
    kind: str | None = None,
) -> Path:
    """Validate and atomically write YAML."""
    validate_document(document, kind=kind)
    content = yaml.safe_dump(
        dict(document),
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    return atomic_write_bytes(operation_root, path, content)


def atomic_update_relative_directory_symlink(
    root: str | Path,
    link_path: str | Path,
    target_path: str | Path,
) -> Path:
    """Atomically publish a relative convenience symlink below one trusted root."""
    trusted_root = Path(root).resolve()
    link = Path(link_path)
    target = Path(target_path)
    link_parent = link.parent
    _ensure_directory(link_parent)
    try:
        link_parent.resolve().relative_to(trusted_root)
        target_resolved = target.resolve(strict=True)
        target_resolved.relative_to(trusted_root)
    except (OSError, ValueError) as exc:
        raise OperationPathError(
            f"latest symlink path escapes trusted root: {link} -> {target}"
        ) from exc
    if not target_resolved.is_dir() or target.is_symlink():
        raise OperationPathError(
            f"latest symlink target must be a regular directory: {target}"
        )
    if os.path.lexists(link) and not link.is_symlink():
        raise OperationPathError(
            f"latest path exists and is not a symbolic link: {link}"
        )

    temporary = link_parent / f".{link.name}.{secrets.token_hex(6)}.tmp"
    relative_target = os.path.relpath(target_resolved, link_parent.resolve())
    try:
        os.symlink(relative_target, temporary, target_is_directory=True)
        os.replace(temporary, link)
        directory_fd = os.open(link_parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()
    return link


def publish_latest_operation_link(workspace: OperationWorkspace) -> Path:
    """Point operations/live/latest at one successfully published operation."""
    return atomic_update_relative_directory_symlink(
        workspace.operations_root,
        workspace.operations_root / "live" / "latest",
        workspace.operation_root,
    )


def remove_latest_operation_link_for(workspace: OperationWorkspace) -> None:
    """Remove a convenience link before its live operation is archived."""
    latest = workspace.operations_root / "live" / "latest"
    if not latest.is_symlink():
        return
    try:
        points_to_workspace = latest.resolve(strict=True) == (
            workspace.operation_root.resolve(strict=True)
        )
    except OSError:
        points_to_workspace = True
    if not points_to_workspace:
        return
    latest.unlink()
    directory_fd = os.open(latest.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _initial_documents(
    change_id: str,
    change_id_source: str,
    timezone_name: str,
    created_at: datetime,
    operation_root: Path,
    purpose: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    iso_offset, _offset_token = format_utc_offset(created_at)
    transition = {
        "scope": "operation",
        "from": None,
        "to": "created",
        "at": created_at.isoformat(timespec="seconds"),
        "reason": "workspace_created",
    }
    metadata = {
        "api_version": API_VERSION,
        "kind": "OperationMetadata",
        "metadata": {
            "change_id": change_id,
            "change_id_source": change_id_source,
            "timezone": timezone_name,
            "utc_offset": iso_offset,
            "created_at": created_at.isoformat(timespec="seconds"),
            "tool_version": __version__,
        },
        "spec": {
            "output_root": str(operation_root),
            "purpose": purpose,
            "lifecycle": "created",
            "workflow_state": None,
            "phases": {},
            "last_transition": transition,
        },
    }
    execution = {
        "schema_version": SCHEMA_VERSION,
        "change_id": change_id,
        "lifecycle": "created",
        "workflow_state": None,
        "phases": {},
        "transitions": [transition],
        "errors": [],
    }
    return metadata, execution


def create_operation_workspace(
    operations_root: str | Path = DEFAULT_OPERATIONS_ROOT,
    *,
    change_id: str | None = None,
    timezone_name: str | None = None,
    now: datetime | None = None,
    random_token_factory: Callable[[], str] | None = None,
    prefix: str = "HC",
    purpose: str = "change",
) -> OperationWorkspace:
    """Create a secure operation root and its initial state documents."""
    if purpose not in {"change", "inspection", "initial_lab_qualification"}:
        raise ValueError(f"unsupported operation purpose: {purpose}")
    resolved_timezone = resolve_timezone_name(timezone_name)
    created_at = now_in_timezone(resolved_timezone, now=now)
    root = Path(operations_root)
    _ensure_directory(root)
    _ensure_directory(root / "live")
    _ensure_directory(root / ".index")
    token_factory = random_token_factory or (lambda: secrets.token_hex(3))

    if change_id is not None:
        resolved_change_id = validate_change_id(change_id)
        source = "specified"
        if operation_location_exists(root, resolved_change_id):
            raise OperationPathError(
                f"operation already exists: {resolved_change_id}"
            )
        operation_root = _dated_operation_root(
            root, resolved_change_id, created_at
        )
        _ensure_directory(operation_root.parent)
        try:
            operation_root.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise OperationPathError(
                f"operation already exists: {operation_root}"
            ) from exc
    else:
        source = "generated"
        for _attempt in range(100):
            resolved_change_id = generate_change_id(
                resolved_timezone,
                now=created_at,
                random_hex=token_factory(),
                prefix=prefix,
            )
            if operation_location_exists(root, resolved_change_id):
                continue
            operation_root = _dated_operation_root(
                root, resolved_change_id, created_at
            )
            _ensure_directory(operation_root.parent)
            try:
                operation_root.mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        else:
            raise OperationPathError(
                "could not allocate a unique generated operation directory"
            )

    operation_root.chmod(0o700)
    workspace = OperationWorkspace(
        operations_root=root,
        operation_root=operation_root,
        change_id=resolved_change_id,
        change_id_source=source,
        timezone=resolved_timezone,
        created_at=created_at,
    )
    metadata, execution = _initial_documents(
        workspace.change_id,
        source,
        resolved_timezone,
        created_at,
        operation_root,
        purpose,
    )
    try:
        atomic_write_yaml(
            operation_root,
            workspace.metadata_path,
            metadata,
            kind="OperationMetadata",
        )
        atomic_write_json(
            operation_root,
            workspace.execution_path,
            execution,
            kind="OperationExecution",
        )
        _write_operation_location(
            root,
            _operation_location_document(
                resolved_change_id,
                created_at=created_at,
                state="live",
                layout="dated-v1",
                relative_path=operation_root.relative_to(root),
                updated_at=created_at,
            ),
        )
    except Exception:
        for owned_path in (workspace.metadata_path, workspace.execution_path):
            if owned_path.exists() and owned_path.is_file():
                owned_path.unlink()
        operation_root.rmdir()
        raise
    return workspace


def open_operation_workspace(
    operations_root: str | Path,
    change_id: str,
) -> OperationWorkspace:
    """Open and validate an existing operation workspace."""
    resolved_change_id = validate_change_id(change_id)
    root = Path(operations_root)
    location = load_operation_location(root, resolved_change_id)
    if location is not None:
        if location["spec"]["state"] == "archived":
            raise OperationArchivedError(
                f"operation is archived: {resolved_change_id}; "
                "use operation status/inspect"
            )
        operation_root = root / location["spec"]["relative_path"]
    else:
        operation_root = root / resolved_change_id
    _assert_below_root(root, operation_root)
    if not operation_root.is_dir() or operation_root.is_symlink():
        raise OperationPathError(f"operation does not exist: {operation_root}")
    metadata = load_operation_metadata(operation_root)
    if metadata["metadata"]["change_id"] != resolved_change_id:
        raise OperationPathError(
            "operation metadata change_id does not match directory name"
        )
    metadata_root = Path(metadata["spec"]["output_root"]).resolve()
    if metadata_root != operation_root.resolve():
        raise OperationPathError(
            "operation metadata output_root does not match directory path"
        )
    created_at = datetime.fromisoformat(metadata["metadata"]["created_at"])
    return OperationWorkspace(
        operations_root=root,
        operation_root=operation_root,
        change_id=resolved_change_id,
        change_id_source=metadata["metadata"]["change_id_source"],
        timezone=metadata["metadata"]["timezone"],
        created_at=created_at,
    )


def _dated_operation_root(
    root: Path,
    change_id: str,
    created_at: datetime,
) -> Path:
    return (
        root
        / "live"
        / created_at.strftime("%Y")
        / created_at.strftime("%m")
        / created_at.strftime("%d")
        / change_id
    )


def _operation_index_path(root: Path, change_id: str) -> Path:
    return root / ".index" / f"{validate_change_id(change_id)}.yaml"


def _operation_location_document(
    change_id: str,
    *,
    created_at: datetime,
    state: str,
    layout: str,
    relative_path: Path,
    updated_at: datetime,
    archive_sha256: str | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "storage_version": 1,
        "state": state,
        "layout": layout,
        "created_date": created_at.date().isoformat(),
        "relative_path": relative_path.as_posix(),
    }
    if archive_sha256 is not None:
        spec["archive_sha256"] = archive_sha256
    return {
        "api_version": API_VERSION,
        "kind": "OperationLocation",
        "metadata": {
            "change_id": change_id,
            "updated_at": updated_at.isoformat(timespec="seconds"),
        },
        "spec": spec,
    }


def _write_operation_location(
    root: Path,
    document: Mapping[str, Any],
) -> Path:
    _ensure_directory(root / ".index")
    return atomic_write_yaml(
        root,
        _operation_index_path(root, str(document["metadata"]["change_id"])),
        document,
        kind="OperationLocation",
    )


def load_operation_location(
    operations_root: str | Path,
    change_id: str,
) -> dict[str, Any] | None:
    """Load an indexed operation location; legacy flat roots have no index."""
    root = Path(operations_root)
    path = _operation_index_path(root, change_id)
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(f"operation index is unsafe: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise OperationPathError(f"operation index is invalid: {path}")
    validate_document(document, kind="OperationLocation")
    relative = Path(document["spec"]["relative_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise OperationPathError(f"operation index path is unsafe: {relative}")
    return document


def operation_location_exists(
    operations_root: str | Path,
    change_id: str,
) -> bool:
    root = Path(operations_root)
    return (
        _operation_index_path(root, change_id).exists()
        or (root / validate_change_id(change_id)).exists()
    )


def list_live_operation_ids(operations_root: str | Path) -> list[str]:
    """List indexed live IDs and legacy flat IDs without scanning dated data."""
    root = Path(operations_root)
    identifiers: set[str] = set()
    index_root = root / ".index"
    if index_root.is_dir():
        for path in index_root.glob("*.yaml"):
            document = load_operation_location(root, path.stem)
            if document and document["spec"]["state"] == "live":
                identifiers.add(path.stem)
    if root.is_dir():
        for path in root.iterdir():
            if path.name.startswith(".") or path.name in {"live", "archive"}:
                continue
            if path.is_dir() and not path.is_symlink():
                try:
                    identifiers.add(validate_change_id(path.name))
                except ValueError:
                    continue
    return sorted(identifiers)


def remove_missing_live_operation_index(
    operations_root: str | Path,
    change_id: str,
) -> bool:
    """Remove an unchanged live index whose operation directory is missing."""
    root = Path(operations_root)
    document = load_operation_location(root, change_id)
    if document is None or document["spec"]["state"] != "live":
        return False
    operation_root = root / document["spec"]["relative_path"]
    _assert_below_root(root, operation_root)
    if operation_root.exists() or operation_root.is_symlink():
        return False

    # Re-read immediately before deletion so a concurrent archive/index update
    # cannot be removed based on the stale document loaded above.
    current = load_operation_location(root, change_id)
    if current != document:
        return False
    _operation_index_path(root, change_id).unlink()
    return True


def list_archived_operation_ids(operations_root: str | Path) -> list[str]:
    """List indexed archived operation IDs without scanning archive data."""
    root = Path(operations_root)
    identifiers: list[str] = []
    index_root = root / ".index"
    if not index_root.is_dir():
        return identifiers
    for path in sorted(index_root.glob("*.yaml")):
        document = load_operation_location(root, path.stem)
        if document and document["spec"]["state"] == "archived":
            identifiers.append(path.stem)
    return identifiers


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_members(operation_root: Path) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for path in sorted(operation_root.rglob("*")):
        if path.is_symlink():
            raise OperationPathError(f"operation archive rejects symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise OperationPathError(
                f"operation archive rejects special file: {path}"
            )
        relative = path.relative_to(operation_root).as_posix()
        if relative == ".operation.lock":
            continue
        members.append({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": _file_sha256(path),
            "mode": stat.S_IMODE(path.stat().st_mode),
        })
    return members


def _write_operation_archive(
    archive_path: Path,
    operation_root: Path,
    manifest: Mapping[str, Any],
) -> None:
    temporary = archive_path.with_name(f".{archive_path.name}.tmp")
    manifest_bytes = yaml.safe_dump(
        dict(manifest), sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for item in manifest["spec"]["files"]:
                        path = operation_root / item["path"]
                        info = tarfile.TarInfo(
                            f"operation/{item['path']}"
                        )
                        info.size = item["size"]
                        info.mode = item["mode"]
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                    info = tarfile.TarInfo("operation-archive-manifest.yaml")
                    info.size = len(manifest_bytes)
                    info.mode = 0o600
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    archive.addfile(info, io.BytesIO(manifest_bytes))
        os.replace(temporary, archive_path)
        archive_path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def read_operation_archive(
    archive_path: str | Path,
    *,
    expected_sha256: str | None = None,
    verify_files: bool = True,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Verify an operation archive and return its manifest and selected files."""
    path = Path(archive_path)
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(f"operation archive is missing or unsafe: {path}")
    actual_archive_sha256 = "sha256:" + _file_sha256(path)
    if expected_sha256 and actual_archive_sha256 != expected_sha256:
        raise OperationPathError("operation archive checksum mismatch")
    selected: dict[str, bytes] = {}
    observed: dict[str, tuple[int, str]] = {}
    manifest: dict[str, Any] | None = None
    with tarfile.open(path, "r:gz") as archive:
        names: set[str] = set()
        for member in archive.getmembers():
            if member.name in names or not member.isfile():
                raise OperationPathError(
                    f"operation archive contains unsafe member: {member.name}"
                )
            names.add(member.name)
            if member.name == "operation-archive-manifest.yaml":
                stream = archive.extractfile(member)
                if stream is None:
                    raise OperationPathError("operation archive Manifest is unreadable")
                loaded = yaml.safe_load(stream.read())
                if not isinstance(loaded, dict):
                    raise OperationPathError("operation archive Manifest is invalid")
                validate_document(loaded, kind="OperationArchiveManifest")
                manifest = loaded
                continue
            if not member.name.startswith("operation/"):
                raise OperationPathError(
                    f"operation archive member path is unsafe: {member.name}"
                )
            relative = member.name.removeprefix("operation/")
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise OperationPathError(
                    f"operation archive member path is unsafe: {member.name}"
                )
            if verify_files or relative in {"metadata.yaml", "execution.json"}:
                stream = archive.extractfile(member)
                if stream is None:
                    raise OperationPathError(
                        f"operation archive member is unreadable: {member.name}"
                    )
                content = stream.read()
                if verify_files:
                    observed[relative] = (
                        len(content),
                        hashlib.sha256(content).hexdigest(),
                    )
                if relative in {"metadata.yaml", "execution.json"}:
                    selected[relative] = content
    if manifest is None:
        raise OperationPathError("operation archive Manifest is missing")
    if verify_files:
        expected = {
            item["path"]: (item["size"], item["sha256"])
            for item in manifest["spec"]["files"]
        }
        if expected != observed:
            raise OperationPathError("operation archive file Manifest mismatch")
    return manifest, selected


def _operation_archive_age_reference(
    metadata: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> tuple[datetime, str]:
    """Resolve the activity timestamp used by archive age eligibility."""
    last_transition = metadata["spec"]["last_transition"]
    closed_at = datetime.fromisoformat(str(last_transition["at"]))
    if (
        metadata["spec"]["lifecycle"] == "cancelled"
        and str(last_transition.get("reason", "")).startswith("operator_closed:")
    ):
        transitions = list(execution.get("transitions", []))
        if len(transitions) >= 2:
            previous_at = datetime.fromisoformat(str(transitions[-2]["at"]))
            return previous_at, "pre_close_last_activity"
    return closed_at, "terminal_transition"


def archive_operation_workspace(
    operations_root: str | Path,
    change_id: str,
    *,
    older_than_days: int = 14,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Archive one eligible terminal operation without device access."""
    if older_than_days < 0:
        raise ValueError("older_than_days must be zero or greater")
    workspace = open_operation_workspace(operations_root, change_id)
    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    lifecycle = metadata["spec"]["lifecycle"]
    if lifecycle not in ARCHIVABLE_OPERATION_STATES:
        raise OperationStateError(
            f"operation lifecycle is not archivable: {lifecycle}"
        )
    if workspace.lock_path.exists():
        raise OperationLockedError(
            f"operation archive requires no lock: {workspace.lock_path}"
        )
    closed_at = datetime.fromisoformat(
        metadata["spec"]["last_transition"]["at"]
    )
    age_reference_at, age_reference = _operation_archive_age_reference(
        metadata,
        execution,
    )
    evaluated_at = now_in_timezone(workspace.timezone, now=now)
    age_seconds = (evaluated_at - age_reference_at).total_seconds()
    if age_seconds < older_than_days * 86400:
        raise OperationStateError(
            f"operation is newer than {older_than_days} day(s) "
            f"(age reference: {age_reference} at "
            f"{age_reference_at.isoformat(timespec='seconds')})"
        )
    root = Path(operations_root)
    created_date = workspace.created_at
    archive_dir = (
        root
        / "archive"
        / created_date.strftime("%Y")
        / created_date.strftime("%m")
        / created_date.strftime("%d")
    )
    archive_path = archive_dir / f"{workspace.change_id}.tar.gz"
    if archive_path.exists():
        raise OperationPathError(f"operation archive already exists: {archive_path}")
    if dry_run:
        return {
            "change_id": workspace.change_id,
            "status": "eligible",
            "lifecycle": lifecycle,
            "closed_at": closed_at.isoformat(timespec="seconds"),
            "age_reference_at": age_reference_at.isoformat(timespec="seconds"),
            "age_reference": age_reference,
            "archive": archive_path,
        }
    archive_lock = OperationLock(
        workspace,
        "archive",
        now=evaluated_at,
    ).acquire()
    try:
        _ensure_directory(archive_dir)
        members = _archive_members(workspace.operation_root)
        manifest = {
            "api_version": API_VERSION,
            "kind": "OperationArchiveManifest",
            "metadata": {
                "change_id": workspace.change_id,
                "archived_at": evaluated_at.isoformat(timespec="seconds"),
                "tool_version": __version__,
            },
            "spec": {
                "storage_version": 1,
                "source_relative_path": workspace.operation_root.relative_to(
                    root
                ).as_posix(),
                "lifecycle": lifecycle,
                "closed_at": closed_at.isoformat(timespec="seconds"),
                "age_reference_at": age_reference_at.isoformat(
                    timespec="seconds"
                ),
                "age_reference": age_reference,
                "files": members,
            },
        }
        validate_document(manifest, kind="OperationArchiveManifest")
        _write_operation_archive(archive_path, workspace.operation_root, manifest)
        archive_sha256 = "sha256:" + _file_sha256(archive_path)
        read_operation_archive(
            archive_path,
            expected_sha256=archive_sha256,
            verify_files=True,
        )
        checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
        atomic_write_bytes(
            root,
            checksum_path,
            (
                f"{archive_sha256.removeprefix('sha256:')}  "
                f"{archive_path.name}\n"
            ).encode(),
        )
        _write_operation_location(
            root,
            _operation_location_document(
                workspace.change_id,
                created_at=workspace.created_at,
                state="archived",
                layout=(
                    "dated-v1"
                    if workspace.operation_root.is_relative_to(root / "live")
                    else "legacy-flat"
                ),
                relative_path=archive_path.relative_to(root),
                updated_at=evaluated_at,
                archive_sha256=archive_sha256,
            ),
        )
        remove_latest_operation_link_for(workspace)
        shutil.rmtree(workspace.operation_root)
        archive_lock._inode = None
        return {
            "change_id": workspace.change_id,
            "status": "archived",
            "lifecycle": lifecycle,
            "closed_at": closed_at.isoformat(timespec="seconds"),
            "age_reference_at": age_reference_at.isoformat(timespec="seconds"),
            "age_reference": age_reference,
            "archive": archive_path,
            "checksum": checksum_path,
            "archive_sha256": archive_sha256,
            "file_count": len(members),
        }
    except Exception:
        location = load_operation_location(root, workspace.change_id)
        if location is None or location["spec"]["state"] == "live":
            archive_path.unlink(missing_ok=True)
            archive_path.with_suffix(archive_path.suffix + ".sha256").unlink(
                missing_ok=True
            )
        raise
    finally:
        if archive_lock.held and workspace.lock_path.exists():
            archive_lock.release()
        elif archive_lock.held:
            archive_lock._inode = None


def close_operation_workspace(
    operations_root: str | Path,
    change_id: str,
    *,
    reason: str,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Close one non-mutating pre-apply operation as cancelled."""
    normalized_reason = str(reason).strip()
    if not normalized_reason:
        raise OperationStateError("operation close requires a non-empty reason")
    workspace = open_operation_workspace(operations_root, change_id)
    metadata = load_operation_metadata(workspace.operation_root)
    lifecycle = metadata["spec"]["lifecycle"]
    workflow_state = metadata["spec"]["workflow_state"]
    if lifecycle not in {"created", "running", "waiting_for_user"}:
        raise OperationStateError(
            f"operation lifecycle cannot be closed: {lifecycle}"
        )
    if workflow_state not in PRE_APPLY_CLOSABLE_WORKFLOW_STATES:
        raise OperationStateError(
            "operation cannot be closed after device mutation may have started: "
            f"workflow_state={workflow_state}"
        )
    if workspace.lock_path.exists():
        raise OperationLockedError(
            f"operation close requires no existing lock: {workspace.lock_path}"
        )
    closed_at = now_in_timezone(workspace.timezone, now=now)
    if dry_run:
        return {
            "change_id": workspace.change_id,
            "status": "eligible",
            "lifecycle": lifecycle,
            "workflow_state": workflow_state,
            "closed_at": closed_at.isoformat(timespec="seconds"),
        }
    with OperationLock(workspace, "operation-close", now=closed_at) as lock:
        transition_operation(
            workspace,
            "cancelled",
            lock=lock,
            reason=f"operator_closed:{normalized_reason}",
            now=closed_at,
        )
    return {
        "change_id": workspace.change_id,
        "status": "cancelled",
        "previous_lifecycle": lifecycle,
        "workflow_state": workflow_state,
        "closed_at": closed_at.isoformat(timespec="seconds"),
    }


def restore_operation_archive(
    operations_root: str | Path,
    change_id: str,
) -> dict[str, Any]:
    """Verify and restore one archived terminal operation to its live path."""
    root = Path(operations_root)
    location = load_operation_location(root, change_id)
    if location is None or location["spec"]["state"] != "archived":
        raise OperationPathError(f"archived operation does not exist: {change_id}")
    archive_path = root / location["spec"]["relative_path"]
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    if not checksum_path.is_file() or checksum_path.is_symlink():
        raise OperationPathError(
            f"operation archive checksum is missing or unsafe: {checksum_path}"
        )
    expected_archive_sha256 = str(location["spec"].get("archive_sha256", ""))
    if checksum_path.read_text(encoding="utf-8").split() != [
        expected_archive_sha256.removeprefix("sha256:"),
        archive_path.name,
    ]:
        raise OperationPathError("operation archive checksum file is invalid")
    manifest, _selected = read_operation_archive(
        archive_path,
        expected_sha256=expected_archive_sha256,
        verify_files=True,
    )
    source_relative = Path(manifest["spec"]["source_relative_path"])
    if source_relative.is_absolute() or ".." in source_relative.parts:
        raise OperationPathError(
            f"operation restore path is unsafe: {source_relative}"
        )
    target = root / source_relative
    _assert_below_root(root, target)
    if target.exists() or target.is_symlink():
        raise OperationPathError(
            f"operation restore target already exists: {target}"
        )
    _ensure_directory(target.parent)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{change_id}.restore-", dir=target.parent)
    )
    published = False
    try:
        expected = {
            str(item["path"]): item for item in manifest["spec"]["files"]
        }
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for relative, record in expected.items():
                member_name = f"operation/{relative}"
                try:
                    member = archive.getmember(member_name)
                except KeyError as exc:
                    raise OperationPathError(
                        f"operation archive member is missing: {member_name}"
                    ) from exc
                if not member.isfile():
                    raise OperationPathError(
                        f"operation archive member is not regular: {member_name}"
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise OperationPathError(
                        f"operation archive member is unreadable: {member_name}"
                    )
                content = stream.read()
                if (
                    len(content) != record["size"]
                    or hashlib.sha256(content).hexdigest() != record["sha256"]
                ):
                    raise OperationPathError(
                        f"operation archive member hash mismatch: {member_name}"
                    )
                destination = staging / relative
                _assert_below_root(staging, destination)
                _ensure_directory(destination.parent)
                destination.write_bytes(content)
                destination.chmod(int(record["mode"]) & 0o777)
        metadata = load_operation_metadata(staging)
        execution = load_operation_execution(staging)
        if metadata["metadata"]["change_id"] != change_id:
            raise OperationPathError("restored operation metadata ID mismatch")
        if execution["change_id"] != change_id:
            raise OperationPathError("restored operation execution ID mismatch")
        if Path(metadata["spec"]["output_root"]).resolve() != target.resolve():
            raise OperationPathError("restored operation output_root mismatch")
        staging.rename(target)
        published = True
        restored_at = now_in_timezone(metadata["metadata"]["timezone"])
        _write_operation_location(
            root,
            _operation_location_document(
                change_id,
                created_at=datetime.fromisoformat(
                    metadata["metadata"]["created_at"]
                ),
                state="live",
                layout=str(location["spec"]["layout"]),
                relative_path=target.relative_to(root),
                updated_at=restored_at,
            ),
        )
        archive_path.unlink()
        checksum_path.unlink(missing_ok=True)
        return {
            "change_id": change_id,
            "status": "restored",
            "lifecycle": metadata["spec"]["lifecycle"],
            "operation_root": target,
            "file_count": len(expected),
        }
    except Exception:
        if published:
            current = load_operation_location(root, change_id)
            if current == location:
                shutil.rmtree(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_archived_operation_documents(
    operations_root: str | Path,
    change_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load verified metadata/execution directly from an archived operation."""
    root = Path(operations_root)
    location = load_operation_location(root, change_id)
    if location is None or location["spec"]["state"] != "archived":
        raise OperationPathError(f"archived operation does not exist: {change_id}")
    archive_path = root / location["spec"]["relative_path"]
    manifest, selected = read_operation_archive(
        archive_path,
        expected_sha256=location["spec"].get("archive_sha256"),
        verify_files=False,
    )
    try:
        metadata = yaml.safe_load(selected["metadata.yaml"])
        execution = json.loads(selected["execution.json"])
    except (KeyError, ValueError) as exc:
        raise OperationPathError(
            "archived operation metadata/execution is missing or invalid"
        ) from exc
    validate_document(metadata, kind="OperationMetadata", allow_unknown_fields=True)
    validate_document(execution, kind="OperationExecution", allow_unknown_fields=True)
    return metadata, execution, manifest


def archived_operation_retention_candidates(
    operations_root: str | Path,
    *,
    older_than_days: int | None = None,
    keep_latest: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Select verified archived operations for one explicit retention rule."""
    if (older_than_days is None) == (keep_latest is None):
        raise ValueError(
            "exactly one of older_than_days or keep_latest must be specified"
        )
    if older_than_days is not None and older_than_days < 0:
        raise ValueError("older_than_days must be zero or greater")
    if keep_latest is not None and keep_latest < 0:
        raise ValueError("keep_latest must be zero or greater")

    root = Path(operations_root)
    records: list[dict[str, Any]] = []
    for change_id in list_archived_operation_ids(root):
        location = load_operation_location(root, change_id)
        if location is None:
            continue
        archive_path = root / location["spec"]["relative_path"]
        manifest, _selected = read_operation_archive(
            archive_path,
            expected_sha256=location["spec"].get("archive_sha256"),
            verify_files=False,
        )
        archived_at = datetime.fromisoformat(
            manifest["metadata"]["archived_at"]
        )
        if archived_at.tzinfo is None:
            raise OperationPathError(
                f"operation archive timestamp has no timezone: {change_id}"
            )
        records.append({
            "change_id": change_id,
            "archived_at": archived_at,
            "archive": archive_path,
        })

    records.sort(
        key=lambda item: (item["archived_at"], item["change_id"]),
        reverse=True,
    )
    if keep_latest is not None:
        selected = records[keep_latest:]
    else:
        evaluated_at = now or datetime.now().astimezone()
        if evaluated_at.tzinfo is None:
            raise ValueError("now must include a timezone")
        selected = [
            item
            for item in records
            if (evaluated_at - item["archived_at"]).total_seconds()
            >= int(older_than_days) * 86400
        ]
    return sorted(
        selected,
        key=lambda item: (item["archived_at"], item["change_id"]),
    )


def delete_archived_operation(
    operations_root: str | Path,
    change_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Verify and delete one archived operation and its lookup index."""
    root = Path(operations_root)
    location = load_operation_location(root, change_id)
    if location is None or location["spec"]["state"] != "archived":
        raise OperationPathError(f"archived operation does not exist: {change_id}")
    archive_path = root / location["spec"]["relative_path"]
    try:
        archive_path.relative_to(root / "archive")
    except ValueError as exc:
        raise OperationPathError(
            f"operation archive path is outside archive root: {archive_path}"
        ) from exc
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    index_path = _operation_index_path(root, change_id)
    for label, path in (
        ("archive", archive_path),
        ("archive checksum", checksum_path),
        ("operation index", index_path),
    ):
        if not path.is_file() or path.is_symlink():
            raise OperationPathError(f"{label} is missing or unsafe: {path}")
    manifest, _selected = read_operation_archive(
        archive_path,
        expected_sha256=location["spec"].get("archive_sha256"),
        verify_files=False,
    )
    expected_checksum = str(location["spec"].get("archive_sha256", ""))
    checksum_parts = checksum_path.read_text(encoding="utf-8").split()
    if checksum_parts != [
        expected_checksum.removeprefix("sha256:"),
        archive_path.name,
    ]:
        raise OperationPathError(
            f"operation archive checksum file is invalid: {checksum_path}"
        )
    result = {
        "change_id": change_id,
        "status": "eligible" if dry_run else "deleted",
        "archived_at": manifest["metadata"]["archived_at"],
        "archive": archive_path,
    }
    if dry_run:
        return result

    archive_path.unlink()
    checksum_path.unlink()
    index_path.unlink()
    parent = archive_path.parent
    archive_root = root / "archive"
    while parent != archive_root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return result


def load_operation_metadata(operation_root: str | Path) -> dict[str, Any]:
    """Load and validate operation metadata."""
    path = Path(operation_root) / "metadata.yaml"
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(f"operation metadata not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise OperationPathError(f"operation metadata is not a mapping: {path}")
    validate_document(
        document,
        kind="OperationMetadata",
        allow_unknown_fields=True,
    )
    return document


def load_operation_execution(operation_root: str | Path) -> dict[str, Any]:
    """Load and validate common operation execution history."""
    path = Path(operation_root) / "execution.json"
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(f"operation execution not found: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise OperationPathError(f"operation execution is not a mapping: {path}")
    validate_document(
        document,
        kind="OperationExecution",
        allow_unknown_fields=True,
    )
    return document


class OperationLock:
    """Exclusive, non-destructively diagnosed operation lock."""

    def __init__(
        self,
        workspace: OperationWorkspace,
        operation: str,
        *,
        now: datetime | None = None,
    ):
        if not operation:
            raise ValueError("operation name is required")
        self.workspace = workspace
        self.operation = operation
        self.now = now
        self._inode: int | None = None

    @property
    def held(self) -> bool:
        return self._inode is not None

    def acquire(self) -> "OperationLock":
        if self.held:
            raise OperationLockedError("operation lock is already held")
        started_at = now_in_timezone(
            self.workspace.timezone,
            now=self.now,
        )
        document = {
            "schema_version": SCHEMA_VERSION,
            "change_id": self.workspace.change_id,
            "operation": self.operation,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "os_user": getpass.getuser(),
            "started_at": started_at.isoformat(timespec="seconds"),
            "tool_version": __version__,
        }
        validate_document(document, kind="OperationLock")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.workspace.lock_path, flags, 0o600)
        except FileExistsError as exc:
            raise OperationLockedError(
                f"operation is locked: {self.workspace.lock_path}"
            ) from exc
        try:
            content = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            os.write(descriptor, content)
            os.fsync(descriptor)
            self._inode = os.fstat(descriptor).st_ino
        except Exception:
            os.close(descriptor)
            self.workspace.lock_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        return self

    def assert_held(self) -> None:
        if not self.held:
            raise OperationLockedError("mutating operation requires a held lock")
        try:
            current_inode = self.workspace.lock_path.stat().st_ino
        except FileNotFoundError as exc:
            raise OperationLockedError(
                "operation lock disappeared while held"
            ) from exc
        if current_inode != self._inode:
            raise OperationLockedError(
                "operation lock was replaced while held"
            )

    def release(self) -> None:
        if not self.held:
            return
        self.assert_held()
        self.workspace.lock_path.unlink()
        self._inode = None

    def __enter__(self) -> "OperationLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def read_operation_lock(
    operation_root: str | Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read lock data without changing it; return a parse warning separately."""
    path = Path(operation_root) / ".operation.lock"
    if not path.exists():
        return None, None
    if not path.is_file() or path.is_symlink():
        return None, f"lock path is not a regular file: {path}"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("lock document is not a mapping")
        validate_document(document, kind="OperationLock")
    except Exception as exc:
        return None, f"lock is unreadable or invalid: {exc}"
    return document, None


def assess_operation_lock(lock_document: Mapping[str, Any]) -> list[str]:
    """Describe stale/remote lock candidates without removing the lock."""
    findings: list[str] = []
    lock_hostname = str(lock_document.get("hostname", ""))
    current_hostname = socket.gethostname()
    if lock_hostname != current_hostname:
        findings.append(
            f"lock belongs to another host: {lock_hostname}"
        )
        return findings
    pid = int(lock_document["pid"])
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        findings.append(
            f"stale candidate: pid {pid} does not exist on {current_hostname}"
        )
    except PermissionError:
        findings.append(
            f"pid {pid} exists but cannot be inspected by the current user"
        )
    return findings


def transition_operation(
    workspace: OperationWorkspace,
    target_state: str,
    *,
    lock: OperationLock,
    reason: str = "",
    now: datetime | None = None,
    allow_inspection_retry: bool = False,
) -> None:
    """Apply one validated common lifecycle transition."""
    lock.assert_held()
    if target_state not in OPERATION_STATES:
        raise OperationStateError(f"unknown operation state: {target_state}")
    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    current_state = metadata["spec"]["lifecycle"]
    inspection_retry = (
        allow_inspection_retry
        and metadata["spec"].get("purpose") == "inspection"
        and metadata["spec"].get("workflow_state") is None
        and current_state in {"completed", "completed_with_warnings"}
        and target_state == "running"
    )
    if target_state not in OPERATION_TRANSITIONS[current_state] and not inspection_retry:
        raise OperationStateError(
            f"invalid operation transition: {current_state} -> {target_state}"
        )
    changed_at = now_in_timezone(workspace.timezone, now=now)
    transition = {
        "scope": "operation",
        "from": current_state,
        "to": target_state,
        "at": changed_at.isoformat(timespec="seconds"),
        "reason": reason,
    }
    metadata["spec"]["lifecycle"] = target_state
    metadata["spec"]["last_transition"] = transition
    execution["lifecycle"] = target_state
    execution["transitions"].append(transition)
    atomic_write_json(
        workspace.operation_root,
        workspace.execution_path,
        execution,
        kind="OperationExecution",
    )
    atomic_write_yaml(
        workspace.operation_root,
        workspace.metadata_path,
        metadata,
        kind="OperationMetadata",
    )


def transition_phase(
    workspace: OperationWorkspace,
    phase: str,
    target_state: str,
    *,
    lock: OperationLock,
    attempt_id: str | None = None,
    reason: str = "",
    now: datetime | None = None,
    allow_retry: bool = False,
) -> None:
    """Create or transition one phase state under a held operation lock."""
    lock.assert_held()
    if not phase:
        raise OperationStateError("phase name is required")
    if target_state not in PHASE_STATES:
        raise OperationStateError(f"unknown phase state: {target_state}")
    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    current_phase = metadata["spec"]["phases"].get(
        phase,
        {"current_attempt": None, "status": "not_started"},
    )
    current_state = current_phase["status"]
    retry_transition = (
        allow_retry
        and current_state
        in {
            "completed",
            "completed_with_warnings",
            "failed",
            "cancelled",
            "unknown",
        }
        and target_state == "running"
        and attempt_id is not None
        and attempt_id != current_phase["current_attempt"]
    )
    if target_state not in PHASE_TRANSITIONS[current_state] and not retry_transition:
        raise OperationStateError(
            f"invalid phase transition for {phase}: "
            f"{current_state} -> {target_state}"
        )
    changed_at = now_in_timezone(workspace.timezone, now=now)
    transition = {
        "scope": f"phase:{phase}",
        "from": current_state,
        "to": target_state,
        "at": changed_at.isoformat(timespec="seconds"),
        "reason": reason,
    }
    updated_phase = {
        "current_attempt": attempt_id or current_phase["current_attempt"],
        "status": target_state,
    }
    metadata["spec"]["phases"][phase] = updated_phase
    metadata["spec"]["last_transition"] = transition
    execution["phases"][phase] = updated_phase
    execution["transitions"].append(transition)
    atomic_write_json(
        workspace.operation_root,
        workspace.execution_path,
        execution,
        kind="OperationExecution",
    )
    atomic_write_yaml(
        workspace.operation_root,
        workspace.metadata_path,
        metadata,
        kind="OperationMetadata",
    )


def transition_workflow(
    workspace: OperationWorkspace,
    target_state: str,
    *,
    lock: OperationLock,
    reason: str = "",
    now: datetime | None = None,
) -> None:
    """Apply one validated Overlay workflow transition."""
    lock.assert_held()
    metadata = load_operation_metadata(workspace.operation_root)
    execution = load_operation_execution(workspace.operation_root)
    current_state = metadata["spec"]["workflow_state"]
    allowed = WORKFLOW_TRANSITIONS.get(current_state)
    if allowed is None or target_state not in allowed:
        raise OperationStateError(
            f"invalid workflow transition: {current_state} -> {target_state}"
        )
    changed_at = now_in_timezone(workspace.timezone, now=now)
    transition = {
        "scope": "workflow",
        "from": current_state,
        "to": target_state,
        "at": changed_at.isoformat(timespec="seconds"),
        "reason": reason,
    }
    metadata["spec"]["workflow_state"] = target_state
    metadata["spec"]["last_transition"] = transition
    execution["workflow_state"] = target_state
    execution["transitions"].append(transition)
    atomic_write_json(
        workspace.operation_root,
        workspace.execution_path,
        execution,
        kind="OperationExecution",
    )
    atomic_write_yaml(
        workspace.operation_root,
        workspace.metadata_path,
        metadata,
        kind="OperationMetadata",
    )


def record_operation_error(
    workspace: OperationWorkspace,
    error: Mapping[str, Any],
    *,
    lock: OperationLock,
) -> None:
    """Append a structured error without replacing earlier failures."""
    lock.assert_held()
    execution = load_operation_execution(workspace.operation_root)
    execution["errors"].append(dict(error))
    atomic_write_json(
        workspace.operation_root,
        workspace.execution_path,
        execution,
        kind="OperationExecution",
    )


class OperationInterruptGuard:
    """Persist safe interruption state before returning KeyboardInterrupt."""

    def __init__(
        self,
        workspace: OperationWorkspace,
        lock: OperationLock,
        *,
        phase: str | None = None,
    ):
        self.workspace = workspace
        self.lock = lock
        self.phase = phase
        self.device_commands_started = False
        self._previous_handlers: dict[int, Any] = {}

    def mark_device_commands_started(self) -> None:
        self.device_commands_started = True

    def _handle(self, signum: int, _frame: Any) -> None:
        interrupted_at = now_in_timezone(self.workspace.timezone)
        metadata = load_operation_metadata(self.workspace.operation_root)
        lifecycle = metadata["spec"]["lifecycle"]
        workflow_state = metadata["spec"]["workflow_state"]
        if self.device_commands_started:
            if workflow_state == "apply_running":
                transition_workflow(
                    self.workspace,
                    "device_state_unknown",
                    lock=self.lock,
                    reason=f"signal:{signum}",
                    now=interrupted_at,
                )
            elif workflow_state == "rollback_running":
                transition_workflow(
                    self.workspace,
                    "rollback_required",
                    lock=self.lock,
                    reason=f"rollback_state_unknown_signal:{signum}",
                    now=interrupted_at,
                )
            if lifecycle == "running":
                transition_operation(
                    self.workspace,
                    "state_unknown",
                    lock=self.lock,
                    reason=f"signal:{signum}",
                    now=interrupted_at,
                )
            code = "DEVICE_STATE_UNKNOWN"
        else:
            if self.phase:
                phase_data = metadata["spec"]["phases"].get(self.phase)
                if phase_data and phase_data["status"] in {
                    "running",
                    "waiting_for_user",
                }:
                    transition_phase(
                        self.workspace,
                        self.phase,
                        "cancelled",
                        lock=self.lock,
                        reason=f"signal:{signum}",
                        now=interrupted_at,
                    )
            if lifecycle in {"created", "running", "waiting_for_user"}:
                transition_operation(
                    self.workspace,
                    "cancelled",
                    lock=self.lock,
                    reason=f"signal:{signum}",
                    now=interrupted_at,
                )
            code = "CANCELLED_BEFORE_APPLY"
        record_operation_error(
            self.workspace,
            {
                "code": code,
                "signal": signum,
                "phase": self.phase,
                "at": interrupted_at.isoformat(timespec="seconds"),
            },
            lock=self.lock,
        )
        raise KeyboardInterrupt

    def __enter__(self) -> "OperationInterruptGuard":
        self.lock.assert_held()
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        for signum, previous_handler in self._previous_handlers.items():
            signal.signal(signum, previous_handler)
        self._previous_handlers.clear()


def _filesystem_type(path: Path) -> str | None:
    """Best-effort Linux mount type lookup without changing system state."""
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return None
    resolved = path.resolve()
    selected_mount: Path | None = None
    selected_type: str | None = None
    for line in mountinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) < 5 or not right_parts:
            continue
        mount_path = Path(
            left_parts[4].replace("\\040", " ").replace("\\011", "\t")
        )
        try:
            resolved.relative_to(mount_path)
        except ValueError:
            continue
        if selected_mount is None or len(mount_path.parts) > len(selected_mount.parts):
            selected_mount = mount_path
            selected_type = right_parts[0]
    return selected_type


def preflight_operation_workspace(
    workspace: OperationWorkspace,
    *,
    expected_artifact_bytes: int = 0,
    device_count: int = 0,
    for_apply: bool = False,
) -> PreflightResult:
    """Run non-device workspace safety checks."""
    issues: list[PreflightIssue] = []
    if expected_artifact_bytes < 0:
        raise ValueError("expected_artifact_bytes must not be negative")
    if device_count < 0:
        raise ValueError("device_count must not be negative")
    required_bytes = max(expected_artifact_bytes * 2, MIN_FREE_SPACE_BYTES)
    if device_count > 50:
        issues.append(
            PreflightIssue(
                "ERROR",
                "PLAN_CONFLICT",
                f"device count {device_count} exceeds the initial limit of 50",
            )
        )
    for label, getter in (
        ("hostname", socket.gethostname),
        ("os_user", getpass.getuser),
    ):
        try:
            value = getter()
        except Exception as exc:
            issues.append(
                PreflightIssue(
                    "ERROR",
                    "VALIDATION_ERROR",
                    f"{label} could not be resolved: {exc}",
                )
            )
        else:
            if not value:
                issues.append(
                    PreflightIssue(
                        "ERROR",
                        "VALIDATION_ERROR",
                        f"{label} resolved to an empty value",
                    )
                )
    for path, expected_mode in (
        (workspace.operation_root, 0o700),
        (workspace.metadata_path, 0o600),
        (workspace.execution_path, 0o600),
    ):
        if path.is_symlink():
            issues.append(
                PreflightIssue(
                    "ERROR",
                    "VALIDATION_ERROR",
                    f"symlink is not allowed: {path}",
                )
            )
            continue
        if not path.exists():
            issues.append(
                PreflightIssue(
                    "ERROR",
                    "INPUT_NOT_FOUND",
                    f"required operation path is missing: {path}",
                )
            )
            continue
        actual_mode = stat.S_IMODE(path.stat().st_mode)
        if actual_mode != expected_mode:
            issues.append(
                PreflightIssue(
                    "ERROR",
                    "VALIDATION_ERROR",
                    f"unsafe permission {actual_mode:o} on {path}; "
                    f"expected {expected_mode:o}",
                )
            )

    free_bytes = shutil.disk_usage(workspace.operation_root).free
    if free_bytes < required_bytes:
        issues.append(
            PreflightIssue(
                "ERROR" if for_apply else "WARN",
                "PLAN_CONFLICT" if for_apply else "PERFORMANCE_BUDGET_EXCEEDED",
                f"free space {free_bytes} is below the initial requirement "
                f"{required_bytes}",
            )
        )

    filesystem_type = _filesystem_type(workspace.operation_root)
    remote_types = {
        "9p",
        "cifs",
        "fuse.sshfs",
        "nfs",
        "nfs4",
        "smb3",
    }
    if filesystem_type in remote_types:
        issues.append(
            PreflightIssue(
                "ERROR" if for_apply else "WARN",
                "PLAN_CONFLICT",
                f"remote filesystem is not supported: {filesystem_type}",
            )
        )
    elif filesystem_type is None:
        issues.append(
            PreflightIssue(
                "ERROR" if for_apply else "WARN",
                "PLAN_CONFLICT",
                "filesystem type could not be determined",
            )
        )

    issues.sort(key=lambda issue: (issue.severity, issue.code, issue.message))
    return PreflightResult(
        issues=tuple(issues),
        free_bytes=free_bytes,
        required_bytes=required_bytes,
        filesystem_type=filesystem_type,
    )


def save_active_change(
    operations_root: str | Path,
    document: Mapping[str, Any],
) -> Path:
    """Atomically save the active before/after association state."""
    root = Path(operations_root)
    _ensure_directory(root)
    state_dir = root / ".state"
    _ensure_directory(state_dir)
    return atomic_write_yaml(
        root,
        state_dir / "active-change.yaml",
        document,
        kind="ActiveHealthCheckChange",
    )


def load_active_change(operations_root: str | Path) -> dict[str, Any]:
    """Load active change state without searching other operation directories."""
    path = Path(operations_root) / ".state" / "active-change.yaml"
    if not path.is_file() or path.is_symlink():
        raise OperationPathError(f"active change state not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise OperationPathError(f"active change state is not a mapping: {path}")
    validate_document(
        document,
        kind="ActiveHealthCheckChange",
        allow_unknown_fields=True,
    )
    return document


def resolve_active_change_for_after(
    operations_root: str | Path,
    *,
    inventory_sha256: str,
    profile_sha256: str,
    expected_output_root: str | Path | None = None,
) -> OperationWorkspace:
    """Resolve only the explicitly recorded active generated-before state."""
    state = load_active_change(operations_root)
    spec = state["spec"]
    if spec["state"] not in {"before_completed", "after_failed"}:
        raise OperationStateError(
            f"active change is not reusable for after: {spec['state']}"
        )
    if spec["after"]["status"] == "completed":
        raise OperationStateError("active change after phase is already completed")
    if spec["before"]["inventory_sha256"] != inventory_sha256:
        raise OperationStateError("active change inventory hash mismatch")
    if spec["before"]["profile_sha256"] != profile_sha256:
        raise OperationStateError("active change profile hash mismatch")

    workspace = open_operation_workspace(
        operations_root,
        spec["change_id"],
    )
    if workspace.change_id_source != "generated":
        raise OperationStateError(
            "active change must reference an automatically generated change-id"
        )
    recorded_root = Path(spec["output_root"]).resolve()
    if recorded_root != workspace.operation_root.resolve():
        raise OperationStateError("active change output_root mismatch")
    if expected_output_root is not None and (
        Path(expected_output_root).resolve() != recorded_root
    ):
        raise OperationStateError(
            "requested output root does not match active change"
        )

    metadata_path = Path(spec["before"]["metadata_path"])
    snapshot_path = Path(spec["before"]["snapshot_path"])
    if metadata_path.resolve() != workspace.metadata_path.resolve():
        raise OperationStateError("active change metadata path mismatch")
    if (
        not snapshot_path.is_file()
        or snapshot_path.is_symlink()
        or not snapshot_path.resolve().is_relative_to(
            workspace.operation_root.resolve()
        )
    ):
        raise OperationStateError(
            "active change before snapshot is missing or unsafe"
        )
    metadata = load_operation_metadata(workspace.operation_root)
    before_phase = metadata["spec"]["phases"].get("before")
    if before_phase is None or before_phase["status"] not in {
        "completed",
        "completed_with_warnings",
    }:
        raise OperationStateError(
            "active change before phase is not completed"
        )
    after_phase = metadata["spec"]["phases"].get("after")
    if after_phase and after_phase["status"] in {
        "completed",
        "completed_with_warnings",
    }:
        raise OperationStateError(
            "active change after phase is already completed"
        )
    return workspace
