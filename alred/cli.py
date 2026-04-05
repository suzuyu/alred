"""
CLI entrypoint and subcommands for alred.
"""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import difflib
import json
import math
import os
import tarfile
import time
from logging import Logger
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
import yaml

try:
    from netmiko import ConnectHandler
    NETMIKO_IMPORT_ERROR: BaseException | None = None
except ImportError as exc:
    ConnectHandler = None
    NETMIKO_IMPORT_ERROR = exc

from .constants import (
    DEFAULT_CISCO_N9KV_KIND_ENV,
    DEFAULT_CISCO_N9KV_KIND_IMAGE,
    DEFAULT_CISCO_N9KV_KIND_NAME,
    DEFAULT_CLAB_SET_GENERATE_CLAB_AUTO_FILES,
    DEFAULT_CISCO_N9KV_STARTUP_CONFIG_TEMPLATE,
    DEFAULT_CLAB_SET_CMDS,
    DEFAULT_CONNECT_CHECK_TIMEOUT,
    DEFAULT_CLAB_TOPOLOGY_NAME,
    DEFAULT_DESCRIPTION_RULES_PATH,
    DEFAULT_KIND_CLUSTER_CONFIG_BASE_DIR,
    DEFAULT_KIND_CLUSTER_CONFIG_CONTAINER_MOUNT_PATH,
    DEFAULT_KIND_CLUSTER_CONFIG_FILENAME_TEMPLATE,
    DEFAULT_KIND_CLUSTER_CONFIG_MOUNT_SUBDIR,
    DEFAULT_KIND_CLUSTER_NODE_SCRIPT_CONTENT,
    DEFAULT_KIND_CLUSTER_NODE_SCRIPT_FILENAME,
    DEFAULT_KIND_CLUSTER_IMAGE,
    DEFAULT_KIND_CLUSTER_KIND,
    DEFAULT_KIND_CLUSTER_STARTUP_CONFIG_TEMPLATE,
    DEFAULT_KIND_NODE_BIND,
    DEFAULT_KIND_NODE_INIT_SCRIPT,
    DEFAULT_LINUX_KIND_IMAGE,
    DEFAULT_LINUX_NODE_BIND,
    DEFAULT_LINUX_NODE_EXEC,
    DEFAULT_LOG_ROTATION,
    DEFAULT_HOSTS_PATH,
    DEFAULT_LINKS_CANDIDATES_FILENAME,
    DEFAULT_LINKS_CONFIRMED_FILENAME,
    DEFAULT_LOGGING_THRESHOLD_MAP,
    DEFAULT_ROLES_PATH,
    DEFAULT_SAMPLES_DIR,
    DEFAULT_SHOW_COMMANDS_PATH,
    DEFAULT_TOPOLOGY_CLAB_FILENAME,
    DEFAULT_TOPOLOGY_DRAWIO_ALL_FILENAME,
    DEFAULT_TOPOLOGY_DRAWIO_FILENAME,
    DEFAULT_TOPOLOGY_GRAPHVIZ_FILENAME,
    DEFAULT_TOPOLOGY_MERMAID_FILENAME,
    DEFAULT_VNI_MAP_CSV_FILENAME,
    DEFAULT_VNI_MAP_MD_FILENAME,
    LLDP_COMMAND_MAP,
    PRIVILEGED_EXEC_DEVICE_TYPES,
    RUNNING_CONFIG_COMMAND_MAP,
    RUNNING_CONFIG_DIFF_COMMAND_MAP,
    RUNNING_CONFIG_DIFF_EXCLUDE_PREFIXES_MAP,
    SAVE_CONFIG_COMMAND_MAP,
    SAVE_CONFIG_SUCCESS_MARKER_MAP,
    SHOW_LOGGING_COMMAND_MAP,
    PUSH_CONFIG_EXCLUDE_LINE_PREFIXES_MAP,
)
from .collect import (
    ConnectCheckResult,
    TransportType,
    build_collector,
    is_nxos_host,
    probe_transport_connectivity,
)
from . import __version__
from .inventory import (
    build_inventory,
    build_terraform_provider_lines,
    load_inventory_data,
    load_inventory_map_from_list,
    parse_hosts_txt,
)
from .logging_check import (
    HostLoggingCheckResult,
    LoggingWarning,
    check_host_logging,
    extract_latest_show_logging_block,
    load_check_patterns,
    parse_last_window,
    render_check_logging_report,
)
from .parsing import (
    build_description_records,
    is_excluded_interface,
    load_description_rules,
    load_mappings,
    load_policy_file,
    load_roles,
    merge_lldp_and_description_links,
    normalize_hostname,
    normalize_interface_name,
    normalize_link_records,
    parse_lldp_file,
    read_links_csv,
    should_collect_running_config,
    should_exclude,
    should_include,
    write_links_csv,
)
from .render import (
    render_drawio_xml_lines,
    render_graphviz_dot_lines,
    render_mermaid_markdown_lines,
)
from .resources import (
    get_resource_dir,
)
from .templates import (
    render_named_template_lines,
)
from .transform import (
    parse_mgmt_ipv4_subnet,
    transform_inventory_mgmt_subnet,
    transform_run_config_text,
)
from .topology import (
    build_node_definitions_from_links,
    build_node_mgmt_ip_map,
    build_normalized_inventory_and_mgmt_maps,
    detect_node_role,
    detect_node_roles,
    get_role_priority,
    is_network_device_type,
    prepare_rendered_candidate_links,
    prepare_rendered_links,
)
from .utils import (
    get_credentials_for_device,
    get_default_log_dir,
    get_links_dir,
    get_netmiko_unavailable_message,
    get_output_dir,
    get_raw_dir,
    get_ssh_options,
    get_topology_dir,
    load_yaml,
    save_yaml,
    setup_logging,
    write_text,
)

def get_lldp_command(device_type: str) -> str:
    """
    Return LLDP collection command for device type.

    Args:
        device_type: Device type string.

    Returns:
        Command string.
    """
    cmd = LLDP_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    raise ValueError(f"Unsupported device_type for LLDP command: {device_type}")


def get_running_config_command(device_type: str) -> str:
    """
    Return running-config command for device type.

    Args:
        device_type: Device type string.

    Returns:
        Command string.
    """
    cmd = RUNNING_CONFIG_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    raise ValueError(f"Unsupported device_type for running-config command: {device_type}")


def get_running_config_diff_command(device_type: str) -> str:
    """
    Return running-config diff command for device type.

    Args:
        device_type: Device type string.

    Returns:
        Command string.
    """
    cmd = RUNNING_CONFIG_DIFF_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    raise ValueError(f"Unsupported device_type for running-config diff command: {device_type}")


def get_show_logging_command(device_type: str) -> str:
    """
    Return show logging command for device type.
    """
    cmd = SHOW_LOGGING_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    raise ValueError(f"Unsupported device_type for show logging command: {device_type}")


def get_save_config_command(device_type: str) -> str:
    """
    Return save-config command for device type.
    """
    cmd = SAVE_CONFIG_COMMAND_MAP.get(device_type)
    if cmd:
        return cmd
    raise ValueError(f"Unsupported device_type for save-config command: {device_type}")


def get_save_config_success_marker(device_type: str) -> str | None:
    """
    Return save-config success marker for device type when strict output validation is needed.
    """
    return SAVE_CONFIG_SUCCESS_MARKER_MAP.get(device_type)


def connect_to_host(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
):
    """
    Open a Netmiko connection and enter enable mode when required.
    """
    if ConnectHandler is None:
        raise RuntimeError(get_netmiko_unavailable_message(NETMIKO_IMPORT_ERROR))

    hostname = host["hostname"]
    ip = host["ip"]
    device_type = host["device_type"]
    netmiko_device_type = host.get("netmiko_device_type")

    if not netmiko_device_type:
        raise ValueError(f"{hostname}: netmiko_device_type is not defined for device_type={device_type}")

    conn_params = {
        "device_type": netmiko_device_type,
        "host": ip,
        "username": username,
        "password": password,
        **get_ssh_options(),
    }
    if enable_secret:
        conn_params["secret"] = enable_secret

    logger.info("CONNECT %s (%s %s)", hostname, device_type, ip)
    conn = ConnectHandler(**conn_params)

    if device_type in PRIVILEGED_EXEC_DEVICE_TYPES:
        if not enable_secret:
            conn.disconnect()
            raise ValueError(
                f"{hostname}: device_type={device_type} requires enable secret. "
                "Use --enable-secret or define ALRED_ENABLE_SECRET."
            )
        logger.info("ENABLE %s", hostname)
        conn.enable()

    return conn


def collect_from_host(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    lldp_output_dir: str,
    run_output_dir: str,
    before_run_input_dir: str,
    show_output_dir: str,
    policy: Dict[str, List[str]],
    logger: Logger,
    transport: TransportType = "auto",
    show_commands: Optional[List[str]] = None,
    show_read_timeout: int = 120,
    show_only: bool = False,
    run_config_only: bool = False,
    show_run_diff: bool = False,
    show_run_diff_comands: bool = False,
    old_generation_id: str = "",
) -> Dict[str, str]:
    """
    Collect LLDP and optional running-config from one host.

    Args:
        host: Host definition.
        username: SSH username.
        password: SSH password.
        lldp_output_dir: LLDP output directory.
        run_output_dir: Running-config output directory.
        before_run_input_dir: Baseline running-config input directory for diff comparison.
        show_output_dir: Show command output directory.
        policy: Policy dictionary.
        logger: Logger.
        transport: Preferred command transport.
        show_commands: Optional extra commands to run and save to old/<generation>/<hostname>_shows.log.
        show_read_timeout: Read timeout used for extra show commands.
        show_only: If True, skip LLDP/running-config collection.
        run_config_only: If True, collect only running-config and skip LLDP.
        show_run_diff: If True, collect running-config and return unified diff against existing <hostname>_run.txt.
        show_run_diff_comands: If True, run device-native diff command and return output section.
        old_generation_id: Shared generation id (YYYYMMDDHHMMSS) used for rotating timestamped outputs.

    """
    hostname = host["hostname"]
    device_type = host["device_type"]

    lldp_outdir = Path(lldp_output_dir)
    run_outdir = Path(run_output_dir)
    show_outdir = Path(show_output_dir)
    lldp_outdir.mkdir(parents=True, exist_ok=True)
    run_outdir.mkdir(parents=True, exist_ok=True)
    show_outdir.mkdir(parents=True, exist_ok=True)
    collector = build_collector(host, username, password, enable_secret, logger, transport)
    result: Dict[str, str] = {}
    rotation_limit = get_log_rotation_limit()
    rotated_output_keys: set[tuple[str, str]] = set()

    def normalize_run_lines_for_diff(text: str, host_device_type: str) -> List[str]:
        """
        Normalize running-config lines for diff comparison.
        """
        lines = text.splitlines()
        prefixes = RUNNING_CONFIG_DIFF_EXCLUDE_PREFIXES_MAP.get(host_device_type, [])
        if not prefixes:
            return lines
        return [line for line in lines if not any(line.lstrip().startswith(p) for p in prefixes)]

    def prune_old_generations(old_dir: Path) -> None:
        """
        Keep only the latest configured generations below old/.
        """
        if rotation_limit > 0:
            generations = sorted([p for p in old_dir.iterdir() if p.is_dir()])
            excess = len(generations) - rotation_limit
            if excess > 0:
                for stale in generations[:excess]:
                    shutil.rmtree(stale, ignore_errors=True)
                    logger.info("REMOVED OLD GENERATION %s", stale)

    def reset_collect_output_variants_once(output_dir: Path, suffix: str) -> None:
        """
        Remove existing current .txt/.json variants at most once per host/suffix in this run.
        """
        key = (str(output_dir), suffix)
        if key in rotated_output_keys:
            return
        rotated_output_keys.add(key)
        for candidate in get_collect_output_variants(output_dir, hostname, suffix):
            if candidate.exists():
                candidate.unlink()
                logger.info("REMOVED CURRENT MIRROR %s", candidate)

    def save_command_result(output_dir: Path, suffix: str, command_result: Any) -> None:
        """
        Save one successful command result to old/<generation>/ and update the latest mirror.
        """
        generation = old_generation_id or datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
        old_dir = output_dir / "old"
        generation_dir = old_dir / generation
        generation_dir.mkdir(parents=True, exist_ok=True)
        old_path = build_collect_output_path(generation_dir, hostname, suffix, command_result.output_format)
        old_path.write_text(command_result.output, encoding="utf-8")
        prune_old_generations(old_dir)

        reset_collect_output_variants_once(output_dir, suffix)
        output_path = build_collect_output_path(output_dir, hostname, suffix, command_result.output_format)
        output_path.write_text(command_result.output, encoding="utf-8")
        logger.info(
            "SAVED %s transport=%s%s",
            old_path,
            command_result.transport,
            f" fallback_from={command_result.fallback_from}" if command_result.fallback_from else "",
        )
        logger.info(
            "UPDATED CURRENT MIRROR %s transport=%s%s",
            output_path,
            command_result.transport,
            f" fallback_from={command_result.fallback_from}" if command_result.fallback_from else "",
        )

    def collect_base_command_both(command: str, read_timeout: int) -> List[Any]:
        """
        In auto mode on NX-OS, collect both NX-API and SSH variants.
        """
        if transport != "auto" or not is_nxos_host(host):
            return [collector.run_command(command, read_timeout=read_timeout)]

        collectors = [
            build_collector(host, username, password, enable_secret, logger, "nxapi"),
            build_collector(host, username, password, enable_secret, logger, "ssh"),
        ]
        results: List[Any] = []
        try:
            for base_collector in collectors:
                results.append(base_collector.run_command(command, read_timeout=read_timeout))
        finally:
            for base_collector in collectors:
                base_collector.close()
        logger.info(
            "AUTO DUAL COLLECT %s command=%s transports=%s",
            hostname,
            command,
            ",".join([r.transport for r in results if getattr(r, "ok", False)]),
        )
        return results

    try:
        run_cmd = get_running_config_command(device_type)
        run_output: Optional[str] = None
        run_output_format: Optional[str] = None
        previous_run_path: Path | None = None
        previous_run_output = ""

        if not show_only:
            if not run_config_only:
                lldp_cmd = get_lldp_command(device_type)
                lldp_results = collect_base_command_both(lldp_cmd, read_timeout=120)
                lldp_successes = [item for item in lldp_results if item.ok]
                if lldp_successes:
                    for item in lldp_successes:
                        save_command_result(lldp_outdir, "lldp", item)
                else:
                    logger.warning("SKIP SAVE %s command=%s", hostname, lldp_cmd)
            else:
                logger.info("SKIP LLDP %s: run-config-only enabled", hostname)

            if should_collect_running_config(device_type, policy):
                run_results = collect_base_command_both(run_cmd, read_timeout=300)
                run_successes = [item for item in run_results if item.ok]
                if run_successes:
                    for item in run_successes:
                        save_command_result(run_outdir, "run", item)
                    preferred_run_result = next(
                        (item for item in run_successes if item.transport == "nxapi"),
                        run_successes[0],
                    )
                    run_output = preferred_run_result.output
                    run_output_format = preferred_run_result.output_format
                else:
                    logger.warning("SKIP SAVE %s command=%s", hostname, run_cmd)
            else:
                logger.info(
                    "SKIP RUNCFG %s: device_type=%s not in collect_running_config_for",
                    hostname,
                    device_type,
                )
        else:
            logger.info("SKIP BASE COLLECT %s: --show-only enabled", hostname)

        if show_run_diff:
            if run_output is None:
                logger.info("RUN %s: %s (for --show-run-diff)", hostname, run_cmd)
                run_result = collector.run_command(run_cmd, read_timeout=300)
                if run_result.ok:
                    run_output = run_result.output
                    run_output_format = run_result.output_format

            if run_output is not None:
                previous_run_path = resolve_collect_output_path_for_format(
                    before_run_input_dir,
                    hostname,
                    "run",
                    run_output_format,
                )
                previous_run_output = (
                    previous_run_path.read_text(encoding="utf-8", errors="ignore")
                    if previous_run_path is not None and previous_run_path.exists()
                    else ""
                )

            if run_output is None:
                logger.info("SKIP RUN DIFF %s: command failed (%s)", hostname, run_cmd)
            elif previous_run_output:
                previous_lines = normalize_run_lines_for_diff(previous_run_output, device_type)
                current_lines = normalize_run_lines_for_diff(run_output, device_type)
                run_ext = ".json" if run_output_format == "json" else ".txt"
                previous_label = (
                    previous_run_path.name
                    if previous_run_path is not None
                    else f"{hostname}_run_prev{run_ext}"
                )
                current_label = f"{hostname}_run_current{run_ext}"
                diff_lines = list(
                    difflib.unified_diff(
                        previous_lines,
                        current_lines,
                        fromfile=previous_label,
                        tofile=current_label,
                        lineterm="",
                    )
                )
                if diff_lines:
                    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    section = [
                        f"### HOST: {hostname}",
                        f"### COLLECTED_AT: {collected_at}",
                        f"### COMMAND: {run_cmd}",
                        f"{hostname}# {run_cmd}",
                        *diff_lines,
                    ]
                    result["run_diff_section"] = "\n".join(section).rstrip()
                else:
                    result["run_diff_no_diff_host"] = hostname
                    logger.info("RUN DIFF NO CHANGE %s", hostname)
            else:
                logger.info(
                    "SKIP RUN DIFF %s: baseline file not found (%s)",
                    hostname,
                    previous_run_path or build_collect_output_path(before_run_input_dir, hostname, "run", None),
                )

        if show_run_diff_comands:
            try:
                run_diff_cmd = get_running_config_diff_command(device_type)
            except ValueError:
                logger.info(
                    "SKIP RUN DIFF COMMAND %s: unsupported device_type=%s",
                    hostname,
                    device_type,
                )
                run_diff_cmd = ""

            if run_diff_cmd:
                logger.info("RUN %s: %s (for --show-run-diff-comands)", hostname, run_diff_cmd)
                diff_result = collector.run_command(run_diff_cmd, read_timeout=show_read_timeout)
                diff_output = diff_result.output.strip() if diff_result.ok else ""
                if diff_output:
                    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    section = [
                        f"### HOST: {hostname}",
                        f"### COLLECTED_AT: {collected_at}",
                        f"### COMMAND: {run_diff_cmd}",
                        f"{hostname}# {run_diff_cmd}",
                        diff_output,
                    ]
                    result["run_diff_command_section"] = "\n".join(section).rstrip()
                elif diff_result.ok:
                    result["run_diff_command_no_diff_host"] = hostname
                    logger.info("RUN DIFF COMMAND NO CHANGE %s", hostname)

        if show_commands:
            host_json_outdir = show_outdir / hostname
            host_show_outdir = show_outdir / hostname
            sections: List[str] = []
            command_list_header = [
                "### COMMAND_LIST",
                *show_commands,
            ]

            for cmd in show_commands:
                if transport == "auto" and is_nxos_host(host):
                    json_sidecar_result = None
                    nxapi_show_collector = build_collector(host, username, password, enable_secret, logger, "nxapi")
                    ssh_show_collector = build_collector(host, username, password, enable_secret, logger, "ssh")
                    try:
                        nxapi_result = nxapi_show_collector.run_command(cmd, read_timeout=show_read_timeout)
                        ssh_result = ssh_show_collector.run_command(cmd, read_timeout=show_read_timeout)
                    finally:
                        nxapi_show_collector.close()
                        ssh_show_collector.close()

                    if nxapi_result.ok and nxapi_result.output_format == "json":
                        json_sidecar_result = nxapi_result

                    # Prefer SSH text in the .log file during auto mode.
                    if ssh_result.ok:
                        show_result = ssh_result
                    elif nxapi_result.ok:
                        show_result = nxapi_result
                    else:
                        show_result = ssh_result
                else:
                    json_sidecar_result = None
                    show_result = collector.run_command(cmd, read_timeout=show_read_timeout)

                output = show_result.output
                status = "OK" if show_result.ok else "ERROR"
                collected_at_dt = datetime.now().astimezone()
                collected_at = collected_at_dt.isoformat(timespec="seconds")

                json_result = json_sidecar_result or (
                    show_result if show_result.ok and show_result.output_format == "json" else None
                )

                if json_result is not None:
                    host_json_outdir.mkdir(parents=True, exist_ok=True)
                    json_filename = f"{hostname}_{sanitize_command_for_filename(cmd)}.json"
                    try:
                        json_text = json.dumps(json.loads(json_result.output), ensure_ascii=False, indent=2) + "\n"
                    except Exception:
                        json_text = json_result.output.rstrip() + "\n"
                    save_current_and_old_snapshot(
                        output_dir=host_json_outdir,
                        filename=json_filename,
                        content=json_text,
                        generation=old_generation_id or datetime.now().astimezone().strftime("%Y%m%d%H%M%S"),
                        keep_generations=rotation_limit,
                        logger=logger,
                        log_label=f"SHOW JSON {hostname} command={cmd}",
                    )

                section = [
                    f"### COMMAND: {cmd}",
                    f"### COLLECTED_AT: {collected_at}",
                    f"### STATUS: {status}",
                    f"### TRANSPORT: {show_result.transport}",
                    *(
                        [f"### OUTPUT_FORMAT: {show_result.output_format}"]
                        if show_result.output_format
                        else []
                    ),
                    *(
                        [f"### FALLBACK_FROM: {show_result.fallback_from}"]
                        if show_result.fallback_from
                        else []
                    ),
                    *(
                        [f"### ERROR: {show_result.error}"]
                        if show_result.error and not show_result.ok
                        else []
                    ),
                    f"{hostname}# {cmd}",
                    output.rstrip(),
                ]
                sections.append("\n".join(section).rstrip())

            body = "\n\n".join(sections).strip()
            save_current_and_old_snapshot(
                output_dir=host_show_outdir,
                filename=f"{hostname}_shows.log",
                content="\n".join(command_list_header).rstrip() + "\n\n" + body + "\n",
                generation=old_generation_id or datetime.now().astimezone().strftime("%Y%m%d%H%M%S"),
                keep_generations=rotation_limit,
                logger=logger,
                log_label=f"SHOW LIST {hostname}",
            )
    finally:
        collector.close()

    return result


