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
from alred.parsing import load_node_map_csv, normalize_interface_name
from alred.topology import detect_node_site
from alred.transform import transform_inventory_mgmt_subnet, transform_run_config_text


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


class TransformRunConfigTextTests(unittest.TestCase):
    def test_node_map_transforms_hostname_mgmt_and_vpc_keepalive(self) -> None:
        source = """hostname prd-leaf01
vdc prd-leaf01 id 1
vrf context management
  ip route 0.0.0.0/0 192.0.2.254
vpc domain 10
  peer-keepalive destination 192.0.2.12 source 192.0.2.11 vrf management
interface mgmt0
  ip address 192.0.2.11/24
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            hostname_map={"prd-leaf01": "lab-leaf01"},
            management_address_map={
                "192.0.2.11": "172.20.20.11",
                "192.0.2.12": "172.20.20.12",
            },
        )

        self.assertEqual(
            transformed,
            """hostname lab-leaf01
vdc lab-leaf01 id 1
vrf context management
  ip route 0.0.0.0/0 192.0.2.254
vpc domain 10
  peer-keepalive destination 172.20.20.12 source 172.20.20.11 vrf management
interface mgmt0
  ip address 172.20.20.11/24
""",
        )
        self.assertEqual(stats["renamed_hostname_lines"], 2)

    def test_node_map_transforms_inventory_key_and_management_ip(self) -> None:
        inventory = {
            "all": {
                "hosts": {
                    "prd-leaf01": {
                        "ansible_host": "192.0.2.11",
                        "device_type": "nxos",
                    }
                }
            }
        }
        rows = [{
            "source_hostname": "prd-leaf01",
            "source_mgmt_ip": "192.0.2.11",
            "target_hostname": "lab-leaf01",
            "target_mgmt_ip": "172.20.20.11",
        }]

        transformed = transform_inventory_mgmt_subnet(inventory, None, rows)

        self.assertEqual(
            transformed["all"]["hosts"],
            {
                "lab-leaf01": {
                    "ansible_host": "172.20.20.11",
                    "device_type": "nxos",
                }
            },
        )

    def test_load_node_map_accepts_source_target_and_prd_lab_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical.csv"
            canonical.write_text(
                "source_hostname,source_mgmt_ip,target_hostname,target_mgmt_ip\n"
                "prd01,192.0.2.1,lab01,172.20.20.1\n",
                encoding="utf-8",
            )
            legacy = root / "legacy.csv"
            legacy.write_text(
                "prd_hostname,prd_mgmt_ip,lab_hostname,lab_mgmt_ip\n"
                "prd02,192.0.2.2,lab02,172.20.20.2\n",
                encoding="utf-8",
            )

            self.assertEqual(load_node_map_csv(str(canonical))[0]["target_hostname"], "lab01")
            self.assertEqual(load_node_map_csv(str(legacy))[0]["target_hostname"], "lab02")

    def test_replaces_existing_username_lines_with_lab_user(self) -> None:
        source = """version 10.4(3)
username admin password 5 old-admin-hash role network-admin
username admin passphrase lifetime 99999 warntime 14 gracetime 3
username cisco password 5 old-cisco-hash role network-admin
username cisco passphrase lifetime 99999 warntime 14 gracetime 3
interface mgmt0
  ip address 192.0.2.10/24
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            lab_username="admin",
            lab_password="lab-secret",
        )

        self.assertEqual(
            transformed,
            """version 10.4(3)
username admin password 0 lab-secret role network-admin
username cisco password 5 old-cisco-hash role network-admin
username cisco passphrase lifetime 99999 warntime 14 gracetime 3
interface mgmt0
  ip address 192.0.2.10/24
""",
        )
        self.assertEqual(stats["removed_username_lines"], 2)
        self.assertEqual(stats["inserted_lab_username"], 1)

    def test_replaces_only_matching_lab_user(self) -> None:
        source = """username admin password 5 old-admin-hash role network-admin
username cisco password 5 old-cisco-hash role network-admin
username cisco passphrase lifetime 99999 warntime 14 gracetime 3
interface Ethernet1/1
  switchport
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            lab_username="admin",
            lab_password="lab-secret",
        )

        self.assertEqual(
            transformed,
            """username admin password 0 lab-secret role network-admin
