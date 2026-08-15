from __future__ import annotations

import pytest

import alred.cli as cli
from alred.evpn_diagram import (
    EVPNDiagramError,
    build_evpn_control_plane_model,
    evpn_model_to_render_context,
)
from alred.schema import validate_document


LEAF_CONFIG = """\
interface loopback0
  ip address 10.0.0.1/32
interface loopback1
  ip address 10.0.1.1/32
interface nve1
  source-interface loopback1
router bgp 65001
  router-id 10.0.0.1
  address-family l2vpn evpn
  template peer RR
    remote-as internal
    update-source loopback0
    address-family l2vpn evpn
      send-community extended
  neighbor 10.0.0.254
    inherit peer RR
"""

SPINE_CONFIG = """\
interface loopback0
  ip address 10.0.0.254/32
router bgp 65001
  router-id 10.0.0.254
  address-family l2vpn evpn
  template peer LEAF
    remote-as internal
    update-source loopback0
    address-family l2vpn evpn
      route-reflector-client
  neighbor 10.0.0.0/24
    inherit peer LEAF
"""

ESTABLISHED_SUMMARY = """\
BGP table version is 3, L2VPN EVPN config peers 1, capable peers 1
Neighbor        V    AS    MsgRcvd    MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.0.254      4 65001         10         10        3    0    0 00:01:00 5
"""


def _model(*, summary: str | None = None) -> dict:
    return build_evpn_control_plane_model(
        {"leaf01": LEAF_CONFIG, "spine01": SPINE_CONFIG},
        operational_summaries={"leaf01": summary} if summary else {},
        node_roles={"leaf01": "leaf", "spine01": "spine"},
        node_functions={
            "leaf01": ["vtep"],
            "spine01": ["evpn-route-reflector"],
        },
        source={"type": "file", "value": "fixture"},
    )


def test_dynamic_rr_range_applies_only_to_confirmed_exact_session() -> None:
    model = _model()

    validate_document(model, kind="EVPNControlPlaneModel")
    assert model["spec"]["status"] == "complete"
    assert len(model["spec"]["peer_ranges"]) == 1
    assert len(model["spec"]["sessions"]) == 1
    session = model["spec"]["sessions"][0]
    assert session["relationship"] == "rr-client"
    assert session["rr_node"] == "spine01"
    assert session["client_node"] == "leaf01"
    assert session["state"] == "configured"
    assert {item["local_as"] for item in session["endpoints"]} == {"65001"}
    context = evpn_model_to_render_context(model)
    assert context["rendered_candidate_links"][0]["endpoints"] == [
        "spine01:",
        "leaf01:",
    ]


def test_operational_summary_promotes_configured_session_to_established() -> None:
    model = _model(summary=ESTABLISHED_SUMMARY)

    session = model["spec"]["sessions"][0]
    assert session["state"] == "established"
    assert "leaf01:bgp_l2vpn_evpn_summary" in session["evidence_refs"]


def test_ambiguous_peer_address_is_not_rendered_as_confirmed_session() -> None:
    duplicate_spine = SPINE_CONFIG.replace("spine01", "spine02")
    model = build_evpn_control_plane_model(
        {
            "leaf01": LEAF_CONFIG,
            "spine01": SPINE_CONFIG,
            "spine02": duplicate_spine,
        },
        source={"type": "file", "value": "fixture"},
    )

    assert model["spec"]["status"] == "partial"
    assert model["spec"]["sessions"] == []
    assert any(
        item["code"] == "EVPN_PEER_AMBIGUOUS"
        for item in model["spec"]["diagnostics"]
    )
    context = evpn_model_to_render_context(model)
    assert "EVPN diagnostics" in context["extra_node_names"]
    assert "EVPN_PEER_AMBIGUOUS: 1" in context["node_address_lines_map"][
        "EVPN diagnostics"
    ]


def test_present_but_unparseable_operational_evidence_fails_closed() -> None:
    with pytest.raises(EVPNDiagramError, match="could not be parsed"):
        _model(summary="unexpected output\n")


