from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace

import pytest
import yaml

from alred import cli
from alred.collect import ConnectCheckResult
from alred.clab_runtime import (
    ClabReadinessError,
    containerlab_inspect_node_states,
    verify_nxos_lab_running_config,
    wait_for_clab_nodes,
)
from alred.managed_config import NXOS_CLAB_SSH_KEY_ALREADY_EXISTS_RULE_ID


def _topology(tmp_path, *, delay=0):
    path = tmp_path / "topology.clab.yaml"
    path.write_text(
        yaml.safe_dump({
            "name": "lab-a",
            "topology": {
                "nodes": {
                    "leaf01": {"kind": "cisco_n9kv", "startup-delay": delay},
                    "server01": {"kind": "linux"},
                }
            },
        }),
        encoding="utf-8",
    )
    return path


def test_wait_accepts_docker_healthy(tmp_path):
    calls = []
    sleeps = []

    def runner(command, **_kwargs):
        calls.append(command)
        if command[0] == "containerlab":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    "lab-a": [{
                        "lab_name": "lab-a",
                        "name": "clab-lab-a-leaf01",
                        "kind": "cisco_n9kv",
                        "state": "running",
                        "status": "healthy",
                    }]
                }),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"Status": "running", "Health": {"Status": "healthy"}}),
            stderr="",
        )

    result = wait_for_clab_nodes(
        _topology(tmp_path), runner=runner, monotonic=lambda: 100.0,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    assert result["leaf01"]["status"] == "ready"
    assert result["leaf01"]["source"] == "containerlab-inspect"
    assert calls == [["containerlab", "inspect", "--all", "--format", "json"]]
    assert sleeps == []


def test_wait_falls_back_to_docker_when_containerlab_inspect_fails(tmp_path):
    calls = []
    messages = []

    def runner(command, **_kwargs):
        calls.append(command)
        if command[0] == "containerlab":
            return SimpleNamespace(
                returncode=1, stdout="", stderr="runtime unavailable"
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"Status": "running", "Health": {"Status": "healthy"}}),
            stderr="",
        )

    result = wait_for_clab_nodes(
        _topology(tmp_path),
        runner=runner,
        monotonic=lambda: 100.0,
        sleeper=lambda _seconds: None,
        status_callback=messages.append,
    )

    assert result["leaf01"]["source"] == "docker-inspect"
    assert calls[1][-1] == "clab-lab-a-leaf01"
    assert any("falling back to Docker inspect" in message for message in messages)


def test_wait_rejects_matching_nodes_in_different_active_lab(tmp_path):
    sleeps = []

    def runner(command, **_kwargs):
        assert command[0] == "containerlab"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "actual-lab": [{
                    "lab_name": "actual-lab",
                    "absLabPath": "/labs/actual.clab.yaml",
                    "name": "clab-actual-lab-leaf01",
                    "kind": "cisco_n9kv",
                    "state": "running",
                    "status": "healthy",
                }]
            }),
            stderr="",
        )

    with pytest.raises(ClabReadinessError, match="actual-lab.*actual.clab.yaml"):
        wait_for_clab_nodes(
            _topology(tmp_path),
            runner=runner,
            monotonic=lambda: 100.0,
            sleeper=lambda seconds: sleeps.append(seconds),
        )

    assert sleeps == []


def test_containerlab_inspect_reports_not_created_for_unknown_lab():
    states, error = containerlab_inspect_node_states(
        "missing-lab",
        ["leaf01"],
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="{}", stderr=""
        ),
    )

    assert error is None
    assert states is not None
    assert states["leaf01"]["status"] == "not-created"


def test_startup_delay_extends_node_deadline(tmp_path):
    clock = iter([100.0, 125.0, 135.0])

    def runner(_command, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="not found")

    with pytest.raises(ClabReadinessError, match="timeout"):
        wait_for_clab_nodes(
            _topology(tmp_path, delay=20),
            health_timeout=10,
            poll_interval=1,
            runner=runner,
            monotonic=lambda: next(clock),
            sleeper=lambda _: None,
        )


