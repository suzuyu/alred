# Route Diff

Mode: nexthop-include

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## leaf01 / TENANT-A / ipv4

COMPLETE

before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=3 / UNCHANGED=2 / changed_count=5 / has_diff=True

## leaf01 / TENANT-A / ipv4 / 192.0.2.0/24

MODIFIED / AD_CHANGED

```diff
- 192.0.2.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
+ 192.0.2.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=200
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:8,&quot;end\_line&quot;:9,&quot;start\_byte&quot;:238,&quot;end\_byte&quot;:343,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:8,&quot;end\_line&quot;:9,&quot;start\_byte&quot;:237,&quot;end\_byte&quot;:342,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 192.0.2.128/25

MODIFIED / NEXTHOP_CHANGED

```diff
- 192.0.2.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
+ 192.0.2.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.2 interface=Ethernet1/2 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:13,&quot;end\_line&quot;:14,&quot;start\_byte&quot;:527,&quot;end\_byte&quot;:634,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:12,&quot;end\_line&quot;:13,&quot;start\_byte&quot;:452,&quot;end\_byte&quot;:559,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 198.51.100.0/24

REMOVED / PREFIX_REMOVED

```diff
- 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:238,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:848,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 198.51.100.128/25

MODIFIED / NEXTHOP_CHANGED, PATH_COUNT_DECREASED

```diff
- 198.51.100.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:10,&quot;end\_line&quot;:12,&quot;start\_byte&quot;:343,&quot;end\_byte&quot;:527,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:10,&quot;end\_line&quot;:11,&quot;start\_byte&quot;:342,&quot;end\_byte&quot;:452,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 203.0.113.0/24

ADDED / PREFIX_ADDED

```diff
+ 203.0.113.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:19,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:923,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:237,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## Sources

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf01-before-route.txt / sha256:c72c512a1d0c17a1bda1ddcf50f9547421fd52f344f49a79ab2a03d45712c513 / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf01-after-route.txt / sha256:52a815f34de87ed1fe269e25d97490e0485ec37f0ebb4ddbab1013fadc597420 / 取得日時: 不明
