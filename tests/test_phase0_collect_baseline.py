from datetime import datetime
import logging
from pathlib import Path

from alred.collect import CommandResult
from alred.cli import (
    build_command_artifact_filename,
    build_collect_output_path,
    collect_from_host,
    get_run_input_dir,
    list_collect_output_files,
    resolve_collect_output_path,
)
from alred.health.manifest import build_collect_manifest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "collect" / "synthetic"


def test_collect_output_path_uses_hostname_suffix_and_format(tmp_path):
    assert build_collect_output_path(tmp_path, "leaf01", "run", None) == (
        tmp_path / "leaf01_run.txt"
    )
    assert build_collect_output_path(tmp_path, "leaf01", "run", "json") == (
        tmp_path / "leaf01_run.json"
    )
    long_name = build_command_artifact_filename(1, "show " + "x" * 300)
    assert len(long_name.encode("utf-8")) < 255
    assert long_name == build_command_artifact_filename(
        1, "show " + "x" * 300
    )


def test_run_input_prefers_config_subdirectory():
    assert get_run_input_dir(FIXTURE_ROOT) == FIXTURE_ROOT / "config"
    assert list_collect_output_files(FIXTURE_ROOT / "config", "run") == [
        FIXTURE_ROOT / "config" / "leaf01_run.txt"
    ]


def test_collect_resolver_prefers_json_when_both_formats_exist(tmp_path):
    text_path = tmp_path / "leaf01_run.txt"
    json_path = tmp_path / "leaf01_run.json"
    text_path.write_text("text", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    assert resolve_collect_output_path(tmp_path, "leaf01", "run") == json_path
    assert list_collect_output_files(tmp_path, "run") == [json_path]


def test_synthetic_transcript_preserves_hostname_and_command_boundaries():
    transcript = (
        FIXTURE_ROOT / "show_lists" / "leaf01" / "leaf01_shows.log"
    ).read_text(encoding="utf-8")

    assert transcript.count("### COMMAND:") == 2
    assert "leaf01# show version" in transcript
    assert "leaf01# show system config reload-pending" in transcript


def test_collect_writes_command_files_and_manifest_prefers_them(
    tmp_path, monkeypatch
):
    class FakeCollector:
        def run_command(self, command, read_timeout):
            return CommandResult(
                command=command,
                ok=True,
                output=f"output for {command}\n",
                transport="ssh",
                output_format="text",
            )

        def close(self):
            return None

    monkeypatch.setattr(
        "alred.cli.build_collector",
        lambda *_args, **_kwargs: FakeCollector(),
    )
    show_root = tmp_path / "raw" / "show_lists"
    collect_from_host(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
        },
        username="admin",
        password="admin",
        enable_secret="",
        lldp_output_dir=str(tmp_path / "raw" / "lldp"),
        run_output_dir=str(tmp_path / "raw" / "config"),
        before_run_input_dir=str(tmp_path / "raw" / "config"),
        show_output_dir=str(show_root),
        policy={"collect_running_config_for": []},
        logger=logging.getLogger("test.collect"),
        transport="ssh",
        show_commands=["show version", "show clock"],
        show_only=True,
        old_generation_id="20260810120000",
    )

    command_root = show_root / "leaf01" / "commands"
    version_path = command_root / "001_show_version.txt"
    clock_path = command_root / "002_clock.txt"
    assert version_path.is_file()
    assert clock_path.is_file()
    assert "show clock" not in version_path.read_text(encoding="utf-8")
    assert "show version" not in clock_path.read_text(encoding="utf-8")
    assert (show_root / "leaf01" / "leaf01_shows.log").is_file()

    now = datetime.fromisoformat("2026-08-10T12:00:00+09:00")
    manifest = build_collect_manifest(
        [tmp_path / "raw"],
        collection_id="COL-1",
        change_id="CHG-1",
        phase="before",
        profiles=["network-baseline-nxos"],
        started_at=now,
        completed_at=now,
        timezone="Asia/Tokyo",
    )
    commands = manifest["spec"]["hosts"]["leaf01"]["commands"]
    assert Path(commands["show_version"]["file"]) == version_path
    assert Path(commands["clock"]["file"]) == clock_path
