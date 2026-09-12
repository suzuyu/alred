"""Offline synthetic interface state evidence, joins, and collection integration."""

from copy import deepcopy
from datetime import datetime
import json
import logging
from pathlib import Path
import shutil

import pytest

from alred.cli import build_parser, cmd_health_check_phase, collect_from_host
from alred.collect import CommandResult
from alred.health.commands import command_id
from alred.health.evaluator import compare_snapshots, evaluate_snapshot
from alred.health.manifest import build_collect_manifest
from alred.health.parsers import NXOS_PARSER_VERSION, ParserError, parse_nxos_command
from alred.health.profile import resolve_profiles
from alred.health.report import render_health_checklist
from alred.health.role_commands import build_role_command_groups
from alred.health.snapshot import SnapshotBuildError, build_health_snapshot
from alred.health.transcript import import_nxos_transcripts
from alred.operation import open_operation_workspace


NOW = datetime.fromisoformat("2026-09-12T12:00:00+09:00")
FIXTURE = Path(__file__).parent / "fixtures/nxos/show_interface/synthetic.txt"


@pytest.fixture
def resolved():
    return resolve_profiles(
        ["network-baseline-nxos"],
        change_id="DETAIL",
        resolved_at=NOW,
        timezone="Asia/Tokyo",
    )


def _status(rows):
    return "Port Name Status Vlan Duplex Speed Type\n" + "".join(
        f"{name} -- {state} 1 auto auto --\n" for name, state in rows
    )


def _detail(admin="down", oper="down", name="Ethernet1/3"):
    return f"{name} is {oper} (XCVR not inserted)\nadmin state is {admin}, Dedicated Interface\n  Hardware: Ethernet\n"


def _snapshot(
    tmp_path,
    resolved,
    *,
    rows=None,
    detail=None,
    adapter="collect",
    phase="before",
    status="OK",
):
    root = tmp_path / phase
    root.mkdir(parents=True, exist_ok=True)
    outputs = {"show interface status": _status(rows or [("Eth1/3", "xcvrAbsen")])}
    if detail is not None:
        outputs["show interface"] = detail
    if adapter == "collect":
        path = root / "leaf01_shows.log"
        path.write_text(
            "\n".join(
                f"### COMMAND: {command}\n### COLLECTED_AT: {NOW.isoformat()}\n"
                f"### STATUS: {status if command == 'show interface' else 'OK'}\n### TRANSPORT: ssh\n"
                f"leaf01# {command}\n{output}\n"
                for command, output in outputs.items()
            )
        )
        manifest = build_collect_manifest(
            [root],
            collection_id=f"DETAIL-{phase}",
            change_id="DETAIL",
            phase=phase,
            profiles=["network-baseline-nxos"],
            started_at=NOW,
            completed_at=NOW,
            timezone="Asia/Tokyo",
        )
    else:
        path = root / "transcript.log"
        path.write_text(
            "\n".join(
                f"leaf01# terminal length 0 ; {command} | no-more\n{output}"
                for command, output in outputs.items()
            )
            + "\nleaf01#\n"
        )
        hosts = root / "hosts.yaml"
        hosts.write_text("all:\n  hosts:\n    leaf01:\n      device_type: nxos\n")
        _, manifest = import_nxos_transcripts(
            [path],
            collection_id=f"DETAIL-{phase}",
            change_id="DETAIL",
            phase=phase,
            profiles=["network-baseline-nxos"],
            imported_at=NOW,
            timezone="Asia/Tokyo",
            hosts_path=hosts,
        )
    # The CLI pins inventory platforms before Snapshot construction.
    manifest["spec"]["hosts"]["leaf01"]["platform"] = "nxos"
    return build_health_snapshot(
        manifest,
        profile_refs=["network-baseline-nxos"],
        created_at=NOW,
        timezone="Asia/Tokyo",
        profile_sha256=resolved["spec"]["resolved"]["effective_sha256"],
    )


