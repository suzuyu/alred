import logging

import pytest

from alred import cli


HOST = {
    "hostname": "leaf01",
    "ip": "192.0.2.10",
    "device_type": "nxos",
}


class FakeConnection:
    def __init__(self, *, config_outputs=None, save_output="Copy complete."):
        self.config_outputs = iter(config_outputs or [])
        self.save_output = save_output
        self.config_calls = []
        self.save_calls = []
        self.exit_config_mode_calls = 0
        self.disconnect_calls = 0

    def send_config_set(self, commands, **kwargs):
        self.config_calls.append((commands, kwargs))
        result = next(self.config_outputs)
        if isinstance(result, Exception):
            raise result
        return result

    def exit_config_mode(self):
        self.exit_config_mode_calls += 1

    def find_prompt(self):
        return "leaf01#"

    def send_command(self, command, **kwargs):
        self.save_calls.append((command, kwargs))
        return self.save_output

    def disconnect(self):
        self.disconnect_calls += 1


def _patch_connection(monkeypatch, connection):
    monkeypatch.setattr(cli, "connect_to_host", lambda *args, **kwargs: connection)


def test_push_config_dir_connection_filter_is_scoped_and_value_safe(tmp_path):
    config_path = tmp_path / "leaf01"
    config_path.write_text(
        """\
username admin password 0 AdminSecret role network-admin
no username admin
username admin-backup password 0 BackupSecret role network-admin
vrf context management
  ip route 0.0.0.0/0 192.0.2.1
  shutdown
vrf context TENANT-A
  vni 50001
interface mgmt0
  vrf member management
  ip address 192.0.2.10/24
logging source-interface mgmt0
ntp source-interface mgmt0
interface Ethernet1/1
  description uplink
line vty 0 4
  exec-timeout 0
  access-class MGMT in
line console
  exec-timeout 0
""",
        encoding="utf-8",
    )

    lines, findings = cli.prepare_push_config_dir_lines(
        config_path,
        device_type="nxos",
        login_username="admin",
    )

    assert lines == [
        "username admin-backup password 0 BackupSecret role network-admin",
        "vrf context TENANT-A",
        "vni 50001",
        "logging source-interface mgmt0",
        "ntp source-interface mgmt0",
        "interface Ethernet1/1",
        "description uplink",
        "line console",
        "exec-timeout 0",
    ]
    assert findings == [
        {
            "rule_id": "current_login_user",
            "line_count": 2,
            "sample": "username admin <redacted>",
        },
        {
            "rule_id": "management_vrf",
            "line_count": 3,
            "sample": "vrf context management",
        },
        {
            "rule_id": "management_interface",
            "line_count": 3,
            "sample": "interface mgmt0",
        },
        {
            "rule_id": "line_vty",
            "line_count": 3,
            "sample": "line vty 0 4",
        },
    ]


def test_push_config_dir_force_includes_connection_sensitive_config(tmp_path):
    config_path = tmp_path / "leaf01"
    config_path.write_text(
        """\
username admin password 0 AdminSecret role network-admin
interface mgmt0
  ip address 192.0.2.10/24
logging source-interface mgmt0
""",
        encoding="utf-8",
    )

    lines, findings = cli.prepare_push_config_dir_lines(
        config_path,
        device_type="nxos",
        login_username="admin",
        force=True,
    )

    assert lines == cli.load_config_lines(str(config_path))
    assert [item["rule_id"] for item in findings] == [
        "current_login_user",
        "management_interface",
    ]


def test_push_config_dir_rejects_ambiguous_flattened_protected_section(tmp_path):
    config_path = tmp_path / "leaf01"
    config_path.write_text(
        "interface mgmt0\nip address 192.0.2.10/24\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing indentation"):
        cli.prepare_push_config_dir_lines(
            config_path,
            device_type="nxos",
            login_username="admin",
        )

    lines, findings = cli.prepare_push_config_dir_lines(
        config_path,
        device_type="nxos",
        login_username="admin",
        force=True,
    )
    assert lines == ["interface mgmt0", "ip address 192.0.2.10/24"]
    assert findings[0]["rule_id"] == "management_interface"