def load_config_lines(path: str) -> List[str]:
    """
    Load push-config command lines from file.
    """
    lines: List[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def push_config_to_host(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    config_lines: List[str],
    logger: Logger,
) -> None:
    """
    Push config lines to a host.
    """
    hostname = host["hostname"]
    device_type = host["device_type"]
    conn = connect_to_host(host, username, password, enable_secret, logger)
    try:
        prefixes = PUSH_CONFIG_EXCLUDE_LINE_PREFIXES_MAP.get(device_type, [])
        filtered_lines = [
            line for line in config_lines
            if not any(line.lstrip().startswith(prefix) for prefix in prefixes)
        ]
        excluded_count = len(config_lines) - len(filtered_lines)
        if excluded_count > 0:
            logger.info(
                "FILTER CONFIG %s: excluded=%d remain=%d by device_type=%s",
                hostname,
                excluded_count,
                len(filtered_lines),
                device_type,
            )
        if not filtered_lines:
            logger.info("SKIP PUSH %s: no config lines after exclusion filter", hostname)
            return

        logger.info("PUSH CONFIG %s: lines=%d", hostname, len(filtered_lines))
        outputs: List[str] = []
        applied_count = 0
        for idx, line in enumerate(filtered_lines, start=1):
            try:
                out = conn.send_config_set(
                    [line],
                    read_timeout=120,
                    enter_config_mode=(idx == 1),
                    exit_config_mode=False,
                )
                outputs.append(out.rstrip())
                applied_count = idx
            except Exception as exc:
                logger.info(
                    "PUSH ERROR %s: applied_lines=%d/%d failed_line=%d command=%s error=%s",
                    hostname,
                    applied_count,
                    len(filtered_lines),
                    idx,
                    line,
                    exc,
                )
                raise

        try:
            conn.exit_config_mode()
        except Exception:
            # Best effort: disconnect in finally will close the session.
            pass

        logger.debug("PUSH RESULT %s:\n%s", hostname, "\n".join(outputs).rstrip())
    finally:
        conn.disconnect()
        logger.info("DISCONNECT %s", hostname)


def save_config_on_host(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    logger: Logger,
) -> None:
    """
    Save running-config on host after push phase.
    """
    hostname = host["hostname"]
    device_type = host["device_type"]
    save_cmd = get_save_config_command(device_type)
    success_marker = get_save_config_success_marker(device_type)
    conn = connect_to_host(host, username, password, enable_secret, logger)
    try:
        logger.info("SAVE CONFIG %s: %s", hostname, save_cmd)
        prompt = conn.find_prompt()
        save_out = conn.send_command(
            save_cmd,
            expect_string=re.escape(prompt),
            read_timeout=180,
            auto_find_prompt=False,
            strip_prompt=False,
            strip_command=False,
            cmd_verify=False,
        )
        logger.debug("SAVE RESULT %s:\n%s", hostname, save_out.rstrip())
        if success_marker and success_marker not in save_out:
            raise RuntimeError(
                f"save command did not return success marker {success_marker!r}: {save_out.strip()!r}"
            )
    finally:
        conn.disconnect()
        logger.info("DISCONNECT %s", hostname)


def print_operation_result_summary(label: str, attempted_count: int, failed_hosts: List[str]) -> None:
    """
    Print a concise operation summary with failed hosts when present.
    """
    print(f"\n=== {label} RESULT ===")
    if attempted_count == 0:
        print("No hosts were processed.")
    elif not failed_hosts:
        print("All hosts succeeded.")
    else:
        print(f"Failed hosts ({len(failed_hosts)}):")
        for hostname in sorted(failed_hosts):
            print(f"- {hostname}")
    print("====================")


def _build_connect_check_cache_key(host: Dict[str, Any], transport: TransportType, username: str) -> tuple[str, str, str, str]:
    """
    Build a stable cache key for pre-flight connectivity checks.
    """
    return (
        str(host.get("hostname", "")),
        str(host.get("ip", "")),
        transport,
        username,
    )


def filter_hosts_by_connect_check(
    hosts: List[Dict[str, Any]],
    args: argparse.Namespace,
    logger: Logger,
) -> tuple[List[Dict[str, Any]], List[ConnectCheckResult]]:
    """
    Run pre-flight connectivity/authentication checks and keep only reachable hosts.
    """
    if getattr(args, "skip_connect_check", False):
        logger.info("CONNECT CHECK skipped by --skip-connect-check")
        return hosts, []

    if not hosts:
        return hosts, []

    workers = max(1, getattr(args, "workers", 1))
    timeout = float(getattr(args, "connect_check_timeout", 3))
    cache = getattr(args, "_connect_check_cache", None)
    if cache is None:
        cache = {}
        setattr(args, "_connect_check_cache", cache)

    logger.info(
        "CONNECT CHECK START targets=%d transport=%s workers=%d timeout=%.1fs",
        len(hosts),
        getattr(args, "transport", "ssh"),
        workers,
        timeout,
    )
    started_at = time.perf_counter()

    reachable_hosts: List[Dict[str, Any]] = []
    failures: List[ConnectCheckResult] = []
    future_to_host: Dict[Any, Dict[str, Any]] = {}
    cached_results: Dict[str, ConnectCheckResult] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for host in hosts:
            username, password, enable_secret = get_credentials_for_device(args, str(host.get("device_type", "")))
            transport = getattr(args, "transport", "ssh")
            cache_key = _build_connect_check_cache_key(host, transport, username)
            cached = cache.get(cache_key)
            if cached is not None:
                cached_results[str(host.get("hostname", ""))] = cached
                continue
            future = executor.submit(
                probe_transport_connectivity,
                host,
                username,
                password,
                enable_secret,
                logger,
                transport,
                timeout,
            )
            future_to_host[future] = host

        for future in as_completed(future_to_host):
            host = future_to_host[future]
            result = future.result()
            username, _password, _enable_secret = get_credentials_for_device(args, str(host.get("device_type", "")))
            transport = getattr(args, "transport", "ssh")
            cache[_build_connect_check_cache_key(host, transport, username)] = result
            cached_results[str(host.get("hostname", ""))] = result

    for host in hosts:
        result = cached_results[str(host.get("hostname", ""))]
        if result.ok:
            reachable_hosts.append(host)
            fallback = f" fallback_from={result.fallback_from}" if result.fallback_from else ""
            logger.info(
                "CONNECT CHECK OK %s ip=%s requested=%s resolved=%s stage=%s elapsed=%.3fs%s",
                result.hostname,
                result.ip,
                result.requested_transport,
                result.resolved_transport or "unknown",
                result.stage,
                result.elapsed_seconds,
                fallback,
            )
        else:
            failures.append(result)
            logger.warning(
                "CONNECT CHECK FAIL %s ip=%s requested=%s stage=%s elapsed=%.3fs error=%s",
                result.hostname,
                result.ip,
                result.requested_transport,
                result.stage,
                result.elapsed_seconds,
                result.error or "unknown error",
            )

    total_elapsed = time.perf_counter() - started_at
    logger.info(
        "CONNECT CHECK SUMMARY reachable=%d unreachable=%d elapsed=%.3fs",
        len(reachable_hosts),
        len(failures),
        total_elapsed,
    )
    if getattr(args, "verbose", False):
        slowest = sorted(
            [*reachable_hosts],
            key=lambda _host: cached_results[str(_host.get("hostname", ""))].elapsed_seconds,
            reverse=True,
        )
        for host in slowest:
            result = cached_results[str(host.get("hostname", ""))]
            logger.debug(
                "CONNECT CHECK DETAIL %s elapsed=%.3fs requested=%s resolved=%s stage=%s ok=%s",
                result.hostname,
                result.elapsed_seconds,
                result.requested_transport,
                result.resolved_transport or "unknown",
                result.stage,
                result.ok,
            )
        for result in sorted(failures, key=lambda x: x.elapsed_seconds, reverse=True):
            logger.debug(
                "CONNECT CHECK DETAIL %s elapsed=%.3fs requested=%s resolved=%s stage=%s ok=%s error=%s",
                result.hostname,
                result.elapsed_seconds,
                result.requested_transport,
                result.resolved_transport or "unknown",
                result.stage,
                result.ok,
                result.error or "unknown error",
            )
    return reachable_hosts, failures


def print_connect_check_failures(label: str, failures: List[ConnectCheckResult]) -> None:
    """
    Print failed pre-flight connectivity/authentication checks.
    """
    if not failures:
        return
    print(f"\n=== {label} CONNECT CHECK FAILURES ===")
    for result in sorted(failures, key=lambda x: x.hostname):
        print(
            f"- {result.hostname} ({result.ip}) requested={result.requested_transport} "
            f"stage={result.stage}: {result.error or 'unknown error'}"
        )
    print("======================================")


def load_show_commands(path: str | None) -> List[str]:
    """
    Load extra show commands from a text file.

    Args:
        path: Optional file path. One command per line.

    Returns:
        Commands list.
    """
    if not path:
        return []

    grouped = load_show_command_groups(path)
    merged: List[str] = []
    for cmds in grouped.values():
        merged.extend(cmds)
    return merged


def load_show_command_groups(path: str | None) -> Dict[str, List[str]]:
    """
    Load grouped show commands from text file.

    Format:
      - Grouped only: section header [group-name]
      - Global commands must be under [all]

    Example:
      [all]
      show version
      [spine]
      show interface status
      [leaf]
      show interface brief
    """
    if not path:
        return {"all": []}

    groups: Dict[str, List[str]] = {"all": []}
    current_group: Optional[str] = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and len(line) > 2:
            current_group = line[1:-1].strip()
            if not current_group:
                current_group = "all"
            groups.setdefault(current_group, [])
            continue
        if current_group is None:
            raise ValueError("show-commands file format error: command must be under a section like [all]")
        groups.setdefault(current_group, []).append(line)
    return groups


def resolve_show_commands_for_host(
    host: Dict[str, Any],
    grouped_commands: Dict[str, List[str]],
    roles: Dict[str, Any],
) -> List[str]:
    """
    Resolve show commands for one host from grouped config.

    Order:
    1. all group commands
    2. device_type group commands (e.g. device_type:nxos)
    3. role group commands (e.g. spine/leaf)
    4. hostname group commands (exact hostname match)
    """
    resolved: List[str] = []
    seen = set()

    for cmd in grouped_commands.get("all", []):
        if cmd not in seen:
            seen.add(cmd)
            resolved.append(cmd)

    hostname = str(host.get("hostname", ""))
    device_type = str(host.get("device_type", "unknown"))
    role_keys = detect_node_roles(hostname, roles) if roles else ["other"]

    group_keys = [f"device_type:{device_type}", *role_keys, hostname]
    for group_key in group_keys:
        for cmd in grouped_commands.get(group_key, []):
            if cmd not in seen:
                seen.add(cmd)
                resolved.append(cmd)

    return resolved


def parse_host_filter(raw: str | None) -> Set[str]:
    """
    Parse comma-separated host filter string.

    Args:
        raw: Comma-separated hostnames.

    Returns:
        Hostname set.
    """
    if not raw:
        return set()

    hosts = set()
    for item in raw.split(","):
        x = item.strip()
        if x:
            hosts.add(x)
    return hosts


def select_target_hosts(
    hosts: List[Dict[str, Any]],
    policy: Dict[str, List[str]],
    logger: Logger,
    target_hosts: Set[str] | None = None,
) -> tuple[List[Dict[str, Any]], int]:
    """
    Filter inventory hosts by explicit hostname and policy.

    Returns:
        Tuple of selected targets and skipped count.
    """
    selected: List[Dict[str, Any]] = []
    skipped = 0
    effective_target_hosts = target_hosts or set()

    for host in hosts:
        hostname = str(host.get("hostname", ""))
        if effective_target_hosts and hostname not in effective_target_hosts:
            continue

        include_ok, include_reason = should_include(host, policy)
        if not include_ok:
            logger.info("SKIP %s: %s", hostname, include_reason)
            skipped += 1
            continue

        exclude_hit, exclude_reason = should_exclude(host, policy)
        if exclude_hit:
            logger.info("SKIP %s: %s", hostname, exclude_reason)
            skipped += 1
            continue

        selected.append(host)

    return selected, skipped


def resolve_hosts_path(raw: str | None, required: bool = False) -> str | None:
    """
    Resolve hosts file path.

    Priority:
    1. --hosts value
    2. DEFAULT_HOSTS_PATH if exists
    """
    if raw:
        return raw
    default_path = Path(DEFAULT_HOSTS_PATH)
    if default_path.exists():
        return str(default_path)
    if required:
        raise FileNotFoundError(
            f"hosts file not found. Specify --hosts or place ./{DEFAULT_HOSTS_PATH}"
        )
    return None


def resolve_generate_clab_hosts_path(raw: str | None) -> str | None:
    """
    Resolve hosts file path for generate-clab.

    Priority:
    1. --hosts value
    2. ./hosts.lab.yaml if exists
    3. ./hosts.yaml if exists
    """
    if raw:
        return raw
    for candidate in ("hosts.lab.yaml", DEFAULT_HOSTS_PATH):
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def resolve_show_commands_path(raw: str | None) -> str | None:
    """
    Resolve show-commands file path.

    Priority:
    1. --show-commands-file value
    2. DEFAULT_SHOW_COMMANDS_PATH if exists
    """
    if raw:
        return raw
    default_path = Path(DEFAULT_SHOW_COMMANDS_PATH)
    if default_path.exists():
        return str(default_path)
    return None


def get_log_rotation_limit() -> int:
    """
    Resolve rotation generation/file count from environment.
    """
    try:
        return int(os.environ.get("ALRED_LOG_ROTATION", os.environ.get("NW_TOOL_LOG_ROTATION", str(DEFAULT_LOG_ROTATION))))
    except ValueError:
        return DEFAULT_LOG_ROTATION


def archive_files_to_old_generation(
    base_dir: str | Path,
    pattern: str,
    generation: str,
    keep_generations: int,
    logger: Logger,
) -> int:
    """
    Move matched files in base_dir to old/<generation>/ and prune old generations.
    """
    base = Path(base_dir)
    if not base.exists():
        return 0

    old_dir = base / "old"
    old_dir.mkdir(parents=True, exist_ok=True)
    generation_dir = old_dir / generation
    generation_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for src in sorted(base.glob(pattern), key=lambda p: p.name):
        if not src.is_file():
            continue
        dst = generation_dir / src.name
        if dst.exists():
            seq = 1
            while True:
                dst = generation_dir / f"{src.stem}_{seq:02d}{src.suffix}"
                if not dst.exists():
                    break
                seq += 1
        src.replace(dst)
        moved += 1
        logger.info("MOVED OLD %s -> %s", src, dst)

    if keep_generations > 0:
        generations = sorted([p for p in old_dir.iterdir() if p.is_dir()])
        excess = len(generations) - keep_generations
        if excess > 0:
            for stale in generations[:excess]:
                shutil.rmtree(stale, ignore_errors=True)
                logger.info("REMOVED OLD GENERATION %s", stale)

    return moved


def prune_old_generations(old_dir: Path, keep_generations: int, logger: Logger) -> None:
    """
    Keep only latest N generations below old/.
    """
    if keep_generations <= 0:
        return

    generations = sorted([p for p in old_dir.iterdir() if p.is_dir()])
    excess = len(generations) - keep_generations
    if excess > 0:
        for stale in generations[:excess]:
            shutil.rmtree(stale, ignore_errors=True)
            logger.info("REMOVED OLD GENERATION %s", stale)


def save_current_and_old_snapshot(
    output_dir: str | Path,
    filename: str,
    content: str,
    generation: str,
    keep_generations: int,
    logger: Logger,
    log_label: str,
) -> tuple[Path, Path]:
    """
    Save one snapshot to old/<generation>/ and update the current mirror.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    old_dir = base / "old"
    generation_dir = old_dir / generation
    generation_dir.mkdir(parents=True, exist_ok=True)

    old_path = generation_dir / filename
    old_path.write_text(content, encoding="utf-8")
    prune_old_generations(old_dir, keep_generations, logger)

    current_path = base / filename
    current_path.write_text(content, encoding="utf-8")

    logger.info("SAVED %s %s", log_label, old_path)
    logger.info("UPDATED CURRENT MIRROR %s %s", log_label, current_path)

    return old_path, current_path


def create_collect_archive(
    output_dir: str | Path,
    generation: str,
    logger: Logger,
    allowed_hosts: Set[str] | None = None,
) -> Path:
    """
    Archive current collect outputs excluding any old/ directories.
    Keep only the latest configured collect-all tar.gz archives.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    archive_path = base / f"collect-all-{generation[:8]}-{generation[8:]}.tar.gz"
    archive_root = base.name
    keep_archives = get_log_rotation_limit()
    optional_root_files = [
        "show_commands.txt",
        "roles.yaml",
        "hosts.yaml",
    ]

    def is_archive_file(path: Path) -> bool:
        return path.name.endswith(".tar") or path.name.endswith(".tar.gz")

    with tarfile.open(archive_path, "w:gz") as tar:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(base)
            if len(relative_path.parts) == 1 and is_archive_file(path):
                continue
            if relative_path.parts and relative_path.parts[0] == "labconfig":
                continue
            if "old" in relative_path.parts:
                continue
            if not should_include_collect_archive_path(relative_path, allowed_hosts):
                logger.info("SKIP COLLECT ARCHIVE PATH filtered-host %s", relative_path)
                continue
            tar.add(path, arcname=str(Path(archive_root) / relative_path))

        for filename in optional_root_files:
            candidate = Path(filename)
            if not candidate.is_file():
                continue
            tar.add(candidate, arcname=candidate.name)
            logger.info("ADDED COLLECT ARCHIVE EXTRA %s", candidate)

    if keep_archives > 0:
        archives = sorted(
            [*base.glob("collect-all-*.tar"), *base.glob("collect-all-*.tar.gz")],
            key=lambda p: p.name,
        )
        excess = len(archives) - keep_archives
        if excess > 0:
            for stale in archives[:excess]:
                if stale == archive_path:
                    continue
                stale.unlink(missing_ok=True)
                logger.info("REMOVED OLD COLLECT ARCHIVE %s", stale)

    logger.info("WROTE COLLECT ARCHIVE %s", archive_path)
    return archive_path


def resolve_archive_filter_hostnames(args: argparse.Namespace, logger: Logger) -> Set[str]:
    """
    Resolve effective hostnames used to filter collect-all archive contents.
    """
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)
    target_hosts = parse_host_filter(args.target_hosts)
    selected_hosts, _skipped = select_target_hosts(hosts, policy, logger, target_hosts=target_hosts)
    return {str(host.get("hostname", "")) for host in selected_hosts if str(host.get("hostname", ""))}


def extract_archive_hostname(relative_path: Path) -> str | None:
    """
    Return hostname for known host-scoped collect artifacts.
    """
    parts = relative_path.parts
    if len(parts) < 2:
        return None

    root = parts[0]
    leaf = parts[-1]

    if root == "config":
        marker = "_run."
        if marker in leaf:
            return leaf.split(marker, 1)[0]
        if leaf.endswith("_run.txt"):
            return leaf[:-8]
        return None

    if root == "lldp":
        marker = "_lldp."
        if marker in leaf:
            return leaf.split(marker, 1)[0]
        if leaf.endswith("_lldp.txt"):
            return leaf[:-9]
        return None

    if root == "show_lists":
        if len(parts) >= 3:
            return parts[1]
        if leaf.endswith("_shows.log"):
            return leaf[:-10]
        return None

    return None


def should_include_collect_archive_path(relative_path: Path, allowed_hosts: Set[str] | None) -> bool:
    """
    Decide whether one path should be included in collect-all archive.
    """
    if not allowed_hosts:
        return True

    hostname = extract_archive_hostname(relative_path)
    if hostname is None:
        return True
    return hostname in allowed_hosts


def resolve_work_log_archive_path(
    output_dir: str | Path,
    default_name: str,
    output_tar: str | None,
) -> Path:
    """
    Resolve archive output path. Bare filenames are placed under output_dir.
    """
    if not output_tar:
        return Path(output_dir) / default_name

    candidate = Path(output_tar)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate
    return Path(output_dir) / candidate.name


def create_named_archive(
    output_dir: str | Path,
    default_name: str,
    source_paths: List[Path],
    logger: Logger,
    output_tar: str | None = None,
) -> Path:
    """
    Create an archive from explicit files/directories and prune old same-prefix archives.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    archive_path = resolve_work_log_archive_path(base, default_name, output_tar)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "w:gz") as tar:
        for source_path in source_paths:
            if not source_path.exists():
                logger.warning("SKIP ARCHIVE SOURCE NOT FOUND %s", source_path)
                continue
            if source_path.is_file():
                try:
                    arcname = str(source_path.relative_to(base))
                except ValueError:
                    arcname = source_path.name
                tar.add(source_path, arcname=arcname)
                logger.info("ADDED ARCHIVE FILE %s", source_path)
                continue
            for path in sorted(source_path.rglob("*")):
                if not path.is_file():
                    continue
                if "old" in path.relative_to(source_path).parts:
                    continue
                tar.add(path, arcname=str(Path(source_path.name) / path.relative_to(source_path)))
                logger.info("ADDED ARCHIVE FILE %s", path)

    archive_basename = archive_path.name.removesuffix(".tar.gz").removesuffix(".tar")
    prefix = archive_basename.rsplit("-", 2)[0]
    keep_archives = get_log_rotation_limit()
    if keep_archives > 0:
        archives = sorted(
            [
                *archive_path.parent.glob(f"{prefix}-*.tar"),
                *archive_path.parent.glob(f"{prefix}-*.tar.gz"),
            ],
            key=lambda p: p.name,
        )
        excess = len(archives) - keep_archives
        if excess > 0:
            for stale in archives[:excess]:
                if stale == archive_path:
                    continue
                stale.unlink(missing_ok=True)
                logger.info("REMOVED OLD WORK LOG ARCHIVE %s", stale)

    logger.info("WROTE WORK LOG ARCHIVE %s", archive_path)
    return archive_path


def extract_non_ok_logging_hosts(report_lines: List[str]) -> List[str]:
    """
    Return hosts whose HOST LOGGING CHECK SUMMARY is not OK.
    """
    try:
        start_idx = report_lines.index("### HOST LOGGING CHECK SUMMARY") + 1
    except ValueError:
        return []

    try:
        end_idx = report_lines.index("### HOST RESULT SUMMARY")
    except ValueError:
        end_idx = len(report_lines)

    hosts: List[str] = []
    for line in report_lines[start_idx:end_idx]:
        stripped = line.strip()
        if not stripped or " : " not in stripped:
            continue
        hostname, status = stripped.split(" : ", 1)
        if status.strip() != "OK":
            hosts.append(hostname.strip())
    return hosts


def extract_run_diff_warning_hosts(diff_log_path: Path) -> List[str]:
    """
    Return hosts that have unsaved config diffs in running_config_diff_commands.log.
    """
    if not diff_log_path.exists():
        return []

    lines = diff_log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines:
        if line.strip():
            if line.strip() == "### NO_DIFF":
                return []
            break

    hosts: List[str] = []
    for line in lines:
        if line.startswith("### HOST: "):
            hosts.append(line.split(": ", 1)[1].strip())
    return sorted(set(hosts))


def format_elapsed_last_window(elapsed: timedelta) -> tuple[int, str]:
    """
    Convert elapsed time into the smallest whole-unit --last window that fully covers it.
    """
    total_seconds = max(0.0, elapsed.total_seconds())
    if total_seconds < 3600:
        amount = max(1, math.ceil(total_seconds / 60))
        return amount, "minutes"
    if total_seconds < 86400:
        amount = math.ceil(total_seconds / 3600)
        return amount, "hours"
    amount = math.ceil(total_seconds / 86400)
    return amount, "days"


def parse_archive_timestamp_from_name(path: Path, prefix: str) -> datetime | None:
    """
    Parse <prefix>-YYYYMMDD-HHMMSS.tar(.gz) into local timezone datetime.
    """
    match = re.fullmatch(rf"{re.escape(prefix)}-(\d{{8}})-(\d{{6}})\.tar(?:\.gz)?", path.name)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").astimezone()
    except ValueError:
        return None


def find_latest_before_work_timestamp(output_dir: str | Path, logger: Logger) -> datetime | None:
    """
    Find the most recent collect-before-work completion timestamp from marker or archive names.
    """
    base = Path(output_dir)
    marker_path = base / "work-log" / "collect-before-work-latest.txt"
    if marker_path.exists():
        try:
            marker_text = marker_path.read_text(encoding="utf-8").strip()
            if marker_text:
                return datetime.fromisoformat(marker_text)
        except ValueError:
            logger.warning("FAILED TO PARSE BEFORE-WORK MARKER %s", marker_path)

    candidates = sorted(
        [*base.glob("before-log-*.tar"), *base.glob("before-log-*.tar.gz")],
        key=lambda p: p.name,
    )
    for candidate in reversed(candidates):
        parsed = parse_archive_timestamp_from_name(candidate, "before-log")
        if parsed is not None:
            return parsed
    return None


def save_latest_before_work_timestamp(output_dir: str | Path, completed_at: datetime, logger: Logger) -> Path:
    """
    Persist the latest collect-before-work completion timestamp for collect-after-work defaults.
    """
    marker_dir = Path(output_dir) / "work-log"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "collect-before-work-latest.txt"
    marker_path.write_text(completed_at.isoformat(timespec="seconds"), encoding="utf-8")
    logger.info("SAVED BEFORE-WORK MARKER %s", marker_path)
    return marker_path


def get_lldp_input_dir(raw_dir: str | Path) -> Path:
    """
    Resolve LLDP input directory.

    Prefer <raw_dir>/lldp if it exists, otherwise fallback to <raw_dir>.
    """
    base = Path(raw_dir)
    sub = base / "lldp"
    return sub if sub.exists() else base


def get_run_input_dir(raw_dir: str | Path) -> Path:
    """
    Resolve running-config input directory.

    Prefer <raw_dir>/config if it exists, otherwise fallback to <raw_dir>.
    """
    base = Path(raw_dir)
    sub = base / "config"
    return sub if sub.exists() else base


def build_collect_output_path(
    output_dir: str | Path,
    hostname: str,
    suffix: str,
    output_format: str | None,
) -> Path:
    """
    Build collected output path.

    NX-API JSON results are stored as .json, otherwise .txt.
    """
    ext = ".json" if output_format == "json" else ".txt"
    return Path(output_dir) / f"{hostname}_{suffix}{ext}"


def get_collect_output_variants(output_dir: str | Path, hostname: str, suffix: str) -> List[Path]:
    """
    Return all supported collected file variants for one host/command type.
    """
    base = Path(output_dir)
    return [
        base / f"{hostname}_{suffix}.txt",
        base / f"{hostname}_{suffix}.json",
    ]


def resolve_collect_output_path_for_format(
    output_dir: str | Path,
    hostname: str,
    suffix: str,
    output_format: str | None,
) -> Path | None:
    """
    Resolve an existing collected output path for the requested output format.

    JSON maps to .json, all other formats map to .txt.
    """
    candidate = build_collect_output_path(output_dir, hostname, suffix, output_format)
    return candidate if candidate.exists() else None


def resolve_collect_output_path(output_dir: str | Path, hostname: str, suffix: str) -> Path | None:
    """
    Resolve an existing collected output path, preferring .json over .txt.
    """
    variants = [
        Path(output_dir) / f"{hostname}_{suffix}.json",
        Path(output_dir) / f"{hostname}_{suffix}.txt",
    ]
    for candidate in variants:
        if candidate.exists():
            return candidate
    return None


def list_collect_output_files(output_dir: str | Path, suffix: str) -> List[Path]:
    """
    List collected files for one command type across .txt and .json.

    When both .json and .txt exist for the same host/suffix, prefer .json.
    """
    base = Path(output_dir)
    selected: Dict[str, Path] = {}

    for candidate in sorted(base.glob(f"*_{suffix}.txt"), key=lambda p: p.name):
        hostname = get_collect_hostname_from_path(candidate, suffix)
        selected[hostname] = candidate

    for candidate in sorted(base.glob(f"*_{suffix}.json"), key=lambda p: p.name):
        hostname = get_collect_hostname_from_path(candidate, suffix)
        selected[hostname] = candidate

    return sorted(selected.values(), key=lambda p: p.name)


def get_collect_hostname_from_path(path: Path, suffix: str) -> str:
    """
    Extract hostname from a collected file path.
    """
    for ext in (".json", ".txt"):
        tail = f"_{suffix}{ext}"
        if path.name.endswith(tail):
            return path.name[:-len(tail)]
    return path.stem


def sanitize_command_for_filename(command: str) -> str:
    """
    Convert a CLI command into a filesystem-friendly token.
    """
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", command.strip())
    token = token.strip("._-")
    return token or "command"


def _strip_json_ns(key: str) -> str:
    """
    Strip NX-API JSON namespace prefix such as m8:foo -> foo.
    """
    return key.split(":", 1)[-1]


def _as_list(value: Any) -> List[Any]:
    """
    Normalize singleton/list nodes to a list.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _json_get_child_by_suffix(node: Any, suffix: str) -> Any:
    """
    Return first direct child whose key suffix matches.
    """
    if not isinstance(node, dict):
        return None
    for key, value in node.items():
        if _strip_json_ns(key) == suffix:
            return value
    return None


def _json_collect_xml_values(node: Any) -> List[str]:
    """
    Collect __XML__value strings recursively.
    """
    values: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if _strip_json_ns(key) == "__XML__value":
                values.append(str(value))
                continue
            values.extend(_json_collect_xml_values(value))
    elif isinstance(node, list):
        for item in node:
            values.extend(_json_collect_xml_values(item))
    return values


def _json_collect_param_values(node: Any, param_fragment: str) -> List[str]:
    """
    Collect __XML__value strings under matching parameter keys.
    """
    values: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            stripped = _strip_json_ns(key)
            if param_fragment in stripped:
                values.extend(_json_collect_xml_values(value))
            values.extend(_json_collect_param_values(value, param_fragment))
    elif isinstance(node, list):
        for item in node:
            values.extend(_json_collect_param_values(item, param_fragment))
    return values


def _json_first_param_value(node: Any, param_fragment: str) -> str:
    """
    Return first matched parameter value or empty string.
    """
    values = _json_collect_param_values(node, param_fragment)
    return values[0] if values else ""


def _load_nxapi_json_body(path: Path) -> Any:
    """
    Load collected NX-API JSON body from file.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def render_nxapi_run_json_as_text(data: Any) -> str:
    """
    Render NX-API running-config JSON into a config-like text form
    that existing text parsers can continue to consume.
    """
    terminal = _json_get_child_by_suffix(
        _json_get_child_by_suffix(
            _json_get_child_by_suffix(data, "filter"),
            "configure",
        ),
        "terminal",
    )
    if not isinstance(terminal, dict):
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines: List[str] = []

    for item in _as_list(_json_get_child_by_suffix(terminal, "vlan")):
        vlan_node = _json_get_child_by_suffix(item, "__XML__PARAM__vlan-id-create-delete")
        if not isinstance(vlan_node, dict):
            continue
        vlan_values = _json_collect_xml_values(vlan_node)
        vlan_id = vlan_values[0] if vlan_values else ""
        vlan_name = _json_first_param_value(vlan_node, "vlan-name")
        segment_id = _json_first_param_value(vlan_node, "segment-id")
        if not vlan_id or (not vlan_name and not segment_id):
            continue
        lines.append(f"vlan {vlan_id}")
        if vlan_name:
            lines.append(f"  name {vlan_name}")
        if segment_id:
            lines.append(f"  vn-segment {segment_id}")

    for item in _as_list(_json_get_child_by_suffix(terminal, "vrf")):
        context = _json_get_child_by_suffix(item, "context")
        context_node = _json_get_child_by_suffix(context, "__XML__PARAM__vrf-name-known-name")
        if not isinstance(context_node, dict):
            continue
        vrf_values = _json_collect_xml_values(context_node)
        vrf_name = vrf_values[0] if vrf_values else ""
        vni_id = _json_first_param_value(_json_get_child_by_suffix(context_node, "vni"), "id")
        if not vrf_name:
            continue
        lines.append(f"vrf context {vrf_name}")
        if vni_id:
            lines.append(f"  vni {vni_id}")

    for item in _as_list(_json_get_child_by_suffix(terminal, "interface")):
        intf_node = _json_get_child_by_suffix(item, "__XML__PARAM__interface")
        if not isinstance(intf_node, dict):
            continue
        intf_values = _json_collect_xml_values(intf_node)
        if_name = intf_values[0] if intf_values else ""
        if not if_name:
            continue
        lines.append(f"interface {if_name}")

        description = _json_first_param_value(intf_node, "desc_line")
        if description:
            lines.append(f"  description {description}")

        vrf_name = _json_first_param_value(intf_node, "vrf-name")
        if vrf_name:
            lines.append(f"  vrf member {vrf_name}")

        ipv4_values = _json_collect_param_values(intf_node, "ip-prefix")
        for idx, value in enumerate(ipv4_values):
            line = f"  ip address {value}"
            if idx > 0:
                line += " secondary"
            lines.append(line)

        for value in _json_collect_param_values(intf_node, "ipv6-prefix"):
            lines.append(f"  ipv6 address {value}")

    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def load_run_text_from_collect_file(path: Path) -> str:
    """
    Load running-config input text from .txt or .json collected file.
    """
    if path.suffix.lower() == ".json":
        return render_nxapi_run_json_as_text(_load_nxapi_json_body(path))
    return path.read_text(encoding="utf-8", errors="ignore")


def load_lldp_records_from_collect_file(
    path: Path,
    local_hostname: str,
    device_type: str,
    mappings: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Load LLDP records from .txt or .json collected file.
    """
    if path.suffix.lower() != ".json":
        text = path.read_text(encoding="utf-8", errors="ignore")
        return parse_lldp_file(text, local_hostname, device_type, mappings)

    data = _load_nxapi_json_body(path)
    if device_type != "nxos":
        return []

    rows = _json_get_child_by_suffix(_json_get_child_by_suffix(data, "TABLE_nbor_detail"), "ROW_nbor_detail")
    records: List[Dict[str, str]] = []
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        remote_hostname = str(row.get("sys_name", "")).strip()
        local_if = str(row.get("l_port_id", "")).strip()
        remote_if = str(row.get("port_id", "")).strip()
        mgmt_addr = str(row.get("mgmt_addr", "")).strip()
        if not remote_hostname or not local_if or not remote_if:
            continue
        if is_excluded_interface(local_if, mappings) or is_excluded_interface(remote_if, mappings):
            continue
        records.append({
            "src_node": normalize_hostname(local_hostname, mappings),
            "src_if": normalize_interface_name(local_if, mappings),
            "dst_node": normalize_hostname(remote_hostname, mappings),
            "dst_if": normalize_interface_name(remote_if, mappings),
            "protocol": "lldp",
            "confidence": "",
            "evidence": "",
            "remote_mgmt_ip": mgmt_addr,
            "rule_name": "",
        })
    return records


