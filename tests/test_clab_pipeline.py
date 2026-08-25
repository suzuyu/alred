import json
from pathlib import Path

import pytest
import yaml

import alred.cli as cli
from alred.cli import build_parser
from alred.portable_evidence import EvidencePackageError


def _only_attempt(root: Path) -> Path:
    attempts = sorted((root / "output/clab-set-cmds/attempts").iterdir())
    assert len(attempts) == 1
    return attempts[0]


def test_clab_set_cmds_records_failed_step_and_preserves_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    pipeline_root = tmp_path / "output/clab-set-cmds"
    pipeline_root.mkdir(parents=True)
    previous_current = {
        "attempt_id": "previous-success",
        "status": "SUCCESS",
    }
    current_path = pipeline_root / "current.json"
    current_path.write_text(
        json.dumps(previous_current, indent=2) + "\n",
        encoding="utf-8",
    )
    existing_output = tmp_path / "output/topology.clab.yaml"
    existing_output.write_text("name: previous\n", encoding="utf-8")

    def fail_collect(_args) -> None:
        raise ValueError("synthetic password=do-not-store pipeline failure")

    monkeypatch.setattr(cli, "cmd_collect", fail_collect)
    args = build_parser().parse_args(
        [
            "clab-set-cmds",
            "--hosts",
            "hosts.yaml",
            "--password",
            "do-not-store",
        ]
    )

    with pytest.raises(ValueError, match="pipeline failure"):
        args.func(args)

    assert json.loads(current_path.read_text(encoding="utf-8")) == previous_current
    attempt = _only_attempt(tmp_path)
    manifest = yaml.safe_load(
        (attempt / "pipeline-manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["metadata"]["status"] == "FAILED"
    assert manifest["metadata"]["completed_at"]
    assert manifest["spec"]["device_access_performed"] is True
    assert manifest["spec"]["error"] == {
        "code": "VALIDATION_ERROR",
        "type": "ValueError",
        "message": "synthetic password=[REDACTED] pipeline failure",
    }
    steps = {step["name"]: step for step in manifest["spec"]["steps"]}
    assert steps["source-resolution"]["status"] == "COMPLETED"
    assert steps["collect-clab"]["status"] == "FAILED"
    assert steps["collect-clab"]["error"] == manifest["spec"]["error"]
    assert all(
        step["status"] == "NOT_STARTED"
        for name, step in steps.items()
        if name not in {"source-resolution", "collect-clab"}
    )
    assert len(manifest["spec"]["outputs"]) == 1
    assert manifest["spec"]["outputs"][0]["path"] == "output/topology.clab.yaml"
    assert manifest["spec"]["outputs"][0]["sha256"]
    assert (
        manifest["spec"]["outputs"][0]["disposition"]
        == "unchanged_existing"
    )
    serialized = (attempt / "pipeline-manifest.yaml").read_text(encoding="utf-8")
    assert "do-not-store" not in serialized


def test_clab_set_cmds_records_interrupted_step_without_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def interrupt_collect(_args) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_collect", interrupt_collect)
    args = build_parser().parse_args(
        ["clab-set-cmds", "--hosts", "hosts.yaml"]
    )

    with pytest.raises(KeyboardInterrupt):
        args.func(args)

    attempt = _only_attempt(tmp_path)
    manifest = yaml.safe_load(
        (attempt / "pipeline-manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["metadata"]["status"] == "INTERRUPTED"
    steps = {step["name"]: step for step in manifest["spec"]["steps"]}
    assert steps["collect-clab"]["status"] == "INTERRUPTED"
    assert manifest["spec"]["error"]["code"] == "INTERRUPTED"
    assert not (tmp_path / "output/clab-set-cmds/current.json").exists()


def test_clab_set_cmds_records_source_resolution_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(
        [
            "clab-set-cmds",
            "--evidence-package",
            "missing-package.tar.gz",
        ]
    )

    with pytest.raises(EvidencePackageError, match="missing-package"):
        args.func(args)

    attempt = _only_attempt(tmp_path)
    manifest = yaml.safe_load(
        (attempt / "pipeline-manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["metadata"]["status"] == "FAILED"
    assert manifest["spec"]["source"] == {
        "type": "evidence-package-archive",
        "path": "missing-package.tar.gz",
    }
    steps = {step["name"]: step for step in manifest["spec"]["steps"]}
    assert steps["source-resolution"]["status"] == "FAILED"
    assert all(
        step["status"] == "NOT_STARTED"
        for name, step in steps.items()
        if name != "source-resolution"
    )
    assert not (tmp_path / "output/clab-set-cmds/current.json").exists()
