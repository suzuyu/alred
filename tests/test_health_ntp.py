"""NTP distribution, peer selection, and evidence regression tests (offline)."""

from copy import deepcopy

import pytest

from alred.health.evaluator import compare_snapshots, evaluate_snapshot
from alred.health.manifest import build_collect_manifest
from alred.health.parsers import NXOS_PARSER_VERSION, ParserError, parse_nxos_command
from alred.health.snapshot import build_health_snapshot
from alred.health.transcript import import_nxos_transcripts
from test_health_phase3 import JST_NOW, _resolved, _snapshot, _sources

DISTRIBUTION = "Distribution : Disabled\nLast operational state: No session"
PEERS = "Peer IP Address Serv/Peer\n192.0.2.123 Server"
HEADER = (
    "Total peers : 1\n* - selected for sync, + - peer mode(active),\n"
    "- - peer mode(passive), = - polled in client mode\n"
    "remote local st poll reach delay vrf\n----------------------\n"
)


def detail(marker="*", st=3, reach="377", vrf="management", address="192.0.2.123"):
    return HEADER + f"{marker}{address} 192.0.2.10 {st} 64 {reach} 0.00107{vrf}\n"


def snapshot(*, status=DISTRIBUTION, peers=PEERS, table=None, phase="before"):
    value = _snapshot(_resolved(), phase=phase)
    host = value["hosts"]["leaf01"]
    host["common"]["ntp"] = {}
    outputs = {"ntp_status": status, "ntp_peers": peers}
    if table is not None:
        outputs["ntp_peer_status"] = table
    for identifier, output in outputs.items():
        parsed, _ = parse_nxos_command(identifier, output)
        host["common"]["ntp"].update(parsed["ntp"])
        host["sources"].update(_sources(identifier))
    return value


def check(value, *, required=False, before=None):
    resolved = _resolved()
    resolved["spec"]["resolved"]["effective"]["spec"]["thresholds"]["ntp"][
        "required"
    ] = required
    kwargs = dict(started_at=JST_NOW, completed_at=JST_NOW)
    result = (
        evaluate_snapshot(value, resolved, **kwargs)
        if before is None
        else compare_snapshots(before, value, resolved, **kwargs)
    )
    return next(row for row in result["checks"] if row["check_id"] == "ntp_health")


@pytest.mark.parametrize(
    "st,reach,marker,expected",
    [
        (1, "1", "*", "PASS"),
        (13, "377", "*", "PASS"),
        (0, "377", "*", "WARN"),
        (14, "377", "*", "WARN"),
        (16, "377", "*", "WARN"),
        (3, "0", "*", "WARN"),
        (3, "377", "+", "WARN"),
        (3, "377", "", "WARN"),
    ],
)
@pytest.mark.parametrize("required", [False, True])
def test_selection_health_and_required_severity(st, reach, marker, expected, required):
    value = snapshot(table=detail(marker, st, reach))
    original = deepcopy(value)
    result = check(value, required=required)
    assert result["result"] == ("FAIL" if required and expected == "WARN" else expected)
    assert result["after"]["synchronization_source"] == "ntp_peer_status"
    assert value == original
    if marker == "*":
        assert "no selected peer" not in result["message"]


@pytest.mark.parametrize(
    "vrf", ["management", " management", "default", " default", ""]
)
def test_delay_and_vrf_are_separated_without_losing_selected_peer(vrf):
    parsed, _ = parse_nxos_command("ntp_peer_status", detail(vrf=vrf))
    peer = parsed["ntp"]["peer_status"]["peers"]["192.0.2.123"]
    assert peer["delay"] == 0.00107
    assert peer["vrf"] == (vrf.strip() or None)
    assert peer["reach"] == 377
    assert peer["reach_text"] == "377"
    assert peer["reach_value"] == 255
    assert peer["line_start"] == peer["line_end"] == 6


