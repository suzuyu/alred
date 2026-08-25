from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import yaml
import pytest
import alred.portable_evidence as portable_evidence
import alred.secret_scan as secret_scan

from alred.cli import (
    build_parser,
    cmd_evidence_package_create,
    cmd_evidence_package_import,
    cmd_evidence_package_prune,
    cmd_evidence_package_prune_imports,
    get_evidence_import_keep_latest,
    get_evidence_package_keep_latest,
    main,
)
from alred.portable_evidence import (
    EvidencePackageError,
    _is_secret_bearing_line,
    canonical_confirmed_links_sha256,
    canonical_links_sha256,
    create_evidence_package,
    import_evidence_package,
    inspect_evidence_package,
    prune_imported_evidence,
    prune_evidence_packages,
    resolve_imported_digital_twin,
    resolve_evidence_collection_source,
    verify_evidence_package,
)
from alred.operation import OperationPathError, create_operation_workspace
from alred.parsing import read_links_csv, write_links_csv
from alred.schema import source_sha256, validate_document
from alred.secret_scan import (
    CATALOG_SHA256,
    CATALOG_VERSION,
    build_scan_result,
    sanitize_text,
    scan_text,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_confirmed_link_semantic_hash_ignores_observation_direction() -> None:
    forward = {
        "src_node": "leaf01",
        "src_if": "Ethernet1/1",
        "dst_node": "spine01",
        "dst_if": "Ethernet1/1",
        "protocol": "lldp",
        "confidence": "high",
        "evidence": "bidirectional-lldp",
        "remote_mgmt_ip": "192.0.2.10",
        "rule_name": "",
        "warning": "",
    }
    reverse = {
        **forward,
        "src_node": "spine01",
        "src_if": "Ethernet1/1",
        "dst_node": "leaf01",
        "dst_if": "Ethernet1/1",
        "remote_mgmt_ip": "192.0.2.20",
    }

    assert canonical_confirmed_links_sha256([forward]) == (
        canonical_confirmed_links_sha256([reverse])
    )
    assert canonical_confirmed_links_sha256([forward]) != (
        canonical_confirmed_links_sha256([{**reverse, "confidence": "medium"}])
    )


@pytest.mark.parametrize(
    "line",
    [
        "username admin password 5 SyntheticHash role network-admin",
        "username admin secret 5 SyntheticHash role network-admin",
        "username admin passphrase lifetime 99999 warntime 14 gracetime 3",
        "enable password SyntheticPassword",
        "enable secret 5 SyntheticHash",
        "snmp-server community SyntheticCommunity group network-operator",
        "snmp-server user monitor network-operator auth sha SyntheticAuth",
        "snmp-server user monitor network-operator priv aes-128 SyntheticPriv",
        "radius-server host 192.0.2.10 key 7 SyntheticRadiusKey",
        "tacacs-server key 7 SyntheticTacacsKey",
        "neighbor 192.0.2.1 password 3 SyntheticHash",
        "password: SyntheticPassword",
        "api-key=SyntheticApiKey",
        "apikey=SyntheticApiKey",
        "client_secret=SyntheticToken",
        "clientsecret=SyntheticToken",
        "community: SyntheticCommunity",
    ],
)
def test_secret_line_patterns_match_only_defined_value_positions(line: str) -> None:
    assert _is_secret_bearing_line(line) is True


def test_secret_scan_catalog_lists_every_implemented_nxos_syntax() -> None:
    catalog = (
        Path(__file__).parents[1]
        / "docs/design/common/SECRET_SCAN_RULE_CATALOG.md"
    ).read_text(encoding="utf-8")
    required_syntax = (
        "username <name> <remainder...> password <remainder...>",
        "username <name> <remainder...> secret <remainder...>",
        "username <name> <remainder...> passphrase <remainder...>",
        "enable password <value> <remainder...>",
        "enable secret <value> <remainder...>",
        "snmp-server community <value> <remainder...>",
        "snmp-server user <remainder...> auth <token> <remainder...>",
        "snmp-server user <remainder...> priv <token> <remainder...>",
        "radius-server <remainder...> key <value> <remainder...>",
        "tacacs-server <remainder...> key <value> <remainder...>",
        "ldap-server host <host> rootDN <dn> password [7] <value> <remainder...>",
        "neighbor <peer> password [0|3|5|7] <value> <remainder...>",
        "password [0|3|5|7] <value> <remainder...>",
        "key-string <value> <remainder...>",
        "password: <value>",
        "password=<value>",
        "secret: <value>",
        "secret=<value>",
        "token: <value>",
        "token=<value>",
        "api_key: <value>",
        "api_key=<value>",
        "api-key: <value>",
        "api-key=<value>",
        "apikey: <value>",
        "apikey=<value>",
        "client_secret: <value>",
        "client_secret=<value>",
        "client-secret: <value>",
        "client-secret=<value>",
        "clientsecret: <value>",
        "clientsecret=<value>",
        "community: <value>",
        "community=<value>",
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "-----END PRIVATE KEY-----",
        "-----END OPENSSH PRIVATE KEY-----",
        "-----END RSA PRIVATE KEY-----",
        "-----END EC PRIVATE KEY-----",
        "-----END ENCRYPTED PRIVATE KEY-----",
    )
    for syntax in required_syntax:
        assert syntax in catalog


@pytest.mark.parametrize(
    "line",
    [
        "send-community extended",
        "match community TENANT-A",
        "set community 65000:100 additive",
        "set extcommunity rt 65000:100 additive",
        "ip community-list standard TENANT-A permit 65000:100",
        "password strength-check",
        "no password strength-check",
        "password secure-mode",
        "no password secure-mode",
        "password required",
        "no password required",
        "description community service-edge",
    ],
)
def test_unmatched_config_commands_are_not_modified_by_keyword(line: str) -> None:
    assert _is_secret_bearing_line(line) is False


def test_nxos_child_credentials_require_a_supported_parent_context() -> None:
    content = """router bgp 65000
  template peer FABRIC
    password 3 SyntheticHash
key chain MACSEC
  key 1
    key-string SyntheticKeyMaterial
"""

    findings = scan_text(
        content,
        artifact_id="leaf01:running_config",
        path="raw/sanitized/leaf01/running_config.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert [finding.rule_id for finding in findings] == [
        "NXOS_BGP_NEIGHBOR_PASSWORD",
        "NXOS_KEY_CHAIN_MATERIAL",
    ]
    standalone = scan_text(
        "password 3 SyntheticHash\nkey-string SyntheticKeyMaterial\n",
        artifact_id="standalone",
        path="standalone.txt",
        platform="nxos",
        content_type="running-config",
    )
    assert not [item for item in standalone if item.confidence == "high"]


def test_common_and_nxos_scan_records_no_secret_values() -> None:
    content = """ldap-server host 192.0.2.10 rootDN cn=admin password 7 SyntheticLdapPassword
Authorization: Bearer SyntheticBearerToken0123456789
endpoint=https://user:SyntheticUriPassword@example.invalid/api
credential=OpaqueSyntheticCredential0123456789
"""

    findings = scan_text(
        content,
        artifact_id="leaf01:running_config",
        path="raw/sanitized/leaf01/running_config.txt",
        platform="nxos",
        content_type="running-config",
    )
    result = build_scan_result(findings, files_scanned=1)
    serialized = yaml.safe_dump(result)

    assert [item.rule_id for item in findings] == [
        "NXOS_LDAP_PASSWORD",
        "SECRET_AUTHORIZATION_HEADER",
        "SECRET_URI_USERINFO",
        "SECRET_SUSPICIOUS_ENTROPY",
    ]
    assert result["catalog_sha256"] == CATALOG_SHA256
    assert result["status"] == "BLOCKED"
    assert "Synthetic" not in serialized


def test_sanitizer_and_post_scan_are_independent() -> None:
    source = """username admin password 5 SyntheticHash role network-admin
router bgp 65000
  template peer FABRIC
    password 3 SyntheticPeerHash
  send-community extended
"""
    sanitized, source_findings = sanitize_text(
        source,
        artifact_id="leaf01:running_config",
        path="raw/sanitized/leaf01/running_config.txt",
        platform="nxos",
        content_type="running-config",
    )
    post_findings = scan_text(
        sanitized,
        artifact_id="leaf01:running_config",
        path="raw/sanitized/leaf01/running_config.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert {item.rule_id for item in source_findings} == {
        "NXOS_USERNAME_PASSWORD",
        "NXOS_BGP_NEIGHBOR_PASSWORD",
    }
    assert post_findings == []
    assert "send-community extended" in sanitized
    assert "SyntheticHash" not in sanitized
    assert "SyntheticPeerHash" not in sanitized


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collection(tmp_path: Path) -> tuple[Path, Path]:
    raw = tmp_path / "raw"
    raw.mkdir()
    contents = {
        "running_config": """hostname prod-leaf01
username admin password 5 SuperSecret role network-admin
username admin passphrase lifetime 99999 warntime 14 gracetime 3
snmp-server community SyntheticCommunity group network-operator
password strength-check
ntp server 10.0.0.10 prefer use-vrf management
router bgp 65000
  template peer FABRIC-PEERS
    send-community extended
route-map EXPORT permit 10
  match community TENANT-A
  set community 65000:100 additive
  set extcommunity rt 65000:100 additive
ip community-list standard TENANT-A permit 65000:100
interface Ethernet1/1
  description prod-spine01 Ethernet1/1
""",
        "lldp_neighbors_detail": "Device ID: prod-spine01\nManagement Address: 10.0.0.20\n",
        "version": "Device name: prod-leaf01\nNXOS: version 10.5(4)\n",
    }
    commands = {}
    for command_id, content in contents.items():
        path = raw / f"{command_id}.txt"
        path.write_text(content, encoding="utf-8")
        commands[command_id] = {
            "status": "success",
            "collected_at": NOW.isoformat(),
            "file": path.name,
            "sha256": _digest(path),
            "source": "alred_collect",
        }
    manifest = {
        "api_version": "alred/v1",
        "kind": "CollectionManifest",
        "metadata": {
            "collection_id": "COL-1",
            "change_id": "CHG-1",
            "phase": "before",
            "started_at": NOW.isoformat(),
            "completed_at": NOW.isoformat(),
            "timezone": "UTC",
        },
        "spec": {
            "profiles": ["network-baseline-nxos"],
            "hosts": {
                "prod-leaf01": {
                    "status": "success",
                    "address": "10.0.0.1",
                    "commands": commands,
                }
            },
        },
    }
    manifest_path = tmp_path / "collection-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest_path, raw


def _published_before_operation(
    operations_root: Path,
    *,
    change_id: str,
    completed_at: datetime,
) -> tuple[Path, Path]:
    workspace = create_operation_workspace(
        operations_root,
        change_id=change_id,
        now=completed_at - timedelta(minutes=1),
    )
    attempt_id = f"before-{change_id.lower()}"
    attempt_dir = (
        workspace.operation_root
        / "health"
        / "before"
        / "attempts"
        / attempt_id
    )
    attempt_dir.mkdir(parents=True)
    manifest_path, raw = _collection(attempt_dir)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"].update(
        {
            "collection_id": f"COL-{change_id}",
            "change_id": change_id,
            "completed_at": completed_at.isoformat(),
        }
    )
    for command in manifest["spec"]["hosts"]["prod-leaf01"]["commands"].values():
        command["file"] = f"raw/{command['file']}"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    snapshot_path = attempt_dir / "snapshot.json"
    snapshot_path.write_text("{}\n", encoding="utf-8")
    profile_sha256 = "sha256:" + "0" * 64
    result = {
        "schema_version": 1,
        "change_id": change_id,
        "phase": "before",
        "attempt_id": attempt_id,
        "status": "COMPLETED",
        "health_result": "PASS",
        "started_at": (completed_at - timedelta(seconds=5)).isoformat(),
        "completed_at": completed_at.isoformat(),
        "artifact_dir": str(attempt_dir),
        "profile_sha256": profile_sha256,
    }
    (attempt_dir / "result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    current = {
        "schema_version": 1,
        "change_id": change_id,
        "phase": "before",
        "attempt_id": attempt_id,
        "artifact_dir": str(attempt_dir),
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": source_sha256(snapshot_path),
        "profile_sha256": profile_sha256,
        "health_result": "PASS",
        "completed_at": completed_at.isoformat(),
    }
    current_path = workspace.operation_root / "health" / "before" / "current.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    return manifest_path, raw


