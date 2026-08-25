from __future__ import annotations

from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import yaml

from alred.cli import build_parser
from alred.health.roles import load_role_config
from alred.lab_transform import load_lab_transform_parameters
from alred.parsing import load_roles, load_sites
from alred.render import get_site_priority as get_render_site_priority
from alred.schema import canonical_sha256, source_sha256, validate_document
from alred.secret_scan import sanitize_text, scan_text
from alred.topology import detect_node_role, detect_node_site, get_site_priority


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTAINERLAB_SAMPLE = (
    REPOSITORY_ROOT / "docs/manual/containerlab/examples/quick-start"
)
TOPOLOGY_SAMPLE = REPOSITORY_ROOT / "docs/manual/topology/examples/quick-start"
SINGLE_SITE_CONTAINERLAB_SAMPLE = (
    REPOSITORY_ROOT / "docs/manual/containerlab/examples/single-site-fabric"
)
SINGLE_SITE_TOPOLOGY_SAMPLE = (
    REPOSITORY_ROOT / "docs/manual/topology/examples/single-site-fabric"
)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_containerlab_quick_start_samples_are_reproducible(tmp_path: Path) -> None:
    empty_clab_env = tmp_path / "clab-env.yaml"
    empty_clab_env.write_text("{}\n", encoding="utf-8")
    generated_config_dir = tmp_path / "labconfig"
    generated_hosts = tmp_path / "hosts.lab.yaml"
    generated_manifest = tmp_path / "lab-transform-manifest.yaml"

    args = build_parser().parse_args([
        "clab-transform-config",
        "--hosts", str(CONTAINERLAB_SAMPLE / "hosts.source.example.yaml"),
        "--input", str(CONTAINERLAB_SAMPLE / "source-config"),
        "--file-suffix", "_run.example.txt",
        "--lab-parameters",
        str(CONTAINERLAB_SAMPLE / "lab-transform-parameters.example.yaml"),
        "--clab-env", str(empty_clab_env),
        "--output-hosts", str(generated_hosts),
        "--output-dir", str(generated_config_dir),
        "--manifest-output", str(generated_manifest),
        "--log-file", str(tmp_path / "clab-transform-config.log"),
    ])
    args.func(args)

    assert _load_yaml(generated_hosts) == _load_yaml(
        CONTAINERLAB_SAMPLE / "hosts.lab.example.yaml"
    )
    for expected in sorted((CONTAINERLAB_SAMPLE / "labconfig").glob("*.txt")):
        actual = generated_config_dir / expected.name
        assert actual.read_text(encoding="utf-8") == expected.read_text(
            encoding="utf-8"
        )

    sample_manifest_path = CONTAINERLAB_SAMPLE / "lab-transform-manifest.example.yaml"
    sample_manifest = _load_yaml(sample_manifest_path)
    validate_document(sample_manifest, kind="LabTransformManifest")

    parameter_spec, parameter_hash = load_lab_transform_parameters(
        CONTAINERLAB_SAMPLE / "lab-transform-parameters.example.yaml"
    )
    assert sample_manifest["spec"]["parameter_source_sha256"] == parameter_hash
    assert sample_manifest["spec"]["resolved_parameter_sha256"] == canonical_sha256(
        parameter_spec
    )

    manifest_root = sample_manifest_path.parent
    for device in sample_manifest["spec"]["devices"]:
        assert source_sha256(manifest_root / device["source_path"]) == device[
            "source_sha256"
        ]
        assert source_sha256(manifest_root / device["output_path"]) == device[
            "output_sha256"
        ]

    topology = _load_yaml(CONTAINERLAB_SAMPLE / "topology.clab.example.yaml")
    assert "startup-config" not in yaml.safe_dump(topology)


def test_quick_start_samples_do_not_contain_high_confidence_secrets() -> None:
    sample_files = sorted(CONTAINERLAB_SAMPLE.rglob("*.txt"))
    sample_files.extend(sorted(CONTAINERLAB_SAMPLE.glob("*.yaml")))

    for path in sample_files:
        findings = scan_text(
            path.read_text(encoding="utf-8"),
            artifact_id=path.name,
            path=str(path.relative_to(REPOSITORY_ROOT)),
            platform="nxos" if path.suffix == ".txt" else None,
            content_type="config" if path.suffix == ".txt" else "text",
        )
        assert not [finding for finding in findings if finding.confidence == "high"]


