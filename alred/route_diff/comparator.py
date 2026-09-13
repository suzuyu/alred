"""Five route comparisons and optional policy evaluation over full snapshots."""
from __future__ import annotations

from copy import deepcopy

from ..schema import canonical_sha256, validate_document
from .control import ProcessingControl
from .domain import RouteInputError
from .evaluator import EVALUATOR_VERSION, evaluate_policy, representative, resolve_policy
from .semantics import MODES, PRIMARY_MODE, describe, project
from .snapshot import IDENTITY, identity, stable, validate_snapshot

COMPARATOR_VERSION = "1.1"
COUNT_FIELDS = ("before_count", "after_count", "ADDED", "REMOVED", "MODIFIED", "UNCHANGED", "changed_count")


def counts(known=True):
    return dict({k: 0 if known else None for k in COUNT_FIELDS}, has_diff=False if known else None)


def _finish_counts(value):
    value["changed_count"] = sum(value[k] for k in ("ADDED", "REMOVED", "MODIFIED"))
    value["has_diff"] = bool(value["changed_count"])


def fingerprint(document):
    return canonical_sha256(dict(snapshot_ids=document["snapshot_ids"], comparison=document["comparison"],
        policy_sha256=document["policy_sha256"], versions={k: v for k, v in document["versions"].items() if k != "renderer"}))


def _scope_record(key):
    return dict(zip(IDENTITY[:3], key))


def _validate_count(value, complete):
    if not complete:
        if any(value[k] is not None for k in (*COUNT_FIELDS, "has_diff")):
            raise RouteInputError("/counts", "unknown or unselected counts must all be null")
        return
    if any(value[k] is None for k in COUNT_FIELDS):
        raise RouteInputError("/counts", "complete counts must be integers")
    if (value["before_count"] != value["REMOVED"] + value["MODIFIED"] + value["UNCHANGED"]
            or value["after_count"] != value["ADDED"] + value["MODIFIED"] + value["UNCHANGED"]
            or value["changed_count"] != value["ADDED"] + value["REMOVED"] + value["MODIFIED"]
            or value["has_diff"] != bool(value["changed_count"])):
        raise RouteInputError("/counts", "route count identities do not hold")


