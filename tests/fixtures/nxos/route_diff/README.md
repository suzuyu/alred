# Route Diff parser fixture

`synthetic/` は [レビュー用入力](../../../../docs/design/network-ops/examples/route-diff-review/README.md)を基にした架空ログ。
実際の parser に入力して期待値を検証するが、特定 model / release の検証済み証拠ではない。
NX-OS 10.4(5)M / 10.5(4) / 10.6(4)M の詳細 route の匿名化済み取得ログは引き続き不足している。

| Source | AF ごとの期待 prefix 数 | 品質 |
|---|---|---|
| leaf01 before / after | IPv4 6、IPv6 4 | COMPLETE |
| leaf02 before / after | IPv4 1、IPv6 1 | COMPLETE |
| leaf03 before | IPv4 1 | COMPLETE |
| leaf03 after | IPv4 の heading 1、解析完了 prefix 0 | UNKNOWN、途中 path |
| default-vrf | IPv4 1、IPv6 1 | COMPLETE、VRF 指定なしの command |
| specific-vrf | IPv4 1、IPv6 1 | COMPLETE、`vrf TENANT-A` の command |

末尾改行、元行・byte offset を保持して使用する。marker や path を変えた異常系は pytest の parameterization で生成する。
default／指定 VRF の fixture は command の取得範囲確認用に作成した合成ログ。
`tests/test_route_diff_commands.py` で parser `1.1` の AF／VRF 照合・command 重複・本文形式を検証する。
