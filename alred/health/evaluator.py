"""Initial common and NX-OS Overlay health evaluators."""

from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
import ipaddress
import re
from typing import Any, Callable, Mapping

from .roles import overlay_profile_scope

from ..logging_check import classify_logging_record
from ..schema import SCHEMA_VERSION, validate_document


class HealthEvaluationError(ValueError):
    """Raised when Snapshot and resolved profile inputs are incompatible."""

    code = "VALIDATION_ERROR"


RESULT_ORDER = {
    "NOT_APPLICABLE": 0,
    "PASS": 1,
    "WARN": 2,
    "UNKNOWN": 3,
    "FAIL": 4,
    "PLAN_ERROR": 5,
}


def assess_cpu_samples(
    samples: list[float],
    *,
    threshold: float,
    required_consecutive: int,
) -> dict[str, Any]:
    """Assess threshold inclusively and track the longest consecutive run."""
    if required_consecutive < 1:
        raise ValueError("required_consecutive must be at least 1")
    longest = 0
    current = 0
    for sample in samples:
        if float(sample) >= threshold:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return {
        "samples": [float(sample) for sample in samples],
        "threshold": float(threshold),
        "threshold_exceeded": longest > 0,
        "longest_consecutive": longest,
        "sustained": longest >= required_consecutive,
        "required_consecutive": required_consecutive,
    }


def _source_evidence(
    snapshot: Mapping[str, Any],
    host: str,
    identifier: str,
) -> list[dict[str, Any]]:
    source = snapshot["hosts"][host]["sources"].get(identifier)
    if not source:
        return []
    return [
        {
            "collection_id": snapshot["collection_id"],
            "command": source.get("command"),
            "file": source.get("file"),
            "sha256": source.get("sha256"),
            "parse_status": source.get("parse_status"),
        }
    ]


def _check(
    *,
    check_id: str,
    profile: str,
    host: str,
    result: str,
    classification: str,
    message: str,
    evidence: list[dict[str, Any]],
    resource: str | None = None,
    before: Any = None,
    after: Any = None,
    display_severity: str | None = None,
) -> dict[str, Any]:
    document = {
        "check_id": check_id,
        "profile": profile,
        "host": host,
        "resource": resource,
        "result": result,
        "classification": classification,
        "message": message,
        "evidence": evidence,
    }
    if before is not None:
        document["before"] = before
    if after is not None:
        document["after"] = after
    if display_severity is not None:
        document["display_severity"] = display_severity
    return document


def _unknown(
    check_definition: Mapping[str, Any],
    host: str,
    message: str,
    evidence: list[dict[str, Any]],
    *,
    resource: str | None = None,
) -> dict[str, Any]:
    return _check(
        check_id=check_definition["id"],
        profile=check_definition["profile"],
        host=host,
        result="UNKNOWN",
        classification="collection_error",
        message=message,
        evidence=evidence,
        resource=resource,
    )


def _effective(resolved_profiles: Mapping[str, Any]) -> Mapping[str, Any]:
    return resolved_profiles["spec"]["resolved"]["effective"]


def _logging_settings(effective: Mapping[str, Any]) -> dict[str, Any]:
    raw = effective["spec"].get("thresholds", {}).get("logging", {})
    severity = int(raw.get("severity_threshold", 4))
    lookback = int(raw.get("lookback_seconds", 604800))
    if not 0 <= severity <= 7:
        raise HealthEvaluationError(
            "logging severity_threshold must be between 0 and 7"
        )
    if lookback < 0:
        raise HealthEvaluationError("logging lookback_seconds must be zero or greater")

    configured_range = raw.get("time_range")
    if configured_range is None:
        time_range = {
            "mode": "lookback-seconds",
            "lookback_seconds": lookback,
        }
    else:
        time_range = dict(configured_range)
        mode = time_range.get("mode")
        if mode == "days":
            if int(time_range.get("days", 0)) < 1:
                raise HealthEvaluationError(
                    "logging time_range.days must be at least 1"
                )
            time_range["days"] = int(time_range["days"])
        elif mode == "start-time":
            try:
                start_time = datetime.fromisoformat(str(time_range["start_time"]))
            except (KeyError, ValueError) as exc:
                raise HealthEvaluationError(
                    "logging time_range.start_time must be ISO 8601"
                ) from exc
            if start_time.tzinfo is None:
                raise HealthEvaluationError(
                    "logging time_range.start_time must include a timezone"
                )
            time_range["start_time"] = start_time.isoformat(timespec="seconds")
        elif mode != "all":
            raise HealthEvaluationError(f"unsupported logging time_range mode: {mode}")
    return {
        "severity_threshold": severity,
        "lookback_seconds": lookback,
        "time_range": time_range,
        "include_patterns": list(raw.get("include_patterns", [])),
        "exclude_patterns": list(raw.get("exclude_patterns", [])),
    }


def _logging_lower_bound(
    settings: Mapping[str, Any],
    upper_bound: datetime,
) -> datetime | None:
    time_range = settings["time_range"]
    mode = time_range["mode"]
    if mode == "all":
        return None
    if mode == "days":
        lower_bound = upper_bound - timedelta(days=time_range["days"])
    elif mode == "start-time":
        lower_bound = datetime.fromisoformat(time_range["start_time"])
    else:
        lower_bound = upper_bound - timedelta(seconds=time_range["lookback_seconds"])
    if lower_bound > upper_bound:
        raise HealthEvaluationError(
            "logging start time must not be later than the Snapshot time"
        )
    return lower_bound


def _matched_logging_records(
    logging: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    lower_bound: datetime | None,
    upper_bound: datetime,
    lower_exclusive: bool = False,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in logging.get("records", []):
        timestamp_text = record.get("timestamp")
        if timestamp_text is None:
            continue
        timestamp = datetime.fromisoformat(timestamp_text)
        if lower_bound is None:
            in_range = timestamp <= upper_bound
        elif lower_exclusive:
            in_range = lower_bound < timestamp <= upper_bound
        else:
            in_range = lower_bound <= timestamp <= upper_bound
        if not in_range:
            continue
        text = str(record.get("text", ""))
        excluded, matched_by_severity, matched_patterns = classify_logging_record(
            text=text,
            record_severity=record.get("severity"),
            severity_threshold=settings["severity_threshold"],
            include_patterns=settings["include_patterns"],
            exclude_patterns=settings["exclude_patterns"],
        )
        if excluded:
            continue
        reasons: list[str] = []
        if matched_by_severity:
            reasons.append(f"severity<={settings['severity_threshold']}")
        reasons.extend(f"include-pattern:{pattern}" for pattern in matched_patterns)
        if reasons:
            matched = dict(record)
            matched["match_reasons"] = reasons
            matches.append(matched)
    return matches


def _logging_or_unknown(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    evidence = _source_evidence(snapshot, host, "show_logging")
    source = snapshot["hosts"][host]["sources"].get("show_logging")
    logging = snapshot["hosts"][host]["common"].get("logging")
    if source is None or source.get("parse_status") != "parsed" or logging is None:
        return None, _unknown(
            definition,
            host,
            "show logging data is unavailable",
            evidence,
            resource="system/logging",
        )
    warnings = logging.get("parse_warnings", [])
    if warnings:
        return None, _unknown(
            definition,
            host,
            "show logging contains unparseable records: " + "; ".join(warnings),
            evidence,
            resource="system/logging",
        )
    return logging, None


def _evaluate_logging(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    logging, unknown = _logging_or_unknown(snapshot, host, definition)
    if unknown is not None:
        return unknown
    assert logging is not None
    settings = _logging_settings(effective)
    upper_bound = datetime.fromisoformat(snapshot["created_at"])
    lower_bound = _logging_lower_bound(settings, upper_bound)
    matches = _matched_logging_records(
        logging,
        settings,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )
    matched_count = len(matches)
    result = "WARN" if matches else "PASS"
    classification = (
        "pre_existing"
        if matches and snapshot["phase"] == "before"
        else "unexpected_change"
        if matches
        else "normal"
    )
    message = (
        f"{matched_count} abnormal log record(s) were observed in the selected time range"
        if matches
        else "No abnormal log records were observed in the selected time range"
    )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=message,
        evidence=_source_evidence(snapshot, host, "show_logging"),
        resource="system/logging",
        after={
            "total_records": len(logging.get("records", [])),
            "matched_records": matched_count,
            "severity_threshold": settings["severity_threshold"],
            "lookback_seconds": settings["lookback_seconds"],
            "time_range": settings["time_range"],
            "window_start": lower_bound.isoformat() if lower_bound else None,
            "window_end": upper_bound.isoformat(),
            "matches": matches,
        },
    )


def _required_commands(
    effective: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        command
        for command in effective["spec"]
        .get("collectors", {})
        .get("nxos", {})
        .get("commands", [])
        if command["required"]
    ]


def _evaluate_collection(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    sources = snapshot["hosts"][host]["sources"]
    missing: list[str] = []
    for command in _required_commands(effective):
        source = sources.get(command["id"])
        if source is None or source.get("parse_status") != "parsed":
            missing.append(command["id"])
    if missing:
        return _unknown(
            definition,
            host,
            "Required command data is unavailable: " + ", ".join(missing),
            [],
            resource="collection",
        )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="PASS",
        classification="normal",
        message="All required command outputs were parsed",
        evidence=[],
        resource="collection",
    )


def _link_endpoint_key(item: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    endpoints = item.get("link_endpoints", [])
    if not isinstance(endpoints, list):
        return ()
    normalized = []
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            return ()
        normalized.append(
            (
                str(endpoint.get("node", "")),
                str(endpoint.get("interface", "")),
            )
        )
    return tuple(sorted(normalized))


def _record_endpoint_key(item: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                (str(item.get("src_node", "")), str(item.get("src_if", ""))),
                (str(item.get("dst_node", "")), str(item.get("dst_if", ""))),
            )
        )
    )


def _link_item_is_in_health_scope(
    item: Mapping[str, Any],
    eligible_hosts: set[str] | None,
) -> bool:
    if eligible_hosts is None:
        return True
    endpoints = item.get("link_endpoints", [])
    if not isinstance(endpoints, list):
        return False
    nodes = {
        str(endpoint.get("node", ""))
        for endpoint in endpoints
        if isinstance(endpoint, Mapping) and endpoint.get("node")
    }
    return bool(nodes) and nodes.issubset(eligible_hosts)


def _lldp_link_context(
    snapshot: Mapping[str, Any],
    host: str,
) -> tuple[
    list[dict[str, Any]],
    Mapping[str, Any] | None,
    str,
    list[str],
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
]:
    evidence = [
        *_source_evidence(snapshot, host, "lldp_neighbors_detail"),
        *_source_evidence(snapshot, host, "running_config"),
    ]
    link_evidence = snapshot.get("link_evidence")
    if not isinstance(link_evidence, Mapping):
        return evidence, None, host, [], [], []
    source_status = link_evidence.get("source_status", {}).get(host, {})
    unavailable = [
        f"{identifier}: {state.get('message', state.get('status', 'unknown'))}"
        for identifier in ("lldp_neighbors_detail", "running_config")
        if (state := source_status.get(identifier, {})).get("status") != "parsed"
    ]
    normalized_host = str(link_evidence.get("host_map", {}).get(host, host))
    spec = link_evidence.get("diagnostics", {}).get("spec", {})
    diagnostics = [
        item
        for item in spec.get("diagnostics", [])
        if normalized_host in item.get("affected_devices", [])
    ]
    claims = [
        item
        for item in spec.get("unevaluated_claims", [])
        if normalized_host in item.get("affected_devices", [])
    ]
    return (
        evidence,
        link_evidence,
        normalized_host,
        unavailable,
        diagnostics,
        claims,
    )


def _evaluate_lldp_evidence_completeness(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    (
        evidence,
        link_evidence,
        normalized_host,
        unavailable,
        diagnostics,
        claims,
    ) = _lldp_link_context(snapshot, host)
    if link_evidence is None:
        return _unknown(
            definition,
            host,
            "Canonical link evidence is unavailable",
            evidence,
            resource=f"links/{host}",
        )
    if unavailable:
        return _unknown(
            definition,
            host,
            "Link source data is unavailable: " + "; ".join(unavailable),
            evidence,
            resource=f"links/{normalized_host}",
        )
    scope = link_evidence.get("health_scope")
    eligible_hosts = (
        {str(item) for item in scope.get("eligible_hosts", [])}
        if isinstance(scope, Mapping)
        else None
    )
    diagnostics = [
        item
        for item in diagnostics
        if _link_item_is_in_health_scope(item, eligible_hosts)
    ]
    claims = [
        item
        for item in claims
        if _link_item_is_in_health_scope(item, eligible_hosts)
    ]
    unknown_diagnostics = [
        item
        for item in diagnostics
        if item.get("classification") == "unknown"
        or item.get("code") == "MULTIPLE_REMOTE_ENDPOINTS"
    ]
    incomplete_claims = [
        item for item in claims if item.get("reason") != "peer-not-in-inventory"
    ]
    one_way_lldp = [
        item for item in diagnostics if item.get("code") == "ONE_WAY_LLDP"
    ]
    details = {
        "normalized_host": normalized_host,
        "diagnostic_ids": [
            item["diagnostic_id"]
            for item in (*unknown_diagnostics, *one_way_lldp)
        ],
        "diagnostics": [*unknown_diagnostics, *one_way_lldp],
        "unevaluated_claims": incomplete_claims,
    }
    if unknown_diagnostics or incomplete_claims:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="UNKNOWN",
            classification="collection_error",
            message="LLDP/description evidence could not be evaluated completely",
            evidence=evidence,
            resource=f"links/{normalized_host}",
            after=details,
        )
    if one_way_lldp:
        result = "FAIL" if definition.get("severity") == "fail" else "WARN"
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result=result,
            classification=(
                "pre_existing"
                if snapshot["phase"] == "before"
                else "unexpected_change"
            ),
            message=f"{len(one_way_lldp)} one-way LLDP diagnostic(s) were observed",
            evidence=evidence,
            resource=f"links/{normalized_host}",
            after=details,
        )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="PASS",
        classification="normal",
        message="LLDP and description evidence is complete",
        evidence=evidence,
        resource=f"links/{normalized_host}",
        after=details,
    )


