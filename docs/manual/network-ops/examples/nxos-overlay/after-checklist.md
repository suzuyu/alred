# Health Check Checklist

- Started at: 2026-08-02T14:15:00+09:00
- Completed at: 2026-08-02T14:15:31+09:00
- Change ID: HC-20260802T140000-p1234-a1b2c3
- Phase: after
- Result: PASS

## Result by Profile

| Profile | PASS | WARN | FAIL | UNKNOWN | N/A |
|---|---:|---:|---:|---:|---:|
| network-baseline-nxos | 44 | 0 | 0 | 0 | 4 |
| nxos-overlay | 13 | 0 | 0 | 0 | 2 |

## Checks

### Device: `leaf01` (192.0.2.11)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 35.0% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 43% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 1 second (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.0.2.123
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Maximum interface error counter delta is 0 (warn: 1, fail: 100)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 2 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All observed IPv4 BGP peers are established
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `vlan_operational_health`: PASS - All 2 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 1 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 2 expected overlay SVI(s) are operational
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 2/2 prefix(es) passed; receiver evidence 2/2

### Device: `leaf02` (192.0.2.12)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 32.0% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 41% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 1 second (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.0.2.123
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Maximum interface error counter delta is 0 (warn: 1, fail: 100)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 2 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All observed IPv4 BGP peers are established
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `vlan_operational_health`: PASS - All 2 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 1 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 2 expected overlay SVI(s) are operational
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 2/2 prefix(es) passed; receiver evidence 2/2

### Device: `spine01` (192.0.2.101)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 30.0% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 40% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 1 second (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.0.2.123
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Maximum interface error counter delta is 0 (warn: 1, fail: 100)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 1 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All observed IPv4 BGP peers are established
- [-] `vpc_health`: NOT_APPLICABLE - vPC is not configured

#### Profile: `nxos-overlay`

- [-] `nve_interface_health`: NOT_APPLICABLE - NVE is not configured
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [-] `type5_prefix_propagation`: NOT_APPLICABLE - No connected prefix is configured for Type-5 advertisement
