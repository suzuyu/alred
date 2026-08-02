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
