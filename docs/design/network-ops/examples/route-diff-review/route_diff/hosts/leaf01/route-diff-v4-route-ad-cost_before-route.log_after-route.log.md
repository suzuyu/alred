# leaf01 / ipv4 / route-ad-cost

レビュー用モック。正常性は未評価。

Before 6 → After 6 / A 1 / R 1 / M 2

## TENANT-A / 198.51.100.0/24 / REMOVED

変更理由: prefix 消失

- AD: 110 → なし
- Cost: 20 → なし

```diff
- 198.51.100.0/24  AD 110  Cost 20
```

## TENANT-A / 203.0.113.0/24 / ADDED

変更理由: prefix 追加

- AD: なし → 110
- Cost: なし → 20

```diff
+ 203.0.113.0/24  AD 110  Cost 20
```

## TENANT-A / 192.0.2.0/24 / MODIFIED

変更理由: AD 変更

- AD: 110 → 200
- Cost: 20 → 20

```diff
- 192.0.2.0/24  AD 110  Cost 20
+ 192.0.2.0/24  AD 200  Cost 20
```

## TENANT-A / 192.0.2.64/26 / MODIFIED

変更理由: Cost 変更

- AD: 110 → 110
- Cost: 20 → 30

```diff
- 192.0.2.64/26  AD 110  Cost 20
+ 192.0.2.64/26  AD 110  Cost 30
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
