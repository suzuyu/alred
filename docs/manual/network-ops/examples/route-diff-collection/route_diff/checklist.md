# Route Diff checklist

チェックは比較完了を意味します。差分なしや Health PASS を意味しません。

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## 全体集計

route-only: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=4 / changed_count=0 / has_diff=False

route-ad: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=4 / changed_count=0 / has_diff=False

route-ad-cost: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=4 / changed_count=0 / has_diff=False

nexthop-include: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=3 / changed_count=1 / has_diff=True

route-ad-cost-nexthop: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=3 / changed_count=1 / has_diff=True

- [x] leaf01 / EMPTY-VRF / ipv6 — COMPLETE

  route-only: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  nexthop-include: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad-cost-nexthop: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

- [x] leaf01 / TENANT-A / ipv4 — COMPLETE

  route-only: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  route-ad: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  nexthop-include: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=1 / changed_count=1 / has_diff=True

  route-ad-cost-nexthop: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=1 / changed_count=1 / has_diff=True

- [x] leaf02 / EMPTY-VRF / ipv6 — COMPLETE

  route-only: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  nexthop-include: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

  route-ad-cost-nexthop: before_count=0 / after_count=0 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=0 / changed_count=0 / has_diff=False

- [x] leaf02 / TENANT-A / ipv4 — COMPLETE

  route-only: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  route-ad: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  nexthop-include: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

  route-ad-cost-nexthop: before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=2 / changed_count=0 / has_diff=False

- [ ] leaf03 / EMPTY-VRF / ipv6 — UNKNOWN

  route-only: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  nexthop-include: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost-nexthop: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  理由: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ipv6 route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:34,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:974,&quot;end\_byte&quot;:1006},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:33,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:974},&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:34,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:974,&quot;end\_byte&quot;:1006},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:39,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1147},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:39,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:1147},&quot;declared\_status&quot;:&quot;OK&quot;,&quot;collected\_at&quot;:&quot;2026-09-13T10:00:00+09:00&quot;,&quot;transport&quot;:&quot;ssh&quot;,&quot;completion\_kind&quot;:&quot;next\_collect\_header&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:0,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:&quot;closed\_section&quot;,&quot;empty\_evidence&quot;:{&quot;heading&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:35,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1045,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;legends&quot;:\[{&quot;text&quot;:&quot;&\#x27;\*&\#x27; denotes best ucast next-hop&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:36,&quot;end\_line&quot;:36,&quot;start\_byte&quot;:1045,&quot;end\_byte&quot;:1077}},{&quot;text&quot;:&quot;&\#x27;\*\*&\#x27; denotes best mcast next-hop&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:37,&quot;end\_line&quot;:37,&quot;start\_byte&quot;:1077,&quot;end\_byte&quot;:1110}},{&quot;text&quot;:&quot;&\#x27;\[x/y\]&\#x27; denotes \[preference/metric\]&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:38,&quot;end\_line&quot;:38,&quot;start\_byte&quot;:1110,&quot;end\_byte&quot;:1146}}\],&quot;command\_end&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288},&quot;vrf\_end&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:40,&quot;end\_line&quot;:44,&quot;start\_byte&quot;:1147,&quot;end\_byte&quot;:1288}},&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:35,&quot;end\_line&quot;:38,&quot;start\_byte&quot;:1006,&quot;end\_byte&quot;:1146,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:0,&quot;parsed\_path\_count&quot;:0},&quot;after&quot;:null,&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]}

- [ ] leaf03 / TENANT-A / ipv4 — UNKNOWN

  route-only: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  nexthop-include: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost-nexthop: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  理由: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:18,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:379,&quot;end\_byte&quot;:409},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:14,&quot;end\_line&quot;:17,&quot;start\_byte&quot;:266,&quot;end\_byte&quot;:379},&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:18,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:379,&quot;end\_byte&quot;:409},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:19,&quot;end\_line&quot;:29,&quot;start\_byte&quot;:409,&quot;end\_byte&quot;:859},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:14,&quot;end\_line&quot;:29,&quot;start\_byte&quot;:266,&quot;end\_byte&quot;:859},&quot;declared\_status&quot;:&quot;OK&quot;,&quot;collected\_at&quot;:&quot;2026-09-13T10:00:00+09:00&quot;,&quot;transport&quot;:&quot;ssh&quot;,&quot;completion\_kind&quot;:&quot;next\_collect\_header&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:30,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:859,&quot;end\_byte&quot;:1006},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:2,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:19,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:409,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:2,&quot;parsed\_path\_count&quot;:2},&quot;after&quot;:null,&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]}

診断: \[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;EMPTY-VRF&quot;,&quot;family&quot;:&quot;ipv6&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null},{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_MISSING&quot;,&quot;evidence&quot;:null}\]
