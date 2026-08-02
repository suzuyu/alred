from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest
import yaml

from alred.operation import (
    OperationLock,
    create_operation_workspace,
    load_operation_metadata,
    transition_workflow,
)
from alred.approval import (
    ApprovalError,
    build_approval_summary,
    create_approval_record,
    load_approval_record,
)
from alred.managed_operation import (
    execute_approved_apply,
    execute_approved_rollback,
    execute_approved_save,
    verify_approved_rollback,
)
from alred.qualification import (
    QualificationError,
    QualificationRequiredError,
    build_qualification_summary,
    create_qualification_record,
    execute_qualification_apply,
    execute_qualification_baseline_save,
    execute_qualification_rollback,
    load_qualification_record,
    qualification_confirmation_phrase,
    validate_qualification_record,
    verify_qualification_rollback,
)
from alred.schema import source_sha256


JST_NOW = datetime.fromisoformat("2026-08-02T13:00:00+09:00")


def _write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _write_yaml(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _candidate(tmp_path, *, health_result="PASS", devices=None):
    devices = devices or ["leaf01", "leaf02"]
    workspace = create_operation_workspace(
        tmp_path / "operations",
        change_id="CHG-QUALIFY-1",
        now=JST_NOW,
    )
    root = workspace.operation_root
    configs = {}
    rollbacks = {}
    for host in devices:
        forward = root / "generated-config" / f"{host}.cfg"
        reverse = root / "rollback-config" / f"{host}.cfg"
        forward.parent.mkdir(parents=True, exist_ok=True)
        reverse.parent.mkdir(parents=True, exist_ok=True)
        forward.write_text(f"vlan {host[-2:]}\n", encoding="utf-8")
        reverse.write_text(f"no vlan {host[-2:]}\n", encoding="utf-8")
        forward.chmod(0o600)
        reverse.chmod(0o600)
        configs[host] = (forward, source_sha256(forward))
        rollbacks[host] = (reverse, source_sha256(reverse))

    plan = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "capability_level": "PLAN_ONLY",
        "devices": {
            host: {
                "status": "PLANNED",
                "forward_config": str(configs[host][0].relative_to(root)),
                "forward_sha256": configs[host][1],
            }
            for host in devices
        },
    }
    rollback = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "policy": "manual",
        "devices": {
            host: {
                "status": "PLANNED",
                "rollback_config": str(rollbacks[host][0].relative_to(root)),
                "rollback_sha256": rollbacks[host][1],
            }
            for host in devices
        },
    }
    running_sources = {}
    for host in devices:
        running = root / "health/before/raw/config" / f"{host}_run.txt"
        running.parent.mkdir(parents=True, exist_ok=True)
        running.write_text(
            f"!Time: dynamic\nhostname {host}\nfeature nv overlay\n",
            encoding="utf-8",
        )
        running.chmod(0o600)
        running_sources[host] = running
    snapshot = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "collection_id": "before-001",
        "phase": "before",
        "profile_sha256": "sha256:" + "a" * 64,
        "hosts": {
            host: {
                "common": {
                    "system": {
                        "platform": "nxos",
                        "model": "Nexus9000 C9300v",
                        "version": "10.5(4)",
                    },
                    "vpc": {"applicable": True, "healthy": True},
                },
                "profiles": {
                    "nxos-overlay": {
                        "config": {"nve": {"configured": True}}
                    }
                },
                "sources": {
                    "running_config": {
                        "status": "success",
                        "parse_status": "parsed",
                        "command": "show running-config",
                        "file": str(running_sources[host]),
                        "sha256": source_sha256(
                            running_sources[host]
                        ).removeprefix("sha256:"),
                    }
                },
            }
            for host in devices
        },
    }
    health = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "before",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["network-baseline-nxos", "nxos-overlay"],
        "result": health_result,
        "counts": {
            "pass": 1 if health_result == "PASS" else 0,
            "warn": 0,
            "fail": 1 if health_result == "FAIL" else 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }
    change_set = {
        "api_version": "alred/v1",
        "kind": "OverlayChangeSet",
        "metadata": {
            "change_id": workspace.change_id,
            "source": "declared",
        },
        "spec": {"device_groups": {}, "l2vnis": [], "l3vnis": []},
    }
    manifest = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "renderer": "nxos-overlay@1.0",
        "templates": {"forward": "forward.j2", "rollback": "rollback.j2"},
        "devices": {
            host: {
                "forward_config": str(configs[host][0].relative_to(root)),
                "rollback_config": str(rollbacks[host][0].relative_to(root)),
                "forward_sha256": configs[host][1],
                "rollback_sha256": rollbacks[host][1],
                "model_sha256": "sha256:" + "b" * 64,
                "actions": [{"resource": "l2vni/10001", "action": "create"}],
            }
            for host in devices
        },
    }
    paths = {
        "plan_path": _write_json(root / "plan/execution-plan.json", plan),
        "rollback_plan_path": _write_json(
            root / "plan/rollback-plan.json",
            rollback,
        ),
        "before_snapshot_path": _write_json(
            root / "health/before/snapshot.json",
            snapshot,
        ),
        "before_health_result_path": _write_json(
            root / "health/before/health-result.json",
            health,
        ),
        "change_set_path": _write_yaml(root / "desired-changes.yaml", change_set),
        "render_manifest_path": _write_json(
            root / "plan/render-manifest.json",
            manifest,
        ),
        "inventory_path": _write_yaml(
            tmp_path / "hosts.lab.yaml",
            {"all": {"hosts": {host: {} for host in devices}}},
        ),
    }
    with OperationLock(workspace, "plan", now=JST_NOW) as lock:
        for state in (
            "planned",
            "before_running",
            "before_completed",
            "plan_ready",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
    return workspace, paths


class FakeQualificationConnection:
    def __init__(self, running_config, config_outputs, *, diff=""):
        self.running_config = running_config
        self.config_outputs = iter(config_outputs)
        self.diff = diff
        self.config_calls = []
        self.disconnected = False

    def send_command(self, command, **_kwargs):
        if command == "show running-config diff":
            return self.diff
        assert command == "show running-config"
        if isinstance(self.running_config, Exception):
            raise self.running_config
        return self.running_config

    def send_config_set(self, commands, **kwargs):
        self.config_calls.append((commands, kwargs))
        result = next(self.config_outputs)
        if isinstance(result, Exception):
            raise result
        return result

    def exit_config_mode(self):
        return None


class FakeSaveConnection:
    def __init__(
        self,
        running_config,
        *,
        diff="",
        post_diff="",
        save_output="Copy complete.",
    ):
        self.running_config = running_config
        self.diff = diff
        self.post_diff = post_diff
        self.save_output = save_output
        self.save_calls = []
        self.disconnected = False

    def find_prompt(self):
        return "leaf#"

    def send_command(self, command, **_kwargs):
        if command == "show running-config":
            return self.running_config
        if command == "show running-config diff":
            return self.post_diff if self.save_calls else self.diff
        if command == "copy running-config startup-config":
            self.save_calls.append(command)
            return self.save_output
        raise AssertionError(command)


def test_qualification_summary_pins_plan_configs_and_lab_target(tmp_path):
    workspace, paths = _candidate(tmp_path)
    summary = build_qualification_summary(workspace, **paths)

    assert summary["target"] == {
        "platform": "nxos",
        "model": "N9K-C9300V",
        "release": "10.5(4)",
        "role": "vtep_leaf",
        "devices": ["leaf01", "leaf02"],
    }
    assert summary["constraints"]["save_on_initial_apply"] is False
    assert "forward_config_leaf01" in summary["artifacts"]
    assert qualification_confirmation_phrase(summary) == (
        "QUALIFY CHG-QUALIFY-1 N9K-C9300V 10.5(4)"
    )


@pytest.mark.parametrize(
    "health_result,devices,message",
    [
        ("FAIL", None, "HealthResult PASS"),
        ("PASS", ["leaf01", "leaf02", "leaf03"], "one or two"),
    ],
)
def test_qualification_summary_fails_closed(
    tmp_path,
    health_result,
    devices,
    message,
):
    workspace, paths = _candidate(
        tmp_path,
        health_result=health_result,
        devices=devices,
    )

    with pytest.raises(QualificationError, match=message):
        build_qualification_summary(workspace, **paths)


def test_qualification_record_requires_exact_phrase_and_rehashes(tmp_path):
    workspace, paths = _candidate(tmp_path)
    summary = build_qualification_summary(workspace, **paths)
    phrase = qualification_confirmation_phrase(summary)

    with OperationLock(workspace, "qualify-approve", now=JST_NOW) as lock:
        with pytest.raises(QualificationRequiredError):
            create_qualification_record(
                workspace,
                summary,
                lock=lock,
                confirm=lambda _phrase: "yes",
                now=JST_NOW,
            )

    with OperationLock(workspace, "qualify-approve", now=JST_NOW) as lock:
        record_path = create_qualification_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _phrase: phrase,
            now=JST_NOW,
            random_hex="a1b2c3",
        )

    record = load_qualification_record(record_path)
    assert record["metadata"]["qualification_id"] == (
        "QLF-20260802T130000-p0900-a1b2c3"
    )
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "approved"
    validate_qualification_record(
        record,
        expected_change_id=workspace.change_id,
        now=JST_NOW + timedelta(hours=3),
    )
    with pytest.raises(QualificationError, match="expired"):
        validate_qualification_record(
            record,
            expected_change_id=workspace.change_id,
            now=JST_NOW + timedelta(hours=4),
        )

    forward_path = Path(
        record["artifacts"]["forward_config_leaf01"]["path"]
    )
    forward_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(QualificationError, match="forward_config_leaf01"):
        validate_qualification_record(
            record,
            expected_change_id=workspace.change_id,
            now=JST_NOW,
        )


