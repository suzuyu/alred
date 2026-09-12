"""Offline target matching and CLI/operation integration."""

from copy import deepcopy
from datetime import datetime
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import alred.cli as cli
from alred.health.execution_context import (
    HealthExecutionContextError,
    load_health_execution_context,
)
from alred.operation import open_operation_workspace
from alred.target_selection import TargetSelectionError, resolve_target_hosts

HOSTS = [
    dict(hostname=name, device_type="nxos", ip=f"192.0.2.{i}")
    for i, name in enumerate(
        ["site-leaf01", "site-leaf02", "site-spine01", "site-border01", "site-Leaf03"],
        1,
    )
]
LOGGER = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "raw,mode,names",
    [
        (None, None, [h["hostname"] for h in HOSTS]),
        ("site-leaf01,site-spine01", "exact", ["site-leaf01", "site-spine01"]),
        ("leaf", "exact", []),
        ("leaf,spine", "contains", ["site-leaf01", "site-leaf02", "site-spine01"]),
        (" leaf , leaf01,leaf ", "contains", ["site-leaf01", "site-leaf02"]),
        ("Leaf", "contains", ["site-Leaf03"]),
        ("", "exact", [h["hostname"] for h in HOSTS]),
    ],
)
def test_literal_selection(raw, mode, names):
    hosts = deepcopy(HOSTS)
    selection = resolve_target_hosts(hosts, {}, LOGGER, targets=raw, mode=mode)
    assert [host["hostname"] for host in selection.hosts] == names
    assert hosts == HOSTS


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        " ",
        ",",
        "leaf,",
        "leaf,,spine",
        "leaf,missing",
        "missing",
        "*",
        "192.0.2.",
    ],
)
def test_contains_invalid_or_unmatched_is_not_all_hosts(raw):
    with pytest.raises(TargetSelectionError):
        resolve_target_hosts(HOSTS, {}, LOGGER, targets=raw, mode="contains")


def test_policy_exclusion_and_empty_selection():
    policy = {"exclude_hostname_contains": ["leaf02"]}
    result = resolve_target_hosts(
        HOSTS, policy, LOGGER, targets="leaf", mode="contains"
    )
    assert [h["hostname"] for h in result.hosts] == ["site-leaf01"]
    assert result.skipped == 1
    with pytest.raises(TargetSelectionError, match="policy"):
        resolve_target_hosts(
            HOSTS,
            {"exclude_device_types": ["nxos"]},
            LOGGER,
            targets="leaf",
            mode="contains",
        )


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "hosts.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        host["hostname"]: {
                            "ansible_host": host["ip"],
                            "device_type": host["device_type"],
                        }
                        for host in HOSTS
                    }
                }
            },
            sort_keys=False,
        )
    )
    return path


@pytest.mark.parametrize(
    "command",
    [
        "collect",
        "collect-list",
        "collect-run-config",
        "collect-run-diff",
        "collect-run-diff-cmd",
        "collect-clab",
        "check-logging",
        "check-clab-startup-config",
        "push-config",
        "push-config-dir",
        "write-memory",
    ],
)
@pytest.mark.parametrize("invalid", [False, True])
def test_each_cli_resolves_targets_before_connecting(
    inventory, tmp_path, monkeypatch, command, invalid
):
    config = tmp_path / "config.txt"
    config.write_text("hostname synthetic\n")
    commands = tmp_path / "commands.txt"
    commands.write_text("[all]\nshow version\n")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    for host in HOSTS:
        (config_dir / host["hostname"]).write_text("hostname synthetic\n")
    extra = {
        "push-config": ["--config-file", str(config)],
        "push-config-dir": ["--input-dir", str(config_dir)],
        "collect-list": ["--show-commands-file", str(commands)],
    }.get(command, [])
    args = cli.build_parser().parse_args(
        [
            command,
            "--hosts",
            str(inventory),
            "--target-hosts",
            "leaf,missing" if invalid else "leaf,spine",
            "--target-hosts-match",
            "contains",
            *extra,
        ]
    )

    class ReachedConnection(Exception):
        pass

    def boundary(targets, *_args, **_kwargs):
        assert [h["hostname"] for h in targets] == [
            "site-leaf01",
            "site-leaf02",
            "site-spine01",
        ]
        raise ReachedConnection

    monkeypatch.setattr(cli, "filter_hosts_by_connect_check", boundary)
    with pytest.raises(TargetSelectionError if invalid else ReachedConnection):
        args.func(args)


def test_all_cli_target_options_support_match_mode():
    def visit(parser):
        for action in parser._actions:
            if action.dest == "target_hosts":
                mode = next(
                    a for a in parser._actions if a.dest == "target_hosts_match"
                )
                assert mode.choices == ["exact", "contains"]
                assert mode.default is None
            if isinstance(action, cli.argparse._SubParsersAction):
                for subparser in action.choices.values():
                    visit(subparser)

    visit(cli.build_parser())