@pytest.mark.parametrize(
    "output",
    [
        "",
        HEADER,
        detail().replace("Total peers : 1", "Total peers : 2"),
        detail() + "truncated garbage",
        detail() + detail().splitlines()[-1],
        detail() + detail(vrf="default").splitlines()[-1],
        detail(marker="?"),
        detail(st=17),
        detail(reach="400"),
        detail(reach="888"),
        detail().replace(" 64 ", " 0 "),
        detail().replace("192.0.2.10", "999.0.0.1"),
        detail().replace("0.00107management", "unavailable"),
    ],
)
def test_malformed_detail_is_rejected_as_a_whole(output):
    with pytest.raises(ParserError):
        parse_nxos_command("ntp_peer_status", output)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "garbage",
        "Peer IP Address Serv/Peer\n192.0.2.123",
        PEERS + "\n192.0.2.123 Server",
    ],
)
def test_invalid_peers_are_not_empty_or_overwritten(output):
    with pytest.raises(ParserError):
        parse_nxos_command("ntp_peers", output)


def test_explicit_clock_state_is_not_overwritten_by_distribution():
    parsed, _ = parse_nxos_command(
        "ntp_status", DISTRIBUTION + "\nClock is synchronized, stratum 3"
    )
    assert parsed["ntp"]["synchronized"] is True
    assert parsed["ntp"]["status_kind"] == "clock"
    assert (
        check(
            snapshot(status=DISTRIBUTION + "\nClock is synchronized", table=detail())
        )["result"]
        == "PASS"
    )


@pytest.mark.parametrize("source", ["ntp_status", "ntp_peers"])
@pytest.mark.parametrize("failure", ["missing", "failed", "unparsed"])
def test_required_evidence_must_be_available(source, failure):
    value = snapshot(table=detail())
    sources = value["hosts"]["leaf01"]["sources"]
    if failure == "missing":
        del sources[source]
    elif failure == "failed":
        sources[source]["status"] = "failed"
    else:
        sources[source]["parse_status"] = "unknown"
    assert check(value)["result"] == "UNKNOWN"


@pytest.mark.parametrize("failure", ["missing", "failed", "unsupported", "malformed"])
@pytest.mark.parametrize("legacy", [False, True])
def test_fallback_requires_explicit_clock_and_marker_evidence(failure, legacy):
    value = snapshot(
        status="Clock is synchronized" if legacy else DISTRIBUTION,
        peers="*192.0.2.123 .GPS. 1 u 20 64 377 0.1 0.1 0.1" if legacy else PEERS,
    )
    sources = value["hosts"]["leaf01"]["sources"]
    if failure != "missing":
        sources.update(_sources("ntp_peer_status"))
        sources["ntp_peer_status"].update(
            status="failed" if failure == "failed" else "success",
            parse_status="unknown",
            parse_warning="NX-OS command returned an error"
            if failure == "unsupported"
            else "unrecognized row",
        )
    assert check(value)["result"] == (
        "PASS" if legacy and failure != "malformed" else "UNKNOWN"
    )


@pytest.mark.parametrize(
    "status,peers,table",
    [
        ("NTP is not configured", PEERS, detail()),
        ("Clock is unsynchronized", PEERS, detail()),
        (DISTRIBUTION, PEERS, "Total peers : 0"),
        (DISTRIBUTION, PEERS, detail(address="192.0.2.124")),
    ],
)
def test_conflicting_evidence_is_unknown(status, peers, table):
    assert (
        check(snapshot(status=status, peers=peers, table=table))["result"] == "UNKNOWN"
    )


@pytest.mark.parametrize("required", [False, True])
def test_explicit_empty_table_is_unconfigured(required):
    value = snapshot(peers="Peer IP Address Serv/Peer", table="Total peers : 0")
    assert check(value, required=required)["result"] == (
        "FAIL" if required else "NOT_APPLICABLE"
    )


