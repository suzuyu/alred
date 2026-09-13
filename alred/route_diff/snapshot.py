"""Validated full route snapshots, independent of storage and Health operations."""
from __future__ import annotations

from copy import deepcopy

from ..schema import canonical_json_bytes, canonical_sha256, validate_document
from .commands import resolve_route_command
from .control import ProcessingControl
from .domain import RouteInputError, canonical_path, canonical_prefix, command_scope, path_key
from .parser import ParsedRouteSource, ROUTE_PARSER_VERSION, NORMALIZER_VERSION, LEGENDS

VERSIONS = dict(terminal_adapter="1.0", parser=ROUTE_PARSER_VERSION, normalizer=NORMALIZER_VERSION, section_adapter="1.0")
IDENTITY = ("device", "vrf", "family", "prefix")


def identity(value, *, scope=False):
    return tuple(value[k] for k in (IDENTITY[:3] if scope else IDENTITY))


def stable(values):
    return sorted(values, key=canonical_json_bytes)


def snapshot_hash(document):
    return canonical_sha256({k: v for k, v in document.items() if k != "snapshot_id"})


def _error(message):
    raise RouteInputError("/snapshot", message)


def _evidence(value, sources):
    source = sources.get(value["source_id"])
    if source is None:
        _error("evidence refers to an unknown source")
    start, end = value["start_line"], value["end_line"]
    selected = source["selected_range"]
    if selected is None or not selected["start_line"] <= start <= end <= selected["end_line"]:
        _error("evidence is outside the selected source interval")
    mapping = source["mapping"]
    if value["start_byte"] != mapping[start - 1]["raw_start_byte"] or value["end_byte"] != mapping[end - 1]["raw_end_byte"]:
        _error("evidence byte range disagrees with source line mapping")
    return source


def _validate_acquisition(command, source, sources):
    proof = command['acquisition_evidence']
    for field in ('header', 'prompt', 'body', 'block'):
        evidence = proof[field]
        if evidence is not None and _evidence(evidence, sources)['id'] != source['id']:
            _error('acquisition belongs to another source')
    block, body, prompt = proof['block'], proof['body'], proof['prompt']
    for evidence in (body, prompt, proof['header']):
        if evidence is not None and (block is None or not block['start_line'] <= evidence['start_line'] <= evidence['end_line'] <= block['end_line']):
            _error('acquisition evidence is outside command block')
    if prompt != command['evidence']:
        _error('acquisition prompt disagrees with command')
    if prompt is not None and body is not None and (body['start_line'] != prompt['end_line'] + 1 or body['end_line'] != block['end_line']):
        _error('body must cover the remainder of its command block')
    if proof['header'] is not None and (prompt is None or proof['header']['start_line'] != block['start_line']
            or proof['header']['end_line'] + 1 != prompt['start_line']):
        _error('collector header must precede its prompt')
    completion = proof['completion_evidence']
    if proof['completion_kind'] in ('next_prompt', 'next_collect_header'):
        if completion is None or block is None or completion['source_id'] != source['id']:
            _error('missing completion evidence')
        start, end = completion['start_line'], completion['end_line']
        mapping = source['mapping']
        if not block['end_line'] + 1 == start <= end <= len(mapping):
            _error('completion evidence is not adjacent to the adopted block')
        if completion['start_byte'] != mapping[start-1]['raw_start_byte'] or completion['end_byte'] != mapping[end-1]['raw_end_byte']:
            _error('completion byte mapping disagrees')
        if proof['completion_kind'] == 'next_prompt' and start != end:
            _error('plain prompt completion must be one line')
    elif completion is not None:
        _error('unexpected completion evidence')
    if proof['completion_kind'] == 'manifest_record':
        if proof['manifest_record_sha256'] != source.get('collection_provenance', {}).get('manifest_record_sha256') or not proof['manifest_record_sha256']:
            _error('manifest completion requires retained collector provenance')
    if source['container_format'] == 'alred-collect' and proof['header'] is None:
        _error('collect source requires a header')


