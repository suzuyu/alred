# VNI Mapping Diff

- Change ID: HC-20260802T140000-p1234-a1b2c3
- Before phase: before
- After phase: after
- Changes: 22

| Change | Type | VNI | VRF | Device | Field | Before | After | Status |
|---|---|---:|---|---|---|---|---|---|
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | nve_member | - | true | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | operational_state | - | Up | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | replication | - | UnicastBGP | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.anycast_gateway | - | true | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.ipv4_addresses | - | ["198.51.100.1/24"] | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.ipv6_addresses | - | [] | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.ipv6_link_local | - | - | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.mtu | - | 9216 | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | svi.vrf | - | TENANT-A | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | vlan | - | 20 | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf01 | vlan_name | - | TENANT-A-APP | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | nve_member | - | true | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | operational_state | - | Up | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | replication | - | UnicastBGP | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.anycast_gateway | - | true | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.ipv4_addresses | - | ["198.51.100.1/24"] | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.ipv6_addresses | - | [] | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.ipv6_link_local | - | - | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.mtu | - | 9216 | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | svi.vrf | - | TENANT-A | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | vlan | - | 120 | OBSERVED |
| ADDED | L2VNI | 10020 | TENANT-A | leaf02 | vlan_name | - | TENANT-A-APP | OBSERVED |
