"""
Parsing and normalization helpers for LLDP / descriptions / links.
"""

from __future__ import annotations

import csv
from logging import Logger
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .constants import (
    CONFIDENCE_RANK,
    DEFAULT_DESCRIPTION_RULES,
    DEFAULT_DESCRIPTION_RULES_PATH,
    DEFAULT_MAPPINGS,
    DEFAULT_POLICY,
    DEFAULT_ROLES,
    DEFAULT_ROLES_PATH,
)
from .utils import load_yaml


def load_policy_file(path: str | None) -> Dict[str, List[str]]:
    """
    Load policy configuration merged with defaults.

    Args:
        path: Optional policy YAML path.

    Returns:
        Policy dictionary.
    """
    if not path:
        return DEFAULT_POLICY.copy()

    loaded = load_yaml(path)
    policy = DEFAULT_POLICY.copy()
    for key in DEFAULT_POLICY:
        policy[key] = loaded.get(key, DEFAULT_POLICY[key]) or []
    return policy


def load_mappings(path: str | None) -> Dict[str, Any]:
    """
    Load mappings merged with defaults.

    Args:
        path: Optional mappings YAML path.

    Returns:
        Mapping configuration.
    """
    if not path:
        return DEFAULT_MAPPINGS.copy()

    loaded = load_yaml(path)
    mappings = DEFAULT_MAPPINGS.copy()
    mappings["node_name_map"] = loaded.get("node_name_map", {}) or {}
    mappings["interface_name_map"] = loaded.get("interface_name_map", {}) or {}
    mappings["exclude_interfaces"] = loaded.get(
        "exclude_interfaces",
        DEFAULT_MAPPINGS["exclude_interfaces"],
    ) or []
    return mappings


def load_roles(path: str | None) -> Dict[str, Any]:
    """
    Load role detection configuration.

    Args:
        path: Optional roles YAML path.

    Returns:
        Role rules.
    """
    if not path:
        default_path = Path(DEFAULT_ROLES_PATH)
        if default_path.exists():
            loaded = load_yaml(str(default_path))
            return loaded.get("role_detection", {}) or {}
        import yaml
        return yaml.safe_load(yaml.safe_dump(DEFAULT_ROLES["role_detection"]))

    loaded = load_yaml(path)
    return loaded.get("role_detection", {}) or {}


def load_description_rules(path: str | None) -> List[Dict[str, str]]:
    """
    Load description parsing rules.

    Args:
        path: Optional description-rules YAML path.

    Returns:
        Description rule list.
    """
    if not path:
        default_path = Path(DEFAULT_DESCRIPTION_RULES_PATH)
        if default_path.exists():
            loaded = load_yaml(str(default_path))
            return loaded.get("description_rules", []) or []
        import yaml
        return yaml.safe_load(yaml.safe_dump(DEFAULT_DESCRIPTION_RULES)).get("description_rules", [])

    loaded = load_yaml(path)
    return loaded.get("description_rules", []) or []


def should_include(host: Dict[str, Any], policy: Dict[str, List[str]]) -> Tuple[bool, str]:
    """
    Check include rules.

    Args:
        host: Host dictionary.
        policy: Policy dictionary.

    Returns:
        (is_included, reason)
    """
    hostname = host["hostname"]
    device_type = host["device_type"]
    include_device_types = policy.get("include_device_types", [])
    include_hostname_contains = policy.get("include_hostname_contains", [])

    if not include_device_types and not include_hostname_contains:
        return True, "no include rules"
    if device_type in include_device_types:
        return True, f"device_type matched include: {device_type}"

    for pattern in include_hostname_contains:
        if pattern in hostname:
            return True, f"hostname matched include substring: {pattern}"

    return False, "not matched by include rules"