def _evaluate(snapshot, resolved, before=None):
    if before is None:
        result = evaluate_snapshot(snapshot, resolved, started_at=NOW, completed_at=NOW)
    else:
        result = compare_snapshots(
            before, snapshot, resolved, started_at=NOW, completed_at=NOW
        )
    # Also exercise result schema and Checklist rendering, without raw output.
    assert "Hardware: Ethernet" not in render_health_checklist(result)
    return next(
        check for check in result["checks"] if check["check_id"] == "interface_health"
    )


@pytest.mark.parametrize("adapter", ["collect", "transcript"])
@pytest.mark.parametrize("phase", ["before", "after", "rollback"])
@pytest.mark.parametrize("admin,expected", [("up", "FAIL"), ("down", "PASS")])
def test_explicit_admin_state_and_absolute_evidence(
    tmp_path, resolved, adapter, phase, admin, expected
):
    snapshot = _snapshot(
        tmp_path, resolved, detail="\n" + _detail(admin), adapter=adapter, phase=phase
    )
    original = deepcopy(snapshot)
    check = _evaluate(snapshot, resolved)
    assert check["result"] == expected
    assert check["after"]["interfaces"]["Eth1/3"]["admin_state"] == admin
    source = snapshot["hosts"]["leaf01"]["sources"]["interface_detail"]
    record = snapshot["hosts"]["leaf01"]["common"]["interface_details"]["Ethernet1/3"]
    raw_lines = Path(source["file"]).read_text().splitlines()
    assert (
        raw_lines[record["line_start"] - 1] == "Ethernet1/3 is down (XCVR not inserted)"
    )
    assert (
        source["output_start_line"]
        <= record["line_start"]
        <= record["line_end"]
        <= source["output_end_line"]
    )
    evidence = next(
        item for item in check["evidence"] if item.get("interface") == "Eth1/3"
    )
    assert evidence["sha256"] == source["sha256"]
    assert evidence["parser_version"] == NXOS_PARSER_VERSION
    assert evidence["line_start"] == record["line_start"]
    assert evidence["collected_at"] == source["collected_at"]
    assert snapshot == original


def test_detail_parser_scope_lines_case_and_unknown_reason():
    common, _ = parse_nxos_command("interface_detail", FIXTURE.read_text())
    details = common["interface_details"]
    assert set(details) == {
        "Ethernet1/1",
        "Ethernet1/2",
        "Ethernet1/3/1",
        "Ethernet1/4",
    }
    assert details["Ethernet1/1"]["admin_state"] == "up"
    assert details["Ethernet1/2"]["operational_state"] == "down"
    assert details["Ethernet1/3/1"]["down_reason"] == "new reason from future release"
    assert details["Ethernet1/4"]["parse_status"] == "unknown"
    assert (
        details["Ethernet1/4"]["admin_state"] == "unknown"
    )  # Do not steal mgmt admin.


@pytest.mark.parametrize(
    "output",
    [
        "",
        "% Invalid command",
        "Error: unsupported",
        '{"TABLE_interface": {}}',
        "Vlan1 is down\nadmin state is down\n",
        _detail() + "Ethernet1/5 BROKEN HEADER\nadmin state is up\n",
        "admin state is up\n" + _detail(),
    ],
)
def test_unusable_whole_source(output):
    with pytest.raises(ParserError):
        parse_nxos_command("interface_detail", output)