def _approved_candidate(tmp_path):
    workspace, paths = _candidate(tmp_path)
    summary = build_qualification_summary(workspace, **paths)
    phrase = qualification_confirmation_phrase(summary)
    with OperationLock(workspace, "qualify-approve", now=JST_NOW) as lock:
        record_path = create_qualification_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _expected: phrase,
            now=JST_NOW,
            random_hex="a1b2c3",
        )
    return workspace, load_qualification_record(record_path)


def _clock():
    current = JST_NOW + timedelta(minutes=1)

    def now():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return now


def _after_snapshot(
    workspace,
    devices=("leaf01", "leaf02"),
    *,
    extra_by_host=None,
):
    extra_by_host = extra_by_host or {}
    hosts = {}
    for host in devices:
        running = (
            workspace.operation_root
            / "health"
            / "after"
            / "raw"
            / f"{host}_run.txt"
        )
        running.parent.mkdir(parents=True, exist_ok=True)
        running.write_text(
            f"hostname {host}\nfeature nv overlay\n"
            f"vlan {host[-2:]}\n"
            f"{extra_by_host.get(host, '')}",
            encoding="utf-8",
        )
        running.chmod(0o600)
        hosts[host] = {
            "sources": {
                "running_config": {
                    "status": "success",
                    "parse_status": "parsed",
                    "command": "show running-config",
                    "file": str(running),
                    "sha256": source_sha256(running).removeprefix("sha256:"),
                }
            }
        }
    return _write_json(
        workspace.operation_root / "health/after/snapshot.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "after",
            "created_at": "2026-08-02T14:00:00+09:00",
            "hosts": hosts,
        },
    )


