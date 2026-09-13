# 複数ログ directory 入力の設計例

**設計時の期待値・実装後の回帰試験で確認済み**。[修正設計 3.5](../../../ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#35-複数機器ログの-directory-入力)を参照。
親 directory の合成ログを架空のホストへ展開したもので、実機ログではない。

| ホスト | before | after | 期待する扱い |
|---|---|---|---|
| leaf01 | [device-a.log](before/device-a.log) | [post-leaf01.txt](after/post-leaf01.txt) | 名前が違っても対応。segment_id 変更を検出 |
| leaf02 | [device-b.log](before/device-b.log) | [device-b-renamed.log](after/device-b-renamed.log) | 名前が違っても対応。差分なし |
| leaf03 | [device-c.log](before/device-c.log) | 未取得 | IPv4 / IPv6 とも UNKNOWN。全経路削除にはしない |

[期待値 JSON](expected.json)は設計用で、正式な製品出力 schema ではない。
全体は PARTIAL、終了 code 3、COMPLETE は 4 scope、UNKNOWN は 2 scope。
leaf01 の NextHop を含む 2 方式で 1 prefix が MODIFIED。

次の command で directory 入力の比較を実行できる。

```bash
python alred.py route-diff-nxos \
  --before docs/design/network-ops/examples/route-diff-input-fix/directory-case/before \
  --after docs/design/network-ops/examples/route-diff-input-fix/directory-case/after \
  --input-format nxos-transcript \
  --output-dir /tmp/alred-route-directory-review/route_diff
```

この例の file はすべて直下にある。子 directory を含む場合は `--recursive` を追加する。
同じホストの AF 分割・重複拒否・再帰探索も F19–F22 の回帰試験で確認した。
