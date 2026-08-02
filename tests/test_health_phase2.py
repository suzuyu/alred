from datetime import datetime
import json
from pathlib import Path
import shutil

import pytest
import yaml

from alred.cli import (
    _archive_legacy_rollback_attempt,
    _direct_health_collect,
    _publish_rollback_attempt,
    _snapshot_workspace,
    _start_rollback_attempt,
    build_parser,
    cmd_health_check_phase,
    cmd_health_check_snapshot,
    main,
)
from alred.health.manifest import build_collect_manifest
from alred.health.execution_context import HealthExecutionContextError
from alred.health.profile import ProfileResolutionError, load_resolved_profiles
from alred.health.parsers import ParserError, parse_nxos_command
from alred.health.snapshot import (
    SnapshotBuildError,
    build_health_snapshot,
)
from alred.health.transcript import (
    TranscriptImportError,
    import_nxos_transcripts,
)
from alred.operation import (
    OperationLock,
    OperationStateError,
    load_operation_metadata,
    open_operation_workspace,
    transition_phase,
    transition_workflow,
)
from alred.qualification import QualificationError


JST_NOW = datetime.fromisoformat("2026-08-01T10:02:03+09:00")
NXOS_FIXTURES = Path(__file__).parent / "fixtures" / "nxos"
COLLECT_FIXTURE = Path(__file__).parent / "fixtures" / "collect" / "synthetic"

COMMAND_FIXTURES = {
    "show version": (NXOS_FIXTURES / "show_version" / "c9300v_10_5_4.txt"),
    "show processes cpu": (NXOS_FIXTURES / "show_processes_cpu" / "c9300v_10_5_4.txt"),
    "show system resources": (
        NXOS_FIXTURES / "show_system_resources" / "c9300v_10_5_4.txt"
    ),
    "show system config reload-pending": (
        NXOS_FIXTURES / "show_reload_pending" / "c9300v_10_5_4_no_pending.txt"
    ),
    "show logging": (NXOS_FIXTURES / "show_logging" / "c9300v_10_5_4_healthy.txt"),
    "show vpc brief": (NXOS_FIXTURES / "show_vpc_brief" / "c9300v_10_5_4_healthy.txt"),
    "show nve interface": (
        NXOS_FIXTURES / "show_nve_interface" / "c9300v_10_5_4_up.txt"
    ),
    "show bgp l2vpn evpn summary": (
        NXOS_FIXTURES / "show_bgp_summary" / "c9300v_10_5_4_evpn_healthy.txt"
    ),
}


def _write_collect_transcript(path):
    sections = ["### COMMAND_LIST", *COMMAND_FIXTURES, ""]
    for index, (command, fixture) in enumerate(COMMAND_FIXTURES.items()):
        sections.extend(
            [
                f"### COMMAND: {command}",
                (f"### COLLECTED_AT: 2026-08-01T10:02:{index:02d}+09:00"),
                "### STATUS: OK",
                "### TRANSPORT: ssh",
                f"leaf01# {command}",
                fixture.read_text(encoding="utf-8").rstrip(),
                "",
            ]
        )
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(sections), encoding="utf-8")


def _write_external_transcript(path):
    sections = []
    for command, fixture in COMMAND_FIXTURES.items():
        sections.extend(
            [
                f"LAB-LEAF-01# terminal length 0 ; {command} | no-more",
                fixture.read_text(encoding="utf-8").rstrip(),
                "",
            ]
        )
    path.write_text("\n".join(sections), encoding="utf-8")


def _build_collect_snapshot(tmp_path):
    collect_root = tmp_path / "collect"
    transcript = collect_root / "show_lists" / "leaf01" / "leaf01_shows.log"
    _write_collect_transcript(transcript)
    manifest = build_collect_manifest(
        [collect_root],
        collection_id="CHG-1-before-001",
        change_id="CHG-1",
        phase="before",
        profiles=["network-baseline-nxos", "nxos-overlay"],
        started_at=JST_NOW,
        completed_at=JST_NOW,
        timezone="Asia/Tokyo",
    )
    snapshot = build_health_snapshot(
        manifest,
        profile_refs=["network-baseline-nxos", "nxos-overlay"],
        created_at=JST_NOW,
        timezone="Asia/Tokyo",
    )
    return manifest, snapshot


def test_collect_adapter_and_nxos_parsers_build_canonical_snapshot(tmp_path):
    manifest, snapshot = _build_collect_snapshot(tmp_path)

    assert manifest["spec"]["hosts"]["leaf01"]["status"] == "success"
    leaf = snapshot["hosts"]["leaf01"]
    assert leaf["collection_status"] == "success"
    assert leaf["common"]["system"]["version"] == "10.5(4)"
    assert leaf["common"]["cpu"] == {
        "five_seconds_percent": 75.0,
        "interrupt_percent": 2.0,
        "one_minute_percent": 50.0,
        "five_minutes_percent": 40.0,
    }
    assert leaf["common"]["resources"]["memory"]["status"] == "OK"
    assert leaf["common"]["reload_pending"] == {
        "required": False,
        "commands": [],
    }
    logging = leaf["common"]["logging"]
    assert len(logging["records"]) == 1
    assert logging["records"][0]["severity"] == 5
    assert logging["parse_warnings"] == []
    assert leaf["common"]["vpc"]["healthy"] is True
    assert leaf["profiles"]["nxos-overlay"]["nve_interface"]["state"] == "Up"
    neighbors = leaf["common"]["routing_neighbors"]["bgp_evpn"]["neighbors"]
    assert neighbors["192.0.2.253"]["state"] == "Established"
    assert neighbors["192.0.2.253"]["prefixes_received"] == 56
    assert all(
        source["parse_status"] == "parsed" for source in leaf["sources"].values()
    )


