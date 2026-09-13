# Route Diff

Mode: route-ad-cost

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## leaf01 / TENANT-A / ipv6

COMPLETE

before_count=4 / after_count=4 / ADDED=0 / REMOVED=0 / MODIFIED=1 / UNCHANGED=3 / changed_count=1 / has_diff=True

## leaf01 / TENANT-A / ipv6 / 2001:db8:500::/64

MODIFIED / METRIC_CHANGED

```diff
- 2001:db8:500::/64 admin_distance=110 metric=20
+ 2001:db8:500::/64 admin_distance=110 metric=40
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:33,&quot;end\_line&quot;:34,&quot;start\_byte&quot;:1452,&quot;end\_byte&quot;:1562,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:32,&quot;end\_line&quot;:33,&quot;start\_byte&quot;:1325,&quot;end\_byte&quot;:1435,&quot;command\_id&quot;:&quot;route\_ipv6\_all\_vrfs&quot;}}

## Sources

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf01-before-route.txt / sha256:c72c512a1d0c17a1bda1ddcf50f9547421fd52f344f49a79ab2a03d45712c513 / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf01-after-route.txt / sha256:52a815f34de87ed1fe269e25d97490e0485ec37f0ebb4ddbab1013fadc597420 / 取得日時: 不明
