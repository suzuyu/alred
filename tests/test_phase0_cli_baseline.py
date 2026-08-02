import argparse
from pathlib import Path
import sys

import pytest

from alred.cli import build_parser, main


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _subcommand_names(parser: argparse.ArgumentParser) -> list[str]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return sorted(action.choices)


def test_top_level_command_set_matches_as_is_fixture():
    expected = (
        FIXTURE_ROOT / "cli" / "top_level_commands.txt"
    ).read_text(encoding="utf-8").splitlines()

    assert _subcommand_names(build_parser()) == expected


def test_top_level_help_exits_successfully(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--help"])

    assert exc_info.value.code == 0
    assert "generate-vni-config" in capsys.readouterr().out


def test_unknown_command_exits_with_argparse_error():
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["not-a-command"])

    assert exc_info.value.code == 2


def test_health_before_requires_input_mode_without_traceback(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(sys, "argv", ["alred", "health-check", "before"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    error = capsys.readouterr().err
    assert exc_info.value.code == 2
    assert "one of the arguments --input --collect is required" in error
    assert "Traceback" not in error


def test_health_before_dependent_option_error_is_concise(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        sys,
        "argv",
        ["alred", "health-check", "before", "--collect"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    error = capsys.readouterr().err
    assert exc_info.value.code == 2
    assert "VALIDATION_ERROR: --collect requires --hosts" in error
    assert "Traceback" not in error