def validate_snapshot(document, *, control=None):
    """Check structure, identity, provenance, quality and content hash without I/O."""
    control = control or ProcessingControl()
    control.checkpoint("validate", 0, len(document.get("routes", [])), unit="routes")
    content_digest = control.validation_digest(document)
    if control.was_validated("RouteSnapshot", content_digest):
        control.checkpoint("validate", len(document["routes"]), len(document["routes"]), unit="routes")
        return
    if isinstance(document.get('versions'), dict) and any(document['versions'].get(k) != v for k, v in VERSIONS.items()):
        _error('unsupported parser, adapter or normalizer version; reparse both raw sources')
    validate_document(document, kind="RouteSnapshot")
    if document["snapshot_id"] != snapshot_hash(document):
        _error("snapshot hash mismatch")
    if any(document["versions"][k] != v for k, v in VERSIONS.items()):
        _error("unsupported parser, adapter or normalizer version; reparse the raw source")
    sources = {}
    for source in document["sources"]:
        if source["id"] in sources:
            _error("duplicate source id")
        sources[source["id"]] = source
        if source["side"] != document["side"] or any(source["versions"][k] != v for k, v in VERSIONS.items()):
            _error("source side or versions disagree with snapshot")
        offset = 0
        for number, row in enumerate(source["mapping"], 1):
            if (row["normalized_line"], row["raw_start_line"], row["raw_end_line"], row["raw_start_byte"]) != (number, number, number, offset):
                _error("source line mapping is not contiguous")
            if row["raw_end_byte"] <= offset:
                _error("source mapping has an empty or reversed byte range")
            offset = row["raw_end_byte"]
        if offset != source["raw_size"]:
            _error("source mapping does not cover the raw bytes")
        selected = source["selected_range"]
        if selected is None:
            if source["mapping"]:
                _error("nonempty source requires a selected interval")
        elif not 1 <= selected["start_line"] <= selected["end_line"] <= len(source["mapping"]):
            _error("invalid selected interval")
        for command in source["commands"]:
            _validate_acquisition(command, source, sources)
            specific = command["command_id"] in ("route_ipv4_vrf", "route_ipv6_vrf")
            declared = command_scope(command["command_id"], command["vrf"] if specific else None)
            if any(command[k] != declared[k] for k in declared):
                _error("command acquisition scope is inconsistent")
            if source["input_format"] in ("nxos-transcript", "alred-collect"):
                parsed = resolve_route_command(command["command"] or "")
                if parsed is None or any(parsed[k] != command[k] for k in parsed) or command["evidence"] is None:
                    _error("transcript command evidence is missing or inconsistent")
                if _evidence(command["evidence"], sources)["id"] != source["id"]:
                    _error("command belongs to a different source")
            elif command["command"] is not None or command["evidence"] is not None:
                _error("body-only source cannot invent a command prompt")
        if source["input_format"] == "alred-collect":
            proof = source.get("collection_provenance", {})
            if (proof.get("adapter_version") != "1.1" or proof.get("status") != "success"
                    or not proof.get("collected_at") or len(source["commands"]) != 1
                    or resolve_route_command(proof.get("command", "")) != resolve_route_command(source["commands"][0]["command"])
                    or proof.get("start_line") != source["selected_range"]["start_line"]
                    or proof.get("end_line") != source["selected_range"]["end_line"]):
                _error("collector provenance is missing or inconsistent")

    scopes, routes = {}, {}
    for scope in document["scopes"]:
        key = identity(scope, scope=True)
        if key in scopes:
            _error("duplicate scope across sources")
        scopes[key] = scope
        source = _evidence(scope["evidence"], sources)
        if scope["device"] != source["device"] or scope["command_scope"] not in source["commands"]:
            _error("scope disagrees with source identity or acquisition")
        if scope["verification"] == "verified" and source["input_format"] not in ("nxos-transcript", "alred-collect"):
            _error("body-only source cannot claim verified provenance")
        acquisition_proof = scope['command_scope']['acquisition_evidence']
        if scope['verification'] == 'verified':
            if acquisition_proof['completion_kind'] == 'eof_unverified':
                _error('verified scope requires command completion evidence')
            if source['container_format'] == 'alred-collect' and acquisition_proof['declared_status'] != 'OK':
                _error('verified collector scope requires successful status')
        body = acquisition_proof['body']
        if body is None or not body['start_line'] <= scope['evidence']['start_line'] <= scope['evidence']['end_line'] <= body['end_line']:
            _error('scope must be inside the adopted command body')
        if scope["verification"] == "user_asserted" and source["input_format"] != "nxos-route-text":
            _error("transcript cannot claim body-only assertion")
        complete = scope["parse_status"] == "COMPLETE" and scope["verification"] != "unknown"
        if (scope["coverage"] == "COMPLETE") != complete:
            _error("coverage conflicts with syntax and verification")
        if scope["health_eligible"] != (complete and scope["verification"] == "verified"):
            _error("Health evidence eligibility conflicts with coverage")
        if scope["parse_status"] == "COMPLETE":
            acquisition = scope["command_scope"]
            if scope["diagnostics"] or any('command_id' not in d for d in source["diagnostics"]):
                _error("complete syntax has unresolved diagnostics")
            if acquisition["family"] != scope["family"] or acquisition["vrf"] not in (None, scope["vrf"]):
                _error("complete scope disagrees with acquisition range")
        basis, empty = scope['empty_basis'], scope['empty_evidence']
        if basis is not None:
            if empty is None or (scope['parse_status'] == 'COMPLETE' and scope['observed_prefix_count']) or scope['explicit_empty'] != (basis == 'explicit_marker'):
                _error('empty table proof conflicts with observed routes or marker')
            if basis == 'explicit_marker':
                _evidence(empty['marker'], sources)
            else:
                proof = scope['command_scope']['acquisition_evidence']
                if proof['completion_kind'] not in ('next_prompt', 'next_collect_header') or scope['verification'] != 'verified':
                    _error('closed empty table requires a verified next command or prompt')
                if empty.get('command_end') != proof['completion_evidence']:
                    _error('empty table command boundary disagrees')
                _evidence(empty['heading'], sources)
                required = LEGENDS if scope['family'] == 'ipv4' else {v for v in LEGENDS if not v.startswith("'%")}
                if not required <= {v['text'] for v in empty.get('legends', [])}:
                    _error('empty table legends are incomplete')
                for legend in empty['legends']:
                    _evidence(legend['evidence'], sources)
                    if not scope['evidence']['start_line'] < legend['evidence']['start_line'] <= scope['evidence']['end_line']:
                        _error('empty table legend outside VRF section')
        elif empty is not None or scope['explicit_empty']:
            _error('empty proof is missing its basis')
        routes[key] = []

    seen = set()
    for index, route in enumerate(document["routes"]):
        if index % 256 == 0:
            control.checkpoint("validate", index, len(document["routes"]), unit="routes")
        key = identity(route)
        if key in seen or key[:3] not in scopes:
            _error("duplicate route or missing parent scope")
        seen.add(key)
        scope = scopes[key[:3]]
        routes[key[:3]].append(route)
        if route["prefix"] != canonical_prefix(route["prefix"], route["family"]):
            _error("route prefix is not canonical")
        source = _evidence(route["evidence"], sources)
        if source["id"] != scope["evidence"]["source_id"]:
            _error("route and scope refer to different sources")
        if not scope["evidence"]["start_line"] <= route["evidence"]["start_line"] <= route["evidence"]["end_line"] <= scope["evidence"]["end_line"]:
            _error("route evidence is outside its VRF section")
        selected = set()
        for field in ("paths", "non_selected_paths"):
            for path in route[field]:
                if canonical_path(path) != path:
                    _error("path is not canonical")
                _evidence(path["evidence"], sources)
                if path["evidence"]["source_id"] != source["id"] or not route["evidence"]["start_line"] <= path["evidence"]["start_line"] <= path["evidence"]["end_line"] <= route["evidence"]["end_line"]:
                    _error("path evidence is outside its route")
                if field == "paths":
                    if path_key(path) in selected and route["parse_status"] == "COMPLETE":
                        _error("complete route has duplicate paths")
                    selected.add(path_key(path))
        if route["parse_status"] == "COMPLETE" and (not route["paths"] or route["ubest"] != len(route["paths"])):
            _error("complete route has missing paths or a ubest mismatch")
        if scope["parse_status"] == "COMPLETE" and route["parse_status"] != "COMPLETE":
            _error("complete scope contains an incomplete route")
    for key, scope in scopes.items():
        values = routes[key]
        if scope["parsed_prefix_count"] != sum(r["parse_status"] == "COMPLETE" for r in values) or scope["parsed_path_count"] != sum(len(r["paths"]) for r in values):
            _error("diagnostic route counts disagree with stored routes")
        if scope["observed_prefix_count"] < len(values):
            _error("observed prefix count is smaller than parsed routes")
        if scope["parse_status"] == "COMPLETE":
            if bool(scope["empty_basis"]) != (not values) or scope["observed_prefix_count"] != len(values):
                _error("complete scope is neither a consistent route table nor an explicit empty table")
    control.checkpoint("validate", len(document["routes"]), len(document["routes"]), unit="routes")
    control.remember_validated("RouteSnapshot", content_digest)


