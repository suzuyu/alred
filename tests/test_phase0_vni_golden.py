from pathlib import Path

from alred.cli import (
    read_vni_gateway_csv,
    render_vni_add_config_lines,
    render_vni_delete_config_lines,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "vni" / "current"


def _golden_lines(name: str) -> list[str]:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8").splitlines()


def test_current_vni_add_renderer_matches_golden():
    records = read_vni_gateway_csv(str(FIXTURE_ROOT / "target.csv"))

    assert render_vni_add_config_lines(records) == _golden_lines("add_leaf01.txt")


def test_current_vni_delete_renderer_matches_golden():
    records = read_vni_gateway_csv(str(FIXTURE_ROOT / "target.csv"))

    assert render_vni_delete_config_lines(records, []) == _golden_lines(
        "delete_leaf01.txt"
    )