@pytest.mark.parametrize(
    "bad",
    [
        "Ethernet1/4 is down\n",
        "Ethernet1/4 is down\nadmin state is maybe\n",
        "Ethernet1/4 is down\nadmin state is up\nadmin state is down\n",
        "Ethernet1/4 is pending\nadmin state is down\n",
        _detail(name="Ethernet1/4") + _detail("up", name="Eth1/4"),
    ],
)
def test_partial_source_preserves_valid_ports(tmp_path, resolved, bad):
    snapshot = _snapshot(tmp_path, resolved, detail=_detail() + bad)
    host = snapshot["hosts"]["leaf01"]
    assert host["sources"]["interface_detail"]["parse_status"] == "unknown"
    assert host["sources"]["interface_detail"]["partial_records"] is True
    assert host["collection_status"] == "partial"
    assert host["parse_warnings"]
    assert (
        host["common"]["interface_details"]["Ethernet1/4"]["parse_status"] == "unknown"
    )
    assert _evaluate(snapshot, resolved)["result"] == "PASS"
    host["common"]["interfaces"]["Eth1/4"] = {
        "status": "sfpAbsent",
        "admin_state": "up",
        "operational_state": "down",
    }
    check = _evaluate(snapshot, resolved)
    assert check["result"] == "UNKNOWN"
    assert check["after"]["admin_state_unknown"] == ["Eth1/4"]


@pytest.mark.parametrize(
    "primary,admin,oper,expected",
    [
        ("connected", "up", "up", "PASS"),
        ("disabled", "down", "down", "PASS"),
        ("notconnect", "down", "down", "PASS"),
        ("notconnect", "up", "down", "FAIL"),
        ("connected", "up", "down", "UNKNOWN"),
        ("disabled", "up", "down", "UNKNOWN"),
        ("connected", "down", "up", "UNKNOWN"),
        ("xcvrAbsen", "up", "up", "UNKNOWN"),
    ],
)
def test_conflict_priority(tmp_path, resolved, primary, admin, oper, expected):
    snapshot = _snapshot(
        tmp_path, resolved, rows=[("Eth1/3", primary)], detail=_detail(admin, oper)
    )
    check = _evaluate(snapshot, resolved)
    assert check["result"] == expected
    assert bool(check["after"]["interface_state_conflicts"]) == (expected == "UNKNOWN")


@pytest.mark.parametrize(
    "detail,status",
    [
        (None, "OK"),
        ("% Invalid command", "OK"),
        (_detail(), "ERROR"),
        ("Ethernet1/3 is down\n", "OK"),
        (_detail(name="Ethernet1/3/1"), "OK"),
    ],
)
def test_missing_or_unusable_detail_never_reinstates_old_admin_inference(
    tmp_path, resolved, detail, status
):
    snapshot = _snapshot(tmp_path, resolved, detail=detail, status=status)
    host = snapshot["hosts"]["leaf01"]
    host["common"]["interfaces"]["Eth1/3"]["admin_state"] = "up"
    original = deepcopy(snapshot)
    assert _evaluate(snapshot, resolved)["result"] == "UNKNOWN"
    assert snapshot == original


@pytest.mark.parametrize(
    "key,value",
    [
        ("admin_state", []),
        ("operational_state", "pending"),
        ("line_start", True),
        ("line_end", 100000),
        ("down_reason", {}),
        ("parse_status", "unknown"),
        ("parse_warning", "bad"),
    ],
)
def test_invalid_nested_detail_is_not_used(tmp_path, resolved, key, value):
    snapshot = _snapshot(tmp_path, resolved, detail=_detail())
    snapshot["hosts"]["leaf01"]["common"]["interface_details"]["Ethernet1/3"][key] = (
        value
    )
    assert _evaluate(snapshot, resolved)["result"] == "UNKNOWN"


@pytest.mark.parametrize("duplicate_source", ["interfaces", "interface_details"])
def test_duplicate_primary_or_detail_alias_is_ambiguous(
    tmp_path, resolved, duplicate_source
):
    snapshot = _snapshot(tmp_path, resolved, detail=_detail())
    records = snapshot["hosts"]["leaf01"]["common"][duplicate_source]
    records["Ethernet1/3" if duplicate_source == "interfaces" else "Eth1/3"] = deepcopy(
        next(iter(records.values()))
    )
    check = _evaluate(snapshot, resolved)
    assert check["result"] == "UNKNOWN"
    assert (
        check["after"]["interface_state_conflicts"]["Eth1/3"]
        == "ambiguous interface identity"
    )


