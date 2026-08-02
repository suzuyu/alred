"""Managed command evidence layered on the existing Netmiko session."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .schema import API_VERSION, validate_document


NXOS_CLI_ERROR_PATTERNS = (
    re.compile(r"(?im)^%\s*(?:invalid|incomplete|ambiguous)\s+command"),
    re.compile(r"(?im)^%\s*error"),
    re.compile(r"(?im)^error:"),
    re.compile(r"(?im)configuration update aborted"),
    re.compile(r"(?im)command rejected"),
)


def nxos_cli_error(response: str) -> str | None:
    """Return the first matching NX-OS CLI error line."""
    for pattern in NXOS_CLI_ERROR_PATTERNS:
        match = pattern.search(response)
        if match:
            line_start = response.rfind("\n", 0, match.start()) + 1
            line_end = response.find("\n", match.end())
            if line_end == -1:
                line_end = len(response)
            return response[line_start:line_end].strip()
    return None


def load_managed_config_commands(path: str | Path) -> list[str]:
    """Load generated config while removing file/paste control lines."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"managed config must be a regular file: {candidate}")
    commands: list[str] = []
    excluded = {"configure terminal", "configure", "end"}
    prohibited = (
        "reload",
        "write erase",
        "erase startup-config",
        "install all",
        "boot nxos",
        "no feature ",
        "feature ",
    )
    for raw in candidate.read_text(encoding="utf-8").splitlines():
        command = raw.strip()
        if not command or command.startswith(("!", "#")):
            continue
        if command.lower() in excluded:
            continue
        if command.lower().startswith(prohibited):
            raise ValueError(
                f"prohibited command in managed config: {command}"
            )
        commands.append(command)
    if not commands:
        raise ValueError(f"managed config contains no commands: {candidate}")
    return commands


def execute_config_session(
    connection: Any,
    commands: Iterable[str],
    *,
    now: Callable[[], datetime],
    detect_cli_errors: bool = True,
    raise_transport_errors: bool = False,
) -> dict[str, Any]:
    """Send one command at a time and preserve response/unknown state."""
    command_list = list(commands)
    results: list[dict[str, Any]] = []
    state = "SUCCESS"
    first_failure: dict[str, Any] | None = None
    for index, command in enumerate(command_list, start=1):
        started_at = now()
        response = ""
        error = None
        status = "SUCCESS"
        try:
            response = connection.send_config_set(
                [command],
                read_timeout=120,
                enter_config_mode=(index == 1),
                exit_config_mode=False,
            )
            response = str(response).rstrip()
            cli_error = nxos_cli_error(response) if detect_cli_errors else None
            if cli_error is not None:
                status = "FAILED"
                error = cli_error
                state = "FAILED"
        except Exception as exc:
            if raise_transport_errors:
                raise
            # The command may have reached the device before timeout/disconnect.
            status = "UNKNOWN"
            error = f"{type(exc).__name__}: {exc}"
            state = "UNKNOWN"
        completed_at = now()
        record = {
            "index": index,
            "command": command,
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "status": status,
            "response": response,
            "error": error,
        }
        results.append(record)
        if status != "SUCCESS":
            first_failure = {
                "command_index": index,
                "message": error or "command failed",
            }
            break
    for index in range(len(results) + 1, len(command_list) + 1):
        timestamp = now().isoformat(timespec="seconds")
        results.append(
            {
                "index": index,
                "command": command_list[index - 1],
                "started_at": timestamp,
                "completed_at": timestamp,
                "status": "NOT_STARTED",
                "response": "",
                "error": "stopped after previous command failure",
            }
        )
    try:
        connection.exit_config_mode()
    except Exception:
        # A failed exit does not change a known command result. The caller
        # disconnects and performs post-collection before any retry.
        pass
    return {
        "status": state,
        "commands": results,
        "first_failure": first_failure,
    }


