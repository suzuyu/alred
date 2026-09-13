"""Regenerate synthetic review artifacts; not a route log parser or production CLI.

Only the hand-authored scenarios below are rendered. No user input is read.
Run with Python 3.11+, from any directory. Outputs stay beside this script.
"""

from __future__ import annotations

import csv
import hashlib
import html
import ipaddress
import json
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODES = ("route-only", "route-ad", "route-ad-cost", "nexthop-include", "route-ad-cost-nexthop")
MODE_LABELS = ("Prefix のみ", "Prefix + AD", "Prefix + AD + Cost", "Prefix + AD + NextHop", "Prefix + AD + Cost + NextHop")
REASON_LABELS = {
    "PREFIX_ADDED": "prefix 追加", "PREFIX_REMOVED": "prefix 消失",
    "AD_CHANGED": "AD 変更", "METRIC_CHANGED": "Cost 変更",
    "NEXTHOP_CHANGED": "NextHop 変更", "PATH_COUNT_DECREASED": "ECMP path 減少",
    "PATH_COUNT_INCREASED": "ECMP path 増加", "PATH_ASSOCIATION_CHANGED": "path 属性の対応変更",
}


def write(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def esc(value):
    return html.escape(str(value), quote=True)


def path(address=None, interface=None, ad=110, *, vrf="TENANT-A", kind="ip", protocol="ospf", metric=20):
    return dict(kind=kind, next_hop_family=("ipv" + str(ipaddress.ip_address(address).version)) if address else None,
                address=str(ipaddress.ip_address(address)) if address else None, interface=interface,
                next_hop_vrf=vrf, admin_distance=ad, protocol=protocol, metric=metric)


def route(host, prefix, before, after, note, *, vrf="TENANT-A"):
    return dict(device=host, vrf=vrf, family="ipv" + str(ipaddress.ip_network(prefix).version), prefix=prefix,
                before=None if before is None else dict(prefix=prefix, paths=before),
                after=None if after is None else dict(prefix=prefix, paths=after), note=note)


P1 = path("192.0.2.1", "Ethernet1/1")
P2 = path("192.0.2.2", "Ethernet1/2")
ROWS = [
    route("leaf01", "198.51.100.0/24", [P1], None, "prefix が消失"),
    route("leaf01", "203.0.113.0/24", None, [P1], "prefix が追加"),
    route("leaf01", "192.0.2.0/24", [P1], [dict(P1, admin_distance=200)], "AD 110 → 200"),
    route("leaf01", "198.51.100.128/25", [P1, P2], [P2], "ECMP 2 → 1。共通 path は差分のみ表示で隠す"),
    route("leaf01", "192.0.2.128/25", [P1], [P2], "next-hop と interface が変更"),
    route("leaf01", "203.0.113.128/25", [P1, P2], [P2, P1], "ECMP 順序と経過時間だけの変化。差分なし"),
    route("leaf01", "2001:db8:100::/64", [path("fe80::1", "Ethernet1/1")],
          [path("fe80::1", "Ethernet1/2")], "同じ link-local address でも interface 変更を検出"),
    route("leaf01", "2001:db8:200::/64", [path("2001:db8::1", "Ethernet1/3")],
          [path("2001:db8::1", "Ethernet1/3")], "IPv6 の省略表記と経過時間だけの変化。差分なし"),
    route("leaf01", "2001:db8:300::/64", [path("::ffff:192.0.2.1", None, 200, vrf="default", protocol="bgp")],
          [path("::ffff:192.0.2.1", None, 200, vrf="TENANT-B", protocol="bgp")], "IPv4-mapped IPv6 を保持し、参照先 VRF の変更を検出"),
    route("leaf01", "192.0.2.64/26", [P1], [dict(P1, metric=30)], "Cost のみ 20 → 30。[110/20] → [110/30]"),
    route("leaf01", "2001:db8:500::/64", [path("fe80::5", "Ethernet1/5", protocol="ospfv3")],
          [path("fe80::5", "Ethernet1/5", protocol="ospfv3", metric=40)], "IPv6 の Cost のみ 20 → 40"),
    route("leaf02", "203.0.113.0/24", [path(None, "Null0", 1, vrf="default", kind="discard", protocol="static", metric=0)],
          [path(None, "Null0", 1, vrf="default", kind="discard", protocol="static", metric=0)], "Null0 の経路。差分なし", vrf="default"),
    route("leaf02", "2001:db8:400::/64", [path("2001:db8::2", "Ethernet1/4", vrf="default")],
          [path("2001:db8::2", "Ethernet1/4", vrf="default")], "差分なし", vrf="default"),
]
UNKNOWN = dict(device="leaf03", vrf="TENANT-A", family="ipv4", coverage="UNKNOWN",
               reason="after の出力が path 行の途中で終了。prefix 消失として数えない")
SOURCES = []


def projection(row, side, mode):
    value = row[side]
    if value is None:
        return None
    if mode == "route-only":
        return [row["prefix"]]
    if mode == "route-ad":
        return sorted({f"{row['prefix']}  AD {p['admin_distance']}" for p in value["paths"]})
    if mode == "route-ad-cost":
        return sorted({f"{row['prefix']}  AD {p['admin_distance']}  Cost {p['metric']}" for p in value["paths"]})
    result = []
    for p in value["paths"]:
        hop = p["address"] or p["kind"]
        cost = f"  Cost {p['metric']}" if mode == "route-ad-cost-nexthop" else ""
        result.append(f"{row['prefix']}  AD {p['admin_distance']}{cost}  via {hop}"
                      f"  dev {p['interface'] or '—'}  vrf {p['next_hop_vrf']}"
                      f"  nh-af {p['next_hop_family'] or '—'}  kind {p['kind']}")
    return sorted(set(result))


def change(row, mode):
    before, after = projection(row, "before", mode), projection(row, "after", mode)
    return "ADDED" if before is None else "REMOVED" if after is None else "UNCHANGED" if before == after else "MODIFIED"


def counts(rows, mode):
    result = {key: 0 for key in ("ADDED", "REMOVED", "MODIFIED", "UNCHANGED")}
    for row in rows:
        result[change(row, mode)] += 1
    result.update(before_count=sum(r["before"] is not None for r in rows), after_count=sum(r["after"] is not None for r in rows))
    result["has_diff"] = any(result[k] for k in ("ADDED", "REMOVED", "MODIFIED"))
    return result


def count_text(rows, mode):
    c = counts(rows, mode)
    return f"A {c['ADDED']} / R {c['REMOVED']} / M {c['MODIFIED']}"


def resource_key(row):
    return hashlib.sha256(encode([row[k] for k in ("device", "vrf", "family", "prefix")]).encode()).hexdigest()[:16]


def path_values(row, side, fields):
    return sorted({encode([p[k] for k in fields]) for p in (row[side] or {}).get("paths", [])})


def reasons(row, mode):
    category = change(row, mode)
    if category == "UNCHANGED":
        return []
    if category in ("ADDED", "REMOVED"):
        return ["PREFIX_" + category]
    codes = []
    if path_values(row, "before", ["admin_distance"]) != path_values(row, "after", ["admin_distance"]):
        codes.append("AD_CHANGED")
    if mode in ("route-ad-cost", "route-ad-cost-nexthop") and path_values(row, "before", ["metric"]) != path_values(row, "after", ["metric"]):
        codes.append("METRIC_CHANGED")
    if mode in ("nexthop-include", "route-ad-cost-nexthop"):
        keys = ["kind", "next_hop_family", "address", "interface", "next_hop_vrf"]
        before, after = path_values(row, "before", keys), path_values(row, "after", keys)
        if before != after:
            codes.append("NEXTHOP_CHANGED")
        if len(before) != len(after):
            codes.append("PATH_COUNT_DECREASED" if len(before) > len(after) else "PATH_COUNT_INCREASED")
    return codes or ["PATH_ASSOCIATION_CHANGED"]


def field_summary(row, mode):
    result = []
    if mode != "route-only":
        for key, label in [("admin_distance", "AD"), ("metric", "Cost")]:
            if key == "metric" and mode not in ("route-ad-cost", "route-ad-cost-nexthop"):
                continue
            values = {side: sorted({p[key] for p in (row[side] or {}).get("paths", [])}) for side in ("before", "after")}
            result.append(dict(field=key, label=label, **values, changed=values["before"] != values["after"]))
    if mode in ("nexthop-include", "route-ad-cost-nexthop"):
        keys = ["kind", "next_hop_family", "address", "interface", "next_hop_vrf"]
        values = {side: [json.loads(value) for value in path_values(row, side, keys)] for side in ("before", "after")}
        result.append(dict(field="next_hops", label="NextHop", **values, changed=values["before"] != values["after"]))
        result.append(dict(field="path_count", label="path 数", before=len(values["before"]), after=len(values["after"]), changed=len(values["before"]) != len(values["after"])))
    return result


def summary_text(item):
    if item["field"] == "next_hops":
        return "変更あり（詳細は path 行を参照）" if item["changed"] else "変更なし"
    def value(v):
        return ", ".join(map(str, v)) if isinstance(v, list) and v else "なし" if isinstance(v, list) else str(v)
    return f"{value(item['before'])} → {value(item['after'])}"


def log_text(host, side):
    lines = []
    spans = {}
    host_rows = [r for r in ROWS if r["device"] == host]
    for family in ("ipv4", "ipv6"):
        command = "show ip route vrf all" if family == "ipv4" else "show ipv6 route vrf all"
        family_rows = [r for r in host_rows if r["family"] == family]
        if not family_rows:
            continue
        lines.extend([f"{host}# {command}", "'*' denotes best ucast next-hop", "'**' denotes best mcast next-hop", ""])
        for vrf in sorted({r["vrf"] for r in family_rows}):
            heading = "IP Route" if family == "ipv4" else "IPv6 Routing"
            block_start = len(lines) + 1
            lines.append(f'{heading} Table for VRF "{vrf}"')
            for row in family_rows:
                if row["vrf"] != vrf or row[side] is None:
                    continue
                prefix = row["prefix"]
                shown_prefix = prefix
                if prefix == "2001:db8:200::/64" and side == "before":
                    shown_prefix = "2001:0DB8:0200:0000:0000:0000:0000:0000/64"
                start = len(lines) + 1
                lines.append(f"{shown_prefix}, ubest/mbest: {len(row[side]['paths'])}/0")
                for p in row[side]["paths"]:
                    hop = p["address"] or p["interface"]
                    if p["next_hop_vrf"] != vrf:
                        hop += "%" + p["next_hop_vrf"]
                    if p["interface"] and p["address"]:
                        hop += ", " + p["interface"]
                    if prefix == "2001:db8:200::/64" and side == "before":
                        hop = hop.replace("2001:db8::1", "2001:0DB8:0000:0000:0000:0000:0000:0001")
                    age = "00:12:34" if side == "before" else "00:00:42"
                    proto = {"ospf": "ospf-UNDERLAY, intra", "ospfv3": "ospfv3-UNDERLAY, intra", "bgp": "bgp-65001, internal"}.get(p["protocol"], p["protocol"])
                    lines.append(f"    *via {hop}, [{p['admin_distance']}/{p['metric']}], {age}, {proto}")
                spans[(family, vrf, prefix)] = (start, len(lines))
            spans[(family, vrf, None)] = (block_start, len(lines))
            lines.append("")
        lines.append(f"{host}#")
    return "\n".join(lines) + "\n", spans


def make_sources():
    for host in ("leaf01", "leaf02", "leaf03"):
        for side in ("before", "after"):
            file = f"inputs/{host}/{side}-route.log"
            if host == "leaf03":
                content = f'{host}# show ip route vrf all\nIP Route Table for VRF "TENANT-A"\n198.51.100.0/24, ubest/mbest: 1/0\n'
                content += "    *via 192.0.2.1, [110/20], 00:01:00, ospf-UNDERLAY, intra\nleaf03#\n" if side == "before" else "    *via 192.0.2."
                spans = {}
            else:
                content, spans = log_text(host, side)
            write(file, content)
            source = dict(id=f"{host}-{side}", device=host, side=side, path="../" + file,
                          sha256="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
                          input_format="nxos-transcript", collected_at=None,
                          completeness="incomplete" if host == "leaf03" and side == "after" else "synthetic_complete")
            SOURCES.append(source)
            for row in [r for r in ROWS if r["device"] == host]:
                key = (row["family"], row["vrf"], row["prefix"])
                # Absence refers to the complete command block, not a fictitious route line.
                start, end = spans.get(key, spans.get((row["family"], row["vrf"], None), (1, len(content.splitlines()))))
                row[f"evidence_{side}"] = dict(source_id=source["id"], start_line=start, end_line=end,
                    command_id="route_ipv4_all_vrfs" if row["family"] == "ipv4" else "route_ipv6_all_vrfs")


def paired_lines(row, mode):
    before = set(projection(row, "before", mode) or [])
    after = set(projection(row, "after", mode) or [])
    pairs = [(v, v, True) for v in sorted(before & after)]
    removed, added = before - after, after - before
    if mode in ("nexthop-include", "route-ad-cost-nexthop"):
        keys = ("kind", "next_hop_family", "address", "interface", "next_hop_vrf")
        groups = {}
        for side, remaining in (("before", removed), ("after", added)):
            for p in (row[side] or {}).get("paths", []):
                single = dict(row, **{side: dict(prefix=row["prefix"], paths=[p])})
                line = projection(single, side, mode)[0]
                if line in remaining:
                    identity = encode([p[key] for key in keys])
                    groups.setdefault(identity, {"before": set(), "after": set()})[side].add(line)
        for identity in sorted(groups):
            group = groups[identity]
            if len(group["before"]) == len(group["after"]) == 1:
                b, a = next(iter(group["before"])), next(iter(group["after"]))
                pairs.append((b, a, False))
                removed.remove(b)
                added.remove(a)
    # Unmatched paths are separate groups; vertical proximity is not replacement evidence.
    pairs += [(b, None, False) for b in sorted(removed)]
    pairs += [(None, a, False) for a in sorted(added)]
    return pairs


def scopes():
    result = []
    for host, vrf, family in sorted({(r["device"], r["vrf"], r["family"]) for r in ROWS}):
        rows = [r for r in ROWS if (r["device"], r["vrf"], r["family"]) == (host, vrf, family)]
        observations = {}
        for side in ("before", "after"):
            route_count = sum(row[side] is not None for row in rows)
            observations[side] = dict(collection_status="complete", observed_prefix_count=route_count,
                parsed_prefix_count=route_count, parsed_path_count=sum(len(row[side]["paths"]) for row in rows if row[side]), unparsed_line_count=0)
        result.append(dict(device=host, vrf=vrf, family=family, coverage="COMPLETE", evaluation="NOT_EVALUATED",
                           observations=observations, modes={m: counts(rows, m) for m in MODES}))
    result.append({**UNKNOWN, "evaluation": "NOT_EVALUATED", "modes": {m: dict(before_count=None, after_count=None,
                  ADDED=None, REMOVED=None, MODIFIED=None, UNCHANGED=None, has_diff=None) for m in MODES},
                  "observations": {"before": dict(collection_status="complete", observed_prefix_count=1, parsed_prefix_count=1, parsed_path_count=1, unparsed_line_count=0),
                                   "after": dict(collection_status="incomplete", observed_prefix_count=1, parsed_prefix_count=0, parsed_path_count=0, unparsed_line_count=1)}})
    return result


def make_reports():
    entries = [{**r, "change_type": change(r, MODES[-1]), "mode_changes": {m: change(r, m) for m in MODES},
                "reason_codes": reasons(r, MODES[-1]), "field_summary": field_summary(r, MODES[-1]),
                "mode_reason_codes": {m: reasons(r, m) for m in MODES},
                "status": "OBSERVED", "evaluation": "NOT_EVALUATED", "expectation_status": "NOT_CONFIGURED", "expectation_rule_id": ""} for r in ROWS if change(r, MODES[-1]) != "UNCHANGED"]
    payload = dict(schema_version=1, kind="RouteDiff", design_status="draft", synthetic=True,
        versions=dict(parser="mock-review-2", normalizer="mock-review-2", comparator="mock-review-2", renderer="mock-review-6"),
        comparison=dict(primary_mode=MODES[-1], modes=list(MODES), before_label="before", after_label="after",
                        ignored_fields=["age", "display_order", "protocol", "tag"]),
        sources=SOURCES, not_selected_scopes=[dict(device="leaf03", family="ipv6", reason="両側で未観測")], summary=dict(coverage="PARTIAL", complete_scope_count=4, unknown_scope_count=1,
        modes={m: counts(ROWS, m) for m in MODES}), scopes=scopes(), entries=entries,
        diagnostics=[{**UNKNOWN, "evidence_before": {"source_id": "leaf03-before", "start_line": 1, "end_line": 5},
                      "evidence_after": {"source_id": "leaf03-after", "start_line": 1, "end_line": 4}}])
    payload["comparison_fingerprint"] = "sha256:" + hashlib.sha256(encode(dict(
        sources=[dict(id=s["id"], sha256=s["sha256"]) for s in SOURCES],
        evidence=[{k: r[k] for k in ("device", "vrf", "family", "prefix", "evidence_before", "evidence_after")} for r in ROWS],
        comparison={k: v for k, v in payload["comparison"].items() if k not in {"before_label", "after_label"}}, scope="all-fixture-scopes", policy=None,
        versions={k: v for k, v in payload["versions"].items() if k != "renderer"})).encode()).hexdigest()
    write("route_diff/route-diff.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    example_entry = next(e for e in entries if e["prefix"] == "192.0.2.64/26")
    identity = {k: example_entry[k] for k in ("device", "vrf", "family", "prefix")}
    entry_key = "sha256:" + hashlib.sha256(encode(dict(identity=identity, mode=MODES[-1],
        before=projection(example_entry, "before", MODES[-1]), after=projection(example_entry, "after", MODES[-1]))).encode()).hexdigest()
    write("review-record.example.json", json.dumps(dict(schema_version=1, kind="RouteDiffReview", design_status="draft", synthetic=True,
        comparison_fingerprint=payload["comparison_fingerprint"], entries=[dict(entry_key=entry_key, resource=identity,
        mode=MODES[-1], status="REVIEWED", comment="入力例: Cost 20 → 30 の表示を確認。Health 判定や投入承認を意味しない。",
        reviewed_at="2026-09-13T12:00:00+09:00")]), ensure_ascii=False, indent=2) + "\n")
    table = ["| 比較完了 | Device | VRF | AF | Before → After | Prefix のみ | Prefix + AD | Prefix + AD + Cost | Prefix + AD + NextHop | Prefix + AD + Cost + NextHop | 差分 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for scope in scopes():
        if scope["coverage"] == "UNKNOWN":
            table.append("| [ ] | leaf03 | TENANT-A | ipv4 | 不明 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 比較不能 |")
            continue
        c = scope["modes"][MODES[-1]]
        cells = [f"A {scope['modes'][m]['ADDED']} / R {scope['modes'][m]['REMOVED']} / M {scope['modes'][m]['MODIFIED']}" for m in MODES]
        table.append(f"| [x] | {scope['device']} | {scope['vrf']} | {scope['family']} | {c['before_count']} → {c['after_count']} | " + " | ".join(cells) + f" | {'あり' if c['has_diff'] else 'なし'} |")
    summary = "\n".join(table)
    write("route_diff/checklist.md", "# Route Diff Checklist — レビュー用モック\n\n合成ログの観測差分。正常性は未評価。checkbox は比較完了を示す。\n\n"
          "A = ADDED、R = REMOVED、M = MODIFIED。route-only の M は常に 0。\n\n" + summary +
          "\n\n比較可能 4 scope、UNKNOWN 1 scope。件数は比較可能 scope のみの部分集計。\n\n"
          "- [ ] leaf03 / TENANT-A / ipv4: after が途中出力。REMOVED として計上しない。\n\n[全体差分](route-diff.md)\n")
    detail = ["# Route Diff — レビュー用モック", "", "方式: `route-ad-cost-nexthop`。観測のみ、正常性は未評価。", "", summary,
              "", "比較不能 1 scope を除く部分集計。1 prefix の複数変更も MODIFIED 1 route。", "",
              "| Device | VRF | AF | Prefix | 変更 | 変更理由 | 内容 | 証跡 |", "|---|---|---|---|---|---|---|---|"]
    for r in entries:
        b = f"../inputs/{r['device']}/before-route.log"
        a = f"../inputs/{r['device']}/after-route.log"
        labels = " / ".join(REASON_LABELS[code] for code in r["reason_codes"])
        detail.append(f"| {r['device']} | {r['vrf']} | {r['family']} | {r['prefix']} | {r['change_type']} | {labels} | {r['note']} | [before]({b}) / [after]({a}) |")
    detail.extend(["", "## 比較不能", "", UNKNOWN["reason"], "", "## 成果物", "",
                   "[JSON](route-diff.json) / [CSV](route-diff.csv) / [Checklist](checklist.md)", ""])
    write("route_diff/route-diff.md", "\n".join(detail))
    csv_path = ROOT / "route_diff/route-diff.csv"
    fields = "device,vrf,family,prefix,mode,change_type,reason_codes,before,after,status,evaluation,expectation_status,expectation_rule_id,evidence_before,evidence_after".split(",")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in entries:
            writer.writerow({k: encode(r[k]) if k in {"reason_codes", "before", "after", "evidence_before", "evidence_after"} else MODES[-1] if k == "mode" else r.get(k, "") for k in fields})
        writer.writerow(dict(device="leaf03", vrf="TENANT-A", family="ipv4", mode=MODES[-1], reason_codes="[]", status="UNKNOWN", evaluation="NOT_EVALUATED", expectation_status="NOT_CONFIGURED",
                             evidence_before=encode(payload["diagnostics"][0]["evidence_before"]), evidence_after=encode(payload["diagnostics"][0]["evidence_after"])))
    return summary


def make_host_markdown(host):
    for family in ("ipv4", "ipv6"):
        rows = [r for r in ROWS if r["device"] == host and r["family"] == family]
        for mode in MODES:
            name = f"route_diff/hosts/{host}/route-diff-v{family[-1]}-{mode}_before-route.log_after-route.log.md"
            lines = [f"# {host} / {family} / {mode}", "", "レビュー用モック。正常性は未評価。", ""]
            if host == "leaf03":
                lines += ["UNKNOWN: " + UNKNOWN["reason"] if family == "ipv4" else "NOT_SELECTED: 両側で IPv6 が未観測。正常とは判定しない。", ""]
            else:
                c = counts(rows, mode)
                lines += [f"Before {c['before_count']} → After {c['after_count']} / {count_text(rows, mode)}", ""]
                for row in rows:
                    if change(row, mode) == "UNCHANGED":
                        continue
                    lines += [f"## {row['vrf']} / {row['prefix']} / {change(row, mode)}", "", "変更理由: " + " / ".join(REASON_LABELS[c] for c in reasons(row, mode)), ""]
                    lines += [f"- {item['label']}: {summary_text(item)}" for item in field_summary(row, mode)]
                    lines += ["", "```diff"]
                    for b, a, same in paired_lines(row, mode):
                        if same:
                            continue
                        if b:
                            lines.append("- " + b)
                        if a:
                            lines.append("+ " + a)
                    lines += ["```", ""]
                if not c["has_diff"]:
                    lines += ["差分なし。", ""]
            lines += [f"[before](../../../inputs/{host}/before-route.log) / [after](../../../inputs/{host}/after-route.log)", ""]
            write(name, "\n".join(lines))


CSS = """
:root{--ink:#172e35;--muted:#52656b;--line:#d9e3e2;--accent:#006b65;--paper:#f5f7f5;--red:#8d202a;--green:#17613c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif}
a{color:var(--accent);text-underline-offset:3px}button,select,input{font:inherit}button,select{cursor:pointer}button:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #cd8400;outline-offset:3px}
header{background:#143a3d;color:#fff;padding:17px 4vw;display:flex;justify-content:space-between;align-items:center;gap:18px}header a{color:#c8f3e5}.brand{font-weight:750;letter-spacing:.04em}.tag{font-size:12px;border:1px solid #638884;border-radius:20px;padding:3px 11px}
main{max-width:1440px;margin:auto;padding:32px 4vw 60px}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;color:var(--accent);font-weight:750}h1{font-size:32px;letter-spacing:-.035em;margin:5px 0 8px}h2{font-size:21px;margin:0 0 14px}h3{font-size:16px}p{margin:8px 0 16px}.muted{color:var(--muted)}.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:25px}.hero .note{max-width:380px;font-size:13px;background:#e8efeb;padding:15px 18px;border-radius:8px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:25px 0 20px;border-bottom:1px solid var(--line);padding-bottom:10px}.tabs button{border:0;background:transparent;color:var(--muted);padding:10px 18px;border-radius:6px}.tabs button.active{background:var(--ink);color:#fff}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 17px}.metric,.card{background:#fff;border:1px solid var(--line);border-radius:9px;padding:18px}.metric strong{font-size:30px;display:block;font-weight:650}.metric span{font-size:12px;color:var(--muted)}.metric.add strong{color:var(--green)}.metric.remove strong{color:var(--red)}.metric.modify strong{color:#845811}
.notice{padding:12px 16px;border:1px solid #e0c994;background:#fff8e8;border-radius:6px;margin:15px 0;font-size:13px}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;background:#fff;border:1px solid var(--line);padding:16px;border-radius:8px}.controls label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}select,input[type=search]{height:39px;border:1px solid #bbc9c8;border-radius:5px;padding:6px 10px;background:white;color:var(--ink);max-width:100%}.controls .check{flex-direction:row;align-items:center;min-height:39px;font-size:14px;color:var(--ink)}input[type=checkbox]{width:17px;height:17px;accent-color:var(--accent)}
.legend{display:flex;gap:20px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:14px 0}.dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}.dot.red{background:#e8b7ba}.dot.green{background:#a7d5b9}.route-group{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff;margin:14px 0}.route-title{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:12px 16px;background:#eef3f1;border-bottom:1px solid var(--line)}.route-title code{font-size:14px}.scope{font-size:12px;color:var(--muted)}.badge{font-size:11px;font-weight:750;padding:3px 8px;border-radius:4px;white-space:nowrap;background:#e1e8e7}.badge.ADDED{color:var(--green);background:#d5ebde}.badge.REMOVED{color:var(--red);background:#f6dfe1}.badge.MODIFIED{color:#6f4a08;background:#faeccb}.badge.UNKNOWN{color:#694300;background:#faeccb}
.pair-head,.pair{display:grid;grid-template-columns:1fr 1fr}.pair-head{font-size:11px;color:var(--muted);background:#f9fbfa}.pair-head>*{padding:8px 14px}.pair>div{min-width:0;padding:11px 14px;border-top:1px solid #e7eeee;display:flex;gap:9px;font:12px/1.75 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.pair>div+div,.pair-head>*+*{border-left:1px solid var(--line)}.removed{background:#fce7e9;color:#731f2a}.added{background:#e0f2e7;color:#155335}.empty{background:#f8faf9;color:#8c9a99}.sign{font-weight:800;flex-shrink:0}.route-foot{padding:9px 15px;font-size:12px;color:var(--muted);border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:14px}.unknown-group{border-color:#d5b267}.unknown-body{padding:18px}.downloads{display:flex;gap:14px;flex-wrap:wrap;font-size:13px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;color:var(--muted);font-size:12px;background:#f3f6f4}th,td{padding:12px;border-bottom:1px solid var(--line);white-space:nowrap}pre{background:#f0f4f2;border-radius:7px;padding:16px;overflow:auto;font-size:12px;line-height:1.8}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}.two-col>*{min-width:0}details{border-top:1px solid var(--line);padding:12px 0}summary{cursor:pointer;font-weight:650}footer{margin-top:35px;font-size:12px;color:var(--muted)}[hidden]{display:none!important}.empty-state{padding:40px;text-align:center;border:1px dashed #b7c9c6;border-radius:8px;background:#fff}.file-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:800px){main{padding:22px 16px}.hero{display:block}.hero .note{max-width:none}.metrics{grid-template-columns:repeat(2,1fr)}.two-col,.file-grid{grid-template-columns:1fr}.route-title{align-items:flex-start}.route-foot{display:block}h1{font-size:26px}.controls label{flex:1 1 130px}.pair>div{padding:9px 7px;font-size:11px}.tabs button{padding:8px 10px}}
.raw-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.raw-side{min-width:0;border:1px solid var(--line);border-radius:7px;overflow:hidden;background:#fff}.raw-heading{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:12px;font-size:12px;background:#edf3f1}.raw-heading strong{color:var(--accent)}.raw-scroll{height:590px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.raw-lines{width:max-content;min-width:100%;padding:6px 0}.raw-line{display:flex;min-height:25px;align-items:baseline;font:12px/25px ui-monospace,SFMono-Regular,Consolas,monospace;padding-right:16px}.raw-line code{white-space:pre;font:inherit}.raw-number{position:sticky;left:0;flex:0 0 40px;text-align:right;padding-right:9px;color:#657778;background:#f3f6f5;border-right:1px solid #dae4e1;user-select:none}.raw-sign{flex:0 0 22px;text-align:center;font-weight:750}.raw-line[data-color=removed]{background:#fce7e9;color:#731f2a}.raw-line[data-color=added]{background:#e0f2e7;color:#155335}.raw-line[data-color=modified],.raw-line[data-color=unknown]{background:#fff1d0;color:#755018}.raw-line[data-color=ignored]{background:#edf2f5;color:#506779}.raw-line.search-hit{outline:2px solid #1b7773;outline-offset:-2px}.raw-help{font-size:12px;margin-top:14px}.raw-controls select:disabled{opacity:.55;cursor:default}
@media(max-width:800px){.raw-columns{gap:6px}.raw-line{font-size:11px}.raw-number{flex-basis:30px}.raw-heading{padding:8px}.raw-scroll{height:470px}}
.reason-list{padding:10px 16px;font-size:13px;color:#665011;background:#fffbf0}.field-summary{display:flex;flex-wrap:wrap;gap:12px 28px;margin:0;padding:12px 16px;border-top:1px solid var(--line)}.field-summary dt{font-size:11px;color:var(--muted)}.field-summary dd{margin:0;font-size:13px}.jump-button,.diff-navigation button{border:1px solid #a4bdb7;background:#fff;color:var(--accent);border-radius:5px;padding:6px 10px;font:inherit;cursor:pointer}.count-link{border:0;padding:3px 6px;text-decoration:underline;text-underline-offset:3px;background:transparent;color:var(--accent);font:inherit}.diff-navigation{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:12px;background:#eaf2ee;padding:12px;border:1px solid var(--line);border-radius:7px;font-size:13px}.diff-navigation button:disabled{opacity:.4;cursor:default}.route-group{scroll-margin-top:90px}.selected-difference{outline:2px solid var(--accent);outline-offset:2px}.raw-line.jump-target{box-shadow:inset 4px 0 var(--accent),inset 0 0 0 1px #8eafa5}.comparison-times{font-size:12px;color:var(--muted)}#raw-jump-context{scroll-margin-top:12px}
@media print{header,.tabs,.controls,.downloads{display:none}.route-group{break-inside:avoid}main{padding:0;max-width:none}.raw-scroll{height:auto;overflow:visible}.raw-line code{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}.raw-lines{width:auto}}
"""

JS = """
const $ = id => document.getElementById(id);
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-tab]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-selected', String(b === button)); });
  document.querySelectorAll('[data-panel]').forEach(p => p.hidden = p.dataset.panel !== button.dataset.tab);
}));
function update() {
  const mode = $('mode').value, host = $('host').value, af = $('af').value, vrf = $('vrf').value;
  const query = $('query').value.toLowerCase().trim(), diffOnly = !$('show-unchanged').checked;
  const reason = $('reason').value, changeType = $('change-type').value;
  let displayed = 0, unknown = 0;
  document.querySelectorAll('[data-mode-panel]').forEach(p => p.hidden = p.dataset.modePanel !== mode);
  document.querySelectorAll('.route-group').forEach(g => {
    const scopeMatch = (!host || g.dataset.host === host) && (!af || g.dataset.af === af) && (!vrf || g.dataset.vrf === vrf);
    const isUnknown = g.dataset.change === 'UNKNOWN';
    // UNKNOWN stays visible even when searching a prefix: it is not an empty table.
    g.hidden = !scopeMatch || (!isUnknown && (!g.dataset.search.includes(query) || (diffOnly && g.dataset.change === 'UNCHANGED') || (reason && !g.dataset.reasons.split(',').includes(reason)) || (changeType && g.dataset.change !== changeType)));
    g.querySelectorAll('.pair').forEach(row => row.hidden = diffOnly && row.dataset.same === 'true');
    if (!g.hidden && g.parentElement.dataset.modePanel === mode) { if (isUnknown) unknown++; else displayed++; }
  });
  const count = MOCK_COUNTS[mode];
  ['ADDED','REMOVED','MODIFIED','UNCHANGED'].forEach(k => $(k).textContent = count[k] === null ? '不明' : count[k]);
  $('count-caption').textContent = '全対象の件数（比較可能 scope のみ） / ' + $('mode').selectedOptions[0].textContent;
  $('visible-count').textContent = '表示: ' + displayed + ' prefix / 比較不能: ' + unknown + ' scope';
  $('empty-state').hidden = displayed + unknown !== 0;
  const unobserved = (host === 'leaf03' || (!host && MOCK_HOST === 'leaf03')) && af === 'ipv6';
  $('empty-state').textContent = unobserved
    ? 'この host の IPv6 入力は両側で未観測です。比較対象外であり、差分なしや正常性 PASS とは判定しません。'
    : 'この表示条件に該当する行はありません。検索、AF、VRF、比較方式を変更して確認できます。';
  if (typeof refreshNavigation === 'function') refreshNavigation();
}
document.querySelectorAll('.controls:not(.raw-controls) input,.controls:not(.raw-controls) select').forEach(el => el.addEventListener('input', update));
update();

function updateRaw() {
  const host = $('raw-host').value, mode = $('raw-mode').value, literal = $('raw-color').value === 'literal';
  const query = $('raw-query').value.toLowerCase();
  let matches = 0;
  document.querySelectorAll('.raw-host').forEach(section => {
    section.hidden = section.dataset.rawHost !== host;
    section.querySelectorAll('.raw-line').forEach(line => {
      const color = literal ? line.dataset.literal : JSON.parse(line.dataset.semantic)[mode];
      line.dataset.color = color;
      line.querySelector('.raw-sign').textContent = {removed:'−',added:'+',modified:'Δ',ignored:'≈',unknown:'?'}[color] || '';
      line.title = {removed:'削除 / 変更前',added:'追加 / 変更後',modified:'変更 prefix の見出し',ignored:'選択した比較方式では対象外の文字列差',unknown:'比較不能',same:'変更なし'}[color];
      const hit = Boolean(query) && line.querySelector('code').textContent.toLowerCase().includes(query);
      line.classList.toggle('search-hit', hit);
      if (!section.hidden && hit) matches++;
    });
  });
  $('raw-mode').disabled = literal;
  $('raw-explanation').textContent = literal
    ? '文字列の行差分です。経過時間・表記・表示順の変化も赤 / 緑になります。経路件数や正常性の判定には使用しません。'
    : '選択した比較方式の結果を元ログへ着色しています。≈ は経過時間・表記や選択方式の対象外項目の違いで、経路変更として数えません。';
  $('raw-search-result').textContent = query ? '検索に一致: ' + matches + ' 行（左右合計）。全行を表示したまま枠で強調しています。' : '左右に全行を表示。検索は一致行を強調し、行を隠しません。';
}
document.querySelectorAll('.raw-controls input,.raw-controls select').forEach(el => el.addEventListener('input', updateRaw));
document.querySelectorAll('.raw-host').forEach(section => {
  const panes = Array.from(section.querySelectorAll('.raw-scroll'));
  let owner = null, releaseTimer;
  panes.forEach(pane => pane.addEventListener('scroll', () => {
    if (!$('raw-sync').checked || (owner && owner !== pane)) return;
    owner = pane;
    const other = panes.find(p => p !== pane), range = pane.scrollHeight - pane.clientHeight;
    other.scrollTop = range > 0 ? pane.scrollTop / range * (other.scrollHeight - other.clientHeight) : 0;
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => owner = null, 80);
  }));
});
updateRaw();
if (location.hash === '#raw') document.querySelector('[data-tab="raw"]').click();
"""


def html_group(row, mode, root_prefix):
    changed = change(row, mode)
    p = f'{root_prefix}inputs/{row["device"]}/'
    codes = reasons(row, mode)
    result = [f'<article id="entry-{resource_key(row)}-{mode}" tabindex="-1" class="route-group"{" hidden" if changed == "UNCHANGED" else ""} data-prefix="{esc(row["prefix"])}" data-reasons="{esc(",".join(codes))}" data-host="{esc(row["device"])}" data-vrf="{esc(row["vrf"])}" data-af="{row["family"]}" data-change="{changed}" data-search="{esc((row["prefix"]+" "+row["device"]+" "+row["vrf"]).lower())}">',
      f'<div class="route-title"><div><div class="scope">{esc(row["device"])} / {esc(row["vrf"])} / {row["family"].upper()}</div><code>{esc(row["prefix"])}</code></div><span class="badge {changed}">{changed}</span></div>',
      '<div class="reason-list">' + (" / ".join(esc(REASON_LABELS[code]) for code in codes) if codes else "変更なし") + '</div>']
    if changed != "UNCHANGED":
        result.append('<dl class="field-summary">' + ''.join(f'<div><dt>{esc(item["label"])}</dt><dd>{esc(summary_text(item))}</dd></div>' for item in field_summary(row, mode)) + '</dl>')
    result.append('<div class="pair-head"><div>BEFORE · before-route.log</div><div>AFTER · after-route.log</div></div>')
    for b, a, same in paired_lines(row, mode):
        result.append(f'<div class="pair" data-same="{str(same).lower()}"{" hidden" if same else ""}>')
        for text, cls, sign in ((b, "removed", "−"), (a, "added", "+")):
            result.append(f'<div class="{"common" if same else cls if text else "empty"}"><span class="sign">{"=" if same else sign if text else ""}</span><span>{esc(text) if text else "—"}</span></div>')
        result.append('</div>')
    eb, ea = row['evidence_before'], row['evidence_after']
    jump = dict(host=row["device"], prefix=row["prefix"], mode=mode,
                before=dict(start=eb["start_line"], end=eb["end_line"], present=row["before"] is not None),
                after=dict(start=ea["start_line"], end=ea["end_line"], present=row["after"] is not None))
    result.append(f'<div class="route-foot"><span>{esc(row["note"])}</span><button class="jump-button" data-log-jump="{esc(encode(jump))}">元ログの該当位置へ</button><span>証跡: <a href="{p}before-route.log">before L{eb["start_line"]}–{eb["end_line"]}</a> · <a href="{p}after-route.log">after L{ea["start_line"]}–{ea["end_line"]}</a></span></div></article>')
    return ''.join(result)


def html_unknown():
    return '<article class="route-group unknown-group" data-host="leaf03" data-vrf="TENANT-A" data-af="ipv4" data-change="UNKNOWN" data-search="leaf03 tenant-a"><div class="route-title"><div><div class="scope">leaf03 / TENANT-A / IPV4</div><strong>比較できない scope</strong></div><span class="badge UNKNOWN">UNKNOWN</span></div><div class="unknown-body">after のログが path 行の途中で終了しています。経路消失や差分なしとは判定しません。<br><span class="muted">Before / After 件数、ADDED / REMOVED / MODIFIED は不明。差分のみ表示でもこの説明を残します。</span></div></article>'


def options(values, selected=""):
    return ''.join(f'<option value="{esc(v)}"{" selected" if v == selected else ""}>{esc(label)}</option>' for v, label in values)


def raw_log_panels(names, root_prefix):
    """Annotate complete synthetic sources using their existing evidence spans.

    Semantic annotations come from the fixture model, never a second parser.
    SequenceMatcher is only used for the explicitly labelled literal text view.
    """
    sections = []
    for host in names:
        logs = {side: (ROOT / f"inputs/{host}/{side}-route.log").read_text().splitlines()
                for side in ("before", "after")}
        literal = {side: ["same"] * len(logs[side]) for side in logs}
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, logs["before"], logs["after"], autojunk=False).get_opcodes():
            if tag != "equal":
                literal["before"][i1:i2] = ["removed"] * (i2 - i1)
                literal["after"][j1:j2] = ["added"] * (j2 - j1)
        semantic = {side: [{m: "unknown" if host == "leaf03" else "same" for m in MODES}
                           for _ in logs[side]] for side in logs}
        for row in [r for r in ROWS if r["device"] == host]:
            for side, other, changed_color in (("before", "after", "removed"), ("after", "before", "added")):
                if row[side] is None:
                    continue
                span = row[f"evidence_{side}"]
                opposite = row[f"evidence_{other}"]
                other_lines = set(logs[other][opposite["start_line"] - 1:opposite["end_line"]]) if row[other] else set()
                for mode in MODES:
                    category = change(row, mode)
                    start = span["start_line"] - 1
                    for offset in range(span["end_line"] - span["start_line"] + 1):
                        if category in ("ADDED", "REMOVED"):
                            color = changed_color
                        elif offset == 0:
                            color = "modified" if category == "MODIFIED" else "same"
                        else:
                            fixture_path = row[side]["paths"][offset - 1]
                            one_path = {**row, side: {"prefix": row["prefix"], "paths": [fixture_path]}}
                            color = "same" if projection(one_path, side, mode)[0] in projection(row, other, mode) else changed_color
                        if color == "same" and logs[side][start + offset] not in other_lines:
                            color = "ignored"
                        semantic[side][start + offset][mode] = color
        panes = []
        for side in logs:
            lines = []
            for i, text in enumerate(logs[side]):
                lines.append(f'<div class="raw-line" data-line="{i + 1}" data-semantic="{esc(encode(semantic[side][i]))}" data-literal="{literal[side][i]}"><span class="raw-number">{i + 1}</span><span class="raw-sign" aria-hidden="true"></span><code>{esc(text)}</code></div>')
            source = f'{root_prefix}inputs/{host}/{side}-route.log'
            panes.append(f'<section class="raw-side"><div class="raw-heading"><strong>{side.upper()}</strong><a href="{source}">{side}-route.log</a><span>{len(logs[side])} 行</span></div><div class="raw-scroll" data-side="{side}" tabindex="0" aria-label="{host} {side} ログ全文"><div class="raw-lines">{"".join(lines)}</div></div></section>')
        warning = '<div class="notice">UNKNOWN: after は途中出力です。経路差分の着色は確定せず、文字列差分だけ確認できます。</div>' if host == 'leaf03' else ''
        sections.append(f'<section class="raw-host" data-raw-host="{host}" hidden>{warning}<div class="raw-columns">{"".join(panes)}</div></section>')
    return ''.join(sections)


def raw_log_view(names, root_prefix):
    return f'''<div class="card"><h2>取得したログを全文で比較</h2>
<p class="muted">command、VRF 見出し、経過時間、空行を含めて、元の行順・表記で表示します。正規化表示の検索や AF / VRF filter は適用しません。</p>
<div class="controls raw-controls"><label>Host<select id="raw-host">{options([(n,n) for n in names], names[0])}</select></label>
<label>着色の基準<select id="raw-color"><option value="semantic">経路の差分</option><option value="literal">ログ文字列の差分</option></select></label>
<label>比較方式<select id="raw-mode">{options(list(zip(MODES, MODE_LABELS)), MODES[-1])}</select></label>
<label>全文内を検索<input id="raw-query" type="search" placeholder="例: [110/30]" aria-label="ログ全文内を検索"></label>
<label class="check"><input id="raw-sync" type="checkbox" checked>スクロール同期</label></div>
<div class="legend"><span><i class="dot red"></i>− 削除 / 変更前</span><span><i class="dot green"></i>+ 追加 / 変更後</span><span>Δ 変更 prefix の見出し</span><span>≈ 比較対象外の文字列差</span><span>? 比較不能</span></div>
<p id="raw-explanation" class="muted" aria-live="polite"></p><p id="raw-search-result" class="muted" aria-live="polite"></p>
<div id="raw-jump-context" class="notice" hidden><span id="raw-jump-message"></span> <button id="return-to-diff" class="jump-button">正規化比較へ戻る</button></div>
{raw_log_panels(names, root_prefix)}
<p class="muted raw-help">左右それぞれの行番号は元ログに対応します。同期は縦方向のスクロール位置の割合を合わせます。同じ高さが同じ prefix とは限りません。全文の行は検索や着色の切替で省略されません。</p></div>'''


def make_html(host=None, diffonly_file=False, raw_default=False):
    prefix = "../../../" if host else ""
    output = prefix + "route_diff/"
    rows = [r for r in ROWS if not host or r["device"] == host]
    unknown = not host or host == "leaf03"
    names = [host] if host else ["leaf01", "leaf02", "leaf03"]
    panels = []
    for mode in MODES:
        groups = ''.join(html_group(r, mode, prefix) for r in sorted(rows, key=lambda r: (r['device'], r['vrf'], r['family'], int(ipaddress.ip_network(r['prefix']).network_address), ipaddress.ip_network(r['prefix']).prefixlen)))
        panels.append(f'<section data-mode-panel="{mode}"{" hidden" if mode != MODES[-1] else ""}>{groups}{html_unknown() if unknown else ""}</section>')
    summary_rows = []
    for scope in scopes():
        if host and scope['device'] != host:
            continue
        values = scope['modes']
        known = scope['coverage'] == 'COMPLETE'
        c = values[MODES[-1]]
        cells = ''
        for m in MODES:
            if not known:
                cells += '<td>不明</td>'
                continue
            links = []
            for key in ("ADDED", "REMOVED", "MODIFIED"):
                count = values[m][key]
                selection = dict(host=scope["device"], vrf=scope["vrf"], family=scope["family"], mode=m, change_type=key)
                links.append(f'<button class="count-link" data-summary-filter="{esc(encode(selection))}" title="{key} の差分へ">{count}</button>' if count else '0')
            cells += '<td>' + ' / '.join(links) + '</td>'
        scope_result = "差分あり" if known and c["has_diff"] else "差分なし" if known else '<button class="count-link" data-coverage-jump>UNKNOWN</button>'
        summary_rows.append(f'<tr><td>{esc(scope["device"])}</td><td>{esc(scope["vrf"])}</td><td>{scope["family"]}</td><td>{str(c["before_count"])+" → "+str(c["after_count"]) if known else "不明"}</td>{cells}<td>{scope_result}</td></tr>')
    file_links = ''.join(f'<a href="{output}{name}">{name}</a>' for name in ("checklist.md", "route-diff.md", "route-diff.json", "route-diff.csv"))
    host_links = ''.join(f'<li>{name}: <a href="{output}hosts/{name}/route-diff.html">正規化比較</a> / <a href="{output}hosts/{name}/route-diff-diffonly.html">差分のみ</a> / <a href="{output}hosts/{name}/route-diff-raw.html">ログ全文</a></li>' for name in names)
    md_links = ''.join(f'<li><a href="{output}hosts/{name}/route-diff-v{af}-{mode}_before-route.log_after-route.log.md">{name} / IPv{af} / {mode}</a></li>' for name in names for af in (4, 6) for mode in MODES)
    logs = ''.join(f'<details><summary>{name} / {side}-route.log</summary><p><a href="{prefix}inputs/{name}/{side}-route.log">入力ログを開く</a></p><pre>{esc((ROOT/f"inputs/{name}/{side}-route.log").read_text())}</pre></details>' for name in names for side in ('before', 'after'))
    data = {m: counts(rows, m) for m in MODES}
    if host == "leaf03":
        data = {m: {k: None for k in data[m]} for m in MODES}
    vrf_options = options([('', 'すべて')] + [(n, n) for n in sorted({r['vrf'] for r in rows} | ({'TENANT-A'} if unknown else set()))])
    title = f'{host} · Route diff' if host else 'Route diff · 設計レビュー'
    subtitle = '2 時点の経路について、prefix・AD・Cost・NextHop の変化を確認する。'
    coverage_rows = []
    for scope in scopes():
        if host and scope["device"] != host:
            continue
        for side, obs in scope["observations"].items():
            coverage_rows.append(f'<tr><td>{scope["device"]}</td><td>{scope["vrf"]}</td><td>{scope["family"]}</td><td>{side}</td><td>{obs["collection_status"]}</td><td>{obs["observed_prefix_count"]}</td><td>{obs["parsed_prefix_count"]}</td><td>{obs["parsed_path_count"]}</td><td>{obs["unparsed_line_count"]}</td><td>{scope["coverage"]}</td></tr>')
    document = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head>
<body><header><div class="brand">alred <span style="font-weight:400;opacity:.7"> / Network operations</span></div><span class="tag">DESIGN REVIEW · 06</span><a href="{prefix}index.html">レビュー入口</a></header>
<main><div class="hero"><div><div class="eyebrow">IPv4 / IPv6 · Offline comparison</div><h1>{title}</h1><p class="muted">{subtitle}</p></div><div class="note"><strong>合成データによる UI モック</strong><br>ログ解析・機器接続は行いません。差分は観測情報で、正常性は未評価です。</div></div>
<p class="comparison-times">before: before-route.log / 取得日時 不明　→　after: after-route.log / 取得日時 不明（合成ログ）</p>
<nav class="tabs" role="tablist" aria-label="レビュー内容"><button class="active" data-tab="compare" role="tab" aria-selected="true">左右比較（正規化）</button><button data-tab="raw" role="tab" aria-selected="false">ログ全文比較</button><button data-tab="summary" role="tab" aria-selected="false">全体サマリー・出力</button><button data-tab="inputs" role="tab" aria-selected="false">入力ログ・コマンド案</button><button data-tab="design" role="tab" aria-selected="false">設計の確認事項</button></nav>
<section data-panel="compare"><p id="count-caption" class="muted">全対象の件数 / Prefix + AD + Cost + NextHop</p><div class="metrics">{''.join(f'<div class="metric {cls}"><span>{label}</span><strong id="{key}">{data[MODES[-1]][key] if data[MODES[-1]][key] is not None else "不明"}</strong><span>route</span></div>' for cls,key,label in [('add','ADDED','追加 · ADDED'),('remove','REMOVED','消失 · REMOVED'),('modify','MODIFIED','変更 · MODIFIED'),('','UNCHANGED','一致 · UNCHANGED')])}</div>
{('<div class="notice">比較可能 4 scope の部分集計です。leaf03 / TENANT-A / IPv4 は比較不能で、件数に含めません。</div>' if not host else '<div class="notice">この host は比較不能です。0 route / 差分なしを意味しません。</div>' if unknown else '')}
<div class="controls"><label>比較方式<select id="mode">{options(list(zip(MODES, MODE_LABELS)), MODES[-1])}</select></label><label>Host<select id="host">{options([('', 'すべて')] + [(n,n) for n in names], host or '')}</select></label><label>VRF<select id="vrf">{vrf_options}</select></label><label>Address family<select id="af">{options([('', 'IPv4 + IPv6'),('ipv4','IPv4'),('ipv6','IPv6')])}</select></label><label>変更種別<select id="change-type">{options([("", "すべて"), ("ADDED", "ADDED"), ("REMOVED", "REMOVED"), ("MODIFIED", "MODIFIED")])}</select></label><label>変更理由<select id="reason">{options([("", "すべて")] + list(REASON_LABELS.items()))}</select></label><label>Prefix / host を検索<input type="search" id="query" placeholder="例: 2001:db8" aria-label="Prefix または host を検索"></label><label class="check"><input id="show-unchanged" type="checkbox">差分行以外も表示</label></div>
<div class="legend"><span><i class="dot red"></i>− 削除された行</span><span><i class="dot green"></i>+ 追加された行</span><span>= 共通行</span><span id="visible-count" aria-live="polite"></span></div>
<p class="muted" style="font-size:12px">差分のある正規化行だけを既定表示。共通行は「差分行以外も表示」で追加できます。経過時間・順序・IPv6 表記差を除外します。集計カードは全対象、下の表示は filter 後です。左右に並ぶ変更行は一意な同一 NextHop の属性変更です。対応未確定の path は左だけの削除群・右だけの追加群として表示します。</p>
<div class="diff-navigation"><button id="previous-difference" disabled>前の差分</button><span id="difference-position" aria-live="polite"></span><button id="next-difference">次の差分</button><span class="muted">現在の表示条件に該当する変更 prefix</span></div>
{''.join(panels)}<div id="empty-state" class="empty-state" hidden>この表示条件に該当する差分はありません。<br><span class="muted">検索、AF、VRF、比較方式を変更して確認できます。</span></div><noscript><div class="notice">表示の切り替えには JavaScript が必要です。全件の確定サマリーは Markdown / JSON を確認してください。</div></noscript></section>
<section data-panel="raw" id="raw-panel" hidden>{raw_log_view(names, prefix)}</section>
<section data-panel="summary" hidden><div class="card"><h2>Prefix の増減と、属性を含む変更を分けて確認</h2><p class="muted">各方式の列は ADDED / REMOVED / MODIFIED。1 prefix の複数 field 変更も M = 1 です。</p><div class="table-wrap"><table id="scope-summary"><thead><tr><th>Host</th><th>VRF</th><th>AF</th><th>Before → After</th><th>Prefix のみ</th><th>Prefix + AD</th><th>Prefix + AD + Cost</th><th>Prefix + AD + NextHop</th><th>Prefix + AD + Cost + NextHop</th><th>結果</th></tr></thead><tbody>{''.join(summary_rows)}</tbody></table></div><p class="muted">件数をクリックすると該当する差分へ移動します。UNKNOWN の件数は不明。checkbox は比較完了を示し、正常性の PASS とは別です。</p><div class="downloads">{file_links}</div></div>
<div class="card" id="coverage-detail" tabindex="-1" style="margin-top:18px"><h2>比較の完全性（合成入力の期待値）</h2><p class="muted">production parser の実行結果ではありません。比較不能を「差分なし」に含めません。</p><div class="table-wrap"><table><thead><tr><th>Host</th><th>VRF</th><th>AF</th><th>時点</th><th>取得状態</th><th>観測 prefix</th><th>解析 prefix</th><th>解析 path</th><th>未解析行</th><th>比較</th></tr></thead><tbody>{''.join(coverage_rows)}</tbody></table></div></div>
<div class="two-col" style="margin-top:18px"><div class="card"><h2>ホスト別 HTML</h2><ul>{host_links}</ul><p class="muted">正規化比較は差分行のみが既定です。「差分行以外も表示」で共通行を追加できます。diffonly file も同じ既定表示を維持し、ログ全文は別 view で確認できます。</p></div><div class="card"><h2>ホスト別 Markdown</h2><details><summary>IPv4 / IPv6 × 5 方式</summary><ul>{md_links}</ul></details></div></div></section>
<section data-panel="inputs" hidden><div class="two-col"><div class="card"><h2>2 ログを直接比較</h2><p>任意の 2 時点を指定。作業途中のログも利用できます。</p><pre>alred route-diff-nxos \\\n  --before inputs/leaf01/before-route.log \\\n  --after inputs/leaf01/after-route.log \\\n  --input-format nxos-transcript \\\n  --output-dir review-01/route_diff</pre><p class="muted">未実装の CLI 案です。このモックで command は実行しません。</p></div><div class="card"><h2>Health Check と同じ処理を使用</h2><pre>alred health-check before --collect \\\n  --profile network-baseline-nxos \\\n  --profile route-diff-nxos</pre><p class="muted">追加 profile 案。standalone の比較は Health の基準状態を更新しません。</p><a href="{prefix}source-map.example.yaml">複数 host の入力 YAML 案</a></div></div><div class="card" style="margin-top:18px"><h2>入力例</h2><p>合成ログです。leaf03 の after は意図的に途中で切れています。</p>{logs}</div></section>
<section data-panel="design" hidden><div class="card"><h2>今回確定した内容</h2><p>初回は CLI・オフライン出力・Health 統合。Web UI は他の alred 機能も含めてリリース後に検討します。</p><p><a href="{prefix}contracts/README.md">共通データ形式・schema のレビュー</a></p><p><strong>nexthop-include = prefix + AD + next-hop</strong>。interface と参照先 VRF を含み、AD と next-hop の対応も比較します。</p><p><strong>採用方式: Prefix + AD + Cost / Prefix + AD + Cost + NextHop</strong><br>Cost は [110/20] の 20（metric）です。AD と Cost、NextHop の対応を保持します。既定表示と主差分は Cost 込みとします。</p><p><a href="{prefix}review-cases.html">追加ケース: 期待変更 / ECMP の対応 / 端末ログ・Health</a></p><h2>追加した操作</h2><p>変更理由の表示・絞り込み、前後の差分への移動、サマリーの件数から移動、元ログの証跡位置へのジャンプと復帰を追加しました。</p><p><a href="{prefix}route-policy.example.yaml">重要経路 policy 案</a> · <a href="{prefix}review-record.example.json">レビュー記録の保存形式案</a></p><p class="muted">ページング / 仮想スクロール、CIDR 検索、レビュー記録保存、policy 判定は設計・入力例のみです。</p><h2>この画面で確認したい点</h2><ol><li>ホスト別 directory と、元 filename の拡張子を残す命名。</li><li>5 方式の切替と、IPv6 用の v6 出力。</li><li>正規化した差分表示と、元ログ全文の左右表示。</li><li>全文表示の着色基準（経路 / 文字列）、元の行番号、スクロール同期。</li><li>サマリーの prefix 件数と、UNKNOWN を別に示す部分集計。</li><li>Cost を含む 2 方式。protocol / route type の比較は将来の拡張候補。</li><li>単独 command は既定で観測のみとし、正常性判定は任意 policy とする。</li></ol><p><a href="{prefix}../../ROUTE_DIFF_DESIGN.md">設計案全文</a> · <a href="{prefix}README.md">レビュー資料の使い方</a></p><p class="muted">この HTML は出力形式のレビュー用です。ログ upload や自由入力からの解析は未実装です。</p></div></section>
<footer>Route diff review · 2026-09-13 · fixture / mock-review-2 · 外部通信なし<br>prefix の存在確認は RIB の観測であり、FIB や実通信の到達性は確認しません。</footer></main>
<script>const MOCK_HOST = {encode(host)}; const MOCK_COUNTS = {encode(data)};</script><script>{JS}</script><script>{(ROOT / "review_interactions.js").read_text()}</script></body></html>'''
    target = f"route_diff/hosts/{host}/route-diff{'-diffonly' if diffonly_file else ''}.html" if host else "index.html"
    if raw_default:
        target = f"route_diff/hosts/{host}/route-diff-raw.html"
        document = document.replace('class="active" data-tab="compare" role="tab" aria-selected="true"', 'data-tab="compare" role="tab" aria-selected="false"')
        document = document.replace('data-tab="raw" role="tab" aria-selected="false"', 'class="active" data-tab="raw" role="tab" aria-selected="true"')
        document = document.replace('<section data-panel="compare">', '<section data-panel="compare" hidden>')
        document = document.replace('<section data-panel="raw" id="raw-panel" hidden>', '<section data-panel="raw" id="raw-panel">')
    write(target, document)


def main():
    make_sources()
    make_reports()
    for host in ("leaf01", "leaf02", "leaf03"):
        make_host_markdown(host)
        make_html(host)
        make_html(host, True)
        make_html(host, raw_default=True)
    make_html()
    from generate_contracts import make_contracts
    make_contracts(ROOT, ROWS, SOURCES, scopes(), MODES)
    from generate_review_cases import make_cases
    make_cases(ROOT, route, path, paired_lines)
    print("Generated synthetic review: index.html, 6 logs, JSON/CSV/Markdown, 9 host HTML files.")


if __name__ == "__main__":
    main()
