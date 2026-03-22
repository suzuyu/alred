"""
Generic utility helpers for alred.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


def setup_logging(log_file: str | None = None, verbose: bool = False) -> logging.Logger:
    """
    Create and configure the tool logger.

    Args:
        log_file: Optional log file path.
        verbose: If True, console logging is DEBUG. Otherwise INFO.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("alred")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def save_yaml(data: Dict[str, Any], path: str) -> None:
    """
    Save a dictionary as YAML.

    Args:
        data: YAML-serializable dictionary.
        path: Output file path.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_yaml(path: str | None) -> Dict[str, Any]:
    """
    Load a YAML file into a dictionary.

    Args:
        path: YAML file path. If None, returns empty dict.

    Returns:
        Parsed YAML data.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path:
        return {}

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def write_text(path: str | Path, lines: List[str]) -> None:
    """
    Write a list of lines to a text file.

    Args:
        path: Output file path.
        lines: Lines to write.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_output_dir(default: str = "raw") -> str:
    """
    Return default output directory, optionally overridden by environment variable.

    Args:
        default: Fallback directory.

    Returns:
        Output directory string.
    """
    return os.environ.get("ALRED_OUTPUT_DIR", os.environ.get("NW_TOOL_OUTPUT_DIR", default))


def get_raw_dir(default: str = "raw") -> str:
    """
    Return default raw collection directory.

    Priority:
    1. ALRED_RAW_DIR
    2. ALRED_OUTPUT_DIR
    3. NW_TOOL_RAW_DIR / NW_TOOL_OUTPUT_DIR (legacy compatibility)
    3. function default

    Args:
        default: Fallback directory.

    Returns:
        Raw directory string.
    """
    return (
        os.environ.get("ALRED_RAW_DIR")
        or os.environ.get("ALRED_OUTPUT_DIR")
        or os.environ.get("NW_TOOL_RAW_DIR")
        or os.environ.get("NW_TOOL_OUTPUT_DIR", default)
    )


def get_links_dir(default: str = "output") -> str:
    """
    Return default normalized links output directory.

    Priority:
    1. ALRED_LINKS_DIR
    2. ALRED_OUTPUT_DIR
    3. NW_TOOL_LINKS_DIR / NW_TOOL_OUTPUT_DIR
    3. function default

    Args:
        default: Fallback directory.

    Returns:
        Links directory string.
    """
    return (
        os.environ.get("ALRED_LINKS_DIR")
        or os.environ.get("ALRED_OUTPUT_DIR")
        or os.environ.get("NW_TOOL_LINKS_DIR")
        or os.environ.get("NW_TOOL_OUTPUT_DIR", default)
    )


def get_topology_dir(default: str = "output") -> str:
    """
    Return default topology output directory.

    Priority:
    1. ALRED_TOPOLOGY_DIR
    2. ALRED_OUTPUT_DIR
    3. NW_TOOL_TOPOLOGY_DIR / NW_TOOL_OUTPUT_DIR
    3. function default

    Args:
        default: Fallback directory.

    Returns:
        Topology directory string.
    """
    return (
        os.environ.get("ALRED_TOPOLOGY_DIR")
        or os.environ.get("ALRED_OUTPUT_DIR")
        or os.environ.get("NW_TOOL_TOPOLOGY_DIR")
        or os.environ.get("NW_TOOL_OUTPUT_DIR", default)
    )


def get_default_log_dir(default: str = "logs") -> str:
    """
    Return default log directory, optionally overridden by environment variable.

    Args:
        default: Fallback directory.

    Returns:
        Log directory string.
    """
    return os.environ.get("ALRED_LOG_DIR", os.environ.get("NW_TOOL_LOG_DIR", default))


def get_credentials_for_device(args: argparse.Namespace, device_type: str) -> Tuple[str, str, str]:
    """
    Resolve SSH credentials from CLI args or environment variables.

    Priority:
    1. CLI args
    2. For asa/asav only: ALRED_FW_USERNAME / ALRED_FW_PASSWORD / ALRED_FW_ENABLE_SECRET
    3. ALRED_USERNAME / ALRED_PASSWORD / ALRED_ENABLE_SECRET
    4. NW_TOOL_* variables for legacy compatibility

    Args:
        args: Parsed CLI args.
        device_type: Target device type.

    Returns:
        (username, password, enable_secret)

    Raises:
        ValueError: If either credential is missing.
    """
    is_firewall = device_type in {"asa", "asav"}
    fw_username = (
        os.environ.get("ALRED_FW_USERNAME") or os.environ.get("NW_TOOL_FW_USERNAME")
    ) if is_firewall else None
    fw_password = (
        os.environ.get("ALRED_FW_PASSWORD") or os.environ.get("NW_TOOL_FW_PASSWORD")
    ) if is_firewall else None
    fw_enable_secret = (
        os.environ.get("ALRED_FW_ENABLE_SECRET", os.environ.get("NW_TOOL_FW_ENABLE_SECRET", ""))
    ) if is_firewall else None

    username = args.username or fw_username or os.environ.get("ALRED_USERNAME") or os.environ.get("NW_TOOL_USERNAME")
    password = args.password or fw_password or os.environ.get("ALRED_PASSWORD") or os.environ.get("NW_TOOL_PASSWORD")
    enable_secret = (
        getattr(args, "enable_secret", None)
        or fw_enable_secret
        or os.environ.get("ALRED_ENABLE_SECRET", "")
        or os.environ.get("NW_TOOL_ENABLE_SECRET", "")
    )
    if not username or not password:
        raise ValueError(
            "Username/password not provided. Use --username/--password or define "
            "ALRED_USERNAME / ALRED_PASSWORD in .env. "
            "For asa/asav you can also use ALRED_FW_USERNAME / ALRED_FW_PASSWORD. "
            "Legacy NW_TOOL_* variables are still supported."
        )
    return username, password, enable_secret


def get_ssh_options() -> Dict[str, Any]:
    """
    Return SSH options from environment variables.

    Returns:
        Dictionary containing port and timeout.
    """
    return {
        "port": int(os.environ.get("ALRED_SSH_PORT", os.environ.get("NW_TOOL_SSH_PORT", 22))),
        "timeout": int(os.environ.get("ALRED_TIMEOUT", os.environ.get("NW_TOOL_TIMEOUT", 60))),
    }
