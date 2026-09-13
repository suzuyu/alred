# Route Diff — レビュー用モック

方式: `route-ad-cost-nexthop`。観測のみ、正常性は未評価。

| 比較完了 | Device | VRF | AF | Before → After | Prefix のみ | Prefix + AD | Prefix + AD + Cost | Prefix + AD + NextHop | Prefix + AD + Cost + NextHop | 差分 |
|---|---|---|---|---|---|---|---|---|---|---|
| [x] | leaf01 | TENANT-A | ipv4 | 6 → 6 | A 1 / R 1 / M 0 | A 1 / R 1 / M 1 | A 1 / R 1 / M 2 | A 1 / R 1 / M 3 | A 1 / R 1 / M 4 | あり |
| [x] | leaf01 | TENANT-A | ipv6 | 4 → 4 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 1 | A 0 / R 0 / M 2 | A 0 / R 0 / M 3 | あり |
| [x] | leaf02 | default | ipv4 | 1 → 1 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | なし |
| [x] | leaf02 | default | ipv6 | 1 → 1 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | なし |
| [ ] | leaf03 | TENANT-A | ipv4 | 不明 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 比較不能 |

比較不能 1 scope を除く部分集計。1 prefix の複数変更も MODIFIED 1 route。

| Device | VRF | AF | Prefix | 変更 | 変更理由 | 内容 | 証跡 |
|---|---|---|---|---|---|---|---|
| leaf01 | TENANT-A | ipv4 | 198.51.100.0/24 | REMOVED | prefix 消失 | prefix が消失 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv4 | 203.0.113.0/24 | ADDED | prefix 追加 | prefix が追加 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv4 | 192.0.2.0/24 | MODIFIED | AD 変更 | AD 110 → 200 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv4 | 198.51.100.128/25 | MODIFIED | NextHop 変更 / ECMP path 減少 | ECMP 2 → 1。共通 path は差分のみ表示で隠す | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv4 | 192.0.2.128/25 | MODIFIED | NextHop 変更 | next-hop と interface が変更 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv6 | 2001:db8:100::/64 | MODIFIED | NextHop 変更 | 同じ link-local address でも interface 変更を検出 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv6 | 2001:db8:300::/64 | MODIFIED | NextHop 変更 | IPv4-mapped IPv6 を保持し、参照先 VRF の変更を検出 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv4 | 192.0.2.64/26 | MODIFIED | Cost 変更 | Cost のみ 20 → 30。[110/20] → [110/30] | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |
| leaf01 | TENANT-A | ipv6 | 2001:db8:500::/64 | MODIFIED | Cost 変更 | IPv6 の Cost のみ 20 → 40 | [before](../inputs/leaf01/before-route.log) / [after](../inputs/leaf01/after-route.log) |

## 比較不能

after の出力が path 行の途中で終了。prefix 消失として数えない

## 成果物

[JSON](route-diff.json) / [CSV](route-diff.csv) / [Checklist](checklist.md)
