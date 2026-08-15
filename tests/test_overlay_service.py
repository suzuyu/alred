from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

from alred.cli import (
    build_parser,
    collapse_drawio_vpc_membership_edges,
    network_diagram_result_lines,
)
from alred.overlay_service import (
    build_overlay_service_model,
    overlay_model_to_render_context,
    overlay_service_detail_markdown_lines,
    overlay_service_detail_render_context,
    overlay_service_links_csv_lines,
    select_overlay_service_ids,
    service_detail_filename,
)
from alred.schema import validate_document


CONFIG = """\
interface loopback1
  ip address 10.0.1.1/32
interface nve1
  source-interface loopback1
  member vni 50001 associate-vrf
  member vni 50900 associate-vrf
vlan 101
  vn-segment 10001
interface Vlan101
  vrf member TENANT-A
  ip address 10.10.10.1/24
  ipv6 address 2001:db8:10::1/64
  fabric forwarding mode anycast-gateway
vrf context TENANT-A
  vni 50001
  rd 65001:50001
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
    route-target export 65001:9000 evpn
vrf context SHARED-SERVICES
  vni 50900
  rd 65001:50900
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
    route-target import 65001:9000 evpn
router bgp 65001
  vrf TENANT-A
    address-family ipv4 unicast
      advertise l2vpn evpn
  vrf SHARED-SERVICES
    address-family ipv4 unicast
      advertise l2vpn evpn
"""


BGP_ROUTES = """\
BGP routing table information for VRF default, address family L2VPN EVPN
Route Distinguisher: 65001:50001 (L3VNI 50001)
*>l[5]:[0]:[0]:[24]:[10.10.10.0] 0.0.0.0 100 0 i
"""


VRF_ROUTES = """\
IP Route Table for VRF "SHARED-SERVICES"
10.10.10.0/24, ubest/mbest: 1/0
    *via 10.0.1.1, [200/0], bgp-65001, internal, tag 65001
"""


NVE_VNI = """\
nve1 50001 BGP Up CP L3 [TENANT-A]
nve1 50900 BGP Up CP L3 [SHARED-SERVICES]
"""


def _model(*, operational: bool = False) -> dict:
    command_texts = None
    if operational:
        command_texts = {
            "bgp_l2vpn_evpn": {"leaf01": BGP_ROUTES},
            "nve_vni": {"leaf01": NVE_VNI},
            "route_ipv4_all_vrfs": {"leaf01": VRF_ROUTES},
            "route_ipv6_all_vrfs": {},
        }
    return build_overlay_service_model(
        {"leaf01": CONFIG},
        node_sites={"leaf01": "adc"},
        operational_command_texts=command_texts,
        source={"type": "file", "value": "fixture"},
    )


def test_builds_services_and_directed_route_leak_from_explicit_rt() -> None:
    model = _model()

    validate_document(model, kind="OverlayServiceModel")
    assert model["spec"]["status"] == "complete"
    assert [item["service_id"] for item in model["spec"]["services"]] == [
        "adc/SHARED-SERVICES",
        "adc/TENANT-A",
    ]
    leak = model["spec"]["route_leaks"][0]
    assert leak["source_service"] == "adc/TENANT-A"
    assert leak["destination_service"] == "adc/SHARED-SERVICES"
    assert leak["matched_route_targets"] == ["65001:9000"]
    assert leak["policy_state"] == "configured"
    assert leak["operational_state"] == "unknown"
    assert leak["verification_scope"] == "unknown"
    assert leak["policy_coverage"] == {
        "source_observed": 1,
        "source_placements": 1,
        "destination_observed": 1,
        "destination_placements": 1,
    }
    context = overlay_model_to_render_context(model)
    link = context["rendered_candidate_links"][0]
    assert link["directed"] is True
    assert link["endpoints"] == ["adc/TENANT-A:", "adc/SHARED-SERVICES:"]
    assert "RT 65001:9000" in link["label"]


def test_operational_type5_and_destination_vrf_route_verify_leak() -> None:
    model = _model(operational=True)

    leak = model["spec"]["route_leaks"][0]
    assert leak["operational_state"] == "verified"
    assert leak["verification_scope"] == "full"
    assert leak["prefix_summary"] == {"expected": 1, "received": 1}
    context = overlay_model_to_render_context(model)
    assert context["rendered_links"][0]["state"] == "verified"
    assert {item["status"] for item in model["spec"]["services"]} == {"healthy"}


