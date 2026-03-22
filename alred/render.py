"""
Rendering helpers for containerlab YAML, Mermaid, and Terraform.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


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
