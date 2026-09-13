# Route Diff Checklist — レビュー用モック

合成ログの観測差分。正常性は未評価。checkbox は比較完了を示す。

A = ADDED、R = REMOVED、M = MODIFIED。route-only の M は常に 0。

| 比較完了 | Device | VRF | AF | Before → After | Prefix のみ | Prefix + AD | Prefix + AD + Cost | Prefix + AD + NextHop | Prefix + AD + Cost + NextHop | 差分 |
|---|---|---|---|---|---|---|---|---|---|---|
| [x] | leaf01 | TENANT-A | ipv4 | 6 → 6 | A 1 / R 1 / M 0 | A 1 / R 1 / M 1 | A 1 / R 1 / M 2 | A 1 / R 1 / M 3 | A 1 / R 1 / M 4 | あり |
| [x] | leaf01 | TENANT-A | ipv6 | 4 → 4 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 1 | A 0 / R 0 / M 2 | A 0 / R 0 / M 3 | あり |
| [x] | leaf02 | default | ipv4 | 1 → 1 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | なし |
| [x] | leaf02 | default | ipv6 | 1 → 1 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | A 0 / R 0 / M 0 | なし |
| [ ] | leaf03 | TENANT-A | ipv4 | 不明 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 比較不能 |

比較可能 4 scope、UNKNOWN 1 scope。件数は比較可能 scope のみの部分集計。

- [ ] leaf03 / TENANT-A / ipv4: after が途中出力。REMOVED として計上しない。

[全体差分](route-diff.md)
