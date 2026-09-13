# leaf01 / ipv4 / nexthop-include

レビュー用モック。正常性は未評価。

Before 6 → After 6 / A 1 / R 1 / M 3

## TENANT-A / 198.51.100.0/24 / REMOVED

変更理由: prefix 消失

- AD: 110 → なし
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 1 → 0

```diff
- 198.51.100.0/24  AD 110  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
```

## TENANT-A / 203.0.113.0/24 / ADDED

変更理由: prefix 追加

- AD: なし → 110
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 0 → 1

```diff
+ 203.0.113.0/24  AD 110  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
```

## TENANT-A / 192.0.2.0/24 / MODIFIED

変更理由: AD 変更

- AD: 110 → 200
- NextHop: 変更なし
- path 数: 1 → 1

```diff
- 192.0.2.0/24  AD 110  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
+ 192.0.2.0/24  AD 200  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
```

## TENANT-A / 198.51.100.128/25 / MODIFIED

変更理由: NextHop 変更 / ECMP path 減少

- AD: 110 → 110
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 2 → 1

```diff
- 198.51.100.128/25  AD 110  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
```

## TENANT-A / 192.0.2.128/25 / MODIFIED

変更理由: NextHop 変更

- AD: 110 → 110
- NextHop: 変更あり（詳細は path 行を参照）
- path 数: 1 → 1

```diff
- 192.0.2.128/25  AD 110  via 192.0.2.1  dev Ethernet1/1  vrf TENANT-A  nh-af ipv4  kind ip
+ 192.0.2.128/25  AD 110  via 192.0.2.2  dev Ethernet1/2  vrf TENANT-A  nh-af ipv4  kind ip
```

[before](../../../inputs/leaf01/before-route.log) / [after](../../../inputs/leaf01/after-route.log)