def test_archive_resolves_same_policy_targets(inventory):
    args = SimpleNamespace(
        hosts=str(inventory),
        policy=None,
        target_hosts="leaf,spine",
        target_hosts_match="contains",
    )
    assert cli.resolve_archive_filter_hostnames(args, LOGGER) == {
        "site-leaf01",
        "site-leaf02",
        "site-spine01",
    }


def test_vni_collect_wrapper_forwards_matching_mode(inventory, monkeypatch):
    args = cli.build_parser().parse_args(
        [
            "generate-vni-config",
            "--hosts",
            str(inventory),
            "--target-hosts",
            "leaf",
            "--target-hosts-match",
            "contains",
        ]
    )
    received = []
    monkeypatch.setattr(cli, "cmd_collect", lambda a: received.append(a))
    cli.run_collect_run_config_from_args(args)
    assert received[0].target_hosts_match == "contains"
    assert received[0].target_hosts == "leaf"


def test_clab_set_wrapper_forwards_matching_mode():
    args = SimpleNamespace(target_hosts="leaf", target_hosts_match="contains")
    result = cli.build_clab_set_step_args(
        {"command": "collect", "args": {}}, args, False
    )
    assert result.target_hosts == "leaf"
    assert result.target_hosts_match == "contains"


def _before_args(inventory, tmp_path, *extras):
    return cli.build_parser().parse_args(
        [
            "health-check",
            "before",
            "--collect",
            "--hosts",
            str(inventory),
            "--change-id",
            "TARGETS",
            "--purpose",
            "inspection",
            "--operations-root",
            str(tmp_path / "operations"),
            *extras,
        ]
    )


def _context(inventory, tmp_path):
    args = _before_args(
        inventory,
        tmp_path,
        "--target-hosts",
        "leaf,spine",
        "--target-hosts-match",
        "contains",
    )
    args.phase = "before"
    workspace, _ = cli._snapshot_workspace(args)
    cli._write_health_execution_context(
        args, workspace, recorded_at=datetime.now().astimezone()
    )
    return workspace


@pytest.mark.parametrize(
    "tokens,mode,expected",
    [
        (None, None, True),
        ("leaf,spine", None, True),
        ("leaf,spine", "contains", True),
        ("site-leaf01,site-leaf02,site-spine01", "exact", True),
        ("leaf", "contains", False),
        (None, "exact", False),
    ],
)
def test_context_reuses_hosts_or_checks_resolved_override(
    inventory, tmp_path, tokens, mode, expected
):
    workspace = _context(inventory, tmp_path)
    extras = (["--target-hosts", tokens] if tokens is not None else []) + (
        ["--target-hosts-match", mode] if mode else []
    )
    args = cli.build_parser().parse_args(
        ["health-check", "after", "--change-id", "TARGETS", *extras]
    )
    if not expected:
        with pytest.raises(HealthExecutionContextError):
            cli._apply_health_followup_execution_context(args, workspace)
    else:
        assert cli._apply_health_followup_execution_context(args, workspace)
        assert args.target_hosts == "site-leaf01,site-leaf02,site-spine01"
        assert args.target_hosts_match == "exact"


def test_legacy_context_empty_means_all_hosts(inventory, tmp_path):
    workspace = _context(inventory, tmp_path)
    path = workspace.operation_root / "health/execution-context.yaml"
    doc = yaml.safe_load(path.read_text())
    del doc["spec"]["collection"]["target_selection"]
    doc["spec"]["collection"]["target_hosts"] = []
    path.write_text(yaml.safe_dump(doc))
    args = cli.build_parser().parse_args(
        ["health-check", "after", "--change-id", "TARGETS"]
    )
    cli._apply_health_followup_execution_context(args, workspace)
    assert args.target_hosts is None
    assert args.target_hosts_match == "exact"


def test_changed_inventory_rejected_before_collect(inventory, tmp_path):
    workspace = _context(inventory, tmp_path)
    inventory.write_text(inventory.read_text() + "\n# drift\n")
    args = cli.build_parser().parse_args(
        ["health-check", "after", "--change-id", "TARGETS"]
    )
    with pytest.raises(HealthExecutionContextError, match="hash"):
        cli._apply_health_followup_execution_context(args, workspace)


def test_failed_first_collection_pins_targets_for_retry(
    inventory, tmp_path, monkeypatch
):
    attempts = []

    def collect(args, *_args, **_kwargs):
        attempts.append((args.target_hosts, args.target_hosts_match))
        raise OSError("synthetic collection interruption")

    monkeypatch.setattr(cli, "run_collect", collect)
    before = _before_args(
        inventory,
        tmp_path,
        "--target-hosts",
        "leaf",
        "--target-hosts-match",
        "contains",
    )
    with pytest.raises(OSError):
        cli.cmd_health_check_phase(before)
    workspace = open_operation_workspace(tmp_path / "operations", "TARGETS")
    context = load_health_execution_context(workspace.operation_root)
    assert context["spec"]["collection"]["target_hosts"] == [
        "site-leaf01",
        "site-leaf02",
    ]
    assert context["spec"]["collection"]["target_selection"] == {
        "mode": "contains",
        "tokens": ["leaf"],
    }
    original = (workspace.operation_root / "health/execution-context.yaml").read_bytes()
    retry = _before_args(
        inventory,
        tmp_path,
        "--target-hosts",
        "spine",
        "--target-hosts-match",
        "contains",
    )
    with pytest.raises(HealthExecutionContextError):
        cli.cmd_health_check_phase(retry)
    retry = _before_args(inventory, tmp_path)
    with pytest.raises(OSError):
        cli.cmd_health_check_phase(retry)
    assert attempts == [("site-leaf01,site-leaf02", "exact")] * 2
    assert (
        workspace.operation_root / "health/execution-context.yaml"
    ).read_bytes() == original
    assert not (workspace.operation_root / "health/before/current.json").exists()


