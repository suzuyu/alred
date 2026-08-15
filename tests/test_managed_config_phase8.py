from datetime import datetime, timedelta, timezone

import pytest

from alred.managed_config import (
    NXOS_CLAB_SSH_KEY_ALREADY_EXISTS_RULE_ID,
    build_nxos_clab_cli_error_allowlist,
    build_execution_document,
    execute_config_session,
    execute_save_session,
    execute_serial_devices,
    load_managed_config_commands,
    load_cli_error_allowlist,
    nxos_cli_error,
    redact_config_execution_result,
)


class FakeConnection:
    def __init__(self, config_outputs=(), save_output="Copy complete."):
        self.config_outputs = iter(config_outputs)
        self.save_output = save_output
        self.config_calls = []
        self.exit_calls = 0

    def send_config_set(self, commands, **kwargs):
        self.config_calls.append((commands, kwargs))
        value = next(self.config_outputs)
        if isinstance(value, Exception):
            raise value
        return value

    def exit_config_mode(self):
        self.exit_calls += 1

    def find_prompt(self):
        return "leaf01#"

    def send_command(self, command, **kwargs):
        return self.save_output


def _clock():
    current = datetime(2026, 7, 30, tzinfo=timezone(timedelta(hours=9)))

    def now():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return now


def test_nxos_error_patterns_do_not_treat_warning_as_failure():
    assert nxos_cli_error("% Invalid command at '^' marker.") is not None
    assert nxos_cli_error("ERROR: configuration rejected") is not None
    assert nxos_cli_error("Warning: interface is already up") is None


def test_managed_config_loader_removes_control_and_comment_lines(tmp_path):
    config = tmp_path / "leaf01.cfg"
    config.write_text(
        """\
! generated
configure terminal
vlan 3901
  name ALRED-LAB
!
end
""",
        encoding="utf-8",
    )

    assert load_managed_config_commands(config) == [
        "vlan 3901",
        "name ALRED-LAB",
    ]


def test_managed_config_loader_rejects_prohibited_commands(tmp_path):
    config = tmp_path / "leaf01.cfg"
    config.write_text("reload\n", encoding="utf-8")

    with pytest.raises(ValueError, match="prohibited"):
        load_managed_config_commands(config)


def test_managed_session_records_each_success_response():
    connection = FakeConnection(["ok one", "ok two"])
    result = execute_config_session(
        connection,
        ["vlan 3901", "name ALRED-LAB"],
        now=_clock(),
    )

    assert result["status"] == "SUCCESS"
    assert [item["status"] for item in result["commands"]] == [
        "SUCCESS",
        "SUCCESS",
    ]
    assert result["commands"][0]["response"] == "ok one"
    assert connection.exit_calls == 1


def test_managed_session_stops_on_cli_error_and_marks_remaining_not_started():
    connection = FakeConnection(
        ["ok", "% Invalid command at '^' marker.", "must not be sent"]
    )
    result = execute_config_session(
        connection,
        ["line one", "line two", "line three"],
        now=_clock(),
    )

    assert result["status"] == "FAILED"
    assert [item["status"] for item in result["commands"]] == [
        "SUCCESS",
        "FAILED",
        "NOT_STARTED",
    ]
    assert len(connection.config_calls) == 2
    assert result["first_failure"]["command_index"] == 2


def test_cli_error_allowlist_continues_and_records_rule(tmp_path):
    allowlist = tmp_path / "allow.yaml"
    allowlist.write_text(
        """rules:
  - id: already-exists
    command_pattern: '^vlan 10$'
    response_pattern: 'Invalid command'
""",
        encoding="utf-8",
    )
    connection = FakeConnection(["% Invalid command", "ok"])

    result = execute_config_session(
        connection,
        ["vlan 10", "name SERVERS"],
        now=_clock(),
        cli_error_allowlist=load_cli_error_allowlist(allowlist),
    )

    assert result["status"] == "WARN"
    assert [item["status"] for item in result["commands"]] == ["WARN", "SUCCESS"]
    assert result["commands"][0]["allow_rule_id"] == "already-exists"


def test_nxos_clab_ssh_key_existing_rule_continues_with_warn():
    connection = FakeConnection([
        "ssh key rsa 2048\n"
        "ERROR: Cannot configure run ssh key without force as the config is "
        "already existing \n\nleaf01(config)#",
        "hostname leaf01\nleaf01(config)#",
    ])

    result = execute_config_session(
        connection,
        ["ssh key rsa 2048", "hostname leaf01"],
        now=_clock(),
        cli_error_allowlist=build_nxos_clab_cli_error_allowlist(),
    )

    assert result["status"] == "WARN"
    assert [item["status"] for item in result["commands"]] == ["WARN", "SUCCESS"]
    assert result["commands"][0]["allow_rule_id"] == (
        NXOS_CLAB_SSH_KEY_ALREADY_EXISTS_RULE_ID
    )


@pytest.mark.parametrize(
    ("command", "response"),
    [
        (
            "ssh key rsa 2048 force",
            "ERROR: Cannot configure run ssh key without force as the config is already existing",
        ),
        (
            "ssh key rsa 2048",
            "ERROR: RSA key generation failed for an unrelated reason",
        ),
    ],
)
def test_nxos_clab_ssh_key_rule_rejects_near_matches(command, response):
    result = execute_config_session(
        FakeConnection([response]),
        [command],
        now=_clock(),
        cli_error_allowlist=build_nxos_clab_cli_error_allowlist(),
    )

    assert result["status"] == "FAILED"
    assert "allow_rule_id" not in result["commands"][0]


