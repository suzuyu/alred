"""Human-readable Health Result renderers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def _duration_line(result: Mapping[str, Any]) -> str:
    """Render a deterministic elapsed duration from Health Result timestamps."""
    started = datetime.fromisoformat(str(result["started_at"]))
    completed = datetime.fromisoformat(str(result["completed_at"]))
    elapsed = int((completed - started).total_seconds())
    if elapsed < 0:
        raise ValueError("Health Result completed_at is before started_at")
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"- Duration: {hours:02d}:{minutes:02d}:{seconds:02d} ({elapsed} seconds)"


def render_health_summary(result: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary from a validated HealthResult."""
    lines = [
        "# Health Check Summary",
        "",
        f"- Change ID: {result['change_id']}",
        f"- Phase: {result['phase']}",
        f"- Started at: {result['started_at']}",
        f"- Completed at: {result['completed_at']}",
        _duration_line(result),
        f"- Profiles: {', '.join(result['profiles'])}",
        f"- Result: {result['result']}",
        "",
        "## Result counts",
        "",
        "| Result | Count |",
        "|---|---:|",
    ]
    for key, label in (
        ("pass", "PASS"),
        ("warn", "WARN"),
        ("fail", "FAIL"),
        ("unknown", "UNKNOWN"),
        ("not_applicable", "NOT_APPLICABLE"),
    ):
        lines.append(f"| {label} | {result['counts'][key]} |")
    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Host | Check | Result | Classification | Detail |",
            "|---|---|---|---|---|",
        ]
    )
    findings = [check for check in result["checks"] if check["result"] != "PASS"]
    if findings:
        for check in findings:
            message = str(check["message"]).replace("|", "\\|")
            lines.append(
                f"| {check['host']} | {check['check_id']} | "
                f"{check['result']} | {check['classification']} | "
                f"{message} |"
            )
    else:
        lines.append("| - | - | PASS | normal | No findings |")
    return "\n".join(lines) + "\n"