@pytest.mark.parametrize(
    "before_status,before_detail,after_status,after_detail,expected",
    [
        ("connected", _detail("up", "up"), "xcvrAbsen", _detail(), "FAIL"),
        ("connected", None, "xcvrAbsen", None, "FAIL"),
        ("xcvrAbsen", _detail(), "xcvrAbsen", _detail(), "PASS"),
        ("connected", _detail("up", "down"), "xcvrAbsen", _detail(), "UNKNOWN"),
        ("connected", _detail("up", "up"), "xcvrAbsen", _detail("up", "up"), "UNKNOWN"),
        ("disabled", None, "xcvrAbsen", None, "UNKNOWN"),
    ],
)
def test_comparison_uses_trusted_operational_states(
    tmp_path,
    resolved,
    before_status,
    before_detail,
    after_status,
    after_detail,
    expected,
):
    before = _snapshot(
        tmp_path, resolved, rows=[("Eth1/3", before_status)], detail=before_detail
    )
    after = _snapshot(
        tmp_path,
        resolved,
        rows=[("Eth1/3", after_status)],
        detail=after_detail,
        phase="after",
    )
    originals = deepcopy((before, after))
    check = _evaluate(after, resolved, before)
    assert check["result"] == expected
    if expected == "FAIL":
        assert check["classification"] == "regression"
    assert {item["collection_id"] for item in check["evidence"]} == {
        "DETAIL-before",
        "DETAIL-after",
    }
    assert (before, after) == originals


@pytest.mark.parametrize("phase", ["before", "after"])
def test_corrupt_primary_blocks_comparison(tmp_path, resolved, phase):
    before = _snapshot(
        tmp_path, resolved, rows=[("Eth1/3", "connected")], detail=_detail("up", "up")
    )
    after = _snapshot(tmp_path, resolved, detail=_detail(), phase="after")
    (before if phase == "before" else after)["hosts"]["leaf01"]["sources"][
        "interface_status"
    ]["parse_status"] = "unknown"
    assert _evaluate(after, resolved, before)["result"] == "UNKNOWN"


def test_confirmed_failure_and_conflicts_both_visible(tmp_path, resolved):
    snapshot = _snapshot(
        tmp_path,
        resolved,
        rows=[("Eth1/3", "xcvrAbsen"), ("Eth1/4", "connected")],
        detail=_detail("up") + _detail("up", name="Ethernet1/4"),
    )
    check = _evaluate(snapshot, resolved)
    assert check["result"] == "FAIL"
    assert check["after"]["admin_state_unknown"] == ["Eth1/4"]
    assert "Eth1/4" in check["message"]


def test_large_output_and_detail_only_ports(tmp_path, resolved):
    snapshot = _snapshot(
        tmp_path,
        resolved,
        detail="".join(_detail(name=f"Ethernet1/{port}") for port in range(1, 1025)),
    )
    check = _evaluate(snapshot, resolved)
    assert check["result"] == "PASS"
    assert set(check["after"]["interfaces"]) == {"Eth1/3"}
    assert len(check["after"]["unmatched_interface_details"]) == 1023


