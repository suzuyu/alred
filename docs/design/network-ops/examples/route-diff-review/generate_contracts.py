"""Build design-only schemas and full snapshot examples, not production resources."""

import json


def make_contracts(root, rows, sources, scopes, modes):
    target = root / "contracts"
    target.mkdir(exist_ok=True)

    def obj(properties, required=None, extra=False):
        return dict(type="object", properties=properties,
                    required=list(properties) if required is None else required, additionalProperties=extra)

    def array(items, minimum=0):
        return dict(type="array", items=items, minItems=minimum)

    def ref(name):
        return {"$ref": "#/$defs/" + name}

    def enum(*values):
        return {"enum": list(values)}

    def nullable(value):
        return {"anyOf": [value, {"type": "null"}]}

    string = dict(type="string", minLength=1)
    integer = dict(type="integer", minimum=0)
    positive = dict(type="integer", minimum=1)
    boolean = dict(type="boolean")
    sha = dict(type="string", pattern="^sha256:[0-9a-f]{64}$")
    family = enum("ipv4", "ipv6")
    prefix = dict(type="string", pattern="^[0-9A-Fa-f:.]+/[0-9]+$")
    identity = dict(device=string, vrf=string, family=family, prefix=prefix)
    hop = dict(kind=enum("ip", "discard", "connected", "local"), next_hop_family=nullable(family),
               address=nullable(string), interface=nullable(string), next_hop_vrf=string)
    path = dict(hop, admin_distance=integer, metric=integer)
    route = obj(dict(prefix=prefix, paths=array(ref("ExpectedPath"), 1)))
    route_data = obj(dict(prefix=prefix, paths=array(ref("CanonicalPath"), 1)), extra=True)
    evidence = obj(dict(source_id=string, start_line=positive, end_line=positive, command_id=string),
                   required=["source_id", "start_line", "end_line"], extra=True)
    counts = obj({**{name: nullable(integer) for name in ("before_count", "after_count", "ADDED", "REMOVED", "MODIFIED", "UNCHANGED")},
                  "has_diff": nullable(boolean)}, extra=True)
    definitions = dict(ExpectedPath=obj(path), CanonicalPath=obj(dict(path, protocol=nullable(string)), required=list(path), extra=True),
        ExpectedRoute=route, Route=route_data, Identity=obj(identity), Evidence=evidence,
        Source=obj(dict(id=string, device=string, side=enum("before", "after"), path=string, sha256=sha,
                        input_format=enum("nxos-transcript", "nxos-route-text"), collected_at=nullable(dict(type="string", format="date-time"))), extra=True),
        Counts=counts, Scope=obj(dict(device=string, vrf=string, family=family,
                                     coverage=enum("COMPLETE", "UNKNOWN", "NOT_SELECTED", "NOT_APPLICABLE")), extra=True))

    def save(name, value):
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def schema(name, value):
        if name in ("route-diff-policy", "route-diff-source-map"):
            packaged = root.parents[4] / "alred/schemas/v1" / (name + ".schema.json")
            save(name + ".schema.json", json.loads(packaged.read_text()))
            return
        save(name + ".schema.json", {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:alred:design:route-diff:" + name,
            "$comment": "Design review only. Not registered in production. Domain validation is separate.",
            **value, "$defs": definitions})

    def yaml_envelope(kind, spec):
        return obj(dict(api_version={"const": "alred/v1"}, kind={"const": kind},
                        metadata=obj(dict(name=string)), spec=spec))

    next_hops = obj(dict(match=enum("contains", "exact"), paths=array(obj(hop), 1)))
    required = obj(dict(identity, min_paths=positive, expected_next_hops=next_hops),
                   required=[*identity, "min_paths"])
    expected = obj(dict(identity, id=string, reason=string,
                        before=nullable(ref("ExpectedRoute")), after=nullable(ref("ExpectedRoute"))))
    policy = obj(dict(required_routes=array(required), exclusions=array(obj(dict(identity, reason=string))),
                      expected_changes=array(expected)), required=[])
    schema("route-diff-policy", yaml_envelope("RouteDiffPolicy", policy))
    source = obj(dict(path=string, input_format=enum("nxos-transcript", "nxos-route-text"),
                      command_id=enum("route_ipv4_all_vrfs", "route_ipv6_all_vrfs"),
                      start_line=positive, end_line=positive, completeness=enum("asserted")),
                 required=["path", "input_format"])
    source["dependentRequired"] = {"start_line": ["end_line"], "end_line": ["start_line"]}
    source["allOf"] = [{"if": {"properties": {"input_format": {"const": "nxos-route-text"}}},
                        "then": {"required": ["command_id"]}}]
    schema("route-diff-source-map", yaml_envelope("RouteDiffSourceMap",
        obj(dict(hosts=array(obj(dict(host=string, before=array(source, 1), after=array(source, 1))), 1)))))
    review_entry = obj(dict(entry_key=sha, resource=ref("Identity"), mode=enum(*modes),
        status=enum("UNREVIEWED", "REVIEWED"), comment=dict(type="string"),
        reviewed_at=nullable(dict(type="string", format="date-time"))), extra=True)
    schema("route-diff-review", obj(dict(schema_version={"const": 1}, kind={"const": "RouteDiffReview"},
        comparison_fingerprint=sha, entries=array(review_entry)), extra=True))
    versions = obj({k: string for k in ("parser", "normalizer", "comparator", "renderer")}, extra=True)
    entry = obj(dict(identity, before=nullable(ref("Route")), after=nullable(ref("Route")),
        evidence_before=ref("Evidence"), evidence_after=ref("Evidence"),
        change_type=enum("ADDED", "REMOVED", "MODIFIED"), reason_codes=array(string),
        expectation_status=enum("NOT_CONFIGURED", "MATCHED", "MISMATCH", "NOT_APPLIED", "UNVERIFIABLE")), extra=True)
    schema("route-diff", obj(dict(schema_version={"const": 1}, kind={"const": "RouteDiff"},
        versions=versions, comparison_fingerprint=sha, comparison=obj(dict(primary_mode=enum(*modes), modes=array(enum(*modes), 1)), extra=True),
        sources=array(ref("Source"), 1), summary=obj(dict(coverage=enum("COMPLETE", "PARTIAL", "UNKNOWN"),
            modes=obj({mode: ref("Counts") for mode in modes})), extra=True),
        scopes=array(ref("Scope")), entries=array(entry), diagnostics=array(dict(type="object"))), extra=True))
    snapshot_route = obj(dict(identity, paths=array(ref("CanonicalPath"), 1), evidence=ref("Evidence")), extra=True)
    schema("route-snapshot", obj(dict(schema_version={"const": 1}, kind={"const": "RouteSnapshot"},
        snapshot_id=string, side=enum("before", "after"), versions=obj({k: string for k in ("terminal_adapter", "parser", "normalizer")}, extra=True),
        sources=array(ref("Source"), 1), scopes=array(ref("Scope")), routes=array(snapshot_route)), extra=True))
    for side in ("before", "after"):
        # Known scopes only: full rows include unchanged routes; leaf03 is explicitly outside this example.
        value = dict(schema_version=1, kind="RouteSnapshot", snapshot_id="synthetic-" + side, side=side, synthetic=True,
            design_status="draft", note="leaf01 / leaf02 の全 route。leaf03 はこの Snapshot 例の対象外。parser 実行結果ではない。",
            versions=dict(terminal_adapter="mock-review-1", parser="mock-review-2", normalizer="mock-review-2"),
            sources=[s for s in sources if s["side"] == side and s["device"] != "leaf03"],
            scopes=[{k: s[k] for k in ("device", "vrf", "family", "coverage")} for s in scopes if s["device"] != "leaf03"],
            routes=[{**{k: row[k] for k in identity}, "paths": row[side]["paths"], "evidence": row["evidence_" + side]}
                    for row in rows if row[side] is not None])
        save("route-snapshot-" + side + ".example.json", value)