def test_topology_quick_start_samples_match_current_renderers(tmp_path: Path) -> None:
    canonical_raw = tmp_path / "raw"
    canonical_raw.mkdir()
    for source in sorted((CONTAINERLAB_SAMPLE / "labconfig").glob("*.txt")):
        target_name = source.name.replace("_run.example.txt", "_run.txt")
        shutil.copyfile(source, canonical_raw / target_name)

    output_dir = tmp_path / "output"
    args = build_parser().parse_args([
        "generate-network-diagram",
        "--input", str(CONTAINERLAB_SAMPLE / "topology.clab.example.yaml"),
        "--roles", str(CONTAINERLAB_SAMPLE / "roles.example.yaml"),
        "--underlay-raw", str(canonical_raw),
        "--all-graph",
        "--output-dir", str(output_dir),
        "--log-file", str(tmp_path / "generate-network-diagram.log"),
    ])
    args.func(args)

    assert (output_dir / "topology-graph.md").read_text(
        encoding="utf-8"
    ) == (TOPOLOGY_SAMPLE / "topology-graph.example.md").read_text(
        encoding="utf-8"
    )
    assert (output_dir / "topology_underlay.md").read_text(
        encoding="utf-8"
    ) == (TOPOLOGY_SAMPLE / "topology_underlay.example.md").read_text(
        encoding="utf-8"
    )
    assert (output_dir / "topology_overlay_service.md").read_text(
        encoding="utf-8"
    ) == (TOPOLOGY_SAMPLE / "topology_overlay_service.example.md").read_text(
        encoding="utf-8"
    )
    assert (output_dir / "overlay-service-links.csv").read_text(
        encoding="utf-8"
    ) == (TOPOLOGY_SAMPLE / "overlay-service-links.example.csv").read_text(
        encoding="utf-8"
    )
    assert _load_yaml(output_dir / "overlay-service-model.yaml")["spec"] == (
        _load_yaml(TOPOLOGY_SAMPLE / "overlay-service-model.example.yaml")["spec"]
    )

    actual_drawio = ET.parse(output_dir / "topology-graph-all.drawio").getroot()
    expected_drawio = ET.parse(
        TOPOLOGY_SAMPLE / "topology-graph-all.example.drawio"
    ).getroot()
    assert [item.get("name") for item in actual_drawio.findall("diagram")] == [
        "Topology TD", "Topology Confirmed Links TD",
        "Topology Defined Roles TD", "Topology LR",
        "Underlay TD", "Underlay LR",
        "EVPN TD", "EVPN LR", "Overlay Service TD", "Overlay Service LR",
    ]

    actual_drawio.set("modified", expected_drawio.attrib["modified"])
    assert ET.tostring(actual_drawio) == ET.tostring(expected_drawio)


def test_quick_start_roles_use_current_schema() -> None:
    config, _path = load_role_config(CONTAINERLAB_SAMPLE / "roles.example.yaml")
    assert config["schema_version"] == 2


def test_topology_quick_start_manifest_schema_and_hashes() -> None:
    manifest = _load_yaml(
        TOPOLOGY_SAMPLE / "network-diagram-manifest.example.yaml"
    )
    validate_document(manifest, kind="NetworkDiagramManifest")
    validate_document(
        _load_yaml(TOPOLOGY_SAMPLE / "link-diagnostics.example.yaml"),
        kind="LinkDiagnostics",
    )

    for item in manifest["spec"]["inputs"] + manifest["spec"]["artifacts"]:
        assert source_sha256(REPOSITORY_ROOT / item["path"]) == item["sha256"]

    confirmed_lines = (
        TOPOLOGY_SAMPLE / "links_confirmed.example.csv"
    ).read_text(encoding="utf-8").splitlines()
    candidate_lines = (
        TOPOLOGY_SAMPLE / "links_candidates.example.csv"
    ).read_text(encoding="utf-8").splitlines()
    assert len(confirmed_lines) == 5
    assert candidate_lines == [confirmed_lines[0]]


