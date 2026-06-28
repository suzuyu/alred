"""
Config transformation helpers for containerlab / NX-OS 9000v lab use.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import ipaddress
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .templates import render_named_template_lines


_SECTION_HEADER_RE = re.compile(r"^\S")
_INTERFACE_HEADER_RE = re.compile(r"^interface\s+(\S+)\s*$", re.IGNORECASE)
_SUBINTERFACE_HEADER_RE = re.compile(r"^interface\s+(\S+)\.(\d+)\s*$", re.IGNORECASE)
_SVI_HEADER_RE = re.compile(r"^interface\s+Vlan(\d+)\s*$", re.IGNORECASE)
_VLAN_HEADER_RE = re.compile(r"^vlan\s+(\d+)\s*$", re.IGNORECASE)
_VPC_HEADER_RE = re.compile(r"^vpc domain\s+\d+\s*$", re.IGNORECASE)
_VRF_MGMT_HEADER_RE = re.compile(r"^vrf context management\s*$", re.IGNORECASE)
_MGMT0_HEADER_RE = re.compile(r"^interface\s+mgmt0\s*$", re.IGNORECASE)
_ENCAP_DOT1Q_RE = re.compile(r"^\s*encapsulation\s+dot1q\s+(\d+)\s*$", re.IGNORECASE)
_IP_TOKEN_RE = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(/\d{1,2})?(?![\d.])")
_IP_ADDRESS_LINE_RE = re.compile(r"^\s*ip address\s+\S+", re.IGNORECASE)
_NO_SWITCHPORT_LINE_RE = re.compile(r"^\s*no switchport\s*$", re.IGNORECASE)
_USERNAME_LINE_RE = re.compile(r"^username\s+(\S+)\b", re.IGNORECASE)
_SNMP_SERVER_USER_LINE_RE = re.compile(r"^snmp-server\s+user\s+\S+\b", re.IGNORECASE)
_LINE_VTY_HEADER_RE = re.compile(r"^line\s+vty(?:\s+\d+(?:\s+\d+)?)?\s*$", re.IGNORECASE)
_ACCESS_CLASS_LINE_RE = re.compile(r"^\s*(?:ipv6\s+)?access-class\b", re.IGNORECASE)
_HOSTNAME_LINE_RE = re.compile(r"^hostname\s+(\S+)\s*$", re.IGNORECASE)
_VDC_LINE_RE = re.compile(r"^vdc\s+(\S+)(\s+.*)?$", re.IGNORECASE)
_VALID_LAB_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_L3_SWITCHPORT_COMPATIBLE_INTERFACE_RE = re.compile(
    r"^interface\s+(?:Ethernet|port-channel)\S*\s*$",
    re.IGNORECASE,
)


@dataclass
class SubinterfaceConversion:
    """
    One L2 sub-interface to SVI/trunk conversion.
    """

    parent_interface: str
    subinterface_name: str
    vlan_id: int
    svi_body_lines: List[str]


def parse_mgmt_ipv4_subnet(clab_merge_data: Dict[str, Any]) -> Optional[ipaddress.IPv4Network]:
    """
    Return mgmt.ipv4-subnet as IPv4Network when present.
    """
    mgmt = clab_merge_data.get("mgmt", {})
    if not isinstance(mgmt, dict):
        return None
    subnet = mgmt.get("ipv4-subnet")
    if not subnet:
        return None
    return ipaddress.ip_network(str(subnet), strict=False)


def remap_ipv4_address(address: ipaddress.IPv4Address, target_subnet: ipaddress.IPv4Network) -> ipaddress.IPv4Address:
    """
    Move an IPv4 address into the target subnet while preserving host bits.
    """
    host_mask = (1 << (32 - target_subnet.prefixlen)) - 1
    host_bits = int(address) & host_mask
    return ipaddress.IPv4Address(int(target_subnet.network_address) + host_bits)


def remap_ipv4_string(value: str, target_subnet: ipaddress.IPv4Network, replace_prefixlen: bool = False) -> str:
    """
    Remap an IPv4 or IPv4/prefix string into the target subnet.
    """
    if "/" in value:
        ip_part, prefix_part = value.split("/", 1)
    else:
        ip_part, prefix_part = value, ""

    try:
        address = ipaddress.ip_address(ip_part)
    except ValueError:
        return value
    if not isinstance(address, ipaddress.IPv4Address):
        return value

    remapped = str(remap_ipv4_address(address, target_subnet))
    if not prefix_part:
        return remapped
    return f"{remapped}/{target_subnet.prefixlen if replace_prefixlen else prefix_part}"


def resolve_node_map_management_ip(
    row: Dict[str, str],
    target_subnet: Optional[ipaddress.IPv4Network],
) -> str:
    """
    Resolve a node-map target IP, then apply the lab subnet when necessary.
    """
    target_ip = ipaddress.IPv4Address(row["target_mgmt_ip"])
    if target_subnet is None or target_ip in target_subnet:
        return str(target_ip)
    return str(remap_ipv4_address(target_ip, target_subnet))


def replace_ipv4_tokens(
    line: str,
    target_subnet: Optional[ipaddress.IPv4Network],
    replace_prefixlen: bool = False,
    address_map: Optional[Dict[str, str]] = None,
) -> str:
    """
    Replace every IPv4 token on a line with the target subnet equivalent.
    """
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        ip_part, separator, prefix = token.partition("/")
        mapped = (address_map or {}).get(ip_part)
        if mapped:
            if separator:
                mapped_prefix = target_subnet.prefixlen if replace_prefixlen and target_subnet else prefix
                return f"{mapped}/{mapped_prefix}"
            return mapped
        if target_subnet is None:
            return token
        return remap_ipv4_string(token, target_subnet, replace_prefixlen=replace_prefixlen)

    return _IP_TOKEN_RE.sub(repl, line)


def transform_vrf_management_line(
    line: str,
    target_subnet: Optional[ipaddress.IPv4Network],
    address_map: Optional[Dict[str, str]] = None,
) -> str:
    """
    Transform management VRF lines while preserving route prefixes.
    """
    stripped = line.strip()
    if stripped.lower().startswith("ip route "):
        leading_ws = line[: len(line) - len(line.lstrip())]
        parts = stripped.split()
        if len(parts) <= 3:
            return line
        prefix_tokens = parts[:3]
        next_hop_tokens = [
            (address_map or {}).get(token)
            or (
                remap_ipv4_string(token, target_subnet, replace_prefixlen=False)
                if target_subnet is not None
                else token
            )
            for token in parts[3:]
        ]
        return leading_ws + " ".join(prefix_tokens + next_hop_tokens)
    return replace_ipv4_tokens(
        line,
        target_subnet,
        replace_prefixlen=True,
        address_map=address_map,
    )


def transform_inventory_mgmt_subnet(
    inventory_data: Dict[str, Any],
    target_subnet: Optional[ipaddress.IPv4Network],
    node_map_rows: Optional[Iterable[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Rewrite ansible_host values into the target mgmt subnet.
    """
    transformed = deepcopy(inventory_data)
    hosts = transformed.get("all", {}).get("hosts", {})
    if not isinstance(hosts, dict):
        return transformed

    rows_by_hostname = {
        row["source_hostname"]: row
        for row in (node_map_rows or [])
    }
    rows_by_target_hostname = {
        row["target_hostname"]: row
        for row in rows_by_hostname.values()
    }
    inventory_hostnames = {str(name) for name in hosts}
    missing_source_hostnames = sorted(
        source_hostname
        for source_hostname, row in rows_by_hostname.items()
        if source_hostname not in inventory_hostnames
        and row["target_hostname"] not in inventory_hostnames
    )
    if missing_source_hostnames:
        raise ValueError(
            "Node map source_hostname or target_hostname not found in inventory: "
            + ", ".join(missing_source_hostnames)
        )
    transformed_hosts: Dict[str, Any] = {}
    for hostname, attrs in hosts.items():
        if not isinstance(attrs, dict):
            transformed_hosts[hostname] = attrs
            continue
        inventory_hostname = str(hostname)
        row = rows_by_hostname.get(inventory_hostname)
        inventory_uses_target_hostname = row is None
        if row is None:
            row = rows_by_target_hostname.get(inventory_hostname)
        ansible_host = attrs.get("ansible_host")
        if row:
            resolved_target_mgmt_ip = resolve_node_map_management_ip(row, target_subnet)
            expected_management_ips = {row["source_mgmt_ip"]}
            if inventory_uses_target_hostname:
                expected_management_ips.add(row["target_mgmt_ip"])
                expected_management_ips.add(resolved_target_mgmt_ip)
            if ansible_host and str(ansible_host) not in expected_management_ips:
                raise ValueError(
                    f"Node map management IP mismatch for {hostname}: "
                    f"inventory={ansible_host} csv="
                    + "/".join(sorted(expected_management_ips))
                )
            attrs["ansible_host"] = resolved_target_mgmt_ip
            target_hostname = row["target_hostname"]
        else:
            if ansible_host and target_subnet is not None:
                attrs["ansible_host"] = remap_ipv4_string(
                    str(ansible_host),
                    target_subnet,
                    replace_prefixlen=False,
                )
            target_hostname = str(hostname)
        if target_hostname in transformed_hosts:
            raise ValueError(f"Duplicate transformed hostname: {target_hostname}")
        transformed_hosts[target_hostname] = attrs

    transformed.setdefault("all", {})["hosts"] = transformed_hosts

    return transformed