def _evaluate_lldp_description_consistency(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    (
        evidence,
        link_evidence,
        normalized_host,
        _unavailable,
        diagnostics,
        _claims,
    ) = _lldp_link_context(snapshot, host)
    scope = (
        link_evidence.get("health_scope")
        if isinstance(link_evidence, Mapping)
        else None
    )
    eligible_hosts = (
        {str(item) for item in scope.get("eligible_hosts", [])}
        if isinstance(scope, Mapping)
        else None
    )
    eligible_links = [] if link_evidence is None else [
        item
        for item in link_evidence.get("confirmed_links", [])
        if item.get("evidence") == "bidirectional-lldp"
        and normalized_host
        in {str(item.get("src_node", "")), str(item.get("dst_node", ""))}
        and (
            eligible_hosts is None
            or {
                str(item.get("src_node", "")),
                str(item.get("dst_node", "")),
            }.issubset(eligible_hosts)
        )
    ]
    eligible_keys = {_record_endpoint_key(item) for item in eligible_links}
    mismatches = [
        item
        for item in diagnostics
        if item.get("code")
        in {"LLDP_DESC_DEVICE_CONFLICT", "LLDP_DESC_INTERFACE_CONFLICT"}
        and _link_endpoint_key(item) in eligible_keys
    ]
    details = {
        "normalized_host": normalized_host,
        "eligible_link_count": len(eligible_links),
        "diagnostic_ids": [item["diagnostic_id"] for item in mismatches],
        "diagnostics": mismatches,
    }
    if not eligible_links:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="No bidirectional LLDP link is eligible for description evaluation",
            evidence=evidence,
            resource=f"links/{normalized_host}",
            after=details,
        )
    if mismatches:
        result = "FAIL" if definition.get("severity") == "fail" else "WARN"
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result=result,
            classification=(
                "pre_existing"
                if snapshot["phase"] == "before"
                else "unexpected_change"
            ),
            message=(
                f"{len(mismatches)} LLDP/description inconsistency "
                "diagnostic(s) were observed"
            ),
            evidence=evidence,
            resource=f"links/{normalized_host}",
            after=details,
        )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="PASS",
        classification="normal",
        message="LLDP and interface description evidence is consistent",
        evidence=evidence,
        resource=f"links/{normalized_host}",
        after=details,
    )


def _evaluate_system(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    system = snapshot["hosts"][host]["common"].get("system")
    evidence = _source_evidence(snapshot, host, "show_version")
    if not system:
        return _unknown(
            definition,
            host,
            "NX-OS system identity is unavailable",
            evidence,
            resource="system",
        )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="PASS",
        classification="normal",
        message=(f"NX-OS {system['version']} model {system['model']} was identified"),
        evidence=evidence,
        resource="system",
        after=system,
    )


def _evaluate_hostname_identity(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    system = snapshot["hosts"][host]["common"].get("system")
    evidence = _source_evidence(snapshot, host, "show_version")
    reported = str((system or {}).get("reported_hostname") or "").strip()
    if not reported:
        return _unknown(
            definition,
            host,
            "NX-OS reported hostname is unavailable",
            evidence,
            resource="system/hostname",
        )
    result = "PASS" if reported == host else "FAIL"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            f"Reported hostname matches inventory hostname: {host}"
            if result == "PASS"
            else f"Reported hostname {reported!r} does not match inventory hostname {host!r}"
        ),
        evidence=evidence,
        resource="system/hostname",
        after={"expected_hostname": host, "reported_hostname": reported},
    )


def _evaluate_cpu(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    cpu = snapshot["hosts"][host]["common"].get("cpu")
    evidence = _source_evidence(snapshot, host, "processes_cpu")
    if not cpu:
        return _unknown(
            definition,
            host,
            "CPU utilization is unavailable",
            evidence,
            resource="system/cpu",
        )
    policy = effective["spec"].get("thresholds", {}).get("cpu", {})
    metric = policy.get("metric", "one_minute_percent")
    threshold = float(policy.get("warn_percent", 80))
    value = cpu.get(metric)
    if value is None:
        metric = "five_seconds_percent"
        value = cpu.get(metric)
    if value is None:
        return _unknown(
            definition,
            host,
            "Configured CPU metric is unavailable",
            evidence,
            resource="system/cpu",
        )
    required_consecutive = int(policy.get("required_consecutive_samples", 3))
    raw_samples = cpu.get("samples", [value])
    sample_values = [
        float(sample.get(metric, value) if isinstance(sample, Mapping) else sample)
        for sample in raw_samples
    ]
    assessment = assess_cpu_samples(
        sample_values,
        threshold=threshold,
        required_consecutive=required_consecutive,
    )
    result = "WARN" if assessment["threshold_exceeded"] else "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="pre_existing" if result == "WARN" else "normal",
        message=(f"CPU {metric} is {value}% (warning threshold: {threshold:g}%)"),
        evidence=evidence,
        resource="system/cpu",
        after={
            "metric": metric,
            "value": value,
            **assessment,
        },
    )


def _evaluate_memory(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    memory = snapshot["hosts"][host]["common"].get("resources", {}).get("memory")
    evidence = _source_evidence(snapshot, host, "system_resources")
    if not memory or memory.get("used_percent") is None:
        return _unknown(
            definition,
            host,
            "Memory utilization is unavailable",
            evidence,
            resource="system/memory",
        )
    policy = effective["spec"].get("thresholds", {}).get("memory", {})
    warn = float(policy.get("warn_percent", 85))
    fail = float(policy.get("fail_percent", 95))
    value = float(memory["used_percent"])
    if value >= fail:
        result = "FAIL"
    elif value >= warn:
        result = "WARN"
    else:
        result = "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="pre_existing" if result != "PASS" else "normal",
        message=(
            f"Memory utilization is {value:g}% (warn: {warn:g}%, fail: {fail:g}%)"
        ),
        evidence=evidence,
        resource="system/memory",
        after={"value": value, "warn": warn, "fail": fail},
    )


def _evaluate_environment(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    environment = snapshot["hosts"][host]["common"].get("environment")
    evidence = _source_evidence(snapshot, host, "environment")
    if environment is None:
        return _unknown(
            definition,
            host,
            "Environment state is unavailable",
            evidence,
            resource="system/environment",
        )
    if not environment.get("applicable", True):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="Hardware environment sensors are unavailable on this platform",
            evidence=evidence,
            resource="system/environment",
        )
    result = "PASS" if environment.get("healthy") else "FAIL"
    alarm_lines = [
        str(line).strip()
        for line in environment.get("alarms", [])
        if str(line).strip()
    ]
    failure_message = "Environment alarm was detected"
    if alarm_lines:
        failure_message += ": " + "; ".join(alarm_lines)
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            "Environment sensors are healthy"
            if result == "PASS"
            else failure_message
        ),
        evidence=evidence,
        resource="system/environment",
        after=environment,
    )


def _optional_uncollected(
    snapshot: Mapping[str, Any], host: str, identifiers: tuple[str, ...]
) -> bool:
    sources = snapshot["hosts"][host].get("sources", {})
    return not any(identifier in sources for identifier in identifiers)


def _evaluate_clock(snapshot, host, definition, effective):
    value = snapshot["hosts"][host]["common"].get("clock")
    evidence = _source_evidence(snapshot, host, "clock")
    clock_source = snapshot["hosts"][host].get("sources", {}).get("clock", {})
    if clock_source.get("source") == "external_transcript":
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="Clock offset is not evaluated for nxos-transcript input",
            evidence=evidence,
            resource="system/clock",
            after=value,
        )
    if value is None:
        if _optional_uncollected(snapshot, host, ("clock",)):
            return _unknown(definition, host, "Device clock was not collected", [], resource="system/clock")
        return _unknown(definition, host, "Device clock is unavailable", evidence, resource="system/clock")
    try:
        device_time = datetime.fromisoformat(value["timestamp"])
        collected_at = (
            snapshot["hosts"][host].get("sources", {}).get("clock", {}).get("collected_at")
            or snapshot["created_at"]
        )
        collected_time = datetime.fromisoformat(collected_at)
        offset = abs((device_time - collected_time).total_seconds())
    except (KeyError, ValueError, TypeError):
        return _unknown(definition, host, "Device clock timestamp is invalid", evidence, resource="system/clock")
    policy = effective["spec"].get("thresholds", {}).get("clock", {})
    warn = float(policy.get("warn_offset_seconds", 60))
    fail = float(policy.get("fail_offset_seconds", 300))
    result = "FAIL" if offset > fail else "WARN" if offset > warn else "PASS"
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="pre_existing" if result != "PASS" else "normal", message=f"Device clock offset is {offset:g} seconds (warn: {warn:g}, fail: {fail:g})", evidence=evidence, resource="system/clock", after={**value, "offset_seconds": offset})


def _evaluate_ntp(snapshot, host, definition, effective):
    value = snapshot["hosts"][host]["common"].get("ntp")
    evidence = [
        *_source_evidence(snapshot, host, "ntp_status"),
        *_source_evidence(snapshot, host, "ntp_peers"),
        *_source_evidence(snapshot, host, "ntp_peer_status"),
        *_source_evidence(snapshot, host, "clock"),
    ]
    if value is None:
        if _optional_uncollected(snapshot, host, ("ntp_status", "ntp_peers")):
            return _unknown(definition, host, "NTP was not collected", [], resource="system/ntp")
        return _unknown(definition, host, "NTP state is unavailable", evidence, resource="system/ntp")
    sources = snapshot["hosts"][host].get("sources", {})
    failed_sources = [
        identifier
        for identifier in ("ntp_status", "ntp_peers")
        if identifier in sources and sources[identifier].get("parse_status") != "parsed"
    ]
    if failed_sources:
        return _unknown(
            definition,
            host,
            "NTP evidence is unavailable: " + ", ".join(failed_sources),
            evidence,
            resource="system/ntp",
        )
    required = bool(effective["spec"].get("thresholds", {}).get("ntp", {}).get("required", False))
    peers = value.get("peers", {})
    peer_status = value.get("peer_status", {})
    detailed_peers = (
        peer_status.get("peers", {})
        if peer_status.get("applicable", True)
        else {}
    )
    configured = value.get("configured")
    if configured is None:
        configured = bool(peers or detailed_peers)
    normalized = {**value, "configured": configured}
    clock_source = str(
        snapshot["hosts"][host]["common"].get("clock", {}).get(
            "time_source", ""
        )
    ).strip()
    if clock_source:
        normalized["clock_time_source"] = clock_source
    if not configured:
        result = "FAIL" if required else "NOT_APPLICABLE"
        message = "NTP is not configured"
    elif value.get("synchronized"):
        selected = sorted(
            address
            for address, peer in (detailed_peers or peers).items()
            if peer.get("selected")
        )
        unhealthy_selected = sorted(
            address
            for address in selected
            if detailed_peers
            and (
                int(detailed_peers[address].get("reach", 0)) < 1
                or not 1 <= int(detailed_peers[address].get("stratum", 16)) <= 15
            )
        )
        result = "PASS" if selected and not unhealthy_selected else "WARN"
        message = "NTP is synchronized"
        if selected:
            message += f" to {', '.join(selected)}"
        if unhealthy_selected:
            message += "; unhealthy selected peer: " + ", ".join(
                unhealthy_selected
            )
        elif not selected:
            message += "; no selected peer was observed"
    else:
        result = "FAIL" if required else "WARN"
        message = "NTP is configured but unsynchronized"
        details = []
        if value.get("operational_state"):
            details.append(f"operational state: {value['operational_state']}")
        if peers and not any(peer.get("selected") for peer in peers.values()):
            details.append("no selected peer")
        if detailed_peers:
            unhealthy = sorted(
                address
                for address, peer in detailed_peers.items()
                if int(peer.get("reach", 0)) < 1
                or not 1 <= int(peer.get("stratum", 16)) <= 15
            )
            if unhealthy:
                details.append("unhealthy peer-status: " + ", ".join(unhealthy))
        if clock_source:
            details.append(f"clock time source: {clock_source}")
        if details:
            message += " (" + "; ".join(details) + ")"
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="pre_existing" if result in {"WARN", "FAIL"} else "normal", message=message, evidence=evidence, resource="system/ntp", after=normalized)


def _evaluate_interfaces(snapshot, host, definition, _effective):
    value = snapshot["hosts"][host]["common"].get("interfaces")
    evidence = [
        *_source_evidence(snapshot, host, "interface_status"),
        *_source_evidence(snapshot, host, "interface_brief"),
    ]
    status_source = snapshot["hosts"][host]["sources"].get("interface_status")
    if status_source is None or status_source.get("parse_status") != "parsed":
        if _optional_uncollected(snapshot, host, ("interface_status",)):
            return _unknown(
                definition,
                host,
                "Interface status was not collected",
                evidence,
                resource="interfaces",
            )
        return _unknown(
            definition,
            host,
            "Interface status could not be parsed",
            evidence,
            resource="interfaces",
        )
    if value is None:
        return _unknown(definition, host, "Interface status is unavailable", evidence, resource="interfaces")
    down = sorted(name for name, item in value.items() if item.get("admin_state") == "up" and item.get("operational_state") != "up")
    result = "FAIL" if down else "PASS"
    message = "Admin-up interfaces are operationally up" if not down else "Admin-up interfaces are down: " + ", ".join(down)
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="target_not_ready" if down else "normal", message=message, evidence=evidence, resource="interfaces", after={"interfaces": value, "admin_up_oper_down": down})


def _evaluate_interface_errors(snapshot, host, definition, effective):
    value = snapshot["hosts"][host]["common"].get("interface_errors")
    evidence = _source_evidence(snapshot, host, "interface_errors")
    if value is None:
        if _optional_uncollected(snapshot, host, ("interface_errors",)):
            return _unknown(definition, host, "Interface error counters were not collected", [], resource="interfaces/errors")
        return _unknown(definition, host, "Interface error counters are unavailable", evidence, resource="interfaces/errors")
    total = sum(sum(counters.values()) for counters in value.values())
    result = "WARN" if total else "PASS"
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="pre_existing" if total else "normal", message=f"Interface error counter total is {total}", evidence=evidence, resource="interfaces/errors", after=value)


def _interface_identity(name: str) -> str:
    compact = re.sub(r"\s+", "", str(name)).casefold()
    ethernet = re.fullmatch(r"(?:ethernet|eth)(.+)", compact)
    if ethernet:
        return f"ethernet{ethernet.group(1)}"
    port_channel = re.fullmatch(r"(?:po|port-channel)(\d+)", compact)
    if port_channel:
        return f"port-channel{port_channel.group(1)}"
    return compact


