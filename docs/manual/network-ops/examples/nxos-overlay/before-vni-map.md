# VNI Mapping

- Change ID: CHG-2026-00123
- Phase: before
- Generated at: 2026-08-16T10:00:00+09:00
- L2VNIs: 5
- L3VNIs: 3
- Conflicts: 0
- Unknowns: 0

## L3VNI

| L3VNI | VRF | Devices | NVE states | Status |
|---:|---|---|---|---|
| 9001 | controller-vpc1 | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | CONSISTENT |
| 19001 | tenant1-vpc1 | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | CONSISTENT |
| 29001 | tenant2-vpc1 | adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | CONSISTENT |

## L2VNI

| L2VNI | VRF | VLAN name | Devices / VLANs | Gateway IPv4 | Gateway IPv6 | IPv6 link-local | NVE states | Status |
|---:|---|---|---|---|---|---|---|---|
| 100 | controller-vpc1 | controller-vpc1-seg1 | adc-lfsw0101=2001, adc-lfsw0102=2001, adc-lfsw0103=2001, adc-lfsw0104=2001 | ["100.64.0.254/24"] | ["fd12:0:0:1::1/64"] | fe80::1 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | CONSISTENT |
| 10101 | tenant1-vpc1 | tenant1-vpc1-server-seg2 | adc-lfsw0103=11, adc-lfsw0104=11 | ["172.16.1.254/24"] | ["fd21:0:0:2::1/64"] | fe80::1 | adc-lfsw0103=Up, adc-lfsw0104=Up | CONSISTENT |
| 10103 | tenant1-vpc1 | tenant1-vpc1-k01-cluster-seg1 | adc-lfsw0101=103, adc-lfsw0102=103, adc-lfsw0103=13, adc-lfsw0104=13 | ["172.16.3.1/24"] | ["fd21:0:0:3::1/64"] | fe80::1 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | DEVICE_VARIANT |
| 10104 | tenant1-vpc1 | tenant1-vpc1-k02-cluster-seg1 | adc-lfsw0101=104, adc-lfsw0102=104, adc-lfsw0103=14, adc-lfsw0104=14 | ["172.16.4.1/24"] | ["fd21:0:0:4::1/64"] | adc-lfsw0101=fe80::1, adc-lfsw0102=fe80::1, adc-lfsw0103=fe80::1, adc-lfsw0104=auto | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | DEVICE_VARIANT |
| 20200 | tenant2-vpc1 | tenant2-vpc1-server-seg1 | adc-lfsw0101=200, adc-lfsw0102=200, adc-lfsw0103=20, adc-lfsw0104=20 | ["172.17.0.254/24"] | ["fd22:0:0:1::1/64"] | fe80::1 | adc-lfsw0101=Up, adc-lfsw0102=Up, adc-lfsw0103=Up, adc-lfsw0104=Up | DEVICE_VARIANT |
