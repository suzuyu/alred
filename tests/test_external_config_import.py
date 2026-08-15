from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from alred.cli import build_parser
from alred.external_config_import import (
    ExternalConfigImportError,
    import_running_configs,
    resolve_running_config_import,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _inventory(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        "leaf01": {"ansible_host": "192.0.2.11", "device_type": "nxos"},
                        "leaf02": {"ansible_host": "192.0.2.12", "device_type": "nxos"},
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_import_directory_is_manifest_pinned_and_normalizable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "leaf01.txt").write_text(
        "hostname leaf01\ninterface Ethernet1/1\n  description leaf02 Ethernet1/1\n",
        encoding="utf-8",
    )
    (source / "leaf02.txt").write_text(
        "hostname leaf02\ninterface Ethernet1/1\n  description leaf01 Ethernet1/1\n",
        encoding="utf-8",
    )
    hosts = _inventory(tmp_path / "hosts.yaml")
    output = tmp_path / "imports"

    result = import_running_configs(
        input_dir=source,
        input_format="running-config-directory",
        hosts_path=hosts,
        output_dir=output,
        imported_at=NOW,
    )
    inventory, configs, lldp, manifest = resolve_running_config_import(output)

    assert inventory.name == "hosts.resolved.yaml"
    assert set(configs) == {"leaf01", "leaf02"}
    assert lldp == {}
    assert manifest["spec"]["lldp"] == "not_provided"
    assert (output / "current.json").is_file()
    assert result["attempt_dir"].is_dir()

    parser = build_parser()
    args = parser.parse_args(
        [
            "normalize-links",
            "--running-config-import",
            str(output),
            "--output-dir",
            str(tmp_path / "links"),
        ]
    )
    args.func(args)
    confirmed = (tmp_path / "links" / "links_confirmed.csv").read_text(encoding="utf-8")
    assert "bidirectional-description" in confirmed


def test_import_rejects_filename_and_embedded_hostname_conflict(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "leaf01.txt").write_text("hostname leaf02\n", encoding="utf-8")
    hosts = _inventory(tmp_path / "hosts.yaml")

    try:
        import_running_configs(
            input_dir=source,
            input_format="running-config-directory",
            hosts_path=hosts,
            output_dir=tmp_path / "imports",
            imported_at=NOW,
        )
    except ExternalConfigImportError as exc:
        assert "EXTERNAL_CONFIG_IDENTITY_CONFLICT" in str(exc)
    else:
        raise AssertionError("identity conflict was accepted")


def test_import_nxos_transcript_splits_multiple_hosts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "session.txt").write_text(
        "leaf01# show running-config\n"
        "hostname leaf01\n"
        "interface Ethernet1/1\n"
        "  description leaf02 Ethernet1/1\n"
        "leaf01# show clock\n"
        "12:00:00\n"
        "leaf02# show running-config\n"
        "hostname leaf02\n"
        "interface Ethernet1/1\n"
        "  description leaf01 Ethernet1/1\n"
        "leaf02#\n",
        encoding="utf-8",
    )
    hosts = _inventory(tmp_path / "hosts.yaml")
    result = import_running_configs(
        input_dir=source,
        input_format="nxos-transcript",
        hosts_path=hosts,
        output_dir=tmp_path / "imports",
        imported_at=NOW,
    )

    _inventory_path, configs, _lldp, _manifest = resolve_running_config_import(
        result["attempt_dir"]
    )
    assert set(configs) == {"leaf01", "leaf02"}
    assert "show clock" not in configs["leaf01"].read_text(encoding="utf-8")
