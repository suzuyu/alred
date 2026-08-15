from __future__ import annotations

import pytest
import yaml

from alred.cli import build_parser
from alred.lab_transform import (
    LabTransformBootstrapConflictError,
    LabTransformCardinalityError,
    UnsupportedLabPlatformError,
    transform_lab_config,
    transform_nxos_lab_config,
    scan_nxos_lab_config,
)
from alred.schema import validate_document


def _resolver(values: dict[str, str]):
    return lambda reference: values[reference]


def test_default_policy_removes_production_endpoints_and_preserves_bootstrap() -> None:
    source = """hostname leaf01
username prod-admin password 5 SECRET role network-admin
ntp server 192.0.2.10 prefer use-vrf management
logging server 192.0.2.20
snmp-server community SECRET group network-operator
aaa group server tacacs+ PROD
  server 192.0.2.30
line vty
  access-class PROD in
interface Ethernet1/1
  description keep-me
"""
    spec = {
        "services": {
            "ntp": {"action": "remove"},
            "logging": {"action": "remove"},
            "dns": {"action": "remove"},
            "aaa": {"action": "remove"},
            "snmp": {"action": "remove"},
        },
        "source_local_users": {"action": "remove"},
        "access_control": {"management_access_class": {"action": "remove"}},
        "lab_users": {"users": []},
        "bootstrap_user": {"action": "preserve"},
    }

    result = transform_nxos_lab_config(source, spec)

    assert "prod-admin" not in result.text
    assert "ntp server" not in result.text
    assert "logging server" not in result.text
    assert "snmp-server" not in result.text
    assert "aaa group" not in result.text
    assert "access-class" not in result.text
    assert "description keep-me" in result.text
    assert result.warnings[0]["id"] == "BOOTSTRAP_CREDENTIAL_PRESERVED"


def test_masked_ntp_address_uses_positional_safe_option_inheritance() -> None:
    source = """ntp server <masked:address> prefer use-vrf management
ntp server <masked:address> use-vrf management
"""
    spec = {
        "services": {
            "ntp": {
                "action": "replace",
                "servers": [{"address": "172.20.20.10"}],
            }
        },
        "lab_users": {"users": []},
        "bootstrap_user": {"action": "preserve"},
    }

    result = transform_nxos_lab_config(source, spec)

    assert result.text == "ntp server 172.20.20.10 prefer use-vrf management\n"
    assert result.stats["generated_ntp"] == 1


def test_ntp_replacement_more_than_source_fails() -> None:
    spec = {
        "services": {
            "ntp": {
                "action": "replace",
                "servers": ["172.20.20.10", "172.20.20.11"],
            }
        },
        "lab_users": {"users": []},
        "bootstrap_user": {"action": "preserve"},
    }

    with pytest.raises(LabTransformCardinalityError):
        transform_nxos_lab_config("ntp server 192.0.2.10\n", spec)


def test_multiple_lab_users_map_common_privileges_to_nxos_roles() -> None:
    spec = {
        "services": {"ntp": {"action": "remove"}},
        "source_local_users": {"action": "remove"},
        "lab_users": {
            "users": [
                {
                    "username": "lab-admin",
                    "privilege": "admin",
                    "primary": True,
                    "authentication": {"password_ref": "LAB_ADMIN_PASSWORD"},
                },
                {
                    "username": "lab-view",
                    "privilege": "read-only",
                    "authentication": {"password_ref": "LAB_VIEW_PASSWORD"},
                },
            ]
        },
        "bootstrap_user": {"action": "preserve"},
    }

    result = transform_nxos_lab_config(
        "username production password 5 SECRET role network-admin\n",
        spec,
        credential_resolver=_resolver({
            "LAB_ADMIN_PASSWORD": "lab-admin-secret",
            "LAB_VIEW_PASSWORD": "lab-view-secret",
        }),
    )

    assert "username production" not in result.text
    assert "username lab-admin password 0 lab-admin-secret role network-admin" in result.text
    assert "username lab-view password 0 lab-view-secret role network-operator" in result.text
    assert result.primary_username == "lab-admin"


