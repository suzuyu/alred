"""Health orchestration adapter for the shared, offline Route Diff core."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from ..schema import canonical_json_bytes, canonical_sha256, validate_document
from ..route_diff.commands import resolve_route_command
from ..route_diff.comparator import compare_snapshots
from ..route_diff.control import ProcessingControl
from ..route_diff.domain import RouteInputError, validate_policy
from ..route_diff.evaluator import representative
from ..route_diff.parser import PROMPT, ParsedRouteSource, parse_route_source
from ..route_diff.snapshot import build_snapshot, snapshot_hash, validate_snapshot
from ..route_diff.terminal import normalize_terminal, sha256
from ..route_diff.sections import prepare_sections

ADAPTER_VERSION = "1.1"


class HealthRouteReportError(ValueError):
    """A known report failure handled by the existing Health CLI error boundary."""

    code = "ROUTE_REPORT_FAILED"


def route_config(value):
    config = deepcopy(value)
    config.setdefault("families", ["ipv4", "ipv6"])
    config.setdefault("vrfs", [])
    config.setdefault("policy", dict(api_version="alred/v1", kind="RouteDiffPolicy",
        metadata=dict(name="health-route-diff"), spec={}))
    config["policy"] = validate_policy(config["policy"])
    for rules in config["policy"]["spec"].values():
        for rule in rules:
            if rule["family"] not in config["families"] or config["vrfs"] and rule["vrf"] not in config["vrfs"]:
                raise RouteInputError("/route_diff/policy", "policy resource is outside selected AF/VRF")
    return config


def enabled(effective):
    return any(c["evaluator"] == "route_diff" for c in effective["spec"]["checks"])


def _unknown(parsed, reason):
    parsed.document["diagnostics"].append(dict(code="HEALTH_ACQUISITION_UNVERIFIED", message=reason))
    for scope in parsed.document["scopes"]:
        scope.update(verification="unknown", verification_reason=reason,
                     parse_status="UNKNOWN", coverage="UNKNOWN", health_eligible=False)
    return parsed


def _parse_record(raw, record, *, source_id, device, command, prepared=None):
    """Keep original bytes; independently verify the adopted manifest interval."""
    terminal = prepared.terminal if prepared else normalize_terminal(raw)
    start, end = record.get("start_line"), record.get("end_line")
    kwargs = dict(source_id=source_id, device=device, command_id=command["command_id"],
                  vrf=command["vrf"] if command["command_id"] in ("route_ipv4_vrf", "route_ipv6_vrf") else None)
    valid_range = (type(start) is int and type(end) is int and 1 <= start <= end <= len(terminal.lines))
    if record.get("status") != "success" or record.get("confidence") != "high" or not valid_range:
        value = parse_route_source(b"", input_format="nxos-route-text", **kwargs)
        value.document.update(terminal=terminal.manifest(), selected_range=(
            dict(start_line=start, end_line=end) if valid_range else
            dict(start_line=1, end_line=len(terminal.lines)) if terminal.lines else None))
        return _unknown(ParsedRouteSource(terminal, value.document),
                        record.get("error") or "missing successful, unambiguous acquisition interval")
    if record.get("source") == "external_transcript":
        # The importer does not include the next command prompt in its interval.
        # An idle prompt is already included; a next command closes the adopted command.
        if end < len(terminal.lines) and PROMPT.fullmatch(terminal.lines[end].text.strip()):
            end += 1
        prompt = PROMPT.fullmatch(terminal.lines[start - 1].text.strip())
        if prompt is None or prompt["host"] != device or resolve_route_command(prompt["command"]) != command:
            return _unknown(parse_route_source(raw, input_format="nxos-route-text", start_line=start, end_line=end, **kwargs),
                            "manifest and raw command prompt disagree")
        return parse_route_source(raw, start_line=start, end_line=end, **kwargs)
    if record.get("source") != "alred_collect":
        return _unknown(parse_route_source(raw, input_format="nxos-route-text", **kwargs), "unsupported acquisition source")
    body_start = record.get("output_start_line")
    body_end = record.get("output_end_line")
    if not (type(body_start) is int and type(body_end) is int and start < body_start <= body_end <= end):
        return _unknown(parse_route_source(raw, input_format="nxos-route-text", **kwargs), "invalid collect body interval")
    try:
        prepared = prepared or prepare_sections(raw, terminal=terminal)
    except RouteInputError as error:
        return _unknown(parse_route_source(raw, input_format='nxos-route-text', start_line=body_start, end_line=body_end, **kwargs),
                        str(error))
    section = next((s for s in prepared.sections if s.start == start), None)
    if (prepared.container_format != 'alred-collect' or section is None or section.end != end
            or section.prompt + 1 != body_start or section.metadata.get('COLLECTED_AT') != record.get('collected_at')
            or resolve_route_command(section.command) != command or section.host != device):
        return _unknown(parse_route_source(raw, input_format='nxos-route-text', start_line=body_start, end_line=body_end, **kwargs),
                        'collector interval or command boundary disagrees with manifest')
    parsed = parse_route_source(raw, start_line=start, end_line=end, prepared=prepared, **kwargs)
    if len(parsed.document['commands']) != 1:
        return _unknown(parsed, 'collector must resolve exactly one route command')
    acquisition = parsed.document['commands'][0]
    parsed.document.update(input_format='alred-collect',
        collection_provenance=dict(adapter_version=ADAPTER_VERSION, status='success',
            collected_at=record['collected_at'], manifest_record_sha256=canonical_sha256(record),
            command=record['command'], start_line=start, end_line=end))
    proof = acquisition['acquisition_evidence']
    if proof['completion_kind'] == 'eof_unverified' and section.metadata.get('STATUS') == 'OK' and not section.metadata.get('ERROR'):
        proof.update(completion_kind='manifest_record', manifest_record_sha256=canonical_sha256(record))
        for scope in parsed.document['scopes']:
            # Existing explicit-empty and nonempty Health evidence can use a verified manifest.
            # Markerless empty tables still require a real next block/prompt.
            if scope['parse_status'] == 'COMPLETE' and (scope['routes'] or scope['explicit_empty']):
                scope.update(verification='verified', verification_reason=None, coverage='COMPLETE', health_eligible=True)
    return parsed


def build_health_routes(manifest, config, *, phase):
    """Return canonical routes and original sources; leave persistence to the caller."""
    parsed, raw_sources, paths, captured, prepared_cache = [], {}, {}, {}, {}
    for host, data in sorted(manifest["spec"]["hosts"].items()):
        if data.get("platform", "nxos") != "nxos":
            continue
        found = set()
        for identifier, record in sorted(data["commands"].items()):
            command = resolve_route_command(record.get("command", ""))
            if command is None or command["family"] not in config["families"]:
                continue
            if config["vrfs"] and command["vrf"] is not None and command["vrf"] not in config["vrfs"]:
                continue
            source_id = canonical_sha256(dict(host=host, identifier=identifier))[7:]
            path = Path(record["file"]) if record.get("file") else None
            raw = b""
            if path is not None and path.is_file() and not path.is_symlink():
                if path not in captured:
                    captured[path] = path.read_bytes()
                raw = captured[path]
                if sha256(raw).removeprefix("sha256:") != record.get("sha256", "").removeprefix("sha256:"):
                    raise RouteInputError("/route_sources", "collection source hash mismatch")
            key = id(raw)
            if key not in prepared_cache:
                try:
                    prepared_cache[key] = prepare_sections(raw)
                except RouteInputError:
                    prepared_cache[key] = None
            value = _parse_record(raw, record, source_id=source_id, device=host, command=command, prepared=prepared_cache[key])
            value.document["display_name"] = path.name if path is not None else identifier
            parsed.append(value)
            raw_sources[source_id] = raw
            paths[source_id] = f"route-sources/{source_id}.log"
            found.add(command["family"])
        for family in sorted(set(config["families"]) - found):
            source_id = canonical_sha256(dict(host=host, missing=family))[7:]
            parsed.append(_unknown(parse_route_source(b"", source_id=source_id, device=host,
                input_format="nxos-route-text", command_id=f"route_{family}_all_vrfs"), "route command was not collected"))
            raw_sources[source_id] = b""
            paths[source_id] = f"route-sources/{source_id}.log"
    if not parsed:
        return None
    return dict(snapshot=build_snapshot(parsed, side="before" if phase == "before" else "after", source_paths=paths), raw=raw_sources)


def store_health_routes(bundle, config, *, operation_root, directory):
    from ..operation import atomic_write_bytes

    if bundle is None:
        return None
    directory = Path(directory)
    for source in bundle["snapshot"]["sources"]:
        atomic_write_bytes(operation_root, directory / source["path"], bundle["raw"][source["id"]])
    raw = canonical_json_bytes(bundle["snapshot"])
    atomic_write_bytes(operation_root, directory / "route-snapshot.json", raw)
    return dict(path="route-snapshot.json", sha256=sha256(raw), snapshot_id=bundle["snapshot"]["snapshot_id"],
                versions=bundle["snapshot"]["versions"], adapter_version=ADAPTER_VERSION, config_sha256=canonical_sha256(config))


def _read_relative(directory, path):
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts):
        raise RouteInputError("/route_diff/path", "artifact path must be a contained relative path")
    candidate = Path(directory)
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RouteInputError("/route_diff/path", "artifact symlinks are not allowed")
    if not candidate.is_file():
        raise RouteInputError("/route_diff/path", f"required artifact is missing: {relative}")
    return candidate.read_bytes()


def load_health_routes(health, health_path):
    reference = health.get("route_diff")
    if reference is None:
        return None
    validate_document(health, kind="HealthSnapshot")
    directory = Path(health_path).parent
    raw = _read_relative(directory, reference["path"])
    if sha256(raw) != reference["sha256"]:
        raise RouteInputError("/route_diff", "RouteSnapshot file hash mismatch")
    snapshot = json.loads(raw)
    validate_snapshot(snapshot)
    if (snapshot["snapshot_id"] != reference["snapshot_id"] or snapshot["versions"] != reference["versions"]
            or reference["adapter_version"] != ADAPTER_VERSION):
        raise RouteInputError("/route_diff", "RouteSnapshot reference or adapter version mismatch")
    sources = {}
    for source in snapshot["sources"]:
        content = _read_relative(directory, source["path"])
        if sha256(content) != source["sha256"]:
            raise RouteInputError("/route_diff", "retained route source hash mismatch")
        sources[source["id"]] = content
    return dict(snapshot=snapshot, raw=sources)


def _side(snapshot, side):
    value = deepcopy(snapshot)
    value["side"] = side
    for source in value["sources"]:
        source["side"] = side
    value["snapshot_id"] = snapshot_hash(value)
    return value


def assess_routes(before, after, effective, bundles, *, single=False):
    """Pure canonical comparison. Missing legacy evidence remains UNKNOWN."""
    if not enabled(effective) or bundles is None or any(b is None for b in bundles):
        return None
    config = route_config(effective["spec"].get("route_diff", {}))
    for health, bundle in zip((before, after), bundles):
        reference = health.get("route_diff")
        if reference is None:
            return None
        route = bundle["snapshot"]
        validate_snapshot(route)
        if (reference["config_sha256"] != canonical_sha256(config) or reference["snapshot_id"] != route["snapshot_id"]
                or reference["versions"] != route["versions"] or reference["adapter_version"] != ADAPTER_VERSION
                or route["side"] != ("before" if health["phase"] == "before" else "after")):
            raise RouteInputError("/route_diff", "detailed snapshot does not match frozen Health context")
    left, right = (_side(b["snapshot"], side) for b, side in zip(bundles, ("before", "after")))
    hosts = {h for h, d in after["hosts"].items() if d.get("platform", "unknown").lower().startswith("nxos")}
    selected = set()
    for host in hosts:
        for family in config["families"]:
            vrfs = config["vrfs"] or sorted({s["vrf"] for snap in (left, right) for s in snap["scopes"]
                if s["device"] == host and s["family"] == family}) or ["default"]
            selected.update((host, vrf, family) for vrf in vrfs)
    policy = deepcopy(config["policy"])
    for rules in policy["spec"].values():
        for rule in rules:
            if rule["device"] not in hosts:
                raise RouteInputError("/route_diff/policy", "policy host is outside eligible inventory")
            selected.add((rule["device"], rule["vrf"], rule["family"]))
    if not selected:
        return None
    if single or after["phase"] == "rollback":
        policy["spec"]["expected_changes"] = []
    diff = compare_snapshots(left, right, selected_scopes=selected, policy=policy)
    return dict(before=left, after=right, diff=diff, rollback=after["phase"] == "rollback" and not single)


def route_check(assessment, host, definition):
    """Build one Health check per host, retaining all underlying rule results."""
    base = dict(check_id=definition["id"], profile=definition["profile"], host=host, resource=None)
    if assessment is None:
        return dict(base, result="UNKNOWN", classification="collection_error", message="Detailed RouteSnapshot is unavailable", evidence=[])
    diff = assessment["diff"]
    scopes = [s for s in diff["scopes"] if s["device"] == host and s["coverage"] != "NOT_SELECTED"]
    rules = {g: [r for r in values if r["device"] == host] for g, values in diff["policy_results"].items()}
    states = [r["result"] for values in rules.values() for r in values if r["result"] in ("PASS", "WARN", "FAIL", "UNKNOWN")]
    if not scopes or any(s["coverage"] != "COMPLETE" or not all(s[side] and s[side]["health_eligible"] for side in ("before", "after")) for s in scopes):
        states.append("UNKNOWN")
    if any(d.get("device") == host and d["code"] == "UNSCOPED_SOURCE" for d in diff["diagnostics"]):
        states.append("UNKNOWN")
    residual = [e["entry_key"] for e in diff["entries"] if e["device"] == host and e["classification"] != "excluded"] if assessment["rollback"] else []
    if residual:
        states.append("FAIL")
    status = representative(states)
    sources = {(s["side"], s["id"]): s for s in diff["sources"]}
    evidence = []
    for scope in scopes:
        for side in ("before", "after"):
            if scope[side] is not None:
                value = scope[side]["evidence"]
                source = sources[side, value["source_id"]]
                evidence.append(dict(value, side=side, file=source["path"], sha256=source["sha256"],
                    parser_version=source["versions"]["parser"], command=scope[side]["command_scope"]["command"]))
    classifications = {r.get("classification") for values in rules.values() for r in values}
    classification = ("collection_error" if status == "UNKNOWN" else
        "regression" if residual or status == "FAIL" and "regression" in classifications else
        "pre_existing" if status == "FAIL" else "unexpected_change" if status == "WARN" else
        "expected_change" if "expected_change" in classifications else "normal")
    return dict(base, result=status, classification=classification,
        message=f"Route Diff: {status}; {len(scopes)} scopes; rollback residuals={len(residual)}", evidence=evidence,
        after=dict(scopes=scopes, policy_results=rules, rollback_residual_entries=residual))


def publish_route_report(assessment, bundles, *, operation_root, report_dir):
    from ..operation import atomic_update_relative_directory_symlink
    from ..route_diff.cli import RouteCLIError, verify_report
    from ..route_diff.report import write_route_report

    if assessment is None:
        return {}
    report_dir = Path(report_dir)
    attempt = report_dir / "route-diff-attempts" / uuid.uuid4().hex
    raw = {(side, key): content for side, bundle in zip(("before", "after"), bundles) for key, content in bundle["raw"].items()}
    checks = [route_check(assessment, host, dict(id="route_diff", profile="route-diff-nxos"))
              for host in sorted({s["device"] for s in assessment["diff"]["comparison"]["selected_scopes"]})]
    context = dict(phase="rollback" if assessment["rollback"] else "after",
                   result=representative([c["result"] for c in checks]), checks=checks)
    try:
        write_route_report(assessment["before"], assessment["after"], assessment["diff"], raw, attempt,
                           labels=dict(before="before", after=context["phase"]), health_context=context)
        verify_report(attempt, ProcessingControl())
    except (RouteCLIError, OSError) as exc:
        raise HealthRouteReportError(str(exc)) from exc
    atomic_update_relative_directory_symlink(operation_root, report_dir / "route_diff", attempt)
    return dict(route_diff_index=str(report_dir / "route_diff/index.html"),
                route_diff_manifest=str(attempt / "report-manifest.json"))
