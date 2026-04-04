"""
Helpers for check-logging parsing and report rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import List, Optional

NXOS_LOG_RECORD_START_RE = re.compile(
    r"^(?P<timestamp>\d{4}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
)
NXOS_SEVERITY_RE = re.compile(r"%[A-Z0-9_]+-(?P<severity>[0-7])-[A-Z0-9_]+:")


@dataclass
class LoggingWarning:
    """
    Warning emitted during collection or parsing.
    """

    hostname: str
    warning_type: str
    message: str
    raw_source: str
    timestamp_text: Optional[str] = None
    timestamp: Optional[datetime] = None
    record_text: Optional[str] = None


@dataclass
class LoggingRecord:
    """
    One normalized show logging record.
    """

    timestamp_text: Optional[str]
    timestamp: Optional[datetime]
    severity: Optional[int]
    raw_lines: List[str]
    normalized_text: str
    parse_warning_messages: List[str] = field(default_factory=list)


@dataclass
class LoggingMatch:
    """
    One matched log record with reasons.
    """

    hostname: str
    raw_source: str
    timestamp_text: Optional[str]
    severity: Optional[int]
    match_reasons: List[str]
    raw_lines: List[str]
    parse_warning_messages: List[str] = field(default_factory=list)


@dataclass
class HostLoggingCheckResult:
    """
    Per-host logging check result.
    """

    hostname: str
    device_type: str
    raw_source: str
    total_records: int = 0
    in_range_records: int = 0
    excluded_records: int = 0
    severity_matched: int = 0
    check_string_matched: int = 0
    matches: List[LoggingMatch] = field(default_factory=list)
    warnings: List[LoggingWarning] = field(default_factory=list)
    skipped: bool = False

    @property
    def matched_records(self) -> int:
        return len(self.matches)

    @property
    def timestamp_parse_warnings(self) -> int:
        return sum(1 for item in self.warnings if item.warning_type == "timestamp_parse")

    @property
    def severity_parse_warnings(self) -> int:
        return sum(1 for item in self.warnings if item.warning_type == "severity_parse")

    @property
    def section_warnings(self) -> int:
        return sum(1 for item in self.warnings if item.warning_type in {"section", "collect", "unsupported"})


def parse_last_window(amount: int, unit: str) -> timedelta:
    """
    Convert CLI --last pair into timedelta.
    """

    if amount < 0:
        raise ValueError("--last value must be zero or greater")

    normalized_unit = unit.lower()
    if normalized_unit in {"day", "days"}:
        return timedelta(days=amount)
    if normalized_unit in {"hour", "hours"}:
        return timedelta(hours=amount)
    if normalized_unit in {"minute", "minutes"}:
        return timedelta(minutes=amount)
    raise ValueError(f"Unsupported --last unit: {unit}")


def load_check_patterns(path: str | None) -> List[str]:
    """
    Load case-insensitive substring patterns from file.
    """

    if not path:
        return []

    patterns: List[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def extract_latest_show_logging_block(hostname: str, text: str, raw_source: str) -> tuple[Optional[str], List[LoggingWarning]]:
    """
    Extract the latest `### COMMAND: show logging` section body from _shows.log.
    """

    warnings: List[LoggingWarning] = []
    command_marker = "### COMMAND: show logging"
    prompt_marker = f"{hostname}# show logging"

    starts = [idx for idx, line in enumerate(text.splitlines()) if line.strip() == command_marker]
    if not starts:
        warnings.append(
            LoggingWarning(
                hostname=hostname,
                warning_type="section",
                message="show logging section not found",
                raw_source=raw_source,
            )
        )
        return None, warnings

    lines = text.splitlines()
    start_idx = starts[-1]
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].startswith("### COMMAND:"):
            end_idx = idx
            break

    section_lines = lines[start_idx:end_idx]
    for idx, line in enumerate(section_lines):
        if line.strip() == prompt_marker:
            body = "\n".join(section_lines[idx + 1:]).strip("\n")
            return body, warnings

    warnings.append(
        LoggingWarning(
            hostname=hostname,
            warning_type="section",
            message=f"show logging prompt marker not found: {prompt_marker}",
            raw_source=raw_source,
        )
    )
    return None, warnings


def parse_nxos_log_records(hostname: str, text: str, raw_source: str, tzinfo) -> tuple[List[LoggingRecord], List[LoggingWarning]]:
    """
    Split NX-OS show logging text into records.
    """

    records: List[LoggingRecord] = []
    warnings: List[LoggingWarning] = []
    current_lines: List[str] = []

    def parse_timestamp_text(timestamp_text: str) -> Optional[datetime]:
        try:
            return datetime.strptime(timestamp_text, "%Y %b %d %H:%M:%S").replace(tzinfo=tzinfo)
        except ValueError:
            return None

    def flush_record() -> None:
        nonlocal current_lines
        if not current_lines:
            return

        header = current_lines[0]
        timestamp_text: Optional[str] = None
        timestamp: Optional[datetime] = None
        severity: Optional[int] = None
        parse_warning_messages: List[str] = []

        timestamp_match = NXOS_LOG_RECORD_START_RE.match(header)
        if timestamp_match:
            timestamp_text = timestamp_match.group("timestamp")
            timestamp = parse_timestamp_text(timestamp_text)
            if timestamp is None:
                message = f"timestamp parse failed: {timestamp_text}"
                parse_warning_messages.append(message)
                warnings.append(
                    LoggingWarning(
                        hostname=hostname,
                        warning_type="timestamp_parse",
                        message=message,
                        raw_source=raw_source,
                        timestamp_text=timestamp_text,
                        timestamp=None,
                        record_text="\n".join(current_lines),
                    )
                )
        else:
            message = "timestamp not found in record header"
            parse_warning_messages.append(message)
            warnings.append(
                LoggingWarning(
                    hostname=hostname,
                    warning_type="timestamp_parse",
                    message=message,
                    raw_source=raw_source,
                    record_text="\n".join(current_lines),
                )
            )

        severity_match = NXOS_SEVERITY_RE.search(header)
        if severity_match:
            severity = int(severity_match.group("severity"))
        else:
            message = "severity not found in record header"
            parse_warning_messages.append(message)
            warnings.append(
                    LoggingWarning(
                        hostname=hostname,
                        warning_type="severity_parse",
                        message=message,
                        raw_source=raw_source,
                        timestamp_text=timestamp_text,
                        timestamp=timestamp,
                        record_text="\n".join(current_lines),
                    )
                )

        records.append(
            LoggingRecord(
                timestamp_text=timestamp_text,
                timestamp=timestamp,
                severity=severity,
                raw_lines=current_lines[:],
                normalized_text="".join(current_lines),
                parse_warning_messages=parse_warning_messages,
            )
        )
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if NXOS_LOG_RECORD_START_RE.match(line):
            flush_record()
            current_lines = [line]
            continue
        if not current_lines:
            continue
        current_lines.append(line)

    flush_record()
    return records, warnings


def check_host_logging(
    hostname: str,
    device_type: str,
    raw_source: str,
    text: Optional[str],
    started_at: datetime,
    last_window: Optional[timedelta],
    severity: int,
    check_patterns: List[str],
    exclude_patterns: List[str],
) -> HostLoggingCheckResult:
    """
    Evaluate one host's show logging body text.
    """

    result = HostLoggingCheckResult(hostname=hostname, device_type=device_type, raw_source=raw_source)
    if text is None:
        return result

    records, warnings = parse_nxos_log_records(hostname, text, raw_source, started_at.tzinfo)
    result.warnings.extend(warnings)
    result.total_records = len(records)

    severity_reason = f"severity<={severity}"
    lowered_patterns = [(pattern, pattern.lower()) for pattern in check_patterns]
    lowered_exclude_patterns = [(pattern, pattern.lower()) for pattern in exclude_patterns]
    lower_bound = started_at - last_window if last_window is not None else None

    for record in records:
        in_range = True
        if lower_bound is not None:
            in_range = record.timestamp is not None and lower_bound <= record.timestamp <= started_at
        if in_range:
            result.in_range_records += 1

        if not in_range:
            continue

        matched_exclude_patterns = [
            original
            for original, lowered in lowered_exclude_patterns
            if lowered in record.normalized_text.lower()
        ]
        if matched_exclude_patterns:
            result.excluded_records += 1
            continue

        matched_by_severity = record.severity is not None and record.severity <= severity
        matched_patterns = [
            original
            for original, lowered in lowered_patterns
            if lowered in record.normalized_text.lower()
        ]

        if matched_by_severity:
            result.severity_matched += 1
        if matched_patterns:
            result.check_string_matched += 1

        if not matched_by_severity and not matched_patterns:
            continue

        match_reasons: List[str] = []
        if matched_by_severity:
            match_reasons.append(severity_reason)
        match_reasons.extend([f"check-string:{pattern}" for pattern in matched_patterns])

        result.matches.append(
            LoggingMatch(
                hostname=hostname,
                raw_source=raw_source,
                timestamp_text=record.timestamp_text,
                severity=record.severity,
                match_reasons=match_reasons,
                raw_lines=record.raw_lines,
                parse_warning_messages=record.parse_warning_messages,
            )
        )

    return result


def render_check_logging_report(
    started_at: datetime,
    mode: str,
    output_root: str,
    last_label: str,
    results: List[HostLoggingCheckResult],
    last_window: Optional[timedelta] = None,
) -> List[str]:
    """
    Render full text report.
    """

    processed_hosts = [item for item in results if not item.skipped]
    skipped_hosts = [item for item in results if item.skipped]
    total_records = sum(item.total_records for item in processed_hosts)
    in_range_records = sum(item.in_range_records for item in processed_hosts)
    excluded_records = sum(item.excluded_records for item in processed_hosts)
    severity_matched = sum(item.severity_matched for item in processed_hosts)
    check_string_matched = sum(item.check_string_matched for item in processed_hosts)
    matched_records = sum(item.matched_records for item in processed_hosts)
    timestamp_warnings = sum(item.timestamp_parse_warnings for item in results)
    severity_warnings = sum(item.severity_parse_warnings for item in results)
    section_warnings = sum(item.section_warnings for item in results)

    lines = [
        "### CHECK LOGGING SUMMARY",
        f"### STARTED_AT: {started_at.isoformat(timespec='seconds')}",
        f"### RAW_DIR: {output_root}",
        f"### MODE: {mode}",
        f"### LAST: {last_label}",
        f"### TARGET_HOSTS: {len(results)}",
        f"### PROCESSED_HOSTS: {len(processed_hosts)}",
        f"### SKIPPED_HOSTS: {len(skipped_hosts)}",
        f"### TOTAL_RECORDS: {total_records}",
        f"### IN_RANGE_RECORDS: {in_range_records}",
        f"### EXCLUDED_RECORDS: {excluded_records}",
        f"### SEVERITY_MATCHED: {severity_matched}",
        f"### CHECK_STRING_MATCHED: {check_string_matched}",
        f"### MATCHED_RECORDS: {matched_records}",
        f"### TIMESTAMP_PARSE_WARNINGS: {timestamp_warnings}",
        f"### SEVERITY_PARSE_WARNINGS: {severity_warnings}",
        f"### SECTION_WARNINGS: {section_warnings}",
        "",
        "### HOST LOGGING CHECK SUMMARY",
    ]

    for item in sorted(results, key=lambda x: x.hostname):
        if item.matched_records > 0:
            lines.append(f"{item.hostname} : Check Matched {item.matched_records}")
        else:
            lines.append(f"{item.hostname} : OK")

    lines.extend(["", "### HOST RESULT SUMMARY"])
    for item in sorted(results, key=lambda x: x.hostname):
        lines.append(
            f"- {item.hostname}: total={item.total_records} in_range={item.in_range_records} "
            f"excluded={item.excluded_records} matched={item.matched_records} severity_warn={item.severity_parse_warnings} "
            f"timestamp_warn={item.timestamp_parse_warnings}"
            + (" skipped=yes" if item.skipped else "")
        )

    lines.extend(["", "### MATCHED LOGS"])
    if matched_records == 0:
        lines.append("No matched log records.")
    else:
        for item in sorted(results, key=lambda x: x.hostname):
            for match in item.matches:
                lines.extend([
                    "",
                    f"### HOST: {match.hostname}",
                    f"### MATCH_REASON: {','.join(match.match_reasons)}",
                    f"### TIMESTAMP: {match.timestamp_text or 'unknown'}",
                    f"### SEVERITY: {match.severity if match.severity is not None else 'unknown'}",
                    f"### RAW_SOURCE: {match.raw_source}",
                ])
                for message in match.parse_warning_messages:
                    lines.append(f"### PARSE_WARNING: {message}")
                lines.extend(match.raw_lines)

    lines.extend(["", "### PARSE WARNINGS"])
    rendered_warnings = 0
    lower_bound = started_at - last_window if last_window is not None else None
    for item in sorted(results, key=lambda x: x.hostname):
        for warning in item.warnings:
            if lower_bound is not None and warning.timestamp is not None:
                if not (lower_bound <= warning.timestamp <= started_at):
                    continue
            rendered_warnings += 1
            lines.extend([
                "",
                f"### HOST: {warning.hostname}",
                f"### WARNING_TYPE: {warning.warning_type}",
                f"### WARNING: {warning.message}",
                f"### RAW_SOURCE: {warning.raw_source}",
            ])
            if warning.timestamp_text:
                lines.append(f"### TIMESTAMP: {warning.timestamp_text}")
            if warning.record_text:
                lines.append(warning.record_text)
    if rendered_warnings == 0:
        lines.append("No parse warnings.")

    return lines
