from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest
import yaml

from alred.cli import build_parser
from alred.operation import create_operation_workspace
from alred.support_bundle import (
    SupportBundleError,
    create_support_bundle,
    inspect_support_bundle,
    load_redaction_policy,
    select_operation_files,
    verify_support_bundle_manifest,
)


NOW = datetime.fromisoformat("2026-08-01T14:00:00+09:00")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _operation(tmp_path, *, include_logging=False):
    operations_root = tmp_path / "operations"
    workspace = create_operation_workspace(
        operations_root,
        change_id="CHG-1",
        now=NOW,
    )
    phase = workspace.operation_root / "health" / "before"
    phase.mkdir(parents=True)
    external = tmp_path / "external-raw"
    external.mkdir()
    hosts = {}
    for index, hostname in enumerate(("leaf01", "leaf02"), start=1):
        raw = external / f"{hostname}.log"
        raw.write_text(
            f"### COMMAND: show test\n"
            f"{hostname}# show test\n"
            f"vrf context TENANT-A\n"
            f"peer 192.0.2.{index}\n"
            f"password SuperSecretValue{index}\n",
            encoding="utf-8",
        )
        commands = {
            "show_test": {
                "status": "success",
                "collected_at": NOW.isoformat(),
                "file": str(raw),
                "sha256": _digest(raw),
                "command": "show test",
                "normalized_command": "show test",
                "source": "external_transcript",
                "transport": "ssh",
                "start_line": 1,
                "end_line": 5,
                "confidence": "high",
            }
        }
        if include_logging:
            commands["show_logging"] = {
                **commands["show_test"],
                "command": "show logging",
                "normalized_command": "show logging",
            }
        hosts[hostname] = {"status": "success", "commands": commands}
    manifest = {
        "api_version": "alred/v1",
        "kind": "CollectionManifest",
        "metadata": {
            "collection_id": "before-001",
            "change_id": "CHG-1",
            "phase": "before",
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "timezone": "Asia/Tokyo",
        },
        "spec": {
            "profiles": ["network-baseline-nxos"],
            "hosts": hosts,
        },
    }
    (phase / "collection-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    return operations_root, workspace, external


def _archive_text(path, member_name):
    with tarfile.open(path, "r:gz") as archive:
        member = archive.extractfile(member_name)
        assert member is not None
        return member.read().decode()


def test_bundle_redacts_consistently_and_verifies_checksums(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    output = tmp_path / "bundles"

    paths = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="before",
        output_dir=output,
        created_at=NOW,
        timezone="Asia/Tokyo",
        symptom="before check warning",
    )

    verification = verify_support_bundle_manifest(paths["manifest"])
    inspection = inspect_support_bundle(paths["archive"])
    assert verification["verified"] is True
    assert any(
        member["name"] == "support-bundle/prompt.md"
        for member in inspection["members"]
    )
    text = _archive_text(
        paths["archive"],
        "support-bundle/raw/before/DEVICE-001/show_test.log",
    )
    assert "leaf01" not in text
    assert "192.0.2.1" not in text
    assert "TENANT-A" not in text
    assert "SuperSecretValue1" not in text
    assert "DEVICE-001" in text
    assert "IP-001" in text
    assert "VRF-001" in text
    assert "***REDACTED***" in text


def test_selector_rejects_symlink_and_never_selects_dot_env(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    (workspace.operation_root / ".env").write_text(
        "TOKEN=secret\n", encoding="utf-8"
    )
    selected = select_operation_files(
        workspace.operation_root,
        phase="before",
    )
    assert all(source.name != ".env" for source, _destination in selected)
    link = workspace.operation_root / "health" / "before" / "unsafe.log"
    link.symlink_to(workspace.operation_root / "metadata.yaml")

    with pytest.raises(SupportBundleError, match="symlink"):
        select_operation_files(workspace.operation_root, phase="before")


def test_selector_includes_qualification_execution_evidence(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    evidence = (
        workspace.operation_root
        / "qualification"
        / "save"
        / "execution.json"
    )
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"result":"SUCCESS"}\n', encoding="utf-8")

    selected = select_operation_files(
        workspace.operation_root,
        phase="all",
    )

    destinations = {destination.as_posix() for _source, destination in selected}
    assert (
        "support-bundle/qualification/save/execution.json"
        in destinations
    )


def test_inspect_rejects_archive_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        content = b"unsafe"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    with pytest.raises(SupportBundleError, match="unsafe archive member"):
        inspect_support_bundle(archive_path)


def test_device_filter_and_split_use_pseudonyms_and_part_index(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    outputs = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="before",
        output_dir=tmp_path / "bundles",
        created_at=NOW,
        timezone="Asia/Tokyo",
        split="device",
        devices=["leaf01", "leaf02"],
    )

    index = yaml.safe_load(outputs["index"].read_text(encoding="utf-8"))
    assert index["spec"]["split"] == "device"
    assert [part["part_id"] for part in index["spec"]["parts"]] == [
        "common",
        "DEVICE-001",
        "DEVICE-002",
    ]
    device_one = outputs["archive_DEVICE-001"]
    names = {
        member["name"]
        for member in inspect_support_bundle(device_one)["members"]
    }
    assert "support-bundle/raw/before/DEVICE-001/show_test.log" in names
    assert not any("DEVICE-002" in name for name in names)
    assert "leaf01" not in device_one.name
    verify_support_bundle_manifest(outputs["manifest_DEVICE-001"])


def test_device_filter_rejects_unknown_device(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    with pytest.raises(SupportBundleError, match="unknown requested devices"):
        create_support_bundle(
            workspace.operation_root,
            change_id="CHG-1",
            phase="before",
            output_dir=tmp_path / "bundles",
            created_at=NOW,
            timezone="Asia/Tokyo",
            devices=["missing-leaf"],
        )


def test_single_archive_device_filter_removes_other_host_evidence(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    outputs = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="before",
        output_dir=tmp_path / "bundles",
        created_at=NOW,
        timezone="Asia/Tokyo",
        devices=["leaf01"],
    )
    with tarfile.open(outputs["archive"], "r:gz") as archive:
        combined = b"\n".join(
            archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        ).decode()
    assert "leaf02" not in combined
    assert "192.0.2.2" not in combined
    assert "DEVICE-002" not in combined


def test_phase_split_creates_only_phases_with_evidence(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    outputs = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="all",
        output_dir=tmp_path / "bundles",
        created_at=NOW,
        timezone="Asia/Tokyo",
        split="phase",
    )
    index = yaml.safe_load(outputs["index"].read_text(encoding="utf-8"))
    assert [part["phase"] for part in index["spec"]["parts"]] == ["before"]
    verify_support_bundle_manifest(outputs["manifest_before"])


def test_site_policy_and_include_toggles(tmp_path):
    _operations_root, workspace, _external = _operation(
        tmp_path,
        include_logging=True,
    )
    generated = workspace.operation_root / "generated-config"
    generated.mkdir()
    (generated / "leaf01.cfg").write_text(
        "tenant-key SiteSecret\n", encoding="utf-8"
    )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """\
api_version: alred/v1
kind: SupportBundleRedactionPolicy
metadata:
  name: test
spec:
  mask_keys:
    - password
    - tenant-key
  mask_patterns:
    - id: serial
      pattern: "SERIAL-[0-9]+"
  pseudonymize:
    hostnames: true
    ip_addresses: true
    vrf_names: true
  preserve:
    - vni
    - vlan
    - interface_name
    - command_name
""",
        encoding="utf-8",
    )
    policy = load_redaction_policy(policy_path)
    assert policy.mask_keys == ("password", "tenant-key")

    outputs = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="all",
        output_dir=tmp_path / "bundles",
        created_at=NOW,
        timezone="Asia/Tokyo",
        redaction_profile=policy_path,
        include_generated_config=False,
        include_raw_logging=False,
    )
    names = {
        member["name"]
        for member in inspect_support_bundle(outputs["archive"])["members"]
    }
    assert not any("generated-config" in name for name in names)
    assert not any("show_logging" in name for name in names)


def test_manifest_source_hash_drift_is_rejected(tmp_path):
    _operations_root, workspace, external = _operation(tmp_path)
    (external / "leaf01.log").write_text("changed\n", encoding="utf-8")
    with pytest.raises(SupportBundleError, match="hash mismatch"):
        create_support_bundle(
            workspace.operation_root,
            change_id="CHG-1",
            phase="before",
            output_dir=tmp_path / "bundles",
            created_at=NOW,
            timezone="Asia/Tokyo",
        )


def test_large_bundle_fails_without_silent_omission(tmp_path):
    _operations_root, workspace, external = _operation(tmp_path)
    raw = external / "leaf01.log"
    raw.write_text("leaf01# show test\n" + ("x" * (1024 * 1024 + 64)))
    manifest_path = (
        workspace.operation_root
        / "health"
        / "before"
        / "collection-manifest.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    record = manifest["spec"]["hosts"]["leaf01"]["commands"]["show_test"]
    record["sha256"] = _digest(raw)
    record.pop("start_line")
    record.pop("end_line")
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    with pytest.raises(SupportBundleError, match="BUNDLE_TOO_LARGE"):
        create_support_bundle(
            workspace.operation_root,
            change_id="CHG-1",
            phase="before",
            output_dir=tmp_path / "bundles",
            created_at=NOW,
            timezone="Asia/Tokyo",
            max_size_mib=1,
        )


def test_prompt_instructions_are_not_duplicated(tmp_path):
    _operations_root, workspace, _external = _operation(tmp_path)
    outputs = create_support_bundle(
        workspace.operation_root,
        change_id="CHG-1",
        phase="before",
        output_dir=tmp_path / "bundles",
        created_at=NOW,
        timezone="Asia/Tokyo",
    )
    prompt = outputs["prompt"].read_text(encoding="utf-8")
    assert prompt.count("1. 事実、推測、追加確認事項") == 1
    assert prompt.count("8. 追加取得には") == 1


def test_cli_exposes_phase9_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "support-bundle",
            "create",
            "--change-id",
            "CHG-1",
            "--phase",
            "after",
            "--devices",
            "leaf01,leaf02",
            "--split",
            "device",
            "--redact-profile",
            "policy.yaml",
            "--no-include-generated-config",
            "--no-include-rollback-config",
            "--no-include-raw-logging",
        ]
    )
    assert args.devices == "leaf01,leaf02"
    assert args.include_generated_config is False
    assert args.include_rollback_config is False
    assert args.include_raw_logging is False
