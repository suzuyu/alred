from pathlib import Path

from alred.cli import (
    build_collect_output_path,
    get_run_input_dir,
    list_collect_output_files,
    resolve_collect_output_path,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "collect" / "synthetic"


def test_collect_output_path_uses_hostname_suffix_and_format(tmp_path):
    assert build_collect_output_path(tmp_path, "leaf01", "run", None) == (
        tmp_path / "leaf01_run.txt"
    )
    assert build_collect_output_path(tmp_path, "leaf01", "run", "json") == (
        tmp_path / "leaf01_run.json"
    )


def test_run_input_prefers_config_subdirectory():
    assert get_run_input_dir(FIXTURE_ROOT) == FIXTURE_ROOT / "config"
    assert list_collect_output_files(FIXTURE_ROOT / "config", "run") == [
        FIXTURE_ROOT / "config" / "leaf01_run.txt"
    ]


def test_collect_resolver_prefers_json_when_both_formats_exist(tmp_path):
    text_path = tmp_path / "leaf01_run.txt"
    json_path = tmp_path / "leaf01_run.json"
    text_path.write_text("text", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    assert resolve_collect_output_path(tmp_path, "leaf01", "run") == json_path
    assert list_collect_output_files(tmp_path, "run") == [json_path]


def test_synthetic_transcript_preserves_hostname_and_command_boundaries():
    transcript = (
        FIXTURE_ROOT / "show_lists" / "leaf01" / "leaf01_shows.log"
    ).read_text(encoding="utf-8")

    assert transcript.count("### COMMAND:") == 2
    assert "leaf01# show version" in transcript
    assert "leaf01# show system config reload-pending" in transcript