def render_health_checklist(result: Mapping[str, Any]) -> str:
    """Render deterministic checklist sections grouped by device and profile."""
    lines = [
        "# Health Check Checklist",
        "",
        f"- Started at: {result['started_at']}",
        f"- Completed at: {result['completed_at']}",
        _duration_line(result),
        f"- Change ID: {result['change_id']}",
        f"- Phase: {result['phase']}",
        f"- Result: {result['result']}",
        "",
        "## Result by Profile",
        "",
        "| Profile | PASS | WARN | FAIL | UNKNOWN | N/A |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    markers = {
        "PASS": "x",
        "NOT_APPLICABLE": "-",
        "WARN": " ",
        "FAIL": " ",
        "UNKNOWN": " ",
        "PLAN_ERROR": " ",
    }
    resolved_profile_order = list(result.get("profiles", []))
    profiles_with_checks = {
        str(check.get("profile") or "unknown") for check in result["checks"]
    }
    profile_order = [
        profile
        for profile in resolved_profile_order
        if profile in profiles_with_checks
    ]
    for check in result["checks"]:
        profile = str(check.get("profile") or "unknown")
        if profile not in profile_order:
            profile_order.append(profile)
    for profile in profile_order:
        profile_checks = [
            check
            for check in result["checks"]
            if str(check.get("profile") or "unknown") == profile
        ]
        counts = {
            status: sum(check["result"] == status for check in profile_checks)
            for status in ("PASS", "WARN", "FAIL", "UNKNOWN", "NOT_APPLICABLE")
        }
        lines.append(
            f"| {profile} | {counts['PASS']} | {counts['WARN']} | "
            f"{counts['FAIL']} | {counts['UNKNOWN']} | {counts['NOT_APPLICABLE']} |"
        )

    lines.extend(["", "### WARN / FAIL / UNKNOWN Items", ""])
    finding_rows: list[tuple[str, str, str, list[str]]] = []
    for profile in profile_order:
        for status in ("WARN", "FAIL", "UNKNOWN"):
            check_hosts: dict[str, set[str]] = {}
            for check in result["checks"]:
                check_profile = str(check.get("profile") or "unknown")
                if check_profile != profile or check["result"] != status:
                    continue
                check_hosts.setdefault(str(check["check_id"]), set()).add(
                    str(check["host"])
                )
            finding_rows.extend(
                (profile, status, check_id, sorted(hosts))
                for check_id, hosts in check_hosts.items()
            )
    if finding_rows:
        lines.extend(
            [
                "| Profile | Result | Check | Hosts |",
                "|---|---|---|---|",
            ]
        )
        for profile, status, check_id, hosts in finding_rows:
            values = (profile, status, check_id, ", ".join(hosts))
            escaped = [str(value).replace("|", "\\|") for value in values]
            lines.append("| " + " | ".join(escaped) + " |")
    else:
        lines.append("- None")

    lines.extend(["", "## Checks", ""])
    checks_by_host: dict[str, list[Mapping[str, Any]]] = {}
    for check in result["checks"]:
        checks_by_host.setdefault(str(check["host"]), []).append(check)
    if not checks_by_host:
        lines.append("- No checks.")
    device_addresses = result.get("device_addresses", {})
    for host in sorted(checks_by_host):
        address = str(device_addresses.get(host, "")).strip()
        heading = f"### Device: `{host}`"
        if address:
            heading += f" ({address})"
        lines.extend([heading, ""])
        for profile in profile_order:
            profile_checks = [
                check
                for check in checks_by_host[host]
                if str(check.get("profile") or "unknown") == profile
            ]
            if not profile_checks:
                continue
            lines.extend([f"#### Profile: `{profile}`", ""])
            for check in profile_checks:
                marker = markers[check["result"]]
                message = " ".join(str(check["message"]).splitlines())
                display_result = check.get("display_severity", check["result"])
                lines.append(
                    f"- [{marker}] `{check['check_id']}`: {display_result} - {message}"
                )
            lines.append("")
    lines.extend(["## Unexecuted Hosts", ""])
    unexecuted = sorted(
        result.get("unexecuted_hosts", []),
        key=lambda item: (
            str(item["host"]),
            str(item["profile"]),
            str(item["reason_code"]),
        ),
    )
    if not unexecuted:
        lines.append("- None")
    else:
        lines.extend(
            [
                "| Host | Platform | Topology Role | Profile | Result | Reason Code | Reason |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for item in unexecuted:
            values = [
                item["host"],
                item["platform"],
                item.get("topology_role") or "-",
                item["profile"],
                item["profile_result"],
                item["reason_code"],
                item["message"],
            ]
            escaped = [str(value).replace("|", "\\|") for value in values]
            lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines).rstrip() + "\n"


def terminal_result_lines(result: Mapping[str, Any]) -> list[str]:
    """Return concise terminal lines without artifact-specific paths."""
    return [
        f"Change ID : {result['change_id']}",
        f"Phase     : {result['phase']}",
        f"Result    : {result['result']}",
        (
            "Checks    : "
            f"PASS={result['counts']['pass']} "
            f"WARN={result['counts']['warn']} "
            f"FAIL={result['counts']['fail']} "
            f"UNKNOWN={result['counts']['unknown']} "
            f"N/A={result['counts']['not_applicable']}"
        ),
    ]


def render_overlay_summary(result: Mapping[str, Any]) -> str:
    """Render configuration/operational/impact Overlay findings."""
    lines = [
        "# Overlay Health Summary",
        "",
        f"- Change ID: {result['change_id']}",
        f"- Source: {result['source']}",
        f"- Result: {result['result']}",
        "",
        "## Sections",
        "",
        "| Section | Result |",
        "|---|---|",
    ]
    for section in ("configuration", "operational", "impact"):
        lines.append(f"| {section.upper()} | {result['sections'][section]} |")
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Host | Section | Resource | Result | Detail |",
            "|---|---|---|---|---|",
        ]
    )
    for check in result["checks"]:
        message = str(check["message"]).replace("|", "\\|")
        lines.append(
            f"| {check['host']} | {check['section']} | "
            f"{check['resource']} | {check['result']} | {message} |"
        )
    if result.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for warning in result["warnings"]:
            lines.append(
                f"- {warning.get('reason', 'warning')}: {warning.get('message', '')}"
            )
    return "\n".join(lines) + "\n"
