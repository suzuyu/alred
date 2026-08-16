# Health Check Checklist

- Started at: 2026-08-16T10:15:00+09:00
- Completed at: 2026-08-16T10:15:31+09:00
- Duration: 00:00:31 (31 seconds)
- Change ID: CHG-2026-00123
- Phase: after
- Result: PASS

## Result by Profile

| Profile | PASS | WARN | FAIL | UNKNOWN | N/A |
|---|---:|---:|---:|---:|---:|
| network-baseline-nxos | 136 | 0 | 0 | 0 | 24 |
| nxos-overlay | 50 | 0 | 0 | 0 | 2 |

## Checks

### Device: `adc-bgrt0101` (192.168.129.101)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-bgrt0101
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [-] `port_channel_health`: NOT_APPLICABLE - Port-channel is not configured
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [-] `vpc_health`: NOT_APPLICABLE - vPC is not configured

### Device: `adc-bgrt0102` (192.168.129.102)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-bgrt0102
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [-] `port_channel_health`: NOT_APPLICABLE - Port-channel is not configured
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [-] `vpc_health`: NOT_APPLICABLE - vPC is not configured

### Device: `adc-lfsw0101` (192.168.129.81)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-lfsw0101
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `nve_peer_regression`: PASS - All observed NVE peers are up
- [x] `nve_vni_health`: PASS - All observed NVE VNIs are up
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 12/12 prefix(es) passed; receiver evidence 24/24
- [x] `vlan_operational_health`: PASS - All 8 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 3 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 9 expected overlay SVI(s) are operational
- [x] `vpc_function_expectation`: PASS - vpc is configured (expectation: optional)
- [x] `vtep_function_expectation`: PASS - vtep is configured (expectation: required)

### Device: `adc-lfsw0102` (192.168.129.82)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-lfsw0102
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `nve_peer_regression`: PASS - All observed NVE peers are up
- [x] `nve_vni_health`: PASS - All observed NVE VNIs are up
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 12/12 prefix(es) passed; receiver evidence 24/24
- [x] `vlan_operational_health`: PASS - All 8 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 3 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 9 expected overlay SVI(s) are operational
- [x] `vpc_function_expectation`: PASS - vpc is configured (expectation: optional)
- [x] `vtep_function_expectation`: PASS - vtep is configured (expectation: required)

### Device: `adc-lfsw0103` (192.168.129.83)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-lfsw0103
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `nve_peer_regression`: PASS - All observed NVE peers are up
- [x] `nve_vni_health`: PASS - All observed NVE VNIs are up
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 12/12 prefix(es) passed; receiver evidence 24/24
- [x] `vlan_operational_health`: PASS - All 9 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 3 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 9 expected overlay SVI(s) are operational
- [x] `vpc_function_expectation`: PASS - vpc is configured (expectation: optional)
- [x] `vtep_function_expectation`: PASS - vtep is configured (expectation: required)

### Device: `adc-lfsw0104` (192.168.129.84)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-lfsw0104
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [x] `port_channel_health`: PASS - Port-channels and members are bundled
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [x] `vpc_health`: PASS - vPC peer and consistency are healthy

#### Profile: `nxos-overlay`

- [x] `nve_interface_health`: PASS - NVE interface state is Up
- [x] `evpn_bgp_health`: PASS - All observed EVPN BGP peers are established
- [x] `nve_peer_regression`: PASS - All observed NVE peers are up
- [x] `nve_vni_health`: PASS - All observed NVE VNIs are up
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [x] `type5_prefix_propagation`: PASS - Type-5 propagation: 12/12 prefix(es) passed; receiver evidence 24/24
- [x] `vlan_operational_health`: PASS - All 9 expected overlay VLAN(s) are operational
- [x] `vrf_operational_health`: PASS - All 3 expected overlay VRF(s) are operational
- [x] `svi_operational_health`: PASS - All 9 expected overlay SVI(s) are operational
- [x] `vpc_function_expectation`: PASS - vpc is configured (expectation: optional)
- [x] `vtep_function_expectation`: PASS - vtep is configured (expectation: required)

### Device: `adc-spsw0101` (192.168.129.90)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-spsw0101
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [-] `port_channel_health`: NOT_APPLICABLE - Port-channel is not configured
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [-] `vpc_health`: NOT_APPLICABLE - vPC is not configured

#### Profile: `nxos-overlay`

- [x] `evpn_rr_neighbor_health`: PASS - All observed EVPN BGP peers are established
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [-] `type5_prefix_propagation`: NOT_APPLICABLE - No connected prefix is configured for Type-5 advertisement
- [x] `evpn_rr_config_health`: PASS - evpn-route-reflector is configured (expectation: required)

### Device: `adc-spsw0102` (192.168.129.89)

#### Profile: `network-baseline-nxos`

- [x] `collection_complete`: PASS - All required command outputs were parsed
- [x] `system_identity`: PASS - NX-OS 10.5(4) model Nexus9000 C9300v was identified
- [x] `hostname_identity`: PASS - Reported hostname matches inventory hostname: adc-spsw0102
- [x] `cpu_utilization`: PASS - CPU one_minute_percent is 24% (warning threshold: 80%)
- [x] `memory_utilization`: PASS - Memory utilization is 44% (warn: 85%, fail: 95%)
- [-] `environment_health`: NOT_APPLICABLE - Hardware environment sensors are unavailable on this platform
- [x] `clock_health`: PASS - Device clock offset is 0 seconds (warn: 60, fail: 300)
- [x] `ntp_health`: PASS - NTP is synchronized to 192.168.129.254
- [x] `interface_health`: PASS - Admin-up interfaces are operationally up
- [x] `interface_error_health`: PASS - Interface error counter total is 0
- [x] `interface_utilization`: PASS - Peak interface utilization is 20.00% on Eth1/1 (output)
- [-] `port_channel_health`: NOT_APPLICABLE - Port-channel is not configured
- [x] `reload_pending`: PASS - No reload-pending configuration exists
- [x] `running_config_diff`: PASS - Running-config matches startup-config
- [x] `logging_health`: PASS - No abnormal log records were observed in the selected time range
- [x] `ipv4_route_count`: PASS - IPv4 route counts were collected for 3 VRFs
- [x] `ospf_neighbor_health`: PASS - All observed OSPF neighbors are FULL
- [x] `bgp_ipv4_health`: PASS - All statically configured IPv4 BGP peers are established
- [-] `bgp_dynamic_neighbor_health`: NOT_APPLICABLE - No dynamic BGP neighbor range is configured
- [-] `vpc_health`: NOT_APPLICABLE - vPC is not configured

#### Profile: `nxos-overlay`

- [x] `evpn_rr_neighbor_health`: PASS - All observed EVPN BGP peers are established
- [x] `evpn_route_health`: PASS - Observed EVPN route count is 16
- [-] `type5_prefix_propagation`: NOT_APPLICABLE - No connected prefix is configured for Type-5 advertisement
- [x] `evpn_rr_config_health`: PASS - evpn-route-reflector is configured (expectation: required)

## Unexecuted Hosts

| Host | Platform | Topology Role | Profile | Result | Reason Code | Reason |
|---|---|---|---|---|---|---|
| adc-bgrt0101 | nxos | network-functions | nxos-overlay | NOT_APPLICABLE | PROFILE_ROLE_EXCLUDED | Topology role is outside the nxos-overlay scope. |
| adc-bgrt0102 | nxos | network-functions | nxos-overlay | NOT_APPLICABLE | PROFILE_ROLE_EXCLUDED | Topology role is outside the nxos-overlay scope. |