def _evaluate_interface_utilization(snapshot, host, definition, effective):
    host_record = snapshot["hosts"][host]
    utilization = host_record["common"].get("interface_utilization")
    evidence = _source_evidence(snapshot, host, "interface_counters_table")
    if utilization is None:
        if _optional_uncollected(
            snapshot, host, ("interface_counters_table",)
        ):
            return _unknown(
                definition,
                host,
                "Interface utilization was not collected",
                evidence,
                resource="interfaces/utilization",
            )
        return _unknown(
            definition,
            host,
            "Interface utilization could not be parsed",
            evidence,
            resource="interfaces/utilization",
        )
    status_source = host_record["sources"].get("interface_status")
    interface_status = host_record["common"].get("interfaces")
    if (
        status_source is None
        or status_source.get("parse_status") != "parsed"
        or not isinstance(interface_status, Mapping)
    ):
        return _unknown(
            definition,
            host,
            "Interface operational state is unavailable for utilization filtering",
            [*evidence, *_source_evidence(snapshot, host, "interface_status")],
            resource="interfaces/utilization",
        )
    thresholds = effective.get("spec", {}).get("thresholds", {}).get(
        "interface_utilization", {}
    )
    info_percent = float(thresholds.get("info_percent", 50))
    warn_percent = float(thresholds.get("warn_percent", 70))
    fail_percent = float(thresholds.get("fail_percent", 90))
    if not 0 <= info_percent < warn_percent < fail_percent <= 100:
        return _unknown(
            definition,
            host,
            "Interface utilization thresholds must satisfy "
            "0 <= info < warn < fail <= 100",
            evidence,
            resource="interfaces/utilization",
        )
    status_by_identity = {
        _interface_identity(name): value for name, value in interface_status.items()
    }
    eligible: dict[str, Any] = {}
    for name, rates in utilization.get("interfaces", {}).items():
        status = status_by_identity.get(_interface_identity(name))
        normalized_name = str(name).casefold()
        if not (
            normalized_name.startswith(("eth", "ethernet", "po", "port-channel"))
            and isinstance(status, Mapping)
            and status.get("operational_state") == "up"
        ):
            continue
        peak = max(
            float(rates.get("input_percent", 0)),
            float(rates.get("output_percent", 0)),
        )
        eligible[name] = {**rates, "peak_percent": peak}
    if not eligible:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="No operational Ethernet or port-channel interface has utilization data",
            evidence=evidence,
            resource="interfaces/utilization",
        )
    peak_name, peak_value = max(
        eligible.items(), key=lambda item: item[1]["peak_percent"]
    )
    peak_percent = float(peak_value["peak_percent"])
    if peak_percent >= fail_percent:
        result, display_severity = "FAIL", None
    elif peak_percent >= warn_percent:
        result, display_severity = "WARN", None
    elif peak_percent >= info_percent:
        result, display_severity = "PASS", "INFO"
    else:
        result, display_severity = "PASS", None
    direction = (
        "input"
        if float(peak_value["input_percent"])
        >= float(peak_value["output_percent"])
        else "output"
    )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            f"Peak interface utilization is {peak_percent:.2f}% "
            f"on {peak_name} ({direction})"
        ),
        evidence=[*evidence, *_source_evidence(snapshot, host, "interface_status")],
        resource="interfaces/utilization",
        after={
            "thresholds": {
                "info_percent": info_percent,
                "warn_percent": warn_percent,
                "fail_percent": fail_percent,
            },
            "peak_interface": peak_name,
            "peak_direction": direction,
            "peak_percent": peak_percent,
            "interfaces": eligible,
        },
        display_severity=display_severity,
    )


def _evaluate_port_channels(snapshot, host, definition, _effective):
    value = snapshot["hosts"][host]["common"].get("port_channels")
    evidence = _source_evidence(snapshot, host, "port_channel_summary")
    if value is None:
        if _optional_uncollected(snapshot, host, ("port_channel_summary",)):
            return _unknown(definition, host, "Port-channel status was not collected", [], resource="port-channels")
        return _unknown(definition, host, "Port-channel status is unavailable", evidence, resource="port-channels")
    if not value.get("applicable", True):
        return _check(check_id=definition["id"], profile=definition["profile"], host=host, result="NOT_APPLICABLE", classification="normal", message="Port-channel is not configured", evidence=evidence, resource="port-channels", after=value)
    unhealthy = sorted(
        name
        for name, channel in value.get("channels", {}).items()
        if not channel.get("up")
        or (
            channel.get("member_check_applicable", True)
            and not channel.get("bundled_members")
        )
    )
    result = "FAIL" if unhealthy else "PASS"
    message = "Port-channels and members are bundled" if not unhealthy else "Unhealthy port-channels: " + ", ".join(unhealthy)
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="target_not_ready" if unhealthy else "normal", message=message, evidence=evidence, resource="port-channels", after=value)


def _evaluate_reload(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    pending = snapshot["hosts"][host]["common"].get("reload_pending")
    evidence = _source_evidence(snapshot, host, "reload_pending")
    if pending is None:
        return _unknown(
            definition,
            host,
            "reload-pending state is unavailable",
            evidence,
            resource="system/reload-pending",
        )
    result = "WARN" if pending["required"] else "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="pre_existing" if result == "WARN" else "normal",
        message=(
            "Reload-pending configuration exists"
            if pending["required"]
            else "No reload-pending configuration exists"
        ),
        evidence=evidence,
        resource="system/reload-pending",
        after=pending,
    )


def _evaluate_running_config_diff(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    value = snapshot["hosts"][host]["common"].get("running_config_diff")
    evidence = _source_evidence(snapshot, host, "running_config_diff")
    if value is None:
        if _optional_uncollected(snapshot, host, ("running_config_diff",)):
            return _unknown(
                definition,
                host,
                "Running/startup configuration diff was not collected",
                [],
                resource="system/running-startup-diff",
            )
        return _unknown(
            definition,
            host,
            "Running/startup configuration diff is unavailable",
            evidence,
            resource="system/running-startup-diff",
        )
    different = bool(value.get("different"))
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="WARN" if different else "PASS",
        classification="pre_existing" if different else "normal",
        message=(
            f"Running-config differs from startup-config "
            f"({value.get('line_count', 0)} non-empty output lines)"
            if different
            else "Running-config matches startup-config"
        ),
        evidence=evidence,
        resource="system/running-startup-diff",
        after=value,
    )


def _evaluate_route_count(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    route_summary = (
        snapshot["hosts"][host]["common"].get("routes", {}).get("ipv4_summary")
    )
    evidence = _source_evidence(snapshot, host, "route_summary_ipv4")
    if not route_summary:
        return _unknown(
            definition,
            host,
            "IPv4 route summary is unavailable",
            evidence,
            resource="routing/ipv4",
        )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result="PASS",
        classification="normal",
        message=(
            f"IPv4 route counts were collected for {len(route_summary['vrfs'])} VRFs"
        ),
        evidence=evidence,
        resource="routing/ipv4",
        after=route_summary,
    )


def _evaluate_ospf(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    ospf = snapshot["hosts"][host]["common"].get("routing_neighbors", {}).get("ospf")
    evidence = _source_evidence(snapshot, host, "ospf_neighbors")
    if ospf is None:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="OSPF was not observed",
            evidence=evidence,
            resource="routing/ospf",
        )
    if not ospf.get("applicable", True):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="OSPF is not configured",
            evidence=evidence,
            resource="routing/ospf",
        )
    non_full = [
        f"{process_key}/{neighbor_id}"
        for process_key, process in ospf["processes"].items()
        for neighbor_id, neighbor in process["neighbors"].items()
        if neighbor["state"] != "FULL"
    ]
    result = "FAIL" if non_full else "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            "All observed OSPF neighbors are FULL"
            if not non_full
            else "Non-FULL OSPF neighbors: " + ", ".join(non_full)
        ),
        evidence=evidence,
        resource="routing/ospf",
        after=ospf,
    )


def _bgp_ipv4_unhealthy(value: Mapping[str, Any]) -> list[str]:
    return [
        f"{vrf}/{address}"
        for vrf, summary in value.get("vrfs", {}).items()
        for address, neighbor in summary.get("neighbors", {}).items()
        if neighbor.get("state") != "Established"
    ]


def _configured_bgp_neighbors(
    snapshot: Mapping[str, Any], host: str, afi: str
) -> tuple[list[dict[str, Any]], bool, bool]:
    config = snapshot["hosts"][host]["common"].get(
        "routing_neighbor_config"
    )
    if not isinstance(config, Mapping):
        return [], False, False
    expected_af = f"{afi}-unicast"
    neighbors: list[dict[str, Any]] = []
    unresolved = False
    for local_as, process in config.get("processes", {}).items():
        for vrf, scope in process.get("vrfs", {}).items():
            if scope.get("resolution_status") == "unresolved":
                unresolved = True
            for address, values in scope.get("neighbors", {}).items():
                try:
                    network = ipaddress.ip_network(str(address), strict=False)
                except ValueError:
                    unresolved = True
                    continue
                if (afi == "ipv4" and network.version != 4) or (
                    afi == "ipv6" and network.version != 6
                ):
                    continue
                address_families = values.get("address_families", {})
                if address_families and expected_af not in address_families:
                    continue
                neighbors.append(
                    {
                        "local_as": str(local_as),
                        "vrf": str(vrf),
                        "address": str(address),
                        "network": str(network),
                        "dynamic": "/" in str(address),
                        "resolution_status": values.get(
                            "resolution_status", "resolved"
                        ),
                    }
                )
    return neighbors, True, unresolved


def _evaluate_bgp_ipv4(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    bgp = snapshot["hosts"][host]["common"].get("routing_neighbors", {}).get("bgp_ipv4")
    evidence = _source_evidence(snapshot, host, "bgp_ipv4_summary")
    configured_neighbors, config_available, config_unresolved = _configured_bgp_neighbors(
        snapshot, host, "ipv4"
    )
    if bgp is None:
        if config_available and (configured_neighbors or config_unresolved):
            return _unknown(
                definition,
                host,
                "IPv4 BGP summary is unavailable for configured neighbors",
                [*evidence, *_source_evidence(snapshot, host, "running_config")],
                resource="routing/bgp-ipv4",
            )
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="IPv4 BGP was not observed",
            evidence=evidence,
            resource="routing/bgp-ipv4",
        )
    if config_available:
        if config_unresolved:
            return _unknown(
                definition,
                host,
                "IPv4 BGP neighbor configuration could not be resolved",
                [*evidence, *_source_evidence(snapshot, host, "running_config")],
                resource="routing/bgp-ipv4",
            )
        static_neighbors = [
            item for item in configured_neighbors if not item["dynamic"]
        ]
        if not static_neighbors:
            return _check(
                check_id=definition["id"],
                profile=definition["profile"],
                host=host,
                result="NOT_APPLICABLE",
                classification="normal",
                message="IPv4 BGP has no statically configured peers",
                evidence=[
                    *evidence,
                    *_source_evidence(snapshot, host, "running_config"),
                ],
                resource="routing/bgp-ipv4",
            )
        unhealthy_static: list[str] = []
        for item in static_neighbors:
            summary = bgp.get("vrfs", {}).get(item["vrf"], {})
            observed = summary.get("neighbors", {}).get(item["address"])
            if observed is None or observed.get("state") != "Established":
                unhealthy_static.append(f"{item['vrf']}/{item['address']}")
        result = "FAIL" if unhealthy_static else "PASS"
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result=result,
            classification="normal" if result == "PASS" else "target_not_ready",
            message=(
                "All statically configured IPv4 BGP peers are established"
                if not unhealthy_static
                else "Missing or unhealthy static IPv4 BGP peers: "
                + ", ".join(unhealthy_static)
            ),
            evidence=[
                *evidence,
                *_source_evidence(snapshot, host, "running_config"),
            ],
            resource="routing/bgp-ipv4",
            after={"configured_neighbors": static_neighbors, "summary": bgp},
        )
    configured = sum(summary["configured_peers"] for summary in bgp["vrfs"].values())
    if not bgp.get("applicable", True) or configured == 0:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="IPv4 BGP has no configured peers",
            evidence=evidence,
            resource="routing/bgp-ipv4",
        )
    unhealthy = _bgp_ipv4_unhealthy(bgp)
    observed_neighbors = sum(
        len(summary.get("neighbors", {})) for summary in bgp["vrfs"].values()
    )
    result = "FAIL" if unhealthy or observed_neighbors == 0 else "PASS"
    if result == "PASS":
        message = "All observed IPv4 BGP peers are established"
    elif unhealthy:
        message = "Unhealthy IPv4 BGP peers: " + ", ".join(unhealthy)
    else:
        message = "IPv4 BGP is configured but no peer rows were observed"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=message,
        evidence=evidence,
        resource="routing/bgp-ipv4",
        after=bgp,
    )


def _evaluate_bgp_dynamic_neighbors(snapshot, host, definition, _effective):
    configured: list[dict[str, Any]] = []
    config_available = False
    config_unresolved = False
    for afi in ("ipv4", "ipv6"):
        neighbors, available, unresolved = _configured_bgp_neighbors(
            snapshot, host, afi
        )
        configured.extend(item for item in neighbors if item["dynamic"])
        config_available = config_available or available
        config_unresolved = config_unresolved or unresolved
    evidence = _source_evidence(snapshot, host, "running_config")
    if not config_available:
        return _unknown(
            definition,
            host,
            "BGP neighbor range configuration is unavailable",
            evidence,
            resource="routing/bgp-dynamic-neighbors",
        )
    if config_unresolved:
        return _unknown(
            definition,
            host,
            "BGP neighbor range configuration could not be resolved",
            evidence,
            resource="routing/bgp-dynamic-neighbors",
        )
    if not configured:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="No dynamic BGP neighbor range is configured",
            evidence=evidence,
            resource="routing/bgp-dynamic-neighbors",
        )
    ranges: list[dict[str, Any]] = []
    results: list[str] = []
    for item in configured:
        network = ipaddress.ip_network(item["network"], strict=False)
        afi = "ipv4" if network.version == 4 else "ipv6"
        source_id = f"bgp_{afi}_summary"
        summary_source = snapshot["hosts"][host]["sources"].get(source_id)
        summary = snapshot["hosts"][host]["common"].get(
            "routing_neighbors", {}
        ).get(f"bgp_{afi}")
        range_result = "PASS"
        matched: list[str] = []
        established: list[str] = []
        if item["resolution_status"] != "resolved":
            range_result = "UNKNOWN"
        elif (
            summary_source is None
            or summary_source.get("parse_status") != "parsed"
            or not isinstance(summary, Mapping)
        ):
            range_result = "UNKNOWN"
        else:
            vrf_summary = summary.get("vrfs", {}).get(item["vrf"], {})
            for address, values in vrf_summary.get("neighbors", {}).items():
                try:
                    peer_address = ipaddress.ip_address(str(address))
                except ValueError:
                    continue
                if peer_address in network:
                    matched.append(str(address))
                    if values.get("state") == "Established":
                        established.append(str(address))
            if not matched:
                range_result = "WARN"
            elif len(established) != len(matched):
                range_result = "FAIL"
        results.append(range_result)
        ranges.append(
            {
                "local_as": item["local_as"],
                "vrf": item["vrf"],
                "range": str(network),
                "address_family": afi,
                "matched_neighbors": sorted(matched),
                "established_neighbors": sorted(established),
                "result": range_result,
            }
        )
        evidence.extend(_source_evidence(snapshot, host, source_id))
    result = max(results, key=lambda value: RESULT_ORDER[value])
    empty_ranges = [item["range"] for item in ranges if item["result"] == "WARN"]
    unhealthy_ranges = [
        item["range"] for item in ranges if item["result"] == "FAIL"
    ]
    unknown_ranges = [
        item["range"] for item in ranges if item["result"] == "UNKNOWN"
    ]
    if unhealthy_ranges:
        message = "Dynamic BGP ranges have non-established neighbors: " + ", ".join(
            unhealthy_ranges
        )
    elif unknown_ranges:
        message = "Dynamic BGP ranges could not be evaluated: " + ", ".join(
            unknown_ranges
        )
    elif empty_ranges:
        message = "Dynamic BGP ranges have no observed neighbors: " + ", ".join(
            empty_ranges
        )
    else:
        message = "All dynamic BGP ranges have established neighbors"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=message,
        evidence=evidence,
        resource="routing/bgp-dynamic-neighbors",
        after={"ranges": ranges},
    )


def _evaluate_vpc(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    vpc = snapshot["hosts"][host]["common"].get("vpc")
    evidence = _source_evidence(snapshot, host, "vpc_brief")
    if vpc is None:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="vPC was not observed",
            evidence=evidence,
            resource="vpc",
        )
    if not vpc.get("applicable", True):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="vPC is not configured",
            evidence=evidence,
            resource="vpc",
        )
    result = "PASS" if vpc.get("healthy") else "FAIL"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            "vPC peer and consistency are healthy"
            if result == "PASS"
            else "vPC peer or consistency is unhealthy"
        ),
        evidence=evidence,
        resource="vpc",
        after=vpc,
    )


