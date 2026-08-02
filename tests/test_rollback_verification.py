from alred.rollback_verification import (
    build_device_verification,
    render_rollback_verification_checklist,
    rollback_snapshot_is_fresh,
    rollback_verification_passes,
    semantic_difference_paths,
)


def test_rollback_snapshot_freshness_uses_execution_completion_time():
    execution = {
        "metadata": {"completed_at": "2026-08-02T21:00:14+09:00"}
    }

    assert rollback_snapshot_is_fresh(
        {"created_at": "2026-08-02T21:00:14+09:00"}, execution
    )
    assert not rollback_snapshot_is_fresh(
        {"created_at": "2026-08-02T21:00:13+09:00"}, execution
    )


def test_integrated_verification_requires_all_four_gates():
    healthy = {
        "snapshot_fresh": True,
        "health_result": "PASS",
        "raw_config_equal": True,
        "semantic_config_equal": True,
    }

    assert rollback_verification_passes(**healthy)
    for key, failed_value in (
        ("snapshot_fresh", False),
        ("health_result", "WARN"),
        ("raw_config_equal", False),
        ("semantic_config_equal", False),
    ):
        candidate = dict(healthy)
        candidate[key] = failed_value
        assert not rollback_verification_passes(**candidate)


def test_semantic_difference_paths_use_json_pointer_without_values():
    before = {"vrfs": {"TENANT/A": {"l3vni": 50001}}, "nve": {"up": True}}
    rollback = {"vrfs": {"TENANT/A": {"l3vni": 50002}}, "nve": {"up": True}}

    assert semantic_difference_paths(before, rollback) == [
        "/vrfs/TENANT~1A/l3vni"
    ]


def test_device_verification_records_counts_but_not_raw_lines():
    evidence = build_device_verification(
        ["hostname leaf01", "username secret password 0 hidden"],
        ["hostname leaf01", "feature nv overlay"],
        {"nve": {"configured": False}},
        {"nve": {"configured": True}},
    )

    assert evidence["raw_config_equal"] is False
    assert evidence["raw_config_diff"] == {
        "added_line_count": 1,
        "removed_line_count": 1,
    }
    assert evidence["semantic_difference_paths"] == ["/nve/configured"]
    assert "secret" not in repr(evidence)


def test_rollback_checklist_groups_gates_devices_and_non_pass_health():
    verification = {
        "metadata": {
            "change_id": "CHG-1",
            "verified_at": "2026-08-02T21:16:32+09:00",
        },
        "status": {
            "result": "ROLLBACK_HEALTH_FAILED",
            "health_result": "WARN",
            "snapshot_fresh": True,
            "raw_config_equal": False,
            "semantic_config_equal": False,
        },
        "devices": {
            "leaf01": {
                "raw_config_equal": False,
                "semantic_config_equal": False,
                "raw_config_diff": {
                    "added_line_count": 1,
                    "removed_line_count": 2,
                },
                "semantic_difference_paths": ["/nve/l2vnis/10010"],
            }
        },
        "artifacts": {
            "before_snapshot": "before.json",
            "rollback_snapshot": "rollback.json",
            "health_result": "health-result.json",
            "verification_json": "verification.json",
        },
    }
    health = {
        "checks": [
            {
                "host": "leaf01",
                "check_id": "logging_health",
                "result": "WARN",
                "message": "5 new abnormal log records were detected",
            }
        ]
    }

    markdown = render_rollback_verification_checklist(verification, health)

    assert "[x] `rollback_snapshot_fresh`: PASS" in markdown
    assert "[ ] `health_restored`: WARN" in markdown
    assert "## Device: `leaf01`" in markdown
    assert "added=1, removed=2" in markdown
    assert "`/nve/l2vnis/10010`" in markdown
    assert "`leaf01/logging_health`: WARN" in markdown
