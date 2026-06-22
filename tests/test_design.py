from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from alred.cli import build_parser
from alred.design import normalize_and_validate_cables
from alred.parsing import normalize_interface_name


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


class InitClabIntegrationTests(unittest.TestCase):
    def test_generates_all_nodes_and_reports_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hosts = root / "hosts.txt"
            cables = root / "clab_cables.csv"
            env = root / "clab_merge.yaml"
            output = root / "topology.clab.yaml"
            normalized = root / "links_design_normalized.csv"
            report = root / "validation.md"

            hosts.write_text(
                "10.0.0.81 leaf01 # nxos\n"
                "10.0.0.90 server01 # linux\n"
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

            parser = build_parser()
            args = parser.parse_args([
                "init-clab",
                "--hosts", str(hosts),
                "--cables", str(cables),
                "--clab-env", str(env),
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


if __name__ == "__main__":
    unittest.main()
