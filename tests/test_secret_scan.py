from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import alred.portable_evidence as portable_evidence
from alred.portable_evidence import EvidencePackageError, create_evidence_package
from alred.schema import validate_document
from alred.secret_scan import build_scan_result, sanitize_text, scan_text
from tests.test_portable_evidence import _collection


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_banner_uses_low_confidence_unless_assignment_is_explicit() -> None:
    content = """banner motd ^C
Do not disclose the password in support requests.
token: SyntheticBannerToken
^C
password strength-check
no password strength-check
send-community extended
"""

    findings = scan_text(
        content,
        artifact_id="leaf01:running_config",
        path="running_config.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert [(item.rule_id, item.confidence, item.line) for item in findings] == [
        ("NXOS_BANNER_SECRET_CANDIDATE", "low", 2),
        ("SECRET_GENERIC_KEY_VALUE", "high", 3),
    ]
    validate_document(
        {
            "api_version": "alred/v1",
            "kind": "SecretScanResult",
            "spec": build_scan_result(findings, files_scanned=1),
        }
    )


def test_private_key_block_is_removed_and_location_contains_no_material() -> None:
    content = """certificate
-----BEGIN ENCRYPTED PRIVATE KEY-----
SyntheticPrivateKeyMaterial
-----END ENCRYPTED PRIVATE KEY-----
public-key SyntheticPublicKey
"""

    sanitized, findings = sanitize_text(
        content,
        artifact_id="leaf01:certificate",
        path="certificate.txt",
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "SECRET_PEM_PRIVATE_KEY"
    assert findings[0].line == 2
    assert findings[0].end_line == 4
    assert "SyntheticPrivateKeyMaterial" not in sanitized
    assert "public-key SyntheticPublicKey" in sanitized


def test_safe_markers_and_routing_community_are_not_high_confidence() -> None:
    content = """password: <redacted:PASSWORD>
token=***REDACTED***
send-community both
match community TENANT-A
set community 65000:100 additive
set extcommunity rt 65000:100 additive
ip community-list standard TENANT-A permit 65000:100
"""

    findings = scan_text(
        content,
        artifact_id="leaf01:running_config",
        path="running_config.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert not [item for item in findings if item.confidence == "high"]


def test_snmp_v1_v2c_trap_host_community_is_sanitized() -> None:
    content = """snmp-server host 192.0.2.10 traps version 2c SyntheticTrapCommunity
snmp-server host 192.0.2.11 informs version 1 SyntheticInformCommunity use-vrf management
snmp-server host 192.0.2.12 traps version 3 priv sample-user
"""

    sanitized, findings = sanitize_text(
        content,
        artifact_id="leaf01:running_config",
        path="running_config.txt",
        platform="nxos",
        content_type="running-config",
    )

    assert [(item.rule_id, item.line) for item in findings] == [
        ("NXOS_SNMP_COMMUNITY", 1),
        ("NXOS_SNMP_COMMUNITY", 2),
    ]
    assert "SyntheticTrapCommunity" not in sanitized
    assert "SyntheticInformCommunity" not in sanitized
    assert "snmp-server host 192.0.2.12 traps version 3 priv sample-user" in sanitized


def test_create_fails_closed_when_sanitizer_leaves_a_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, raw = _collection(tmp_path)

    def ineffective_sanitizer(content: str, **_kwargs: object) -> tuple[str, list[object]]:
        return content, []

    monkeypatch.setattr(
        portable_evidence,
        "sanitize_text",
        ineffective_sanitizer,
    )

    with pytest.raises(EvidencePackageError, match="EVIDENCE_BLOCKED_SECRET"):
        create_evidence_package(
            collection_manifest=manifest,
            raw_root=raw,
            profile="digital-twin",
            output_dir=tmp_path / "packages",
            created_at=NOW,
        )
    assert not (tmp_path / "packages").exists()


def test_non_utf8_command_output_is_not_treated_as_clean(tmp_path: Path) -> None:
    manifest_path, raw = _collection(tmp_path)
    binary = raw / "running_config.txt"
    binary.write_bytes(b"hostname leaf01\n\xff\n")
    manifest = portable_evidence.yaml.safe_load(
        manifest_path.read_text(encoding="utf-8")
    )
    manifest["spec"]["hosts"]["prod-leaf01"]["commands"]["running_config"][
        "sha256"
    ] = portable_evidence._sha256_bytes(binary.read_bytes())
    manifest_path.write_text(
        portable_evidence.yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(EvidencePackageError, match="EVIDENCE_SCAN_FAILED"):
        create_evidence_package(
            collection_manifest=manifest_path,
            raw_root=raw,
            profile="digital-twin",
            output_dir=tmp_path / "packages",
            created_at=NOW,
        )


def test_verify_and_inspect_rescan_self_consistent_archive_content(
    tmp_path: Path,
) -> None:
    manifest_path, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest_path,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    files, manifest = portable_evidence._read_archive(created["archive"])
    config_name = "alred-evidence/raw/sanitized/prod-leaf01/running_config.txt"
    files[config_name] += b"username injected password 5 SyntheticInjectedHash\n"
    running_entry = next(
        entry
        for entry in manifest["spec"]["files"]
        if entry["command_id"] == "running_config"
    )
    running_entry["export_sha256"] = portable_evidence._sha256_bytes(
        files[config_name]
    )
    files["alred-evidence/package-manifest.yaml"] = yaml.safe_dump(
        manifest,
        sort_keys=False,
        allow_unicode=True,
    ).encode()
    files["alred-evidence/checksums.sha256"] = "".join(
        f"{portable_evidence._sha256_bytes(content)}  "
        f"{name.removeprefix('alred-evidence/')}\n"
        for name, content in sorted(files.items())
        if name != "alred-evidence/checksums.sha256"
    ).encode()
    tampered = tmp_path / "self-consistent-but-unsafe.tar.gz"
    portable_evidence._deterministic_archive(tampered, files)

    with pytest.raises(EvidencePackageError, match="EVIDENCE_BLOCKED_SECRET"):
        portable_evidence.verify_evidence_package(tampered)
    with pytest.raises(EvidencePackageError, match="EVIDENCE_BLOCKED_SECRET"):
        portable_evidence.inspect_evidence_package(tampered)


def test_legacy_manifest_is_rescanned_without_disabling_compatibility(
    tmp_path: Path,
) -> None:
    manifest_path, raw = _collection(tmp_path)
    created = create_evidence_package(
        collection_manifest=manifest_path,
        raw_root=raw,
        profile="digital-twin",
        output_dir=tmp_path / "packages",
        created_at=NOW,
    )
    files, manifest = portable_evidence._read_archive(created["archive"])
    manifest["spec"].pop("secret_scan")
    for entry in manifest["spec"]["files"]:
        entry.pop("redaction_count")
    files["alred-evidence/package-manifest.yaml"] = yaml.safe_dump(
        manifest,
        sort_keys=False,
        allow_unicode=True,
    ).encode()
    files["alred-evidence/checksums.sha256"] = "".join(
        f"{portable_evidence._sha256_bytes(content)}  "
        f"{name.removeprefix('alred-evidence/')}\n"
        for name, content in sorted(files.items())
        if name != "alred-evidence/checksums.sha256"
    ).encode()
    legacy = tmp_path / "legacy-safe.tar.gz"
    portable_evidence._deterministic_archive(legacy, files)

    verified = portable_evidence.verify_evidence_package(legacy)
    inspected = portable_evidence.inspect_evidence_package(legacy)
    imported = portable_evidence.import_evidence_package(
        legacy,
        output_dir=tmp_path / "legacy-import",
        imported_at=NOW,
    )

    assert verified["secret_scan_status"] == "CLEAN"
    assert verified["secret_scan_declared"] is False
    assert inspected["secret_scan_declared"] is False
    assert (imported["import_dir"] / "package-manifest.yaml").is_file()