def test_logging_parser_marks_unrecognized_timestamp_as_warning():
    common, _profiles = parse_nxos_command(
        "show_logging",
        "Jul 29 09:45:00 leaf01 %APP-3-ERROR: malformed timestamp",
        timezone="Asia/Tokyo",
    )

    assert common["logging"]["records"] == []
    assert common["logging"]["parse_warnings"] == [
        "syslog records were present but timestamps were not recognized"
    ]


def test_external_transcript_matches_inventory_alias_and_same_state(tmp_path):
    _collect_manifest, collect_snapshot = _build_collect_snapshot(tmp_path)
    transcript_path = tmp_path / "external.log"
    _write_external_transcript(transcript_path)
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        "leaf01": {
                            "device_type": "nxos",
                            "aliases": ["LAB-LEAF-01"],
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    import_manifest, collection_manifest = import_nxos_transcripts(
        [transcript_path],
        collection_id="CHG-1-before-002",
        change_id="CHG-1",
        phase="before",
        profiles=["network-baseline-nxos", "nxos-overlay"],
        imported_at=JST_NOW,
        timezone="Asia/Tokyo",
        hosts_path=hosts_path,
    )
    transcript_snapshot = build_health_snapshot(
        collection_manifest,
        profile_refs=["network-baseline-nxos", "nxos-overlay"],
        created_at=JST_NOW,
        timezone="Asia/Tokyo",
    )

    host_import = import_manifest["spec"]["hosts"]["leaf01"]
    assert host_import["matched_by"] == "alias"
    assert host_import["detected_prompts"] == ["LAB-LEAF-01"]
    assert import_manifest["spec"]["summary"]["commands_detected"] == 8
    assert (
        transcript_snapshot["hosts"]["leaf01"]["common"]
        == collect_snapshot["hosts"]["leaf01"]["common"]
    )
    assert (
        transcript_snapshot["hosts"]["leaf01"]["profiles"]
        == collect_snapshot["hosts"]["leaf01"]["profiles"]
    )


def test_external_transcript_tracks_preamble_and_duplicate_as_unknown(tmp_path):
    transcript = tmp_path / "duplicate.log"
    version = COMMAND_FIXTURES["show version"].read_text(encoding="utf-8")
    transcript.write_text(
        "unattributed preamble\n"
        f"leaf01# show version\n{version}\n"
        f"leaf01# show version\n{version}\n",
        encoding="utf-8",
    )

    import_manifest, collection_manifest = import_nxos_transcripts(
        [transcript],
        collection_id="CHG-1-before-003",
        change_id="CHG-1",
        phase="before",
        profiles=["baseline"],
        imported_at=JST_NOW,
        timezone="Asia/Tokyo",
    )

    summary = import_manifest["spec"]["summary"]
    assert summary["unresolved_segments"] == 1
    assert summary["ambiguous_segments"] == 2
    command = collection_manifest["spec"]["hosts"]["leaf01"]["commands"]["show_version"]
    assert command["status"] == "failed"
    assert command["confidence"] == "low"
    snapshot = build_health_snapshot(
        collection_manifest,
        profile_refs=["baseline"],
        created_at=JST_NOW,
        timezone="Asia/Tokyo",
    )
    assert snapshot["hosts"]["leaf01"]["collection_status"] == "failed"
    assert (
        snapshot["hosts"]["leaf01"]["sources"]["show_version"]["parse_status"]
        == "unknown"
    )


def test_inventory_alias_collision_fails_closed(tmp_path):
    transcript = tmp_path / "external.log"
    transcript.write_text("shared# show version\noutput\n", encoding="utf-8")
    hosts = tmp_path / "hosts.yaml"
    hosts.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        "leaf01": {"aliases": ["shared"]},
                        "leaf02": {"aliases": ["shared"]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TranscriptImportError, match="ambiguous"):
        import_nxos_transcripts(
            [transcript],
            collection_id="CHG-1-before-004",
            change_id="CHG-1",
            phase="before",
            profiles=["baseline"],
            imported_at=JST_NOW,
            timezone="Asia/Tokyo",
            hosts_path=hosts,
        )


def test_snapshot_rejects_source_drift_after_manifest(tmp_path):
    manifest, _snapshot = _build_collect_snapshot(tmp_path)
    record = manifest["spec"]["hosts"]["leaf01"]["commands"]["show_version"]
    Path(record["file"]).write_text("changed\n", encoding="utf-8")

    with pytest.raises(SnapshotBuildError, match="hash mismatch"):
        build_health_snapshot(
            manifest,
            profile_refs=["network-baseline-nxos", "nxos-overlay"],
            created_at=JST_NOW,
            timezone="Asia/Tokyo",
        )


def test_collect_manifest_prefers_running_config_text_over_json_sidecar(
    tmp_path,
):
    collected = tmp_path / "collect"
    config = collected / "config"
    config.mkdir(parents=True)
    (config / "leaf01_run.json").write_text(
        '{"structured": true}\n',
        encoding="utf-8",
    )
    text_path = config / "leaf01_run.txt"
    text_path.write_text(
        "hostname leaf01\nfeature nv overlay\n",
        encoding="utf-8",
    )
    manifest = build_collect_manifest(
        [collected],
        collection_id="CHG-1-before-dual",
        change_id="CHG-1",
        phase="before",
        profiles=["nxos-overlay"],
        started_at=JST_NOW,
        completed_at=JST_NOW,
        timezone="Asia/Tokyo",
    )

    record = manifest["spec"]["hosts"]["leaf01"]["commands"]["running_config"]
    assert record["status"] == "success"
    assert Path(record["file"]) == text_path.resolve()


def test_health_snapshot_cli_is_offline_and_writes_operation_artifacts(
    tmp_path,
    capsys,
):
    operations_root = tmp_path / "operations"
    args = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--phase",
            "before",
            "--change-id",
            "CHG-1",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_snapshot(args)

    output = capsys.readouterr().out
    phase_dir = operations_root / "CHG-1" / "health" / "before"
    assert "=== HEALTH SNAPSHOT SUMMARY ===" in output
    assert (phase_dir / "collection-manifest.yaml").is_file()
    snapshot_path = phase_dir / "snapshot.json"
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["change_id"] == "CHG-1"
    assert snapshot["hosts"]["leaf01"]["collection_status"] == "partial"
    resolved = yaml.safe_load(
        (operations_root / "CHG-1" / "health" / "resolved-profiles.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert resolved["spec"]["resolved"]["profile_names"] == ["network-baseline-nxos"]
    assert resolved["spec"]["requested"][0]["resolution_source"] == "default"


def test_health_before_and_after_offline_wrappers_share_snapshot_path(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-1",
            "--operations-root",
            str(operations_root),
        ]
    )
    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-1",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_phase(before)
    cmd_health_check_phase(after)

    operation = operations_root / "CHG-1" / "health"
    assert (operation / "before" / "snapshot.json").is_file()
    assert (operation / "after" / "snapshot.json").is_file()
    assert (operation / "report" / "health-result.json").is_file()


def _offline_before_args(
    operations_root,
    *,
    profiles=("network-baseline-nxos",),
    input_path=COLLECT_FIXTURE,
    reason=None,
):
    argv = [
            "health-check",
            "before",
            "--input",
            str(input_path),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-RETRY",
            "--operations-root",
            str(operations_root),
        ]
    for profile in profiles:
        argv.extend(["--profile", profile])
    if reason is not None:
        argv.extend(["--revision-reason", reason])
    return build_parser().parse_args(argv)


def test_health_before_warn_or_completed_can_create_new_attempt(tmp_path):
    operations_root = tmp_path / "operations"

    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    first_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    first_snapshot = Path(first_current["snapshot_path"])
    first_sha256 = first_current["snapshot_sha256"]

    cmd_health_check_phase(_offline_before_args(operations_root))

    second_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    attempts = list((operation / "health/before/attempts").iterdir())
    metadata = load_operation_metadata(operation)
    assert len(attempts) == 2
    assert second_current["attempt_id"] != first_current["attempt_id"]
    assert first_snapshot.is_file()
    assert first_current["snapshot_sha256"] == first_sha256
    assert Path(second_current["snapshot_path"]).is_file()
    assert metadata["spec"]["phases"]["before"]["status"] in {
        "completed",
        "completed_with_warnings",
    }
    assert (operation / "health/before/snapshot.json").read_bytes() == Path(
        second_current["snapshot_path"]
    ).read_bytes()


def test_health_before_retry_rejects_changed_profile(tmp_path):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    original_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )

    with pytest.raises(ProfileResolutionError):
        cmd_health_check_phase(
            _offline_before_args(operations_root, profiles=("nxos-overlay",))
        )

    current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    assert current == original_current
    assert len(list((operation / "health/before/attempts").iterdir())) == 1


def test_health_before_retry_is_blocked_after_plan_artifact(tmp_path):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    plan_path = operation / "plan/execution-plan.json"
    plan_path.parent.mkdir()
    plan_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(OperationStateError, match="after plan"):
        cmd_health_check_phase(_offline_before_args(operations_root))


def test_health_before_explicit_profile_revision_preserves_old_attempt(tmp_path):
    operations_root = tmp_path / "operations"
    override = tmp_path / "logging-excludes.yaml"
    override.write_text(
        """\
api_version: alred/v1
kind: HealthCheckProfile
metadata:
  name: test-logging-excludes
  version: "1.0"
spec:
  platforms: [nxos]
  thresholds:
    logging:
      exclude_patterns: [known harmless event]
""",
        encoding="utf-8",
    )
    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    first_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )

    cmd_health_check_phase(
        _offline_before_args(
            operations_root,
            profiles=("network-baseline-nxos", str(override)),
            reason="Exclude one reviewed lab-only logging event",
        )
    )

    second_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    revised_dir = Path(second_current["artifact_dir"])
    revision = json.loads((revised_dir / "profile-revision.json").read_text())
    old_profile = yaml.safe_load(
        (
            Path(first_current["artifact_dir"]) / "resolved-profiles.yaml"
        ).read_text()
    )
    fixed_profile = yaml.safe_load(
        (operation / "health/resolved-profiles.yaml").read_text()
    )
    assert first_current["profile_sha256"] != second_current["profile_sha256"]
    assert first_current["attempt_id"] != second_current["attempt_id"]
    assert revision["reason"] == "Exclude one reviewed lab-only logging event"
    assert revision["previous"]["effective_sha256"] == first_current[
        "profile_sha256"
    ]
    assert revision["revised"]["effective_sha256"] == second_current[
        "profile_sha256"
    ]
    assert revision["changes"]
    assert old_profile["spec"]["resolved"]["profile_names"] == [
        "network-baseline-nxos"
    ]
    assert fixed_profile["spec"]["resolved"]["profile_names"] == [
        "network-baseline-nxos",
        "test-logging-excludes",
    ]