def build_clab_topology_data(
    rendered_links: List[Dict[str, Any]],
    nodes: Dict[str, Dict[str, Any]],
    include_nodes: bool,
) -> Dict[str, Any]:
    """
    Build containerlab topology dictionary.

    Args:
        rendered_links: Rendered links.
        nodes: topology.nodes definitions.
        include_nodes: Whether to include nodes.

    Returns:
        Topology dictionary.
    """
    topology: Dict[str, Any] = {
        "links": [{"endpoints": link["endpoints"]} for link in rendered_links],
    }
    if include_nodes:
        topology["nodes"] = nodes
    return {"topology": topology}


def deep_merge_dicts(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep-merge dictionaries.

    Behavior:
    - If both values are dicts, merge recursively.
    - Otherwise, overlay value replaces base value.

    Args:
        base: Base dictionary.
        overlay: Overlay dictionary.

    Returns:
        Merged dictionary.
    """
    for key, value in overlay.items():
        base_value = base.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            deep_merge_dicts(base_value, value)
        else:
            base[key] = value
    return base


def apply_clab_merge_file(
    topology_data: Dict[str, Any],
    merge_path: str | None,
    logger: Logger,
    label: str,
) -> Dict[str, Any]:
    """
    Apply merge YAML into containerlab topology data.

    Args:
        topology_data: Generated topology data.
        merge_path: Optional merge YAML path.
        logger: Logger.
        label: Log label for source kind.

    Returns:
        Merged topology data.
    """
    if not merge_path:
        return topology_data

    merge_data = load_yaml(merge_path)
    deep_merge_dicts(topology_data, merge_data)
    logger.info("Merged %s file: %s", label, merge_path)
    return topology_data


def finalize_clab_topology_data(
    topology_data: Dict[str, Any],
    generated_links: List[Dict[str, Any]],
    generated_node_names: Set[str],
    roles: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Finalize merged topology data.

    - Append topology.links from merge files to generated links (generated first).
    - Deduplicate identical link objects while preserving order.
    - Reorder top-level keys to: name, mgmt, topology.
    - Reorder topology keys to start with: kinds, defaults, nodes, links.

    Args:
        topology_data: Merged topology data.
        generated_links: Generated links list.
        generated_node_names: Hostnames generated from link records (non-merge nodes).
        roles: Role rules.

    Returns:
        Finalized topology data.
    """
    topology = topology_data.setdefault("topology", {})
    merged_links = topology.get("links", [])
    combined_links: List[Dict[str, Any]] = []
    seen = set()

    def split_endpoint(ep: str) -> tuple[str, str]:
        if ":" in ep:
            node, iface = ep.split(":", 1)
            return node, iface
        return ep, ""

    def natural_key(text: str) -> tuple[Any, ...]:
        parts = re.split(r"(\d+)", text)
        out: List[Any] = []
        for p in parts:
            if p.isdigit():
                out.append(int(p))
            else:
                out.append(p.lower())
        return tuple(out)

    nodes_map_for_role = topology.get("nodes", {})

    def resolve_node_role(node_name: str) -> str:
        if isinstance(nodes_map_for_role, dict):
            attrs = nodes_map_for_role.get(node_name)
            if isinstance(attrs, dict):
                group = attrs.get("group")
                if isinstance(group, str) and group.strip():
                    return group.strip()
        return detect_node_role(node_name, roles)

    def link_sort_key(link: Dict[str, Any]) -> tuple[Any, ...]:
        endpoints = link.get("endpoints", [])
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            return (9999, (), 9999, (), (), ())
        left_node, left_if = split_endpoint(str(endpoints[0]))
        right_node, right_if = split_endpoint(str(endpoints[1]))
        left_role = resolve_node_role(left_node)
        right_role = resolve_node_role(right_node)
        return (
            get_role_priority(left_role, roles),
            natural_key(left_role),
            natural_key(left_node),
            natural_key(left_if),
            get_role_priority(right_role, roles),
            natural_key(right_role),
            natural_key(right_node),
            natural_key(right_if),
        )

    for link in generated_links + (merged_links if isinstance(merged_links, list) else []):
        if not isinstance(link, dict):
            continue
        try:
            key = json.dumps(link, sort_keys=True, ensure_ascii=False)
        except TypeError:
            key = str(link)
        if key in seen:
            continue
        seen.add(key)
        combined_links.append(link)

    topology["links"] = sorted(combined_links, key=link_sort_key)
    nodes_map = topology.get("nodes", {})
    if isinstance(nodes_map, dict):
        generated_entries: List[tuple[str, Dict[str, Any], str, int]] = []
        lab_entries: List[tuple[str, Dict[str, Any]]] = []

        for node_name, attrs in nodes_map.items():
            if node_name in generated_node_names:
                role = str(attrs.get("group") or detect_node_role(node_name, roles))
                priority = get_role_priority(role, roles)
                generated_entries.append((node_name, attrs, role, priority))
            else:
                lab_entries.append((node_name, attrs))

        generated_name_set = {name for name, _attrs in nodes_map.items() if name in generated_node_names}

        def generated_node_sort_key(entry: tuple[str, Dict[str, Any], str, int]) -> tuple[Any, ...]:
            node_name, _attrs, role, priority = entry
            cluster_base = node_name
            cluster_member_order = 2
            member_name = node_name

            if "-" in node_name:
                prefix, suffix = node_name.split("-", 1)
                if prefix in generated_name_set:
                    cluster_base = prefix
                    cluster_member_order = 1
                    member_name = suffix
            else:
                has_children = any(
                    candidate.startswith(f"{node_name}-") for candidate in generated_name_set
                )
                if has_children:
                    cluster_base = node_name
                    cluster_member_order = 0

            return (
                priority,
                role,
                natural_key(cluster_base),
                cluster_member_order,
                natural_key(member_name),
            )

        generated_entries.sort(key=generated_node_sort_key)

        ordered_nodes: Dict[str, Any] = {}
        for node_name, attrs, _, _ in generated_entries:
            ordered_nodes[node_name] = attrs
        for node_name, attrs in lab_entries:
            ordered_nodes[node_name] = attrs
        topology["nodes"] = ordered_nodes

    ordered_topology: Dict[str, Any] = {}
    for key in ("kinds", "defaults", "nodes", "links"):
        if key in topology:
            ordered_topology[key] = topology[key]
    for key, value in topology.items():
        if key not in ordered_topology:
            ordered_topology[key] = value

    ordered: Dict[str, Any] = {}
    for key in ("name", "mgmt"):
        if key in topology_data:
            ordered[key] = topology_data[key]
    ordered["topology"] = ordered_topology

    for key, value in topology_data.items():
        if key not in ordered:
            ordered[key] = value

    return ordered


def apply_linux_csv_overlay(
    topology_data: Dict[str, Any],
    linux_csv_path: str | None,
    logger: Logger,
) -> Set[str]:
    """
    Append linux nodes/links from CSV into topology data.

    CSV headers:
    hostname,VLAN_ID,IP_CIDR,DEF_GW,IPV6_CIDR,DEF_GW6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
    """
    if not linux_csv_path:
        return set()

    csv_path = Path(linux_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"linux csv not found: {linux_csv_path}")

    topology = topology_data.setdefault("topology", {})
    kinds = topology.setdefault("kinds", {})
    nodes = topology.setdefault("nodes", {})
    links = topology.setdefault("links", [])

    linux_kind = kinds.setdefault("linux", {})
    if "image" not in linux_kind:
        linux_kind["image"] = DEFAULT_LINUX_KIND_IMAGE

    required = [
        "hostname", "VLAN_ID", "IP_CIDR", "DEF_GW", "IPV6_CIDR", "DEF_GW6",
        "LEAF1", "LEAF1_IF", "LEAF2", "LEAF2_IF",
    ]

    added_nodes: Set[str] = set()
    added_links = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"linux csv has no header: {linux_csv_path}")
        missing_headers = [h for h in required if h not in reader.fieldnames]
        if missing_headers:
            raise ValueError(f"linux csv missing headers: {', '.join(missing_headers)}")

        for row in reader:
            hostname = str(row.get("hostname", "")).strip()
            if not hostname:
                continue

            nodes[hostname] = {
                "kind": "linux",
                "env": {
                    "VLAN_ID": str(row.get("VLAN_ID", "")).strip(),
                    "IP_CIDR": str(row.get("IP_CIDR", "")).strip(),
                    "DEF_GW": str(row.get("DEF_GW", "")).strip(),
                    "IPV6_CIDR": str(row.get("IPV6_CIDR", "")).strip(),
                    "DEF_GW6": str(row.get("DEF_GW6", "")).strip(),
                },
                "binds": [DEFAULT_LINUX_NODE_BIND],
                "exec": [DEFAULT_LINUX_NODE_EXEC],
                "group": "server",
            }
            added_nodes.add(hostname)

            leaf1 = str(row.get("LEAF1", "")).strip()
            leaf1_if = str(row.get("LEAF1_IF", "")).strip()
            leaf2 = str(row.get("LEAF2", "")).strip()
            leaf2_if = str(row.get("LEAF2_IF", "")).strip()
            if leaf1 and leaf1_if:
                links.append({"endpoints": [f"{leaf1}:{leaf1_if}", f"{hostname}:eth1"]})
                added_links += 1
            if leaf2 and leaf2_if:
                links.append({"endpoints": [f"{leaf2}:{leaf2_if}", f"{hostname}:eth2"]})
                added_links += 1

    logger.info(
        "Merged linux csv %s: nodes=%d links=%d",
        linux_csv_path,
        len(added_nodes),
        added_links,
    )
    return added_nodes


def apply_kind_cluster_csv_overlay(
    topology_data: Dict[str, Any],
    kind_cluster_csv_path: str | None,
    logger: Logger,
) -> Set[str]:
    """
    Append kind cluster nodes/links from CSV into topology data.

    CSV headers:
    cluster,hostname,VLAN_ID,IP_CIDR,DEF_GW,ROUTES4,IPV6_CIDR,DEF_GW6,ROUTES6,LEAF1,LEAF1_IF,LEAF2,LEAF2_IF
    """
    if not kind_cluster_csv_path:
        return set()

    csv_path = Path(kind_cluster_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"kind cluster csv not found: {kind_cluster_csv_path}")

    topology = topology_data.setdefault("topology", {})
    kinds = topology.setdefault("kinds", {})
    nodes = topology.setdefault("nodes", {})
    links = topology.setdefault("links", [])

    kind_kind = kinds.setdefault(DEFAULT_KIND_CLUSTER_KIND, {})
    if "image" not in kind_kind:
        kind_kind["image"] = DEFAULT_KIND_CLUSTER_IMAGE

    required = [
        "cluster", "hostname", "VLAN_ID", "IP_CIDR", "DEF_GW", "ROUTES4",
        "IPV6_CIDR", "DEF_GW6", "ROUTES6", "LEAF1", "LEAF1_IF", "LEAF2", "LEAF2_IF",
    ]

    added_nodes: Set[str] = set()
    added_links = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"kind cluster csv has no header: {kind_cluster_csv_path}")
        missing_headers = [h for h in required if h not in reader.fieldnames]
        if missing_headers:
            raise ValueError(f"kind cluster csv missing headers: {', '.join(missing_headers)}")

        for row in reader:
            cluster = str(row.get("cluster", "")).strip()
            host_part = str(row.get("hostname", "")).strip()
            if not cluster or not host_part:
                continue

            cluster_node = cluster
            if cluster_node not in nodes:
                nodes[cluster_node] = {
                    "kind": DEFAULT_KIND_CLUSTER_KIND,
                    "startup-config": DEFAULT_KIND_CLUSTER_STARTUP_CONFIG_TEMPLATE.format(cluster=cluster),
                    "group": "kind-cluster",
                    "extras": {
                        "k8s_kind": {
                            "deploy": {
                                "kubeconfig": f"k8s_kind/{cluster}/kubeconfig-{cluster}",
                                "wait": "0s",
                            }
                        }
                    },
                }
                added_nodes.add(cluster_node)

            node_name = f"{cluster}-{host_part}"
            vlan_id = str(row.get("VLAN_ID", "")).strip()
            ip_cidr = str(row.get("IP_CIDR", "")).strip()
            def_gw = str(row.get("DEF_GW", "")).strip()
            routes4 = str(row.get("ROUTES4", "")).strip()
            ipv6_cidr = str(row.get("IPV6_CIDR", "")).strip()
            def_gw6 = str(row.get("DEF_GW6", "")).strip()
            routes6 = str(row.get("ROUTES6", "")).strip()

            script_lines = [
                "sh -lc '",
                f'  export VLAN_ID="{vlan_id}";',
                f'  export IP_CIDR="{ip_cidr}";',
                f'  export DEF_GW="{def_gw}";',
                f'  export IPV6_CIDR="{ipv6_cidr}";',
                f'  export DEF_GW6="{def_gw6}";',
                '  export MTU="9000";',
                '  export SET_DEFAULT_ROUTE="false";',
                "",
                f'  export ROUTES4="{routes4} via {def_gw}";',
                f'  export ROUTES6="{routes6} via {def_gw6}";',
                "",
                "  ls -l /scripts || true;",
                f"  {DEFAULT_KIND_NODE_INIT_SCRIPT}",
                "'",
            ]

            nodes[node_name] = {
                "kind": "ext-container",
                "binds": [DEFAULT_KIND_NODE_BIND],
                "exec": ["\n".join(script_lines)],
                "group": "kind-cluster",
            }
            added_nodes.add(node_name)

            leaf1 = str(row.get("LEAF1", "")).strip()
            leaf1_if = str(row.get("LEAF1_IF", "")).strip()
            leaf2 = str(row.get("LEAF2", "")).strip()
            leaf2_if = str(row.get("LEAF2_IF", "")).strip()
            if leaf1 and leaf1_if:
                links.append({"endpoints": [f"{leaf1}:{leaf1_if}", f"{node_name}:eth1"]})
                added_links += 1
            if leaf2 and leaf2_if:
                links.append({"endpoints": [f"{leaf2}:{leaf2_if}", f"{node_name}:eth2"]})
                added_links += 1

    logger.info(
        "Merged kind-cluster csv %s: nodes=%d links=%d",
        kind_cluster_csv_path,
        len(added_nodes),
        added_links,
    )
    return added_nodes


def _kind_member_role(host_part: str) -> str:
    host = host_part.strip().lower()
    if host == "control-plane" or host.startswith("control-plane-"):
        return "control-plane"
    return "worker"


def generate_kind_cluster_config_files(
    kind_cluster_csv_path: str | None,
    logger: Logger,
    base_dir: Path | None = None,
) -> List[Path]:
    """
    Generate kind cluster startup-config files from kind-cluster CSV.

    Output:
      .alred/<cluster>/<cluster>.kind.yaml
    """
    if not kind_cluster_csv_path:
        return []

    class _KindYamlDumper(yaml.SafeDumper):
        def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
            return super().increase_indent(flow, False)

    csv_path = Path(kind_cluster_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"kind cluster csv not found: {kind_cluster_csv_path}")

    root = Path.cwd() if base_dir is None else base_dir
    output_root = root / DEFAULT_KIND_CLUSTER_CONFIG_BASE_DIR
    linux_host_path = str((output_root / DEFAULT_KIND_CLUSTER_CONFIG_MOUNT_SUBDIR).resolve())
    (output_root / DEFAULT_KIND_CLUSTER_CONFIG_MOUNT_SUBDIR).mkdir(parents=True, exist_ok=True)

    cluster_roles: Dict[str, List[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"kind cluster csv has no header: {kind_cluster_csv_path}")
        for row in reader:
            cluster = str(row.get("cluster", "")).strip()
            host_part = str(row.get("hostname", "")).strip()
            if not cluster or not host_part:
                continue
            roles = cluster_roles.setdefault(cluster, [])
            roles.append(_kind_member_role(host_part))

    written_paths: List[Path] = []
    for cluster, roles in cluster_roles.items():
        cluster_dir = output_root / cluster
        cluster_dir.mkdir(parents=True, exist_ok=True)
        out_path = cluster_dir / DEFAULT_KIND_CLUSTER_CONFIG_FILENAME_TEMPLATE.format(cluster=cluster)

        data: Dict[str, Any] = {
            "kind": "Cluster",
            "apiVersion": "kind.x-k8s.io/v1alpha4",
            "networking": {"ipFamily": "dual"},
            "nodes": [],
        }
        nodes_data: List[Dict[str, Any]] = data["nodes"]
        for role in roles:
            nodes_data.append(
                {
                    "role": role,
                    "extraMounts": [
                        {
                            "hostPath": linux_host_path,
                            "containerPath": DEFAULT_KIND_CLUSTER_CONFIG_CONTAINER_MOUNT_PATH,
                            "readOnly": True,
                        }
                    ],
                }
            )

        yaml_text = yaml.dump(
            data,
            Dumper=_KindYamlDumper,
            sort_keys=False,
            allow_unicode=True,
            width=4096,
        )
        write_text(str(out_path), yaml_text.splitlines())
        written_paths.append(out_path)

    if written_paths:
        logger.info(
            "Generated kind cluster startup-config files: %s",
            ", ".join(str(p) for p in written_paths),
        )
    return written_paths


def generate_kind_cluster_support_script(
    trigger_path: str | None,
    logger: Logger,
    base_dir: Path | None = None,
) -> Optional[Path]:
    """
    Generate support script for kind-cluster nodes:
      .alred/linux/init-bond-singlevlan-route.sh
    """
    if not trigger_path:
        return None

    root = Path.cwd() if base_dir is None else base_dir
    script_dir = root / DEFAULT_KIND_CLUSTER_CONFIG_BASE_DIR / DEFAULT_KIND_CLUSTER_CONFIG_MOUNT_SUBDIR
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / DEFAULT_KIND_CLUSTER_NODE_SCRIPT_FILENAME
    script_path.write_text(DEFAULT_KIND_CLUSTER_NODE_SCRIPT_CONTENT.rstrip("\n") + "\n", encoding="utf-8")
    try:
        script_path.chmod(0o755)
    except OSError:
        # Non-fatal on environments without chmod support
        pass
    logger.info("Generated kind cluster support script: %s", script_path)
    return script_path


def apply_cisco_n9kv_kind_defaults(
    topology_data: Dict[str, Any],
    raw_dir: str,
    logger: Logger,
) -> Dict[str, Any]:
    """
    If any topology.nodes entry has kind=cisco_n9kv, apply default kind values.
    """
    topology = topology_data.get("topology", {})
    if not isinstance(topology, dict):
        return topology_data

    nodes = topology.get("nodes", {})
    if not isinstance(nodes, dict):
        return topology_data

    has_n9kv_node = any(
        isinstance(attrs, dict) and str(attrs.get("kind", "")).strip() == DEFAULT_CISCO_N9KV_KIND_NAME
        for attrs in nodes.values()
    )
    if not has_n9kv_node:
        return topology_data

    kinds = topology.setdefault("kinds", {})
    if not isinstance(kinds, dict):
        return topology_data
    n9kv = kinds.setdefault(DEFAULT_CISCO_N9KV_KIND_NAME, {})
    if not isinstance(n9kv, dict):
        return topology_data

    n9kv.setdefault("image", DEFAULT_CISCO_N9KV_KIND_IMAGE)
    n9kv.setdefault(
        "startup-config",
        DEFAULT_CISCO_N9KV_STARTUP_CONFIG_TEMPLATE.format(raw_dir=raw_dir),
    )
    env = n9kv.get("env")
    if not isinstance(env, dict):
        env = {}
        n9kv["env"] = env
    for k, v in DEFAULT_CISCO_N9KV_KIND_ENV.items():
        env.setdefault(k, v)

    logger.info(
        "Applied defaults for kind %s from nodes condition (raw_dir=%s)",
        DEFAULT_CISCO_N9KV_KIND_NAME,
        raw_dir,
    )
    return topology_data


class FlowStyleList(list):
    """YAML dumper hint for flow-style sequence."""


class DoubleQuotedString(str):
    """YAML dumper hint for double-quoted scalar."""


class ClabYamlDumper(yaml.SafeDumper):
    """Custom YAML dumper for clab topology output."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        # Force list indentation under mapping keys (e.g., topology.links).
        return super().increase_indent(flow, False)


def _represent_flow_style_list(dumper: yaml.Dumper, data: FlowStyleList) -> yaml.nodes.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


ClabYamlDumper.add_representer(FlowStyleList, _represent_flow_style_list)


def _represent_double_quoted_str(dumper: yaml.Dumper, data: DoubleQuotedString) -> yaml.nodes.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


ClabYamlDumper.add_representer(DoubleQuotedString, _represent_double_quoted_str)


def apply_clab_yaml_style(data: Any, parent_key: str = "") -> Any:
    """
    Apply clab-specific YAML style hints.

    - topology.links[*].endpoints is rendered as inline flow sequence.
    """
    if isinstance(data, dict):
        return {k: apply_clab_yaml_style(v, k) for k, v in data.items()}
    if isinstance(data, list):
        styled: List[Any] = []
        for v in data:
            x = apply_clab_yaml_style(v, parent_key)
            if parent_key == "endpoints" and isinstance(x, str):
                x = DoubleQuotedString(x)
            styled.append(x)
        if parent_key == "endpoints":
            return FlowStyleList(styled)
        return styled
    return data


def render_clab_yaml_lines(
    topology_data: Dict[str, Any],
    generated_node_names: Set[str],
    roles: Dict[str, Any],
) -> List[str]:
    """
    Render topology data to YAML lines with clab-specific formatting.
    """
    styled = apply_clab_yaml_style(topology_data)
    dumped = yaml.dump(
        styled,
        Dumper=ClabYamlDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    )
    lines = dumped.rstrip("\n").splitlines()
    lines = add_top_level_spacing(lines)
    lines = add_node_group_comments(lines, topology_data, generated_node_names, roles)
    lines = add_link_left_node_comments(lines)
    return lines


def add_top_level_spacing(lines: List[str]) -> List[str]:
    """
    Add a blank line between top-level mapping keys for readability.
    """
    output: List[str] = []
    seen_top_level = False

    for line in lines:
        if line and not line.startswith(" "):
            if seen_top_level and (not output or output[-1] != ""):
                output.append("")
            seen_top_level = True
        output.append(line)

    return output


def add_node_group_comments(
    lines: List[str],
    topology_data: Dict[str, Any],
    generated_node_names: Set[str],
    roles: Dict[str, Any],
) -> List[str]:
    """
    Add comments in topology.nodes.

    - Generated nodes: grouped with `# <role>`
    - Merge/lab nodes: grouped under a single `# lab-nodes`
    """
    node_comment_by_name: Dict[str, str] = {}
    nodes_map = topology_data.get("topology", {}).get("nodes", {})
    if isinstance(nodes_map, dict):
        last_role: Optional[str] = None
        lab_header_added = False
        for node_name, attrs in nodes_map.items():
            if node_name in generated_node_names:
                role = str(attrs.get("group") or detect_node_role(node_name, roles))
                if role != last_role:
                    node_comment_by_name[node_name] = role
                    last_role = role
            else:
                if not lab_header_added:
                    node_comment_by_name[node_name] = "lab-nodes"
                    lab_header_added = True

    output: List[str] = []
    in_nodes = False
    node_key_re = re.compile(r"^\s{4}([^:\s][^:]*):\s*$")

    for line in lines:
        stripped = line.strip()

        if stripped == "nodes:":
            in_nodes = True
            output.append(line)
            continue

        if in_nodes:
            if not line.startswith("    "):
                in_nodes = False
            else:
                m = node_key_re.match(line)
                if m:
                    node_name = m.group(1)
                    comment = node_comment_by_name.get(node_name)
                    if comment:
                        output.append(f"    # {comment}")
                output.append(line)
                continue

        output.append(line)

    return output


def add_link_left_node_comments(lines: List[str]) -> List[str]:
    """
    Add left-node comments inside topology.links block.

    Example:
      links:
        # spsw0101
        - endpoints: ["spsw0101:Eth1/1", "lfsw0101:Eth1/8"]
    """
    output: List[str] = []
    in_links = False
    current_left_node: Optional[str] = None
    endpoint_re = re.compile(r'^\s*-\s+endpoints:\s+\["([^"]+)",\s+"([^"]+)"\]\s*$')

    for line in lines:
        stripped = line.strip()

        if stripped == "links:":
            in_links = True
            current_left_node = None
            output.append(line)
            continue

        if in_links:
            if not line.startswith("    "):
                in_links = False
            else:
                m = endpoint_re.match(stripped)
                if m:
                    left_endpoint = m.group(1)
                    left_node = left_endpoint.split(":", 1)[0]
                    if left_node != current_left_node:
                        output.append(f"    # {left_node}")
                        current_left_node = left_node
                output.append(line)
                continue

        output.append(line)

    return output


def load_underlay_render_config(path: str | None) -> Dict[str, Any]:
    """
    Load underlay rendering config.

    Supported keys:
    - target_roles: list[str]
    - vrf: str (default means no explicit vrf member in interface block)
    - interface: str (default: loopback0)
    - label: str (default: lo0)
    - interfaces: list of {name, label, vrf} (preferred for multi-loopback)
    """
    defaults: Dict[str, Any] = {
        "target_roles": ["super-spine", "spine", "leaf", "border-gateway"],
        "vrf": "default",
        "interface": "loopback0",
        "label": "lo0",
        "interfaces": [
            {"name": "loopback0", "label": "lo0", "vrf": "default"},
        ],
    }
    if not path:
        return defaults
    loaded = load_yaml(path)
    out = defaults.copy()
    for key in ("target_roles", "vrf", "interface", "label", "interfaces"):
        if key in loaded and loaded.get(key) is not None:
            out[key] = loaded.get(key)
    # Backward compatibility: if interfaces not explicitly provided, synthesize from interface/label/vrf.
    if "interfaces" not in loaded:
        out["interfaces"] = [
            {
                "name": str(out.get("interface", "loopback0")),
                "label": str(out.get("label", "lo0")),
                "vrf": str(out.get("vrf", "default")),
            }
        ]
    return out


def parse_underlay_loopback_ips_from_run(text: str, interface_name: str, vrf: str) -> tuple[str, List[str]]:
    """
    Parse one run-config text and return loopback primary/secondary IPv4 for underlay display.
    """
    lines = text.splitlines()
    in_target = False
    current_vrf = "default"
    ip_value = ""
    secondary_ips: List[str] = []

    def vrf_matches(v: str) -> bool:
        want = (vrf or "default").strip()
        have = (v or "default").strip()
        return want == have

    for line in lines:
        m_intf = re.match(r"^interface\s+(\S+)\s*$", line)
        if m_intf:
            if in_target and vrf_matches(current_vrf) and (ip_value or secondary_ips):
                return ip_value, secondary_ips
            in_target = m_intf.group(1).lower() == interface_name.lower()
            current_vrf = "default"
            ip_value = ""
            secondary_ips = []
            continue

        if not in_target:
            continue

        if line and not line.startswith(" "):
            if vrf_matches(current_vrf) and (ip_value or secondary_ips):
                return ip_value, secondary_ips
            in_target = False
            current_vrf = "default"
            ip_value = ""
            secondary_ips = []
            continue

        m_vrf = re.match(r"^\s+vrf member\s+(\S+)\s*$", line)
        if m_vrf:
            current_vrf = m_vrf.group(1)
            continue

        m_ip = re.match(r"^\s+ip address\s+(\S+)(?:\s+secondary)?\s*$", line)
        if m_ip:
            addr = m_ip.group(1)
            if "secondary" in line:
                secondary_ips.append(addr)
            elif not ip_value:
                ip_value = addr

    if in_target and vrf_matches(current_vrf) and (ip_value or secondary_ips):
        return ip_value, secondary_ips
    return "", []


def build_underlay_loopback_maps(
    raw_dir: str,
    mappings: Dict[str, Any],
    interface_name: str,
    vrf: str,
) -> tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Build normalized node -> underlay loopback IPv4 map from collected running-config files.
    """
    underlay_map: Dict[str, str] = {}
    underlay_secondary_map: Dict[str, List[str]] = {}
    run_files = list_collect_output_files(get_run_input_dir(raw_dir), "run")
    for f in run_files:
        hostname = get_collect_hostname_from_path(f, "run")
        text = load_run_text_from_collect_file(f)
        ip_value, secondary_ips = parse_underlay_loopback_ips_from_run(
            text,
            interface_name=interface_name,
            vrf=vrf,
        )
        if not ip_value and not secondary_ips:
            continue
        normalized = normalize_hostname(hostname, mappings)
        if ip_value:
            underlay_map[hostname] = ip_value
            underlay_map[normalized] = ip_value
        if secondary_ips:
            underlay_secondary_map[hostname] = secondary_ips
            underlay_secondary_map[normalized] = secondary_ips
    return underlay_map, underlay_secondary_map


def build_underlay_interface_ip_maps(
    raw_dir: str,
    mappings: Dict[str, Any],
    vrf: str,
) -> Dict[str, Dict[str, str]]:
    """
    Build normalized node -> normalized interface -> IPv4(without prefix) map from collected running-config files.
    """
    node_if_ip: Dict[str, Dict[str, str]] = {}
    run_files = list_collect_output_files(get_run_input_dir(raw_dir), "run")

    for f in run_files:
        hostname = get_collect_hostname_from_path(f, "run")
        text = load_run_text_from_collect_file(f)
        lines = text.splitlines()

        in_intf = False
        intf_name = ""
        intf_vrf = "default"
        intf_ip = ""

        def flush_interface() -> None:
            nonlocal intf_name, intf_vrf, intf_ip
            if not intf_name or not intf_ip:
                return
            want_vrf = (vrf or "default").strip()
            have_vrf = (intf_vrf or "default").strip()
            if want_vrf != have_vrf:
                return
            normalized_node = normalize_hostname(hostname, mappings)
            normalized_if = normalize_interface_name(intf_name, mappings)
            pure_ip = intf_ip.split("/", 1)[0]
            node_if_ip.setdefault(hostname, {})[normalized_if] = pure_ip
            node_if_ip.setdefault(normalized_node, {})[normalized_if] = pure_ip

        for line in lines:
            m_intf = re.match(r"^interface\s+(\S+)\s*$", line)
            if m_intf:
                if in_intf:
                    flush_interface()
                in_intf = True
                intf_name = m_intf.group(1)
                intf_vrf = "default"
                intf_ip = ""
                continue

            if not in_intf:
                continue

            if line and not line.startswith(" "):
                flush_interface()
                in_intf = False
                intf_name = ""
                intf_vrf = "default"
                intf_ip = ""
                continue

            m_vrf = re.match(r"^\s+vrf member\s+(\S+)\s*$", line)
            if m_vrf:
                intf_vrf = m_vrf.group(1)
                continue

            m_ip = re.match(r"^\s+ip address\s+(\S+)(?:\s+secondary)?\s*$", line)
            if m_ip and "secondary" not in line and not intf_ip:
                intf_ip = m_ip.group(1)

        if in_intf:
            flush_interface()

    return node_if_ip


def build_underlay_link_label_map(
    rendered_links: List[Dict[str, Any]],
    node_if_ip_map: Dict[str, Dict[str, str]],
) -> Dict[str, str]:
    """
    Build mermaid link label override map: \"leftNode|leftIf|rightNode|rightIf\" -> \"a ↔ b\".
    """
    out: Dict[str, str] = {}
    for link in rendered_links:
        ep1, ep2 = link["endpoints"]
        left_node, left_if = ep1.split(":", 1)
        right_node, right_if = ep2.split(":", 1)
        left_ip = node_if_ip_map.get(left_node, {}).get(left_if, "")
        right_ip = node_if_ip_map.get(right_node, {}).get(right_if, "")
        if left_ip and right_ip:
            key = f"{left_node}|{left_if}|{right_node}|{right_if}"
            out[key] = f"{left_ip} ↔ {right_ip}"
    return out


def filter_links_by_target_roles(
    links: List[Dict[str, Any]],
    roles: Dict[str, Any],
    target_roles: Set[str],
) -> List[Dict[str, Any]]:
    """
    Keep only links where both endpoints belong to target roles.
    """
    out: List[Dict[str, Any]] = []
    for link in links:
        ep1, ep2 = link.get("endpoints", ["", ""])
        n1 = ep1.split(":", 1)[0]
        n2 = ep2.split(":", 1)[0]
        matched_r1 = set(detect_node_roles(n1, roles))
        matched_r2 = set(detect_node_roles(n2, roles))
        if matched_r1.intersection(target_roles) and matched_r2.intersection(target_roles):
            out.append(link)
    return out


def add_underlay_suffix_to_path(path: str) -> str:
    """
    Add '_underlay' before file extension if not already present.
    """
    p = Path(path)
    suffix = p.suffix
    stem = p.stem
    if stem.endswith("_underlay"):
        return str(p)
    if suffix:
        return str(p.with_name(f"{stem}_underlay{suffix}"))
    return str(p.with_name(f"{stem}_underlay"))


def build_mermaid_address_maps(
    normalized_inventory_map: Dict[str, Dict[str, Any]],
    normalized_mgmt_ip_map: Dict[str, str],
    roles: Dict[str, Any],
    underlay_config: Dict[str, Any],
    underlay_ip_maps: Dict[str, Dict[str, str]],
    underlay_secondary_ip_maps: Optional[Dict[str, Dict[str, List[str]]]] = None,
) -> tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]:
    """
    Build node address map/label map/lines map for Mermaid rendering.
    """
    address_map = dict(normalized_mgmt_ip_map)
    label_map: Dict[str, str] = {}
    lines_map: Dict[str, List[str]] = {}
    target_roles = set(underlay_config.get("target_roles", []))
    interface_specs = underlay_config.get("interfaces", [])

    for node in normalized_inventory_map.keys():
        matched_roles = set(detect_node_roles(node, roles))
        if matched_roles.intersection(target_roles):
            label_lines: List[str] = []
            if "underlay-route-reflector" in matched_roles:
                label_lines.append("(BGP-RR)")
            for spec in interface_specs:
                if not isinstance(spec, dict):
                    continue
                name = str(spec.get("name", "")).strip()
                label = str(spec.get("label", name)).strip() or name
                if not name:
                    continue
                ip_map = underlay_ip_maps.get(name.lower(), {})
                ip_value = ip_map.get(node, "")
                sec_ip_map = (underlay_secondary_ip_maps or {}).get(name.lower(), {})
                sec_values = sec_ip_map.get(node, [])
                if ip_value:
                    label_lines.append(f"{label}: {ip_value}")
                for sec in sec_values:
                    label_lines.append(f"{label}(sec) : {sec}")
            if label_lines:
                lines_map[node] = label_lines
                # Keep first as backward-compatible single map values.
                first = label_lines[0]
                if ": " in first:
                    first_label, first_value = first.split(": ", 1)
                    address_map[node] = first_value
                    label_map[node] = first_label.strip()

    return address_map, label_map, lines_map