def test_push_config_dir_filters_standalone_management_reset_commands(tmp_path):
    config_path = tmp_path / "leaf01"
    config_path.write_text(
        """\
no vrf context management
default interface mgmt0
default line vty 0 4
logging source-interface mgmt0
""",
        encoding="utf-8",
    )

    lines, findings = cli.prepare_push_config_dir_lines(
        config_path,
        device_type="nxos",
        login_username="admin",
    )

    assert lines == ["logging source-interface mgmt0"]
    assert [item["rule_id"] for item in findings] == [
        "management_vrf",
        "management_interface",
        "line_vty",
    ]


@pytest.mark.parametrize("force", [False, True])
def test_push_config_dir_applies_filter_before_confirmation(
    tmp_path,
    monkeypatch,
    capsys,
    force,
):
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        """\
all:
  hosts:
    leaf01:
      ansible_host: 192.0.2.10
      device_type: nxos
""",
        encoding="utf-8",
    )
    input_dir = tmp_path / "config"
    input_dir.mkdir()
    (input_dir / "leaf01").write_text(
        """\
username admin password 0 MustNotBePrinted role network-admin
interface mgmt0
  ip address 192.0.2.10/24
logging source-interface mgmt0
""",
        encoding="utf-8",
    )
    observed = []

    def push(_host, _username, _password, _enable, lines, *_args):
        observed.append(lines)
        return "SUCCESS"

    monkeypatch.setattr(cli, "push_config_to_host", push)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    arguments = [
        "push-config-dir",
        "--hosts",
        str(hosts_path),
        "--input-dir",
        str(input_dir),
        "--username",
        "admin",
        "--password",
        "admin",
        "--skip-connect-check",
        "--workers",
        "1",
        "--log-file",
        str(tmp_path / "push.log"),
    ]
    if force:
        arguments.append("--force")

    result = cli.cmd_push_config_dir(cli.build_parser().parse_args(arguments))
    output = capsys.readouterr().out

    assert result["pushed_hosts"] == ["leaf01"]
    assert "MustNotBePrinted" not in output
    assert "MustNotBePrinted" not in (tmp_path / "push.log").read_text(
        encoding="utf-8"
    )
    assert "current_login_user" in output
    assert "management_interface" in output
    assert "logging source-interface mgmt0" in observed[0]
    assert ("username admin password" in "\n".join(observed[0])) is force
    assert ("interface mgmt0" in observed[0]) is force
    assert ("WARNING: --force" in output) is force


def test_push_sends_one_line_at_a_time_and_disconnects(monkeypatch):
    connection = FakeConnection(config_outputs=["ok-1", "ok-2"])
    _patch_connection(monkeypatch, connection)

    cli.push_config_to_host(
        HOST,
        "user",
        "password",
        "",
        ["vlan 10", "name SERVERS"],
        logging.getLogger("test-push"),
    )

    assert [call[0] for call in connection.config_calls] == [
        ["vlan 10"],
        ["name SERVERS"],
    ]
    assert connection.config_calls[0][1] == {
        "read_timeout": 120,
        "enter_config_mode": True,
        "exit_config_mode": False,
    }
    assert connection.config_calls[1][1]["enter_config_mode"] is False
    assert connection.exit_config_mode_calls == 1
    assert connection.disconnect_calls == 1