username cisco password 5 old-cisco-hash role network-admin
username cisco passphrase lifetime 99999 warntime 14 gracetime 3
interface Ethernet1/1
  switchport
""",
        )
        self.assertEqual(stats["removed_username_lines"], 1)

    def test_adds_lab_user_when_matching_user_does_not_exist(self) -> None:
        source = """username cisco password 5 old-cisco-hash role network-admin
interface Ethernet1/1
  switchport
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            lab_username="admin",
            lab_password="lab-secret",
        )

        self.assertEqual(
            transformed,
            """username cisco password 5 old-cisco-hash role network-admin
username admin password 0 lab-secret role network-admin
interface Ethernet1/1
  switchport
""",
        )
        self.assertEqual(stats["removed_username_lines"], 0)
        self.assertEqual(stats["inserted_lab_username"], 1)

    def test_does_not_change_users_without_lab_credentials(self) -> None:
        source = "username cisco password 5 old-hash role network-admin\n"

        transformed, stats = transform_run_config_text(source, None)

        self.assertEqual(transformed, source)
        self.assertEqual(stats["removed_username_lines"], 0)
        self.assertEqual(stats["inserted_lab_username"], 0)

    def test_delete_username_removes_all_users_and_snmp_users(self) -> None:
        source = """no password strength-check
username admin password 5 old-admin-hash role network-admin
username cisco password 5 old-cisco-hash role network-admin
username cisco passphrase lifetime 99999 warntime 14 gracetime 3
snmp-server user admin network-admin auth md5 admin-hash localizedV2key
snmp-server user cisco network-admin auth md5 cisco-hash localizedV2key
snmp-server community public group network-operator
interface mgmt0
  ip address 192.0.2.10/24
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            lab_username="ignored",
            lab_password="ignored",
            delete_username=True,
        )

        self.assertEqual(
            transformed,
            """no password strength-check
snmp-server community public group network-operator
interface mgmt0
  ip address 192.0.2.10/24
""",
        )
        self.assertEqual(stats["removed_username_lines"], 3)
        self.assertEqual(stats["removed_snmp_user_lines"], 2)
        self.assertEqual(stats["inserted_lab_username"], 0)

    def test_delete_access_class_only_changes_line_vty_sections(self) -> None:
        source = """interface Ethernet1/1
  description access-class should remain in text
line console
  access-class CONSOLE-ACL in
  exec-timeout 0
line vty
  access-class MGMT-V4 in
  ipv6 access-class MGMT-V6 in
  exec-timeout 0
line vty 0 4
  access-class SECONDARY-V4 in vrf-also
  transport input ssh
"""

        transformed, stats = transform_run_config_text(
            source,
            None,
            delete_access_class=True,
        )

        self.assertEqual(
            transformed,
            """interface Ethernet1/1
  description access-class should remain in text
line console
  access-class CONSOLE-ACL in
  exec-timeout 0
line vty
  exec-timeout 0
line vty 0 4
  transport input ssh