@pytest.mark.parametrize("invalid", [False, True])
def test_clab_risk_scan_and_push_share_concrete_targets(
    inventory, tmp_path, monkeypatch, invalid
):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    # Non-target hosts deliberately have no config: risk scanning must skip them.
    for name in ["site-leaf01", "site-leaf02"]:
        (config_dir / name).write_text(f"hostname {name}\n")
    topology = tmp_path / "lab.yaml"
    topology.write_text("name: synthetic\ntopology:\n  nodes: {}\n")
    args = cli.build_parser().parse_args(
        [
            "clab-apply-config",
            "--hosts",
            str(inventory),
            "--topology",
            str(topology),
            "--input-dir",
            str(config_dir),
            "--target-hosts",
            "leaf,missing" if invalid else "leaf",
            "--target-hosts-match",
            "contains",
            "--accept-connectivity-risk",
        ]
    )
    readiness_calls, pushes = [], []
    monkeypatch.setattr(
        cli, "wait_for_clab_nodes", lambda *a, **kw: readiness_calls.append(True) or {}
    )

    def push(push_args):
        pushes.append(push_args.target_hosts)
        assert push_args.target_hosts_match == "exact"
        return {"aborted": True, "command_results": {}}

    monkeypatch.setattr(cli, "cmd_push_config_dir", push)
    if invalid:
        with pytest.raises(TargetSelectionError):
            cli.cmd_clab_apply_config(args)
        assert not readiness_calls and not pushes
    else:
        cli.cmd_clab_apply_config(args)
        assert pushes == ["site-leaf01,site-leaf02"]


def test_collect_all_freezes_targets_for_steps_and_archive(
    inventory, tmp_path, monkeypatch
):
    commands = tmp_path / "shows.txt"
    commands.write_text("[all]\nshow version\n")
    args = cli.build_parser().parse_args(
        [
            "collect-all",
            "--hosts",
            str(inventory),
            "--target-hosts",
            "leaf,spine",
            "--target-hosts-match",
            "contains",
            "--filter-archive-hosts",
            "--show-commands-file",
            str(commands),
        ]
    )
    observed = []

    def collect(step, *_a, **_kw):
        observed.append((step.target_hosts, step.target_hosts_match))

    monkeypatch.setattr(cli, "run_collect", collect)

    def archive(*a, **kw):
        assert kw["allowed_hosts"] == {"site-leaf01", "site-leaf02", "site-spine01"}
        return tmp_path / "archive.tar"

    monkeypatch.setattr(cli, "create_collect_archive", archive)
    cli.run_collect_all_flow(args, LOGGER)
    assert observed == [("site-leaf01,site-leaf02,site-spine01", "exact")] * 4


def test_invalid_contains_cli_has_validation_code_without_traceback(
    inventory, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "alred",
            "collect",
            "--hosts",
            str(inventory),
            "--target-hosts",
            "leaf,missing",
            "--target-hosts-match",
            "contains",
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "VALIDATION_ERROR" in stderr and "missing" in stderr
    assert "Traceback" not in stderr


def test_partial_context_before_attempt_still_pins_hosts(
    inventory, tmp_path, monkeypatch
):
    # Simulate interruption after writing context but before recording an attempt.
    workspace = _context(inventory, tmp_path)
    original = (workspace.operation_root / "health/execution-context.yaml").read_bytes()

    def forbidden(*a, **kw):
        pytest.fail("changed targets must not connect")

    monkeypatch.setattr(cli, "run_collect", forbidden)
    args = _before_args(
        inventory,
        tmp_path,
        "--target-hosts",
        "border",
        "--target-hosts-match",
        "contains",
    )
    with pytest.raises(HealthExecutionContextError):
        cli.cmd_health_check_phase(args)
    assert (
        workspace.operation_root / "health/execution-context.yaml"
    ).read_bytes() == original


def test_contains_treats_glob_characters_literally():
    hosts = [dict(hostname=n, device_type="nxos") for n in ["leaf01", "leaf*01"]]
    selected = resolve_target_hosts(hosts, {}, LOGGER, targets="leaf*", mode="contains")
    assert [h["hostname"] for h in selected.hosts] == ["leaf*01"]
