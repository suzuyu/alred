from copy import deepcopy

from alred.capability import (
    evaluate_capability,
    load_capability_registry,
    required_overlay_capabilities,
)


def _changeset():
    return {
        "spec": {
            "l3vnis": [{"vni": 50001}],
            "l2vnis": [
                {
                    "vni": 10010,
                    "svi": {"ipv6_addresses": ["2001:db8::1/64"]},
                }
            ],
        }
    }


def _snapshot(hosts):
    return {
        "hosts": {
            host: {
                "common": {
                    "system": {
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
            }
            for host in hosts
        }
    }


def test_exact_c9300v_vpc_vtep_leaf_is_apply_verified():
    snapshot = _snapshot(["leaf01", "leaf02"])
    result = evaluate_capability(
        load_capability_registry(),
        snapshot,
        ["leaf01", "leaf02"],
        required_overlay_capabilities(_changeset()),
    )

    assert result["level"] == "APPLY_VERIFIED"
    assert all(
        device["missing_capabilities"] == []
        for device in result["devices"].values()
    )


def test_release_or_role_mismatch_fails_closed():
    snapshot = _snapshot(["leaf01"])
    changed = deepcopy(snapshot)
    changed["hosts"]["leaf01"]["common"]["system"]["version"] = "10.5(5)"

    result = evaluate_capability(
        load_capability_registry(),
        changed,
        ["leaf01"],
        required_overlay_capabilities(_changeset()),
    )

    assert result["level"] == "PLAN_ONLY"
    assert result["devices"]["leaf01"]["evidence"] is None