def execute_save_session(
    connection: Any,
    *,
    command: str,
    success_marker: str | None,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """Execute a save command and return full evidence without retry."""
    started_at = now()
    response = ""
    error = None
    status = "SUCCESS"
    try:
        prompt = connection.find_prompt()
        response = str(
            connection.send_command(
                command,
                expect_string=re.escape(prompt),
                read_timeout=180,
                auto_find_prompt=False,
                strip_prompt=False,
                strip_command=False,
                cmd_verify=False,
            )
        ).rstrip()
        if success_marker and success_marker not in response:
            status = "FAILED"
            error = (
                f"save response does not contain success marker "
                f"{success_marker!r}"
            )
    except Exception as exc:
        status = "UNKNOWN"
        error = f"{type(exc).__name__}: {exc}"
    completed_at = now()
    return {
        "command": command,
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "status": status,
        "response": response,
        "error": error,
    }


def execute_serial_devices(
    device_order: Sequence[str],
    commands: Mapping[str, Sequence[str]],
    *,
    connect: Callable[[str], Any],
    disconnect: Callable[[Any], None],
    now: Callable[[], datetime],
    precheck: (
        Callable[
            [str, Any],
            tuple[bool, str] | tuple[bool, str, str],
        ]
        | None
    ) = None,
    before_commands: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Execute serial:1 and stop the current/remaining devices on failure."""
    devices: dict[str, Any] = {
        hostname: {
            "status": "NOT_STARTED",
            "commands": [],
            "save": None,
        }
        for hostname in device_order
    }
    first_failure = None
    for hostname in device_order:
        device_commands = list(commands.get(hostname, ()))
        if not device_commands:
            devices[hostname]["status"] = "NO_CHANGE"
            continue
        connection = None
        try:
            connection = connect(hostname)
        except Exception as exc:
            devices[hostname]["status"] = "FAILED"
            first_failure = {
                "host": hostname,
                "stage": "connect",
                "message": f"{type(exc).__name__}: {exc}",
            }
            break
        try:
            if precheck is not None:
                try:
                    precheck_result = precheck(hostname, connection)
                    ok, message = precheck_result[:2]
                    precheck_status = (
                        precheck_result[2]
                        if len(precheck_result) == 3
                        else "FAILED"
                    )
                except Exception as exc:
                    ok = False
                    message = f"{type(exc).__name__}: {exc}"
                    precheck_status = "UNKNOWN"
                if not ok:
                    if precheck_status not in {"FAILED", "UNKNOWN"}:
                        raise ValueError(
                            "precheck failure status must be FAILED or UNKNOWN"
                        )
                    devices[hostname]["status"] = precheck_status
                    first_failure = {
                        "host": hostname,
                        "stage": "command",
                        "message": f"precheck failed: {message}",
                    }
                    break
            if before_commands is not None:
                before_commands(hostname)
            result = execute_config_session(
                connection,
                device_commands,
                now=now,
            )
            devices[hostname]["status"] = result["status"]
            devices[hostname]["commands"] = result["commands"]
            if result["status"] != "SUCCESS":
                failure = result["first_failure"] or {}
                first_failure = {
                    "host": hostname,
                    "stage": "command",
                    "command_index": failure.get("command_index", 1),
                    "message": failure.get("message", "command failed"),
                }
                break
        finally:
            try:
                disconnect(connection)
            except Exception:
                pass
    overall = "SUCCESS"
    if first_failure is not None:
        failed_device = devices[first_failure["host"]]
        overall = (
            "UNKNOWN"
            if failed_device["status"] == "UNKNOWN"
            else "FAILED"
        )
    return {
        "status": overall,
        "devices": devices,
        "first_failure": first_failure,
    }


def build_execution_document(
    *,
    change_id: str,
    mode: str,
    started_at: datetime,
    completed_at: datetime,
    timezone_name: str,
    execution_plan_sha256: str,
    rollback_plan_sha256: str,
    approval_id: str,
    serial_result: Mapping[str, Any],
    config_artifacts: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Build and validate the persisted apply/rollback execution evidence."""
    if mode not in {"apply", "rollback"}:
        raise ValueError(f"unsupported execution mode: {mode}")
    devices = {}
    for hostname, result in serial_result["devices"].items():
        artifact = config_artifacts[hostname]
        devices[hostname] = {
            "status": result["status"],
            "config_path": artifact["path"],
            "config_sha256": artifact["sha256"],
            "commands": list(result["commands"]),
            "save": result.get("save"),
        }
    serial_status = serial_result["status"]
    if mode == "apply":
        overall = {
            "SUCCESS": "APPLIED_PENDING_HEALTH",
            "FAILED": "APPLY_FAILED",
            "UNKNOWN": "DEVICE_STATE_UNKNOWN",
        }[serial_status]
    else:
        overall = {
            "SUCCESS": "ROLLED_BACK_PENDING_HEALTH",
            "FAILED": "ROLLBACK_FAILED",
            "UNKNOWN": "ROLLBACK_FAILED",
        }[serial_status]
    document = {
        "api_version": API_VERSION,
        "kind": "OverlayConfigExecution",
        "metadata": {
            "change_id": change_id,
            "mode": mode,
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "timezone": timezone_name,
        },
        "spec": {
            "execution_plan_sha256": execution_plan_sha256,
            "rollback_plan_sha256": rollback_plan_sha256,
            "approval_id": approval_id,
            "serial": 1,
            "stop_on_first_error": True,
            "automatic_retry": False,
        },
        "status": {
            "result": overall,
            "devices": devices,
            "first_failure": serial_result["first_failure"],
        },
    }
    validate_document(document, kind="OverlayConfigExecution")
    return document
