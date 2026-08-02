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
from getpass import getpass
import json
import math
import os
import sys
import tarfile
import time
from logging import Logger
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
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
    ADDITIONAL_RUNNING_CONFIG_COMMANDS_MAP,
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
    DEFAULT_SITES_PATH,
    DEFAULT_SAMPLES_DIR,
    DEFAULT_SHOW_COMMANDS_PATH,
    DEFAULT_TOPOLOGY_CLAB_FILENAME,
    DEFAULT_TOPOLOGY_DRAWIO_ALL_FILENAME,
    DEFAULT_TOPOLOGY_DRAWIO_FILENAME,
    DEFAULT_TOPOLOGY_GRAPHVIZ_FILENAME,
    DEFAULT_TOPOLOGY_MERMAID_FILENAME,
    DEFAULT_VNI_MAP_CSV_FILENAME,
    DEFAULT_VNI_MAP_MD_FILENAME,
    DEVICE_TYPE_TO_KIND,
    LLDP_COMMAND_MAP,
    PRIVILEGED_EXEC_DEVICE_TYPES,
    REQUIRE_ENABLE_SECRET_DEVICE_TYPES,
    RUNNING_CONFIG_COMMAND_MAP,
    RUNNING_CONFIG_DIFF_COMMAND_MAP,
    RUNNING_CONFIG_DIFF_EXCLUDE_PREFIXES_MAP,
    SAVE_CONFIG_COMMAND_MAP,
    SAVE_CONFIG_SUCCESS_MARKER_MAP,
    SEND_COMMAND_OPTIONS_MAP,
    SSH_SESSION_PREP_COMMANDS_MAP,
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
from .design import (
    normalize_and_validate_cables,
    read_cable_table,
    render_validation_report,
    validate_inventory,
    write_normalized_cables,
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
from .managed_config import (
    execute_config_session,
    execute_save_session,
)
from .capability import (
    CapabilityError,
    evaluate_capability,
    load_capability_registry,
    required_overlay_capabilities,
)
from .qualification import (
    QualificationError,
    QualificationRequiredError,
    build_qualification_summary,
    create_qualification_record,
    execute_qualification_apply,
    execute_qualification_baseline_save,
    execute_qualification_rollback,
    load_qualification_record,
    qualification_confirmation_phrase,
    verify_qualification_rollback,
)
from .approval import (
    ApprovalError,
    ApprovalRequiredError,
    build_approval_summary,
    create_approval_record,
    load_approval_record,
)
from .managed_operation import (
    execute_approved_apply,
    execute_approved_rollback,
    execute_approved_rollback_save,
    execute_approved_save,
    verify_approved_rollback,
)
from .operation import (
    DEFAULT_OPERATIONS_ROOT,
    OperationError,
    OperationInterruptGuard,
    OperationLock,
    OperationPathError,
    OperationStateError,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_yaml,
    create_operation_workspace,
    generate_attempt_id,
    load_operation_execution,
    load_operation_metadata,
    now_in_timezone,
    open_operation_workspace,
    preflight_operation_workspace,
    record_operation_error,
    resolve_timezone_name,
    assess_operation_lock,
    transition_operation,
    transition_phase,
    transition_workflow,
    read_operation_lock,
    load_active_change,
    resolve_active_change_for_after,
    save_active_change,
)
from .parsing import (
    build_description_records,
    get_inventory_device_type,
    is_excluded_interface,
    load_description_rules,
    load_mappings,
    load_node_map_csv,
    load_policy_file,
    load_roles,
    load_sites,
    merge_lldp_and_description_links,
    merge_node_map_into_mappings,
    normalize_hostname,
    normalize_interface_name,
    normalize_link_records,
    parse_interface_descriptions_from_run,
    parse_remote_from_description,
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
from .schema import source_sha256, validate_document
from .health.manifest import (
    CollectionAdapterError,
    build_collect_manifest,
)
from .health.snapshot import (
    SnapshotBuildError,
    build_health_snapshot,
)
from .health.evaluator import (
    HealthEvaluationError,
    compare_snapshots,
    evaluate_snapshot,
)
from .health.profile import (
    DEFAULT_HEALTH_PROFILE,
    apply_logging_time_range_override,
    ProfileResolutionError,
    load_resolved_profiles,
    resolve_profiles,
)
from .health.execution_context import (
    CONTEXT_RELATIVE_PATH,
    HealthExecutionContextError,
    build_health_execution_context,
    load_health_execution_context,
    verify_source_file,
)
from .health.report import (
    render_health_checklist,
    render_health_summary,
    render_overlay_summary,
    terminal_result_lines,
)
from .health.vni_map import (
    build_overlay_state,
    compare_overlay_states,
    overlay_diff_csv,
    overlay_profile_enabled,
    overlay_state_csv,
    render_overlay_diff_markdown,
    render_overlay_state_markdown,
)
from .health.overlay import (
    OverlayDiscoveryError,
    discover_overlay_changes,
)
from .health.overlay_evaluator import (
    OverlayEvaluationError,
    assess_overlay_convergence,
    evaluate_overlay_change,
)
from .overlay_render import (
    OverlayRenderError,
    adapt_legacy_vni_add_records,
    adapt_legacy_vni_delete_records,
    render_changeset,
    render_canonical_overlay_model,
    resolve_changeset,
    write_rendered_configs,
)
from .overlay_conflict import (
    OverlayConflictError,
    assess_overlay_conflicts,
    render_conflict_report_markdown,
    require_conflict_free,
)
from .preparation import (
    ReferenceStateError,
    select_reference_state,
)
from .device_groups import (
    load_device_groups_file,
    load_overlay_change_set,
    write_overlay_plan_inputs,
)
from .health.transcript import (
    TranscriptImportError,
    import_nxos_transcripts,
)
from .transform import (
    parse_mgmt_ipv4_subnet,
    resolve_node_map_management_ip,
    transform_inventory_mgmt_subnet,
    transform_run_config_text,
)
from .support_bundle import (
    SupportBundleError,
    create_support_bundle,
    inspect_support_bundle,
    verify_support_bundle_manifest,
)
from .topology import (
    build_node_definitions_from_links,
    build_node_definitions_from_inventory,
    build_node_mgmt_ip_map,
    build_normalized_inventory_and_mgmt_maps,
    detect_node_role,
    detect_node_roles,
    detect_node_site,
    get_role_priority,
    is_network_device_type,
    prepare_rendered_candidate_links,
    prepare_rendered_links,
)
from .utils import (
    get_credentials_for_device,
    get_optional_credentials_for_device,
    get_default_log_dir,
    get_links_dir,
    get_netmiko_unavailable_message,
    get_output_dir,
    get_raw_dir,
    get_ssh_options,
    get_topology_dir,
    load_yaml,
    resolve_netmiko_device_type,
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


def get_send_command_options(device_type: str) -> Dict[str, Any]:
    """
    Return Netmiko send_command options for device-specific prompt handling.
    """
    return dict(SEND_COMMAND_OPTIONS_MAP.get(device_type, {}))


def normalize_run_lines_for_diff(text: str, device_type: str) -> List[str]:
    """
    Normalize running-config lines for diff comparison.
    """
    lines = [line.rstrip("\r") for line in text.splitlines()]
    prefixes = RUNNING_CONFIG_DIFF_EXCLUDE_PREFIXES_MAP.get(device_type, [])
    if prefixes:
        lines = [line for line in lines if not any(line.lstrip().startswith(prefix) for prefix in prefixes)]

    # Ignore newline-only differences at the end of config snapshots.
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def apply_password_prompt_options(args: argparse.Namespace) -> None:
    """
    Apply Ansible-style runtime password prompts to parsed args.

    Args:
        args: Parsed CLI args.
    """
    if getattr(args, "ask_pass", False) and not getattr(args, "password", None):
        args.password = getpass("SSH password: ")
    if getattr(args, "ask_become_pass", False) and not getattr(args, "enable_secret", None):
        args.enable_secret = getpass("Enable secret / become password: ")


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
    netmiko_device_type = resolve_netmiko_device_type(host)

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
    for prep_command in SSH_SESSION_PREP_COMMANDS_MAP.get(device_type, []):
        try:
            logger.info("SESSION PREP %s: %s", hostname, prep_command)
            conn.send_command_timing(
                prep_command,
                read_timeout=20,
                strip_prompt=False,
                strip_command=False,
                cmd_verify=False,
            )
        except Exception as exc:
            logger.warning("SESSION PREP FAILED %s command=%s error=%s", hostname, prep_command, exc)

    if device_type in PRIVILEGED_EXEC_DEVICE_TYPES:
        if not enable_secret and device_type in REQUIRE_ENABLE_SECRET_DEVICE_TYPES:
            conn.disconnect()
            raise ValueError(
                f"{hostname}: device_type={device_type} requires enable secret. "
                "Use --enable-secret, -K/--ask-become-pass, or define ALRED_ENABLE_SECRET."
            )
        logger.info("ENABLE %s", hostname)
        try:
            conn.enable()
        except Exception as exc:
            conn.disconnect()
            raise ValueError(
                f"{hostname}: failed to enter privileged exec for device_type={device_type}. "
                "Use --enable-secret, -K/--ask-become-pass, or define ALRED_ENABLE_SECRET if this device requires one."
            ) from exc

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
        output_text = command_result.output
        if command_result.output_format == "json":
            raw_json_text = output_text.lstrip()
            json_start_positions = [
                pos for pos in [raw_json_text.find("{"), raw_json_text.find("[")]
                if pos >= 0
            ]
            if json_start_positions:
                raw_json_text = raw_json_text[min(json_start_positions):]
            try:
                parsed_json, end_index = json.JSONDecoder().raw_decode(raw_json_text)
                trailing_text = raw_json_text[end_index:].strip()
                if trailing_text:
                    logger.info(
                        "TRIM JSON TRAILING OUTPUT %s suffix=%s chars=%d",
                        hostname,
                        suffix,
                        len(trailing_text),
                    )
                output_text = json.dumps(parsed_json, ensure_ascii=False, indent=2) + "\n"
            except Exception as exc:
                logger.warning("FAILED TO NORMALIZE JSON %s suffix=%s error=%s", hostname, suffix, exc)
        old_path = build_collect_output_path(generation_dir, hostname, suffix, command_result.output_format)
        old_path.write_text(output_text, encoding="utf-8")
        prune_old_generations(old_dir)

        reset_collect_output_variants_once(output_dir, suffix)
        output_path = build_collect_output_path(output_dir, hostname, suffix, command_result.output_format)
        output_path.write_text(output_text, encoding="utf-8")
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

                for extra in ADDITIONAL_RUNNING_CONFIG_COMMANDS_MAP.get(device_type, []):
                    extra_cmd = str(extra.get("command", ""))
                    extra_suffix = str(extra.get("suffix", ""))
                    extra_output_format = extra.get("output_format")
                    extra_read_timeout = int(extra.get("read_timeout", 300))
                    if not extra_cmd or not extra_suffix:
                        continue
                    extra_result = collector.run_command(extra_cmd, read_timeout=extra_read_timeout)
                    if extra_result.ok:
                        if extra_output_format:
                            extra_result.output_format = str(extra_output_format)
                        save_command_result(run_outdir, extra_suffix, extra_result)
                    else:
                        logger.warning("SKIP SAVE %s command=%s", hostname, extra_cmd)
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
                logger.info("RUN %s: %s (for --show-run-diff-commands)", hostname, run_diff_cmd)
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
        result = execute_config_session(
            conn,
            filtered_lines,
            now=lambda: datetime.now().astimezone(),
            detect_cli_errors=False,
            raise_transport_errors=True,
        )
        logger.debug(
            "PUSH RESULT %s:\n%s",
            hostname,
            "\n".join(
                item["response"] for item in result["commands"]
                if item["response"]
            ).rstrip(),
        )
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
        result = execute_save_session(
            conn,
            command=save_cmd,
            success_marker=success_marker,
            now=lambda: datetime.now().astimezone(),
        )
        logger.debug("SAVE RESULT %s:\n%s", hostname, result["response"])
        if result["status"] != "SUCCESS":
            raise RuntimeError(
                result["error"] or "save command failed"
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
            username, password, enable_secret = get_credentials_for_device(args, str(host.get("device_type", "")), host)
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
            username, _password, _enable_secret = get_credentials_for_device(args, str(host.get("device_type", "")), host)
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
    1. -i/--inventory/--hosts value
    2. DEFAULT_HOSTS_PATH if exists
    """
    if raw:
        return raw
    default_path = Path(DEFAULT_HOSTS_PATH)
    if default_path.exists():
        return str(default_path)
    if required:
        raise FileNotFoundError(
            f"hosts file not found. Specify -i/--inventory/--hosts or place ./{DEFAULT_HOSTS_PATH}"
        )
    return None


def resolve_generate_clab_hosts_path(raw: str | None) -> str | None:
    """
    Resolve hosts file path for generate-clab.

    Priority:
    1. -i/--inventory/--hosts value
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


def load_effective_mappings(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Load standard mappings and merge optional node-map CSV hostname mappings.
    """
    mappings = load_mappings(getattr(args, "mappings", None))
    node_map_rows = load_node_map_csv(getattr(args, "node_map", None))
    return merge_node_map_into_mappings(mappings, node_map_rows)


def require_collect_all_show_commands(args: argparse.Namespace) -> str:
    """
    Ensure collect-all can run its collect-list step before touching devices.
    """
    show_commands_file = resolve_show_commands_path(getattr(args, "show_commands_file", None))
    if show_commands_file:
        return show_commands_file
    raise ValueError(
        f"{args.command} requires --show-commands-file or ./{DEFAULT_SHOW_COMMANDS_PATH} "
        "for the collect-list step"
    )


def _inventory_completion_candidates(parsed_args: argparse.Namespace) -> List[str]:
    """
    Return hostname candidates from the best available inventory file.
    """
    inventory_candidates: List[str] = []
    raw_hosts = getattr(parsed_args, "hosts", None)
    if raw_hosts:
        inventory_candidates.append(str(raw_hosts))
    inventory_candidates.extend(["hosts.lab.yaml", DEFAULT_HOSTS_PATH])

    for path_str in inventory_candidates:
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            continue
        try:
            inventory_data = load_yaml(str(path))
            hosts = load_inventory_data(inventory_data)
        except Exception:
            continue
        return sorted({str(host.get("hostname", "")).strip() for host in hosts if str(host.get("hostname", "")).strip()})

    return []


def _complete_comma_separated_hosts(prefix: str, parsed_args: argparse.Namespace) -> List[str]:
    """
    Complete comma-separated hostname lists from inventory.
    """
    prefix_text, partial = prefix.rsplit(",", 1) if "," in prefix else ("", prefix)
    chosen = {part.strip() for part in prefix_text.split(",") if part.strip()}
    base = f"{prefix_text}," if prefix_text else ""

    candidates: List[str] = []
    for hostname in _inventory_completion_candidates(parsed_args):
        if hostname in chosen:
            continue
        if partial and not hostname.startswith(partial):
            continue
        candidates.append(f"{base}{hostname}")
    return candidates


def _list_path_candidates(prefix: str, extensions: Tuple[str, ...] | None = None) -> List[str]:
    """
    Complete filesystem paths from the current working directory.
    """
    expanded = Path(prefix).expanduser()
    directory = expanded.parent if prefix and not prefix.endswith("/") else expanded
    partial = expanded.name if prefix and not prefix.endswith("/") else ""

    if prefix.startswith("~"):
        root_display = "~" if str(expanded).startswith(str(Path.home())) else str(directory)
    else:
        root_display = "" if str(directory) == "." else str(directory)

    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        return []

    matches: List[str] = []
    for entry in entries:
        if partial and not entry.name.startswith(partial):
            continue
        if entry.is_file() and extensions and entry.suffix.lower() not in extensions:
            continue

        if root_display in {"", "."}:
            candidate = entry.name
        else:
            candidate = f"{root_display.rstrip('/')}/{entry.name}"
        if entry.is_dir():
            candidate += "/"
        matches.append(candidate)
    return matches


def _build_completion_spec() -> Dict[str, str]:
    """
    Build completion kind mapping keyed by action dest.
    """
    return {
        "hosts": "yaml_file",
        "design_hosts": "txt_file",
        "policy": "yaml_file",
        "roles": "yaml_file",
        "sites": "yaml_file",
        "clab_env": "yaml_file",
        "clab_merge": "yaml_file",
        "clab_lab_profile": "yaml_file",
        "credentials": "yaml_file",
        "mappings": "yaml_file",
        "description_rules": "yaml_file",
        "show_commands_file": "txt_file",
        "config_file": "txt_file",
        "input": "any_file",
        "input_dir": "any_file",
        "output": "any_file",
        "output_dir": "any_file",
        "output_hosts": "any_file",
        "output_file": "any_file",
        "output_csv": "any_file",
        "output_md": "any_file",
        "output_clab": "any_file",
        "startup_dir": "any_file",
        "before_show_run_dir": "any_file",
        "csv_file": "csv_file",
        "linux_csv": "csv_file",
        "kind_cluster_csv": "csv_file",
        "cables": "csv_file",
        "target_hosts": "host_list",
        "show_hosts": "host_list",
    }


def _iter_subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    """
    Return the subparser action if present.
    """
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _hide_subparser_from_help(subparsers: argparse._SubParsersAction, name: str) -> None:
    """
    Keep an internal subcommand parseable while removing it from help output.
    """
    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if action.dest != name
    ]
    public_names = [choice_name for choice_name in subparsers.choices if choice_name != name]
    subparsers.metavar = "{" + ",".join(public_names) + "}"


def _find_active_parser(parser: argparse.ArgumentParser, words: List[str]) -> argparse.ArgumentParser:
    """
    Resolve the active parser for already-entered tokens.
    """
    active = parser
    for token in words[1:]:
        if token.startswith("-"):
            continue
        subparsers = _iter_subparser_action(active)
        if subparsers is None:
            continue
        next_parser = subparsers.choices.get(token)
        if next_parser is not None:
            active = next_parser
    return active


def _option_action_map(parser: argparse.ArgumentParser) -> Dict[str, argparse.Action]:
    """
    Return mapping from option string to argparse action.
    """
    option_map: Dict[str, argparse.Action] = {}
    for action in parser._actions:
        for option_string in action.option_strings:
            option_map[option_string] = action
    return option_map


def _complete_for_action(prefix: str, action: argparse.Action, parsed_args: argparse.Namespace) -> List[str]:
    """
    Return completion candidates for a specific option action.
    """
    kind = _build_completion_spec().get(action.dest, "")
    if kind == "yaml_file":
        return _list_path_candidates(prefix, (".yaml", ".yml"))
    if kind == "txt_file":
        return _list_path_candidates(prefix, (".txt",))
    if kind == "csv_file":
        return _list_path_candidates(prefix, (".csv",))
    if kind == "any_file":
        return _list_path_candidates(prefix, None)
    if kind == "host_list":
        return _complete_comma_separated_hosts(prefix, parsed_args)
    if action.choices:
        return [str(choice) for choice in action.choices if str(choice).startswith(prefix)]
    return []


def _extract_completion_hosts_arg(words: List[str]) -> str | None:
    """
    Extract explicit inventory path from partial command words when present.
    """
    option_names = {"-i", "--inventory", "--hosts"}
    for index, token in enumerate(words):
        if token in option_names and index + 1 < len(words):
            value = words[index + 1].strip()
            if value and not value.startswith("-"):
                return value
    return None


def _render_bash_completion_script() -> str:
    """
    Render bash completion script.
    """
    return """_alred_completion() {
  local IFS=$'\\n'
  COMPREPLY=($(\"${COMP_WORDS[0]}\" __complete bash \"$COMP_CWORD\" -- \"${COMP_WORDS[@]}\" 2>/dev/null))
}
complete -F _alred_completion alred
"""


def _render_zsh_completion_script() -> str:
    """
    Render zsh completion script using bash-style completion compatibility.
    """
    return """autoload -U bashcompinit
bashcompinit
_alred_completion() {
  local -a replies
  replies=(${(@f)$(\"$words[1]\" __complete zsh \"$((CURRENT-1))\" -- \"${words[@]}\" 2>/dev/null)})
  compadd -- $replies
}
complete -F _alred_completion alred
"""


def cmd_completion(args: argparse.Namespace) -> None:
    """
    Print shell completion script.
    """
    if args.shell == "bash":
        print(_render_bash_completion_script(), end="")
        return
    if args.shell == "zsh":
        print(_render_zsh_completion_script(), end="")
        return
    raise ValueError(f"Unsupported shell: {args.shell}")


def cmd_internal_complete(args: argparse.Namespace) -> None:
    """
    Return dynamic completion candidates for shell integration.
    """
    parser = build_parser()
    words = list(args.words)
    if not words:
        return

    cword = max(0, args.cword)
    current = words[cword] if cword < len(words) else ""
    prior_words = words[:cword]
    active = _find_active_parser(parser, prior_words)
    parsed_args = argparse.Namespace(hosts=_extract_completion_hosts_arg(prior_words))

    option_map = _option_action_map(active)
    prev_word = words[cword - 1] if cword > 0 else ""
    prev_action = option_map.get(prev_word)

    candidates: List[str] = []
    if prev_action is not None and not current.startswith("-"):
        candidates = _complete_for_action(current, prev_action, parsed_args)
    elif current.startswith("-"):
        for option in sorted(option_map.keys()):
            if option.startswith(current):
                candidates.append(option)
    else:
        subparsers = _iter_subparser_action(active)
        if subparsers is not None:
            for name in sorted(subparsers.choices.keys()):
                if name == "__complete":
                    continue
                if name.startswith(current):
                    candidates.append(name)
        for option in sorted(option_map.keys()):
            if option.startswith(current):
                candidates.append(option)

    for candidate in candidates:
        print(candidate)


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


def apply_linux_kind_defaults(
    topology_data: Dict[str, Any],
    logger: Logger,
) -> Dict[str, Any]:
    """Apply the default Linux image when at least one Linux node exists."""
    topology = topology_data.get("topology", {})
    if not isinstance(topology, dict):
        return topology_data
    nodes = topology.get("nodes", {})
    if not isinstance(nodes, dict):
        return topology_data
    if not any(
        isinstance(attrs, dict) and str(attrs.get("kind", "")).strip() == "linux"
        for attrs in nodes.values()
    ):
        return topology_data

    kinds = topology.setdefault("kinds", {})
    if not isinstance(kinds, dict):
        return topology_data
    linux = kinds.setdefault("linux", {})
    if not isinstance(linux, dict):
        return topology_data
    if "image" not in linux:
        linux["image"] = DEFAULT_LINUX_KIND_IMAGE
        logger.info("Applied default image for kind linux: %s", DEFAULT_LINUX_KIND_IMAGE)
    return topology_data


def parse_startup_delay_batch_spec(value: str | None) -> Tuple[int, int] | None:
    """
    Parse startup delay batch spec.

    Args:
        value: Spec in BATCH,SECONDS format, e.g. 5,600.

    Returns:
        (batch_size, delay_seconds) or None.

    Raises:
        ValueError: If the spec is invalid.
    """
    if not value:
        return None
    parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("startup delay spec must be BATCH,SECONDS, e.g. 5,600")
    try:
        batch_size = int(parts[0])
        delay_seconds = int(parts[1])
    except ValueError as exc:
        raise ValueError("startup delay spec must contain integers: BATCH,SECONDS") from exc
    if batch_size <= 0:
        raise ValueError("startup delay batch size must be greater than 0")
    if delay_seconds < 0:
        raise ValueError("startup delay seconds must be greater than or equal to 0")
    return batch_size, delay_seconds


def apply_n9kv_startup_delay(
    topology_data: Dict[str, Any],
    startup_delay_spec: str | None,
    logger: Logger,
) -> int:
    """
    Add staggered startup-delay to cisco_n9kv nodes.

    Args:
        topology_data: containerlab topology data.
        startup_delay_spec: BATCH,SECONDS spec, e.g. 5,600.
        logger: Logger.

    Returns:
        Number of nodes updated.
    """
    spec = parse_startup_delay_batch_spec(startup_delay_spec)
    if spec is None:
        return 0
    batch_size, delay_seconds = spec

    topology = topology_data.get("topology", {})
    if not isinstance(topology, dict):
        return 0
    nodes = topology.get("nodes", {})
    if not isinstance(nodes, dict):
        return 0

    n9kv_nodes = [
        (node_name, attrs)
        for node_name, attrs in nodes.items()
        if isinstance(attrs, dict) and str(attrs.get("kind", "")).strip() == DEFAULT_CISCO_N9KV_KIND_NAME
    ]

    updated = 0
    for index, (node_name, attrs) in enumerate(n9kv_nodes):
        delay = (index // batch_size) * delay_seconds
        if delay <= 0:
            continue
        if "startup-delay" in attrs:
            logger.info(
                "Skipped startup-delay for %s because it is already set: %s",
                node_name,
                attrs.get("startup-delay"),
            )
            continue
        attrs["startup-delay"] = delay
        updated += 1

    if n9kv_nodes:
        logger.info(
            "Applied cisco_n9kv startup-delay spec batch=%d seconds=%d nodes=%d updated=%d",
            batch_size,
            delay_seconds,
            len(n9kv_nodes),
            updated,
        )
    return updated


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


def infer_generate_mermaid_input_format(input_path: str, requested_format: str) -> str:
    """
    Resolve generate-mermaid input format.

    Args:
        input_path: Input file path.
        requested_format: csv, clab, or auto.

    Returns:
        Resolved format name.
    """
    if requested_format != "auto":
        return requested_format

    suffix = Path(input_path).suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return "clab"
    return "csv"


def clab_kind_to_device_type(kind: str) -> str:
    """
    Convert containerlab kind to inventory device_type.

    Args:
        kind: containerlab kind value.

    Returns:
        device_type value used by alred inventory helpers.
    """
    for device_type, mapped_kind in DEVICE_TYPE_TO_KIND.items():
        if kind == mapped_kind:
            return device_type
    return "linux" if kind == "linux" else "unknown"


def read_clab_node_diagram_value(attrs: Dict[str, Any], key: str) -> str:
    """
    Read diagram metadata from a clab node definition.

    Args:
        attrs: Node attributes from topology.nodes.
        key: Metadata key such as site or domain.

    Returns:
        Metadata value or empty string.
    """
    labels = attrs.get("labels", {})
    if isinstance(labels, dict):
        for label_key in (key, f"alred.{key}"):
            value = labels.get(label_key)
            if value:
                return str(value).strip()

    extras = attrs.get("extras", {})
    if isinstance(extras, dict):
        alred_data = extras.get("alred", {})
        if isinstance(alred_data, dict):
            value = alred_data.get(key)
            if value:
                return str(value).strip()

    # Accept direct keys for diagram-only YAML inputs. containerlab-safe
    # metadata should use labels or extras.alred.
    value = attrs.get(key)
    if value:
        return str(value).strip()
    return ""


def split_clab_endpoint(endpoint: Any) -> Tuple[str, str]:
    """
    Split a containerlab endpoint string into node and interface.

    Args:
        endpoint: endpoint value like node:interface.

    Returns:
        Tuple of node name and interface name.

    Raises:
        ValueError: If the endpoint is malformed.
    """
    value = str(endpoint).strip()
    if ":" not in value:
        raise ValueError(f"Invalid clab endpoint without ':': {value}")
    node, iface = value.split(":", 1)
    node = node.strip()
    iface = iface.strip()
    if not node or not iface:
        raise ValueError(f"Invalid clab endpoint: {value}")
    return node, iface


def read_clab_topology_for_diagram(input_path: str) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, Any]], List[str]]:
    """
    Read containerlab topology YAML as diagram records.

    Args:
        input_path: containerlab YAML path.

    Returns:
        (link records, inventory map inferred from topology.nodes, node names)
    """
    data = load_yaml(input_path)
    topology = data.get("topology", {})
    if not isinstance(topology, dict):
        raise ValueError(f"Invalid clab topology YAML: {input_path}")

    raw_nodes = topology.get("nodes", {})
    node_inventory: Dict[str, Dict[str, Any]] = {}
    node_names: List[str] = []
    if isinstance(raw_nodes, dict):
        for raw_name, raw_attrs in raw_nodes.items():
            node_name = str(raw_name).strip()
            if not node_name:
                continue
            attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
            kind = str(attrs.get("kind", "unknown"))
            info: Dict[str, Any] = {
                "hostname": node_name,
                "device_type": clab_kind_to_device_type(kind),
                "kind": kind,
            }
            mgmt_ip = attrs.get("mgmt-ipv4")
            if mgmt_ip:
                info["ip"] = str(mgmt_ip)
            group = attrs.get("group")
            if group:
                info["group"] = str(group)
            site = read_clab_node_diagram_value(attrs, "site") or read_clab_node_diagram_value(attrs, "domain")
            if site:
                info["site"] = site
            node_inventory[node_name] = info
            node_names.append(node_name)

    records: List[Dict[str, str]] = []
    raw_links = topology.get("links", [])
    if not isinstance(raw_links, list):
        raise ValueError(f"Invalid clab topology.links in {input_path}")

    for idx, raw_link in enumerate(raw_links, start=1):
        if not isinstance(raw_link, dict):
            continue
        endpoints = raw_link.get("endpoints", [])
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise ValueError(f"Invalid clab link endpoints at topology.links[{idx}]")
        src_node, src_if = split_clab_endpoint(endpoints[0])
        dst_node, dst_if = split_clab_endpoint(endpoints[1])
        records.append({
            "src_node": src_node,
            "src_if": src_if,
            "dst_node": dst_node,
            "dst_if": dst_if,
            "protocol": "clab",
            "confidence": "high",
            "evidence": "clab-topology",
        })
        if src_node not in node_inventory and src_node not in node_names:
            node_names.append(src_node)
        if dst_node not in node_inventory and dst_node not in node_names:
            node_names.append(dst_node)

    return records, node_inventory, node_names


def apply_site_labels_to_nodes(nodes: Dict[str, Dict[str, Any]], sites: Dict[str, Any]) -> int:
    """
    Add labels.site to node definitions from site detection rules.

    Args:
        nodes: topology.nodes mapping.
        sites: Site detection rules.

    Returns:
        Number of nodes updated.
    """
    if not sites:
        return 0

    updated = 0
    for node_name, attrs in nodes.items():
        if not isinstance(attrs, dict):
            continue
        existing_site = read_clab_node_diagram_value(attrs, "site")
        if existing_site:
            continue
        site = detect_node_site(node_name, sites)
        if not site:
            continue
        labels = attrs.setdefault("labels", {})
        if not isinstance(labels, dict):
            labels = {}
            attrs["labels"] = labels
        labels["site"] = site
        updated += 1

    return updated


def apply_site_labels_to_topology_data(topology_data: Dict[str, Any], sites: Dict[str, Any]) -> int:
    """
    Add labels.site to topology.nodes from site detection rules.

    Args:
        topology_data: containerlab topology data.
        sites: Site detection rules.

    Returns:
        Number of nodes updated.
    """
    topology = topology_data.get("topology", {})
    if not isinstance(topology, dict):
        return 0
    nodes = topology.get("nodes", {})
    if not isinstance(nodes, dict):
        return 0
    return apply_site_labels_to_nodes(nodes, sites)


def prepare_topology_diagram_context(args: argparse.Namespace, logger: Logger) -> Dict[str, Any]:
    """
    Build shared topology diagram rendering inputs for Mermaid/Graphviz/draw.io.
    """
    input_format = infer_generate_mermaid_input_format(args.input, getattr(args, "input_format", "csv"))
    mappings = load_effective_mappings(args)
    roles = load_roles(args.roles)
    sites = load_sites(getattr(args, "sites", None))

    inventory_map: Dict[str, Dict[str, Any]] = {}
    extra_node_names: List[str] = []
    if input_format == "clab":
        records, clab_inventory_map, extra_node_names = read_clab_topology_for_diagram(args.input)
        inventory_map.update(clab_inventory_map)
    else:
        records = read_links_csv(args.input)

    hosts_path = resolve_hosts_path(args.hosts, required=False)
    if hosts_path:
        inventory_data = load_yaml(hosts_path)
        inventory_map.update(load_inventory_map_from_list(load_inventory_data(inventory_data)))

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
            inventory_map=inventory_map,
        )

    normalized_inventory_map, normalized_mgmt_ip_map = build_normalized_inventory_and_mgmt_maps(
        inventory_map=inventory_map,
        mgmt_ip_map=mgmt_ip_map,
        mappings=mappings,
    )
    node_role_map = {
        node: str(attrs.get("group", "")).strip()
        for node, attrs in normalized_inventory_map.items()
        if isinstance(attrs, dict) and str(attrs.get("group", "")).strip()
    }
    node_site_map = {
        node: str(attrs.get("site", "")).strip()
        for node, attrs in normalized_inventory_map.items()
        if isinstance(attrs, dict) and str(attrs.get("site", "")).strip()
    }
    for node in list(normalized_inventory_map):
        node_site_map.setdefault(node, detect_node_site(node, sites))

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
        "sites": sites,
        "normalized_inventory_map": normalized_inventory_map,
        "normalized_mgmt_ip_map": normalized_mgmt_ip_map,
        "rendered_links": rendered_links,
        "rendered_candidate_links": rendered_candidate_links,
        "node_address_map": node_address_map,
        "node_address_label_map": node_address_label_map,
        "node_address_lines_map": node_address_lines_map,
        "link_label_map": link_label_map,
        "node_interface_label_map": node_interface_label_map,
        "extra_node_names": extra_node_names,
        "node_role_map": node_role_map,
        "node_site_map": node_site_map,
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
        group_by_site=getattr(args, "group_by_site", False),
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        node_interface_label_map=context["node_interface_label_map"],
        node_role_map=context["node_role_map"],
        node_site_map=context["node_site_map"],
        sites=context["sites"],
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


def collect_cable_description_warnings(
    local_hostname: str,
    device_type: str,
    transformed_text: str,
    normalized_cables: Iterable[Dict[str, Any]],
    inventory_map: Dict[str, Dict[str, Any]],
    mappings: Dict[str, Any],
    description_rules: List[Dict[str, str]],
) -> List[str]:
    """Compare one transformed config's interface descriptions with cable peers."""
    local_node = normalize_hostname(local_hostname, mappings)
    descriptions = {
        normalize_interface_name(item["local_if"], mappings, device_type): item["description"]
        for item in parse_interface_descriptions_from_run(transformed_text)
    }
    expected_peers: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for cable in normalized_cables:
        if not cable.get("enabled"):
            continue
        src = (str(cable["src_node"]), str(cable["src_if"]))
        dst = (str(cable["dst_node"]), str(cable["dst_if"]))
        expected_peers[src] = dst
        expected_peers[dst] = src

    warnings: List[str] = []
    for endpoint, expected in sorted(expected_peers.items()):
        if endpoint[0] != local_node:
            continue
        description = descriptions.get(endpoint[1])
        expected_text = f"{expected[0]}:{expected[1]}"
        endpoint_text = f"{endpoint[0]}:{endpoint[1]}"
        if description is None:
            warnings.append(
                f"Cable/description missing: {endpoint_text} expected={expected_text}"
            )
            continue
        parsed = parse_remote_from_description(description, description_rules)
        if not parsed:
            warnings.append(
                f"Cable/description unparseable: {endpoint_text} "
                f"expected={expected_text} description={description}"
            )
            continue
        remote_node = normalize_hostname(parsed["remote_host"], mappings)
        remote_type = get_inventory_device_type(remote_node, inventory_map, mappings)
        remote_if = (
            normalize_interface_name(parsed["remote_if"], mappings, remote_type)
            if parsed["remote_if"]
            else ""
        )
        node_matches = remote_node == expected[0]
        interface_matches = not remote_if or remote_if == expected[1]
        if not node_matches or not interface_matches:
            actual_text = f"{remote_node}:{remote_if or '(unspecified)'}"
            warnings.append(
                f"Cable/description mismatch: {endpoint_text} expected={expected_text} "
                f"description={actual_text}"
            )
    return warnings


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
    node_map_rows = load_node_map_csv(getattr(args, "node_map", None))
    hostname_map = {
        row["source_hostname"]: row["target_hostname"]
        for row in node_map_rows
    }
    management_address_map = {
        row["source_mgmt_ip"]: resolve_node_map_management_ip(row, mgmt_subnet)
        for row in node_map_rows
    }
    source_hostname_by_target = {
        row["target_hostname"]: row["source_hostname"]
        for row in node_map_rows
    }

    transformed_inventory = transform_inventory_mgmt_subnet(
        inventory_data,
        mgmt_subnet,
        node_map_rows=node_map_rows,
    )
    save_yaml(transformed_inventory, args.output_hosts)
    logger.info(
        "WROTE TRANSFORMED HOSTS %s mgmt_subnet=%s",
        args.output_hosts,
        str(mgmt_subnet) if mgmt_subnet is not None else "disabled",
    )

    normalized_cables: List[Dict[str, Any]] = []
    cable_inventory_map: Dict[str, Dict[str, Any]] = {}
    cable_mappings: Dict[str, Any] = {}
    description_rules: List[Dict[str, str]] = []
    cables_path = getattr(args, "cables", None)
    if cables_path:
        cable_mappings = load_effective_mappings(args)
        description_rules = load_description_rules(
            getattr(args, "description_rules", None)
        )
        cable_inventory_map = load_inventory_map_from_list(
            load_inventory_data(transformed_inventory)
        )
        raw_cables, cable_issues = read_cable_table(cables_path)
        normalized_cables, normalization_issues = normalize_and_validate_cables(
            raw_cables,
            cable_inventory_map,
            cable_mappings,
        )
        for issue in cable_issues + normalization_issues:
            location = f"row {issue.row}: " if issue.row is not None else ""
            logger.warning("CABLE CHECK %s%s", location, issue.message)

    raw_dir = Path(args.input)
    run_dir = get_run_input_dir(raw_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(getattr(args, "file_suffix", "_run.txt") or "")

    hosts = inventory_data.get("all", {}).get("hosts", {})
    if not isinstance(hosts, dict):
        raise ValueError(f"Invalid hosts inventory format: {hosts_path}")

    transformed_count = 0
    missing_files: List[str] = []
    cable_description_warning_count = 0

    for hostname in sorted(hosts.keys()):
        host_attrs = hosts.get(hostname, {})
        if not isinstance(host_attrs, dict):
            host_attrs = {}
        host = dict(host_attrs)
        host["hostname"] = hostname
        device_type = str(host.get("device_type", ""))
        lab_credentials = None
        delete_username = bool(getattr(args, "delete_username", False))
        if device_type == "nxos" and not delete_username:
            lab_credentials = get_optional_credentials_for_device(args, device_type, host)

        source_hostname = source_hostname_by_target.get(str(hostname), str(hostname))
        source_path = run_dir / f"{source_hostname}{suffix}"
        if not source_path.exists():
            missing_files.append(str(source_path))
            logger.warning("SKIP MISSING RUN CONFIG %s", source_path)
            continue

        source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        target_hostname = hostname_map.get(str(hostname), str(hostname))
        transformed_text, stats = transform_run_config_text(
            source_text,
            mgmt_subnet,
            lab_username=lab_credentials[0] if lab_credentials else None,
            lab_password=lab_credentials[1] if lab_credentials else None,
            delete_username=delete_username and device_type == "nxos",
            delete_access_class=bool(getattr(args, "delete_access_class", False))
            and device_type == "nxos",
            hostname_map=hostname_map,
            management_address_map=management_address_map,
        )
        if normalized_cables:
            description_warnings = collect_cable_description_warnings(
                target_hostname,
                device_type,
                transformed_text,
                normalized_cables,
                cable_inventory_map,
                cable_mappings,
                description_rules,
            )
            cable_description_warning_count += len(description_warnings)
            for warning in description_warnings:
                logger.warning("%s", warning)
        output_path = output_dir / f"{target_hostname}{suffix}"
        output_path.write_text(transformed_text, encoding="utf-8")
        transformed_count += 1
        logger.info(
            "WROTE LAB CONFIG %s subif_conversions=%d mgmt_sections=%d parent_added=%d parent_merged=%d svi_merged=%d no_switchport_added=%d username_removed=%d snmp_user_removed=%d access_class_removed=%d hostname_renamed=%d description_renamed=%d lab_username_added=%d",
            output_path,
            stats["subinterface_conversions"],
            stats["management_section_updates"],
            stats["generated_parent_interfaces"],
            stats["merged_existing_parent_interfaces"],
            stats["merged_existing_svis"],
            stats["inserted_no_switchport"],
            stats["removed_username_lines"],
            stats["removed_snmp_user_lines"],
            stats["removed_access_class_lines"],
            stats["renamed_hostname_lines"],
            stats["renamed_description_lines"],
            stats["inserted_lab_username"],
        )

    logger.info(
        "TRANSFORM COMPLETE hosts=%d configs=%d missing=%d cable_description_warnings=%d",
        len(hosts),
        transformed_count,
        len(missing_files),
        cable_description_warning_count,
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
        raise ValueError("--show-commands-file and --show-run-diff-commands cannot be used together")
    if args.show_run_diff and args.show_run_diff_comands:
        raise ValueError("--show-run-diff and --show-run-diff-commands cannot be used together")
    if args.show_only and not show_commands and not args.show_run_diff and not args.show_run_diff_comands:
        raise ValueError("--show-only requires --show-commands-file or --show-run-diff or --show-run-diff-commands")
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
                *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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
        *get_credentials_for_device(args, device_type, host),
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


def check_clab_startup_config_for_host(
    host: Dict[str, Any],
    username: str,
    password: str,
    enable_secret: str,
    startup_dir: Path,
    current_dir: Path,
    file_suffix: str,
    logger: Logger,
) -> Dict[str, Any]:
    """
    Compare generated startup-config and live running-config for one lab host.
    """
    hostname = str(host.get("hostname", ""))
    device_type = str(host.get("device_type", ""))
    startup_path = startup_dir / f"{hostname}{file_suffix}"

    result: Dict[str, Any] = {
        "hostname": hostname,
        "device_type": device_type,
        "startup_path": str(startup_path),
        "status": "unknown",
    }

    if not startup_path.exists():
        result["status"] = "missing-startup"
        result["message"] = f"startup-config not found: {startup_path}"
        return result

    try:
        run_cmd = get_running_config_command(device_type)
    except ValueError as exc:
        result["status"] = "unsupported"
        result["message"] = str(exc)
        return result

    expected_text = startup_path.read_text(encoding="utf-8", errors="ignore")
    conn = connect_to_host(host, username, password, enable_secret, logger)
    try:
        logger.info("RUN %s: %s (for check-clab-startup-config)", hostname, run_cmd)
        current_text = conn.send_command(
            run_cmd,
            read_timeout=300,
            **get_send_command_options(device_type),
        )
    finally:
        conn.disconnect()

    current_path = current_dir / f"{hostname}{file_suffix}"
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text(current_text.rstrip() + "\n", encoding="utf-8")
    result["current_path"] = str(current_path)

    expected_lines = normalize_run_lines_for_diff(expected_text, device_type)
    current_lines = normalize_run_lines_for_diff(current_text, device_type)
    if expected_lines == current_lines:
        result["status"] = "matched"
        return result

    result["status"] = "diff"
    result["diff_lines"] = list(
        difflib.unified_diff(
            expected_lines,
            current_lines,
            fromfile=f"{hostname}_startup-config",
            tofile=f"{hostname}_running-config",
            lineterm="",
        )
    )
    return result


def cmd_check_clab_startup_config(args: argparse.Namespace) -> None:
    """
    Verify that lab nodes booted with the expected startup-config.
    """
    logger = setup_logging(args.log_file, args.verbose)
    hosts_path = resolve_generate_clab_hosts_path(args.hosts)
    if not hosts_path:
        raise FileNotFoundError(
            "hosts file not found. Specify -i/--inventory/--hosts or place ./hosts.lab.yaml"
        )

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

    startup_dir = Path(args.startup_dir)
    output_dir = Path(args.output_dir)
    current_dir = output_dir / "current"
    report_path = output_dir / "check-clab-startup-config.txt"
    file_suffix = str(getattr(args, "file_suffix", "_run.txt") or "")

    logger.info("Loaded %d hosts from %s", len(hosts), hosts_path)
    logger.info("Startup config dir=%s", startup_dir)
    logger.info("Startup config file suffix=%s", file_suffix)
    logger.info("Check targets=%d skipped=%d workers=%d", len(targets), skipped, max(1, args.workers))

    targets, connect_failures = filter_hosts_by_connect_check(targets, args, logger)
    skipped += len(connect_failures)
    print_connect_check_failures("CHECK CLAB STARTUP", connect_failures)

    results: List[Dict[str, Any]] = []
    for failure in connect_failures:
        results.append(
            {
                "hostname": failure.hostname,
                "device_type": failure.device_type,
                "status": "connect-failed",
                "message": failure.error or "connect check failed",
            }
        )

    if targets:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_host = {
                executor.submit(
                    check_clab_startup_config_for_host,
                    host,
                    *get_credentials_for_device(args, str(host.get("device_type", "")), host),
                    startup_dir,
                    current_dir,
                    file_suffix,
                    logger,
                ): host
                for host in targets
            }
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.exception("FAILED %s: %s", host["hostname"], exc)
                    results.append(
                        {
                            "hostname": host["hostname"],
                            "device_type": host.get("device_type", "unknown"),
                            "status": "failed",
                            "message": str(exc),
                        }
                    )

    counts = {
        "matched": 0,
        "diff": 0,
        "missing-startup": 0,
        "unsupported": 0,
        "connect-failed": 0,
        "failed": 0,
    }
    for item in results:
        status = str(item.get("status", "unknown"))
        if status in counts:
            counts[status] += 1

    report_lines = [
        "### CLAB STARTUP CONFIG CHECK SUMMARY",
        f"hosts_file: {hosts_path}",
        f"startup_dir: {startup_dir}",
        f"file_suffix: {file_suffix}",
        f"current_dir: {current_dir}",
        f"matched: {counts['matched']}",
        f"diff: {counts['diff']}",
        f"missing_startup: {counts['missing-startup']}",
        f"unsupported: {counts['unsupported']}",
        f"connect_failed: {counts['connect-failed']}",
        f"failed: {counts['failed']}",
        f"skipped: {skipped}",
        "",
        "### HOST RESULT SUMMARY",
    ]
    for item in sorted(results, key=lambda x: str(x.get("hostname", ""))):
        hostname = str(item.get("hostname", ""))
        status = str(item.get("status", "unknown"))
        message = str(item.get("message", ""))
        line = f"- {hostname}: {status}"
        if message:
            line += f" ({message})"
        report_lines.append(line)

    detail_items = [
        item for item in sorted(results, key=lambda x: str(x.get("hostname", "")))
        if str(item.get("status", "")) != "matched"
    ]
    if detail_items:
        report_lines.extend(["", "### HOST DETAILS"])
        for item in detail_items:
            report_lines.extend(
                [
                    "",
                    f"### HOST: {item.get('hostname', '')}",
                    f"### STATUS: {item.get('status', '')}",
                    f"### DEVICE_TYPE: {item.get('device_type', '')}",
                ]
            )
            if item.get("startup_path"):
                report_lines.append(f"### STARTUP_PATH: {item['startup_path']}")
            if item.get("current_path"):
                report_lines.append(f"### CURRENT_PATH: {item['current_path']}")
            if item.get("message"):
                report_lines.append(f"### MESSAGE: {item['message']}")
            diff_lines = item.get("diff_lines", [])
            if diff_lines:
                report_lines.extend(["### DIFF", *diff_lines])

    write_text(report_path, report_lines)
    logger.info("Wrote startup-config verification report to %s", report_path)

    summary_lines = [
        "### CLAB STARTUP CONFIG CHECK SUMMARY",
        f"matched: {counts['matched']}",
        f"diff: {counts['diff']}",
        f"missing_startup: {counts['missing-startup']}",
        f"unsupported: {counts['unsupported']}",
        f"connect_failed: {counts['connect-failed']}",
        f"failed: {counts['failed']}",
        f"report: {report_path}",
    ]
    print("\n".join(summary_lines))


def run_collect_all_flow(args: argparse.Namespace, logger: Logger) -> Path:
    """
    Run all collect-family flows and package current outputs.
    """
    require_collect_all_show_commands(args)
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
                *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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
                    *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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
                *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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
                    *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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
                *get_credentials_for_device(args, str(host.get("device_type", "")), host),
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

    mappings = load_effective_mappings(args)
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

    lldp_records = normalize_link_records(lldp_records, mappings, hosts)
    description_records = normalize_link_records(description_records, mappings, hosts)

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

    print_normalize_links_result_summary(confirmed, candidates, args.output_confirmed, args.output_candidates)


def collect_lldp_description_mismatch_summary(
    confirmed: List[Dict[str, str]],
    candidates: List[Dict[str, str]],
) -> Tuple[List[str], List[str]]:
    """
    Collect human-readable LLDP/description mismatch summary rows.

    Args:
        confirmed: Confirmed link records.
        candidates: Candidate link records.

    Returns:
        (mismatch_hosts, mismatch_details)
    """
    hosts = set()
    details = set()

    for record in confirmed + candidates:
        warning_text = record.get("warning", "")
        for warning in [item.strip() for item in warning_text.split(";") if item.strip()]:
            if not warning.startswith("lldp-description-mismatch"):
                continue
            src_node = record.get("src_node", "")
            src_if = record.get("src_if", "")
            if src_node:
                hosts.add(src_node)
            mismatch = warning.partition(":")[2].strip()
            for item in mismatch.split():
                if item.startswith(("lldp=", "description=")):
                    endpoint = item.partition("=")[2]
                    hostname = endpoint.partition(":")[0]
                    if hostname:
                        hosts.add(hostname)
            local_endpoint = f"{src_node}:{src_if}" if src_if else src_node
            details.add(f"{local_endpoint} -> {mismatch}" if mismatch else local_endpoint)

    return sorted(hosts), sorted(details)


def print_normalize_links_result_summary(
    confirmed: List[Dict[str, str]],
    candidates: List[Dict[str, str]],
    confirmed_output: str,
    candidates_output: str | None,
) -> None:
    """
    Print a concise normalize-links result summary.

    Args:
        confirmed: Confirmed link records.
        candidates: Candidate link records.
        confirmed_output: Confirmed CSV path.
        candidates_output: Candidate CSV path.
    """
    mismatch_hosts, mismatch_details = collect_lldp_description_mismatch_summary(confirmed, candidates)

    print("\n### NORMALIZE LINKS RESULT ###")
    if mismatch_hosts:
        print("LLDP / Description : MISMATCH")
        print("")
        print("Mismatch hosts:")
        for hostname in mismatch_hosts:
            print(f"- {hostname}")
        print("")
        print("Mismatch links:")
        for detail in mismatch_details:
            print(f"- {detail}")
    else:
        print("LLDP / Description : OK")

    print("")
    print(f"Confirmed links output : {confirmed_output}")
    if candidates_output:
        print(f"Candidate links output : {candidates_output}")
    else:
        print("Candidate links output : disabled")
    print("##############################")


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
    mappings = load_effective_mappings(args)
    for record in records:
        record["device"] = normalize_hostname(str(record.get("device", "")), mappings)
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
    return adapt_legacy_vni_add_records(
        records,
        existing_before_records,
    )["context"]


def render_vni_add_config_lines(
    records: List[Dict[str, str]],
    existing_before_records: List[Dict[str, str]] | None = None,
) -> List[str]:
    """
    Render NX-OS add config lines for VNI gateway records.
    """
    return render_canonical_overlay_model(
        adapt_legacy_vni_add_records(records, existing_before_records)
    )


def build_vni_delete_render_context(
    records_to_delete: List[Dict[str, str]],
    remaining_after_records: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Build Jinja2 render context for delete config.
    """
    return adapt_legacy_vni_delete_records(
        records_to_delete,
        remaining_after_records,
    )["context"]


def render_vni_delete_config_lines(
    records_to_delete: List[Dict[str, str]],
    remaining_after_records: List[Dict[str, str]],
) -> List[str]:
    """
    Render NX-OS delete config lines for VNI gateway records.
    """
    return render_canonical_overlay_model(
        adapt_legacy_vni_delete_records(
            records_to_delete,
            remaining_after_records,
        )
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
        credentials=getattr(args, "credentials", None),
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
    mappings = load_effective_mappings(args)
    roles = load_roles(args.roles)
    sites = load_sites(getattr(args, "sites", None))

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
    site_label_count = apply_site_labels_to_topology_data(topology_data, sites)
    apply_n9kv_startup_delay(topology_data, getattr(args, "n9kv_startup_delay", None), logger)
    topology_data = apply_linux_kind_defaults(topology_data, logger)
    topology_data = apply_cisco_n9kv_kind_defaults(topology_data, get_raw_dir("raw"), logger)
    topology_data = finalize_clab_topology_data(topology_data, generated_links, generated_node_names, roles)
    write_text(args.output, render_clab_yaml_lines(topology_data, generated_node_names, roles))

    logger.info("Skipped %d links by min-confidence=%s", skipped_by_confidence, args.min_confidence)
    logger.info("Wrote %d links to %s", len(rendered_links), args.output)
    if args.include_nodes:
        logger.info("Generated %d nodes", len(nodes))
        if args.group_by_role:
            logger.info("Added node groups from role detection")
        if site_label_count:
            logger.info("Added site labels from site detection: %d nodes", site_label_count)


def cmd_init_clab(args: argparse.Namespace) -> None:
    """Generate a containerlab topology from hosts.txt and a cable table."""
    logger = setup_logging(args.log_file, args.verbose)
    mappings = load_effective_mappings(args)
    roles = load_roles(args.roles)
    sites = load_sites(getattr(args, "sites", None))

    entries = parse_hosts_txt(args.design_hosts)
    source_inventory = build_inventory(entries)
    clab_env_path = args.clab_env
    if not clab_env_path and Path("clab_merge.yaml").exists():
        clab_env_path = "clab_merge.yaml"
    clab_env_data = load_yaml(clab_env_path)
    try:
        mgmt_subnet = parse_mgmt_ipv4_subnet(clab_env_data)
    except ValueError:
        mgmt_subnet = None
    inventory_data = transform_inventory_mgmt_subnet(source_inventory, mgmt_subnet)
    inventory_map = load_inventory_map_from_list(load_inventory_data(inventory_data))

    raw_cables, issues = read_cable_table(args.cables)
    normalized_cables, cable_issues = normalize_and_validate_cables(
        raw_cables,
        inventory_map,
        mappings,
    )
    issues.extend(cable_issues)
    issues.extend(validate_inventory(inventory_map, normalized_cables, mappings, clab_env_data))

    write_normalized_cables(args.output_normalized, normalized_cables)
    write_text(args.validation_report, render_validation_report(issues))
    for issue in issues:
        location = f"row {issue.row}: " if issue.row is not None else ""
        getattr(logger, "error" if issue.severity == "error" else "warning")(
            "%s%s", location, issue.message
        )

    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise ValueError(
            f"init-clab validation failed with {len(errors)} error(s); "
            f"see {args.validation_report}"
        )
    if args.validate_only:
        logger.info("Validation passed; topology generation skipped by --validate-only")
        return

    link_records = [
        {
            "src_node": str(record["src_node"]),
            "src_if": str(record["src_if"]),
            "dst_node": str(record["dst_node"]),
            "dst_if": str(record["dst_if"]),
            "protocol": "design",
            "confidence": "high",
            "evidence": "cable-table",
        }
        for record in normalized_cables
        if record["enabled"]
    ]
    rendered_links, _ = prepare_rendered_links(
        records=link_records,
        mappings=mappings,
        roles=roles,
        min_confidence="low",
        logger=logger,
        inventory_map=inventory_map,
        clab_mode=True,
    )
    mgmt_ip_map = build_node_mgmt_ip_map(inventory_map, mappings, logger)
    nodes = build_node_definitions_from_inventory(
        inventory_map=inventory_map,
        mappings=mappings,
        mgmt_ip_map=mgmt_ip_map,
        roles=roles,
        include_group=args.group_by_role,
    )
    site_label_count = apply_site_labels_to_nodes(nodes, sites)
    topology_data = build_clab_topology_data(rendered_links, nodes, include_nodes=True)
    topology_data["name"] = DEFAULT_CLAB_TOPOLOGY_NAME
    generated_links = deepcopy(topology_data["topology"]["links"])
    generated_node_names = set(nodes)

    if clab_env_path:
        topology_data = apply_clab_merge_file(topology_data, clab_env_path, logger, "clab-env")
    if args.clab_merge and args.clab_merge != clab_env_path:
        topology_data = apply_clab_merge_file(topology_data, args.clab_merge, logger, "clab-merge")
    if args.clab_lab_profile:
        topology_data = apply_clab_merge_file(
            topology_data,
            args.clab_lab_profile,
            logger,
            "clab-lab-profile",
        )
    if args.name:
        topology_data["name"] = args.name
    apply_n9kv_startup_delay(topology_data, getattr(args, "n9kv_startup_delay", None), logger)
    topology_data = apply_linux_kind_defaults(topology_data, logger)
    topology_data = apply_cisco_n9kv_kind_defaults(topology_data, get_raw_dir("raw"), logger)
    topology_data = finalize_clab_topology_data(
        topology_data,
        generated_links,
        generated_node_names,
        roles,
    )
    write_text(args.output, render_clab_yaml_lines(topology_data, generated_node_names, roles))
    logger.info("Wrote %d nodes and %d links to %s", len(nodes), len(rendered_links), args.output)
    if site_label_count:
        logger.info("Added site labels from site detection: %d nodes", site_label_count)


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
        group_by_site=getattr(args, "group_by_site", False),
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        extra_node_names=context["extra_node_names"],
        node_role_map=context["node_role_map"],
        node_site_map=context["node_site_map"],
        sites=context["sites"],
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
        group_by_site=getattr(args, "group_by_site", False),
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        node_role_map=context["node_role_map"],
        node_site_map=context["node_site_map"],
        sites=context["sites"],
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
        group_by_site=getattr(args, "group_by_site", False),
        add_comments=args.add_comments,
        title=context["title"],
        candidate_links=context["rendered_candidate_links"],
        node_address_map=context["node_address_map"],
        node_address_label_map=context["node_address_label_map"],
        node_address_lines_map=context["node_address_lines_map"],
        link_label_map=context["link_label_map"],
        node_interface_label_map=context["node_interface_label_map"],
        node_role_map=context["node_role_map"],
        node_site_map=context["node_site_map"],
        sites=context["sites"],
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
    mappings = load_effective_mappings(args)
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
    apply_n9kv_startup_delay(topology_data, getattr(args, "n9kv_startup_delay", None), logger)
    topology_data = apply_linux_kind_defaults(topology_data, logger)
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
            inventory_map=inventory_map,
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
        "credentials": getattr(args, "credentials", None),
        "transport": getattr(args, "transport", None),
        "target_hosts": getattr(args, "target_hosts", None),
        "workers": getattr(args, "workers", None),
        "mappings": getattr(args, "mappings", None),
        "description_rules": getattr(args, "description_rules", None),
        "roles": getattr(args, "roles", None),
        "sites": getattr(args, "sites", None),
        "linux_csv": getattr(args, "linux_csv", None),
        "kind_cluster_csv": getattr(args, "kind_cluster_csv", None),
        "clab_env": getattr(args, "clab_env", None),
        "node_map": getattr(args, "node_map", None),
        "cables": getattr(args, "cables", None),
        "file_suffix": getattr(args, "file_suffix", None),
        "delete_username": getattr(args, "delete_username", None),
        "delete_access_class": getattr(args, "delete_access_class", None),
        "clab_merge": getattr(args, "clab_merge", None),
        "clab_lab_profile": getattr(args, "clab_lab_profile", None),
        "include_svi": getattr(args, "include_svi", None),
        "group_by_site": getattr(args, "group_by_site", None),
    }
    for key, value in common_optional_overrides.items():
        if value is not None:
            data[key] = value
    if "credentials" not in data and hasattr(args, "credentials"):
        data["credentials"] = getattr(args, "credentials", None)

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
    if getattr(args, "node_map", None) and handler_command in {
        "generate-clab",
        "generate-mermaid",
        "generate-graphviz",
        "generate-drawio",
    }:
        data["hosts"] = "hosts.lab.yaml"

    step_args = argparse.Namespace(**data)
    if handler_command in {"generate-mermaid", "generate-graphviz", "generate-drawio"}:
        if not hasattr(step_args, "input_format"):
            step_args.input_format = "csv"
        if not hasattr(step_args, "sites"):
            step_args.sites = None
        if not hasattr(step_args, "group_by_site"):
            step_args.group_by_site = False
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


def _operation_cli_error(exc: Exception) -> None:
    code = getattr(exc, "code", "VALIDATION_ERROR")
    print(f"{code}: {exc}", file=sys.stderr)
    raise SystemExit(2)


def _operation_recommended_action(
    lifecycle: str,
    workflow_state: str | None,
    lock_present: bool,
) -> str:
    if lock_present:
        return "Inspect the lock owner and wait; do not remove the lock automatically."
    if lifecycle == "created":
        return "Start the next planned phase."
    if lifecycle == "running":
        return "Inspect execution history before resuming."
    if lifecycle == "waiting_for_user":
        return "Review the pending decision or approval."
    if lifecycle in {"failed", "state_unknown"}:
        return "Reconcile actual state and create a new plan before apply."
    if workflow_state == "rollback_required":
        return "Review the approved rollback plan."
    return "No mutating action is recommended."


def cmd_operation_status(args: argparse.Namespace) -> None:
    """Print concise common operation state without modifying the workspace."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        metadata = load_operation_metadata(workspace.operation_root)
        execution = load_operation_execution(workspace.operation_root)
        lock_data, lock_warning = read_operation_lock(workspace.operation_root)
        preflight = preflight_operation_workspace(workspace)
    except Exception as exc:
        _operation_cli_error(exc)
        return

    last_transition = metadata["spec"]["last_transition"]
    print("=== OPERATION STATUS ===")
    print(f"Change ID      : {workspace.change_id}")
    print(f"Lifecycle      : {metadata['spec']['lifecycle']}")
    print(f"Workflow       : {metadata['spec']['workflow_state'] or '-'}")
    print(f"Timezone       : {metadata['metadata']['timezone']}")
    print(f"Output         : {workspace.operation_root}")
    if lock_data:
        lock_findings = assess_operation_lock(lock_data)
        print(
            "Lock           : "
            f"held operation={lock_data['operation']} "
            f"pid={lock_data['pid']} host={lock_data['hostname']}"
        )
        for finding in lock_findings:
            print(f"Lock note      : {finding}")
    elif lock_warning:
        print(f"Lock           : invalid ({lock_warning})")
    else:
        print("Lock           : not held")
    print(
        "Last transition: "
        f"{last_transition['scope']} "
        f"{last_transition['from'] or '-'} -> {last_transition['to']} "
        f"at {last_transition['at']}"
    )
    print(f"Transitions    : {len(execution['transitions'])}")
    print(
        "Preflight      : "
        f"{'PASS' if preflight.ok else 'WARN/FAIL'} "
        f"filesystem={preflight.filesystem_type or 'unknown'}"
    )
    print(
        "Recommended    : "
        + _operation_recommended_action(
            metadata["spec"]["lifecycle"],
            metadata["spec"]["workflow_state"],
            lock_data is not None or lock_warning is not None,
        )
    )


def cmd_operation_inspect(args: argparse.Namespace) -> None:
    """Print operation artifacts and transition history read-only."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        metadata = load_operation_metadata(workspace.operation_root)
        execution = load_operation_execution(workspace.operation_root)
        lock_data, lock_warning = read_operation_lock(workspace.operation_root)
    except Exception as exc:
        _operation_cli_error(exc)
        return

    approval_files = sorted(
        (workspace.operation_root / "approval").glob("approval-record*.json")
    ) if (workspace.operation_root / "approval").is_dir() else []
    print("=== OPERATION INSPECT ===")
    print(f"Change ID       : {workspace.change_id}")
    print(f"Metadata SHA-256: {source_sha256(workspace.metadata_path)}")
    print(f"Execution SHA-256: {source_sha256(workspace.execution_path)}")
    print(f"Approvals       : {len(approval_files)}")
    for approval_path in approval_files:
        print(f"  - {approval_path}")
    if lock_data:
        print("Lock:")
        print(json.dumps(lock_data, ensure_ascii=False, indent=2, sort_keys=True))
    elif lock_warning:
        print(f"Lock warning: {lock_warning}")
    else:
        print("Lock: not held")
    print("Phases:")
    if metadata["spec"]["phases"]:
        for phase, phase_data in sorted(metadata["spec"]["phases"].items()):
            print(
                f"  - {phase}: {phase_data['status']} "
                f"attempt={phase_data['current_attempt'] or '-'}"
            )
    else:
        print("  - none")
    print("Transitions:")
    for transition in execution["transitions"]:
        print(
            f"  - {transition['at']} {transition['scope']}: "
            f"{transition['from'] or '-'} -> {transition['to']} "
            f"({transition['reason'] or '-'})"
        )
    print(f"Errors: {len(execution['errors'])}")


def _parse_named_artifacts(values: List[str] | None) -> Dict[str, str]:
    artifacts: Dict[str, str] = {}
    for raw in values or []:
        name, separator, path = raw.partition("=")
        if not separator or not name or not path:
            raise ApprovalError(
                "--artifact must use NAME=PATH"
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ApprovalError(
                "artifact NAME must use lowercase letters, digits, and '_'"
            )
        if name in artifacts:
            raise ApprovalError(f"duplicate artifact name: {name}")
        artifacts[name] = path
    return artifacts


def cmd_overlay_change_approve(args: argparse.Namespace) -> None:
    """Create an interactive approval record for exact plan hashes."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        plan_path = args.plan or (
            workspace.operation_root / "plan" / "execution-plan.json"
        )
        rollback_plan_path = args.rollback_plan or (
            workspace.operation_root / "plan" / "rollback-plan.json"
        )
        artifacts = _parse_named_artifacts(args.artifact)
        summary = build_approval_summary(
            workspace,
            plan_path=plan_path,
            rollback_plan_path=rollback_plan_path,
            artifacts=artifacts,
            max_devices=args.max_devices,
            save_on_success=args.save_on_success,
            rollback_policy=args.rollback_policy,
        )
        preflight = preflight_operation_workspace(
            workspace,
            device_count=summary["device_count"],
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise ApprovalError(f"operation preflight failed: {details}")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ApprovalRequiredError(
                "approval requires an interactive TTY; pipes and --yes are unsupported"
            )

        print("=== OVERLAY CHANGE APPROVAL ===")
        print(f"Change ID: {workspace.change_id}")
        print("Artifacts:")
        for name, digest in sorted(summary["artifacts"].items()):
            print(f"  - {name}: {summary['paths'][name]}")
            print(f"    {digest}")
        print("Constraints:")
        for name, value in sorted(summary["constraints"].items()):
            print(f"  - {name}: {value}")

        def confirm(_summary: Dict[str, Any]) -> bool:
            return input("Type 'yes' to approve: ").strip().lower() == "yes"

        with OperationLock(workspace, "approve") as lock:
            output_path = create_approval_record(
                workspace,
                summary,
                lock=lock,
                confirm=confirm,
                approval_hours=args.approval_hours,
            )
        print(f"Approval: {output_path}")
    except (ApprovalError, OperationError, ValueError, OSError) as exc:
        _operation_cli_error(exc)


def cmd_overlay_change_qualify_approve(args: argparse.Namespace) -> None:
    """Approve an exact PLAN_ONLY candidate for initial 9000v qualification."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        root = workspace.operation_root
        qualification_plan_path = Path(
            args.plan or root / "plan/execution-plan.json"
        )
        qualification_plan = json.loads(
            qualification_plan_path.read_text(encoding="utf-8")
        )
        default_change_set = qualification_plan.get("artifacts", {}).get(
            "change_set",
            root / "desired-changes.yaml",
        )
        summary = build_qualification_summary(
            workspace,
            plan_path=qualification_plan_path,
            rollback_plan_path=(
                args.rollback_plan or root / "plan/rollback-plan.json"
            ),
            before_snapshot_path=(
                args.before_snapshot or root / "health/before/snapshot.json"
            ),
            before_health_result_path=(
                args.before_health_result
                or root / "health/before/health-result.json"
            ),
            change_set_path=args.change_set or default_change_set,
            render_manifest_path=(
                args.render_manifest or root / "plan/render-manifest.json"
            ),
            inventory_path=args.hosts,
        )
        preflight = preflight_operation_workspace(
            workspace,
            device_count=len(summary["target"]["devices"]),
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise QualificationError(
                f"operation preflight failed: {details}"
            )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise QualificationRequiredError(
                "qualification approval requires an interactive TTY"
            )

        phrase = qualification_confirmation_phrase(summary)
        print("=== INITIAL LAB QUALIFICATION APPROVAL ===")
        print(f"Change ID : {workspace.change_id}")
        print(f"Target    : {summary['target']['model']} "
              f"{summary['target']['release']}")
        print("Devices   : " + ", ".join(summary["target"]["devices"]))
        print("Save      : disabled for initial apply")
        print("Rollback  : manual")
        print("Pinned artifacts:")
        for name, artifact in sorted(summary["artifacts"].items()):
            print(f"  - {name}: {artifact['path']}")
            print(f"    {artifact['sha256']}")

        def confirm(expected: str) -> str:
            print("Type the exact qualification phrase:")
            print(expected)
            return input("> ").strip()

        with OperationLock(workspace, "qualify-approve") as lock:
            output_path = create_qualification_record(
                workspace,
                summary,
                lock=lock,
                confirm=confirm,
                approval_hours=args.approval_hours,
            )
        print(f"Qualification record: {output_path}")
        print("Device configuration has not been sent.")
    except (
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def cmd_overlay_change_apply(args: argparse.Namespace) -> int:
    """Execute an interactively approved APPLY_VERIFIED plan."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        root = workspace.operation_root
        plan_path = Path(args.approved_plan or root / "plan/execution-plan.json")
        rollback_path = Path(
            args.approved_rollback_plan or root / "plan/rollback-plan.json"
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        inventory_path = Path(plan["artifacts"]["inventory"])
        inventory = load_inventory_data(load_yaml(str(inventory_path)))
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory
        }
        approval = load_approval_record(
            args.approval_record or root / "approval/approval-record.json"
        )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ApprovalRequiredError("apply requires an interactive TTY")
        phrase = f"APPLY {workspace.change_id}"
        print("=== APPROVED OVERLAY APPLY ===")
        print(f"Change ID : {workspace.change_id}")
        print("Devices   : " + ", ".join(plan["devices"]))
        print("Serial    : 1")
        print("Save      : after health only")
        print("Type the exact apply phrase:")
        print(phrase)
        if input("> ").strip() != phrase:
            raise ApprovalRequiredError("exact apply phrase was not provided")
        logger = setup_logging(
            args.log_file or str(root / "apply/apply.log"),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host, username, password, enable_secret, logger
            )

        with OperationLock(workspace, "overlay-change-apply") as lock:
            with OperationInterruptGuard(
                workspace, lock, phase="approved_apply"
            ) as guard:
                execution = execute_approved_apply(
                    workspace,
                    approval,
                    plan_path=plan_path,
                    rollback_plan_path=rollback_path,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=guard,
                )
        print(f"Execution : {root / 'apply/execution.json'}")
        for host, result in execution["status"]["devices"].items():
            print(f"- {host}: {result['status']}")
        print(f"Result    : {execution['status']['result']}")
        return 0 if execution["status"]["result"] == "APPLIED_PENDING_HEALTH" else 4
    except (
        ApprovalError,
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def cmd_overlay_change_rollback(args: argparse.Namespace) -> int:
    """Execute an approved manual rollback without saving."""
    try:
        workspace = open_operation_workspace(
            args.operations_root, args.change_id
        )
        root = workspace.operation_root
        plan_path = Path(args.approved_plan or root / "plan/execution-plan.json")
        rollback_path = Path(
            args.approved_rollback_plan or root / "plan/rollback-plan.json"
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        inventory_path = Path(plan["artifacts"]["inventory"])
        inventory = load_inventory_data(load_yaml(str(inventory_path)))
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory
        }
        approval = load_approval_record(
            args.approval_record or root / "approval/approval-record.json"
        )
        current_snapshot = Path(
            args.current_snapshot or root / "health/after/snapshot.json"
        )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ApprovalRequiredError("rollback requires an interactive TTY")
        phrase = f"ROLLBACK {workspace.change_id}"
        print("=== APPROVED OVERLAY ROLLBACK ===")
        print(f"Change ID : {workspace.change_id}")
        print(f"Snapshot  : {current_snapshot}")
        print("Serial    : 1 (reverse order)")
        print("Save      : disabled")
        print("Type the exact rollback phrase:")
        print(phrase)
        if input("> ").strip() != phrase:
            raise ApprovalRequiredError(
                "exact rollback phrase was not provided"
            )
        logger = setup_logging(
            args.log_file or str(root / "rollback/rollback.log"),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host, username, password, enable_secret, logger
            )

        with OperationLock(workspace, "overlay-change-rollback") as lock:
            with OperationInterruptGuard(
                workspace, lock, phase="approved_rollback"
            ) as guard:
                execution = execute_approved_rollback(
                    workspace,
                    approval,
                    plan_path=plan_path,
                    rollback_plan_path=rollback_path,
                    current_snapshot_path=current_snapshot,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=guard,
                )
        print(f"Execution : {root / 'rollback/execution.json'}")
        for host, result in execution["status"]["devices"].items():
            print(f"- {host}: {result['status']}")
        print(f"Result    : {execution['status']['result']}")
        print("Next      : run health-check rollback")
        return (
            0
            if execution["status"]["result"]
            == "ROLLED_BACK_PENDING_HEALTH"
            else 4
        )
    except (
        ApprovalError,
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def cmd_overlay_change_save(args: argparse.Namespace) -> int:
    """Save an approved, health-verified Overlay apply."""
    try:
        save_mode = getattr(args, "save_mode", "apply")
        workspace = open_operation_workspace(
            args.operations_root, args.change_id
        )
        root = workspace.operation_root
        plan_path = Path(args.approved_plan or root / "plan/execution-plan.json")
        rollback_path = Path(
            args.approved_rollback_plan or root / "plan/rollback-plan.json"
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        inventory_path = Path(plan["artifacts"]["inventory"])
        inventory = load_inventory_data(load_yaml(str(inventory_path)))
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory
        }
        approval = load_approval_record(
            args.approval_record or root / "approval/approval-record.json"
        )
        snapshot = Path(
            args.after_snapshot
            or root
            / "health"
            / ("after" if save_mode == "apply" else "rollback")
            / "snapshot.json"
        )
        targets = [
            host
            for host, item in plan["devices"].items()
            if item["status"] == "PLANNED"
        ]
        preflight = preflight_operation_workspace(
            workspace,
            device_count=len(targets),
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise QualificationError(
                f"operation preflight failed: {details}"
            )
        logger = setup_logging(
            args.log_file
            or str(root / save_mode / "save.log"),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host, username, password, enable_secret, logger
            )

        print(
            "=== APPROVED OVERLAY "
            + ("SAVE" if save_mode == "apply" else "ROLLBACK SAVE")
            + " ==="
        )
        print(f"Change ID : {workspace.change_id}")
        print("Devices   : " + ", ".join(targets))
        print(f"Snapshot  : {snapshot}")
        print("Approval  : save_on_success=true")
        print("Serial    : 1")
        print("Retry     : disabled")
        with OperationLock(workspace, "overlay-change-save") as lock:
            with OperationInterruptGuard(
                workspace, lock, phase="approved_save"
            ) as guard:
                save_executor = (
                    execute_approved_save
                    if save_mode == "apply"
                    else execute_approved_rollback_save
                )
                execution = save_executor(
                    workspace,
                    approval,
                    plan_path=plan_path,
                    rollback_plan_path=rollback_path,
                    after_snapshot_path=snapshot,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    save_command=get_save_config_command("nxos"),
                    success_marker=get_save_config_success_marker("nxos"),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=guard,
                )
        print(
            f"Execution : "
            f"{root / save_mode / 'save-execution.json'}"
        )
        for host, result in execution["status"]["devices"].items():
            print(f"- {host}: {result['status']}")
            print(
                f"  log={root / save_mode / 'devices' / host / 'save.log'}"
            )
        print(f"Result    : {execution['status']['result']}")
        return (
            0
            if execution["status"]["result"]
            in {"APPLIED_AND_VERIFIED", "ROLLED_BACK_AND_SAVED"}
            else 5
        )
    except (
        ApprovalError,
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def cmd_overlay_change_qualify(args: argparse.Namespace) -> int:
    """Execute an approved initial 9000v qualification without saving."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        record_path = (
            Path(args.qualification_record)
            if args.qualification_record
            else workspace.operation_root
            / "qualification"
            / "qualification-record.json"
        )
        record = load_qualification_record(record_path)
        pinned_inventory = Path(
            record["artifacts"]["inventory"]["path"]
        ).resolve()
        requested_inventory = Path(args.hosts).resolve()
        if requested_inventory != pinned_inventory:
            raise QualificationError(
                "--hosts must match the inventory pinned by qualification"
            )
        inventory_data = load_yaml(str(requested_inventory))
        inventory_list = load_inventory_data(inventory_data)
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory_list
        }
        target_devices = list(record["target"]["devices"])
        preflight = preflight_operation_workspace(
            workspace,
            device_count=len(target_devices),
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise QualificationError(
                f"operation preflight failed: {details}"
            )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise QualificationRequiredError(
                "qualification apply requires an interactive TTY"
            )

        print("=== INITIAL LAB QUALIFICATION APPLY ===")
        print(f"Change ID : {workspace.change_id}")
        print(f"Target    : {record['target']['model']} "
              f"{record['target']['release']}")
        print("Devices   : " + ", ".join(target_devices))
        print("Serial    : 1")
        print("Save      : disabled")
        print("Retry     : disabled")
        print("Rollback  : manual")
        phrase = f"APPLY-QUALIFICATION {workspace.change_id}"
        print("Type the exact execution phrase:")
        print(phrase)
        if input("> ").strip() != phrase:
            raise QualificationRequiredError(
                "exact qualification execution phrase was not provided"
            )

        logger = setup_logging(
            args.log_file
            or str(
                workspace.operation_root
                / "qualification"
                / "apply"
                / "apply.log"
            ),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host,
                username,
                password,
                enable_secret,
                logger,
            )

        with OperationLock(workspace, "qualify") as lock:
            with OperationInterruptGuard(
                workspace,
                lock,
                phase="qualification_apply",
            ) as interrupt_guard:
                execution = execute_qualification_apply(
                    workspace,
                    record,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=interrupt_guard,
                )
        print("Qualification execution:")
        print(
            workspace.operation_root
            / "qualification"
            / "apply"
            / "execution.json"
        )
        for host, result in execution["status"]["devices"].items():
            print(
                f"- {host}: {result['status']} "
                f"commands={len(result['commands'])}"
            )
        print(f"Result: {execution['status']['result']}")
        print("Configuration save: SKIPPED")
        print("Next: run after Health Check before any save decision.")
        return (
            0
            if execution["status"]["result"] == "APPLIED_PENDING_HEALTH"
            else 4
        )
    except (
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def cmd_overlay_change_qualify_rollback(args: argparse.Namespace) -> int:
    """Execute the pinned qualification rollback without saving."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        record_path = (
            Path(args.qualification_record)
            if args.qualification_record
            else workspace.operation_root
            / "qualification"
            / "qualification-record.json"
        )
        record = load_qualification_record(record_path)
        pinned_inventory = Path(
            record["artifacts"]["inventory"]["path"]
        ).resolve()
        requested_inventory = Path(args.hosts).resolve()
        if requested_inventory != pinned_inventory:
            raise QualificationError(
                "--hosts must match the inventory pinned by qualification"
            )
        current_snapshot = (
            Path(args.current_snapshot)
            if args.current_snapshot
            else workspace.operation_root / "health" / "after" / "snapshot.json"
        )
        inventory_data = load_yaml(str(requested_inventory))
        inventory_list = load_inventory_data(inventory_data)
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory_list
        }
        target_devices = list(reversed(record["target"]["devices"]))
        preflight = preflight_operation_workspace(
            workspace,
            device_count=len(target_devices),
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise QualificationError(
                f"operation preflight failed: {details}"
            )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise QualificationRequiredError(
                "qualification rollback requires an interactive TTY"
            )

        print("=== INITIAL LAB QUALIFICATION ROLLBACK ===")
        print(f"Change ID : {workspace.change_id}")
        print("Devices   : " + ", ".join(target_devices))
        print(f"Snapshot  : {current_snapshot}")
        print("Serial    : 1 (reverse device order)")
        print("Save      : disabled")
        print("Retry     : disabled")
        phrase = f"ROLLBACK-QUALIFICATION {workspace.change_id}"
        print("Type the exact rollback phrase:")
        print(phrase)
        if input("> ").strip() != phrase:
            raise QualificationRequiredError(
                "exact qualification rollback phrase was not provided"
            )

        logger = setup_logging(
            args.log_file
            or str(
                workspace.operation_root
                / "qualification"
                / "rollback"
                / "rollback.log"
            ),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host,
                username,
                password,
                enable_secret,
                logger,
            )

        with OperationLock(workspace, "qualify-rollback") as lock:
            with OperationInterruptGuard(
                workspace,
                lock,
                phase="qualification_rollback",
            ) as interrupt_guard:
                execution = execute_qualification_rollback(
                    workspace,
                    record,
                    current_snapshot_path=current_snapshot,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=interrupt_guard,
                )
        print("Qualification rollback execution:")
        print(
            workspace.operation_root
            / "qualification"
            / "rollback"
            / "execution.json"
        )
        for host, result in execution["status"]["devices"].items():
            print(
                f"- {host}: {result['status']} "
                f"commands={len(result['commands'])}"
            )
        print(f"Result: {execution['status']['result']}")
        print("Configuration save: SKIPPED")
        print("Next: collect rollback health and verify raw/semantic diff.")
        return (
            0
            if execution["status"]["result"]
            == "ROLLED_BACK_PENDING_HEALTH"
            else 4
        )
    except (
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def cmd_overlay_change_qualify_save_baseline(
    args: argparse.Namespace,
) -> int:
    """Qualify NX-OS save only after verified baseline restoration."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        record_path = (
            Path(args.qualification_record)
            if args.qualification_record
            else workspace.operation_root
            / "qualification"
            / "qualification-record.json"
        )
        record = load_qualification_record(record_path)
        pinned_inventory = Path(
            record["artifacts"]["inventory"]["path"]
        ).resolve()
        requested_inventory = Path(args.hosts).resolve()
        if requested_inventory != pinned_inventory:
            raise QualificationError(
                "--hosts must match the inventory pinned by qualification"
            )
        inventory_data = load_yaml(str(requested_inventory))
        inventory_list = load_inventory_data(inventory_data)
        inventory_hosts = {
            str(host["hostname"]): host for host in inventory_list
        }
        target_devices = list(record["target"]["devices"])
        preflight = preflight_operation_workspace(
            workspace,
            device_count=len(target_devices),
            for_apply=True,
        )
        if not preflight.ok:
            details = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in preflight.issues
                if issue.severity == "ERROR"
            )
            raise QualificationError(
                f"operation preflight failed: {details}"
            )
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise QualificationRequiredError(
                "qualification baseline save requires an interactive TTY"
            )

        print("=== INITIAL LAB QUALIFICATION BASELINE SAVE ===")
        print(f"Change ID : {workspace.change_id}")
        print("Devices   : " + ", ".join(target_devices))
        print("Precheck  : before running-config and startup diff")
        print("Serial    : 1")
        print("Retry     : disabled")
        phrase = f"SAVE-QUALIFICATION-BASELINE {workspace.change_id}"
        print("Type the exact baseline save phrase:")
        print(phrase)
        if input("> ").strip() != phrase:
            raise QualificationRequiredError(
                "exact qualification baseline save phrase was not provided"
            )

        logger = setup_logging(
            args.log_file
            or str(
                workspace.operation_root
                / "qualification"
                / "save"
                / "save.log"
            ),
            args.verbose,
        )

        def connect(hostname: str) -> Any:
            host = inventory_hosts[hostname]
            username, password, enable_secret = get_credentials_for_device(
                args,
                str(host.get("device_type", "")),
                host,
            )
            return connect_to_host(
                host,
                username,
                password,
                enable_secret,
                logger,
            )

        with OperationLock(workspace, "qualify-save-baseline") as lock:
            with OperationInterruptGuard(
                workspace,
                lock,
                phase="qualification_save",
            ) as interrupt_guard:
                execution = execute_qualification_baseline_save(
                    workspace,
                    record,
                    inventory_hosts=inventory_hosts,
                    connect=connect,
                    disconnect=lambda connection: connection.disconnect(),
                    save_command=get_save_config_command("nxos"),
                    success_marker=get_save_config_success_marker("nxos"),
                    lock=lock,
                    now=lambda: now_in_timezone(workspace.timezone),
                    interrupt_guard=interrupt_guard,
                )
        print("Qualification baseline save execution:")
        print(
            workspace.operation_root
            / "qualification"
            / "save"
            / "execution.json"
        )
        for host, result in execution["status"]["devices"].items():
            print(f"- {host}: {result['status']}")
        print(f"Result: {execution['status']['result']}")
        return (
            0
            if execution["status"]["result"]
            == "QUALIFICATION_SAVE_SUCCEEDED"
            else 4
        )
    except (
        QualificationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)
        return 2


def _write_overlay_conflict_report(
    operation_root: Path,
    artifact_dir: Path,
    report: Mapping[str, Any],
) -> tuple[Path, Path]:
    json_path = artifact_dir / "conflict-report.json"
    markdown_path = artifact_dir / "conflict-report.md"
    atomic_write_json(
        operation_root,
        json_path,
        report,
        kind="OverlayConflictReport",
    )
    atomic_write_bytes(
        operation_root,
        markdown_path,
        render_conflict_report_markdown(report).encode("utf-8"),
    )
    return json_path, markdown_path


def cmd_overlay_change_prepare_plan(args: argparse.Namespace) -> None:
    """Build a preparation-only plan from one prior healthy terminal state."""
    workspace = None
    try:
        loaded_change_set = load_overlay_change_set(Path(args.change_set))
        change_set = loaded_change_set.document
        change_id = change_set["metadata"]["change_id"]
        operation_root = Path(args.operations_root) / change_id
        workspace = (
            open_operation_workspace(args.operations_root, change_id)
            if operation_root.exists()
            else create_operation_workspace(
                args.operations_root,
                change_id=change_id,
            )
        )
        metadata = load_operation_metadata(workspace.operation_root)
        if metadata["spec"]["workflow_state"] is not None:
            raise OperationStateError(
                "prepare-plan requires an operation before the normal plan workflow"
            )
        previous_phase = metadata["spec"]["phases"].get("prepare_plan")
        current_path = workspace.operation_root / "preparation" / "current.json"
        if current_path.exists() or (
            previous_phase
            and previous_phase["status"] in {"completed", "completed_with_warnings"}
        ):
            raise OperationStateError(
                "a completed prepare-plan already exists and will not be overwritten"
            )
        if previous_phase and previous_phase["status"] in {
            "running",
            "waiting_for_user",
        }:
            raise OperationStateError("a prepare-plan attempt is already in progress")
        evaluated_at = now_in_timezone(workspace.timezone)
        attempt_id = generate_attempt_id(
            "prepare-plan",
            workspace.timezone,
            now=evaluated_at,
        )
        preparation_dir = (
            workspace.operation_root
            / "preparation"
            / "attempts"
            / attempt_id
        )
        preparation_artifact_dir = f"preparation/attempts/{attempt_id}"
        target_hosts = sorted(resolve_changeset(change_set))

        with OperationLock(workspace, "overlay-change-prepare-plan") as lock:
            transition_phase(
                workspace,
                "prepare_plan",
                "running",
                lock=lock,
                attempt_id=attempt_id,
                reason="offline_reference_selection_started",
                now=evaluated_at,
                allow_retry=previous_phase is not None,
            )
            attempt_result = {
                "schema_version": 1,
                "change_id": change_id,
                "attempt_id": attempt_id,
                "status": "RUNNING",
                "started_at": evaluated_at.isoformat(timespec="seconds"),
                "artifact_dir": str(preparation_dir),
            }
            atomic_write_json(
                workspace.operation_root,
                preparation_dir / "result.json",
                attempt_result,
                kind="OverlayPreparationAttempt",
            )
            try:
                selected = select_reference_state(
                    args.operations_root,
                    current_change_id=change_id,
                    target_hosts=target_hosts,
                    evaluated_at=evaluated_at,
                    max_age_days=args.reference_max_age_days,
                    reference_state=args.reference_state,
                    reference_operation_id=args.reference_operation_id,
                    reference_phase=args.reference_phase,
                )
                atomic_write_json(
                    workspace.operation_root,
                    preparation_dir / "reference-state.json",
                    selected.document,
                    kind="OverlayReferenceState",
                )
                conflict_report = assess_overlay_conflicts(
                    change_set,
                    selected.snapshot,
                )
                conflict_path, _conflict_markdown = (
                    _write_overlay_conflict_report(
                        workspace.operation_root,
                        preparation_dir,
                        conflict_report,
                    )
                )
                require_conflict_free(conflict_report)

                render_snapshot = deepcopy(selected.snapshot)
                render_snapshot["change_id"] = change_id
                rendered = render_changeset(change_set, render_snapshot)
                input_manifest, _resolved_targets = write_overlay_plan_inputs(
                    workspace.operation_root,
                    loaded_change_set,
                    artifact_dir=preparation_artifact_dir,
                    inputs_dir=f"{preparation_artifact_dir}/inputs",
                )
                manifest = write_rendered_configs(
                    workspace.operation_root,
                    change_id,
                    rendered,
                    artifact_dir=preparation_artifact_dir,
                    config_dir=f"{preparation_artifact_dir}/generated-config",
                    rollback_dir=f"{preparation_artifact_dir}/rollback-config",
                    input_hashes={
                        "change_set": input_manifest["change_set"][
                            "resolved_canonical_sha256"
                        ],
                        "device_groups": input_manifest["device_groups"][
                            "resolved_canonical_sha256"
                        ],
                        "reference_state": selected.document["source"][
                            "snapshot_sha256"
                        ],
                        "conflict_report": source_sha256(conflict_path),
                    },
                )
                devices = {
                    host: {
                        "status": (
                            "NO_CHANGE"
                            if not result.forward_config
                            else "PLANNED"
                        ),
                        "forward_config": manifest["devices"][host][
                            "forward_config"
                        ],
                        "forward_sha256": result.forward_sha256,
                        "model_sha256": result.model_sha256,
                        "actions": list(result.actions),
                    }
                    for host, result in sorted(rendered.items())
                }
                rollback_devices = {
                    host: {
                        "status": (
                            "NO_CHANGE"
                            if not result.rollback_config
                            else "PLANNED"
                        ),
                        "rollback_config": manifest["devices"][host][
                            "rollback_config"
                        ],
                        "rollback_sha256": result.rollback_sha256,
                        "actions": list(result.actions),
                    }
                    for host, result in sorted(rendered.items())
                }
                execution = {
                    "schema_version": 1,
                    "change_id": change_id,
                    "preparation_only": True,
                    "capability_level": "PLAN_ONLY",
                    "devices": devices,
                    "warnings": [
                        {
                            "code": "PREPARATION_ONLY",
                            "message": (
                                "Collect a fresh before Snapshot and run normal "
                                "overlay-change plan before approval or apply"
                            ),
                        }
                    ],
                    "artifacts": {
                        "reference_state": str(
                            preparation_dir / "reference-state.json"
                        ),
                        "conflict_report": str(conflict_path),
                        "input_manifest": str(
                            preparation_dir / "input-manifest.json"
                        ),
                        "resolved_targets": str(
                            preparation_dir / "resolved-targets.yaml"
                        ),
                        "render_manifest": str(
                            preparation_dir / "render-manifest.json"
                        ),
                    },
                    "constraints": {
                        "preparation_only": True,
                        "approval_allowed": False,
                        "fresh_before_required": True,
                    },
                }
                rollback = {
                    "schema_version": 1,
                    "change_id": change_id,
                    "policy": "manual",
                    "devices": rollback_devices,
                    "ownership": {
                        "scope": "preparation_reference_only",
                        "source": "render-manifest.json",
                    },
                    "artifacts": {
                        "reference_state": str(
                            preparation_dir / "reference-state.json"
                        ),
                        "render_manifest": str(
                            preparation_dir / "render-manifest.json"
                        ),
                    },
                    "verification": {
                        "fresh_before_required": True,
                        "approval_allowed": False,
                    },
                }
                atomic_write_json(
                    workspace.operation_root,
                    preparation_dir / "execution-plan.json",
                    execution,
                    kind="ExecutionPlan",
                )
                atomic_write_json(
                    workspace.operation_root,
                    preparation_dir / "rollback-plan.json",
                    rollback,
                    kind="RollbackPlan",
                )
                completed_at = now_in_timezone(workspace.timezone)
                attempt_result.update(
                    {
                        "status": "PASS",
                        "completed_at": completed_at.isoformat(timespec="seconds"),
                    }
                )
                atomic_write_json(
                    workspace.operation_root,
                    preparation_dir / "result.json",
                    attempt_result,
                    kind="OverlayPreparationAttempt",
                )
                atomic_write_json(
                    workspace.operation_root,
                    workspace.operation_root / "preparation" / "current.json",
                    {
                        "schema_version": 1,
                        "change_id": change_id,
                        "attempt_id": attempt_id,
                        "artifact_dir": str(preparation_dir),
                        "completed_at": completed_at.isoformat(timespec="seconds"),
                    },
                    kind="OverlayPreparationCurrent",
                )
                transition_phase(
                    workspace,
                    "prepare_plan",
                    "completed",
                    lock=lock,
                    reason="preparation_only_plan_completed",
                    now=completed_at,
                )
            except Exception as exc:
                failed_at = now_in_timezone(workspace.timezone)
                error = {
                    "code": getattr(exc, "code", "VALIDATION_ERROR"),
                    "message": str(exc),
                    "phase": "prepare_plan",
                    "attempt_id": attempt_id,
                    "at": failed_at.isoformat(timespec="seconds"),
                }
                record_operation_error(workspace, error, lock=lock)
                attempt_result.update(
                    {
                        "status": "FAILED",
                        "completed_at": failed_at.isoformat(timespec="seconds"),
                        "error": {
                            "code": error["code"],
                            "message": error["message"],
                        },
                    }
                )
                atomic_write_json(
                    workspace.operation_root,
                    preparation_dir / "result.json",
                    attempt_result,
                    kind="OverlayPreparationAttempt",
                )
                transition_phase(
                    workspace,
                    "prepare_plan",
                    "failed",
                    lock=lock,
                    reason="preparation_only_plan_failed",
                    now=failed_at,
                )
                raise

        print("=== OVERLAY PREPARATION PLAN ===")
        print(f"Change ID       : {change_id}")
        print(
            "Reference       : "
            f"{selected.document['source']['operation_id']} "
            f"({selected.document['source']['phase']})"
        )
        print(f"Reference age   : {selected.document['age']['days']} days")
        print(f"Conflict check  : {conflict_report['result']}")
        print(f"Devices         : {len(devices)}")
        print(f"Execution plan  : {preparation_dir / 'execution-plan.json'}")
        print(f"Generated config: {preparation_dir / 'generated-config'}")
        print("Apply            : BLOCKED (fresh before and normal plan required)")
    except (
        OverlayConflictError,
        ReferenceStateError,
        OverlayRenderError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def _read_overlay_plan_artifact(path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise OperationStateError(
            f"required {kind} artifact is missing or unsafe: {path}"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise OperationStateError(f"{kind} artifact must be an object: {path}")
    validate_document(document, kind=kind)
    return document


def _current_path_has_expected_suffix(
    raw_path: str,
    expected_relative: Path,
) -> bool:
    raw_parts = Path(raw_path).parts
    suffix = expected_relative.parts
    return len(raw_parts) >= len(suffix) and raw_parts[-len(suffix) :] == suffix


def _validate_overlay_plan_health_result(
    health: Mapping[str, Any],
    *,
    change_id: str,
    require_gate_decision: bool = True,
) -> None:
    if health.get("change_id") != change_id or health.get("phase") != "before":
        raise OperationStateError("before HealthResult operation identity mismatch")
    result = health.get("result")
    if result not in {"PASS", "WARN"}:
        raise OperationStateError(
            f"before HealthResult {result!r} is not eligible for plan"
        )
    gate = health.get("operation_gate", {})
    if (
        require_gate_decision
        and isinstance(gate, Mapping)
        and gate.get("required")
    ):
        decision = gate.get("decision")
        if not isinstance(decision, Mapping) or decision.get("action") != "continue":
            raise OperationStateError(
                "before operation gate requires a recorded continue decision"
            )


def _resolve_overlay_plan_before(
    args: argparse.Namespace,
    change_id: str,
) -> tuple[Any, dict[str, Any], Path, dict[str, str]]:
    workspace = open_operation_workspace(args.operations_root, change_id)
    phase_root = workspace.operation_root / "health" / "before"
    expected_before = phase_root / "snapshot.json"
    explicit_before = getattr(args, "before", None)
    if (
        explicit_before is not None
        and Path(explicit_before).resolve() != expected_before.resolve()
    ):
        raise OperationPathError(
            f"--before must be the current operation Snapshot: {expected_before}"
        )

    metadata = load_operation_metadata(workspace.operation_root)
    phase = metadata["spec"].get("phases", {}).get("before")
    if not isinstance(phase, Mapping) or phase.get("status") not in {
        "completed",
        "completed_with_warnings",
    }:
        status = phase.get("status") if isinstance(phase, Mapping) else "not_started"
        raise OperationStateError(
            f"latest before phase is not completed: {status}"
        )

    current_path = phase_root / "current.json"
    if current_path.exists() or current_path.is_symlink():
        current = _read_overlay_plan_artifact(current_path, "HealthPhaseCurrent")
        attempt_id = current["attempt_id"]
        if current["change_id"] != change_id or current["phase"] != "before":
            raise OperationStateError("before current pointer identity mismatch")
        if phase.get("current_attempt") != attempt_id:
            raise OperationStateError(
                "latest before attempt does not match the successful current pointer"
            )
        attempt_relative = Path("health/before/attempts") / attempt_id
        attempt_dir = workspace.operation_root / attempt_relative
        attempt_snapshot = attempt_dir / "snapshot.json"
        attempt_health_path = attempt_dir / "health-result.json"
        attempt_result_path = attempt_dir / "result.json"
        if not _current_path_has_expected_suffix(
            current["artifact_dir"], attempt_relative
        ) or not _current_path_has_expected_suffix(
            current["snapshot_path"], attempt_relative / "snapshot.json"
        ):
            raise OperationStateError(
                "before current pointer contains an unexpected artifact path"
            )
        attempt_result = _read_overlay_plan_artifact(
            attempt_result_path, "HealthPhaseAttempt"
        )
        if (
            attempt_result.get("change_id") != change_id
            or attempt_result.get("attempt_id") != attempt_id
            or attempt_result.get("status") != "COMPLETED"
        ):
            raise OperationStateError("before attempt result is not completed")
        attempt_before = _read_overlay_plan_artifact(
            attempt_snapshot, "HealthSnapshot"
        )
        before = _read_overlay_plan_artifact(expected_before, "HealthSnapshot")
        expected_hash = current["snapshot_sha256"]
        if (
            source_sha256(attempt_snapshot) != expected_hash
            or source_sha256(expected_before) != expected_hash
        ):
            raise OperationStateError(
                "before Snapshot hash does not match the current pointer"
            )
        if attempt_before != before:
            raise OperationStateError(
                "published before Snapshot differs from the current attempt"
            )
        attempt_health = _read_overlay_plan_artifact(
            attempt_health_path, "HealthResult"
        )
        health = _read_overlay_plan_artifact(
            phase_root / "health-result.json", "HealthResult"
        )
        _validate_overlay_plan_health_result(
            attempt_health,
            change_id=change_id,
            require_gate_decision=False,
        )
        _validate_overlay_plan_health_result(health, change_id=change_id)
        if (
            attempt_health.get("result") != current["health_result"]
            or health.get("result") != current["health_result"]
            or attempt_result.get("health_result") != current["health_result"]
        ):
            raise OperationStateError(
                "before HealthResult does not match the current pointer"
            )
        if (
            before.get("change_id") != change_id
            or before.get("phase") != "before"
            or before.get("profile_sha256") != current["profile_sha256"]
            or attempt_result.get("profile_sha256") != current["profile_sha256"]
        ):
            raise OperationStateError(
                "before Snapshot profile or operation identity mismatch"
            )
        result = current["health_result"]
    else:
        before = _read_overlay_plan_artifact(expected_before, "HealthSnapshot")
        health = _read_overlay_plan_artifact(
            phase_root / "health-result.json", "HealthResult"
        )
        _validate_overlay_plan_health_result(health, change_id=change_id)
        if before.get("change_id") != change_id or before.get("phase") != "before":
            raise OperationStateError("before Snapshot operation identity mismatch")
        attempt_id = str(phase.get("current_attempt") or "legacy")
        result = str(health["result"])

    return workspace, before, expected_before, {
        "source": (
            "explicit --before"
            if explicit_before is not None
            else "inferred from ChangeSet change_id"
        ),
        "attempt_id": attempt_id,
        "health_result": result,
    }


def cmd_overlay_change_plan(args: argparse.Namespace) -> None:
    """Build a PLAN_ONLY execution/rollback plan from a declared ChangeSet."""
    try:
        change_set_path = Path(args.change_set)
        loaded_change_set = load_overlay_change_set(change_set_path)
        change_set = loaded_change_set.document
        change_id = change_set.get("metadata", {}).get("change_id")
        if not isinstance(change_id, str) or not change_id:
            raise OverlayRenderError("ChangeSet metadata.change_id is required")
        workspace, before, expected_before, before_selection = (
            _resolve_overlay_plan_before(args, change_id)
        )
        plan_dir = workspace.operation_root / "plan"
        execution_path = plan_dir / "execution-plan.json"
        rollback_path = plan_dir / "rollback-plan.json"
        if (
            execution_path.exists()
            or rollback_path.exists()
            or (plan_dir / "input-manifest.json").exists()
            or (plan_dir / "resolved-targets.yaml").exists()
        ):
            raise OperationStateError("plan artifacts already exist")
        conflict_report = assess_overlay_conflicts(change_set, before)
        conflict_path, _conflict_markdown = _write_overlay_conflict_report(
            workspace.operation_root,
            plan_dir,
            conflict_report,
        )
        require_conflict_free(conflict_report)
        rendered = render_changeset(change_set, before)
        input_manifest, _resolved_targets = write_overlay_plan_inputs(
            workspace.operation_root,
            loaded_change_set,
        )
        manifest = write_rendered_configs(
            workspace.operation_root,
            workspace.change_id,
            rendered,
            input_hashes={
                "change_set": input_manifest["change_set"][
                    "resolved_canonical_sha256"
                ],
                "device_groups": input_manifest["device_groups"][
                    "resolved_canonical_sha256"
                ],
                "input_manifest": source_sha256(
                    plan_dir / "input-manifest.json"
                ),
                "resolved_targets": input_manifest["resolved_targets"][
                    "canonical_sha256"
                ],
                "conflict_report": source_sha256(conflict_path),
            },
        )
        devices = {
            host: {
                "status": (
                    "NO_CHANGE"
                    if not result.forward_config
                    else "PLANNED"
                ),
                "forward_config": manifest["devices"][host][
                    "forward_config"
                ],
                "forward_sha256": result.forward_sha256,
                "model_sha256": result.model_sha256,
                "actions": list(result.actions),
            }
            for host, result in sorted(rendered.items())
        }
        rollback_devices = {
            host: {
                "status": (
                    "NO_CHANGE"
                    if not result.rollback_config
                    else "PLANNED"
                ),
                "rollback_config": manifest["devices"][host][
                    "rollback_config"
                ],
                "rollback_sha256": result.rollback_sha256,
                "actions": list(result.actions),
            }
            for host, result in sorted(rendered.items())
        }
        registry = load_capability_registry(args.capability_registry)
        capability = evaluate_capability(
            registry,
            before,
            sorted(rendered),
            required_overlay_capabilities(change_set),
        )
        capability_path = plan_dir / "capability-evaluation.json"
        atomic_write_bytes(
            workspace.operation_root,
            capability_path,
            (
                json.dumps(
                    capability,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        capability_level = capability["level"]
        inventory_path = None
        inventory_sha256 = None
        if capability_level == "APPLY_VERIFIED":
            if not args.hosts:
                raise CapabilityError(
                    "APPLY_VERIFIED plan requires --hosts to pin inventory"
                )
            inventory_document = load_yaml(args.hosts)
            inventory_path = plan_dir / "inventory.yaml"
            atomic_write_bytes(
                workspace.operation_root,
                inventory_path,
                yaml.safe_dump(
                    inventory_document,
                    sort_keys=False,
                    allow_unicode=True,
                ).encode("utf-8"),
            )
            inventory_sha256 = source_sha256(inventory_path)
        warnings = []
        if capability_level != "APPLY_VERIFIED":
            warnings.append(
                {
                    "code": "APPLY_CAPABILITY_UNVERIFIED",
                    "message": (
                        "One or more exact model/release/role capability "
                        "sets are not APPLY_VERIFIED"
                    ),
                }
            )
        approval_artifacts = {
            "change_set": str(
                workspace.operation_root
                / input_manifest["change_set"]["pinned_path"]
            ),
            "input_manifest": str(plan_dir / "input-manifest.json"),
            "resolved_targets": str(plan_dir / "resolved-targets.yaml"),
            "conflict_report": str(conflict_path),
        }
        pinned_groups = input_manifest["device_groups"].get("pinned_path")
        if pinned_groups:
            approval_artifacts["device_groups"] = str(
                workspace.operation_root / pinned_groups
            )
        execution_plan = {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "capability_level": capability_level,
            "devices": devices,
            "warnings": warnings,
            "artifacts": {
                "change_set": approval_artifacts["change_set"],
                "before_snapshot": str(expected_before),
                "input_manifest": str(plan_dir / "input-manifest.json"),
                "resolved_targets": str(plan_dir / "resolved-targets.yaml"),
                "conflict_report": str(conflict_path),
                "device_groups": approval_artifacts.get("device_groups"),
                "approval_artifacts": approval_artifacts,
                "render_manifest": str(
                    plan_dir / "render-manifest.json"
                ),
                "capability_evaluation": str(capability_path),
                "inventory": str(inventory_path) if inventory_path else None,
                "inventory_sha256": inventory_sha256,
            },
            "constraints": {
                "serial": 1,
                "max_devices": 50,
                "requires_interactive_approval": True,
                "save_after_health_check_only": True,
            },
        }
        rollback_plan = {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "policy": "manual",
            "devices": rollback_devices,
            "ownership": {
                "scope": "operation_owned_resources_only",
                "source": "render-manifest.json",
            },
            "artifacts": {
                "before_snapshot": str(expected_before),
                "render_manifest": str(
                    plan_dir / "render-manifest.json"
                ),
            },
            "verification": {
                "running_config_diff": "required",
                "health_check": "required",
                "expected_difference": "none",
            },
        }
        started_at = now_in_timezone(workspace.timezone)
        with OperationLock(workspace, "overlay-change-plan") as lock:
            metadata = load_operation_metadata(workspace.operation_root)
            if metadata["spec"]["workflow_state"] is None:
                transition_workflow(
                    workspace,
                    "planned",
                    lock=lock,
                    reason="overlay_plan_started",
                    now=started_at,
                )
                transition_workflow(
                    workspace,
                    "before_running",
                    lock=lock,
                    reason="existing_before_snapshot_selected",
                    now=started_at,
                )
                transition_workflow(
                    workspace,
                    "before_completed",
                    lock=lock,
                    reason="existing_before_snapshot_validated",
                    now=started_at,
                )
            atomic_write_json(
                workspace.operation_root,
                execution_path,
                execution_plan,
                kind="ExecutionPlan",
            )
            atomic_write_json(
                workspace.operation_root,
                rollback_path,
                rollback_plan,
                kind="RollbackPlan",
            )
            transition_workflow(
                workspace,
                "plan_ready",
                lock=lock,
                reason="execution_and_rollback_plans_created",
                now=now_in_timezone(workspace.timezone),
            )
        print("=== OVERLAY CHANGE PLAN ===")
        print(f"Change ID       : {workspace.change_id}")
        print(f"Before source   : {before_selection['source']}")
        print(f"Before attempt  : {before_selection['attempt_id']}")
        print(f"Before snapshot : {expected_before}")
        print(f"Before result   : {before_selection['health_result']}")
        print(f"Capability      : {capability_level}")
        print(f"Devices         : {len(devices)}")
        for host, device in devices.items():
            config_path = (
                workspace.operation_root / device["forward_config"]
                if device["forward_config"]
                else "-"
            )
            print(
                f"- {host}: {device['status']} "
                f"config={config_path}"
            )
        print(f"Execution plan  : {execution_path}")
        print(f"Rollback plan   : {rollback_path}")
        print(f"Render manifest : {plan_dir / 'render-manifest.json'}")
        print(f"Input manifest  : {plan_dir / 'input-manifest.json'}")
        print(f"Resolved targets: {plan_dir / 'resolved-targets.yaml'}")
        print(f"Conflict report : {conflict_path}")
        print(f"Capability proof : {capability_path}")
        print(
            "Apply            : "
            + (
                "ELIGIBLE FOR APPROVAL"
                if capability_level == "APPLY_VERIFIED"
                else "BLOCKED (APPLY_VERIFIED evidence required)"
            )
        )
    except (
        CapabilityError,
        OverlayConflictError,
        OverlayRenderError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def _snapshot_workspace(args: argparse.Namespace):
    operations_root = Path(args.operations_root)
    if args.phase != "before" and not args.change_id:
        raise OperationStateError(
            f"health-check snapshot --phase {args.phase} requires --change-id"
        )
    if args.change_id:
        operation_root = operations_root / args.change_id
        if operation_root.exists():
            workspace = open_operation_workspace(
                operations_root,
                args.change_id,
            )
        elif args.phase == "before":
            workspace = create_operation_workspace(
                operations_root,
                change_id=args.change_id,
                timezone_name=args.timezone,
            )
        else:
            raise OperationPathError(
                f"operation does not exist: {operation_root}"
            )
    else:
        workspace = create_operation_workspace(
            operations_root,
            timezone_name=args.timezone,
        )
    phase_directory = (
        f"{args.phase}-recheck"
        if bool(getattr(args, "recheck", False))
        else args.phase
    )
    attempt_id = getattr(args, "_health_attempt_id", None)
    if args.phase in {"before", "rollback"} and attempt_id:
        expected_output = (
            workspace.operation_root
            / "health"
            / args.phase
            / "attempts"
            / attempt_id
        )
    else:
        expected_output = workspace.operation_root / "health" / phase_directory
    if args.output and Path(args.output).resolve() != expected_output.resolve():
        raise OperationPathError(
            f"--output must match the operation phase path: {expected_output}"
        )
    return workspace, expected_output


def _logging_time_range_from_args(
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    if bool(getattr(args, "logging_all", False)):
        return {"mode": "all"}
    days = getattr(args, "logging_days", None)
    if days is not None:
        if days < 1:
            raise ProfileResolutionError("--logging-days must be at least 1")
        return {"mode": "days", "days": days}
    start_text = getattr(args, "logging_start_time", None)
    if start_text is None:
        return None
    try:
        start_time = datetime.fromisoformat(start_text)
    except ValueError as exc:
        raise ProfileResolutionError(
            "--logging-start-time must be an ISO 8601 datetime"
        ) from exc
    if start_time.tzinfo is None:
        raise ProfileResolutionError(
            "--logging-start-time must include a timezone offset"
        )
    return {
        "mode": "start-time",
        "start_time": start_time.isoformat(timespec="seconds"),
    }


def _add_logging_time_range_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--logging-all",
        action="store_true",
        help=(
            "Check all timestamped show logging records "
            "(initial before or explicit profile revision)"
        ),
    )
    group.add_argument(
        "--logging-days",
        type=int,
        metavar="DAYS",
        help=(
            "Check records from DAYS before Snapshot time "
            "(initial before or explicit profile revision)"
        ),
    )
    group.add_argument(
        "--logging-start-time",
        metavar="ISO8601",
        help=(
            "Check records since a timezone-aware ISO 8601 time "
            "(initial before or explicit profile revision)"
        ),
    )


def _inherit_fixed_logging_time_range(
    requested: dict[str, Any],
    fixed: Mapping[str, Any],
) -> dict[str, Any]:
    fixed_logging = fixed["spec"]["resolved"]["effective"]["spec"].get(
        "thresholds",
        {},
    ).get("logging", {})
    time_range = fixed_logging.get("time_range")
    if time_range is None:
        return requested
    return apply_logging_time_range_override(requested, time_range)


def cmd_health_check_snapshot(args: argparse.Namespace) -> int:
    """Build a Snapshot from existing files without device access."""
    try:
        workspace, output_dir = _snapshot_workspace(args)
        args.change_id = workspace.change_id
        if (
            args.timezone is not None
            and workspace.timezone != resolve_timezone_name(args.timezone)
        ):
            raise OperationStateError(
                "requested timezone does not match operation metadata"
            )
        metadata = load_operation_metadata(workspace.operation_root)
        phase_state = (
            f"{args.phase}_recheck"
            if bool(getattr(args, "recheck", False))
            else args.phase
        )
        retrying_phase = bool(
            args.phase in {"before", "rollback"}
            and getattr(args, "_health_attempt_id", None)
            and phase_state in metadata["spec"]["phases"]
        )
        retrying_before = bool(args.phase == "before" and retrying_phase)
        if phase_state in metadata["spec"]["phases"] and not retrying_phase:
            raise OperationStateError(
                f"phase already exists and will not be overwritten: "
                f"{phase_state}"
            )
        started_at = now_in_timezone(workspace.timezone)
        logging_time_range = _logging_time_range_from_args(args)
        resolved_path = (
            workspace.operation_root / "health" / "resolved-profiles.yaml"
        )
        if args.phase == "before":
            supplied_profiles = getattr(args, "_health_resolved_profiles", None)
            if supplied_profiles is not None:
                resolved_profiles = supplied_profiles
            elif bool(getattr(args, "recheck", False)):
                if logging_time_range is not None:
                    raise OperationStateError(
                        "logging range options cannot override a before recheck"
                    )
                resolved_profiles = load_resolved_profiles(resolved_path)
                if args.profile:
                    requested_profiles = resolve_profiles(
                        args.profile,
                        change_id=workspace.change_id,
                        resolved_at=started_at,
                        timezone=workspace.timezone,
                    )
                    requested_profiles = _inherit_fixed_logging_time_range(
                        requested_profiles,
                        resolved_profiles,
                    )
                    if (
                        requested_profiles["spec"]["resolved"]["effective_sha256"]
                        != resolved_profiles["spec"]["resolved"]["effective_sha256"]
                    ):
                        raise ProfileResolutionError(
                            "recheck profile does not match fixed before profile"
                        )
            else:
                if resolved_path.exists() and retrying_before:
                    resolved_profiles = load_resolved_profiles(resolved_path)
                    fixed_range = (
                        resolved_profiles["spec"]["resolved"]["effective"][
                            "spec"
                        ]
                        .get("thresholds", {})
                        .get("logging", {})
                        .get("time_range")
                    )
                    if (
                        logging_time_range is not None
                        and logging_time_range != fixed_range
                    ):
                        raise ProfileResolutionError(
                            "before retry logging range does not match the "
                            "fixed profile; use a new change ID"
                        )
                    requested_profiles = resolve_profiles(
                        args.profile or [DEFAULT_HEALTH_PROFILE],
                        change_id=workspace.change_id,
                        resolved_at=started_at,
                        resolution_source=(
                            "explicit" if args.profile else "default"
                        ),
                        timezone=workspace.timezone,
                    )
                    requested_profiles = _inherit_fixed_logging_time_range(
                        requested_profiles,
                        resolved_profiles,
                    )
                    if (
                        requested_profiles["spec"]["resolved"][
                            "effective_sha256"
                        ]
                        != resolved_profiles["spec"]["resolved"][
                            "effective_sha256"
                        ]
                    ):
                        raise ProfileResolutionError(
                            "before retry profile does not match fixed profile; "
                            "use a new change ID for policy changes"
                        )
                else:
                    if resolved_path.exists():
                        raise OperationStateError(
                            f"resolved profile already exists: {resolved_path}"
                        )
                    resolved_profiles = resolve_profiles(
                        args.profile or [DEFAULT_HEALTH_PROFILE],
                        change_id=workspace.change_id,
                        resolved_at=started_at,
                        resolution_source=(
                            "explicit" if args.profile else "default"
                        ),
                        timezone=workspace.timezone,
                    )
                    if logging_time_range is not None:
                        resolved_profiles = apply_logging_time_range_override(
                            resolved_profiles, logging_time_range
                        )
        else:
            if logging_time_range is not None:
                raise OperationStateError(
                    "logging range options are valid only for the initial before"
                )
            resolved_profiles = load_resolved_profiles(resolved_path)
            if args.profile:
                requested_profiles = resolve_profiles(
                    args.profile,
                    change_id=workspace.change_id,
                    resolved_at=started_at,
                    timezone=workspace.timezone,
                )
                requested_profiles = _inherit_fixed_logging_time_range(
                    requested_profiles,
                    resolved_profiles,
                )
                if (
                    requested_profiles["spec"]["resolved"]["effective_sha256"]
                    != resolved_profiles["spec"]["resolved"]["effective_sha256"]
                ):
                    raise ProfileResolutionError(
                        "after profile does not match fixed before profile"
                    )
        profile_names = resolved_profiles["spec"]["resolved"]["profile_names"]
        profile_sha256 = resolved_profiles["spec"]["resolved"][
            "effective_sha256"
        ]
        attempt_id = getattr(args, "_health_attempt_id", None) or generate_attempt_id(
            args.phase,
            workspace.timezone,
            now=started_at,
        )
        collection_id = f"{workspace.change_id}-{attempt_id}"
        overlay_state = None
        with OperationLock(workspace, f"health-check-snapshot-{args.phase}") as lock:
            preflight = preflight_operation_workspace(workspace)
            if not preflight.ok:
                details = "; ".join(
                    f"{issue.code}: {issue.message}"
                    for issue in preflight.issues
                    if issue.severity == "ERROR"
                )
                raise OperationStateError(
                    f"operation preflight failed: {details}"
                )
            if metadata["spec"]["lifecycle"] == "created":
                transition_operation(
                    workspace,
                    "running",
                    lock=lock,
                    reason="health_snapshot_started",
                    now=started_at,
                )
            transition_phase(
                workspace,
                phase_state,
                "running",
                lock=lock,
                attempt_id=attempt_id,
                reason="offline_snapshot_started",
                now=started_at,
                allow_retry=retrying_phase,
            )
            try:
                completed_at = now_in_timezone(workspace.timezone)
                import_manifest = None
                if args.input_format == "alred-collect":
                    manifest = build_collect_manifest(
                        args.input,
                        collection_id=collection_id,
                        change_id=workspace.change_id,
                        phase=args.phase,
                        profiles=profile_names,
                        started_at=started_at,
                        completed_at=completed_at,
                        timezone=workspace.timezone,
                    )
                else:
                    import_manifest, manifest = import_nxos_transcripts(
                        args.input,
                        collection_id=collection_id,
                        change_id=workspace.change_id,
                        phase=args.phase,
                        profiles=profile_names,
                        imported_at=completed_at,
                        timezone=workspace.timezone,
                        hosts_path=args.hosts,
                    )
                snapshot = build_health_snapshot(
                    manifest,
                    profile_refs=profile_names,
                    created_at=completed_at,
                    timezone=workspace.timezone,
                    profile_sha256=profile_sha256,
                )
                health_result = evaluate_snapshot(
                    snapshot,
                    resolved_profiles,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                if (
                    args.phase == "before"
                    and not resolved_path.exists()
                    and getattr(args, "_health_attempt_id", None) is None
                ):
                    atomic_write_yaml(
                        workspace.operation_root,
                        resolved_path,
                        resolved_profiles,
                        kind="ResolvedHealthCheckProfiles",
                    )
                atomic_write_yaml(
                    workspace.operation_root,
                    output_dir / "collection-manifest.yaml",
                    manifest,
                    kind="CollectionManifest",
                )
                if import_manifest is not None:
                    atomic_write_yaml(
                        workspace.operation_root,
                        output_dir / "transcript-import-manifest.yaml",
                        import_manifest,
                        kind="TranscriptImportManifest",
                    )
                atomic_write_json(
                    workspace.operation_root,
                    output_dir / "snapshot.json",
                    snapshot,
                    kind="HealthSnapshot",
                )
                atomic_write_json(
                    workspace.operation_root,
                    output_dir / "health-result.json",
                    health_result,
                    kind="HealthResult",
                )
                atomic_write_bytes(
                    workspace.operation_root,
                    output_dir / "checklist.md",
                    render_health_checklist(health_result).encode("utf-8"),
                )
                if overlay_profile_enabled(profile_names):
                    overlay_state = build_overlay_state(snapshot)
                    atomic_write_yaml(
                        workspace.operation_root,
                        output_dir / "overlay-state.yaml",
                        overlay_state,
                        kind="OverlayState",
                    )
                    atomic_write_bytes(
                        workspace.operation_root,
                        output_dir / "vni-map.md",
                        render_overlay_state_markdown(overlay_state).encode(
                            "utf-8"
                        ),
                    )
                    atomic_write_bytes(
                        workspace.operation_root,
                        output_dir / "vni-map.csv",
                        overlay_state_csv(overlay_state).encode("utf-8"),
                    )
                warning_count = sum(
                    len(host["parse_warnings"])
                    for host in snapshot["hosts"].values()
                )
                phase_result = (
                    "completed_with_warnings"
                    if warning_count or health_result["result"] != "PASS"
                    else "completed"
                )
                transition_phase(
                    workspace,
                    phase_state,
                    phase_result,
                    lock=lock,
                    reason="offline_snapshot_completed",
                    now=completed_at,
                )
            except Exception as exc:
                failed_at = now_in_timezone(workspace.timezone)
                transition_phase(
                    workspace,
                    phase_state,
                    "failed",
                    lock=lock,
                    reason="offline_snapshot_failed",
                    now=failed_at,
                )
                record_operation_error(
                    workspace,
                    {
                        "code": getattr(exc, "code", "PARSER_ERROR"),
                        "phase": args.phase,
                        "at": failed_at.isoformat(timespec="seconds"),
                        "message": str(exc),
                    },
                    lock=lock,
                )
                raise
        print("=== HEALTH SNAPSHOT SUMMARY ===")
        print(f"Change ID : {workspace.change_id}")
        print(f"Phase     : {args.phase}")
        print(f"Input     : {args.input_format}")
        print(f"Hosts     : {len(snapshot['hosts'])}")
        print(f"Warnings  : {warning_count}")
        for line in terminal_result_lines(health_result):
            if not line.startswith(("Change ID", "Phase")):
                print(line)
        display_dir = output_dir
        if args.phase == "before" and getattr(args, "_health_attempt_id", None):
            display_dir = workspace.operation_root / "health" / "before"
            print(f"Attempt   : {output_dir}")
        print(f"Manifest  : {display_dir / 'collection-manifest.yaml'}")
        if import_manifest is not None:
            print(
                "Import    : "
                f"{display_dir / 'transcript-import-manifest.yaml'}"
            )
        print(f"Snapshot  : {display_dir / 'snapshot.json'}")
        print(f"Checklist : {display_dir / 'checklist.md'}")
        if overlay_state is not None:
            print(f"Overlay   : {display_dir / 'overlay-state.yaml'}")
            print(f"VNI Map   : {display_dir / 'vni-map.md'}")
            print(f"VNI CSV   : {display_dir / 'vni-map.csv'}")
        if (
            args.phase == "before"
            and workspace.change_id_source == "generated"
            and args.hosts
        ):
            inventory_digest = source_sha256(args.hosts).removeprefix(
                "sha256:"
            )
            save_active_change(
                args.operations_root,
                {
                    "api_version": "alred/v1",
                    "kind": "ActiveHealthCheckChange",
                    "metadata": {
                        "updated_at": completed_at.isoformat(timespec="seconds"),
                        "timezone": workspace.timezone,
                    },
                    "spec": {
                        "change_id": workspace.change_id,
                        "change_id_source": "generated",
                        "state": "before_completed",
                        "output_root": str(workspace.operation_root),
                        "before": {
                            "completed_at": completed_at.isoformat(
                                timespec="seconds"
                            ),
                            "metadata_path": str(workspace.metadata_path),
                            "snapshot_path": str(output_dir / "snapshot.json"),
                            "inventory_sha256": inventory_digest,
                            "profile_sha256": profile_sha256.removeprefix(
                                "sha256:"
                            ),
                        },
                        "after": {"status": "not_started"},
                    },
                },
            )
        return _health_result_exit_code(health_result["result"])
    except (
        CollectionAdapterError,
        TranscriptImportError,
        SnapshotBuildError,
        HealthEvaluationError,
        ProfileResolutionError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def _resolve_health_after_change_id(args: argparse.Namespace) -> bool:
    if args.change_id:
        return False
    active = load_active_change(args.operations_root)
    args.change_id = active["spec"]["change_id"]
    print("Change ID was not specified.")
    print(f"Using active before Change ID: {args.change_id}")
    return True


def _optional_existing_file(path: str | None, *, label: str) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise HealthExecutionContextError(
            f"{label} file is missing or unsafe: {candidate}"
        )
    return str(candidate.resolve())


def _resolved_credentials_path(args: argparse.Namespace) -> str | None:
    if args.credentials:
        return _optional_existing_file(
            args.credentials,
            label="credentials",
        )
    default_path = Path("clab_credentials.yaml")
    if default_path.is_file() and not default_path.is_symlink():
        return str(default_path.resolve())
    return None


def _write_health_execution_context(
    args: argparse.Namespace,
    workspace,
    *,
    recorded_at: datetime,
) -> None:
    context_path = workspace.operation_root / CONTEXT_RELATIVE_PATH
    if context_path.exists():
        raise OperationStateError(
            f"health execution context already exists: {context_path}"
        )
    input_mode = "collect" if args.collect else "input"
    if args.collect:
        args.hosts = str(
            Path(resolve_hosts_path(args.hosts, required=True)).resolve()
        )
        args.policy = _optional_existing_file(args.policy, label="policy")
        args.credentials = _resolved_credentials_path(args)
        collection = {
            "transport": args.transport,
            "target_hosts": sorted(parse_host_filter(args.target_hosts)),
            "workers": args.workers,
            "show_read_timeout": args.show_read_timeout,
            "skip_connect_check": args.skip_connect_check,
            "connect_check_timeout": args.connect_check_timeout,
        }
    else:
        if args.hosts is not None:
            args.hosts = _optional_existing_file(args.hosts, label="inventory")
        collection = None
    context = build_health_execution_context(
        change_id=workspace.change_id,
        recorded_at=recorded_at,
        timezone=workspace.timezone,
        input_mode=input_mode,
        inventory_path=args.hosts,
        policy_path=args.policy if args.collect else None,
        input_format=args.input_format if not args.collect else None,
        collection=collection,
        authentication={
            "username": args.username if args.collect else None,
            "credentials_file": args.credentials if args.collect else None,
            "ask_pass": bool(args.ask_pass) if args.collect else False,
            "ask_become_pass": (
                bool(args.ask_become_pass) if args.collect else False
            ),
            "password_was_cli": (
                args.password is not None if args.collect else False
            ),
            "enable_secret_was_cli": (
                args.enable_secret is not None if args.collect else False
            ),
        },
    )
    atomic_write_yaml(
        workspace.operation_root,
        context_path,
        context,
        kind="HealthCheckExecutionContext",
    )


def _inherit_context_source(
    reference: Mapping[str, str] | None,
    supplied_path: str | None,
    *,
    label: str,
    phase: str = "after",
) -> str | None:
    if reference is None:
        if supplied_path is not None:
            raise HealthExecutionContextError(
                f"{label} was not used by before and cannot be added to "
                f"{phase}"
            )
        return None
    return verify_source_file(reference, supplied_path, label=label)


def _apply_health_followup_execution_context(
    args: argparse.Namespace,
    workspace,
) -> bool:
    phase = args.health_check_command
    context = load_health_execution_context(workspace.operation_root)
    if context is None:
        return False
    if context["metadata"]["timezone"] != workspace.timezone:
        raise HealthExecutionContextError(
            "health execution context timezone does not match operation"
        )
    spec = context["spec"]
    explicit_mode = bool(args.collect or args.input)
    if not explicit_mode:
        if spec["input_mode"] == "input":
            raise OperationStateError(
                f"health-check {phase} requires --input because before used "
                "offline input; --input-format is inherited when omitted"
            )
        args.collect = True

    inventory = spec["inventory"]
    if args.collect or args.input:
        if inventory is not None:
            args.hosts = verify_source_file(
                inventory,
                args.hosts,
                label="inventory",
            )
        elif args.hosts is not None and spec["input_mode"] == "input":
            raise HealthExecutionContextError(
                "inventory was not used by before and cannot be added to "
                f"{phase}"
            )

    if args.input:
        if args.input_format is None and spec["input_mode"] == "input":
            args.input_format = spec["input_format"]
        return True

    if spec["input_mode"] != "collect":
        return True
    args.policy = _inherit_context_source(
        spec["policy"],
        args.policy,
        label="policy",
        phase=phase,
    )
    collection = spec["collection"]
    recorded_targets = collection["target_hosts"]
    if args.target_hosts is not None:
        requested_targets = sorted(parse_host_filter(args.target_hosts))
        if requested_targets != recorded_targets:
            raise HealthExecutionContextError(
                f"{phase} target-hosts do not match before"
            )
    args.target_hosts = (
        ",".join(recorded_targets) if recorded_targets else None
    )
    for name in (
        "transport",
        "workers",
        "show_read_timeout",
        "skip_connect_check",
        "connect_check_timeout",
    ):
        if getattr(args, name) is None:
            setattr(args, name, collection[name])

    authentication = spec["authentication"]
    if args.username is None:
        args.username = authentication["username"]
    if args.credentials is None:
        args.credentials = authentication["credentials_file"]
    if args.credentials is not None:
        args.credentials = _optional_existing_file(
            args.credentials,
            label="credentials",
        )
    args.ask_pass = bool(
        args.ask_pass
        or authentication["ask_pass"]
        or (
            args.password is None
            and authentication["password_was_cli"]
        )
    )
    args.ask_become_pass = bool(
        args.ask_become_pass
        or authentication["ask_become_pass"]
        or (
            args.enable_secret is None
            and authentication["enable_secret_was_cli"]
        )
    )
    return True


def _set_health_followup_collect_defaults(args: argparse.Namespace) -> None:
    defaults = {
        "transport": "ssh",
        "workers": 5,
        "show_read_timeout": 120,
        "skip_connect_check": False,
        "connect_check_timeout": DEFAULT_CONNECT_CHECK_TIMEOUT,
    }
    for name, value in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, value)


def _direct_health_collect(
    args: argparse.Namespace,
    workspace,
    resolved_profiles: Mapping[str, Any],
) -> Path:
    phase = args.health_check_command
    effective = resolved_profiles["spec"]["resolved"]["effective"]
    commands = [
        item["command"]
        for item in effective["spec"]
        .get("collectors", {})
        .get("nxos", {})
        .get("commands", [])
        if item["id"] != "running_config"
    ]
    attempt_id = getattr(args, "_health_attempt_id", None)
    phase_root = workspace.operation_root / "health" / phase
    if phase in {"before", "rollback"} and attempt_id:
        phase_root = phase_root / "attempts" / attempt_id
    raw_dir = phase_root / "raw"
    command_path = phase_root / "show-commands.txt"
    atomic_write_bytes(
        workspace.operation_root,
        command_path,
        (
            "[device_type:nxos]\n"
            + "\n".join(commands).rstrip()
            + "\n"
        ).encode("utf-8"),
    )
    collect_args = argparse.Namespace(
        command="collect",
        hosts=args.hosts,
        policy=args.policy,
        roles=None,
        username=args.username,
        password=args.password,
        ask_pass=args.ask_pass,
        enable_secret=args.enable_secret,
        credentials=args.credentials,
        ask_become_pass=args.ask_become_pass,
        transport=args.transport,
        target_hosts=args.target_hosts,
        output=str(raw_dir),
        before_show_run_dir=None,
        workers=args.workers,
        show_commands_file=str(command_path),
        show_hosts=None,
        show_read_timeout=args.show_read_timeout,
        skip_connect_check=args.skip_connect_check,
        connect_check_timeout=args.connect_check_timeout,
        log_file=str(phase_root / "collect.log"),
        verbose=args.verbose,
        show_run_diff=False,
        show_run_diff_comands=False,
        show_only=False,
        run_config_only=True,
    )
    started_at = now_in_timezone(workspace.timezone)
    collection_phase = f"{phase}_collect"
    with OperationLock(workspace, f"health-check-{collection_phase}") as lock:
        transition_phase(
            workspace,
            collection_phase,
            "running",
            lock=lock,
            attempt_id=generate_attempt_id(
                collection_phase,
                workspace.timezone,
                now=started_at,
            ),
            reason="direct_collection_started",
            now=started_at,
            allow_retry=bool(getattr(args, "_health_retry", False)),
        )
        try:
            run_collect(
                collect_args,
                setup_logging(collect_args.log_file, collect_args.verbose),
            )
            transition_phase(
                workspace,
                collection_phase,
                "completed",
                lock=lock,
                reason="direct_collection_completed",
                now=now_in_timezone(workspace.timezone),
            )
        except Exception as exc:
            failed_at = now_in_timezone(workspace.timezone)
            transition_phase(
                workspace,
                collection_phase,
                "failed",
                lock=lock,
                reason="direct_collection_failed",
                now=failed_at,
            )
            record_operation_error(
                workspace,
                {
                    "code": getattr(exc, "code", "COLLECTION_ERROR"),
                    "phase": collection_phase,
                    "at": failed_at.isoformat(timespec="seconds"),
                    "message": str(exc),
                },
                lock=lock,
            )
            raise
    return raw_dir


def _validate_before_retry_context(args: argparse.Namespace, workspace) -> None:
    context = load_health_execution_context(workspace.operation_root)
    if context is None:
        return
    spec = context["spec"]
    requested_mode = "collect" if args.collect else "input"
    if spec["input_mode"] != requested_mode:
        raise HealthExecutionContextError(
            "before retry input mode does not match the fixed before context"
        )
    if spec["inventory"] is not None:
        args.hosts = verify_source_file(
            spec["inventory"],
            args.hosts,
            label="inventory",
        )
    elif args.hosts is not None:
        raise HealthExecutionContextError(
            "inventory was not fixed by the original before"
        )
    if args.collect:
        if spec["policy"] is not None:
            args.policy = verify_source_file(
                spec["policy"],
                args.policy,
                label="policy",
            )
        elif args.policy is not None:
            raise HealthExecutionContextError(
                "policy was not fixed by the original before"
            )


def _profile_value_changes(
    before: Any,
    after: Any,
    path: str = "",
) -> list[dict[str, Any]]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes = []
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}/{key}" if path else f"/{key}"
            changes.extend(
                _profile_value_changes(
                    before.get(key, "<absent>"),
                    after.get(key, "<absent>"),
                    child_path,
                )
            )
        return changes
    if before == after:
        return []
    return [{"path": path or "/", "before": before, "after": after}]


def _prepare_before_profiles(
    args: argparse.Namespace,
    workspace,
    logging_time_range: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    resolved_path = workspace.operation_root / "health" / "resolved-profiles.yaml"
    revision_reason = str(getattr(args, "revision_reason", "") or "").strip()
    revision_requested = bool(revision_reason)
    requested = resolve_profiles(
        args.profile or [DEFAULT_HEALTH_PROFILE],
        change_id=workspace.change_id,
        resolved_at=now_in_timezone(workspace.timezone),
        resolution_source="explicit" if args.profile else "default",
        timezone=workspace.timezone,
    )
    if not resolved_path.exists():
        if revision_requested:
            raise ProfileResolutionError(
                "--revision-reason requires an existing completed before"
            )
        if logging_time_range is not None:
            requested = apply_logging_time_range_override(
                requested,
                logging_time_range,
            )
        return requested, None

    fixed = load_resolved_profiles(resolved_path)
    fixed_range = (
        fixed["spec"]["resolved"]["effective"]["spec"]
        .get("thresholds", {})
        .get("logging", {})
        .get("time_range")
    )
    if revision_requested:
        if logging_time_range is not None:
            requested = apply_logging_time_range_override(
                requested,
                logging_time_range,
            )
        elif fixed_range is not None:
            requested = apply_logging_time_range_override(requested, fixed_range)
        previous_hash = fixed["spec"]["resolved"]["effective_sha256"]
        revised_hash = requested["spec"]["resolved"]["effective_sha256"]
        if previous_hash == revised_hash:
            raise ProfileResolutionError(
                "--revision-reason was provided but the effective profile "
                "did not change"
            )
        changes = _profile_value_changes(
            fixed["spec"]["resolved"]["effective"],
            requested["spec"]["resolved"]["effective"],
        )
        return requested, {
            "reason": revision_reason,
            "previous": {
                "path": str(resolved_path),
                "effective_sha256": previous_hash,
                "profile_names": fixed["spec"]["resolved"]["profile_names"],
            },
            "revised": {
                "effective_sha256": revised_hash,
                "profile_names": requested["spec"]["resolved"]["profile_names"],
            },
            "changes": changes,
        }

    if logging_time_range is not None and logging_time_range != fixed_range:
        raise ProfileResolutionError(
            "before retry logging range does not match the fixed profile; "
            "use a new change ID"
        )
    requested = _inherit_fixed_logging_time_range(requested, fixed)
    if (
        requested["spec"]["resolved"]["effective_sha256"]
        != fixed["spec"]["resolved"]["effective_sha256"]
    ):
        raise ProfileResolutionError(
            "before retry profile does not match fixed profile; "
            "use --revision-reason to record an explicit profile revision"
        )
    return fixed, None


def _archive_legacy_before_attempt(workspace, metadata: Mapping[str, Any]) -> None:
    phase = metadata["spec"].get("phases", {}).get("before")
    phase_root = workspace.operation_root / "health" / "before"
    snapshot_path = phase_root / "snapshot.json"
    if not phase or not snapshot_path.is_file():
        return
    attempt_id = phase.get("current_attempt") or "legacy-before"
    attempt_dir = phase_root / "attempts" / attempt_id
    resolved_path = workspace.operation_root / "health" / "resolved-profiles.yaml"
    resolved = load_resolved_profiles(resolved_path)
    profile_sha256 = resolved["spec"]["resolved"]["effective_sha256"]
    if not attempt_dir.exists():
        attempt_dir.mkdir(parents=True)
        for child in phase_root.iterdir():
            if child.name in {"attempts", "current.json"}:
                continue
            destination = attempt_dir / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            elif child.is_file() and not child.is_symlink():
                shutil.copy2(child, destination)
        shutil.copy2(resolved_path, attempt_dir / "resolved-profiles.yaml")
        health = json.loads(
            (attempt_dir / "health-result.json").read_text(encoding="utf-8")
        )
        atomic_write_json(
            workspace.operation_root,
            attempt_dir / "result.json",
            {
                "schema_version": 1,
                "change_id": workspace.change_id,
                "phase": "before",
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "health_result": health["result"],
                "started_at": health["started_at"],
                "completed_at": health["completed_at"],
                "artifact_dir": str(attempt_dir),
                "profile_sha256": profile_sha256,
            },
            kind="HealthPhaseAttempt",
        )
    elif not (attempt_dir / "resolved-profiles.yaml").exists():
        shutil.copy2(resolved_path, attempt_dir / "resolved-profiles.yaml")
    result_path = attempt_dir / "result.json"
    if result_path.exists():
        legacy_result = json.loads(result_path.read_text(encoding="utf-8"))
        if "profile_sha256" not in legacy_result:
            legacy_result["profile_sha256"] = profile_sha256
            atomic_write_json(
                workspace.operation_root,
                result_path,
                legacy_result,
                kind="HealthPhaseAttempt",
            )
    health = json.loads(
        (attempt_dir / "health-result.json").read_text(encoding="utf-8")
    )
    atomic_write_json(
        workspace.operation_root,
        phase_root / "current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "before",
            "attempt_id": attempt_id,
            "artifact_dir": str(attempt_dir),
            "snapshot_path": str(attempt_dir / "snapshot.json"),
            "snapshot_sha256": source_sha256(attempt_dir / "snapshot.json"),
            "profile_sha256": profile_sha256,
            "health_result": health["result"],
            "completed_at": health["completed_at"],
        },
        kind="HealthPhaseCurrent",
    )


def _start_before_attempt(args: argparse.Namespace, workspace) -> dict[str, Any]:
    metadata = load_operation_metadata(workspace.operation_root)
    if metadata["spec"].get("workflow_state") is not None:
        raise OperationStateError(
            "before cannot be retried after the Overlay workflow has started"
        )
    blocking_paths = [
        workspace.operation_root / "plan" / "execution-plan.json",
        workspace.operation_root / "approval" / "approval-record.json",
        workspace.operation_root / "apply" / "execution.json",
    ]
    if any(path.exists() for path in blocking_paths):
        raise OperationStateError(
            "before cannot be retried after plan, approval, or apply artifacts exist"
        )
    phases = metadata["spec"].get("phases", {})
    previous = phases.get("before")
    if previous and previous["status"] in {"running", "waiting_for_user"}:
        raise OperationStateError("a before attempt is already in progress")
    retry = previous is not None or phases.get("before_collect") is not None
    if retry:
        _validate_before_retry_context(args, workspace)
        _archive_legacy_before_attempt(workspace, metadata)
    started_at = now_in_timezone(workspace.timezone)
    attempt_id = generate_attempt_id("before", workspace.timezone, now=started_at)
    attempt_dir = (
        workspace.operation_root / "health" / "before" / "attempts" / attempt_id
    )
    args._health_attempt_id = attempt_id
    args._health_retry = retry
    result = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "before",
        "attempt_id": attempt_id,
        "status": "RUNNING",
        "started_at": started_at.isoformat(timespec="seconds"),
        "artifact_dir": str(attempt_dir),
        "profile_sha256": args._health_resolved_profiles["spec"]["resolved"][
            "effective_sha256"
        ],
    }
    atomic_write_yaml(
        workspace.operation_root,
        attempt_dir / "resolved-profiles.yaml",
        args._health_resolved_profiles,
        kind="ResolvedHealthCheckProfiles",
    )
    revision = getattr(args, "_health_profile_revision", None)
    if revision is not None:
        revision_path = attempt_dir / "profile-revision.json"
        revision_document = {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "attempt_id": attempt_id,
            "revised_at": started_at.isoformat(timespec="seconds"),
            "reason": revision["reason"],
            "previous": revision["previous"],
            "revised": {
                **revision["revised"],
                "path": str(attempt_dir / "resolved-profiles.yaml"),
            },
            "changes": revision["changes"],
        }
        atomic_write_json(
            workspace.operation_root,
            revision_path,
            revision_document,
            kind="HealthProfileRevision",
        )
        result["profile_revision"] = str(revision_path)
    atomic_write_json(
        workspace.operation_root,
        attempt_dir / "result.json",
        result,
        kind="HealthPhaseAttempt",
    )
    return result


def _fail_before_attempt(workspace, attempt: dict[str, Any], exc: BaseException) -> None:
    attempt_dir = Path(attempt["artifact_dir"])
    execution = load_operation_execution(workspace.operation_root)
    last_error = execution["errors"][-1] if execution["errors"] else {}
    code = last_error.get("code") or getattr(exc, "code", "VALIDATION_ERROR")
    if not isinstance(code, str):
        code = "VALIDATION_ERROR"
    message = last_error.get("message") or str(exc)
    attempt.update(
        {
            "status": "FAILED",
            "completed_at": now_in_timezone(workspace.timezone).isoformat(
                timespec="seconds"
            ),
            "error": {"code": code, "message": message},
        }
    )
    atomic_write_json(
        workspace.operation_root,
        attempt_dir / "result.json",
        attempt,
        kind="HealthPhaseAttempt",
    )


def _publish_before_attempt(workspace, attempt: dict[str, Any]) -> None:
    attempt_dir = Path(attempt["artifact_dir"])
    phase_root = workspace.operation_root / "health" / "before"
    health = json.loads(
        (attempt_dir / "health-result.json").read_text(encoding="utf-8")
    )
    for child in attempt_dir.iterdir():
        if child.name in {"result.json", "resolved-profiles.yaml"}:
            continue
        destination = phase_root / child.name
        if child.is_dir():
            staged = phase_root / f".{child.name}.{attempt['attempt_id']}.tmp"
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(child, staged)
            if destination.exists():
                shutil.rmtree(destination)
            staged.replace(destination)
        elif child.is_file() and not child.is_symlink():
            atomic_write_bytes(
                workspace.operation_root,
                destination,
                child.read_bytes(),
            )
    atomic_write_bytes(
        workspace.operation_root,
        workspace.operation_root / "health" / "resolved-profiles.yaml",
        (attempt_dir / "resolved-profiles.yaml").read_bytes(),
    )
    completed_at = health["completed_at"]
    attempt.update(
        {
            "status": "COMPLETED",
            "health_result": health["result"],
            "completed_at": completed_at,
        }
    )
    atomic_write_json(
        workspace.operation_root,
        attempt_dir / "result.json",
        attempt,
        kind="HealthPhaseAttempt",
    )
    atomic_write_json(
        workspace.operation_root,
        phase_root / "current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "before",
            "attempt_id": attempt["attempt_id"],
            "artifact_dir": str(attempt_dir),
            "snapshot_path": str(attempt_dir / "snapshot.json"),
            "snapshot_sha256": source_sha256(attempt_dir / "snapshot.json"),
            "profile_sha256": attempt["profile_sha256"],
            "health_result": health["result"],
            "completed_at": completed_at,
        },
        kind="HealthPhaseCurrent",
    )


def _copy_attempt_artifacts(
    workspace,
    source: Path,
    destination_root: Path,
    *,
    excluded: set[str],
) -> None:
    """Publish immutable attempt files to compatibility paths atomically."""
    for child in source.iterdir():
        if child.name in excluded:
            continue
        destination = destination_root / child.name
        if child.is_dir():
            staged = (
                destination_root
                / f".{child.name}.{generate_attempt_id('publish', workspace.timezone)}.tmp"
            )
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(child, staged)
            if destination.exists():
                shutil.rmtree(destination)
            staged.replace(destination)
        elif child.is_file() and not child.is_symlink():
            atomic_write_bytes(
                workspace.operation_root,
                destination,
                child.read_bytes(),
            )


def _rollback_verification_roots(workspace) -> tuple[Path, Path]:
    qualification = (
        workspace.operation_root
        / "qualification/qualification-record.json"
    ).is_file()
    root = (
        workspace.operation_root / "qualification/rollback"
        if qualification
        else workspace.operation_root / "rollback"
    )
    return root, root / "verification-attempts"


def _archive_legacy_rollback_attempt(
    workspace,
    metadata: Mapping[str, Any],
) -> None:
    phase_root = workspace.operation_root / "health/rollback"
    snapshot_path = phase_root / "snapshot.json"
    if not snapshot_path.is_file():
        return
    phase = metadata["spec"].get("phases", {}).get("rollback", {})

    def complete_attempt(candidate: Path) -> bool:
        return (
            (candidate / "snapshot.json").is_file()
            and (candidate / "health-result.json").is_file()
        )

    attempt_id = None
    attempt_dir = None
    current_path = phase_root / "current.json"
    if current_path.is_file():
        try:
            current = json.loads(current_path.read_text(encoding="utf-8"))
            current_id = current.get("attempt_id")
            current_dir = phase_root / "attempts" / str(current_id)
            if current_id and complete_attempt(current_dir):
                attempt_id = str(current_id)
                attempt_dir = current_dir
        except (json.JSONDecodeError, OSError):
            pass
    phase_attempt_id = phase.get("current_attempt")
    if attempt_dir is None and phase_attempt_id:
        phase_attempt_dir = phase_root / "attempts" / phase_attempt_id
        if complete_attempt(phase_attempt_dir):
            attempt_id = phase_attempt_id
            attempt_dir = phase_attempt_dir
    if attempt_dir is None:
        attempt_id = "legacy-rollback"
        attempt_dir = phase_root / "attempts" / attempt_id
        suffix = 1
        while attempt_dir.exists() and not complete_attempt(attempt_dir):
            attempt_id = f"legacy-rollback-{suffix}"
            attempt_dir = phase_root / "attempts" / attempt_id
            suffix += 1
    resolved_path = workspace.operation_root / "health/resolved-profiles.yaml"
    resolved = load_resolved_profiles(resolved_path)
    profile_sha256 = resolved["spec"]["resolved"]["effective_sha256"]
    if not attempt_dir.exists():
        attempt_dir.mkdir(parents=True)
        for child in phase_root.iterdir():
            if child.name in {"attempts", "current.json"}:
                continue
            destination = attempt_dir / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            elif child.is_file() and not child.is_symlink():
                shutil.copy2(child, destination)
        shutil.copy2(resolved_path, attempt_dir / "resolved-profiles.yaml")
    health = json.loads(
        (attempt_dir / "health-result.json").read_text(encoding="utf-8")
    )
    if not (attempt_dir / "result.json").is_file():
        atomic_write_json(
            workspace.operation_root,
            attempt_dir / "result.json",
            {
                "schema_version": 1,
                "change_id": workspace.change_id,
                "phase": "rollback",
                "attempt_id": attempt_id,
                "status": "COMPLETED",
                "health_result": health["result"],
                "started_at": health["started_at"],
                "completed_at": health["completed_at"],
                "artifact_dir": str(attempt_dir),
                "profile_sha256": profile_sha256,
            },
            kind="HealthPhaseAttempt",
        )
    atomic_write_json(
        workspace.operation_root,
        phase_root / "current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "rollback",
            "attempt_id": attempt_id,
            "artifact_dir": str(attempt_dir),
            "snapshot_path": str(attempt_dir / "snapshot.json"),
            "snapshot_sha256": source_sha256(attempt_dir / "snapshot.json"),
            "profile_sha256": profile_sha256,
            "health_result": health["result"],
            "completed_at": health["completed_at"],
        },
        kind="HealthPhaseCurrent",
    )

    report_root = workspace.operation_root / "health/rollback-report"
    report_attempt = report_root / "attempts" / attempt_id
    if (report_root / "health-result.json").is_file() and not report_attempt.exists():
        report_attempt.mkdir(parents=True)
        for name in ("health-result.json", "summary.md"):
            source = report_root / name
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source, report_attempt / name)

    verification_root, attempts_root = _rollback_verification_roots(workspace)
    verification_attempt = attempts_root / attempt_id
    legacy_verification = verification_root / "verification.json"
    if legacy_verification.is_file() and not verification_attempt.exists():
        verification_attempt.mkdir(parents=True)
        for name in ("verification.json", "verification-checklist.md"):
            source = verification_root / name
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source, verification_attempt / name)
    if (
        (verification_attempt / "verification.json").is_file()
        and (verification_attempt / "verification-checklist.md").is_file()
    ):
        verification = json.loads(
            (verification_attempt / "verification.json").read_text(
                encoding="utf-8"
            )
        )
        checklist = verification_attempt / "verification-checklist.md"
        atomic_write_json(
            workspace.operation_root,
            verification_root / "verification-current.json",
            {
                "schema_version": 1,
                "change_id": workspace.change_id,
                "attempt_id": attempt_id,
                "result": verification["status"]["result"],
                "verification_path": str(
                    verification_attempt / "verification.json"
                ),
                "checklist_path": str(checklist),
                "health_report_path": str(
                    report_attempt / "health-result.json"
                ),
                "completed_at": verification["metadata"]["verified_at"],
            },
            kind="RollbackVerificationCurrent",
        )


def _start_rollback_attempt(
    args: argparse.Namespace,
    workspace,
    resolved_profiles: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = load_operation_metadata(workspace.operation_root)
    workflow = metadata["spec"].get("workflow_state")
    if workflow not in {"rolled_back", "rollback_health_failed"}:
        raise OperationStateError(
            "rollback health check requires rolled_back or "
            "rollback_health_failed"
        )
    phases = metadata["spec"].get("phases", {})
    for phase_name in ("rollback_collect", "rollback"):
        existing = phases.get(phase_name)
        if existing and existing["status"] in {"running", "waiting_for_user"}:
            raise OperationStateError(
                "a rollback health attempt is already in progress"
            )
    retry = "rollback" in phases or "rollback_collect" in phases
    if retry:
        _archive_legacy_rollback_attempt(workspace, metadata)
    started_at = now_in_timezone(workspace.timezone)
    attempt_id = generate_attempt_id(
        "rollback",
        workspace.timezone,
        now=started_at,
    )
    attempt_dir = (
        workspace.operation_root / "health/rollback/attempts" / attempt_id
    )
    args._health_attempt_id = attempt_id
    args._health_retry = retry
    result = {
        "schema_version": 1,
        "change_id": workspace.change_id,
        "phase": "rollback",
        "attempt_id": attempt_id,
        "status": "RUNNING",
        "started_at": started_at.isoformat(timespec="seconds"),
        "artifact_dir": str(attempt_dir),
        "profile_sha256": resolved_profiles["spec"]["resolved"][
            "effective_sha256"
        ],
    }
    atomic_write_yaml(
        workspace.operation_root,
        attempt_dir / "resolved-profiles.yaml",
        resolved_profiles,
        kind="ResolvedHealthCheckProfiles",
    )
    atomic_write_json(
        workspace.operation_root,
        attempt_dir / "result.json",
        result,
        kind="HealthPhaseAttempt",
    )
    return result


def _fail_rollback_attempt(
    workspace,
    attempt: dict[str, Any],
    exc: BaseException,
) -> None:
    attempt.update(
        {
            "status": "FAILED",
            "completed_at": now_in_timezone(workspace.timezone).isoformat(
                timespec="seconds"
            ),
            "error": {
                "code": str(getattr(exc, "code", "VALIDATION_ERROR")),
                "message": str(exc),
            },
        }
    )
    atomic_write_json(
        workspace.operation_root,
        Path(attempt["artifact_dir"]) / "result.json",
        attempt,
        kind="HealthPhaseAttempt",
    )


def _publish_rollback_attempt(
    workspace,
    attempt: dict[str, Any],
    *,
    report_dir: Path,
    verification_dir: Path,
    verification: Mapping[str, Any],
) -> None:
    attempt_dir = Path(attempt["artifact_dir"])
    phase_root = workspace.operation_root / "health/rollback"
    report_root = workspace.operation_root / "health/rollback-report"
    verification_root, _attempts_root = _rollback_verification_roots(workspace)
    _copy_attempt_artifacts(
        workspace,
        attempt_dir,
        phase_root,
        excluded={"result.json", "resolved-profiles.yaml"},
    )
    _copy_attempt_artifacts(
        workspace,
        report_dir,
        report_root,
        excluded=set(),
    )
    _copy_attempt_artifacts(
        workspace,
        verification_dir,
        verification_root,
        excluded=set(),
    )
    health = json.loads(
        (attempt_dir / "health-result.json").read_text(encoding="utf-8")
    )
    completed_at = verification["metadata"]["verified_at"]
    attempt.update(
        {
            "status": "COMPLETED",
            "health_result": health["result"],
            "completed_at": completed_at,
        }
    )
    atomic_write_json(
        workspace.operation_root,
        attempt_dir / "result.json",
        attempt,
        kind="HealthPhaseAttempt",
    )
    atomic_write_json(
        workspace.operation_root,
        phase_root / "current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "phase": "rollback",
            "attempt_id": attempt["attempt_id"],
            "artifact_dir": str(attempt_dir),
            "snapshot_path": str(attempt_dir / "snapshot.json"),
            "snapshot_sha256": source_sha256(attempt_dir / "snapshot.json"),
            "profile_sha256": attempt["profile_sha256"],
            "health_result": health["result"],
            "completed_at": completed_at,
        },
        kind="HealthPhaseCurrent",
    )
    atomic_write_json(
        workspace.operation_root,
        verification_root / "verification-current.json",
        {
            "schema_version": 1,
            "change_id": workspace.change_id,
            "attempt_id": attempt["attempt_id"],
            "result": verification["status"]["result"],
            "verification_path": str(
                verification_dir / "verification.json"
            ),
            "checklist_path": str(
                verification_dir / "verification-checklist.md"
            ),
            "health_report_path": str(report_dir / "health-result.json"),
            "completed_at": completed_at,
        },
        kind="RollbackVerificationCurrent",
    )


def _verify_and_publish_rollback_attempt(
    workspace,
    rollback_attempt: dict[str, Any],
) -> tuple[dict[str, Any], Path, Path]:
    attempt_id = rollback_attempt["attempt_id"]
    attempt_dir = Path(rollback_attempt["artifact_dir"])
    report_dir = (
        workspace.operation_root
        / "health/rollback-report/attempts"
        / attempt_id
    )
    record_path = (
        workspace.operation_root
        / "qualification/qualification-record.json"
    )
    if record_path.is_file():
        record = load_qualification_record(record_path)
        verification_dir = (
            workspace.operation_root
            / "qualification/rollback/verification-attempts"
            / attempt_id
        )
        with OperationLock(
            workspace,
            "qualification-rollback-verify",
        ) as lock:
            verification = verify_qualification_rollback(
                workspace,
                record,
                rollback_snapshot_path=attempt_dir / "snapshot.json",
                report_dir=report_dir,
                verification_dir=verification_dir,
                update_workflow=False,
                lock=lock,
                now=lambda: now_in_timezone(workspace.timezone),
            )
    else:
        verification_dir = (
            workspace.operation_root
            / "rollback/verification-attempts"
            / attempt_id
        )
        with OperationLock(
            workspace,
            "approved-rollback-verify",
        ) as lock:
            verification = verify_approved_rollback(
                workspace,
                rollback_snapshot_path=attempt_dir / "snapshot.json",
                plan_path=(
                    workspace.operation_root / "plan/execution-plan.json"
                ),
                report_dir=report_dir,
                verification_dir=verification_dir,
                update_workflow=False,
                lock=lock,
                now=lambda: now_in_timezone(workspace.timezone),
            )
    _publish_rollback_attempt(
        workspace,
        rollback_attempt,
        report_dir=report_dir,
        verification_dir=verification_dir,
        verification=verification,
    )
    verified = (
        verification["status"]["result"]
        == "ROLLED_BACK_AND_VERIFIED"
    )
    with OperationLock(
        workspace,
        "rollback-health-workflow",
    ) as lock:
        transition_workflow(
            workspace,
            (
                "rolled_back_and_verified"
                if verified
                else "rollback_health_failed"
            ),
            lock=lock,
            reason=(
                "rollback_health_retry_verified"
                if verified
                else "rollback_health_attempt_failed"
            ),
            now=now_in_timezone(workspace.timezone),
        )
    return (
        verification,
        verification_dir / "verification.json",
        verification_dir / "verification-checklist.md",
    )


def cmd_health_check_phase(args: argparse.Namespace) -> int:
    """Run before/after/rollback using input or the shared collect runner."""
    phase = args.health_check_command
    args.phase = phase
    active_change_inherited = False
    logging_time_range = _logging_time_range_from_args(args)
    if phase != "before" and logging_time_range is not None:
        raise OperationStateError(
            "logging range options are valid only for the initial before"
        )
    if phase == "after":
        active_change_inherited = _resolve_health_after_change_id(args)
    elif phase == "rollback" and not args.change_id:
        raise OperationStateError("health-check rollback requires --change-id")
    if args.collect and args.input:
        raise OperationStateError("--collect and --input cannot be used together")
    if phase == "before" and not args.collect and not args.input:
        raise OperationStateError(
            f"health-check {phase} requires --collect or --input"
        )
    if phase in {"after", "rollback"}:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        _apply_health_followup_execution_context(args, workspace)
        if not args.collect and not args.input:
            raise OperationStateError(
                f"health-check {phase} requires --collect or --input because "
                "the before execution context is unavailable"
            )
        if args.collect:
            _set_health_followup_collect_defaults(args)
            apply_password_prompt_options(args)
        if phase == "after" and active_change_inherited:
            if not args.hosts:
                raise OperationStateError(
                    "active before cannot be verified without an inherited "
                    "or explicit inventory"
                )
            fixed_profiles = load_resolved_profiles(
                workspace.operation_root
                / "health"
                / "resolved-profiles.yaml"
            )
            resolve_active_change_for_after(
                args.operations_root,
                inventory_sha256=source_sha256(args.hosts).removeprefix(
                    "sha256:"
                ),
                profile_sha256=fixed_profiles["spec"]["resolved"][
                    "effective_sha256"
                ].removeprefix("sha256:"),
            )
    if args.collect and not args.hosts:
        raise OperationStateError("--collect requires --hosts")
    if args.input and not args.input_format:
        raise OperationStateError("--input-format is required with --input")
    before_attempt = None
    rollback_attempt = None
    if phase == "before":
        workspace, _output = _snapshot_workspace(args)
        args.change_id = workspace.change_id
        resolved_before, profile_revision = _prepare_before_profiles(
            args,
            workspace,
            logging_time_range,
        )
        args._health_resolved_profiles = resolved_before
        args._health_profile_revision = profile_revision
        before_attempt = _start_before_attempt(args, workspace)
    elif phase == "rollback":
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        resolved_rollback = load_resolved_profiles(
            workspace.operation_root / "health/resolved-profiles.yaml"
        )
        rollback_attempt = _start_rollback_attempt(
            args,
            workspace,
            resolved_rollback,
        )
    try:
        if args.collect:
            workspace, _output = _snapshot_workspace(args)
            # Pin the automatically generated before change-id before handing
            # collected raw to the offline Snapshot path. Without this, the
            # second workspace resolution generates a different operation.
            args.change_id = workspace.change_id
            started_at = now_in_timezone(workspace.timezone)
            if phase == "before":
                resolved = args._health_resolved_profiles
            elif phase == "rollback":
                resolved = resolved_rollback
            else:
                resolved = load_resolved_profiles(
                    workspace.operation_root
                    / "health"
                    / "resolved-profiles.yaml"
                )
            raw_dir = _direct_health_collect(args, workspace, resolved)
            args.input = [str(raw_dir)]
            args.input_format = "alred-collect"
        result = cmd_health_check_snapshot(args)
    except (Exception, SystemExit) as exc:
        if before_attempt is not None:
            workspace = open_operation_workspace(
                args.operations_root,
                args.change_id,
            )
            _fail_before_attempt(workspace, before_attempt, exc)
        if rollback_attempt is not None:
            workspace = open_operation_workspace(
                args.operations_root,
                args.change_id,
            )
            _fail_rollback_attempt(workspace, rollback_attempt, exc)
        raise
    if phase == "before":
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        _publish_before_attempt(workspace, before_attempt)
        if not (workspace.operation_root / CONTEXT_RELATIVE_PATH).exists():
            _write_health_execution_context(
                args,
                workspace,
                recorded_at=now_in_timezone(workspace.timezone),
            )
        result_path = (
            workspace.operation_root
            / "health"
            / "before"
            / "health-result.json"
        )
        health_result = json.loads(result_path.read_text(encoding="utf-8"))
        gate = health_result.get("operation_gate", {})
        if gate.get("required"):
            continued = False
            if sys.stdin.isatty() and sys.stdout.isatty():
                print("=== OPERATION GATE ===")
                for reason in gate.get("reasons", []):
                    print(
                        f"- {reason['host']}: {reason['code']} "
                        f"({reason['message']})"
                    )
                continued = (
                    input("Type 'yes' to continue with this before state: ")
                    .strip()
                    .lower()
                    == "yes"
                )
            gate["decision"] = {
                "action": "continue" if continued else "stop",
                "decided_at": now_in_timezone(
                    workspace.timezone
                ).isoformat(timespec="seconds"),
                "interactive": bool(
                    sys.stdin.isatty() and sys.stdout.isatty()
                ),
            }
            atomic_write_json(
                workspace.operation_root,
                result_path,
                health_result,
                kind="HealthResult",
            )
            if not continued:
                print(
                    "Operation gate was not approved; subsequent apply "
                    "must not continue."
                )
    if phase == "after":
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        compare_result = cmd_health_check_compare(
            argparse.Namespace(
                before=str(
                    workspace.operation_root
                    / "health"
                    / "before"
                    / "snapshot.json"
                ),
                after=str(
                    workspace.operation_root
                    / "health"
                    / "after"
                    / "snapshot.json"
                ),
                profile=args.profile,
                operations_root=args.operations_root,
                output=None,
            )
        )
        result = max(result, compare_result)
    if phase == "after" and args.change_id:
        try:
            active = load_active_change(args.operations_root)
        except OperationError:
            active = None
        if active and active["spec"]["change_id"] == args.change_id:
            completed_at = now_in_timezone(active["metadata"]["timezone"])
            active["metadata"]["updated_at"] = completed_at.isoformat(
                timespec="seconds"
            )
            active["spec"]["state"] = "completed"
            active["spec"]["after"]["status"] = "completed"
            save_active_change(args.operations_root, active)
    if phase == "rollback":
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        try:
            (
                verification,
                evidence,
                verification_checklist,
            ) = _verify_and_publish_rollback_attempt(
                workspace,
                rollback_attempt,
            )
        except (Exception, SystemExit) as exc:
            _fail_rollback_attempt(workspace, rollback_attempt, exc)
            if isinstance(
                exc,
                (
                    QualificationError,
                    HealthEvaluationError,
                    ProfileResolutionError,
                    OperationError,
                    ValueError,
                    OSError,
                ),
            ):
                _operation_cli_error(exc)
            raise
        print("=== ROLLBACK VERIFICATION ===")
        print(f"Result    : {verification['status']['result']}")
        print(
            "Raw config: "
            f"{verification['status']['raw_config_equal']}"
        )
        print(
            "Semantic  : "
            f"{verification['status']['semantic_config_equal']}"
        )
        print(
            "Evidence  : "
            f"{evidence}"
        )
        print(f"Checklist : {verification_checklist}")
        result = max(
            result,
            (
                0
                if verification["status"]["result"]
                == "ROLLED_BACK_AND_VERIFIED"
                else 4
            ),
        )
    return result


def _health_result_exit_code(result: str) -> int:
    return {
        "PASS": 0,
        "NOT_APPLICABLE": 0,
        "WARN": 1,
        "UNKNOWN": 3,
        "FAIL": 4,
        "PLAN_ERROR": 2,
    }[result]


def _load_snapshot_file(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink():
        raise HealthEvaluationError(f"Snapshot not found: {candidate}")
    document = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise HealthEvaluationError(f"Snapshot is not a JSON object: {candidate}")
    return document


def cmd_health_check_compare(args: argparse.Namespace) -> int:
    """Compare two offline Snapshots and write common health results."""
    try:
        before = _load_snapshot_file(args.before)
        after = _load_snapshot_file(args.after)
        if before.get("change_id") != after.get("change_id"):
            raise HealthEvaluationError("before/after change_id mismatch")
        workspace = open_operation_workspace(
            args.operations_root,
            before["change_id"],
        )
        expected_before = (
            workspace.operation_root / "health" / "before" / "snapshot.json"
        )
        expected_after = (
            workspace.operation_root / "health" / "after" / "snapshot.json"
        )
        if Path(args.before).resolve() != expected_before.resolve():
            raise OperationPathError(
                f"--before must be the operation Snapshot: {expected_before}"
            )
        if Path(args.after).resolve() != expected_after.resolve():
            raise OperationPathError(
                f"--after must be the operation Snapshot: {expected_after}"
            )
        resolved_path = (
            workspace.operation_root / "health" / "resolved-profiles.yaml"
        )
        resolved_profiles = load_resolved_profiles(resolved_path)
        started_at = now_in_timezone(workspace.timezone)
        if args.profile:
            requested = resolve_profiles(
                args.profile,
                change_id=workspace.change_id,
                resolved_at=started_at,
                timezone=workspace.timezone,
            )
            requested = _inherit_fixed_logging_time_range(
                requested,
                resolved_profiles,
            )
            if (
                requested["spec"]["resolved"]["effective_sha256"]
                != resolved_profiles["spec"]["resolved"]["effective_sha256"]
            ):
                raise ProfileResolutionError(
                    "compare profile does not match fixed before profile"
                )
        recheck = bool(getattr(args, "recheck", False))
        output_dir = (
            workspace.operation_root
            / "health"
            / ("report-recheck" if recheck else "report")
        )
        if args.output and Path(args.output).resolve() != output_dir.resolve():
            raise OperationPathError(
                f"--output must match the operation report path: {output_dir}"
            )
        metadata = load_operation_metadata(workspace.operation_root)
        phase_name = "compare_recheck" if recheck else "compare"
        if phase_name in metadata["spec"]["phases"]:
            raise OperationStateError(
                f"{phase_name} phase already exists and will not be overwritten"
            )
        overlay_diff = None
        with OperationLock(workspace, "health-check-compare") as lock:
            transition_phase(
                workspace,
                phase_name,
                "running",
                lock=lock,
                attempt_id=generate_attempt_id(
                    phase_name,
                    workspace.timezone,
                    now=started_at,
                ),
                reason="offline_compare_started",
                now=started_at,
            )
            try:
                completed_at = now_in_timezone(workspace.timezone)
                result = compare_snapshots(
                    before,
                    after,
                    resolved_profiles,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                result["artifacts"] = {
                    "before_snapshot": str(expected_before),
                    "after_snapshot": str(expected_after),
                    "summary": str(output_dir / "summary.md"),
                }
                profile_names = resolved_profiles["spec"]["resolved"][
                    "profile_names"
                ]
                if overlay_profile_enabled(profile_names):
                    before_overlay = build_overlay_state(before)
                    after_overlay = build_overlay_state(after)
                    overlay_diff = compare_overlay_states(
                        before_overlay,
                        after_overlay,
                    )
                    result["artifacts"].update(
                        {
                            "vni_map_diff_json": str(
                                output_dir / "vni-map-diff.json"
                            ),
                            "vni_map_diff_markdown": str(
                                output_dir / "vni-map-diff.md"
                            ),
                            "vni_map_diff_csv": str(
                                output_dir / "vni-map-diff.csv"
                            ),
                        }
                    )
                atomic_write_json(
                    workspace.operation_root,
                    output_dir / "health-result.json",
                    result,
                    kind="HealthResult",
                )
                atomic_write_bytes(
                    workspace.operation_root,
                    output_dir / "summary.md",
                    render_health_summary(result).encode("utf-8"),
                )
                if overlay_diff is not None:
                    atomic_write_json(
                        workspace.operation_root,
                        output_dir / "vni-map-diff.json",
                        overlay_diff,
                        kind="OverlayVniMapDiff",
                    )
                    atomic_write_bytes(
                        workspace.operation_root,
                        output_dir / "vni-map-diff.md",
                        render_overlay_diff_markdown(overlay_diff).encode(
                            "utf-8"
                        ),
                    )
                    atomic_write_bytes(
                        workspace.operation_root,
                        output_dir / "vni-map-diff.csv",
                        overlay_diff_csv(overlay_diff).encode("utf-8"),
                    )
                transition_phase(
                    workspace,
                    phase_name,
                    (
                        "completed"
                        if result["result"] == "PASS"
                        else "completed_with_warnings"
                    ),
                    lock=lock,
                    reason="offline_compare_completed",
                    now=completed_at,
                )
            except Exception as exc:
                failed_at = now_in_timezone(workspace.timezone)
                transition_phase(
                    workspace,
                    phase_name,
                    "failed",
                    lock=lock,
                    reason="offline_compare_failed",
                    now=failed_at,
                )
                record_operation_error(
                    workspace,
                    {
                        "code": getattr(exc, "code", "PARSER_ERROR"),
                        "phase": phase_name,
                        "at": failed_at.isoformat(timespec="seconds"),
                        "message": str(exc),
                    },
                    lock=lock,
                )
                raise
        print("=== HEALTH CHECK COMPARE SUMMARY ===")
        for line in terminal_result_lines(result):
            print(line)
        print(f"Report    : {output_dir / 'summary.md'}")
        print(f"JSON      : {output_dir / 'health-result.json'}")
        if overlay_diff is not None:
            print(f"VNI Diff  : {output_dir / 'vni-map-diff.md'}")
            print(f"VNI JSON  : {output_dir / 'vni-map-diff.json'}")
            print(f"VNI CSV   : {output_dir / 'vni-map-diff.csv'}")
        return _health_result_exit_code(result["result"])
    except (
        HealthEvaluationError,
        ProfileResolutionError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def cmd_overlay_check_discover(args: argparse.Namespace) -> None:
    """Discover new Overlay resources from existing before/after Snapshots."""
    try:
        before = _load_snapshot_file(args.before)
        after = _load_snapshot_file(args.after)
        if before.get("change_id") != after.get("change_id"):
            raise OverlayDiscoveryError("before/after change_id mismatch")
        workspace = open_operation_workspace(
            args.operations_root,
            before["change_id"],
        )
        output_path = (
            workspace.operation_root / "overlay" / "discovered-changes.yaml"
        )
        if output_path.exists():
            raise OperationStateError(
                f"discovered ChangeSet already exists: {output_path}"
            )
        generated_at = now_in_timezone(workspace.timezone)
        device_groups = None
        if args.device_groups:
            _group_document, group_resolution = load_device_groups_file(
                args.device_groups,
                allow_legacy=True,
            )
            device_groups = {
                name: value["devices"]
                for name, value in group_resolution.groups.items()
            }
        document = discover_overlay_changes(
            before,
            after,
            generated_at=generated_at,
            device_groups=device_groups,
        )
        with OperationLock(workspace, "overlay-check-discover") as lock:
            transition_phase(
                workspace,
                "overlay_discovery",
                "running",
                lock=lock,
                attempt_id=generate_attempt_id(
                    "overlay-discovery",
                    workspace.timezone,
                    now=generated_at,
                ),
                reason="overlay_discovery_started",
                now=generated_at,
            )
            atomic_write_yaml(
                workspace.operation_root,
                output_path,
                document,
                kind="OverlayChangeSet",
            )
            transition_phase(
                workspace,
                "overlay_discovery",
                (
                    "completed_with_warnings"
                    if document["status"]["conflicts"]
                    else "completed"
                ),
                lock=lock,
                reason="overlay_discovery_completed",
                now=generated_at,
            )
        print("=== OVERLAY DISCOVERY SUMMARY ===")
        print(f"Change ID : {workspace.change_id}")
        print(f"L2VNI     : {len(document['spec']['l2vnis'])}")
        print(f"L3VNI     : {len(document['spec']['l3vnis'])}")
        print(f"Conflicts : {len(document['status']['conflicts'])}")
        print(f"ChangeSet : {output_path}")
    except (
        OverlayDiscoveryError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def cmd_overlay_check_evaluate(args: argparse.Namespace) -> int:
    """Evaluate an expected or discovered ChangeSet against offline Snapshots."""
    try:
        requested_change_id = getattr(args, "change_id", None)
        if requested_change_id:
            workspace = open_operation_workspace(
                args.operations_root,
                requested_change_id,
            )
            before_path = (
                Path(args.before)
                if args.before
                else workspace.operation_root
                / "health"
                / "before"
                / "snapshot.json"
            )
            after_path = (
                Path(args.after)
                if args.after
                else workspace.operation_root
                / "health"
                / "after"
                / "snapshot.json"
            )
        else:
            if not args.before or not args.after:
                raise OverlayEvaluationError(
                    "overlay-check evaluate requires --change-id or both "
                    "--before and --after"
                )
            before_path = Path(args.before)
            after_path = Path(args.after)
            workspace = None

        before = _load_snapshot_file(before_path)
        after = _load_snapshot_file(after_path)
        if before.get("change_id") != after.get("change_id"):
            raise OverlayEvaluationError("before/after change_id mismatch")
        if workspace is None:
            workspace = open_operation_workspace(
                args.operations_root,
                before["change_id"],
            )
        elif before.get("change_id") != workspace.change_id:
            raise OverlayEvaluationError(
                "Snapshot change_id does not match --change-id"
            )
        if args.change_set:
            change_set_path = Path(args.change_set)
        else:
            declared_change_set = (
                workspace.operation_root / "inputs" / "change-set.yaml"
            )
            discovered_change_set = (
                workspace.operation_root
                / "overlay"
                / "discovered-changes.yaml"
            )
            change_set_path = (
                declared_change_set
                if declared_change_set.is_file()
                else discovered_change_set
            )
        change_set = load_overlay_change_set(change_set_path).document
        if change_set["metadata"]["change_id"] != workspace.change_id:
            raise OverlayEvaluationError(
                "ChangeSet change_id does not match operation change_id"
            )
        recheck = bool(getattr(args, "recheck", False))
        output_dir = (
            workspace.operation_root
            / "overlay"
            / "recheck"
            if recheck
            else workspace.operation_root / "overlay"
        )
        output_json = output_dir / "health-result.json"
        output_summary = output_dir / "overlay-summary.md"
        if output_json.exists() or output_summary.exists():
            raise OperationStateError(
                "Overlay evaluation artifacts already exist"
            )
        started_at = now_in_timezone(workspace.timezone)
        with OperationLock(workspace, "overlay-check-evaluate") as lock:
            workflow_state = load_operation_metadata(
                workspace.operation_root
            )["spec"]["workflow_state"]
            completes_apply_after = workflow_state in {
                "apply_completed",
                "after_running",
            }
            if recheck and workflow_state == "rollback_required":
                original_result_path = (
                    workspace.operation_root
                    / "overlay"
                    / "health-result.json"
                )
                if (
                    not original_result_path.is_file()
                    or json.loads(
                        original_result_path.read_text(encoding="utf-8")
                    ).get("result")
                    != "UNKNOWN"
                ):
                    raise OperationStateError(
                        "rollback_required can only be reconciled by "
                        "--recheck when the original Overlay result is UNKNOWN"
                    )
                completes_apply_after = True
            common_after_result = None
            if completes_apply_after:
                common_after_path = (
                    workspace.operation_root
                    / "health"
                    / (
                        "report-recheck"
                        if (
                            workspace.operation_root
                            / "health"
                            / "report-recheck"
                            / "health-result.json"
                        ).is_file()
                        else "report"
                    )
                    / "health-result.json"
                )
                if (
                    not common_after_path.is_file()
                    or common_after_path.is_symlink()
                ):
                    raise OperationStateError(
                        "common before/after HealthResult is required "
                        "before Overlay evaluation"
                    )
                common_after_result = json.loads(
                    common_after_path.read_text(encoding="utf-8")
                )
                validate_document(common_after_result, kind="HealthResult")
                if workflow_state in {
                    "apply_completed",
                    "rollback_required",
                }:
                    transition_workflow(
                        workspace,
                        "after_running",
                        lock=lock,
                        reason=(
                            "overlay_after_recheck_started"
                            if workflow_state == "rollback_required"
                            else "overlay_after_evaluation_started"
                        ),
                        now=started_at,
                    )
            transition_phase(
                workspace,
                (
                    "overlay_evaluate_recheck"
                    if recheck
                    else "overlay_evaluate"
                ),
                "running",
                lock=lock,
                attempt_id=generate_attempt_id(
                    "overlay-evaluate",
                    workspace.timezone,
                    now=started_at,
                ),
                reason="offline_overlay_evaluation_started",
                now=started_at,
            )
            try:
                completed_at = now_in_timezone(workspace.timezone)
                result = evaluate_overlay_change(
                    before,
                    after,
                    change_set,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                atomic_write_json(
                    workspace.operation_root,
                    output_json,
                    result,
                    kind="OverlayHealthResult",
                )
                atomic_write_bytes(
                    workspace.operation_root,
                    output_summary,
                    render_overlay_summary(result).encode("utf-8"),
                )
                transition_phase(
                    workspace,
                    (
                        "overlay_evaluate_recheck"
                        if recheck
                        else "overlay_evaluate"
                    ),
                    (
                        "completed"
                        if result["result"]
                        in {"VERIFIED", "OBSERVED_HEALTHY"}
                        else "completed_with_warnings"
                    ),
                    lock=lock,
                    reason="offline_overlay_evaluation_completed",
                    now=completed_at,
                )
                if completes_apply_after:
                    after_ok = (
                        common_after_result["result"] == "PASS"
                        and result["result"]
                        in {"VERIFIED", "OBSERVED_HEALTHY"}
                    )
                    transition_workflow(
                        workspace,
                        "after_completed" if after_ok else "health_failed",
                        lock=lock,
                        reason=(
                            "overlay_after_verified"
                            if after_ok
                            else "overlay_after_health_failed"
                        ),
                        now=completed_at,
                    )
                    if not after_ok:
                        transition_workflow(
                            workspace,
                            "rollback_required",
                            lock=lock,
                            reason="overlay_after_requires_rollback",
                            now=completed_at,
                        )
            except Exception as exc:
                failed_at = now_in_timezone(workspace.timezone)
                transition_phase(
                    workspace,
                    (
                        "overlay_evaluate_recheck"
                        if recheck
                        else "overlay_evaluate"
                    ),
                    "failed",
                    lock=lock,
                    reason="offline_overlay_evaluation_failed",
                    now=failed_at,
                )
                record_operation_error(
                    workspace,
                    {
                        "code": getattr(exc, "code", "PARSER_ERROR"),
                        "phase": "overlay_evaluate",
                        "at": failed_at.isoformat(timespec="seconds"),
                        "message": str(exc),
                    },
                    lock=lock,
                )
                current_workflow = load_operation_metadata(
                    workspace.operation_root
                )["spec"]["workflow_state"]
                if current_workflow == "after_running":
                    transition_workflow(
                        workspace,
                        "health_failed",
                        lock=lock,
                        reason="qualification_after_evaluation_failed",
                        now=failed_at,
                    )
                    transition_workflow(
                        workspace,
                        "rollback_required",
                        lock=lock,
                        reason="qualification_after_requires_rollback",
                        now=failed_at,
                    )
                raise
        print("=== OVERLAY HEALTH SUMMARY ===")
        print(f"Change ID     : {workspace.change_id}")
        print(f"Result        : {result['result']}")
        print(f"Configuration : {result['sections']['configuration']}")
        print(f"Operational   : {result['sections']['operational']}")
        print(f"Impact        : {result['sections']['impact']}")
        print(f"Before        : {before_path}")
        print(f"After         : {after_path}")
        print(f"ChangeSet     : {change_set_path}")
        print(f"JSON          : {output_json}")
        print(f"Summary       : {output_summary}")
        return {
            "VERIFIED": 0,
            "OBSERVED_HEALTHY": 0,
            "WARN": 1,
            "PLAN_ERROR": 2,
            "UNKNOWN": 3,
            "FAIL": 4,
        }[result["result"]]
    except (
        OverlayEvaluationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def cmd_overlay_check_converge(args: argparse.Namespace) -> int:
    """Assess an ordered set of saved Overlay health attempts."""
    try:
        results = []
        change_id = None
        for path_value in args.result:
            path = Path(path_value)
            document = json.loads(path.read_text(encoding="utf-8"))
            validate_document(document, kind="OverlayHealthResult")
            if change_id is None:
                change_id = document["change_id"]
            elif document["change_id"] != change_id:
                raise OverlayEvaluationError(
                    "convergence result change_id mismatch"
                )
            results.append(document)
        workspace = open_operation_workspace(
            args.operations_root,
            change_id,
        )
        assessment = assess_overlay_convergence(
            results,
            consecutive_passes=args.consecutive_passes,
        )
        assessment["schema_version"] = 1
        assessment["change_id"] = change_id
        for record, source in zip(
            assessment["attempts"],
            args.result,
            strict=True,
        ):
            record["source_file"] = str(Path(source))
        output_path = workspace.operation_root / "overlay" / "convergence.json"
        if output_path.exists():
            raise OperationStateError(
                f"convergence artifact already exists: {output_path}"
            )
        atomic_write_json(
            workspace.operation_root,
            output_path,
            assessment,
            kind="OverlayConvergenceResult",
        )
        print("=== OVERLAY CONVERGENCE ===")
        print(f"Change ID  : {change_id}")
        print(f"Attempts   : {len(results)}")
        print(f"Required   : {args.consecutive_passes}")
        print(f"Converged  : {'yes' if assessment['converged'] else 'no'}")
        print(f"JSON       : {output_path}")
        return 0 if assessment["converged"] else 4
    except (
        OverlayEvaluationError,
        OperationError,
        ValueError,
        OSError,
    ) as exc:
        _operation_cli_error(exc)


def cmd_support_bundle_create(args: argparse.Namespace) -> None:
    """Create a redacted support archive from one operation."""
    try:
        workspace = open_operation_workspace(
            args.operations_root,
            args.change_id,
        )
        devices = (
            [
                value.strip()
                for value in args.devices.split(",")
                if value.strip()
            ]
            if args.devices
            else None
        )
        outputs = create_support_bundle(
            workspace.operation_root,
            change_id=workspace.change_id,
            phase=args.phase,
            output_dir=args.output,
            created_at=now_in_timezone(workspace.timezone),
            timezone=workspace.timezone,
            symptom=args.symptom,
            questions=args.question,
            prompt_language=args.prompt_language,
            max_size_mib=args.max_bundle_size_mib,
            split=args.split,
            devices=devices,
            redaction_profile=args.redact_profile,
            include_generated_config=args.include_generated_config,
            include_rollback_config=args.include_rollback_config,
            include_raw_logging=args.include_raw_logging,
        )
        print("=== SUPPORT BUNDLE CREATED ===")
        for name, path in outputs.items():
            print(f"{name.capitalize():10}: {path}")
        print("Warning   : archive is redacted but not encrypted")
    except (SupportBundleError, OperationError, ValueError, OSError) as exc:
        _operation_cli_error(exc)


def cmd_support_bundle_inspect(args: argparse.Namespace) -> None:
    """Inspect a support archive without extraction."""
    try:
        result = inspect_support_bundle(args.bundle)
        print("=== SUPPORT BUNDLE INSPECT ===")
        print(f"Archive : {result['archive']}")
        print(f"Files   : {len(result['members'])}")
        for member in result["members"]:
            print(f"- {member['name']} ({member['size']} bytes)")
    except (SupportBundleError, ValueError, OSError, tarfile.TarError) as exc:
        _operation_cli_error(exc)


def cmd_support_bundle_verify(args: argparse.Namespace) -> None:
    """Verify external and internal support bundle checksums."""
    try:
        result = verify_support_bundle_manifest(args.manifest)
        print("=== SUPPORT BUNDLE VERIFIED ===")
        print(f"Archive : {result['archive']}")
        print(f"SHA-256 : {result['archive_sha256']}")
        print(f"Files   : {result['files']}")
    except (SupportBundleError, ValueError, OSError, tarfile.TarError) as exc:
        _operation_cli_error(exc)


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

    p_operation = subparsers.add_parser(
        "operation",
        help="Inspect common operation workspace state",
    )
    operation_subparsers = p_operation.add_subparsers(
        dest="operation_command",
        required=True,
    )
    for operation_name, handler, help_text in (
        ("status", cmd_operation_status, "Show concise operation state"),
        ("inspect", cmd_operation_inspect, "Show operation artifacts and history"),
    ):
        operation_parser = operation_subparsers.add_parser(
            operation_name,
            help=help_text,
        )
        operation_parser.add_argument(
            "--change-id",
            required=True,
            help="Operation change ID",
        )
        operation_parser.add_argument(
            "--operations-root",
            default=DEFAULT_OPERATIONS_ROOT,
            help=f"Operation root directory (default: {DEFAULT_OPERATIONS_ROOT})",
        )
        operation_parser.set_defaults(func=handler)

    p_overlay_change = subparsers.add_parser(
        "overlay-change",
        help="Plan, approve, apply, and rollback managed Overlay changes",
    )
    overlay_change_subparsers = p_overlay_change.add_subparsers(
        dest="overlay_change_command",
        required=True,
    )
    p_overlay_plan = overlay_change_subparsers.add_parser(
        "plan",
        help="Generate PLAN_ONLY forward and rollback artifacts",
    )
    p_overlay_plan.add_argument(
        "--change-set",
        required=True,
        help=(
            "OverlayChangeSet YAML; device_groups_ref is resolved relative "
            "to this file"
        ),
    )
    p_overlay_plan.add_argument(
        "--before",
        help=(
            "Current operation before Snapshot; when omitted, resolve the "
            "latest completed before from ChangeSet metadata.change_id"
        ),
    )
    p_overlay_plan.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        help="Inventory to pin for APPLY_VERIFIED execution",
    )
    p_overlay_plan.add_argument(
        "--capability-registry",
        help="NX-OS capability registry YAML (default: packaged registry)",
    )
    p_overlay_plan.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_plan.set_defaults(func=cmd_overlay_change_plan)
    p_overlay_prepare_plan = overlay_change_subparsers.add_parser(
        "prepare-plan",
        help=(
            "Generate a preparation-only plan from a prior healthy terminal "
            "state without device access"
        ),
    )
    p_overlay_prepare_plan.add_argument(
        "--change-set",
        required=True,
        help=(
            "OverlayChangeSet YAML; device_groups_ref is resolved relative "
            "to this file"
        ),
    )
    reference_group = p_overlay_prepare_plan.add_mutually_exclusive_group(
        required=True
    )
    reference_group.add_argument(
        "--reference-state",
        choices=["latest-known-good"],
        help="Automatically select the latest healthy terminal state",
    )
    reference_group.add_argument(
        "--reference-operation-id",
        help="Operation ID containing the healthy state to reference",
    )
    p_overlay_prepare_plan.add_argument(
        "--reference-phase",
        choices=["after", "rollback"],
        help=(
            "Reference phase for --reference-operation-id; default is "
            "derived from the terminal workflow state"
        ),
    )
    p_overlay_prepare_plan.add_argument(
        "--reference-max-age-days",
        type=int,
        default=30,
        help="Maximum reference Snapshot age in days (default: 30)",
    )
    p_overlay_prepare_plan.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_prepare_plan.set_defaults(
        func=cmd_overlay_change_prepare_plan
    )
    p_overlay_approve = overlay_change_subparsers.add_parser(
        "approve",
        help="Interactively approve exact plan and rollback artifact hashes",
    )
    p_overlay_approve.add_argument(
        "--change-id",
        required=True,
        help="Operation change ID",
    )
    p_overlay_approve.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
        help=f"Operation root directory (default: {DEFAULT_OPERATIONS_ROOT})",
    )
    p_overlay_approve.add_argument(
        "--plan",
        help=(
            "Execution plan JSON or YAML below the operation root "
            "(default: <operation>/plan/execution-plan.json)"
        ),
    )
    p_overlay_approve.add_argument(
        "--rollback-plan",
        help=(
            "Rollback plan JSON or YAML below the operation root "
            "(default: <operation>/plan/rollback-plan.json)"
        ),
    )
    p_overlay_approve.add_argument(
        "--artifact",
        action="append",
        help="Additional approved artifact as NAME=PATH (repeatable)",
    )
    p_overlay_approve.add_argument(
        "--approval-hours",
        type=int,
        default=24,
        help="Approval validity in hours, 1-24 (default: 24)",
    )
    p_overlay_approve.add_argument(
        "--max-devices",
        type=int,
        default=50,
        help="Approved maximum device count, 1-50 (default: 50)",
    )
    p_overlay_approve.add_argument(
        "--save-on-success",
        dest="save_on_success",
        action="store_true",
        help=(
            "Approve saving configuration after successful health checks "
            "(default: enabled)"
        ),
    )
    p_overlay_approve.add_argument(
        "--no-save-on-success",
        dest="save_on_success",
        action="store_false",
        help="Do not approve configuration save",
    )
    p_overlay_approve.set_defaults(save_on_success=True)
    p_overlay_approve.add_argument(
        "--rollback-policy",
        choices=["manual"],
        default="manual",
        help="Rollback policy (initial implementation: manual)",
    )
    p_overlay_approve.set_defaults(func=cmd_overlay_change_approve)
    p_overlay_apply = overlay_change_subparsers.add_parser(
        "apply",
        help="Apply an approved APPLY_VERIFIED plan serially",
        description=(
            "Revalidate approval, plan, rollback, inventory, config hashes, "
            "and live running config before serial managed apply."
        ),
    )
    p_overlay_apply.add_argument("--change-id", required=True)
    p_overlay_apply.add_argument("--approved-plan")
    p_overlay_apply.add_argument("--approved-rollback-plan")
    p_overlay_apply.add_argument("--approval-record")
    p_overlay_apply.add_argument("-u", "--user", "--username", dest="username")
    p_overlay_apply.add_argument("--password")
    p_overlay_apply.add_argument("-k", "--ask-pass", action="store_true")
    p_overlay_apply.add_argument("--enable-secret")
    p_overlay_apply.add_argument("--credentials")
    p_overlay_apply.add_argument(
        "-K", "--ask-become-pass", action="store_true"
    )
    p_overlay_apply.add_argument("--log-file")
    p_overlay_apply.add_argument("--verbose", action="store_true")
    p_overlay_apply.add_argument(
        "--operations-root", default=DEFAULT_OPERATIONS_ROOT
    )
    p_overlay_apply.set_defaults(func=cmd_overlay_change_apply)
    p_overlay_save = overlay_change_subparsers.add_parser(
        "save",
        help="Save an approved apply after common and Overlay health pass",
        description=(
            "Revalidate approval and health artifacts, verify every live "
            "running configuration against the after Snapshot, then save "
            "serially without retry."
        ),
    )
    p_overlay_save.add_argument("--change-id", required=True)
    p_overlay_save.add_argument("--approved-plan")
    p_overlay_save.add_argument("--approved-rollback-plan")
    p_overlay_save.add_argument("--approval-record")
    p_overlay_save.add_argument("--after-snapshot")
    p_overlay_save.add_argument(
        "-u", "--user", "--username", dest="username"
    )
    p_overlay_save.add_argument("--password")
    p_overlay_save.add_argument("-k", "--ask-pass", action="store_true")
    p_overlay_save.add_argument("--enable-secret")
    p_overlay_save.add_argument("--credentials")
    p_overlay_save.add_argument(
        "-K", "--ask-become-pass", action="store_true"
    )
    p_overlay_save.add_argument("--log-file")
    p_overlay_save.add_argument("--verbose", action="store_true")
    p_overlay_save.add_argument(
        "--operations-root", default=DEFAULT_OPERATIONS_ROOT
    )
    p_overlay_save.set_defaults(func=cmd_overlay_change_save)
    p_overlay_rollback_save = overlay_change_subparsers.add_parser(
        "save-rollback",
        help="Save the restored baseline after verified rollback",
        description=(
            "After rollback health plus raw and semantic restoration pass, "
            "verify every live running configuration against the rollback "
            "Snapshot, then restore startup-config serially without retry."
        ),
    )
    p_overlay_rollback_save.add_argument("--change-id", required=True)
    p_overlay_rollback_save.add_argument("--approved-plan")
    p_overlay_rollback_save.add_argument("--approved-rollback-plan")
    p_overlay_rollback_save.add_argument("--approval-record")
    p_overlay_rollback_save.add_argument(
        "--after-snapshot",
        help="Rollback Snapshot (default: operation health/rollback)",
    )
    p_overlay_rollback_save.add_argument(
        "-u", "--user", "--username", dest="username"
    )
    p_overlay_rollback_save.add_argument("--password")
    p_overlay_rollback_save.add_argument(
        "-k", "--ask-pass", action="store_true"
    )
    p_overlay_rollback_save.add_argument("--enable-secret")
    p_overlay_rollback_save.add_argument("--credentials")
    p_overlay_rollback_save.add_argument(
        "-K", "--ask-become-pass", action="store_true"
    )
    p_overlay_rollback_save.add_argument("--log-file")
    p_overlay_rollback_save.add_argument(
        "--verbose", action="store_true"
    )
    p_overlay_rollback_save.add_argument(
        "--operations-root", default=DEFAULT_OPERATIONS_ROOT
    )
    p_overlay_rollback_save.set_defaults(
        func=cmd_overlay_change_save,
        save_mode="rollback",
    )
    p_overlay_rollback = overlay_change_subparsers.add_parser(
        "rollback",
        help="Run the approved inverse configuration in reverse order",
        description=(
            "Validate approved hashes and same-session after Snapshot drift, "
            "then run the pinned rollback serially without retry or save."
        ),
    )
    p_overlay_rollback.add_argument("--change-id", required=True)
    p_overlay_rollback.add_argument("--approved-plan")
    p_overlay_rollback.add_argument("--approved-rollback-plan")
    p_overlay_rollback.add_argument("--approval-record")
    p_overlay_rollback.add_argument("--current-snapshot")
    p_overlay_rollback.add_argument(
        "-u", "--user", "--username", dest="username"
    )
    p_overlay_rollback.add_argument("--password")
    p_overlay_rollback.add_argument("-k", "--ask-pass", action="store_true")
    p_overlay_rollback.add_argument("--enable-secret")
    p_overlay_rollback.add_argument("--credentials")
    p_overlay_rollback.add_argument(
        "-K", "--ask-become-pass", action="store_true"
    )
    p_overlay_rollback.add_argument("--log-file")
    p_overlay_rollback.add_argument("--verbose", action="store_true")
    p_overlay_rollback.add_argument(
        "--operations-root", default=DEFAULT_OPERATIONS_ROOT
    )
    p_overlay_rollback.set_defaults(func=cmd_overlay_change_rollback)
    p_overlay_qualify_approve = overlay_change_subparsers.add_parser(
        "qualify-approve",
        help=(
            "Interactively approve a PLAN_ONLY Nexus 9000v candidate "
            "for initial lab qualification"
        ),
        description=(
            "Interactively approve a PLAN_ONLY Nexus 9000v candidate "
            "for initial lab qualification. This does not send configuration."
        ),
    )
    p_overlay_qualify_approve.add_argument(
        "--change-id",
        required=True,
        help="Operation change ID",
    )
    p_overlay_qualify_approve.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        required=True,
        help="Exact hosts.yaml source to pin for qualification",
    )
    p_overlay_qualify_approve.add_argument("--plan")
    p_overlay_qualify_approve.add_argument("--rollback-plan")
    p_overlay_qualify_approve.add_argument("--before-snapshot")
    p_overlay_qualify_approve.add_argument("--before-health-result")
    p_overlay_qualify_approve.add_argument("--change-set")
    p_overlay_qualify_approve.add_argument("--render-manifest")
    p_overlay_qualify_approve.add_argument(
        "--approval-hours",
        type=int,
        default=4,
        help="Qualification validity in hours, 1-4 (default: 4)",
    )
    p_overlay_qualify_approve.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_qualify_approve.set_defaults(
        func=cmd_overlay_change_qualify_approve
    )
    p_overlay_qualify = overlay_change_subparsers.add_parser(
        "qualify",
        help=(
            "Apply an interactively approved Nexus 9000v qualification "
            "candidate without saving"
        ),
        description=(
            "Apply an approved initial Nexus 9000v qualification candidate "
            "with serial=1, no retry, no automatic rollback, and no save."
        ),
    )
    p_overlay_qualify.add_argument("--change-id", required=True)
    p_overlay_qualify.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        required=True,
        help="Exact hosts.yaml pinned by qualify-approve",
    )
    p_overlay_qualify.add_argument("--qualification-record")
    p_overlay_qualify.add_argument(
        "-u",
        "--user",
        "--username",
        dest="username",
    )
    p_overlay_qualify.add_argument("--password")
    p_overlay_qualify.add_argument(
        "-k",
        "--ask-pass",
        action="store_true",
    )
    p_overlay_qualify.add_argument("--enable-secret")
    p_overlay_qualify.add_argument("--credentials")
    p_overlay_qualify.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
    )
    p_overlay_qualify.add_argument("--log-file")
    p_overlay_qualify.add_argument("--verbose", action="store_true")
    p_overlay_qualify.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_qualify.set_defaults(func=cmd_overlay_change_qualify)
    p_overlay_qualify_rollback = overlay_change_subparsers.add_parser(
        "qualify-rollback",
        help=(
            "Rollback an initial Nexus 9000v qualification without saving"
        ),
        description=(
            "Run the pinned rollback in reverse device order after an "
            "after snapshot (including emergency collection). The live "
            "running configuration "
            "must match that snapshot. No retry or save is performed."
        ),
    )
    p_overlay_qualify_rollback.add_argument("--change-id", required=True)
    p_overlay_qualify_rollback.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        required=True,
        help="Exact hosts.yaml pinned by qualify-approve",
    )
    p_overlay_qualify_rollback.add_argument("--qualification-record")
    p_overlay_qualify_rollback.add_argument(
        "--current-snapshot",
        help=(
            "After Snapshot (including emergency collection) used for the "
            "same-session drift check (default: operation health/after)"
        ),
    )
    p_overlay_qualify_rollback.add_argument(
        "-u",
        "--user",
        "--username",
        dest="username",
    )
    p_overlay_qualify_rollback.add_argument("--password")
    p_overlay_qualify_rollback.add_argument(
        "-k",
        "--ask-pass",
        action="store_true",
    )
    p_overlay_qualify_rollback.add_argument("--enable-secret")
    p_overlay_qualify_rollback.add_argument("--credentials")
    p_overlay_qualify_rollback.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
    )
    p_overlay_qualify_rollback.add_argument("--log-file")
    p_overlay_qualify_rollback.add_argument(
        "--verbose",
        action="store_true",
    )
    p_overlay_qualify_rollback.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_qualify_rollback.set_defaults(
        func=cmd_overlay_change_qualify_rollback
    )
    p_overlay_qualify_save = overlay_change_subparsers.add_parser(
        "qualify-save-baseline",
        help=(
            "Qualify NX-OS configuration save after verified rollback"
        ),
        description=(
            "After qualification rollback is fully verified, require the "
            "live running configuration to match before and require no "
            "running/startup diff, then save serially without retry."
        ),
    )
    p_overlay_qualify_save.add_argument("--change-id", required=True)
    p_overlay_qualify_save.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        required=True,
        help="Exact hosts.yaml pinned by qualify-approve",
    )
    p_overlay_qualify_save.add_argument("--qualification-record")
    p_overlay_qualify_save.add_argument(
        "-u",
        "--user",
        "--username",
        dest="username",
    )
    p_overlay_qualify_save.add_argument("--password")
    p_overlay_qualify_save.add_argument(
        "-k",
        "--ask-pass",
        action="store_true",
    )
    p_overlay_qualify_save.add_argument("--enable-secret")
    p_overlay_qualify_save.add_argument("--credentials")
    p_overlay_qualify_save.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
    )
    p_overlay_qualify_save.add_argument("--log-file")
    p_overlay_qualify_save.add_argument(
        "--verbose",
        action="store_true",
    )
    p_overlay_qualify_save.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_qualify_save.set_defaults(
        func=cmd_overlay_change_qualify_save_baseline
    )

    p_health_check = subparsers.add_parser(
        "health-check",
        help="Build and evaluate reusable health snapshots",
    )
    health_check_subparsers = p_health_check.add_subparsers(
        dest="health_check_command",
        required=True,
    )
    for phase_name in ("before", "after", "rollback"):
        phase_parser = health_check_subparsers.add_parser(
            phase_name,
            help=(
                f"Run {phase_name} health check from existing input or "
                "the shared collect runner"
            ),
        )
        input_mode = phase_parser.add_mutually_exclusive_group(
            required=phase_name == "before"
        )
        input_mode.add_argument(
            "--input",
            action="append",
            help=(
                "Existing input file/directory (repeatable; after/rollback "
                "require this when before used offline input)"
            ),
        )
        phase_parser.add_argument(
            "--input-format",
            choices=["alred-collect", "nxos-transcript"],
            help=(
                "Required with --input except after/rollback inherit the "
                "format from an offline before; automatic detection is not "
                "used"
            ),
        )
        input_mode.add_argument(
            "--collect",
            action="store_true",
            help=(
                "Access devices through the existing collect runner "
                "(after/rollback inherit this when before used direct "
                "collection)"
            ),
        )
        phase_parser.add_argument(
            "--change-id",
            help=(
                "Operation change ID; before generates one when omitted, "
                "after resolves a valid active before, rollback requires an "
                "existing operation ID"
            ),
        )
        phase_parser.add_argument(
            "--profile",
            action="append",
            help=(
                "Profile reference (repeatable; before default: "
                "network-baseline-nxos; after/rollback inherit before)"
            ),
        )
        if phase_name == "before":
            phase_parser.add_argument(
                "--revision-reason",
                help=(
                    "Auditable reason that explicitly authorizes a fixed "
                    "profile revision before plan"
                ),
            )
        _add_logging_time_range_arguments(phase_parser)
        phase_parser.add_argument(
            "-i",
            "--inventory",
            "--hosts",
            dest="hosts",
            help=(
                "hosts.yaml for direct collection or transcript aliases; "
                "after/rollback inherit and hash-verify the before inventory"
            ),
        )
        phase_parser.add_argument("--policy", help="Collection policy YAML")
        phase_parser.add_argument(
            "-u", "--user", "--username", dest="username"
        )
        phase_parser.add_argument("--password")
        phase_parser.add_argument(
            "-k", "--ask-pass", action="store_true"
        )
        phase_parser.add_argument("--enable-secret")
        phase_parser.add_argument("--credentials")
        phase_parser.add_argument(
            "-K", "--ask-become-pass", action="store_true"
        )
        phase_parser.add_argument(
            "--transport",
            choices=["auto", "nxapi", "ssh"],
            default=None if phase_name in {"after", "rollback"} else "ssh",
            help=(
                "Command transport (default: ssh; after/rollback inherit the "
                "before transport when an execution context exists)"
            ),
        )
        phase_parser.add_argument("--target-hosts")
        phase_parser.add_argument(
            "--workers",
            type=int,
            default=None if phase_name in {"after", "rollback"} else 5,
        )
        phase_parser.add_argument(
            "--show-read-timeout",
            type=int,
            default=None if phase_name in {"after", "rollback"} else 120,
        )
        phase_parser.add_argument(
            "--skip-connect-check",
            action="store_true",
            default=(
                None if phase_name in {"after", "rollback"} else False
            ),
        )
        phase_parser.add_argument(
            "--connect-check-timeout",
            type=float,
            default=(
                None
                if phase_name in {"after", "rollback"}
                else DEFAULT_CONNECT_CHECK_TIMEOUT
            ),
        )
        phase_parser.add_argument("--verbose", action="store_true")
        phase_parser.add_argument(
            "--operations-root",
            default=DEFAULT_OPERATIONS_ROOT,
        )
        phase_parser.add_argument(
            "--output",
            help="Phase output path; must match <operation>/health/<phase>",
        )
        phase_parser.add_argument(
            "--timezone",
            help="IANA timezone (default: ALRED_TIMEZONE or Asia/Tokyo)",
        )
        phase_parser.set_defaults(func=cmd_health_check_phase)
    p_health_snapshot = health_check_subparsers.add_parser(
        "snapshot",
        help="Build a Snapshot from existing collect or transcript files",
    )
    p_health_snapshot.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input file or directory (repeatable)",
    )
    p_health_snapshot.add_argument(
        "--input-format",
        choices=["alred-collect", "nxos-transcript"],
        required=True,
        help="Explicit input adapter; automatic detection is not used",
    )
    p_health_snapshot.add_argument(
        "--phase",
        choices=["before", "after"],
        required=True,
        help="Snapshot phase",
    )
    p_health_snapshot.add_argument(
        "--change-id",
        help="Operation change ID; generated for before when omitted",
    )
    p_health_snapshot.add_argument(
        "--profile",
        action="append",
        help=(
            "Profile reference recorded in the Snapshot (repeatable; "
            "before default: network-baseline-nxos)"
        ),
    )
    _add_logging_time_range_arguments(p_health_snapshot)
    p_health_snapshot.add_argument(
        "--hosts",
        help="Optional hosts.yaml used for transcript hostname aliases",
    )
    p_health_snapshot.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
        help=f"Operation root directory (default: {DEFAULT_OPERATIONS_ROOT})",
    )
    p_health_snapshot.add_argument(
        "--output",
        help="Phase output path; must match <operation>/health/<phase>",
    )
    p_health_snapshot.add_argument(
        "--timezone",
        help="IANA timezone (default: ALRED_TIMEZONE or Asia/Tokyo)",
    )
    p_health_snapshot.add_argument(
        "--recheck",
        action="store_true",
        help=(
            "Reparse immutable input into health/<phase>-recheck without "
            "replacing the original Snapshot"
        ),
    )
    p_health_snapshot.set_defaults(func=cmd_health_check_snapshot)
    p_health_compare = health_check_subparsers.add_parser(
        "compare",
        help="Compare existing before and after Snapshots offline",
    )
    p_health_compare.add_argument(
        "--before",
        required=True,
        help="Before snapshot.json",
    )
    p_health_compare.add_argument(
        "--after",
        required=True,
        help="After snapshot.json",
    )
    p_health_compare.add_argument(
        "--profile",
        action="append",
        help="Optional explicit profile reference for hash verification",
    )
    p_health_compare.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
        help=f"Operation root directory (default: {DEFAULT_OPERATIONS_ROOT})",
    )
    p_health_compare.add_argument(
        "--output",
        help=(
            "Report path; must match <operation>/health/report or "
            "report-recheck with --recheck"
        ),
    )
    p_health_compare.add_argument(
        "--recheck",
        action="store_true",
        help=(
            "Re-evaluate immutable before/after Snapshots into "
            "health/report-recheck without replacing the original report"
        ),
    )
    p_health_compare.set_defaults(func=cmd_health_check_compare)

    p_overlay_check = subparsers.add_parser(
        "overlay-check",
        help="Analyze Overlay state without applying configuration",
    )
    overlay_check_subparsers = p_overlay_check.add_subparsers(
        dest="overlay_check_command",
        required=True,
    )
    p_overlay_discover = overlay_check_subparsers.add_parser(
        "discover",
        help="Discover new Overlay resources from before/after Snapshots",
    )
    p_overlay_discover.add_argument("--before", required=True)
    p_overlay_discover.add_argument("--after", required=True)
    p_overlay_discover.add_argument(
        "--device-groups",
        help=(
            "Optional OverlayDeviceGroups YAML (hierarchy supported) or "
            "legacy mapping; exact memberships compress discovered targets"
        ),
    )
    p_overlay_discover.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_discover.set_defaults(func=cmd_overlay_check_discover)
    p_overlay_evaluate = overlay_check_subparsers.add_parser(
        "evaluate",
        help="Evaluate Overlay configuration, operation, and impact offline",
    )
    p_overlay_evaluate.add_argument(
        "--change-id",
        help=(
            "Operation change ID; defaults before/after Snapshots and the "
            "pinned ChangeSet from the operation workspace"
        ),
    )
    p_overlay_evaluate.add_argument(
        "--before",
        help=(
            "Before Snapshot JSON (default with --change-id: "
            "health/before/snapshot.json)"
        ),
    )
    p_overlay_evaluate.add_argument(
        "--after",
        help=(
            "After Snapshot JSON (default with --change-id: "
            "health/after/snapshot.json)"
        ),
    )
    p_overlay_evaluate.add_argument(
        "--change-set",
        help=(
            "Expected/discovered ChangeSet YAML (default: operation "
            "inputs/change-set.yaml, then overlay/discovered-changes.yaml)"
        ),
    )
    p_overlay_evaluate.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_evaluate.add_argument(
        "--recheck",
        action="store_true",
        help=(
            "Write immutable re-evaluation under overlay/recheck; an "
            "original UNKNOWN may reconcile rollback_required"
        ),
    )
    p_overlay_evaluate.set_defaults(func=cmd_overlay_check_evaluate)
    p_overlay_converge = overlay_check_subparsers.add_parser(
        "converge",
        help="Assess ordered saved Overlay health results",
    )
    p_overlay_converge.add_argument(
        "--result",
        action="append",
        required=True,
        help="OverlayHealthResult JSON in attempt order (repeatable)",
    )
    p_overlay_converge.add_argument(
        "--consecutive-passes",
        type=int,
        default=2,
    )
    p_overlay_converge.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_overlay_converge.set_defaults(func=cmd_overlay_check_converge)

    p_support = subparsers.add_parser(
        "support-bundle",
        help="Create and verify redacted operation support archives",
    )
    support_subparsers = p_support.add_subparsers(
        dest="support_bundle_command",
        required=True,
    )
    p_support_create = support_subparsers.add_parser("create")
    p_support_create.add_argument("--change-id", required=True)
    p_support_create.add_argument(
        "--phase",
        choices=["before", "after", "rollback", "all"],
        required=True,
    )
    p_support_create.add_argument(
        "--split",
        choices=["none", "phase", "device"],
        default="none",
    )
    p_support_create.add_argument(
        "--devices",
        help="Comma-separated hostnames; default is all manifest hosts",
    )
    p_support_create.add_argument(
        "--redact-profile",
        help="Site-specific SupportBundleRedactionPolicy YAML",
    )
    p_support_create.add_argument(
        "--include-generated-config",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_support_create.add_argument(
        "--include-rollback-config",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_support_create.add_argument(
        "--include-raw-logging",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_support_create.add_argument(
        "--max-bundle-size-mib",
        type=int,
        default=100,
    )
    p_support_create.add_argument(
        "--prompt-language",
        choices=["ja", "en"],
        default="ja",
    )
    p_support_create.add_argument("--symptom")
    p_support_create.add_argument("--question", action="append")
    p_support_create.add_argument(
        "--operations-root",
        default=DEFAULT_OPERATIONS_ROOT,
    )
    p_support_create.add_argument(
        "--output",
        default="support-bundles",
    )
    p_support_create.set_defaults(func=cmd_support_bundle_create)
    p_support_inspect = support_subparsers.add_parser("inspect")
    p_support_inspect.add_argument("--bundle", required=True)
    p_support_inspect.set_defaults(func=cmd_support_bundle_inspect)
    p_support_verify = support_subparsers.add_parser("verify")
    p_support_verify.add_argument("--manifest", required=True)
    p_support_verify.set_defaults(func=cmd_support_bundle_verify)

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
    p_transform.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_transform.add_argument(
        "--clab-env",
        help="containerlab env YAML used to read mgmt.ipv4-subnet (default: ./clab_merge.yaml if exists)",
    )
    p_transform.add_argument(
        "--node-map",
        help="CSV mapping source/production hostnames and management IPs to target/lab values",
    )
    p_transform.add_argument(
        "--cables",
        help="Cable CSV used to warn about transformed interface description mismatches",
    )
    p_transform.add_argument(
        "--mappings",
        help="Mappings YAML used to normalize cable and description endpoints",
    )
    p_transform.add_argument(
        "--description-rules",
        help=f"Description rules YAML used with --cables (default: ./{DEFAULT_DESCRIPTION_RULES_PATH} if exists)",
    )
    p_transform.add_argument("-u", "--user", "--username", dest="username", help="Lab username for NX-OS startup-config")
    p_transform.add_argument("--password", help="Lab password for NX-OS startup-config")
    p_transform.add_argument(
        "--credentials",
        help="Credentials YAML path used for NX-OS lab users (default: ./clab_credentials.yaml if exists)",
    )
    p_transform.add_argument(
        "--delete-username",
        action="store_true",
        help="Remove NX-OS username and snmp-server user lines instead of adding a lab user",
    )
    p_transform.add_argument(
        "--delete-access-class",
        action="store_true",
        help="Remove access-class commands from NX-OS line vty sections",
    )
    p_transform.add_argument(
        "--input",
        default=default_raw_dir,
        help="Raw root directory for source running-config files (reads <input>/config when present)",
    )
    p_transform.add_argument(
        "--file-suffix",
        default="_run.txt",
        help="Optional literal suffix in input filename pattern: <hostname><suffix>",
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

    p_init_clab = subparsers.add_parser(
        "init-clab",
        help="Generate containerlab YAML from hosts.txt and a cable CSV",
    )
    p_init_clab.add_argument(
        "--hosts",
        dest="design_hosts",
        default="hosts.txt",
        help="Input hosts.txt (default: ./hosts.txt)",
    )
    p_init_clab.add_argument("--cables", required=True, help="Input cable CSV")
    p_init_clab.add_argument(
        "--clab-env",
        help="containerlab environment YAML for mgmt IP conversion and merge (default: ./clab_merge.yaml if exists)",
    )
    p_init_clab.add_argument("--mappings", help="Mappings YAML path")
    p_init_clab.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_init_clab.add_argument("--sites", help=f"Site detection YAML path (default: ./{DEFAULT_SITES_PATH} if exists)")
    p_init_clab.add_argument("--clab-merge", help="Additional YAML to merge after --clab-env")
    p_init_clab.add_argument("--clab-lab-profile", help="Lab profile YAML merged last")
    p_init_clab.add_argument(
        "--n9kv-startup-delay",
        "--startup-delay-nxos",
        dest="n9kv_startup_delay",
        help="Add staggered startup-delay to cisco_n9kv nodes as BATCH,SECONDS, e.g. 5,600",
    )
    p_init_clab.add_argument(
        "--group-by-role",
        dest="group_by_role",
        action="store_true",
        help="Add role-based group to topology.nodes",
    )
    p_init_clab.add_argument(
        "--no-group-by-role",
        dest="group_by_role",
        action="store_false",
        help="Do not add role-based group to topology.nodes",
    )
    p_init_clab.set_defaults(group_by_role=True)
    p_init_clab.add_argument(
        "--name",
        help=f"Topology name override (default: {DEFAULT_CLAB_TOPOLOGY_NAME}, or merged YAML name)",
    )
    p_init_clab.add_argument(
        "--output",
        default=f"{default_topology_dir}/{DEFAULT_TOPOLOGY_CLAB_FILENAME}",
        help="Output containerlab YAML",
    )
    p_init_clab.add_argument(
        "--output-normalized",
        default=f"{default_topology_dir}/links_design_normalized.csv",
        help="Output normalized cable CSV",
    )
    p_init_clab.add_argument(
        "--validation-report",
        default=f"{default_topology_dir}/init_clab_validation.md",
        help="Output validation report",
    )
    p_init_clab.add_argument("--validate-only", action="store_true", help="Validate inputs without generating topology YAML")
    p_init_clab.add_argument("--log-file", default=f"{default_log_dir}/init-clab.log", help="Log file path")
    p_init_clab.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_init_clab.set_defaults(func=cmd_init_clab)

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
        p.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
        p.add_argument("--policy", help="Policy YAML path")
        p.add_argument(
            "--roles",
            help=f"Role detection YAML path for grouped show commands (default: ./{DEFAULT_ROLES_PATH} if exists)",
        )
        p.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
        p.add_argument("--password", help="SSH password")
        p.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
        p.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
        p.add_argument(
            "--credentials",
            help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
        )
        p.add_argument(
            "-K",
            "--ask-become-pass",
            action="store_true",
            help="Prompt for enable secret / become password at runtime",
        )
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
        help="Run only extra show mode (--show-commands-file/--show-run-diff/--show-run-diff-commands) and skip base LLDP/running-config collection",
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
        help="Collect with --show-run-diff-commands mode",
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
    p_check_logging.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_check_logging.add_argument("--policy", help="Policy YAML path")
    p_check_logging.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
    p_check_logging.add_argument("--password", help="SSH password")
    p_check_logging.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
    p_check_logging.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_check_logging.add_argument(
        "--credentials",
        help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
    )
    p_check_logging.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
        help="Prompt for enable secret / become password at runtime",
    )
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

    p_check_clab_startup = subparsers.add_parser(
        "check-clab-startup-config",
        help="Compare generated startup-config and live running-config on lab nodes",
    )
    p_check_clab_startup.add_argument(
        "-i",
        "--inventory",
        "--hosts",
        dest="hosts",
        help="Input hosts YAML (default: ./hosts.lab.yaml, then ./hosts.yaml)",
    )
    p_check_clab_startup.add_argument("--policy", help="Policy YAML path")
    p_check_clab_startup.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
    p_check_clab_startup.add_argument("--password", help="SSH password")
    p_check_clab_startup.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
    p_check_clab_startup.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_check_clab_startup.add_argument(
        "--credentials",
        help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
    )
    p_check_clab_startup.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
        help="Prompt for enable secret / become password at runtime",
    )
    p_check_clab_startup.add_argument(
        "--target-hosts",
        help="Comma-separated target hostnames for startup-config verification",
    )
    p_check_clab_startup.add_argument(
        "--startup-dir",
        default=f"{default_raw_dir}/labconfig",
        help="Directory containing generated startup-config files (<hostname><suffix>)",
    )
    p_check_clab_startup.add_argument(
        "--file-suffix",
        default="_run.txt",
        help="Optional literal suffix in startup-config filename pattern: <hostname><suffix>",
    )
    p_check_clab_startup.add_argument(
        "--output-dir",
        default=f"{default_output_dir}/check-clab-startup-config",
        help="Output directory for current running-config snapshots and report",
    )
    p_check_clab_startup.add_argument("--workers", type=int, default=5, help="Number of parallel device checks")
    p_check_clab_startup.add_argument(
        "--skip-connect-check",
        action="store_true",
        help="Skip default pre-flight connectivity/authentication checks before device operations",
    )
    p_check_clab_startup.add_argument(
        "--connect-check-timeout",
        type=float,
        default=DEFAULT_CONNECT_CHECK_TIMEOUT,
        help="Timeout in seconds for pre-flight TCP/authentication checks",
    )
    p_check_clab_startup.add_argument(
        "--log-file",
        default=f"{default_log_dir}/check-clab-startup-config.log",
        help="Log file path",
    )
    p_check_clab_startup.add_argument("--verbose", action="store_true", help="Verbose logging")
    p_check_clab_startup.set_defaults(func=cmd_check_clab_startup_config)

    p_clab_set = subparsers.add_parser(
        "clab-set-cmds",
        help="Run the predefined collect/normalize/containerlab/Mermaid/VNI pipeline",
    )
    p_clab_set.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_clab_set.add_argument("--policy", help="Policy YAML path")
    p_clab_set.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
    p_clab_set.add_argument("--password", help="SSH password")
    p_clab_set.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
    p_clab_set.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_clab_set.add_argument(
        "--credentials",
        help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
    )
    p_clab_set.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
        help="Prompt for enable secret / become password at runtime",
    )
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
    p_clab_set.add_argument(
        "--sites",
        help=f"Site detection YAML path override for render steps (default: ./{DEFAULT_SITES_PATH} if exists)",
    )
    p_clab_set.add_argument("--group-by-site", action="store_true", help="Group rendered diagrams by site/domain metadata or sites.yaml")
    p_clab_set.add_argument("--linux-csv", help="CSV override for generate-clab")
    p_clab_set.add_argument("--kind-cluster-csv", help="Kind cluster CSV override for generate-clab")
    p_clab_set.add_argument("--clab-env", help="YAML override for clab-transform-config")
    p_clab_set.add_argument(
        "--node-map",
        help="CSV mapping source/production hostnames and management IPs to target/lab values",
    )
    p_clab_set.add_argument(
        "--cables",
        help="Cable CSV used to validate transformed interface descriptions",
    )
    p_clab_set.add_argument(
        "--delete-username",
        action="store_true",
        help="Remove NX-OS username and snmp-server user lines from generated startup-configs",
    )
    p_clab_set.add_argument(
        "--delete-access-class",
        action="store_true",
        help="Remove access-class commands from NX-OS line vty sections in generated startup-configs",
    )
    p_clab_set.add_argument(
        "--file-suffix",
        default=None,
        help="Suffix for clab-transform-config input filename pattern: <hostname><suffix>",
    )
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
        p.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
        p.add_argument("--policy", help="Policy YAML path")
        p.add_argument(
            "--roles",
            help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)",
        )
        p.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
        p.add_argument("--password", help="SSH password")
        p.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
        p.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
        p.add_argument(
            "--credentials",
            help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
        )
        p.add_argument(
            "-K",
            "--ask-become-pass",
            action="store_true",
            help="Prompt for enable secret / become password at runtime",
        )
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
    p_norm.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
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
    p_gen.add_argument("-i", "--inventory", "--hosts", dest="hosts", help="Input hosts YAML (default: ./hosts.lab.yaml, then ./hosts.yaml)")
    p_gen.add_argument("--mappings", help="Mappings YAML path")
    p_gen.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_gen.add_argument("--sites", help=f"Site detection YAML path (default: ./{DEFAULT_SITES_PATH} if exists)")
    p_gen.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_gen.add_argument(
        "--n9kv-startup-delay",
        "--startup-delay-nxos",
        dest="n9kv_startup_delay",
        help="Add staggered startup-delay to cisco_n9kv nodes as BATCH,SECONDS, e.g. 5,600",
    )
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
        help="Input confirmed links CSV or containerlab YAML",
    )
    p_mermaid.add_argument("--input-format", choices=["auto", "csv", "clab"], default="auto", help="Input format (default: auto)")
    p_mermaid.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_mermaid.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_mermaid.add_argument("--mappings", help="Mappings YAML path")
    p_mermaid.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_mermaid.add_argument("--sites", help=f"Site detection YAML path (default: ./{DEFAULT_SITES_PATH} if exists)")
    p_mermaid.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_mermaid.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_mermaid.add_argument("--group-by-role", action="store_true")
    p_mermaid.add_argument("--group-by-site", action="store_true", help="Group nodes by site/domain metadata or sites.yaml")
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
        help="Input confirmed links CSV or containerlab YAML",
    )
    p_graphviz.add_argument("--input-format", choices=["auto", "csv", "clab"], default="auto", help="Input format (default: auto)")
    p_graphviz.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_graphviz.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_graphviz.add_argument("--mappings", help="Mappings YAML path")
    p_graphviz.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_graphviz.add_argument("--sites", help=f"Site detection YAML path (default: ./{DEFAULT_SITES_PATH} if exists)")
    p_graphviz.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_graphviz.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_graphviz.add_argument("--group-by-role", action="store_true")
    p_graphviz.add_argument("--group-by-site", action="store_true", help="Group nodes by site/domain metadata or sites.yaml")
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
        help="Input confirmed links CSV or containerlab YAML",
    )
    p_drawio.add_argument("--input-format", choices=["auto", "csv", "clab"], default="auto", help="Input format (default: auto)")
    p_drawio.add_argument("--input-candidates", help="Optional input candidate links CSV")
    p_drawio.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_drawio.add_argument("--mappings", help="Mappings YAML path")
    p_drawio.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_drawio.add_argument("--sites", help=f"Site detection YAML path (default: ./{DEFAULT_SITES_PATH} if exists)")
    p_drawio.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_drawio.add_argument("--direction", choices=["TD", "LR", "BT", "RL"], default="TD")
    p_drawio.add_argument("--group-by-role", action="store_true")
    p_drawio.add_argument("--group-by-site", action="store_true", help="Group nodes by site/domain metadata or sites.yaml")
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
    p_doc.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH} if exists)")
    p_doc.add_argument("--mappings", help="Mappings YAML path")
    p_doc.add_argument("--roles", help=f"Role detection YAML path (default: ./{DEFAULT_ROLES_PATH} if exists)")
    p_doc.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low")
    p_doc.add_argument(
        "--n9kv-startup-delay",
        "--startup-delay-nxos",
        dest="n9kv_startup_delay",
        help="Add staggered startup-delay to cisco_n9kv nodes as BATCH,SECONDS, e.g. 5,600",
    )
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
    p_vni_cfg.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
    p_vni_cfg.add_argument("--policy", help="Policy YAML path")
    p_vni_cfg.add_argument("-u", "--user", "--username", dest="username", help="SSH username")
    p_vni_cfg.add_argument("--password", help="SSH password")
    p_vni_cfg.add_argument("-k", "--ask-pass", action="store_true", help="Prompt for SSH password at runtime")
    p_vni_cfg.add_argument("--enable-secret", help="Enable password for devices that require privileged exec")
    p_vni_cfg.add_argument(
        "--credentials",
        help="Credentials YAML path (default: ./clab_credentials.yaml if exists)",
    )
    p_vni_cfg.add_argument(
        "-K",
        "--ask-become-pass",
        action="store_true",
        help="Prompt for enable secret / become password at runtime",
    )
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
    p_tf.add_argument("-i", "--inventory", "--hosts", dest="hosts", help=f"Input hosts.yaml (default: ./{DEFAULT_HOSTS_PATH})")
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

    p_completion = subparsers.add_parser("completion", help="Print shell completion script")
    p_completion.add_argument("shell", choices=["bash", "zsh"], help="Target shell")
    p_completion.set_defaults(func=cmd_completion)

    p_internal_complete = subparsers.add_parser("__complete", help=argparse.SUPPRESS)
    p_internal_complete.add_argument("shell", choices=["bash", "zsh"], help=argparse.SUPPRESS)
    p_internal_complete.add_argument("cword", type=int, help=argparse.SUPPRESS)
    p_internal_complete.add_argument("words", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    p_internal_complete.set_defaults(func=cmd_internal_complete)
    _hide_subparser_from_help(subparsers, "__complete")
    return parser


def main() -> None:
    """
    Main CLI entrypoint.
    """
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    apply_password_prompt_options(args)
    try:
        result = args.func(args)
    except (OperationError, ProfileResolutionError) as exc:
        _operation_cli_error(exc)
    if isinstance(result, int) and result:
        raise SystemExit(result)
