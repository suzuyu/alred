from __future__ import annotations

from copy import deepcopy
import logging

from alred.constants import DEFAULT_DESCRIPTION_RULES
from alred.link_diagnostics import (
    attach_link_diagnostics,
    build_confirmed_links_page_notice,
    build_link_diagnostics,
    empty_link_diagnostics,
    render_mismatch_links_markdown,
)
from alred.parsing import merge_lldp_and_description_links
from alred.parsing import build_description_records, normalize_link_records
from alred.render import (
    render_drawio_xml_lines,
    render_graphviz_dot_lines,
    render_mermaid_graph_lines,
)
from alred.schema import validate_document


def _record(src_node: str, src_if: str, dst_node: str, dst_if: str) -> dict[str, str]:
    return {
        "src_node": src_node,
        "src_if": src_if,
        "dst_node": dst_node,
        "dst_if": dst_if,
    }


def _build(lldp: list[dict[str, str]], descriptions: list[dict[str, str]]):
    confirmed, candidates = merge_lldp_and_description_links(lldp, descriptions)
    document = build_link_diagnostics(
        lldp_records=lldp,
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts={"leaf01", "spine01"},
        lldp_hosts={"leaf01", "spine01"},
        normalizer_version="test",
        source="fixture",
    )
    return confirmed, candidates, document


def test_opposite_endpoint_description_conflict_attaches_to_confirmed_link():
    lldp = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/1"),
    ]
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/9"),
    ]

    confirmed, _candidates, document = _build(lldp, descriptions)

    diagnostics = document["spec"]["diagnostics"]
    assert [item["code"] for item in diagnostics] == [
        "LLDP_DESC_INTERFACE_CONFLICT"
    ]
    assert diagnostics[0]["local_endpoint"] == {
        "node": "spine01",
        "interface": "Ethernet1/2",
    }
    rendered = [{"endpoints": ["leaf01:Ethernet1/1", "spine01:Ethernet1/2"]}]
    assert attach_link_diagnostics(rendered, document) == {
        diagnostics[0]["diagnostic_id"]
    }
    assert rendered[0]["diagnostic_state"] == "conflict"
    assert confirmed[0]["evidence"] == "bidirectional-lldp"
    assert build_confirmed_links_page_notice(document, rendered) == ""


def test_nonreciprocal_description_claims_remain_directional_candidates():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/9"),
    ]

    confirmed, candidates, document = _build([], descriptions)

    assert confirmed == []
    assert len(candidates) == 2
    diagnostics = document["spec"]["diagnostics"]
    assert [item["code"] for item in diagnostics] == [
        "DESCRIPTION_NOT_RECIPROCAL",
        "DESCRIPTION_NOT_RECIPROCAL",
    ]
    leaf_claim = next(
        item
        for item in diagnostics
        if item["local_endpoint"]["node"] == "leaf01"
    )
    assert leaf_claim["expected_reciprocal_claim"] == {
        "local_endpoint": {"node": "spine01", "interface": "Ethernet1/2"},
        "configured_endpoint": {"node": "leaf01", "interface": "Ethernet1/1"},
    }
    assert leaf_claim["actual_reciprocal_claims"] == [
        {
            "local_endpoint": {
                "node": "spine01",
                "interface": "Ethernet1/2",
            },
            "configured_endpoint": {
                "node": "leaf01",
                "interface": "Ethernet1/9",
            },
        }
    ]
    report = "\n".join(render_mismatch_links_markdown(document))
    assert "- A-side claim: `leaf01:Ethernet1/1 -> spine01:Ethernet1/2`" in report
    assert "- Expected reverse: `spine01:Ethernet1/2 -> leaf01:Ethernet1/1`" in report
    assert "- Actual reverse: `spine01:Ethernet1/2 -> leaf01:Ethernet1/9`" in report
    assert "remote interface differs" in report
    assert "- LLDP endpoint: `-`" not in report
    rendered = [
        {"endpoints": ["spine01:Ethernet1/2", "leaf01:Ethernet1/1"]},
        {"endpoints": ["leaf01:Ethernet1/9", "spine01:Ethernet1/2"]},
    ]
    attach_link_diagnostics(rendered, document)
    assert all(link["diagnostic_state"] == "conflict" for link in rendered)
    assert all(link["directed"] is True for link in rendered)
    assert rendered[0]["endpoints"] == [
        "leaf01:Ethernet1/1",
        "spine01:Ethernet1/2",
    ]
    notice = build_confirmed_links_page_notice(document, [])
    assert "2 excluded diagnostics" in notice
    assert "CONFLICT: 2, WARNING: 0, UNKNOWN: 0" in notice
    assert "Candidate/claim links are not drawn" in notice
    assert "See mismatch-links.md" in notice