def test_single_site_fabric_inventory_topology_and_config_align() -> None:
    hosts = _load_yaml(
        SINGLE_SITE_CONTAINERLAB_SAMPLE / "hosts.lab.example.yaml"
    )["all"]["hosts"]
    topology = _load_yaml(
        SINGLE_SITE_CONTAINERLAB_SAMPLE / "topology.clab.example.yaml"
    )
    nodes = topology["topology"]["nodes"]
    links = topology["topology"]["links"]
    nxos_nodes = {
        name for name, attrs in nodes.items()
        if attrs.get("kind") == "cisco_n9kv"
    }

    assert len(nodes) == 22
    assert len(links) == 40
    assert len(nxos_nodes) == 8
    assert set(hosts) == nxos_nodes
    assert all(name.startswith("adc-") for name in nodes)
    assert all("startup-config" not in nodes[name] for name in nxos_nodes)
    assert nodes["adc-bgrt0101"]["group"] == "network-functions"
    assert nodes["adc-bgrt0102"]["group"] == "network-functions"
    assert {
        name: attrs["ansible_host"] for name, attrs in hosts.items()
    } == {
        name: nodes[name]["mgmt-ipv4"] for name in nxos_nodes
    }

    required_inventory_fields = {
        "os_type",
        "ansible_network_os",
        "ansible_connection",
        "netmiko_device_type",
    }
    assert all(required_inventory_fields <= set(attrs) for attrs in hosts.values())

    for name, attrs in nodes.items():
        for value in attrs.get("binds", []):
            source = str(value).split(":", 1)[0]
            assert (SINGLE_SITE_CONTAINERLAB_SAMPLE / source).exists(), name
        startup = attrs.get("startup-config")
        if startup:
            assert (SINGLE_SITE_CONTAINERLAB_SAMPLE / startup).is_file(), name
            kind_config = _load_yaml(SINGLE_SITE_CONTAINERLAB_SAMPLE / startup)
            for kind_node in kind_config.get("nodes", []):
                for mount in kind_node.get("extraMounts", []):
                    assert (
                        SINGLE_SITE_CONTAINERLAB_SAMPLE / mount["hostPath"]
                    ).exists(), name

    descriptions: dict[tuple[str, str], str] = {}
    for path in sorted(
        (SINGLE_SITE_CONTAINERLAB_SAMPLE / "source-config").glob("*_run.txt")
    ):
        text = path.read_text(encoding="utf-8")
        assert "\ninterface mgmt0\n" in text
        assert "\n!interface mgmt0\n" not in text
        if path.name.startswith("adc-lfsw01"):
            assert "route-target import 65001:19002" not in text
            assert text.count("route-target import 65001:29001") == 4
        hostname = path.name.removesuffix("_run.txt")
        current_interface = None
        for line in text.splitlines():
            interface_match = re.match(r"^interface\s+(\S+)", line, re.IGNORECASE)
            if interface_match:
                current_interface = interface_match.group(1)
                continue
            if line and not line[0].isspace() and not line.startswith("!"):
                current_interface = None
            description_match = re.match(
                r"^\s*description\s+(\S+)", line, re.IGNORECASE
            )
            if description_match and current_interface:
                interface = current_interface.casefold().replace(
                    "ethernet", "eth"
                ).replace("port-channel", "po")
                descriptions[(hostname, interface)] = description_match.group(1)

    for link in links:
        endpoints = link["endpoints"]
        assert len(endpoints) == 2
        for position in (0, 1):
            node, interface = endpoints[position].split(":", 1)
            peer = endpoints[1 - position].split(":", 1)[0]
            if node not in nxos_nodes:
                continue
            normalized_interface = interface.casefold().replace(
                "ethernet", "eth"
            ).replace("port-channel", "po")
            assert descriptions[(node, normalized_interface)] == peer


def test_single_site_fabric_roles_resolve_sample_hostnames() -> None:
    roles_path = SINGLE_SITE_CONTAINERLAB_SAMPLE / "roles.example.yaml"
    config, _path = load_role_config(roles_path)
    roles = load_roles(str(roles_path))

    assert config["schema_version"] == 2
    assert detect_node_role("adc-spsw0101", roles) == "spine"
    assert detect_node_role("adc-lfsw0101", roles) == "leaf"
    assert detect_node_role("adc-bgrt0101", roles) == "network-functions"
    assert detect_node_role("adc-ctsv0101", roles) == "server"