def test_clab_apply_records_readiness_interrupt(tmp_path, monkeypatch):
    topology = _topology(tmp_path)
    monkeypatch.setattr(
        cli,
        "wait_for_clab_nodes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    (tmp_path / "hosts.lab.yaml").write_text(
        "all:\n  hosts:\n    leaf01:\n      device_type: nxos\n"
    )
    args = SimpleNamespace(
        topology=str(topology),
        hosts=str(tmp_path / "hosts.lab.yaml"),
        lab_transform_manifest=str(tmp_path / "lab-transform-manifest.yaml"),
        input_dir=None,
        health_timeout=1200,
        poll_interval=10,
        ignore_startup_delay=False,
        log_file=str(tmp_path / "logs" / "clab-apply-config.log"),
        verbose=False,
        write_memory=False,
        output_dir=str(tmp_path / "apply-output"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_clab_apply_config(args)

    assert exc_info.value.code == 130

    attempt = next((tmp_path / "apply-output").glob("apply-*"))
    result = yaml.safe_load((attempt / "apply-result.yaml").read_text())
    assert result["status"] == "INTERRUPTED_READINESS"
    log_text = (tmp_path / "logs" / "clab-apply-config.log").read_text()
    assert "CLAB APPLY START" in log_text
    assert "CLAB READINESS INTERRUPTED" in log_text


def test_clab_apply_reconnects_successful_hosts_with_post_apply_credentials(
    tmp_path, monkeypatch
):
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        yaml.safe_dump({
            "all": {
                "hosts": {
                    "leaf01": {"ansible_host": "192.0.2.10", "device_type": "nxos"}
                }
            }
        }),
        encoding="utf-8",
    )
    observed = []
    monkeypatch.setattr(
        cli,
        "wait_for_clab_nodes",
        lambda *_args, **_kwargs: {
            "leaf01": {"runtime": "running", "health": "healthy"}
        },
    )
    builtin_rule_ids = []

    def push_config(push_args):
        assert push_args._disable_push_dir_connection_safety_filter is True
        builtin_rule_ids.extend(
            str(rule["id"])
            for rule in push_args._builtin_cli_error_allowlist
        )
        return {
            "aborted": False,
            "pushed_hosts": ["leaf01"],
            "failed_hosts": [],
        }

    monkeypatch.setattr(cli, "cmd_push_config_dir", push_config)

    def reconnect(host, username, password, _enable, _logger, transport, _timeout):
        observed.append((host["hostname"], username, password, transport))
        return SimpleNamespace(ok=True, error=None)

    monkeypatch.setattr(cli, "probe_transport_connectivity", reconnect)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "leaf01").write_text("hostname leaf01\n", encoding="utf-8")

    class Connection:
        def send_command(self, *_args, **_kwargs):
            return "hostname leaf01\n"

        def disconnect(self):
            return None

    monkeypatch.setattr(cli, "connect_to_host", lambda *_args, **_kwargs: Connection())
    args = SimpleNamespace(
        topology=str(_topology(tmp_path)),
        health_timeout=1200,
        poll_interval=10,
        ignore_startup_delay=False,
        log_file=str(tmp_path / "apply.log"),
        verbose=False,
        lab_transform_manifest=None,
        accept_connectivity_risk=True,
        username="admin",
        password="admin",
        credentials=None,
        write_memory=False,
        hosts=str(hosts_path),
        connect_check_timeout=3,
        input_dir=str(config_dir),
        file_hostname_include=False,
        file_suffix="",
        ignore_all_cli_errors=False,
        output_dir=str(tmp_path / "apply-output"),
    )

    cli.cmd_clab_apply_config(args)

    assert observed == [("leaf01", "admin", "admin", "ssh")]
    assert builtin_rule_ids == [NXOS_CLAB_SSH_KEY_ALREADY_EXISTS_RULE_ID]
    assert (tmp_path / "apply-output" / "current.json").is_file()


def test_semantic_verification_ignores_dynamic_lines_and_scrubs_credentials():
    expected = """hostname leaf01
username lab-admin password 0 clear-secret role network-admin
ntp server 172.20.20.10 use-vrf management
"""
    current = """version 10.5(4)
hostname leaf01
username lab-admin password 5 encrypted-value role network-admin
ntp server 172.20.20.10 use-vrf management
feature nxapi
"""

    result = verify_nxos_lab_running_config(expected, current)

    assert result["status"] == "VERIFIED"
    assert "clear-secret" not in "\n".join(result["diff"])
    assert "encrypted-value" not in "\n".join(result["diff"])


