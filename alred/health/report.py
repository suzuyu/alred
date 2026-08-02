"""Human-readable Health Result renderers."""

from __future__ import annotations

from typing import Any, Mapping


def render_health_summary(result: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary from a validated HealthResult."""
    lines = [
        "# Health Check Summary",
        "",
        f"- Change ID: {result['change_id']}",
        f"- Phase: {result['phase']}",
        f"- Started at: {result['started_at']}",
        f"- Completed at: {result['completed_at']}",
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
    """Render deterministic checklist sections grouped by device."""
    lines = [
        "# Health Check Checklist",
        "",
        f"- Started at: {result['started_at']}",
        f"- Completed at: {result['completed_at']}",
        f"- Change ID: {result['change_id']}",
        f"- Phase: {result['phase']}",
        f"- Result: {result['result']}",
        "",
        "## Checks",
        "",
    ]
    markers = {
        "PASS": "x",
        "NOT_APPLICABLE": "-",
        "WARN": " ",
        "FAIL": " ",
        "UNKNOWN": " ",
        "PLAN_ERROR": " ",
    }
    checks_by_host: dict[str, list[Mapping[str, Any]]] = {}
    for check in result["checks"]:
        checks_by_host.setdefault(str(check["host"]), []).append(check)
    if not checks_by_host:
        lines.append("- No checks.")
    for host in sorted(checks_by_host):
        lines.extend([f"### Device: `{host}`", ""])
        for check in checks_by_host[host]:
            marker = markers[check["result"]]
            message = " ".join(str(check["message"]).splitlines())
            lines.append(
                f"- [{marker}] `{check['check_id']}`: {check['result']} - {message}"
            )
        lines.append("")
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
