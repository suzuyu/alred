import re
from pathlib import Path

import yaml


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nxos"
METADATA_PATH = FIXTURE_ROOT / "metadata" / "c9300v_10_5_4.yaml"


def _load_metadata():
    return yaml.safe_load(METADATA_PATH.read_text(encoding="utf-8"))


def test_c9300v_metadata_references_existing_command_fixtures():
    metadata = _load_metadata()

    assert metadata["api_version"] == "alred/v1"
    assert metadata["kind"] == "NxosFixtureMetadata"
    assert metadata["metadata"]["source_type"] == "lab"
    assert metadata["metadata"]["sanitized"] is True
    assert metadata["spec"]["model"] == "Nexus 9000v C9300v"
    assert metadata["spec"]["release"] == "10.5(4)"

    commands = metadata["spec"]["commands"]
    assert len(commands) == 11
    for item in commands:
        fixture_path = (METADATA_PATH.parent / item["fixture"]).resolve()
        assert fixture_path.is_relative_to(FIXTURE_ROOT.resolve())
        assert fixture_path.is_file()
        assert fixture_path.read_text(encoding="utf-8").strip()


def test_c9300v_fixture_preserves_expected_observations():
    metadata = _load_metadata()
    expected = metadata["spec"]["expected"]
    version = (
        FIXTURE_ROOT / "show_version" / "c9300v_10_5_4.txt"
    ).read_text(encoding="utf-8")
    cpu = (
        FIXTURE_ROOT / "show_processes_cpu" / "c9300v_10_5_4.txt"
    ).read_text(encoding="utf-8")
    reload_pending = (
        FIXTURE_ROOT
        / "show_reload_pending"
        / "c9300v_10_5_4_no_pending.txt"
    ).read_text(encoding="utf-8")

    assert f"NXOS: version {expected['show_version']['release']}" in version
    assert "cisco Nexus9000 C9300v Chassis" in version
    assert (
        f"five seconds: {expected['cpu']['five_seconds_total_percent']}%"
        in cpu
    )
    assert "require copy r s + reload" in reload_pending
    reload_lines = reload_pending.strip().splitlines()
    assert reload_lines[1] == reload_lines[2]
    assert set(reload_lines[1]) == {"="}


def test_c9300v_fixture_has_no_known_sensitive_or_source_identifiers():
    fixture_text = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    )

    forbidden_patterns = [
        r"\\$[156]\\$",
        r"(?i)\\b(?:password|passwd)\\s+[0579]\\s+\\S+",
        r"(?i)\\busername\\s+(?:admin|cisco)\\b",
        r"(?i)\\bsnmp-server\\s+community\\b",
        r"(?i)\\b(?:private[-_ ]?key|api[-_ ]?token)\\b",
        r"\\blfsw\\d+\\b",
        r"\\bbgrt\\d+\\b",
        r"\\bspsw\\d+\\b",
    ]

    for pattern in forbidden_patterns:
        assert re.search(pattern, fixture_text) is None, pattern
