# Route Diff checklist

チェックは比較完了を意味します。差分なしや Health PASS を意味しません。

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## 全体集計

route-only: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=0 / UNCHANGED=11 / changed_count=2 / has_diff=True

route-ad: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=1 / UNCHANGED=10 / changed_count=3 / has_diff=True

route-ad-cost: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=3 / UNCHANGED=8 / changed_count=5 / has_diff=True

nexthop-include: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=5 / UNCHANGED=6 / changed_count=7 / has_diff=True

route-ad-cost-nexthop: before_count=12 / after_count=12 / ADDED=1 / REMOVED=1 / MODIFIED=7 / UNCHANGED=4 / changed_count=9 / has_diff=True

- [x] leaf01 / TENANT-A / ipv4 — COMPLETE

  route-only: before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=0 / UNCHANGED=5 / changed_count=2 / has_diff=True

  route-ad: before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=1 / UNCHANGED=4 / changed_count=3 / has_diff=True

  route-ad-cost: before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=2 / UNCHANGED=3 / changed_count=4 / has_diff=True

  nexthop-include: before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=3 / UNCHANGED=2 / changed_count=5 / has_diff=True

  route-ad-cost-nexthop: before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=4 / UNCHANGED=1 / changed_count=6 / has_diff=True

- [x] leaf01 / TENANT-A / ipv6 — COMPLETE

  route-only: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=4 / changed_count=0 / has_diff=False

  route-ad: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=4 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=3 / changed_count=1 / has_diff=True

  nexthop-include: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=2 / UNCHANGED=2 / changed_count=2 / has_diff=True

  route-ad-cost-nexthop: before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=3 / UNCHANGED=1 / changed_count=3 / has_diff=True

- [x] leaf02 / default / ipv4 — COMPLETE

  route-only: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  nexthop-include: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad-cost-nexthop: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

- [x] leaf02 / default / ipv6 — COMPLETE

  route-only: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad-cost: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  nexthop-include: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

  route-ad-cost-nexthop: before_count=1 / after_count=1 / ADDED=0 / REMOVED=0 / MODIFIED=0 / UNCHANGED=1 / changed_count=0 / has_diff=False

- [ ] leaf03 / TENANT-A / ipv4 — UNKNOWN

  route-only: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  nexthop-include: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  route-ad-cost-nexthop: before_count=null / after_count=null / ADDED=null / REMOVED=null / MODIFIED=null / UNCHANGED=null / changed_count=null / has_diff=null

  理由: {&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;before&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;verified&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:null,&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:159},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:159},&quot;declared\_status&quot;:null,&quot;collected\_at&quot;:null,&quot;transport&quot;:null,&quot;completion\_kind&quot;:&quot;next\_prompt&quot;,&quot;completion\_evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:5,&quot;start\_byte&quot;:159,&quot;end\_byte&quot;:167},&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[\],&quot;observed\_prefix\_count&quot;:1,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:159,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;COMPLETE&quot;,&quot;coverage&quot;:&quot;COMPLETE&quot;,&quot;verification\_reason&quot;:null,&quot;health\_eligible&quot;:true,&quot;parsed\_prefix\_count&quot;:1,&quot;parsed\_path\_count&quot;:1},&quot;after&quot;:{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;verification&quot;:&quot;unknown&quot;,&quot;command\_scope&quot;:{&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;vrf&quot;:null,&quot;command&quot;:&quot;show ip route vrf all&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;acquisition\_evidence&quot;:{&quot;header&quot;:null,&quot;prompt&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:1,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:30},&quot;body&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115},&quot;block&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:1,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:0,&quot;end\_byte&quot;:115},&quot;declared\_status&quot;:null,&quot;collected\_at&quot;:null,&quot;transport&quot;:null,&quot;completion\_kind&quot;:&quot;eof\_unverified&quot;,&quot;completion\_evidence&quot;:null,&quot;manifest\_record\_sha256&quot;:null}},&quot;diagnostics&quot;:\[{&quot;code&quot;:&quot;UNSUPPORTED\_PATH&quot;,&quot;message&quot;:&quot;incomplete or unsupported path syntax&quot;,&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:4,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:98,&quot;end\_byte&quot;:115},{&quot;code&quot;:&quot;PATH\_COUNT\_MISMATCH&quot;,&quot;message&quot;:&quot;selected unicast path count does not match ubest&quot;,&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:3,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:64,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}\],&quot;observed\_prefix\_count&quot;:1,&quot;explicit\_empty&quot;:false,&quot;empty\_basis&quot;:null,&quot;empty\_evidence&quot;:null,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;parse\_status&quot;:&quot;UNKNOWN&quot;,&quot;coverage&quot;:&quot;UNKNOWN&quot;,&quot;verification\_reason&quot;:&quot;SOURCE\_TERMINATOR\_OR\_ASSERTION\_MISSING&quot;,&quot;health\_eligible&quot;:false,&quot;parsed\_prefix\_count&quot;:0,&quot;parsed\_path\_count&quot;:0},&quot;modes&quot;:{&quot;route-only&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;nexthop-include&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null},&quot;route-ad-cost-nexthop&quot;:{&quot;before\_count&quot;:null,&quot;after\_count&quot;:null,&quot;ADDED&quot;:null,&quot;REMOVED&quot;:null,&quot;MODIFIED&quot;:null,&quot;UNCHANGED&quot;:null,&quot;changed\_count&quot;:null,&quot;has\_diff&quot;:null}},&quot;diagnostics&quot;:\[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_INCOMPLETE&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}\]}

診断: \[{&quot;device&quot;:&quot;leaf03&quot;,&quot;vrf&quot;:&quot;TENANT-A&quot;,&quot;family&quot;:&quot;ipv4&quot;,&quot;side&quot;:&quot;after&quot;,&quot;code&quot;:&quot;SCOPE\_INCOMPLETE&quot;,&quot;evidence&quot;:{&quot;source\_id&quot;:&quot;leaf03&quot;,&quot;start\_line&quot;:2,&quot;end\_line&quot;:4,&quot;start\_byte&quot;:30,&quot;end\_byte&quot;:115,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}\]
