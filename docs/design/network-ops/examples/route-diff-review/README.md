# Route Diff レビュー資料

状態: **設計レビュー用 UI モック。比較 API は別途実装済み**。
[設計案](../../ROUTE_DIFF_DESIGN.md)と入力・出力を並べて確認するための合成 sample。
任意ログの解析、機器への接続、Health operation の変更は行わない。

## 開き方

[index.html](index.html) をブラウザで直接開く。Web server や外部通信は不要。
ファイルリンクで開けない環境では、checkout 内の同じ HTML をブラウザへドラッグして開く。

- **左右比較（正規化）**: 差分行のみを既定表示。host、VRF、AF、5 比較方式、prefix 検索を選び、「差分行以外も表示」を ON にすると共通行も表示する。
- **変更理由・差分移動**: Cost / AD / NextHop / ECMP などの理由を表示し、理由や変更種別で絞り込む。「前の差分」「次の差分」で現在の条件に該当する変更 prefix を移動する。
- **ログ全文比較**: 元ログを行番号付きで左右に表示する。経路差分 / 文字列差分の着色、全文検索、スクロール同期を切り替える。
- **全体サマリー・出力**: route 数と方式ごとの件数を比較し、各出力 file を開く。
- **完全性**: 取得状態、観測 / 解析 prefix 数、解析 path 数、未解析行数の期待表示を確認する。合成入力に対する値であり、production parser の実行結果ではない。
- **入力ログ・コマンド案**: 架空の before / after ログと、未実装 CLI の提案を確認する。
- **設計の確認事項**: 合意事項と、今回レビューする選択肢を確認する。

## レビュー順

