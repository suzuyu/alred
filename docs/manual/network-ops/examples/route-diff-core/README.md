# Route Diff 比較・オフライン出力 API の実出力例

合成ログを **実装済みの parser → Snapshot → comparator / evaluator** へ入力して生成した JSON。
手作業の期待表示である [HTML モック](../../../../design/network-ops/examples/route-diff-review/index.html)と区別する。
本番 renderer の HTML / Markdown / CSV も下記から確認できる。standalone CLI も実装済み。機種・release の実機検証結果ではない。

| ファイル | 確認する内容 |
|---|---|
| [route-snapshot-before.json](route-snapshot-before.json) | 全経路・全 path、取得 command、元行・byte、入力 hash |
| [route-snapshot-after.json](route-snapshot-after.json) | 変更後の全経路と、leaf03 の不完全な path の証跡 |
| [route-diff.json](route-diff.json) | 5 方式の差分、scope ごとの品質、部分集計、policy なしの NOT_EVALUATED |
| [route-diff-policy.json](route-diff-policy.json) | leaf01／TENANT-A／IPv4 を指定し、期待 Cost 変更と必須経路を判定 |

観測比較の完全な 4 scope は before / after 各 12 route、追加 1、削除 1。
MODIFIED は route-only / route-ad / route-ad-cost / nexthop-include / route-ad-cost-nexthop の順に
0 / 1 / 3 / 5 / 7 件。leaf03 は UNKNOWN として件数から分離し、全体は PARTIAL / exit_code 3。

policy 付き例では Cost 20 → 30 が MATCHED、必須経路も満たす。一方、同じ scope にある別 prefix の
削除・NextHop 変更は予定された変更ではないため、全体は WARN / exit_code 1。
MATCHED がネットワーク全体の PASS を意味しないことを確認できる。他 scope は NOT_SELECTED。

`RouteDiff.entries` は既定方式の変更 prefix のみを保持する。各 entry の `modes` で 5 方式を確認し、
差分のない経路は Snapshot、未成立を含む全 policy rule は `policy_results` を参照する。
raw の元ファイルは [合成 fixture](../../../../../tests/fixtures/nxos/route_diff/README.md)を使用している。

## 再生成

alred の Python 開発環境で、リポジトリのルートから実行する。

```bash
python docs/manual/network-ops/examples/route-diff-core/generate_examples.py
```

この script は上記の JSON 4 ファイルを更新する文書保守用のもの。公開 CLI の代替ではない。
CLI の保存 lifecycle / atomic publish は P5 で接続した。

オフライン出力も生成する場合は、新しい出力先を指定する。

```bash
python docs/manual/network-ops/examples/route-diff-core/generate_examples.py --report-dir /tmp/alred-route-diff-example
```

既存 directory は上書きしない。途中失敗の file は保持し、全 file が完成した場合だけ
`report-manifest.json` に比較 fingerprint と各 file の hash を記録する。公開 command の代替ではない。

package schema は [RouteSnapshot](../../../../../alred/schemas/v1/route-snapshot.schema.json)と
[RouteDiff](../../../../../alred/schemas/v1/route-diff.schema.json)、API の契約は
[設計 15](../../../../design/network-ops/ROUTE_DIFF_DESIGN.md#15-snapshot比較policy-判定の実装契約p3)を参照する。

## オフライン実出力

- [index.html](route_diff/index.html): 5 方式、差分のみ既定、ページング、元ログ全文、レビュー保存・復元。
- [checklist.md](route_diff/checklist.md): scope ごとの比較完了と 5 方式の件数。
- [route-diff.md](route_diff/route-diff.md): 全体サマリーと prefix 別差分。
- [route-diff.csv](route_diff/route-diff.csv): 既定方式の変更 9 prefix と UNKNOWN 1 scope。
- [route-diff.json](route_diff/route-diff.json): renderer version 付きの正式比較結果。
- [leaf01 の正規化表示](route_diff/hosts/leaf01/route-diff.html)。
- [leaf01 の全文表示](route_diff/hosts/leaf01/route-diff-raw.html)。

いずれも本番 API で生成した合成ログの結果。HTML は保存済み結果の閲覧用で、任意ログを
ブラウザから取り込んで比較する機能は持たない。network / server / CDN は不要。
全体サマリーの長い証跡は初期状態で折りたたむ。UNKNOWN の対象・理由は見出しに残し、
Sources は入力ごと、versions / fingerprint と Policy はそれぞれの見出しから展開できる。
実装 API は [設計 16](../../../../design/network-ops/ROUTE_DIFF_DESIGN.md#16-オフライン-renderer-apip4)を参照する。

## CLI からの生成

同じ合成ログを CLI で比較する場合は、リポジトリのルートから次を実行する。

```bash
python alred.py route-diff-nxos --source-map docs/design/network-ops/examples/route-diff-review/source-map.example.yaml --output-dir /tmp/alred-route-cli-example
```

leaf03 の UNKNOWN を含むため終了 code は `3`。完了したレポートと元 bytes / Snapshot は保存される。
`--output-dir` は既存の非空 directory を拒否するため、再実行時は新しい path を指定する。