def test_nonreciprocal_description_report_distinguishes_missing_remote_interface():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", ""),
    ]

    _confirmed, _candidates, document = _build([], descriptions)

    diagnostics = document["spec"]["diagnostics"]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["actual_reciprocal_claims"] == [
        {
            "local_endpoint": {
                "node": "spine01",
                "interface": "Ethernet1/2",
            },
            "configured_endpoint": {"node": "leaf01", "interface": ""},
        }
    ]
    report = "\n".join(render_mismatch_links_markdown(document))
    assert "- Actual reverse: `spine01:Ethernet1/2 -> leaf01`" in report
    assert "does not specify the expected remote interface" in report
    assert "- Rendered as conflict claim: no" in report


def test_legacy_nonreciprocal_diagnostic_without_comparison_evidence_is_readable():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/9"),
    ]
    _confirmed, _candidates, document = _build([], descriptions)
    legacy = deepcopy(document)
    for diagnostic in legacy["spec"]["diagnostics"]:
        diagnostic.pop("expected_reciprocal_claim")
        diagnostic.pop("actual_reciprocal_claims")

    validate_document(legacy, kind="LinkDiagnostics")
    report = "\n".join(render_mismatch_links_markdown(legacy))

    assert "- Actual reverse: `not recorded in this artifact`" in report
    assert "legacy diagnostic does not contain peer-side comparison evidence" in report


def test_one_way_description_without_peer_config_is_not_a_mismatch():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
    ]
    confirmed, candidates = merge_lldp_and_description_links([], descriptions)
    document = build_link_diagnostics(
        lldp_records=[],
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts={"leaf01"},
        lldp_hosts=set(),
        normalizer_version="test",
    )

    assert document["spec"]["diagnostics"] == []
    assert len(document["spec"]["unevaluated_claims"]) == 1
    claim = document["spec"]["unevaluated_claims"][0]
    assert claim["source"] == "description"
    assert claim["reason"] == "peer-evidence-not-collected"
    rendered = [{"endpoints": ["leaf01:Ethernet1/1", "spine01:Ethernet1/2"]}]
    assert attach_link_diagnostics(rendered, document) == set()
    assert "diagnostic_state" not in rendered[0]
    report = "\n".join(render_mismatch_links_markdown(document))
    assert (
        "- One-sided / not evaluated claims: 1 (not counted as mismatches)"
        in report
    )
    assert "## One-sided / Not Evaluated Claims" not in report
    assert "peer-evidence-not-collected" not in report


def test_one_way_description_with_peer_config_but_no_peer_links_is_not_mismatch():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
    ]
    confirmed, candidates = merge_lldp_and_description_links([], descriptions)
    document = build_link_diagnostics(
        lldp_records=[],
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts={"leaf01", "spine01"},
        lldp_hosts=set(),
        normalizer_version="test",
    )

    assert document["spec"]["diagnostics"] == []
    assert document["spec"]["unevaluated_claims"][0]["reason"] == (
        "peer-link-evidence-not-found"
    )


