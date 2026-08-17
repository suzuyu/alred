from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_REQUIREMENTS = REPO_ROOT / "packaging/linux/requirements-build.lock"
DOCKERFILES = tuple(
    REPO_ROOT / f"packaging/linux/Dockerfile.{variant}"
    for variant in ("glibc217", "glibc228", "glibc234")
)


def _locked_package_names() -> set[str]:
    names: set[str] = set()
    for line in BUILD_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        names.add(stripped.split("==", 1)[0].lower())
    return names


def test_binary_build_lock_contains_runtime_and_pyinstaller_dependencies():
    assert {
        "jinja2",
        "jsonschema",
        "netmiko",
        "ntc-templates",
        "pyinstaller",
        "python-dotenv",
        "pyyaml",
    } <= _locked_package_names()


def test_all_glibc_builds_install_the_shared_locked_requirements():
    for dockerfile in DOCKERFILES:
        content = dockerfile.read_text(encoding="utf-8")
        assert (
            "COPY packaging/linux/requirements-build.lock "
            "/tmp/alred-requirements-build.lock"
        ) in content
        assert "-r /tmp/alred-requirements-build.lock" in content


def test_pyinstaller_spec_collects_alred_package_resources():
    content = (REPO_ROOT / "alred.spec").read_text(encoding="utf-8")
    assert 'collect_data_files("alred")' in content
    assert 'collect_data_files("ntc_templates")' in content
    assert 'collect_submodules("netmiko")' in content
    assert '("THIRD_PARTY_LICENSES.txt", ".")' in content


def test_ntc_templates_are_a_direct_dependency_with_third_party_notice():
    project = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    notices = (REPO_ROOT / "THIRD_PARTY_LICENSES.txt").read_text(
        encoding="utf-8"
    )

    assert '"ntc-templates>=9.0,<10"' in project
    assert "ntc-templates" in notices
    assert "TextFSM" in notices
    assert "Apache License 2.0" in notices


def test_release_artifact_helper_defaults_to_glibc217_and_keeps_options():
    script = REPO_ROOT / "scripts/build_release_artifacts_linux_x86_64.sh"
    completed = subprocess.run(
        ["bash", str(script), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--variant glibc217|glibc228|glibc234" in completed.stderr
    assert "--all-variants" in completed.stderr

    content = script.read_text(encoding="utf-8")
    assert "variants=(glibc217)" in content
    assert "variants=(glibc217 glibc228 glibc234)" in content