def test_push_stops_after_first_transport_exception(monkeypatch):
    connection = FakeConnection(
        config_outputs=["ok-1", TimeoutError("synthetic timeout"), "not-used"]
    )
    _patch_connection(monkeypatch, connection)

    with pytest.raises(TimeoutError, match="synthetic timeout"):
        cli.push_config_to_host(
            HOST,
            "user",
            "password",
            "",
            ["line 1", "line 2", "line 3"],
            logging.getLogger("test-push-error"),
        )

    assert [call[0] for call in connection.config_calls] == [
        ["line 1"],
        ["line 2"],
    ]
    assert connection.exit_config_mode_calls == 0
    assert connection.disconnect_calls == 1


def test_direct_push_detects_cli_error_by_default(monkeypatch, caplog):
    connection = FakeConnection(
        config_outputs=["% Invalid command at '^' marker.", "not-used"]
    )
    _patch_connection(monkeypatch, connection)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="CLI error"):
            cli.push_config_to_host(
                HOST,
                "user",
                "password",
                "",
                ["invalid line", "must not run"],
                logging.getLogger("test-push-strict"),
            )

    assert len(connection.config_calls) == 1
    assert connection.disconnect_calls == 1
    assert (
        "PUSH CLI FAILED host=leaf01 line=1/2 command=invalid line "
        "error=% Invalid command at '^' marker."
    ) in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_expected_cli_host_failure_log_has_no_traceback(caplog):
    with caplog.at_level(logging.ERROR):
        cli._log_push_host_failure(
            logging.getLogger("test-push-host-failure"),
            "leaf01",
            cli.ConfigPushCliError("synthetic CLI error"),
        )

    assert "PUSH HOST FAILED host=leaf01 error=synthetic CLI error" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_cli_failure_logs_five_previous_safe_commands(monkeypatch, caplog):
    commands = [
        "hostname leaf01",
        "feature lacp",
        "interface Ethernet1/48",
        "interface Ethernet1/49",
        "username lab-user password 0 ClearSecret role network-admin",
        "lacp rate fast",
        "switchport mode trunk",
    ]
    connection = FakeConnection(
        config_outputs=[
            "ok-1",
            "ok-2",
            "ok-3",
            "ok-4",
            "ok-5",
            "ok-6",
            "% Invalid command at '^' marker.",
        ]
    )
    _patch_connection(monkeypatch, connection)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(cli.ConfigPushCliError):
            cli.push_config_to_host(
                HOST,
                "user",
                "password",
                "",
                commands,
                logging.getLogger("test-push-context"),
            )

    context_messages = [
        record.getMessage()
        for record in caplog.records
        if "PUSH CLI CONTEXT" in record.getMessage()
    ]
    assert len(context_messages) == 5
    assert "line=2/7 status=SUCCESS command=feature lacp" in context_messages[0]
    assert "line=6/7 status=SUCCESS command=lacp rate fast" in context_messages[-1]
    assert all("hostname leaf01" not in message for message in context_messages)
    assert "ClearSecret" not in caplog.text
    assert "<redacted>" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_fail_fast_with_one_worker_does_not_start_next_host():
    started = []

    def operation(hostname):
        started.append(hostname)
        raise cli.ConfigPushCliError("synthetic CLI error")

    successes, failures, not_started = cli._execute_host_operation_batches(
        ["leaf01", "leaf02", "leaf03"],
        operation,
        workers=1,
        fail_fast=True,
    )

    assert successes == []
    assert [item for item, _exc in failures] == ["leaf01"]
    assert not_started == ["leaf02", "leaf03"]
    assert started == ["leaf01"]


def test_fail_fast_finishes_current_worker_batch_only():
    started = []

    def operation(hostname):
        started.append(hostname)
        if hostname == "leaf01":
            raise cli.ConfigPushCliError("synthetic CLI error")
        return "SUCCESS"

    successes, failures, not_started = cli._execute_host_operation_batches(
        ["leaf01", "leaf02", "leaf03"],
        operation,
        workers=2,
        fail_fast=True,
    )

    assert [item for item, _result in successes] == ["leaf02"]
    assert [item for item, _exc in failures] == ["leaf01"]
    assert not_started == ["leaf03"]
    assert sorted(started) == ["leaf01", "leaf02"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["push-config", "--config-file", "config.txt", "--fail-fast"],
        ["push-config-dir", "--input-dir", "config", "--fail-fast"],
        [
            "clab-apply-config",
            "--topology",
            "topology.clab.yaml",
            "--input-dir",
            "config",
            "--fail-fast",
        ],
    ],
)
def test_push_commands_accept_fail_fast(arguments):
    args = cli.build_parser().parse_args(arguments)

    assert args.fail_fast is True