def test_resolve_evidence_source_uses_latest_published_before_by_default(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    _published_before_operation(
        operations_root,
        change_id="CHG-OLDER",
        completed_at=NOW,
    )
    latest_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-LATEST",
        completed_at=NOW + timedelta(minutes=1),
    )

    source = resolve_evidence_collection_source(
        operations_root=operations_root,
    )

    assert source.selection == "operation-current-before"
    assert source.change_id == "CHG-LATEST"
    assert source.collection_manifest == latest_manifest


def test_resolve_evidence_source_removes_missing_live_operation_index(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    stale_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-STALE",
        completed_at=NOW + timedelta(minutes=1),
    )
    expected_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-AVAILABLE",
        completed_at=NOW,
    )
    stale_operation_root = stale_manifest.parents[4]
    shutil.rmtree(stale_operation_root)

    source = resolve_evidence_collection_source(
        operations_root=operations_root,
    )

    assert source.change_id == "CHG-AVAILABLE"
    assert source.collection_manifest == expected_manifest
    assert not (operations_root / ".index" / "CHG-STALE.yaml").exists()


def test_resolve_explicit_evidence_source_removes_missing_live_operation_index(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    stale_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-STALE",
        completed_at=NOW,
    )
    shutil.rmtree(stale_manifest.parents[4])

    with pytest.raises(OperationPathError, match="operation does not exist"):
        resolve_evidence_collection_source(
            operations_root=operations_root,
            change_id="CHG-STALE",
        )

    assert not (operations_root / ".index" / "CHG-STALE.yaml").exists()


