"""Acquisition scope must survive default/specific/all VRF command parsing."""
from copy import deepcopy
from pathlib import Path

import pytest

from alred.route_diff.commands import resolve_route_command
from alred.route_diff.domain import RouteInputError, validate_source_map
from alred.route_diff.parser import parse_route_source
from alred.schema import DocumentValidationError


def transcript(command, vrf, family="ipv4"):
    heading = "IP Route" if family == "ipv4" else "IPv6 Routing"
    prefix = "192.0.2.0/24" if family == "ipv4" else "2001:db8::/64"
    return (f'leaf01# {command}\n{heading} Table for VRF "{vrf}"\n'
            f'{prefix}, ubest/mbest: 1/0\n    *via Null0, [1/0], static\nleaf01#\n').encode()


def parse(raw, **kwargs):
    return parse_route_source(raw, source_id="test", device="leaf01", **kwargs).document


@pytest.mark.parametrize("family,keyword", [("ipv4", "ip"), ("ipv6", "ipv6")])
@pytest.mark.parametrize("suffix,scope,vrf", [("", "default_vrf", "default"),
    (" vrf TENANT-A", "vrf", "TENANT-A"), (" vrf default", "vrf", "default"),
    (" vrf all", "all_vrfs", "TENANT-A")])
def test_full_table_command_variants(family, keyword, suffix, scope, vrf):
    command = f"show {keyword} route{suffix}"
    raw = transcript(command, vrf, family)
    result = parse(raw)
    table = result["scopes"][0]
    assert table["coverage"] == "COMPLETE"
    assert table["vrf"] == vrf and table["family"] == family
    assert table["command_scope"]["command_id"] == f"route_{family}_{scope}"
    assert table["command_scope"]["vrf"] == (None if scope == "all_vrfs" else vrf)
    assert table["command_scope"]["command"] == command
    evidence = table["command_scope"]["evidence"]
    assert raw[evidence["start_byte"]:evidence["end_byte"]].decode().strip() == f"leaf01# {command}"
    assert result["commands"] == [table["command_scope"]]
    assert result["versions"]["parser"] == "1.2"


def test_keyword_normalization_preserves_vrf_case():
    command = "terminal length 0; terminal width 511; SHOW IP ROUTE VRF Tenant-a | no-more"
    assert parse(transcript(command, "Tenant-a"))["scopes"][0]["coverage"] == "COMPLETE"
    scope = parse(transcript(command, "TENANT-A"))["scopes"][0]
    assert scope["coverage"] == "UNKNOWN"
    assert "VRF_COMMAND_MISMATCH" in {d["code"] for d in scope["diagnostics"]}


@pytest.mark.parametrize("command", ["show ip route summary", "show ip route 192.0.2.0/24",
    "show ipv6 route vrf TENANT-A | include via", "sh ip route", "show ip route vrf A extra"])
def test_filtered_or_abbreviated_commands_do_not_prove_full_tables(command):
    assert resolve_route_command(command) is None
    result = parse(transcript(command, "TENANT-A"))
    assert result["scopes"] == []
    assert "ROUTE_COMMAND_MISSING" in {d["code"] for d in result["diagnostics"]}


@pytest.mark.parametrize("command,vrf,family,reason", [
    ("show ip route", "TENANT-A", "ipv4", "VRF_COMMAND_MISMATCH"),
    ("show ipv6 route vrf A", "B", "ipv6", "VRF_COMMAND_MISMATCH"),
    ("show ip route vrf A", "A", "ipv6", "AF_COMMAND_MISMATCH")])
def test_command_heading_mismatch_is_unknown(command, vrf, family, reason):
    scope = parse(transcript(command, vrf, family))["scopes"][0]
    assert scope["coverage"] == "UNKNOWN"
    assert reason in {d["code"] for d in scope["diagnostics"]}


