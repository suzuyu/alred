from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import pytest
import yaml

from alred.approval import calculate_approval_artifact_hashes
from alred.cli import build_parser, cmd_overlay_change_plan
from alred.device_groups import (
    DeviceGroupError,
    load_overlay_change_set,
    resolve_device_groups,
    resolve_resource_targets,
    write_overlay_plan_inputs,
)
from alred.health.overlay import parse_overlay_running_config
from alred.operation import (
    OperationLock,
    create_operation_workspace,
    transition_phase,
)
from alred.overlay_render import render_changeset, resolve_changeset
from alred.schema import DocumentValidationError, validate_document


JST_NOW = datetime.fromisoformat("2026-08-02T12:00:00+09:00")
FABRIC_CONFIG = """\
feature nv overlay
interface nve1
  no shutdown
  global ingress-replication protocol bgp
router bgp 65000
route-map IPv4_REDISTRIBUTE_ALL permit 10
route-map IPv6_REDISTRIBUTE_ALL permit 10
"""


def _external_documents(change_id="CHG-1"):
    groups = {
        "api_version": "alred/v1",
        "kind": "OverlayDeviceGroups",
        "metadata": {"name": "fabric-a"},
        "spec": {
            "device_groups": {
                "pair-01": {"devices": ["leaf01", "leaf02"]},
                "pair-02": {"devices": ["leaf03", "leaf04"]},
                "server-leafs": {"groups": ["pair-01"]},
                "storage-leafs": {"groups": ["pair-02"]},
                "all-vtep-leafs": {
                    "groups": ["server-leafs", "storage-leafs"]
                },
            }
        },
    }
    change_set = {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {"change_id": change_id, "source": "declared"},
        "spec": {
            "device_groups_ref": {"path": "./device-groups.yaml"},
            "l2vnis": [
                {
                    "vni": 10020,
                    "default_vlan": 20,
                    "targets": {
                        "groups": {
                            "server-leafs": {},
                            "storage-leafs": {"vlan": 120},
                        }
                    },
                }
            ],
            "l3vnis": [],
        },
    }
    return change_set, groups


def _write_bundle(root: Path, change_id="CHG-1") -> Path:
    root.mkdir(parents=True)
    change_set, groups = _external_documents(change_id)
    (root / "desired-changes.yaml").write_text(
        yaml.safe_dump(change_set, sort_keys=False),
        encoding="utf-8",
    )
    (root / "device-groups.yaml").write_text(
        yaml.safe_dump(groups, sort_keys=False),
        encoding="utf-8",
    )
    return root / "desired-changes.yaml"


def _snapshot(change_id="CHG-1"):
    parsed = parse_overlay_running_config(FABRIC_CONFIG)
    return {
        "schema_version": 1,
        "change_id": change_id,
        "collection_id": f"{change_id}-before-001",
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
                "profiles": {"nxos-overlay": {"config": deepcopy(parsed)}},
                "sources": {},
            }
            for host in ("leaf01", "leaf02", "leaf03", "leaf04")
        },
    }


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


def test_external_group_ref_materializes_nested_groups(tmp_path):
    path = _write_bundle(tmp_path / "bundle")

    loaded = load_overlay_change_set(path)

    assert loaded.source_mode == "external"
    assert loaded.resolution.groups["all-vtep-leafs"]["devices"] == [
        "leaf01",
        "leaf02",
        "leaf03",
        "leaf04",
    ]
    assert loaded.resolution.chains["server-leafs"]["leaf01"] == [
        ["server-leafs", "pair-01"]
    ]
    assert "device_groups_ref" not in loaded.document["spec"]
    assert "device_groups" in loaded.document["spec"]
    resolved = resolve_changeset(loaded.document)
    assert resolved["leaf02"]["l2vnis"][0]["vlan"] == 20
    assert resolved["leaf04"]["l2vnis"][0]["vlan"] == 120


def test_plan_inputs_pin_source_hashes_and_group_chains(tmp_path):
    path = _write_bundle(tmp_path / "bundle")
    loaded = load_overlay_change_set(path)
    operation_root = tmp_path / "operation"
    operation_root.mkdir()

    manifest, resolved = write_overlay_plan_inputs(operation_root, loaded)

    validate_document(manifest, kind="OverlayInputManifest")
    validate_document(resolved, kind="OverlayResolvedTargets")
    assert (operation_root / "inputs/change-set.yaml").is_file()
    assert (operation_root / "inputs/device-groups.yaml").is_file()
    assert (operation_root / "plan/input-manifest.json").is_file()
    assert (operation_root / "plan/resolved-targets.yaml").is_file()
    assert manifest["device_groups"]["mode"] == "external"
    resource = resolved["spec"]["resources"][0]
    assert resource["devices"]["leaf01"]["group_chains"] == [
        ["server-leafs", "pair-01"]
    ]


def test_overlay_change_plan_accepts_external_groups_and_pins_approval_inputs(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=JST_NOW,
    )
    before_path = _write_completed_before(workspace, _snapshot())
    change_set_path = _write_bundle(tmp_path / "bundle")
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

    plan = json.loads(
        (workspace.operation_root / "plan/execution-plan.json").read_text()
    )
    rollback = json.loads(
        (workspace.operation_root / "plan/rollback-plan.json").read_text()
    )
    assert set(plan["artifacts"]["approval_artifacts"]) == {
        "change_set",
        "device_groups",
        "input_manifest",
        "resolved_targets",
        "conflict_report",
    }
    hashes = calculate_approval_artifact_hashes(workspace, plan, rollback)
    assert set(hashes) == {
        "execution_plan",
        "rollback_plan",
        "change_set",
        "device_groups",
        "input_manifest",
        "resolved_targets",
        "conflict_report",
    }
    pinned_groups = workspace.operation_root / "inputs/device-groups.yaml"
    pinned = yaml.safe_load(pinned_groups.read_text())
    pinned["metadata"]["name"] = "modified"
    pinned_groups.write_text(yaml.safe_dump(pinned), encoding="utf-8")
    changed_hashes = calculate_approval_artifact_hashes(
        workspace,
        plan,
        rollback,
    )
    assert changed_hashes["device_groups"] != hashes["device_groups"]
    assert "Input manifest" in capsys.readouterr().out