def test_resolve_evidence_source_change_id_overrides_latest(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    older_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-OLDER",
        completed_at=NOW,
    )
    _published_before_operation(
        operations_root,
        change_id="CHG-LATEST",
        completed_at=NOW + timedelta(minutes=1),
    )

    source = resolve_evidence_collection_source(
        operations_root=operations_root,
        change_id="CHG-OLDER",
    )

    assert source.change_id == "CHG-OLDER"
    assert source.collection_manifest == older_manifest


def test_resolve_evidence_source_ignores_newer_failed_attempt_directory(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    manifest, _raw = _published_before_operation(
        operations_root,
        change_id="CHG-CURRENT",
        completed_at=NOW,
    )
    failed_dir = manifest.parent.parent / "before-failed-newer"
    failed_dir.mkdir()
    (failed_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "change_id": "CHG-CURRENT",
                "phase": "before",
                "attempt_id": "before-failed-newer",
                "status": "FAILED",
                "started_at": (NOW + timedelta(minutes=1)).isoformat(),
                "completed_at": (NOW + timedelta(minutes=2)).isoformat(),
                "artifact_dir": str(failed_dir),
                "error": {"code": "TEST_FAILURE", "message": "synthetic"},
            }
        ),
        encoding="utf-8",
    )

    source = resolve_evidence_collection_source(
        operations_root=operations_root,
    )

    assert source.attempt_id == "before-chg-current"
    assert source.collection_manifest == manifest


def test_resolve_evidence_source_rejects_ambiguous_latest_completion(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    _published_before_operation(
        operations_root,
        change_id="CHG-A",
        completed_at=NOW,
    )
    _published_before_operation(
        operations_root,
        change_id="CHG-B",
        completed_at=NOW,
    )

    with pytest.raises(EvidencePackageError, match="specify --change-id"):
        resolve_evidence_collection_source(operations_root=operations_root)


def test_resolve_evidence_source_skips_raw_only_legacy_directory(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    raw_only = (
        operations_root
        / "HC-20260730T114524-p0900-9727f1-R2"
        / "health"
        / "before"
        / "raw"
    )
    raw_only.mkdir(parents=True)
    latest_manifest, _raw = _published_before_operation(
        operations_root,
        change_id="HC-20260810T171935-p0900-a2dd8a",
        completed_at=NOW,
    )

    source = resolve_evidence_collection_source(
        operations_root=operations_root,
    )

    assert source.change_id == "HC-20260810T171935-p0900-a2dd8a"
    assert source.collection_manifest == latest_manifest


def test_resolve_evidence_source_rejects_explicit_raw_only_legacy_directory(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    change_id = "HC-20260730T114524-p0900-9727f1-R2"
    (
        operations_root / change_id / "health" / "before" / "raw"
    ).mkdir(parents=True)

    with pytest.raises(OperationPathError, match="operation metadata not found"):
        resolve_evidence_collection_source(
            operations_root=operations_root,
            change_id=change_id,
        )


def test_resolve_evidence_source_fails_closed_for_legacy_current_without_metadata(
    tmp_path: Path,
) -> None:
    operations_root = tmp_path / "operations"
    change_id = "HC-20260730T114524-p0900-9727f1-R2"
    current = operations_root / change_id / "health" / "before" / "current.json"
    current.parent.mkdir(parents=True)
    current.write_text("{}\n", encoding="utf-8")
    _published_before_operation(
        operations_root,
        change_id="HC-20260810T171935-p0900-a2dd8a",
        completed_at=NOW,
    )

    with pytest.raises(OperationPathError, match="operation metadata not found"):
        resolve_evidence_collection_source(operations_root=operations_root)


def test_resolve_evidence_source_keeps_explicit_manifest_compatibility(
    tmp_path: Path,
) -> None:
    manifest, raw = _collection(tmp_path)

    source = resolve_evidence_collection_source(
        operations_root=tmp_path / "operations",
        collection_manifest=manifest,
        raw_root=raw,
    )

    assert source.selection == "explicit-collection-manifest"
    assert source.collection_manifest == manifest
    assert source.raw_root == raw


def test_evidence_create_cli_automatically_uses_latest_operation_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operations_root = tmp_path / "operations"
    _published_before_operation(
        operations_root,
        change_id="CHG-LATEST",
        completed_at=NOW,
    )
    args = build_parser().parse_args(
        [
            "evidence-package",
            "create",
            "--operations-root",
            str(operations_root),
            "--profile",
            "digital-twin",
            "--output-dir",
            str(tmp_path / "packages"),
        ]
    )

    cmd_evidence_package_create(args)

    output = yaml.safe_load(capsys.readouterr().out)
    assert output["source_selection"] == "operation-current-before"
    assert output["source_change_id"] == "CHG-LATEST"
    assert output["source_attempt_id"] == "before-chg-latest"
    assert output["source_completed_at"] == NOW.isoformat()
    assert Path(output["source_manifest"]).is_file()
    assert Path(output["archive"]).is_file()


def test_evidence_create_parser_keeps_manual_source_pair_optional() -> None:
    automatic = build_parser().parse_args(
        ["evidence-package", "create", "--profile", "digital-twin"]
    )
    explicit = build_parser().parse_args(
        [
            "evidence-package",
            "create",
            "--collection-manifest",
            "collection-manifest.yaml",
            "--input",
            "raw",
            "--profile",
            "digital-twin",
        ]
    )

    assert automatic.change_id is None
    assert automatic.collection_manifest is None
    assert automatic.input is None
    assert automatic.config_content == "sanitized"
    assert automatic.output_dir == "evidence-packages"
    assert automatic.keep_latest_packages is None
    assert explicit.collection_manifest == "collection-manifest.yaml"
    assert explicit.input == "raw"


def test_evidence_package_retention_keeps_latest_per_profile(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"
    digital_packages = [
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=output,
            created_at=NOW + timedelta(minutes=index),
        )
        for index in range(4)
    ]
    ai_package = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="ai-analysis",
        output_dir=output,
        created_at=NOW + timedelta(minutes=4),
    )
    sensitive_package = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=output,
        disclosure_preset="protected-preserve",
        config_content="verbatim",
        acknowledge_sensitive_config=True,
        created_at=NOW + timedelta(minutes=5),
    )

    preview = prune_evidence_packages(output, keep_latest=3, dry_run=True)

    assert [item["package_id"] for item in preview["deleted"]] == [
        digital_packages[0]["package_id"]
    ]
    assert digital_packages[0]["archive"].is_file()
    assert preview["released_bytes"] > 0

    result = prune_evidence_packages(output, keep_latest=3)

    assert [item["package_id"] for item in result["deleted"]] == [
        digital_packages[0]["package_id"]
    ]
    assert not digital_packages[0]["archive"].exists()
    assert not digital_packages[0]["checksum"].exists()
    assert all(item["archive"].is_file() for item in digital_packages[1:])
    assert ai_package["archive"].is_file()
    assert sensitive_package["archive"].is_file()


def test_evidence_create_cli_applies_retention_after_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"
    existing = [
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=output,
            created_at=NOW - timedelta(days=3 - index),
        )
        for index in range(3)
    ]
    args = build_parser().parse_args(
        [
            "evidence-package",
            "create",
            "--collection-manifest",
            str(manifest),
            "--input",
            str(raw),
            "--profile",
            "digital-twin",
            "--output-dir",
            str(output),
            "--keep-latest-packages",
            "3",
        ]
    )

    cmd_evidence_package_create(args)

    rendered = yaml.safe_load(capsys.readouterr().out)
    assert rendered["retention"]["keep_latest"] == 3
    assert rendered["retention"]["deleted"][0]["package_id"] == (
        existing[0]["package_id"]
    )
    assert not existing[0]["archive"].exists()
    assert not existing[0]["checksum"].exists()


