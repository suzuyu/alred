"""Canonical LLDP/description diagnostics and human-readable reporting."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from .schema import API_VERSION, validate_document


Endpoint = tuple[str, str]
DescriptionClaim = tuple[Endpoint, Endpoint]


def _endpoint(record: Mapping[str, Any], prefix: str) -> Endpoint:
    return (
        str(record.get(f"{prefix}_node", "")).strip(),
        str(record.get(f"{prefix}_if", "")).strip(),
    )


def _endpoint_document(endpoint: Endpoint | None) -> dict[str, str] | None:
    if endpoint is None or not endpoint[0]:
        return None
    return {"node": endpoint[0], "interface": endpoint[1]}


def _endpoint_text(endpoint: Endpoint | None) -> str:
    if endpoint is None:
        return "-"
    return f"{endpoint[0]}:{endpoint[1]}" if endpoint[1] else endpoint[0]


def _description_claim_document(claim: DescriptionClaim) -> dict[str, Any]:
    return {
        "local_endpoint": _endpoint_document(claim[0]),
        "configured_endpoint": _endpoint_document(claim[1]),
    }


def _description_claim_text(claim: DescriptionClaim) -> str:
    return f"{_endpoint_text(claim[0])} -> {_endpoint_text(claim[1])}"


def _canonical_endpoints(first: Endpoint, second: Endpoint) -> tuple[Endpoint, Endpoint]:
    return tuple(sorted((first, second)))  # type: ignore[return-value]


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _record_key(record: Mapping[str, Any]) -> tuple[Endpoint, Endpoint]:
    return _endpoint(record, "src"), _endpoint(record, "dst")


def _link_state(
    endpoints: tuple[Endpoint, Endpoint],
    confirmed_keys: set[tuple[Endpoint, Endpoint]],
    candidate_keys: set[tuple[Endpoint, Endpoint]],
    *,
    default: str,
) -> str:
    canonical = _canonical_endpoints(*endpoints)
    if canonical in confirmed_keys:
        return "confirmed"
    if canonical in candidate_keys:
        return "candidate"
    return default


def _diagnostic(
    *,
    code: str,
    classification: str,
    link_state: str,
    link_endpoints: tuple[Endpoint, Endpoint],
    local_endpoint: Endpoint,
    observed_endpoint: Endpoint | None,
    configured_endpoint: Endpoint | None,
    inventory_hosts: set[str],
    message: str,
    group_value: Any | None = None,
    candidate_endpoints: Sequence[Endpoint] = (),
    expected_reciprocal_claim: DescriptionClaim | None = None,
    actual_reciprocal_claims: Sequence[DescriptionClaim] = (),
) -> dict[str, Any]:
    canonical = _canonical_endpoints(*link_endpoints)
    identity = {
        "code": code,
        "link_endpoints": canonical,
        "local_endpoint": local_endpoint,
        "observed_endpoint": observed_endpoint,
        "configured_endpoint": configured_endpoint,
        "candidate_endpoints": sorted(candidate_endpoints),
    }
    involved = {
        endpoint[0]
        for endpoint in (
            local_endpoint,
            observed_endpoint,
            configured_endpoint,
            *candidate_endpoints,
        )
        if endpoint is not None and endpoint[0] in inventory_hosts
    }
    document = {
        "diagnostic_id": _stable_id("linkdiag", identity),
        "group_id": _stable_id(
            "linkgroup", group_value if group_value is not None else canonical
        ),
        "code": code,
        "classification": classification,
        "link_state": link_state,
        "link_endpoints": [
            _endpoint_document(canonical[0]),
            _endpoint_document(canonical[1]),
        ],
        "local_endpoint": _endpoint_document(local_endpoint),
        "observed_endpoint": _endpoint_document(observed_endpoint),
        "configured_endpoint": _endpoint_document(configured_endpoint),
        "affected_devices": sorted(involved),
        "message": message,
    }
    if candidate_endpoints:
        document["candidate_endpoints"] = [
            _endpoint_document(endpoint) for endpoint in candidate_endpoints
        ]
    if expected_reciprocal_claim is not None:
        document["expected_reciprocal_claim"] = _description_claim_document(
            expected_reciprocal_claim
        )
        document["actual_reciprocal_claims"] = [
            _description_claim_document(claim)
            for claim in sorted(actual_reciprocal_claims)
        ]
    return document


def _unevaluated_claim(
    *,
    source: str,
    local_endpoint: Endpoint,
    claimed_endpoint: Endpoint,
    inventory_hosts: set[str],
    reason: str,
) -> dict[str, Any]:
    identity = {
        "source": source,
        "local_endpoint": local_endpoint,
        "claimed_endpoint": claimed_endpoint,
        "reason": reason,
    }
    reason_text = {
        "peer-not-in-inventory": "the peer is outside the inventory",
        "peer-evidence-not-collected": "peer source evidence was not collected",
        "peer-link-evidence-not-found": (
            "the peer source was collected but no peer link records were parsed"
        ),
    }[reason]
    return {
        "claim_id": _stable_id("linkclaim", identity),
        "source": source,
        "reason": reason,
        "link_endpoints": [
            _endpoint_document(endpoint)
            for endpoint in _canonical_endpoints(local_endpoint, claimed_endpoint)
        ],
        "local_endpoint": _endpoint_document(local_endpoint),
        "claimed_endpoint": _endpoint_document(claimed_endpoint),
        "affected_devices": sorted(
            {
                endpoint[0]
                for endpoint in (local_endpoint, claimed_endpoint)
                if endpoint[0] in inventory_hosts
            }
        ),
        "message": (
            f"{source} claim {_endpoint_text(local_endpoint)} -> "
            f"{_endpoint_text(claimed_endpoint)} was not compared because "
            f"{reason_text}"
        ),
    }


def _has_reciprocal_description(
    local: Endpoint,
    configured: Endpoint,
    descriptions_by_local: Mapping[Endpoint, Sequence[Endpoint]],
) -> bool:
    if configured[1]:
        return local in descriptions_by_local.get(configured, ())
    return any(
        remote[0] == local[0]
        and (not remote[1] or remote[1] == local[1])
        for remote_local, remotes in descriptions_by_local.items()
        if remote_local[0] == configured[0]
        for remote in remotes
    )


def _reciprocal_description_claims(
    configured: Endpoint,
    descriptions_by_local: Mapping[Endpoint, Sequence[Endpoint]],
) -> list[DescriptionClaim]:
    """Return peer-side claims comparable with an expected reverse claim."""
    if configured[1]:
        local_endpoints = (configured,)
    else:
        local_endpoints = tuple(
            local
            for local in descriptions_by_local
            if local[0] == configured[0]
        )
    return sorted(
        {
            (peer_local, remote)
            for peer_local in local_endpoints
            for remote in descriptions_by_local.get(peer_local, ())
        }
    )


def empty_link_diagnostics(
    normalizer_version: str,
    *,
    source: str = "",
) -> dict[str, Any]:
    """Return a schema-valid model for a source without link evidence."""
    document = {
        "api_version": API_VERSION,
        "kind": "LinkDiagnostics",
        "metadata": {
            "normalizer_version": normalizer_version,
            "parser_versions": {
                "lldp": normalizer_version,
                "description": normalizer_version,
            },
            **({"source": source} if source else {}),
        },
        "spec": {
            "evaluation_status": "not-evaluated",
            "result": "unknown",
            "coverage": {
                "inventory_hosts": [],
                "running_config_hosts": [],
                "lldp_hosts": [],
                "confirmed_link_count": 0,
                "candidate_link_count": 0,
            },
            "diagnostics": [],
            "unevaluated_claims": [],
            "affected_devices": [],
            "unresolved_peer_references": [],
        },
    }
    validate_document(document, kind="LinkDiagnostics")
    return document


def build_link_diagnostics(
    *,
    lldp_records: Sequence[Mapping[str, Any]],
    description_records: Sequence[Mapping[str, Any]],
    confirmed_links: Sequence[Mapping[str, Any]],
    candidate_links: Sequence[Mapping[str, Any]],
    inventory_hosts: Iterable[str],
    running_config_hosts: Iterable[str],
    lldp_hosts: Iterable[str],
    normalizer_version: str,
    source: str = "",
    parser_versions: Mapping[str, str] | None = None,
    policy_hashes: Mapping[str, str] | None = None,
    description_ambiguities: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build deterministic diagnostics without changing canonical link rows."""
    inventory = {str(item) for item in inventory_hosts if str(item)}
    config_coverage = {str(item) for item in running_config_hosts if str(item)}
    lldp_coverage = {str(item) for item in lldp_hosts if str(item)}
    confirmed_keys = {
        _canonical_endpoints(*_record_key(record)) for record in confirmed_links
    }
    candidate_keys = {
        _canonical_endpoints(*_record_key(record)) for record in candidate_links
    }
    lldp_by_local: dict[Endpoint, list[Endpoint]] = {}
    desc_by_local: dict[Endpoint, list[Endpoint]] = {}
    for record in lldp_records:
        local, remote = _record_key(record)
        if local[0] and remote[0] and remote not in lldp_by_local.setdefault(local, []):
            lldp_by_local[local].append(remote)
    for record in description_records:
        local, remote = _record_key(record)
        if local[0] and remote[0] and remote not in desc_by_local.setdefault(local, []):
            desc_by_local[local].append(remote)
    for values in lldp_by_local.values():
        values.sort()
    for values in desc_by_local.values():
        values.sort()
    lldp_evidence_hosts = {endpoint[0] for endpoint in lldp_by_local}
    description_evidence_hosts = {endpoint[0] for endpoint in desc_by_local}

    diagnostics: list[dict[str, Any]] = []
    unevaluated_claims: list[dict[str, Any]] = []

    for ambiguity in description_ambiguities:
        local = (
            str(ambiguity.get("local_node", "")),
            str(ambiguity.get("local_if", "")),
        )
        candidates = sorted(
            {
                (
                    str(item.get("node", "")),
                    str(item.get("interface", "")),
                )
                for item in ambiguity.get("candidate_endpoints", [])
                if isinstance(item, Mapping) and str(item.get("node", ""))
            }
        )
        if not local[0] or len(candidates) < 2:
            continue
        diagnostics.append(
            _diagnostic(
                code="DESCRIPTION_AMBIGUOUS",
                classification="unknown",
                link_state="unresolved",
                link_endpoints=(local, candidates[0]),
                local_endpoint=local,
                observed_endpoint=None,
                configured_endpoint=None,
                candidate_endpoints=candidates,
                inventory_hosts=inventory,
                message=(
                    f"{_endpoint_text(local)} description matches multiple endpoints: "
                    + ", ".join(_endpoint_text(value) for value in candidates)
                ),
                group_value=local,
            )
        )

    for local, observed_values in sorted(lldp_by_local.items()):
        if len(observed_values) > 1:
            first = observed_values[0]
            diagnostics.append(
                _diagnostic(
                    code="MULTIPLE_REMOTE_ENDPOINTS",
                    classification="conflict",
                    link_state="candidate",
                    link_endpoints=(local, first),
                    local_endpoint=local,
                    observed_endpoint=first,
                    configured_endpoint=None,
                    candidate_endpoints=observed_values,
                    inventory_hosts=inventory,
                    message=(
                        f"{_endpoint_text(local)} has multiple LLDP peers: "
                        + ", ".join(_endpoint_text(value) for value in observed_values)
                    ),
                )
            )
        for observed in observed_values:
            endpoints = (local, observed)
            state = _link_state(
                endpoints, confirmed_keys, candidate_keys, default="candidate"
            )
            for configured in desc_by_local.get(local, []):
                code = ""
                if observed[0] != configured[0]:
                    code = "LLDP_DESC_DEVICE_CONFLICT"
                elif configured[1] and observed[1] != configured[1]:
                    code = "LLDP_DESC_INTERFACE_CONFLICT"
                if code:
                    diagnostics.append(
                        _diagnostic(
                            code=code,
                            classification="conflict",
                            link_state=state,
                            link_endpoints=endpoints,
                            local_endpoint=local,
                            observed_endpoint=observed,
                            configured_endpoint=configured,
                            inventory_hosts=inventory,
                            message=(
                                f"{_endpoint_text(local)}: LLDP={_endpoint_text(observed)} "
                                f"description={_endpoint_text(configured)}"
                            ),
                        )
                    )
            reverse_exists = local in lldp_by_local.get(observed, [])
            if not reverse_exists:
                if observed[0] not in inventory:
                    unevaluated_claims.append(
                        _unevaluated_claim(
                            source="lldp",
                            local_endpoint=local,
                            claimed_endpoint=observed,
                            inventory_hosts=inventory,
                            reason="peer-not-in-inventory",
                        )
                    )
                elif observed[0] not in lldp_coverage:
                    unevaluated_claims.append(
                        _unevaluated_claim(
                            source="lldp",
                            local_endpoint=local,
                            claimed_endpoint=observed,
                            inventory_hosts=inventory,
                            reason="peer-evidence-not-collected",
                        )
                    )
                elif observed[0] not in lldp_evidence_hosts:
                    unevaluated_claims.append(
                        _unevaluated_claim(
                            source="lldp",
                            local_endpoint=local,
                            claimed_endpoint=observed,
                            inventory_hosts=inventory,
                            reason="peer-link-evidence-not-found",
                        )
                    )
                elif local[0] in lldp_coverage:
                    diagnostics.append(
                        _diagnostic(
                            code="ONE_WAY_LLDP",
                            classification="warning",
                            link_state=state,
                            link_endpoints=endpoints,
                            local_endpoint=local,
                            observed_endpoint=observed,
                            configured_endpoint=None,
                            inventory_hosts=inventory,
                            message=(
                                f"LLDP is only observed from {_endpoint_text(local)} "
                                f"to {_endpoint_text(observed)} although both endpoint "
                                "LLDP outputs were collected"
                            ),
                        )
                    )

    for local, configured_values in sorted(desc_by_local.items()):
        if len(configured_values) > 1:
            first = configured_values[0]
            diagnostics.append(
                _diagnostic(
                    code="MULTIPLE_REMOTE_ENDPOINTS",
                    classification="conflict",
                    link_state="claim",
                    link_endpoints=(local, first),
                    local_endpoint=local,
                    observed_endpoint=None,
                    configured_endpoint=first,
                    candidate_endpoints=configured_values,
                    inventory_hosts=inventory,
                    message=(
                        f"{_endpoint_text(local)} has multiple description peers: "
                        + ", ".join(_endpoint_text(value) for value in configured_values)
                    ),
                )
            )
        for configured in configured_values:
            if _has_reciprocal_description(local, configured, desc_by_local):
                continue
            if local in lldp_by_local:
                continue
            endpoints = (local, configured)
            state = _link_state(
                endpoints, confirmed_keys, candidate_keys, default="claim"
            )
            if configured[0] not in inventory:
                unevaluated_claims.append(
                    _unevaluated_claim(
                        source="description",
                        local_endpoint=local,
                        claimed_endpoint=configured,
                        inventory_hosts=inventory,
                        reason="peer-not-in-inventory",
                    )
                )
            elif configured[0] not in config_coverage:
                unevaluated_claims.append(
                    _unevaluated_claim(
                        source="description",
                        local_endpoint=local,
                        claimed_endpoint=configured,
                        inventory_hosts=inventory,
                        reason="peer-evidence-not-collected",
                    )
                )
            elif configured[0] not in description_evidence_hosts:
                unevaluated_claims.append(
                    _unevaluated_claim(
                        source="description",
                        local_endpoint=local,
                        claimed_endpoint=configured,
                        inventory_hosts=inventory,
                        reason="peer-link-evidence-not-found",
                    )
                )
            elif local[0] in config_coverage:
                expected_reciprocal_claim = (configured, local)
                actual_reciprocal_claims = _reciprocal_description_claims(
                    configured, desc_by_local
                )
                diagnostics.append(
                    _diagnostic(
                        code="DESCRIPTION_NOT_RECIPROCAL",
                        classification="conflict",
                        link_state=state if state != "candidate" else "claim",
                        link_endpoints=endpoints,
                        local_endpoint=local,
                        observed_endpoint=None,
                        configured_endpoint=configured,
                        inventory_hosts=inventory,
                        message=(
                            f"Description claim {_endpoint_text(local)} -> "
                            f"{_endpoint_text(configured)} does not match expected "
                            f"reverse claim {_description_claim_text(expected_reciprocal_claim)} "
                            "although both endpoint running configs were collected"
                        ),
                        group_value=tuple(sorted((local[0], configured[0]))),
                        expected_reciprocal_claim=expected_reciprocal_claim,
                        actual_reciprocal_claims=actual_reciprocal_claims,
                    )
                )

    unresolved: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        if diagnostic["code"] == "DESCRIPTION_AMBIGUOUS":
            for endpoint in diagnostic.get("candidate_endpoints", []):
                if endpoint["node"] in inventory:
                    continue
                unresolved.append(
                    {
                        "peer": endpoint["node"],
                        "local_endpoint": diagnostic["local_endpoint"],
                        "source": "description",
                        "diagnostic_id": diagnostic["diagnostic_id"],
                    }
                )
            continue
        if diagnostic["code"] != "REMOTE_DEVICE_UNRESOLVED":
            continue
        for source_name, field in (
            ("lldp", "observed_endpoint"),
            ("description", "configured_endpoint"),
        ):
            endpoint = diagnostic.get(field)
            if not endpoint or endpoint["node"] in inventory:
                continue
            unresolved.append(
                {
                    "peer": endpoint["node"],
                    "local_endpoint": diagnostic["local_endpoint"],
                    "source": source_name,
                    "diagnostic_id": diagnostic["diagnostic_id"],
                }
            )

    unique_diagnostics = {
        item["diagnostic_id"]: item for item in diagnostics
    }
    diagnostics = sorted(
        unique_diagnostics.values(),
        key=lambda item: (
            {"confirmed": 0, "candidate": 1, "claim": 2, "unresolved": 3}[
                item["link_state"]
            ],
            tuple(
                (endpoint["node"], endpoint["interface"])
                for endpoint in item["link_endpoints"]
            ),
            item["code"],
            item["diagnostic_id"],
        ),
    )
    unresolved = sorted(
        {json.dumps(item, sort_keys=True): item for item in unresolved}.values(),
        key=lambda item: (
            item["peer"],
            item["local_endpoint"]["node"],
            item["local_endpoint"]["interface"],
            item["source"],
        ),
    )
    unevaluated_claims = sorted(
        {
            item["claim_id"]: item for item in unevaluated_claims
        }.values(),
        key=lambda item: (
            item["source"],
            item["local_endpoint"]["node"],
            item["local_endpoint"]["interface"],
            item["claimed_endpoint"]["node"],
            item["claimed_endpoint"]["interface"],
        ),
    )
    affected = sorted(
        {
            device
            for diagnostic in diagnostics
            for device in diagnostic["affected_devices"]
        }
    )
    if not config_coverage and not lldp_coverage:
        evaluation_status = "not-evaluated"
    elif inventory.issubset(config_coverage) and inventory.issubset(lldp_coverage):
        evaluation_status = "complete"
    else:
        evaluation_status = "partial"
    if unevaluated_claims and evaluation_status == "complete":
        evaluation_status = "partial"
    if any(item["classification"] == "conflict" for item in diagnostics):
        result = "conflict"
    elif evaluation_status != "complete" or any(
        item["classification"] == "unknown" for item in diagnostics
    ):
        result = "unknown"
    elif any(item["classification"] == "warning" for item in diagnostics):
        result = "warning"
    else:
        result = "pass"
    document = {
        "api_version": API_VERSION,
        "kind": "LinkDiagnostics",
        "metadata": {
            "normalizer_version": normalizer_version,
            "parser_versions": dict(
                parser_versions
                or {
                    "lldp": normalizer_version,
                    "description": normalizer_version,
                }
            ),
            **({"policy_hashes": dict(policy_hashes)} if policy_hashes else {}),
            **({"source": source} if source else {}),
        },
        "spec": {
            "evaluation_status": evaluation_status,
            "result": result,
            "coverage": {
                "inventory_hosts": sorted(inventory),
                "running_config_hosts": sorted(config_coverage),
                "lldp_hosts": sorted(lldp_coverage),
                "confirmed_link_count": len(confirmed_links),
                "candidate_link_count": len(candidate_links),
            },
            "diagnostics": diagnostics,
            "unevaluated_claims": unevaluated_claims,
            "affected_devices": affected,
            "unresolved_peer_references": unresolved,
        },
    }
    validate_document(document, kind="LinkDiagnostics")
    return document


