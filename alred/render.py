"""
Rendering helpers for containerlab YAML, Mermaid, Graphviz, draw.io, and Terraform.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .constants import (
    DRAWIO_HOST,
    DRAWIO_LAYOUT,
    DRAWIO_MODEL_ATTRIBUTES,
    DRAWIO_STYLE_CONTAINER,
    DRAWIO_STYLE_DEVICE_CONTAINER,
    DRAWIO_STYLE_DEVICE_LABEL,
    DRAWIO_STYLE_EDGE,
    DRAWIO_STYLE_EDGE_DASHED_SUFFIX,
    DRAWIO_STYLE_LEAF_CONTAINER,
    DRAWIO_STYLE_NIC,
    DRAWIO_STYLE_NODE,
    DRAWIO_VERSION,
)


def render_clab_lines(
    rendered_links: List[Dict[str, Any]],
    nodes: Dict[str, Dict[str, Any]],
    include_nodes: bool,
) -> List[str]:
    """
    Render containerlab topology YAML lines.

    Args:
        rendered_links: Rendered links.
        nodes: topology.nodes definitions.
        include_nodes: Whether to include nodes.

    Returns:
        YAML lines.
    """
    lines: List[str] = []
    lines.append("topology:")

    if include_nodes:
        lines.append("  nodes:")
        for node_name, attrs in nodes.items():
            lines.append(f"    {node_name}:")
            lines.append(f'      kind: {attrs["kind"]}')
            if "mgmt-ipv4" in attrs:
                lines.append(f'      mgmt-ipv4: {attrs["mgmt-ipv4"]}')
            if "group" in attrs:
                lines.append(f'      group: {attrs["group"]}')
        lines.append("")

    lines.append("  links:")

    current_left_node = None
    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        left_node = ep1.split(":", 1)[0]

        if left_node != current_left_node:
            if current_left_node is not None:
                lines.append("")
            lines.append(f"    # {left_node}")
            current_left_node = left_node

        lines.append(f'    - endpoints: ["{ep1}", "{ep2}"]')

    return lines


def mermaid_safe_node_id(name: str) -> str:
    """
    Convert node name into Mermaid-safe identifier.

    Args:
        name: Raw node name.

    Returns:
        Mermaid-safe node id.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def graphviz_escape(value: str) -> str:
    """
    Escape a string for Graphviz DOT quoted labels.

    Args:
        value: Raw label text.

    Returns:
        Escaped label text.
    """
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace('"', '\\"')


def drawio_modified_timestamp() -> str:
    """
    Build draw.io-compatible modified timestamp in UTC.

    Returns:
        Timestamp like 2026-04-05T12:34:56.789Z.
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_mermaid_node_line(node_name: str, mgmt_ip: str = "") -> str:
    """
    Build Mermaid node line.

    Args:
        node_name: Node name.
        mgmt_ip: Optional management IP label.

    Returns:
        Mermaid node declaration line.
    """
    node_id = mermaid_safe_node_id(node_name)
    label = f"{node_name}<br/>mgmt: {mgmt_ip}" if mgmt_ip else node_name
    return f'  {node_id}["{label}"]'


def build_mermaid_node_line_with_label(node_name: str, address_value: str = "", address_label: str = "mgmt") -> str:
    """
    Build Mermaid node line with custom address label.

    Args:
        node_name: Node name.
        address_value: Optional address value.
        address_label: Label prefix such as mgmt or lo0.

    Returns:
        Mermaid node declaration line.
    """
    node_id = mermaid_safe_node_id(node_name)
    label = f"{node_name}<br/>{address_label}: {address_value}" if address_value else node_name
    return f'  {node_id}["{label}"]'


def build_mermaid_node_line_with_lines(node_name: str, lines: List[str]) -> str:
    """
    Build Mermaid node line with multiple label lines.

    Args:
        node_name: Node name.
        lines: Label lines, e.g. ["lo0: 10.0.0.1/32", "lo1: 10.0.1.1/32"].

    Returns:
        Mermaid node declaration line.
    """
    node_id = mermaid_safe_node_id(node_name)
    if not lines:
        return f'  {node_id}["{node_name}"]'
    label = f"{node_name}<br/>" + "<br/>".join(lines)
    return f'  {node_id}["{label}"]'


def build_mermaid_link_line(
    left_node: str,
    left_if: str,
    right_node: str,
    right_if: str,
    candidate: bool = False,
    evidence: str = "",
    label_override: str = "",
) -> str:
    """
    Build Mermaid edge line.

    Args:
        left_node: Left node.
        left_if: Left interface.
        right_node: Right node.
        right_if: Right interface.
        candidate: Whether candidate link.
        evidence: Optional evidence label.
        label_override: Optional full edge label.

    Returns:
        Mermaid edge line.
    """
    left_id = mermaid_safe_node_id(left_node)
    right_id = mermaid_safe_node_id(right_node)

    if candidate:
        label = f"{left_if} ? {right_if}<br/>{evidence}" if evidence else f"{left_if} ? {right_if}"
        return f'  {left_id} -.->|"{label}"| {right_id}'

    label = label_override or f"{left_if} ↔ {right_if}"
    return f'  {left_id} -->|"{label}"| {right_id}'


def render_mermaid_graph_lines(
    rendered_links: List[Dict[str, Any]],
    roles: Dict[str, Any],
    normalized_inventory_map: Dict[str, Dict[str, Any]],
    normalized_mgmt_ip_map: Dict[str, str],
    detect_node_role_func: Callable[[str, Dict[str, Any]], str],
    get_role_priority_func: Callable[[str, Dict[str, Any]], int],
    is_network_device_type_func: Callable[[str], bool],
    direction: str,
    group_by_role: bool,
    add_comments: bool,
    candidate_links: Optional[List[Dict[str, Any]]] = None,
    node_address_map: Optional[Dict[str, str]] = None,
    node_address_label_map: Optional[Dict[str, str]] = None,
    node_address_lines_map: Optional[Dict[str, List[str]]] = None,
    link_label_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Render Mermaid graph lines.

    Args:
        rendered_links: Confirmed rendered links.
        roles: Role rules.
        normalized_inventory_map: Inventory lookup.
        normalized_mgmt_ip_map: Mgmt IP lookup.
        detect_node_role_func: Injected role detection function.
        get_role_priority_func: Injected role priority function.
        is_network_device_type_func: Injected device type checker.
        direction: Mermaid direction.
        group_by_role: Whether to use role subgraphs.
        add_comments: Whether to add comments by left node.
        candidate_links: Optional candidate links.
        node_address_map: Optional node -> displayed address map.
        node_address_label_map: Optional node -> address label map.
        node_address_lines_map: Optional node -> multiple address label lines.
        link_label_map: Optional link label override map.

    Returns:
        Mermaid graph lines without markdown fences.
    """
    node_names = set()

    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        node_names.add(ep1.split(":", 1)[0])
        node_names.add(ep2.split(":", 1)[0])

    if candidate_links:
        for link in candidate_links:
            ep1, ep2 = link["endpoints"]
            node_names.add(ep1.split(":", 1)[0])
            node_names.add(ep2.split(":", 1)[0])

    sorted_nodes = sorted(
        node_names,
        key=lambda n: (
            get_role_priority_func(detect_node_role_func(n, roles), roles),
            n,
        ),
    )

    lines: List[str] = []
    lines.append(f"graph {direction}")

    if group_by_role:
        role_to_nodes: Dict[str, List[str]] = {}
        for node in sorted_nodes:
            role = detect_node_role_func(node, roles)
            role_to_nodes.setdefault(role, []).append(node)

        for role, nodes in sorted(
            role_to_nodes.items(),
            key=lambda x: (get_role_priority_func(x[0], roles), x[0]),
        ):
            subgraph_name = role.replace("-", "_")
            lines.append(f"  subgraph {subgraph_name}[{role}]")
            for node in nodes:
                host_info = normalized_inventory_map.get(node, {})
                device_type = str(host_info.get("device_type", "unknown"))
                address_value = ""
                address_label = "mgmt"
                if is_network_device_type_func(device_type):
                    if node_address_lines_map and node in node_address_lines_map:
                        lines.append(build_mermaid_node_line_with_lines(node, node_address_lines_map[node]))
                        continue
                    address_value = (node_address_map or normalized_mgmt_ip_map).get(node, "")
                    address_label = (node_address_label_map or {}).get(node, "mgmt")
                lines.append(build_mermaid_node_line_with_label(node, address_value, address_label))
            lines.append("  end")
    else:
        for node in sorted_nodes:
            host_info = normalized_inventory_map.get(node, {})
            device_type = str(host_info.get("device_type", "unknown"))
            address_value = ""
            address_label = "mgmt"
            if is_network_device_type_func(device_type):
                if node_address_lines_map and node in node_address_lines_map:
                    lines.append(build_mermaid_node_line_with_lines(node, node_address_lines_map[node]))
                    continue
                address_value = (node_address_map or normalized_mgmt_ip_map).get(node, "")
                address_label = (node_address_label_map or {}).get(node, "mgmt")
            lines.append(build_mermaid_node_line_with_label(node, address_value, address_label))

    lines.append("")

    current_left_node = None
    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        left_node, left_if = ep1.split(":", 1)
        right_node, right_if = ep2.split(":", 1)

        if add_comments and left_node != current_left_node:
            if current_left_node is not None:
                lines.append("")
            lines.append(f"  %% {left_node}")
            current_left_node = left_node

        link_key = f"{left_node}|{left_if}|{right_node}|{right_if}"
        label_override = (link_label_map or {}).get(link_key, "")
        lines.append(
            build_mermaid_link_line(
                left_node,
                left_if,
                right_node,
                right_if,
                candidate=False,
                label_override=label_override,
            )
        )

    if candidate_links:
        lines.append("")
        lines.append("  %% candidate links")
        for link in candidate_links:
            ep1, ep2 = link["endpoints"]
            left_node, left_if = ep1.split(":", 1)
            right_node, right_if = ep2.split(":", 1)
            evidence = link.get("evidence", "")
            lines.append(
                build_mermaid_link_line(
                    left_node,
                    left_if,
                    right_node,
                    right_if,
                    candidate=True,
                    evidence=evidence,
                )
            )

    return lines