def test_health_before_profile_revision_requires_reason(tmp_path):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    attempt_count = len(list((operation / "health/before/attempts").iterdir()))

    with pytest.raises(ProfileResolutionError, match="revision-reason"):
        cmd_health_check_phase(
            _offline_before_args(
                operations_root,
                profiles=("network-baseline-nxos", "nxos-overlay"),
            )
        )

    assert len(list((operation / "health/before/attempts").iterdir())) == attempt_count


def test_revision_reason_requires_existing_profile_difference(tmp_path):
    operations_root = tmp_path / "operations"
    with pytest.raises(ProfileResolutionError, match="existing completed before"):
        cmd_health_check_phase(
            _offline_before_args(
                operations_root,
                reason="No previous profile exists",
            )
        )

    cmd_health_check_phase(_offline_before_args(operations_root))
    with pytest.raises(ProfileResolutionError, match="did not change"):
        cmd_health_check_phase(
            _offline_before_args(
                operations_root,
                reason="No effective change",
            )
        )


def test_failed_profile_revision_keeps_previous_current_and_profile(tmp_path):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(_offline_before_args(operations_root))
    operation = operations_root / "CHG-RETRY"
    original_current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    original_profile = (
        operation / "health/resolved-profiles.yaml"
    ).read_bytes()

    with pytest.raises(SystemExit):
        cmd_health_check_phase(
            _offline_before_args(
                operations_root,
                profiles=("network-baseline-nxos", "nxos-overlay"),
                input_path=tmp_path / "missing-input",
                reason="Add Overlay checks before plan",
            )
        )

    current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    attempts = [
        json.loads((path / "result.json").read_text())
        for path in (operation / "health/before/attempts").iterdir()
    ]
    assert current == original_current
    assert (operation / "health/resolved-profiles.yaml").read_bytes() == original_profile
    assert any(
        attempt["status"] == "FAILED" and attempt.get("profile_revision")
        for attempt in attempts
    )


