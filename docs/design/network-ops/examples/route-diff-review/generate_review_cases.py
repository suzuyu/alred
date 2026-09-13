"""Render hand-authored acceptance examples, not a policy evaluator or importer."""

import hashlib
import html
import json
import re


def make_cases(root, route, path, paired_lines):
    def save(name, value):
        (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def sha(raw):
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def esc(value):
        return html.escape(str(value), quote=True)

    def pre(value):
        return '<pre>' + esc(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'

    p1, p2 = path("192.0.2.1", "Ethernet1/1"), path("192.0.2.2", "Ethernet1/2")
    resource = dict(device="leaf01", vrf="TENANT-A", family="ipv4", prefix="192.0.2.64/26")

    def state(paths):
        # Protocol is retained by canonical input but outside expectation matching fields.
        return dict(prefix=resource['prefix'], paths=[{k: v for k, v in p.items() if k != "protocol"} for p in paths])

    expected_before, expected_after = state([p1]), state([dict(p1, metric=30)])
    scenarios = [
        ("matched", "予定どおりの Cost 変更", expected_before, expected_after, "MATCHED", "PASS", "expected_change", "必須条件も満たした例。この check の PASS は全体 PASS ではありません。"),
        ("mismatch", "予定外の Cost 変更", expected_before, state([dict(p1, metric=40)]), "MISMATCH", "WARN", "unexpected_change", "予定は 20 → 30、観測は 20 → 40。metric が不一致。"),
        ("not-applied", "予定した変更が未成立", expected_before, expected_before, "NOT_APPLIED", "WARN", "unexpected_change", "観測差分は UNCHANGED でも rule の結果一覧には残します。"),
        ("extra-hop", "Cost は予定どおりだが NextHop も変更", expected_before, state([dict(p2, metric=30)]), "MISMATCH", "WARN", "unexpected_change", "AD / Cost だけの一致では期待変更にしません。"),
        ("before-mismatch", "before が計画と不一致", state([dict(p1, metric=10)]), expected_after, "MISMATCH", "WARN", "unexpected_change", "after だけを照合せず、before の metric 不一致も残します。"),
        ("required-fail", "予定した削除だが必須経路違反", expected_before, None, "MATCHED", "FAIL", "regression", "この例だけ期待 after は null。required prefix 欠落は独立して FAIL。"),
        ("unverified", "申告ログでは Health 用証跡不足", expected_before, expected_after, "UNVERIFIABLE", "UNKNOWN", "collection_error", "構文は完全で観測比較可能でも user_asserted だけでは Health 判定に採用しません。"),
    ]
    expected_cases = []
    for key, title, before, after, status, health, classification, note in scenarios:
        expected_cases.append(dict(id=key, title=title, resource=resource,
            expected=dict(before=expected_before, after=None if key == 'required-fail' else expected_after),
            observed=dict(before=before, after=after), expectation_status=status,
            observation='UNCHANGED' if key == 'not-applied' else 'REMOVED' if key == 'required-fail' else 'MODIFIED',
            verification='user_asserted' if key == 'unverified' else 'verified',
            health_eligible=key != 'unverified', health_result=health, classification=classification, note=note))
        case = expected_cases[-1]
        case['expectation_rule_id'] = 'remove-required-route' if key == 'required-fail' else 'cost-20-to-30'
        case['policy'] = dict(required_routes=[dict(resource, min_paths=1)],
            expected_changes=[dict(id=case['expectation_rule_id'], reason=title, **resource, **case['expected'])])
        case['resolved_policy_sha256'] = sha(json.dumps(case['policy'], sort_keys=True, ensure_ascii=False).encode())
        case['mismatch_fields'] = {
            'mismatch': ['after.paths.metric'], 'not-applied': ['after.paths.metric'],
            'extra-hop': ['after.paths.address', 'after.paths.interface'],
            'before-mismatch': ['before.paths.metric'],
        }.get(key, [])

    p3, p4, p5 = (path(f"192.0.2.{i}", f"Ethernet1/{i}") for i in (3, 4, 5))
    ecmp_cases = []
    for key, title, before, after in [
        ('same-hop', '同じ NextHop の Cost 変更', [p1, p2], [p2, dict(p1, metric=30)]),
        ('exchange', '共通 path を残して複数 NextHop が交換', [p1, p2, p5], [p3, p4, p5]),
        ('ambiguous', '同じ NextHop に複数の属性候補', [p1, dict(p1, metric=40)], [dict(p1, metric=30), dict(p1, metric=50)]),
    ]:
        r = route('leaf01', '198.51.100.128/25', before, after, title)
        ecmp_cases.append(dict(id=key, title=title, route=r,
            pairs=[dict(before=b, after=a, common=same) for b, a, same in paired_lines(r, 'route-ad-cost-nexthop')]))

    clean = ('leaf01# show ip route vrf all\nIP Route Table for VRF "TENANT-A"\n'
             '192.0.2.64/26, ubest/mbest: 1/0\n'
             '    *via 192.0.2.1, Ethernet1/1, [110/20], 00:01:00, ospf-UNDERLAY, intra\nleaf01#\n')
    body = '\n'.join(clean.splitlines()[1:4])
    terminal_cases = []
    specs = [
        ('sgr-crlf', 'BOM / CRLF / ANSI の色指定', '\ufeff' + clean.replace('192.0.2.64/26', '\x1b[32m192.0.2.64/26\x1b[0m').replace('\n', '\r\n'), clean, 'verified', True, '既知の SGR と改行だけを解析用に整形。', ['UTF8_BOM', 'CRLF_TO_LF', 'SGR_REMOVED']),
        ('asserted', '終端のない本文を完全取得と申告', body, body, 'user_asserted', False, '構文正常。観測比較は可能、Health 用証跡は不足。', []),
        ('asserted-broken', '破損した本文を完全取得と申告', body.rsplit('    *via', 1)[0] + '    *via 192.0.2.', None, 'unknown', False, '利用者申告でも途中 path の破損を免除しない。', ['INCOMPLETE_PATH']),
        ('wrapped', 'address が terminal 幅で折り返し', clean.replace('192.0.2.1,', '192.0.\n2.1,'), None, 'unknown', False, '折り返しの復元を推測しない。', ['AMBIGUOUS_WRAP']),
        ('pager', 'ページャー表示の混入', clean.replace('    *via', '--More--\n    *via'), None, 'unknown', False, 'ページャーを消すだけでは完全取得にしない。', ['PAGER_UNSUPPORTED']),
        ('cursor', 'cursor 移動の混入', clean.replace('192.0.2.1,', '\x1b[2D192.0.2.1,'), None, 'unknown', False, '画面の再描画を復元しない。', ['CONTROL_UNSUPPORTED']),
        ('backspace', 'backspace の混入', clean.replace('192.0.2.1,', '192.0.2.9\b1,'), None, 'unknown', False, '前文字を削除して address を確定しない。', ['CONTROL_UNSUPPORTED']),
        ('bare-cr', '単独 CR の混入', clean.replace('192.0.2.1,', '192.0.2.9\r192.0.2.1,'), None, 'unknown', False, '単独 CR を改行や上書きと仮定しない。', ['CONTROL_UNSUPPORTED']),
    ]
    for key, title, raw, normalized, verification, eligible, note, transforms in specs:
        raw_bytes = raw.encode('utf-8')
        mapping, offset = [], 0
        chunks = raw_bytes.split(b'\n')
        raw_lines = [line + b'\n' for line in chunks[:-1]] + ([chunks[-1]] if chunks[-1] else [])
        for number, line in enumerate(raw_lines, 1):
            mapping.append(dict(raw_start_line=number, raw_end_line=number,
                raw_start_byte=offset, raw_end_byte=offset + len(line),
                normalized_line=number if normalized is not None else None))
            offset += len(line)
        operations = []
        # Locations of explicitly authored safe fixture transformations, not an importer.
        if key == 'sgr-crlf':
            for match in re.finditer(rb'\xef\xbb\xbf|\r\n|\x1b\[[0-9;]*m', raw_bytes):
                value = match.group()
                operations.append(dict(kind='UTF8_BOM' if value == b'\xef\xbb\xbf' else 'CRLF_TO_LF' if value == b'\r\n' else 'SGR_REMOVED',
                    raw_start_byte=match.start(), raw_end_byte=match.end()))
        diagnostics = []
        markers = {'asserted-broken': b'    *via 192.0.2.', 'wrapped': b'192.0.\n2.1', 'pager': b'--More--',
                   'cursor': b'\x1b[2D', 'backspace': b'\b', 'bare-cr': b'\r'}
        if key in markers:
            start = raw_bytes.index(markers[key])
            end = start + len(markers[key])
            diagnostics.append(dict(code=transforms[0], raw_start_byte=start, raw_end_byte=end,
                raw_start_line=raw_bytes[:start].count(b'\n') + 1,
                raw_end_line=raw_bytes[:end].count(b'\n') + 1))
        terminal_cases.append(dict(id=key, title=title, raw_text=raw, raw_sha256=sha(raw_bytes),
            input_contract=dict(host='leaf01', input_format='nxos-route-text' if key.startswith('asserted') else 'nxos-transcript',
                command_id='route_ipv4_all_vrfs', completeness='asserted' if key.startswith('asserted') else 'not_asserted'),
            expected_normalized_text=normalized, normalized_sha256=sha(normalized.encode()) if normalized is not None else None,
            parse_status='COMPLETE' if normalized is not None else 'UNKNOWN', verification=verification,
            health_eligible=eligible, expected_mapping=mapping, expected_operations=operations, expected_diagnostics=diagnostics,
            transformations_or_diagnostics=transforms, note=note))
    envelope = dict(schema_version=1, synthetic=True, kind='RouteDiffAcceptanceExamples',
        status='手作業で定義した期待値。別途実装した comparator / evaluator の受け入れテストにも使用する。',
        expectations=expected_cases, ecmp=ecmp_cases)
    save('review-cases.example.json', envelope)
    save('terminal-cases.example.json', dict(schema_version=1, synthetic=True, kind='TerminalInputExamples',
        status='UTF-8 encode で raw bytes を再現する合成 fixture。実機対応の証明ではない。', cases=terminal_cases,
        invalid_encoding_example=dict(raw_bytes_hex='6c65616630312320ff0a', expected='INPUT_VALIDATION_ERROR', exit_code=2,
            reason='不正な UTF-8 を置換して route parser へ渡さない。')))

    def visible(raw):
        return ''.join('\\r' if ch == '\r' else '\\t' if ch == '\t' else f'\\x{ord(ch):02x}' if ord(ch) < 32 and ch != '\n'
                       else '\\ufeff' if ch == '\ufeff' else ch for ch in raw)

    expected_html = []
    for c in expected_cases:
        expected_html.append(f'<article data-case="{c["id"]}"><h2>{esc(c["title"])}</h2>'
            f'<p class="result">観測 {c["observation"]} / 期待照合 {c["expectation_status"]} / この check の Health {c["health_result"]}</p>'
            f'<p>{esc(c["note"])}</p><div class="columns"><div><h3>期待 before / after</h3>{pre(c["expected"])}</div>'
            f'<div><h3>観測 before / after</h3>{pre(c["observed"])}</div></div></article>')
    ecmp_html = []
    for c in ecmp_cases:
        lines = []
        for pair in c['pairs']:
            common, b, a = pair['common'], pair['before'], pair['after']
            label = '共通 path' if common else '同じ NextHop の属性変更' if b and a else '削除群（対応未確定）' if b else '追加群（対応未確定）'
            lines.append(f'<div class="pair-label">{label}</div><div class="pair" data-common="{str(common).lower()}">'
                f'<pre class="{"same" if common else "removed" if b else "empty"}">{esc(b or "—")}</pre>'
                f'<pre class="{"same" if common else "added" if a else "empty"}">{esc(a or "—")}</pre></div>')
        ecmp_html.append(f'<article data-ecmp="{c["id"]}"><h2>{c["title"]}</h2><p>MODIFIED は 1 prefix。path の対応未確定は、route 比較の UNKNOWN ではありません。</p>{"".join(lines)}</article>')
    terminal_html = []
    for c in terminal_cases:
        eligible = '評価可能（他の profile 条件は別途確認）' if c['health_eligible'] else 'UNKNOWN / Health 用証跡不足'
        terminal_html.append(f'<article data-terminal="{c["id"]}"><h2>{c["title"]}</h2>'
            f'<p class="result">解析 {c["parse_status"]} / {c["verification"]} / Health {eligible}</p><p>{c["note"]}</p>'
            f'<div class="columns"><div><h3>元ログ（制御文字を可視化）</h3>{pre(visible(c["raw_text"]))}</div>'
            f'<div><h3>解析用 text の期待値</h3>{pre(c["expected_normalized_text"] if c["expected_normalized_text"] is not None else "未確定。行の連結や制御文字の除去で補わない。")}</div></div>'
            f'<details><summary>入力条件・hash / 行と byte 範囲</summary>{pre(dict(input_contract=c["input_contract"], raw_sha256=c["raw_sha256"], mapping=c["expected_mapping"], operations=c["expected_operations"], diagnostics=c["expected_diagnostics"]))}</details></article>')

    def selector(id_, data):
        return f'<select id="{id_}">' + ''.join(f'<option value="{c["id"]}">{esc(c["title"])}</option>' for c in data) + '</select>'

    page = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Route diff · 追加ケースレビュー</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f7f6;color:#20373d;font:15px/1.65 system-ui,sans-serif}main{max-width:1380px;margin:auto;padding:28px}a{color:#12686c}h1{font-size:28px}.notice,.result{padding:14px;background:#fff1cf;border-radius:6px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0}button,select{font:inherit;padding:10px;border:1px solid #a3bcbc;border-radius:5px;background:white;max-width:100%}button[aria-selected=true]{background:#173d40;color:white}article{background:white;padding:20px;border:1px solid #d1dddd;border-radius:8px;margin:16px 0}.columns,.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.columns>div{min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;background:#edf3f2;font:12px/1.6 monospace;margin:0;max-height:480px;overflow:auto}.removed{background:#ffe2e4}.added{background:#dcf5e4}.empty{background:#f4f6f6}.pair-label{margin-top:18px}.check{display:block;margin:15px 0}[hidden]{display:none!important}details{margin-top:16px}@media(max-width:650px){main{padding:14px}.columns{grid-template-columns:1fr}.pair{gap:4px}pre{padding:6px;font-size:11px}h1{font-size:23px}}
</style><main><a href="index.html">← 全体のレビューへ</a><h1>Route diff · 追加ケースレビュー</h1>
<p class="notice">合成入力と期待出力を切り替えるモックです。任意ログや policy を解析・評価する機能は未実装です。元の 3 host の集計とは別のケース集です。</p>
<nav class="tabs" aria-label="追加ケース"><button data-tab="expected" aria-selected="true">期待変更</button><button data-tab="ecmp" aria-selected="false">ECMP の対応</button><button data-tab="terminal" aria-selected="false">端末ログ・Health</button></nav>
'''
    page += '<section data-panel="expected"><p>期待変更と評価対象外を区別し、必須経路違反・証跡不足は免除しません。</p>' + selector('expected-case', expected_cases) + ''.join(expected_html) + '</section>'
    page += '<section data-panel="ecmp" hidden><p>左右に対応させるのは共通行と、一意な同一 NextHop の属性変更だけです。</p>' + selector('ecmp-case', ecmp_cases) + '<label class="check"><input type="checkbox" id="case-show-common">差分行以外も表示</label>' + ''.join(ecmp_html) + '</section>'
    page += '<section data-panel="terminal" hidden><p>制御文字を可視化しています。JSON の raw_text を UTF-8 encode すると元 bytes を再現できます。</p>' + selector('terminal-case', terminal_cases) + ''.join(terminal_html) + '</section>'
    page += '''<p><a href="expected-changes.example.yaml">期待変更 policy 入力案</a> / <a href="review-cases.example.json">比較・判定の期待出力</a> / <a href="terminal-cases.example.json">端末入力と mapping の期待値</a> / <a href="../../ROUTE_DIFF_DESIGN.md">設計書</a></p></main>
<script>
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('[data-tab]').forEach(t=>t.setAttribute('aria-selected',String(t===b)));
  document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.tab);
}));
for(const [id,attr] of [['expected-case','data-case'],['ecmp-case','data-ecmp'],['terminal-case','data-terminal']]){
  const select=document.getElementById(id);
  const update=()=>document.querySelectorAll('['+attr+']').forEach(c=>c.hidden=c.getAttribute(attr)!==select.value);
  select.addEventListener('change',update);update();
}
const common=document.getElementById('case-show-common');
function updateCommon(){document.querySelectorAll('[data-common="true"]').forEach(p=>{p.hidden=!common.checked;p.previousElementSibling.hidden=!common.checked;});}
common.addEventListener('change',updateCommon);updateCommon();
</script></html>'''
    (root / 'review-cases.html').write_text(page, encoding='utf-8')
