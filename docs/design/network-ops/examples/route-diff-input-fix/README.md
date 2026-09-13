# 統合収集ログの修正設計・入出力レビュー

**設計レビュー用の固定期待値・実装後の回帰試験で確認済み**。[修正設計](../../ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md)の合成例。
実機ログを複製・匿名化した fixture ではなく、問題となった grammar を架空の値で組み立てたもの。
この directory の JSON / HTML は設計時の期待値とモックを保持している。
実装済み renderer の出力は [マニュアルのサンプル](../../../../manual/network-ops/examples/route-diff-collection/README.md)を参照する。
`expected.json` の `implementation_status` は設計作成時の状態であり、現在の実装状況ではない。

## 確認するファイル

| 入出力 | 内容 |
|---|---|
| [before.txt](before.txt) | 非 route 2 command、HMM 1 prefix、VXLAN 1 prefix、IPv6 の空 VRF |
| [after.txt](after.txt) | segment_id だけを 19001 から 19002 に変更 |
| [after-incomplete.txt](after-incomplete.txt) | 最後の非 route command の直前で切断。IPv6 command の終端を失う |
| [expected.json](expected.json) | 設計用の独立期待値。正式な RouteDiff schema の出力ではない |
| [review.html](review.html) | 期待される件数、VXLAN の左右表示、証跡と UNKNOWN、ログ表示範囲の切替案 |

`review.html` は静的な設計モック。ログの読み込み・解析はせず、外部通信も行わない。
既存の production HTML サンプルや今回の利用者ログの解析結果と混同しない。
第 5 節で「対象 route command 区間のみ / 入力ログ全体」を切り替えられる。
合成入力の固定表示であり、検索・区間解析・文字列 diff の実装ではない。

複数ホストの [directory 入力例](directory-case/README.md)では、異なる file 名の対応と片側欠落を確認する。

## 期待値

| 比較方式 | before / after | ADDED | REMOVED | MODIFIED | UNCHANGED |
|---|---:|---:|---:|---:|---:|
| Prefix | 2 / 2 | 0 | 0 | 0 | 2 |
| Prefix + AD | 2 / 2 | 0 | 0 | 0 | 2 |
| Prefix + AD + Cost | 2 / 2 | 0 | 0 | 0 | 2 |
| Prefix + AD + NextHop | 2 / 2 | 0 | 0 | 1 | 1 |
| Prefix + AD + Cost + NextHop | 2 / 2 | 0 | 0 | 1 | 1 |

COMPLETE は 2 scope（IPv4 の TENANT-A と IPv6 の EMPTY-VRF）。IPv6 は before / after 0 件。
HMM は unchanged、VXLAN は `SEGMENT_ID_CHANGED`。Policy 未指定なので完全比較の終了 code は 0。

不完全な after を使った場合は IPv6 が UNKNOWN で code 3。IPv4 の比較は完了し、全体は PARTIAL。
IPv6 の件数は null とし、正常空の 0 件に置き換えない。COMMAND_LIST に残った未実行の非 route command は
対象外の未完了として記録するが、IPv4 を UNKNOWN にしない。

## 実装後の確認 command

次の command で期待値と同じ結果を確認できる。
既存の出力先は使わず、新しい directory を指定する。

```bash
python alred.py route-diff-nxos \
  --before docs/design/network-ops/examples/route-diff-input-fix/before.txt \
  --after docs/design/network-ops/examples/route-diff-input-fix/after.txt \
  --input-format nxos-transcript \
  --output-dir /tmp/alred-route-input-fix-review/route_diff
```

設計例の追加時点では製品 code を変更せず、その後の実装・受入結果を [実装計画](../../../../implementation/ROUTE_DIFF_IMPLEMENTATION_PLAN.md)へ記録した。