""",
        )
        self.assertEqual(stats["removed_access_class_lines"], 3)

    def test_rejects_lab_password_with_whitespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain whitespace"):
            transform_run_config_text(
                "interface mgmt0\n",
                None,
                lab_username="admin",
                lab_password="invalid password",
            )


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

    def test_transform_step_receives_credentials(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "clab-set-cmds",
            "--credentials",
            "lab-credentials.yaml",
        ])
        transform_step = next(
            step for step in DEFAULT_CLAB_SET_CMDS
            if step.get("command") == "clab-transform-config"
        )

        step_args = build_clab_set_step_args(transform_step, args, verbose=False)

        self.assertEqual(step_args.credentials, "lab-credentials.yaml")

    def test_transform_step_receives_delete_username(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clab-set-cmds", "--delete-username"])
        transform_step = next(
            step for step in DEFAULT_CLAB_SET_CMDS
            if step.get("command") == "clab-transform-config"
        )

        step_args = build_clab_set_step_args(transform_step, args, verbose=False)

        self.assertTrue(step_args.delete_username)

    def test_transform_step_receives_delete_access_class(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clab-set-cmds", "--delete-access-class"])
        transform_step = next(
            step for step in DEFAULT_CLAB_SET_CMDS
            if step.get("command") == "clab-transform-config"
        )

        step_args = build_clab_set_step_args(transform_step, args, verbose=False)

        self.assertTrue(step_args.delete_access_class)

    def test_node_map_is_forwarded_and_lab_inventory_is_used_downstream(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clab-set-cmds", "--node-map", "clab_node_map.csv"])
        transform_step = next(
            step for step in DEFAULT_CLAB_SET_CMDS
            if step.get("command") == "clab-transform-config"
        )
        generate_step = next(
            step for step in DEFAULT_CLAB_SET_CMDS
            if step.get("command") == "generate-clab"
        )

        transform_args = build_clab_set_step_args(transform_step, args, verbose=False)
        generate_args = build_clab_set_step_args(generate_step, args, verbose=False)

        self.assertEqual(transform_args.node_map, "clab_node_map.csv")
        self.assertEqual(generate_args.node_map, "clab_node_map.csv")
        self.assertEqual(generate_args.hosts, "hosts.lab.yaml")


class TransformConfigIntegrationTests(unittest.TestCase):
    def test_node_map_renames_output_file_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_config = root / "raw" / "config"
            raw_config.mkdir(parents=True)
            hosts = root / "hosts.yaml"
            node_map = root / "clab_node_map.csv"
            clab_env = root / "clab_merge.yaml"
            output_hosts = root / "hosts.lab.yaml"
            output_dir = root / "raw" / "labconfig"
            hosts.write_text(
                yaml.safe_dump({
                    "all": {
                        "hosts": {
                            "prd-leaf01": {
                                "ansible_host": "192.0.2.11",
                                "device_type": "nxos",
                            }
                        }
                    }
                }, sort_keys=False),
                encoding="utf-8",
            )
            node_map.write_text(
                "source_hostname,source_mgmt_ip,target_hostname,target_mgmt_ip\n"
                "prd-leaf01,192.0.2.11,lab-leaf01,172.20.20.11\n",
                encoding="utf-8",
            )
            clab_env.write_text("{}\n", encoding="utf-8")
            (raw_config / "prd-leaf01_run.txt").write_text(
                """hostname prd-leaf01
vdc prd-leaf01 id 1
interface mgmt0
  ip address 192.0.2.11/24
""",
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args([
                "clab-transform-config",
                "--hosts", str(hosts),
                "--clab-env", str(clab_env),
                "--node-map", str(node_map),
                "--delete-username",
                "--input", str(root / "raw"),
                "--output-hosts", str(output_hosts),
                "--output-dir", str(output_dir),
                "--log-file", str(root / "transform.log"),
            ])

            args.func(args)

            generated = output_dir / "lab-leaf01_run.txt"
            self.assertTrue(generated.exists())
            self.assertFalse((output_dir / "prd-leaf01_run.txt").exists())
            self.assertIn("hostname lab-leaf01", generated.read_text(encoding="utf-8"))
            transformed_inventory = yaml.safe_load(output_hosts.read_text(encoding="utf-8"))
            self.assertEqual(
                transformed_inventory["all"]["hosts"]["lab-leaf01"]["ansible_host"],
                "172.20.20.11",
            )


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