def validate_diff(document, *, control=None):
    """Check the result schema, fingerprint, policy hash and count projections."""
    control = control or ProcessingControl()
    control.checkpoint("validate_diff", 0, len(document.get("entries", [])), unit="routes")
    content_digest = control.validation_digest(document)
    if control.was_validated("RouteDiff", content_digest):
        control.checkpoint("validate_diff", len(document["entries"]), len(document["entries"]), unit="routes")
        return
    validate_document(document, kind="RouteDiff")
    if document["comparison_fingerprint"] != fingerprint(document):
        raise RouteInputError("/comparison_fingerprint", "comparison fingerprint mismatch")
    if document["comparison"]["modes"] != list(MODES) or document["comparison"]["primary_mode"] != PRIMARY_MODE:
        raise RouteInputError("/comparison", "unsupported mode contract")
    selected = {identity(s, scope=True) for s in document["comparison"]["selected_scopes"]}
    if len(selected) != len(document["comparison"]["selected_scopes"]):
        raise RouteInputError("/comparison", "duplicate selected scope")
    if document["policy"] is not None:
        policy, policy_hash = resolve_policy(document["policy"], selected)
        if policy != document["policy"] or policy_hash != document["policy_sha256"]:
            raise RouteInputError("/policy", "resolved policy hash mismatch")
    elif document["policy_sha256"] is not None:
        raise RouteInputError("/policy", "policy hash without a policy")
    scopes, observed = {}, {}
    for scope in document["scopes"]:
        key = identity(scope, scope=True)
        if key in scopes:
            raise RouteInputError("/scopes", "duplicate comparison scope")
        scopes[key] = scope
        if (scope["coverage"] != "NOT_SELECTED") != (key in selected):
            raise RouteInputError("/scopes", "scope selection disagrees with comparison")
        observed[key] = {mode: {c: 0 for c in ("ADDED", "REMOVED", "MODIFIED")} for mode in MODES}
        if scope["coverage"] == "COMPLETE" and not all(scope[side] is not None and scope[side]["coverage"] == "COMPLETE" for side in ("before", "after")):
            raise RouteInputError("/scopes", "complete comparison lacks a complete input scope")
        for value in scope["modes"].values():
            _validate_count(value, scope["coverage"] == "COMPLETE")
            if scope["coverage"] == "COMPLETE" and any(value[side + "_count"] != scope[side]["parsed_prefix_count"] for side in ("before", "after")):
                raise RouteInputError("/counts", "comparison counts disagree with complete input scope")
    if not selected <= set(scopes):
        raise RouteInputError("/scopes", "selected scope is missing")
    seen = set()
    for index, entry in enumerate(document["entries"]):
        if index % 256 == 0:
            control.checkpoint("validate_diff", index, len(document["entries"]), unit="routes")
        key = identity(entry)
        if key in seen or key[:3] not in scopes or scopes[key[:3]]["coverage"] != "COMPLETE":
            raise RouteInputError("/entries", "duplicate entry or entry in an incomplete scope")
        seen.add(key)
        if entry["before"] is None and entry["after"] is None:
            raise RouteInputError("/entries", "changed entry cannot be absent on both sides")
        for side in ("before", "after"):
            if entry[side] is not None and identity(entry[side]) != key:
                raise RouteInputError("/entries", "entry resource disagrees with observed route")
        expected_key = canonical_sha256(dict(resource={k: entry[k] for k in IDENTITY}, mode=PRIMARY_MODE,
            before=stable(project(entry["before"])) if entry["before"] else None,
            after=stable(project(entry["after"])) if entry["after"] else None))
        if entry["mode"] != PRIMARY_MODE or entry["entry_key"] != expected_key:
            raise RouteInputError("/entries", "entry mode or key disagrees with its primary projection")
        for mode in MODES:
            expected = describe(entry["before"], entry["after"], mode)
            if any(entry["modes"][mode][k] != v for k, v in expected.items()):
                raise RouteInputError("/entries", "mode projection disagrees with entry routes")
            if expected["change_type"] != "UNCHANGED":
                observed[key[:3]][mode][expected["change_type"]] += 1
        if any(entry[k] != entry["modes"][PRIMARY_MODE][k] for k in ("change_type", "reason_codes", "field_summary")):
            raise RouteInputError("/entries", "primary projection disagrees with entry")
    complete = [s for s in scopes.values() if s["coverage"] == "COMPLETE"]
    unknown_count = sum(s["coverage"] == "UNKNOWN" for s in scopes.values())
    unknown_sources = sum(d.get("code") == "UNSCOPED_SOURCE" for d in document["diagnostics"])
    coverage = "UNKNOWN" if not complete else "PARTIAL" if unknown_count or unknown_sources else "COMPLETE"
    expected_summary = dict(coverage=coverage, complete_scope_count=len(complete), unknown_scope_count=unknown_count, unknown_source_count=unknown_sources)
    if any(document["summary"][k] != v for k, v in expected_summary.items()):
        raise RouteInputError("/summary", "summary coverage disagrees with scope diagnostics")
    for scope in complete:
        for mode in MODES:
            if any(scope["modes"][mode][k] != n for k, n in observed[identity(scope, scope=True)][mode].items()):
                raise RouteInputError("/counts", "changed route counts disagree with entries")
    for mode, value in document["summary"]["modes"].items():
        _validate_count(value, bool(complete))
        if complete and any(value[k] != sum(s["modes"][mode][k] for s in complete) for k in COUNT_FIELDS):
            raise RouteInputError("/summary", "aggregate counts disagree with complete scopes")
    results = document["policy_results"]
    if document["policy"] is None:
        evaluation = "NOT_EVALUATED"
        if any(results.values()) or any(e["evaluation"] != "NOT_EVALUATED" or e["expectation_status"] != "NOT_CONFIGURED" for e in document["entries"]):
            raise RouteInputError("/policy_results", "policy results without a policy")
    else:
        for group in ("required_routes", "expected_changes", "exclusions"):
            expected_resources = {identity(rule) for rule in document["policy"]["spec"][group]}
            actual_resources = {identity(rule) for rule in results[group]}
            if actual_resources != expected_resources or len(actual_resources) != len(results[group]):
                raise RouteInputError("/policy_results", "policy rule results are missing or duplicated")
        general = {identity(r): r for r in results["general_changes"]}
        if set(general) != seen or len(general) != len(results["general_changes"]):
            raise RouteInputError("/policy_results", "general results disagree with changed entries")
        for entry in document["entries"]:
            rule = general[identity(entry)]
            if entry["evaluation"] != rule["result"] or entry["classification"] != rule["classification"]:
                raise RouteInputError("/entries", "entry evaluation disagrees with policy result")
        states = [r["result"] for group in results.values() for r in group]
        if coverage != "COMPLETE" or any(not all(s[side] is not None and s[side]["health_eligible"] for side in ("before", "after")) for s in scopes.values() if s["coverage"] != "NOT_SELECTED"):
            states.append("UNKNOWN")
        evaluation = representative(states)
    exit_code = 3 if coverage != "COMPLETE" or evaluation == "UNKNOWN" else 4 if evaluation == "FAIL" else 1 if evaluation == "WARN" else 0
    if document["evaluation"] != evaluation or document["exit_code"] != exit_code:
        raise RouteInputError("/evaluation", "representative evaluation or exit code is inconsistent")
    control.checkpoint("validate_diff", len(document["entries"]), len(document["entries"]), unit="routes")
    control.remember_validated("RouteDiff", content_digest)


