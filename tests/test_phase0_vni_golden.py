from pathlib import Path

from alred.cli import (
    build_vni_diff,
    parse_vni_gateway_records_from_run,
    read_vni_gateway_csv,
    render_vni_add_config_lines,
    render_vni_delete_config_lines,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "vni" / "current"


def _golden_lines(name: str) -> list[str]:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8").splitlines()


def test_current_vni_add_renderer_matches_golden():
    records = read_vni_gateway_csv(str(FIXTURE_ROOT / "target.csv"))

    assert render_vni_add_config_lines(records) == _golden_lines("add_leaf01.txt")


def test_current_vni_delete_renderer_matches_golden():
    records = read_vni_gateway_csv(str(FIXTURE_ROOT / "target.csv"))

    assert render_vni_delete_config_lines(records, []) == _golden_lines(
        "delete_leaf01.txt"
    )


def test_legacy_vni_csv_accepts_optional_link_local_without_config_diff():
    source = FIXTURE_ROOT / "target.csv"
    records = read_vni_gateway_csv(str(source))
    assert all(record["ipv6_link_local"] == "" for record in records)

    updated = [dict(record, ipv6_link_local="auto") for record in records]
    adds, deletes, changes = build_vni_diff(records, updated)

    assert adds == []
    assert deletes == []
    assert changes == []


def test_legacy_vni_parser_reports_explicit_and_auto_link_local():
    base = """\
vlan 10
  vn-segment 10010
vrf context TENANT-A
  vni 50001
interface Vlan10
  vrf member TENANT-A
  ipv6 address 2001:db8:10::1/64
interface nve1
  member vni 10010
  member vni 50001 associate-vrf
"""

    auto = parse_vni_gateway_records_from_run(base, "leaf01")
    explicit = parse_vni_gateway_records_from_run(
        base.replace(
            "  ipv6 address 2001:db8:10::1/64\n",
            "  ipv6 address 2001:db8:10::1/64\n"
            "  ipv6 link-local fe80::1\n",
        ),
        "leaf01",
    )

    assert auto[0]["ipv6_link_local"] == "auto"
    assert explicit[0]["ipv6_link_local"] == "fe80::1"