def test_direct_push_ignore_all_records_status_and_continues(monkeypatch, caplog):
    connection = FakeConnection(
        config_outputs=["% Invalid command at '^' marker.", "ok"]
    )
    _patch_connection(monkeypatch, connection)

    with caplog.at_level(logging.WARNING):
        status = cli.push_config_to_host(
            HOST,
            "user",
            "password",
            "",
            ["invalid line", "second line"],
            logging.getLogger("test-push-ignore"),
            ignore_all_cli_errors=True,
        )

    assert status == "IGNORED_ERROR"
    assert len(connection.config_calls) == 2
    assert connection.disconnect_calls == 1
    assert (
        "PUSH CLI IGNORED_ERROR host=leaf01 line=1/2 command=invalid line "
        "error=% Invalid command at '^' marker."
    ) in caplog.text


def test_direct_push_ignore_all_logs_context_for_each_error(monkeypatch, caplog):
    commands = [
        "hostname leaf01",
        "interface Ethernet1/49",
        "description to-leaf02",
        "switchport mode trunk",
        "lacp rate fast",
        "switchport trunk allowed vlan 103",
    ]
    connection = FakeConnection(
        config_outputs=[
            "ok-1",
            "ok-2",
            "ok-3",
            "% Invalid command at '^' marker.",
            "ok-5",
            "% Invalid command at '^' marker.",
        ]
    )
    _patch_connection(monkeypatch, connection)

    with caplog.at_level(logging.WARNING):
        status = cli.push_config_to_host(
            HOST,
            "user",
            "password",
            "",
            commands,
            logging.getLogger("test-push-ignore-context"),
            ignore_all_cli_errors=True,
        )

    ignored_messages = [
        record.getMessage()
        for record in caplog.records
        if "PUSH CLI IGNORED_ERROR" in record.getMessage()
    ]
    context_messages = [
        record.getMessage()
        for record in caplog.records
        if "PUSH CLI CONTEXT" in record.getMessage()
    ]
    assert status == "IGNORED_ERROR"
    assert len(ignored_messages) == 2
    assert "line=4/6 command=switchport mode trunk" in ignored_messages[0]
    assert "line=6/6 command=switchport trunk allowed vlan 103" in ignored_messages[1]
    assert any("line=3/6 status=SUCCESS command=description to-leaf02" in message for message in context_messages)
    assert any("line=5/6 status=SUCCESS command=lacp rate fast" in message for message in context_messages)


def test_save_uses_nxos_command_and_success_marker(monkeypatch):
    connection = FakeConnection(save_output="Copy complete.\nleaf01#")
    _patch_connection(monkeypatch, connection)

    cli.save_config_on_host(
        HOST,
        "user",
        "password",
        "",
        logging.getLogger("test-save"),
    )

    assert connection.save_calls[0][0] == "copy running-config startup-config"
    assert connection.save_calls[0][1]["read_timeout"] == 180
    assert connection.save_calls[0][1]["cmd_verify"] is False
    assert connection.disconnect_calls == 1


def test_save_rejects_output_without_success_marker(monkeypatch):
    connection = FakeConnection(save_output="% Error: synthetic failure")
    _patch_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="success marker"):
        cli.save_config_on_host(
            HOST,
            "user",
            "password",
            "",
            logging.getLogger("test-save-error"),
        )

    assert connection.disconnect_calls == 1