def _evaluate_nve(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    nve = (
        snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get("nve_interface")
    )
    evidence = _source_evidence(snapshot, host, "nve_interface")
    if nve is None:
        config = (
            snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get("config")
        )
        if config is not None and not config.get("nve", {}).get(
            "configured",
            False,
        ):
            return _check(
                check_id=definition["id"],
                profile=definition["profile"],
                host=host,
                result="NOT_APPLICABLE",
                classification="normal",
                message="NVE is not configured",
                evidence=[
                    *_source_evidence(snapshot, host, "running_config"),
                    *evidence,
                ],
                resource="nve",
            )
        return _unknown(
            definition,
            host,
            "NVE interface state is unavailable",
            evidence,
            resource="nve",
        )
    if not nve.get("applicable", True):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="NVE is not configured",
            evidence=evidence,
            resource="nve",
        )
    result = "PASS" if nve.get("state", "").lower() == "up" else "FAIL"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=f"NVE interface state is {nve.get('state')}",
        evidence=evidence,
        resource=f"nve/{nve.get('name', 'unknown')}",
        after=nve,
    )


def _evaluate_evpn_bgp(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    bgp = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get("evpn_bgp")
    evidence = _source_evidence(
        snapshot,
        host,
        "bgp_l2vpn_evpn_summary",
    )
    if bgp is None:
        config = (
            snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get("config")
        )
        if config is not None and not config.get(
            "evpn_bgp_configured",
            False,
        ):
            return _check(
                check_id=definition["id"],
                profile=definition["profile"],
                host=host,
                result="NOT_APPLICABLE",
                classification="normal",
                message="EVPN BGP is not configured",
                evidence=[
                    *_source_evidence(snapshot, host, "running_config"),
                    *evidence,
                ],
                resource="bgp/evpn",
            )
        return _unknown(
            definition,
            host,
            "EVPN BGP state is unavailable",
            evidence,
            resource="bgp/evpn",
        )
    if not bgp.get("applicable", True):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="EVPN BGP is not configured",
            evidence=evidence,
            resource="bgp/evpn",
        )
    unhealthy = [
        address
        for address, neighbor in bgp.get("neighbors", {}).items()
        if neighbor.get("state") != "Established"
    ]
    healthy = bool(bgp.get("neighbors")) and not unhealthy
    result = "PASS" if healthy else "FAIL"
    if result == "PASS":
        message = "All observed EVPN BGP peers are established"
    elif unhealthy:
        message = "Unhealthy EVPN BGP peers: " + ", ".join(unhealthy)
    else:
        message = "EVPN BGP is configured but no peer rows were observed"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=message,
        evidence=evidence,
        resource="bgp/evpn",
        after=bgp,
    )


def _evaluate_nve_peers(snapshot, host, definition, _effective):
    value = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "nve_peers"
    )
    evidence = _source_evidence(snapshot, host, "nve_peers")
    if value is None:
        return _unknown(definition, host, "NVE peer state is unavailable", evidence, resource="nve/peers")
    if not value.get("applicable", True):
        return _check(check_id=definition["id"], profile=definition["profile"], host=host, result="NOT_APPLICABLE", classification="normal", message="NVE is not configured", evidence=evidence, resource="nve/peers")
    unhealthy = sorted(
        address
        for address, peer in value.get("peers", {}).items()
        if str(peer.get("state", "")).lower() != "up"
    )
    result = "FAIL" if unhealthy else "PASS"
    message = "All observed NVE peers are up" if not unhealthy else "Unhealthy NVE peers: " + ", ".join(unhealthy)
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="normal" if result == "PASS" else "target_not_ready", message=message, evidence=evidence, resource="nve/peers", after=value)


def _evaluate_nve_vnis(snapshot, host, definition, _effective):
    value = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "nve_vnis"
    )
    evidence = _source_evidence(snapshot, host, "nve_vni")
    if value is None:
        return _unknown(definition, host, "NVE VNI state is unavailable", evidence, resource="nve/vnis")
    if not value.get("applicable", True):
        return _check(check_id=definition["id"], profile=definition["profile"], host=host, result="NOT_APPLICABLE", classification="normal", message="NVE is not configured", evidence=evidence, resource="nve/vnis")
    unhealthy = sorted(
        vni
        for vni, item in value.get("vnis", {}).items()
        if str(item.get("state", "")).lower() != "up"
    )
    result = "FAIL" if unhealthy else "PASS"
    message = "All observed NVE VNIs are up" if not unhealthy else "Unhealthy NVE VNIs: " + ", ".join(unhealthy)
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="normal" if result == "PASS" else "target_not_ready", message=message, evidence=evidence, resource="nve/vnis", after=value)


def _overlay_operational_scope(config: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """Derive device-local VLAN, VRF, and SVI expectations from running config."""
    vlans = {
        str(vlan)
        for vlan, value in config.get("vlans", {}).items()
        if value.get("vni") is not None
    }
    vrfs = {
        str(vrf)
        for vrf, value in config.get("vrfs", {}).items()
        if value.get("l3vni") is not None
    }
    svis: set[str] = set()
    for vlan, value in config.get("svis", {}).items():
        vrf = str(value.get("vrf", "default"))
        if str(vlan) in vlans or vrf in vrfs:
            svis.add(str(vlan))
            if vrf != "default":
                vrfs.add(vrf)
    return vlans, vrfs, svis


def _evaluate_overlay_resource_state(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    *,
    kind: str,
    command_id: str,
) -> dict[str, Any]:
    profile = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {})
    config = profile.get("config")
    evidence = [
        *_source_evidence(snapshot, host, "running_config"),
        *_source_evidence(snapshot, host, command_id),
    ]
    if config is None:
        return _unknown(definition, host, "Overlay running-config evidence is unavailable", evidence, resource=f"overlay/{kind}")
    expected = dict(zip(("vlan", "vrf", "svi"), _overlay_operational_scope(config)))[kind]
    if not expected:
        return _check(check_id=definition["id"], profile=definition["profile"], host=host, result="NOT_APPLICABLE", classification="normal", message=f"No overlay {kind.upper()} is configured", evidence=evidence, resource=f"overlay/{kind}")

    field = {"vlan": "vlans", "vrf": "vrfs", "svi": "svis"}[kind]
    value = profile.get(field)
    if value is None:
        return _unknown(definition, host, f"{kind.upper()} operational state is unavailable", evidence, resource=f"overlay/{kind}")
    member = "interfaces" if kind == "svi" else field
    observed = value.get(member, {})
    failures: list[str] = []
    for name in sorted(expected, key=lambda item: (not item.isdigit(), int(item) if item.isdigit() else item)):
        key = f"Vlan{name}" if kind == "svi" else name
        item = observed.get(key if kind == "svi" else name)
        if item is None:
            failures.append(f"{key}=missing")
        elif kind == "vlan" and str(item.get("status", "")).lower() != "active":
            failures.append(f"{name}={item.get('status', 'unknown')}")
        elif kind == "vrf" and str(item.get("state", "")).lower() != "up":
            failures.append(f"{name}={item.get('state', 'unknown')}")
        elif kind == "svi":
            configured = config.get("svis", {}).get(name, {})
            admin = str(item.get("admin_state", "unknown")).lower()
            operational = str(
                item.get("operational_state", item.get("protocol_state", "unknown"))
            ).lower()
            if not configured.get("admin_enabled", True):
                failures.append(f"{key}=configured shutdown")
            elif admin != "up" or operational != "up":
                failures.append(f"{key}={admin}/{operational}")
    result = "FAIL" if failures else "PASS"
    label = {"vlan": "VLAN", "vrf": "VRF", "svi": "SVI"}[kind]
    message = (
        f"All {len(expected)} expected overlay {label}(s) are operational"
        if not failures
        else f"Unhealthy overlay {label}(s): " + ", ".join(failures)
    )
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="normal" if result == "PASS" else "target_not_ready", message=message, evidence=evidence, resource=f"overlay/{kind}", after={"expected": sorted(expected), "failures": failures})


def _evaluate_vlan_operational(snapshot, host, definition, _effective):
    return _evaluate_overlay_resource_state(snapshot, host, definition, kind="vlan", command_id="vlan_brief")


def _evaluate_vrf_operational(snapshot, host, definition, _effective):
    return _evaluate_overlay_resource_state(snapshot, host, definition, kind="vrf", command_id="vrf")


def _evaluate_svi_operational(snapshot, host, definition, _effective):
    return _evaluate_overlay_resource_state(snapshot, host, definition, kind="svi", command_id="interface_brief")


def _evaluate_evpn_routes(snapshot, host, definition, _effective):
    value = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "evpn_routes"
    )
    evidence = _source_evidence(snapshot, host, "bgp_l2vpn_evpn")
    if value is None:
        return _unknown(definition, host, "EVPN route state is unavailable", evidence, resource="bgp/evpn/routes")
    if not value.get("applicable", True):
        return _check(check_id=definition["id"], profile=definition["profile"], host=host, result="NOT_APPLICABLE", classification="normal", message="EVPN BGP is not configured", evidence=evidence, resource="bgp/evpn/routes")
    count = int(value.get("route_count", 0))
    result = "PASS" if count else "WARN"
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="normal" if result == "PASS" else "pre_existing", message=f"Observed EVPN route count is {count}", evidence=evidence, resource="bgp/evpn/routes", after=value)


def _prefix_list_decision(
    config: Mapping[str, Any], name: str, prefix: str
) -> bool | None:
    entries = config.get("prefix_lists", {}).get(name)
    if not entries:
        return None
    candidate = ipaddress.ip_network(prefix, strict=False)
    for entry in entries:
        base = ipaddress.ip_network(entry["prefix"], strict=False)
        if candidate.version != base.version or not candidate.subnet_of(base):
            continue
        minimum = int(entry.get("ge", base.prefixlen))
        maximum = int(
            entry.get(
                "le",
                candidate.max_prefixlen if "ge" in entry else base.prefixlen,
            )
        )
        if minimum <= candidate.prefixlen <= maximum:
            return entry["action"] == "permit"
    return False


def _route_map_decision(
    config: Mapping[str, Any], name: str, prefix: str
) -> bool | None:
    sequences = config.get("route_map_policies", {}).get(name)
    if not sequences:
        return None
    for sequence in sequences:
        if sequence.get("unsupported_matches"):
            return None
        names = sequence.get("match_ip_prefix_lists", [])
        if names:
            decisions = [
                _prefix_list_decision(config, prefix_list, prefix)
                for prefix_list in names
            ]
            if any(decision is None for decision in decisions):
                return None
            if not any(decisions):
                continue
        return sequence["action"] == "permit"
    return False


