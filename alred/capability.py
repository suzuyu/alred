"""Exact NX-OS model/release/role capability registry evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .overlay_render import normalize_nxos_model
from .resources import get_resource_dir
from .schema import source_sha256, validate_document


class CapabilityError(ValueError):
    """Raised when a capability registry cannot be evaluated safely."""


def default_registry_path() -> Path:
    return get_resource_dir("capabilities") / "nxos.yaml"


def load_capability_registry(path: str | Path | None = None) -> dict[str, Any]:
    candidate = Path(path) if path else default_registry_path()
    if not candidate.is_file() or candidate.is_symlink():
        raise CapabilityError(f"capability registry not found: {candidate}")
    document = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != (
        "NxosCapabilityRegistry"
    ):
        raise CapabilityError("invalid NX-OS capability registry envelope")
    validate_document(document, kind="NxosCapabilityRegistry")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise CapabilityError("capability registry entries must be a list")
    document["_path"] = str(candidate.resolve())
    document["_sha256"] = source_sha256(candidate)
    return document


def required_overlay_capabilities(change_set: Mapping[str, Any]) -> set[str]:
    required = {
        "baseline_commands",
        "reload_pending",
        "global_ir_bgp",
        "evpn_vni",
        "rollback_diff",
    }
    spec = change_set.get("spec", {})
    if spec.get("l3vnis"):
        required.update({"new_l3vni", "bgp_vrf_af"})
    for item in spec.get("l2vnis", []):
        svi = item.get("svi")
        if not isinstance(svi, Mapping):
            continue
        required.add("svi_mtu")
        if svi.get("ipv6_addresses"):
            required.add("ipv6_link_local")
    return required


def _snapshot_role(host: Mapping[str, Any]) -> str:
    common = host.get("common", {})
    vpc = common.get("vpc", {})
    config = host.get("profiles", {}).get("nxos-overlay", {}).get("config", {})
    nve = config.get("nve", {})
    if nve.get("configured") and vpc.get("applicable"):
        return "vpc_vtep_leaf"
    if nve.get("configured"):
        return "vtep_leaf"
    return "other"


def evaluate_capability(
    registry: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    target_hosts: Sequence[str],
    required: set[str],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    entries = registry.get("entries", [])
    for hostname in target_hosts:
        host = snapshot.get("hosts", {}).get(hostname, {})
        system = host.get("common", {}).get("system", {})
        model = normalize_nxos_model(str(system.get("model", "")))
        release = str(system.get("version", ""))
        role = _snapshot_role(host)
        match = next(
            (
                entry
                for entry in entries
                if entry.get("model") == model
                and entry.get("release") == release
                and entry.get("role") == role
            ),
            None,
        )
        available = set(match.get("capabilities", [])) if match else set()
        missing = sorted(required - available)
        verified = (
            match is not None
            and match.get("level") == "APPLY_VERIFIED"
            and not missing
        )
        results[hostname] = {
            "model": model,
            "release": release,
            "role": role,
            "level": "APPLY_VERIFIED" if verified else "PLAN_ONLY",
            "required_capabilities": sorted(required),
            "missing_capabilities": missing,
            "evidence": match.get("evidence") if match else None,
        }
    verified_all = bool(results) and all(
        item["level"] == "APPLY_VERIFIED" for item in results.values()
    )
    return {
        "level": "APPLY_VERIFIED" if verified_all else "PLAN_ONLY",
        "registry_path": registry["_path"],
        "registry_sha256": registry["_sha256"],
        "devices": results,
    }
