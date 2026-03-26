"""
Role detection and topology preparation helpers.
"""

from __future__ import annotations

from logging import Logger
from typing import Any, Dict, List, Optional, Tuple

from .constants import DEVICE_TYPE_TO_KIND, NETWORK_DEVICE_TYPES
from .parsing import confidence_allowed, is_excluded_interface, normalize_hostname, normalize_interface_name


def is_network_device_type(device_type: str) -> bool:
    """
    Return whether device type is considered a network device.

    Args:
        device_type: Device type string.

    Returns:
        True if network device.
    """
    return device_type in NETWORK_DEVICE_TYPES


def detect_node_role(node: str, roles: Dict[str, Any]) -> str:
    """
    Detect logical role from node name.

    Matching order:
    1. position_matches
    2. startswith
    3. endswith
    4. contains

    Args:
        node: Node name.
        roles: Role rules.

    Returns:
        Detected role or "other".
    """
    x = node.lower()

    for role, rule in roles.items():
        for item in rule.get("position_matches", []):
            pos = int(item.get("pos", -1))
            value = str(item.get("value", "")).lower()
            if pos >= 0 and value and x[pos:pos + len(value)] == value:
                return role

        for prefix in rule.get("startswith", []):
            if x.startswith(str(prefix).lower()):
                return role

        for suffix in rule.get("endswith", []):
            if x.endswith(str(suffix).lower()):
                return role

        for keyword in rule.get("contains", []):
            if str(keyword).lower() in x:
                return role

    return "other"


def detect_node_roles(node: str, roles: Dict[str, Any]) -> List[str]:
    """
    Detect all matching logical roles from node name.

    Matching order per role:
    1. position_matches
    2. startswith
    3. endswith
    4. contains

    Roles are returned in YAML definition order. If nothing matches,
    returns ["other"].

    Args:
        node: Node name.
        roles: Role rules.

    Returns:
        Matched roles list.
    """
    x = node.lower()
    matched: List[str] = []

    for role, rule in roles.items():
        role_matched = False

        for item in rule.get("position_matches", []):
            pos = int(item.get("pos", -1))
            value = str(item.get("value", "")).lower()
            if pos >= 0 and value and x[pos:pos + len(value)] == value:
                role_matched = True
                break

        if not role_matched:
            for prefix in rule.get("startswith", []):
                if x.startswith(str(prefix).lower()):
                    role_matched = True
                    break

        if not role_matched:
            for suffix in rule.get("endswith", []):
                if x.endswith(str(suffix).lower()):
                    role_matched = True
                    break

        if not role_matched:
            for keyword in rule.get("contains", []):
                if str(keyword).lower() in x:
                    role_matched = True
                    break

        if role_matched:
            matched.append(role)

    return matched or ["other"]


def get_role_priority(role: str, roles: Dict[str, Any]) -> int:
    """
    Return numeric sort priority for a role.

    Args:
        role: Role name.
        roles: Role rules.

    Returns:
        Numeric priority. Unknown roles default to 99.
    """
    rule = roles.get(role)
    if not rule:
        return 99
    return int(rule.get("priority", 99))