def split_config_sections(text: str) -> List[List[str]]:
    """
    Split config text into top-level sections.
    """
    sections: List[List[str]] = []
    current: List[str] = []

    for line in text.splitlines():
        if current and line and _SECTION_HEADER_RE.match(line):
            sections.append(current)
            current = [line]
            continue

        if not current:
            current = [line]
            continue
        current.append(line)

    if current:
        sections.append(current)

    return sections


def join_config_sections(sections: Iterable[Iterable[str]]) -> str:
    """
    Join top-level sections back into config text.
    """
    lines: List[str] = []
    for section in sections:
        lines.extend(section)
    return "\n".join(lines).rstrip() + "\n"


def render_template_body_lines(template_name: str, context: Dict[str, Any]) -> List[str]:
    """
    Render a full section template and return only body lines.
    """
    lines = render_named_template_lines(template_name, context)
    if not lines:
        return []
    return lines[1:]


def render_inserted_section_lines(template_name: str, context: Dict[str, Any]) -> List[str]:
    """
    Render a generated section and append one blank separator line.
    """
    lines = render_named_template_lines(template_name, context)
    if not lines:
        return []
    return lines + [""]


def unique_body_lines(lines: Iterable[str]) -> List[str]:
    """
    Deduplicate section body lines while preserving order.
    """
    result: List[str] = []
    seen = set()
    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def merge_section_body_lines(section: List[str], candidate_body_lines: Iterable[str]) -> List[str]:
    """
    Merge body lines into an existing top-level section.
    """
    merged = list(section)
    existing = {line.strip() for line in merged[1:] if line.strip()}

    for line in candidate_body_lines:
        normalized = line.strip()
        if not normalized or normalized in existing:
            continue
        merged.append(line if line.startswith(" ") else f"  {normalized}")
        existing.add(normalized)

    return merged