def should_exclude(host: Dict[str, Any], policy: Dict[str, List[str]]) -> Tuple[bool, str]:
    """
    Check exclude rules.

    Args:
        host: Host dictionary.
        policy: Policy dictionary.

    Returns:
        (is_excluded, reason)
    """
    hostname = host["hostname"]
    device_type = host["device_type"]

    for excluded_type in policy.get("exclude_device_types", []):
        if device_type == excluded_type:
            return True, f"device_type matched exclude: {excluded_type}"

    for pattern in policy.get("exclude_hostname_contains", []):
        if pattern in hostname:
            return True, f"hostname matched exclude substring: {pattern}"

    return False, ""


def should_collect_running_config(device_type: str, policy: Dict[str, List[str]]) -> bool:
    """
    Check whether running-config should be collected.

    Args:
        device_type: Device type string.
        policy: Policy dictionary.

    Returns:
        True if running-config should be collected.
    """
    return device_type in set(policy.get("collect_running_config_for", []))


def confidence_allowed(record_confidence: str, min_confidence: str) -> bool:
    """
    Check whether a record passes min-confidence threshold.

    Args:
        record_confidence: Record confidence.
        min_confidence: Required minimum confidence.

    Returns:
        True if record passes.
    """
    record_rank = CONFIDENCE_RANK.get((record_confidence or "").lower(), 0)
    required_rank = CONFIDENCE_RANK.get((min_confidence or "").lower(), 1)
    return record_rank >= required_rank


def normalize_hostname(name: str, mappings: Dict[str, Any]) -> str:
    """
    Normalize hostname using node_name_map.

    Args:
        name: Raw hostname.
        mappings: Mapping config.

    Returns:
        Normalized hostname.
    """
    name = name.strip()
    return mappings.get("node_name_map", {}).get(name, name)


def normalize_interface_name(ifname: str, mappings: Dict[str, Any]) -> str:
    """
    Normalize interface name to canonical format.

    Args:
        ifname: Raw interface name.
        mappings: Mapping config.

    Returns:
        Canonical interface name.
    """
    raw = ifname.strip()

    mapped = mappings.get("interface_name_map", {}).get(raw)
    if mapped:
        return mapped

    x = re.sub(r"\s+", "", raw)
    xl = x.lower()

    m = re.fullmatch(r"(?:eth|ethernet)(\d+/\d+)", xl)
    if m:
        return f"Ethernet{m.group(1)}"

    m = re.fullmatch(r"(?:eth|ethernet)(\d+)", xl)
    if m:
        return f"Ethernet{m.group(1)}"

    m = re.fullmatch(r"mgmt(\d+)", xl)
    if m:
        return f"mgmt{m.group(1)}"

    m = re.fullmatch(r"(?:lo|loopback)(\d+)", xl)
    if m:
        return f"loopback{m.group(1)}"

    m = re.fullmatch(r"(?:po|port-channel)(\d+)", xl)
    if m:
        return f"Port-channel{m.group(1)}"

    return x


def is_excluded_interface(ifname: str, mappings: Dict[str, Any]) -> bool:
    """
    Check whether interface should be excluded.

    Special behavior:
    - Any exact match in exclude_interfaces is excluded.
    - If exclude_interfaces contains Port-channel / port-channel,
      all Port-channel<number> are excluded.

    Args:
        ifname: Interface name.
        mappings: Mapping config.

    Returns:
        True if excluded.
    """
    normalized = normalize_interface_name(ifname, mappings)
    normalized_lc = normalized.strip().lower().replace(" ", "")

    excluded_raw = mappings.get("exclude_interfaces", []) or []
    excluded = [normalize_interface_name(i, mappings).lower().replace(" ", "") for i in excluded_raw]

    if normalized_lc in excluded:
        return True

    if "port-channel" in excluded and normalized_lc.startswith("port-channel"):
        return True

    return False


