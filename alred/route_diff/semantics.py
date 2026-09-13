"""Order-independent route projections shared by comparison and policy evaluation."""
from .domain import FORWARDING_FIELDS, HOP_FIELDS, PATH_FIELDS
from .snapshot import stable

MODES = ("route-only", "route-ad", "route-ad-cost", "nexthop-include", "route-ad-cost-nexthop")
PRIMARY_MODE = MODES[-1]
FIELDS = {
    "route-only": (),
    "route-ad": ("admin_distance",),
    "route-ad-cost": ("admin_distance", "metric"),
    "nexthop-include": (*HOP_FIELDS, "admin_distance"),
    PRIMARY_MODE: PATH_FIELDS,
}


def project(route, mode=PRIMARY_MODE):
    if route is None:
        return None
    return frozenset(tuple(path[k] for k in FIELDS[mode]) for path in route["paths"])


def values(route, fields):
    return set() if route is None else {tuple(p[k] for k in fields) for p in route["paths"]}


def describe(before, after, mode):
    left, right = project(before, mode), project(after, mode)
    change = "ADDED" if before is None else "REMOVED" if after is None else "UNCHANGED" if left == right else "MODIFIED"
    reasons, summary, attribute_changes = [], {}, []
    fields = FIELDS[mode]
    for field, reason in (("admin_distance", "AD_CHANGED"), ("metric", "METRIC_CHANGED")):
        if field in fields:
            a, b = values(before, (field,)), values(after, (field,))
            summary[field] = dict(before=sorted(x[0] for x in a), after=sorted(x[0] for x in b))
            if a != b:
                attribute_changes.append(reason)
    if "address" in fields:
        a, b = values(before, HOP_FIELDS), values(after, HOP_FIELDS)
        summary["next_hops"] = dict(before=[dict(zip(HOP_FIELDS, x)) for x in stable(a)],
                                    after=[dict(zip(HOP_FIELDS, x)) for x in stable(b)])
        summary["path_count"] = dict(before=len(before["paths"]) if before else 0, after=len(after["paths"]) if after else 0)
        if a != b:
            attribute_changes.append("NEXTHOP_CHANGED")
            for field in FORWARDING_FIELDS:
                if values(before, (field,)) != values(after, (field,)):
                    attribute_changes.append(field.upper() + '_CHANGED')
            if all(values(before, (field,)) == values(after, (field,)) for field in HOP_FIELDS):
                attribute_changes.append('PATH_ASSOCIATION_CHANGED')
    if change in ("ADDED", "REMOVED"):
        reasons = ["PREFIX_" + change]
    elif change == "MODIFIED":
        reasons.extend(attribute_changes)
        if "address" in fields and len(before["paths"]) != len(after["paths"]):
            reasons.append("PATH_COUNT_DECREASED" if len(after["paths"]) < len(before["paths"]) else "PATH_COUNT_INCREASED")
        if not attribute_changes:
            reasons.append("PATH_ASSOCIATION_CHANGED")
    return dict(change_type=change, reason_codes=reasons, field_summary=summary)


def mismatch_fields(expected, observed, side):
    if expected is None or observed is None:
        return [] if expected is observed else [side + ".presence"]
    differences = [side + ".paths." + k for k in PATH_FIELDS if values(expected, (k,)) != values(observed, (k,))]
    if not differences and project(expected) != project(observed):
        differences.append(side + ".paths.association")
    return differences
