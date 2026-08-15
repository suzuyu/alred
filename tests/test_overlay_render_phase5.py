from datetime import datetime
from pathlib import Path

import pytest
import json
import yaml

from alred.capability import (
    evaluate_capability,
    load_capability_registry,
    required_overlay_capabilities,
)
from alred.cli import build_parser, cmd_overlay_change_plan
from alred.health.overlay import parse_overlay_running_config
from alred.overlay_render import (
    FORWARD_TEMPLATE,
    ROLLBACK_TEMPLATE,
    OverlayRenderError,
    normalize_nxos_model,
    render_changeset,
    resolve_changeset,
    write_rendered_configs,
)
from alred.operation import (
    OperationLock,
    create_operation_workspace,
    transition_phase,
)


JST_NOW = datetime.fromisoformat("2026-08-01T12:00:00+09:00")

FABRIC_CONFIG = """\
feature nv overlay
interface nve1
  no shutdown
  global ingress-replication protocol bgp
router bgp 65000
route-map IPv4_REDISTRIBUTE_ALL permit 10
route-map IPv6_REDISTRIBUTE_ALL permit 10
"""


def test_nxos_model_normalization_accepts_show_version_spelling():
    assert normalize_nxos_model("Nexus9000 C9300v") == "N9K-C9300V"
    assert normalize_nxos_model("N9K-C9336C-FX2") == "N9K-C9336C-FX2"


def _changeset(source="declared"):
    return {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {
            "change_id": "CHG-1",
            "source": source,
            "generated_at": JST_NOW.isoformat(),
        },
        "spec": {
            "device_groups": {
                "server-leafs": {"devices": ["leaf01", "leaf02"]}
            },
            "l2vnis": [
                {
                    "vni": 10010,
                    "default_vlan": 10,
                    "vlan_name": "TENANT-A-WEB",
                    "vrf": "TENANT-A",
                    "l3vni": 50001,
                    "svi": {
                        "ipv4_addresses": ["192.0.2.1/24"],
                        "ipv6_addresses": ["2001:db8:10::1/64"],
                        "gateway_mode": "anycast",
                    },
                    "targets": {"groups": {"server-leafs": {}}},
                }
            ],
            "l3vnis": [
                {
                    "vni": 50001,
                    "vrf": "TENANT-A",
                    "targets": {"groups": {"server-leafs": {}}},
                }
            ],
        },
    }


def _snapshot(configs):
    return {
        "schema_version": 1,
        "change_id": "CHG-1",
        "collection_id": "before-001",
        "phase": "before",
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            host: {
                "common": {
                    "system": {
                        "platform": "nxos",
                        "model": "N9K-C9300v",
                        "version": "10.5(4)",
                    }
                },
                "profiles": {
                    "nxos-overlay": {
                        "config": parse_overlay_running_config(config)
                    }
                },
                "sources": {},
            }
            for host, config in configs.items()
        },
    }


def _snapshot_for_model(configs, model, version="10.4(5)M"):
    snapshot = _snapshot(configs)
    for host in snapshot["hosts"].values():
        host["common"]["system"].update(
            {"model": model, "version": version}
        )
    return snapshot


def _minimal_changeset():
    document = _changeset()
    document["spec"]["l3vnis"] = []
    l2vni = document["spec"]["l2vnis"][0]
    l2vni.pop("vrf")
    l2vni.pop("l3vni")
    l2vni.pop("svi")
    return document


