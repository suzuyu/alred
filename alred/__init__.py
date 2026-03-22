"""
alred package.

Network topology collection / normalization / rendering utilities.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


def _resolve_version() -> str:
    try:
        return version("alred")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with pyproject_path.open("rb") as fh:
                data = tomllib.load(fh)
            return data.get("project", {}).get("version", "0.0.0")
        return "0.0.0"


__version__ = _resolve_version()

from .cli import main

__all__ = ["main", "__version__"]