@pytest.mark.parametrize(
    "profiles", [["network-baseline-nxos"], ["network-baseline-nxos", "nxos-overlay"]]
)
@pytest.mark.parametrize(
    "roles",
    [
        None,
        {
            "schema_version": 2,
            "role_detection": {
                "leaf": {"functions": {"vtep": {}}},
                "spine": {"functions": {"evpn-route-reflector": {}}},
            },
        },
    ],
)
def test_command_is_optional_common_and_deduplicated(profiles, roles):
    resolved = resolve_profiles(
        profiles, change_id="DETAIL", resolved_at=NOW, timezone="Asia/Tokyo"
    )
    effective = resolved["spec"]["resolved"]["effective"]
    commands = effective["spec"]["collectors"]["nxos"]["commands"]
    assert [c for c in commands if c["id"] == "interface_detail"] == [
        {"id": "interface_detail", "command": "show interface", "required": False}
    ]
    groups = build_role_command_groups(effective, roles)
    assert groups["device_type:nxos"].count("show interface") == 1
    assert (
        sum(cmd == "show interface" for group in groups.values() for cmd in group) == 1
    )
    legacy = deepcopy(effective)
    legacy["spec"]["collectors"]["nxos"]["commands"] = [
        c for c in commands if c["id"] != "interface_detail"
    ]
    assert all(
        "show interface" not in commands
        for commands in build_role_command_groups(legacy, roles).values()
    )


@pytest.mark.parametrize(
    "command,expected",
    [
        ("show interface", "interface_detail"),
        ("terminal length 0 ; SHOW INTERFACE | no-more", "interface_detail"),
        ("show interface status", "interface_status"),
        ("show interface brief", "interface_brief"),
        ("show interface counters table", "interface_counters_table"),
        ("show interface Ethernet1/3", "unsupported_show_interface_ethernet1_3"),
        ("show interface | include admin", "unsupported_show_interface_include_admin"),
    ],
)
def test_command_matching_is_exact(command, expected):
    assert command_id(command) == expected


@pytest.mark.parametrize("failed", [False, True])
def test_shared_collector_saves_detail_artifact_and_timeout(
    tmp_path, resolved, monkeypatch, failed
):
    calls = []

    class FakeCollector:
        def run_command(self, command, read_timeout):
            calls.append((command, read_timeout))
            is_detail = command == "show interface"
            return CommandResult(
                command=command,
                ok=not (failed and is_detail),
                output=_detail() if is_detail else _status([("Eth1/3", "xcvrAbsen")]),
                error="read timeout" if failed and is_detail else None,
                transport="ssh",
                output_format="text",
            )

        def close(self):
            pass

    monkeypatch.setattr("alred.cli.build_collector", lambda *a, **kw: FakeCollector())
    root = tmp_path / "raw"
    collect_from_host(
        {"hostname": "leaf01", "ip": "192.0.2.1", "device_type": "nxos"},
        username="fixture",
        password="",
        enable_secret="",
        lldp_output_dir=str(root / "lldp"),
        run_output_dir=str(root / "config"),
        before_run_input_dir=str(root / "config"),
        show_output_dir=str(root / "show_lists"),
        policy={"collect_running_config_for": []},
        logger=logging.getLogger("test.interface-detail"),
        transport="ssh",
        show_commands=["show interface", "show interface status"],
        show_only=True,
        show_read_timeout=37,
    )
    assert calls == [("show interface", 37), ("show interface status", 37)]
    manifest = build_collect_manifest(
        [root],
        collection_id="DETAIL-before",
        change_id="DETAIL",
        phase="before",
        profiles=["network-baseline-nxos"],
        started_at=NOW,
        completed_at=NOW,
        timezone="Asia/Tokyo",
        host_platforms={"leaf01": "nxos"},
    )
    source = manifest["spec"]["hosts"]["leaf01"]["commands"]["interface_detail"]
    assert Path(source["file"]).name == "001_interface_detail.txt"
    snapshot = build_health_snapshot(
        manifest,
        profile_refs=["network-baseline-nxos"],
        created_at=NOW,
        timezone="Asia/Tokyo",
        profile_sha256=resolved["spec"]["resolved"]["effective_sha256"],
    )
    assert _evaluate(snapshot, resolved)["result"] == ("UNKNOWN" if failed else "PASS")
    if failed:
        assert "interface_details" not in snapshot["hosts"]["leaf01"]["common"]