def test_startup_check_records_connect_failure_device_type_from_inventory(
    tmp_path, monkeypatch
):
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(
        yaml.safe_dump({
            "all": {
                "hosts": {
                    "leaf01": {"ansible_host": "192.0.2.10", "device_type": "nxos"}
                }
            }
        }),
        encoding="utf-8",
    )
    failure = ConnectCheckResult(
        hostname="leaf01",
        ip="192.0.2.10",
        requested_transport="ssh",
        resolved_transport=None,
        ok=False,
        stage="tcp",
        elapsed_seconds=0.1,
        error="refused",
    )
    monkeypatch.setattr(
        cli, "filter_hosts_by_connect_check", lambda targets, _args, _logger: ([], [failure])
    )
    args = cli.build_parser().parse_args([
        "check-clab-startup-config",
        "--hosts", str(hosts_path),
        "--startup-dir", str(tmp_path / "startup"),
        "--output-dir", str(tmp_path / "output"),
        "--log-file", str(tmp_path / "check.log"),
    ])

    args.func(args)

    report = (tmp_path / "output" / "check-clab-startup-config.txt").read_text()
    assert "### DEVICE_TYPE: nxos" in report
    assert "connect-failed" in report


def test_clab_apply_reuses_live_verified_node_from_matching_current(
    tmp_path, monkeypatch
):
    topology = _topology(tmp_path)
    hosts_path = tmp_path / "hosts.yaml"
    hosts_path.write_text(yaml.safe_dump({
        "all": {"hosts": {
            "leaf01": {"ansible_host": "192.0.2.10", "device_type": "nxos"}
        }}
    }), encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "leaf01"
    config_path.write_text("hostname leaf01\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "lab-transform-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump({
        "api_version": "alred/v1",
        "kind": "LabTransformManifest",
        "spec": {
            "parameter_source_sha256": None,
            "resolved_parameter_sha256": "sha256:" + "0" * 64,
            "devices": [{
                "hostname": "leaf01",
                "platform": "nxos",
                "source_path": "source/leaf01",
                "source_sha256": digest,
                "output_path": "config/leaf01",
                "output_sha256": digest,
                "legacy_stats": {},
                "adapter_stats": {},
                "warnings": [],
                "risk_findings": [],
                "primary_username": None,
                "post_apply_username": "admin",
                "post_apply_password_ref": None,
                "bootstrap_action": "preserve",
            }],
        },
    }, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        cli, "wait_for_clab_nodes", lambda *_args, **_kwargs: {
            "leaf01": {"runtime": "running", "health": "healthy"}
        }
    )
    push_calls = []

    def push(_args):
        push_calls.append("push")
        return {
            "aborted": False,
            "pushed_hosts": ["leaf01"],
            "failed_hosts": [],
            "command_results": {},
        }

    monkeypatch.setattr(cli, "cmd_push_config_dir", push)
    monkeypatch.setattr(
        cli,
        "probe_transport_connectivity",
        lambda *_args, **_kwargs: SimpleNamespace(ok=True, error=None),
    )

    running_text = {"value": "hostname leaf01\n"}

    class Connection:
        def send_command(self, *_args, **_kwargs):
            return running_text["value"]

        def disconnect(self):
            return None

    monkeypatch.setattr(cli, "connect_to_host", lambda *_args, **_kwargs: Connection())
    args = SimpleNamespace(
        topology=str(topology),
        health_timeout=1200,
        poll_interval=10,
        ignore_startup_delay=False,
        log_file=str(tmp_path / "apply.log"),
        verbose=False,
        lab_transform_manifest=str(manifest_path),
        accept_connectivity_risk=True,
        reapply_all=False,
        username="admin",
        password="admin",
        credentials=None,
        write_memory=False,
        hosts=str(hosts_path),
        connect_check_timeout=3,
        input_dir=None,
        file_hostname_include=False,
        file_suffix="",
        ignore_all_cli_errors=False,
        output_dir=str(tmp_path / "apply-output"),
        target_hosts=None,
    )

    cli.cmd_clab_apply_config(args)
    cli.cmd_clab_apply_config(args)

    assert push_calls == ["push"]
    attempts = sorted((tmp_path / "apply-output").glob("apply-*"))
    second = yaml.safe_load((attempts[-1] / "apply-result.yaml").read_text())
    assert second["reused_verified_hosts"] == ["leaf01"]
    assert second["pushed_hosts"] == []

    current_before_failure = (
        tmp_path / "apply-output" / "current.json"
    ).read_bytes()
    running_text["value"] = "hostname wrong-leaf\n"
    with pytest.raises(cli.ClabApplyError):
        cli.cmd_clab_apply_config(args)

    assert push_calls == ["push", "push"]
    assert (tmp_path / "apply-output" / "current.json").read_bytes() == current_before_failure
    failed_attempt = sorted((tmp_path / "apply-output").glob("apply-*"))[-1]
    failed = yaml.safe_load((failed_attempt / "apply-result.yaml").read_text())
    assert failed["status"] == "FAILED"
