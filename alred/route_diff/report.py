"""Offline reports from validated snapshots; no device access or operation mutation."""
from __future__ import annotations

import base64
from collections import defaultdict
from copy import deepcopy
import csv
import hashlib
import html
from io import StringIO
import json
import os
from pathlib import Path
import re

from ..resources import get_resource_dir
from ..schema import canonical_sha256
from .comparator import compare_snapshots, validate_diff
from .control import ProcessingControl
from .domain import HOP_FIELDS, RouteInputError
from .semantics import FIELDS, MODES, PRIMARY_MODE, describe, project
from .snapshot import IDENTITY, identity, stable

RENDERER_VERSION = "1.1"
CSV_FIELDS = ("device", "vrf", "family", "prefix", "mode", "change_type", "reason_codes", "before", "after",
              "status", "evaluation", "expectation_status", "expectation_rule_id", "evidence_before", "evidence_after")


def review_key(resource, before, after, mode):
    return canonical_sha256(dict(resource=resource, mode=mode,
        before=stable(project(before, mode)) if before else None,
        after=stable(project(after, mode)) if after else None))


def pair_paths(before, after, mode):
    """Return projected path index groups, with only unambiguous NH pairing."""
    groups = []
    for route in (before, after):
        grouped = defaultdict(list)
        for i, path in enumerate(route["paths"] if route else []):
            grouped[tuple(path[k] for k in FIELDS[mode])].append(i)
        groups.append(grouped)
    left, right = groups
    rows = []
    for key in stable(left.keys() & right.keys()):
        rows.append(dict(before=left.pop(key), after=right.pop(key), kind="common"))
    if "address" in FIELDS[mode]:
        hops = [defaultdict(list), defaultdict(list)]
        for side, grouped in enumerate(groups):
            for key in grouped:
                hops[side][key[:len(HOP_FIELDS)]].append(key)
        for hop in stable(hops[0].keys() & hops[1].keys()):
            a, b = hops[0][hop], hops[1][hop]
            if len(a) == len(b) == 1:
                rows.append(dict(before=left.pop(a[0]), after=right.pop(b[0]), kind="attributes"))
    rows.extend(dict(before=left[k], after=[], kind="removed") for k in stable(left))
    rows.extend(dict(before=[], after=right[k], kind="added") for k in stable(right))
    return rows


def safe_component(value, limit=64):
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip(".") or "source"
    reserved = cleaned.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if cleaned != value or len(cleaned) > limit or reserved:
        cleaned = cleaned[:limit - 13] + "-" + hashlib.sha256(value.encode()).hexdigest()[:12]
    return cleaned