1. leaf01 / IPv4 を選び、`route-only` → `route-ad` → `route-ad-cost` → `route-ad-cost-nexthop` の順に切り替える。
2. `192.0.2.64/26` の Cost 20 → 30 が Cost 込み方式でのみ差分になることを確認する。
3. `198.51.100.128/25` を検索し、既定では共通 ECMP path が隠れ、「差分行以外も表示」を ON にすると表示されることを確認する。
4. IPv6 を選び、link-local interface と参照先 VRF の変更を確認する。
5. leaf02 は全方式で差分なし、leaf03 / IPv4 は UNKNOWN として表示されることを確認する。
6. 全体サマリー、ファイル名、Markdown、JSON / CSV の列をレビューする。
7. [ログ全文比較](index.html#raw)で、経過時間や空白も残った元ログを確認する。
8. 着色を「ログ文字列の差分」へ変え、経路としては同一でも文字列の変化が赤 / 緑になることを確認する。
9. 正規化 view で変更理由を `Cost 変更` にし、`AD / Cost / NextHop / path 数` の summary と差分移動を確認する。
10. 「元ログの該当位置へ」で左右の証跡位置へ移動し、「正規化比較へ戻る」で filter と位置が保持されることを確認する。
11. 全体サマリーの件数をクリックし、対応する host / VRF / AF / mode / change type で正規化 view が開くことを確認する。

leaf03 には IPv6 入力がない。IPv6 は未対象であり、差分なしや正常性 PASS ではない。
すべての sample は観測のみで、必須 prefix などの正常性判定は含めていない。

## 件数の期待値

比較可能な 4 scope について、before / after は各 12 route。
同じ prefix でも device / VRF が違えば別 route と数える。

| 方式 | ADDED | REMOVED | MODIFIED | UNCHANGED |
|---|---:|---:|---:|---:|
| route-only | 1 | 1 | 0 | 11 |
| route-ad | 1 | 1 | 1 | 10 |
| route-ad-cost | 1 | 1 | 3 | 8 |
| nexthop-include | 1 | 1 | 5 | 6 |
| route-ad-cost-nexthop | 1 | 1 | 7 | 4 |

比較不能な leaf03 / TENANT-A / IPv4 は上記件数に含めず、UNKNOWN 1 scope と表示する。
Cost を含む 2 方式を追加し、既定表示 / JSON / CSV の主差分は `route-ad-cost-nexthop` とする。
Cost は `[110/20]` の `20`、JSON field は `metric`。旧 `nexthop-include` は Cost を無視する。
route-only の MODIFIED は常に 0。next-hop だけの変化は route-only では差分なしになる。

## 入力案と出力案

- 入力: [複数 host の source map](source-map.example.yaml)、[before ログ](inputs/leaf01/before-route.log)、[after ログ](inputs/leaf01/after-route.log)
- 全体: [checklist.md](route_diff/checklist.md)、[route-diff.md](route_diff/route-diff.md)、[JSON](route_diff/route-diff.json)、[CSV](route_diff/route-diff.csv)
- ホスト別: [leaf01 正規化比較](route_diff/hosts/leaf01/route-diff.html)、[leaf01 差分のみ](route_diff/hosts/leaf01/route-diff-diffonly.html)（どちらも差分行のみが既定）
- ログ全文: [leaf01 ログ全文比較](route_diff/hosts/leaf01/route-diff-raw.html)、[leaf03 途中出力の左右比較](route_diff/hosts/leaf03/route-diff-raw.html)
- 異常例: [leaf03 正規化比較](route_diff/hosts/leaf03/route-diff.html)、[途中で切れた after](inputs/leaf03/after-route.log)
- 追加の入力例: [重要経路 policy](route-policy.example.yaml)、[レビュー記録](review-record.example.json)

各 host directory に IPv4 / IPv6 × 5 方式の Markdown も配置している。
`before-route.log` / `after-route.log` は拡張子を含めて filename に残す。
正規化 view は比較対象の値だけを表示する。ログ全文 view は元の行順・表記・行番号を保持する。
経路基準の着色は 5 方式に従い、文字列だけの違いは淡い青灰色 `≈` とする。
文字列基準では経過時間などの違いも赤 / 緑になるが、経路件数と正常性判定は変わらない。
全文検索は行を隠さず枠で強調する。スクロール同期は位置の割合を合わせるもので、prefix の行合わせではない。
正規化 view からのジャンプでは比例同期を OFF にし、before / after の各証跡位置を個別に表示する。
経路が存在しない側は、不存在を確認する VRF section を強調する。

## 今回の実装範囲

このモックでは、変更理由 / field summary、理由・変更種別 filter、差分移動、サマリー連携、
元ログへの往復、比較完全性の期待表示を動作確認できる。
JSON / CSV / Markdown も同じ合成 model の変更理由を持つ。

以下は [設計案 10](../../ROUTE_DIFF_DESIGN.md#10-追加の推奨仕様合意済み一部実装)と入力例までで、モック UI には未実装:

- 100 prefix / page のページング、ログ全文の仮想スクロール、1 万 / 10 万 / 100 万 route の性能検証。
- prefix 完全一致 / CIDR 包含検索。現在の検索 UI は従来の文字列検索。
- 時点ラベルの編集。現在は before / after、取得日時は不明と表示する。
- レビュー記録の保存 / 読み込み UI、重要経路 policy evaluator。review-record は架空の記録例で、Health 判定や承認ではない。

追加の UI script は [review_interactions.js](review_interactions.js)を HTML へ埋め込むため、出力 HTML 単独で開ける。

## 再生成

この directory の sample と HTML を再生成する場合:

```bash
python docs/design/network-ops/examples/route-diff-review/generate_mock.py
```

`generate_mock.py` は手作業で定義した合成シナリオを描画するだけの文書用 script。
raw input を解析して期待結果を検証する parser test ではない。実装の受け入れには別途、
sanitized NX-OS fixture と production parser / comparator のテストが必要。
script に対応 release の認定や未知入力を解釈する機能はない。

レビューで修正する場合は、設計書の R1–R10、sample、実装状況を同じ作業で更新する。

## 優先項目と端末ログの追加レビュー

[追加ケースの UI](review-cases.html)で次を切り替える。既存 3 host の件数とは別のケース集。

- 期待変更: Cost 20 → 30 / 40 / 未変更、before 不一致、NextHop の予定外変更、予定した削除でも必須経路 FAIL、申告ログで UNKNOWN。
- ECMP の対応: 共通 path と同一 NextHop の属性変更だけを対応させる。複数交換・曖昧な候補は左右別の削除群 / 追加群にする。既定は差分行のみ。
- 端末ログ・Health: BOM / CRLF / SGR の整形、利用者申告、折り返し / ページャー / cursor / backspace / 単独 CR を比較する。

[期待変更 policy 入力](expected-changes.example.yaml)、[比較・判定の期待出力](review-cases.example.json)、
[端末入力・mapping の期待値](terminal-cases.example.json)を同梱する。
JSON の `raw_text` は escape 表記で元の制御文字を保持し、UTF-8 encode により raw bytes を再現できる。
UI は制御文字を実行せず可視化する。JSON には decode error の byte 入力例も含む。

期待変更照合と terminal adapter の結果は手作業で定義した期待値。UI の選択はケースを切り替えるもので、
YAML や任意ログの解析は実装していない。既存 importer の挙動も変更していない。
一方、既存モックの Markdown / HTML の path 対応は、一意な同一 NextHop だけを並べる規則へ更新した。
`generate_mock.py` から `generate_review_cases.py` も呼び出すため、通常の再生成で追加資料も更新される。

## 初回リリースの準備

[実装計画](../../../../implementation/ROUTE_DIFF_IMPLEMENTATION_PLAN.md)で作業順と受け入れ条件を管理する。
CLI・オフライン出力・Health 統合を先行し、Web UI は他の alred 機能も含めてリリース後に検討する。
[Schema レビュー資料](contracts/README.md)に 5 種の構造 schema と、UNCHANGED を含む Snapshot 例を追加した。
Policy / Source Map / RouteSnapshot / RouteDiff / RouteDiffReview の package 登録、入力・Snapshot・比較・policy 判定・renderer API は実装済み。
[API 実出力例](../../../../manual/network-ops/examples/route-diff-core/README.md)は合成ログを実際に解析して生成する。
このモック自体は引き続き手作業の期待 model を表示する。standalone CLI は実装済み。Health 接続、release 別の詳細 route fixture、性能検証は未完了。