def test_preserved_bootstrap_admin_conflicts_with_lab_user_admin() -> None:
    spec = {
        "lab_users": {
            "users": [{
                "username": "admin",
                "privilege": "admin",
                "primary": True,
                "authentication": {"password_ref": "LAB_ADMIN_PASSWORD"},
            }]
        },
        "bootstrap_user": {"action": "preserve"},
    }

    with pytest.raises(LabTransformBootstrapConflictError):
        transform_nxos_lab_config(
            "hostname leaf01\n",
            spec,
            credential_resolver=_resolver({"LAB_ADMIN_PASSWORD": "new-secret"}),
        )


def test_bootstrap_credential_replacement_is_explicit_warning() -> None:
    spec = {
        "lab_users": {"users": []},
        "bootstrap_user": {
            "action": "replace-credential",
            "authentication": {"password_ref": "LAB_ADMIN_PASSWORD"},
        },
    }

    result = transform_nxos_lab_config(
        "hostname leaf01\n",
        spec,
        credential_resolver=_resolver({"LAB_ADMIN_PASSWORD": "new-secret"}),
    )

    assert "username admin password 0 new-secret role network-admin" in result.text
    assert result.warnings[0]["id"] == "BOOTSTRAP_CREDENTIAL_REPLACEMENT"


def test_service_and_management_access_replacements_are_complete_sets() -> None:
    source = """logging server 192.0.2.20
ip name-server 192.0.2.53
tacacs server PROD
  address ipv4 192.0.2.30
  key 7 PRODKEY
snmp-server community PROD group network-admin
ip access-list PROD-MGMT
  10 permit ip 192.0.2.0/24 any
line vty
  access-class PROD-MGMT in
"""
    spec = {
        "services": {
            "ntp": {"action": "remove"},
            "logging": {
                "action": "replace",
                "servers": [{"address": "172.20.20.20", "use_vrf": "management"}],
            },
            "dns": {
                "action": "replace",
                "name_servers": ["172.20.20.53"],
                "lookup_vrf": "management",
            },
            "aaa": {
                "action": "replace",
                "servers": [{
                    "protocol": "tacacs",
                    "name": "LAB-TACACS-1",
                    "address": "172.20.20.30",
                    "credential_ref": "LAB_TACACS_KEY",
                }],
            },
            "snmp": {
                "action": "replace",
                "communities": [{
                    "credential_ref": "LAB_SNMP_COMMUNITY",
                    "group": "network-operator",
                }],
            },
        },
        "access_control": {
            "management_access_class": {
                "action": "replace",
                "name": "LAB-MGMT",
                "rules": [{"sequence": 10, "action": "permit", "source": "172.20.20.0/24"}],
            }
        },
        "lab_users": {"users": []},
        "bootstrap_user": {"action": "preserve"},
    }

    result = transform_nxos_lab_config(
        source,
        spec,
        credential_resolver=_resolver({
            "LAB_TACACS_KEY": "lab-tacacs-key",
            "LAB_SNMP_COMMUNITY": "lab-community",
        }),
    )

    assert "192.0.2." not in result.text
    assert "logging server 172.20.20.20 use-vrf management" in result.text
    assert "ip name-server 172.20.20.53" in result.text
    assert "tacacs-server host 172.20.20.30 key 0 lab-tacacs-key" in result.text
    assert "snmp-server community lab-community group network-operator" in result.text
    assert "ip access-list LAB-MGMT" in result.text
    assert "10 permit ip 172.20.20.0/24 any" in result.text
    assert "access-class LAB-MGMT in" in result.text