def prepare_topology_diagram_context(args: argparse.Namespace, logger: Logger) -> Dict[str, Any]:
    """
    Build shared topology diagram rendering inputs for Mermaid/Graphviz/draw.io.
    """
    records = read_links_csv(args.input)
    mappings = load_mappings(args.mappings)
    roles = load_roles(args.roles)

    inventory_map: Dict[str, Dict[str, Any]] = {}
    hosts_path = resolve_hosts_path(args.hosts, required=False)
    if hosts_path:
        inventory_data = load_yaml(hosts_path)
        inventory_map = load_inventory_map_from_list(load_inventory_data(inventory_data))

    candidate_records: List[Dict[str, str]] = []
    if getattr(args, "input_candidates", None):
        candidate_records = read_links_csv(args.input_candidates)

    mgmt_ip_map = build_node_mgmt_ip_map(
        inventory_map=inventory_map,
        mappings=mappings,
        logger=logger,
    )

    rendered_links, skipped_by_confidence = prepare_rendered_links(
        records=records,
        mappings=mappings,
        roles=roles,
        min_confidence=args.min_confidence,
        logger=logger,
        log_skips=False,
        inventory_map=inventory_map,
        clab_mode=False,
    )

    rendered_candidate_links: List[Dict[str, Any]] = []
    if candidate_records:
        rendered_candidate_links = prepare_rendered_candidate_links(
            records=candidate_records,
            mappings=mappings,
            roles=roles,
            logger=logger,
        )

    normalized_inventory_map, normalized_mgmt_ip_map = build_normalized_inventory_and_mgmt_maps(
        inventory_map=inventory_map,
        mgmt_ip_map=mgmt_ip_map,
        mappings=mappings,
    )

    node_address_map: Optional[Dict[str, str]] = None
    node_address_label_map: Optional[Dict[str, str]] = None
    node_address_lines_map: Optional[Dict[str, List[str]]] = None
    link_label_map: Optional[Dict[str, str]] = None
    node_interface_label_map: Optional[Dict[str, str]] = None
    output_path = args.output
    title = args.title
    if getattr(args, "underlay", False):
        underlay_cfg = load_underlay_render_config(args.underlay_config)
        target_roles = set(underlay_cfg.get("target_roles", []))
        rendered_links = filter_links_by_target_roles(rendered_links, roles, target_roles)
        if rendered_candidate_links:
            rendered_candidate_links = filter_links_by_target_roles(rendered_candidate_links, roles, target_roles)
        underlay_ip_maps: Dict[str, Dict[str, str]] = {}
        underlay_secondary_ip_maps: Dict[str, Dict[str, List[str]]] = {}
        for spec in underlay_cfg.get("interfaces", []):
            if not isinstance(spec, dict):
                continue
            iface = str(spec.get("name", "loopback0"))
            vrf = str(spec.get("vrf", underlay_cfg.get("vrf", "default")))
            primary_map, secondary_map = build_underlay_loopback_maps(
                raw_dir=args.underlay_raw,
                mappings=mappings,
                interface_name=iface,
                vrf=vrf,
            )
            underlay_ip_maps[iface.lower()] = primary_map
            underlay_secondary_ip_maps[iface.lower()] = secondary_map
        node_address_map, node_address_label_map, node_address_lines_map = build_mermaid_address_maps(
            normalized_inventory_map=normalized_inventory_map,
            normalized_mgmt_ip_map=normalized_mgmt_ip_map,
            roles=roles,
            underlay_config=underlay_cfg,
            underlay_ip_maps=underlay_ip_maps,
            underlay_secondary_ip_maps=underlay_secondary_ip_maps,
        )
        underlay_if_ip_map = build_underlay_interface_ip_maps(
            raw_dir=args.underlay_raw,
            mappings=mappings,
            vrf=str(underlay_cfg.get("vrf", "default")),
        )
        node_interface_label_map = {}
        for node_name, iface_ip_map in underlay_if_ip_map.items():
            for iface_name, ip_value in iface_ip_map.items():
                node_interface_label_map[f"{node_name}|{iface_name}"] = ip_value
        link_label_map = build_underlay_link_label_map(
            rendered_links=rendered_links,
            node_if_ip_map=underlay_if_ip_map,
        )
        output_path = add_underlay_suffix_to_path(output_path)
        title = f"{title} (UNDERLAY)"
        logger.info(
            "Underlay render enabled: roles=%s vrf=%s interface=%s label=%s raw=%s",
            ",".join(underlay_cfg.get("target_roles", [])),
            underlay_cfg.get("vrf", "default"),
            ",".join([str(x.get("name", "")) for x in underlay_cfg.get("interfaces", []) if isinstance(x, dict)]),
            ",".join([str(x.get("label", "")) for x in underlay_cfg.get("interfaces", []) if isinstance(x, dict)]),
            args.underlay_raw,
        )

    return {
        "roles": roles,
        "normalized_inventory_map": normalized_inventory_map,
        "normalized_mgmt_ip_map": normalized_mgmt_ip_map,
        "rendered_links": rendered_links,
        "rendered_candidate_links": rendered_candidate_links,
        "node_address_map": node_address_map,
        "node_address_label_map": node_address_label_map,
        "node_address_lines_map": node_address_lines_map,
        "link_label_map": link_label_map,
        "node_interface_label_map": node_interface_label_map,
        "output_path": output_path,
        "title": title,
        "skipped_by_confidence": skipped_by_confidence,
    }


def build_drawio_page_diagram(
    args: argparse.Namespace,
    logger: Logger,
    direction: str,
    underlay: bool,
    page_name: str,
) -> tuple[ET.Element, Dict[str, str]]:
    """
    Build one draw.io <diagram> element for the requested variant.
    """
    page_args = argparse.Namespace(**vars(args))
    page_args.direction = direction
    page_args.underlay = underlay
    context = prepare_topology_diagram_context(page_args, logger)

    drawio_lines = render_drawio_xml_lines(
        rendered_links=context["rendered_links"],
        roles=context["roles"],
        normalized_inventory_map=context["normalized_inventory_map"],
        normalized_mgmt_ip_map=context["normalized_mgmt_ip_map"],
        detect_node_role_func=detect_node_role,
        get_role_priority_func=get_role_priority,
        is_network_device_type_func=is_network_device_type,
        direction=direction,
        group_by_role=args.group_by_role,
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        node_interface_label_map=context["node_interface_label_map"],
    )
    root = ET.fromstring("\n".join(drawio_lines))
    diagram = root.find("diagram")
    if diagram is None:
        raise ValueError("draw.io output did not contain a <diagram> element")
    diagram.attrib["name"] = page_name
    diagram.attrib["id"] = re.sub(r"[^a-z0-9]+", "-", page_name.lower()).strip("-") or "topology"
    return diagram, dict(root.attrib)


def build_drawio_multipage_lines(diagrams: List[ET.Element], mxfile_attrs: Dict[str, str]) -> List[str]:
    """
    Build one draw.io mxfile from multiple <diagram> elements.
    """
    if not diagrams:
        raise ValueError("draw.io multi-page export requires at least one diagram")

    mxfile = ET.Element(
        "mxfile",
        mxfile_attrs,
    )

    for diagram in diagrams:
        mxfile.append(diagram)

    xml_text = ET.tostring(mxfile, encoding="unicode")
    return xml_text.splitlines()


def cmd_prepare_hosts(args: argparse.Namespace) -> None:
    """
    Convert hosts.txt into hosts.yaml.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    entries = parse_hosts_txt(args.input)
    inventory = build_inventory(entries)
    save_yaml(inventory, args.output)
    logger.info("Generated %s", args.output)


def cmd_transform_config(args: argparse.Namespace) -> None:
    """
    Transform hosts.yaml and NX-OS running-config files for lab use.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    clab_env_path = args.clab_env
    if not clab_env_path and Path("clab_merge.yaml").exists():
        clab_env_path = "clab_merge.yaml"
    clab_env_data = load_yaml(clab_env_path)
    mgmt_subnet = parse_mgmt_ipv4_subnet(clab_env_data)

    transformed_inventory = transform_inventory_mgmt_subnet(inventory_data, mgmt_subnet)
    save_yaml(transformed_inventory, args.output_hosts)
    logger.info(
        "WROTE TRANSFORMED HOSTS %s mgmt_subnet=%s",
        args.output_hosts,
        str(mgmt_subnet) if mgmt_subnet is not None else "disabled",
    )

    raw_dir = Path(args.input)
    run_dir = get_run_input_dir(raw_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    hosts = inventory_data.get("all", {}).get("hosts", {})
    if not isinstance(hosts, dict):
        raise ValueError(f"Invalid hosts inventory format: {hosts_path}")

    transformed_count = 0
    missing_files: List[str] = []

    for hostname in sorted(hosts.keys()):
        source_path = run_dir / f"{hostname}_run.txt"
        if not source_path.exists():
            missing_files.append(str(source_path))
            logger.warning("SKIP MISSING RUN CONFIG %s", source_path)
            continue

        source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        transformed_text, stats = transform_run_config_text(source_text, mgmt_subnet)
        output_path = output_dir / source_path.name
        output_path.write_text(transformed_text, encoding="utf-8")
        transformed_count += 1
        logger.info(
            "WROTE LAB CONFIG %s subif_conversions=%d mgmt_sections=%d parent_added=%d parent_merged=%d svi_merged=%d",
            output_path,
            stats["subinterface_conversions"],
            stats["management_section_updates"],
            stats["generated_parent_interfaces"],
            stats["merged_existing_parent_interfaces"],
            stats["merged_existing_svis"],
        )

    logger.info(
        "TRANSFORM COMPLETE hosts=%d configs=%d missing=%d",
        len(hosts),
        transformed_count,
        len(missing_files),
    )


def cmd_generate_sample_config(args: argparse.Namespace) -> None:
    """
    Generate sample config/input files used by command arguments.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    templates_dir = get_resource_dir("sample_configs")
    if not templates_dir.exists():
        raise FileNotFoundError(f"Sample config templates directory not found: {templates_dir}")

    template_files = sorted([p for p in templates_dir.iterdir() if p.is_file()])
    if not template_files:
        raise FileNotFoundError(f"No sample config templates found in: {templates_dir}")

    for src in template_files:
        dst = outdir / src.name
        if dst.exists() and not args.force:
            logger.info("SKIP EXISTS %s (use --force to overwrite)", dst)
            continue
        shutil.copy2(src, dst)
        logger.info("WROTE %s", dst)

    logger.info("Generated sample config set from %s into %s", templates_dir, outdir)


def run_collect(args: argparse.Namespace, logger: Logger, old_generation_id: str | None = None) -> None:
    """
    Collect raw LLDP and optional running-config files.
    """
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)
    show_commands_file = resolve_show_commands_path(args.show_commands_file)
    run_config_only = getattr(args, "run_config_only", False)
    # Dedicated subcommands should not execute extra show command lists.
    if args.command in {"collect-clab", "collect-run-config"} and args.show_commands_file:
        raise ValueError(f"{args.command} does not support --show-commands-file")
    if args.command in {"collect-run-diff", "collect-run-diff-cmd", "collect-clab", "collect-run-config"}:
        show_commands_file = None
    show_commands = load_show_commands(show_commands_file)
    show_command_groups = load_show_command_groups(show_commands_file)
    target_hosts = parse_host_filter(args.target_hosts)
    show_hosts = parse_host_filter(args.show_hosts)
    roles = load_roles(args.roles)
    if args.show_commands_file and args.show_run_diff:
        raise ValueError("--show-commands-file and --show-run-diff cannot be used together")
    if args.show_commands_file and args.show_run_diff_comands:
        raise ValueError("--show-commands-file and --show-run-diff-comands cannot be used together")
    if args.show_run_diff and args.show_run_diff_comands:
        raise ValueError("--show-run-diff and --show-run-diff-comands cannot be used together")
    if args.show_only and not show_commands and not args.show_run_diff and not args.show_run_diff_comands:
        raise ValueError("--show-only requires --show-commands-file or --show-run-diff or --show-run-diff-comands")
    if args.command == "collect-list" and not show_commands:
        raise ValueError(
            f"collect-list requires --show-commands-file or ./{DEFAULT_SHOW_COMMANDS_PATH}"
        )
    before_show_run_dir = getattr(args, "before_show_run_dir", None)
    if before_show_run_dir and not args.show_run_diff:
        raise ValueError("--before-show-run-dir can only be used with --show-run-diff or collect-run-diff")

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info("Policy file: %s", args.policy if args.policy else "(default)")
    logger.info("Transport mode: %s", args.transport)
    if target_hosts:
        logger.info("Collect target-hosts filter: %d specified hosts", len(target_hosts))
    if show_commands:
        if show_hosts:
            logger.info(
                "Extra show commands: %d commands for %d specified hosts",
                len(show_commands),
                len(show_hosts),
            )
        else:
            logger.info("Extra show commands: %d commands for all collect targets", len(show_commands))
    if args.show_run_diff:
        if show_hosts:
            logger.info("Running-config diff: enabled for %d specified hosts", len(show_hosts))
        else:
            logger.info("Running-config diff: enabled for all collect targets")
    if args.show_run_diff_comands:
        if show_hosts:
            logger.info("Running-config diff commands: enabled for %d specified hosts", len(show_hosts))
        else:
            logger.info("Running-config diff commands: enabled for all collect targets")

    lldp_output_dir = str(Path(args.output) / "lldp")
    run_output_dir = str(Path(args.output) / "config")
    before_run_input_dir = str(get_run_input_dir(before_show_run_dir or args.output))
    is_collect_list = args.command == "collect-list"
    show_output_dir = str(Path(args.output) / "show_lists") if is_collect_list else str(Path(args.output))
    run_diff_output_dir = (
        str(Path(args.output) / "show_run_diff")
        if args.show_run_diff
        else str(Path(args.output))
    )
    run_diff_cmd_output_dir = (
        str(Path(args.output) / "show_run_diff_commands")
        if args.show_run_diff_comands
        else str(Path(args.output))
    )
    generation_id = old_generation_id or datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    Path(lldp_output_dir).mkdir(parents=True, exist_ok=True)
    Path(run_output_dir).mkdir(parents=True, exist_ok=True)
    Path(show_output_dir).mkdir(parents=True, exist_ok=True)
    Path(run_diff_output_dir).mkdir(parents=True, exist_ok=True)
    Path(run_diff_cmd_output_dir).mkdir(parents=True, exist_ok=True)
    if args.show_run_diff and not Path(before_run_input_dir).exists():
        raise FileNotFoundError(f"before show-run directory not found: {before_run_input_dir}")
    logger.info(
        "Collect output dirs: lldp=%s config=%s before-run=%s show=%s run-diff=%s run-diff-cmd=%s old-generation=%s",
        lldp_output_dir,
        run_output_dir,
        before_run_input_dir,
        show_output_dir,
        run_diff_output_dir,
        run_diff_cmd_output_dir,
        generation_id,
    )
    collected = skipped = failed = 0
    run_diff_sections: List[str] = []
    run_diff_no_change_hosts: List[str] = []
    run_diff_command_sections: List[str] = []
    run_diff_command_no_change_hosts: List[str] = []
    targets: List[Dict[str, Any]] = []

    for host in hosts:
        if target_hosts and host["hostname"] not in target_hosts:
            continue

        include_ok, include_reason = should_include(host, policy)
        if not include_ok:
            logger.info("SKIP %s: %s", host["hostname"], include_reason)
            skipped += 1
            continue

        exclude_hit, exclude_reason = should_exclude(host, policy)
        if exclude_hit:
            logger.info("SKIP %s: %s", host["hostname"], exclude_reason)
            skipped += 1
            continue

        targets.append(host)

    workers = max(1, args.workers)
    logger.info("Collect targets=%d workers=%d", len(targets), workers)
    targets, connect_failures = filter_hosts_by_connect_check(targets, args, logger)
    print_connect_check_failures("COLLECT", connect_failures)
    if not targets:
        logger.warning("No reachable/authenticated collect targets after connect check")
        logger.info(
            "SUMMARY collected=%d skipped=%d failed=%d output_dir=%s",
            collected,
            skipped + len(connect_failures),
            failed,
            args.output,
        )
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_host = {
            executor.submit(
                collect_from_host,
                host,
                *get_credentials_for_device(args, str(host.get("device_type", ""))),
                lldp_output_dir,
                run_output_dir,
                before_run_input_dir,
                show_output_dir,
                policy,
                logger,
                args.transport,
                (
                    resolve_show_commands_for_host(host, show_command_groups, roles)
                    if show_commands and (not show_hosts or host["hostname"] in show_hosts)
                    else None
                ),
                args.show_read_timeout,
                args.show_only,
                run_config_only,
                args.show_run_diff and (not show_hosts or host["hostname"] in show_hosts),
                args.show_run_diff_comands and (not show_hosts or host["hostname"] in show_hosts),
                generation_id,
            ): host
            for host in targets
        }

        for future in as_completed(future_to_host):
            host = future_to_host[future]
            try:
                result = future.result()
                run_diff_section = result.get("run_diff_section", "")
                if run_diff_section:
                    run_diff_sections.append(run_diff_section)
                run_diff_no_diff_host = result.get("run_diff_no_diff_host", "")
                if run_diff_no_diff_host:
                    run_diff_no_change_hosts.append(run_diff_no_diff_host)
                run_diff_command_section = result.get("run_diff_command_section", "")
                if run_diff_command_section:
                    run_diff_command_sections.append(run_diff_command_section)
                run_diff_command_no_diff_host = result.get("run_diff_command_no_diff_host", "")
                if run_diff_command_no_diff_host:
                    run_diff_command_no_change_hosts.append(run_diff_command_no_diff_host)
                collected += 1
            except Exception as exc:
                logger.exception("FAILED %s: %s", host["hostname"], exc)
                failed += 1

    if args.show_run_diff:
        if run_diff_sections:
            diff_parts: List[str] = ["\n\n".join(sorted(run_diff_sections)).rstrip()]
            if run_diff_no_change_hosts:
                no_diff_lines = ["### NO_DIFF_HOSTS", *sorted(run_diff_no_change_hosts)]
                diff_parts.append("\n".join(no_diff_lines).rstrip())
            diff_body = "\n\n".join([x for x in diff_parts if x]).rstrip()
        else:
            no_diff_lines = ["### NO_DIFF", "No differences detected in compared hosts."]
            if run_diff_no_change_hosts:
                no_diff_lines.extend(["", "### NO_DIFF_HOSTS", *sorted(run_diff_no_change_hosts)])
            logger.info("RUN DIFF: no host differences detected (%d hosts)", len(run_diff_no_change_hosts))
            diff_body = "\n".join(no_diff_lines).rstrip()
        save_current_and_old_snapshot(
            output_dir=run_diff_output_dir,
            filename="running_config_diff.log",
            content=diff_body + "\n",
            generation=generation_id,
            keep_generations=get_log_rotation_limit(),
            logger=logger,
            log_label="RUN DIFF",
        )
        logger.info("SAVED RUN DIFF SUMMARY (hosts=%d)", len(run_diff_sections))

    if args.show_run_diff_comands:
        if run_diff_command_sections:
            diff_parts: List[str] = ["\n\n".join(sorted(run_diff_command_sections)).rstrip()]
            if run_diff_command_no_change_hosts:
                no_diff_lines = ["### NO_DIFF_HOSTS", *sorted(run_diff_command_no_change_hosts)]
                diff_parts.append("\n".join(no_diff_lines).rstrip())
            diff_body = "\n\n".join([x for x in diff_parts if x]).rstrip()
        else:
            no_diff_lines = ["### NO_DIFF", "No differences detected in compared hosts."]
            if run_diff_command_no_change_hosts:
                no_diff_lines.extend(["", "### NO_DIFF_HOSTS", *sorted(run_diff_command_no_change_hosts)])
            logger.info(
                "RUN DIFF COMMANDS: no host differences detected (%d hosts)",
                len(run_diff_command_no_change_hosts),
            )
            diff_body = "\n".join(no_diff_lines).rstrip()
        save_current_and_old_snapshot(
            output_dir=run_diff_cmd_output_dir,
            filename="running_config_diff_commands.log",
            content=diff_body + "\n",
            generation=generation_id,
            keep_generations=get_log_rotation_limit(),
            logger=logger,
            log_label="RUN DIFF COMMANDS",
        )
        logger.info("SAVED RUN DIFF COMMANDS SUMMARY (hosts=%d)", len(run_diff_command_sections))

    logger.info(
        "SUMMARY collected=%d skipped=%d failed=%d output_dir=%s",
        collected, skipped, failed, args.output
    )


def cmd_collect(args: argparse.Namespace) -> None:
    """
    Collect raw LLDP and optional running-config files.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    run_collect(args, logger)


def run_check_logging_for_host(
    host: Dict[str, Any],
    args: argparse.Namespace,
    logger: Logger,
    started_at: datetime,
    last_window,
    check_patterns: List[str],
    exclude_patterns: List[str],
) -> HostLoggingCheckResult:
    """
    Run check-logging for one host using either raw or live collection.
    """

    hostname = str(host.get("hostname", ""))
    device_type = str(host.get("device_type", "unknown"))
    raw_root = str(args.output)
    default_raw_source = str(Path(raw_root) / "show_lists" / hostname / f"{hostname}_shows.log")

    if device_type != "nxos":
        result = HostLoggingCheckResult(
            hostname=hostname,
            device_type=device_type,
            raw_source=default_raw_source,
            skipped=True,
        )
        result.warnings.append(
            LoggingWarning(
                hostname=hostname,
                warning_type="unsupported",
                message=f"unsupported device_type for check-logging: {device_type}",
                raw_source=default_raw_source,
            )
        )
        return result

    severity = args.severity
    if severity is None:
        severity = DEFAULT_LOGGING_THRESHOLD_MAP.get(device_type)
    if severity is None:
        raise ValueError(f"default logging severity is not defined for device_type={device_type}")

    if args.no_collect_raw_check:
        raw_path = Path(default_raw_source)
        if not raw_path.exists():
            result = HostLoggingCheckResult(
                hostname=hostname,
                device_type=device_type,
                raw_source=str(raw_path),
                skipped=True,
            )
            result.warnings.append(
                LoggingWarning(
                    hostname=hostname,
                    warning_type="section",
                    message="raw show log file not found",
                    raw_source=str(raw_path),
                )
            )
            return result

        show_text = raw_path.read_text(encoding="utf-8", errors="ignore")
        body_text, warnings = extract_latest_show_logging_block(hostname, show_text, str(raw_path))
        result = check_host_logging(
            hostname=hostname,
            device_type=device_type,
            raw_source=str(raw_path),
            text=body_text,
            started_at=started_at,
            last_window=last_window,
            severity=severity,
            check_patterns=check_patterns,
            exclude_patterns=exclude_patterns,
        )
        result.warnings.extend(warnings)
        if body_text is None:
            result.skipped = True
        return result

    if args.transport == "nxapi":
        raise ValueError("check-logging does not support --transport nxapi for NX-OS")

    command = get_show_logging_command(device_type)
    collector = build_collector(
        host,
        *get_credentials_for_device(args, device_type),
        logger,
        "ssh",
    )
    try:
        command_result = collector.run_command(command, read_timeout=120)
    finally:
        collector.close()

    raw_source = f"{hostname} live:{command}"
    if not command_result.ok:
        result = HostLoggingCheckResult(
            hostname=hostname,
            device_type=device_type,
            raw_source=raw_source,
            skipped=True,
        )
        result.warnings.append(
            LoggingWarning(
                hostname=hostname,
                warning_type="collect",
                message=command_result.error or "show logging collection failed",
                raw_source=raw_source,
            )
        )
        return result

    return check_host_logging(
        hostname=hostname,
        device_type=device_type,
        raw_source=raw_source,
        text=command_result.output,
        started_at=started_at,
        last_window=last_window,
        severity=severity,
        check_patterns=check_patterns,
        exclude_patterns=exclude_patterns,
    )


def run_check_logging(args: argparse.Namespace, logger: Logger) -> tuple[Path, List[str]]:
    """
    Execute check-logging and return current report path and rendered lines.
    """
    if args.severity is not None and not 0 <= args.severity <= 7:
        raise ValueError("--severity must be between 0 and 7")

    started_at = datetime.now().astimezone()
    last_window = parse_last_window(int(args.last[0]), str(args.last[1])) if args.last else None
    last_label = f"{args.last[0]} {args.last[1]}" if args.last else "all"
    check_patterns = load_check_patterns(args.check_string)
    exclude_patterns = load_check_patterns(args.uncheck_string)

    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)
    target_hosts = parse_host_filter(args.target_hosts)
    targets, skipped = select_target_hosts(hosts, policy, logger, target_hosts=target_hosts)

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info("check-logging targets=%d skipped_by_policy=%d workers=%d", len(targets), skipped, max(1, args.workers))
    logger.info("check-logging mode=%s raw_dir=%s", "raw" if args.no_collect_raw_check else "live", args.output)
    logger.info("check-logging last=%s", last_label)
    logger.info("check-logging patterns=%d", len(check_patterns))
    logger.info("check-logging exclude_patterns=%d", len(exclude_patterns))

    results: List[HostLoggingCheckResult] = []

    supported_targets = [host for host in targets if str(host.get("device_type", "unknown")) == "nxos"]
    unsupported_targets = [host for host in targets if str(host.get("device_type", "unknown")) != "nxos"]

    for host in unsupported_targets:
        results.append(
            HostLoggingCheckResult(
                hostname=str(host.get("hostname", "")),
                device_type=str(host.get("device_type", "unknown")),
                raw_source=str(Path(args.output) / "show_lists" / str(host.get("hostname", "")) / f"{host.get('hostname', '')}_shows.log"),
                skipped=True,
                warnings=[
                    LoggingWarning(
                        hostname=str(host.get("hostname", "")),
                        warning_type="unsupported",
                        message=f"unsupported device_type for check-logging: {host.get('device_type', 'unknown')}",
                        raw_source=str(Path(args.output) / "show_lists" / str(host.get("hostname", "")) / f"{host.get('hostname', '')}_shows.log"),
                    )
                ],
            )
        )

    if not args.no_collect_raw_check and supported_targets:
        connect_args = argparse.Namespace(**vars(args))
        connect_args.transport = "ssh"
        supported_targets, connect_failures = filter_hosts_by_connect_check(supported_targets, connect_args, logger)
        print_connect_check_failures("CHECK-LOGGING", connect_failures)
        for failure in connect_failures:
            results.append(
                HostLoggingCheckResult(
                    hostname=failure.hostname,
                    device_type="nxos",
                    raw_source=f"{failure.hostname} live:show logging",
                    skipped=True,
                    warnings=[
                        LoggingWarning(
                            hostname=failure.hostname,
                            warning_type="collect",
                            message=f"connect check failed: {failure.error or 'unknown error'}",
                            raw_source=f"{failure.hostname} live:show logging",
                        )
                    ],
                )
            )

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_host = {
            executor.submit(
                run_check_logging_for_host,
                host,
                args,
                logger,
                started_at,
                last_window,
                check_patterns,
                exclude_patterns,
            ): host
            for host in supported_targets
        }
        for future in as_completed(future_to_host):
            host = future_to_host[future]
            try:
                results.append(future.result())
            except Exception as exc:
                hostname = str(host.get("hostname", ""))
                logger.exception("CHECK-LOGGING FAILED %s: %s", hostname, exc)
                results.append(
                    HostLoggingCheckResult(
                        hostname=hostname,
                        device_type=str(host.get("device_type", "unknown")),
                        raw_source=str(Path(args.output) / "show_lists" / hostname / f"{hostname}_shows.log"),
                        skipped=True,
                        warnings=[
                            LoggingWarning(
                                hostname=hostname,
                                warning_type="collect",
                                message=str(exc),
                                raw_source=str(Path(args.output) / "show_lists" / hostname / f"{hostname}_shows.log"),
                            )
                        ],
                    )
                )

    output_dir = Path(args.output) / "check-logging"
    generation_id = started_at.strftime("%Y%m%d%H%M%S")
    output_name = "check-logging.txt"
    report_lines = render_check_logging_report(
        started_at=started_at,
        mode="raw" if args.no_collect_raw_check else "live",
        output_root=args.output,
        last_label=last_label,
        results=results,
        last_window=last_window,
    )
    old_path, current_path = save_current_and_old_snapshot(
        output_dir=output_dir,
        filename=output_name,
        content="\n".join(report_lines).rstrip() + "\n",
        generation=generation_id,
        keep_generations=get_log_rotation_limit(),
        logger=logger,
        log_label="CHECK LOGGING",
    )
    logger.info("WROTE CHECK LOGGING REPORT current=%s old=%s", current_path, old_path)
    return current_path, report_lines