def _escape_markdown(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _recommended_check(code: str) -> str:
    return {
        "LLDP_DESC_DEVICE_CONFLICT": (
            "Compare LLDP detail and the local interface description, then verify cabling."
        ),
        "LLDP_DESC_INTERFACE_CONFLICT": (
            "Compare both endpoint interfaces in LLDP detail and interface descriptions."
        ),
        "DESCRIPTION_NOT_RECIPROCAL": (
            "Verify both interface descriptions and confirm the physical peer."
        ),
        "ONE_WAY_LLDP": (
            "Verify LLDP enablement, receive/transmit state, and neighbor output on both endpoints."
        ),
        "MULTIPLE_REMOTE_ENDPOINTS": (
            "Inspect the local interface evidence and resolve the peer before using the link."
        ),
        "DESCRIPTION_AMBIGUOUS": (
            "Refine description rules so the description resolves to exactly one endpoint."
        ),
        "REMOTE_DEVICE_UNRESOLVED": (
            "Add or correct the inventory or hostname mapping, then regenerate diagnostics."
        ),
    }.get(code, "Inspect the referenced evidence and regenerate diagnostics.")


def _document_endpoint(value: Mapping[str, Any] | None) -> Endpoint | None:
    if not value:
        return None
    node = str(value.get("node", ""))
    if not node:
        return None
    return node, str(value.get("interface", ""))


def _document_description_claim(value: Mapping[str, Any]) -> DescriptionClaim:
    local = _document_endpoint(value.get("local_endpoint"))
    configured = _document_endpoint(value.get("configured_endpoint"))
    if local is None or configured is None:
        raise ValueError("description claim requires two endpoints")
    return local, configured


def _reciprocal_difference(
    expected_claim: DescriptionClaim,
    actual_claims: Sequence[DescriptionClaim],
) -> str:
    expected_remote = expected_claim[1]
    if not actual_claims:
        return "No peer-side description claim was parsed at the expected interface; the description may be absent or unmatched by the active rules."
    actual_remotes = [claim[1] for claim in actual_claims]
    if expected_remote in actual_remotes:
        return "The expected reverse claim is present."
    same_device = [item for item in actual_remotes if item[0] == expected_remote[0]]
    if same_device:
        if expected_remote[1] and any(not item[1] for item in same_device):
            return "The remote device matches, but the peer-side description does not specify the expected remote interface."
        return "The remote device matches, but the remote interface differs from the expected reverse claim."
    return "The peer-side description points to a different remote device."


def _diagnostic_comparison_lines(item: Mapping[str, Any]) -> list[str]:
    code = str(item["code"])
    local = _document_endpoint(item.get("local_endpoint"))
    observed = _document_endpoint(item.get("observed_endpoint"))
    configured = _document_endpoint(item.get("configured_endpoint"))

    if code == "DESCRIPTION_NOT_RECIPROCAL" and local and configured:
        original_claim = (local, configured)
        expected_value = item.get("expected_reciprocal_claim")
        expected_claim = (
            _document_description_claim(expected_value)
            if isinstance(expected_value, Mapping)
            else (configured, local)
        )
        lines = [
            f"- A-side claim: `{_description_claim_text(original_claim)}`",
            f"- Expected reverse: `{_description_claim_text(expected_claim)}`",
        ]
        if "actual_reciprocal_claims" not in item:
            lines.extend(
                [
                    "- Actual reverse: `not recorded in this artifact`",
                    "- Difference: The legacy diagnostic does not contain peer-side comparison evidence.",
                ]
            )
            return lines
        actual_claims = [
            _document_description_claim(value)
            for value in item.get("actual_reciprocal_claims", [])
        ]
        if actual_claims:
            lines.append(
                "- Actual reverse: "
                + ", ".join(
                    f"`{_description_claim_text(claim)}`" for claim in actual_claims
                )
            )
        else:
            lines.append("- Actual reverse: `(none)`")
        lines.append(
            f"- Difference: {_reciprocal_difference(expected_claim, actual_claims)}"
        )
        return lines

    if (
        code in {"LLDP_DESC_DEVICE_CONFLICT", "LLDP_DESC_INTERFACE_CONFLICT"}
        and local
        and observed
        and configured
    ):
        lines = [
            f"- LLDP observed: `{_description_claim_text((local, observed))}`",
            f"- Description configured: `{_description_claim_text((local, configured))}`",
        ]
        field = "remote device" if code == "LLDP_DESC_DEVICE_CONFLICT" else "remote interface"
        lines.append(
            f"- Difference: The {field} differs between LLDP and the interface description."
        )
        return lines

    if code == "ONE_WAY_LLDP" and local and observed:
        return [
            f"- LLDP observed: `{_description_claim_text((local, observed))}`",
            f"- Expected reverse: `{_description_claim_text((observed, local))}`",
            "- Actual reverse: `(none)`",
            "- Difference: The reverse LLDP adjacency was not observed.",
        ]

    if code == "MULTIPLE_REMOTE_ENDPOINTS" and local:
        source = "LLDP" if observed else "Description"
        candidates = [
            _document_endpoint(value) for value in item.get("candidate_endpoints", [])
        ]
        return [
            f"- Local endpoint: `{_endpoint_text(local)}`",
            f"- {source} candidates: "
            + ", ".join(f"`{_endpoint_text(value)}`" for value in candidates),
            "- Difference: More than one remote endpoint was resolved for the same local endpoint.",
        ]

    if code == "DESCRIPTION_AMBIGUOUS" and local:
        candidates = [
            _document_endpoint(value) for value in item.get("candidate_endpoints", [])
        ]
        return [
            f"- Local endpoint: `{_endpoint_text(local)}`",
            "- Description candidates: "
            + ", ".join(f"`{_endpoint_text(value)}`" for value in candidates),
            "- Difference: The description resolves to multiple endpoint candidates.",
        ]

    return [
        f"- Local endpoint: `{_endpoint_text(local)}`",
        f"- LLDP observed: `{_endpoint_text(observed)}`",
        f"- Description configured: `{_endpoint_text(configured)}`",
    ]


def render_mismatch_links_markdown(
    document: Mapping[str, Any],
    *,
    node_site_map: Mapping[str, str] | None = None,
    node_role_map: Mapping[str, str] | None = None,
    sites: Mapping[str, Any] | None = None,
    roles: Mapping[str, Any] | None = None,
    rendered_diagnostic_ids: Iterable[str] = (),
    render_skip_reasons: Mapping[str, str] | None = None,
) -> list[str]:
    """Render a stable mismatch report from a validated diagnostic model."""
    validate_document(document, kind="LinkDiagnostics")
    spec = document["spec"]
    diagnostics = list(spec["diagnostics"])
    unevaluated_claims = list(spec["unevaluated_claims"])
    rendered = set(rendered_diagnostic_ids)
    skip_reasons = dict(render_skip_reasons or {})
    site_map = dict(node_site_map or {})
    role_map = dict(node_role_map or {})
    site_rules = dict(sites or {})
    role_rules = dict(roles or {})

    code_counts: dict[str, int] = {}
    device_groups: dict[str, set[str]] = {}
    local_counts: dict[str, int] = {}
    peer_counts: dict[str, int] = {}
    device_codes: dict[str, set[str]] = {}
    for item in diagnostics:
        code = item["code"]
        code_counts[code] = code_counts.get(code, 0) + 1
        group_id = item["group_id"]
        local_node = item["local_endpoint"]["node"]
        if item["classification"] == "conflict":
            local_counts[local_node] = local_counts.get(local_node, 0) + 1
        for device in item["affected_devices"]:
            if item["classification"] == "conflict":
                device_groups.setdefault(device, set()).add(group_id)
            device_codes.setdefault(device, set()).add(code)
        peer_nodes = {
            endpoint["node"]
            for endpoint in (
                item.get("observed_endpoint"),
                item.get("configured_endpoint"),
            )
            if endpoint and endpoint["node"] != local_node
        }
        for device in peer_nodes.intersection(item["affected_devices"]):
            peer_counts[device] = peer_counts.get(device, 0) + 1

    lines = [
        "# Link Mismatch Report",
        "",
        "## Summary",
        "",
        f"- Evaluation status: `{spec['evaluation_status']}`",
        f"- Result: `{spec['result'].upper()}`",
        f"- Evaluated links: {spec['coverage']['confirmed_link_count'] + spec['coverage']['candidate_link_count']}",
        f"- Mismatched links: {len({item['group_id'] for item in diagnostics if item['classification'] == 'conflict'})}",
        f"- Diagnostics: {len(diagnostics)}",
        (
            "- One-sided / not evaluated claims: "
            f"{len(unevaluated_claims)} (not counted as mismatches)"
        ),
        f"- Affected devices: {len(spec['affected_devices'])}",
        "",
        "### Affected Devices",
        "",
    ]
    if spec["affected_devices"]:
        lines.extend(
            [
                "| Device | Site | Role | Conflict links | Local conflicts | Referenced as peer | Diagnostics |",
                "|---|---|---|---:|---:|---:|---|",
            ]
        )
        for device in sorted(
            spec["affected_devices"],
            key=lambda item: (
                int(site_rules.get(site_map.get(item, ""), {}).get("priority", 1000)),
                site_map.get(item, ""),
                int(role_rules.get(role_map.get(item, ""), {}).get("priority", 99)),
                role_map.get(item, ""),
                item,
            ),
        ):
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_markdown(device),
                        _escape_markdown(site_map.get(device, "-")),
                        _escape_markdown(role_map.get(device, "-")),
                        str(len(device_groups.get(device, set()))),
                        str(local_counts.get(device, 0)),
                        str(peer_counts.get(device, 0)),
                        ", ".join(f"`{code}`" for code in sorted(device_codes.get(device, set()))),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No affected devices.")

    lines.extend(["", "### Diagnostics", ""])
    if code_counts:
        lines.extend(["| Diagnostic | Count |", "|---|---:|"])
        for code, count in sorted(code_counts.items()):
            lines.append(f"| `{code}` | {count} |")
    else:
        lines.append("No diagnostics.")

    unresolved = spec["unresolved_peer_references"]
    if unresolved:
        lines.extend(
            [
                "",
                "### Unresolved Peer References",
                "",
                "| Referenced peer | Referenced from | Source | Diagnostic |",
                "|---|---|---|---|",
            ]
        )
        for item in unresolved:
            lines.append(
                f"| {_escape_markdown(item['peer'])} | "
                f"{_escape_markdown(_endpoint_text((item['local_endpoint']['node'], item['local_endpoint']['interface'])))} | "
                f"{item['source']} | `{item['diagnostic_id']}` |"
            )

    if not diagnostics:
        lines.extend([""])
        if spec["evaluation_status"] == "not-evaluated":
            lines.extend(
                [
                    "LLDP and interface description evidence were not provided.",
                    "No conclusion about link consistency can be made.",
                ]
            )
        elif spec["evaluation_status"] == "partial":
            lines.extend(
                [
                    "No link mismatches were detected in the evaluated evidence.",
                    "Coverage is incomplete; this is not an all-links consistency result.",
                ]
            )
        else:
            lines.append("No link mismatches were detected.")
        return lines

    detail_sections = (
        ("conflict", "Mismatched Links"),
        ("warning", "Warnings"),
        ("unknown", "Unknown Diagnostics"),
    )
    for classification, heading in detail_sections:
        section_items = [
            item for item in diagnostics
            if item["classification"] == classification
        ]
        if not section_items:
            continue
        lines.extend(["", f"## {heading}", ""])
        for item in section_items:
            endpoints = [
                (endpoint["node"], endpoint["interface"])
                for endpoint in item["link_endpoints"]
            ]
            if item["link_state"] == "claim" and item.get("configured_endpoint"):
                endpoints = [
                    (
                        item["local_endpoint"]["node"],
                        item["local_endpoint"]["interface"],
                    ),
                    (
                        item["configured_endpoint"]["node"],
                        item["configured_endpoint"]["interface"],
                    ),
                ]
            arrow = " ↔ " if item["link_state"] == "confirmed" else " → "
            lines.extend(
                [
                    f"### {_escape_markdown(_endpoint_text(endpoints[0]))}{arrow}{_escape_markdown(_endpoint_text(endpoints[1]))}",
                    "",
                    f"- Diagnostic: `{item['code']}`",
                    f"- Classification: `{item['classification']}`",
                    f"- Link state: `{item['link_state']}`",
                ]
            )
            lines.extend(_diagnostic_comparison_lines(item))
            lines.extend(
                [
                    f"- Cause: {_escape_markdown(item['message'])}",
                    f"- Recommended check: {_recommended_check(item['code'])}",
                    (
                        "- Rendered as conflict claim: "
                        if item["link_state"] == "claim"
                        else "- Rendered in diagram: "
                    )
                    + ("yes" if item["diagnostic_id"] in rendered else "no"),
                ]
            )
            if item["diagnostic_id"] not in rendered:
                lines.append(
                    f"- Render skip reason: `{skip_reasons.get(item['diagnostic_id'], 'not-in-rendered-link-set')}`"
                )
            lines.append("")
    return lines


def diagnostic_index(document: Mapping[str, Any]) -> dict[tuple[Endpoint, Endpoint], list[dict[str, Any]]]:
    """Index diagnostics by direction-independent endpoint pair."""
    validate_document(document, kind="LinkDiagnostics")
    index: dict[tuple[Endpoint, Endpoint], list[dict[str, Any]]] = {}
    for item in document["spec"]["diagnostics"]:
        endpoints = tuple(
            (endpoint["node"], endpoint["interface"])
            for endpoint in item["link_endpoints"]
        )
        key = _canonical_endpoints(*endpoints)  # type: ignore[arg-type]
        index.setdefault(key, []).append(item)
        local = item["local_endpoint"]
        for candidate in item.get("candidate_endpoints", []):
            candidate_key = _canonical_endpoints(
                (local["node"], local["interface"]),
                (candidate["node"], candidate["interface"]),
            )
            if item not in index.setdefault(candidate_key, []):
                index[candidate_key].append(item)
    return index


def attach_link_diagnostics(
    rendered_links: Sequence[dict[str, Any]],
    document: Mapping[str, Any],
) -> set[str]:
    """Attach matching diagnostics to render links and return rendered IDs."""
    index = diagnostic_index(document)
    rendered_ids: set[str] = set()
    for link in rendered_links:
        endpoints = []
        for value in link.get("endpoints", []):
            node, separator, interface = str(value).partition(":")
            endpoints.append((node, interface if separator else ""))
        if len(endpoints) != 2:
            continue
        items = index.get(_canonical_endpoints(endpoints[0], endpoints[1]), [])
        if not items:
            continue
        link["diagnostics"] = items
        if any(item["classification"] == "conflict" for item in items):
            link["diagnostic_state"] = "conflict"
        elif any(item["classification"] == "unknown" for item in items):
            link["diagnostic_state"] = "unknown"
        else:
            link["diagnostic_state"] = "warning"
        if any(item["link_state"] == "claim" for item in items):
            link["directed"] = True
            claim = next(item for item in items if item["link_state"] == "claim")
            configured = claim.get("configured_endpoint")
            if configured:
                local = claim["local_endpoint"]
                link["endpoints"] = [
                    f"{local['node']}:{local['interface']}",
                    f"{configured['node']}:{configured['interface']}",
                ]
        rendered_ids.update(item["diagnostic_id"] for item in items)
    return rendered_ids


def build_confirmed_links_page_notice(
    document: Mapping[str, Any],
    rendered_links: Sequence[Mapping[str, Any]],
    *,
    report_name: str = "mismatch-links.md",
) -> str:
    """Summarize diagnostics omitted from a confirmed-links-only page."""
    validate_document(document, kind="LinkDiagnostics")
    rendered_ids = {
        str(item["diagnostic_id"])
        for link in rendered_links
        for item in link.get("diagnostics", [])
    }
    excluded = [
        item
        for item in document["spec"]["diagnostics"]
        if item["diagnostic_id"] not in rendered_ids
    ]
    if not excluded:
        return ""

    counts = {"conflict": 0, "warning": 0, "unknown": 0}
    for item in excluded:
        counts[item["classification"]] += 1
    return (
        f"⚠ CONFIRMED-ONLY VIEW: {len(excluded)} excluded diagnostics "
        f"(CONFLICT: {counts['conflict']}, WARNING: {counts['warning']}, "
        f"UNKNOWN: {counts['unknown']}). Candidate/claim links are not drawn. "
        f"See {report_name}."
    )