def test_evidence_package_retention_skips_invalid_pair(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"
    packages = [
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=output,
            created_at=NOW + timedelta(minutes=index),
        )
        for index in range(2)
    ]
    packages[0]["checksum"].write_text(
        f"{'0' * 64}  {packages[0]['archive'].name}\n",
        encoding="utf-8",
    )

    result = prune_evidence_packages(output, keep_latest=1)

    assert result["deleted"] == []
    assert len(result["skipped"]) == 1
    assert packages[0]["archive"].is_file()
    assert packages[0]["checksum"].is_file()
    assert packages[1]["archive"].is_file()


def test_evidence_package_prune_cli_dry_run(tmp_path: Path, capsys) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"
    packages = [
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=output,
            created_at=NOW + timedelta(minutes=index),
        )
        for index in range(2)
    ]
    args = build_parser().parse_args(
        [
            "evidence-package",
            "prune",
            "--output-dir",
            str(output),
            "--keep-latest-packages",
            "1",
            "--dry-run",
        ]
    )

    cmd_evidence_package_prune(args)

    rendered = capsys.readouterr().out
    assert f"DELETE-ELIGIBLE {packages[0]['package_id']}" in rendered
    assert "eligible=1" in rendered
    assert all(item["archive"].is_file() for item in packages)


def test_evidence_package_keep_latest_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALRED_EVIDENCE_PACKAGE_KEEP_LATEST", "5")

    assert get_evidence_package_keep_latest() == 5


def test_evidence_create_rejects_invalid_retention_environment_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"
    monkeypatch.setenv("ALRED_EVIDENCE_PACKAGE_KEEP_LATEST", "invalid")
    args = build_parser().parse_args(
        [
            "evidence-package",
            "create",
            "--collection-manifest",
            str(manifest),
            "--input",
            str(raw),
            "--profile",
            "digital-twin",
            "--output-dir",
            str(output),
        ]
    )

    with pytest.raises(
        EvidencePackageError,
        match="ALRED_EVIDENCE_PACKAGE_KEEP_LATEST must be an integer",
    ):
        cmd_evidence_package_create(args)

    assert not output.exists()


def test_prune_imported_evidence_keeps_latest_per_profile_and_sensitivity(
    tmp_path: Path,
) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "packages"
    imports = tmp_path / "imports"
    imported_ids: list[str] = []
    for offset in range(4):
        created = create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=packages,
            created_at=NOW + timedelta(minutes=offset),
        )
        imported = import_evidence_package(
            created["archive"],
            output_dir=imports,
            imported_at=NOW + timedelta(hours=offset),
        )
        imported_ids.append(imported["package_id"])

    ai_created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="ai-analysis",
        output_dir=packages,
        created_at=NOW + timedelta(minutes=10),
    )
    ai_imported = import_evidence_package(
        ai_created["archive"],
        output_dir=imports,
        imported_at=NOW + timedelta(hours=10),
    )
    sensitive_created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        config_content="verbatim",
        acknowledge_sensitive_config=True,
        output_dir=packages,
        created_at=NOW + timedelta(minutes=20),
    )
    sensitive_imported = import_evidence_package(
        sensitive_created["archive"],
        output_dir=imports,
        acknowledge_sensitive_config=True,
        imported_at=NOW + timedelta(hours=20),
    )

    result = prune_imported_evidence(imports, keep_latest=3)

    assert [item["package_id"] for item in result["deleted"]] == [imported_ids[0]]
    assert not (imports / imported_ids[0]).exists()
    assert all((imports / package_id).is_dir() for package_id in imported_ids[1:])
    assert (imports / ai_imported["package_id"]).is_dir()
    assert (imports / sensitive_imported["package_id"]).is_dir()
    assert (imports / "latest").resolve() == (imports / sensitive_imported["package_id"]).resolve()


def test_prune_imported_evidence_skips_invalid_and_unknown_directories(
    tmp_path: Path,
) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    imports = tmp_path / "imports"
    imported = import_evidence_package(
        created["archive"], output_dir=imports, imported_at=NOW
    )
    corrupt = imported["import_dir"] / "inventory" / "hosts.resolved.yaml"
    corrupt.write_text("changed\n", encoding="utf-8")
    unknown = imports / "manual-data"
    unknown.mkdir()

    result = prune_imported_evidence(imports, keep_latest=1)

    assert result["verified"] == 0
    assert result["deleted"] == []
    assert len(result["skipped"]) == 2
    assert corrupt.is_file()
    assert unknown.is_dir()


