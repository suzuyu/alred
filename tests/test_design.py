from __future__ import annotations

import logging
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from alred.cli import apply_n9kv_startup_delay, build_clab_set_step_args, build_parser
from alred.constants import DEFAULT_CLAB_SET_CMDS
from alred.design import normalize_and_validate_cables
from alred.parsing import normalize_interface_name
from alred.topology import detect_node_site


class DeviceAwareNormalizationTests(unittest.TestCase):
    def test_linux_port_names_become_container_interfaces(self) -> None:
        mappings = {"interface_name_map": {}, "node_name_map": {}, "exclude_interfaces": []}
        self.assertEqual(normalize_interface_name("Port 1", mappings, "linux"), "eth1")
        self.assertEqual(normalize_interface_name("PORT2", mappings, "linux"), "eth2")
        self.assertEqual(normalize_interface_name("eth3", mappings, "linux"), "eth3")
        self.assertEqual(normalize_interface_name("Eth1/1", mappings, "nxos"), "Ethernet1/1")

    def test_explicit_mapping_has_priority(self) -> None:
        mappings = {
            "interface_name_map": {"Port 1": "eth10"},
            "node_name_map": {},
            "exclude_interfaces": [],
        }
        self.assertEqual(normalize_interface_name("Port 1", mappings, "linux"), "eth10")


class DesignValidationTests(unittest.TestCase):
    def test_duplicate_endpoint_and_linux_eth0_are_errors(self) -> None:
        inventory = {
            "leaf01": {"device_type": "nxos", "ip": "192.0.2.1"},
            "server01": {"device_type": "linux", "ip": "192.0.2.2"},
        }
        mappings = {"interface_name_map": {}, "node_name_map": {}, "exclude_interfaces": []}
        records = [
            {
                "src_node": "leaf01", "src_if": "Eth1/1",
                "dst_node": "server01", "dst_if": "Port 0",
                "enabled": True, "description": "", "row": 2,
            },
            {
                "src_node": "leaf01", "src_if": "Ethernet1/1",
                "dst_node": "server01", "dst_if": "Port 2",
                "enabled": True, "description": "", "row": 3,
            },
        ]
        _normalized, issues = normalize_and_validate_cables(records, inventory, mappings)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        self.assertTrue(any("eth0" in message for message in errors))
        self.assertTrue(any("already used" in message for message in errors))


class SiteDetectionTests(unittest.TestCase):
    def test_specific_prefix_beats_earlier_broad_contains(self) -> None:
        sites = {
            "wan": {"contains": ["p", "pe", "internet"]},
            "adc": {"startswith": ["adc-"]},
        }

        self.assertEqual(detect_node_site("adc-spsw0101", sites), "adc")
        self.assertEqual(detect_node_site("p01", sites), "wan")
        self.assertEqual(detect_node_site("internet-pe01", sites), "wan")


class StartupDelayTests(unittest.TestCase):
    def test_applies_staggered_n9kv_startup_delay(self) -> None:
        topology = {
            "topology": {
                "nodes": {
                    "n1": {"kind": "cisco_n9kv"},
                    "n2": {"kind": "cisco_n9kv"},
                    "n3": {"kind": "cisco_n9kv"},
                    "n4": {"kind": "cisco_n9kv", "startup-delay": 123},
                    "n5": {"kind": "cisco_n9kv"},
                    "server1": {"kind": "linux"},
                }
            }
        }

        updated = apply_n9kv_startup_delay(topology, "2,600", logging.getLogger("test"))
        nodes = topology["topology"]["nodes"]

        self.assertEqual(updated, 2)
        self.assertNotIn("startup-delay", nodes["n1"])
        self.assertNotIn("startup-delay", nodes["n2"])
        self.assertEqual(nodes["n3"]["startup-delay"], 600)
        self.assertEqual(nodes["n4"]["startup-delay"], 123)
        self.assertEqual(nodes["n5"]["startup-delay"], 1200)
        self.assertNotIn("startup-delay", nodes["server1"])


class ClabSetCmdsTests(unittest.TestCase):
    def test_generate_diagram_steps_have_site_grouping_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clab-set-cmds"])

        for step in DEFAULT_CLAB_SET_CMDS:
            if step.get("command") not in {"generate-mermaid", "generate-graphviz", "generate-drawio"}:
                continue
            step_args = build_clab_set_step_args(step, args, verbose=False)
            self.assertEqual(step_args.input_format, "csv")
            self.assertIsNone(step_args.sites)
            self.assertFalse(step_args.group_by_site)


