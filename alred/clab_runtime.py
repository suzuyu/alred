"""Containerlab runtime readiness checks used before post-boot config push."""

from __future__ import annotations

import json
import difflib
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

import yaml


class ClabReadinessError(ValueError):
    """Raised when a required Containerlab node cannot become ready."""

    code = "CLAB_NODE_NOT_READY"


class ClabApplyError(RuntimeError):
    """Raised after config mutation when apply or reconnect verification fails."""

    code = "APPLY_FAILED"


_SEMANTIC_PREFIXES = (
    "hostname ",
    "interface mgmt0",
    "ip address ",
    "ip route ",
    "ntp server ",
    "logging server ",
    "logging source-interface ",
    "ip name-server ",
    "ip domain-",
    "aaa ",
    "tacacs server ",
    "radius server ",
    "snmp-server ",
    "username ",
    "line vty",
    "access-class ",
    "ip access-list ",
)


def _semantic_line(line: str) -> str | None:
    stripped = line.strip()
    lowered = stripped.lower()
    if not stripped or stripped.startswith(("!", "#")):
        return None
    if "<masked" in lowered or "redacted secret" in lowered:
        return "<blocked-sensitive-placeholder>"
    if lowered.startswith("username "):
        tokens = stripped.split()
        role = tokens[tokens.index("role") + 1] if "role" in tokens else "<unspecified>"
        return f"username {tokens[1]} role {role}"
    if lowered.startswith("key "):
        return "key <credential-present>"
    if lowered.startswith("snmp-server community "):
        tokens = stripped.split()
        group = tokens[tokens.index("group") + 1] if "group" in tokens else "<unspecified>"
        return f"snmp-server community <credential-present> group {group}"
    if any(lowered.startswith(prefix) for prefix in _SEMANTIC_PREFIXES):
        return stripped
    return None


def sanitized_semantic_config(text: str) -> str:
    """Return only lab invariants, replacing credential values before persistence."""
    lines = [value for line in text.splitlines() if (value := _semantic_line(line))]
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def verify_nxos_lab_running_config(expected: str, current: str) -> dict[str, Any]:
    """Compare security and connectivity invariants without requiring byte equality."""
    expected_lines = sanitized_semantic_config(expected).splitlines()
    current_lines = sanitized_semantic_config(current).splitlines()
    blocked = "<blocked-sensitive-placeholder>" in current_lines
    current_counts: dict[str, int] = {}
    for line in current_lines:
        current_counts[line] = current_counts.get(line, 0) + 1
    missing: list[str] = []
    for line in expected_lines:
        if current_counts.get(line, 0) > 0:
            current_counts[line] -= 1
        else:
            missing.append(line)
    diff = list(difflib.unified_diff(
        expected_lines,
        current_lines,
        fromfile="expected-semantic-config",
        tofile="running-semantic-config",
        lineterm="",
    ))
    if blocked or missing:
        status = "FAILED"
    elif diff:
        status = "VERIFIED_WITH_DIFF"
    else:
        status = "VERIFIED"
    return {
        "status": status,
        "missing_invariants": missing,
        "blocked_sensitive_placeholder": blocked,
        "diff": diff,
        "expected_invariant_count": len(expected_lines),
        "current_invariant_count": len(current_lines),
    }