def test_prune_imported_evidence_never_deletes_latest_target(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "packages"
    imports = tmp_path / "imports"
    imported_ids: list[str] = []
    for offset in range(3):
        created = create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=packages,
            created_at=NOW + timedelta(minutes=offset),
        )
        imported = import_evidence_package(
            created["archive"],
            output_dir=imports,
            imported_at=NOW + timedelta(hours=offset),
        )
        imported_ids.append(imported["package_id"])
    latest = imports / "latest"
    latest.unlink()
    latest.symlink_to(imported_ids[0], target_is_directory=True)

    result = prune_imported_evidence(imports, keep_latest=1)

    assert (imports / imported_ids[0]).is_dir()
    assert (imports / imported_ids[2]).is_dir()
    assert not (imports / imported_ids[1]).exists()
    assert any("latest import target is protected" in item["reason"] for item in result["skipped"])


def test_evidence_import_applies_retention_after_success(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "packages"
    imports = tmp_path / "imports"
    archives: list[Path] = []
    for offset in range(2):
        created = create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=packages,
            created_at=NOW + timedelta(minutes=offset),
        )
        archives.append(created["archive"])

    for archive in archives:
        args = build_parser().parse_args(
            [
                "evidence-package",
                "import",
                "--bundle",
                str(archive),
                "--output-dir",
                str(imports),
                "--keep-latest-packages",
                "1",
            ]
        )
        cmd_evidence_package_import(args)

    package_dirs = [
        path for path in imports.iterdir() if path.is_dir() and not path.is_symlink()
    ]
    assert len(package_dirs) == 1
    assert (imports / "latest").resolve() == package_dirs[0].resolve()


def test_evidence_import_without_bundle_selects_latest_verified_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "evidence-packages"
    imports = tmp_path / "imports"
    older = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=packages,
        created_at=NOW,
    )
    newer = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=packages,
        created_at=NOW + timedelta(minutes=1),
    )
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        ["evidence-package", "import", "--output-dir", str(imports)]
    )

    cmd_evidence_package_import(args)

    output = capsys.readouterr().out
    assert args.bundle is None
    assert older["package_id"] not in (imports / "latest").resolve().name
    assert (imports / "latest").resolve().name == newer["package_id"]
    assert "source_selection: latest-verified" in output
    assert f"source_bundle: evidence-packages/{newer['archive'].name}" in output


def test_evidence_import_without_bundle_fails_closed_on_invalid_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "evidence-packages"
    create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=packages,
        created_at=NOW,
    )
    (packages / "broken.tar.gz").write_bytes(b"broken")
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["evidence-package", "import"])

    with pytest.raises(
        EvidencePackageError,
        match="automatic bundle selection found an invalid archive",
    ):
        cmd_evidence_package_import(args)


def test_evidence_import_checksum_file_requires_explicit_bundle() -> None:
    args = build_parser().parse_args(
        ["evidence-package", "import", "--checksum-file", "package.sha256"]
    )

    with pytest.raises(
        EvidencePackageError,
        match="--checksum-file requires --bundle",
    ):
        cmd_evidence_package_import(args)


def test_evidence_prune_imports_cli_dry_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, raw = _collection(tmp_path)
    packages = tmp_path / "packages"
    imports = tmp_path / "imports"
    for offset in range(2):
        created = create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=packages,
            created_at=NOW + timedelta(minutes=offset),
        )
        import_evidence_package(
            created["archive"],
            output_dir=imports,
            imported_at=NOW + timedelta(hours=offset),
        )
    args = build_parser().parse_args(
        [
            "evidence-package",
            "prune-imports",
            "--output-dir",
            str(imports),
            "--keep-latest-packages",
            "1",
            "--dry-run",
        ]
    )

    cmd_evidence_package_prune_imports(args)

    output = capsys.readouterr().out
    assert "DELETE-ELIGIBLE" in output
    assert "eligible=1" in output
    assert len(
        [path for path in imports.iterdir() if path.is_dir() and not path.is_symlink()]
    ) == 2


def test_evidence_import_retention_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALRED_EVIDENCE_IMPORT_KEEP_LATEST", "5")
    assert get_evidence_import_keep_latest() == 5


def test_evidence_import_rejects_invalid_retention_environment_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    output = tmp_path / "imports"
    monkeypatch.setenv("ALRED_EVIDENCE_IMPORT_KEEP_LATEST", "invalid")
    args = build_parser().parse_args(
        [
            "evidence-package",
            "import",
            "--bundle",
            str(created["archive"]),
            "--output-dir",
            str(output),
        ]
    )

    with pytest.raises(
        EvidencePackageError,
        match="ALRED_EVIDENCE_IMPORT_KEEP_LATEST must be an integer",
    ):
        cmd_evidence_package_import(args)

    assert not output.exists()


def test_create_verify_inspect_and_import_digital_twin(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    output = tmp_path / "packages"

    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=output,
        created_at=NOW,
    )

    verified = verify_evidence_package(created["archive"])
    inspected = inspect_evidence_package(created["archive"])
    assert verified["verified"] is True
    assert verified["external_checksum_verified"] is True
    assert verified["external_checksum_selection"] == "inferred"
    assert Path(verified["external_checksum_file"]) == created["checksum"]
    assert inspected["profile"] == "digital-twin"
    assert inspected["config_content"] == "sanitized"
    assert inspected["secret_scan_status"] == "CLEAN"
    assert verified["secret_scan_status"] == "CLEAN"
    assert verified["secret_scan_catalog_match"] is True
    assert verified["secret_scan_catalog_sha256"] == CATALOG_SHA256
    assert verified["secret_scan_catalog_version"] == CATALOG_VERSION

    with tarfile.open(created["archive"], "r:gz") as archive:
        member = archive.extractfile(
            "alred-evidence/raw/sanitized/prod-leaf01/running_config.txt"
        )
        assert member is not None
        config = member.read().decode()
    assert "prod-leaf01" in config
    assert "10.0.0.10" in config
    assert "SuperSecret" not in config
    assert "SyntheticCommunity" not in config
    assert "username admin passphrase" not in config
    assert "! REDACTED NXOS_USERNAME_PASSWORD" in config
    assert "! REDACTED NXOS_SNMP_COMMUNITY" in config
    assert "ntp server 10.0.0.10" in config
    assert "prefer use-vrf management" in config
    assert "send-community extended" in config
    assert "set community 65000:100 additive" in config
    assert "match community TENANT-A" in config
    assert "set extcommunity rt 65000:100 additive" in config
    assert "ip community-list standard TENANT-A" in config
    assert "password strength-check" in config

    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imports",
        imported_at=NOW,
    )
    package_manifest = yaml.safe_load(
        (imported["import_dir"] / "package-manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        resource["resource_id"] == "canonical_link_diagnostics"
        for resource in package_manifest["spec"]["resources"]
    )
    assert (
        imported["import_dir"] / "canonical" / "link-diagnostics.yaml"
    ).is_file()
    assert (imported["import_dir"] / "package-manifest.yaml").is_file()
    assert (imported["import_dir"] / "import-record.yaml").is_file()
    assert imported["external_checksum_verified"] is True
    assert imported["external_checksum_selection"] == "inferred"
    latest = tmp_path / "imports" / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == imported["import_dir"].resolve()
    inventory, configs, manifest = resolve_imported_digital_twin(latest)
    assert inventory.is_file()
    assert set(configs) == {"prod-leaf01"}
    assert manifest["metadata"]["package_id"] == imported["package_id"]


def test_old_secret_scan_catalog_is_revalidated_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    current_catalog = "sha256:" + "f" * 64
    monkeypatch.setattr(portable_evidence, "CATALOG_SHA256", current_catalog)
    monkeypatch.setattr(secret_scan, "CATALOG_SHA256", current_catalog)

    verified = verify_evidence_package(created["archive"])
    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imports",
        imported_at=NOW,
    )
    record = yaml.safe_load(
        (imported["import_dir"] / "import-record.yaml").read_text(encoding="utf-8")
    )

    assert verified["secret_scan_declared"] is True
    assert verified["secret_scan_catalog_match"] is False
    assert verified["secret_scan_catalog_sha256"] == current_catalog
    assert imported["secret_scan_catalog_match"] is False
    assert record["spec"]["secret_scan_catalog_match"] is False
    assert record["spec"]["secret_scan_catalog_sha256"] == current_catalog
    assert record["spec"]["secret_scan_catalog_version"] == CATALOG_VERSION
    inventory, configs, _manifest = resolve_imported_digital_twin(
        imported["import_dir"]
    )
    assert inventory.is_file()
    assert set(configs) == {"prod-leaf01"}