def test_profile_mismatch_from_main_has_no_traceback(
    tmp_path,
    monkeypatch,
    capsys,
):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(_offline_before_args(operations_root))
    monkeypatch.setattr(
        "sys.argv",
        [
            "alred.py",
            "health-check",
            "before",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-RETRY",
            "--profile",
            "nxos-overlay",
            "--operations-root",
            str(operations_root),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "VALIDATION_ERROR" in stderr
    assert "Traceback" not in stderr


def test_health_before_help_exposes_profile_revision_options(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["health-check", "before", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--revise-profile" not in output
    assert "--revision-reason" in output
    assert "default: ssh" in " ".join(output.split())


def test_health_followup_collection_transport_is_resolved_from_context():
    before = build_parser().parse_args(
        ["health-check", "before", "--collect"]
    )
    rollback = build_parser().parse_args(
        [
            "health-check",
            "rollback",
            "--collect",
            "--change-id",
            "CHG-1",
        ]
    )
    after = build_parser().parse_args(
        ["health-check", "after", "--collect", "--change-id", "CHG-1"]
    )

    assert before.transport == "ssh"
    assert rollback.transport is None
    assert after.transport is None


def test_after_can_collect_emergency_evidence_while_rollback_required(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-EMERGENCY",
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)
    workspace = open_operation_workspace(
        operations_root,
        "CHG-EMERGENCY",
    )
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
            "apply_failed",
            "rollback_required",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-EMERGENCY",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_phase(after)

    assert (workspace.operation_root / "health/after/snapshot.json").is_file()
    assert (
        load_operation_metadata(workspace.operation_root)["spec"]["workflow_state"]
        == "rollback_required"
    )


def test_health_before_collect_reuses_existing_runner(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )
    observed = {}

    def fake_collect(args, _logger, old_generation_id=None):
        observed["args"] = args
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)
    args = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(hosts_path),
            "--change-id",
            "CHG-1",
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_phase(args)

    phase_root = operations_root / "CHG-1" / "health" / "before"
    commands = (phase_root / "show-commands.txt").read_text(encoding="utf-8")
    assert observed["args"].command == "collect"
    assert observed["args"].run_config_only is True
    assert commands.startswith("[device_type:nxos]\n")
    assert "show version" in commands
    assert "show logging" in commands
    assert "show running-config" not in commands
    assert (phase_root / "raw").is_dir()
    assert (phase_root / "snapshot.json").is_file()


def test_health_before_collect_can_retry_completed_collection(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )
    calls = []

    def fake_collect(args, _logger, old_generation_id=None):
        calls.append(args.output)
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)

    def args():
        return build_parser().parse_args(
            [
                "health-check",
                "before",
                "--collect",
                "--hosts",
                str(hosts_path),
                "--change-id",
                "CHG-COLLECT-RETRY",
                "--profile",
                "network-baseline-nxos",
                "--logging-days",
                "1",
                "--operations-root",
                str(operations_root),
            ]
        )

    cmd_health_check_phase(args())
    cmd_health_check_phase(args())

    operation = operations_root / "CHG-COLLECT-RETRY"
    metadata = load_operation_metadata(operation)
    current = json.loads(
        (operation / "health/before/current.json").read_text()
    )
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert metadata["spec"]["phases"]["before_collect"]["status"] == "completed"
    assert metadata["spec"]["phases"]["before"]["status"] in {
        "completed",
        "completed_with_warnings",
    }
    assert len(list((operation / "health/before/attempts").iterdir())) == 2
    assert Path(current["artifact_dir"]).is_dir()


def test_health_before_collect_reuses_generated_change_id_for_snapshot(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )

    def fake_collect(args, _logger, old_generation_id=None):
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)
    args = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(hosts_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_phase(args)

    operations = [
        path
        for path in operations_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(operations) == 1
    assert args.change_id == operations[0].name
    assert (operations[0] / "health" / "before" / "raw").is_dir()
    assert (operations[0] / "health" / "before" / "snapshot.json").is_file()

    resolved = yaml.safe_load(
        (operations[0] / "health" / "resolved-profiles.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert resolved["spec"]["requested"][0]["resolution_source"] == "default"


def test_health_after_change_id_inherits_before_collect_context(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )
    observed = []

    def fake_collect(args, _logger, old_generation_id=None):
        observed.append(args)
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)
    monkeypatch.setattr("alred.cli.getpass", lambda _prompt: "prompted-secret")
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(hosts_path),
            "--change-id",
            "CHG-INHERIT",
            "--workers",
            "2",
            "--password",
            "must-not-be-persisted",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)

    context_path = operations_root / "CHG-INHERIT" / "health" / "execution-context.yaml"
    context_text = context_path.read_text(encoding="utf-8")
    context = yaml.safe_load(context_text)
    assert "must-not-be-persisted" not in context_text
    assert context["spec"]["input_mode"] == "collect"
    assert context["spec"]["inventory"]["path"] == str(hosts_path.resolve())
    assert context["spec"]["collection"]["transport"] == "ssh"
    assert context["spec"]["collection"]["workers"] == 2
    assert context["spec"]["authentication"]["password_was_cli"] is True

    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--change-id",
            "CHG-INHERIT",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(after)

    assert after.collect is True
    assert after.hosts == str(hosts_path.resolve())
    assert after.transport == "ssh"
    assert after.workers == 2
    assert after.ask_pass is True
    assert len(observed) == 2
    assert (
        operations_root / "CHG-INHERIT" / "health" / "after" / "snapshot.json"
    ).is_file()


def test_health_rollback_change_id_inherits_before_collect_context(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )

    def fake_collect(args, _logger, old_generation_id=None):
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(hosts_path),
            "--change-id",
            "CHG-ROLLBACK-INHERIT",
            "--workers",
            "2",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)

    observed = []

    def fake_direct_collect(args, workspace, resolved_profiles):
        observed.append(args)
        return workspace.operation_root / "health" / "rollback" / "raw"

    monkeypatch.setattr("alred.cli._direct_health_collect", fake_direct_collect)
    monkeypatch.setattr("alred.cli.cmd_health_check_snapshot", lambda args: 0)
    monkeypatch.setattr(
        "alred.cli._start_rollback_attempt",
        lambda args, workspace, resolved: {
            "attempt_id": "rollback-test",
            "artifact_dir": str(
                workspace.operation_root
                / "health/rollback/attempts/rollback-test"
            ),
        },
    )
    monkeypatch.setattr(
        "alred.cli._verify_and_publish_rollback_attempt",
        lambda workspace, attempt: (
            {
                "status": {
                    "result": "ROLLED_BACK_AND_VERIFIED",
                    "raw_config_equal": True,
                    "semantic_config_equal": True,
                }
            },
            workspace.operation_root / "rollback/verification.json",
            workspace.operation_root / "rollback/verification-checklist.md",
        ),
    )
    rollback = build_parser().parse_args(
        [
            "health-check",
            "rollback",
            "--change-id",
            "CHG-ROLLBACK-INHERIT",
            "--operations-root",
            str(operations_root),
        ]
    )

    assert cmd_health_check_phase(rollback) == 0
    assert rollback.collect is True
    assert rollback.hosts == str(hosts_path.resolve())
    assert rollback.transport == "ssh"
    assert rollback.workers == 2
    assert len(observed) == 1


def test_health_rollback_collect_retry_uses_new_attempt(tmp_path, monkeypatch):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(
        build_parser().parse_args(
            [
                "health-check",
                "before",
                "--input",
                str(COLLECT_FIXTURE),
                "--input-format",
                "alred-collect",
                "--change-id",
                "CHG-ROLLBACK-RETRY",
                "--operations-root",
                str(operations_root),
            ]
        )
    )
    workspace = open_operation_workspace(
        operations_root,
        "CHG-ROLLBACK-RETRY",
    )
    with OperationLock(workspace, "rollback-state", now=JST_NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
            "approved",
            "apply_running",
            "apply_completed",
            "after_running",
            "after_completed",
            "rollback_required",
            "rollback_running",
            "rolled_back",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
        for phase_name in ("rollback_collect", "rollback"):
            transition_phase(
                workspace,
                phase_name,
                "running",
                lock=lock,
                attempt_id=f"legacy-{phase_name}",
                now=JST_NOW,
            )
            transition_phase(
                workspace,
                phase_name,
                "completed",
                lock=lock,
                now=JST_NOW,
            )

    before_root = workspace.operation_root / "health/before"
    rollback_root = workspace.operation_root / "health/rollback"
    rollback_root.mkdir(parents=True)
    snapshot = json.loads((before_root / "snapshot.json").read_text())
    snapshot["phase"] = "rollback"
    (rollback_root / "snapshot.json").write_text(json.dumps(snapshot))
    shutil.copy2(
        before_root / "health-result.json",
        rollback_root / "health-result.json",
    )
    resolved = load_resolved_profiles(
        workspace.operation_root / "health/resolved-profiles.yaml"
    )
    args = build_parser().parse_args(
        [
            "health-check",
            "rollback",
            "--collect",
            "--change-id",
            "CHG-ROLLBACK-RETRY",
            "--hosts",
            str(tmp_path / "hosts.yaml"),
            "--operations-root",
            str(operations_root),
        ]
    )
    attempt = _start_rollback_attempt(args, workspace, resolved)
    args.phase = "rollback"
    _workspace, snapshot_output = _snapshot_workspace(args)
    assert snapshot_output == Path(attempt["artifact_dir"])
    assert snapshot_output.parent.parent.name == "rollback"
    monkeypatch.setattr(
        "alred.cli.run_collect",
        lambda collect_args, _logger: shutil.copytree(
            COLLECT_FIXTURE,
            collect_args.output,
            dirs_exist_ok=True,
        ),
    )

    raw_dir = _direct_health_collect(args, workspace, resolved)

    metadata = load_operation_metadata(workspace.operation_root)
    assert attempt["attempt_id"] != "legacy-rollback"
    assert args._health_retry is True
    assert str(raw_dir).startswith(attempt["artifact_dir"])
    assert metadata["spec"]["phases"]["rollback_collect"]["status"] == "completed"
    assert (
        metadata["spec"]["phases"]["rollback_collect"]["current_attempt"]
        != "legacy-rollback_collect"
    )
    assert (rollback_root / "attempts/legacy-rollback/result.json").is_file()


def test_archive_rollback_prefers_published_current_over_failed_phase_attempt(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(
        build_parser().parse_args(
            [
                "health-check",
                "before",
                "--input",
                str(COLLECT_FIXTURE),
                "--input-format",
                "alred-collect",
                "--change-id",
                "CHG-ROLLBACK-PARTIAL",
                "--operations-root",
                str(operations_root),
            ]
        )
    )
    workspace = open_operation_workspace(
        operations_root,
        "CHG-ROLLBACK-PARTIAL",
    )
    before_root = workspace.operation_root / "health/before"
    rollback_root = workspace.operation_root / "health/rollback"
    completed_id = "rollback-completed"
    completed_dir = rollback_root / "attempts" / completed_id
    completed_dir.mkdir(parents=True)
    shutil.copy2(before_root / "snapshot.json", completed_dir / "snapshot.json")
    snapshot = json.loads((completed_dir / "snapshot.json").read_text())
    snapshot["phase"] = "rollback"
    (completed_dir / "snapshot.json").write_text(json.dumps(snapshot))
    shutil.copy2(
        before_root / "health-result.json",
        completed_dir / "health-result.json",
    )
    shutil.copy2(completed_dir / "snapshot.json", rollback_root / "snapshot.json")
    shutil.copy2(
        completed_dir / "health-result.json",
        rollback_root / "health-result.json",
    )
    (rollback_root / "current.json").write_text(
        json.dumps({"attempt_id": completed_id})
    )
    failed_id = "rollback-failed"
    failed_dir = rollback_root / "attempts" / failed_id
    failed_dir.mkdir(parents=True)
    (failed_dir / "result.json").write_text(
        json.dumps({"attempt_id": failed_id, "status": "FAILED"})
    )
    metadata = {
        "spec": {
            "phases": {
                "rollback": {"current_attempt": failed_id},
            }
        }
    }

    _archive_legacy_rollback_attempt(workspace, metadata)

    current = json.loads((rollback_root / "current.json").read_text())
    assert current["attempt_id"] == completed_id
    assert (completed_dir / "result.json").is_file()
    assert not (failed_dir / "health-result.json").exists()


def test_health_rollback_verification_error_is_rendered_without_traceback(
    tmp_path,
    monkeypatch,
    capsys,
):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(
        build_parser().parse_args(
            [
                "health-check",
                "before",
                "--input",
                str(COLLECT_FIXTURE),
                "--input-format",
                "alred-collect",
                "--change-id",
                "CHG-ROLLBACK-ERROR",
                "--operations-root",
                str(operations_root),
            ]
        )
    )
    workspace = open_operation_workspace(
        operations_root,
        "CHG-ROLLBACK-ERROR",
    )
    attempt_dir = workspace.operation_root / "health/rollback/attempts/test"
    monkeypatch.setattr(
        "alred.cli._start_rollback_attempt",
        lambda args, operation, resolved: {
            "attempt_id": "test",
            "artifact_dir": str(attempt_dir),
        },
    )
    monkeypatch.setattr("alred.cli.cmd_health_check_snapshot", lambda args: 0)
    monkeypatch.setattr("alred.cli._fail_rollback_attempt", lambda *args: None)
    monkeypatch.setattr(
        "alred.cli._verify_and_publish_rollback_attempt",
        lambda *args: (_ for _ in ()).throw(
            QualificationError("managed artifact not found: snapshot.json")
        ),
    )
    rollback = build_parser().parse_args(
        [
            "health-check",
            "rollback",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-ROLLBACK-ERROR",
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_health_check_phase(rollback)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "QUALIFICATION_INVALID: managed artifact not found" in stderr
    assert "Traceback" not in stderr


def test_publish_rollback_attempt_updates_current_and_compatibility_paths(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    cmd_health_check_phase(
        build_parser().parse_args(
            [
                "health-check",
                "before",
                "--input",
                str(COLLECT_FIXTURE),
                "--input-format",
                "alred-collect",
                "--change-id",
                "CHG-PUBLISH-ROLLBACK",
                "--operations-root",
                str(operations_root),
            ]
        )
    )
    workspace = open_operation_workspace(
        operations_root,
        "CHG-PUBLISH-ROLLBACK",
    )
    resolved = load_resolved_profiles(
        workspace.operation_root / "health/resolved-profiles.yaml"
    )
    attempt_id = "rollback-attempt-002"
    attempt_dir = workspace.operation_root / "health/rollback/attempts" / attempt_id
    report_dir = (
        workspace.operation_root / "health/rollback-report/attempts" / attempt_id
    )
    verification_dir = (
        workspace.operation_root / "rollback/verification-attempts" / attempt_id
    )
    attempt_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    verification_dir.mkdir(parents=True)
    (attempt_dir / "snapshot.json").write_text("{}\n")
    (attempt_dir / "health-result.json").write_text(
        json.dumps({"result": "WARN"})
    )
    (attempt_dir / "checklist.md").write_text("attempt checklist\n")
    (report_dir / "health-result.json").write_text("{}\n")
    (report_dir / "summary.md").write_text("report\n")
    (verification_dir / "verification.json").write_text("{}\n")
    (verification_dir / "verification-checklist.md").write_text(
        "verification\n"
    )
    attempt = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "rollback",
        "attempt_id": attempt_id,
        "status": "RUNNING",
        "started_at": JST_NOW.isoformat(),
        "artifact_dir": str(attempt_dir),
        "profile_sha256": resolved["spec"]["resolved"]["effective_sha256"],
    }
    verification = {
        "metadata": {"verified_at": JST_NOW.isoformat()},
        "status": {"result": "ROLLBACK_HEALTH_FAILED"},
    }

    _publish_rollback_attempt(
        workspace,
        attempt,
        report_dir=report_dir,
        verification_dir=verification_dir,
        verification=verification,
    )

    current = json.loads(
        (workspace.operation_root / "health/rollback/current.json").read_text()
    )
    verification_current = json.loads(
        (
            workspace.operation_root / "rollback/verification-current.json"
        ).read_text()
    )
    assert current["attempt_id"] == attempt_id
    assert verification_current["attempt_id"] == attempt_id
    assert (
        workspace.operation_root / "health/rollback/checklist.md"
    ).read_text() == "attempt checklist\n"
    assert (
        workspace.operation_root / "rollback/verification-checklist.md"
    ).read_text() == "verification\n"


def test_health_after_rejects_changed_inherited_inventory(
    tmp_path,
    monkeypatch,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )

    def fake_collect(args, _logger, old_generation_id=None):
        shutil.copytree(COLLECT_FIXTURE, args.output, dirs_exist_ok=True)

    monkeypatch.setattr("alred.cli.run_collect", fake_collect)
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(hosts_path),
            "--change-id",
            "CHG-DRIFT",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf02:\n      device_type: nxos\n",
        encoding="utf-8",
    )
    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--change-id",
            "CHG-DRIFT",
            "--operations-root",
            str(operations_root),
        ]
    )

    with pytest.raises(HealthExecutionContextError, match="inventory hash"):
        cmd_health_check_phase(after)


def test_health_after_offline_before_requires_only_new_input_path(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--change-id",
            "CHG-OFFLINE",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)

    missing_input = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--change-id",
            "CHG-OFFLINE",
            "--operations-root",
            str(operations_root),
        ]
    )
    with pytest.raises(OperationStateError, match="before used offline input"):
        cmd_health_check_phase(missing_input)

    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--change-id",
            "CHG-OFFLINE",
            "--input",
            str(COLLECT_FIXTURE),
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(after)

    assert after.input_format == "alred-collect"
    assert (
        operations_root / "CHG-OFFLINE" / "health" / "after" / "snapshot.json"
    ).is_file()


def test_health_after_legacy_operation_accepts_explicit_input_options(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    legacy_before = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--phase",
            "before",
            "--change-id",
            "CHG-LEGACY",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_snapshot(legacy_before)
    assert not (
        operations_root / "CHG-LEGACY" / "health" / "execution-context.yaml"
    ).exists()

    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--change-id",
            "CHG-LEGACY",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(after)

    assert (
        operations_root / "CHG-LEGACY" / "health" / "after" / "snapshot.json"
    ).is_file()


def test_after_without_change_id_reuses_active_generated_before(
    tmp_path,
):
    operations_root = tmp_path / "operations"
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n",
        encoding="utf-8",
    )
    before = build_parser().parse_args(
        [
            "health-check",
            "before",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--hosts",
            str(hosts_path),
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(operations_root),
        ]
    )
    cmd_health_check_phase(before)
    active = yaml.safe_load(
        (operations_root / ".state" / "active-change.yaml").read_text(encoding="utf-8")
    )
    change_id = active["spec"]["change_id"]
    after = build_parser().parse_args(
        [
            "health-check",
            "after",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--hosts",
            str(hosts_path),
            "--operations-root",
            str(operations_root),
        ]
    )

    cmd_health_check_phase(after)

    assert after.change_id == change_id
    assert (
        operations_root / change_id / "health" / "after" / "snapshot.json"
    ).is_file()
    completed = yaml.safe_load(
        (operations_root / ".state" / "active-change.yaml").read_text(encoding="utf-8")
    )
    assert completed["spec"]["state"] == "completed"


def test_health_snapshot_after_requires_change_id(tmp_path, capsys):
    args = build_parser().parse_args(
        [
            "health-check",
            "snapshot",
            "--input",
            str(COLLECT_FIXTURE),
            "--input-format",
            "alred-collect",
            "--phase",
            "after",
            "--profile",
            "network-baseline-nxos",
            "--operations-root",
            str(tmp_path / "operations"),
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_health_check_snapshot(args)

    assert exc_info.value.code == 2
    assert "requires --change-id" in capsys.readouterr().err


@pytest.mark.parametrize(
    "output",
    [
        "",
        "% Invalid command at '^' marker.",
        "truncated and unrecognized",
    ],
)
def test_supported_parser_never_treats_unrecognized_output_as_healthy(output):
    with pytest.raises(ParserError):
        parse_nxos_command("processes_cpu", output)


def test_nve_vni_parser_does_not_merge_adjacent_rows():
    output = """\
Interface VNI      Multicast-group   State Mode Type [BD/VRF]      Flags
nve1      103901   UnicastBGP        Up    CP   L2 [3901]
nve1      903900   n/a               Up    CP   L3 [ALRED-LAB-01]
"""

    _common, profiles = parse_nxos_command("nve_vni", output)

    vnis = profiles["nxos-overlay"]["nve_vnis"]["vnis"]
    assert vnis["103901"]["type"] == "L2"
    assert vnis["103901"]["context"] == "3901"
    assert vnis["103901"]["flags"] == []
    assert vnis["903900"]["type"] == "L3"
    assert vnis["903900"]["context"] == "ALRED-LAB-01"


def test_collect_adapter_prefers_nested_current_show_log_over_root_mirror(
    tmp_path,
):
    root = tmp_path / "raw"
    nested = root / "show_lists" / "leaf01" / "leaf01_shows.log"
    mirror = root / "show_lists" / "leaf01_shows.log"
    _write_collect_transcript(nested)
    mirror.write_bytes(nested.read_bytes())

    manifest = build_collect_manifest(
        [root],
        collection_id="CHG-1-before-005",
        change_id="CHG-1",
        phase="before",
        profiles=["baseline"],
        started_at=JST_NOW,
        completed_at=JST_NOW,
        timezone="Asia/Tokyo",
    )

    assert manifest["spec"]["hosts"]["leaf01"]["status"] == "success"
    assert all(
        record["status"] == "success"
        for record in manifest["spec"]["hosts"]["leaf01"]["commands"].values()
    )