def test_single_site_fabric_sites_include_multisite_extension_rules() -> None:
    sites = load_sites(
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "sites.example.yaml")
    )

    assert detect_node_site("p01-edge01", sites) == "wan"
    assert detect_node_site("pe01", sites) == "wan"
    assert detect_node_site("adc-lfsw0101", sites) == "adc"
    assert detect_node_site("bdc-lfsw0101", sites) == "bdc"
    assert detect_node_site("cdc-lfsw0101", sites) == "cdc"
    assert get_site_priority("wan", sites) == 10
    assert get_site_priority("adc", sites) == 100
    assert get_site_priority("bdc", sites) == 100
    assert get_site_priority("cdc", sites) == 100
    assert get_site_priority("unknown", sites) == 1000
    assert get_site_priority("no-priority", {"no-priority": {}}) == 1000
    assert get_render_site_priority("unknown", sites) == 1000
    assert get_render_site_priority("no-priority", {"no-priority": {}}) == 1000


def test_single_site_fabric_secret_mask_example_and_configs_are_safe() -> None:
    mask_input = (
        SINGLE_SITE_CONTAINERLAB_SAMPLE
        / "secret-mask-example/input.example.txt"
    ).read_text(encoding="utf-8")
    expected_output = (
        SINGLE_SITE_CONTAINERLAB_SAMPLE
        / "secret-mask-example/output.example.txt"
    ).read_text(encoding="utf-8")
    sanitized, findings = sanitize_text(
        mask_input,
        artifact_id="single-site-secret-mask-example",
        path="secret-mask-example/input.example.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert sanitized == expected_output
    assert [finding.rule_id for finding in findings] == [
        "NXOS_USERNAME_PASSWORD",
        "NXOS_USERNAME_PASSWORD",
        "NXOS_SNMP_USER_AUTH_PRIV",
        "NXOS_SNMP_COMMUNITY",
        "NXOS_SNMP_COMMUNITY",
    ]

    config_paths = sorted(
        (SINGLE_SITE_CONTAINERLAB_SAMPLE / "source-config").glob("*_run.txt")
    ) + sorted(
        (SINGLE_SITE_CONTAINERLAB_SAMPLE / "labconfig").glob("*_run.txt")
    )
    assert len(config_paths) == 16
    for path in config_paths:
        text = path.read_text(encoding="utf-8")
        assert "\ninterface mgmt0\n" in text
        assert "\n!interface mgmt0\n" not in text
        if path.name.startswith("adc-lfsw01"):
            assert "route-target import 65001:19002" not in text
            assert text.count("route-target import 65001:29001") == 4
        findings = scan_text(
            text,
            artifact_id=path.name,
            path=str(path.relative_to(REPOSITORY_ROOT)),
            platform="nxos",
            content_type="running-config",
        )
        assert not [finding for finding in findings if finding.confidence == "high"]


def test_single_site_fabric_transform_is_reproducible(tmp_path: Path) -> None:
    generated_config_dir = tmp_path / "labconfig"
    generated_hosts = tmp_path / "hosts.lab.yaml"
    generated_manifest = tmp_path / "lab-transform-manifest.yaml"
    args = build_parser().parse_args([
        "clab-transform-config",
        "--hosts",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "hosts.source.example.yaml"),
        "--input",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "source-config"),
        "--lab-parameters",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "lab-transform-parameters.example.yaml"),
        "--output-hosts",
        str(generated_hosts),
        "--output-dir",
        str(generated_config_dir),
        "--manifest-output",
        str(generated_manifest),
        "--log-file",
        str(tmp_path / "clab-transform-config.log"),
    ])
    args.func(args)

    assert _load_yaml(generated_hosts) == _load_yaml(
        SINGLE_SITE_CONTAINERLAB_SAMPLE / "hosts.lab.example.yaml"
    )
    for expected in sorted(
        (SINGLE_SITE_CONTAINERLAB_SAMPLE / "labconfig").glob("*_run.txt")
    ):
        assert (generated_config_dir / expected.name).read_text(
            encoding="utf-8"
        ) == expected.read_text(encoding="utf-8")

    sample_manifest = _load_yaml(
        SINGLE_SITE_CONTAINERLAB_SAMPLE / "lab-transform-manifest.example.yaml"
    )
    validate_document(sample_manifest, kind="LabTransformManifest")
    for device in sample_manifest["spec"]["devices"]:
        assert source_sha256(
            REPOSITORY_ROOT / device["source_path"]
        ) == device["source_sha256"]
        assert source_sha256(
            SINGLE_SITE_CONTAINERLAB_SAMPLE / device["output_path"]
        ) == device["output_sha256"]