def test_distinct_vrfs_coexist_and_selection_does_not_lowercase():
    raw = transcript("show ip route vrf A", "A") + transcript("show ip route vrf a", "a")
    assert [s["vrf"] for s in parse(raw)["scopes"]] == ["A", "a"]
    selected = parse(raw, command_id="route_ipv4_vrf", vrf="a")
    assert [s["vrf"] for s in selected["scopes"]] == ["a"]
    assert selected["scopes"][0]["coverage"] == "COMPLETE"


@pytest.mark.parametrize("first,second,vrf", [
    ("show ip route vrf A", "show ip route vrf A", "A"),
    ("show ip route vrf all", "show ip route vrf A", "A"),
    ("show ip route", "show ip route vrf default", "default")])
def test_ambiguous_repeated_acquisition_requires_interval(first, second, vrf):
    raw = transcript(first, vrf) + transcript(second, vrf)
    with pytest.raises(RouteInputError, match="route command"):
        parse(raw)
    assert parse(raw, start_line=1, end_line=5)["scopes"][0]["coverage"] == "COMPLETE"


@pytest.mark.parametrize("family", ["ipv4", "ipv6"])
def test_body_source_requires_declared_vrf_and_preserves_assertion(family):
    raw = transcript("unused", "Tenant-a", family).split(b"\n", 1)[1].rsplit(b"leaf01#", 1)[0]
    result = parse(raw, input_format="nxos-route-text", command_id=f"route_{family}_vrf",
                   vrf="Tenant-a", completeness="asserted")
    scope = result["scopes"][0]
    assert scope["coverage"] == "COMPLETE" and not scope["health_eligible"]
    assert scope["command_scope"]["command"] is None
    assert scope["command_scope"]["evidence"] is None
    with pytest.raises(RouteInputError, match="VRF"):
        parse(raw, input_format="nxos-route-text", command_id=f"route_{family}_vrf")


def test_missing_named_table_is_not_an_empty_table():
    result = parse(b"leaf01# show ip route vrf MISSING\n% VRF not found\nleaf01#\n")
    assert result["scopes"] == []
    assert result["commands"][0]["vrf"] == "MISSING"
    assert "VRF_HEADING_MISSING" in {d["code"] for d in result["diagnostics"]}


@pytest.mark.parametrize("filename,vrf", [("default-vrf.txt", "default"), ("specific-vrf.txt", "TENANT-A")])
def test_saved_command_fixtures(filename, vrf):
    fixture = Path(__file__).parent / "fixtures/nxos/route_diff/synthetic" / filename
    result = parse(fixture.read_bytes())
    assert [(s["family"], s["vrf"], len(s["routes"]), s["coverage"]) for s in result["scopes"]] == [
        ("ipv4", vrf, 1, "COMPLETE"), ("ipv6", vrf, 1, "COMPLETE")]


@pytest.mark.parametrize("declaration,valid", [
    ({"command_id":"route_ipv4_vrf", "vrf":"TENANT-A"}, True),
    ({"command_id":"route_ipv6_vrf", "vrf":"TENANT-A"}, True),
    ({"command_id":"route_ipv4_default_vrf"}, True),
    ({"command_id":"route_ipv6_all_vrfs"}, True),
    ({"command_id":"route_ipv4_vrf"}, False),
    ({"command_id":"route_ipv4_vrf", "vrf":"all"}, False),
    ({"command_id":"route_ipv4_all_vrfs", "vrf":"A"}, False),
    ({"vrf":"A"}, False)])
def test_source_map_command_scope_contract(tmp_path, declaration, valid):
    source = dict(path="before.txt", input_format="nxos-route-text", **declaration)
    after = dict(deepcopy(source), path="after.txt")
    value = dict(api_version="alred/v1", kind="RouteDiffSourceMap", metadata=dict(name="scope"),
                 spec=dict(hosts=[dict(host="leaf01", before=[source], after=[after])]))
    if valid:
        assert validate_source_map(value, base_dir=tmp_path) == value
    else:
        with pytest.raises((RouteInputError, DocumentValidationError)):
            validate_source_map(value, base_dir=tmp_path)
