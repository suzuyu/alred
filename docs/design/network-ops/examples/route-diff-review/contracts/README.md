# Route Diff の schema レビュー資料

状態: **このディレクトリの Policy / Source Map は package schema の複製、その他は UI 設計用 Draft 2020-12**。
[正本の設計 12](../../../ROUTE_DIFF_DESIGN.md#12-初回リリース範囲と共通処理の契約)に沿って構造を検証する。
入力検証・parser・Snapshot・comparator / evaluator・renderer は Python API として実装。standalone CLI は実装済み。Health 接続も実装済み。
正式な [RouteSnapshot schema](../../../../../../alred/schemas/v1/route-snapshot.schema.json)と
[RouteDiff schema](../../../../../../alred/schemas/v1/route-diff.schema.json)、
[RouteDiffReview schema](../../../../../../alred/schemas/v1/route-diff-review.schema.json)は package に登録済み。
ここにある同名 schema はモック用の旧 Draft であり、本番検証には使用しない。
[実出力例](../../../../../manual/network-ops/examples/route-diff-core/README.md)は正式 schema で検証する。

| schema | 対応する例 | 主な責務 |
|---|---|---|
| [RouteDiffSourceMap](route-diff-source-map.schema.json) | [source map](../source-map.example.yaml) | host、before / after の source、形式、採用区間、完全取得の申告 |
| [RouteDiffPolicy](route-diff-policy.schema.json) | [必須経路](../route-policy.example.yaml)、[期待変更](../expected-changes.example.yaml) | 必須条件、除外、期待する全 path tuple |
| [RouteSnapshot](route-snapshot.schema.json) | [before](route-snapshot-before.example.json)、[after](route-snapshot-after.example.json) | 各時点の全 route、source、品質、version |
| [RouteDiff](route-diff.schema.json) | [観測差分](../route_diff/route-diff.json) | 比較条件、5 方式の summary、差分 entries、診断 |
| [RouteDiffReview](route-diff-review.schema.json) | [確認記録](../review-record.example.json) | 比較 fingerprint、resource、mode、レビュー状態 |

Policy / Source Map は `alred/schemas/v1/` を正本としてここへ複製する。その他の `$defs` は設計資料の生成元で共通定義する。
Source Map の command ID は default／指定／全 VRF に対応する。指定 VRF の ID では `vrf` が必須で、
他の ID では指定しない。取得範囲と本文形式の規則は
[設計 14.4](../../../ROUTE_DIFF_DESIGN.md#144-default-vrf指定-vrf-の-command-対応)を参照する。
出力 file は内部参照だけで検証できる。
YAML 入力は未知 field を拒否する。JSON 出力の同じ major の追加 field は reader で許容する設計とする。
`required_routes.min_paths` は初期入力で明示必須。path の AD / Cost を省略して期待変更の wildcard にはしない。
Snapshot 例は leaf01 / leaf02 の全 route（各時点 12 route）を含み、UNCHANGED も残す。
leaf03 の未知 scope はこの Snapshot 例の対象外。全体 RouteDiff の部分集計例とは対象が異なることを明記する。

## 構造検証と未実装の境界

構造検証では必須 field、型、enum、非負 AD / Cost、正整数 min_paths、hash 形式、
時刻形式、開始 / 終了行指定の組を確認する。
このディレクトリの RouteDiff schema はモックの観測 envelope を対象とする。
package schema では terminal mapping、全 policy rule 結果、品質と件数の構造も検証する。

次は schema の成功だけでは保証しない。Policy の IP / AF / kind、重複・競合・対象 scope と、Source Map の重複区間は domain validator で検証済み。
Snapshot / RouteDiff の domain validator では source 範囲、hash、品質、件数、policy 結果の整合も検証する。
以下を機能全体の受け入れ条件とし、Health 接続は後続段階に残す。レビュー取り込みは P4、CLI の保存 lifecycle は P5 で実装した:

- prefix / address の妥当性、canonical network、AF / kind / interface の整合。
- duplicate resource / path / rule id、source 区間の重複、開始行と終了行の大小。
- source bytes と hash / evidence の対応、外部 path の扱い、Snapshot の同一性。
- 全 mode の件数式、UNKNOWN の件数 null、policy の対象外 / exclusion 競合。
- before / after の完全一致照合、必須経路判定、Health 適格性。
- review fingerprint / entry key の照合、改ざん・別比較のレビュー取り込み拒否。

## 再生成・確認

```bash
python docs/design/network-ops/examples/route-diff-review/generate_mock.py
python -m pytest tests/test_route_diff_contract_examples.py tests/test_route_diff_review_mock.py tests/test_documentation.py
```

[generate_contracts.py](../generate_contracts.py)は設計資料だけを生成する。
正式 Review schema と domain validator は P4 で接続した。登録済みの 5 schema は source / wheel / ネイティブ形式の API で検証する。