class InitClabIntegrationTests(unittest.TestCase):
    def test_generates_all_nodes_and_reports_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts.txt"
            cables = root / "clab_cables.csv"
            env = root / "clab_merge.yaml"
            sites = root / "sites.yaml"
            output = root / "topology.clab.yaml"
            normalized = root / "links_design_normalized.csv"
            report = root / "validation.md"

            hosts.write_text(
                "10.0.0.81 leaf01 # nxos\n"
                "10.0.0.90 server01 # linux, profile=bond, vlan=2001, ipv4=100.64.0.1/24, "
                "ipv4_gw=100.64.0.254, ipv6=fd12:0:0:1::101/64, "
                "ipv6_gw=fd12:0:0:1::1\n"
                "10.0.0.91 unused01 # linux\n",
                encoding="utf-8",
            )
            cables.write_text(
                "src_node,src_if,dst_node,dst_if,enabled,description\n"
                "leaf01,Eth1/1,server01,Port 1,true,server link\n",
                encoding="utf-8",
            )
            env.write_text(
                "mgmt:\n"
                "  network: clab-mgmt\n"
                "  ipv4-subnet: 192.168.129.0/24\n"
                "  ipv4-range: 192.168.129.80/28\n",
                encoding="utf-8",
            )
            sites.write_text(
                "site_detection:\n"
                "  site-a:\n"
                "    startswith:\n"
                "      - leaf\n"
                "      - server\n",
                encoding="utf-8",
            )

            parser = build_parser()
            args = parser.parse_args([
                "init-clab",
                "--hosts", str(hosts),
                "--cables", str(cables),
                "--clab-env", str(env),
                "--sites", str(sites),
                "--output", str(output),
                "--output-normalized", str(normalized),
                "--validation-report", str(report),
                "--log-file", str(root / "init-clab.log"),
            ])
            args.func(args)

            topology = yaml.safe_load(output.read_text(encoding="utf-8"))
            nodes = topology["topology"]["nodes"]
            self.assertEqual(set(nodes), {"leaf01", "server01", "unused01"})
            self.assertEqual(
                topology["topology"]["kinds"]["linux"]["image"],
                "ghcr.io/hellt/network-multitool:latest",
            )
            self.assertEqual(nodes["leaf01"]["mgmt-ipv4"], "192.168.129.81")
            self.assertEqual(nodes["server01"]["mgmt-ipv4"], "192.168.129.90")
            self.assertEqual(nodes["leaf01"]["labels"]["site"], "site-a")
            self.assertEqual(nodes["server01"]["labels"]["site"], "site-a")
            self.assertEqual(nodes["server01"]["env"]["VLAN_ID"], "2001")
            self.assertEqual(nodes["server01"]["env"]["IP_CIDR"], "100.64.0.1/24")
            self.assertEqual(nodes["server01"]["env"]["DEF_GW"], "100.64.0.254")
            self.assertEqual(nodes["server01"]["env"]["IPV6_CIDR"], "fd12:0:0:1::101/64")
            self.assertEqual(nodes["server01"]["env"]["DEF_GW6"], "fd12:0:0:1::1")
            self.assertEqual(nodes["server01"]["env"]["SET_DEFAULT_ROUTE"], "true")
            self.assertEqual(nodes["server01"]["binds"], ["scripts/linux:/scripts:ro"])
            self.assertEqual(nodes["server01"]["exec"], ["sh -lc '/scripts/init-bond-singlevlan-route.sh'"])
            self.assertEqual(
                set(topology["topology"]["links"][0]["endpoints"]),
                {"leaf01:Ethernet1/1", "server01:eth1"},
            )
            normalized_text = normalized.read_text(encoding="utf-8")
            self.assertIn("Ethernet1/1", normalized_text)
            self.assertIn("eth1", normalized_text)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Node has no cable connections: unused01", report_text)
            self.assertIn("overlaps dynamic range", report_text)