def test_auto_rt_is_resolved_per_l3vni_and_is_not_a_cross_vrf_wildcard() -> None:
    config = CONFIG.replace(
        "    route-target export 65001:9000 evpn\n", ""
    ).replace(
        "    route-target import 65001:9000 evpn\n", ""
    )
    model = build_overlay_service_model(
        {"leaf01": config},
        node_sites={"leaf01": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    assert model["spec"]["route_leaks"] == []
    services = {item["vrf"]: item for item in model["spec"]["services"]}
    assert services["TENANT-A"]["export_route_targets"] == ["65001:50001"]
    assert services["SHARED-SERVICES"]["import_route_targets"] == ["65001:50900"]


def test_unresolved_site_does_not_merge_same_vrf_across_nodes() -> None:
    model = build_overlay_service_model(
        {"leaf01": CONFIG, "leaf02": CONFIG},
        source={"type": "file", "value": "fixture"},
    )

    tenant_ids = sorted(
        item["service_id"]
        for item in model["spec"]["services"]
        if item["vrf"] == "TENANT-A"
    )
    assert tenant_ids == [
        "unresolved:leaf01/TENANT-A",
        "unresolved:leaf02/TENANT-A",
    ]


def test_vrf_only_border_placement_does_not_conflict_with_vtep_l3vni() -> None:
    border_config = """\
vrf context TENANT-A
interface Vlan101
  vrf member TENANT-A
  ip address 192.0.2.1/24
router bgp 65001
  vrf TENANT-A
    address-family ipv4 unicast
"""
    model = build_overlay_service_model(
        {"leaf01": CONFIG, "border01": border_config},
        node_sites={"leaf01": "adc", "border01": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    assert tenant["l3vni"] == 50001
    assert tenant["conflicts"] == []
    assert {item["node"] for item in tenant["placements"]} == {
        "border01", "leaf01"
    }
    assert {
        item["node"]: item["placement_type"]
        for item in tenant["placements"]
    } == {
        "border01": "service-edge",
        "leaf01": "evpn-vtep",
    }
    leak = next(
        item for item in model["spec"]["route_leaks"]
        if item["source_service"] == "adc/TENANT-A"
    )
    assert leak["policy_coverage"]["source_placements"] == 1
    context = overlay_service_detail_render_context(
        tenant, model["spec"]["route_leaks"]
    )
    assert "Placement border01" not in context["normalized_inventory_map"]
    assert context["node_address_lines_map"]["Service Edge border01"] == [
        "Type: VRF service edge",
        "Evidence: VRF present; EVPN binding absent",
    ]
    assert any(
        set(item["endpoints"])
        == {"Service Edge border01:", "Service adc/TENANT-A:"}
        and item["label"] == "VRF attachment"
        for item in context["rendered_links"]
    )
    markdown = "\n".join(
        overlay_service_detail_markdown_lines(
            tenant, model["spec"]["route_leaks"]
        )
    )
    assert "## EVPN Placements" in markdown
    assert "| leaf01 | evpn-vtep |" in markdown
    assert "## Service Edge Attachments" in markdown
    assert "| border01 | service-edge |" in markdown


def test_l2_only_service_uses_l2_only_evpn_placement() -> None:
    config = """\
interface loopback1
  ip address 10.0.1.1/32
interface nve1
  source-interface loopback1
  member vni 10001
vlan 101
  vn-segment 10001
"""
    model = build_overlay_service_model(
        {"leaf01": config},
        node_sites={"leaf01": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    validate_document(model, kind="OverlayServiceModel")
    service = model["spec"]["services"][0]
    assert service["vrf"] is None
    assert service["placements"] == [
        {
            "node": "leaf01",
            "placement_type": "l2-only",
            "vtep_addresses": ["10.0.1.1"],
            "vpc_domain": None,
            "vpc_shared_vtep_addresses": [],
            "nve_l3_member": False,
        }
    ]


def test_traditional_l3vni_keeps_device_local_vlan_svi_bindings() -> None:
    traditional_leaf01 = CONFIG + """\
vlan 500
  vn-segment 50001
interface Vlan500
  vrf member TENANT-A
  ip forward
  ipv6 address use-link-local-only
"""
    traditional_leaf02 = CONFIG + """\
vlan 501
  vn-segment 50001
interface Vlan501
  vrf member TENANT-A
  ip forward
  ipv6 address use-link-local-only
"""
    model = build_overlay_service_model(
        {"leaf01": traditional_leaf01, "leaf02": traditional_leaf02},
        node_sites={"leaf01": "adc", "leaf02": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    assert tenant["l3vni_mode"] == "traditional_vlan_svi"
    assert tenant["l3vni_mode_state"] == "consistent"
    assert [
        (item["node"], item["vlan"], item["svi"], item["svi_behavior"])
        for item in tenant["l3vni_bindings"]
    ] == [
        ("leaf01", 500, "Vlan500", "ip-forward"),
        ("leaf02", 501, "Vlan501", "ip-forward"),
    ]
    assert all(
        item["ipv6_use_link_local_only"]
        for item in tenant["l3vni_bindings"]
    )
    assert {item["l2vni"] for item in tenant["l2_services"]} == {10001}
    markdown = "\n".join(
        overlay_service_detail_markdown_lines(
            tenant, model["spec"]["route_leaks"]
        )
    )
    assert "| leaf01 | 50001 | Traditional VLAN/SVI | 500 | Vlan500 |" in markdown
    assert "| leaf02 | 50001 | Traditional VLAN/SVI | 501 | Vlan501 |" in markdown


def test_mixed_l3vni_modes_are_reported_as_conflict() -> None:
    traditional_leaf02 = CONFIG + """\
vlan 500
  vn-segment 50001
interface Vlan500
  vrf member TENANT-A
  ip forward
"""
    model = build_overlay_service_model(
        {"leaf01": CONFIG, "leaf02": traditional_leaf02},
        node_sites={"leaf01": "adc", "leaf02": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    assert tenant["l3vni_mode"] == "conflict"
    assert tenant["l3vni_mode_state"] == "conflict"
    assert tenant["status"] == "conflict"
    assert {item["mode"] for item in tenant["l3vni_bindings"]} == {
        "new_l3vni", "traditional_vlan_svi"
    }


def test_l2vni_keeps_device_local_vlan_bindings() -> None:
    leaf02 = CONFIG.replace("vlan 101\n", "vlan 102\n").replace(
        "interface Vlan101\n", "interface Vlan102\n"
    )
    model = build_overlay_service_model(
        {"leaf01": CONFIG, "leaf02": leaf02},
        node_sites={"leaf01": "adc", "leaf02": "adc"},
        source={"type": "file", "value": "fixture"},
    )

    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    l2_service = tenant["l2_services"][0]
    assert l2_service["vlan"] is None
    assert l2_service["vlan_state"] == "per-device"
    assert [
        (binding["node"], binding["vlan"], binding["svi"])
        for binding in l2_service["bindings"]
    ] == [
        ("leaf01", 101, "Vlan101"),
        ("leaf02", 102, "Vlan102"),
    ]


def test_selector_uses_union_and_adds_only_direct_route_leak_context() -> None:
    model = _model()

    selected, context = select_overlay_service_ids(model, vrfs=["TENANT-A"])

    assert selected == {"adc/TENANT-A"}
    assert context == {"adc/SHARED-SERVICES"}
    rendered = overlay_model_to_render_context(
        model, selected_ids=selected, context_ids=context
    )
    assert "Context: direct route leak neighbor" in rendered[
        "node_address_lines_map"
    ]["adc/SHARED-SERVICES"]
    assert "L2VNI: 1" in rendered["node_address_lines_map"]["adc/TENANT-A"]


def test_route_leak_csv_is_stable_and_directional() -> None:
    lines = overlay_service_links_csv_lines(_model())

    assert lines[0].startswith("leak_id,source_service,destination_service")
    assert ",adc/TENANT-A,adc/SHARED-SERVICES," in lines[1]


def test_summary_layout_ranks_highest_degree_service_as_hub() -> None:
    service_ids = [
        "adc/controller-vpc1",
        "adc/tenant1-vpc1",
        "adc/tenant2-vpc1",
    ]
    model = {
        "spec": {
            "services": [
                {
                    "service_id": service_id,
                    "site": "adc",
                    "vrf": service_id.split("/", 1)[1],
                    "l3vni": None,
                    "l2_services": [],
                    "placements": [],
                    "status": "configured",
                }
                for service_id in service_ids
            ],
            "route_leaks": [
                {
                    "source_service": source,
                    "destination_service": destination,
                    "matched_route_targets": ["65001:9001"],
                    "operational_state": "unknown",
                    "verification_scope": "unknown",
                    "address_families": ["ipv4"],
                }
                for source, destination in (
                    ("adc/controller-vpc1", "adc/tenant1-vpc1"),
                    ("adc/tenant1-vpc1", "adc/controller-vpc1"),
                    ("adc/controller-vpc1", "adc/tenant2-vpc1"),
                    ("adc/tenant2-vpc1", "adc/controller-vpc1"),
                )
            ],
        }
    }

    context = overlay_model_to_render_context(model)

    assert context["node_layout_rank_map"] == {
        "adc/controller-vpc1": 0,
        "adc/tenant1-vpc1": 1,
        "adc/tenant2-vpc1": 1,
    }


def test_detail_marks_auto_rt_and_includes_svi_gateway_addresses() -> None:
    model = _model()
    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    l2_service = tenant["l2_services"][0]

    assert l2_service["gateway_state"] == "yes"
    assert l2_service["gateway_modes"] == ["anycast"]
    assert l2_service["ipv4_addresses"] == ["10.10.10.1/24"]
    assert l2_service["ipv6_addresses"] == ["2001:db8:10::1/64"]
    assert tenant["l3vni_mode"] == "new_l3vni"
    lines = overlay_service_detail_markdown_lines(
        tenant, model["spec"]["route_leaks"]
    )
    markdown = "\n".join(lines)
    assert "65001:50001 (auto)" in markdown
    assert "65001:9000 (auto)" not in markdown
    assert "| 10001 | leaf01 | 101 | Vlan101 | yes | 10.10.10.1/24 | 2001:db8:10::1/64 |" in markdown
    assert "New L3VNI (VLAN/SVI-less)" in markdown

    context = overlay_service_detail_render_context(
        tenant, model["spec"]["route_leaks"]
    )
    assert "L2VNI 10001" in context["normalized_inventory_map"]
    assert "Gateway: yes" in context["node_address_lines_map"]["L2VNI 10001"]
    assert "VLAN 101 (SVI): leaf01" in context[
        "node_address_lines_map"
    ]["L2VNI 10001"]
    assert all(
        "Vlan101" not in value
        for value in context["node_address_lines_map"]["L2VNI 10001"]
    )
    assert "Same-VRF Import RT 65001-50001" in context[
        "normalized_inventory_map"
    ]
    assert "Same-VRF Export RT 65001-50001" in context[
        "normalized_inventory_map"
    ]
    leak_node = "Outbound Route Leak adc/SHARED-SERVICES"
    assert leak_node in context["normalized_inventory_map"]
    assert context["node_address_lines_map"][leak_node] == [
        "To: adc/SHARED-SERVICES",
        "RT: 65001:9000",
        "AF: ipv4",
        "State: unknown",
    ]
    assert "Export RT 65001-9000" not in context["normalized_inventory_map"]
    assert any(
        link["directed"] and link["endpoints"][1] == "Service adc/TENANT-A:"
        for link in context["rendered_links"]
    )
    assert not any(
        set(link["endpoints"])
        == {"Placement leaf01:", "Service adc/TENANT-A:"}
        for link in context["rendered_links"]
    )
    assert any(
        set(link["endpoints"])
        == {"Placement leaf01:", "L3VNI 50001:"}
        for link in context["rendered_links"]
    )
    assert any(
        set(link["endpoints"])
        == {"Placement leaf01:", "L2VNI 10001:"}
        for link in context["rendered_links"]
    )
    membership_links = [
        link
        for link in context["rendered_links"]
        if "Placement leaf01:" in link["endpoints"]
    ]
    assert membership_links
    assert {link["label"] for link in membership_links} == {""}


def test_unmatched_explicit_rt_is_displayed_as_additional() -> None:
    config = CONFIG.replace(
        "    route-target import 65001:9000 evpn\n", ""
    )
    model = build_overlay_service_model(
        {"leaf01": config},
        node_sites={"leaf01": "adc"},
        source={"type": "file", "value": "fixture"},
    )
    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )

    context = overlay_service_detail_render_context(
        tenant, model["spec"]["route_leaks"]
    )

    node = "Additional Export RT 65001-9000"
    assert context["node_address_lines_map"][node] == [
        "RT: 65001:9000",
        "Peer: unresolved",
    ]
    assert not any(
        value.startswith("Outbound Route Leak ")
        for value in context["normalized_inventory_map"]
    )


def test_route_leak_detail_groups_afs_and_keeps_same_vrf_rt() -> None:
    model = _model()
    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )
    leaks = [
        {
            "source_service": "adc/TENANT-A",
            "destination_service": "adc/SHARED-SERVICES",
            "matched_route_targets": ["65001:50001"],
            "address_families": ["ipv4"],
            "operational_state": "verified",
        },
        {
            "source_service": "adc/TENANT-A",
            "destination_service": "adc/SHARED-SERVICES",
            "matched_route_targets": ["65001:50001"],
            "address_families": ["ipv6"],
            "operational_state": "unknown",
        },
    ]

    context = overlay_service_detail_render_context(tenant, leaks)

    assert "Same-VRF Export RT 65001-50001" in context[
        "normalized_inventory_map"
    ]
    node = "Outbound Route Leak adc/SHARED-SERVICES"
    assert context["node_address_lines_map"][node] == [
        "To: adc/SHARED-SERVICES",
        "RT: 65001:50001",
        "AF: ipv4, ipv6",
        "State: ipv4=verified; ipv6=unknown",
    ]
    matching_edges = [
        item
        for item in context["rendered_candidate_links"]
        if node + ":" in item["endpoints"]
    ]
    assert len(matching_edges) == 1
    assert matching_edges[0]["label"] == "route leak"


def test_vpc_pair_is_visually_grouped_without_merging_placements() -> None:
    vpc_config = CONFIG.replace(
        "interface loopback1\n  ip address 10.0.1.1/32\n",
        "interface loopback1\n"
        "  ip address 10.0.1.1/32\n"
        "  ip address 10.0.2.1/32 secondary\n"
        "vpc domain 10\n",
    )
    vpc_leaf02 = vpc_config.replace(
        "vlan 101\n"
        "  vn-segment 10001\n"
        "interface Vlan101\n"
        "  vrf member TENANT-A\n"
        "  ip address 10.10.10.1/24\n"
        "  ipv6 address 2001:db8:10::1/64\n"
        "  fabric forwarding mode anycast-gateway\n",
        "",
    )
    model = build_overlay_service_model(
        {"leaf01": vpc_config, "leaf02": vpc_leaf02},
        node_sites={"leaf01": "adc", "leaf02": "adc"},
        source={"type": "file", "value": "fixture"},
    )
    tenant = next(
        item for item in model["spec"]["services"]
        if item["service_id"] == "adc/TENANT-A"
    )

    context = overlay_service_detail_render_context(
        tenant, model["spec"]["route_leaks"]
    )

    vpc_role = "vPC Domain 10 · shared VTEP 10.0.2.1"
    assert context["placement_roles"] == [vpc_role]
    assert context["vpc_group_roles"] == [vpc_role]
    assert context["node_role_map"]["Placement leaf01"] == vpc_role
    assert context["node_role_map"]["Placement leaf02"] == vpc_role
    assert {
        node
        for node in context["normalized_inventory_map"]
        if node.startswith("Placement ")
    } == {"Placement leaf01", "Placement leaf02"}
    l2_membership_edges = [
        item
        for item in context["rendered_links"]
        if "L2VNI 10001:" in item["endpoints"]
        and any(
            endpoint.startswith("Placement ")
            for endpoint in item["endpoints"]
        )
    ]
    assert [
        next(
            endpoint
            for endpoint in item["endpoints"]
            if endpoint.startswith("Placement ")
        )
        for item in l2_membership_edges
    ] == ["Placement leaf01:"]

    tenant["placements"] = [
        item for item in tenant["placements"] if item["node"] == "leaf01"
    ]
    one_sided_context = overlay_service_detail_render_context(
        tenant, model["spec"]["route_leaks"]
    )
    assert one_sided_context["placement_roles"] == ["placement"]
    assert one_sided_context["node_role_map"]["Placement leaf01"] == "placement"


def test_drawio_collapses_only_complete_vpc_member_edge_sets() -> None:
    root = ET.fromstring(
        """\
<mxfile>
  <diagram>
    <mxGraphModel>
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="10" value="vPC Domain 10" vertex="1" parent="1" />
        <mxCell id="11" value="Placement leaf01" vertex="1" parent="10" />
        <mxCell id="12" value="Placement leaf02" vertex="1" parent="10" />
        <mxCell id="20" value="L2VNI 100" vertex="1" parent="1" />
        <mxCell id="21" value="L2VNI 200" vertex="1" parent="1" />
        <mxCell id="30" value="" edge="1" parent="1" source="11" target="20" />
        <mxCell id="31" value="" edge="1" parent="1" source="12" target="20" />
        <mxCell id="32" value="" edge="1" parent="1" source="11" target="21" />
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""
    )

    collapsed = collapse_drawio_vpc_membership_edges(
        root, vpc_group_roles={"vPC Domain 10"}
    )

    edges = root.findall(".//mxCell[@edge='1']")
    assert collapsed == 1
    assert [(edge.get("source"), edge.get("target")) for edge in edges] == [
        ("10", "20"),
        ("11", "21"),
    ]


def test_network_diagram_result_uses_short_output_paths() -> None:
    output_dir = Path("out/site")

    lines = network_diagram_result_lines(
        output_dir=output_dir,
        diagram_paths=[
            output_dir / "topology-graph.md",
            output_dir / "topology-graph-all.drawio",
        ],
        detail_markdown_count=3,
        detail_drawio_count=3,
        status="SUCCESS",
    )

    assert "Output directory:" not in lines
    assert "  out/site/topology-graph.md" in lines
    assert "  out/site/topology-graph-all.drawio" in lines
    assert "  out/site/overlay-services/" in lines
    assert lines[-2:] == ["Status: SUCCESS", "################################"]


def test_network_diagram_result_uses_one_long_output_directory() -> None:
    output_dir = Path("very/long/output-directory")

    lines = network_diagram_result_lines(
        output_dir=output_dir,
        diagram_paths=[output_dir / "topology-graph.md"],
        detail_markdown_count=0,
        detail_drawio_count=0,
        status="PARTIAL",
    )

    assert lines[2:4] == [
        "Output directory:",
        "  very/long/output-directory",
    ]
    assert "  topology-graph.md" in lines
    assert not any("Overlay Service details:" in line for line in lines)
    assert lines[-2:] == ["Status: PARTIAL", "################################"]


def test_network_diagram_result_path_thresholds_are_inclusive() -> None:
    for value, compact in (
        ("abcdefghijklmnop", True),
        ("abcdefghijklmnopq", False),
        ("a/b", True),
        ("a/b/c", False),
    ):
        output_dir = Path(value)
        lines = network_diagram_result_lines(
            output_dir=output_dir,
            diagram_paths=[output_dir / "topology-graph.md"],
            detail_markdown_count=0,
            detail_drawio_count=0,
            status="SUCCESS",
        )
        assert ("Output directory:" not in lines) is compact


def test_network_diagram_generates_selected_service_drawio_detail(
    tmp_path: Path,
    capsys,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "leaf01_run.txt").write_text(CONFIG, encoding="utf-8")
    topology = tmp_path / "topology.clab.yaml"
    topology.write_text(
        yaml.safe_dump(
            {
                "name": "overlay-detail",
                "topology": {"nodes": {"leaf01": {"kind": "cisco_n9kv"}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    sites = tmp_path / "sites.yaml"
    sites.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "site_detection": {
                    "adc": {"priority": 10, "startswith": ["leaf"]}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    args = build_parser().parse_args(
        [
            "generate-network-diagram",
            "--input", str(topology),
            "--input-format", "clab",
            "--underlay-raw", str(raw),
            "--sites", str(sites),
            "--service", "adc/TENANT-A",
            "--overlay-detail-format", "markdown,drawio",
            "--output-dir", str(output),
            "--log-file", str(tmp_path / "network-diagram.log"),
        ]
    )

    args.func(args)
    summary = capsys.readouterr().out.split(
        "### NETWORK DIAGRAM RESULT ###", 1
    )[1]
    assert "Output directory:" in summary
    assert f"  {output}" in summary
    assert "  topology-graph.md" in summary
    assert "  topology_overlay_service.md" in summary
    assert "  topology-graph.drawio" in summary
    assert "Overlay Service details:" in summary
    assert "  Markdown: 1 files" in summary
    assert "  draw.io: 1 files" in summary
    assert "Status: SUCCESS" in summary
    assert "overlay-service-model.yaml" not in summary

    basename = service_detail_filename("adc/TENANT-A", "")
    markdown_path = output / "overlay-services" / f"{basename}.md"
    drawio_path = output / "overlay-services" / f"{basename}.drawio"
    assert markdown_path.is_file()
    assert drawio_path.is_file()
    drawio = ET.parse(drawio_path).getroot()
    assert [page.get("name") for page in drawio.findall("diagram")] == [
        "Overlay Detail adc/TENANT-A"
    ]
    text = drawio_path.read_text(encoding="utf-8")
    assert "L2VNI 10001" in text
    assert "Gateway: yes" in text
    role_geometries = {}
    for cell in drawio.findall(".//mxCell"):
        role = cell.get("value")
        if role not in {
            "inbound", "outbound", "service", "placement",
            "l3vni-interface", "l2-service",
        } or cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        assert geometry is not None
        role_geometries[role] = {
            name: float(geometry.get(name, "0"))
            for name in ("x", "y", "width", "height")
        }
    assert set(role_geometries) == {
        "inbound", "outbound", "service", "placement",
        "l3vni-interface", "l2-service",
    }
    assert role_geometries["inbound"]["y"] == role_geometries["outbound"]["y"]
    assert role_geometries["service"]["y"] > role_geometries["inbound"]["y"]
    component_y = role_geometries["l3vni-interface"]["y"]
    assert role_geometries["l2-service"]["y"] == component_y
    assert component_y > role_geometries["service"]["y"]
    assert role_geometries["placement"]["y"] > component_y
    left = min(item["x"] for item in role_geometries.values())
    right = max(item["x"] + item["width"] for item in role_geometries.values())
    service = role_geometries["service"]
    assert service["x"] + service["width"] / 2 == (left + right) / 2
    components = [
        role_geometries["l3vni-interface"],
        role_geometries["l2-service"],
    ]
    component_left = min(item["x"] for item in components)
    component_right = max(item["x"] + item["width"] for item in components)
    assert (component_left + component_right) / 2 == (left + right) / 2
    placement = role_geometries["placement"]
    assert placement["x"] + placement["width"] / 2 == (left + right) / 2
    manifest = yaml.safe_load(
        (output / "network-diagram-manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["spec"]["options"]["overlay_detail_formats"] == [
        "markdown", "drawio"
    ]


def test_individual_renderers_support_overlay_service_view(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "leaf01_run.txt").write_text(CONFIG, encoding="utf-8")
    sites = tmp_path / "sites.yaml"
    sites.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "site_detection": {
                    "adc": {"priority": 10, "startswith": ["leaf"]}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    parser = build_parser()
    mermaid = tmp_path / "topology_overlay_service.md"
    mermaid_args = parser.parse_args(
        [
            "generate-mermaid", "--view", "overlay-service",
            "--underlay-raw", str(raw), "--sites", str(sites),
            "--vrf", "TENANT-A", "--output", str(mermaid),
            "--log-file", str(tmp_path / "mermaid.log"),
        ]
    )
    mermaid_args.func(mermaid_args)
    mermaid_text = mermaid.read_text(encoding="utf-8")
    assert "adc/TENANT-A" in mermaid_text
    assert "Context: direct route leak neighbor" in mermaid_text

    dot = tmp_path / "topology_overlay_service.dot"
    graphviz_args = parser.parse_args(
        [
            "generate-graphviz", "--view", "overlay-service",
            "--underlay-raw", str(raw), "--sites", str(sites),
            "--output", str(dot), "--log-file", str(tmp_path / "graphviz.log"),
        ]
    )
    graphviz_args.func(graphviz_args)
    dot_text = dot.read_text(encoding="utf-8")
    assert dot_text.startswith("digraph topology {")
    assert " -> " in dot_text

    drawio = tmp_path / "topology_overlay_service.drawio"
    drawio_args = parser.parse_args(
        [
            "generate-drawio", "--view", "overlay-service",
            "--underlay-raw", str(raw), "--sites", str(sites),
            "--output", str(drawio), "--log-file", str(tmp_path / "drawio.log"),
        ]
    )
    drawio_args.func(drawio_args)
    assert "endArrow=block" in drawio.read_text(encoding="utf-8")