def test_evidence_cli_does_not_repeat_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["alred", "evidence-package", "import"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 6
    error = capsys.readouterr().err
    assert error.count("EVIDENCE_INVALID_SOURCE:") == 1


def test_verify_and_import_continue_when_inferred_checksum_is_absent(
    tmp_path: Path,
) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    created["checksum"].unlink()

    verified = verify_evidence_package(created["archive"])
    assert verified["verified"] is True
    assert verified["external_checksum_verified"] is False
    assert verified["external_checksum_selection"] == "not-found"
    assert verified["external_checksum_file"] is None

    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imports",
        imported_at=NOW,
    )
    record = yaml.safe_load(
        (imported["import_dir"] / "import-record.yaml").read_text(encoding="utf-8")
    )
    assert imported["external_checksum_verified"] is False
    assert record["spec"]["external_checksum_verified"] is False
    assert record["spec"]["external_checksum_selection"] == "not-found"


def test_verify_fails_closed_for_mismatched_inferred_checksum(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    created["checksum"].write_text(
        f"{'0' * 64}  {created['archive'].name}\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidencePackageError, match="archive checksum mismatch"):
        verify_evidence_package(created["archive"])


def test_digital_twin_can_explicitly_pseudonymize_identity(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        disclosure_preset="pseudonymized",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )

    with tarfile.open(created["archive"], "r:gz") as archive:
        member = archive.extractfile(
            "alred-evidence/raw/sanitized/node-001/running_config.txt"
        )
        assert member is not None
        config = member.read().decode()
    assert "prod-leaf01" not in config
    assert "10.0.0.10" not in config
    assert "ntp server 198.18." in config
    assert "send-community extended" in config
    assert "set community 65000:100 additive" in config
    assert "match community TENANT-A" in config
    assert "set extcommunity rt 65000:100 additive" in config
    assert "ip community-list standard TENANT-A" in config
    assert "password strength-check" in config


def test_shared_collect_transcript_is_exported_as_one_output_per_command(
    tmp_path: Path,
) -> None:
    manifest_path, raw = _collection(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    transcript = raw / "leaf01_shows.log"
    transcript.write_text(
        "!Command: show clock\n"
        "prod-leaf01# show clock\n"
        "12:00:00 UTC Mon Aug 10 2026\n"
        "!Command: show version\n"
        "prod-leaf01# show version\n"
        "NXOS: version 10.5(4)\n",
        encoding="utf-8",
    )
    digest = _digest(transcript)
    commands = manifest["spec"]["hosts"]["prod-leaf01"]["commands"]
    commands["clock"] = {
        "status": "success",
        "collected_at": NOW.isoformat(),
        "file": transcript.name,
        "sha256": digest,
        "source": "alred_collect",
        "start_line": 1,
        "end_line": 3,
        "output_start_line": 3,
        "output_end_line": 3,
    }
    commands["version"] = {
        "status": "success",
        "collected_at": NOW.isoformat(),
        "file": transcript.name,
        "sha256": digest,
        "source": "alred_collect",
        "start_line": 4,
        "end_line": 6,
        "output_start_line": 6,
        "output_end_line": 6,
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    created = create_evidence_package(
        collection_manifest=manifest_path,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )

    with tarfile.open(created["archive"], "r:gz") as archive:
        clock = archive.extractfile(
            "alred-evidence/raw/sanitized/prod-leaf01/clock.txt"
        )
        version = archive.extractfile(
            "alred-evidence/raw/sanitized/prod-leaf01/version.txt"
        )
        embedded_manifest_file = archive.extractfile(
            "alred-evidence/collection-manifest.yaml"
        )
        package_manifest_file = archive.extractfile(
            "alred-evidence/package-manifest.yaml"
        )
        assert clock is not None
        assert version is not None
        assert embedded_manifest_file is not None
        assert package_manifest_file is not None
        assert clock.read().decode() == "12:00:00 UTC Mon Aug 10 2026\n"
        assert version.read().decode() == "NXOS: version 10.5(4)\n"
        embedded_manifest = yaml.safe_load(embedded_manifest_file.read())
        package_manifest = yaml.safe_load(package_manifest_file.read())

    validate_document(package_manifest, kind="EvidencePackageManifest")
    assert package_manifest["spec"]["secret_scan"]["status"] == "CLEAN"

    exported_clock = embedded_manifest["spec"]["hosts"]["prod-leaf01"][
        "commands"
    ]["clock"]
    assert "output_start_line" not in exported_clock
    clock_entry = next(
        item
        for item in package_manifest["spec"]["files"]
        if item["artifact_id"] == "prod-leaf01:clock"
    )
    assert clock_entry["source_range"] == {
        "start_line": 1,
        "end_line": 3,
        "output_start_line": 3,
        "output_end_line": 3,
    }


def test_out_of_bounds_command_range_is_rejected(tmp_path: Path) -> None:
    manifest_path, raw = _collection(tmp_path)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    version = manifest["spec"]["hosts"]["prod-leaf01"]["commands"]["version"]
    version["output_start_line"] = 100
    version["output_end_line"] = 101
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(EvidencePackageError, match="range outside source"):
        create_evidence_package(
            collection_manifest=manifest_path,
            raw_root=raw,
            profile="digital-twin",
            output_dir=tmp_path / "packages",
            created_at=NOW,
        )


def test_verbatim_requires_acknowledgement_and_preserves_running_config_bytes(
    tmp_path: Path,
) -> None:
    manifest, raw = _collection(tmp_path)
    with pytest.raises(EvidencePackageError, match="NOT_ACKNOWLEDGED"):
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=tmp_path / "packages",
            disclosure_preset="protected-preserve",
            config_content="verbatim",
            created_at=NOW,
        )

    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        disclosure_preset="protected-preserve",
        config_content="verbatim",
        acknowledge_sensitive_config=True,
        created_at=NOW,
    )

    assert created["archive"].name.endswith(".sensitive.tar.gz")
    assert created["secret_scan_status"] == "ACKNOWLEDGED_SENSITIVE"
    assert created["secret_scan_high_confidence"] > 0
    with tarfile.open(created["archive"], "r:gz") as archive:
        member = archive.extractfile(
            "alred-evidence/raw/verbatim/prod-leaf01/running_config.txt"
        )
        assert member is not None
        assert member.read() == (raw / "running_config.txt").read_bytes()
        manifest_member = archive.extractfile(
            "alred-evidence/package-manifest.yaml"
        )
        assert manifest_member is not None
        package_manifest_text = manifest_member.read().decode()
    assert "SuperSecret" not in package_manifest_text
    assert "SyntheticCommunity" not in package_manifest_text
    with pytest.raises(EvidencePackageError, match="NOT_ACKNOWLEDGED"):
        import_evidence_package(
            created["archive"],
            output_dir=tmp_path / "imports",
            imported_at=NOW,
        )
    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imports",
        acknowledge_sensitive_config=True,
        imported_at=NOW,
    )
    assert (imported["import_dir"] / "raw" / "verbatim").is_dir()
    assert imported["external_checksum_verified"] is True
    assert imported["external_checksum_selection"] == "inferred"


def test_ai_analysis_includes_all_successful_collection_and_prompt(tmp_path: Path) -> None:
    manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest,
        raw_root=raw,
        profile="ai-analysis",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )

    with tarfile.open(created["archive"], "r:gz") as archive:
        names = set(archive.getnames())
        assert "alred-evidence/analysis/prompt.md" in names
        assert "alred-evidence/analysis/STRUCTURE.md" in names
        assert "alred-evidence/raw/sanitized/node-001/running_config.txt" in names
        assert "alred-evidence/raw/sanitized/node-001/lldp_neighbors_detail.txt" in names
        assert "alred-evidence/raw/sanitized/node-001/version.txt" in names


