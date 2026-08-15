"""Common, value-free secret detection and sanitization for text artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .schema import canonical_sha256


CATALOG_VERSION = 1
ENGINE_VERSION = 1

_RULE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"id": "SECRET_PEM_PRIVATE_KEY", "confidence": "high", "scope": "text"},
    {"id": "SECRET_GENERIC_KEY_VALUE", "confidence": "high", "scope": "text"},
    {"id": "SECRET_AUTHORIZATION_HEADER", "confidence": "high", "scope": "text"},
    {"id": "SECRET_URI_USERINFO", "confidence": "high", "scope": "text"},
    {"id": "SECRET_SUSPICIOUS_ENTROPY", "confidence": "low", "scope": "text"},
    {"id": "SECRET_KEYWORD_ONLY", "confidence": "low", "scope": "text"},
    {"id": "NXOS_USERNAME_PASSWORD", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_ENABLE_SECRET", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_SNMP_COMMUNITY", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_SNMP_USER_AUTH_PRIV", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_RADIUS_SHARED_SECRET", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_TACACS_SHARED_SECRET", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_LDAP_PASSWORD", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_BGP_NEIGHBOR_PASSWORD", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_KEY_CHAIN_MATERIAL", "confidence": "high", "scope": "nxos"},
    {"id": "NXOS_BANNER_SECRET_CANDIDATE", "confidence": "low", "scope": "nxos"},
)

_PRIVATE_KEY_BEGIN_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9-]+ )*PRIVATE KEY-----"
)
_PRIVATE_KEY_END_RE = re.compile(
    r"-----END (?:[A-Z0-9-]+ )*PRIVATE KEY-----"
)
_GENERIC_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:^|[\s,{])[\"']?"
    r"(?:password|secret|token|api[-_]?key|client[-_]?secret|community)"
    r"[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s,}\"']+)"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)\bauthorization\s*:\s*(?:bearer|basic|token)\s+(?P<value>\S+)"
)
_URI_USERINFO_RE = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(?P<value>[^\s/@]+)@[^\s/]+"
)
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9+/=_-]{24,}$")
_SENSITIVE_NEAR_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:^|[\s,{])[\"']?"
    r"(?:credential|access[-_]?key|private[-_]?value)"
    r"[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s,}\"']+)"
)
_KEYWORD_RE = re.compile(
    r"(?i)\b(?:password|passphrase|secret|token|api[-_]?key|client[-_]?secret)\b"
)
_SAFE_VALUES = {"***redacted***", "<redacted>", "redacted"}
_SAFE_NXOS_POLICY_RE = re.compile(
    r"(?i)^\s*(?:no\s+)?"
    r"(?:password\s+(?:strength-check|secure-mode)|password\s+required)\s*$"
)

_NXOS_DIRECT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (rule_id, re.compile(pattern, re.IGNORECASE))
    for rule_id, pattern in (
        (
            "NXOS_USERNAME_PASSWORD",
            r"^\s*username\s+\S+(?:\s+\S+)*\s+(?:password|secret|passphrase)(?:\s+\S+)+\s*$",
        ),
        ("NXOS_ENABLE_SECRET", r"^\s*enable\s+(?:password|secret)(?:\s+\S+)+\s*$"),
        ("NXOS_SNMP_COMMUNITY", r"^\s*snmp-server\s+community\s+\S+(?:\s+\S+)*\s*$"),
        (
            "NXOS_SNMP_USER_AUTH_PRIV",
            r"^\s*snmp-server\s+user\s+.*\b(?:auth|priv)\s+\S+(?:\s+\S+)*\s*$",
        ),
        (
            "NXOS_SNMP_COMMUNITY",
            r"^\s*snmp-server\s+host\s+\S+\s+(?:traps|informs)\s+version\s+(?:1|2c)\s+\S+(?:\s+\S+)*\s*$",
        ),
        (
            "NXOS_RADIUS_SHARED_SECRET",
            r"^\s*radius-server(?:\s+\S+)*\s+key(?:\s+\S+)+\s*$",
        ),
        (
            "NXOS_TACACS_SHARED_SECRET",
            r"^\s*tacacs-server(?:\s+\S+)*\s+key(?:\s+\S+)+\s*$",
        ),
        (
            "NXOS_LDAP_PASSWORD",
            r"^\s*ldap-server\s+host\s+\S+\s+(?:test\s+)?rootDN\s+\S+.*\bpassword(?:\s+7)?\s+\S+(?:\s+\S+)*\s*$",
        ),
        (
            "NXOS_BGP_NEIGHBOR_PASSWORD",
            r"^\s*neighbor\s+\S+\s+password(?:\s+[0375])?\s+\S+(?:\s+\S+)*\s*$",
        ),
    )
)

CATALOG_DOCUMENT: dict[str, Any] = {
    "catalog_version": CATALOG_VERSION,
    "engine_version": ENGINE_VERSION,
    "rules": list(_RULE_DEFINITIONS),
    "selectors": {
        "private_key_begin": _PRIVATE_KEY_BEGIN_RE.pattern,
        "private_key_end": _PRIVATE_KEY_END_RE.pattern,
        "generic_assignment": _GENERIC_ASSIGNMENT_RE.pattern,
        "authorization": _AUTHORIZATION_RE.pattern,
        "uri_userinfo": _URI_USERINFO_RE.pattern,
        "sensitive_near_assignment": _SENSITIVE_NEAR_ASSIGNMENT_RE.pattern,
        "safe_nxos_policy": _SAFE_NXOS_POLICY_RE.pattern,
        "nxos_direct": [
            {"rule_id": rule_id, "pattern": pattern.pattern}
            for rule_id, pattern in _NXOS_DIRECT_RULES
        ],
        "nxos_contexts": {
            "bgp_password": "router bgp|template peer > password [0|3|5|7] value",
            "key_string": "key chain|key > key-string value",
            "banner": "banner delimiter body",
        },
        "safe_values": sorted(_SAFE_VALUES),
    },
}
CATALOG_SHA256 = canonical_sha256(CATALOG_DOCUMENT)


@dataclass(frozen=True)
class SecretFinding:
    """One secret candidate without captured secret material."""

    rule_id: str
    confidence: str
    artifact_id: str
    path: str
    line: int
    end_line: int | None = None

    def as_document(self) -> dict[str, Any]:
        location = {"line": self.line}
        if self.end_line is not None and self.end_line != self.line:
            location = {"start_line": self.line, "end_line": self.end_line}
        return {
            "rule_id": self.rule_id,
            "confidence": self.confidence,
            "artifact_id": self.artifact_id,
            "path": self.path,
            "location": location,
            "count": 1,
        }


def _safe_value(value: str) -> bool:
    normalized = value.strip("'\"").casefold()
    return normalized in _SAFE_VALUES or bool(
        re.fullmatch(r"<redacted:[a-z0-9_.-]+>", normalized)
    )


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _banner_delimiter(line: str) -> str | None:
    match = re.match(r"(?i)^\s*banner\s+\S+\s+(\S+)\s*$", line)
    return match.group(1) if match else None


def _nxos_context_rule(line: str, parents: Iterable[str]) -> str | None:
    if _SAFE_NXOS_POLICY_RE.match(line):
        return None
    for rule_id, pattern in _NXOS_DIRECT_RULES:
        if pattern.match(line):
            return rule_id
    stripped = line.strip()
    parent_text = "\n".join(parents).casefold()
    if re.match(r"(?i)^password(?:\s+[0357])?\s+\S+(?:\s+\S+)*$", stripped):
        if "router bgp " in parent_text or "template peer " in parent_text:
            return "NXOS_BGP_NEIGHBOR_PASSWORD"
    if re.match(r"(?i)^key-string(?:\s+\S+)+$", stripped):
        if "key chain " in parent_text or re.search(r"(?m)^key\s+\S+", parent_text):
            return "NXOS_KEY_CHAIN_MATERIAL"
    return None


def _common_high_rule(line: str) -> str | None:
    match = _AUTHORIZATION_RE.search(line)
    if match and not _safe_value(match.group("value")):
        return "SECRET_AUTHORIZATION_HEADER"
    match = _URI_USERINFO_RE.search(line)
    if match and not _safe_value(match.group("value")):
        return "SECRET_URI_USERINFO"
    match = _GENERIC_ASSIGNMENT_RE.search(line)
    if match and not _safe_value(match.group("value")):
        return "SECRET_GENERIC_KEY_VALUE"
    return None


def _common_low_rule(line: str) -> str | None:
    match = _SENSITIVE_NEAR_ASSIGNMENT_RE.search(line)
    if (
        match
        and not _safe_value(match.group("value"))
        and _OPAQUE_RE.fullmatch(match.group("value"))
    ):
        return "SECRET_SUSPICIOUS_ENTROPY"
    return None


def scan_text(
    content: str,
    *,
    artifact_id: str,
    path: str,
    platform: str | None = None,
    content_type: str = "text",
) -> list[SecretFinding]:
    """Scan text and return value-free findings in stable source order."""
    findings: list[SecretFinding] = []
    lines = content.splitlines()
    parents: list[tuple[int, str]] = []
    banner: str | None = None
    private_start: int | None = None

    for line_number, line in enumerate(lines, start=1):
        if private_start is not None:
            if _PRIVATE_KEY_END_RE.search(line):
                findings.append(
                    SecretFinding(
                        "SECRET_PEM_PRIVATE_KEY",
                        "high",
                        artifact_id,
                        path,
                        private_start,
                        line_number,
                    )
                )
                private_start = None
            continue
        if _PRIVATE_KEY_BEGIN_RE.search(line):
            private_start = line_number
            continue

        if banner is not None:
            if line.strip() == banner:
                banner = None
                continue
            common_rule = _common_high_rule(line)
            if common_rule:
                findings.append(
                    SecretFinding(common_rule, "high", artifact_id, path, line_number)
                )
            elif _KEYWORD_RE.search(line):
                findings.append(
                    SecretFinding(
                        "NXOS_BANNER_SECRET_CANDIDATE",
                        "low",
                        artifact_id,
                        path,
                        line_number,
                    )
                )
            continue

        nxos_config_like = platform == "nxos" and content_type in {
            "running-config",
            "cli-output",
        }
        if nxos_config_like:
            delimiter = _banner_delimiter(line)
            if delimiter:
                banner = delimiter
                continue

        stripped = line.strip()
        if not stripped or stripped.startswith(("!", "#")):
            continue

        indent = _line_indent(line)
        while parents and parents[-1][0] >= indent:
            parents.pop()

        rule_id = None
        if nxos_config_like:
            rule_id = _nxos_context_rule(line, (item[1] for item in parents))
        if rule_id is None:
            rule_id = _common_high_rule(line)
        if rule_id:
            findings.append(
                SecretFinding(rule_id, "high", artifact_id, path, line_number)
            )
        else:
            low_rule = _common_low_rule(line)
            if low_rule:
                findings.append(
                    SecretFinding(low_rule, "low", artifact_id, path, line_number)
                )
            elif (
                nxos_config_like
                and _KEYWORD_RE.search(line)
                and not _SAFE_NXOS_POLICY_RE.match(line)
            ):
                findings.append(
                    SecretFinding(
                        "SECRET_KEYWORD_ONLY",
                        "low",
                        artifact_id,
                        path,
                        line_number,
                    )
                )

        if nxos_config_like:
            parents.append((indent, stripped))

    if private_start is not None:
        findings.append(
            SecretFinding(
                "SECRET_PEM_PRIVATE_KEY",
                "high",
                artifact_id,
                path,
                private_start,
                len(lines) or private_start,
            )
        )
    return findings


def sanitize_text(
    content: str,
    *,
    artifact_id: str,
    path: str,
    platform: str | None = None,
    content_type: str = "text",
) -> tuple[str, list[SecretFinding]]:
    """Remove high-confidence findings while preserving unrelated text."""
    findings = scan_text(
        content,
        artifact_id=artifact_id,
        path=path,
        platform=platform,
        content_type=content_type,
    )
    high_by_start = {
        finding.line: finding
        for finding in findings
        if finding.confidence == "high"
    }
    output: list[str] = []
    line_number = 1
    lines = content.splitlines()
    while line_number <= len(lines):
        finding = high_by_start.get(line_number)
        if finding is None:
            output.append(lines[line_number - 1])
            line_number += 1
            continue
        output.append(f"! REDACTED {finding.rule_id}")
        line_number = (finding.end_line or finding.line) + 1
    return "\n".join(output).rstrip() + "\n", findings


def build_scan_result(
    findings: Iterable[SecretFinding],
    *,
    files_scanned: int,
    files_not_scanned: int = 0,
    acknowledged_sensitive: bool = False,
) -> dict[str, Any]:
    """Build the stable manifest representation for a completed scan."""
    ordered = sorted(
        findings,
        key=lambda item: (item.path, item.line, item.rule_id, item.artifact_id),
    )
    high = sum(item.confidence == "high" for item in ordered)
    low = sum(item.confidence == "low" for item in ordered)
    if files_not_scanned:
        status = "NOT_SCANNED"
    elif acknowledged_sensitive:
        status = "ACKNOWLEDGED_SENSITIVE"
    elif high:
        status = "BLOCKED"
    elif low:
        status = "LOW_CONFIDENCE_FINDINGS"
    else:
        status = "CLEAN"
    return {
        "catalog_version": CATALOG_VERSION,
        "catalog_sha256": CATALOG_SHA256,
        "status": status,
        "files_scanned": files_scanned,
        "files_not_scanned": files_not_scanned,
        "high_confidence": high,
        "low_confidence": low,
        "findings": [item.as_document() for item in ordered],
    }


def is_secret_bearing_line(line: str) -> bool:
    """Compatibility helper for direct, context-independent high-confidence syntax."""
    return any(
        finding.confidence == "high"
        for finding in scan_text(
            line,
            artifact_id="line",
            path="line",
            platform="nxos",
            content_type="running-config",
        )
    )
