"""Safe, human-readable evidence for rollback restoration verification."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence


def _json_pointer_token(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def rollback_snapshot_is_fresh(
    snapshot: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> bool:
    """Return whether Snapshot creation followed rollback completion."""
    return datetime.fromisoformat(snapshot["created_at"]) >= datetime.fromisoformat(
        execution["metadata"]["completed_at"]
    )


def rollback_verification_passes(
    *,
    snapshot_fresh: bool,
    health_result: str,
    raw_config_equal: bool,
    semantic_config_equal: bool,
) -> bool:
    """Apply the four mandatory rollback restoration gates."""
    return (
        snapshot_fresh
        and health_result == "PASS"
        and raw_config_equal
        and semantic_config_equal
    )


def semantic_difference_paths(
    before: Any,
    rollback: Any,
    path: str = "",
) -> list[str]:
    """Return differing JSON Pointer paths without exposing field values."""
    if isinstance(before, Mapping) and isinstance(rollback, Mapping):
        differences: list[str] = []
        for key in sorted(set(before) | set(rollback), key=str):
            child = f"{path}/{_json_pointer_token(key)}"
            if key not in before or key not in rollback:
                differences.append(child)
            else:
                differences.extend(
                    semantic_difference_paths(
                        before[key],
                        rollback[key],
                        child,
                    )
                )
        return differences
    if isinstance(before, list) and isinstance(rollback, list):
        differences = []
        for index in range(max(len(before), len(rollback))):
            child = f"{path}/{index}"
            if index >= len(before) or index >= len(rollback):
                differences.append(child)
            else:
                differences.extend(
                    semantic_difference_paths(
                        before[index],
                        rollback[index],
                        child,
                    )
                )
        return differences
    return [] if before == rollback else [path or "/"]


def raw_config_diff_counts(
    before: Sequence[str],
    rollback: Sequence[str],
) -> dict[str, int]:
    """Count changed normalized lines without persisting their contents."""
    added = 0
    removed = 0
    matcher = SequenceMatcher(a=before, b=rollback, autojunk=False)
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed += before_end - before_start
        if tag in {"replace", "insert"}:
            added += after_end - after_start
    return {
        "added_line_count": added,
        "removed_line_count": removed,
    }


def build_device_verification(
    before_raw: Sequence[str],
    rollback_raw: Sequence[str],
    before_semantic: Any,
    rollback_semantic: Any,
) -> dict[str, Any]:
    """Build one device's non-secret rollback comparison evidence."""
    semantic_equal = (
        before_semantic is not None and before_semantic == rollback_semantic
    )
    return {
        "raw_config_equal": before_raw == rollback_raw,
        "semantic_config_equal": semantic_equal,
        "raw_config_diff": raw_config_diff_counts(before_raw, rollback_raw),
        "semantic_difference_paths": (
            []
            if semantic_equal
            else semantic_difference_paths(before_semantic, rollback_semantic)
        ),
    }


def _checkbox(passed: bool) -> str:
    return "[x]" if passed else "[ ]"


def _inline(value: Any) -> str:
    return str(value).replace("`", "\\`").replace("\n", " ")


def render_rollback_verification_checklist(
    verification: Mapping[str, Any],
    health_result: Mapping[str, Any],
) -> str:
    """Render integrated rollback gates and per-device evidence as Markdown."""
    metadata = verification["metadata"]
    status = verification["status"]
    lines = [
        "# Rollback Verification Checklist",
        "",
        f"- Verified at: {metadata['verified_at']}",
        f"- Change ID: {metadata['change_id']}",
        f"- Result: {status['result']}",
        "",
        "## Integrated Gates",
        "",
    ]
    gates = (
        ("rollback_snapshot_fresh", status.get("snapshot_fresh", False), None),
        (
            "health_restored",
            status["health_result"] == "PASS",
            status["health_result"],
        ),
        (
            "raw_running_config_restored",
            status["raw_config_equal"],
            None,
        ),
        (
            "overlay_semantic_config_restored",
            status["semantic_config_equal"],
            None,
        ),
    )
    for check_id, passed, explicit_result in gates:
        result = explicit_result or ("PASS" if passed else "FAIL")
        lines.append(f"- {_checkbox(passed)} `{check_id}`: {result}")

    for host, device in sorted(verification["devices"].items()):
        lines.extend(["", f"## Device: `{_inline(host)}`", ""])
        for check_id in ("raw_config_equal", "semantic_config_equal"):
            passed = device[check_id]
            lines.append(
                f"- {_checkbox(passed)} `{check_id}`: "
                f"{'PASS' if passed else 'FAIL'}"
            )
        if not device["raw_config_equal"]:
            raw_diff = device.get("raw_config_diff", {})
            lines.append(
                "- Raw config difference counts: "
                f"added={raw_diff.get('added_line_count', 'UNKNOWN')}, "
                f"removed={raw_diff.get('removed_line_count', 'UNKNOWN')}"
            )
        if not device["semantic_config_equal"]:
            paths = device.get("semantic_difference_paths", [])
            lines.append("- Semantic difference paths:")
            if paths:
                lines.extend(f"  - `{_inline(path)}`" for path in paths)
            else:
                lines.append("  - `UNKNOWN`")

    non_pass = [
        check
        for check in health_result.get("checks", [])
        if check.get("result") not in {"PASS", "NOT_APPLICABLE"}
    ]
    lines.extend(["", "## Non-Pass Health Checks", ""])
    if non_pass:
        for check in non_pass:
            identity = "/".join(
                value
                for value in (
                    str(check.get("host", "global")),
                    str(check.get("check_id", "unknown")),
                )
                if value
            )
            lines.append(
                f"- `{_inline(identity)}`: {check.get('result', 'UNKNOWN')} - "
                f"{_inline(check.get('message', 'No message'))}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Evidence", ""])
    for label, key in (
        ("Before Snapshot", "before_snapshot"),
        ("Rollback Snapshot", "rollback_snapshot"),
        ("Health Result", "health_result"),
        ("Verification JSON", "verification_json"),
    ):
        value = verification["artifacts"].get(key)
        if value:
            lines.append(f"- {label}: `{_inline(value)}`")
    return "\n".join(lines) + "\n"