def parse_key_value_stanzas(text: str) -> List[Dict[str, str]]:
    """
    Parse LLDP detail text into key/value stanzas.

    Args:
        text: Raw LLDP detail text.

    Returns:
        List of stanza dictionaries.
    """
    stanzas: List[Dict[str, str]] = []
    current: Dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            if current and (
                "System Name" in current or
                "Port id" in current or
                "Local Port id" in current
            ):
                stanzas.append(current)
                current = {}
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        current[key.strip()] = value.strip()

    if current and (
        "System Name" in current or
        "Port id" in current or
        "Local Port id" in current
    ):
        stanzas.append(current)

    return stanzas


def parse_nxos_lldp_detail(text: str, local_hostname: str, mappings: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Parse NX-OS-like LLDP detail output.

    Args:
        text: Raw LLDP detail.
        local_hostname: Local host.
        mappings: Mapping config.

    Returns:
        Directional LLDP records.
    """
    records: List[Dict[str, str]] = []

    for stanza in parse_key_value_stanzas(text):
        remote_hostname = stanza.get("System Name", "").strip()
        local_if = stanza.get("Local Port id", "").strip()
        remote_if = stanza.get("Port id", "").strip()
        mgmt_addr = stanza.get("Management Address", "").strip()

        if not remote_hostname or not local_if or not remote_if:
            continue

        if is_excluded_interface(local_if, mappings) or is_excluded_interface(remote_if, mappings):
            continue

        records.append({
            "src_node": normalize_hostname(local_hostname, mappings),
            "src_if": normalize_interface_name(local_if, mappings),
            "dst_node": normalize_hostname(remote_hostname, mappings),
            "dst_if": normalize_interface_name(remote_if, mappings),
            "protocol": "lldp",
            "confidence": "",
            "evidence": "",
            "remote_mgmt_ip": mgmt_addr,
            "rule_name": "",
        })

    return records


def parse_linux_lldp(text: str, local_hostname: str, mappings: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Parse Linux lldpcli output.

    Args:
        text: Raw LLDP text.
        local_hostname: Local host.
        mappings: Mapping config.

    Returns:
        Directional LLDP records.
    """
    records: List[Dict[str, str]] = []
    current_local_if = ""
    current_remote_name = ""
    current_remote_port = ""

    for line in text.splitlines():
        s = line.strip()

        m = re.search(r"Interface:\s*(\S+)", s)
        if m:
            current_local_if = m.group(1)

        m = re.search(r"SysName:\s*(\S+)", s)
        if m:
            current_remote_name = m.group(1)

        m = re.search(r"PortID:\s*(\S+)", s)
        if m:
            current_remote_port = m.group(1)

        if current_local_if and current_remote_name and current_remote_port:
            if not is_excluded_interface(current_local_if, mappings) and not is_excluded_interface(current_remote_port, mappings):
                records.append({
                    "src_node": normalize_hostname(local_hostname, mappings),
                    "src_if": normalize_interface_name(current_local_if, mappings),
                    "dst_node": normalize_hostname(current_remote_name, mappings),
                    "dst_if": normalize_interface_name(current_remote_port, mappings),
                    "protocol": "lldp",
                    "confidence": "",
                    "evidence": "",
                    "remote_mgmt_ip": "",
                    "rule_name": "",
                })

            current_local_if = ""
            current_remote_name = ""
            current_remote_port = ""

    return records


def parse_lldp_file(text: str, local_hostname: str, device_type: str, mappings: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Dispatch LLDP parser by device type.

    Args:
        text: Raw LLDP text.
        local_hostname: Local host.
        device_type: Device type.
        mappings: Mapping config.

    Returns:
        Parsed directional LLDP records.
    """
    if device_type in {"nxos", "ios", "iosxe", "iosxr", "eos", "asa", "asav"}:
        return parse_nxos_lldp_detail(text, local_hostname, mappings)
    if device_type == "linux":
        return parse_linux_lldp(text, local_hostname, mappings)
    if device_type == "junos":
        return []
    return []


def parse_interface_descriptions_from_run(text: str) -> List[Dict[str, str]]:
    """
    Extract interface descriptions from running-config text.

    Args:
        text: Raw running-config text.

    Returns:
        List of {local_if, description}.
    """
    results: List[Dict[str, str]] = []
    current_if: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        m = re.match(r"^interface\s+(\S+)", line)
        if m:
            current_if = m.group(1)
            continue

        if current_if:
            m = re.match(r"^\s*description\s+(.+)$", line)
            if m:
                results.append({
                    "local_if": current_if,
                    "description": m.group(1).strip(),
                })

    return results


def parse_remote_from_description(description: str, rules: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Parse remote endpoint from description using regex rules.

    Args:
        description: Description text.
        rules: Regex rules.

    Returns:
        Parsed remote endpoint info or None.
    """
    for rule in rules:
        pattern = rule.get("regex")
        if not pattern:
            continue

        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            remote_host = m.groupdict().get("remote_host", "").strip()
            remote_if = m.groupdict().get("remote_if", "").strip()

            if remote_host:
                return {
                    "remote_host": remote_host,
                    "remote_if": remote_if,
                    "rule_name": rule.get("name", "unknown"),
                }

    return None


def build_description_records(
    local_hostname: str,
    run_text: str,
    mappings: Dict[str, Any],
    description_rules: List[Dict[str, str]],
    include_svi: bool = False,
) -> List[Dict[str, str]]:
    """
    Build directional records from interface descriptions.

    Args:
        local_hostname: Local hostname.
        run_text: Raw running-config.
        mappings: Mapping config.
        description_rules: Regex rules.
        include_svi: Whether to include SVI (interface Vlan*) descriptions.

    Returns:
        Directional description-based records.
    """
    records: List[Dict[str, str]] = []

    for item in parse_interface_descriptions_from_run(run_text):
        local_if = item["local_if"]
        desc = item["description"]

        if not include_svi and local_if.lower().startswith("vlan"):
            continue

        parsed = parse_remote_from_description(desc, description_rules)
        if not parsed:
            continue

        if is_excluded_interface(local_if, mappings):
            continue
        if parsed["remote_if"] and is_excluded_interface(parsed["remote_if"], mappings):
            continue

        records.append({
            "src_node": normalize_hostname(local_hostname, mappings),
            "src_if": normalize_interface_name(local_if, mappings),
            "dst_node": normalize_hostname(parsed["remote_host"], mappings),
            "dst_if": normalize_interface_name(parsed["remote_if"], mappings),
            "protocol": "description",
            "confidence": "",
            "evidence": "",
            "remote_mgmt_ip": "",
            "rule_name": parsed["rule_name"],
        })

    return records


def normalize_link_record(record: Dict[str, str], mappings: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize one link record.

    Args:
        record: Raw link record.
        mappings: Mapping config.

    Returns:
        Normalized record copy.
    """
    normalized = dict(record)
    normalized["src_node"] = normalize_hostname(record.get("src_node", ""), mappings)
    normalized["dst_node"] = normalize_hostname(record.get("dst_node", ""), mappings)
    normalized["src_if"] = normalize_interface_name(record.get("src_if", ""), mappings)
    normalized["dst_if"] = normalize_interface_name(record.get("dst_if", ""), mappings)
    return normalized


def normalize_link_records(records: Iterable[Dict[str, str]], mappings: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Normalize all link records.

    Args:
        records: Iterable of records.
        mappings: Mapping config.

    Returns:
        Normalized record list.
    """
    return [normalize_link_record(r, mappings) for r in records]


def record_key(r: Dict[str, str]) -> Tuple[str, str, str, str]:
    """
    Return directional key for a link record.

    Args:
        r: Link record.

    Returns:
        (src_node, src_if, dst_node, dst_if)
    """
    return (r["src_node"], r["src_if"], r["dst_node"], r["dst_if"])


def _format_endpoint(record: Dict[str, str]) -> str:
    """
    Format the remote endpoint of a link record.

    Args:
        record: Link record.

    Returns:
        node:interface string.
    """
    dst_if = record.get("dst_if", "")
    return f"{record.get('dst_node', '')}:{dst_if}" if dst_if else record.get("dst_node", "")


def _description_matches_lldp(lldp_record: Dict[str, str], desc_record: Dict[str, str]) -> bool:
    """
    Check whether a description-derived endpoint matches an LLDP endpoint.

    Args:
        lldp_record: LLDP link record.
        desc_record: Description-derived link record.

    Returns:
        True when description remote endpoint matches LLDP.
    """
    if lldp_record.get("dst_node", "") != desc_record.get("dst_node", ""):
        return False
    desc_dst_if = desc_record.get("dst_if", "")
    if desc_dst_if and lldp_record.get("dst_if", "") != desc_dst_if:
        return False
    return True


def _append_link_warning(record: Dict[str, str], warning: str) -> None:
    """
    Append a warning string to a link record.

    Args:
        record: Link record.
        warning: Warning text.
    """
    if not warning:
        return
    current = record.get("warning", "")
    warnings = [item for item in current.split("; ") if item] if current else []
    if warning not in warnings:
        warnings.append(warning)
    record["warning"] = "; ".join(warnings)


def _lldp_description_mismatch_warning(
    lldp_record: Dict[str, str],
    desc_record: Dict[str, str],
) -> str:
    """
    Build a warning when LLDP and description disagree.

    Args:
        lldp_record: LLDP link record.
        desc_record: Description-derived link record.

    Returns:
        Warning text, or empty string when endpoints match.
    """
    if _description_matches_lldp(lldp_record, desc_record):
        return ""
    return (
        "lldp-description-mismatch: "
        f"lldp={_format_endpoint(lldp_record)} "
        f"description={_format_endpoint(desc_record)}"
    )


def _local_endpoint_index(records: Iterable[Dict[str, str]]) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
    """
    Index link records by local endpoint.

    Args:
        records: Link records.

    Returns:
        Mapping of (src_node, src_if) to records.
    """
    index: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for record in records:
        index.setdefault((record.get("src_node", ""), record.get("src_if", "")), []).append(record)
    return index


def merge_lldp_and_description_links(
    lldp_records: Iterable[Dict[str, str]],
    description_records: Iterable[Dict[str, str]],
    logger: Optional[Logger] = None,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Merge LLDP and description-derived link records.

    Confirmed:
    - bidirectional LLDP -> high
    - LLDP + description -> medium
    - bidirectional description -> low

    Candidate:
    - one-way description -> low
    - one-way LLDP -> low

    Args:
        lldp_records: LLDP directional records.
        description_records: Description directional records.
        logger: Optional logger.

    Returns:
        (confirmed, candidates)
    """
    lldp_records = list(lldp_records)
    description_records = list(description_records)
    lldp_map: Dict[Tuple[str, str, str, str], Dict[str, str]] = {record_key(r): r for r in lldp_records}
    desc_map: Dict[Tuple[str, str, str, str], Dict[str, str]] = {record_key(r): r for r in description_records}
    desc_by_local = _local_endpoint_index(description_records)
    lldp_by_local = _local_endpoint_index(lldp_records)

    confirmed: List[Dict[str, str]] = []
    candidates: List[Dict[str, str]] = []
    emitted = set()

    lldp_bidirectional = 0
    lldp_plus_desc = 0
    desc_bidirectional = 0
    candidate_oneway_desc = 0
    candidate_oneway_lldp = 0
    lldp_description_mismatches = 0

    all_keys = set(lldp_map.keys()) | set(desc_map.keys())

    for key in all_keys:
        reverse_key = (key[2], key[3], key[0], key[1])
        canon_key = tuple(sorted([key, reverse_key]))

        if canon_key in emitted:
            continue

        key_in_lldp = key in lldp_map
        rev_in_lldp = reverse_key in lldp_map
        key_in_desc = key in desc_map
        rev_in_desc = reverse_key in desc_map

        selected: Optional[Dict[str, str]] = None
        candidate: Optional[Dict[str, str]] = None

        if key_in_lldp and rev_in_lldp:
            selected = dict(lldp_map[key])
            selected["protocol"] = "lldp"
            selected["confidence"] = "high"
            selected["evidence"] = "bidirectional-lldp"
            lldp_bidirectional += 1

        elif (key_in_lldp and rev_in_desc) or (key_in_desc and rev_in_lldp):
            base = (
                lldp_map.get(key) or
                lldp_map.get(reverse_key) or
                desc_map.get(key) or
                desc_map.get(reverse_key)
            )
            selected = dict(base)
            selected["protocol"] = "lldp+description"
            selected["confidence"] = "medium"
            selected["evidence"] = "lldp-plus-description"
            lldp_plus_desc += 1

        elif key_in_desc and rev_in_desc:
            selected = dict(desc_map[key])
            selected["protocol"] = "description"
            selected["confidence"] = "low"
            selected["evidence"] = "bidirectional-description"
            desc_bidirectional += 1

        else:
            base = lldp_map.get(key) or desc_map.get(key)
            if base:
                candidate = dict(base)
                if key_in_desc or rev_in_desc:
                    candidate["protocol"] = "description"
                    candidate["confidence"] = "low"
                    candidate["evidence"] = "one-way-description"
                    candidate_oneway_desc += 1
                else:
                    candidate["protocol"] = "lldp"
                    candidate["confidence"] = "low"
                    candidate["evidence"] = "one-way-lldp"
                    candidate_oneway_lldp += 1

        if selected:
            for desc_record in desc_by_local.get((selected.get("src_node", ""), selected.get("src_if", "")), []):
                if selected.get("protocol", "").startswith("lldp"):
                    warning = _lldp_description_mismatch_warning(selected, desc_record)
                    if warning:
                        _append_link_warning(selected, warning)
            if selected.get("warning"):
                lldp_description_mismatches += 1
            confirmed.append(selected)
            emitted.add(canon_key)
        elif candidate:
            candidate_local = (candidate.get("src_node", ""), candidate.get("src_if", ""))
            if candidate.get("protocol") == "description":
                for lldp_record in lldp_by_local.get(candidate_local, []):
                    warning = _lldp_description_mismatch_warning(lldp_record, candidate)
                    if warning:
                        _append_link_warning(candidate, warning)
            elif candidate.get("protocol") == "lldp":
                for desc_record in desc_by_local.get(candidate_local, []):
                    warning = _lldp_description_mismatch_warning(candidate, desc_record)
                    if warning:
                        _append_link_warning(candidate, warning)
            if candidate.get("warning"):
                lldp_description_mismatches += 1
            candidates.append(candidate)
            emitted.add(canon_key)

    if logger:
        logger.info("Confirmed bidirectional LLDP links: %d", lldp_bidirectional)
        logger.info("Confirmed LLDP + description links: %d", lldp_plus_desc)
        logger.info("Confirmed bidirectional description links: %d", desc_bidirectional)
        logger.info("Candidate one-way description links: %d", candidate_oneway_desc)
        logger.info("Candidate one-way LLDP links: %d", candidate_oneway_lldp)
        if lldp_description_mismatches:
            logger.warning("LLDP/description mismatch links: %d", lldp_description_mismatches)

    return confirmed, candidates


def write_links_csv(records: List[Dict[str, str]], path: str) -> None:
    """
    Write link records to CSV.

    Args:
        records: Link records.
        path: Output CSV path.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "src_node",
        "src_if",
        "dst_node",
        "dst_if",
        "protocol",
        "confidence",
        "evidence",
        "remote_mgmt_ip",
        "rule_name",
        "warning",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in fields})


def read_links_csv(path: str) -> List[Dict[str, str]]:
    """
    Read link records from CSV.

    Args:
        path: Input CSV path.

    Returns:
        List of records.
    """
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