def _type5_expectations(
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for local_as, process in config.get("bgp_processes", {}).items():
        for vrf, vrf_bgp in process.get("vrfs", {}).items():
            vrf_config = config.get("vrfs", {}).get(vrf, {})
            l3vni = vrf_config.get("l3vni")
            for family, af in vrf_bgp.get("address_families", {}).items():
                commands = af.get("commands", [])
                redistributions = [
                    command
                    for command in commands
                    if command.startswith("redistribute direct")
                ]
                if not redistributions:
                    continue
                for vlan, svi in config.get("svis", {}).items():
                    if svi.get("vrf") != vrf:
                        continue
                    addresses = svi.get(
                        "ipv4_addresses" if family == "ipv4" else "ipv6_addresses",
                        [],
                    )
                    for address in addresses:
                        prefix = str(ipaddress.ip_interface(address).network)
                        decisions: list[bool | None] = []
                        for command in redistributions:
                            match = re.match(
                                r"redistribute direct(?: route-map (\S+))?$", command
                            )
                            if not match:
                                decisions.append(None)
                            elif match.group(1):
                                decisions.append(
                                    _route_map_decision(config, match.group(1), prefix)
                                )
                            else:
                                decisions.append(True)
                        item = {
                            "vrf": vrf,
                            "family": family,
                            "prefix": prefix,
                            "vlan": int(vlan),
                            "l3vni": l3vni,
                            "local_as": local_as,
                        }
                        if any(decision is True for decision in decisions):
                            expected.append(item)
                        elif any(decision is None for decision in decisions):
                            unknown.append(item)
    unique = {
        (item["vrf"], item["family"], item["prefix"]): item for item in expected
    }
    unknown_unique = {
        (item["vrf"], item["family"], item["prefix"]): item for item in unknown
        if (item["vrf"], item["family"], item["prefix"]) not in unique
    }
    return list(unique.values()), list(unknown_unique.values())


def _build_type5_route_indexes(
    snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build reusable presence indexes without duplicating them in artifacts."""
    evpn: dict[str, Any] = {}
    vrf: dict[str, Any] = {}
    for host, host_data in snapshot["hosts"].items():
        overlay = host_data["profiles"].get("nxos-overlay", {})
        evpn_routes = overlay.get("evpn_routes")
        if evpn_routes is None or not evpn_routes.get("applicable", True):
            evpn[host] = None
        else:
            by_prefix: dict[str, list[Mapping[str, Any]]] = {}
            for route in evpn_routes.get("routes", []):
                if route.get("route_type") != 5 or not route.get("prefix"):
                    continue
                by_prefix.setdefault(str(route["prefix"]), []).append(route)
            evpn[host] = by_prefix

        vrf_routes = overlay.get("vrf_routes")
        if vrf_routes is None:
            vrf[host] = None
            continue
        family_indexes: dict[str, set[tuple[str, str]]] = {}
        for family in ("ipv4", "ipv6"):
            if family not in vrf_routes:
                continue
            family_value = vrf_routes.get(family, {})
            routes = family_value.get(
                "routes", family_value if isinstance(family_value, list) else []
            )
            family_indexes[family] = {
                (str(route.get("vrf", "")), str(route.get("prefix", "")))
                for route in routes
                if route.get("vrf") and route.get("prefix")
            }
        vrf[host] = family_indexes
    return {"evpn": evpn, "vrf": vrf}


def _has_type5(
    snapshot: Mapping[str, Any],
    host: str,
    prefix: str,
    route_indexes: Mapping[str, Any] | None = None,
) -> bool | None:
    if route_indexes is not None:
        routes_by_prefix = route_indexes["evpn"].get(host)
        return None if routes_by_prefix is None else prefix in routes_by_prefix
    routes = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "evpn_routes"
    )
    if routes is None or not routes.get("applicable", True):
        return None
    return any(
        route.get("route_type") == 5 and route.get("prefix") == prefix
        for route in routes.get("routes", [])
    )


def _type5_origin_scope(
    snapshot: Mapping[str, Any], host: str
) -> tuple[list[str], set[str]] | None:
    origin_nve = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "nve_interface"
    )
    if not origin_nve or not origin_nve.get("applicable", True):
        return None
    secondary = origin_nve.get("secondary_address")
    members: list[str] = []
    next_hops: set[str] = set()
    for candidate, data in snapshot["hosts"].items():
        nve = data["profiles"].get("nxos-overlay", {}).get("nve_interface")
        if not nve or not nve.get("applicable", True):
            continue
        same_origin = candidate == host or (
            secondary is not None and nve.get("secondary_address") == secondary
        )
        if not same_origin:
            continue
        members.append(candidate)
        for key in ("primary_address", "secondary_address"):
            if nve.get(key):
                next_hops.add(str(nve[key]))
    return sorted(members), next_hops


def _has_origin_type5(
    snapshot: Mapping[str, Any],
    host: str,
    prefix: str,
    next_hops: set[str],
    route_indexes: Mapping[str, Any] | None = None,
) -> bool | None:
    if route_indexes is not None:
        routes_by_prefix = route_indexes["evpn"].get(host)
        if routes_by_prefix is None:
            return None
        matching = routes_by_prefix.get(prefix, [])
        return any(
            route.get("local") is True
            or route.get("next_hop") in next_hops
            or any(
                path.get("local") is True or path.get("next_hop") in next_hops
                for path in route.get("paths", [])
            )
            for route in matching
        )
    routes = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "evpn_routes"
    )
    if routes is None or not routes.get("applicable", True):
        return None
    matching = [
        route
        for route in routes.get("routes", [])
        if route.get("route_type") == 5 and route.get("prefix") == prefix
    ]
    return any(
        route.get("local") is True
        or route.get("next_hop") in next_hops
        or any(
            path.get("local") is True or path.get("next_hop") in next_hops
            for path in route.get("paths", [])
        )
        for route in matching
    )


def _has_vrf_route(
    snapshot: Mapping[str, Any],
    host: str,
    vrf: str,
    prefix: str,
    route_indexes: Mapping[str, Any] | None = None,
) -> bool | None:
    family = "ipv6" if ":" in prefix else "ipv4"
    if route_indexes is not None:
        families = route_indexes["vrf"].get(host)
        if families is None or family not in families:
            return None
        return (vrf, prefix) in families[family]
    value = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "vrf_routes"
    )
    if value is None:
        return None
    if family not in value:
        return None
    family_value = value.get(family, value)
    routes = family_value.get(
        "routes", family_value if isinstance(family_value, list) else []
    )
    return any(
        route.get("vrf") == vrf and route.get("prefix") == prefix
        for route in routes
    )


def _evpn_route_targets(
    vrf_config: Mapping[str, Any], *, direction: str
) -> set[str]:
    targets: set[str] = set()
    for af in vrf_config.get("address_families", {}).values():
        for command in af.get("commands", []):
            match = re.match(
                r"route-target\s+(both|import|export)\s+(\S+)(?:\s+evpn)?$",
                command,
            )
            if match and match.group(1) in {"both", direction}:
                targets.add(match.group(2))
    return targets


def _imports_type5(
    origin_vrf: Mapping[str, Any], receiver_vrf: Mapping[str, Any]
) -> tuple[bool, str]:
    if origin_vrf.get("l3vni") != receiver_vrf.get("l3vni"):
        return False, "l3vni-mismatch"
    exports = _evpn_route_targets(origin_vrf, direction="export")
    imports = _evpn_route_targets(receiver_vrf, direction="import")
    if exports and imports:
        if "auto" in exports and "auto" in imports:
            return True, "matching-l3vni-auto-rt"
        return bool(exports & imports), "explicit-rt-intersection"
    return True, "matching-l3vni-implicit-auto-rt"


def _evaluate_type5_prefix_propagation(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    resolved_roles: Mapping[str, Any] | None,
    route_indexes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {})
    config = profile.get("config")
    evidence = [
        *_source_evidence(snapshot, host, "running_config"),
        *_source_evidence(snapshot, host, "bgp_l2vpn_evpn"),
    ]
    if config is None:
        return _unknown(
            definition, host, "Overlay configuration is unavailable", evidence,
            resource="bgp/evpn/type-5",
        )
    expected, unresolved = _type5_expectations(config)
    if not expected:
        if unresolved:
            return _check(
                check_id=definition["id"], profile=definition["profile"], host=host,
                result="UNKNOWN", classification="collection_error",
                message="Type-5 advertisement policy could not be resolved safely",
                evidence=evidence, resource="bgp/evpn/type-5",
                after={"unresolved_prefixes": unresolved},
            )
        return _check(
            check_id=definition["id"], profile=definition["profile"], host=host,
            result="NOT_APPLICABLE", classification="normal",
            message="No connected prefix is configured for Type-5 advertisement",
            evidence=evidence, resource="bgp/evpn/type-5",
        )

    role_devices = (
        resolved_roles.get("spec", {}).get("devices", {})
        if resolved_roles is not None else {}
    )
    rr_hosts = sorted(
        candidate for candidate, role in role_devices.items()
        if "evpn-route-reflector" in role.get("functions", {})
    )
    origin_scope = _type5_origin_scope(snapshot, host)
    origin_members, origin_next_hops = origin_scope or ([], set())
    findings: list[dict[str, Any]] = []
    for item in expected:
        receivers = []
        for candidate, candidate_data in sorted(snapshot["hosts"].items()):
            if candidate in origin_members:
                continue
            role = role_devices.get(candidate, {})
            if role and role.get("topology_role") not in {"leaf", "border-gateway"}:
                continue
            candidate_config = candidate_data["profiles"].get(
                "nxos-overlay", {}
            ).get("config", {})
            candidate_vrf = candidate_config.get("vrfs", {}).get(item["vrf"], {})
            origin_vrf = config.get("vrfs", {}).get(item["vrf"], {})
            imports, _selection_basis = _imports_type5(origin_vrf, candidate_vrf)
            if imports:
                receivers.append(candidate)
        origin_present = (
            _has_origin_type5(
                snapshot,
                host,
                item["prefix"],
                origin_next_hops,
                route_indexes,
            )
            if origin_scope is not None
            else None
        )
        rr_state = {
            rr: _has_type5(snapshot, rr, item["prefix"], route_indexes)
            for rr in rr_hosts
        }
        receiver_state = {
            receiver: {
                "type5": _has_type5(
                    snapshot, receiver, item["prefix"], route_indexes
                ),
                "vrf_route": _has_vrf_route(
                    snapshot,
                    receiver,
                    item["vrf"],
                    item["prefix"],
                    route_indexes,
                ),
            }
            for receiver in receivers
        }
        covered_receivers = sum(
            state["type5"] is not None and state["vrf_route"] is not None
            for state in receiver_state.values()
        )
        findings.append({
            **item,
            "origin_type5": origin_present,
            "origin_devices": origin_members,
            "origin_next_hops": sorted(origin_next_hops),
            "route_reflectors": rr_state,
            "receivers": receiver_state,
            "receiver_coverage": f"{covered_receivers}/{len(receivers)}",
        })

    unknown_state = bool(unresolved) or not rr_hosts or any(
        finding["origin_type5"] is None
        or any(value is None for value in finding["route_reflectors"].values())
        or any(
            state["type5"] is None or state["vrf_route"] is None
            for state in finding["receivers"].values()
        )
        for finding in findings
    )
    failed = any(
        finding["origin_type5"] is False
        or any(value is False for value in finding["route_reflectors"].values())
        or any(
            state["type5"] is False or state["vrf_route"] is False
            for state in finding["receivers"].values()
        )
        for finding in findings
    )
    result = "FAIL" if failed else "UNKNOWN" if unknown_state else "PASS"
    failures: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []
    for finding in findings:
        context = {"vrf": finding["vrf"], "prefix": finding["prefix"]}
        if finding["origin_type5"] is False:
            failures.append({
                **context,
                "stage": "ORIGIN",
                "devices": finding["origin_devices"],
                "reason": "expected origin path is missing",
            })
        elif finding["origin_type5"] is None:
            unknowns.append({
                **context, "stage": "ORIGIN", "devices": finding["origin_devices"],
                "reason": "origin evidence is unavailable",
            })
        failed_rr = sorted(
            device for device, state in finding["route_reflectors"].items()
            if state is False
        )
        unknown_rr = sorted(
            device for device, state in finding["route_reflectors"].items()
            if state is None
        )
        if failed_rr:
            failures.append({
                **context, "stage": "EVPN_RR", "devices": failed_rr,
                "reason": "Type-5 route is missing",
            })
        if unknown_rr:
            unknowns.append({
                **context, "stage": "EVPN_RR", "devices": unknown_rr,
                "reason": "route evidence is unavailable",
            })
        for field, stage, reason in (
            ("type5", "RECEIVER_TYPE5", "Type-5 route is missing"),
            ("vrf_route", "RECEIVER_VRF_ROUTE", "VRF route is missing"),
        ):
            failed_devices = sorted(
                device for device, state in finding["receivers"].items()
                if state[field] is False
            )
            unknown_devices = sorted(
                device for device, state in finding["receivers"].items()
                if state[field] is None
            )
            if failed_devices:
                failures.append({
                    **context, "stage": stage, "devices": failed_devices,
                    "reason": reason,
                })
            if unknown_devices:
                unknowns.append({
                    **context, "stage": stage, "devices": unknown_devices,
                    "reason": "evidence is unavailable",
                })

    total_receivers = sum(len(finding["receivers"]) for finding in findings)
    covered_receivers = sum(
        sum(
            state["type5"] is not None and state["vrf_route"] is not None
            for state in finding["receivers"].values()
        )
        for finding in findings
    )
    stage_summary = {
        "prefixes": {
            "passed": sum(
                not any(
                    item["vrf"] == finding["vrf"]
                    and item["prefix"] == finding["prefix"]
                    for item in [*failures, *unknowns]
                )
                for finding in findings
            ),
            "total": len(findings),
        },
        "receiver_evidence": {
            "covered": covered_receivers,
            "total": total_receivers,
        },
    }
    details = failures if result == "FAIL" else unknowns
    if details:
        rendered_details = "; ".join(
            f"{item['stage']} {item['vrf']} {item['prefix']} on "
            f"{','.join(item['devices']) or '-'}: {item['reason']}"
            for item in details
        )
        message = (
            f"Type-5 propagation: {len(details)} issue(s) across "
            f"{len(findings)} prefix(es); {rendered_details}"
        )
    else:
        receiver_text = (
            f"receiver evidence {covered_receivers}/{total_receivers}"
            if total_receivers
            else "receiver stage NOT_APPLICABLE (0 targets)"
        )
        message = (
            f"Type-5 propagation: {len(findings)}/{len(findings)} "
            f"prefix(es) passed; {receiver_text}"
        )
    return _check(
        check_id=definition["id"], profile=definition["profile"], host=host,
        result=result,
        classification=("normal" if result == "PASS" else
                        "target_not_ready" if result == "FAIL" else "collection_error"),
        message=message,
        evidence=evidence, resource="bgp/evpn/type-5",
        after={
            "mode": "full",
            "failures": failures,
            "unknowns": unknowns,
            "stage_summary": stage_summary,
            "unresolved_prefixes": unresolved,
        },
    )


def _configured_function(config: Mapping[str, Any] | None, function_name: str) -> bool | None:
    if config is None:
        return None
    if function_name == "vtep":
        return bool(config.get("nve", {}).get("configured"))
    if function_name == "vpc":
        return bool(config.get("vpc", {}).get("configured"))
    if function_name == "evpn-route-reflector":
        state = config.get("rr_config", {}).get("evpn", {})
        if state.get("resolution_status") == "unresolved":
            return None
        return bool(state.get("configured"))
    if function_name == "underlay-route-reflector":
        state = config.get("rr_config", {}).get("underlay", {})
        if state.get("resolution_status") == "unresolved":
            return None
        return bool(state.get("configured"))
    return None


def _evaluate_function_expectation(
    snapshot: Mapping[str, Any],
    host: str,
    function_name: str,
    function: Mapping[str, Any],
) -> dict[str, Any]:
    check_ids = {
        "vtep": "vtep_function_expectation",
        "vpc": "vpc_function_expectation",
        "evpn-route-reflector": "evpn_rr_config_health",
        "underlay-route-reflector": "underlay_rr_config_health",
    }
    definition = {
        "id": check_ids.get(
            function_name, f"{function_name.replace('-', '_')}_config_health"
        ),
        "profile": "nxos-overlay",
    }
    config = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get("config")
    configured = _configured_function(config, function_name)
    evidence = _source_evidence(snapshot, host, "running_config")
    expectation = str(function["expectation"])
    if configured is None:
        rr_family = {
            "evpn-route-reflector": "evpn",
            "underlay-route-reflector": "underlay",
        }.get(function_name)
        rr_state = (
            config.get("rr_config", {}).get(rr_family, {})
            if config is not None and rr_family is not None
            else {}
        )
        reason_code = (
            "RR_TEMPLATE_UNRESOLVED"
            if rr_state.get("resolution_status") == "unresolved"
            else "CONFIG_EVIDENCE_UNAVAILABLE"
        )
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="UNKNOWN",
            classification="collection_error",
            message=f"{reason_code}: {function_name} configuration could not be resolved safely",
            evidence=evidence,
            resource=f"functions/{function_name}",
            after={
                "expectation": expectation,
                "configured": None,
                "source": function["source"],
                "reason_code": reason_code,
                "resolution_errors": rr_state.get("resolution_errors", []),
            },
        )
    if expectation == "required":
        result = "PASS" if configured else "FAIL"
    elif expectation == "forbidden":
        result = "FAIL" if configured else "PASS"
    else:
        result = "PASS" if configured else "NOT_APPLICABLE"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result in {"PASS", "NOT_APPLICABLE"} else "target_not_ready",
        message=f"{function_name} is {'configured' if configured else 'not configured'} (expectation: {expectation})",
        evidence=evidence,
        resource=f"functions/{function_name}",
        after={"expectation": expectation, "configured": configured, "source": function["source"]},
    )


SINGLE_EVALUATORS: dict[
    str,
    Callable[
        [Mapping[str, Any], str, Mapping[str, Any], Mapping[str, Any]],
        dict[str, Any],
    ],
] = {
    "collection_complete": _evaluate_collection,
    "system_identity": _evaluate_system,
    "hostname_identity": _evaluate_hostname_identity,
    "lldp_evidence_completeness": _evaluate_lldp_evidence_completeness,
    "lldp_description_consistency": _evaluate_lldp_description_consistency,
    "cpu_utilization": _evaluate_cpu,
    "memory_utilization": _evaluate_memory,
    "environment_health": _evaluate_environment,
    "clock_health": _evaluate_clock,
    "ntp_health": _evaluate_ntp,
    "interface_health": _evaluate_interfaces,
    "interface_error_health": _evaluate_interface_errors,
    "interface_utilization": _evaluate_interface_utilization,
    "port_channel_health": _evaluate_port_channels,
    "logging_health": _evaluate_logging,
    "running_config_diff": _evaluate_running_config_diff,
    "reload_pending": _evaluate_reload,
    "ipv4_route_count": _evaluate_route_count,
    "ospf_neighbor_health": _evaluate_ospf,
    "bgp_ipv4_health": _evaluate_bgp_ipv4,
    "bgp_dynamic_neighbor_health": _evaluate_bgp_dynamic_neighbors,
    "vpc_health": _evaluate_vpc,
    "nve_interface_health": _evaluate_nve,
    "evpn_bgp_health": _evaluate_evpn_bgp,
    "nve_peer_health": _evaluate_nve_peers,
    "nve_vni_health": _evaluate_nve_vnis,
    "evpn_route_health": _evaluate_evpn_routes,
    "vlan_operational_health": _evaluate_vlan_operational,
    "vrf_operational_health": _evaluate_vrf_operational,
    "svi_operational_health": _evaluate_svi_operational,
}


def _counts(checks: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        result.lower(): sum(1 for check in checks if check["result"] == result)
        for result in (
            "PASS",
            "WARN",
            "FAIL",
            "UNKNOWN",
            "NOT_APPLICABLE",
        )
    }


def _overall(checks: list[Mapping[str, Any]]) -> str:
    if not checks:
        return "NOT_APPLICABLE"
    return max(
        (str(check["result"]) for check in checks),
        key=lambda result: RESULT_ORDER[result],
    )


def _validate_inputs(
    snapshot: Mapping[str, Any],
    resolved_profiles: Mapping[str, Any],
) -> Mapping[str, Any]:
    validate_document(snapshot, kind="HealthSnapshot", allow_unknown_fields=True)
    validate_document(
        resolved_profiles,
        kind="ResolvedHealthCheckProfiles",
        allow_unknown_fields=True,
    )
    resolved = resolved_profiles["spec"]["resolved"]
    if snapshot["profile_sha256"] != resolved["effective_sha256"]:
        raise HealthEvaluationError("Snapshot profile hash mismatch")
    if snapshot["change_id"] != resolved_profiles["metadata"]["change_id"]:
        raise HealthEvaluationError("Snapshot change_id mismatch")
    return resolved["effective"]


def _overlay_check_applies(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    resolved_roles: Mapping[str, Any],
) -> bool:
    if resolved_roles["spec"]["role_schema_version"] == 1:
        return True
    evaluator = str(definition["evaluator"])
    functions = resolved_roles["spec"]["devices"][host]["functions"]
    config = snapshot["hosts"][host]["profiles"].get("nxos-overlay", {}).get(
        "config"
    )
    if evaluator in {"nve_interface_health", "nve_peer_health", "nve_vni_health", "vlan_operational_health", "vrf_operational_health", "svi_operational_health"}:
        return "vtep" in functions or _configured_function(config, "vtep") is True
    if evaluator in {
        "evpn_bgp_health",
        "evpn_route_health",
        "type5_prefix_propagation",
    }:
        return (
            "vtep" in functions
            or "evpn-route-reflector" in functions
            or bool(config and config.get("evpn_bgp_configured"))
        )
    return True


def _profile_platform_scope(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> tuple[bool, str, str, str]:
    """Resolve one check's platform scope without using driver names."""
    allowed = {
        str(item).lower()
        for item in definition.get("platforms", effective["spec"].get("platforms", []))
    }
    raw_platform = snapshot["hosts"][host].get("platform")
    if raw_platform is None and allowed == {"nxos"}:
        # v1 Snapshots created before platform provenance was added were
        # produced only by the NX-OS Health adapters.
        platform = "nxos"
    else:
        platform = str(raw_platform or "unknown").lower()
    if platform in {"", "unknown"}:
        return False, "UNKNOWN", "PROFILE_PLATFORM_UNRESOLVED", "unknown"
    if platform not in allowed:
        return False, "NOT_APPLICABLE", "PROFILE_PLATFORM_EXCLUDED", platform
    return True, "PASS", "PROFILE_PLATFORM_INCLUDED", platform


def _append_unexecuted_profile(
    target: list[dict[str, Any]],
    *,
    host: str,
    platform: str,
    topology_role: str | None,
    profile: str,
    profile_result: str,
    reason_code: str,
) -> None:
    if any(item["host"] == host and item["profile"] == profile for item in target):
        return
    target.append(
        {
            "host": host,
            "platform": platform,
            "topology_role": topology_role,
            "profile": profile,
            "profile_result": profile_result,
            "reason_code": reason_code,
            "message": (
                "Host platform is outside the profile scope."
                if reason_code == "PROFILE_PLATFORM_EXCLUDED"
                else "Host platform could not be resolved safely."
            ),
        }
    )


def evaluate_snapshot(
    snapshot: Mapping[str, Any],
    resolved_profiles: Mapping[str, Any],
    *,
    started_at: datetime,
    completed_at: datetime,
    resolved_roles: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one before/after Snapshot without prompting."""
    effective = _validate_inputs(snapshot, resolved_profiles)
    type5_route_indexes = (
        _build_type5_route_indexes(snapshot)
        if any(
            definition.get("evaluator") == "type5_prefix_propagation"
            for definition in effective["spec"]["checks"]
        )
        else None
    )
    checks: list[dict[str, Any]] = []
    unexecuted_hosts: list[dict[str, Any]] = []
    for host in sorted(snapshot["hosts"]):
        for definition in effective["spec"]["checks"]:
            profile_name = str(definition.get("profile", ""))
            execute_platform, platform_result, platform_reason, platform = (
                _profile_platform_scope(snapshot, host, definition, effective)
            )
            if not execute_platform:
                topology_role = None
                if resolved_roles is not None:
                    topology_role = resolved_roles["spec"]["devices"][host][
                        "topology_role"
                    ]
                _append_unexecuted_profile(
                    unexecuted_hosts,
                    host=host,
                    platform=platform,
                    topology_role=topology_role,
                    profile=profile_name,
                    profile_result=platform_result,
                    reason_code=platform_reason,
                )
                continue
            if resolved_roles is not None:
                role_data = resolved_roles["spec"]["devices"][host]
                if profile_name == "nxos-overlay":
                    execute, profile_result, reason_code = overlay_profile_scope(
                        resolved_roles,
                        host,
                    )
                    if not execute:
                        if not any(
                            item["host"] == host
                            and item["profile"] == profile_name
                            for item in unexecuted_hosts
                        ):
                            unexecuted_hosts.append(
                                {
                                    "host": host,
                                    "platform": "nxos",
                                    "topology_role": role_data["topology_role"],
                                    "profile": profile_name,
                                    "profile_result": profile_result,
                                    "reason_code": reason_code,
                                    "message": (
                                        "Topology role is outside the nxos-overlay scope."
                                        if reason_code == "PROFILE_ROLE_EXCLUDED"
                                        else "Topology role could not be resolved safely."
                                    ),
                                }
                            )
                        continue
                    if not _overlay_check_applies(
                        snapshot, host, definition, resolved_roles
                    ):
                        continue
                elif (
                    profile_name == "network-baseline-nxos"
                    and role_data["topology_role"] == "server"
                ):
                    if not any(
                        item["host"] == host and item["profile"] == profile_name
                        for item in unexecuted_hosts
                    ):
                        unexecuted_hosts.append(
                            {
                                "host": host,
                                "platform": "nxos",
                                "topology_role": "server",
                                "profile": profile_name,
                                "profile_result": "NOT_APPLICABLE",
                                "reason_code": "PROFILE_ROLE_EXCLUDED",
                                "message": "Server role is outside the NX-OS profile scope.",
                            }
                        )
                    continue
            evaluator_name = definition["evaluator"]
            evaluator = SINGLE_EVALUATORS.get(evaluator_name)
            if (
                resolved_roles is not None
                and profile_name == "nxos-overlay"
                and evaluator_name == "evpn_bgp_health"
                and resolved_roles["spec"]["role_schema_version"] == 2
            ):
                definition = deepcopy(definition)
                functions = resolved_roles["spec"]["devices"][host]["functions"]
                topology_role = resolved_roles["spec"]["devices"][host]["topology_role"]
                if "evpn-route-reflector" in functions:
                    definition["id"] = "evpn_rr_neighbor_health"
                elif topology_role == "border-gateway":
                    definition["id"] = "border_evpn_bgp_health"
            if evaluator_name == "type5_prefix_propagation":
                checks.append(
                    _evaluate_type5_prefix_propagation(
                        snapshot,
                        host,
                        definition,
                        resolved_roles,
                        type5_route_indexes,
                    )
                )
                continue
            if evaluator is None:
                checks.append(
                    _unknown(
                        definition,
                        host,
                        f"Evaluator is not implemented: {definition['evaluator']}",
                        [],
                    )
                )
                continue
            checks.append(evaluator(snapshot, host, definition, effective))
        if (
            resolved_roles is not None
            and resolved_roles["spec"]["role_schema_version"] == 2
        ):
            role_data = resolved_roles["spec"]["devices"][host]
            execute, _profile_result, _reason_code = overlay_profile_scope(
                resolved_roles, host
            )
            if execute:
                for function_name, function in sorted(
                    role_data["functions"].items()
                ):
                    checks.append(
                        _evaluate_function_expectation(
                            snapshot, host, function_name, function
                        )
                    )
    gate_reasons = [
        {
            "code": (
                (
                    "SUSTAINED_HIGH_CPU"
                    if check.get("after", {}).get("sustained")
                    else "HIGH_CPU"
                )
                if check["check_id"] == "cpu_utilization"
                else "RELOAD_PENDING_CONFIG_EXISTS"
            ),
            "host": check["host"],
            "message": check["message"],
        }
        for check in checks
        if check["result"] == "WARN"
        and check["check_id"] in {"cpu_utilization", "reload_pending"}
        and snapshot["phase"] == "before"
    ]
    blocking_gate_reasons = [
        reason
        for reason in gate_reasons
        if reason["code"] in {"SUSTAINED_HIGH_CPU", "RELOAD_PENDING_CONFIG_EXISTS"}
    ]
    overall = _overall(checks)
    if any(item["profile_result"] == "UNKNOWN" for item in unexecuted_hosts):
        if overall in {"PASS", "WARN", "NOT_APPLICABLE"}:
            overall = "UNKNOWN"
    result = {
        "schema_version": SCHEMA_VERSION,
        "change_id": snapshot["change_id"],
        "phase": snapshot["phase"],
        "timezone": snapshot.get("timezone", "Asia/Tokyo"),
        "profile_sha256": snapshot["profile_sha256"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "profiles": resolved_profiles["spec"]["resolved"]["profile_names"],
        "device_addresses": {
            host: str(host_data["address"])
            for host, host_data in sorted(snapshot["hosts"].items())
            if host_data.get("address")
        },
        "result": overall,
        "counts": _counts(checks),
        "checks": checks,
        "unexecuted_hosts": unexecuted_hosts,
        "operation_gate": {
            "required": bool(blocking_gate_reasons),
            "reasons": gate_reasons,
            "decision": None,
        },
        "artifacts": {},
    }
    validate_document(result, kind="HealthResult")
    return result


def _combined_evidence(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    identifier: str,
) -> list[dict[str, Any]]:
    return [
        *_source_evidence(before, host, identifier),
        *_source_evidence(after, host, identifier),
    ]


def _compare_logging(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    before_logging, before_unknown = _logging_or_unknown(
        before,
        host,
        definition,
    )
    after_logging, after_unknown = _logging_or_unknown(
        after,
        host,
        definition,
    )
    evidence = _combined_evidence(before, after, host, "show_logging")
    if before_unknown is not None or after_unknown is not None:
        messages = [
            item["message"]
            for item in (before_unknown, after_unknown)
            if item is not None
        ]
        return _unknown(
            definition,
            host,
            "before/after logging comparison is unavailable: " + "; ".join(messages),
            evidence,
            resource="system/logging",
        )
    assert before_logging is not None and after_logging is not None
    settings = _logging_settings(effective)
    before_upper = datetime.fromisoformat(before["created_at"])
    before_lower = _logging_lower_bound(settings, before_upper)
    after_upper = datetime.fromisoformat(after["created_at"])
    baseline_matches = _matched_logging_records(
        before_logging,
        settings,
        lower_bound=before_lower,
        upper_bound=before_upper,
    )
    work_matches = _matched_logging_records(
        after_logging,
        settings,
        lower_bound=before_upper,
        upper_bound=after_upper,
        lower_exclusive=True,
    )
    baseline_fingerprints = {record["fingerprint"] for record in baseline_matches}
    new_matches = [
        record
        for record in work_matches
        if record["fingerprint"] not in baseline_fingerprints
    ]
    if new_matches:
        result = "WARN"
        classification = "regression"
        message = (
            f"{len(new_matches)} new abnormal log record(s) were detected "
            "during the operation window"
        )
    elif baseline_matches:
        result = "PASS"
        classification = "pre_existing"
        message = "No new abnormal logs; only the before baseline was observed"
    else:
        result = "PASS"
        classification = "normal"
        message = "No abnormal logs were detected during the operation window"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=message,
        evidence=evidence,
        resource="system/logging",
        before={
            "time_range": settings["time_range"],
            "window_start": before_lower.isoformat() if before_lower else None,
            "window_end": before_upper.isoformat(),
            "matched_records": len(baseline_matches),
            "matches": baseline_matches,
        },
        after={
            "window_start": before_upper.isoformat(),
            "window_end": after_upper.isoformat(),
            "matched_records": len(new_matches),
            "matches": new_matches,
        },
    )


def _compare_system(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_system = before["hosts"][host]["common"].get("system")
    after_system = after["hosts"][host]["common"].get("system")
    evidence = _combined_evidence(
        before,
        after,
        host,
        "show_version",
    )
    if not before_system or not after_system:
        return _unknown(
            definition,
            host,
            "System identity is unavailable in before or after",
            evidence,
            resource="system",
        )
    before_uptime = before_system.get("uptime_seconds")
    after_uptime = after_system.get("uptime_seconds")
    if (
        before_uptime is not None
        and after_uptime is not None
        and after_uptime < before_uptime
    ):
        result = "FAIL"
        classification = "regression"
        message = "Device uptime decreased; an unexpected reload is possible"
    elif before_system.get("version") != after_system.get("version"):
        result = "WARN"
        classification = "unexpected_change"
        message = (
            f"NX-OS version changed {before_system.get('version')} -> "
            f"{after_system.get('version')}"
        )
    else:
        result = "PASS"
        classification = "normal"
        message = "System identity and uptime were preserved"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=message,
        evidence=evidence,
        resource="system",
        before=before_system,
        after=after_system,
    )


def _compare_reload(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_pending = before["hosts"][host]["common"].get("reload_pending")
    after_pending = after["hosts"][host]["common"].get("reload_pending")
    evidence = _combined_evidence(
        before,
        after,
        host,
        "reload_pending",
    )
    if before_pending is None or after_pending is None:
        return _unknown(
            definition,
            host,
            "reload-pending state is unavailable in before or after",
            evidence,
            resource="system/reload-pending",
        )
    before_commands = set(before_pending["commands"])
    after_commands = set(after_pending["commands"])
    added = sorted(after_commands - before_commands)
    if added:
        result = "FAIL"
        classification = "regression"
        message = "New reload-pending configuration was detected"
    elif after_commands:
        result = "WARN"
        classification = "pre_existing"
        message = "Only pre-existing reload-pending configuration remains"
    elif before_commands:
        result = "PASS"
        classification = "improvement"
        message = "Pre-existing reload-pending configuration was cleared"
    else:
        result = "PASS"
        classification = "normal"
        message = "No reload-pending configuration exists"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=message,
        evidence=evidence,
        resource="system/reload-pending",
        before=before_pending,
        after=after_pending,
    )


def _compare_interfaces(before, after, host, definition, effective):
    check = _evaluate_interfaces(after, host, definition, effective)
    before_value = before["hosts"][host]["common"].get("interfaces")
    after_value = after["hosts"][host]["common"].get("interfaces")
    if before_value is None or after_value is None:
        return check
    before_up = {name for name, item in before_value.items() if item.get("operational_state") == "up"}
    after_up = {name for name, item in after_value.items() if item.get("operational_state") == "up"}
    lost = sorted(before_up - after_up)
    check = deepcopy(check)
    check["before"] = before_value
    if lost:
        check.update(result="FAIL", classification="regression", message="Interface regression: " + ", ".join(lost))
    return check


def _compare_ntp(before, after, host, definition, effective):
    check = _evaluate_ntp(after, host, definition, effective)
    old = before["hosts"][host]["common"].get("ntp")
    new = after["hosts"][host]["common"].get("ntp")
    if old is None or new is None:
        return check
    def selected(value):
        detailed = value.get("peer_status", {}).get("peers", {})
        candidates = detailed or value.get("peers", {})
        return {
            address for address, peer in candidates.items() if peer.get("selected")
        }

    lost_peers = sorted(selected(old) - selected(new))
    check = deepcopy(check)
    check["before"] = old
    if (old.get("synchronized") and not new.get("synchronized")) or lost_peers:
        check.update(result="FAIL", classification="regression", message="NTP synchronization regression" + (": lost peer " + ", ".join(lost_peers) if lost_peers else ""))
    return check


def _compare_interface_errors(before, after, host, definition, effective):
    old = before["hosts"][host]["common"].get("interface_errors")
    new = after["hosts"][host]["common"].get("interface_errors")
    if old is None or new is None:
        return _evaluate_interface_errors(after, host, definition, effective)
    deltas: dict[str, dict[str, int]] = {}
    reset = False
    new_counter = False
    for interface, counters in new.items():
        for name, value in counters.items():
            previous = old.get(interface, {}).get(name)
            if previous is None:
                if value:
                    deltas.setdefault(interface, {})[name] = value
                    new_counter = True
                continue
            if value < previous:
                reset = True
            elif value > previous:
                deltas.setdefault(interface, {})[name] = value - previous
    evidence = [*_combined_evidence(before, after, host, "interface_errors")]
    if reset:
        return _unknown(definition, host, "Interface error counter decreased without a proven reset", evidence, resource="interfaces/errors")
    maximum = max((value for counters in deltas.values() for value in counters.values()), default=0)
    policy = effective["spec"].get("thresholds", {}).get("interface_errors", {})
    warn = int(policy.get("warn_delta", 1))
    fail = int(policy.get("fail_delta", 100))
    result = (
        "WARN"
        if new_counter
        else "FAIL"
        if maximum >= fail
        else "WARN"
        if maximum >= warn
        else "PASS"
    )
    return _check(check_id=definition["id"], profile=definition["profile"], host=host, result=result, classification="regression" if result != "PASS" else "normal", message=f"Maximum interface error counter delta is {maximum} (warn: {warn}, fail: {fail})", evidence=evidence, resource="interfaces/errors", before=old, after={"counters": new, "deltas": deltas})


def _compare_port_channels(before, after, host, definition, effective):
    check = _evaluate_port_channels(after, host, definition, effective)
    old = before["hosts"][host]["common"].get("port_channels")
    new = after["hosts"][host]["common"].get("port_channels")
    if old is None or new is None:
        return check
    lost: list[str] = []
    for name, channel in old.get("channels", {}).items():
        old_members = set(channel.get("bundled_members", []))
        new_channel = new.get("channels", {}).get(name, {})
        if channel.get("up") and not new_channel.get("up"):
            lost.append(name)
        lost.extend(f"{name}/{member}" for member in sorted(old_members - set(new_channel.get("bundled_members", []))))
    check = deepcopy(check)
    check["before"] = old
    if lost:
        check.update(result="FAIL", classification="regression", message="Port-channel regression: " + ", ".join(lost))
    return check


def _compare_environment(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_value = before["hosts"][host]["common"].get("environment")
    after_value = after["hosts"][host]["common"].get("environment")
    evidence = _combined_evidence(before, after, host, "environment")
    if before_value is None or after_value is None:
        return _unknown(
            definition,
            host,
            "Environment state is unavailable in before or after",
            evidence,
            resource="system/environment",
        )
    if not before_value.get("applicable", True) and not after_value.get(
        "applicable",
        True,
    ):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="Hardware environment sensors are unavailable",
            evidence=evidence,
            resource="system/environment",
        )
    result, classification = _compare_binary_health(
        bool(before_value.get("healthy")),
        bool(after_value.get("healthy")),
    )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=f"Environment health comparison result is {result}",
        evidence=evidence,
        resource="system/environment",
        before=before_value,
        after=after_value,
    )


def _compare_route_count(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    effective: Mapping[str, Any],
) -> dict[str, Any]:
    before_summary = (
        before["hosts"][host]["common"].get("routes", {}).get("ipv4_summary")
    )
    after_summary = after["hosts"][host]["common"].get("routes", {}).get("ipv4_summary")
    evidence = _combined_evidence(
        before,
        after,
        host,
        "route_summary_ipv4",
    )
    if not before_summary or not after_summary:
        return _unknown(
            definition,
            host,
            "IPv4 route summary is unavailable in before or after",
            evidence,
            resource="routing/ipv4",
        )
    before_vrfs = set(before_summary["vrfs"])
    after_vrfs = set(after_summary["vrfs"])
    removed_vrfs = sorted(before_vrfs - after_vrfs)
    if removed_vrfs:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="FAIL",
            classification="regression",
            message=("IPv4 route summary lost VRFs: " + ", ".join(removed_vrfs)),
            evidence=evidence,
            resource="routing/ipv4",
            before=before_summary,
            after=after_summary,
        )
    added_vrfs = sorted(after_vrfs - before_vrfs)
    policy = effective["spec"].get("thresholds", {}).get("route_count", {})
    warn_threshold = float(policy.get("warn_decrease_percent", 10))
    fail_threshold = float(policy.get("fail_decrease_percent", 30))
    decreases: dict[str, float] = {}
    for vrf, before_count in before_summary["vrfs"].items():
        initial = int(before_count["routes"])
        current = int(after_summary["vrfs"][vrf]["routes"])
        decrease = (
            ((initial - current) / initial) * 100
            if initial > 0 and current < initial
            else 0.0
        )
        decreases[vrf] = round(decrease, 2)
    maximum = max(decreases.values(), default=0.0)
    if maximum >= fail_threshold:
        result = "FAIL"
        classification = "regression"
    elif maximum >= warn_threshold:
        result = "WARN"
        classification = "regression"
    else:
        result = "PASS"
        classification = "normal"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=(
            f"Maximum IPv4 route-count decrease is {maximum:g}% "
            f"(warn: {warn_threshold:g}%, fail: {fail_threshold:g}%)"
            + ("; added VRFs: " + ", ".join(added_vrfs) if added_vrfs else "")
        ),
        evidence=evidence,
        resource="routing/ipv4",
        before=before_summary,
        after={**after_summary, "decrease_percent": decreases},
    )


def _ospf_full_set(value: Mapping[str, Any]) -> set[str]:
    return {
        f"{process_key}/{neighbor_id}"
        for process_key, process in value.get("processes", {}).items()
        for neighbor_id, neighbor in process.get("neighbors", {}).items()
        if neighbor.get("state") == "FULL"
    }


def _compare_ospf(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_value = (
        before["hosts"][host]["common"].get("routing_neighbors", {}).get("ospf")
    )
    after_value = (
        after["hosts"][host]["common"].get("routing_neighbors", {}).get("ospf")
    )
    evidence = _combined_evidence(before, after, host, "ospf_neighbors")
    if before_value is None and after_value is None:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="OSPF was not observed",
            evidence=evidence,
            resource="routing/ospf",
        )
    if before_value is None or after_value is None:
        return _unknown(
            definition,
            host,
            "OSPF state is unavailable in before or after",
            evidence,
            resource="routing/ospf",
        )
    lost = sorted(_ospf_full_set(before_value) - _ospf_full_set(after_value))
    result = "FAIL" if lost else "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="regression" if lost else "normal",
        message=(
            "All before OSPF FULL neighbors were preserved"
            if not lost
            else "OSPF FULL neighbors were lost: " + ", ".join(lost)
        ),
        evidence=evidence,
        resource="routing/ospf",
        before=before_value,
        after=after_value,
    )


def _bgp_ipv4_established_set(value: Mapping[str, Any]) -> set[str]:
    return {
        f"{vrf}/{address}"
        for vrf, summary in value.get("vrfs", {}).items()
        for address, neighbor in summary.get("neighbors", {}).items()
        if neighbor.get("state") == "Established"
    }


def _compare_bgp_ipv4(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_value = (
        before["hosts"][host]["common"].get("routing_neighbors", {}).get("bgp_ipv4")
    )
    after_value = (
        after["hosts"][host]["common"].get("routing_neighbors", {}).get("bgp_ipv4")
    )
    evidence = _combined_evidence(
        before,
        after,
        host,
        "bgp_ipv4_summary",
    )
    if before_value is None and after_value is None:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="IPv4 BGP was not observed",
            evidence=evidence,
            resource="routing/bgp-ipv4",
        )
    if before_value is None or after_value is None:
        return _unknown(
            definition,
            host,
            "IPv4 BGP state is unavailable in before or after",
            evidence,
            resource="routing/bgp-ipv4",
        )
    lost = sorted(
        _bgp_ipv4_established_set(before_value) - _bgp_ipv4_established_set(after_value)
    )
    result = "FAIL" if lost else "PASS"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="regression" if lost else "normal",
        message=(
            "All before IPv4 BGP Established peers were preserved"
            if not lost
            else "IPv4 BGP peers were lost: " + ", ".join(lost)
        ),
        evidence=evidence,
        resource="routing/bgp-ipv4",
        before=before_value,
        after=after_value,
    )


def _compare_binary_health(
    before_value: bool,
    after_value: bool,
) -> tuple[str, str]:
    if before_value and not after_value:
        return "FAIL", "regression"
    if not before_value and after_value:
        return "PASS", "improvement"
    if not after_value:
        return "FAIL", "pre_existing"
    return "PASS", "normal"


def _compare_vpc(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_vpc = before["hosts"][host]["common"].get("vpc")
    after_vpc = after["hosts"][host]["common"].get("vpc")
    evidence = _combined_evidence(before, after, host, "vpc_brief")
    if before_vpc is None and after_vpc is None:
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="vPC was not observed",
            evidence=evidence,
            resource="vpc",
        )
    if before_vpc is None or after_vpc is None:
        return _unknown(
            definition,
            host,
            "vPC applicability changed or could not be observed",
            evidence,
            resource="vpc",
        )
    if not before_vpc.get("applicable", True) and not after_vpc.get(
        "applicable",
        True,
    ):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="vPC is not configured",
            evidence=evidence,
            resource="vpc",
        )
    result, classification = _compare_binary_health(
        bool(before_vpc.get("healthy")),
        bool(after_vpc.get("healthy")),
    )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=f"vPC health comparison result is {result}",
        evidence=evidence,
        resource="vpc",
        before=before_vpc,
        after=after_vpc,
    )


def _compare_nve(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_nve = (
        before["hosts"][host]["profiles"].get("nxos-overlay", {}).get("nve_interface")
    )
    after_nve = (
        after["hosts"][host]["profiles"].get("nxos-overlay", {}).get("nve_interface")
    )
    evidence = _combined_evidence(before, after, host, "nve_interface")
    if before_nve is None or after_nve is None:
        before_config = (
            before["hosts"][host]["profiles"]
            .get("nxos-overlay", {})
            .get("config", {})
            .get("nve", {})
        )
        after_config = (
            after["hosts"][host]["profiles"]
            .get("nxos-overlay", {})
            .get("config", {})
            .get("nve", {})
        )
        if (
            before_config.get("configured") is False
            and after_config.get("configured") is False
        ):
            return _check(
                check_id=definition["id"],
                profile=definition["profile"],
                host=host,
                result="NOT_APPLICABLE",
                classification="normal",
                message="NVE is not configured",
                evidence=evidence,
                resource="nve",
            )
        return _unknown(
            definition,
            host,
            "NVE state is unavailable in before or after",
            evidence,
            resource="nve",
        )
    if not before_nve.get("applicable", True) and not after_nve.get(
        "applicable",
        True,
    ):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="NVE is not configured",
            evidence=evidence,
            resource="nve",
        )
    result, classification = _compare_binary_health(
        before_nve.get("state", "").lower() == "up",
        after_nve.get("state", "").lower() == "up",
    )
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=(
            f"NVE state changed {before_nve.get('state')} -> {after_nve.get('state')}"
        ),
        evidence=evidence,
        resource=f"nve/{after_nve.get('name', 'unknown')}",
        before=before_nve,
        after=after_nve,
    )


def _evpn_healthy(value: Mapping[str, Any]) -> bool:
    neighbors = value.get("neighbors", {})
    return bool(neighbors) and all(
        neighbor.get("state") == "Established" for neighbor in neighbors.values()
    )


def _compare_evpn(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    before_bgp = (
        before["hosts"][host]["profiles"].get("nxos-overlay", {}).get("evpn_bgp")
    )
    after_bgp = after["hosts"][host]["profiles"].get("nxos-overlay", {}).get("evpn_bgp")
    evidence = _combined_evidence(
        before,
        after,
        host,
        "bgp_l2vpn_evpn_summary",
    )
    if before_bgp is None or after_bgp is None:
        before_config = (
            before["hosts"][host]["profiles"]
            .get("nxos-overlay", {})
            .get("config", {})
        )
        after_config = (
            after["hosts"][host]["profiles"]
            .get("nxos-overlay", {})
            .get("config", {})
        )
        if (
            before_config.get("evpn_bgp_configured") is False
            and after_config.get("evpn_bgp_configured") is False
        ):
            return _check(
                check_id=definition["id"],
                profile=definition["profile"],
                host=host,
                result="NOT_APPLICABLE",
                classification="normal",
                message="EVPN BGP is not configured",
                evidence=[
                    *_combined_evidence(before, after, host, "running_config"),
                    *evidence,
                ],
                resource="bgp/evpn",
            )
        return _unknown(
            definition,
            host,
            "EVPN BGP state is unavailable in before or after",
            evidence,
            resource="bgp/evpn",
        )
    if not before_bgp.get("applicable", True) and not after_bgp.get(
        "applicable",
        True,
    ):
        return _check(
            check_id=definition["id"],
            profile=definition["profile"],
            host=host,
            result="NOT_APPLICABLE",
            classification="normal",
            message="EVPN BGP is not configured",
            evidence=evidence,
            resource="bgp/evpn",
        )
    result, classification = _compare_binary_health(
        _evpn_healthy(before_bgp),
        _evpn_healthy(after_bgp),
    )
    before_established = {
        address
        for address, neighbor in before_bgp.get("neighbors", {}).items()
        if neighbor.get("state") == "Established"
    }
    after_established = {
        address
        for address, neighbor in after_bgp.get("neighbors", {}).items()
        if neighbor.get("state") == "Established"
    }
    lost = sorted(before_established - after_established)
    if lost:
        result = "FAIL"
        classification = "regression"
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification=classification,
        message=(
            "EVPN BGP peers were preserved"
            if not lost and result == "PASS"
            else "EVPN BGP peer regression: " + ", ".join(lost)
        ),
        evidence=evidence,
        resource="bgp/evpn",
        before=before_bgp,
        after=after_bgp,
    )


def compare_snapshots(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    resolved_profiles: Mapping[str, Any],
    *,
    started_at: datetime,
    completed_at: datetime,
    resolved_roles: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare compatible before/after Snapshots and classify regressions."""
    effective = _validate_inputs(before, resolved_profiles)
    _validate_inputs(after, resolved_profiles)
    if before["change_id"] != after["change_id"]:
        raise HealthEvaluationError("before/after change_id mismatch")
    if before["profile_sha256"] != after["profile_sha256"]:
        raise HealthEvaluationError("before/after profile hash mismatch")
    if set(before["hosts"]) != set(after["hosts"]):
        raise HealthEvaluationError("before/after host set mismatch")
    before_links = before.get("link_evidence")
    after_links = after.get("link_evidence")
    if isinstance(before_links, Mapping) != isinstance(after_links, Mapping):
        raise HealthEvaluationError("before/after link evidence availability mismatch")
    if isinstance(before_links, Mapping) and isinstance(after_links, Mapping):
        if before_links.get("normalizer_version") != after_links.get(
            "normalizer_version"
        ):
            raise HealthEvaluationError("before/after link normalizer version mismatch")
        if before_links.get("builder_version") != after_links.get(
            "builder_version"
        ):
            raise HealthEvaluationError("before/after link builder version mismatch")
        if before_links.get("policy_hashes") != after_links.get("policy_hashes"):
            raise HealthEvaluationError("before/after link policy hash mismatch")

    type5_enabled = any(
        definition.get("evaluator") == "type5_prefix_propagation"
        for definition in effective["spec"]["checks"]
    )
    before_type5_route_indexes = (
        _build_type5_route_indexes(before) if type5_enabled else None
    )
    after_type5_route_indexes = (
        _build_type5_route_indexes(after) if type5_enabled else None
    )
    checks: list[dict[str, Any]] = []
    unexecuted_hosts: list[dict[str, Any]] = []
    for host in sorted(before["hosts"]):
        for definition in effective["spec"]["checks"]:
            profile_name = str(definition.get("profile", ""))
            execute_platform, platform_result, platform_reason, platform = (
                _profile_platform_scope(after, host, definition, effective)
            )
            if not execute_platform:
                topology_role = None
                if resolved_roles is not None:
                    topology_role = resolved_roles["spec"]["devices"][host][
                        "topology_role"
                    ]
                _append_unexecuted_profile(
                    unexecuted_hosts,
                    host=host,
                    platform=platform,
                    topology_role=topology_role,
                    profile=profile_name,
                    profile_result=platform_result,
                    reason_code=platform_reason,
                )
                continue
            if resolved_roles is not None:
                role_data = resolved_roles["spec"]["devices"][host]
                if profile_name == "nxos-overlay":
                    execute, profile_result, reason_code = overlay_profile_scope(
                        resolved_roles,
                        host,
                    )
                    if not execute:
                        if profile_result == "UNKNOWN":
                            raise HealthEvaluationError(
                                f"ROLE_SCOPE_INVALID: {host} topology role is unresolved"
                            )
                        if not any(
                            item["host"] == host and item["profile"] == profile_name
                            for item in unexecuted_hosts
                        ):
                            unexecuted_hosts.append(
                                {
                                    "host": host,
                                    "platform": "nxos",
                                    "topology_role": role_data["topology_role"],
                                    "profile": profile_name,
                                    "profile_result": profile_result,
                                    "reason_code": reason_code,
                                    "message": "Topology role is outside the nxos-overlay scope.",
                                }
                            )
                        continue
                    if not _overlay_check_applies(
                        after, host, definition, resolved_roles
                    ):
                        continue
                elif (
                    profile_name == "network-baseline-nxos"
                    and role_data["topology_role"] == "server"
                ):
                    if not any(
                        item["host"] == host and item["profile"] == profile_name
                        for item in unexecuted_hosts
                    ):
                        unexecuted_hosts.append(
                            {
                                "host": host,
                                "platform": "nxos",
                                "topology_role": "server",
                                "profile": profile_name,
                                "profile_result": "NOT_APPLICABLE",
                                "reason_code": "PROFILE_ROLE_EXCLUDED",
                                "message": "Server role is outside the NX-OS profile scope.",
                            }
                        )
                    continue
            evaluator_name = definition["evaluator"]
            if (
                resolved_roles is not None
                and profile_name == "nxos-overlay"
                and evaluator_name == "evpn_bgp_health"
                and resolved_roles["spec"]["role_schema_version"] == 2
            ):
                definition = deepcopy(definition)
                functions = resolved_roles["spec"]["devices"][host]["functions"]
                topology_role = resolved_roles["spec"]["devices"][host]["topology_role"]
                if "evpn-route-reflector" in functions:
                    definition["id"] = "evpn_rr_neighbor_health"
                elif topology_role == "border-gateway":
                    definition["id"] = "border_evpn_bgp_health"
            if evaluator_name == "system_identity":
                check = _compare_system(before, after, host, definition)
            elif evaluator_name == "hostname_identity":
                before_check = _evaluate_hostname_identity(
                    before, host, definition, effective
                )
                check = _evaluate_hostname_identity(
                    after, host, definition, effective
                )
                check["before"] = before_check.get("after", {
                    "result": before_check["result"],
                    "message": before_check["message"],
                })
                if before_check["result"] == "PASS" and check["result"] != "PASS":
                    check["classification"] = "regression"
                elif before_check["result"] != "PASS" and check["result"] == "PASS":
                    check["classification"] = "improvement"
                elif before_check["result"] == check["result"] == "FAIL":
                    check["classification"] = "pre_existing"
            elif evaluator_name in {
                "lldp_evidence_completeness",
                "lldp_description_consistency",
            }:
                evaluator = SINGLE_EVALUATORS[evaluator_name]
                before_check = evaluator(
                    before,
                    host,
                    definition,
                    effective,
                )
                check = evaluator(
                    after,
                    host,
                    definition,
                    effective,
                )
                check["before"] = before_check.get(
                    "after",
                    {
                        "result": before_check["result"],
                        "message": before_check["message"],
                    },
                )
                if RESULT_ORDER[check["result"]] > RESULT_ORDER[
                    before_check["result"]
                ]:
                    check["classification"] = "regression"
                elif RESULT_ORDER[check["result"]] < RESULT_ORDER[
                    before_check["result"]
                ]:
                    check["classification"] = "improvement"
                elif check["result"] in {"WARN", "FAIL", "UNKNOWN"}:
                    check["classification"] = "pre_existing"
            elif evaluator_name == "logging_health":
                check = _compare_logging(before, after, host, definition, effective)
            elif evaluator_name == "reload_pending":
                check = _compare_reload(before, after, host, definition)
            elif evaluator_name == "environment_health":
                check = _compare_environment(before, after, host, definition)
            elif evaluator_name == "interface_health":
                check = _compare_interfaces(before, after, host, definition, effective)
            elif evaluator_name == "ntp_health":
                check = _compare_ntp(before, after, host, definition, effective)
            elif evaluator_name == "interface_error_health":
                check = _compare_interface_errors(before, after, host, definition, effective)
            elif evaluator_name == "port_channel_health":
                check = _compare_port_channels(before, after, host, definition, effective)
            elif evaluator_name == "ipv4_route_count":
                check = _compare_route_count(
                    before,
                    after,
                    host,
                    definition,
                    effective,
                )
            elif evaluator_name == "ospf_neighbor_health":
                check = _compare_ospf(before, after, host, definition)
            elif evaluator_name == "bgp_ipv4_health":
                check = _compare_bgp_ipv4(
                    before,
                    after,
                    host,
                    definition,
                )
            elif evaluator_name == "vpc_health":
                check = _compare_vpc(before, after, host, definition)
            elif evaluator_name == "nve_interface_health":
                check = _compare_nve(before, after, host, definition)
            elif evaluator_name == "evpn_bgp_health":
                check = _compare_evpn(before, after, host, definition)
            elif evaluator_name in {"nve_peer_health", "nve_vni_health"}:
                evaluator = SINGLE_EVALUATORS[evaluator_name]
                check = evaluator(after, host, definition, effective)
                field = "nve_peers" if evaluator_name == "nve_peer_health" else "nve_vnis"
                member = "peers" if evaluator_name == "nve_peer_health" else "vnis"
                before_value = before["hosts"][host]["profiles"].get("nxos-overlay", {}).get(field)
                after_value = after["hosts"][host]["profiles"].get("nxos-overlay", {}).get(field)
                if before_value is not None and after_value is not None:
                    before_up = {
                        key
                        for key, value in before_value.get(member, {}).items()
                        if str(value.get("state", "")).lower() == "up"
                    }
                    after_up = {
                        key
                        for key, value in after_value.get(member, {}).items()
                        if str(value.get("state", "")).lower() == "up"
                    }
                    lost = sorted(before_up - after_up)
                    check["before"] = before_value
                    if lost:
                        check.update(
                            result="FAIL",
                            classification="regression",
                            message=f"{field} regression: " + ", ".join(lost),
                        )
            elif evaluator_name == "evpn_route_health":
                check = _evaluate_evpn_routes(after, host, definition, effective)
                before_value = before["hosts"][host]["profiles"].get("nxos-overlay", {}).get("evpn_routes")
                after_value = after["hosts"][host]["profiles"].get("nxos-overlay", {}).get("evpn_routes")
                if before_value is not None and after_value is not None:
                    lost = sorted(set(before_value.get("route_keys", [])) - set(after_value.get("route_keys", [])))
                    check["before"] = before_value
                    if lost:
                        check.update(
                            result="FAIL" if not after_value.get("route_count") else "WARN",
                            classification="regression",
                            message=f"EVPN route regression: {len(lost)} route(s) lost",
                        )
            elif evaluator_name == "type5_prefix_propagation":
                check = _evaluate_type5_prefix_propagation(
                    after,
                    host,
                    definition,
                    resolved_roles,
                    after_type5_route_indexes,
                )
                before_check = _evaluate_type5_prefix_propagation(
                    before,
                    host,
                    definition,
                    resolved_roles,
                    before_type5_route_indexes,
                )
                check["before"] = before_check.get("after", {
                    "result": before_check["result"],
                    "message": before_check["message"],
                })
                if before_check["result"] == "PASS" and check["result"] != "PASS":
                    check["classification"] = "regression"
            elif evaluator_name in {
                "vlan_operational_health",
                "vrf_operational_health",
                "svi_operational_health",
            }:
                evaluator = SINGLE_EVALUATORS[evaluator_name]
                before_check = evaluator(before, host, definition, effective)
                check = evaluator(after, host, definition, effective)
                check["before"] = before_check.get("after", {
                    "result": before_check["result"],
                    "message": before_check["message"],
                })
                if before_check["result"] == "PASS" and check["result"] != "PASS":
                    check["classification"] = "regression"
            else:
                evaluator = SINGLE_EVALUATORS.get(evaluator_name)
                if evaluator is None:
                    check = _unknown(
                        definition,
                        host,
                        f"Evaluator is not implemented: {evaluator_name}",
                        [],
                    )
                else:
                    check = evaluator(after, host, definition, effective)
                    if evaluator_name == "collection_complete":
                        before_check = evaluator(
                            before,
                            host,
                            definition,
                            effective,
                        )
                        if before_check["result"] != "PASS":
                            check = before_check
                    elif evaluator_name in {
                        "cpu_utilization",
                        "memory_utilization",
                        "interface_utilization",
                        "bgp_dynamic_neighbor_health",
                    }:
                        before_check = evaluator(
                            before,
                            host,
                            definition,
                            effective,
                        )
                        check = deepcopy(check)
                        check["before"] = before_check.get("after")
                        if RESULT_ORDER[check["result"]] > RESULT_ORDER[
                            before_check["result"]
                        ]:
                            check["classification"] = "regression"
                        elif RESULT_ORDER[check["result"]] < RESULT_ORDER[
                            before_check["result"]
                        ]:
                            check["classification"] = "improvement"
                        elif check["result"] in {"WARN", "FAIL", "UNKNOWN"}:
                            check["classification"] = "pre_existing"
                        if evaluator_name == "bgp_dynamic_neighbor_health":
                            before_ranges = {
                                (
                                    item.get("local_as"),
                                    item.get("vrf"),
                                    item.get("range"),
                                ): item
                                for item in (before_check.get("after") or {}).get(
                                    "ranges", []
                                )
                            }
                            lost_ranges = []
                            for item in (check.get("after") or {}).get("ranges", []):
                                key = (
                                    item.get("local_as"),
                                    item.get("vrf"),
                                    item.get("range"),
                                )
                                before_item = before_ranges.get(key, {})
                                if (
                                    before_item.get("established_neighbors")
                                    and not item.get("matched_neighbors")
                                ):
                                    lost_ranges.append(str(item.get("range")))
                            if lost_ranges:
                                check.update(
                                    result="FAIL",
                                    classification="regression",
                                    message=(
                                        "Dynamic BGP range regression; all observed "
                                        "neighbors disappeared: "
                                        + ", ".join(sorted(lost_ranges))
                                    ),
                                )
            checks.append(check)
        if (
            resolved_roles is not None
            and resolved_roles["spec"]["role_schema_version"] == 2
        ):
            role_data = resolved_roles["spec"]["devices"][host]
            execute, _profile_result, _reason_code = overlay_profile_scope(
                resolved_roles, host
            )
            if execute:
                for function_name, function in sorted(role_data["functions"].items()):
                    check = _evaluate_function_expectation(
                        after, host, function_name, function
                    )
                    before_config = before["hosts"][host]["profiles"].get("nxos-overlay", {}).get("config")
                    after_config = after["hosts"][host]["profiles"].get("nxos-overlay", {}).get("config")
                    before_configured = _configured_function(before_config, function_name)
                    after_configured = _configured_function(after_config, function_name)
                    check["before"] = {
                        "expectation": function["expectation"],
                        "configured": before_configured,
                    }
                    if before_configured is True and after_configured is False:
                        check.update(
                            result="FAIL",
                            classification="regression",
                            message=f"{function_name} configuration was removed",
                        )
                    checks.append(check)

    overall = _overall(checks)
    if any(item["profile_result"] == "UNKNOWN" for item in unexecuted_hosts):
        if overall in {"PASS", "WARN", "NOT_APPLICABLE"}:
            overall = "UNKNOWN"
    result = {
        "schema_version": SCHEMA_VERSION,
        "change_id": before["change_id"],
        "phase": "compare",
        "timezone": after.get("timezone", "Asia/Tokyo"),
        "profile_sha256": before["profile_sha256"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "profiles": resolved_profiles["spec"]["resolved"]["profile_names"],
        "device_addresses": {
            host: str(host_data["address"])
            for host, host_data in sorted(after["hosts"].items())
            if host_data.get("address")
        },
        "result": overall,
        "counts": _counts(checks),
        "checks": checks,
        "unexecuted_hosts": unexecuted_hosts,
        "operation_gate": {"required": False, "reasons": [], "decision": None},
        "artifacts": {},
    }
    validate_document(result, kind="HealthResult")
    return result
