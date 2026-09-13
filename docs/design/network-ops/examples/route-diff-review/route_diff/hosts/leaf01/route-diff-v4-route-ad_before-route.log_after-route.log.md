# leaf01 / ipv4 / route-ad

レビュー用モック。正常性は未評価。

Before 6 → After 6 / A 1 / R 1 / M 1

## TENANT-A / 198.51.100.0/24 / REMOVED

変更理由: prefix 消失

- AD: 110 → なし

```diff
- 198.51.100.0/24  AD 110
```

## TENANT-A / 203.0.113.0/24 / ADDED

変更理由: prefix 追加

- AD: なし → 110

```diff
+ 203.0.113.0/24  AD 110
```

## TENANT-A / 192.0.2.0/24 / MODIFIED

変更理由: AD 変更

- AD: 110 → 200

```diff
- 192.0.2.0/24  AD 110
+ 192.0.2.0/24  AD 200
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