def _visible(text):
    return "".join(c if (c == "\t" or ord(c) >= 32 and not 127 <= ord(c) <= 159 and c not in "\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
                   else {"\r": "\\r", "\b": "\\b"}.get(c, f"\\x{ord(c):02x}" if ord(c) < 256 else f"\\u{ord(c):04x}") for c in text)


def build_report_model(before, after, result, raw_sources, *, control=None):
    """Verify evidence, then build shared route data and compact display projections."""
    control = control or ProcessingControl()
    validate_diff(result, control=control)
    selected = {identity(s, scope=True) for s in result["comparison"]["selected_scopes"]}
    actual = compare_snapshots(before, after, selected_scopes=selected or None, policy=result["policy"], control=control)
    actual["versions"]["renderer"] = result["versions"]["renderer"]
    if actual != result and selected:
        # An implicit selection also retains sources whose scope could not be found.
        # The v1 result records resolved scopes, not whether selection was implicit.
        actual = compare_snapshots(before, after, policy=result["policy"], control=control)
        actual["versions"]["renderer"] = result["versions"]["renderer"]
    if actual != result:
        raise RouteInputError("/result", "comparison does not match the supplied snapshots")
    result = deepcopy(result)
    result["versions"]["renderer"] = RENDERER_VERSION
    expected_sources = {(s["side"], s["id"]) for s in result["sources"]}
    if set(raw_sources) != expected_sources:
        raise RouteInputError("/raw_sources", "provide exactly the before/after source bytes")
    sources = []
    for i, source in enumerate(result["sources"]):
        control.checkpoint("render_sources", i, len(result["sources"]), unit="sources")
        raw = raw_sources[(source["side"], source["id"])]
        if not isinstance(raw, bytes) or "sha256:" + hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise RouteInputError("/raw_sources", "raw source hash mismatch")
        lines = []
        for number, mapping in enumerate(source["mapping"]):
            if number % 1024 == 0:
                control.checkpoint("render_raw", number, len(source["mapping"]), unit="lines")
            line = raw[mapping["raw_start_byte"]:mapping["raw_end_byte"]].decode("utf-8")
            if line.endswith("\n"):
                line = line[:-1]
                if line.endswith("\r"):
                    line = line[:-1]
            lines.append(_visible(line))
        selected = result['comparison']['selected_scopes']
        host_selected = [s for s in selected if s['device'] == source['device']]
        ranges = []
        for command in source['commands']:
            block = command['acquisition_evidence']['block']
            if block and (not host_selected or any(s['family'] == command['family'] and command['vrf'] in (None, s['vrf']) for s in host_selected)):
                ranges.append(dict(start_line=block['start_line'], end_line=block['end_line'],
                                   key=[command['command_id'], command['vrf']], command=command['command'] or command['command_id']))
        sources.append(dict(meta=source, lines=lines, route_ranges=sorted(ranges, key=lambda r: r['start_line']), bytes=base64.b64encode(raw).decode("ascii"),
                            colors={m: {} for m in MODES}))
    source_index = {(s["meta"]["side"], s["meta"]["id"]): s for s in sources}

    def paint(side, evidence, mode, symbol, heading=False):
        source = source_index[(side, evidence["source_id"])]
        end = evidence["start_line"] if heading else evidence["end_line"]
        for number in range(evidence["start_line"], end + 1):
            source["colors"][mode][str(number)] = symbol

    def path_text(side, route, indexes):
        texts = []
        for index in indexes:
            e = route["paths"][index]["evidence"]
            lines = source_index[(side, e["source_id"])]["lines"]
            texts.append("\n".join(lines[e["start_line"] - 1:e["end_line"]]))
        return sorted(texts)

    scopes = {identity(s, scope=True): s for s in result["scopes"]}
    maps = [{identity(r): r for r in s["routes"]} for s in (before, after)]
    entries = {identity(e): e for e in result["entries"]}
    rows = []
    keys = stable(maps[0].keys() | maps[1].keys())
    for i, key in enumerate(keys):
        if i % 256 == 0:
            control.checkpoint("render_routes", i, len(keys), unit="routes")
        scope = scopes.get(key[:3])
        if scope is None or scope["coverage"] != "COMPLETE":
            continue
        a, b = (m.get(key) for m in maps)
        resource = dict(zip(IDENTITY, key))
        entry = entries.get(key)
        row = dict(resource=resource, before=a, after=b, modes={}, evaluation=entry["evaluation"] if entry else "NOT_EVALUATED",
                   expectation_status=entry["expectation_status"] if entry else "NOT_CONFIGURED")
        for side, route in (("before", a), ("after", b)):
            row["evidence_" + side] = route["evidence"] if route else scope[side]["evidence"]
        for mode in MODES:
            projection = describe(a, b, mode)
            pairs = pair_paths(a, b, mode)
            projection["pairs"] = pairs
            projection["entry_key"] = review_key(resource, a, b, mode) if projection["change_type"] != "UNCHANGED" else None
            row["modes"][mode] = projection
            for side, route in (("before", a), ("after", b)):
                if route and projection["change_type"] != "UNCHANGED":
                    paint(side, route["evidence"], mode, "Δ", heading=True)
            for pair in pairs:
                common = pair["kind"] == "common"
                textual = common and path_text("before", a, pair["before"]) != path_text("after", b, pair["after"])
                for side, route, symbol in (("before", a, "−"), ("after", b, "+")):
                    for index in pair[side]:
                        paint(side, route["paths"][index]["evidence"], mode, "≈" if textual else "=" if common else symbol)
        rows.append(row)
    for scope in result["scopes"]:
        if scope["coverage"] != "UNKNOWN":
            continue
        for side in ("before", "after"):
            if scope[side]:
                for mode in MODES:
                    paint(side, scope[side]["evidence"], mode, "?")
    for diagnostic in result["diagnostics"]:
        if diagnostic.get("code") == "UNSCOPED_SOURCE":
            for source in sources:
                if source["meta"]["side"] == diagnostic.get("side") and source["meta"]["id"] == diagnostic.get("source_id"):
                    for mode in MODES:
                        source["colors"][mode] = {str(n): "?" for n in range(1, len(source["lines"]) + 1)}
    return dict(result=result, rows=rows, sources=sources, modes=list(MODES), fields={m: list(FIELDS[m]) for m in MODES})


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _md(value):
    escaped = html.escape(str(value)).replace("\\", "\\\\")
    escaped = escaped.translate(str.maketrans({c: "\\" + c for c in "[]()!*_#"}))
    return escaped.replace("|", "&#124;").replace("`", "&#96;").replace("\r", "\\r").replace("\n", "<br>")


def _cell(value):
    value = _json(value) if isinstance(value, (dict, list)) else "" if value is None else str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def render_csv(model):
    out = StringIO(newline="")
    writer = csv.DictWriter(out, CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in model["result"]["entries"]:
        row = {key: entry.get(key) for key in CSV_FIELDS}
        row["status"] = "COMPLETE"
        writer.writerow({k: _cell(v) for k, v in row.items()})
    for scope in model["result"]["scopes"]:
        if scope["coverage"] == "UNKNOWN":
            row = {k: scope[k] for k in IDENTITY[:3]}
            row.update(mode=PRIMARY_MODE, status="UNKNOWN", change_type="UNKNOWN", evaluation="UNKNOWN",
                       reason_codes=scope.get("diagnostics", []), before=scope["before"], after=scope["after"])
            writer.writerow({k: _cell(v) for k, v in row.items()})
    for diagnostic in model["result"]["diagnostics"]:
        if diagnostic.get("code") == "UNSCOPED_SOURCE":
            writer.writerow({"mode": PRIMARY_MODE, "status": "UNKNOWN", "change_type": "UNKNOWN", "evaluation": "UNKNOWN",
                             "reason_codes": _cell([diagnostic])})
    return out.getvalue()


def _counts(counts):
    return " / ".join(f"{key}={value if value is not None else 'null'}" for key, value in counts.items())


def render_checklist(model):
    result = model["result"]
    lines = ["# Route Diff checklist", "", "チェックは比較完了を意味します。差分なしや Health PASS を意味しません。", "",
             f"Coverage: {result['summary']['coverage']} / Evaluation: {result['evaluation']}", ""]
    lines += ["## 全体集計", ""]
    for mode in MODES:
        lines += [f"{mode}: {_counts(result['summary']['modes'][mode])}", ""]
    for scope in result["scopes"]:
        lines += [f"- [{'x' if scope['coverage'] == 'COMPLETE' else ' '}] " + " / ".join(_md(scope[k]) for k in IDENTITY[:3]) + f" — {scope['coverage']}", ""]
        for mode in MODES:
            lines += [f"  {mode}: {_counts(scope['modes'][mode])}", ""]
        if scope["coverage"] != "COMPLETE":
            lines += ["  理由: " + _md(_json(scope)), ""]
    if result["diagnostics"]:
        lines += ["診断: " + _md(_json(result["diagnostics"])), ""]
    return "\n".join(lines)


def _path_label(route, indexes, mode):
    if not indexes:
        return ""
    path = route["paths"][indexes[0]]
    return route["prefix"] + " " + " ".join(f"{field}={path[field]}" for field in FIELDS[mode])


def render_markdown(model, *, mode=PRIMARY_MODE, host=None, family=None):
    result = model["result"]
    lines = ["# Route Diff", "", f"Mode: {mode}", "", f"Coverage: {result['summary']['coverage']} / Evaluation: {result['evaluation']}", ""]
    if "labels" in model:
        lines += ["比較時点: " + _md(model["labels"]["before"]) + " → " + _md(model["labels"]["after"]), ""]
    if host is None:
        lines += ["全体集計: " + _counts(result["summary"]["modes"][mode]), ""]
    scopes = [s for s in result["scopes"] if (host is None or s["device"] == host) and (family is None or s["family"] == family)]
    if not scopes:
        lines += ["UNKNOWN / 未観測: この AF の比較結果はありません。", ""]
    for scope in scopes:
        lines += ["## " + " / ".join(_md(scope[k]) for k in IDENTITY[:3]), "", scope["coverage"], "", _counts(scope["modes"][mode]), ""]
        if scope["coverage"] != "COMPLETE":
            lines += ["診断: " + _md(_json(scope)), ""]
    for row in model["rows"]:
        r, projection = row["resource"], row["modes"][mode]
        if host is not None and r["device"] != host or family is not None and r["family"] != family or projection["change_type"] == "UNCHANGED":
            continue
        lines += ["## " + " / ".join(_md(r[k]) for k in IDENTITY), "",
                  projection["change_type"] + " / " + ", ".join(projection["reason_codes"]), "", "```diff"]
        for pair in projection["pairs"]:
            if pair["kind"] == "common":
                continue
            for side, marker in (("before", "-"), ("after", "+")):
                if pair[side]:
                    label = _path_label(row[side], pair[side], mode).replace("`", "\\u0060").replace("\n", "\\n").replace("\r", "\\r")
                    lines.append(marker + " " + label)
        lines += ["```", "", "証跡: " + _md(_json({s: row["evidence_" + s] for s in ("before", "after")})), ""]
    lines += ["## Sources", ""]
    for source in result["sources"]:
        if host is None or source["device"] == host:
            lines += [f"- {_md(source['side'])}: {_md(source['path'] or source['id'])} / {source['sha256']} / 取得日時: 不明", ""]
    if host is None:
        lines += ["## Policy results", "", _md(_json(result["policy_results"])), "", "## Diagnostics", "", _md(_json(result["diagnostics"])), ""]
    return "\n".join(lines)


def render_html(model, *, host=None, raw=False):
    # All values are data, never executable markup. No source-controlled URL is used.
    from .review import review_catalog

    data = dict(model, initial_host=host, initial_raw=raw, review_catalog=review_catalog(model))
    data["result"] = {k: v for k, v in model["result"].items() if k not in ("entries", "sources")}
    if host is not None:
        data["rows"] = [r for r in model["rows"] if r["resource"]["device"] == host]
        data["sources"] = [s for s in model["sources"] if s["meta"]["device"] == host]
    encoded = _json(data).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (get_resource_dir("j2") / "route_diff.html.j2").read_text(encoding="utf-8")
    return template.replace("__ROUTE_DIFF_DATA__", encoded)


def write_route_report(before, after, result, raw_sources, output_dir, *, control=None, labels=None, review=None, health_context=None):
    """Write a new directory, retaining partial files on failure; manifest is last."""
    control = control or ProcessingControl()
    target = Path(output_dir)
    if os.path.lexists(target):
        raise RouteInputError("/output_dir", "output already exists; use a new directory")
    model = build_report_model(before, after, result, raw_sources, control=control)
    if health_context is not None:
        if (not isinstance(health_context, dict) or health_context.get("phase") not in ("after", "rollback")
                or health_context.get("result") not in ("PASS", "WARN", "FAIL", "UNKNOWN")
                or not isinstance(health_context.get("checks"), list)):
            raise RouteInputError("/health_context", "invalid Health route assessment")
        model["health_context"] = deepcopy(health_context)
    if labels is not None:
        if set(labels) != {"before", "after"} or any(not isinstance(v, str) or not v.strip() or any(ord(c) < 32 for c in v) for v in labels.values()):
            raise RouteInputError("/labels", "before/after labels must be nonempty text without control characters")
        model["labels"] = dict(labels)
    if review is not None or labels is not None:
        from .review import validate_review
        model["review"] = validate_review(review if review is not None else dict(schema_version=1, kind="RouteDiffReview",
            comparison_fingerprint=result["comparison_fingerprint"], entries=[]), model)
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}

    def write(name, content):
        control.checkpoint("render_files", len(hashes), None, unit="files", path=name)
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = content.encode("utf-8")
        path.write_bytes(raw)
        hashes[name] = "sha256:" + hashlib.sha256(raw).hexdigest()

    write("route-diff.json", json.dumps(model["result"], ensure_ascii=False, indent=2) + "\n")
    if health_context is not None:
        write("health-assessment.json", json.dumps(health_context, ensure_ascii=False, indent=2) + "\n")
    if "review" in model:
        write("route-diff-review.json", json.dumps(model["review"], ensure_ascii=False, indent=2) + "\n")
    write("route-diff.csv", render_csv(model))
    health_notice = (f"Health Route 判定 ({health_context['phase']}): **{health_context['result']}**。"
                    "復元判定を含む根拠は `health-assessment.json` を参照。\n\n") if health_context else ""
    write("route-diff.md", health_notice + render_markdown(model))
    write("checklist.md", health_notice + render_checklist(model))
    write("index.html", render_html(model))
    hosts = sorted({s["device"] for s in result["sources"]} | {s["device"] for s in result["scopes"]})
    used = set()
    for host in hosts:
        directory = safe_component(host)
        if directory.casefold() in used:
            directory += "-" + hashlib.sha256(host.encode()).hexdigest()[:12]
        used.add(directory.casefold())
        names = []
        for side in ("before", "after"):
            sources = [s for s in result["sources"] if s["side"] == side and s["device"] == host]
            name = Path(sources[0]["path"] or sources[0]["id"]).name if len(sources) == 1 else side + "-set-" + canonical_sha256(sources)[7:19]
            names.append(safe_component(name))
        for family, suffix in (("ipv4", "v4"), ("ipv6", "v6")):
            for mode in MODES:
                write(f"hosts/{directory}/route-diff-{suffix}-{mode}_{names[0]}_{names[1]}.md", render_markdown(model, mode=mode, host=host, family=family))
        for name in ("route-diff.html", "route-diff-diffonly.html", "route-diff-raw.html"):
            write(f"hosts/{directory}/{name}", render_html(model, host=host, raw=name == "route-diff-raw.html"))
    control.checkpoint("render_complete", len(hashes), len(hashes), unit="files")
    manifest = dict(schema_version=1, kind="RouteDiffReportManifest", renderer_version=RENDERER_VERSION,
                    comparison_fingerprint=result["comparison_fingerprint"], files=hashes)
    (target / "report-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