def test_one_way_lldp_requires_peer_link_records_not_only_collected_output():
    lldp = [_record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2")]
    confirmed, candidates = merge_lldp_and_description_links(lldp, [])

    incomplete = build_link_diagnostics(
        lldp_records=lldp,
        description_records=[],
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts=set(),
        lldp_hosts={"leaf01"},
        normalizer_version="test",
    )
    assert incomplete["spec"]["diagnostics"] == []
    assert incomplete["spec"]["unevaluated_claims"][0]["source"] == "lldp"

    collected_without_peer_links = build_link_diagnostics(
        lldp_records=lldp,
        description_records=[],
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts=set(),
        lldp_hosts={"leaf01", "spine01"},
        normalizer_version="test",
    )
    assert collected_without_peer_links["spec"]["diagnostics"] == []
    assert collected_without_peer_links["spec"]["unevaluated_claims"][0][
        "reason"
    ] == "peer-link-evidence-not-found"

    lldp_with_both_host_records = [
        *lldp,
        _record("spine01", "Ethernet1/9", "leaf01", "Ethernet1/8"),
    ]
    _confirmed, candidates = merge_lldp_and_description_links(
        lldp_with_both_host_records, []
    )
    comparable = build_link_diagnostics(
        lldp_records=lldp_with_both_host_records,
        description_records=[],
        confirmed_links=[],
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts=set(),
        lldp_hosts={"leaf01", "spine01"},
        normalizer_version="test",
    )
    assert [item["code"] for item in comparable["spec"]["diagnostics"]] == [
        "ONE_WAY_LLDP",
        "ONE_WAY_LLDP",
    ]
    assert all(
        item["classification"] == "warning"
        for item in comparable["spec"]["diagnostics"]
    )
    assert comparable["spec"]["unevaluated_claims"] == []
    report = "\n".join(render_mismatch_links_markdown(comparable))
    assert "- Mismatched links: 0" in report
    assert "## Warnings" in report
    assert "## Mismatched Links" not in report
    assert "- LLDP observed: `leaf01:Ethernet1/1 -> spine01:Ethernet1/2`" in report
    assert "- Expected reverse: `spine01:Ethernet1/2 -> leaf01:Ethernet1/1`" in report
    assert "- Actual reverse: `(none)`" in report


def test_device_only_descriptions_are_reciprocal_at_device_scope():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", ""),
        _record("spine01", "Ethernet1/2", "leaf01", ""),
    ]
    confirmed, candidates = merge_lldp_and_description_links([], descriptions)
    document = build_link_diagnostics(
        lldp_records=[],
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts={"leaf01", "spine01"},
        lldp_hosts=set(),
        normalizer_version="test",
    )

    assert document["spec"]["diagnostics"] == []
    assert document["spec"]["unevaluated_claims"] == []


def test_missing_lldp_coverage_is_partial_unknown_not_pass():
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/1"),
    ]
    confirmed, candidates = merge_lldp_and_description_links([], descriptions)

    document = build_link_diagnostics(
        lldp_records=[],
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01", "spine01"},
        running_config_hosts={"leaf01", "spine01"},
        lldp_hosts=set(),
        normalizer_version="test",
    )

    assert document["spec"]["evaluation_status"] == "partial"
    assert document["spec"]["result"] == "unknown"
    report = "\n".join(render_mismatch_links_markdown(document))
    assert "Coverage is incomplete" in report
    assert "No link mismatches were detected.\n" not in report


def test_remote_outside_inventory_is_unevaluated_not_unknown_diagnostic():
    lldp = [_record("leaf01", "Ethernet1/1", "unknown-peer", "Ethernet1/2")]
    confirmed, candidates = merge_lldp_and_description_links(lldp, [])
    document = build_link_diagnostics(
        lldp_records=lldp,
        description_records=[],
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"leaf01"},
        running_config_hosts={"leaf01"},
        lldp_hosts={"leaf01"},
        normalizer_version="test",
    )

    assert document["spec"]["diagnostics"] == []
    assert document["spec"]["unevaluated_claims"][0]["reason"] == (
        "peer-not-in-inventory"
    )
    report = "\n".join(render_mismatch_links_markdown(document))
    assert (
        "- One-sided / not evaluated claims: 1 (not counted as mismatches)"
        in report
    )
    assert "## One-sided / Not Evaluated Claims" not in report
    assert "peer-not-in-inventory" not in report
    assert "REMOTE_DEVICE_UNRESOLVED" not in report