def _write_completed_before(workspace, snapshot):
    phase_dir = workspace.operation_root / "health/before"
    phase_dir.mkdir(parents=True)
    (phase_dir / "snapshot.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    health = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "before",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["nxos-overlay"],
        "result": "PASS",
        "counts": {
            "pass": 1,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }
    (phase_dir / "health-result.json").write_text(
        json.dumps(health), encoding="utf-8"
    )
    with OperationLock(workspace, "test-before", now=JST_NOW) as lock:
        transition_phase(
            workspace,
            "before",
            "running",
            lock=lock,
            attempt_id="legacy-before",
            now=JST_NOW,
        )
        transition_phase(
            workspace, "before", "completed", lock=lock, now=JST_NOW
        )
    return phase_dir / "snapshot.json"


def test_resolve_changeset_applies_defaults_and_groups():
    resolved = resolve_changeset(_changeset())

    assert set(resolved) == {"leaf01", "leaf02"}
    assert resolved["leaf01"]["l3vnis"][0]["mode"] == "new_l3vni"
    assert resolved["leaf01"]["l3vnis"][0]["address_families"] == {
        "ipv4": {
            "advertise_l2vpn_evpn": True,
            "redistribute_direct_route_map": "IPv4_REDISTRIBUTE_ALL",
            "redistribute_static_route_map": "IPv4_REDISTRIBUTE_ALL",
            "maximum_paths_ibgp": 4,
        },
        "ipv6": {
            "advertise_l2vpn_evpn": True,
            "redistribute_direct_route_map": "IPv6_REDISTRIBUTE_ALL",
            "redistribute_static_route_map": "IPv6_REDISTRIBUTE_ALL",
            "maximum_paths_ibgp": 4,
        },
    }
    svi = resolved["leaf01"]["l2vnis"][0]["svi"]
    assert svi["mtu"] == 9216
    assert svi["ipv6_link_local"] == "fe80::1"
    assert svi["ipv6_nd_suppress_ra"] is True


def test_renderer_generates_forward_and_scoped_new_vrf_rollback():
    rendered = render_changeset(
        _changeset(),
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )

    leaf = rendered["leaf01"]
    assert "vni 50001 l3" in leaf.forward_config
    assert "mtu 9216" in leaf.forward_config
    assert "ipv6 link-local fe80::1" in leaf.forward_config
    assert "ipv6 nd suppress-ra" in leaf.forward_config
    assert "global ingress-replication protocol bgp" not in leaf.forward_config
    assert "router bgp 65000" in leaf.forward_config
    assert "redistribute static route-map IPv6_REDISTRIBUTE_ALL" in leaf.forward_config
    assert "maximum-paths ibgp 4" in leaf.forward_config
    assert "router bgp 65000\n  no vrf TENANT-A" in leaf.rollback_config
    assert "no vrf context TENANT-A" in leaf.rollback_config
    assert "no redistribute direct" not in leaf.rollback_config
    assert leaf.forward_sha256.startswith("sha256:")
    assert leaf.model_sha256.startswith("sha256:")
    assert FORWARD_TEMPLATE == "nxos_overlay_forward_config.j2"
    assert ROLLBACK_TEMPLATE == "nxos_overlay_rollback_config.j2"


@pytest.mark.parametrize(
    "manifest_name",
    [
        "n9k-c9336c-fx2.yaml",
        "n9k-c93180yc-fx3.yaml",
        "n9k-c9348gc-fx3.yaml",
        "n9k-c9364c-h1.yaml",
    ],
)
def test_hardware_document_review_goldens_remain_plan_only(manifest_name):
    fixture_root = (
        Path(__file__).parent
        / "fixtures/nxos/hardware_document_review"
    )
    manifest = yaml.safe_load(
        (fixture_root / "models" / manifest_name).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["source_type"] == "synthetic_document_review"
    assert manifest["review_status"] == "DOCUMENT_REVIEWED"
    assert manifest["apply_allowed"] is False

    scenarios = {
        "minimal": _minimal_changeset(),
        "dual_stack": _changeset(),
    }
    for scenario_name, document in scenarios.items():
        result = render_changeset(
            document,
            _snapshot_for_model(
                {"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG},
                manifest["model"],
                manifest["release"],
            ),
        )["leaf01"]
        expected = manifest["scenarios"][scenario_name]
        forward_path = (
            fixture_root / "models" / expected["forward"]
        ).resolve()
        rollback_path = (
            fixture_root / "models" / expected["rollback"]
        ).resolve()

        assert result.forward_config == forward_path.read_text(
            encoding="utf-8"
        )
        assert result.rollback_config == rollback_path.read_text(
            encoding="utf-8"
        )
        assert result.forward_sha256 == expected["forward_sha256"]
        assert result.rollback_sha256 == expected["rollback_sha256"]
        assert "interface Ethernet" not in result.forward_config
        assert "containerlab" not in result.forward_config.lower()

        capability = evaluate_capability(
            load_capability_registry(),
            _snapshot_for_model(
                {"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG},
                manifest["model"],
                manifest["release"],
            ),
            ["leaf01", "leaf02"],
            required_overlay_capabilities(document),
        )
        assert capability["level"] == "PLAN_ONLY"
        assert all(
            device["evidence"] is None
            for device in capability["devices"].values()
        )


def test_renderer_can_omit_ipv6_nd_suppress_ra():
    document = _changeset()
    document["spec"]["l2vnis"][0]["svi"][
        "ipv6_nd_suppress_ra"
    ] = False

    rendered = render_changeset(
        document,
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )

    assert "ipv6 address 2001:db8:10::1/64" in rendered["leaf01"].forward_config
    assert "ipv6 nd suppress-ra" not in rendered["leaf01"].forward_config

    configured = {
        host: FABRIC_CONFIG + result.forward_config
        for host, result in rendered.items()
    }
    repeated = render_changeset(document, _snapshot(configured))
    assert repeated["leaf01"].forward_config == ""


def test_renderer_rejects_ipv6_nd_option_on_ipv4_only_svi():
    document = _changeset()
    svi = document["spec"]["l2vnis"][0]["svi"]
    svi.pop("ipv6_addresses")
    svi["ipv6_nd_suppress_ra"] = False

    with pytest.raises(OverlayRenderError, match="IPv6-specific options"):
        resolve_changeset(document)


def test_renderer_rejects_invalid_or_wrong_family_svi_addresses():
    invalid = _changeset()
    invalid["spec"]["l2vnis"][0]["svi"]["ipv4_addresses"] = [
        "not-an-address"
    ]
    with pytest.raises(OverlayRenderError, match="invalid ipv4_addresses"):
        resolve_changeset(invalid)

    wrong_family = _changeset()
    wrong_family["spec"]["l2vnis"][0]["svi"]["ipv4_addresses"] = [
        "2001:db8::1/64"
    ]
    with pytest.raises(OverlayRenderError, match="wrong address family"):
        resolve_changeset(wrong_family)


def test_renderer_rejects_missing_fabric_prerequisite_and_discovered_input():
    with pytest.raises(OverlayRenderError, match="global ingress"):
        render_changeset(
            _changeset(),
            _snapshot(
                {
                    "leaf01": FABRIC_CONFIG.replace(
                        "  global ingress-replication protocol bgp\n", ""
                    ),
                    "leaf02": FABRIC_CONFIG,
                }
            ),
        )

    with pytest.raises(OverlayRenderError, match="promoted"):
        resolve_changeset(_changeset(source="discovered"))


def test_renderer_is_noop_when_generated_resources_already_exist():
    initial = render_changeset(
        _changeset(),
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )
    configured = {
        host: FABRIC_CONFIG + result.forward_config
        for host, result in initial.items()
    }

    repeated = render_changeset(_changeset(), _snapshot(configured))

    assert repeated["leaf01"].forward_config == ""
    assert repeated["leaf01"].rollback_config == ""
    assert all(
        action["action"] == "preserve"
        for action in repeated["leaf01"].actions
    )


def test_render_outputs_are_atomically_written_with_manifest(tmp_path):
    rendered = render_changeset(
        _changeset(),
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )

    manifest = write_rendered_configs(tmp_path, "CHG-1", rendered)

    assert (tmp_path / "generated-config" / "leaf01.cfg").is_file()
    assert (tmp_path / "rollback-config" / "leaf01.cfg").is_file()
    assert (tmp_path / "plan" / "render-manifest.json").is_file()
    assert manifest["templates"] == {
        "forward": "alred/j2/nxos_overlay_forward_config.j2",
        "rollback": "alred/j2/nxos_overlay_rollback_config.j2",
    }


def test_traditional_l3vni_renders_forwarding_svi_and_scoped_rollback():
    document = _changeset()
    document["spec"]["l2vnis"] = []
    document["spec"]["l3vnis"][0].update(
        {
            "mode": "traditional_vlan_svi",
            "default_vlan": 3001,
            "svi": {},
            "address_families": {"ipv4": {}},
        }
    )

    leaf = render_changeset(
        document,
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )["leaf01"]

    assert "vlan 3001\n  vn-segment 50001" in leaf.forward_config
    assert "interface Vlan3001" in leaf.forward_config
    assert "mtu 9216" in leaf.forward_config
    assert "ip forward" in leaf.forward_config
    assert "no interface Vlan3001" in leaf.rollback_config
    assert "no vlan 3001" in leaf.rollback_config


def test_existing_bgp_vrf_rollback_removes_only_owned_lines():
    existing = FABRIC_CONFIG + """\
vrf context TENANT-A
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
router bgp 65000
  vrf TENANT-A
    address-family ipv4 unicast
      advertise l2vpn evpn
"""
    document = _changeset()
    document["spec"]["l2vnis"][0]["svi"].pop("ipv6_addresses")
    document["spec"]["l3vnis"][0]["address_families"] = {"ipv4": {}}

    leaf = render_changeset(
        document,
        _snapshot({"leaf01": existing, "leaf02": existing}),
    )["leaf01"]

    assert "router bgp 65000\n  no vrf TENANT-A" not in leaf.rollback_config
    assert "no advertise l2vpn evpn" not in leaf.rollback_config
    assert (
        "no redistribute static route-map IPv4_REDISTRIBUTE_ALL"
        in leaf.rollback_config
    )
    assert (
        "no redistribute direct route-map IPv4_REDISTRIBUTE_ALL"
        in leaf.rollback_config
    )
    assert "no maximum-paths ibgp 4" in leaf.rollback_config


def test_overlay_change_plan_writes_plan_only_artifacts(tmp_path, capsys):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    before_path = _write_completed_before(
        workspace,
        _snapshot({"leaf01": FABRIC_CONFIG, "leaf02": FABRIC_CONFIG}),
    )
    before_path.chmod(0o600)
    change_set_path = workspace.operation_root / "desired.yaml"
    change_set_path.write_text(
        yaml.safe_dump(_changeset(), sort_keys=False),
        encoding="utf-8",
    )
    change_set_path.chmod(0o600)
    args = build_parser().parse_args(
        [
            "overlay-change",
            "plan",
            "--change-set",
            str(change_set_path),
            "--before",
            str(before_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_overlay_change_plan(args)

    execution = json.loads(
        (
            workspace.operation_root / "plan" / "execution-plan.json"
        ).read_text(encoding="utf-8")
    )
    rollback = json.loads(
        (
            workspace.operation_root / "plan" / "rollback-plan.json"
        ).read_text(encoding="utf-8")
    )
    assert execution["capability_level"] == "PLAN_ONLY"
    assert execution["devices"]["leaf01"]["status"] == "PLANNED"
    assert rollback["policy"] == "manual"
    output = capsys.readouterr().out
    assert "Apply            : BLOCKED" in output
    assert (
        f"config: {workspace.operation_root / 'generated-config/leaf01.cfg'}"
        in output
    )
