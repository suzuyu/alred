# VNI Mapping

- Change ID: HC-20260802T140000-p1234-a1b2c3
- Phase: before
- Generated at: 2026-08-02T14:00:31+09:00
- L2VNIs: 1
- L3VNIs: 1
- Conflicts: 0
- Unknowns: 0

## L3VNI

| L3VNI | VRF | Devices | NVE states | Status |
|---:|---|---|---|---|
| 50001 | TENANT-A | leaf01, leaf02 | leaf01=Up, leaf02=Up | CONSISTENT |

## L2VNI

| L2VNI | VRF | VLAN name | Devices / VLANs | Gateway IPv4 | Gateway IPv6 | NVE states | Status |
|---:|---|---|---|---|---|---|---|
| 10010 | TENANT-A | TENANT-A-WEB | leaf01=10, leaf02=110 | ["192.0.2.1/24"] | ["2001:db8:10::1/64"] | leaf01=Up, leaf02=Up | DEVICE_VARIANT |