def order_link_endpoints(
    src_node: str,
    src_if: str,
    dst_node: str,
    dst_if: str,
    roles: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    """
    Reorder link endpoints based on role priority.

    Args:
        src_node: Source node.
        src_if: Source interface.
        dst_node: Destination node.
        dst_if: Destination interface.
        roles: Role rules.

    Returns:
        Ordered tuple (left_node, left_if, right_node, right_if)
    """
    src_role = detect_node_role(src_node, roles)
    dst_role = detect_node_role(dst_node, roles)

    src_pri = get_role_priority(src_role, roles)
    dst_pri = get_role_priority(dst_role, roles)

    if src_pri < dst_pri:
        return src_node, src_if, dst_node, dst_if
    if dst_pri < src_pri:
        return dst_node, dst_if, src_node, src_if

    if src_node <= dst_node:
        return src_node, src_if, dst_node, dst_if
    return dst_node, dst_if, src_node, src_if


def link_sort_key(link: Dict[str, Any], roles: Dict[str, Any]) -> Tuple[Any, ...]:
    """
    Return stable sort key for rendered link.

    Args:
        link: Rendered link dictionary.
        roles: Role rules.

    Returns:
        Sort tuple.
    """
    ep1, ep2 = link["endpoints"]

    node1, if1 = ep1.split(":", 1)
    node2, if2 = ep2.split(":", 1)

    role1 = detect_node_role(node1, roles)
    role2 = detect_node_role(node2, roles)

    pri1 = get_role_priority(role1, roles)
    pri2 = get_role_priority(role2, roles)

    return (
        min(pri1, pri2),
        max(pri1, pri2),
        node1,
        node2,
        if1,
        if2,
    )


def build_node_mgmt_ip_map(
    inventory_map: Dict[str, Dict[str, Any]],
    mappings: Dict[str, Any],
    logger: Optional[Logger] = None,
) -> Dict[str, str]:
    """
    Build node -> management IPv4 map from inventory.

    Source of truth is inventory host IP.

    Args:
        inventory_map: Inventory keyed by hostname.
        mappings: Mapping config.
        logger: Optional logger.

    Returns:
        Node -> management IP map.
    """
    node_ip_map: Dict[str, str] = {}

    for hostname, attrs in inventory_map.items():
        mgmt_ip = str(attrs.get("ip", "")).strip()
        if not mgmt_ip:
            continue

        normalized_name = normalize_hostname(hostname, mappings)

        if hostname in node_ip_map and node_ip_map[hostname] != mgmt_ip and logger:
            logger.warning(
                "Conflicting mgmt IP for hostname %s: existing=%s new=%s",
                hostname,
                node_ip_map[hostname],
                mgmt_ip,
            )

        if normalized_name in node_ip_map and node_ip_map[normalized_name] != mgmt_ip and logger:
            logger.warning(
                "Conflicting mgmt IP for normalized hostname %s: existing=%s new=%s",
                normalized_name,
                node_ip_map[normalized_name],
                mgmt_ip,
            )

        node_ip_map[hostname] = mgmt_ip
        node_ip_map[normalized_name] = mgmt_ip

    return node_ip_map


def build_node_definitions_from_links(
    rendered_links: List[Dict[str, Any]],
    inventory_map: Dict[str, Dict[str, Any]],
    mappings: Dict[str, Any],
    mgmt_ip_map: Dict[str, str],
    roles: Optional[Dict[str, Any]] = None,
    include_group: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Build topology.nodes from rendered links.

    Args:
        rendered_links: Rendered links.
        inventory_map: Inventory keyed by hostname.
        mappings: Mapping config.
        mgmt_ip_map: Node -> management IP map.
        roles: Role rules for group assignment.
        include_group: Whether to include node group based on role detection.

    Returns:
        Node definitions keyed by node name.
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    normalized_inventory_map: Dict[str, Dict[str, Any]] = {}

    for original_name, attrs in inventory_map.items():
        normalized_name = normalize_hostname(original_name, mappings)
        normalized_inventory_map[original_name] = attrs
        normalized_inventory_map[normalized_name] = attrs

    for link in rendered_links:
        for endpoint in link["endpoints"]:
            node_name = endpoint.split(":", 1)[0]

            host_info = normalized_inventory_map.get(node_name, {})
            device_type = str(host_info.get("device_type", "unknown"))
            kind = DEVICE_TYPE_TO_KIND.get(device_type, "linux")

            if node_name not in nodes:
                node_def: Dict[str, Any] = {"kind": kind}

                if is_network_device_type(device_type):
                    mgmt_ip = mgmt_ip_map.get(node_name, "")
                    if mgmt_ip:
                        node_def["mgmt-ipv4"] = mgmt_ip
                if include_group and roles is not None:
                    node_def["group"] = detect_node_role(node_name, roles)

                nodes[node_name] = node_def

    return dict(sorted(nodes.items(), key=lambda x: x[0]))


def build_normalized_inventory_and_mgmt_maps(
    inventory_map: Dict[str, Dict[str, Any]],
    mgmt_ip_map: Dict[str, str],
    mappings: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """
    Build normalized inventory and mgmt maps.

    Args:
        inventory_map: Inventory keyed by hostname.
        mgmt_ip_map: Node -> management IP map.
        mappings: Mapping config.

    Returns:
        (normalized_inventory_map, normalized_mgmt_ip_map)
    """
    normalized_inventory_map: Dict[str, Dict[str, Any]] = {}
    for original_name, attrs in inventory_map.items():
        normalized_name = normalize_hostname(original_name, mappings)
        normalized_inventory_map[original_name] = attrs
        normalized_inventory_map[normalized_name] = attrs

    normalized_mgmt_ip_map: Dict[str, str] = {}
    for original_name, ip in mgmt_ip_map.items():
        normalized_name = normalize_hostname(original_name, mappings)
        normalized_mgmt_ip_map[original_name] = ip
        normalized_mgmt_ip_map[normalized_name] = ip

    return normalized_inventory_map, normalized_mgmt_ip_map


def should_skip_clab_link(record: Dict[str, str], mappings: Dict[str, Any], inventory_map: Dict[str, Dict[str, Any]]) -> bool:
    """
    Decide whether a confirmed link should be excluded from topology.yml generation.

    Policy:
    - Port-channel links are always excluded.
    - Network-device to network-device links are allowed even if they are description-low,
      as long as they are confirmed.
    - Ethernet links are kept.

    Args:
        record: Confirmed link record.
        mappings: Mapping config.
        inventory_map: Inventory keyed by hostname.

    Returns:
        True if link should be skipped.
    """
    src_if = normalize_interface_name(record.get("src_if", ""), mappings)
    dst_if = normalize_interface_name(record.get("dst_if", ""), mappings)

    if src_if.lower().startswith("port-channel") or dst_if.lower().startswith("port-channel"):
        return True

    return False


def prepare_rendered_links(
    records: List[Dict[str, str]],
    mappings: Dict[str, Any],
    roles: Dict[str, Any],
    min_confidence: str,
    logger: Logger,
    log_skips: bool = True,
    inventory_map: Optional[Dict[str, Dict[str, Any]]] = None,
    clab_mode: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Normalize, filter, deduplicate, reorder, and sort links for rendering.

    Args:
        records: Input records.
        mappings: Mapping config.
        roles: Role rules.
        min_confidence: Minimum required confidence.
        logger: Logger.
        log_skips: Whether to log confidence skips.
        inventory_map: Optional inventory map.
        clab_mode: If True, apply clab-specific filtering.

    Returns:
        (rendered_links, skipped_by_confidence)
    """
    rendered_links: List[Dict[str, Any]] = []
    seen = set()
    skipped_by_confidence = 0

    for r in records:
        if not confidence_allowed(r.get("confidence", ""), min_confidence):
            skipped_by_confidence += 1
            if log_skips:
                logger.info(
                    "SKIP by confidence: %s:%s -> %s:%s (confidence=%s, min=%s)",
                    r.get("src_node", ""),
                    r.get("src_if", ""),
                    r.get("dst_node", ""),
                    r.get("dst_if", ""),
                    r.get("confidence", ""),
                    min_confidence,
                )
            continue

        if clab_mode and inventory_map is not None and should_skip_clab_link(r, mappings, inventory_map):
            logger.debug(
                "SKIP by clab filter: %s:%s -> %s:%s protocol=%s evidence=%s",
                r.get("src_node", ""),
                r.get("src_if", ""),
                r.get("dst_node", ""),
                r.get("dst_if", ""),
                r.get("protocol", ""),
                r.get("evidence", ""),
            )
            continue

        src_node = normalize_hostname(r["src_node"], mappings)
        dst_node = normalize_hostname(r["dst_node"], mappings)
        src_if = normalize_interface_name(r["src_if"], mappings)
        dst_if = normalize_interface_name(r["dst_if"], mappings)

        if is_excluded_interface(src_if, mappings) or is_excluded_interface(dst_if, mappings):
            continue

        left_node, left_if, right_node, right_if = order_link_endpoints(
            src_node, src_if, dst_node, dst_if, roles
        )

        key = (left_node, left_if, right_node, right_if)
        if key in seen:
            continue
        seen.add(key)

        rendered_links.append({
            "endpoints": [
                f"{left_node}:{left_if}",
                f"{right_node}:{right_if}",
            ]
        })

    rendered_links = sorted(rendered_links, key=lambda x: link_sort_key(x, roles))
    return rendered_links, skipped_by_confidence


def prepare_rendered_candidate_links(
    records: List[Dict[str, str]],
    mappings: Dict[str, Any],
    roles: Dict[str, Any],
    logger: Optional[Logger] = None,
) -> List[Dict[str, Any]]:
    """
    Normalize and sort candidate links for Mermaid rendering.

    Args:
        records: Candidate records.
        mappings: Mapping config.
        roles: Role rules.
        logger: Optional logger.

    Returns:
        Render-ready candidate links.
    """
    rendered_links: List[Dict[str, Any]] = []
    seen = set()

    for r in records:
        src_node = normalize_hostname(r["src_node"], mappings)
        dst_node = normalize_hostname(r["dst_node"], mappings)
        src_if = normalize_interface_name(r["src_if"], mappings)
        dst_if = normalize_interface_name(r["dst_if"], mappings)

        if logger:
            logger.debug(
                "CANDIDATE normalized: %s:%s -> %s:%s evidence=%s",
                src_node, src_if, dst_node, dst_if, r.get("evidence", "")
            )

        if is_excluded_interface(src_if, mappings) or is_excluded_interface(dst_if, mappings):
            if logger:
                logger.debug(
                    "CANDIDATE excluded: %s:%s -> %s:%s",
                    src_node, src_if, dst_node, dst_if
                )
            continue

        left_node, left_if, right_node, right_if = order_link_endpoints(
            src_node, src_if, dst_node, dst_if, roles
        )

        key = (left_node, left_if, right_node, right_if, r.get("evidence", ""))
        if key in seen:
            if logger:
                logger.debug("CANDIDATE duplicate dropped: %s", key)
            continue
        seen.add(key)

        rendered_links.append({
            "endpoints": [
                f"{left_node}:{left_if}",
                f"{right_node}:{right_if}",
            ],
            "evidence": r.get("evidence", ""),
        })

    rendered_links = sorted(rendered_links, key=lambda x: link_sort_key(x, roles))
    return rendered_links
