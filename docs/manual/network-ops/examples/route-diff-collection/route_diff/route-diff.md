# Route Diff

Mode: route-ad-cost-nexthop

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

全体集計: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=3 / changed_count=1 / has_diff=True

## leaf01 / EMPTY-VRF / ipv6

COMPLETE

before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

## leaf01 / TENANT-A / ipv4

COMPLETE

before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=1 / changed_count=1 / has_diff=True

## leaf02 / EMPTY-VRF / ipv6

COMPLETE

before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

## leaf02 / TENANT-A / ipv4

COMPLETE

before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

## leaf03 / EMPTY-VRF / ipv6

UNKNOWN

before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

診断: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ipv6 route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:34,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:974,&quot;end\_byte&quot;:1006},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:33,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:974},&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:34,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:974,&quot;end\_byte&quot;:1006},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:39,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1147},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:39,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:1147},&quot;declared\_status&quot;:&quot;OK&quot;,&quot;collected\_at&quot;:&quot;2026-09-13T10:00:00+09:00&quot;,&quot;transport&quot;:&quot;ssh&quot;,&quot;completion\_kind&quot;:&quot;next\_collect\_header&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:0,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:&quot;closed\_section&quot;,&quot;empty\_evidence&quot;:{&quot;heading&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:35,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1045,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;legends&quot;:\[{&quot;text&quot;:&quot;&\#x27;\*&\#x27; denotes best ucast next-hop&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:36,&quot;end\_line&quot;:36,&quot;start\_byte&quot;:1045,&quot;end\_byte&quot;:1077}},{&quot;text&quot;:&quot;&\#x27;\*\*&\#x27; denotes best mcast next-hop&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:37,&quot;end\_line&quot;:37,&quot;start\_byte&quot;:1077,&quot;end\_byte&quot;:1110}},{&quot;text&quot;:&quot;&\#x27;\[x/y\]&\#x27; denotes \[preference/metric\]&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:38,&quot;end\_line&quot;:38,&quot;start\_byte&quot;:1110,&quot;end\_byte&quot;:1146}}\],&quot;command\_end&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288},&quot;vrf\_end&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288}},&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:38,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1146,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:0,&quot;parsed\_path\_count&quot;:0},&quot;after&quot;:null,&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]}

## leaf03 / TENANT-A / ipv4

UNKNOWN

before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

診断: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:18,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:379,&quot;end\_byte&quot;:409},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:14,&quot;end\_line&quot;:17,&quot;start\_byte&quot;:266,&quot;end\_byte&quot;:379},&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:18,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:379,&quot;end\_byte&quot;:409},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:19,&quot;end\_line&quot;:29,&quot;start\_byte&quot;:409,&quot;end\_byte&quot;:859},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:14,&quot;end\_line&quot;:29,&quot;start\_byte&quot;:266,&quot;end\_byte&quot;:859},&quot;declared\_status&quot;:&quot;OK&quot;,&quot;collected\_at&quot;:&quot;2026-09-13T10:00:00+09:00&quot;,&quot;transport&quot;:&quot;ssh&quot;,&quot;completion\_kind&quot;:&quot;next\_collect\_header&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:1006},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:2,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:19,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:409,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:2,&quot;parsed\_path\_count&quot;:2},&quot;after&quot;:null,&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]}

## leaf01 / TENANT-A / ipv4 / 198.51.100.0/24

MODIFIED / NEXTHOP_CHANGED, SEGMENT_ID_CHANGED

```diff
- 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=203.0.113.1 interface=None next_hop_vrf=default next_hop_table_family=None encapsulation=vxlan segment_id=19001 tunnel_id=0xcb007101 asymmetric=True admin_distance=200 metric=0
+ 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=203.0.113.1 interface=None next_hop_vrf=default next_hop_table_family=None encapsulation=vxlan segment_id=19002 tunnel_id=0xcb007101 asymmetric=True admin_distance=200 metric=0
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:27,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:687,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:27,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:687,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## Sources

- before: docs/design/network-ops/examples/route-diff-input-fix/directory-case/before/device-a.log / sha256:57eac36d6cab4e16a9022fd37b2f523f1241b36d0bf995e16b44a927882859e3 / 取得日時: 不明

- before: docs/design/network-ops/examples/route-diff-input-fix/directory-case/before/device-b.log / sha256:70882ef14c5021f497fa911836c915c84a0031fff914c0b230c607e5a4205359 / 取得日時: 不明

- before: docs/design/network-ops/examples/route-diff-input-fix/directory-case/before/device-c.log / sha256:878bdf481c8378ddddb496f1908d51449259d21f4bc3378a9f344b28e8d0eb0b / 取得日時: 不明

- after: docs/design/network-ops/examples/route-diff-input-fix/directory-case/after/post-leaf01.txt / sha256:dc7145d9cab3d744b4d22dc1ec96261139484609c794d5552d533568d513a25b / 取得日時: 不明

- after: docs/design/network-ops/examples/route-diff-input-fix/directory-case/after/device-b-renamed.log / sha256:70882ef14c5021f497fa911836c915c84a0031fff914c0b230c607e5a4205359 / 取得日時: 不明

## Policy results

{&quot;required\_routes&quot;:\[\],&quot;expected\_changes&quot;:\[\],&quot;exclusions&quot;:\[\],&quot;general\_changes&quot;:\[\]}

## Diagnostics

\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null},{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]
