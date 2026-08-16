import argparse
import logging

import pytest

from alred import cli
from alred.collect import ConnectCheckResult, evaluate_prompt_hostname


HOST = {
    "hostname": "leaf01",
    "ip": "192.0.2.10",
    "device_type": "nxos",
    "netmiko_device_type": "cisco_nxos",
}


def _args(*, allow=False):
    return argparse.Namespace(
        skip_connect_check=False,
        workers=1,
        connect_check_timeout=3,
        transport="ssh",
        allow_hostname_mismatch=allow,
        verbose=False,
    )


def test_prompt_hostname_normalizes_config_mode_and_detects_default():
    assert evaluate_prompt_hostname("leaf01", "leaf01(config-if)#", "nxos") == (
        "match",
        "leaf01",
        None,
    )
    status, reported, message = evaluate_prompt_hostname(
        "leaf01", "switch#", "nxos"
    )
    assert status == "default_hostname"
    assert reported == "switch"
    assert "default nxos hostname" in message


def test_connect_check_mismatch_requires_explicit_override(monkeypatch):
    result = ConnectCheckResult(
        hostname="leaf01",
        ip="192.0.2.10",
        requested_transport="ssh",
        resolved_transport="ssh",
        ok=False,
        stage="hostname",
        elapsed_seconds=0.1,
        error="prompt hostname 'leaf02' does not match inventory hostname 'leaf01'",
        reported_hostname="leaf02",
        identity_status="mismatch",
    )
    monkeypatch.setattr(cli, "probe_transport_connectivity", lambda *_args: result)
    monkeypatch.setattr(
        cli,
        "get_credentials_for_device",
        lambda *_args: ("user", "password", ""),
    )
    logger = logging.getLogger("hostname-identity-test")

    reachable, failures = cli.filter_hosts_by_connect_check(
        [dict(HOST)], _args(), logger
    )
    assert reachable == []
    assert failures == [result]

    overridden_host = dict(HOST)
    reachable, failures = cli.filter_hosts_by_connect_check(
        [overridden_host], _args(allow=True), logger
    )
    assert failures == []
    assert reachable == [overridden_host]
    assert overridden_host["_allow_hostname_mismatch"] is True


def test_default_hostname_requires_separate_mutation_confirmation(monkeypatch):
    args = _args()
    result = ConnectCheckResult(
        hostname="leaf01",
        ip="192.0.2.10",
        requested_transport="ssh",
        resolved_transport="ssh",
        ok=True,
        stage="auth",
        elapsed_seconds=0.1,
        reported_hostname="switch",
        identity_status="default_hostname",
        warning="device uses the default nxos hostname",
    )
    args._connect_check_default_hostname_warnings = [result]
    host = dict(HOST)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    assert cli.confirm_default_hostname_mutation([host], args, logging.getLogger())
    assert host["_default_hostname_confirmed"] is True


def test_mutation_session_revalidates_prompt_hostname(monkeypatch):
    class Connection:
        def __init__(self, prompt):
            self.prompt = prompt
            self.disconnected = False

        def find_prompt(self):
            return self.prompt

        def disconnect(self):
            self.disconnected = True

    mismatch = Connection("leaf02#")
    monkeypatch.setattr(cli, "ConnectHandler", lambda **_kwargs: mismatch)
    with pytest.raises(ValueError, match="allow-hostname-mismatch"):
        cli.connect_to_host(dict(HOST), "user", "password", "", logging.getLogger())
    assert mismatch.disconnected is True

    allowed = Connection("leaf02#")
    monkeypatch.setattr(cli, "ConnectHandler", lambda **_kwargs: allowed)
    host = {**HOST, "_allow_hostname_mismatch": True}
    assert cli.connect_to_host(
        host, "user", "password", "", logging.getLogger()
    ) is allowed

    default = Connection("switch#")
    monkeypatch.setattr(cli, "ConnectHandler", lambda **_kwargs: default)
    host = {**HOST, "_default_hostname_confirmed": True}
    assert cli.connect_to_host(
        host, "user", "password", "", logging.getLogger()
    ) is default
