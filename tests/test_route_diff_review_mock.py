"""Document mock checks; these do not certify a production route parser."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "docs/design/network-ops/examples/route-diff-review"
SPEC = importlib.util.spec_from_file_location("route_diff_review_mock", ROOT / "generate_mock.py")
mock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mock)


@pytest.mark.parametrize("reverse", [False, True])
def test_ecmp_pairs_only_same_unique_next_hop_and_preserves_all_values(reverse):
    p1, p2 = mock.P1, mock.P2
    p3, p4 = mock.path("192.0.2.3", "Ethernet1/3"), mock.path("192.0.2.4", "Ethernet1/4")
    before = [p1, p2, p3]
    after = [dict(p1, metric=30), p2, p4]
    if reverse:
        before.reverse()
        after.reverse()
    row = mock.route("leaf01", "198.51.100.0/24", before, after, "fixture")
    mode = "route-ad-cost-nexthop"
    pairs = mock.paired_lines(row, mode)
    assert len(pairs) == 4
    assert sum(same for _, _, same in pairs) == 1
    linked_changes = [(b, a) for b, a, same in pairs if b and a and not same]
    assert len(linked_changes) == 1
    assert all("via 192.0.2.1 " in value for value in linked_changes[0])
    for index, side in enumerate(("before", "after")):
        assert sorted(p[index] for p in pairs if p[index]) == mock.projection(row, side, mode)
    assert mock.change(row, mode) == "MODIFIED"


def test_multiple_attribute_candidates_for_same_next_hop_are_not_arbitrarily_paired():
    p = mock.P1
    row = mock.route("leaf01", "198.51.100.0/24", [p, dict(p, metric=40)],
                     [dict(p, metric=30), dict(p, metric=50)], "fixture")
    pairs = mock.paired_lines(row, "route-ad-cost-nexthop")
    assert len(pairs) == 4
    assert all((b is None) != (a is None) for b, a, _ in pairs)


@pytest.mark.parametrize("mode", ["route-only", "route-ad", "route-ad-cost"])
def test_modes_without_next_hop_do_not_infer_path_pairing(mode):
    row = mock.route("leaf01", "198.51.100.0/24", [mock.P1],
                     [dict(mock.P1, admin_distance=200, metric=30)], "fixture")
    pairs = mock.paired_lines(row, mode)
    assert all(same or not (b and a) for b, a, same in pairs)
