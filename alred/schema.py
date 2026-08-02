"""
Machine-readable schema loading, validation, canonicalization, and hashing.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .resources import get_resource_dir


SCHEMA_VERSION = 1
API_VERSION = "alred/v1"

SCHEMA_FILES = {
    "ActiveHealthCheckChange": "active-health-check-change.schema.json",
    "ApprovalRecord": "approval-record.schema.json",
    "CollectionManifest": "collection-manifest.schema.json",
    "ExecutionPlan": "execution-plan.schema.json",
    "HealthCheckProfile": "health-check-profile.schema.json",
    "HealthCheckExecutionContext": "health-check-execution-context.schema.json",
    "HealthResult": "health-result.schema.json",
    "HealthPhaseAttempt": "health-phase-attempt.schema.json",
    "HealthPhaseCurrent": "health-phase-current.schema.json",
    "HealthProfileRevision": "health-profile-revision.schema.json",
    "HealthSnapshot": "health-snapshot.schema.json",
    "ManagedRollbackVerification": "managed-rollback-verification.schema.json",
    "OperationExecution": "operation-execution.schema.json",
    "OperationLock": "operation-lock.schema.json",
    "OperationMetadata": "operation-metadata.schema.json",
    "NxosCapabilityRegistry": "nxos-capability-registry.schema.json",
    "OverlayChangeSet": "overlay-change-set.schema.json",
    "OverlayDeviceGroups": "overlay-device-groups.schema.json",
    "OverlayInputManifest": "overlay-input-manifest.schema.json",
    "OverlayResolvedTargets": "overlay-resolved-targets.schema.json",
    "OverlayConfigExecution": "overlay-config-execution.schema.json",
    "OverlayConflictReport": "overlay-conflict-report.schema.json",
    "OverlayConvergenceResult": "overlay-convergence-result.schema.json",
    "OverlayHealthResult": "overlay-health-result.schema.json",
    "OverlayRenderManifest": "overlay-render-manifest.schema.json",
    "OverlayReferenceState": "overlay-reference-state.schema.json",
    "OverlayPreparationAttempt": "overlay-preparation-attempt.schema.json",
    "OverlayPreparationCurrent": "overlay-preparation-current.schema.json",
    "OverlayState": "overlay-state.schema.json",
    "OverlayVniMapDiff": "overlay-vni-map-diff.schema.json",
    "OverlaySaveExecution": "overlay-save-execution.schema.json",
    "QualificationRecord": "qualification-record.schema.json",
    "QualificationRollbackVerification": "qualification-rollback-verification.schema.json",
    "RollbackVerificationCurrent": "rollback-verification-current.schema.json",
    "QualificationSaveExecution": "qualification-save-execution.schema.json",
    "RollbackPlan": "rollback-plan.schema.json",
    "ResolvedHealthCheckProfiles": "resolved-health-check-profiles.schema.json",
    "SupportBundleManifest": "support-bundle-manifest.schema.json",
    "SupportBundleIndex": "support-bundle-index.schema.json",
    "SupportBundleRedactionPolicy": "support-bundle-redaction-policy.schema.json",
    "TranscriptImportManifest": "transcript-import-manifest.schema.json",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One stable, machine-readable schema validation issue."""

    path: str
    validator: str
    message: str


class DocumentValidationError(ValueError):
    """Raised when a document does not conform to its registered schema."""

    code = "VALIDATION_ERROR"

    def __init__(self, kind: str, issues: list[ValidationIssue]):
        self.kind = kind
        self.issues = issues
        detail = "; ".join(
            f"{issue.path}: {issue.message}" for issue in issues
        )
        super().__init__(f"{kind} validation failed: {detail}")


class UnsupportedSchemaError(ValueError):
    """Raised when no supported schema exists for a document."""

    code = "SCHEMA_UNSUPPORTED"


def _json_pointer(parts: list[Any]) -> str:
    if not parts:
        return "/"
    escaped = [
        str(part).replace("~", "~0").replace("/", "~1")
        for part in parts
    ]
    return "/" + "/".join(escaped)


def get_schema_path(kind: str) -> Path:
    """Return the packaged schema path for a registered kind."""
    filename = SCHEMA_FILES.get(kind)
    if filename is None:
        raise UnsupportedSchemaError(f"unsupported schema kind: {kind}")
    path = get_resource_dir("schemas") / "v1" / filename
    if not path.is_file():
        raise UnsupportedSchemaError(
            f"schema resource is missing for kind {kind}: {path}"
        )
    return path


def load_schema(kind: str) -> dict[str, Any]:
    """Load one registered Draft 2020-12 JSON schema."""
    return json.loads(get_schema_path(kind).read_text(encoding="utf-8"))


def infer_document_kind(document: Mapping[str, Any]) -> str:
    """
    Infer a registered schema kind from a YAML envelope or JSON document.
    """
    api_version = document.get("api_version")
    if api_version is not None:
        if api_version != API_VERSION:
            raise UnsupportedSchemaError(
                f"unsupported api_version: {api_version!r}"
            )
        kind = document.get("kind")
        if not isinstance(kind, str) or not kind:
            raise UnsupportedSchemaError(
                "api_version document requires a non-empty kind"
            )
        return kind

    schema_version = document.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"unsupported schema_version: {schema_version!r}"
        )

    if "approval_id" in document:
        return "ApprovalRecord"
    if "operation" in document and "pid" in document:
        return "OperationLock"
    if "transitions" in document and "lifecycle" in document:
        return "OperationExecution"
    raise UnsupportedSchemaError(
        "cannot infer schema kind from JSON document"
    )


def validate_document(
    document: Mapping[str, Any],
    *,
    kind: str | None = None,
    allow_unknown_fields: bool = False,
) -> None:
    """Validate a document and raise stable, sorted validation issues."""
    resolved_kind = kind or infer_document_kind(document)
    schema = load_schema(resolved_kind)
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    issues: list[ValidationIssue] = []
    for error in validator.iter_errors(document):
        validator_name = str(error.validator or "unknown")
        if validator_name == "additionalProperties":
            if allow_unknown_fields:
                continue
            properties = error.schema.get("properties", {})
            if isinstance(error.instance, dict) and isinstance(properties, dict):
                unknown_fields = sorted(set(error.instance) - set(properties))
                for field in unknown_fields:
                    issues.append(
                        ValidationIssue(
                            path=_json_pointer(
                                [*list(error.absolute_path), field]
                            ),
                            validator=validator_name,
                            message="unknown field",
                        )
                    )
                continue
        issues.append(
            ValidationIssue(
                path=_json_pointer(list(error.absolute_path)),
                validator=validator_name,
                message=error.message,
            )
        )
    issues.sort(key=lambda issue: (issue.path, issue.validator, issue.message))
    if issues:
        raise DocumentValidationError(resolved_kind, issues)


def canonical_json_bytes(document: Any) -> bytes:
    """Return the initial canonical JSON representation."""
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(document: Any) -> str:
    """Hash a canonical document and include the algorithm prefix."""
    return "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def source_sha256(path: str | Path) -> str:
    """Hash source bytes without parsing or normalization."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