def test_legacy_distribution_false_is_corrected_from_valid_detail():
    value = snapshot(table=detail())
    ntp = value["hosts"]["leaf01"]["common"]["ntp"]
    del ntp["status_kind"]
    del ntp["distribution"]
    ntp["synchronized"] = False
    peer = ntp["peer_status"]["peers"]["192.0.2.123"]
    del peer["reach_value"]
    del peer["reach_text"]
    assert check(value)["result"] == "PASS"
    ntp["peer_status"]["total_peers"] = 2
    assert check(value)["result"] == "UNKNOWN"


@pytest.mark.parametrize(
    "new_table,expected",
    [
        (detail(), "PASS"),
        (detail(marker="+"), "FAIL"),
        (detail(reach="0"), "FAIL"),
        (detail(vrf="default"), "FAIL"),
        (None, "UNKNOWN"),
    ],
)
def test_compare_uses_normalized_selection_and_rejects_missing_evidence(
    new_table, expected
):
    before = snapshot(table=detail())
    after = snapshot(table=new_table, phase="after")
    original = deepcopy((before, after))
    result = check(after, before=before)
    assert result["result"] == expected
    if expected == "FAIL":
        assert result["classification"] == "regression"
    assert (before, after) == original


def test_compare_missing_before_does_not_invent_regression():
    assert (
        check(snapshot(table=detail(), phase="after"), before=snapshot())["result"]
        == "UNKNOWN"
    )


def test_ipv6_identity_is_canonical_for_compare():
    before = snapshot(
        peers="2001:db8::123 Server", table=detail(address="2001:0db8:0:0:0:0:0:123")
    )
    after = snapshot(
        peers="2001:0db8::123 Server",
        table=detail(address="2001:db8::123"),
        phase="after",
    )
    assert check(after, before=before)["result"] == "PASS"


@pytest.mark.parametrize("adapter", ["collect", "transcript"])
def test_raw_output_to_result_and_absolute_evidence_lines(tmp_path, adapter):
    outputs = {
        "show ntp status": DISTRIBUTION,
        "show ntp peers": PEERS,
        "show ntp peer-status": detail(),
    }
    path = tmp_path / "leaf01_shows.log"
    if adapter == "collect":
        path.write_text(
            "\n".join(
                f"### COMMAND: {cmd}\n### COLLECTED_AT: {JST_NOW.isoformat()}\n"
                f"### STATUS: OK\n### TRANSPORT: ssh\nleaf01# {cmd}\n{output}\n"
                for cmd, output in outputs.items()
            )
        )
        manifest = build_collect_manifest(
            [tmp_path],
            collection_id="CHG-1-before",
            change_id="CHG-1",
            phase="before",
            profiles=["network-baseline-nxos"],
            started_at=JST_NOW,
            completed_at=JST_NOW,
            timezone="Asia/Tokyo",
        )
    else:
        path.write_text(
            "\n".join(f"leaf01# {cmd}\n{output}" for cmd, output in outputs.items())
            + "\nleaf01#\n"
        )
        hosts = tmp_path / "hosts.yaml"
        hosts.write_text("all:\n  hosts:\n    leaf01:\n      device_type: nxos\n")
        _, manifest = import_nxos_transcripts(
            [path],
            collection_id="CHG-1-before",
            change_id="CHG-1",
            phase="before",
            profiles=["network-baseline-nxos"],
            imported_at=JST_NOW,
            timezone="Asia/Tokyo",
            hosts_path=hosts,
        )
    manifest["spec"]["hosts"]["leaf01"]["platform"] = "nxos"
    value = build_health_snapshot(
        manifest,
        profile_refs=["network-baseline-nxos"],
        created_at=JST_NOW,
        timezone="Asia/Tokyo",
        profile_sha256=_resolved()["spec"]["resolved"]["effective_sha256"],
    )
    result = check(value)
    assert result["result"] == "PASS", result["message"]
    evidence = next(
        row for row in result["evidence"] if row.get("resource") == "192.0.2.123"
    )
    assert evidence["parser_version"] == NXOS_PARSER_VERSION
    assert (
        path.read_text()
        .splitlines()[evidence["start_line"] - 1]
        .startswith("*192.0.2.123")
    )
