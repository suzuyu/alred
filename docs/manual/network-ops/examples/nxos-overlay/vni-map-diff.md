# VNI Mapping Diff

- Change ID: CHG-2026-00123
- Before phase: before
- After phase: after
- Field changes: 52
- Display rows: 14

## L2VNI 10100 — VRF tenant1-vpc1

| Change | Field | Devices | Before | After | Status |
|---|---|---|---|---|---|
| ADDED | nve_member | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | true | OBSERVED |
| ADDED | operational_state | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | Up | OBSERVED |
| ADDED | replication | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | UnicastBGP | OBSERVED |
| ADDED | svi.admin_enabled | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | true | OBSERVED |
| ADDED | svi.anycast_gateway | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | true | OBSERVED |
| ADDED | svi.ipv4_addresses | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | ["172.16.0.254/24"] | OBSERVED |
| ADDED | svi.ipv6_addresses | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | ["fd21:0:0:1::1/64"] | OBSERVED |
| ADDED | svi.ipv6_link_local | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | fe80::1 | OBSERVED |
| ADDED | svi.ipv6_nd_suppress_ra | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | true | OBSERVED |
| ADDED | svi.mtu | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | 9216 | OBSERVED |
| ADDED | svi.vrf | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | tenant1-vpc1 | OBSERVED |
| ADDED | vlan | adc-lfsw0101, adc-lfsw0102 | - | 100 | OBSERVED |
| ADDED | vlan | adc-lfsw0103, adc-lfsw0104 | - | 10 | OBSERVED |
| ADDED | vlan_name | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | - | tenant1-vpc1-server-seg1 | OBSERVED |

## Field Source List

| Fields | Source | Verification command |
|---|---|---|
| operational_state, replication | Operational command output | `show nve vni` |
| nve_member, svi.admin_enabled, svi.anycast_gateway, svi.ipv4_addresses, svi.ipv6_addresses, svi.ipv6_link_local, svi.ipv6_nd_suppress_ra, svi.mtu, svi.vrf, vlan, vlan_name | Running configuration | `show running-config` |

## Evidence Files

| Command | Device | Before evidence | After evidence |
|---|---|---|---|
| `show nve vni` | adc-lfsw0101 | synthetic/before/adc-lfsw0101/nve_vni.txt | synthetic/after/adc-lfsw0101/nve_vni.txt |
| `show nve vni` | adc-lfsw0102 | synthetic/before/adc-lfsw0102/nve_vni.txt | synthetic/after/adc-lfsw0102/nve_vni.txt |
| `show nve vni` | adc-lfsw0103 | synthetic/before/adc-lfsw0103/nve_vni.txt | synthetic/after/adc-lfsw0103/nve_vni.txt |
| `show nve vni` | adc-lfsw0104 | synthetic/before/adc-lfsw0104/nve_vni.txt | synthetic/after/adc-lfsw0104/nve_vni.txt |
| `show running-config` | adc-lfsw0101 | synthetic/before/adc-lfsw0101/running_config.txt | synthetic/after/adc-lfsw0101/running_config.txt |
| `show running-config` | adc-lfsw0102 | synthetic/before/adc-lfsw0102/running_config.txt | synthetic/after/adc-lfsw0102/running_config.txt |
| `show running-config` | adc-lfsw0103 | synthetic/before/adc-lfsw0103/running_config.txt | synthetic/after/adc-lfsw0103/running_config.txt |
| `show running-config` | adc-lfsw0104 | synthetic/before/adc-lfsw0104/running_config.txt | synthetic/after/adc-lfsw0104/running_config.txt |