@pytest.mark.parametrize("stage", ["collection", "parser", "prepublication"])
@pytest.mark.parametrize("purpose", ["change", "inspection"])
def test_failed_retry_preserves_current_and_previous_evidence(
    tmp_path, resolved, monkeypatch, capsys, stage, purpose
):
    import alred.cli as cli

    _snapshot(tmp_path / "input", resolved, detail=_detail())
    raw_input = tmp_path / "input/before/leaf01_shows.log"
    hosts = tmp_path / "hosts.yaml"
    hosts.write_text("all:\n  hosts:\n    leaf01:\n      device_type: nxos\n")
    operations = tmp_path / "operations"
    failing = False
    collected = []
    real_builder, real_write = cli.build_health_snapshot, cli.atomic_write_json

    def fake_collect(args, _logger, old_generation_id=None):
        assert (
            Path(args.show_commands_file)
            .read_text()
            .splitlines()
            .count("show interface")
            == 1
        )
        root = Path(args.output)
        root.mkdir(parents=True)
        shutil.copyfile(raw_input, root / raw_input.name)
        collected.append(root)
        if failing and stage == "collection":
            raise OSError("synthetic collection interruption")

    def build(manifest, **kwargs):
        if failing and stage == "parser":
            source = manifest["spec"]["hosts"]["leaf01"]["commands"]["interface_detail"]
            Path(source["file"]).write_text("synthetic source drift")
        return real_builder(manifest, **kwargs)

    def write(root, path, document, **kwargs):
        if (
            failing
            and stage == "prepublication"
            and Path(path).name == "health-result.json"
        ):
            raise OSError("synthetic publication interruption")
        return real_write(root, path, document, **kwargs)

    monkeypatch.setattr(cli, "run_collect", fake_collect)
    monkeypatch.setattr(cli, "build_health_snapshot", build)
    monkeypatch.setattr(cli, "atomic_write_json", write)

    def run():
        args = build_parser().parse_args(
            [
                "health-check",
                "before",
                "--collect",
                "--hosts",
                str(hosts),
                "--change-id",
                "DETAIL",
                "--profile",
                "network-baseline-nxos",
                "--logging-days",
                "1",
                "--operations-root",
                str(operations),
                "--purpose",
                purpose,
            ]
        )
        return cmd_health_check_phase(args)

    run()
    phase_root = (
        open_operation_workspace(operations, "DETAIL").operation_root / "health/before"
    )
    current_path = phase_root / "current.json"
    original_current = current_path.read_bytes()
    current = json.loads(original_current)
    original_artifacts = {
        path: path.read_bytes()
        for path in Path(current["artifact_dir"]).rglob("*")
        if path.is_file()
    }
    failing = True
    with pytest.raises((SystemExit, SnapshotBuildError, OSError)):
        run()
    assert current_path.read_bytes() == original_current
    assert all(
        path.read_bytes() == content for path, content in original_artifacts.items()
    )
    results = [
        json.loads(path.read_text())
        for path in phase_root.glob("attempts/*/result.json")
    ]
    assert sorted(item["status"] for item in results) == ["COMPLETED", "FAILED"]
    assert "Traceback" not in capsys.readouterr().err
    failing = False
    run()
    assert len(set(collected)) == 3
    assert json.loads(current_path.read_text())["attempt_id"] != current["attempt_id"]
    assert len(list(phase_root.glob("attempts/*/result.json"))) == 3


def test_duplicate_status_row_is_not_silently_overwritten():
    with pytest.raises(ParserError, match="duplicate interface status row"):
        parse_nxos_command(
            "interface_status",
            _status([("Eth1/3", "connected"), ("Eth1/3", "disabled")]),
        )


def test_duplicate_detail_blocks_conflict_even_for_connected_port(tmp_path, resolved):
    snapshot = _snapshot(
        tmp_path,
        resolved,
        rows=[("Eth1/3", "connected")],
        detail=_detail("up", "up") + _detail("up", "up", name="Eth1/3"),
    )
    assert _evaluate(snapshot, resolved)["result"] == "UNKNOWN"