def test_server_description_outside_inventory_keeps_normal_candidate_style():
    descriptions = [
        _record(
            "adc-lfsw0101",
            "Ethernet1/4",
            "adc-k01-control-plane",
            "Ethernet1",
        )
    ]
    confirmed, candidates = merge_lldp_and_description_links([], descriptions)
    document = build_link_diagnostics(
        lldp_records=[],
        description_records=descriptions,
        confirmed_links=confirmed,
        candidate_links=candidates,
        inventory_hosts={"adc-lfsw0101"},
        running_config_hosts={"adc-lfsw0101"},
        lldp_hosts=set(),
        normalizer_version="test",
    )

    rendered = [
        {
            "endpoints": [
                "adc-lfsw0101:Ethernet1/4",
                "adc-k01-control-plane:Ethernet1",
            ],
            "evidence": "one-way-description",
        }
    ]
    assert attach_link_diagnostics(rendered, document) == set()
    assert "diagnostic_state" not in rendered[0]
    assert document["spec"]["unevaluated_claims"][0]["reason"] == (
        "peer-not-in-inventory"
    )


def test_ambiguous_description_is_diagnostic_and_not_a_link():
    ambiguity_records: list[dict] = []
    descriptions = build_description_records(
        "leaf01",
        "interface Ethernet1/1\n  description peers spine01 Ethernet1/2 and spine02\n",
        {},
        [
            {
                "name": "peer_list",
                "regex": (
                    r"(?P<remote_host>spine\d+)"
                    r"(?: (?P<remote_if>Ethernet\S+))?"
                ),
            },
        ],
        ambiguity_records=ambiguity_records,
    )
    assert descriptions == []
    assert len(ambiguity_records) == 1

    document = build_link_diagnostics(
        lldp_records=[],
        description_records=[],
        confirmed_links=[],
        candidate_links=[],
        inventory_hosts={"leaf01", "spine01", "spine02"},
        running_config_hosts={"leaf01", "spine01", "spine02"},
        lldp_hosts={"leaf01", "spine01", "spine02"},
        normalizer_version="test",
        description_ambiguities=ambiguity_records,
    )
    validate_document(document, kind="LinkDiagnostics")
    diagnostic = document["spec"]["diagnostics"][0]
    assert diagnostic["code"] == "DESCRIPTION_AMBIGUOUS"
    assert diagnostic["candidate_endpoints"] == [
        {"node": "spine01", "interface": "Ethernet1/2"},
        {"node": "spine02", "interface": ""},
    ]


def test_description_rule_order_preserves_existing_fallback_behavior():
    ambiguity_records: list[dict] = []
    descriptions = build_description_records(
        "leaf01",
        "interface Ethernet1/1\n  description TO_spine01_Ethernet1/2\n",
        {},
        DEFAULT_DESCRIPTION_RULES["description_rules"],
        ambiguity_records=ambiguity_records,
    )

    assert ambiguity_records == []
    assert descriptions[0]["dst_node"] == "spine01"
    assert descriptions[0]["dst_if"] == "Ethernet1/2"
    assert descriptions[0]["rule_name"] == "to_hostname_interface"


def test_description_rules_recognize_management_and_vpc_interface_tokens():
    for remote_if in ("MGMT", "mgmt", "vPC-peer-link", "vpc-peer-link"):
        descriptions = build_description_records(
            "leaf01",
            f"interface Ethernet1/1\n  description leaf02 {remote_if}\n",
            {},
            DEFAULT_DESCRIPTION_RULES["description_rules"],
        )

        assert len(descriptions) == 1
        assert descriptions[0]["dst_node"] == "leaf02"
        assert descriptions[0]["dst_if"] == remote_if


def test_description_interface_token_alone_is_not_a_remote_hostname():
    for description in ("MGMT", "mgmt", "vPC-peer-link", "vpc-peer-link"):
        records = build_description_records(
            "leaf01",
            f"interface Ethernet1/1\n  description {description}\n",
            {},
            DEFAULT_DESCRIPTION_RULES["description_rules"],
        )

        assert records == []


def test_description_endpoint_matching_excluded_node_substring_is_ignored():
    descriptions = build_description_records(
        "leaf01",
        "interface Ethernet1/1\n  description TO_UNUSED-LINK_Ethernet1/2\n",
        {"exclude_node_name_contains": ["unused"]},
        DEFAULT_DESCRIPTION_RULES["description_rules"],
    )

    assert descriptions == []


