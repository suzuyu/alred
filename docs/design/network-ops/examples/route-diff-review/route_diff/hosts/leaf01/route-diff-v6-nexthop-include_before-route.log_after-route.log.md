# leaf01 / ipv6 / nexthop-include

レビュー用モック。正常性は未評価。

Before 4 → After 4 / A 0 / R 0 / M 2

## TENANT-A / 2001:db8:100::/64 / MODIFIED

変更理由: NextHop 変更

- AD: 110 → 110
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 1 → 1

```diff
- 2001:db8:100::/64  AD 110  via fe80::1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv6  kind ip
+ 2001:db8:100::/64  AD 110  via fe80::1  dev Ethernet1/2  vrf TENANT-A  nh-af ipv6  kind ip
```

## TENANT-A / 2001:db8:300::/64 / MODIFIED

変更理由: NextHop 変更

- AD: 200 → 200
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 1 → 1

```diff
- 2001:db8:300::/64  AD 200  via ::ffff:192.0.2.1  dev —  vrf default  nh-af ipv6  kind ip
+ 2001:db8:300::/64  AD 200  via ::ffff:192.0.2.1  dev —  vrf TENANT-B  nh-af ipv6  kind ip
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