def load_clab_node_deadlines(
    topology_path: str | Path,
    *,
    started_at: float,
    health_timeout: float,
    honor_startup_delay: bool = True,
) -> tuple[str, dict[str, float]]:
    """Load cisco_n9kv node deadlines from topology startup-delay values."""
    document = yaml.safe_load(Path(topology_path).read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ClabReadinessError("Containerlab topology must be a YAML mapping")
    lab_name = str(document.get("name", "")).strip()
    if not lab_name:
        raise ClabReadinessError("Containerlab topology requires name")
    topology = document.get("topology", {})
    nodes = topology.get("nodes", {}) if isinstance(topology, Mapping) else {}
    if not isinstance(nodes, Mapping):
        raise ClabReadinessError("Containerlab topology.nodes must be a mapping")
    deadlines: dict[str, float] = {}
    for node, attributes in nodes.items():
        if not isinstance(attributes, Mapping):
            continue
        if str(attributes.get("kind", "")) != "cisco_n9kv":
            continue
        delay = float(attributes.get("startup-delay", 0)) if honor_startup_delay else 0
        if delay < 0:
            raise ClabReadinessError(f"negative startup-delay for node {node}")
        deadlines[str(node)] = started_at + delay + health_timeout
    if not deadlines:
        raise ClabReadinessError("topology contains no cisco_n9kv nodes")
    return lab_name, deadlines


def docker_node_state(
    lab_name: str,
    node: str,
    *,
    container_name: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read one container State object without shell interpolation."""
    container = container_name or f"clab-{lab_name}-{node}"
    completed = runner(
        ["docker", "inspect", "--format", "{{json .State}}", container],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "not-created",
            "source": "docker-inspect",
            "container": container,
            "detail": completed.stderr.strip(),
        }
    try:
        state = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ClabReadinessError(f"invalid docker inspect state for {node}") from exc
    runtime_status = str(state.get("Status", "unknown")).lower()
    health = state.get("Health")
    health_status = (
        str(health.get("Status", "unknown")).lower()
        if isinstance(health, Mapping)
        else None
    )
    if health_status == "healthy":
        return {
            "status": "ready",
            "source": "docker-inspect",
            "container": container,
            "runtime": runtime_status,
            "health": health_status,
        }
    if health_status in {"unhealthy"} or runtime_status in {"exited", "dead", "removing"}:
        return {
            "status": "failed",
            "source": "docker-inspect",
            "container": container,
            "runtime": runtime_status,
            "health": health_status,
        }
    if health_status is None and runtime_status == "running":
        return {
            "status": "ready",
            "source": "docker-inspect",
            "container": container,
            "runtime": runtime_status,
            "health": None,
        }
    return {
        "status": "waiting",
        "source": "docker-inspect",
        "container": container,
        "runtime": runtime_status,
        "health": health_status,
    }


def _inspect_node_name(lab_name: str, row: Mapping[str, Any]) -> str:
    """Resolve a node name from one containerlab inspect JSON row."""
    explicit = str(row.get("node_name", "") or row.get("node", "")).strip()
    if explicit:
        return explicit
    container_name = str(row.get("name", "")).strip()
    prefix = f"clab-{lab_name}-"
    if container_name.startswith(prefix):
        return container_name[len(prefix):]
    return ""


def containerlab_inspect_node_states(
    lab_name: str,
    nodes: Sequence[str],
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """Read target states from `containerlab inspect --all` without parsing a topology."""
    try:
        completed = runner(
            ["containerlab", "inspect", "--all", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return None, f"exit={completed.returncode}: {detail}"
    try:
        document = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(document, Mapping):
        return None, "JSON root is not an object"

    target_nodes = set(nodes)
    rows = document.get(lab_name)
    if rows is None:
        candidates: list[str] = []
        for candidate_lab, candidate_rows in document.items():
            if not isinstance(candidate_rows, Sequence) or isinstance(
                candidate_rows, (str, bytes)
            ):
                continue
            active_nodes: set[str] = set()
            topology_paths: set[str] = set()
            for item in candidate_rows:
                if not isinstance(item, Mapping):
                    continue
                state = str(item.get("state", "")).lower()
                status_text = str(item.get("status", "")).lower()
                if state != "running" or "unhealthy" in status_text:
                    continue
                node_name = _inspect_node_name(str(candidate_lab), item)
                if node_name:
                    active_nodes.add(node_name)
                topology_path = str(
                    item.get("absLabPath", "") or item.get("labPath", "")
                ).strip()
                if topology_path:
                    topology_paths.add(topology_path)
            if target_nodes and target_nodes.issubset(active_nodes):
                path_text = ",".join(sorted(topology_paths)) or "unknown-topology"
                candidates.append(f"{candidate_lab} ({path_text})")
        if candidates:
            raise ClabReadinessError(
                f"Topology lab name '{lab_name}' does not match active Containerlab "
                f"lab(s) with the same target nodes: {', '.join(sorted(candidates))}. "
                "Use the topology file that deployed the target lab."
            )
        return {
            node: {
                "status": "not-created",
                "source": "containerlab-inspect",
                "runtime": "not-found",
                "health": None,
                "detail": f"lab '{lab_name}' is not listed",
            }
            for node in sorted(target_nodes)
        }, None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return None, f"lab '{lab_name}' entry is not an array"

    by_node: dict[str, Mapping[str, Any]] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        node_name = _inspect_node_name(lab_name, item)
        if node_name:
            by_node[node_name] = item

    states: dict[str, dict[str, Any]] = {}
    for node in sorted(target_nodes):
        row = by_node.get(node)
        if row is None:
            states[node] = {
                "status": "not-created",
                "source": "containerlab-inspect",
                "runtime": "not-found",
                "health": None,
                "detail": f"node '{node}' is not listed in lab '{lab_name}'",
            }
            continue
        runtime_status = str(row.get("state", "unknown")).lower()
        status_text = str(row.get("status", "unknown")).strip()
        status_lower = status_text.lower()
        health_status = (
            "unhealthy" if "unhealthy" in status_lower
            else "healthy" if "healthy" in status_lower
            else None
        )
        if health_status == "healthy":
            status = "ready"
        elif health_status == "unhealthy" or runtime_status in {
            "exited", "dead", "removing"
        }:
            status = "failed"
        else:
            status = "waiting"
        states[node] = {
            "status": status,
            "source": "containerlab-inspect",
            "container": str(row.get("name", "")),
            "runtime": runtime_status,
            "health": health_status,
            "detail": status_text,
        }
    return states, None


def _readiness_message(node: str, state: Mapping[str, Any]) -> str:
    """Render a secret-free readiness status line for console and file logs."""
    values = [
        f"node={node}",
        f"status={state.get('status', 'unknown')}",
        f"source={state.get('source', 'unknown')}",
        f"runtime={state.get('runtime', 'unknown')}",
        f"health={state.get('health') or 'none'}",
    ]
    detail = " ".join(str(state.get("detail", "")).split())
    if detail:
        values.append(f"detail={detail[:300]}")
    return " ".join(values)


def wait_for_clab_nodes(
    topology_path: str | Path,
    *,
    health_timeout: float = 1200,
    poll_interval: float = 10,
    honor_startup_delay: bool = True,
    runner: Callable[..., Any] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Wait until all cisco_n9kv nodes are healthy or their deadlines fail."""
    if health_timeout <= 0 or poll_interval <= 0:
        raise ClabReadinessError("health timeout and poll interval must be positive")
    started_at = monotonic()
    lab_name, deadlines = load_clab_node_deadlines(
        topology_path,
        started_at=started_at,
        health_timeout=health_timeout,
        honor_startup_delay=honor_startup_delay,
    )
    pending = set(deadlines)
    results: dict[str, dict[str, Any]] = {}
    last_states: dict[str, dict[str, Any]] = {}
    last_inspect_error: str | None = None
    if status_callback is not None:
        status_callback(
            f"start lab={lab_name} nodes={len(pending)} "
            f"health_timeout={health_timeout:g} poll_interval={poll_interval:g}"
        )
    while pending:
        current = monotonic()
        inspect_states, inspect_error = containerlab_inspect_node_states(
            lab_name,
            sorted(pending),
            runner=runner,
        )
        if (
            inspect_error
            and inspect_error != last_inspect_error
            and status_callback is not None
        ):
            status_callback(
                "containerlab inspect unavailable; falling back to Docker inspect: "
                + inspect_error[:300]
            )
        last_inspect_error = inspect_error
        for node in sorted(tuple(pending)):
            state = (
                dict(inspect_states[node])
                if inspect_states is not None and node in inspect_states
                else docker_node_state(lab_name, node, runner=runner)
            )
            if state["status"] not in {"ready", "failed"}:
                docker_state = docker_node_state(
                    lab_name,
                    node,
                    container_name=str(state.get("container", "")) or None,
                    runner=runner,
                )
                if (
                    docker_state["status"] in {"ready", "failed"}
                    or inspect_states is None
                ):
                    state = docker_state
            if state != last_states.get(node) and status_callback is not None:
                status_callback(_readiness_message(node, state))
            last_states[node] = state
            if state["status"] == "ready":
                results[node] = state
                pending.remove(node)
                continue
            if state["status"] == "failed":
                raise ClabReadinessError(f"Containerlab node failed before config push: {node}: {state}")
            if current >= deadlines[node]:
                raise ClabReadinessError(f"Containerlab node readiness timeout: {node}: {state}")
        if pending:
            if status_callback is not None:
                status_callback(
                    f"waiting lab={lab_name} pending={','.join(sorted(pending))} "
                    f"next_poll_seconds={poll_interval:g}"
                )
            sleeper(poll_interval)
    return results