def test_unresolved_peer_template_does_not_create_configured_session() -> None:
    leaf = LEAF_CONFIG.replace("inherit peer RR", "inherit peer MISSING")

    model = build_evpn_control_plane_model(
        {"leaf01": leaf, "spine01": SPINE_CONFIG},
        source={"type": "file", "value": "fixture"},
    )

    assert model["spec"]["status"] == "partial"
    assert model["spec"]["sessions"] == []
    assert any(
        item["code"] == "EVPN_PEER_TEMPLATE_UNRESOLVED"
        for item in model["spec"]["diagnostics"]
    )


def test_operational_only_session_keeps_both_mapped_nodes() -> None:
    leaf = "interface loopback0\n  ip address 10.0.0.1/32\n"
    spine = "interface loopback0\n  ip address 10.0.0.254/32\n"

    model = build_evpn_control_plane_model(
        {"leaf01": leaf, "spine01": spine},
        operational_summaries={"leaf01": ESTABLISHED_SUMMARY},
        source={"type": "file", "value": "fixture"},
    )

    validate_document(model, kind="EVPNControlPlaneModel")
    assert set(model["spec"]["nodes"]) == {"leaf01", "spine01"}
    assert model["spec"]["sessions"][0]["state"] == "established"


def test_shared_secondary_nve_address_is_labeled_as_vpc_shared() -> None:
    leaf1 = LEAF_CONFIG.replace(
        "interface loopback0",
        "vpc domain 1\ninterface loopback0",
    ).replace(
        "  ip address 10.0.1.1/32\ninterface nve1",
        "  ip address 10.0.1.1/32\n"
        "  ip address 10.0.2.1/32 secondary\n"
        "interface nve1",
    )
    leaf2 = leaf1.replace("10.0.0.1", "10.0.0.2").replace(
        "10.0.1.1", "10.0.1.2"
    )

    model = build_evpn_control_plane_model(
        {"leaf01": leaf1, "leaf02": leaf2, "spine01": SPINE_CONFIG},
        source={"type": "file", "value": "fixture"},
    )

    for hostname in ("leaf01", "leaf02"):
        node = model["spec"]["nodes"][hostname]
        assert node["vpc_domain"] == "1"
        assert node["vpc_shared_vtep_addresses"] == ["10.0.2.1"]
    context = evpn_model_to_render_context(model)
    assert "VTEP: 10.0.1.1" in context["node_address_lines_map"]["leaf01"]
    assert "VTEP (vPC shared): 10.0.2.1" in context[
        "node_address_lines_map"
    ]["leaf01"]


def test_unpaired_secondary_nve_address_is_not_labeled_as_vpc_shared() -> None:
    leaf = LEAF_CONFIG.replace(
        "interface loopback0",
        "vpc domain 1\ninterface loopback0",
    ).replace(
        "  ip address 10.0.1.1/32\ninterface nve1",
        "  ip address 10.0.1.1/32\n"
        "  ip address 10.0.2.1/32 secondary\n"
        "interface nve1",
    )

    model = build_evpn_control_plane_model(
        {"leaf01": leaf, "spine01": SPINE_CONFIG},
        source={"type": "file", "value": "fixture"},
    )

    node = model["spec"]["nodes"]["leaf01"]
    assert node["vpc_shared_vtep_addresses"] == []
    context = evpn_model_to_render_context(model)
    assert "VTEP: 10.0.2.1" in context["node_address_lines_map"]["leaf01"]


def test_cli_reports_unsupported_evpn_parser_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Parser:
        @staticmethod
        def parse_args() -> object:
            def fail(_args: object) -> None:
                raise EVPNDiagramError("invalid EVPN summary")

            return type("Args", (), {"func": staticmethod(fail)})()

    monkeypatch.setattr(cli, "build_parser", lambda: Parser())
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "apply_password_prompt_options", lambda _args: None)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 3
    error = capsys.readouterr().err
    assert error == "PARSER_UNSUPPORTED: invalid EVPN summary\n"
    assert "Traceback" not in error
