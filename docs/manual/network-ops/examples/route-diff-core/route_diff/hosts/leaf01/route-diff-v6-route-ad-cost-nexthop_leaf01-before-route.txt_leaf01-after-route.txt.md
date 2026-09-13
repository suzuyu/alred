# Route Diff

Mode: route-ad-cost-nexthop

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## leaf01 / TENANT-A / ipv6

COMPLETE

before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=3 / UNCHANGED=1 / changed_count=3 / has_diff=True

## leaf01 / TENANT-A / ipv6 / 2001:db8:100::/64

MODIFIED / NEXTHOP_CHANGED

```diff
- 2001:db8:100::/64 kind=ip next_hop_family=ipv6 address=fe80::1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
+ 2001:db8:100::/64 kind=ip next_hop_family=ipv6 address=fe80::1 interface=Ethernet1/2 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:27,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:1068,&quot;end\_byte&quot;:1176,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:26,&quot;end\_line&quot;:27,&quot;start\_byte&quot;:993,&quot;end\_byte&quot;:1101,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv6 / 2001:db8:300::/64

MODIFIED / NEXTHOP_CHANGED

```diff
- 2001:db8:300::/64 kind=ip next_hop_family=ipv6 address=::ffff:c000:201 interface=None next_hop_vrf=default next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=200 metric=20
+ 2001:db8:300::/64 kind=ip next_hop_family=ipv6 address=::ffff:c000:201 interface=None next_hop_vrf=TENANT-B next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=200 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:31,&quot;end\_line&quot;:32,&quot;start\_byte&quot;:1341,&quot;end\_byte&quot;:1452,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:31,&quot;start\_byte&quot;:1213,&quot;end\_byte&quot;:1325,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv6 / 2001:db8:500::/64

MODIFIED / METRIC_CHANGED

```diff
- 2001:db8:500::/64 kind=ip next_hop_family=ipv6 address=fe80::5 interface=Ethernet1/5 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
+ 2001:db8:500::/64 kind=ip next_hop_family=ipv6 address=fe80::5 interface=Ethernet1/5 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=40
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:33,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:1452,&quot;end\_byte&quot;:1562,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:32,&quot;end\_line&quot;:33,&quot;start\_byte&quot;:1325,&quot;end\_byte&quot;:1435,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;}}

## Sources

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf01-before-route.txt / sha256:c72c512a1d0c17a1bda1ddcf50f9547421fd52f344f49a79ab2a03d45712c513 / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf01-after-route.txt / sha256:52a815f34de87ed1fe269e25d97490e0485ec37f0ebb4ddbab1013fadc597420 / 取得日時: 不明
