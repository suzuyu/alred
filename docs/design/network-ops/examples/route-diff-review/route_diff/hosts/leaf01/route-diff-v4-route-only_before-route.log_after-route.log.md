# leaf01 / ipv4 / route-only

レビュー用モック。正常性は未評価。

Before 6 → After 6 / A 1 / R 1 / M 0

## TENANT-A / 198.51.100.0/24 / REMOVED

変更理由: prefix 消失


```diff
- 198.51.100.0/24
```

## TENANT-A / 203.0.113.0/24 / ADDED

変更理由: prefix 追加


```diff
+ 203.0.113.0/24
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
