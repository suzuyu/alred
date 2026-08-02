import json
from pathlib import Path

import pytest

from alred.schema import (
    DocumentValidationError,
    SCHEMA_FILES,
    canonical_json_bytes,
    canonical_sha256,
    get_schema_path,
    validate_document,
)


def test_all_registered_schemas_are_packaged_and_draft_2020_12():
    for kind in SCHEMA_FILES:
        schema_path = get_schema_path(kind)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        assert schema_path.is_file()
        assert schema["$schema"].endswith("draft/2020-12/schema")


def test_operation_metadata_rejects_unknown_fields_with_json_pointer():
    document = {
        "api_version": "alred/v1",
        "kind": "OperationMetadata",
        "metadata": {
            "change_id": "CHG-1",
            "change_id_source": "specified",
            "timezone": "Asia/Tokyo",
            "utc_offset": "+09:00",
            "created_at": "2026-08-01T10:00:00+09:00",
            "tool_version": "0.2.0a1",
            "unexpected": True,
        },
        "spec": {
            "output_root": "operations/CHG-1",
            "lifecycle": "created",
            "workflow_state": None,
            "phases": {},
            "last_transition": {
                "scope": "operation",
                "from": None,
                "to": "created",
                "at": "2026-08-01T10:00:00+09:00",
                "reason": "test",
            },
        },
    }

    with pytest.raises(DocumentValidationError) as exc_info:
        validate_document(document)

    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.issues[0].path == "/metadata/unexpected"
    assert exc_info.value.issues[0].validator == "additionalProperties"
    assert exc_info.value.issues[0].message == "unknown field"


def test_saved_output_reader_can_allow_same_major_extension_fields():
    document = {
        "schema_version": 1,
        "change_id": "CHG-1",
        "lifecycle": "created",
        "workflow_state": None,
        "phases": {},
        "transitions": [],
        "errors": [],
        "future_field": {"safe": True},
    }

    validate_document(
        document,
        kind="OperationExecution",
        allow_unknown_fields=True,
    )


def test_canonical_hash_is_independent_of_mapping_order():
    first = {"b": [2, 1], "a": {"x": True}}
    second = {"a": {"x": True}, "b": [2, 1]}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(first).startswith("sha256:")


def test_phase1_boundary_schemas_accept_minimum_documents():
    profile = {
        "api_version": "alred/v1",
        "kind": "HealthCheckProfile",
        "metadata": {"name": "baseline", "version": "1"},
        "spec": {
            "platforms": ["nxos"],
            "checks": [
                {
                    "id": "collection_complete",
                    "evaluator": "collection_complete",
                    "severity": "fail",
                }
            ],
        },
    }
    manifest = {
        "api_version": "alred/v1",
        "kind": "CollectionManifest",
        "metadata": {
            "collection_id": "CHG-1-before-001",
            "change_id": "CHG-1",
            "phase": "before",
            "started_at": "2026-08-01T10:00:00+09:00",
            "completed_at": "2026-08-01T10:01:00+09:00",
            "timezone": "Asia/Tokyo",
        },
        "spec": {"profiles": ["baseline"], "hosts": {}},
    }
    snapshot = {
        "schema_version": 1,
        "change_id": "CHG-1",
        "collection_id": "CHG-1-before-001",
        "phase": "before",
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {},
    }
    result = {
        "schema_version": 1,
        "change_id": "CHG-1",
        "phase": "before",
        "started_at": "2026-08-01T10:00:00+09:00",
        "completed_at": "2026-08-01T10:01:00+09:00",
        "profiles": ["baseline"],
        "result": "PASS",
        "counts": {
            "pass": 0,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }

    validate_document(profile)
    validate_document(manifest)
    validate_document(snapshot, kind="HealthSnapshot")
    validate_document(result, kind="HealthResult")