def _run_apply(workspace, record, *, first_output="ok"):
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\n",
            [first_output if host == "leaf01" else "ok"],
        )
        for host in ("leaf01", "leaf02")
    }
    with OperationLock(workspace, "qualify", now=JST_NOW) as lock:
        return execute_qualification_apply(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )


def _mark_rollback_verified(workspace):
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        for state in (
            "apply_running",
            "apply_completed",
            "after_running",
            "after_completed",
            "rollback_required",
            "rollback_running",
            "rolled_back",
            "rolled_back_and_verified",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
    _write_json(
        workspace.operation_root
        / "qualification"
        / "rollback"
        / "verification.json",
        {
            "api_version": "alred/v1",
            "kind": "QualificationRollbackVerification",
            "metadata": {
                "change_id": workspace.change_id,
                "verified_at": JST_NOW.isoformat(),
                "timezone": "Asia/Tokyo",
            },
            "status": {
                "result": "ROLLED_BACK_AND_VERIFIED",
                "health_result": "PASS",
                "raw_config_equal": True,
                "semantic_config_equal": True,
            },
            "devices": {
                host: {
                    "raw_config_equal": True,
                    "semantic_config_equal": True,
                }
                for host in ("leaf01", "leaf02")
            },
            "artifacts": {
                "before_snapshot": "before.json",
                "rollback_snapshot": "rollback.json",
                "health_result": "health.json",
            },
        },
    )


def test_qualification_baseline_save_after_verified_rollback(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _mark_rollback_verified(workspace)
    created = []

    def connect(host):
        connection = FakeSaveConnection(
            f"hostname {host}\nfeature nv overlay\n"
        )
        created.append((host, connection))
        return connection

    with OperationLock(
        workspace,
        "qualify-save-baseline",
        now=JST_NOW,
    ) as lock:
        execution = execute_qualification_baseline_save(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=connect,
            disconnect=lambda connection: setattr(
                connection,
                "disconnected",
                True,
            ),
            save_command="copy running-config startup-config",
            success_marker="Copy complete.",
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == (
        "QUALIFICATION_SAVE_SUCCEEDED"
    )
    assert [host for host, _connection in created] == [
        "leaf01",
        "leaf02",
        "leaf01",
        "leaf02",
    ]
    assert sum(len(connection.save_calls) for _, connection in created) == 2
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "qualification_completed"
    assert (
        workspace.operation_root
        / "qualification/save/devices/leaf01/save.log"
    ).is_file()


def test_qualification_baseline_save_preflight_blocks_all_devices(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _mark_rollback_verified(workspace)
    created = []

    def connect(host):
        connection = FakeSaveConnection(
            f"hostname {host}\nfeature nv overlay\n",
            diff="vlan 999",
        )
        created.append(connection)
        return connection

    with OperationLock(
        workspace,
        "qualify-save-baseline",
        now=JST_NOW,
    ) as lock:
        execution = execute_qualification_baseline_save(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=connect,
            disconnect=lambda connection: setattr(
                connection,
                "disconnected",
                True,
            ),
            save_command="copy running-config startup-config",
            success_marker="Copy complete.",
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "QUALIFICATION_SAVE_FAILED"
    assert not any(connection.save_calls for connection in created)
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rolled_back_and_verified"


def test_normal_approved_apply_reuses_managed_executor(tmp_path):
    workspace, paths = _candidate(tmp_path)
    plan_path = paths["plan_path"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["capability_level"] = "APPLY_VERIFIED"
    plan["artifacts"] = {
        "before_snapshot": str(paths["before_snapshot_path"]),
        "inventory": str(paths["inventory_path"]),
        "inventory_sha256": source_sha256(paths["inventory_path"]),
    }
    _write_json(plan_path, plan)
    summary = build_approval_summary(
        workspace,
        plan_path=plan_path,
        rollback_plan_path=paths["rollback_plan_path"],
    )
    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            now=JST_NOW,
            random_hex="abcdef",
        )
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }

    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        execution = execute_approved_apply(
            workspace,
            load_approval_record(approval_path),
            plan_path=plan_path,
            rollback_plan_path=paths["rollback_plan_path"],
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "APPLIED_PENDING_HEALTH"
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "apply_completed"
    assert (
        workspace.operation_root / "apply/devices/leaf01/commands.log"
    ).is_file()
    assert execution["status"]["devices"]["leaf01"]["pre_apply_diff"] == ""


def test_normal_apply_rejects_modified_resolved_targets_before_connect(tmp_path):
    workspace, paths = _candidate(tmp_path)
    resolved_targets = _write_yaml(
        workspace.operation_root / "plan/resolved-targets.yaml",
        {"kind": "resolved", "devices": ["leaf01", "leaf02"]},
    )
    plan = json.loads(paths["plan_path"].read_text(encoding="utf-8"))
    plan["capability_level"] = "APPLY_VERIFIED"
    plan["artifacts"] = {
        "before_snapshot": str(paths["before_snapshot_path"]),
        "inventory": str(paths["inventory_path"]),
        "inventory_sha256": source_sha256(paths["inventory_path"]),
        "approval_artifacts": {
            "resolved_targets": str(resolved_targets),
        },
    }
    _write_json(paths["plan_path"], plan)
    summary = build_approval_summary(
        workspace,
        plan_path=paths["plan_path"],
        rollback_plan_path=paths["rollback_plan_path"],
    )
    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            now=JST_NOW,
            random_hex="abcdef",
        )
    resolved_targets.write_text(
        yaml.safe_dump({"kind": "modified", "devices": ["leaf01"]}),
        encoding="utf-8",
    )
    connected = []

    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        with pytest.raises(ApprovalError, match="artifact hash mismatch"):
            execute_approved_apply(
                workspace,
                load_approval_record(approval_path),
                plan_path=paths["plan_path"],
                rollback_plan_path=paths["rollback_plan_path"],
                inventory_hosts={
                    host: {"device_type": "nxos"}
                    for host in ("leaf01", "leaf02")
                },
                connect=lambda host: connected.append(host),
                disconnect=lambda _connection: None,
                lock=lock,
                now=_clock(),
            )

    assert connected == []


def test_normal_approved_apply_rejects_unrelated_unsaved_config(tmp_path):
    workspace, paths = _candidate(tmp_path)
    plan = json.loads(paths["plan_path"].read_text(encoding="utf-8"))
    plan["capability_level"] = "APPLY_VERIFIED"
    plan["artifacts"] = {
        "before_snapshot": str(paths["before_snapshot_path"]),
        "inventory": str(paths["inventory_path"]),
        "inventory_sha256": source_sha256(paths["inventory_path"]),
    }
    _write_json(paths["plan_path"], plan)
    summary = build_approval_summary(
        workspace,
        plan_path=paths["plan_path"],
        rollback_plan_path=paths["rollback_plan_path"],
        save_on_success=True,
    )
    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            now=JST_NOW,
            random_hex="abcdef",
        )
    connection = FakeQualificationConnection(
        "hostname leaf01\nfeature nv overlay\n",
        ["must not run"],
        diff="feature unrelated-change",
    )

    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        execution = execute_approved_apply(
            workspace,
            load_approval_record(approval_path),
            plan_path=paths["plan_path"],
            rollback_plan_path=paths["rollback_plan_path"],
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda _host: connection,
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "APPLY_FAILED"
    assert connection.config_calls == []
    assert "unrelated changes" in execution["status"]["first_failure"][
        "message"
    ]


def _write_verified_after_results(workspace):
    health = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "compare",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["network-baseline-nxos", "nxos-overlay"],
        "result": "PASS",
        "counts": {
            "pass": 1,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }
    overlay = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "source": "declared",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "result": "VERIFIED",
        "sections": {
            "configuration": "PASS",
            "operational": "PASS",
            "impact": "PASS",
        },
        "counts": {
            "pass": 3,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
            "plan_error": 0,
        },
        "checks": [],
        "warnings": [],
        "conflicts": [],
        "convergence": None,
    }
    _write_json(
        workspace.operation_root / "health/report/health-result.json",
        health,
    )
    _write_json(
        workspace.operation_root / "overlay/health-result.json",
        overlay,
    )


def test_normal_approved_save_after_verified_health(tmp_path):
    workspace, paths = _candidate(tmp_path)
    plan = json.loads(paths["plan_path"].read_text(encoding="utf-8"))
    plan["capability_level"] = "APPLY_VERIFIED"
    plan["artifacts"] = {
        "before_snapshot": str(paths["before_snapshot_path"]),
        "inventory": str(paths["inventory_path"]),
        "inventory_sha256": source_sha256(paths["inventory_path"]),
    }
    _write_json(paths["plan_path"], plan)
    summary = build_approval_summary(
        workspace,
        plan_path=paths["plan_path"],
        rollback_plan_path=paths["rollback_plan_path"],
        save_on_success=True,
    )
    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            now=JST_NOW,
            random_hex="abcdef",
        )
    approval = load_approval_record(approval_path)
    apply_connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\n", ["ok"]
        )
        for host in ("leaf01", "leaf02")
    }
    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        execute_approved_apply(
            workspace,
            approval,
            plan_path=paths["plan_path"],
            rollback_plan_path=paths["rollback_plan_path"],
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: apply_connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )
    after = _after_snapshot(workspace)
    _write_verified_after_results(workspace)
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        transition_workflow(
            workspace, "after_running", lock=lock, now=JST_NOW
        )
        transition_workflow(
            workspace, "after_completed", lock=lock, now=JST_NOW
        )
    created = []

    def connect(host):
        connection = FakeSaveConnection(
            f"hostname {host}\nfeature nv overlay\nvlan {host[-2:]}\n",
            diff="vlan pending",
        )
        created.append(connection)
        return connection

    with OperationLock(workspace, "save", now=JST_NOW) as lock:
        execution = execute_approved_save(
            workspace,
            approval,
            plan_path=paths["plan_path"],
            rollback_plan_path=paths["rollback_plan_path"],
            after_snapshot_path=after,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=connect,
            disconnect=lambda _connection: None,
            save_command="copy running-config startup-config",
            success_marker="Copy complete.",
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "APPLIED_AND_VERIFIED"
    assert sum(len(connection.save_calls) for connection in created) == 2
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "completed"
    assert (
        workspace.operation_root
        / "apply/devices/leaf01/save-result.json"
    ).is_file()
    apply_execution = json.loads(
        (workspace.operation_root / "apply/execution.json").read_text()
    )
    assert apply_execution["status"]["result"] == "APPLIED_AND_VERIFIED"


def test_normal_approved_rollback_runs_reverse_order(tmp_path, monkeypatch):
    workspace, paths = _candidate(tmp_path)
    plan = json.loads(paths["plan_path"].read_text(encoding="utf-8"))
    plan["capability_level"] = "APPLY_VERIFIED"
    plan["artifacts"] = {
        "before_snapshot": str(paths["before_snapshot_path"]),
        "inventory": str(paths["inventory_path"]),
        "inventory_sha256": source_sha256(paths["inventory_path"]),
    }
    _write_json(paths["plan_path"], plan)
    summary = build_approval_summary(
        workspace,
        plan_path=paths["plan_path"],
        rollback_plan_path=paths["rollback_plan_path"],
    )
    with OperationLock(workspace, "approve", now=JST_NOW) as lock:
        approval_path = create_approval_record(
            workspace,
            summary,
            lock=lock,
            confirm=lambda _summary: True,
            now=JST_NOW,
            random_hex="abcdef",
        )
    approval = load_approval_record(approval_path)
    apply_connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\n", ["ok"]
        )
        for host in ("leaf01", "leaf02")
    }
    with OperationLock(workspace, "apply", now=JST_NOW) as lock:
        execute_approved_apply(
            workspace,
            approval,
            plan_path=paths["plan_path"],
            rollback_plan_path=paths["rollback_plan_path"],
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: apply_connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        transition_workflow(
            workspace, "after_running", lock=lock, now=JST_NOW
        )
        transition_workflow(
            workspace, "after_completed", lock=lock, now=JST_NOW
        )
    after = _after_snapshot(workspace)
    connected = []
    rollback_connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\nvlan {host[-2:]}\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }
    with OperationLock(workspace, "rollback", now=JST_NOW) as lock:
        execution = execute_approved_rollback(
            workspace,
            approval,
            plan_path=paths["plan_path"],
            rollback_plan_path=paths["rollback_plan_path"],
            current_snapshot_path=after,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: (
                connected.append(host) or rollback_connections[host]
            ),
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "ROLLED_BACK_PENDING_HEALTH"
    assert connected == ["leaf02", "leaf01"]
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rolled_back"

    before = json.loads(paths["before_snapshot_path"].read_text())
    rollback = json.loads(json.dumps(before))
    rollback["phase"] = "rollback"
    rollback["collection_id"] = "rollback-001"
    rollback["created_at"] = "2026-08-02T15:00:00+09:00"
    for host in ("leaf01", "leaf02"):
        before_source = Path(
            before["hosts"][host]["sources"]["running_config"]["file"]
        )
        rollback_source = (
            workspace.operation_root
            / "health/rollback/raw"
            / f"{host}_run.txt"
        )
        rollback_source.parent.mkdir(parents=True, exist_ok=True)
        rollback_source.write_text(before_source.read_text(), encoding="utf-8")
        rollback_source.chmod(0o600)
        source = rollback["hosts"][host]["sources"]["running_config"]
        source["file"] = str(rollback_source)
        source["sha256"] = source_sha256(rollback_source).removeprefix(
            "sha256:"
        )
    rollback_path = _write_json(
        workspace.operation_root / "health/rollback/snapshot.json",
        rollback,
    )
    comparison = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "rollback",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["nxos-overlay"],
        "result": "PASS",
        "counts": {
            "pass": 1,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }
    monkeypatch.setattr(
        "alred.managed_operation.load_resolved_profiles",
        lambda _path: {},
    )
    monkeypatch.setattr(
        "alred.managed_operation.compare_snapshots",
        lambda *_args, **_kwargs: dict(comparison),
    )
    with OperationLock(workspace, "rollback-verify", now=JST_NOW) as lock:
        verification = verify_approved_rollback(
            workspace,
            rollback_snapshot_path=rollback_path,
            plan_path=paths["plan_path"],
            lock=lock,
            now=lambda: JST_NOW + timedelta(hours=3),
        )

    assert verification["status"]["snapshot_fresh"] is True
    assert verification["status"]["result"] == "ROLLED_BACK_AND_VERIFIED"
    checklist = workspace.operation_root / "rollback/verification-checklist.md"
    assert checklist.is_file()
    assert "[x] `raw_running_config_restored`: PASS" in checklist.read_text()


def test_qualification_apply_records_serial_success_without_save(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }
    connected = []

    with OperationLock(workspace, "qualify", now=JST_NOW) as lock:
        execution = execute_qualification_apply(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: (
                connected.append(host) or connections[host]
            ),
            disconnect=lambda connection: setattr(
                connection,
                "disconnected",
                True,
            ),
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "APPLIED_PENDING_HEALTH"
    assert connected == ["leaf01", "leaf02"]
    assert all(connection.disconnected for connection in connections.values())
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "apply_completed"
    assert (
        workspace.operation_root
        / "qualification/apply/devices/leaf01/commands.log"
    ).is_file()
    assert execution["status"]["devices"]["leaf01"]["save"] is None


def test_qualification_apply_stops_all_config_on_before_drift(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    connection = FakeQualificationConnection(
        "hostname leaf01\nfeature changed\n",
        ["must not run"],
    )

    with OperationLock(workspace, "qualify", now=JST_NOW) as lock:
        execution = execute_qualification_apply(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda _host: connection,
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "APPLY_FAILED"
    assert connection.config_calls == []
    assert execution["status"]["devices"]["leaf02"]["status"] == "NOT_STARTED"
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rollback_required"


def test_qualification_apply_precheck_timeout_is_state_unknown(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    connection = FakeQualificationConnection(
        TimeoutError("show timeout"),
        ["must not run"],
    )

    with OperationLock(workspace, "qualify", now=JST_NOW) as lock:
        execution = execute_qualification_apply(
            workspace,
            record,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda _host: connection,
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "DEVICE_STATE_UNKNOWN"
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rollback_required"


def test_qualification_rollback_is_reverse_serial_and_does_not_save(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _run_apply(workspace, record)
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        for state in (
            "after_running",
            "after_completed",
        ):
            transition_workflow(workspace, state, lock=lock, now=JST_NOW)
    snapshot = _after_snapshot(workspace)
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\nvlan {host[-2:]}\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }
    connected = []

    with OperationLock(workspace, "qualify-rollback", now=JST_NOW) as lock:
        execution = execute_qualification_rollback(
            workspace,
            record,
            current_snapshot_path=snapshot,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: (
                connected.append(host) or connections[host]
            ),
            disconnect=lambda connection: setattr(
                connection,
                "disconnected",
                True,
            ),
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "ROLLED_BACK_PENDING_HEALTH"
    assert connected == ["leaf02", "leaf01"]
    assert all(
        device["save"] is None
        for device in execution["status"]["devices"].values()
    )
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rolled_back"
    assert (
        workspace.operation_root
        / "qualification/rollback/devices/leaf02/commands.log"
    ).is_file()


def test_qualification_rollback_drift_stays_rollback_required(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _run_apply(
        workspace,
        record,
        first_output="% Invalid command at '^' marker.",
    )
    snapshot = _after_snapshot(workspace)
    connection = FakeQualificationConnection(
        "hostname leaf02\nunexpected drift\n",
        ["must not run"],
    )

    with OperationLock(workspace, "qualify-rollback", now=JST_NOW) as lock:
        execution = execute_qualification_rollback(
            workspace,
            record,
            current_snapshot_path=snapshot,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda _host: connection,
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    assert execution["status"]["result"] == "ROLLBACK_FAILED"
    assert connection.config_calls == []
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rollback_required"


def test_expired_qualification_record_still_allows_safety_rollback(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _run_apply(
        workspace,
        record,
        first_output="% Invalid command at '^' marker.",
    )
    snapshot = _after_snapshot(workspace)
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\nvlan {host[-2:]}\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }

    with OperationLock(workspace, "qualify-rollback", now=JST_NOW) as lock:
        execution = execute_qualification_rollback(
            workspace,
            record,
            current_snapshot_path=snapshot,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=lambda: JST_NOW + timedelta(hours=5),
        )

    assert execution["status"]["result"] == "ROLLED_BACK_PENDING_HEALTH"


def test_qualification_rollback_rejects_residual_vlan_reference(tmp_path):
    workspace, record = _approved_candidate(tmp_path)
    _run_apply(
        workspace,
        record,
        first_output="% Invalid command at '^' marker.",
    )
    snapshot = _after_snapshot(
        workspace,
        extra_by_host={"leaf02": "switchport access vlan 02\n"},
    )

    with OperationLock(workspace, "qualify-rollback", now=JST_NOW) as lock:
        with pytest.raises(QualificationError, match="residual references"):
            execute_qualification_rollback(
                workspace,
                record,
                current_snapshot_path=snapshot,
                inventory_hosts={
                    host: {"device_type": "nxos"}
                    for host in ("leaf01", "leaf02")
                },
                connect=lambda _host: pytest.fail("must not connect"),
                disconnect=lambda _connection: None,
                lock=lock,
                now=_clock(),
            )


def test_qualification_rollback_verification_requires_raw_and_semantic_match(
    tmp_path,
    monkeypatch,
):
    workspace, record = _approved_candidate(tmp_path)
    _run_apply(workspace, record)
    with OperationLock(workspace, "state", now=JST_NOW) as lock:
        transition_workflow(
            workspace,
            "after_running",
            lock=lock,
            now=JST_NOW,
        )
        transition_workflow(
            workspace,
            "after_completed",
            lock=lock,
            now=JST_NOW,
        )
    after_snapshot = _after_snapshot(workspace)
    connections = {
        host: FakeQualificationConnection(
            f"hostname {host}\nfeature nv overlay\nvlan {host[-2:]}\n",
            ["ok"],
        )
        for host in ("leaf01", "leaf02")
    }
    with OperationLock(workspace, "qualify-rollback", now=JST_NOW) as lock:
        execute_qualification_rollback(
            workspace,
            record,
            current_snapshot_path=after_snapshot,
            inventory_hosts={
                host: {"device_type": "nxos"}
                for host in ("leaf01", "leaf02")
            },
            connect=lambda host: connections[host],
            disconnect=lambda _connection: None,
            lock=lock,
            now=_clock(),
        )

    before = json.loads(
        (
            workspace.operation_root / "health/before/snapshot.json"
        ).read_text(encoding="utf-8")
    )
    rollback = json.loads(json.dumps(before))
    rollback["phase"] = "rollback"
    rollback["collection_id"] = "rollback-001"
    rollback["created_at"] = "2026-08-02T15:00:00+09:00"
    for host in ("leaf01", "leaf02"):
        before_source = Path(
            before["hosts"][host]["sources"]["running_config"]["file"]
        )
        rollback_source = (
            workspace.operation_root
            / "health"
            / "rollback"
            / "raw"
            / f"{host}_run.txt"
        )
        rollback_source.parent.mkdir(parents=True, exist_ok=True)
        rollback_source.write_text(
            before_source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        rollback_source.chmod(0o600)
        source = rollback["hosts"][host]["sources"]["running_config"]
        source["file"] = str(rollback_source)
        source["sha256"] = source_sha256(rollback_source).removeprefix(
            "sha256:"
        )
    rollback_path = _write_json(
        workspace.operation_root / "health/rollback/snapshot.json",
        rollback,
    )
    comparison = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "compare",
        "started_at": JST_NOW.isoformat(),
        "completed_at": JST_NOW.isoformat(),
        "profiles": ["nxos-overlay"],
        "result": "PASS",
        "counts": {
            "pass": 1,
            "warn": 0,
            "fail": 0,
            "unknown": 0,
            "not_applicable": 0,
        },
        "checks": [],
    }
    monkeypatch.setattr(
        "alred.qualification.load_resolved_profiles",
        lambda _path: {},
    )
    monkeypatch.setattr(
        "alred.qualification.compare_snapshots",
        lambda *_args, **_kwargs: dict(comparison),
    )

    with OperationLock(
        workspace,
        "qualification-rollback-verify",
        now=JST_NOW,
    ) as lock:
        verification = verify_qualification_rollback(
            workspace,
            record,
            rollback_snapshot_path=rollback_path,
            lock=lock,
            now=lambda: JST_NOW + timedelta(hours=3),
        )

    assert verification["status"]["result"] == "ROLLED_BACK_AND_VERIFIED"
    assert verification["status"]["snapshot_fresh"] is True
    assert verification["status"]["raw_config_equal"] is True
    assert verification["status"]["semantic_config_equal"] is True
    assert verification["devices"]["leaf01"]["raw_config_diff"] == {
        "added_line_count": 0,
        "removed_line_count": 0,
    }
    checklist = (
        workspace.operation_root
        / "qualification/rollback/verification-checklist.md"
    )
    assert checklist.is_file()
    assert "# Rollback Verification Checklist" in checklist.read_text()
    assert load_operation_metadata(
        workspace.operation_root
    )["spec"]["workflow_state"] == "rolled_back_and_verified"