def test_inline_nested_groups_remain_supported():
    change_set, groups = _external_documents()
    change_set["spec"].pop("device_groups_ref")
    change_set["spec"]["device_groups"] = groups["spec"]["device_groups"]

    validate_document(change_set, kind="OverlayChangeSet")
    resolved = resolve_changeset(change_set)

    assert set(resolved) == {"leaf01", "leaf02", "leaf03", "leaf04"}


def test_group_cycles_unknown_references_and_depth_are_rejected():
    with pytest.raises(DeviceGroupError, match="cycle detected"):
        resolve_device_groups(
            {
                "a": {"groups": ["b"]},
                "b": {"groups": ["a"]},
            }
        )
    with pytest.raises(DeviceGroupError, match="unknown child"):
        resolve_device_groups({"a": {"groups": ["missing"]}})
    definitions = {
        f"g{index}": {"groups": [f"g{index + 1}"]}
        for index in range(16)
    }
    definitions["g16"] = {"devices": ["leaf01"]}
    with pytest.raises(DeviceGroupError, match="exceeds 16 levels"):
        resolve_device_groups(definitions)


def test_external_ref_rejects_absolute_path_and_symlink(tmp_path):
    change_set, groups = _external_documents()
    groups_path = tmp_path / "groups.yaml"
    groups_path.write_text(yaml.safe_dump(groups), encoding="utf-8")
    change_set["spec"]["device_groups_ref"]["path"] = str(groups_path)
    change_set_path = tmp_path / "absolute.yaml"
    change_set_path.write_text(yaml.safe_dump(change_set), encoding="utf-8")
    with pytest.raises(DocumentValidationError):
        load_overlay_change_set(change_set_path)

    change_set["spec"]["device_groups_ref"]["path"] = "linked.yaml"
    change_set_path = tmp_path / "symlink.yaml"
    change_set_path.write_text(yaml.safe_dump(change_set), encoding="utf-8")
    (tmp_path / "linked.yaml").symlink_to(groups_path)
    with pytest.raises(DeviceGroupError, match="symlink"):
        load_overlay_change_set(change_set_path)


def test_conflicting_group_overrides_require_explicit_device_override():
    resolution = resolve_device_groups(
        {
            "a": {"devices": ["leaf01"]},
            "b": {"devices": ["leaf01"]},
        }
    )
    resource = {
        "vni": 10020,
        "targets": {"groups": {"a": {"vlan": 20}, "b": {"vlan": 120}}},
    }
    with pytest.raises(DeviceGroupError, match="conflicting group overrides"):
        resolve_resource_targets(resource, resolution)

    resource["targets"]["devices"] = {"leaf01": {"vlan": 220}}
    targets, evidence = resolve_resource_targets(resource, resolution)
    assert targets["leaf01"] == {"vlan": 220}
    assert evidence["leaf01"]["device_override"] is True


def test_manual_external_and_inline_samples_render_identically():
    root = Path("docs/manual/network-ops/examples/overlay-changeset")
    external = load_overlay_change_set(root / "desired-changes.yaml")
    minimal = load_overlay_change_set(root / "desired-changes.minimal.yaml")
    inline = load_overlay_change_set(root / "desired-changes.inline.yaml")
    change_id = external.document["metadata"]["change_id"]
    config_root = Path(
        "docs/manual/containerlab/examples/single-site-fabric/labconfig"
    )
    hosts = {}
    for path in sorted(config_root.glob("adc-lfsw01*_run.txt")):
        config = parse_overlay_running_config(path.read_text(encoding="utf-8"))
        for vlan, value in list(config["vlans"].items()):
            if value.get("vni") != 10100:
                continue
            config["vlans"].pop(vlan)
            config["svis"].pop(vlan)
        config["nve"]["l2vnis"].pop("10100")
        hosts[path.stem.removesuffix("_run")] = {
            "common": {
                "system": {
                    "platform": "nxos",
                    "model": "N9K-C9300v",
                    "version": "10.5(4)",
                }
            },
            "profiles": {"nxos-overlay": {"config": config}},
            "sources": {},
        }
    snapshot = {
        "schema_version": 1,
        "change_id": change_id,
        "collection_id": f"{change_id}-before-001",
        "phase": "before",
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": hosts,
    }

    external_rendered = render_changeset(external.document, snapshot)
    minimal_rendered = render_changeset(minimal.document, snapshot)
    inline_rendered = render_changeset(inline.document, snapshot)

    expected = {
        host: result.forward_config
        for host, result in external_rendered.items()
    }
    assert expected == {
        host: result.forward_config for host, result in minimal_rendered.items()
    }
    assert expected == {
        host: result.forward_config for host, result in inline_rendered.items()
    }
    for host in ("adc-lfsw0101", "adc-lfsw0103"):
        assert external_rendered[host].forward_config == (
            root / f"{host}.cfg"
        ).read_text(encoding="utf-8")
        assert external_rendered[host].rollback_config == (
            root / f"{host}-rollback.cfg"
        ).read_text(encoding="utf-8")