def build_snapshot(parsed_sources: list[ParsedRouteSource], *, side: str, source_paths=None, control=None):
    """Assemble immutable-by-convention evidence; return a detached JSON document."""
    control = control or ProcessingControl()
    if side not in ("before", "after"):
        _error("before/after side and at least one parsed source are required")
    result = dict(schema_version=1, kind="RouteSnapshot", side=side, versions=dict(VERSIONS), sources=[], scopes=[], routes=[])
    for index, parsed in enumerate(parsed_sources):
        control.checkpoint("snapshot", index, len(parsed_sources), unit="sources")
        source = deepcopy(parsed.document)
        if source["terminal"] != parsed.terminal.manifest():
            _error("parser manifest disagrees with retained raw evidence")
        manifest = source["terminal"]
        record = dict(id=source["source_id"], device=source["device"], side=side,
            path=(source_paths or {}).get(source["source_id"]), sha256=manifest["raw_sha256"],
            normalized_sha256=manifest["normalized_sha256"], raw_size=len(parsed.terminal.raw),
            selected_range=source["selected_range"], mapping=manifest["mapping"], commands=source["commands"],
            diagnostics=source["diagnostics"], versions=source["versions"], input_format=source["input_format"])
        record.update(container_format=source["container_format"], notices=source["notices"])
        result["sources"].append(record)
        if "display_name" in source:
            record["display_name"] = source["display_name"]
        if "collection_provenance" in source:
            record["collection_provenance"] = source["collection_provenance"]
        for scope in source["scopes"]:
            for route in scope.pop("routes"):
                for field in ("paths", "non_selected_paths"):
                    route[field] = stable(route[field])
                result["routes"].append(dict(route, **{k: scope[k] for k in IDENTITY[:3]}))
            result["scopes"].append(scope)
    for field in ("sources", "scopes", "routes"):
        result[field] = stable(result[field])
    result["snapshot_id"] = snapshot_hash(result)
    validate_snapshot(result, control=control)
    return result
