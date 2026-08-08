# VNI Mapping Diff

- Change ID: HC-20260802T140000-p1234-a1b2c3
- Before phase: before
- After phase: after
- Field changes: 32
- Display rows: 17

## L2VNI 10020 — VRF TENANT-B

| Change | Field | Devices | Before | After | Status |
|---|---|---|---|---|---|
| ADDED | nve_member | leaf01, leaf02 | - | true | OBSERVED |
| ADDED | operational_state | leaf01, leaf02 | - | Up | OBSERVED |
| ADDED | replication | leaf01, leaf02 | - | UnicastBGP | OBSERVED |
| ADDED | svi.anycast_gateway | leaf01, leaf02 | - | true | OBSERVED |
| ADDED | svi.ipv4_addresses | leaf01, leaf02 | - | ["198.51.100.1/24"] | OBSERVED |
| ADDED | svi.ipv6_addresses | leaf01, leaf02 | - | [] | OBSERVED |
| ADDED | svi.ipv6_link_local | leaf01, leaf02 | - | - | OBSERVED |
| ADDED | svi.mtu | leaf01, leaf02 | - | 9216 | OBSERVED |
| ADDED | svi.vrf | leaf01, leaf02 | - | TENANT-B | OBSERVED |
| ADDED | vlan | leaf01 | - | 20 | OBSERVED |
| ADDED | vlan | leaf02 | - | 120 | OBSERVED |
| ADDED | vlan_name | leaf01, leaf02 | - | TENANT-B-APP | OBSERVED |

## L3VNI 50002 — VRF TENANT-B

| Change | Field | Devices | Before | After | Status |
|---|---|---|---|---|---|
| ADDED | bgp_processes.65000.address_families.ipv4.commands | leaf01, leaf02 | - | ["advertise l2vpn evpn"] | OBSERVED |
| ADDED | local_as | leaf01, leaf02 | - | ["65000"] | OBSERVED |
| ADDED | nve_associate_vrf | leaf01, leaf02 | - | true | OBSERVED |
| ADDED | operational_state | leaf01, leaf02 | - | Up | OBSERVED |
| ADDED | rd | leaf01, leaf02 | - | auto | OBSERVED |

## Field Source List

| Fields | Source | Verification command |
|---|---|---|
| operational_state, replication | Operational command output | `show nve vni` |
| bgp_processes.65000.address_families.ipv4.commands, local_as, nve_associate_vrf, nve_member, rd, svi.anycast_gateway, svi.ipv4_addresses, svi.ipv6_addresses, svi.ipv6_link_local, svi.mtu, svi.vrf, vlan, vlan_name | Running configuration | `show running-config` |

## Evidence Files

| Command | Device | Before evidence | After evidence |
|---|---|---|---|
| `show nve vni` | leaf01 | health/before/raw/leaf01/shows.log | health/after/raw/leaf01/shows.log |
| `show nve vni` | leaf02 | health/before/raw/leaf02/shows.log | health/after/raw/leaf02/shows.log |
| `show running-config` | leaf01 | health/before/raw/leaf01/config.txt | health/after/raw/leaf01/config.txt |
| `show running-config` | leaf02 | health/before/raw/leaf02/config.txt | health/after/raw/leaf02/config.txt |
