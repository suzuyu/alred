"""
Helpers for accessing bundled package resources across source, installed, and
PyInstaller environments.
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_package_dir() -> Path:
    """
    Return the root directory that contains the packaged ``alred`` resources.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "alred"
    return Path(__file__).resolve().parent


def get_resource_dir(name: str) -> Path:
    """
    Return a named resource directory under the packaged ``alred`` root.
    """
    return get_package_dir() / name
