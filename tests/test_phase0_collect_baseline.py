from datetime import datetime
import logging
from pathlib import Path

from alred.collect import CommandResult, SshCollector
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


def test_collect_reuses_base_lldp_for_canonical_command_artifact(
    tmp_path, monkeypatch
):
    executed = []

    class FakeCollector:
        def run_command(self, command, read_timeout):
            executed.append(command)
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
    raw_root = tmp_path / "raw"
    show_root = raw_root / "show_lists"
    collect_from_host(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
        },
        username="admin",
        password="admin",
        enable_secret="",
        lldp_output_dir=str(raw_root / "lldp"),
        run_output_dir=str(raw_root / "config"),
        before_run_input_dir=str(raw_root / "config"),
        show_output_dir=str(show_root),
        policy={"collect_running_config_for": []},
        logger=logging.getLogger("test.collect-lldp-command"),
        transport="ssh",
        show_commands=["show lldp neighbors detail", "show version"],
        old_generation_id="20260810120000",
    )

    assert executed == ["show lldp neighbors detail", "show version"]
    command_path = (
        show_root / "leaf01" / "commands" / "001_lldp_neighbors_detail.txt"
    )
    mirror_path = raw_root / "lldp" / "leaf01_lldp.txt"
    assert command_path.is_file()
    assert mirror_path.read_text(encoding="utf-8") == (
        "output for show lldp neighbors detail\n"
    )
    assert "### STATUS: OK" in command_path.read_text(encoding="utf-8")
    assert "show lldp neighbors detail" in (
        show_root / "leaf01" / "leaf01_shows.log"
    ).read_text(encoding="utf-8")

    now = datetime.fromisoformat("2026-08-10T12:00:00+09:00")
    manifest = build_collect_manifest(
        [raw_root],
        collection_id="COL-LLDP-1",
        change_id="CHG-LLDP-1",
        phase="before",
        profiles=["network-baseline-nxos"],
        started_at=now,
        completed_at=now,
        timezone="Asia/Tokyo",
    )
    record = manifest["spec"]["hosts"]["leaf01"]["commands"][
        "lldp_neighbors_detail"
    ]
    assert record["status"] == "success"
    assert record["source"] == "alred_collect"
    assert Path(record["file"]) == command_path


def test_collect_manifest_uses_legacy_lldp_only_without_command_artifact(
    tmp_path,
):
    lldp_path = tmp_path / "lldp" / "leaf01_lldp.txt"
    lldp_path.parent.mkdir(parents=True)
    lldp_path.write_text("legacy LLDP output\n", encoding="utf-8")
    now = datetime.fromisoformat("2026-08-10T12:00:00+09:00")

    manifest = build_collect_manifest(
        [tmp_path],
        collection_id="COL-LEGACY-1",
        change_id="CHG-LEGACY-1",
        phase="before",
        profiles=["network-baseline-nxos"],
        started_at=now,
        completed_at=now,
        timezone="Asia/Tokyo",
    )

    record = manifest["spec"]["hosts"]["leaf01"]["commands"][
        "lldp_neighbors_detail"
    ]
    assert record["source"] == "lldp"
    assert Path(record["file"]) == lldp_path


def test_ssh_collector_retries_session_initialization_once(monkeypatch):
    connections = []
    sleeps = []

    class FakeConnection:
        def send_command(self, command, **_kwargs):
            return f"output for {command}"

        def disconnect(self):
            return None

    def fake_connect_handler(**_kwargs):
        if not connections:
            connections.append("failed")
            raise RuntimeError("terminal length 0 prompt was not detected")
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr("alred.collect.ConnectHandler", fake_connect_handler)
    monkeypatch.setattr("alred.collect.time.sleep", sleeps.append)
    collector = SshCollector(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
            "netmiko_device_type": "cisco_nxos",
        },
        "admin",
        "password",
        "",
        logging.getLogger("test.ssh-retry"),
    )

    result = collector.run_command("show version", read_timeout=120)

    assert result.ok is True
    assert result.output == "output for show version"
    assert len(connections) == 2
    assert sleeps == [1]


