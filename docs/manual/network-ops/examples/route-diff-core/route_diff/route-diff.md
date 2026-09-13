# Route Diff

Mode: route-ad-cost-nexthop

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

全体集計: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=7 / UNCHANGED=4 / changed_count=9 / has_diff=True

## leaf01 / TENANT-A / ipv4

COMPLETE

before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=4 / UNCHANGED=1 / changed_count=6 / has_diff=True

## leaf01 / TENANT-A / ipv6

COMPLETE

before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=3 / UNCHANGED=1 / changed_count=3 / has_diff=True

## leaf02 / default / ipv4

COMPLETE

before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

## leaf02 / default / ipv6

COMPLETE

before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

## leaf03 / TENANT-A / ipv4

UNKNOWN

before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

診断: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:null,&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:159},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:159},&quot;declared\_status&quot;:null,&quot;collected\_at&quot;:null,&quot;transport&quot;:null,&quot;completion\_kind&quot;:&quot;next\_prompt&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:5,&quot;start\_byte&quot;:159,&quot;end\_byte&quot;:167},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:1,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:159,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:1,&quot;parsed\_path\_count&quot;:1},&quot;after&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;unknown&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:null,&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:115},&quot;declared\_status&quot;:null,&quot;collected\_at&quot;:null,&quot;transport&quot;:null,&quot;completion\_kind&quot;:&quot;eof\_unverified&quot;,&quot;completion\_evidence&quot;:null,&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[{&quot;code&quot;:&quot;UNSUPPORTED\_PATH&quot;,&quot;message&quot;:&quot;incomplete or unsupported path syntax&quot;,&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:4,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:98,&quot;end\_byte&quot;:115},{&quot;code&quot;:&quot;PATH\_COUNT\_MISMATCH&quot;,&quot;message&quot;:&quot;selected unicast path count does not match ubest&quot;,&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:3,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:64,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}\],&quot;observed\_prefix\_count&quot;:1,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;UNKNOWN&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;verification\_reason&quot;:&quot;SOURCE\_TERMINATOR\_OR\_ASSERTION\_MISSING&quot;,&quot;health\_eligible&quot;:false,&quot;parsed\_prefix\_count&quot;:0,&quot;parsed\_path\_count&quot;:0},&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_INCOMPLETE&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}\]}

## leaf01 / TENANT-A / ipv4 / 192.0.2.0/24

MODIFIED / AD_CHANGED

```diff
- 192.0.2.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
+ 192.0.2.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=200 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:8,&quot;end\_line&quot;:9,&quot;start\_byte&quot;:238,&quot;end\_byte&quot;:343,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:8,&quot;end\_line&quot;:9,&quot;start\_byte&quot;:237,&quot;end\_byte&quot;:342,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 192.0.2.128/25

MODIFIED / NEXTHOP_CHANGED

```diff
- 192.0.2.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
+ 192.0.2.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.2 interface=Ethernet1/2 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:13,&quot;end\_line&quot;:14,&quot;start\_byte&quot;:527,&quot;end\_byte&quot;:634,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:12,&quot;end\_line&quot;:13,&quot;start\_byte&quot;:452,&quot;end\_byte&quot;:559,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 192.0.2.64/26

MODIFIED / METRIC_CHANGED

```diff
- 192.0.2.64/26 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
+ 192.0.2.64/26 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=30
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:18,&quot;end\_line&quot;:19,&quot;start\_byte&quot;:817,&quot;end\_byte&quot;:923,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:17,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:742,&quot;end\_byte&quot;:848,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 198.51.100.0/24

REMOVED / PREFIX_REMOVED

```diff
- 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:238,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:848,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 198.51.100.128/25

MODIFIED / NEXTHOP_CHANGED, PATH_COUNT_DECREASED

```diff
- 198.51.100.128/25 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:10,&quot;end\_line&quot;:12,&quot;start\_byte&quot;:343,&quot;end\_byte&quot;:527,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:10,&quot;end\_line&quot;:11,&quot;start\_byte&quot;:342,&quot;end\_byte&quot;:452,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 203.0.113.0/24

ADDED / PREFIX_ADDED

```diff
+ 203.0.113.0/24 kind=ip next_hop_family=ipv4 address=192.0.2.1 interface=Ethernet1/1 next_hop_vrf=TENANT-A next_hop_table_family=None encapsulation=None segment_id=None tunnel_id=None asymmetric=None admin_distance=110 metric=20
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:19,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:923,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:237,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

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

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf03-before-route.txt / sha256:9033e87a093122c6c6c726244bdcabeb04a812675168e477131860c406828d45 / 取得日時: 不明

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf02-before-route.txt / sha256:5e9e3936f3c7ad7f0ec647cbbe52dd12f76f137a23325b98504ca57b9ecbd4ff / 取得日時: 不明

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf01-before-route.txt / sha256:c72c512a1d0c17a1bda1ddcf50f9547421fd52f344f49a79ab2a03d45712c513 / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf03-after-route.txt / sha256:6743ba833f0ff4b09f9227d2dab16b4c30bd7f42abbdc855b2a107c6b4a9641e / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf02-after-route.txt / sha256:6a658111f63d29e2c57ef69762ed882803505b53b8fc2f4456d92d09ca80da5f / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf01-after-route.txt / sha256:52a815f34de87ed1fe269e25d97490e0485ec37f0ebb4ddbab1013fadc597420 / 取得日時: 不明

## Policy results

{&quot;required\_routes&quot;:\[\],&quot;expected\_changes&quot;:\[\],&quot;exclusions&quot;:\[\],&quot;general\_changes&quot;:\[\]}

## Diagnostics

\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_INCOMPLETE&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}\]
