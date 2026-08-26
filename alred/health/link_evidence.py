"""Canonical LLDP/description evidence shared by Health input adapters."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..constants import NETWORK_DEVICE_TYPES
from ..link_diagnostics import build_link_diagnostics
from ..parsing import (
    build_description_records,
    merge_lldp_and_description_links,
    normalize_hostname,
    normalize_link_records,
    parse_lldp_file,
)
from ..schema import canonical_sha256, validate_document
from .parsers import NXOS_PARSER_VERSION, ParserError, parse_nxos_command
from .snapshot import read_manifest_command_output


LINK_EVIDENCE_BUILDER_VERSION = "1.1"


def _source_state(
    host_record: Mapping[str, Any],
    identifier: str,
) -> tuple[Mapping[str, Any] | None, dict[str, str]]:
    record = host_record.get("commands", {}).get(identifier)
    if record is None:
        return None, {"status": "missing", "message": "command is missing"}
    if record.get("status") != "success":
        status = str(record.get("status") or "failed")
        return None, {
            "status": status,
            "message": str(record.get("error") or f"collection status is {status}"),
        }
    return record, {"status": "success", "message": "command was selected"}


def _validated_output(
    host_record: Mapping[str, Any],
    identifier: str,
    *,
    device_type: str,
) -> tuple[str | None, dict[str, str]]:
    record, state = _source_state(host_record, identifier)
    if record is None:
        return None, state
    output = read_manifest_command_output(record)
    try:
        parse_nxos_command(
            identifier,
            output,
            device_type=device_type,
        )
    except (KeyError, ParserError) as exc:
        return None, {"status": "unknown", "message": str(exc)}
    return output, {"status": "parsed", "message": "command output was parsed"}


def build_health_link_evidence(
    manifest: Mapping[str, Any],
    *,
    inventory: Mapping[str, Mapping[str, Any]],
    mappings: Mapping[str, Any],
    description_rules: Sequence[Mapping[str, str]],
    normalizer_version: str,
    include_svi: bool = False,
    resolved_roles: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one adapter-independent canonical link evidence document."""
    validate_document(manifest, kind="CollectionManifest")
    mapping_data = dict(mappings)
    rules = [dict(item) for item in description_rules]
    inventory_map = {
        str(host): dict(attributes)
        for host, attributes in inventory.items()
    }
    if not inventory_map:
        inventory_map = {
            str(host): {
                "hostname": str(host),
                "device_type": str(record.get("platform") or "nxos"),
            }
            for host, record in manifest["spec"]["hosts"].items()
        }

    normalized_inventory: dict[str, dict[str, Any]] = {}
    for hostname, attributes in inventory_map.items():
        normalized = normalize_hostname(hostname, mapping_data)
        existing = normalized_inventory.get(normalized)
        if existing is not None and existing != attributes:
            raise ValueError(
                f"multiple inventory hosts normalize to the same name: {normalized}"
            )
        normalized_inventory[normalized] = attributes

    resolved_devices = (
        resolved_roles.get("spec", {}).get("devices", {})
        if isinstance(resolved_roles, Mapping)
        else {}
    )
    eligible_hosts: list[str] = []
    excluded_hosts: dict[str, str] = {}
    for hostname, attributes in sorted(inventory_map.items()):
        normalized = normalize_hostname(hostname, mapping_data)
        device_type = str(attributes.get("device_type") or "unknown").lower()
        topology_role = str(
            resolved_devices.get(hostname, {}).get("topology_role") or ""
        )
        role_status = str(resolved_devices.get(hostname, {}).get("status") or "")
        if topology_role == "server":
            excluded_hosts[normalized] = "topology-role-server"
        elif topology_role == "wan-provider":
            excluded_hosts[normalized] = "topology-role-external"
        elif role_status == "conflict":
            excluded_hosts[normalized] = "topology-role-unresolved"
        elif device_type not in NETWORK_DEVICE_TYPES:
            excluded_hosts[normalized] = "platform-outside-network-devices"
        else:
            eligible_hosts.append(normalized)

    lldp_records: list[dict[str, str]] = []
    description_records: list[dict[str, str]] = []
    description_ambiguities: list[dict[str, Any]] = []
    lldp_hosts: set[str] = set()
    running_config_hosts: set[str] = set()
    host_map: dict[str, str] = {}
    source_status: dict[str, dict[str, dict[str, str]]] = {}

    for hostname, host_record in sorted(manifest["spec"]["hosts"].items()):
        normalized_host = normalize_hostname(hostname, mapping_data)
        host_map[hostname] = normalized_host
        device_type = str(
            inventory_map.get(hostname, {}).get("device_type")
            or host_record.get("platform")
            or "nxos"
        ).lower()
        lldp_output, lldp_state = _validated_output(
            host_record,
            "lldp_neighbors_detail",
            device_type=device_type,
        )
        running_output, running_state = _validated_output(
            host_record,
            "running_config",
            device_type=device_type,
        )
        source_status[hostname] = {
            "lldp_neighbors_detail": lldp_state,
            "running_config": running_state,
        }
        if lldp_output is not None:
            lldp_hosts.add(normalized_host)
            lldp_records.extend(
                parse_lldp_file(
                    lldp_output,
                    hostname,
                    device_type,
                    mapping_data,
                )
            )
        if running_output is not None:
            running_config_hosts.add(normalized_host)
            description_records.extend(
                build_description_records(
                    hostname,
                    running_output,
                    mapping_data,
                    rules,
                    include_svi=include_svi,
                    ambiguity_records=description_ambiguities,
                )
            )

    lldp_records = normalize_link_records(
        lldp_records,
        mapping_data,
        inventory_map,
    )
    description_records = normalize_link_records(
        description_records,
        mapping_data,
        inventory_map,
    )
    confirmed_links, candidate_links = merge_lldp_and_description_links(
        lldp_records,
        description_records,
    )
    policy_hashes = {
        "mappings": canonical_sha256(mapping_data),
        "description_rules": canonical_sha256(rules),
    }
    diagnostics = build_link_diagnostics(
        lldp_records=lldp_records,
        description_records=description_records,
        confirmed_links=confirmed_links,
        candidate_links=candidate_links,
        inventory_hosts=normalized_inventory,
        running_config_hosts=running_config_hosts,
        lldp_hosts=lldp_hosts,
        normalizer_version=normalizer_version,
        source=f"health:{manifest['metadata']['collection_id']}",
        parser_versions={
            "lldp": NXOS_PARSER_VERSION,
            "description": NXOS_PARSER_VERSION,
        },
        policy_hashes=policy_hashes,
        description_ambiguities=description_ambiguities,
    )
    return {
        "normalizer_version": normalizer_version,
        "builder_version": LINK_EVIDENCE_BUILDER_VERSION,
        "policy_hashes": policy_hashes,
        "host_map": host_map,
        "source_status": source_status,
        "health_scope": {
            "eligible_hosts": sorted(set(eligible_hosts)),
            "excluded_hosts": excluded_hosts,
        },
        "confirmed_links": confirmed_links,
        "candidate_links": candidate_links,
        "diagnostics": diagnostics,
    }
