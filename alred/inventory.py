"""
Inventory and hosts-related helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from .constants import DEVICE_MAP


def parse_hosts_comment(comment: str) -> Dict[str, Any]:
    """
    Parse hosts.txt comment metadata.

    Example:
        linux, profile=bond, vlan=2001, ipv4=100.64.0.1/24
    """
    parts = [part.strip() for part in comment.split(",") if part.strip()]
    if not parts:
        return {"device_type": "unknown", "metadata": {}}

    device_type = parts[0]
    metadata: Dict[str, str] = {}
    flags: List[str] = []
    colon_keys = {"profile", "vlan", "ipv4", "ipv4_gw", "ipv6", "ipv6_gw", "default_route", "bind", "exec"}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
        elif ":" in part and part.split(":", 1)[0].strip().lower().replace("-", "_") in colon_keys:
            key, value = part.split(":", 1)
        else:
            flags.append(part)
            continue
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key:
            metadata[key] = value

    if "bond" in {flag.lower() for flag in flags} and "profile" not in metadata:
        metadata["profile"] = "bond"
    if flags:
        metadata["flags"] = ",".join(flags)

    return {"device_type": device_type.strip(), "metadata": metadata}


def parse_hosts_txt(path: str) -> List[Dict[str, Any]]:
    """
    Parse hosts.txt into structured entries.

    Expected format:
        192.168.129.81 lfsw0101 # nxos

    Args:
        path: Input hosts.txt path.

    Returns:
        List of entries with hostname, ip, device_type.

    Raises:
        ValueError: If format is invalid or IP/hostname is duplicated.
    """
    entries: List[Dict[str, str]] = []
    seen_ips = set()
    seen_hosts = set()

    for lineno, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        device_type = "unknown"
        metadata: Dict[str, str] = {}
        data_part = line
        if "#" in line:
            data_part, comment = line.split("#", 1)
            parsed_comment = parse_hosts_comment(comment.strip())
            device_type = str(parsed_comment["device_type"])
            metadata = parsed_comment["metadata"]

        parts = data_part.split()
        if len(parts) < 2:
            raise ValueError(f"{path}:{lineno}: invalid format: {raw_line}")

        ip, hostname = parts[0], parts[1]

        if ip in seen_ips:
            raise ValueError(f"{path}:{lineno}: duplicate IP detected: {ip}")
        if hostname in seen_hosts:
            raise ValueError(f"{path}:{lineno}: duplicate hostname detected: {hostname}")

        seen_ips.add(ip)
        seen_hosts.add(hostname)
        entry: Dict[str, Any] = {
            "hostname": hostname,
            "ip": ip,
            "device_type": device_type,
        }
        if metadata:
            entry["metadata"] = metadata
        entries.append(entry)

    return entries


def build_inventory(entries: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Build Ansible-style inventory data from parsed entries.

    Args:
        entries: Parsed hosts entries.

    Returns:
        Inventory dictionary.
    """
    inventory: Dict[str, Any] = {"all": {"hosts": {}}}

    for entry in entries:
        host_vars: Dict[str, Any] = {
            "ansible_host": entry["ip"],
            "device_type": entry["device_type"],
            "os_type": entry["device_type"],
        }
        if entry.get("metadata"):
            host_vars["metadata"] = entry["metadata"]
        host_vars.update(DEVICE_MAP.get(entry["device_type"], {}))
        inventory["all"]["hosts"][entry["hostname"]] = host_vars

    return inventory


def load_inventory_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert raw inventory YAML data into normalized host list.

    Args:
        data: Inventory YAML dictionary.

    Returns:
        List of normalized host dictionaries.
    """
    result: List[Dict[str, Any]] = []

    for hostname, attrs in data.get("all", {}).get("hosts", {}).items():
        result.append({
            "hostname": hostname,
            "ip": attrs.get("ansible_host"),
            "device_type": attrs.get("device_type", "unknown"),
            "os_type": attrs.get("os_type", attrs.get("device_type", "unknown")),
            "ansible_connection": attrs.get("ansible_connection"),
            "netmiko_device_type": attrs.get("netmiko_device_type"),
            "ansible_network_os": attrs.get("ansible_network_os"),
            "metadata": attrs.get("metadata", {}),
        })

    return result


def load_inventory_map_from_list(hosts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Convert inventory host list to hostname-keyed dict.

    Args:
        hosts: Host list.

    Returns:
        Hostname-keyed dictionary.
    """
    return {h["hostname"]: h for h in hosts}


def build_terraform_provider_lines(
    inventory_map: Dict[str, Dict[str, Any]],
    roles: Dict[str, Any],
    detect_node_role_func: Callable[[str, Dict[str, Any]], str],
    provider_version: str | None = None,
) -> List[str]:
    """
    Build Terraform main.tf lines from inventory.

    Only nxos devices are included in provider "nxos" devices list.

    Args:
        inventory_map: Host inventory map.
        roles: Role detection rules.
        detect_node_role_func: Injected role detection function.
        provider_version: Optional Terraform provider version constraint.

    Returns:
        Terraform main.tf lines.
    """
    groups: Dict[str, List[Dict[str, str]]] = {}

    for hostname in sorted(inventory_map.keys()):
        host = inventory_map[hostname]
        device_type = str(host.get("device_type", "unknown"))
        ip = str(host.get("ip", "")).strip()

        if device_type != "nxos" or not ip:
            continue

        role = detect_node_role_func(hostname, roles)
        group_name = f"{role.replace('-', '_')}s"
        groups.setdefault(group_name, []).append({
            "name": hostname,
            "url": f"https://{ip}",
        })

    lines: List[str] = []
    if provider_version:
        lines.extend([
            "terraform {",
            "  required_providers {",
            "    nxos = {",
            '      source  = "CiscoDevNet/nxos"',
            f'      version = "{provider_version}"',
            "    }",
            "  }",
            "}",
            "",
        ])

    lines.append("locals {")

    for group_name in sorted(groups.keys()):
        lines.append(f"  {group_name} = [")
        for item in groups[group_name]:
            lines.append("    {")
            lines.append(f'      name = "{item["name"]}"')
            lines.append(f'      url  = "{item["url"]}"')
            lines.append("    },")
        lines.append("  ]")

    lines.append("}")
    lines.append("")
    lines.append('provider "nxos" {')
    lines.append('  username = "admin"')
    lines.append('  password = "admin"')

    local_refs = [f"local.{group_name}" for group_name in sorted(groups.keys())]
    if local_refs:
        lines.append(f"  devices  = concat({', '.join(local_refs)})")
    else:
        lines.append("  devices  = []")

    lines.append("}")

    return lines
