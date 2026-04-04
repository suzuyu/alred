"""
alred package.

Network topology collection / normalization / rendering utilities.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def _resolve_version() -> str:
    try:
        return version("alred")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            if tomllib is not None:
                with pyproject_path.open("rb") as fh:
                    data = tomllib.load(fh)
                return data.get("project", {}).get("version", "0.0.0")
            for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if line.startswith("version"):
                    _, _, value = line.partition("=")
                    return value.strip().strip('"').strip("'") or "0.0.0"
        return "0.0.0"


__version__ = _resolve_version()

from .cli import main

__all__ = ["main", "__version__"]