def render_mermaid_markdown_lines(
    rendered_links: List[Dict[str, Any]],
    roles: Dict[str, Any],
    normalized_inventory_map: Dict[str, Dict[str, Any]],
    normalized_mgmt_ip_map: Dict[str, str],
    detect_node_role_func: Callable[[str, Dict[str, Any]], str],
    get_role_priority_func: Callable[[str, Dict[str, Any]], int],
    is_network_device_type_func: Callable[[str], bool],
    direction: str,
    group_by_role: bool,
    add_comments: bool,
    title: str,
    candidate_links: Optional[List[Dict[str, Any]]] = None,
    node_address_map: Optional[Dict[str, str]] = None,
    node_address_label_map: Optional[Dict[str, str]] = None,
    node_address_lines_map: Optional[Dict[str, List[str]]] = None,
    link_label_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Render Markdown lines containing Mermaid fenced block.

    Args:
        rendered_links: Confirmed rendered links.
        roles: Role rules.
        normalized_inventory_map: Inventory lookup.
        normalized_mgmt_ip_map: Mgmt IP lookup.
        detect_node_role_func: Injected role detection function.
        get_role_priority_func: Injected role priority function.
        is_network_device_type_func: Injected device type checker.
        direction: Mermaid direction.
        group_by_role: Whether to use subgraphs.
        add_comments: Whether to add comments.
        title: Markdown title.
        candidate_links: Optional candidate links.
        node_address_map: Optional node -> displayed address map.
        node_address_label_map: Optional node -> address label map.
        node_address_lines_map: Optional node -> multiple address label lines.
        link_label_map: Optional link label override map.

    Returns:
        Markdown lines.
    """
    graph_lines = render_mermaid_graph_lines(
        rendered_links=rendered_links,
        roles=roles,
        normalized_inventory_map=normalized_inventory_map,
        normalized_mgmt_ip_map=normalized_mgmt_ip_map,
        detect_node_role_func=detect_node_role_func,
        get_role_priority_func=get_role_priority_func,
        is_network_device_type_func=is_network_device_type_func,
        direction=direction,
        group_by_role=group_by_role,
        add_comments=add_comments,
        candidate_links=candidate_links,
        node_address_map=node_address_map,
        node_address_label_map=node_address_label_map,
        node_address_lines_map=node_address_lines_map,
        link_label_map=link_label_map,
    )

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("```mermaid")
    lines.extend(graph_lines)
    lines.append("```")

    return lines


def render_graphviz_dot_lines(
    rendered_links: List[Dict[str, Any]],
    roles: Dict[str, Any],
    normalized_inventory_map: Dict[str, Dict[str, Any]],
    normalized_mgmt_ip_map: Dict[str, str],
    detect_node_role_func: Callable[[str, Dict[str, Any]], str],
    get_role_priority_func: Callable[[str, Dict[str, Any]], int],
    is_network_device_type_func: Callable[[str], bool],
    direction: str,
    group_by_role: bool,
    add_comments: bool,
    title: str,
    candidate_links: Optional[List[Dict[str, Any]]] = None,
    node_address_map: Optional[Dict[str, str]] = None,
    node_address_label_map: Optional[Dict[str, str]] = None,
    node_address_lines_map: Optional[Dict[str, List[str]]] = None,
    link_label_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Render Graphviz DOT lines.

    Args:
        rendered_links: Confirmed rendered links.
        roles: Role rules.
        normalized_inventory_map: Inventory lookup.
        normalized_mgmt_ip_map: Mgmt IP lookup.
        detect_node_role_func: Injected role detection function.
        get_role_priority_func: Injected role priority function.
        is_network_device_type_func: Injected device type checker.
        direction: Diagram direction.
        group_by_role: Whether to use role clusters.
        add_comments: Whether to add comments.
        title: Graph label shown at top.
        candidate_links: Optional candidate links.
        node_address_map: Optional node -> displayed address map.
        node_address_label_map: Optional node -> address label map.
        node_address_lines_map: Optional node -> multiple address label lines.
        link_label_map: Optional link label override map.

    Returns:
        DOT lines.
    """
    rankdir_map = {
        "TD": "TB",
        "BT": "BT",
        "LR": "LR",
        "RL": "RL",
    }
    rankdir = rankdir_map.get(direction, "TB")

    node_names = set()

    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        node_names.add(ep1.split(":", 1)[0])
        node_names.add(ep2.split(":", 1)[0])

    if candidate_links:
        for link in candidate_links:
            ep1, ep2 = link["endpoints"]
            node_names.add(ep1.split(":", 1)[0])
            node_names.add(ep2.split(":", 1)[0])

    sorted_nodes = sorted(
        node_names,
        key=lambda n: (
            get_role_priority_func(detect_node_role_func(n, roles), roles),
            n,
        ),
    )

    lines: List[str] = []
    lines.append("graph topology {")
    lines.append(f'  label="{graphviz_escape(title)}";')
    lines.append('  labelloc="t";')
    lines.append('  rankdir="%s";' % rankdir)
    lines.append('  graph [fontname="Helvetica"];')
    lines.append('  node [shape=box, style="rounded", fontname="Helvetica"];')
    lines.append('  edge [fontname="Helvetica"];')
    lines.append("")

    def build_node_label(node: str) -> str:
        host_info = normalized_inventory_map.get(node, {})
        device_type = str(host_info.get("device_type", "unknown"))
        label_lines = [node]
        if is_network_device_type_func(device_type):
            if node_address_lines_map and node in node_address_lines_map:
                label_lines.extend(node_address_lines_map[node])
            else:
                address_value = (node_address_map or normalized_mgmt_ip_map).get(node, "")
                address_label = (node_address_label_map or {}).get(node, "mgmt")
                if address_value:
                    label_lines.append(f"{address_label}: {address_value}")
        return graphviz_escape("\n".join(label_lines))

    if group_by_role:
        role_to_nodes: Dict[str, List[str]] = {}
        for node in sorted_nodes:
            role = detect_node_role_func(node, roles)
            role_to_nodes.setdefault(role, []).append(node)

        for role, nodes in sorted(
            role_to_nodes.items(),
            key=lambda x: (get_role_priority_func(x[0], roles), x[0]),
        ):
            cluster_name = mermaid_safe_node_id(role)
            lines.append(f"  subgraph cluster_{cluster_name} {{")
            lines.append(f'    label="{graphviz_escape(role)}";')
            for node in nodes:
                node_id = mermaid_safe_node_id(node)
                lines.append(f'    {node_id} [label="{build_node_label(node)}"];')
            lines.append("  }")
    else:
        for node in sorted_nodes:
            node_id = mermaid_safe_node_id(node)
            lines.append(f'  {node_id} [label="{build_node_label(node)}"];')

    lines.append("")

    current_left_node = None
    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        left_node, left_if = ep1.split(":", 1)
        right_node, right_if = ep2.split(":", 1)
        left_id = mermaid_safe_node_id(left_node)
        right_id = mermaid_safe_node_id(right_node)

        if add_comments and left_node != current_left_node:
            if current_left_node is not None:
                lines.append("")
            lines.append(f"  // {left_node}")
            current_left_node = left_node

        link_key = f"{left_node}|{left_if}|{right_node}|{right_if}"
        label = (link_label_map or {}).get(link_key, "") or f"{left_if} ↔ {right_if}"
        lines.append(f'  {left_id} -- {right_id} [label="{graphviz_escape(label)}"];')

    if candidate_links:
        lines.append("")
        lines.append("  // candidate links")
        for link in candidate_links:
            ep1, ep2 = link["endpoints"]
            left_node, left_if = ep1.split(":", 1)
            right_node, right_if = ep2.split(":", 1)
            evidence = str(link.get("evidence", "")).strip()
            label = f"{left_if} ? {right_if}"
            if evidence:
                label = f"{label}\n{evidence}"
            left_id = mermaid_safe_node_id(left_node)
            right_id = mermaid_safe_node_id(right_node)
            lines.append(
                f'  {left_id} -- {right_id} [label="{graphviz_escape(label)}", style=dashed, color=gray50];'
            )

    lines.append("}")
    return lines


def render_drawio_xml_lines(
    rendered_links: List[Dict[str, Any]],
    roles: Dict[str, Any],
    normalized_inventory_map: Dict[str, Dict[str, Any]],
    normalized_mgmt_ip_map: Dict[str, str],
    detect_node_role_func: Callable[[str, Dict[str, Any]], str],
    get_role_priority_func: Callable[[str, Dict[str, Any]], int],
    is_network_device_type_func: Callable[[str], bool],
    direction: str,
    group_by_role: bool,
    add_comments: bool,
    title: str,
    candidate_links: Optional[List[Dict[str, Any]]] = None,
    node_address_map: Optional[Dict[str, str]] = None,
    node_address_label_map: Optional[Dict[str, str]] = None,
    node_address_lines_map: Optional[Dict[str, List[str]]] = None,
    link_label_map: Optional[Dict[str, str]] = None,
    node_interface_label_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Render draw.io XML lines.

    Args:
        rendered_links: Confirmed rendered links.
        roles: Role rules.
        normalized_inventory_map: Inventory lookup.
        normalized_mgmt_ip_map: Mgmt IP lookup.
        detect_node_role_func: Injected role detection function.
        get_role_priority_func: Injected role priority function.
        is_network_device_type_func: Injected device type checker.
        direction: Diagram direction.
        group_by_role: Whether to use role containers.
        add_comments: Whether to add section comments.
        title: Diagram title.
        candidate_links: Optional candidate links.
        node_address_map: Optional node -> displayed address map.
        node_address_label_map: Optional node -> address label map.
        node_address_lines_map: Optional node -> multiple address label lines.
        link_label_map: Optional link label override map.
        node_interface_label_map: Optional "node|interface" -> displayed NIC label map.

    Returns:
        draw.io XML lines.
    """
    del add_comments

    all_links = list(rendered_links)
    if candidate_links:
        all_links.extend(candidate_links)

    node_names = set()
    for link in all_links:
        ep1, ep2 = link["endpoints"]
        node_names.add(ep1.split(":", 1)[0])
        node_names.add(ep2.split(":", 1)[0])

    sorted_nodes = sorted(
        node_names,
        key=lambda n: (
            get_role_priority_func(detect_node_role_func(n, roles), roles),
            n,
        ),
    )

    origin_x = int(DRAWIO_LAYOUT["origin_x"])
    origin_y = int(DRAWIO_LAYOUT["origin_y"])
    node_width = int(DRAWIO_LAYOUT["node_width"])
    node_height = int(DRAWIO_LAYOUT["node_height"])
    node_gap_x = int(DRAWIO_LAYOUT["node_gap_x"])
    node_gap_y = int(DRAWIO_LAYOUT["node_gap_y"])
    container_padding = int(DRAWIO_LAYOUT["container_padding"])
    container_header = int(DRAWIO_LAYOUT["container_header"])
    container_gap = int(DRAWIO_LAYOUT["container_gap"])
    nic_top_gap = int(DRAWIO_LAYOUT["nic_top_gap"])
    nic_box_width = int(DRAWIO_LAYOUT["nic_box_width"])
    nic_box_height = int(DRAWIO_LAYOUT["nic_box_height"])
    nic_box_gap = int(DRAWIO_LAYOUT["nic_box_gap"])

    node_role_map = {node: detect_node_role_func(node, roles) for node in sorted_nodes}
    role_priority_map = {
        role: get_role_priority_func(role, roles)
        for role in {node_role_map[node] for node in sorted_nodes}
    }
    horizontal = direction in {"LR", "RL"}
    leaf_roles = sorted(
        [role for role in set(node_role_map.values()) if "leaf" in role.lower()],
        key=lambda role: (role_priority_map.get(role, 9999), role),
    )
    primary_leaf_role = leaf_roles[0] if leaf_roles else None
    leaf_priority = role_priority_map.get(primary_leaf_role, 9999)
    node_is_network_device_map = {}
    for node in sorted_nodes:
        host_info = normalized_inventory_map.get(node, {})
        device_type = str(host_info.get("device_type", "unknown"))
        node_is_network_device_map[node] = is_network_device_type_func(device_type)
    adjacency_map: Dict[str, List[str]] = {node: [] for node in sorted_nodes}
    node_interfaces_map: Dict[str, List[str]] = {node: [] for node in sorted_nodes}
    node_interface_side_map: Dict[tuple[str, str], str] = {}

    def infer_interface_side(node_name: str, peer_name: str) -> str:
        node_priority = role_priority_map.get(node_role_map.get(node_name, ""), 9999)
        peer_priority = role_priority_map.get(node_role_map.get(peer_name, ""), 9999)
        if horizontal:
            return "left" if peer_priority < node_priority else "right"
        return "top" if peer_priority < node_priority else "bottom"

    for link in all_links:
        ep1, ep2 = link["endpoints"]
        left_node = ep1.split(":", 1)[0]
        right_node = ep2.split(":", 1)[0]
        adjacency_map.setdefault(left_node, []).append(right_node)
        adjacency_map.setdefault(right_node, []).append(left_node)
        left_if = ep1.split(":", 1)[1]
        right_if = ep2.split(":", 1)[1]
        if left_if and left_if not in node_interfaces_map.setdefault(left_node, []):
            node_interfaces_map[left_node].append(left_if)
            node_interface_side_map[(left_node, left_if)] = infer_interface_side(left_node, right_node)
        if right_if and right_if not in node_interfaces_map.setdefault(right_node, []):
            node_interfaces_map[right_node].append(right_if)
            node_interface_side_map[(right_node, right_if)] = infer_interface_side(right_node, left_node)

    def build_node_value(node: str) -> str:
        host_info = normalized_inventory_map.get(node, {})
        device_type = str(host_info.get("device_type", "unknown"))
        lines = [node]
        if node_address_lines_map and node in node_address_lines_map:
            lines.extend(node_address_lines_map[node])
        elif is_network_device_type_func(device_type):
            address_value = (node_address_map or normalized_mgmt_ip_map).get(node, "")
            address_label = (node_address_label_map or {}).get(node, "mgmt")
            if address_value:
                lines.append(f"{address_label}: {address_value}")
        return "<br>".join(lines)

    def get_node_content_height(node: str) -> int:
        line_count = max(build_node_value(node).count("<br>") + 1, 1)
        return max(node_height, 28 + max(line_count - 1, 0) * 20)

    cell_specs: List[Dict[str, Any]] = []
    node_id_map: Dict[str, str] = {}
    node_geometry_map: Dict[str, Dict[str, Any]] = {}
    nic_id_map: Dict[tuple[str, str], str] = {}
    next_id = 2

    def alloc_id() -> str:
        nonlocal next_id
        next_id += 1
        return str(next_id)

    def add_node(node: str, x: int, y: int, parent_id: str = "1") -> None:
        if node_interfaces_map.get(node):
            node_id = alloc_id()
            node_id_map[node] = node_id
            footprint_height = get_node_footprint_height(node)
            footprint_width = get_node_footprint_width(node)
            interfaces = node_interfaces_map.get(node, [])
            top_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "top")
            bottom_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "bottom")
            left_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "left")
            right_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "right")
            top_extra = nic_box_height if top_count else 0
            bottom_extra = nic_box_height if bottom_count else 0
            left_extra = nic_box_width + nic_top_gap if left_count else 0
            right_extra = nic_box_width + nic_top_gap if right_count else 0
            content_x = left_extra
            content_y = top_extra
            content_width = max(footprint_width - left_extra - right_extra, node_width)
            content_height = max(footprint_height - top_extra - bottom_extra, get_node_content_height(node))
            node_geometry_map[node] = {
                "parent": parent_id,
                "x": x,
                "y": y,
                "width": footprint_width,
                "height": footprint_height,
                "container_id": node_id,
                "content_x": content_x,
                "content_y": content_y,
                "content_width": content_width,
                "content_height": content_height,
            }
            cell_specs.append(
                {
                    "kind": "vertex",
                    "id": node_id,
                    "value": "",
                    "style": DRAWIO_STYLE_DEVICE_CONTAINER,
                    "parent": parent_id,
                    "x": x,
                    "y": y,
                    "width": footprint_width,
                    "height": footprint_height,
                }
            )
            label_id = alloc_id()
            cell_specs.append(
                {
                    "kind": "vertex",
                    "id": label_id,
                    "value": build_node_value(node),
                    "style": DRAWIO_STYLE_DEVICE_LABEL,
                    "parent": str(node_id),
                    "x": content_x,
                    "y": content_y,
                    "width": content_width,
                    "height": content_height,
                }
            )
            add_nic_boxes_for_node(node)
            return

        node_id = alloc_id()
        node_id_map[node] = node_id
        node_geometry_map[node] = {
            "parent": parent_id,
                "x": x,
                "y": y,
                "width": node_width,
                "height": get_node_content_height(node),
                "container_id": node_id,
            }
        cell_specs.append(
            {
                "kind": "vertex",
                "id": node_id,
                "value": build_node_value(node),
                "style": DRAWIO_STYLE_NODE,
                "parent": parent_id,
                "x": x,
                "y": y,
                "width": node_width,
                "height": get_node_content_height(node),
            }
        )

    def get_node_footprint_height(node: str) -> int:
        base_content_height = get_node_content_height(node)
        if not node_interfaces_map.get(node):
            return base_content_height
        interfaces = node_interfaces_map.get(node, [])
        top_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "top")
        bottom_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "bottom")
        left_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "left")
        right_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "right")
        vertical_extra = 0
        if top_count:
            vertical_extra += nic_top_gap + nic_box_height
        if bottom_count:
            vertical_extra += nic_top_gap + nic_box_height
        side_column_height = 0
        if left_count:
            side_column_height = max(side_column_height, nic_top_gap + left_count * nic_box_height + max(left_count - 1, 0) * nic_box_gap)
        if right_count:
            side_column_height = max(side_column_height, nic_top_gap + right_count * nic_box_height + max(right_count - 1, 0) * nic_box_gap)
        return max(base_content_height + vertical_extra, base_content_height + side_column_height)

    def get_node_footprint_width(node: str) -> int:
        if not node_interfaces_map.get(node):
            return node_width
        interfaces = node_interfaces_map.get(node, [])
        top_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "top")
        bottom_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "bottom")
        left_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "left")
        right_count = sum(1 for iface in interfaces if node_interface_side_map.get((node, iface)) == "right")

        row_width = 0
        if top_count:
            row_width = max(row_width, top_count * nic_box_width + max(top_count - 1, 0) * nic_box_gap)
        if bottom_count:
            row_width = max(row_width, bottom_count * nic_box_width + max(bottom_count - 1, 0) * nic_box_gap)
        center_width = max(node_width, row_width)
        left_extra = nic_box_width + nic_top_gap if left_count else 0
        right_extra = nic_box_width + nic_top_gap if right_count else 0
        return max(center_width + left_extra + right_extra, node_width)

    def add_nic_boxes_for_node(node: str) -> None:
        if not node_interfaces_map.get(node):
            return
        geom = node_geometry_map.get(node)
        if not geom:
            return
        interfaces = node_interfaces_map.get(node, [])
        parent_id = str(geom["container_id"])

        grouped_interfaces = {
            "top": [iface for iface in interfaces if node_interface_side_map.get((node, iface)) == "top"],
            "bottom": [iface for iface in interfaces if node_interface_side_map.get((node, iface)) == "bottom"],
            "left": [iface for iface in interfaces if node_interface_side_map.get((node, iface)) == "left"],
            "right": [iface for iface in interfaces if node_interface_side_map.get((node, iface)) == "right"],
        }

        total_width = int(geom["width"])
        total_height = int(geom["height"])
        content_y = int(geom.get("content_y", 0))
        content_height = int(geom.get("content_height", node_height))

        for side, side_interfaces in grouped_interfaces.items():
            for index, iface in enumerate(side_interfaces):
                if side == "top":
                    row_width = len(side_interfaces) * nic_box_width + max(len(side_interfaces) - 1, 0) * nic_box_gap
                    nic_x = max((total_width - row_width) // 2, 0) + index * (nic_box_width + nic_box_gap)
                    nic_y = 0
                elif side == "bottom":
                    row_width = len(side_interfaces) * nic_box_width + max(len(side_interfaces) - 1, 0) * nic_box_gap
                    nic_x = max((total_width - row_width) // 2, 0) + index * (nic_box_width + nic_box_gap)
                    nic_y = total_height - nic_box_height
                elif side == "left":
                    nic_x = nic_top_gap
                    nic_y = content_y + max((content_height - (len(side_interfaces) * nic_box_height + max(len(side_interfaces) - 1, 0) * nic_box_gap)) // 2, 0) + index * (nic_box_height + nic_box_gap)
                else:
                    nic_x = total_width - nic_box_width - nic_top_gap
                    nic_y = content_y + max((content_height - (len(side_interfaces) * nic_box_height + max(len(side_interfaces) - 1, 0) * nic_box_gap)) // 2, 0) + index * (nic_box_height + nic_box_gap)

                nic_id = alloc_id()
                nic_id_map[(node, iface)] = nic_id
                if node_interface_label_map is not None:
                    nic_value = (node_interface_label_map or {}).get(f"{node}|{iface}", "IP Unknown")
                else:
                    nic_value = iface
                cell_specs.append(
                    {
                        "kind": "vertex",
                        "id": nic_id,
                        "value": nic_value,
                        "style": DRAWIO_STYLE_NIC,
                        "parent": parent_id,
                        "x": nic_x,
                        "y": nic_y,
                        "width": nic_box_width,
                        "height": nic_box_height,
                    }
                )

    def add_container(container_id: str, label: str, x: int, y: int, width: int, height: int, style: str) -> None:
        cell_specs.append(
            {
                "kind": "vertex",
                "id": container_id,
                "value": label,
                "style": style,
                "parent": "1",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        )

    if group_by_role:
        role_to_nodes: Dict[str, List[str]] = {}
        for node in sorted_nodes:
            role = node_role_map[node]
            role_to_nodes.setdefault(role, []).append(node)

        role_items = sorted(
            role_to_nodes.items(),
            key=lambda x: (get_role_priority_func(x[0], roles), x[0]),
        )
        leaf_nodes = role_to_nodes.get(primary_leaf_role or "", [])
        leaf_order_map = {node: index for index, node in enumerate(leaf_nodes)}

        def get_attached_leaf_index(node: str) -> float:
            if node in leaf_order_map:
                return float(leaf_order_map[node])
            attached_leaf_indexes = sorted(
                leaf_order_map[neighbor]
                for neighbor in adjacency_map.get(node, [])
                if neighbor in leaf_order_map
            )
            if attached_leaf_indexes:
                return sum(attached_leaf_indexes) / len(attached_leaf_indexes)
            return float(len(leaf_order_map) + 1000)

        def get_node_sort_key(node: str) -> tuple[float, str]:
            role = node_role_map[node]
            if role == primary_leaf_role:
                return (get_attached_leaf_index(node), node)
            if role_priority_map.get(role, 9999) > leaf_priority and leaf_order_map:
                return (get_attached_leaf_index(node), node)
            return (float(sorted_nodes.index(node)), node)

        for role, nodes in role_items:
            role_to_nodes[role] = sorted(nodes, key=get_node_sort_key)

        def compute_container_dimensions(role: str, nodes: List[str]) -> tuple[int, int, int]:
            if horizontal:
                columns = 1
            else:
                columns = max(len(nodes), 1)
            rows = (len(nodes) + columns - 1) // columns
            if horizontal:
                container_width = max(get_node_footprint_width(node) for node in nodes) + container_padding * 2
                container_height = (
                    sum(get_node_footprint_height(node) for node in nodes)
                    + max(len(nodes) - 1, 0) * node_gap_y
                    + container_padding * 2
                    + container_header
                )
            else:
                container_width = (
                    sum(get_node_footprint_width(node) for node in nodes)
                    + max(len(nodes) - 1, 0) * node_gap_x
                    + container_padding * 2
                )
                container_height = (
                    max(get_node_footprint_height(node) for node in nodes)
                    + container_padding * 2
                    + container_header
                )
            return columns, container_width, container_height

        def compute_role_anchor(role: str, nodes: List[str]) -> float | None:
            if role == primary_leaf_role or not leaf_order_map:
                return None
            if role_priority_map.get(role, 9999) <= leaf_priority:
                return None
            anchor_values = [
                get_attached_leaf_index(node)
                for node in nodes
                if get_attached_leaf_index(node) < float(len(leaf_order_map) + 999)
            ]
            if not anchor_values:
                return None
            return sum(anchor_values) / len(anchor_values)

        def build_container_style(is_leaf: bool = False) -> str:
            base_style = DRAWIO_STYLE_LEAF_CONTAINER if is_leaf else DRAWIO_STYLE_CONTAINER
            return f"{base_style}startSize={container_header};"

        def group_roles_by_priority(role_pairs: List[tuple[str, List[str]]]) -> List[List[tuple[str, List[str]]]]:
            grouped: Dict[int, List[tuple[str, List[str]]]] = {}
            for role, nodes in role_pairs:
                grouped.setdefault(role_priority_map.get(role, 9999), []).append((role, nodes))
            return [grouped[key] for key in sorted(grouped.keys())]

        if horizontal and primary_leaf_role:
            left_roles = []
            right_roles = []
            for role, nodes in role_items:
                if role == primary_leaf_role:
                    continue
                if role_priority_map.get(role, 9999) <= leaf_priority:
                    left_roles.append((role, nodes))
                else:
                    right_roles.append((role, nodes))

            def estimate_vertical_stack_height(role_pairs: List[tuple[str, List[str]]]) -> int:
                if not role_pairs:
                    return 0
                heights = [compute_container_dimensions(role, nodes)[2] for role, nodes in role_pairs]
                return sum(heights) + max(len(heights) - 1, 0) * container_gap

            leaf_nodes_sorted = role_to_nodes[primary_leaf_role]
            leaf_columns, leaf_width, leaf_height = compute_container_dimensions(primary_leaf_role, leaf_nodes_sorted)
            right_role_bands = group_roles_by_priority(right_roles)

            def estimate_right_band_height(band: List[tuple[str, List[str]]]) -> int:
                if not band:
                    return 0
                sorted_band = sorted(
                    band,
                    key=lambda item: (
                        compute_role_anchor(item[0], item[1]) if compute_role_anchor(item[0], item[1]) is not None else float(len(leaf_nodes_sorted) + 1000),
                        role_priority_map.get(item[0], 9999),
                        item[0],
                    ),
                )
                row_bottom_map: Dict[int, int] = {}
                next_free_y = 0
                max_bottom = 0
                for role, nodes in sorted_band:
                    _columns, _container_width, container_height = compute_container_dimensions(role, nodes)
                    anchor = compute_role_anchor(role, nodes)
                    if anchor is None:
                        row_key = len(row_bottom_map) + 1000
                    else:
                        row_key = int(round(anchor))
                    if row_key not in row_bottom_map:
                        row_y = max(next_free_y, row_key * (node_height + node_gap_y))
                    else:
                        row_y = row_bottom_map[row_key]
                    row_bottom_map[row_key] = row_y + container_height + container_gap
                    next_free_y = max(next_free_y, row_bottom_map[row_key])
                    max_bottom = max(max_bottom, row_y + container_height)
                return max_bottom

            left_total_height = estimate_vertical_stack_height(left_roles)
            right_total_height = max([estimate_right_band_height(band) for band in right_role_bands], default=0)
            overall_height = max(left_total_height, leaf_height, right_total_height, node_height)
            leaf_y = origin_y + max((overall_height - leaf_height) // 2, 0)
            right_base_y = origin_y + max((overall_height - right_total_height) // 2, 0)

            cursor_x = origin_x
            for role, nodes in left_roles:
                columns, container_width, container_height = compute_container_dimensions(role, nodes)
                container_y = origin_y + max((overall_height - container_height) // 2, 0)
                container_id = alloc_id()
                add_container(
                    container_id=container_id,
                    label=role,
                    x=cursor_x,
                    y=container_y,
                    width=container_width,
                    height=container_height,
                    style=build_container_style(),
                )
                node_cursor_y = container_header + container_padding
                for node in nodes:
                    add_node(
                        node=node,
                        x=container_padding,
                        y=node_cursor_y,
                        parent_id=container_id,
                    )
                    node_cursor_y += get_node_footprint_height(node) + node_gap_y
                cursor_x += container_width + container_gap

            leaf_x = cursor_x
            leaf_container_id = alloc_id()
            add_container(
                container_id=leaf_container_id,
                label=primary_leaf_role,
                x=leaf_x,
                y=leaf_y,
                width=leaf_width,
                height=leaf_height,
                style=build_container_style(is_leaf=True),
            )
            node_cursor_y = container_header + container_padding
            for node in leaf_nodes_sorted:
                add_node(
                    node=node,
                    x=container_padding,
                    y=node_cursor_y,
                    parent_id=leaf_container_id,
                )
                node_cursor_y += get_node_footprint_height(node) + node_gap_y

            current_band_x = leaf_x + leaf_width + container_gap
            for band in right_role_bands:
                sorted_band = sorted(
                    band,
                    key=lambda item: (
                        compute_role_anchor(item[0], item[1]) if compute_role_anchor(item[0], item[1]) is not None else float(len(leaf_nodes_sorted) + 1000),
                        role_priority_map.get(item[0], 9999),
                        item[0],
                    ),
                )
                row_right_x: Dict[int, int] = {}
                row_y_map: Dict[int, int] = {}
                band_width = 0
                next_free_y = right_base_y
                for role, nodes in sorted_band:
                    columns, container_width, container_height = compute_container_dimensions(role, nodes)
                    anchor = compute_role_anchor(role, nodes)
                    if anchor is None:
                        row_key = len(row_y_map) + 1000
                    else:
                        row_key = int(round(anchor))

                    if row_key not in row_y_map:
                        anchor_y = leaf_y + container_header + container_padding + row_key * (node_height + node_gap_y)
                        row_y_map[row_key] = max(next_free_y, anchor_y - container_header - container_padding)
                        next_free_y = row_y_map[row_key] + container_height + container_gap

                    container_x = row_right_x.get(row_key, current_band_x)
                    container_y = row_y_map[row_key]
                    container_id = alloc_id()
                    add_container(
                        container_id=container_id,
                        label=role,
                        x=container_x,
                        y=container_y,
                        width=container_width,
                        height=container_height,
                        style=build_container_style(),
                    )
                    node_cursor_y = container_header + container_padding
                    for node in nodes:
                        add_node(
                            node=node,
                            x=container_padding,
                            y=node_cursor_y,
                            parent_id=container_id,
                        )
                        node_cursor_y += get_node_footprint_height(node) + node_gap_y
                    row_right_x[row_key] = container_x + container_width + container_gap
                    band_width = max(band_width, row_right_x[row_key] - current_band_x)
                current_band_x += band_width + container_gap
        elif primary_leaf_role:
            top_roles = []
            bottom_roles = []
            for role, nodes in role_items:
                if role == primary_leaf_role:
                    continue
                if role_priority_map.get(role, 9999) <= leaf_priority:
                    top_roles.append((role, nodes))
                else:
                    bottom_roles.append((role, nodes))

            top_role_bands = group_roles_by_priority(top_roles)
            bottom_role_bands = group_roles_by_priority(bottom_roles)

            def estimate_band_width(band: List[tuple[str, List[str]]]) -> int:
                if not band:
                    return 0
                widths = [compute_container_dimensions(role, role_to_nodes[role])[0 if False else 1] for role, _nodes in band]
                return sum(widths) + max(len(widths) - 1, 0) * container_gap

            top_band_widths = [estimate_band_width(band) for band in top_role_bands]
            bottom_band_widths = [estimate_band_width(band) for band in bottom_role_bands]

            top_band_heights = [
                max(compute_container_dimensions(role, role_to_nodes[role])[2] for role, _nodes in band)
                for band in top_role_bands
            ]
            top_total_height = sum(top_band_heights)
            if top_role_bands:
                top_total_height += container_gap * len(top_role_bands)

            leaf_nodes_sorted = role_to_nodes[primary_leaf_role]
            leaf_columns, leaf_width, leaf_height = compute_container_dimensions(primary_leaf_role, leaf_nodes_sorted)
            overall_width = max([leaf_width] + top_band_widths + bottom_band_widths + [node_width])
            leaf_x = origin_x + max((overall_width - leaf_width) // 2, 0)
            leaf_y = origin_y + top_total_height

            current_band_y = origin_y
            for band, band_height, band_width in zip(top_role_bands, top_band_heights, top_band_widths):
                top_cursor_x = origin_x + max((overall_width - band_width) // 2, 0)
                for role, nodes in band:
                    columns, container_width, container_height = compute_container_dimensions(role, role_to_nodes[role])
                    container_id = alloc_id()
                    add_container(
                        container_id=container_id,
                        label=role,
                        x=top_cursor_x,
                        y=current_band_y,
                        width=container_width,
                        height=container_height,
                        style=build_container_style(),
                    )
                    node_cursor_x = container_padding
                    for node in role_to_nodes[role]:
                        add_node(
                            node=node,
                            x=node_cursor_x,
                            y=container_header + container_padding,
                            parent_id=container_id,
                        )
                        node_cursor_x += get_node_footprint_width(node) + node_gap_x
                    top_cursor_x += container_width + container_gap
                current_band_y += band_height + container_gap

            leaf_container_id = alloc_id()
            add_container(
                container_id=leaf_container_id,
                label=primary_leaf_role,
                x=leaf_x,
                y=leaf_y,
                width=leaf_width,
                height=leaf_height,
                style=build_container_style(is_leaf=True),
            )
            node_cursor_x = container_padding
            for node in leaf_nodes_sorted:
                add_node(
                    node=node,
                    x=node_cursor_x,
                    y=container_header + container_padding,
                    parent_id=leaf_container_id,
                )
                node_cursor_x += get_node_footprint_width(node) + node_gap_x

            def compute_bottom_x(role: str, nodes: List[str], container_width: int, band_origin_x: int) -> int:
                anchor = compute_role_anchor(role, nodes)
                if anchor is None:
                    return band_origin_x
                anchor_x = leaf_x + int(anchor * (node_width + node_gap_x))
                return max(band_origin_x, anchor_x - (container_width // 2))

            current_band_y = leaf_y + leaf_height + (container_gap if bottom_role_bands else 0)
            for band, band_width in zip(bottom_role_bands, bottom_band_widths):
                sorted_band = sorted(
                    band,
                    key=lambda item: (
                        compute_role_anchor(item[0], item[1]) if compute_role_anchor(item[0], item[1]) is not None else float(len(leaf_nodes_sorted) + 1000),
                        role_priority_map.get(item[0], 9999),
                        item[0],
                    ),
                )
                band_height = 0
                column_bottom_y: Dict[int, int] = {}
                column_x_map: Dict[int, int] = {}
                band_origin_x = origin_x + max((overall_width - band_width) // 2, 0)
                next_free_x = band_origin_x
                for role, nodes in sorted_band:
                    columns, container_width, container_height = compute_container_dimensions(role, role_to_nodes[role])
                    preferred_x = compute_bottom_x(role, nodes, container_width, band_origin_x)
                    anchor = compute_role_anchor(role, nodes)
                    if anchor is None:
                        column_key = len(column_x_map) + 1000
                    else:
                        column_key = int(round(anchor))

                    if column_key not in column_x_map:
                        column_x_map[column_key] = max(next_free_x, preferred_x)
                        next_free_x = column_x_map[column_key] + container_width + container_gap

                    container_x = column_x_map[column_key]
                    container_y = column_bottom_y.get(column_key, current_band_y)
                    container_id = alloc_id()
                    add_container(
                        container_id=container_id,
                        label=role,
                        x=container_x,
                        y=container_y,
                        width=container_width,
                        height=container_height,
                        style=build_container_style(),
                    )
                    node_cursor_x = container_padding
                    for node in role_to_nodes[role]:
                        add_node(
                            node=node,
                            x=node_cursor_x,
                            y=container_header + container_padding,
                            parent_id=container_id,
                        )
                        node_cursor_x += get_node_footprint_width(node) + node_gap_x
                    column_bottom_y[column_key] = container_y + container_height + container_gap
                    band_height = max(band_height, column_bottom_y[column_key] - current_band_y)
                current_band_y += band_height + container_gap
        else:
            cursor_x = origin_x
            cursor_y = origin_y
            for role, nodes in role_items:
                columns, container_width, container_height = compute_container_dimensions(role, role_to_nodes[role])
                container_id = alloc_id()
                add_container(
                    container_id=container_id,
                    label=role,
                    x=cursor_x,
                    y=cursor_y,
                    width=container_width,
                    height=container_height,
                    style=build_container_style(),
                )

                if horizontal:
                    node_cursor_y = container_header + container_padding
                    for node in role_to_nodes[role]:
                        add_node(
                            node=node,
                            x=container_padding,
                            y=node_cursor_y,
                            parent_id=container_id,
                        )
                        node_cursor_y += get_node_footprint_height(node) + node_gap_y
                else:
                    node_cursor_x = container_padding
                    for node in role_to_nodes[role]:
                        add_node(
                            node=node,
                            x=node_cursor_x,
                            y=container_header + container_padding,
                            parent_id=container_id,
                        )
                        node_cursor_x += get_node_footprint_width(node) + node_gap_x

                if horizontal:
                    cursor_x += container_width + container_gap
                else:
                    cursor_y += container_height + container_gap
    else:
        columns = 3 if horizontal else 2
        for index, node in enumerate(sorted_nodes):
            col = index % columns
            row = index // columns
            add_node(
                node=node,
                x=origin_x + col * (node_width + node_gap_x),
                y=origin_y + row * (node_height + node_gap_y),
            )

    def build_drawio_edge_label(
        left_node: str,
        left_if: str,
        right_node: str,
        right_if: str,
        evidence: str = "",
    ) -> str:
        if node_interface_label_map:
            return ""
        label_parts: List[str] = []
        if (left_node, left_if) not in nic_id_map:
            label_parts.append(left_if)
        if (right_node, right_if) not in nic_id_map:
            label_parts.append(right_if)
        label = " ↔ ".join([part for part in label_parts if part])
        if evidence:
            label = f"{label}<br>{evidence}" if label else evidence
        return label

    def build_horizontal_edge_anchor_style(source_side: str, target_side: str) -> str:
        if not horizontal:
            return ""

        exit_x = "0.5"
        entry_x = "0.5"
        if source_side == "left":
            exit_x = "0"
        elif source_side == "right":
            exit_x = "1"

        if target_side == "left":
            entry_x = "0"
        elif target_side == "right":
            entry_x = "1"

        return (
            f"exitX={exit_x};exitY=0.5;exitDx=0;exitDy=0;"
            f"entryX={entry_x};entryY=0.5;entryDx=0;entryDy=0;"
        )

    def add_edge(
        source_id: str,
        target_id: str,
        label: str,
        dashed: bool = False,
        source_side: str = "",
        target_side: str = "",
    ) -> None:
        edge_id = alloc_id()
        style = DRAWIO_STYLE_EDGE
        if dashed:
            style += DRAWIO_STYLE_EDGE_DASHED_SUFFIX
        style += build_horizontal_edge_anchor_style(source_side, target_side)
        cell_specs.append(
            {
                "kind": "edge",
                "id": edge_id,
                "value": "<br>".join(label.split("\n")),
                "style": style,
                "parent": "1",
                "source": source_id,
                "target": target_id,
            }
        )

    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        left_node, left_if = ep1.split(":", 1)
        right_node, right_if = ep2.split(":", 1)
        source_id = nic_id_map.get((left_node, left_if), node_id_map[left_node])
        target_id = nic_id_map.get((right_node, right_if), node_id_map[right_node])
        source_side = node_interface_side_map.get((left_node, left_if), "")
        target_side = node_interface_side_map.get((right_node, right_if), "")
        link_key = f"{left_node}|{left_if}|{right_node}|{right_if}"
        edge_label = ""
        if not node_interface_label_map:
            edge_label = (link_label_map or {}).get(link_key, "")
        if not edge_label:
            edge_label = build_drawio_edge_label(left_node, left_if, right_node, right_if)
        add_edge(
            source_id,
            target_id,
            edge_label,
            dashed=False,
            source_side=source_side,
            target_side=target_side,
        )

    if candidate_links:
        for link in candidate_links:
            ep1, ep2 = link["endpoints"]
            left_node, left_if = ep1.split(":", 1)
            right_node, right_if = ep2.split(":", 1)
            source_id = nic_id_map.get((left_node, left_if), node_id_map[left_node])
            target_id = nic_id_map.get((right_node, right_if), node_id_map[right_node])
            source_side = node_interface_side_map.get((left_node, left_if), "")
            target_side = node_interface_side_map.get((right_node, right_if), "")
            label = build_drawio_edge_label(left_node, left_if, right_node, right_if)
            add_edge(
                source_id,
                target_id,
                label,
                dashed=True,
                source_side=source_side,
                target_side=target_side,
            )

    def center_vertices_vertically() -> None:
        if not horizontal:
            return

        vertex_specs = [spec for spec in cell_specs if spec.get("kind") == "vertex"]
        if not vertex_specs:
            return

        vertex_by_id = {str(spec["id"]): spec for spec in vertex_specs}
        absolute_cache: Dict[str, tuple[int, int]] = {}

        def get_absolute_position(spec: Dict[str, Any]) -> tuple[int, int]:
            spec_id = str(spec["id"])
            if spec_id in absolute_cache:
                return absolute_cache[spec_id]

            local_x = int(spec["x"])
            local_y = int(spec["y"])
            parent_id = str(spec.get("parent", "1"))
            parent_spec = vertex_by_id.get(parent_id)
            if parent_spec is None:
                absolute_cache[spec_id] = (local_x, local_y)
                return absolute_cache[spec_id]

            parent_x, parent_y = get_absolute_position(parent_spec)
            absolute_cache[spec_id] = (parent_x + local_x, parent_y + local_y)
            return absolute_cache[spec_id]

        top_level_vertices = []
        min_y = None
        max_y = None
        for spec in vertex_specs:
            abs_x, abs_y = get_absolute_position(spec)
            del abs_x
            spec_max_y = abs_y + int(spec["height"])
            min_y = abs_y if min_y is None else min(min_y, abs_y)
            max_y = spec_max_y if max_y is None else max(max_y, spec_max_y)
            if str(spec.get("parent")) == "1":
                top_level_vertices.append(spec)

        if min_y is None or max_y is None or not top_level_vertices:
            return

        content_height = max_y - min_y
        page_height = int(DRAWIO_MODEL_ATTRIBUTES.get("pageHeight", "1080"))
        target_min_y = max((page_height - content_height) // 2, 0)
        offset_y = target_min_y - min_y
        if offset_y == 0:
            return
        for spec in top_level_vertices:
            spec["y"] = int(spec["y"]) + offset_y

    center_vertices_vertically()

    mxfile = ET.Element(
        "mxfile",
        {
            "host": DRAWIO_HOST,
            "modified": drawio_modified_timestamp(),
            "agent": "alred",
            "version": DRAWIO_VERSION,
        },
    )
    diagram = ET.SubElement(mxfile, "diagram", {"id": "topology", "name": title})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        DRAWIO_MODEL_ATTRIBUTES,
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    for spec in cell_specs:
        if spec["kind"] == "vertex":
            cell = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": str(spec["id"]),
                    "value": str(spec["value"]),
                    "style": str(spec["style"]),
                    "vertex": "1",
                    "parent": str(spec["parent"]),
                },
            )
            ET.SubElement(
                cell,
                "mxGeometry",
                {
                    "x": str(spec["x"]),
                    "y": str(spec["y"]),
                    "width": str(spec["width"]),
                    "height": str(spec["height"]),
                    "as": "geometry",
                },
            )
            continue

        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": str(spec["id"]),
                "value": str(spec["value"]),
                "style": str(spec["style"]),
                "edge": "1",
                "parent": str(spec["parent"]),
                "source": str(spec["source"]),
                "target": str(spec["target"]),
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    xml_text = ET.tostring(mxfile, encoding="unicode", short_empty_elements=True)
    return xml_text.splitlines()