def test_digital_twin_package_regenerates_and_verifies_canonical_links(
    tmp_path: Path,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imports",
        imported_at=NOW,
    )
    parser = build_parser()
    args = parser.parse_args(
        [
            "normalize-links",
            "--evidence-package",
            str(imported["import_dir"]),
            "--output-dir",
            str(tmp_path / "links"),
        ]
    )
    args.func(args)

    verification = json.loads(
        (tmp_path / "links" / "link-verification.json").read_text(encoding="utf-8")
    )
    assert verification["status"] == "VERIFIED"
    assert (tmp_path / "links" / "links_confirmed.csv").is_file()
    assert (tmp_path / "links" / "links_candidates.csv").is_file()
    assert (tmp_path / "links" / "link-diagnostics.yaml").is_file()
    assert (tmp_path / "links" / "mismatch-links.md").is_file()


def test_standalone_consumers_default_to_latest_imported_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imported-evidence",
        imported_at=NOW,
    )
    monkeypatch.chdir(tmp_path)
    parser = build_parser()

    normalize_args = parser.parse_args(
        ["normalize-links", "--output-dir", str(tmp_path / "latest-links")]
    )
    normalize_args.func(normalize_args)
    assert normalize_args.evidence_package == "imported-evidence/latest"
    assert (tmp_path / "latest-links" / "links_confirmed.csv").is_file()

    transform_args = parser.parse_args(
        [
            "clab-transform-config",
            "--output-hosts",
            str(tmp_path / "latest-hosts.lab.yaml"),
            "--output-dir",
            str(tmp_path / "latest-labconfig"),
        ]
    )
    transform_args.func(transform_args)
    assert transform_args.evidence_import == "imported-evidence/latest"
    assert (tmp_path / "latest-hosts.lab.yaml").is_file()
    assert (tmp_path / "latest-labconfig" / "prod-leaf01_run.txt").is_file()

    mermaid_args = parser.parse_args(
        [
            "generate-mermaid",
            "--link-output-dir",
            str(tmp_path / "latest-mermaid-links"),
            "--output",
            str(tmp_path / "latest-topology.md"),
        ]
    )
    mermaid_args.func(mermaid_args)
    assert mermaid_args.evidence_package == "imported-evidence/latest"
    assert (tmp_path / "latest-topology.md").is_file()