def rewrite_management_sections(
    section: List[str],
    target_subnet: Optional[ipaddress.IPv4Network],
    address_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Rewrite management-related section IPs.
    """
    if (target_subnet is None and not address_map) or not section:
        return list(section)

    header = section[0]
    updated = [header]

    if _VRF_MGMT_HEADER_RE.match(header):
        updated.extend(
            transform_vrf_management_line(line, target_subnet, address_map)
            for line in section[1:]
        )
        return updated

    if _MGMT0_HEADER_RE.match(header):
        updated.extend(
            replace_ipv4_tokens(
                line,
                target_subnet,
                replace_prefixlen=True,
                address_map=address_map,
            )
            for line in section[1:]
        )
        return updated

    if _VPC_HEADER_RE.match(header):
        for line in section[1:]:
            if "peer-keepalive" in line.lower():
                updated.append(
                    replace_ipv4_tokens(
                        line,
                        target_subnet,
                        replace_prefixlen=False,
                        address_map=address_map,
                    )
                )
            else:
                updated.append(line)
        return updated

    return list(section)


def ensure_no_switchport_for_l3_interface(section: List[str]) -> List[str]:
    """
    Insert ``no switchport`` into routed-capable interface sections that have an IP address.
    """
    if not section:
        return list(section)

    header = section[0].strip()
    if not _L3_SWITCHPORT_COMPATIBLE_INTERFACE_RE.match(header):
        return list(section)

    has_ip_address = any(_IP_ADDRESS_LINE_RE.match(line) for line in section[1:])
    has_no_switchport = any(_NO_SWITCHPORT_LINE_RE.match(line) for line in section[1:])
    if not has_ip_address or has_no_switchport:
        return list(section)

    updated = [section[0]]
    insert_at = 1
    while insert_at < len(section) and re.match(r"^\s*description\b", section[insert_at], re.IGNORECASE):
        updated.append(section[insert_at])
        insert_at += 1

    updated.append("  no switchport")
    updated.extend(section[insert_at:])
    return updated


def count_inserted_no_switchport(original: List[str], updated: List[str]) -> int:
    """
    Return 1 when ``no switchport`` was added by transformation, otherwise 0.
    """
    if any(_NO_SWITCHPORT_LINE_RE.match(line) for line in original[1:]):
        return 0
    return int(any(_NO_SWITCHPORT_LINE_RE.match(line) for line in updated[1:]))


def analyze_subinterface_conversions(sections: List[List[str]]) -> Tuple[List[SubinterfaceConversion], set[int], set[int], set[str]]:
    """
    Scan sections and collect sub-interface conversion candidates plus existing targets.
    """
    conversions: List[SubinterfaceConversion] = []
    existing_vlans: set[int] = set()
    existing_svis: set[int] = set()
    existing_parents: set[str] = set()

    for section in sections:
        if not section:
            continue
        header = section[0].strip()

        vlan_match = _VLAN_HEADER_RE.match(header)
        if vlan_match:
            existing_vlans.add(int(vlan_match.group(1)))
            continue

        svi_match = _SVI_HEADER_RE.match(header)
        if svi_match:
            existing_svis.add(int(svi_match.group(1)))
            continue

        interface_match = _INTERFACE_HEADER_RE.match(header)
        if interface_match:
            existing_parents.add(interface_match.group(1))

        subif_match = _SUBINTERFACE_HEADER_RE.match(header)
        if not subif_match:
            continue

        parent_interface = subif_match.group(1)
        subinterface_name = subif_match.group(0)
        fallback_vlan = int(subif_match.group(2))
        vlan_id = fallback_vlan
        svi_body_lines: List[str] = []

        for line in section[1:]:
            encap_match = _ENCAP_DOT1Q_RE.match(line)
            if encap_match:
                vlan_id = int(encap_match.group(1))
                continue
            if not line.strip():
                continue
            svi_body_lines.append(line.strip())

        conversions.append(
            SubinterfaceConversion(
                parent_interface=parent_interface,
                subinterface_name=subinterface_name,
                vlan_id=vlan_id,
                svi_body_lines=svi_body_lines,
            )
        )

    return conversions, existing_vlans, existing_svis, existing_parents


def build_subinterface_maps(
    conversions: List[SubinterfaceConversion],
) -> Tuple[Dict[int, List[str]], Dict[str, List[int]]]:
    """
    Aggregate sub-interface conversions by VLAN and parent interface.
    """
    svi_lines_by_vlan: Dict[int, List[str]] = {}
    parent_vlans: Dict[str, List[int]] = defaultdict(list)

    for conversion in conversions:
        vlan_id = conversion.vlan_id
        parent = conversion.parent_interface
        existing_body = svi_lines_by_vlan.get(vlan_id, [])
        svi_lines_by_vlan[vlan_id] = unique_body_lines(existing_body + conversion.svi_body_lines)
        if vlan_id not in parent_vlans[parent]:
            parent_vlans[parent].append(vlan_id)

    for parent, vlans in parent_vlans.items():
        parent_vlans[parent] = sorted(vlans)

    return svi_lines_by_vlan, dict(parent_vlans)


def build_lab_username_section(username: str, password: str) -> List[str]:
    """
    Build one NX-OS plaintext lab username command.
    """
    if not _VALID_LAB_USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Lab username may contain only letters, numbers, '.', '_', and '-'."
        )
    if not password or any(character.isspace() for character in password):
        raise ValueError("Lab password must be non-empty and must not contain whitespace.")
    return [f"username {username} password 0 {password} role network-admin"]


def remove_line_vty_access_class(section: List[str]) -> Tuple[List[str], int]:
    """
    Remove access-class commands from one line vty section.
    """
    if not section or not _LINE_VTY_HEADER_RE.match(section[0].strip()):
        return list(section), 0

    updated = [section[0]]
    removed = 0
    for line in section[1:]:
        if _ACCESS_CLASS_LINE_RE.match(line):
            removed += 1
            continue
        updated.append(line)
    return updated, removed


def transform_run_config_text(
    text: str,
    target_subnet: Optional[ipaddress.IPv4Network],
    lab_username: Optional[str] = None,
    lab_password: Optional[str] = None,
    delete_username: bool = False,
    delete_access_class: bool = False,
    hostname_map: Optional[Dict[str, str]] = None,
    management_address_map: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, int]]:
    """
    Transform one NX-OS running-config for lab use.
    """
    sections = split_config_sections(text)
    conversions, existing_vlans, existing_svis, existing_parents = analyze_subinterface_conversions(sections)
    svi_lines_by_vlan, parent_vlans = build_subinterface_maps(conversions)
    conversions_by_subif_name = {item.subinterface_name: item for item in conversions}

    new_sections: List[List[str]] = []
    inserted_vlan_ids: set[int] = set()
    processed_existing_svis: set[int] = set()
    processed_existing_parents: set[str] = set()
    inserted_no_switchport = 0
    lab_username_section: Optional[List[str]] = None
    lab_username_insert_at: Optional[int] = None
    removed_username_lines = 0
    removed_snmp_user_lines = 0
    removed_access_class_lines = 0
    renamed_hostname_lines = 0

    if not delete_username and (lab_username is not None or lab_password is not None):
        if lab_username is None or lab_password is None:
            raise ValueError("Both lab_username and lab_password are required.")
        lab_username_section = build_lab_username_section(lab_username, lab_password)

    for section in sections:
        if not section:
            continue

        rewritten_section = rewrite_management_sections(
            section,
            target_subnet,
            address_map=management_address_map,
        )
        header = rewritten_section[0].strip()

        hostname_match = _HOSTNAME_LINE_RE.match(header)
        if hostname_match:
            target_hostname = (hostname_map or {}).get(hostname_match.group(1))
            if target_hostname:
                rewritten_section[0] = f"hostname {target_hostname}"
                header = rewritten_section[0]
                renamed_hostname_lines += 1

        vdc_match = _VDC_LINE_RE.match(header)
        if vdc_match:
            target_hostname = (hostname_map or {}).get(vdc_match.group(1))
            if target_hostname:
                rewritten_section[0] = (
                    f"vdc {target_hostname}{vdc_match.group(2) or ''}"
                )
                header = rewritten_section[0]
                renamed_hostname_lines += 1

        username_match = _USERNAME_LINE_RE.match(header)
        if delete_username and username_match:
            removed_username_lines += 1
            continue
        if delete_username and _SNMP_SERVER_USER_LINE_RE.match(header):
            removed_snmp_user_lines += 1
            continue
        if lab_username_section is not None and username_match:
            if username_match.group(1).casefold() == str(lab_username).casefold():
                if lab_username_insert_at is None:
                    lab_username_insert_at = len(new_sections)
                removed_username_lines += 1
                continue

        if delete_access_class:
            rewritten_section, removed = remove_line_vty_access_class(rewritten_section)
            removed_access_class_lines += removed
            header = rewritten_section[0].strip()

        subif_match = _SUBINTERFACE_HEADER_RE.match(header)
        if subif_match:
            conversion = conversions_by_subif_name.get(subif_match.group(0))
            if conversion is not None:
                vlan_key = conversion.vlan_id
                if vlan_key not in inserted_vlan_ids:
                    if vlan_key not in existing_vlans:
                        new_sections.append(
                            render_inserted_section_lines(
                                "transform_vlan_section.j2",
                                {"vlan_id": vlan_key},
                            )
                        )
                    if vlan_key not in existing_svis:
                        new_sections.append(
                            render_inserted_section_lines(
                                "transform_svi_section.j2",
                                {
                                    "vlan_id": vlan_key,
                                    "body_lines": svi_lines_by_vlan.get(vlan_key, []),
                                },
                            )
                        )
                    inserted_vlan_ids.add(vlan_key)
            continue

        svi_match = _SVI_HEADER_RE.match(header)
        if svi_match:
            vlan_id = int(svi_match.group(1))
            if vlan_id in svi_lines_by_vlan:
                rewritten_section = merge_section_body_lines(
                    rewritten_section,
                    render_template_body_lines(
                        "transform_svi_section.j2",
                        {"vlan_id": vlan_id, "body_lines": svi_lines_by_vlan[vlan_id]},
                    ),
                )
                processed_existing_svis.add(vlan_id)
            new_sections.append(rewritten_section)
            continue

        interface_match = _INTERFACE_HEADER_RE.match(header)
        if interface_match:
            interface_name = interface_match.group(1)
            if interface_name in parent_vlans:
                rewritten_section = merge_section_body_lines(
                    rewritten_section,
                    render_template_body_lines(
                        "transform_parent_trunk_section.j2",
                        {
                            "interface_name": interface_name,
                            "vlans": parent_vlans[interface_name],
                        },
                    ),
                )
                processed_existing_parents.add(interface_name)
            original_section = list(rewritten_section)
            rewritten_section = ensure_no_switchport_for_l3_interface(rewritten_section)
            inserted_no_switchport += count_inserted_no_switchport(original_section, rewritten_section)
            new_sections.append(rewritten_section)
            continue

        new_sections.append(rewritten_section)

    if lab_username_section is not None:
        insert_at = lab_username_insert_at
        if insert_at is None:
            insert_at = next(
                (
                    index
                    for index, section in enumerate(new_sections)
                    if section and _INTERFACE_HEADER_RE.match(section[0].strip())
                ),
                len(new_sections),
            )
        new_sections.insert(insert_at, lab_username_section)

    missing_parents = sorted(set(parent_vlans) - processed_existing_parents)
    for parent in missing_parents:
        new_sections.append(
            render_inserted_section_lines(
                "transform_parent_trunk_section.j2",
                {"interface_name": parent, "vlans": parent_vlans[parent]},
            )
        )

    return join_config_sections(new_sections), {
        "management_section_updates": sum(
            1
            for section in sections
            if section
            and (
                _VRF_MGMT_HEADER_RE.match(section[0].strip())
                or _MGMT0_HEADER_RE.match(section[0].strip())
                or _VPC_HEADER_RE.match(section[0].strip())
            )
        ) if target_subnet is not None or management_address_map else 0,
        "subinterface_conversions": len(conversions),
        "generated_parent_interfaces": len(missing_parents),
        "merged_existing_parent_interfaces": len(processed_existing_parents & existing_parents),
        "merged_existing_svis": len(processed_existing_svis & existing_svis),
        "inserted_no_switchport": inserted_no_switchport,
        "removed_username_lines": removed_username_lines,
        "removed_snmp_user_lines": removed_snmp_user_lines,
        "removed_access_class_lines": removed_access_class_lines,
        "inserted_lab_username": 1 if lab_username_section is not None else 0,
        "renamed_hostname_lines": renamed_hostname_lines,
    }
