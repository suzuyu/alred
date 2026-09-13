# Route Diff

Mode: route-only

Coverage: PARTIAL / Evaluation: NOT_EVALUATED

## leaf01 / TENANT-A / ipv4

COMPLETE

before_count=6 / after_count=6 / ADDED=1 / REMOVED=1 / MODIFIED=0 / UNCHANGED=5 / changed_count=2 / has_diff=True

## leaf01 / TENANT-A / ipv4 / 198.51.100.0/24

REMOVED / PREFIX_REMOVED

```diff
- 198.51.100.0/24 
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:238,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:18,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:848,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## leaf01 / TENANT-A / ipv4 / 203.0.113.0/24

ADDED / PREFIX_ADDED

```diff
+ 203.0.113.0/24 
```

証跡: {&quot;before&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:5,&quot;end\_line&quot;:19,&quot;start\_byte&quot;:96,&quot;end\_byte&quot;:923,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;},&quot;after&quot;:{&quot;source\_id&quot;:&quot;leaf01&quot;,&quot;start\_line&quot;:6,&quot;end\_line&quot;:7,&quot;start\_byte&quot;:130,&quot;end\_byte&quot;:237,&quot;command\_id&quot;:&quot;route\_ipv4\_all\_vrfs&quot;}}

## Sources

- before: tests/fixtures/nxos/route\_diff/synthetic/leaf01-before-route.txt / sha256:c72c512a1d0c17a1bda1ddcf50f9547421fd52f344f49a79ab2a03d45712c513 / 取得日時: 不明

- after: tests/fixtures/nxos/route\_diff/synthetic/leaf01-after-route.txt / sha256:52a815f34de87ed1fe269e25d97490e0485ec37f0ebb4ddbab1013fadc597420 / 取得日時: 不明
