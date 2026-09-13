"""Policy evaluation over validated route observations, without reading raw logs."""
from copy import deepcopy

from ..schema import canonical_sha256
from .domain import HOP_FIELDS, validate_policy
from .semantics import PRIMARY_MODE, describe, mismatch_fields, project, values
from .snapshot import IDENTITY, identity, stable

EVALUATOR_VERSION = "1.1"


def representative(results):
    # Unknown evidence takes precedence for the representative exit status.
    for result in ("UNKNOWN", "FAIL", "WARN", "PASS"):
        if result in results:
            return result
    return "PASS"


def resolve_policy(policy, selected_scopes):
    value = validate_policy(policy, selected_scopes=selected_scopes)
    for group in ("required_routes", "expected_changes", "exclusions"):
        rules = value["spec"].setdefault(group, [])
        for rule in rules:
            if "expected_next_hops" in rule:
                rule["expected_next_hops"]["paths"] = stable(rule["expected_next_hops"]["paths"])
            for side in ("before", "after"):
                if rule.get(side) is not None:
                    rule[side]["paths"] = stable(rule[side]["paths"])
        value["spec"][group] = stable(rules)
    return value, canonical_sha256(value)


def evaluate_policy(policy, contexts, entries, *, control):
    """Contexts carry whole validated scopes, including unchanged/missing routes."""
    results = {g: [] for g in ("required_routes", "expected_changes", "exclusions", "general_changes")}
    if policy is None:
        return results

    def observation(rule):
        key = identity(rule)
        context = contexts[key[:3]]
        before, after = (context[side + "_routes"].get(key[3]) for side in ("before", "after"))
        scopes = [context[side] for side in ("before", "after")]
        eligible = all(s is not None and s["health_eligible"] for s in scopes)
        record = {k: rule[k] for k in IDENTITY}
        for side, route, scope in zip(("before", "after"), (before, after), scopes):
            record["evidence_" + side] = deepcopy(route["evidence"] if route else scope["evidence"] if scope else None)
        return context, before, after, eligible, record

    expected_by_key, required_by_key, excluded_by_key = {}, {}, {}
    all_rules = sum(len(policy["spec"][g]) for g in ("required_routes", "expected_changes", "exclusions"))
    completed = 0
    for group in ("required_routes", "expected_changes", "exclusions"):
        for rule in policy["spec"][group]:
            if completed % 256 == 0:
                control.checkpoint("evaluate", completed, all_rules, unit="rules")
            completed += 1
            context, before, after, eligible, record = observation(rule)
            key = identity(rule)
            if group == "exclusions":
                record.update(result="EXCLUDED", classification="excluded", reason=rule["reason"])
                excluded_by_key[key] = record
            elif group == "required_routes":
                states, violations = {}, {}
                for side, route in (("before", before), ("after", after)):
                    scope = context[side]
                    issues = []
                    if scope is None or not scope["health_eligible"]:
                        state = "UNKNOWN"
                        issues.append("EVIDENCE_INSUFFICIENT")
                    else:
                        if route is None:
                            issues.append("REQUIRED_PREFIX_MISSING")
                        else:
                            if len(route["paths"]) < rule["min_paths"]:
                                issues.append("MIN_PATHS_NOT_MET")
                            hops = rule.get("expected_next_hops")
                            if hops:
                                required = {tuple(p[k] for k in HOP_FIELDS) for p in hops["paths"]}
                                actual = values(route, HOP_FIELDS)
                                if (actual != required if hops["match"] == "exact" else not required <= actual):
                                    issues.append("EXPECTED_NEXT_HOPS_MISMATCH")
                        state = "FAIL" if issues else "PASS"
                    states[side], violations[side] = state, issues
                result = representative(states.values())
                classification = "collection_error" if result == "UNKNOWN" else "pre_existing" if states["before"] == "FAIL" else "regression" if states["after"] == "FAIL" else "satisfied"
                record.update(result=result, classification=classification, before_result=states["before"], after_result=states["after"],
                              violations=violations, recovered=states == dict(before="FAIL", after="PASS"), rule=deepcopy(rule))
                required_by_key[key] = record
            else:
                mismatches = []
                if not eligible:
                    expectation, result, classification = "UNVERIFIABLE", "UNKNOWN", "collection_error"
                else:
                    for side, observed in (("before", before), ("after", after)):
                        mismatches.extend(mismatch_fields(rule[side], observed, side))
                    if not mismatches:
                        expectation, result, classification = "MATCHED", "PASS", "expected_change"
                    else:
                        expectation = "NOT_APPLIED" if project(before) == project(after) else "MISMATCH"
                        result, classification = "WARN", "unexpected_change"
                known = {side: context[side] is not None and context[side]["coverage"] == "COMPLETE" for side in ("before", "after")}
                record.update(result=result, classification=classification, id=rule["id"], reason=rule["reason"],
                    expectation_status=expectation, expected=dict(before=deepcopy(rule["before"]), after=deepcopy(rule["after"])),
                    observed=dict(before=deepcopy(before), after=deepcopy(after)), observed_known=known, mismatch_fields=mismatches)
                expected_by_key[key] = record
            results[group].append(record)
    control.checkpoint("evaluate", completed, all_rules, unit="rules")

    for index, entry in enumerate(entries):
        if index % 256 == 0:
            control.checkpoint("evaluate", index, len(entries), unit="routes")
        key = identity(entry)
        _, before, after, eligible, record = observation(entry)
        expected, required, excluded = expected_by_key.get(key), required_by_key.get(key), excluded_by_key.get(key)
        entry["expectation_status"] = expected["expectation_status"] if expected else "NOT_CONFIGURED"
        entry["expectation_rule_id"] = expected["id"] if expected else None
        reasons = describe(before, after, PRIMARY_MODE)["reason_codes"]
        result, classification = "PASS", "observed"
        if not eligible:
            result, classification = "UNKNOWN", "collection_error"
        elif excluded:
            result, classification = "EXCLUDED", "excluded"
        elif expected:
            result, classification = expected["result"], expected["classification"]
        elif any(r in reasons for r in ("PREFIX_REMOVED", "NEXTHOP_CHANGED", "PATH_COUNT_DECREASED")):
            result, classification = "WARN", "regression"
        if required and required["result"] in ("FAIL", "UNKNOWN"):
            result = representative([result, required["result"]])
            classification = required["classification"] if result == required["result"] else classification
        record.update(result=result, classification=classification, reason_codes=reasons)
        results["general_changes"].append(record)
        entry.update(evaluation=result, classification=classification)
    control.checkpoint("evaluate", len(entries), len(entries), unit="routes")
    return results