def test_normalized_links_exclude_mapped_node_substring_case_insensitively():
    records = [
        _record("leaf01", "Ethernet1/1", "parking", "Ethernet1/2"),
        _record("leaf01", "Ethernet1/3", "spine01", "Ethernet1/4"),
    ]
    mappings = {
        "node_name_map": {"parking": "Unused-Peer"},
        "exclude_node_name_contains": ["UNUSED"],
    }

    normalized = normalize_link_records(records, mappings)

    assert len(normalized) == 1
    assert normalized[0]["dst_node"] == "spine01"


def test_mismatch_report_contains_affected_device_summary_and_details():
    lldp = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/1"),
    ]
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/9"),
    ]
    _confirmed, _candidates, document = _build(lldp, descriptions)

    lines = render_mismatch_links_markdown(
        document,
        node_site_map={"leaf01": "site-1", "spine01": "site-1"},
        node_role_map={"leaf01": "leaf", "spine01": "spine"},
    )
    report = "\n".join(lines)

    assert "### Affected Devices" in report
    assert "| leaf01 | site-1 | leaf |" in report
    assert "| spine01 | site-1 | spine |" in report
    assert "`LLDP_DESC_INTERFACE_CONFLICT`" in report
    assert "- LLDP observed: `leaf01:Ethernet1/1 -> spine01:Ethernet1/2`" in report
    assert "- Description configured: `leaf01:Ethernet1/1 -> spine01:Ethernet1/9`" in report
    assert "remote interface differs between LLDP" in report
    assert "- Rendered in diagram: no" in report


def test_not_evaluated_report_does_not_claim_no_mismatches():
    document = empty_link_diagnostics("test", source="topology.clab.yaml")
    validate_document(document, kind="LinkDiagnostics")

    report = "\n".join(render_mismatch_links_markdown(document))

    assert "Evaluation status: `not-evaluated`" in report
    assert "No conclusion about link consistency can be made." in report
    assert "No link mismatches were detected." not in report


def test_all_renderers_show_red_conflict_edge_and_code():
    lldp = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/2"),
        _record("spine01", "Ethernet1/2", "leaf01", "Ethernet1/1"),
    ]
    descriptions = [
        _record("leaf01", "Ethernet1/1", "spine01", "Ethernet1/9"),
    ]
    _confirmed, _candidates, document = _build(lldp, descriptions)
    rendered = [{"endpoints": ["leaf01:Ethernet1/1", "spine01:Ethernet1/2"]}]
    attach_link_diagnostics(rendered, document)
    roles: dict[str, dict[str, object]] = {}
    inventory = {
        "leaf01": {"device_type": "nxos"},
        "spine01": {"device_type": "nxos"},
    }
    common = {
        "rendered_links": rendered,
        "roles": roles,
        "normalized_inventory_map": inventory,
        "normalized_mgmt_ip_map": {},
        "detect_node_role_func": lambda _node, _roles: "other",
        "get_role_priority_func": lambda _role, _roles: 99,
        "is_network_device_type_func": lambda value: value == "nxos",
        "direction": "TD",
        "group_by_role": False,
        "add_comments": False,
        "candidate_links": [],
    }

    mermaid = "\n".join(render_mermaid_graph_lines(**common))
    graphviz = "\n".join(render_graphviz_dot_lines(**common, title="Topology"))
    drawio = "\n".join(
        render_drawio_xml_lines(
            **common,
            title="Topology",
            page_notice=(
                "⚠ CONFIRMED-ONLY VIEW: 1 excluded diagnostics "
                "(CONFLICT: 1, WARNING: 0, UNKNOWN: 0). "
                "Candidate/claim links are not drawn. See mismatch-links.md."
            ),
        )
    )

    assert "linkStyle 0 stroke:#dc2626" in mermaid
    assert "LLDP_DESC_INTERFACE_CONFLICT" in mermaid
    assert 'color=\"#dc2626\"' in graphviz
    assert "LLDP_DESC_INTERFACE_CONFLICT" in graphviz
    assert "strokeColor=#dc2626" in drawio
    assert "LLDP_DESC_INTERFACE_CONFLICT" in drawio
    assert "CONFIRMED-ONLY VIEW: 1 excluded diagnostics" in drawio
    assert "fillColor=#fffbeb" in drawio
    assert "See mismatch-links.md" in drawio
