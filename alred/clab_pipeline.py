"""Immutable terminal records for the ``clab-set-cmds`` pipeline."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import yaml

from .operation import atomic_write_bytes
from .schema import canonical_sha256, source_sha256


_ERROR_CODE_PREFIX = re.compile(r"^([A-Z][A-Z0-9_]+):")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passphrase|secret|token)(\s*[=:]\s*)(\S+)"
)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _safe_error_message(
    exc: BaseException,
    sensitive_values: Sequence[str],
) -> str:
    message = str(exc)
    for value in sensitive_values:
        if value:
            message = message.replace(value, "[REDACTED]")
    message = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        message,
    )
    return message[:2000]


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, KeyboardInterrupt):
        return "INTERRUPTED"
    explicit = getattr(exc, "code", None)
    if explicit:
        return str(explicit)
    match = _ERROR_CODE_PREFIX.match(str(exc))
    if match:
        return match.group(1)
    if isinstance(exc, FileNotFoundError):
        return "INPUT_NOT_FOUND"
    if isinstance(exc, (ValueError, TypeError)):
        return "VALIDATION_ERROR"
    if isinstance(exc, SystemExit):
        return "CLI_EXIT"
    return "UNEXPECTED_ERROR"


class ClabSetPipelineAttempt:
    """Persist one pipeline attempt without changing the successful pointer on failure."""

    def __init__(
        self,
        *,
        pipeline_root: str | Path,
        requested_source: Mapping[str, Any],
        steps: Sequence[Mapping[str, Any]],
        expected_outputs: Sequence[str | Path],
        tool_version: str,
        started_at: datetime,
    ) -> None:
        self.pipeline_root = Path(pipeline_root)
        self.expected_outputs = [Path(path) for path in expected_outputs]
        source_hash = canonical_sha256(dict(requested_source))[-8:]
        self.attempt_id = (
            f"clab-{started_at.strftime('%Y%m%dT%H%M%S%z-%f')}-{source_hash}"
        )
        self.attempt_dir = (
            self.pipeline_root / "attempts" / self.attempt_id
        )
        self.attempt_dir.mkdir(parents=True, exist_ok=False)
        self.manifest_path = self.attempt_dir / "pipeline-manifest.yaml"
        self._baseline_outputs = self._output_hashes()
        step_records = [
            {
                "name": "source-resolution",
                "command": "source-resolution",
                "status": "NOT_STARTED",
            }
        ]
        step_records.extend(
            {
                "name": str(step.get("name", step.get("command", ""))),
                "command": str(step.get("command", "")),
                "status": "NOT_STARTED",
            }
            for step in steps
        )
        self.document: dict[str, Any] = {
            "api_version": "alred/v1",
            "kind": "ClabSetPipelineManifest",
            "metadata": {
                "attempt_id": self.attempt_id,
                "status": "RUNNING",
                "started_at": _iso(started_at),
                "completed_at": None,
                "tool_version": tool_version,
            },
            "spec": {
                "requested_source": deepcopy(dict(requested_source)),
                "source": deepcopy(dict(requested_source)),
                "steps": step_records,
                "outputs": [],
                "device_access_performed": False,
                "deploy_performed": False,
                "config_push_performed": False,
            },
        }
        self._write()

    def _write(self) -> None:
        atomic_write_bytes(
            self.pipeline_root,
            self.manifest_path,
            yaml.safe_dump(
                self.document,
                sort_keys=False,
                allow_unicode=True,
            ).encode("utf-8"),
        )

    def _step(self, name: str) -> dict[str, Any]:
        for step in self.document["spec"]["steps"]:
            if step["name"] == name:
                return step
        raise ValueError(f"unknown clab-set-cmds pipeline step: {name}")

    def _output_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in self.expected_outputs:
            if path.is_file() and not path.is_symlink():
                hashes[str(path)] = source_sha256(path)
        return hashes

    def _record_outputs(self) -> None:
        current = self._output_hashes()
        outputs: list[dict[str, str]] = []
        for path, digest in sorted(current.items()):
            baseline = self._baseline_outputs.get(path)
            disposition = (
                "created"
                if baseline is None
                else "modified"
                if baseline != digest
                else "unchanged_existing"
            )
            outputs.append(
                {
                    "path": path,
                    "sha256": digest,
                    "disposition": disposition,
                }
            )
        self.document["spec"]["outputs"] = outputs

    def start_step(
        self,
        name: str,
        *,
        started_at: datetime,
        device_access: bool = False,
    ) -> None:
        step = self._step(name)
        if step["status"] != "NOT_STARTED":
            raise ValueError(f"pipeline step cannot start from {step['status']}: {name}")
        step["status"] = "RUNNING"
        step["started_at"] = _iso(started_at)
        if device_access:
            # A failed collect may already have accessed some devices. Record this
            # conservatively as soon as the collection handler starts.
            self.document["spec"]["device_access_performed"] = True
        self._write()

    def complete_step(
        self,
        name: str,
        *,
        completed_at: datetime,
    ) -> None:
        step = self._step(name)
        if step["status"] != "RUNNING":
            raise ValueError(
                f"pipeline step cannot complete from {step['status']}: {name}"
            )
        step["status"] = "COMPLETED"
        step["completed_at"] = _iso(completed_at)
        self._write()

    def skip_step(
        self,
        name: str,
        *,
        reason: str,
        completed_at: datetime,
    ) -> None:
        step = self._step(name)
        if step["status"] != "NOT_STARTED":
            raise ValueError(f"pipeline step cannot skip from {step['status']}: {name}")
        step["status"] = "SKIPPED"
        step["completed_at"] = _iso(completed_at)
        step["reason"] = reason
        self._write()

    def set_resolved_source(self, source: Mapping[str, Any]) -> None:
        self.document["spec"]["source"] = deepcopy(dict(source))
        self._write()

    def finish_success(self, *, completed_at: datetime) -> None:
        if any(
            step["status"] in {"NOT_STARTED", "RUNNING", "FAILED", "INTERRUPTED"}
            for step in self.document["spec"]["steps"]
        ):
            raise ValueError("pipeline cannot succeed with unfinished or failed steps")
        self._record_outputs()
        self.document["metadata"]["status"] = "SUCCESS"
        self.document["metadata"]["completed_at"] = _iso(completed_at)
        self._write()
        atomic_write_bytes(
            self.pipeline_root,
            self.pipeline_root / "current.json",
            (
                json.dumps(
                    {
                        "attempt_id": self.attempt_id,
                        "status": "SUCCESS",
                        "manifest": str(self.manifest_path),
                        "manifest_sha256": source_sha256(self.manifest_path),
                        "completed_at": _iso(completed_at),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )

    def finish_failure(
        self,
        exc: BaseException,
        *,
        completed_at: datetime,
        sensitive_values: Sequence[str] = (),
    ) -> None:
        interrupted = isinstance(exc, KeyboardInterrupt)
        terminal_status = "INTERRUPTED" if interrupted else "FAILED"
        error = {
            "code": _error_code(exc),
            "type": type(exc).__name__,
            "message": _safe_error_message(exc, sensitive_values),
        }
        running_step: dict[str, Any] | None = None
        for step in self.document["spec"]["steps"]:
            if step["status"] == "RUNNING":
                running_step = step
                break
        if running_step is not None:
            running_step["status"] = terminal_status
            running_step["completed_at"] = _iso(completed_at)
            running_step["error"] = deepcopy(error)
        self._record_outputs()
        self.document["metadata"]["status"] = terminal_status
        self.document["metadata"]["completed_at"] = _iso(completed_at)
        self.document["spec"]["error"] = error
        self._write()
