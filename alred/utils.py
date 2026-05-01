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

from .constants import NETMIKO_DEVICE_TYPE_OVERRIDE_MAP


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


def _load_credentials_data(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Load optional structured credentials from --credentials or ./clab_credentials.yaml.
    """
    explicit_path = getattr(args, "credentials", None)
    credentials_path = explicit_path
    if not credentials_path and hasattr(args, "credentials"):
        default_path = Path("clab_credentials.yaml")
        if default_path.exists():
            credentials_path = str(default_path)

    if not credentials_path:
        return {}

    cache_key = "_credentials_data"
    cached = getattr(args, cache_key, None)
    cached_path = getattr(args, "_credentials_path", None)
    if cached is not None and cached_path == credentials_path:
        return cached

    data = load_yaml(credentials_path)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid credentials YAML format: {credentials_path}")

    credentials_data = data.get("credentials", data)
    if credentials_data is None:
        credentials_data = {}
    if not isinstance(credentials_data, dict):
        raise ValueError(f"Invalid credentials section in YAML: {credentials_path}")

    setattr(args, cache_key, credentials_data)
    setattr(args, "_credentials_path", credentials_path)
    return credentials_data


def _credential_field(entry: Dict[str, Any], key: str) -> str | None:
    """
    Resolve a credential field from a literal value or <key>_env reference.
    """
    value = entry.get(key)
    if value is not None:
        return str(value)

    env_name = entry.get(f"{key}_env")
    if env_name:
        env_value = os.environ.get(str(env_name))
        if env_value is not None:
            return env_value
    return None


def _merge_credential_entry(resolved: Dict[str, str], entry: Any) -> None:
    """
    Merge username/password/enable_secret values from one credential entry.
    """
    if not isinstance(entry, dict):
        return

    for key in ("username", "password", "enable_secret"):
        value = _credential_field(entry, key)
        if value is not None:
            resolved[key] = value


def _get_structured_credentials(
    args: argparse.Namespace,
    device_type: str,
    host: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """
    Resolve credentials from defaults, device_type, and hosts sections.
    """
    credentials_data = _load_credentials_data(args)
    if not credentials_data:
        return {}

    resolved: Dict[str, str] = {}
    _merge_credential_entry(resolved, credentials_data.get("defaults"))

    device_type_credentials = credentials_data.get("device_type", {})
    if isinstance(device_type_credentials, dict):
        _merge_credential_entry(resolved, device_type_credentials.get(device_type))

    hostname = str((host or {}).get("hostname", ""))
    hosts = credentials_data.get("hosts", {})
    if hostname and isinstance(hosts, dict):
        _merge_credential_entry(resolved, hosts.get(hostname))

    return resolved


def get_credentials_for_device(
    args: argparse.Namespace,
    device_type: str,
    host: Dict[str, Any] | None = None,
) -> Tuple[str, str, str]:
    """
    Resolve SSH credentials from CLI args, optional credentials YAML, or environment variables.

    Priority:
    1. CLI args
    2. Optional credentials YAML: hosts > device_type > defaults
    3. For asa/asav only: ALRED_FW_USERNAME / ALRED_FW_PASSWORD / ALRED_FW_ENABLE_SECRET
    4. ALRED_USERNAME / ALRED_PASSWORD / ALRED_ENABLE_SECRET
    5. NW_TOOL_* variables for legacy compatibility

    Args:
        args: Parsed CLI args.
        device_type: Target device type.
        host: Optional host inventory entry used for host-specific credentials.

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

    structured_credentials = _get_structured_credentials(args, device_type, host)

    username = (
        args.username
        or structured_credentials.get("username")
        or fw_username
        or os.environ.get("ALRED_USERNAME")
        or os.environ.get("NW_TOOL_USERNAME")
    )
    password = (
        args.password
        or structured_credentials.get("password")
        or fw_password
        or os.environ.get("ALRED_PASSWORD")
        or os.environ.get("NW_TOOL_PASSWORD")
    )
    enable_secret = (
        getattr(args, "enable_secret", None)
        or structured_credentials.get("enable_secret")
        or fw_enable_secret
        or os.environ.get("ALRED_ENABLE_SECRET", "")
        or os.environ.get("NW_TOOL_ENABLE_SECRET", "")
    )
    if not username or not password:
        raise ValueError(
            "Username/password not provided. Use --username/--password or define "
            "credentials YAML or ALRED_USERNAME / ALRED_PASSWORD in .env. "
            "Use -k/--ask-pass to enter the SSH password at runtime. "
            "For asa/asav you can also use ALRED_FW_USERNAME / ALRED_FW_PASSWORD. "
            "Legacy NW_TOOL_* variables are still supported."
        )
    return username, password, enable_secret


def resolve_netmiko_device_type(host: Dict[str, Any]) -> str | None:
    """
    Return the Netmiko driver name to use for a host.
    """
    device_type = str(host.get("device_type") or "")
    override = NETMIKO_DEVICE_TYPE_OVERRIDE_MAP.get(device_type)
    if override:
        return override

    netmiko_device_type = host.get("netmiko_device_type")
    return str(netmiko_device_type) if netmiko_device_type else None


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


def get_netmiko_unavailable_message(import_error: BaseException | None = None) -> str:
    """
    Return a context-aware error message for missing Netmiko.
    """
    if getattr(sys, "frozen", False):
        message = (
            "netmiko is not available in this binary build. "
            "Rebuild the PyInstaller binary with netmiko bundled "
            '(for example, `--collect-submodules netmiko`) or use an updated release binary.'
        )
    else:
        message = "netmiko is not installed. Please install with: pip install netmiko"
    if import_error is not None:
        return f"{message} Root import error: {import_error}"
    return message