def test_single_site_fabric_diagrams_are_reproducible(tmp_path: Path) -> None:
    args = build_parser().parse_args([
        "generate-network-diagram",
        "--input",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "topology.clab.example.yaml"),
        "--input-format",
        "clab",
        "--roles",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "roles.example.yaml"),
        "--sites",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "sites.example.yaml"),
        "--underlay-raw",
        str(SINGLE_SITE_CONTAINERLAB_SAMPLE / "labconfig"),
        "--all-graph",
        "--all-overlay-details",
        "--overlay-detail-format",
        "markdown,drawio",
        "--output-dir",
        str(tmp_path),
        "--log-file",
        str(tmp_path / "generate-network-diagram.log"),
    ])
    args.func(args)

    for filename in (
        "topology-graph.md",
        "topology_underlay.md",
        "topology_evpn.md",
        "topology_overlay_service.md",
        "overlay-service-links.csv",
    ):
        assert (tmp_path / filename).read_text(encoding="utf-8") == (
            SINGLE_SITE_TOPOLOGY_SAMPLE / filename
        ).read_text(encoding="utf-8")

    assert _load_yaml(tmp_path / "overlay-service-model.yaml")["spec"] == (
        _load_yaml(SINGLE_SITE_TOPOLOGY_SAMPLE / "overlay-service-model.yaml")["spec"]
    )
    for expected in sorted(
        (SINGLE_SITE_TOPOLOGY_SAMPLE / "overlay-services").glob("*.md")
    ):
        assert (
            tmp_path / "overlay-services" / expected.name
        ).read_text(encoding="utf-8") == expected.read_text(encoding="utf-8")
    for expected in sorted(
        (SINGLE_SITE_TOPOLOGY_SAMPLE / "overlay-services").glob("*.drawio")
    ):
        actual_root = ET.parse(
            tmp_path / "overlay-services" / expected.name
        ).getroot()
        expected_root = ET.parse(expected).getroot()
        actual_root.set("modified", expected_root.attrib["modified"])
        assert ET.tostring(actual_root) == ET.tostring(expected_root)

    topology_text = (tmp_path / "topology-graph.md").read_text(encoding="utf-8")
    assert "graph TD" in topology_text
    assert (
        topology_text.index("subgraph adc_spine[spine]")
        < topology_text.index("subgraph adc_leaf[leaf]")
        < topology_text.index("subgraph adc_network_functions[network-functions]")
        < topology_text.index("subgraph adc_server[server]")
    )

    underlay_text = (tmp_path / "topology_underlay.md").read_text(
        encoding="utf-8"
    )
    assert "graph TD" in underlay_text
    assert underlay_text.index("subgraph adc_spine[spine]") < underlay_text.index(
        "subgraph adc_leaf[leaf]"
    )
    assert "subgraph adc_server[server]" not in underlay_text
    assert "adc-ctsv0101" not in underlay_text
    assert "adc-k01" not in underlay_text

    actual_drawio = ET.parse(tmp_path / "topology-graph-all.drawio").getroot()
    expected_drawio = ET.parse(
        SINGLE_SITE_TOPOLOGY_SAMPLE / "topology-graph-all.drawio"
    ).getroot()
    assert [item.get("name") for item in actual_drawio.findall("diagram")] == [
        "Topology TD", "Topology Confirmed Links TD",
        "Topology Defined Roles TD", "Topology LR",
        "Underlay TD", "Underlay LR",
        "EVPN TD", "EVPN LR", "Overlay Service TD", "Overlay Service LR",
    ]

    evpn_lr = next(
        page for page in actual_drawio.findall("diagram")
        if page.get("name") == "EVPN LR"
    )
    evpn_cells = {
        cell.get("id"): cell for cell in evpn_lr.findall(".//mxCell")
    }
    evpn_edges = [
        cell for cell in evpn_cells.values() if cell.get("edge") == "1"
    ]
    assert evpn_edges
    for edge in evpn_edges:
        source = evpn_cells[edge.get("source")]
        target = evpn_cells[edge.get("target")]
        assert str(source.get("value", "")).startswith("adc-spsw")
        assert str(target.get("value", "")).startswith("adc-lfsw")
        style = edge.get("style", "")
        assert "exitX=1;exitY=0.5" in style
        assert "entryX=0;entryY=0.5" in style

    for page_name in ("Overlay Service TD", "Overlay Service LR"):
        page = next(
            item for item in actual_drawio.findall("diagram")
            if item.get("name") == page_name
        )
        service_geometries = {}
        for cell in page.findall(".//mxCell"):
            value = str(cell.get("value", "")).split("<br>", 1)[0]
            if (
                cell.get("vertex") != "1"
                or value
                not in {
                    "adc/controller-vpc1",
                    "adc/tenant1-vpc1",
                    "adc/tenant2-vpc1",
                }
            ):
                continue
            geometry = cell.find("mxGeometry")
            assert geometry is not None
            service_geometries[value] = {
                name: float(geometry.get(name, "0"))
                for name in ("x", "y", "width", "height")
            }
        assert set(service_geometries) == {
            "adc/controller-vpc1",
            "adc/tenant1-vpc1",
            "adc/tenant2-vpc1",
        }
        controller = service_geometries["adc/controller-vpc1"]
        tenant1 = service_geometries["adc/tenant1-vpc1"]
        tenant2 = service_geometries["adc/tenant2-vpc1"]
        if page_name.endswith("TD"):
            assert controller["y"] < tenant1["y"] == tenant2["y"]
            assert tenant1["x"] < tenant2["x"]
            tenant_center = (
                tenant1["x"] + tenant2["x"] + tenant2["width"]
            ) / 2
            assert controller["x"] + controller["width"] / 2 == tenant_center
        else:
            assert controller["x"] < tenant1["x"] == tenant2["x"]
            assert tenant1["y"] < tenant2["y"]
            tenant_center = (
                tenant1["y"] + tenant2["y"] + tenant2["height"]
            ) / 2
            assert controller["y"] + controller["height"] / 2 == tenant_center

        service_cells = [
            cell
            for cell in page.findall(".//mxCell")
            if cell.get("vertex") == "1"
            and str(cell.get("value", "")).startswith("adc/")
        ]
        assert len(service_cells) == 3

        styles = [
            cell.get("style", "")
            for cell in page.findall(".//mxCell")
            if cell.get("edge") == "1"
        ]
        assert any("0.35" in style for style in styles)
        assert any("0.65" in style for style in styles)
        if page_name.endswith("TD"):
            assert all(
                ("exitY=1" in style and "entryY=0" in style)
                or ("exitY=0" in style and "entryY=1" in style)
                for style in styles
            )
        else:
            assert all(
                ("exitX=1" in style and "entryX=0" in style)
                or ("exitX=0" in style and "entryX=1" in style)
                for style in styles
            )

    actual_drawio.set("modified", expected_drawio.attrib["modified"])
    assert ET.tostring(actual_drawio) == ET.tostring(expected_drawio)

    topology_td = next(
        page for page in actual_drawio.findall("diagram")
        if page.get("name") == "Topology TD"
    )
    network_functions_group = topology_td.find(
        ".//mxCell[@value='network-functions']/mxGeometry"
    )
    server_group = topology_td.find(".//mxCell[@value='server']/mxGeometry")
    assert network_functions_group is not None
    assert server_group is not None
    assert network_functions_group.get("y") == server_group.get("y")
    assert network_functions_group.get("x") != server_group.get("x")

    sample_manifest = _load_yaml(
        SINGLE_SITE_TOPOLOGY_SAMPLE / "network-diagram-manifest.yaml"
    )
    validate_document(sample_manifest, kind="NetworkDiagramManifest")
    validate_document(
        _load_yaml(SINGLE_SITE_TOPOLOGY_SAMPLE / "link-diagnostics.yaml"),
        kind="LinkDiagnostics",
    )
    for item in sample_manifest["spec"]["inputs"] + sample_manifest["spec"]["artifacts"]:
        assert source_sha256(REPOSITORY_ROOT / item["path"]) == item["sha256"]
