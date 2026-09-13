# 全体収集ログ・複数ホストの実出力例

[HTML を開く](route_diff/index.html)。合成ログを本番 parser / comparator / renderer で処理した出力。
実機から取得したログや、設計モックの固定表示ではない。

- leaf01: HMM を保持し、VXLAN の segment_id 変更を NextHop 2 方式で検出する。
- leaf02: before / after の file 名が異なるが、同じホストとして比較する。差分なし。
- leaf03: after が未取得のため IPv4 / IPv6 が UNKNOWN。全経路削除としない。
- 全体は PARTIAL、COMPLETE 4 scope / UNKNOWN 2 scope、MODIFIED 1 prefix。
- 「ログ全文比較」は対象 route command 区間が既定。「入力ログ全体」で管理行と他 command も確認できる。

入力は [directory の合成例](../../../../design/network-ops/examples/route-diff-input-fix/directory-case/README.md)。
本サンプルは API から生成し、directory 探索の CLI 試験は `tests/test_route_diff_collection_fix.py` で別途確認する。

再生成は既存の出力先を避けて実行する。

```bash
PYTHONPATH=. python docs/manual/network-ops/examples/route-diff-collection/generate_examples.py \
  --report-dir /tmp/route-collection-example
```

元 bytes は HTML の Sources とダウンロード機能から確認できる。全生成物の hash は
[report-manifest.json](route_diff/report-manifest.json)で追跡する。