def cmd_check_logging(args: argparse.Namespace) -> None:
    """
    Check device show logging output for recent error logs.
    """

    logger = setup_logging(args.log_file, args.verbose)
    _, report_lines = run_check_logging(args, logger)

    try:
        host_check_start = report_lines.index("### HOST LOGGING CHECK SUMMARY")
    except ValueError:
        host_check_start = 0
    try:
        host_check_end = report_lines.index("### HOST RESULT SUMMARY")
    except ValueError:
        host_check_end = len(report_lines)
    print("\n".join(report_lines[host_check_start:host_check_end]).rstrip())


def run_collect_all_flow(args: argparse.Namespace, logger: Logger) -> Path:
    """
    Run all collect-family flows and package current outputs.
    """
    generation_id = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    setattr(args, "_connect_check_cache", {})
    logger.info("START COLLECT-ALL generation=%s", generation_id)

    step_definitions = [
        (
            "collect-clab",
            {
                "command": "collect-clab",
                "show_commands_file": None,
                "show_run_diff": False,
                "show_run_diff_comands": False,
                "show_only": False,
                "run_config_only": False,
                "before_show_run_dir": None,
            },
        ),
        (
            "collect-list",
            {
                "command": "collect-list",
                "show_run_diff": False,
                "show_run_diff_comands": False,
                "show_only": True,
                "run_config_only": False,
                "before_show_run_dir": None,
            },
        ),
        (
            "collect-run-diff",
            {
                "command": "collect-run-diff",
                "show_commands_file": None,
                "show_run_diff": True,
                "show_run_diff_comands": False,
                "show_only": True,
                "run_config_only": False,
            },
        ),
        (
            "collect-run-diff-cmd",
            {
                "command": "collect-run-diff-cmd",
                "show_commands_file": None,
                "show_run_diff": False,
                "show_run_diff_comands": True,
                "show_only": True,
                "run_config_only": False,
                "before_show_run_dir": None,
            },
        ),
    ]

    for step_name, overrides in step_definitions:
        step_args = argparse.Namespace(**vars(args))
        for key, value in overrides.items():
            setattr(step_args, key, value)
        logger.info("COLLECT-ALL STEP %s", step_name)
        run_collect(step_args, logger, old_generation_id=generation_id)

    archive_filter_hosts: Set[str] | None = None
    if getattr(args, "filter_archive_hosts", False):
        archive_filter_hosts = resolve_archive_filter_hostnames(args, logger)
        logger.info(
            "COLLECT-ALL ARCHIVE HOST FILTER enabled hosts=%d",
            len(archive_filter_hosts),
        )

    return create_collect_archive(args.output, generation_id, logger, allowed_hosts=archive_filter_hosts)


def cmd_collect_all(args: argparse.Namespace) -> None:
    """
    Run all collect-family flows and package current outputs.
    """
    logger = setup_logging(args.log_file, args.verbose)
    run_collect_all_flow(args, logger)


def run_collect_workflow_and_summarize(
    args: argparse.Namespace,
    logger: Logger,
    mode: str,
) -> None:
    """
    Run collect-all + check-logging(raw) + collect-run-diff-cmd and print a final summary.
    """
    started_at = datetime.now().astimezone()
    timestamp_label = started_at.strftime("%Y%m%d-%H%M%S")
    is_before = mode == "before"
    phase_label = "事前" if is_before else "事後"

    logger.info("START COLLECT-%s-WORK timestamp=%s", mode.upper(), timestamp_label)

    collect_archive_path = run_collect_all_flow(args, logger)

    check_args = argparse.Namespace(**vars(args))
    check_args.command = "check-logging"
    check_args.transport = "ssh"
    check_args.no_collect_raw_check = True
    if is_before:
        check_args.last = args.last or [7, "days"]
    else:
        check_args.last = args.last
        if not check_args.last:
            last_before = find_latest_before_work_timestamp(args.output, logger)
            if last_before is None:
                raise ValueError(
                    "collect-after-work requires previous collect-before-work history. "
                    "Run collect-before-work first or specify --last VALUE UNIT."
                )
            elapsed = started_at - last_before
            amount, unit = format_elapsed_last_window(elapsed)
            check_args.last = [amount, unit]
            logger.info(
                "COLLECT-AFTER-WORK AUTO LAST from before-work=%s elapsed=%s resolved=%s %s",
                last_before.isoformat(timespec="seconds"),
                elapsed,
                amount,
                unit,
            )
    report_path, report_lines = run_check_logging(check_args, logger)

    diff_args = argparse.Namespace(**vars(args))
    diff_args.command = "collect-run-diff-cmd"
    diff_args.show_run_diff = False
    diff_args.show_run_diff_comands = True
    diff_args.show_only = True
    diff_args.run_config_only = False
    diff_args.show_commands_file = None
    diff_args.before_show_run_dir = None
    run_collect(diff_args, logger)
    diff_log_path = Path(args.output) / "show_run_diff_commands" / "running_config_diff_commands.log"

    archive_name = f"{'before' if is_before else 'after'}-log-{timestamp_label}.tar.gz"
    bundle_archive_path = create_named_archive(
        args.output,
        archive_name,
        [collect_archive_path, report_path, diff_log_path],
        logger,
        output_tar=args.output_tar,
    )

    if is_before:
        save_latest_before_work_timestamp(args.output, datetime.now().astimezone(), logger)

    logging_warning_hosts = extract_non_ok_logging_hosts(report_lines)
    diff_warning_hosts = extract_run_diff_warning_hosts(diff_log_path)

    print(f"{phase_label}ログ tar: {bundle_archive_path}")
    print(f"collect-all tar: {collect_archive_path}")
    print(f"check-logging: {report_path}")
    print(f"collect-run-diff-cmd: {diff_log_path}")
    if not logging_warning_hosts and not diff_warning_hosts:
        print(f"{phase_label}チェック(check: logging severity, check: show run diff) OK")
        return

    if logging_warning_hosts:
        print("!!!HOST LOGGING 要チェック !!!")
        print("\n".join(logging_warning_hosts))
    if diff_warning_hosts:
        print("!!!保存されていない Config があります!!!")
        print("\n".join(diff_warning_hosts))


def cmd_collect_before_work(args: argparse.Namespace) -> None:
    """
    Run pre-work collection, logging check, diff check, and bundle outputs.
    """
    logger = setup_logging(args.log_file, args.verbose)
    run_collect_workflow_and_summarize(args, logger, mode="before")


def cmd_collect_after_work(args: argparse.Namespace) -> None:
    """
    Run post-work collection, logging check, diff check, and bundle outputs.
    """
    logger = setup_logging(args.log_file, args.verbose)
    run_collect_workflow_and_summarize(args, logger, mode="after")


def cmd_push_config(args: argparse.Namespace) -> None:
    """
    Push config lines from file to target hosts.
    """
    logger = setup_logging(args.log_file, args.verbose)
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)
    config_lines = load_config_lines(args.config_file)
    if not config_lines:
        raise ValueError(f"no config lines found in {args.config_file}")

    target_hosts = parse_host_filter(args.target_hosts)
    targets, skipped = select_target_hosts(
        hosts,
        policy,
        logger,
        target_hosts=target_hosts,
    )

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info("Push targets=%d skipped=%d workers=%d", len(targets), skipped, max(1, args.workers))
    logger.info("Config file=%s lines=%d", args.config_file, len(config_lines))
    logger.info("write-memory=%s", args.write_memory)
    targets, connect_failures = filter_hosts_by_connect_check(targets, args, logger)
    skipped += len(connect_failures)
    print_connect_check_failures("PUSH", connect_failures)

    if not targets:
        logger.info("No targets to push")
        return

    print("\n=== PUSH TARGETS ===")
    for host in sorted(targets, key=lambda x: str(x.get("hostname", ""))):
        print(f"- {host['hostname']} ({host['ip']}, {host['device_type']})")
    print("====================")
    answer = input(f"Proceed with push to {len(targets)} reachable hosts? [yes/no]: ").strip().lower()
    if answer != "yes":
        logger.info("Aborted by user input: %s", answer)
        return

    pushed = failed = 0
    pushed_hosts: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_host = {
            executor.submit(
                push_config_to_host,
                host,
                *get_credentials_for_device(args, str(host.get("device_type", ""))),
                config_lines,
                logger,
            ): host
            for host in targets
        }
        for future in as_completed(future_to_host):
            host = future_to_host[future]
            try:
                future.result()
                pushed += 1
                pushed_hosts.append(host)
            except Exception as exc:
                logger.exception("FAILED %s: %s", host["hostname"], exc)
                failed += 1

    saved = save_failed = 0
    failed_save_hosts: List[str] = []
    if args.write_memory and pushed_hosts:
        logger.info("START SAVE PHASE hosts=%d", len(pushed_hosts))
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_host = {
                executor.submit(
                    save_config_on_host,
                    host,
                    *get_credentials_for_device(args, str(host.get("device_type", ""))),
                    logger,
                ): host
                for host in pushed_hosts
            }
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    future.result()
                    saved += 1
                except Exception as exc:
                    logger.error("FAILED SAVE %s: %s", host["hostname"], exc)
                    save_failed += 1
                    failed_save_hosts.append(str(host["hostname"]))
    elif not args.write_memory:
        logger.info("SKIP SAVE PHASE: --write-memory not set")

    logger.info("SUMMARY pushed=%d skipped=%d failed=%d saved=%d save_failed=%d", pushed, skipped, failed, saved, save_failed)
    if args.write_memory:
        if not pushed_hosts:
            logger.info("SAVE RESULT no hosts were processed")
        elif failed_save_hosts:
            logger.warning("SAVE RESULT failed_hosts=%s", ",".join(sorted(failed_save_hosts)))
        else:
            logger.info("SAVE RESULT all hosts succeeded")
        print_operation_result_summary("SAVE", len(pushed_hosts), failed_save_hosts)


def cmd_push_config_dir(args: argparse.Namespace) -> None:
    """
    Push per-host config files from a directory.

    Target file pattern:
      <hostname><suffix>
    """
    logger = setup_logging(args.log_file, args.verbose)
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)
    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    target_hosts = parse_host_filter(args.target_hosts)
    suffix = str(args.file_suffix or "")

    def resolve_config_path_for_host(hostname: str) -> Path | None:
        # Exact filename mode: <hostname><suffix>
        if not args.file_hostname_include:
            filename = f"{hostname}{suffix}"
            candidate = input_dir / filename
            return candidate if candidate.exists() else None

        # Include mode: filename contains hostname and ends with suffix (if provided)
        matched = sorted(
            [
                p for p in input_dir.iterdir()
                if p.is_file()
                and hostname in p.name
                and (not suffix or p.name.endswith(suffix))
            ],
            key=lambda p: p.name,
        )
        if not matched:
            return None
        if len(matched) > 1:
            logger.warning(
                "SKIP %s: multiple files matched in include mode: %s",
                hostname,
                ", ".join([m.name for m in matched]),
            )
            return None
        return matched[0]
    filtered_hosts, skipped = select_target_hosts(
        hosts,
        policy,
        logger,
        target_hosts=target_hosts,
    )
    targets: List[Dict[str, Any]] = []
    missing = 0

    for host in filtered_hosts:
        hostname = host["hostname"]

        config_path = resolve_config_path_for_host(hostname)
        if config_path is None:
            logger.info(
                "SKIP %s: config file not found (dir=%s suffix=%s include-mode=%s)",
                hostname,
                input_dir,
                suffix if suffix else "(none)",
                args.file_hostname_include,
            )
            missing += 1
            continue

        host_copy = dict(host)
        host_copy["config_path"] = str(config_path)
        targets.append(host_copy)

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info(
        "Push-dir candidates=%d skipped=%d missing-config=%d workers=%d",
        len(targets),
        skipped,
        missing,
        max(1, args.workers),
    )
    targets, connect_failures = filter_hosts_by_connect_check(targets, args, logger)
    skipped += len(connect_failures)
    print_connect_check_failures("PUSH", connect_failures)

    if not targets:
        logger.info("No targets to push")
        return

    print("\n=== PUSH TARGETS ===")
    for host in sorted(targets, key=lambda x: str(x.get("hostname", ""))):
        print(f"- {host['hostname']} ({host['ip']}, {host['device_type']}): {host['config_path']}")
    print("====================")
    answer = input(f"Proceed with push to {len(targets)} reachable hosts? [yes/no]: ").strip().lower()
    if answer != "yes":
        logger.info("Aborted by user input: %s", answer)
        return

    pushed = failed = 0
    pushed_hosts: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_host = {}
        for host in targets:
            config_lines = load_config_lines(str(host["config_path"]))
            if not config_lines:
                logger.info("SKIP %s: no config lines found (%s)", host["hostname"], host["config_path"])
                skipped += 1
                continue
            future = executor.submit(
                push_config_to_host,
                host,
                *get_credentials_for_device(args, str(host.get("device_type", ""))),
                config_lines,
                logger,
            )
            future_to_host[future] = host

        for future in as_completed(future_to_host):
            host = future_to_host[future]
            try:
                future.result()
                pushed += 1
                pushed_hosts.append(host)
            except Exception as exc:
                logger.exception("FAILED %s: %s", host["hostname"], exc)
                failed += 1

    saved = save_failed = 0
    failed_save_hosts: List[str] = []
    if args.write_memory and pushed_hosts:
        logger.info("START SAVE PHASE hosts=%d", len(pushed_hosts))
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_host = {
                executor.submit(
                    save_config_on_host,
                    host,
                    *get_credentials_for_device(args, str(host.get("device_type", ""))),
                    logger,
                ): host
                for host in pushed_hosts
            }
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    future.result()
                    saved += 1
                except Exception as exc:
                    logger.error("FAILED SAVE %s: %s", host["hostname"], exc)
                    save_failed += 1
                    failed_save_hosts.append(str(host["hostname"]))
    elif not args.write_memory:
        logger.info("SKIP SAVE PHASE: --write-memory not set")

    logger.info(
        "SUMMARY pushed=%d skipped=%d missing=%d failed=%d saved=%d save_failed=%d",
        pushed,
        skipped,
        missing,
        failed,
        saved,
        save_failed,
    )
    if args.write_memory:
        if not pushed_hosts:
            logger.info("SAVE RESULT no hosts were processed")
        elif failed_save_hosts:
            logger.warning("SAVE RESULT failed_hosts=%s", ",".join(sorted(failed_save_hosts)))
        else:
            logger.info("SAVE RESULT all hosts succeeded")
        print_operation_result_summary("SAVE", len(pushed_hosts), failed_save_hosts)


def cmd_write_memory(args: argparse.Namespace) -> None:
    """
    Save running-config on selected hosts without pushing config.
    """
    logger = setup_logging(args.log_file, args.verbose)
    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = load_inventory_data(inventory_data)
    policy = load_policy_file(args.policy)

    target_hosts = parse_host_filter(args.target_hosts)
    targets, skipped = select_target_hosts(
        hosts,
        policy,
        logger,
        target_hosts=target_hosts,
    )

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info("Write-memory targets=%d skipped=%d workers=%d", len(targets), skipped, max(1, args.workers))
    targets, connect_failures = filter_hosts_by_connect_check(targets, args, logger)
    skipped += len(connect_failures)
    print_connect_check_failures("WRITE MEMORY", connect_failures)

    if not targets:
        logger.info("No targets to save")
        return

    print("\n=== WRITE MEMORY TARGETS ===")
    for host in sorted(targets, key=lambda x: str(x.get("hostname", ""))):
        print(f"- {host['hostname']} ({host['ip']}, {host['device_type']})")
    print("============================")
    answer = input(f"Proceed with save-config on {len(targets)} reachable hosts? [yes/no]: ").strip().lower()
    if answer != "yes":
        logger.info("Aborted by user input: %s", answer)
        return

    saved = failed = 0
    failed_hosts: List[str] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_host = {
            executor.submit(
                save_config_on_host,
                host,
                *get_credentials_for_device(args, str(host.get("device_type", ""))),
                logger,
            ): host
            for host in targets
        }
        for future in as_completed(future_to_host):
            host = future_to_host[future]
            try:
                future.result()
                saved += 1
            except Exception as exc:
                logger.error("FAILED SAVE %s: %s", host["hostname"], exc)
                failed += 1
                failed_hosts.append(str(host["hostname"]))

    logger.info("SUMMARY saved=%d skipped=%d failed=%d", saved, skipped, failed)
    if failed_hosts:
        logger.warning("WRITE MEMORY RESULT failed_hosts=%s", ",".join(sorted(failed_hosts)))
    else:
        logger.info("WRITE MEMORY RESULT all hosts succeeded")
    print_operation_result_summary("WRITE MEMORY", len(targets), failed_hosts)