class GenerateMermaidClabInputTests(unittest.TestCase):
    def test_generates_mermaid_from_clab_topology_with_standalone_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clab = root / "topology.clab.yaml"
            output = root / "topology.md"

            clab.write_text(
                "topology:\n"
                "  nodes:\n"
                "    leaf01:\n"
                "      kind: cisco_n9kv\n"
                "      mgmt-ipv4: 192.0.2.11\n"
                "      group: leaf\n"
                "    server01:\n"
                "      kind: linux\n"
                "      group: server\n"
                "    unused01:\n"
                "      kind: linux\n"
                "      group: standalone\n"
                "  links:\n"
                "    - endpoints: [\"leaf01:Ethernet1/1\", \"server01:eth1\"]\n",
                encoding="utf-8",
            )

            parser = build_parser()
            args = parser.parse_args([
                "generate-mermaid",
                "--input", str(clab),
                "--group-by-role",
                "--output", str(output),
                "--log-file", str(root / "generate-mermaid.log"),
            ])
            args.func(args)

            mermaid = output.read_text(encoding="utf-8")
            self.assertIn("leaf01<br/>mgmt: 192.0.2.11", mermaid)
            self.assertIn("server01", mermaid)
            self.assertIn("unused01", mermaid)
            self.assertIn("subgraph leaf[leaf]", mermaid)
            self.assertIn("subgraph standalone[standalone]", mermaid)
            self.assertIn('server01 -->|"eth1 ↔ Ethernet1/1"| leaf01', mermaid)

    def test_generates_site_and_role_hierarchy_from_clab_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clab = root / "topology.clab.yaml"
            output = root / "topology.md"

            clab.write_text(
                "topology:\n"
                "  nodes:\n"
                "    site1-bgw01:\n"
                "      kind: cisco_n9kv\n"
                "      group: border-gateway\n"
                "      labels:\n"
                "        site: site-1\n"
                "    wan01:\n"
                "      kind: cisco_n9kv\n"
                "      group: wan\n"
                "      labels:\n"
                "        site: wan\n"
                "    site2-bgw01:\n"
                "      kind: cisco_n9kv\n"
                "      group: border-gateway\n"
                "      labels:\n"
                "        site: site-2\n"
                "  links:\n"
                "    - endpoints: [\"site1-bgw01:Ethernet1/1\", \"wan01:Ethernet1/1\"]\n"
                "    - endpoints: [\"wan01:Ethernet1/2\", \"site2-bgw01:Ethernet1/1\"]\n",
                encoding="utf-8",
            )

            parser = build_parser()
            args = parser.parse_args([
                "generate-mermaid",
                "--input", str(clab),
                "--group-by-site",
                "--group-by-role",
                "--output", str(output),
                "--log-file", str(root / "generate-mermaid.log"),
            ])
            args.func(args)

            mermaid = output.read_text(encoding="utf-8")
            self.assertIn("subgraph site_site_1[site-1]", mermaid)
            self.assertIn("subgraph site_1_border_gateway[border-gateway]", mermaid)
            self.assertIn("subgraph site_wan[wan]", mermaid)
            self.assertIn("subgraph site_site_2[site-2]", mermaid)

    def test_detects_sites_from_sites_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clab = root / "topology.clab.yaml"
            sites = root / "sites.yaml"
            output = root / "topology.md"

            clab.write_text(
                "topology:\n"
                "  nodes:\n"
                "    site1-bgw01:\n"
                "      kind: cisco_n9kv\n"
                "      group: border-gateway\n"
                "    wan01:\n"
                "      kind: cisco_n9kv\n"
                "      group: wan\n"
                "  links:\n"
                "    - endpoints: [\"site1-bgw01:Ethernet1/1\", \"wan01:Ethernet1/1\"]\n",
                encoding="utf-8",
            )
            sites.write_text(
                "site_detection:\n"
                "  site-1:\n"
                "    priority: 1\n"
                "    startswith:\n"
                "      - site1-\n"
                "  wan:\n"
                "    priority: 0\n"
                "    startswith:\n"
                "      - wan\n",
                encoding="utf-8",
            )

            parser = build_parser()
            args = parser.parse_args([
                "generate-mermaid",
                "--input", str(clab),
                "--sites", str(sites),
                "--group-by-site",
                "--group-by-role",
                "--output", str(output),
                "--log-file", str(root / "generate-mermaid.log"),
            ])
            args.func(args)

            mermaid = output.read_text(encoding="utf-8")
            self.assertIn("subgraph site_site_1[site-1]", mermaid)
            self.assertIn("subgraph site_wan[wan]", mermaid)
            self.assertLess(
                mermaid.index("subgraph site_wan[wan]"),
                mermaid.index("subgraph site_site_1[site-1]"),
            )

    def test_graphviz_and_drawio_group_by_site_from_clab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clab = root / "topology.clab.yaml"
            roles = root / "roles.yaml"
            sites = root / "sites.yaml"
            dot_output = root / "topology.dot"
            drawio_output = root / "topology.drawio"

            clab.write_text(
                "topology:\n"
                "  nodes:\n"
                "    site1-bgw01:\n"
                "      kind: cisco_n9kv\n"
                "      group: bgw\n"
                "      labels:\n"
                "        site: site-1\n"
                "    site1-rs01:\n"
                "      kind: cisco_n9kv\n"
                "      group: rs\n"
                "      labels:\n"
                "        site: site-1\n"
                "    site1-spine01:\n"
                "      kind: cisco_n9kv\n"
                "      group: spine\n"
                "      labels:\n"
                "        site: site-1\n"
                "    wan01:\n"
                "      kind: cisco_n9kv\n"
                "      group: wan\n"
                "      labels:\n"
                "        site: wan\n"
                "    site2-bgw01:\n"
                "      kind: cisco_n9kv\n"
                "      group: bgw\n"
                "      labels:\n"
                "        site: site-2\n"
                "  links:\n"
                "    - endpoints: [\"site1-bgw01:Ethernet1/1\", \"site1-rs01:Ethernet1/1\"]\n"
                "    - endpoints: [\"site1-bgw01:Ethernet1/2\", \"site1-spine01:Ethernet1/1\"]\n"
                "    - endpoints: [\"site1-bgw01:Ethernet1/3\", \"wan01:Ethernet1/1\"]\n"
                "    - endpoints: [\"wan01:Ethernet1/2\", \"site2-bgw01:Ethernet1/1\"]\n",
                encoding="utf-8",
            )
            roles.write_text(
                "role_detection:\n"
                "  border-gateway:\n"
                "    priority: 0\n"
                "    contains:\n"
                "      - bgw\n"
                "  route-server:\n"
                "    priority: 0\n"
                "    contains:\n"
                "      - rs\n"
                "  spine:\n"
                "    priority: 2\n"
                "    contains:\n"
                "      - spine\n",
                encoding="utf-8",
            )
            sites.write_text(
                "site_detection:\n"
                "  wan:\n"
                "    priority: 0\n"
                "  site-1:\n"
                "    priority: 1\n"
                "  site-2:\n"
                "    priority: 1\n",
                encoding="utf-8",
            )

            parser = build_parser()
            dot_args = parser.parse_args([
                "generate-graphviz",
                "--input", str(clab),
                "--roles", str(roles),
                "--sites", str(sites),
                "--group-by-site",
                "--group-by-role",
                "--output", str(dot_output),
                "--log-file", str(root / "generate-graphviz.log"),
            ])
            dot_args.func(dot_args)

            drawio_args = parser.parse_args([
                "generate-drawio",
                "--input", str(clab),
                "--roles", str(roles),
                "--sites", str(sites),
                "--group-by-site",
                "--group-by-role",
                "--output", str(drawio_output),
                "--log-file", str(root / "generate-drawio.log"),
            ])
            drawio_args.func(drawio_args)

            dot = dot_output.read_text(encoding="utf-8")
            drawio = drawio_output.read_text(encoding="utf-8")
            self.assertIn("subgraph cluster_site_site_1", dot)
            self.assertIn('label="site-1"', dot)
            self.assertLess(dot.index('label="wan"'), dot.index('label="site-1"'))
            self.assertLess(dot.index('label="bgw"'), dot.index('label="spine"'))
            self.assertIn("site-1", drawio)
            self.assertIn("site-2", drawio)
            self.assertLess(drawio.index("wan"), drawio.index("site-1"))
            self.assertLess(drawio.index('value="bgw"'), drawio.index('value="spine"'))
            self.assertLess(drawio.index('value="rs"'), drawio.index('value="spine"'))
            self.assertIn('value="bgw"', drawio)
            self.assertIn('value="rs"', drawio)
            drawio_root = ET.fromstring(drawio)
            cells = {
                cell.attrib.get("id", ""): cell
                for cell in drawio_root.findall(".//mxCell")
            }
            site1_id = next(
                cell_id
                for cell_id, cell in cells.items()
                if cell.attrib.get("value") == "site-1"
            )
            role_geometry = {}
            for cell in cells.values():
                if cell.attrib.get("parent") != site1_id:
                    continue
                value = cell.attrib.get("value")
                if value not in {"bgw", "rs", "spine"}:
                    continue
                geom = cell.find("mxGeometry")
                self.assertIsNotNone(geom)
                role_geometry[value] = (
                    int(float(geom.attrib.get("x", "0"))),
                    int(float(geom.attrib.get("y", "0"))),
                )
            self.assertEqual(role_geometry["bgw"][1], role_geometry["rs"][1])
            self.assertLess(role_geometry["bgw"][0], role_geometry["rs"][0])
            self.assertLess(role_geometry["bgw"][1], role_geometry["spine"][1])

            bgw_label = next(
                cell
                for cell in cells.values()
                if "site1-bgw01" in cell.attrib.get("value", "")
            )
            bgw_device_id = bgw_label.attrib["parent"]
            wan_nic = next(
                cell
                for cell in cells.values()
                if cell.attrib.get("parent") == bgw_device_id
                and cell.attrib.get("value") == "Ethernet1/3"
            )
            wan_nic_geom = wan_nic.find("mxGeometry")
            self.assertIsNotNone(wan_nic_geom)
            self.assertEqual(int(float(wan_nic_geom.attrib.get("y", "0"))), 0)


if __name__ == "__main__":
    unittest.main()