def test_ssh_collector_does_not_retry_command_failure(monkeypatch):
    connect_calls = []

    class FakeConnection:
        def send_command(self, _command, **_kwargs):
            raise RuntimeError("read timeout after command send")

        def disconnect(self):
            return None

    def fake_connect_handler(**_kwargs):
        connect_calls.append(1)
        return FakeConnection()

    monkeypatch.setattr("alred.collect.ConnectHandler", fake_connect_handler)
    collector = SshCollector(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
            "netmiko_device_type": "cisco_nxos",
        },
        "admin",
        "password",
        "",
        logging.getLogger("test.ssh-no-command-retry"),
    )

    result = collector.run_command("show version", read_timeout=120)
    next_result = collector.run_command("show clock", read_timeout=120)

    assert result.ok is False
    assert result.error == "read timeout after command send"
    assert next_result.ok is False
    assert next_result.error == "read timeout after command send"
    assert connect_calls == [1]


def test_ssh_collector_reuses_one_session_for_multiple_commands(monkeypatch):
    connect_calls = []
    commands = []

    class FakeConnection:
        def send_command(self, command, **_kwargs):
            commands.append(command)
            return f"output for {command}"

        def disconnect(self):
            return None

    def fake_connect_handler(**_kwargs):
        connect_calls.append(1)
        return FakeConnection()

    monkeypatch.setattr("alred.collect.ConnectHandler", fake_connect_handler)
    collector = SshCollector(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
            "netmiko_device_type": "cisco_nxos",
        },
        "admin",
        "password",
        "",
        logging.getLogger("test.ssh-session-reuse"),
    )

    first = collector.run_command("show lldp neighbors detail", 120)
    second = collector.run_command("show running-config", 300)

    assert first.ok is True
    assert second.ok is True
    assert connect_calls == [1]
    assert commands == [
        "show lldp neighbors detail",
        "show running-config",
    ]


def test_failed_base_command_is_preserved_in_collection_manifest(
    tmp_path, monkeypatch
):
    class FakeCollector:
        def run_command(self, command, read_timeout):
            if command == "show lldp neighbors detail":
                return CommandResult(
                    command=command,
                    ok=False,
                    output="terminal length 0 prompt was not detected",
                    transport="ssh",
                    error="terminal length 0 prompt was not detected",
                )
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
    raw_root = tmp_path / "raw"
    stale_lldp = raw_root / "lldp" / "leaf01_lldp.txt"
    stale_lldp.parent.mkdir(parents=True)
    stale_lldp.write_text("stale previous-generation LLDP\n", encoding="utf-8")
    result = collect_from_host(
        {
            "hostname": "leaf01",
            "ip": "192.0.2.1",
            "device_type": "nxos",
        },
        username="admin",
        password="admin",
        enable_secret="",
        lldp_output_dir=str(raw_root / "lldp"),
        run_output_dir=str(raw_root / "config"),
        before_run_input_dir=str(raw_root / "config"),
        show_output_dir=str(raw_root / "show_lists"),
        policy={"collect_running_config_for": ["nxos"]},
        logger=logging.getLogger("test.collect-failed-command"),
        transport="ssh",
        show_commands=["show version"],
        old_generation_id="20260810120000",
    )

    manifest = build_collect_manifest(
        [raw_root],
        collection_id="COL-FAILED-1",
        change_id="CHG-FAILED-1",
        phase="before",
        profiles=["network-baseline-nxos"],
        started_at=datetime.fromisoformat("2026-08-10T12:00:00+09:00"),
        completed_at=datetime.fromisoformat("2026-08-10T12:01:00+09:00"),
        timezone="Asia/Tokyo",
    )

    record = manifest["spec"]["hosts"]["leaf01"]["commands"][
        "lldp_neighbors_detail"
    ]
    assert result["command_failure_count"] == 1
    assert record["status"] == "failed"
    assert record["error"] == "terminal length 0 prompt was not detected"
    assert manifest["spec"]["hosts"]["leaf01"]["status"] == "partial"
    assert not stale_lldp.exists()
