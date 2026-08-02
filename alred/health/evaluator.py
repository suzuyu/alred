"""Initial common and NX-OS Overlay health evaluators."""

from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
from typing import Any, Callable, Mapping

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
    return _check(
        check_id=definition["id"],
        profile=definition["profile"],
        host=host,
        result=result,
        classification="normal" if result == "PASS" else "target_not_ready",
        message=(
            "Environment sensors are healthy"
            if result == "PASS"
            else "Environment alarm was detected"
        ),
        evidence=evidence,
        resource="system/environment",
        after=environment,
    )


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


def _evaluate_bgp_ipv4(
    snapshot: Mapping[str, Any],
    host: str,
    definition: Mapping[str, Any],
    _effective_profile: Mapping[str, Any],
) -> dict[str, Any]:
    bgp = snapshot["hosts"][host]["common"].get("routing_neighbors", {}).get("bgp_ipv4")
    evidence = _source_evidence(snapshot, host, "bgp_ipv4_summary")
    if bgp is None:
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


SINGLE_EVALUATORS: dict[
    str,
    Callable[
        [Mapping[str, Any], str, Mapping[str, Any], Mapping[str, Any]],
        dict[str, Any],
    ],
] = {
    "collection_complete": _evaluate_collection,
    "system_identity": _evaluate_system,
    "cpu_utilization": _evaluate_cpu,
    "memory_utilization": _evaluate_memory,
    "environment_health": _evaluate_environment,
    "logging_health": _evaluate_logging,
    "reload_pending": _evaluate_reload,
    "ipv4_route_count": _evaluate_route_count,
    "ospf_neighbor_health": _evaluate_ospf,
    "bgp_ipv4_health": _evaluate_bgp_ipv4,
    "vpc_health": _evaluate_vpc,
    "nve_interface_health": _evaluate_nve,
    "evpn_bgp_health": _evaluate_evpn_bgp,
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


def evaluate_snapshot(
    snapshot: Mapping[str, Any],
    resolved_profiles: Mapping[str, Any],
    *,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    """Evaluate one before/after Snapshot without prompting."""
    effective = _validate_inputs(snapshot, resolved_profiles)
    checks: list[dict[str, Any]] = []
    for host in sorted(snapshot["hosts"]):
        for definition in effective["spec"]["checks"]:
            evaluator = SINGLE_EVALUATORS.get(definition["evaluator"])
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
    result = {
        "schema_version": SCHEMA_VERSION,
        "change_id": snapshot["change_id"],
        "phase": snapshot["phase"],
        "timezone": snapshot.get("timezone", "Asia/Tokyo"),
        "profile_sha256": snapshot["profile_sha256"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "profiles": resolved_profiles["spec"]["resolved"]["profile_names"],
        "result": _overall(checks),
        "counts": _counts(checks),
        "checks": checks,
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

    checks: list[dict[str, Any]] = []
    for host in sorted(before["hosts"]):
        for definition in effective["spec"]["checks"]:
            evaluator_name = definition["evaluator"]
            if evaluator_name == "system_identity":
                check = _compare_system(before, after, host, definition)
            elif evaluator_name == "logging_health":
                check = _compare_logging(before, after, host, definition, effective)
            elif evaluator_name == "reload_pending":
                check = _compare_reload(before, after, host, definition)
            elif evaluator_name == "environment_health":
                check = _compare_environment(before, after, host, definition)
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
                    }:
                        before_check = evaluator(
                            before,
                            host,
                            definition,
                            effective,
                        )
                        check = deepcopy(check)
                        check["before"] = before_check.get("after")
                        if check["result"] in {"WARN", "FAIL"}:
                            check["classification"] = (
                                "pre_existing"
                                if before_check["result"] in {"WARN", "FAIL"}
                                else "regression"
                            )
                        elif before_check["result"] in {"WARN", "FAIL"}:
                            check["classification"] = "improvement"
            checks.append(check)

    result = {
        "schema_version": SCHEMA_VERSION,
        "change_id": before["change_id"],
        "phase": "compare",
        "timezone": after.get("timezone", "Asia/Tokyo"),
        "profile_sha256": before["profile_sha256"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "profiles": resolved_profiles["spec"]["resolved"]["profile_names"],
        "result": _overall(checks),
        "counts": _counts(checks),
        "checks": checks,
        "operation_gate": {"required": False, "reasons": [], "decision": None},
        "artifacts": {},
    }
    validate_document(result, kind="HealthResult")
    return result
