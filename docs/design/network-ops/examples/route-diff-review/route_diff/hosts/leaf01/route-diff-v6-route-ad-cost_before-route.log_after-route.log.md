# leaf01 / ipv6 / route-ad-cost

レビュー用モック。正常性は未評価。

Before 4 → After 4 / A 0 / R 0 / M 1

## TENANT-A / 2001:db8:500::/64 / MODIFIED

変更理由: Cost 変更

- AD: 110 → 110
- Cost: 20 → 40

```diff
- 2001:db8:500::/64  AD 110  Cost 20
+ 2001:db8:500::/64  AD 110  Cost 40
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
