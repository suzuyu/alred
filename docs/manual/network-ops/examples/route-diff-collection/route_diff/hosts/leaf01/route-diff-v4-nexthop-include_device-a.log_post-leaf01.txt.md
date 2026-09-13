# Route Diff

Mode: nexthop-include

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## leaf01 / TENANT-A / ipv4

COMPLETE

before_count=2 / after_count=2 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=1 / changed_count=1 / has_diff=True

## leaf01 / TENANT-A / ipv4 / 198.51.100.0/24

MODIFIED / NEXTHOP_CHANGED, SEGMENT_ID_CHANGED

```diff
- 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=203.0.113.1 interface=None next_hop_vrf=default next_hop_table_family=None encapsulation=vxlan segment_id=19001 tunnel_id=0xcb007101 asymmetric=True admin_distance=200
+ 198.51.100.0/24 kind=ip next_hop_family=ipv4 address=203.0.113.1 interface=None next_hop_vrf=default next_hop_table_family=None encapsulation=vxlan segment_id=19002 tunnel_id=0xcb007101 asymmetric=True admin_distance=200
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:27,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:687,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:27,&quot;end\_line&quot;:28,&quot;start\_byte&quot;:687,&quot;end\_byte&quot;:858,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## Sources

- before: docs/design/network-ops/examples/route-diff-input-fix/directory-case/before/device-a.log / sha256:57eac36d6cab4e16a9022fd37b2f523f1241b36d0bf995e16b44a927882859e3 / 取得日時: 不明

- after: docs/design/network-ops/examples/route-diff-input-fix/directory-case/after/post-leaf01.txt / sha256:dc7145d9cab3d744b4d22dc1ec96261139484609c794d5552d533568d513a25b / 取得日時: 不明