def cmd_normalize_links(args: argparse.Namespace) -> None:
    """
    Parse raw files and produce confirmed/candidate CSV files.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)

    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    hosts = {h["hostname"]: h for h in load_inventory_data(inventory_data)}

    mappings = load_mappings(args.mappings)
    description_rules = load_description_rules(args.description_rules)
    raw_dir = Path(args.input)
    lldp_dir = get_lldp_input_dir(raw_dir)
    run_dir = get_run_input_dir(raw_dir)

    lldp_records: List[Dict[str, str]] = []
    description_records: List[Dict[str, str]] = []

    lldp_files = list_collect_output_files(lldp_dir, "lldp")
    logger.info("Found %d LLDP files in %s", len(lldp_files), lldp_dir)

    for f in lldp_files:
        local_hostname = get_collect_hostname_from_path(f, "lldp")
        host = hosts.get(local_hostname)
        device_type = host["device_type"] if host else "unknown"
        records = load_lldp_records_from_collect_file(f, local_hostname, device_type, mappings)
        logger.info("PARSED LLDP %s: %d links", f.name, len(records))
        lldp_records.extend(records)

    run_files = list_collect_output_files(run_dir, "run")
    logger.info("Found %d running-config files in %s", len(run_files), run_dir)

    for f in run_files:
        local_hostname = get_collect_hostname_from_path(f, "run")
        text = load_run_text_from_collect_file(f)
        records = build_description_records(
            local_hostname,
            text,
            mappings,
            description_rules,
            include_svi=args.include_svi,
        )
        logger.info("PARSED RUN %s: %d description links", f.name, len(records))
        description_records.extend(records)

    lldp_records = normalize_link_records(lldp_records, mappings)
    description_records = normalize_link_records(description_records, mappings)

    confirmed, candidates = merge_lldp_and_description_links(
        lldp_records=lldp_records,
        description_records=description_records,
        logger=logger,
    )

    write_links_csv(confirmed, args.output_confirmed)
    logger.info("Wrote %d confirmed links to %s", len(confirmed), args.output_confirmed)

    if args.output_candidates:
        write_links_csv(candidates, args.output_candidates)
        logger.info("Wrote %d candidate links to %s", len(candidates), args.output_candidates)


def parse_vni_gateway_state_from_run(text: str, device: str) -> Dict[str, Any]:
    """
    Parse one running-config text and extract VNI/VRF/VLAN gateway mapping state.

    Returns:
        Dictionary with:
        - records: List[Dict[str, str]]
        - vrf_to_l3vni: Dict[str, str]
        - nve_l2vnis: Set[str]
        - nve_l3vnis: Set[str]
    """
    lines = text.splitlines()

    vlan_to_vni: Dict[str, str] = {}
    vlan_to_name: Dict[str, str] = {}
    vrf_to_l3vni: Dict[str, str] = {}
    svi_info: Dict[str, Dict[str, str]] = {}
    nve_l2vnis: Set[str] = set()
    nve_l3vnis: Set[str] = set()

    # Parse VLAN -> vn-segment
    current_vlan: Optional[str] = None
    for line in lines:
        m_vlan = re.match(r"^vlan\s+(\d+)\s*$", line)
        if m_vlan:
            current_vlan = m_vlan.group(1)
            continue
        if line and not line.startswith(" "):
            current_vlan = None
            continue
        if current_vlan:
            m_name = re.match(r"^\s+name\s+(.+?)\s*$", line)
            if m_name:
                vlan_to_name[current_vlan] = m_name.group(1).strip()
                continue
            m_vni = re.match(r"^\s+vn-segment\s+(\d+)\s*$", line)
            if m_vni:
                vlan_to_vni[current_vlan] = m_vni.group(1)

    # Parse VRF -> l3vni
    current_vrf: Optional[str] = None
    for line in lines:
        m_vrf = re.match(r"^vrf context\s+(\S+)\s*$", line)
        if m_vrf:
            current_vrf = m_vrf.group(1)
            continue
        if line and not line.startswith(" "):
            current_vrf = None
            continue
        if current_vrf:
            m_l3vni = re.match(r"^\s+vni\s+(\d+)(?:\s+l3)?\s*$", line)
            if m_l3vni:
                vrf_to_l3vni[current_vrf] = m_l3vni.group(1)

    # Parse interface nve1 -> member vni / associate-vrf
    in_nve1 = False
    for line in lines:
        m_nve = re.match(r"^interface\s+(nve\d+)\s*$", line, re.IGNORECASE)
        if m_nve:
            in_nve1 = m_nve.group(1).lower() == "nve1"
            continue
        if line and not line.startswith(" "):
            in_nve1 = False
            continue
        if not in_nve1:
            continue

        m_nve_l3 = re.match(r"^\s+member vni\s+(\d+)\s+associate-vrf\s*$", line)
        if m_nve_l3:
            nve_l3vnis.add(m_nve_l3.group(1))
            continue

        m_nve_l2 = re.match(r"^\s+member vni\s+(\d+)\s*$", line)
        if m_nve_l2:
            nve_l2vnis.add(m_nve_l2.group(1))

    # Parse interface VlanX -> vrf/gateway
    current_svi: Optional[str] = None
    for line in lines:
        m_svi = re.match(r"^interface\s+Vlan(\d+)\s*$", line)
        if m_svi:
            current_svi = m_svi.group(1)
            svi_info.setdefault(current_svi, {"vrf": "", "gateway_ipv4": "", "gateway_ipv6": ""})
            continue
        if line and not line.startswith(" "):
            current_svi = None
            continue
        if current_svi:
            m_vrfm = re.match(r"^\s+vrf member\s+(\S+)\s*$", line)
            if m_vrfm:
                svi_info[current_svi]["vrf"] = m_vrfm.group(1)
                continue
            m_ip4 = re.match(r"^\s+ip address\s+(\S+)(?:\s+secondary)?\s*$", line)
            if m_ip4 and not svi_info[current_svi]["gateway_ipv4"] and "secondary" not in line:
                svi_info[current_svi]["gateway_ipv4"] = m_ip4.group(1)
                continue
            m_ip6 = re.match(r"^\s+ipv6 address\s+(\S+)\s*$", line)
            if m_ip6:
                ip6 = m_ip6.group(1)
                if ip6 != "use-link-local-only" and not svi_info[current_svi]["gateway_ipv6"]:
                    svi_info[current_svi]["gateway_ipv6"] = ip6

    records: List[Dict[str, str]] = []
    for vlan, info in svi_info.items():
        vrf = info.get("vrf", "")
        if not vrf or vrf == "management":
            continue
        l2vni = vlan_to_vni.get(vlan, "")
        if not l2vni:
            continue
        l3vni = vrf_to_l3vni.get(vrf, "")
        # Exclude L3 SVI (same as VRF L3VNI) from L2VNI mapping table.
        if l3vni and l2vni == l3vni:
            continue
        records.append({
            "l3vni": l3vni,
            "vrf": vrf,
            "l2vni": l2vni,
            "gateway_ipv4": info.get("gateway_ipv4", ""),
            "gateway_ipv6": info.get("gateway_ipv6", ""),
            "device": device,
            "vlan": vlan,
            "vlan_name": vlan_to_name.get(vlan, ""),
        })

    return {
        "records": records,
        "vrf_to_l3vni": vrf_to_l3vni,
        "nve_l2vnis": nve_l2vnis,
        "nve_l3vnis": nve_l3vnis,
    }


def parse_vni_gateway_records_from_run(text: str, device: str) -> List[Dict[str, str]]:
    """
    Parse one running-config text and extract VNI/VRF/VLAN gateway mappings.

    Returns:
        Records with keys:
        - l3vni, vrf, l2vni, gateway_ipv4, gateway_ipv6, device, vlan
    """
    state = parse_vni_gateway_state_from_run(text, device)
    return list(state.get("records", []))


def collect_vni_gateway_records_from_run_dir(raw_dir: str | Path, logger: Logger) -> List[Dict[str, str]]:
    """
    Collect VNI gateway records from running-config files under raw/config.
    """
    run_dir = get_run_input_dir(raw_dir)
    run_files = list_collect_output_files(run_dir, "run")
    logger.info("Found %d running-config files in %s", len(run_files), run_dir)

    records: List[Dict[str, str]] = []
    for f in run_files:
        device = get_collect_hostname_from_path(f, "run")
        text = load_run_text_from_collect_file(f)
        state = parse_vni_gateway_state_from_run(text, device)
        parsed = list(state.get("records", []))
        vrf_to_l3vni = dict(state.get("vrf_to_l3vni", {}))
        nve_l2vnis = set(state.get("nve_l2vnis", set()))
        nve_l3vnis = set(state.get("nve_l3vnis", set()))

        missing_l3 = sorted(vni for vni in vrf_to_l3vni.values() if vni and vni not in nve_l3vnis)
        extra_l3 = sorted(vni for vni in nve_l3vnis if vni not in set(vrf_to_l3vni.values()))
        missing_l2 = sorted(
            {r.get("l2vni", "") for r in parsed if r.get("l2vni", "") and r.get("l2vni", "") not in nve_l2vnis}
        )

        logger.info(
            "PARSED %s: %d records l3vni=%d nve-l3=%d nve-l2=%d",
            f.name,
            len(parsed),
            len(vrf_to_l3vni),
            len(nve_l3vnis),
            len(nve_l2vnis),
        )
        if missing_l3:
            logger.warning(
                "VNI MAP %s: vrf-context l3vni missing under interface nve1 associate-vrf: %s",
                device,
                ", ".join(missing_l3),
            )
        if extra_l3:
            logger.warning(
                "VNI MAP %s: interface nve1 associate-vrf vni missing under vrf context: %s",
                device,
                ", ".join(extra_l3),
            )
        if missing_l2:
            logger.warning(
                "VNI MAP %s: l2vni derived from vlan/svi missing under interface nve1: %s",
                device,
                ", ".join(missing_l2),
            )

        records.extend(parsed)

    return sort_vni_gateway_records(records)


def sort_vni_gateway_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def as_int(x: str) -> int:
        try:
            return int(x)
        except Exception:
            return 0

    return sorted(
        records,
        key=lambda r: (
            as_int(r.get("l3vni", "")),
            r.get("vrf", ""),
            as_int(r.get("l2vni", "")),
            r.get("device", ""),
            as_int(r.get("vlan", "")),
        ),
    )


def write_vni_gateway_csv(records: List[Dict[str, str]], path: str, include_vlan_name: bool = False) -> None:
    fields = ["l3vni", "vrf", "l2vni", "gateway_ipv4", "gateway_ipv6", "device", "vlan"]
    if include_vlan_name:
        fields.append("vlan_name")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in fields})


def render_vni_gateway_markdown_lines(
    records: List[Dict[str, str]],
    title: str,
    include_vlan_name: bool = False,
) -> List[str]:
    lines = [f"# {title}", ""]
    if include_vlan_name:
        lines.append("| l3vni | vrf | l2vni | gateway_ipv4 | gateway_ipv6 | device | vlan | vlan_name |")
        lines.append("|---|---|---|---|---|---|---|---|")
    else:
        lines.append("| l3vni | vrf | l2vni | gateway_ipv4 | gateway_ipv6 | device | vlan |")
        lines.append("|---|---|---|---|---|---|---|")
    for r in records:
        if include_vlan_name:
            lines.append(
                "| {l3vni} | {vrf} | {l2vni} | {gateway_ipv4} | {gateway_ipv6} | {device} | {vlan} | {vlan_name} |".format(
                    l3vni=r.get("l3vni", ""),
                    vrf=r.get("vrf", ""),
                    l2vni=r.get("l2vni", ""),
                    gateway_ipv4=r.get("gateway_ipv4", ""),
                    gateway_ipv6=r.get("gateway_ipv6", ""),
                    device=r.get("device", ""),
                    vlan=r.get("vlan", ""),
                    vlan_name=r.get("vlan_name", ""),
                )
            )
        else:
            lines.append(
                "| {l3vni} | {vrf} | {l2vni} | {gateway_ipv4} | {gateway_ipv6} | {device} | {vlan} |".format(
                    l3vni=r.get("l3vni", ""),
                    vrf=r.get("vrf", ""),
                    l2vni=r.get("l2vni", ""),
                    gateway_ipv4=r.get("gateway_ipv4", ""),
                    gateway_ipv6=r.get("gateway_ipv6", ""),
                    device=r.get("device", ""),
                    vlan=r.get("vlan", ""),
                )
            )
    return lines


def cmd_generate_vni_map(args: argparse.Namespace) -> None:
    """
    Parse collected running-config files and generate VNI/VRF/VLAN gateway mapping outputs.
    """
    logger = setup_logging(args.log_file, args.verbose)
    records = collect_vni_gateway_records_from_run_dir(args.input, logger)
    write_vni_gateway_csv(records, args.output_csv, include_vlan_name=args.include_vlan_name)
    write_text(
        args.output_md,
        render_vni_gateway_markdown_lines(records, args.title, include_vlan_name=args.include_vlan_name),
    )
    logger.info("Wrote %d records to %s and %s", len(records), args.output_csv, args.output_md)


VNI_GATEWAY_CSV_FIELDS = [
    "l3vni",
    "vrf",
    "l2vni",
    "gateway_ipv4",
    "gateway_ipv6",
    "device",
    "vlan",
    "vlan_name",
]


def normalize_vni_gateway_record(record: Dict[str, str]) -> Dict[str, str]:
    """
    Normalize one VNI gateway CSV record.
    """
    normalized: Dict[str, str] = {}
    for field in VNI_GATEWAY_CSV_FIELDS:
        normalized[field] = str(record.get(field, "") or "").strip()
    return normalized


def read_vni_gateway_csv(path: str) -> List[Dict[str, str]]:
    """
    Read VNI gateway CSV and normalize supported fields.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"vni gateway csv has no header: {path}")
        missing = [field for field in VNI_GATEWAY_CSV_FIELDS[:-1] if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"vni gateway csv missing headers: {', '.join(missing)}")
        return [normalize_vni_gateway_record(row) for row in reader]


def build_vni_entity_key(record: Dict[str, str]) -> tuple[str, str]:
    """
    Build unique entity key for one device-local SVI/VLAN definition.
    """
    return (
        record.get("device", ""),
        record.get("vlan", ""),
    )


def index_vni_gateway_records(records: List[Dict[str, str]], label: str) -> Dict[tuple[str, str], Dict[str, str]]:
    """
    Index VNI gateway records by device/vlan and reject duplicates.
    """
    indexed: Dict[tuple[str, str], Dict[str, str]] = {}
    for record in records:
        key = build_vni_entity_key(record)
        if not key[0] or not key[1]:
            raise ValueError(f"{label}: device/vlan is required for all rows")
        if key in indexed:
            raise ValueError(f"{label}: duplicate device/vlan row found for {key[0]} vlan {key[1]}")
        indexed[key] = record
    return indexed