def test_clab_transform_cli_publishes_configs_and_valid_manifest(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAB_ADMIN_PASSWORD", "lab-secret")
    (tmp_path / "raw" / "config").mkdir(parents=True)
    (tmp_path / "hosts.yaml").write_text(
        yaml.safe_dump({
            "all": {
                "hosts": {
                    "leaf01": {"ansible_host": "192.0.2.10", "device_type": "nxos"}
                }
            }
        }),
        encoding="utf-8",
    )
    (tmp_path / "raw" / "config" / "leaf01_run.txt").write_text(
        """hostname leaf01
username production password 5 SECRET role network-admin
ntp server 192.0.2.20 prefer use-vrf management
""",
        encoding="utf-8",
    )
    parameters = {
        "api_version": "alred/v1",
        "kind": "LabTransformParameters",
        "metadata": {"name": "test"},
        "spec": {
            "services": {
                "ntp": {
                    "action": "replace",
                    "servers": [{"address": "172.20.20.10"}],
                }
            },
            "lab_users": {
                "users": [{
                    "username": "lab-admin",
                    "privilege": "admin",
                    "primary": True,
                    "authentication": {"password_ref": "LAB_ADMIN_PASSWORD"},
                }]
            },
            "bootstrap_user": {"action": "preserve"},
        },
    }
    (tmp_path / "lab-parameters.yaml").write_text(
        yaml.safe_dump(parameters, sort_keys=False), encoding="utf-8"
    )
    args = build_parser().parse_args([
        "clab-transform-config",
        "--hosts", "hosts.yaml",
        "--input", "raw",
        "--lab-parameters", "lab-parameters.yaml",
        "--output-hosts", "hosts.lab.yaml",
        "--output-dir", "raw/labconfig",
        "--log-file", "logs/transform.log",
    ])

    args.func(args)

    config = (tmp_path / "raw" / "labconfig" / "leaf01_run.txt").read_text()
    assert "username production" not in config
    assert "username lab-admin password 0 lab-secret role network-admin" in config
    assert "ntp server 172.20.20.10 prefer use-vrf management" in config
    manifest = yaml.safe_load(
        (tmp_path / "raw" / "lab-transform-manifest.yaml").read_text()
    )
    validate_document(manifest, kind="LabTransformManifest")
    assert manifest["spec"]["devices"][0]["output_path"] == "labconfig/leaf01_run.txt"


def test_platform_adapter_registry_fails_closed_for_unsupported_platform() -> None:
    with pytest.raises(UnsupportedLabPlatformError):
        transform_lab_config("hostname r1\n", {}, platform="iosxe")


def test_lab_risk_scan_blocks_active_mask_and_classifies_connectivity_changes() -> None:
    findings = scan_nxos_lab_config(
        "hostname leaf01\nusername lab-admin password 0 <masked:secret> role network-admin\n"
    )

    assert any(item["id"] == "LAB_MASK_PLACEHOLDER_ACTIVE" and item["level"] == "BLOCK" for item in findings)
    assert any(item["id"] == "LAB_LOCAL_USER_CHANGE" and item["level"] == "WARN" for item in findings)


def test_lab_risk_scan_blocks_orphan_username_passphrase_policy() -> None:
    findings = scan_nxos_lab_config(
        "hostname leaf01\n"
        "username cisco passphrase lifetime 99999 warntime 14 gracetime 3\n"
    )

    assert any(
        item["id"] == "LAB_ORPHAN_USERNAME_PASSPHRASE"
        and item["level"] == "BLOCK"
        for item in findings
    )


def test_default_policy_removes_username_passphrase_with_source_user() -> None:
    source = (
        "username cisco password 5 SECRET role network-admin\n"
        "username cisco passphrase lifetime 99999 warntime 14 gracetime 3\n"
    )

    result = transform_nxos_lab_config(source, {})

    assert "username cisco" not in result.text
    assert not any(
        item["id"] == "LAB_ORPHAN_USERNAME_PASSPHRASE"
        for item in result.risk_findings
    )


def test_lab_risk_scan_requires_management_address_in_fixed_lab_subnet() -> None:
    config = "interface mgmt0\n  ip address 192.0.2.10/24\n"

    missing = scan_nxos_lab_config(config, require_management_mapping=True)
    outside = scan_nxos_lab_config(
        config,
        allowed_management_subnet="172.20.20.0/24",
        require_management_mapping=True,
    )

    assert any(item["id"] == "LAB_MANAGEMENT_SUBNET_UNVERIFIED" for item in missing)
    assert any(item["id"] == "LAB_MANAGEMENT_ADDRESS_OUTSIDE_SUBNET" for item in outside)
