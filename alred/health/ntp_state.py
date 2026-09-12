"""NTP evidence validation and clock-state inference, separate from distribution."""

from copy import deepcopy
import ipaddress
import re
from typing import Any, Mapping

NTP_STATE_VERSION = "1.0"
MAX_SELECTED_STRATUM = 13


class NtpEvidenceError(ValueError):
    """NTP evidence cannot support a reliable health decision."""


def _address(value: Any) -> str:
    if not isinstance(value, str):
        raise NtpEvidenceError("invalid NTP address")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise NtpEvidenceError("invalid NTP address") from exc


def _peers(value: Any, *, detailed: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NtpEvidenceError("NTP peer table is unavailable")
    peers = {}
    for address, raw in value.items():
        address = _address(address)
        if address in peers or not isinstance(raw, Mapping):
            raise NtpEvidenceError("duplicate or invalid NTP peer")
        peer = deepcopy(dict(raw))
        if type(peer.get("selected")) is not bool:
            raise NtpEvidenceError("invalid NTP selected state")
        if detailed:
            stratum = peer.get("stratum")
            if type(stratum) is not int or not 0 <= stratum <= 16:
                raise NtpEvidenceError("invalid NTP stratum")
            reach = peer.get("reach_text")
            if reach is None:
                if type(peer.get("reach")) is not int:
                    raise NtpEvidenceError("invalid NTP reach")
                reach = str(peer["reach"])
            if not isinstance(reach, str) or not re.fullmatch(r"[0-7]{1,3}", reach):
                raise NtpEvidenceError("invalid NTP reach")
            reach_value = int(reach, 8)
            if reach_value > 255 or (
                "reach_value" in peer
                and (
                    type(peer["reach_value"]) is not int
                    or peer["reach_value"] != reach_value
                )
            ):
                raise NtpEvidenceError("inconsistent NTP reach")
            peer["reach_value"] = reach_value
            vrf = peer.get("vrf")
            if vrf is not None and (not isinstance(vrf, str) or not vrf.strip()):
                raise NtpEvidenceError("invalid NTP VRF")
        peers[address] = peer
    return peers


def ntp_state_view(host: Mapping[str, Any]) -> dict[str, Any]:
    """Validate same-generation sources and return an independent evaluation view."""
    sources = host.get("sources", {})
    for identifier in ("ntp_status", "ntp_peers"):
        source = sources.get(identifier, {})
        if source.get("status") != "success" or source.get("parse_status") != "parsed":
            raise NtpEvidenceError("NTP evidence is unavailable: " + identifier)
    value = host.get("common", {}).get("ntp")
    if not isinstance(value, Mapping):
        raise NtpEvidenceError("NTP state is unavailable")
    view = deepcopy(dict(value))
    peers = _peers(value.get("peers"))
    source = sources.get("ntp_peer_status", {})
    detail_available = (
        source.get("status") == "success" and source.get("parse_status") == "parsed"
    )
    if (
        source.get("status") == "success"
        and source.get("parse_status") == "unknown"
        and source.get("parse_warning") != "NX-OS command returned an error"
    ):
        raise NtpEvidenceError("NTP peer-status is malformed or ambiguous")
    details = {}
    if detail_available:
        table = value.get("peer_status")
        if not isinstance(table, Mapping):
            raise NtpEvidenceError("NTP peer-status table is unavailable")
        details = _peers(table.get("peers"), detailed=True)
        total = table.get("total_peers", len(details))
        if type(total) is not int or total != len(details):
            raise NtpEvidenceError("NTP Total peers does not match parsed rows")
        if "applicable" in table and table["applicable"] is not bool(details):
            raise NtpEvidenceError("NTP peer-status applicability conflicts with rows")
        view["peer_status"] = {**table, "peers": details}
    else:
        view["detail_unavailable_reason"] = (
            "NTP peer-status was not collected or is unsupported/failed"
        )

    explicit = value.get("synchronized")
    if explicit is not None and type(explicit) is not bool:
        raise NtpEvidenceError("invalid NTP synchronization state")
    kind = value.get("status_kind")
    if kind == "distribution" or (
        kind is None and value.get("operational_state") is not None
    ):
        # Old parsers fabricated synchronized=false from CFS No session.
        explicit = None
    configured = value.get("configured")
    if configured is not None and type(configured) is not bool:
        raise NtpEvidenceError("invalid NTP configured state")
    if configured is False and (peers or details):
        raise NtpEvidenceError("NTP unconfigured state conflicts with observed peers")
    configured = bool(peers or details or configured)
    if not configured and explicit is True:
        raise NtpEvidenceError("NTP synchronized state conflicts with empty peers")
    if detail_available and peers and not details:
        raise NtpEvidenceError("NTP configured peers conflict with empty peer-status")
    candidates = details if detail_available else peers
    selected = sorted(
        address for address, peer in candidates.items() if peer["selected"]
    )
    if detail_available and any(address not in peers for address in selected):
        raise NtpEvidenceError("NTP selected peer is absent from configured peers")
    unhealthy = sorted(
        address
        for address in selected
        if detail_available
        and (
            details[address]["reach_value"] == 0
            or not 1 <= details[address]["stratum"] <= MAX_SELECTED_STRATUM
        )
    )
    if not configured:
        synchronized, origin = False, "empty_peers"
    elif detail_available:
        synchronized, origin = bool(selected) and not unhealthy, "ntp_peer_status"
        if explicit is False and synchronized:
            raise NtpEvidenceError(
                "NTP explicit unsynchronized state conflicts with healthy selected peer"
            )
    elif explicit is not None:
        synchronized, origin = explicit and bool(selected), "ntp_status+ntp_peers"
    else:
        synchronized, origin = None, "unknown"
    view.update(
        peers=peers,
        configured=configured,
        synchronized=synchronized,
        synchronization_source=origin,
        selected_peers=selected,
        unhealthy_selected_peers=unhealthy,
    )
    clock_source = host.get("common", {}).get("clock", {}).get("time_source")
    if clock_source:
        view["clock_time_source"] = clock_source
    return view