def test_legacy_link_hash_is_verified_before_direction_neutral_comparison(
    tmp_path: Path,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    manifest = yaml.safe_load(collection_manifest.read_text(encoding="utf-8"))
    leaf_lldp = raw / "lldp_neighbors_detail.txt"
    leaf_lldp.write_text(
        "System Name: prod-spine01\n"
        "Local Port id: Ethernet1/1\n"
        "Port id: Ethernet1/1\n"
        "Management Address: 10.0.0.20\n",
        encoding="utf-8",
    )
    manifest["spec"]["hosts"]["prod-leaf01"]["commands"][
        "lldp_neighbors_detail"
    ]["sha256"] = hashlib.sha256(leaf_lldp.read_bytes()).hexdigest()
    spine_config = raw / "spine_running_config.txt"
    spine_config.write_text(
        "hostname prod-spine01\n"
        "interface Ethernet1/1\n"
        "  description prod-leaf01 Ethernet1/1\n",
        encoding="utf-8",
    )
    spine_lldp = raw / "spine_lldp_neighbors_detail.txt"
    spine_lldp.write_text(
        "System Name: prod-leaf01\n"
        "Local Port id: Ethernet1/1\n"
        "Port id: Ethernet1/1\n"
        "Management Address: 10.0.0.1\n",
        encoding="utf-8",
    )
    manifest["spec"]["hosts"]["prod-spine01"] = {
        "status": "success",
        "address": "10.0.0.20",
        "commands": {
            "running_config": {
                "status": "success",
                "collected_at": NOW.isoformat(),
                "file": spine_config.name,
                "sha256": hashlib.sha256(spine_config.read_bytes()).hexdigest(),
                "source": "alred_collect",
            },
            "lldp_neighbors_detail": {
                "status": "success",
                "collected_at": NOW.isoformat(),
                "file": spine_lldp.name,
                "sha256": hashlib.sha256(spine_lldp.read_bytes()).hexdigest(),
                "source": "alred_collect",
            },
        },
    }
    collection_manifest.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    imported = import_evidence_package(
        created["archive"], output_dir=tmp_path / "imports", imported_at=NOW
    )
    import_dir = imported["import_dir"]
    manifest_path = import_dir / "package-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    confirmed_resource = next(
        resource
        for resource in manifest["spec"]["resources"]
        if resource["resource_id"] == "canonical_links_confirmed"
    )
    confirmed_path = import_dir / confirmed_resource["path"]
    reversed_records = []
    for record in read_links_csv(str(confirmed_path)):
        reversed_records.append(
            {
                **record,
                "src_node": record["dst_node"],
                "src_if": record["dst_if"],
                "dst_node": record["src_node"],
                "dst_if": record["src_if"],
            }
        )
    assert reversed_records
    write_links_csv(reversed_records, str(confirmed_path))
    confirmed_resource.pop("semantic_version")
    confirmed_resource["sha256"] = hashlib.sha256(
        confirmed_path.read_bytes()
    ).hexdigest()
    confirmed_resource["semantic_sha256"] = canonical_links_sha256(
        reversed_records
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    args = build_parser().parse_args(
        [
            "normalize-links",
            "--evidence-package",
            str(import_dir),
            "--output-dir",
            str(tmp_path / "legacy-links"),
        ]
    )
    args.func(args)

    verification = json.loads(
        (tmp_path / "legacy-links" / "link-verification.json").read_text(
            encoding="utf-8"
        )
    )
    assert verification["status"] == "VERIFIED"
    assert verification["packaged_confirmed_semantic_version"] == 1


def test_digital_twin_lldp_is_optional_and_description_is_retained(
    tmp_path: Path,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    manifest = yaml.safe_load(collection_manifest.read_text(encoding="utf-8"))
    del manifest["spec"]["hosts"]["prod-leaf01"]["commands"]["lldp_neighbors_detail"]
    collection_manifest.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    imported = import_evidence_package(
        created["archive"], output_dir=tmp_path / "imports", imported_at=NOW
    )
    args = build_parser().parse_args(
        ["normalize-links", "--evidence-package", str(imported["import_dir"])]
    )
    monkey_output = tmp_path / "links"
    args.output_dir = str(monkey_output)
    args.func(args)
    assert "one-way-description" in (
        monkey_output / "links_candidates.csv"
    ).read_text(encoding="utf-8")


def test_clab_set_cmds_accepts_evidence_archive_as_offline_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        ["clab-set-cmds", "--evidence-package", str(created["archive"])]
    )
    args.func(args)

    assert (tmp_path / "hosts.lab.yaml").is_file()
    lab_inventory = yaml.safe_load(
        (tmp_path / "hosts.lab.yaml").read_text(encoding="utf-8")
    )
    lab_host = lab_inventory["all"]["hosts"]["prod-leaf01"]
    assert lab_host["os_type"] == "nxos"
    assert lab_host["ansible_network_os"] == "cisco.nxos.nxos"
    assert lab_host["ansible_connection"] == "network_cli"
    assert lab_host["netmiko_device_type"] == "cisco_nxos"
    assert (tmp_path / "raw" / "labconfig" / "prod-leaf01_run.txt").is_file()
    assert (tmp_path / "output" / "links_confirmed.csv").is_file()
    assert (tmp_path / "output" / "topology.clab.yaml").is_file()
    assert (tmp_path / "output" / "topology-graph.md").is_file()
    current_path = tmp_path / "output" / "clab-set-cmds" / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    assert current["status"] == "SUCCESS"
    manifest = yaml.safe_load(
        (tmp_path / current["manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["metadata"]["status"] == "SUCCESS"
    assert manifest["spec"]["requested_source"] == {
        "type": "evidence-package-archive",
        "path": str(created["archive"]),
    }
    assert manifest["spec"]["source"]["type"] == "evidence-package"
    assert manifest["spec"]["source"]["manifest_sha256"]
    steps = {step["name"]: step for step in manifest["spec"]["steps"]}
    assert steps["source-resolution"]["status"] == "COMPLETED"
    assert steps["collect-clab"]["status"] == "SKIPPED"
    assert all(
        step["status"] == "COMPLETED"
        for name, step in steps.items()
        if name not in {"source-resolution", "collect-clab"}
    )
    assert manifest["spec"]["device_access_performed"] is False
    assert manifest["spec"]["outputs"]
    assert {
        output["disposition"] for output in manifest["spec"]["outputs"]
    } == {"created"}


def test_clab_set_cmds_defaults_to_latest_imported_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imported-evidence",
        imported_at=NOW,
    )
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["clab-set-cmds"])

    args.func(args)

    assert args.evidence_package is None
    assert args.evidence_import == "imported-evidence/latest"
    current = json.loads(
        (tmp_path / "output/clab-set-cmds/current.json").read_text(
            encoding="utf-8"
        )
    )
    attempt_manifest = yaml.safe_load(
        (tmp_path / current["manifest"]).read_text(encoding="utf-8")
    )
    assert attempt_manifest["spec"]["requested_source"] == {
        "type": "evidence-package",
        "path": "imported-evidence/latest",
    }
    assert attempt_manifest["spec"]["device_access_performed"] is False


def test_generate_network_diagram_defaults_to_latest_imported_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_manifest, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=collection_manifest,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    imported = import_evidence_package(
        created["archive"],
        output_dir=tmp_path / "imported-evidence",
        imported_at=NOW,
    )
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "network-diagram"
    args = build_parser().parse_args([
        "generate-network-diagram",
        "--output-dir", str(output),
    ])

    args.func(args)

    assert (output / "topology-graph.md").is_file()
    assert (output / "topology_underlay.md").is_file()
    assert (output / "topology-graph.drawio").is_file()
    manifest = yaml.safe_load(
        (output / "network-diagram-manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["spec"]["source"] == {
        "type": "evidence-package",
        "value": "imported-evidence/latest",
    }


def test_generate_mermaid_can_normalize_latest_operation_inline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = tmp_path / "operations"
    _published_before_operation(
        operations,
        change_id="HC-LATEST",
        completed_at=NOW,
    )
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        [
            "generate-mermaid",
            "--latest-operation",
            "--operations-root",
            str(operations),
            "--output",
            str(tmp_path / "latest.md"),
        ]
    )
    args.func(args)

    assert (tmp_path / "latest.md").is_file()
    assert (tmp_path / "output" / "links_candidates.csv").is_file()