def compare_snapshots(before, after, *, selected_scopes=None, policy=None, expected_policy_sha256=None, control=None):
    """Compare selected scope unions without inferring absence from missing logs."""
    control = control or ProcessingControl()
    for snapshot, side in ((before, "before"), (after, "after")):
        validate_snapshot(snapshot, control=control)
        if snapshot["side"] != side:
            raise RouteInputError("/side", "before/after snapshot labels do not match the comparison direction")
    if any(before["versions"][k] != after["versions"][k] for k in ("parser", "normalizer", "terminal_adapter")):
        raise RouteInputError("/versions", "snapshot parser versions disagree")
    lookup = {side: {identity(s, scope=True): s for s in snapshot["scopes"]} for side, snapshot in (("before", before), ("after", after))}
    route_lookup = {"before": {}, "after": {}}
    for side, snapshot in (("before", before), ("after", after)):
        for route in snapshot["routes"]:
            route_lookup[side].setdefault(identity(route, scope=True), {})[route["prefix"]] = route
    discovered = set(lookup["before"]) | set(lookup["after"])
    for snapshot in (before, after):
        for source in snapshot["sources"]:
            for command in source["commands"]:
                if command["vrf"] is not None:
                    discovered.add((source["device"], command["vrf"], command["family"]))
    if selected_scopes is None:
        selected = discovered
    else:
        selected = set()
        for key in selected_scopes:
            if not isinstance(key, tuple) or len(key) != 3 or not all(isinstance(v, str) and v for v in key) or key[2] not in ("ipv4", "ipv6"):
                raise RouteInputError("/selected_scopes", "expected (device, vrf, family) tuples")
            selected.add(key)
        if not selected:
            raise RouteInputError("/selected_scopes", "an explicit empty scope selection is not a comparison")
    resolved_policy, policy_hash = resolve_policy(policy, selected) if policy is not None else (None, None)
    if expected_policy_sha256 is not None and expected_policy_sha256 != policy_hash:
        raise RouteInputError("/policy", "policy differs from the frozen policy hash")
    result = dict(schema_version=1, kind="RouteDiff", snapshot_ids=dict(before=before["snapshot_id"], after=after["snapshot_id"]),
        versions=dict(before["versions"], comparator=COMPARATOR_VERSION, evaluator=EVALUATOR_VERSION, renderer=None),
        comparison=dict(primary_mode=PRIMARY_MODE, modes=list(MODES), selected_scopes=[_scope_record(k) for k in stable(selected)]),
        policy=resolved_policy, policy_sha256=policy_hash, sources=deepcopy(before["sources"] + after["sources"]), scopes=[], entries=[], diagnostics=[])
    contexts, complete_count, unknown_count = {}, 0, 0
    union = stable(discovered | selected)
    for scope_index, key in enumerate(union):
        control.checkpoint("compare", scope_index, len(union), unit="scopes")
        a, b = lookup["before"].get(key), lookup["after"].get(key)
        known = all(s is not None and s["coverage"] == "COMPLETE" for s in (a, b))
        coverage = "NOT_SELECTED" if key not in selected else "COMPLETE" if known else "UNKNOWN"
        record = dict(_scope_record(key), coverage=coverage, before=deepcopy(a), after=deepcopy(b),
                      modes={mode: counts(coverage == "COMPLETE") for mode in MODES}, diagnostics=[])
        result["scopes"].append(record)
        if coverage == "NOT_SELECTED":
            continue
        contexts[key] = dict(before=a, after=b, before_routes=route_lookup["before"].get(key, {}), after_routes=route_lookup["after"].get(key, {}))
        if not known:
            unknown_count += 1
            for side, scope in (("before", a), ("after", b)):
                if scope is None or scope["coverage"] != "COMPLETE":
                    issue = dict(_scope_record(key), side=side, code="SCOPE_MISSING" if scope is None else "SCOPE_INCOMPLETE",
                                 evidence=scope["evidence"] if scope else None)
                    record["diagnostics"].append(issue)
                    result["diagnostics"].append(issue)
            continue
        complete_count += 1
        left, right = contexts[key]["before_routes"], contexts[key]["after_routes"]
        prefixes = sorted(set(left) | set(right))
        for mode in MODES:
            record["modes"][mode].update(before_count=len(left), after_count=len(right))
        for index, prefix in enumerate(prefixes):
            if index % 256 == 0:
                control.checkpoint("compare", index, len(prefixes), unit="routes", **_scope_record(key))
            old, new = left.get(prefix), right.get(prefix)
            projections = {mode: describe(old, new, mode) for mode in MODES}
            for mode, projection in projections.items():
                record["modes"][mode][projection["change_type"]] += 1
            primary = projections[PRIMARY_MODE]
            if primary["change_type"] == "UNCHANGED":
                continue
            resource = dict(_scope_record(key), prefix=prefix)
            entry_key = canonical_sha256(dict(resource=resource, mode=PRIMARY_MODE,
                before=stable(project(old)) if old else None, after=stable(project(new)) if new else None))
            result["entries"].append(dict(resource, entry_key=entry_key, mode=PRIMARY_MODE, before=deepcopy(old), after=deepcopy(new),
                evidence_before=deepcopy(old["evidence"] if old else a["evidence"]), evidence_after=deepcopy(new["evidence"] if new else b["evidence"]),
                **primary, modes=projections, evaluation="NOT_EVALUATED", classification="observed",
                expectation_status="NOT_CONFIGURED", expectation_rule_id=None))
        for value in record["modes"].values():
            _finish_counts(value)
        control.checkpoint("compare", len(prefixes), len(prefixes), unit="routes", **_scope_record(key))
    control.checkpoint("compare", len(union), len(union), unit="scopes")

    # An unassignable source remains visible even if another source parsed successfully.
    unknown_sources = []
    for side, snapshot in (("before", before), ("after", after)):
        scoped_sources = {s["evidence"]["source_id"] for s in snapshot["scopes"]}
        for source in snapshot["sources"]:
            relevant = selected_scopes is None or any(k[0] == source["device"] and (not source["commands"] or any(
                c["family"] == k[2] and c["vrf"] in (None, k[1]) for c in source["commands"])) for k in selected)
            nonroute_only = not source['commands'] and source['notices'] and all(d['code'] == 'ROUTE_COMMAND_MISSING' for d in source['diagnostics'])
            other_routes = any(s['device'] == source['device'] for s in snapshot['scopes'])
            missing_commands = [d for d in source['diagnostics'] if 'command_id' in d and (selected_scopes is None or any(
                k[0] == source['device'] and k[2] == d.get('family') and d.get('vrf') in (None, k[1]) for k in selected))]
            if (relevant and source["id"] not in scoped_sources and not (nonroute_only and other_routes)) or missing_commands:
                issue = dict(code="UNSCOPED_SOURCE", side=side, source_id=source["id"], device=source["device"], diagnostics=source["diagnostics"])
                unknown_sources.append(issue)
    result["diagnostics"].extend(unknown_sources)
    complete = [s for s in result["scopes"] if s["coverage"] == "COMPLETE"]
    totals = {mode: counts(bool(complete)) for mode in MODES}
    for mode in MODES:
        if complete:
            for field in COUNT_FIELDS:
                totals[mode][field] = sum(s["modes"][mode][field] for s in complete)
            _finish_counts(totals[mode])
    coverage = "UNKNOWN" if not complete else "PARTIAL" if unknown_count or unknown_sources else "COMPLETE"
    result["summary"] = dict(coverage=coverage, complete_scope_count=complete_count, unknown_scope_count=unknown_count,
                             unknown_source_count=len(unknown_sources), modes=totals)
    result["policy_results"] = evaluate_policy(resolved_policy, contexts, result["entries"], control=control)
    if resolved_policy is None:
        evaluation = "NOT_EVALUATED"
    else:
        states = [r["result"] for group in result["policy_results"].values() for r in group]
        if coverage != "COMPLETE" or any(not all(c[side] is not None and c[side]["health_eligible"] for side in ("before", "after")) for c in contexts.values()):
            states.append("UNKNOWN")
        evaluation = representative(states)
    result["evaluation"] = evaluation
    result["exit_code"] = 3 if coverage != "COMPLETE" or evaluation == "UNKNOWN" else 4 if evaluation == "FAIL" else 1 if evaluation == "WARN" else 0
    result["comparison_fingerprint"] = fingerprint(result)
    validate_diff(result, control=control)
    return result