def test_ignore_all_cli_errors_detects_and_continues():
    connection = FakeConnection(["% Invalid command", "ok"])

    result = execute_config_session(
        connection,
        ["line one", "line two"],
        now=_clock(),
        ignore_all_cli_errors=True,
    )

    assert result["status"] == "IGNORED_ERROR"
    assert [item["status"] for item in result["commands"]] == [
        "IGNORED_ERROR",
        "SUCCESS",
    ]


def test_config_result_redaction_removes_command_and_echoed_secrets():
    result = {
        "status": "SUCCESS",
        "commands": [{
            "index": 1,
            "command": "username lab-admin password 0 VerySecret role network-admin",
            "response": "username lab-admin password 0 VerySecret role network-admin\nok",
            "error": None,
        }],
        "first_failure": None,
    }

    redacted = redact_config_execution_result(result)

    assert "VerySecret" not in str(redacted)
    assert "<redacted>" in redacted["commands"][0]["command"]
    assert "VerySecret" in str(result)


def test_transport_exception_is_unknown_and_is_not_retried():
    connection = FakeConnection(
        [TimeoutError("response timeout"), "must not be sent"]
    )
    result = execute_config_session(
        connection,
        ["line one", "line two"],
        now=_clock(),
    )

    assert result["status"] == "UNKNOWN"
    assert result["commands"][0]["status"] == "UNKNOWN"
    assert result["commands"][1]["status"] == "NOT_STARTED"
    assert len(connection.config_calls) == 1


def test_save_requires_success_marker_and_preserves_response():
    result = execute_save_session(
        FakeConnection(save_output="% Error: failed"),
        command="copy running-config startup-config",
        success_marker="Copy complete.",
        now=_clock(),
    )

    assert result["status"] == "FAILED"
    assert result["response"] == "% Error: failed"
    assert "success marker" in result["error"]


def test_serial_devices_stop_unstarted_hosts_after_first_failure():
    connections = {
        "leaf01": FakeConnection(["ok"]),
        "leaf02": FakeConnection(["% Invalid command"]),
        "leaf03": FakeConnection(["must not run"]),
    }
    connected = []
    disconnected = []

    result = execute_serial_devices(
        ["leaf01", "leaf02", "leaf03"],
        {
            "leaf01": ["line one"],
            "leaf02": ["line two"],
            "leaf03": ["line three"],
        },
        connect=lambda hostname: (
            connected.append(hostname) or connections[hostname]
        ),
        disconnect=lambda connection: disconnected.append(connection),
        now=_clock(),
    )

    assert result["status"] == "FAILED"
    assert connected == ["leaf01", "leaf02"]
    assert len(disconnected) == 2
    assert result["devices"]["leaf01"]["status"] == "SUCCESS"
    assert result["devices"]["leaf02"]["status"] == "FAILED"
    assert result["devices"]["leaf03"]["status"] == "NOT_STARTED"


def test_serial_precheck_failure_sends_no_configuration():
    connection = FakeConnection(["must not run"])
    result = execute_serial_devices(
        ["leaf01"],
        {"leaf01": ["line one"]},
        connect=lambda _hostname: connection,
        disconnect=lambda _connection: None,
        precheck=lambda _hostname, _connection: (False, "running config drift"),
        now=_clock(),
    )

    assert result["status"] == "FAILED"
    assert connection.config_calls == []
    assert "precheck failed" in result["first_failure"]["message"]


def test_serial_precheck_transport_exception_is_unknown():
    connection = FakeConnection(["must not run"])

    def unavailable(_hostname, _connection):
        raise TimeoutError("show running-config timeout")

    result = execute_serial_devices(
        ["leaf01"],
        {"leaf01": ["line one"]},
        connect=lambda _hostname: connection,
        disconnect=lambda _connection: None,
        precheck=unavailable,
        now=_clock(),
    )

    assert result["status"] == "UNKNOWN"
    assert result["devices"]["leaf01"]["status"] == "UNKNOWN"
    assert connection.config_calls == []


def test_execution_document_records_unknown_and_unstarted_devices():
    started = _clock()()
    completed = _clock()()
    connection = FakeConnection([TimeoutError("timeout")])
    serial = execute_serial_devices(
        ["leaf01", "leaf02"],
        {"leaf01": ["line one"], "leaf02": ["line two"]},
        connect=lambda _hostname: connection,
        disconnect=lambda _connection: None,
        now=_clock(),
    )
    document = build_execution_document(
        change_id="CHG-1",
        mode="apply",
        started_at=started,
        completed_at=completed,
        timezone_name="Asia/Tokyo",
        execution_plan_sha256="sha256:" + "a" * 64,
        rollback_plan_sha256="sha256:" + "b" * 64,
        approval_id="APR-test",
        serial_result=serial,
        config_artifacts={
            "leaf01": {
                "path": "generated-config/leaf01.cfg",
                "sha256": "sha256:" + "c" * 64,
            },
            "leaf02": {
                "path": "generated-config/leaf02.cfg",
                "sha256": "sha256:" + "d" * 64,
            },
        },
    )

    assert document["status"]["result"] == "DEVICE_STATE_UNKNOWN"
    assert document["status"]["devices"]["leaf01"]["status"] == "UNKNOWN"
    assert document["status"]["devices"]["leaf02"]["status"] == "NOT_STARTED"