def group_vni_records_by_device(records: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """
    Group VNI gateway records by device.
    """
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for record in records:
        grouped.setdefault(record.get("device", ""), []).append(record)
    return grouped


def sort_device_vni_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Sort device-local VNI records by vlan/l2vni/vrf for stable config generation.
    """
    def as_int(value: str) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    return sorted(
        records,
        key=lambda r: (
            as_int(r.get("vlan", "")),
            as_int(r.get("l2vni", "")),
            r.get("vrf", ""),
        ),
    )


def build_vni_add_render_context(
    records: List[Dict[str, str]],
    existing_before_records: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """
    Build Jinja2 render context for add config.
    """
    sorted_records = sort_device_vni_records(records)
    existing_before_records = existing_before_records or []
    existing_l3_keys = {
        (record.get("vrf", ""), record.get("l3vni", ""))
        for record in existing_before_records
        if record.get("vrf", "") and record.get("l3vni", "")
    }
    existing_l2vnis = {
        record.get("l2vni", "")
        for record in existing_before_records
        if record.get("l2vni", "")
    }
    emitted_l3: Set[tuple[str, str]] = set()
    emitted_l2: Set[str] = set()
    l3vnis: List[Dict[str, str]] = []
    evpn_l2vnis: List[str] = []
    nve_l3vnis: List[str] = []

    for record in sorted_records:
        vrf = record.get("vrf", "")
        l3vni = record.get("l3vni", "")
        key = (vrf, l3vni)
        if vrf and l3vni and key not in emitted_l3 and key not in existing_l3_keys:
            l3vnis.append({"vrf": vrf, "l3vni": l3vni})
            nve_l3vnis.append(l3vni)
            emitted_l3.add(key)

    for record in sorted_records:
        l2vni = record.get("l2vni", "")
        if l2vni and l2vni not in emitted_l2 and l2vni not in existing_l2vnis:
            evpn_l2vnis.append(l2vni)
            emitted_l2.add(l2vni)

    return {
        "l3vnis": l3vnis,
        "evpn_l2vnis": evpn_l2vnis,
        "vlans": sorted_records,
        "svis": sorted_records,
        "nve_members": [record.get("l2vni", "") for record in sorted_records if record.get("l2vni", "")],
        "nve_l3vnis": nve_l3vnis,
    }


def render_vni_add_config_lines(
    records: List[Dict[str, str]],
    existing_before_records: List[Dict[str, str]] | None = None,
) -> List[str]:
    """
    Render NX-OS add config lines for VNI gateway records.
    """
    return render_named_template_lines(
        "vni_add_config.j2",
        build_vni_add_render_context(records, existing_before_records=existing_before_records),
    )


def build_vni_delete_render_context(
    records_to_delete: List[Dict[str, str]],
    remaining_after_records: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Build Jinja2 render context for delete config.
    """
    sorted_delete_records = sort_device_vni_records(records_to_delete)
    remaining_l3 = {(r.get("vrf", ""), r.get("l3vni", "")) for r in remaining_after_records}
    remaining_l2 = {r.get("l2vni", "") for r in remaining_after_records if r.get("l2vni", "")}
    removed_l3_done: Set[tuple[str, str]] = set()
    removed_l2_done: Set[str] = set()
    l3vnis: List[Dict[str, str]] = []
    evpn_l2vnis: List[str] = []

    for record in sorted_delete_records:
        l2vni = record.get("l2vni", "")
        if l2vni and l2vni not in remaining_l2 and l2vni not in removed_l2_done:
            evpn_l2vnis.append(l2vni)
            removed_l2_done.add(l2vni)

    for record in sorted_delete_records:
        l3_key = (record.get("vrf", ""), record.get("l3vni", ""))
        if l3_key[0] and l3_key[1] and l3_key not in remaining_l3 and l3_key not in removed_l3_done:
            l3vnis.append({"vrf": l3_key[0], "l3vni": l3_key[1]})
            removed_l3_done.add(l3_key)

    return {
        "nve_members": [record.get("l2vni", "") for record in sorted_delete_records if record.get("l2vni", "")],
        "evpn_l2vnis": evpn_l2vnis,
        "vlans": [record.get("vlan", "") for record in sorted_delete_records if record.get("vlan", "")],
        "l3vnis": l3vnis,
    }


def render_vni_delete_config_lines(
    records_to_delete: List[Dict[str, str]],
    remaining_after_records: List[Dict[str, str]],
) -> List[str]:
    """
    Render NX-OS delete config lines for VNI gateway records.
    """
    return render_named_template_lines(
        "vni_delete_config.j2",
        build_vni_delete_render_context(records_to_delete, remaining_after_records),
    )


def build_vni_diff(
    before_records: List[Dict[str, str]],
    after_records: List[Dict[str, str]],
) -> tuple[List[Dict[str, str]], List[Dict[str, str]], List[tuple[Dict[str, str], Dict[str, str]]]]:
    """
    Build add/delete/change sets from before/after VNI records.
    """
    before_index = index_vni_gateway_records(before_records, "before-vni-csv")
    after_index = index_vni_gateway_records(after_records, "vni-gateway-map")

    adds: List[Dict[str, str]] = []
    deletes: List[Dict[str, str]] = []
    changes: List[tuple[Dict[str, str], Dict[str, str]]] = []

    all_keys = sorted(set(before_index) | set(after_index))
    for key in all_keys:
        before_record = before_index.get(key)
        after_record = after_index.get(key)
        if before_record is None and after_record is not None:
            adds.append(after_record)
        elif after_record is None and before_record is not None:
            deletes.append(before_record)
        elif before_record is not None and after_record is not None and before_record != after_record:
            changes.append((before_record, after_record))

    return adds, deletes, changes


def build_vni_diff_record_sets(
    before_records: List[Dict[str, str]],
    after_records: List[Dict[str, str]],
) -> tuple[List[Dict[str, str]], List[Dict[str, str]], List[tuple[Dict[str, str], Dict[str, str]]], List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Build raw diff plus effective add/delete record sets.

    Changes are expanded into delete(old) + add(new) for output files.
    """
    adds, deletes, changes = build_vni_diff(before_records, after_records)
    delete_records = deletes + [before for before, _after in changes]
    add_records = adds + [after for _before, after in changes]
    return adds, deletes, changes, add_records, delete_records


def build_prefixed_output_path(path: str, output_dir: str, prefix: str) -> str:
    """
    Build output file path with prefixed filename under the target output directory.
    """
    p = Path(path)
    return str(Path(output_dir) / f"{prefix}{p.name}")


def write_vni_diff_csv_outputs(
    target_csv_path: str,
    output_dir: str,
    add_records: List[Dict[str, str]],
    delete_records: List[Dict[str, str]],
    logger: Logger,
) -> None:
    """
    Write add/delete CSV outputs under the configured output directory.
    """
    add_path = build_prefixed_output_path(target_csv_path, output_dir, "add_")
    del_path = build_prefixed_output_path(target_csv_path, output_dir, "del_")
    write_vni_gateway_csv(sort_vni_gateway_records(add_records), add_path, include_vlan_name=True)
    write_vni_gateway_csv(sort_vni_gateway_records(delete_records), del_path, include_vlan_name=True)
    logger.info(
        "WROTE VNI DIFF CSV add=%s (%d records) delete=%s (%d records)",
        add_path,
        len(add_records),
        del_path,
        len(delete_records),
    )


def write_vni_config_outputs(
    output_dir: str,
    merged_output: str,
    before_records: List[Dict[str, str]],
    after_records: List[Dict[str, str]],
    logger: Logger,
) -> None:
    """
    Write per-device and merged VNI config outputs.
    """
    adds, deletes, changes, add_records, delete_records = build_vni_diff_record_sets(before_records, after_records)

    after_by_device = group_vni_records_by_device(after_records)
    before_by_device = group_vni_records_by_device(before_records)
    delete_by_device = group_vni_records_by_device(delete_records)
    add_by_device = group_vni_records_by_device(add_records)
    devices = sorted(set(delete_by_device) | set(add_by_device))

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    merged_sections: List[str] = []

    for device in devices:
        device_lines: List[str] = ["conf t", "!"]
        delete_lines = render_vni_delete_config_lines(
            delete_by_device.get(device, []),
            after_by_device.get(device, []),
        )
        add_lines = render_vni_add_config_lines(
            add_by_device.get(device, []),
            existing_before_records=before_by_device.get(device, []),
        )
        body_lines = [line for line in delete_lines + add_lines if line is not None]
        while body_lines and body_lines[-1] == "!":
            body_lines.pop()
        if body_lines:
            device_lines.extend(body_lines)
            device_lines.extend(["end", ""])
            device_path = outdir / f"{device}.txt"
            device_path.write_text("\n".join(device_lines), encoding="utf-8")
            logger.info(
                "WROTE VNI CONFIG %s add=%d delete=%d change=%d",
                device_path,
                len(add_by_device.get(device, [])),
                len(delete_by_device.get(device, [])),
                len([1 for before, _after in changes if before.get('device', '') == device]),
            )
            merged_sections.append(f"### DEVICE: {device}\n" + "\n".join(device_lines).rstrip())

    merged_path = Path(merged_output)
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    if merged_sections:
        merged_path.write_text("\n\n".join(merged_sections).rstrip() + "\n", encoding="utf-8")
    else:
        merged_path.write_text("### NO_DIFF\nNo config changes generated.\n", encoding="utf-8")
    logger.info(
        "WROTE MERGED VNI CONFIG %s devices=%d add=%d delete=%d change=%d",
        merged_path,
        len(devices),
        len(adds),
        len(deletes),
        len(changes),
    )


def write_vni_config_outputs_from_record_sets(
    output_dir: str,
    merged_output: str,
    add_records: List[Dict[str, str]],
    delete_records: List[Dict[str, str]],
    existing_before_records: List[Dict[str, str]],
    remaining_after_records: List[Dict[str, str]],
    logger: Logger,
) -> None:
    """
    Write per-device and merged VNI config outputs from explicit add/delete record sets.
    """
    after_by_device = group_vni_records_by_device(remaining_after_records)
    before_by_device = group_vni_records_by_device(existing_before_records)
    delete_by_device = group_vni_records_by_device(delete_records)
    add_by_device = group_vni_records_by_device(add_records)
    devices = sorted(set(delete_by_device) | set(add_by_device))

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    merged_sections: List[str] = []

    for device in devices:
        device_lines: List[str] = ["conf t", "!"]
        delete_lines = render_vni_delete_config_lines(
            delete_by_device.get(device, []),
            after_by_device.get(device, []),
        )
        add_lines = render_vni_add_config_lines(
            add_by_device.get(device, []),
            existing_before_records=before_by_device.get(device, []),
        )
        body_lines = [line for line in delete_lines + add_lines if line is not None]
        while body_lines and body_lines[-1] == "!":
            body_lines.pop()
        if body_lines:
            device_lines.extend(body_lines)
            device_lines.extend(["end", ""])
            device_path = outdir / f"{device}.txt"
            device_path.write_text("\n".join(device_lines), encoding="utf-8")
            logger.info(
                "WROTE VNI CONFIG %s add=%d delete=%d",
                device_path,
                len(add_by_device.get(device, [])),
                len(delete_by_device.get(device, [])),
            )
            merged_sections.append(f"### DEVICE: {device}\n" + "\n".join(device_lines).rstrip())

    merged_path = Path(merged_output)
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    if merged_sections:
        merged_path.write_text("\n\n".join(merged_sections).rstrip() + "\n", encoding="utf-8")
    else:
        merged_path.write_text("### NO_DIFF\nNo config changes generated.\n", encoding="utf-8")
    logger.info(
        "WROTE MERGED VNI CONFIG %s devices=%d add=%d delete=%d",
        merged_path,
        len(devices),
        len(add_records),
        len(delete_records),
    )


def run_collect_run_config_from_args(args: argparse.Namespace) -> None:
    """
    Run collect-run-config flow using current generate-vni-config arguments.
    """
    collect_args = argparse.Namespace(
        command="collect-run-config",
        hosts=args.hosts,
        policy=args.policy,
        roles=None,
        username=args.username,
        password=args.password,
        enable_secret=args.enable_secret,
        transport=args.transport,
        target_hosts=args.target_hosts,
        output=args.collect_output,
        before_show_run_dir=None,
        workers=args.workers,
        show_commands_file=None,
        show_hosts=None,
        show_read_timeout=120,
        show_only=False,
        run_config_only=True,
        show_run_diff=False,
        show_run_diff_comands=False,
        log_file=args.collect_log_file,
        verbose=args.verbose,
    )
    cmd_collect(collect_args)


def cmd_generate_vni_config(args: argparse.Namespace) -> None:
    """
    Generate NX-OS VNI config from target CSV and optional before-state CSV.
    """
    logger = setup_logging(args.log_file, args.verbose)
    if not args.vni_gateway_map and not args.vni_gateway_map_add and not args.vni_gateway_map_del:
        raise ValueError(
            "One of --vni-gateway-map, --vni-gateway-map-add, or --vni-gateway-map-del is required"
        )

    if args.vni_gateway_map and (args.vni_gateway_map_add or args.vni_gateway_map_del):
        raise ValueError(
            "--vni-gateway-map cannot be used together with --vni-gateway-map-add/--vni-gateway-map-del"
        )

    if args.vni_gateway_map_add or args.vni_gateway_map_del:
        add_records = (
            sort_vni_gateway_records(read_vni_gateway_csv(args.vni_gateway_map_add))
            if args.vni_gateway_map_add
            else []
        )
        delete_records = (
            sort_vni_gateway_records(read_vni_gateway_csv(args.vni_gateway_map_del))
            if args.vni_gateway_map_del
            else []
        )
        logger.info(
            "Loaded direct VNI config inputs add=%s (%d records) delete=%s (%d records)",
            args.vni_gateway_map_add or "(none)",
            len(add_records),
            args.vni_gateway_map_del or "(none)",
            len(delete_records),
        )
        write_vni_config_outputs_from_record_sets(
            output_dir=args.output_dir,
            merged_output=args.output_merged,
            add_records=add_records,
            delete_records=delete_records,
            existing_before_records=[],
            remaining_after_records=[],
            logger=logger,
        )
        write_vni_config_outputs_from_record_sets(
            output_dir=args.output_rollback_dir,
            merged_output=args.output_rollback_merged,
            add_records=delete_records,
            delete_records=add_records,
            existing_before_records=[],
            remaining_after_records=[],
            logger=logger,
        )
        return

    target_records = sort_vni_gateway_records(read_vni_gateway_csv(args.vni_gateway_map))

    before_records: List[Dict[str, str]] = []
    before_csv_path = args.before_vni_csv

    if before_csv_path:
        before_records = sort_vni_gateway_records(read_vni_gateway_csv(before_csv_path))
        logger.info("Loaded before VNI CSV %s records=%d", before_csv_path, len(before_records))
    elif args.disable_auto_collect:
        logger.info("Auto collect disabled and no before VNI CSV provided: generating add-only config")
    else:
        logger.info("No before VNI CSV provided: running collect-run-config and generating before CSV")
        run_collect_run_config_from_args(args)
        before_records = collect_vni_gateway_records_from_run_dir(args.collect_output, logger)
        write_vni_gateway_csv(
            before_records,
            args.generated_before_vni_csv,
            include_vlan_name=True,
        )
        logger.info("Wrote generated before VNI CSV %s records=%d", args.generated_before_vni_csv, len(before_records))

    if not before_csv_path and args.disable_auto_collect:
        _adds, _deletes, _changes, add_records, delete_records = build_vni_diff_record_sets([], target_records)
        write_vni_diff_csv_outputs(args.vni_gateway_map, args.output_csv_dir, add_records, delete_records, logger)
        write_vni_config_outputs(
            output_dir=args.output_dir,
            merged_output=args.output_merged,
            before_records=[],
            after_records=target_records,
            logger=logger,
        )
        write_vni_config_outputs(
            output_dir=args.output_rollback_dir,
            merged_output=args.output_rollback_merged,
            before_records=target_records,
            after_records=[],
            logger=logger,
        )
        return

    _adds, _deletes, _changes, add_records, delete_records = build_vni_diff_record_sets(before_records, target_records)
    write_vni_diff_csv_outputs(args.vni_gateway_map, args.output_csv_dir, add_records, delete_records, logger)
    write_vni_config_outputs(
        output_dir=args.output_dir,
        merged_output=args.output_merged,
        before_records=before_records,
        after_records=target_records,
        logger=logger,
    )
    write_vni_config_outputs(
        output_dir=args.output_rollback_dir,
        merged_output=args.output_rollback_merged,
        before_records=target_records,
        after_records=before_records,
        logger=logger,
    )


def cmd_generate_clab(args: argparse.Namespace) -> None:
    """
    Generate containerlab topology YAML.

    Args:
        args: Parsed CLI args.
    """
    args = apply_generate_clab_auto_files(args)
    logger = setup_logging(args.log_file, args.verbose)

    records = read_links_csv(args.input)
    mappings = load_mappings(args.mappings)
    roles = load_roles(args.roles)

    inventory_map: Dict[str, Dict[str, Any]] = {}
    hosts_path = resolve_generate_clab_hosts_path(args.hosts)
    if hosts_path:
        inventory_data = load_yaml(hosts_path)
        inventory_map = load_inventory_map_from_list(load_inventory_data(inventory_data))

    mgmt_ip_map = build_node_mgmt_ip_map(
        inventory_map=inventory_map,
        mappings=mappings,
        logger=logger,
    )

    rendered_links, skipped_by_confidence = prepare_rendered_links(
        records=records,
        mappings=mappings,
        roles=roles,
        min_confidence=args.min_confidence,
        logger=logger,
        log_skips=True,
        inventory_map=inventory_map,
        clab_mode=True,
    )

    nodes = {}
    if args.include_nodes:
        nodes = build_node_definitions_from_links(
            rendered_links=rendered_links,
            inventory_map=inventory_map,
            mappings=mappings,
            mgmt_ip_map=mgmt_ip_map,
            roles=roles,
            include_group=args.group_by_role,
        )

    topology_data = build_clab_topology_data(
        rendered_links=rendered_links,
        nodes=nodes,
        include_nodes=args.include_nodes,
    )
    linux_csv_nodes = apply_linux_csv_overlay(topology_data, args.linux_csv, logger)
    kind_cluster_csv_nodes = apply_kind_cluster_csv_overlay(topology_data, args.kind_cluster_csv, logger)
    generate_kind_cluster_config_files(args.kind_cluster_csv, logger)
    generate_kind_cluster_support_script(args.kind_cluster_csv or args.linux_csv, logger)
    generated_links = deepcopy(topology_data["topology"].get("links", []))
    generated_node_names = set(nodes.keys()) | linux_csv_nodes | kind_cluster_csv_nodes
    topology_data = apply_clab_merge_file(topology_data, args.clab_merge, logger, "clab-merge")
    topology_data = apply_clab_merge_file(topology_data, args.clab_lab_profile, logger, "clab-lab-profile")
    topology_data["name"] = args.name
    topology_data = apply_cisco_n9kv_kind_defaults(topology_data, get_raw_dir("raw"), logger)
    topology_data = finalize_clab_topology_data(topology_data, generated_links, generated_node_names, roles)
    write_text(args.output, render_clab_yaml_lines(topology_data, generated_node_names, roles))

    logger.info("Skipped %d links by min-confidence=%s", skipped_by_confidence, args.min_confidence)
    logger.info("Wrote %d links to %s", len(rendered_links), args.output)
    if args.include_nodes:
        logger.info("Generated %d nodes", len(nodes))
        if args.group_by_role:
            logger.info("Added node groups from role detection")


def cmd_generate_mermaid(args: argparse.Namespace) -> None:
    """
    Generate Mermaid Markdown.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    context = prepare_topology_diagram_context(args, logger)

    md_lines = render_mermaid_markdown_lines(
        rendered_links=context["rendered_links"],
        roles=context["roles"],
        normalized_inventory_map=context["normalized_inventory_map"],
        normalized_mgmt_ip_map=context["normalized_mgmt_ip_map"],
        detect_node_role_func=detect_node_role,
        get_role_priority_func=get_role_priority,
        is_network_device_type_func=is_network_device_type,
        direction=args.direction,
        group_by_role=args.group_by_role,
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
    )
    write_text(context["output_path"], md_lines)

    logger.info("Skipped %d confirmed links by min-confidence=%s", context["skipped_by_confidence"], args.min_confidence)
    logger.info("Rendered %d confirmed links", len(context["rendered_links"]))
    logger.info("Rendered %d candidate links", len(context["rendered_candidate_links"]))
    logger.info("Wrote Mermaid markdown to %s", context["output_path"])


def cmd_generate_graphviz(args: argparse.Namespace) -> None:
    """
    Generate Graphviz DOT.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)
    context = prepare_topology_diagram_context(args, logger)

    dot_lines = render_graphviz_dot_lines(
        rendered_links=context["rendered_links"],
        roles=context["roles"],
        normalized_inventory_map=context["normalized_inventory_map"],
        normalized_mgmt_ip_map=context["normalized_mgmt_ip_map"],
        detect_node_role_func=detect_node_role,
        get_role_priority_func=get_role_priority,
        is_network_device_type_func=is_network_device_type,
        direction=args.direction,
        group_by_role=args.group_by_role,
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
    )
    write_text(context["output_path"], dot_lines)

    logger.info("Skipped %d confirmed links by min-confidence=%s", context["skipped_by_confidence"], args.min_confidence)
    logger.info("Rendered %d confirmed links", len(context["rendered_links"]))
    logger.info("Rendered %d candidate links", len(context["rendered_candidate_links"]))
    logger.info("Wrote Graphviz DOT to %s", context["output_path"])


def cmd_generate_drawio(args: argparse.Namespace) -> None:
    """
    Generate draw.io XML.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)

    default_topology_dir = get_topology_dir("output")
    default_output_path = f"{default_topology_dir}/{DEFAULT_TOPOLOGY_DRAWIO_FILENAME}"
    default_all_output_path = f"{default_topology_dir}/{DEFAULT_TOPOLOGY_DRAWIO_ALL_FILENAME}"

    if getattr(args, "all_graph", False):
        output_path = args.output
        if output_path == default_output_path:
            output_path = default_all_output_path

        page_variants = [
            ("Topology TD", "TD", False),
            ("Topology LR", "LR", False),
            ("Topology BT", "BT", False),
            ("Topology RL", "RL", False),
            ("Underlay TD", "TD", True),
            ("Underlay LR", "LR", True),
            ("Underlay BT", "BT", True),
            ("Underlay RL", "RL", True),
        ]
        diagrams: List[ET.Element] = []
        mxfile_attrs: Dict[str, str] | None = None
        for page_name, direction, underlay in page_variants:
            diagram, page_mxfile_attrs = build_drawio_page_diagram(
                args=args,
                logger=logger,
                direction=direction,
                underlay=underlay,
                page_name=page_name,
            )
            diagrams.append(diagram)
            if mxfile_attrs is None:
                mxfile_attrs = page_mxfile_attrs

        write_text(output_path, build_drawio_multipage_lines(diagrams, mxfile_attrs or {}))
        logger.info("Wrote draw.io multi-page XML to %s", output_path)
        logger.info("Rendered %d draw.io pages", len(diagrams))
        return

    context = prepare_topology_diagram_context(args, logger)

    drawio_lines = render_drawio_xml_lines(
        rendered_links=context["rendered_links"],
        roles=context["roles"],
        normalized_inventory_map=context["normalized_inventory_map"],
        normalized_mgmt_ip_map=context["normalized_mgmt_ip_map"],
        detect_node_role_func=detect_node_role,
        get_role_priority_func=get_role_priority,
        is_network_device_type_func=is_network_device_type,
        direction=args.direction,
        group_by_role=args.group_by_role,
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        node_interface_label_map=context["node_interface_label_map"],
    )
    write_text(context["output_path"], drawio_lines)

    logger.info("Skipped %d confirmed links by min-confidence=%s", context["skipped_by_confidence"], args.min_confidence)
    logger.info("Rendered %d confirmed links", len(context["rendered_links"]))
    logger.info("Rendered %d candidate links", len(context["rendered_candidate_links"]))
    logger.info("Wrote draw.io XML to %s", context["output_path"])


def cmd_generate_doc(args: argparse.Namespace) -> None:
    """
    Generate both containerlab YAML and Mermaid Markdown.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)

    records = read_links_csv(args.input)
    mappings = load_mappings(args.mappings)
    roles = load_roles(args.roles)

    inventory_map: Dict[str, Dict[str, Any]] = {}
    hosts_path = resolve_hosts_path(args.hosts, required=False)
    if hosts_path:
        inventory_data = load_yaml(hosts_path)
        inventory_map = load_inventory_map_from_list(load_inventory_data(inventory_data))

    candidate_records: List[Dict[str, str]] = []
    if args.input_candidates:
        candidate_records = read_links_csv(args.input_candidates)

    mgmt_ip_map = build_node_mgmt_ip_map(
        inventory_map=inventory_map,
        mappings=mappings,
        logger=logger,
    )

    rendered_links, skipped_by_confidence = prepare_rendered_links(
        records=records,
        mappings=mappings,
        roles=roles,
        min_confidence=args.min_confidence,
        logger=logger,
        log_skips=True,
        inventory_map=inventory_map,
        clab_mode=True,
    )

    nodes = {}
    if args.include_nodes:
        nodes = build_node_definitions_from_links(
            rendered_links=rendered_links,
            inventory_map=inventory_map,
            mappings=mappings,
            mgmt_ip_map=mgmt_ip_map,
            roles=roles,
            include_group=args.group_by_role,
        )

    topology_data = build_clab_topology_data(
        rendered_links=rendered_links,
        nodes=nodes,
        include_nodes=args.include_nodes,
    )
    generated_links = deepcopy(topology_data["topology"].get("links", []))
    generated_node_names = set(nodes.keys())
    topology_data = apply_clab_merge_file(topology_data, args.clab_merge, logger, "clab-merge")
    topology_data = apply_clab_merge_file(topology_data, args.clab_lab_profile, logger, "clab-lab-profile")
    topology_data = apply_cisco_n9kv_kind_defaults(topology_data, get_raw_dir("raw"), logger)
    topology_data = finalize_clab_topology_data(topology_data, generated_links, generated_node_names, roles)
    write_text(args.output_clab, render_clab_yaml_lines(topology_data, generated_node_names, roles))

    rendered_candidate_links: List[Dict[str, Any]] = []
    if candidate_records:
        rendered_candidate_links = prepare_rendered_candidate_links(
            records=candidate_records,
            mappings=mappings,
            roles=roles,
            logger=logger,
        )

    normalized_inventory_map, normalized_mgmt_ip_map = build_normalized_inventory_and_mgmt_maps(
        inventory_map=inventory_map,
        mgmt_ip_map=mgmt_ip_map,
        mappings=mappings,
    )

    node_address_map: Optional[Dict[str, str]] = None
    node_address_label_map: Optional[Dict[str, str]] = None
    node_address_lines_map: Optional[Dict[str, List[str]]] = None
    link_label_map: Optional[Dict[str, str]] = None
    output_md_path = args.output_md
    title = args.title
    if args.underlay:
        underlay_cfg = load_underlay_render_config(args.underlay_config)
        target_roles = set(underlay_cfg.get("target_roles", []))
        rendered_links = filter_links_by_target_roles(rendered_links, roles, target_roles)
        if rendered_candidate_links:
            rendered_candidate_links = filter_links_by_target_roles(rendered_candidate_links, roles, target_roles)
        underlay_ip_maps: Dict[str, Dict[str, str]] = {}
        underlay_secondary_ip_maps: Dict[str, Dict[str, List[str]]] = {}
        for spec in underlay_cfg.get("interfaces", []):
            if not isinstance(spec, dict):
                continue
            iface = str(spec.get("name", "loopback0"))
            vrf = str(spec.get("vrf", underlay_cfg.get("vrf", "default")))
            primary_map, secondary_map = build_underlay_loopback_maps(
                raw_dir=args.underlay_raw,
                mappings=mappings,
                interface_name=iface,
                vrf=vrf,
            )
            underlay_ip_maps[iface.lower()] = primary_map
            underlay_secondary_ip_maps[iface.lower()] = secondary_map
        node_address_map, node_address_label_map, node_address_lines_map = build_mermaid_address_maps(
            normalized_inventory_map=normalized_inventory_map,
            normalized_mgmt_ip_map=normalized_mgmt_ip_map,
            roles=roles,
            underlay_config=underlay_cfg,
            underlay_ip_maps=underlay_ip_maps,
            underlay_secondary_ip_maps=underlay_secondary_ip_maps,
        )
        underlay_if_ip_map = build_underlay_interface_ip_maps(
            raw_dir=args.underlay_raw,
            mappings=mappings,
            vrf=str(underlay_cfg.get("vrf", "default")),
        )
        link_label_map = build_underlay_link_label_map(
            rendered_links=rendered_links,
            node_if_ip_map=underlay_if_ip_map,
        )
        output_md_path = add_underlay_suffix_to_path(output_md_path)
        title = f"{title} (UNDERLAY)"
        logger.info(
            "Underlay render enabled: roles=%s vrf=%s interface=%s label=%s raw=%s",
            ",".join(underlay_cfg.get("target_roles", [])),
            underlay_cfg.get("vrf", "default"),
            ",".join([str(x.get("name", "")) for x in underlay_cfg.get("interfaces", []) if isinstance(x, dict)]),
            ",".join([str(x.get("label", "")) for x in underlay_cfg.get("interfaces", []) if isinstance(x, dict)]),
            args.underlay_raw,
        )

    md_lines = render_mermaid_markdown_lines(
        rendered_links=rendered_links,
        roles=roles,
        normalized_inventory_map=normalized_inventory_map,
        normalized_mgmt_ip_map=normalized_mgmt_ip_map,
        detect_node_role_func=detect_node_role,
        get_role_priority_func=get_role_priority,
        is_network_device_type_func=is_network_device_type,
        direction=args.direction,
        group_by_role=args.group_by_role,
        add_comments=args.add_comments,
        title=title,
        candidate_links=rendered_candidate_links,
        node_address_map=node_address_map,
        node_address_label_map=node_address_label_map,
        node_address_lines_map=node_address_lines_map,
        link_label_map=link_label_map,
    )
    write_text(output_md_path, md_lines)

    logger.info("Skipped %d links by min-confidence=%s", skipped_by_confidence, args.min_confidence)
    logger.info("Wrote %d confirmed links to %s", len(rendered_links), args.output_clab)
    logger.info("Wrote %d candidate links into Mermaid", len(rendered_candidate_links))
    logger.info("Wrote Mermaid markdown to %s", output_md_path)
    if args.include_nodes:
        logger.info("Generated %d nodes", len(nodes))


def cmd_generate_tf(args: argparse.Namespace) -> None:
    """
    Generate Terraform main.tf from hosts inventory.

    Args:
        args: Parsed CLI args.
    """
    logger = setup_logging(args.log_file, args.verbose)

    hosts_path = resolve_hosts_path(args.hosts, required=True)
    inventory_data = load_yaml(hosts_path)
    inventory_map = load_inventory_map_from_list(load_inventory_data(inventory_data))
    roles = load_roles(args.roles)

    lines = build_terraform_provider_lines(
        inventory_map=inventory_map,
        roles=roles,
        detect_node_role_func=detect_node_role,
        provider_version=getattr(args, "provider_version", None),
    )
    write_text(args.output, lines)

    logger.info("Generated Terraform file %s", args.output)


def markdown_table_escape(value: str) -> str:
    """
    Escape CSV cell text for Markdown table output.
    """
    return value.replace("|", r"\|").replace("\n", "<br/>")


def render_csv_as_markdown_table(rows: List[List[str]]) -> List[str]:
    """
    Render CSV rows as a Markdown table.
    """
    if not rows:
        return []

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = [markdown_table_escape(cell) for cell in normalized_rows[0]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(markdown_table_escape(cell) for cell in row) + " |")
    return lines


def cmd_csv_to_md(args: argparse.Namespace) -> None:
    """
    Convert a CSV file into a Markdown table file.
    """
    logger = setup_logging(args.log_file, args.verbose)
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    output_path = Path(args.output_file) if args.output_file else csv_path.with_suffix(".md")
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"CSV file is empty: {csv_path}")

    write_text(output_path, render_csv_as_markdown_table(rows))
    logger.info("Converted %s to %s", csv_path, output_path)


def apply_generate_clab_auto_files(args: argparse.Namespace) -> argparse.Namespace:
    """
    Fill generate-clab optional file arguments from cwd when they are unset.
    """
    for arg_name, filename in DEFAULT_CLAB_SET_GENERATE_CLAB_AUTO_FILES.items():
        if getattr(args, arg_name, None):
            continue
        candidate = Path(filename)
        if candidate.exists():
            setattr(args, arg_name, filename)
    return args


def build_clab_set_step_args(
    step: Dict[str, Any],
    args: argparse.Namespace,
    verbose: bool,
) -> argparse.Namespace:
    """
    Build effective argparse namespace for one clab-set-cmds step.
    """
    data = deepcopy(step.get("args", {}))
    handler_command = str(step.get("command", data.get("command", "")))
    subcommand = str(data.get("command", handler_command))
    data["command"] = subcommand
    data["verbose"] = verbose

    # Common overrides from clab-set-cmds CLI.
    common_optional_overrides = {
        "hosts": getattr(args, "hosts", None),
        "policy": getattr(args, "policy", None),
        "username": getattr(args, "username", None),
        "password": getattr(args, "password", None),
        "enable_secret": getattr(args, "enable_secret", None),
        "transport": getattr(args, "transport", None),
        "target_hosts": getattr(args, "target_hosts", None),
        "workers": getattr(args, "workers", None),
        "mappings": getattr(args, "mappings", None),
        "description_rules": getattr(args, "description_rules", None),
        "roles": getattr(args, "roles", None),
        "linux_csv": getattr(args, "linux_csv", None),
        "kind_cluster_csv": getattr(args, "kind_cluster_csv", None),
        "clab_env": getattr(args, "clab_env", None),
        "clab_merge": getattr(args, "clab_merge", None),
        "clab_lab_profile": getattr(args, "clab_lab_profile", None),
        "include_svi": getattr(args, "include_svi", None),
    }
    for key, value in common_optional_overrides.items():
        if value is not None:
            data[key] = value

    raw_output = getattr(args, "output", None)
    if raw_output is not None:
        if handler_command == "collect":
            data["output"] = raw_output
        elif handler_command == "clab-transform-config":
            data["input"] = raw_output
            data["output_dir"] = f"{raw_output}/labconfig"
        elif handler_command in {"normalize-links", "generate-vni-map"}:
            data["input"] = raw_output
        if "underlay_raw" in data:
            data["underlay_raw"] = raw_output

    step_args = argparse.Namespace(**data)
    if handler_command == "generate-clab":
        return apply_generate_clab_auto_files(step_args)
    return step_args


def cmd_clab_set_cmds(args: argparse.Namespace) -> None:
    """
    Run the predefined collect/normalize/render pipeline for containerlab workflows.
    """
    step_handlers = {
        "collect": cmd_collect,
        "clab-transform-config": cmd_transform_config,
        "normalize-links": cmd_normalize_links,
        "generate-clab": cmd_generate_clab,
        "generate-mermaid": cmd_generate_mermaid,
        "generate-drawio": cmd_generate_drawio,
        "generate-vni-map": cmd_generate_vni_map,
    }

    verbose = bool(getattr(args, "verbose", False))
    for index, step in enumerate(DEFAULT_CLAB_SET_CMDS, start=1):
        name = str(step.get("name", f"step-{index}"))
        command = str(step.get("command", ""))
        if getattr(args, "without_collect", False) and command == "collect":
            print(f"[{index}/{len(DEFAULT_CLAB_SET_CMDS)}] {name} ({command}) [skip: --without-collect]")
            continue
        handler = step_handlers.get(command)
        if handler is None:
            raise ValueError(f"Unsupported clab-set-cmds step command: {command}")

        step_args = build_clab_set_step_args(step, args, verbose)
        print(f"[{index}/{len(DEFAULT_CLAB_SET_CMDS)}] {name} ({command})")
        handler(step_args)


def build_parser() -> argparse.ArgumentParser:
    """
    Build CLI parser.

    Returns:
        Configured parser.
    """
    default_log_dir = get_default_log_dir()
    default_output_dir = get_output_dir()
    default_raw_dir = get_raw_dir(default_output_dir)
    default_links_dir = get_links_dir("output")
    default_topology_dir = get_topology_dir("output")

    parser = argparse.ArgumentParser(
        description = "Collect LLDP and running-config, normalize links, generate containerlab, Mermaid, Terraform, and VNI outputs, and push config to devices"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_prepare = subparsers.add_parser("prepare-hosts", help="Generate Ansible-style hosts.yaml from hosts.txt")
    p_prepare.add_argument("--input", required=True, help="Input hosts.txt")
    p_prepare.add_argument("--output", required=True, help="Output hosts.yaml")
    p_prepare.add_argument("--log-file", default=f"{default_log_dir}/prepare-hosts.log", help="Log file path")
    p_prepare.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_prepare.set_defaults(func=cmd_prepare_hosts)

    p_transform = subparsers.add_parser(
        "clab-transform-config",
        help="Transform hosts.yaml and NX-OS running-config files for containerlab / NX-OS 9000v lab use",
    )
    p_transform.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_transform.add_argument(
        "--clab-env",
        help="containerlab env YAML used to read mgmt.ipv4-subnet (default: ./clab_merge.yaml if exists)",
    )
    p_transform.add_argument(
        "--input",
        default=default_raw_dir,
        help="Raw root directory for source running-config files (reads <input>/config when present)",
    )
    p_transform.add_argument(
        "--output-hosts",
        default="hosts.lab.yaml",
        help="Output transformed hosts inventory",
    )
    p_transform.add_argument(
        "--output-dir",
        default=f"{default_raw_dir}/labconfig",
        help="Output directory for transformed running-config files",
    )
    p_transform.add_argument(
        "--log-file",
        default=f"{default_log_dir}/clab-transform-config.log",
        help="Log file path",
    )
    p_transform.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_transform.set_defaults(func=cmd_transform_config)

    p_sample = subparsers.add_parser(
        "generate-sample-config",
        help="Generate sample config/input files for CLI arguments",
    )
    p_sample.add_argument(
        "--output-dir",
        default=DEFAULT_SAMPLES_DIR,
        help="Output directory for sample files",
    )
    p_sample.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files if they already exist",
    )
    p_sample.add_argument(
        "--log-file",
        default=f"{default_log_dir}/generate-sample-config.log",
        help="Log file path",
    )
    p_sample.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_sample.set_defaults(func=cmd_generate_sample_config)

    def add_collect_common_arguments(
        p: argparse.ArgumentParser,
        require_show_commands_file: bool = False,
        default_transport: str = "auto",
    ) -> None:
        p.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
        p.add_argument("--policy", help="Policy YAML path")
        p.add_argument(
            "--roles",
            help=f"Role detection YAML path for grouped show commands (default: ./{DEFAULT_ROLES_PATH} if exists)",
        )
        p.add_argument("--username", help="SSH username")
        p.add_argument("--password", help="SSH password")
        p.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
        p.add_argument(
            "--transport",
            choices=["auto", "nxapi", "ssh"],
            default=default_transport,
            help="Command transport. auto prefers NX-API for NX-OS and falls back to SSH; non-NX-OS stays on SSH",
        )
        p.add_argument(
            "--target-hosts",
            help="Comma-separated target hostnames for base collect target selection",
        )
        p.add_argument(
            "--output",
            default=default_raw_dir,
            help="Raw root directory (collect writes LLDP to <output>/lldp and running-config to <output>/config)",
        )
        p.add_argument(
            "--before-show-run-dir",
            help="Baseline show running-config directory for diff comparison (prefers <dir>/config if present)",
        )
        p.add_argument("--workers", type=int, default=5, help="Number of parallel device collections")
        p.add_argument(
            "--show-commands-file",
            required=require_show_commands_file,
            help=f"Path to extra commands file (default: ./{DEFAULT_SHOW_COMMANDS_PATH} if exists)",
        )
        p.add_argument(
            "--show-hosts",
            help="Comma-separated hostnames for extra command collection target (default: all collect targets)",
        )
        p.add_argument(
            "--show-read-timeout",
            type=int,
            default=120,
            help="Read timeout in seconds for extra commands",
        )
        p.add_argument(
            "--skip-connect-check",
            action="store_true",
            help="Skip default pre-flight connectivity/authentication checks before device operations",
        )
        p.add_argument(
            "--connect-check-timeout",
            type=float,
            default=DEFAULT_CONNECT_CHECK_TIMEOUT,
            help="Timeout in seconds for pre-flight TCP/authentication checks",
        )
        p.add_argument("--log-file", default=f"{default_log_dir}/collect.log", help="Log file path")
        p.add_argument("--verbose", action="store_true", help="Verbose logging")

    p_collect = subparsers.add_parser("collect", help="Collect LLDP and optionally running-config")
    add_collect_common_arguments(p_collect, require_show_commands_file=False)
    p_collect.add_argument(
        "--show-run-diff",
        action="store_true",
        help="Collect show running-config diff against existing <hostname>_run.txt and write changed hosts to one file",
    )
    p_collect.add_argument(
        "--show-run-diff-comands",
        "--show-run-diff-commands",
        action="store_true",
        dest="show_run_diff_comands",
        help="Run device-native running-config diff command (nxos: show running-config diff) and write hosts with output to one file",
    )
    p_collect.add_argument(
        "--show-only",
        action="store_true",
        help="Run only extra show mode (--show-commands-file/--show-run-diff/--show-run-diff-comands) and skip base LLDP/running-config collection",
    )
    p_collect.set_defaults(func=cmd_collect)

    p_collect_list = subparsers.add_parser(
        "collect-list",
        help="Collect with --show-commands-file mode (same as collect --show-commands-file ...)",
    )
    add_collect_common_arguments(p_collect_list, require_show_commands_file=False)
    p_collect_list.set_defaults(
        func=cmd_collect,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=True,
    )

    p_collect_run_diff = subparsers.add_parser(
        "collect-run-diff",
        help="Collect with --show-run-diff mode",
    )
    add_collect_common_arguments(
        p_collect_run_diff,
        require_show_commands_file=False,
        default_transport="ssh",
    )
    p_collect_run_diff.set_defaults(
        func=cmd_collect,
        show_run_diff=True,
        show_run_diff_comands=False,
        show_only=False,
    )

    p_collect_run_diff_cmd = subparsers.add_parser(
        "collect-run-diff-cmd",
        help="Collect with --show-run-diff-comands mode",
    )
    add_collect_common_arguments(p_collect_run_diff_cmd, require_show_commands_file=False)
    p_collect_run_diff_cmd.set_defaults(
        func=cmd_collect,
        show_run_diff=False,
        show_run_diff_comands=True,
        show_only=True,
        run_config_only=False,
    )

    p_collect_run_config = subparsers.add_parser(
        "collect-run-config",
        help="Collect only running-config (same storage/rotation as collect)",
    )
    add_collect_common_arguments(p_collect_run_config, require_show_commands_file=False)
    p_collect_run_config.set_defaults(
        func=cmd_collect,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=True,
    )

    p_collect_clab = subparsers.add_parser(
        "collect-clab",
        help="Collect base data for lab use (show running-config + show lldp)",
    )
    add_collect_common_arguments(p_collect_clab, require_show_commands_file=False)
    p_collect_clab.set_defaults(
        func=cmd_collect,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=False,
    )

    def add_filter_archive_hosts_argument(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--filter-archive-hosts",
            action="store_true",
            help="When creating archive files, include only host-scoped artifacts for the effective target hosts from --hosts/--policy/--target-hosts",
        )

    p_collect_all = subparsers.add_parser(
        "collect-all",
        help="Run collect-clab, collect-list, collect-run-diff, and collect-run-diff-cmd in one flow",
    )
    add_collect_common_arguments(p_collect_all, require_show_commands_file=False)
    add_filter_archive_hosts_argument(p_collect_all)
    p_collect_all.set_defaults(
        func=cmd_collect_all,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=False,
        filter_archive_hosts=False,
    )

    def add_collect_work_arguments(
        p: argparse.ArgumentParser,
        default_log_file: str,
    ) -> None:
        add_collect_common_arguments(p, require_show_commands_file=False)
        add_filter_archive_hosts_argument(p)
        p.add_argument(
            "--last",
            nargs=2,
            metavar=("VALUE", "UNIT"),
            help="Time range for check-logging. collect-before-work defaults to 7 days; collect-after-work auto-calculates from the latest collect-before-work.",
        )
        p.add_argument(
            "--severity",
            type=int,
            help=(
                "Syslog severity (0-7). Check logs with severity less than or equal to this value.\n"
                "0=emergency, 1=alert, 2=critical, 3=error, 4=warning, 5=notice, 6=informational, 7=debug"
            ),
        )
        p.add_argument(
            "--check-string",
            help="File containing case-insensitive substring patterns to match against normalized log records",
        )
        p.add_argument(
            "--uncheck-string",
            help="File containing case-insensitive substring patterns used to exclude normalized log records",
        )
        p.add_argument(
            "--output-tar",
            help="Output tar filename or path for the bundled before/after work logs",
        )
        p.set_defaults(log_file=default_log_file)

    p_collect_before_work = subparsers.add_parser(
        "collect-before-work",
        help="Run collect-all, check-logging(raw), collect-run-diff-cmd, then bundle pre-work outputs",
    )
    add_collect_work_arguments(
        p_collect_before_work,
        default_log_file=f"{default_log_dir}/collect-before-work.log",
    )
    p_collect_before_work.set_defaults(
        func=cmd_collect_before_work,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=False,
        filter_archive_hosts=True,
    )

    p_collect_after_work = subparsers.add_parser(
        "collect-after-work",
        help="Run collect-all, check-logging(raw), collect-run-diff-cmd, then bundle post-work outputs",
    )
    add_collect_work_arguments(
        p_collect_after_work,
        default_log_file=f"{default_log_dir}/collect-after-work.log",
    )
    p_collect_after_work.set_defaults(
        func=cmd_collect_after_work,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=False,
        filter_archive_hosts=True,
    )

    p_check_logging = subparsers.add_parser(
        "check-logging",
        help="Check show logging output for recent logs that match severity or custom strings",
    )
    p_check_logging.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_check_logging.add_argument("--policy", help="Policy YAML path")
    p_check_logging.add_argument("--username", help="SSH username")
    p_check_logging.add_argument("--password", help="SSH password")
    p_check_logging.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_check_logging.add_argument(
        "--transport",
        choices=["auto", "nxapi", "ssh"],
        default="auto",
        help="Command transport. check-logging uses SSH for NX-OS show logging; nxapi is not supported",
    )
    p_check_logging.add_argument(
        "--target-hosts",
        help="Comma-separated target hostnames for check-logging target selection",
    )
    p_check_logging.add_argument(
        "--output",
        default=default_raw_dir,
        help="Raw root directory for raw input lookup and report output",
    )
    p_check_logging.add_argument("--workers", type=int, default=5, help="Number of parallel device checks")
    p_check_logging.add_argument(
        "--no-collect-raw-check",
        action="store_true",
        help="Read show logging from <output>/show_lists/<hostname>/<hostname>_shows.log instead of collecting live",
    )
    p_check_logging.add_argument(
        "--last",
        nargs=2,
        metavar=("VALUE", "UNIT"),
        help="Time range relative to command start, for example: --last 1 days",
    )
    p_check_logging.add_argument(
        "--severity",
        type=int,
        help=(
            "Syslog severity (0-7). Check logs with severity less than or equal to this value.\n"
            "0=emergency, 1=alert, 2=critical, 3=error, 4=warning, 5=notice, 6=informational, 7=debug"
        ),
    )
    p_check_logging.add_argument(
        "--check-string",
        help="File containing case-insensitive substring patterns to match against normalized log records",
    )
    p_check_logging.add_argument(
        "--uncheck-string",
        help="File containing case-insensitive substring patterns used to exclude normalized log records",
    )
    p_check_logging.add_argument(
        "--skip-connect-check",
        action="store_true",
        help="Skip default pre-flight connectivity/authentication checks before live device operations",
    )
    p_check_logging.add_argument(
        "--connect-check-timeout",
        type=float,
        default=DEFAULT_CONNECT_CHECK_TIMEOUT,
        help="Timeout in seconds for pre-flight TCP/authentication checks",
    )
    p_check_logging.add_argument(
        "--log-file",
        default=f"{default_log_dir}/check-logging.log",
        help="Log file path",
    )
    p_check_logging.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_check_logging.set_defaults(func=cmd_check_logging)

    p_clab_set = subparsers.add_parser(
        "clab-set-cmds",
        help="Run the predefined collect/normalize/containerlab/Mermaid/VNI pipeline",
    )
    p_clab_set.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_clab_set.add_argument("--policy", help="Policy YAML path")
    p_clab_set.add_argument("--username", help="SSH username")
    p_clab_set.add_argument("--password", help="SSH password")
    p_clab_set.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_clab_set.add_argument(
        "--transport",
        choices=["auto", "nxapi", "ssh"],
        default="auto",
        help="Command transport for collect phase",
    )
    p_clab_set.add_argument(
        "--target-hosts",
        help="Comma-separated target hostnames for collect target selection",
    )
    p_clab_set.add_argument(
        "--output",
        default=default_raw_dir,
        help="Raw root directory for collect phase",
    )
    p_clab_set.add_argument("--workers", type=int, default=5, help="Number of parallel device collections")
    p_clab_set.add_argument("--mappings", help="Mappings YAML path override for normalize/render steps")
    p_clab_set.add_argument(
        "--description-rules",
        help=f"Description rules YAML path override for normalize step (default: ./{DEFAULT_DESCRIPTION_RULES_PATH} if exists)",
    )
    p_clab_set.add_argument(
        "--roles",
        help=f"Role detection YAML path override for render steps (default: ./{DEFAULT_ROLES_PATH} if exists)",
    )
    p_clab_set.add_argument("--linux-csv", help="CSV override for generate-clab")
    p_clab_set.add_argument("--kind-cluster-csv", help="Kind cluster CSV override for generate-clab")
    p_clab_set.add_argument("--clab-env", help="YAML override for clab-transform-config")
    p_clab_set.add_argument("--clab-merge", help="YAML override for generate-clab")
    p_clab_set.add_argument("--clab-lab-profile", help="Lab profile YAML override for generate-clab")
    p_clab_set.add_argument(
        "--include-svi",
        action="store_true",
        help="Include SVI (interface Vlan*) links in Mermaid output",
    )
    p_clab_set.add_argument(
        "--without-collect",
        action="store_true",
        help="Skip collect-clab and use existing raw inputs, for example after extracting a collect-all tar",
    )
    p_clab_set.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_clab_set.set_defaults(func=cmd_clab_set_cmds)

    def add_push_target_arguments(p: argparse.ArgumentParser) -> None:
        p.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
        p.add_argument("--policy", help="Policy YAML path")
        p.add_argument(
            "--roles",
            help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)",
        )
        p.add_argument("--username", help="SSH username")
        p.add_argument("--password", help="SSH password")
        p.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
        p.add_argument(
            "--target-hosts",
            help="Comma-separated target hostnames (default: all hosts selected by policy)",
        )
        p.add_argument("--workers", type=int, default=5, help="Number of parallel device operations")
        p.add_argument(
            "--skip-connect-check",
            action="store_true",
            help="Skip default pre-flight connectivity/authentication checks before device operations",
        )
        p.add_argument(
            "--connect-check-timeout",
            type=float,
            default=DEFAULT_CONNECT_CHECK_TIMEOUT,
            help="Timeout in seconds for pre-flight TCP/authentication checks",
        )

    p_push = subparsers.add_parser("push-config", help="Push config lines to devices")
    add_push_target_arguments(p_push)
    p_push.add_argument("--config-file", required=True, help="Config lines file (one line per command)")
    p_push.add_argument(
        "--write-memory",
        action="store_true",
        dest="write_memory",
        help="Save config after push (default: disabled)",
    )
    p_push.add_argument("--log-file", default=f"{default_log_dir}/push-config.log", help="Log file path")
    p_push.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_push.set_defaults(func=cmd_push_config)

    p_push_dir = subparsers.add_parser(
        "push-config-dir",
        help="Push per-host config files from directory pattern <hostname><suffix>",
    )
    add_push_target_arguments(p_push_dir)
    p_push_dir.add_argument(
        "--input-dir",
        default=f"{default_raw_dir}/config",
        help="Input directory containing per-host config files",
    )
    p_push_dir.add_argument(
        "--file-suffix",
        default="",
        help="Optional literal suffix in filename pattern: <hostname><suffix>",
    )
    p_push_dir.add_argument(
        "--file-hostname-include",
        action="store_true",
        help="Match file when hostname is included in filename (with suffix filter)",
    )
    p_push_dir.add_argument(
        "--write-memory",
        action="store_true",
        dest="write_memory",
        help="Save config after all pushes complete (default: disabled)",
    )
    p_push_dir.add_argument("--log-file", default=f"{default_log_dir}/push-config-dir.log", help="Log file path")
    p_push_dir.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_push_dir.set_defaults(func=cmd_push_config_dir)

    p_write_memory = subparsers.add_parser(
        "write-memory",
        help="Save running-config on selected devices without pushing config",
    )
    add_push_target_arguments(p_write_memory)
    p_write_memory.add_argument(
        "--log-file",
        default=f"{default_log_dir}/write-memory.log",
        help="Log file path",
    )
    p_write_memory.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_write_memory.set_defaults(func=cmd_write_memory)

    p_norm = subparsers.add_parser(
        "normalize-links",
        help="Parse raw LLDP/running-config output and generate confirmed/candidate CSV",
    )
    p_norm.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_norm.add_argument(
        "--input",
        default=default_raw_dir,
        help="Raw root directory (reads <input>/lldp and <input>/config when present)",
    )
    p_norm.add_argument("--mappings", help="Mappings YAML path")
    p_norm.add_argument(
        "--description-rules",
        help=f"Description rules YAML path (default: ./{DEFAULT_DESCRIPTION_RULES_PATH} if exists)",
    )
    p_norm.add_argument(
        "--include-svi",
        action="store_true",
        help="Include SVI (interface Vlan*) descriptions during normalization",
    )
    p_norm.add_argument(
        "--output-confirmed",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
        help="Output confirmed CSV",
    )
    p_norm.add_argument(
        "--output-candidates",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CANDIDATES_FILENAME}",
        help="Output candidate CSV",
    )
    p_norm.add_argument("--log-file", default=f"{default_log_dir}/normalize-links.log", help="Log file path")
    p_norm.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_norm.set_defaults(func=cmd_normalize_links)

    p_gen = subparsers.add_parser("generate-clab", help="Generate containerlab YAML from confirmed CSV")
    p_gen.add_argument(
        "--input",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
        help="Input confirmed links CSV",
    )
    p_gen.add_argument("--hosts", help="Input hosts YAML (default: ./hosts.lab.yaml, then ./hosts.yaml)")
    p_gen.add_argument("--mappings", help="Mappings YAML path")
    p_gen.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_gen.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_gen.add_argument(
        "--include-nodes",
        dest="include_nodes",
        action="store_true",
        help="Include topology.nodes",
    )
    p_gen.add_argument(
        "--no-include-nodes",
        dest="include_nodes",
        action="store_false",
        help="Do not include topology.nodes",
    )
    p_gen.set_defaults(include_nodes=True)
    p_gen.add_argument(
        "--group-by-role",
        dest="group_by_role",
        action="store_true",
        help="Add role-based group to topology.nodes",
    )
    p_gen.add_argument(
        "--no-group-by-role",
        dest="group_by_role",
        action="store_false",
        help="Do not add role-based group to topology.nodes",
    )
    p_gen.set_defaults(group_by_role=True)
    p_gen.add_argument("--linux-csv", help="CSV file for linux server nodes/links overlay")
    p_gen.add_argument("--kind-cluster-csv", help="CSV file for kind cluster/ext-container nodes/links overlay")
    p_gen.add_argument("--clab-merge", help="YAML file to deep-merge into generated topology")
    p_gen.add_argument("--clab-lab-profile", help="YAML file for lab/server settings to merge after --clab-merge")
    p_gen.add_argument(
        "--name",
        default=DEFAULT_CLAB_TOPOLOGY_NAME,
        help=f"Topology name for output YAML (default: {DEFAULT_CLAB_TOPOLOGY_NAME})",
    )
    p_gen.add_argument(
        "--output",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_CLAB_FILENAME}",
        help="Output topology.yml",
    )
    p_gen.add_argument("--log-file", default=f"{default_log_dir}/generate-clab.log", help="Log file path")
    p_gen.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_gen.set_defaults(func=cmd_generate_clab)

    p_mermaid = subparsers.add_parser("generate-mermaid", help="Generate Mermaid markdown from links CSV")
    p_mermaid.add_argument(
        "--input",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
        help="Input confirmed links CSV",
    )
    p_mermaid.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_mermaid.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_mermaid.add_argument("--mappings", help="Mappings YAML path")
    p_mermaid.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_mermaid.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_mermaid.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_mermaid.add_argument("--group-by-role", action="store_true")
    p_mermaid.add_argument("--add-comments", action="store_true")
    p_mermaid.add_argument("--underlay", action="store_true", help="Show underlay loopback instead of mgmt for target roles")
    p_mermaid.add_argument("--underlay-config", help="YAML config for underlay display (roles/vrf/interface/label)")
    p_mermaid.add_argument(
        "--underlay-raw",
        default=default_raw_dir,
        help="Raw root directory for underlay lookup (uses <dir>/config when present)",
    )
    p_mermaid.add_argument("--title", default="Network Topology")
    p_mermaid.add_argument(
        "--output",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_MERMAID_FILENAME}",
        help="Output Markdown file (.md)",
    )
    p_mermaid.add_argument("--log-file", default=f"{default_log_dir}/generate-mermaid.log", help="Log file path")
    p_mermaid.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_mermaid.set_defaults(func=cmd_generate_mermaid)

    p_graphviz = subparsers.add_parser("generate-graphviz", help="Generate Graphviz DOT from links CSV")
    p_graphviz.add_argument(
        "--input",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
        help="Input confirmed links CSV",
    )
    p_graphviz.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_graphviz.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_graphviz.add_argument("--mappings", help="Mappings YAML path")
    p_graphviz.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_graphviz.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_graphviz.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_graphviz.add_argument("--group-by-role", action="store_true")
    p_graphviz.add_argument("--add-comments", action="store_true")
    p_graphviz.add_argument("--underlay", action="store_true", help="Show underlay loopback instead of mgmt for target roles")
    p_graphviz.add_argument("--underlay-config", help="YAML config for underlay display (roles/vrf/interface/label)")
    p_graphviz.add_argument(
        "--underlay-raw",
        default=default_raw_dir,
        help="Raw root directory for underlay lookup (uses <dir>/config when present)",
    )
    p_graphviz.add_argument("--title", default="Network Topology")
    p_graphviz.add_argument(
        "--output",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_GRAPHVIZ_FILENAME}",
        help="Output Graphviz DOT file (.dot)",
    )
    p_graphviz.add_argument("--log-file", default=f"{default_log_dir}/generate-graphviz.log", help="Log file path")
    p_graphviz.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_graphviz.set_defaults(func=cmd_generate_graphviz)

    p_drawio = subparsers.add_parser("generate-drawio", help="Generate draw.io XML from links CSV")
    p_drawio.add_argument(
        "--input",
        default=f"{default_links_dir}/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
        help="Input confirmed links CSV",
    )
    p_drawio.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_drawio.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_drawio.add_argument("--mappings", help="Mappings YAML path")
    p_drawio.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_drawio.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_drawio.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_drawio.add_argument("--group-by-role", action="store_true")
    p_drawio.add_argument("--add-comments", action="store_true")
    p_drawio.add_argument("--all-graph", action="store_true", help="Write all draw.io graph variants as separate pages")
    p_drawio.add_argument("--underlay", action="store_true", help="Show underlay loopback instead of mgmt for target roles")
    p_drawio.add_argument("--underlay-config", help="YAML config for underlay display (roles/vrf/interface/label)")
    p_drawio.add_argument(
        "--underlay-raw",
        default=default_raw_dir,
        help="Raw root directory for underlay lookup (uses <dir>/config when present)",
    )
    p_drawio.add_argument("--title", default="Network Topology")
    p_drawio.add_argument(
        "--output",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_DRAWIO_FILENAME}",
        help="Output draw.io file (.drawio)",
    )
    p_drawio.add_argument("--log-file", default=f"{default_log_dir}/generate-drawio.log", help="Log file path")
    p_drawio.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_drawio.set_defaults(func=cmd_generate_drawio)

    p_doc = subparsers.add_parser("generate-doc", help="Generate both containerlab YAML and Mermaid markdown")
    p_doc.add_argument("--input", required=True, help="Input confirmed links CSV")
    p_doc.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_doc.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_doc.add_argument("--mappings", help="Mappings YAML path")
    p_doc.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_doc.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_doc.add_argument("--include-nodes", action="store_true")
    p_doc.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_doc.add_argument("--group-by-role", action="store_true")
    p_doc.add_argument("--add-comments", action="store_true")
    p_doc.add_argument("--underlay", action="store_true", help="Show underlay loopback instead of mgmt for target roles")
    p_doc.add_argument("--underlay-config", help="YAML config for underlay display (roles/vrf/interface/label)")
    p_doc.add_argument(
        "--underlay-raw",
        default=default_raw_dir,
        help="Raw root directory for underlay lookup (uses <dir>/config when present)",
    )
    p_doc.add_argument("--title", default="Network Topology")
    p_doc.add_argument("--clab-merge", help="YAML file to deep-merge into generated topology")
    p_doc.add_argument("--clab-lab-profile", help="YAML file for lab/server settings to merge after --clab-merge")
    p_doc.add_argument(
        "--output-clab",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_CLAB_FILENAME}",
        help="Output containerlab YAML",
    )
    p_doc.add_argument(
        "--output-md",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_MERMAID_FILENAME}",
        help="Output Mermaid Markdown",
    )
    p_doc.add_argument("--log-file", default=f"{default_log_dir}/generate-doc.log", help="Log file path")
    p_doc.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_doc.set_defaults(func=cmd_generate_doc)

    p_vni = subparsers.add_parser(
        "generate-vni-map",
        help="Generate L3VNI/VRF/L2VNI/gateway map from running-config files",
    )
    p_vni.add_argument(
        "--input",
        default=default_raw_dir,
        help="Raw root directory for *_run.txt (uses <input>/config when present)",
    )
    p_vni.add_argument(
        "--output-csv",
        default=f"{default_links_dir}/{DEFAULT_VNI_MAP_CSV_FILENAME}",
        help="Output CSV path",
    )
    p_vni.add_argument(
        "--output-md",
        default=f"{default_links_dir}/{DEFAULT_VNI_MAP_MD_FILENAME}",
        help="Output Markdown path",
    )
    p_vni.add_argument("--title", default="VNI / VRF / Gateway Map", help="Markdown title")
    p_vni.add_argument(
        "--no-vlan-name",
        dest="include_vlan_name",
        action="store_false",
        help="Do not include VLAN name column",
    )
    p_vni.set_defaults(include_vlan_name=True)
    p_vni.add_argument("--log-file", default=f"{default_log_dir}/generate-vni-map.log", help="Log file path")
    p_vni.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_vni.set_defaults(func=cmd_generate_vni_map)

    p_vni_cfg = subparsers.add_parser(
        "generate-vni-config",
        help="Generate NX-OS config from target VNI gateway CSV and optional before-state CSV",
    )
    p_vni_cfg.add_argument(
        "--vni-gateway-map",
        help="Target VNI gateway CSV to apply via diff comparison mode",
    )
    p_vni_cfg.add_argument(
        "--vni-gateway-map-add",
        help="Precomputed add CSV to render directly without before-state comparison",
    )
    p_vni_cfg.add_argument(
        "--vni-gateway-map-del",
        help="Precomputed delete CSV to render directly without before-state comparison",
    )
    p_vni_cfg.add_argument(
        "--before-vni-csv",
        help="Before-state VNI gateway CSV for diff comparison",
    )
    p_vni_cfg.add_argument(
        "--disable-auto-collect",
        action="store_true",
        help="Do not run collect-run-config when --before-vni-csv is not provided; generate add-only config",
    )
    p_vni_cfg.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_vni_cfg.add_argument("--policy", help="Policy YAML path")
    p_vni_cfg.add_argument("--username", help="SSH username")
    p_vni_cfg.add_argument("--password", help="SSH password")
    p_vni_cfg.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_vni_cfg.add_argument(
        "--transport",
        choices=["auto", "nxapi", "ssh"],
        default="auto",
        help="Command transport used when auto collect is enabled",
    )
    p_vni_cfg.add_argument(
        "--target-hosts",
        help="Comma-separated target hostnames for auto collect target selection",
    )
    p_vni_cfg.add_argument(
        "--collect-output",
        default=default_raw_dir,
        help="Raw root directory for auto collect output",
    )
    p_vni_cfg.add_argument("--workers", type=int, default=5, help="Number of parallel device collections")
    p_vni_cfg.add_argument(
        "--generated-before-vni-csv",
        default=f"{default_links_dir}/vni_gateway_map_before.csv",
        help="Output path for generated before-state VNI CSV when auto collect is used",
    )
    p_vni_cfg.add_argument(
        "--output-csv-dir",
        default=default_links_dir,
        help="Output directory for add_/del_ diff CSV files",
    )
    p_vni_cfg.add_argument(
        "--output-dir",
        default=f"{default_links_dir}/vni_config",
        help="Output directory for per-device config files",
    )
    p_vni_cfg.add_argument(
        "--output-merged",
        default=f"{default_links_dir}/vni_config.txt",
        help="Output path for merged config file",
    )
    p_vni_cfg.add_argument(
        "--output-rollback-dir",
        default=f"{default_links_dir}/vni_config_rollback",
        help="Output directory for per-device rollback config files",
    )
    p_vni_cfg.add_argument(
        "--output-rollback-merged",
        default=f"{default_links_dir}/vni_config_rollback.txt",
        help="Output path for merged rollback config file",
    )
    p_vni_cfg.add_argument(
        "--collect-log-file",
        default=f"{default_log_dir}/collect-run-config.log",
        help="Log file path for auto collect phase",
    )
    p_vni_cfg.add_argument(
        "--log-file",
        default=f"{default_log_dir}/generate-vni-config.log",
        help="Log file path",
    )
    p_vni_cfg.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_vni_cfg.set_defaults(func=cmd_generate_vni_config)

    p_tf = subparsers.add_parser("generate-tf", help="Generate Terraform main.tf from hosts.yaml")
    p_tf.add_argument("--hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_tf.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_tf.add_argument("--provider-version", help='Terraform provider version constraint, e.g. ">= 0.5.0"')
    p_tf.add_argument("--output", required=True, help="Output main.tf")
    p_tf.add_argument("--log-file", default=f"{default_log_dir}/generate-tf.log", help="Log file path")
    p_tf.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_tf.set_defaults(func=cmd_generate_tf)

    p_csv_to_md = subparsers.add_parser("csv-to-md", help="Convert a CSV file to a Markdown table")
    p_csv_to_md.add_argument("--csv-file", required=True, help="Input CSV file")
    p_csv_to_md.add_argument("--output-file", help="Output Markdown file (default: same basename with .md)")
    p_csv_to_md.add_argument("--log-file", default=f"{default_log_dir}/csv-to-md.log", help="Log file path")
    p_csv_to_md.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_csv_to_md.set_defaults(func=cmd_csv_to_md)

    return parser


def main() -> None:
    """
    Main CLI entrypoint.
    """
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
