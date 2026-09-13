"""Validate design artifacts without registering production Route Diff schemas."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1] / "docs/design/network-ops/examples/route-diff-review"


def validator(name):
    schema = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def example(name):
    path = ROOT / name
    return yaml.safe_load(path.read_text()) if path.suffix == ".yaml" else json.loads(path.read_text())


@pytest.mark.parametrize(("schema", "file"), [
    ("route-diff-policy", "route-policy.example.yaml"),
    ("route-diff-policy", "expected-changes.example.yaml"),
    ("route-diff-source-map", "source-map.example.yaml"),
    ("route-diff-review", "review-record.example.json"),
    ("route-diff", "route_diff/route-diff.json"),
    ("route-snapshot", "contracts/route-snapshot-before.example.json"),
    ("route-snapshot", "contracts/route-snapshot-after.example.json"),
])
def test_design_examples_match_structural_schema(schema, file):
    validator(schema).validate(example(file))


@pytest.mark.parametrize("mutation", ["unknown", "zero_paths", "missing_metric", "negative_metric", "null_prefix"])
def test_policy_rejects_malformed_inputs(mutation):
    value = deepcopy(example("expected-changes.example.yaml"))
    rule = value["spec"]["expected_changes"][0]
    if mutation == "unknown":
        rule["metrics"] = 30
    elif mutation == "zero_paths":
        value["spec"]["required_routes"][0]["min_paths"] = 0
    elif mutation == "missing_metric":
        del rule["after"]["paths"][0]["metric"]
    elif mutation == "negative_metric":
        rule["after"]["paths"][0]["metric"] = -1
    else:
        rule["prefix"] = None
    assert list(validator("route-diff-policy").iter_errors(value))


def test_source_map_requires_complete_range_and_command_for_body_only():
    value = deepcopy(example("source-map.example.yaml"))
    source = value["spec"]["hosts"][0]["before"][0]
    source["start_line"] = 1
    assert list(validator("route-diff-source-map").iter_errors(value))
    source["end_line"] = 10
    validator("route-diff-source-map").validate(value)
    source["input_format"] = "nxos-route-text"
    assert list(validator("route-diff-source-map").iter_errors(value))
    source["command_id"] = "route_ipv4_all_vrfs"
    validator("route-diff-source-map").validate(value)


def test_snapshot_examples_include_unchanged_routes_and_resolvable_evidence():
    report = example("route_diff/route-diff.json")
    changed = {(r['device'], r['vrf'], r['family'], r['prefix']) for r in report['entries']}
    for side in ("before", "after"):
        snapshot = example(f"contracts/route-snapshot-{side}.example.json")
        assert len(snapshot['routes']) == 12
        identities = {(r['device'], r['vrf'], r['family'], r['prefix']) for r in snapshot['routes']}
        assert len(identities - changed) == 4
        sources = {s['id']: s for s in snapshot['sources']}
        for source in sources.values():
            raw = (ROOT / 'contracts' / source['path']).read_bytes()
            assert source['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest()
        for row in snapshot['routes']:
            e = row['evidence']
            source = sources[e['source_id']]
            lines = (ROOT / 'contracts' / source['path']).read_text().splitlines()
            assert 1 <= e['start_line'] <= e['end_line'] <= len(lines)


def test_output_additions_are_tolerated_but_major_changes_are_rejected():
    value = example("review-record.example.json")
    value['future_display_hint'] = 'allowed'
    validator('route-diff-review').validate(value)
    value['schema_version'] = 2
    assert list(validator('route-diff-review').iter_errors(value))
