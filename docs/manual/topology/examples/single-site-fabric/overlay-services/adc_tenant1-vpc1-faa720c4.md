# Overlay Service: adc/tenant1-vpc1

- Site: `adc`
- VRF: `tenant1-vpc1`
- L3VNI: `19001`
- L3VNI Mode: `Traditional VLAN/SVI`
- RD: `auto`
- Status: `configured`

## Route Targets

- Import: `65001:19001 (auto), 65001:9001`
- Export: `65001:19001 (auto)`

## EVPN Placements

| Node | Type | VTEP | vPC shared VTEP | NVE L3 member |
|---|---|---|---|---|
| adc-lfsw0101 | evpn-vtep | 10.0.1.1, 10.0.2.1 | 10.0.2.1 | true |
| adc-lfsw0102 | evpn-vtep | 10.0.1.2, 10.0.2.1 | 10.0.2.1 | true |
| adc-lfsw0103 | evpn-vtep | 10.0.1.3, 10.0.2.2 | 10.0.2.2 | true |
| adc-lfsw0104 | evpn-vtep | 10.0.1.4, 10.0.2.2 | 10.0.2.2 | true |

## Service Edge Attachments

| Node | Type | Evidence |
|---|---|---|
| adc-bgrt0101 | service-edge | VRF present; EVPN binding absent |
| adc-bgrt0102 | service-edge | VRF present; EVPN binding absent |

## L3VNI Interfaces

| Node | L3VNI | L3VNI Mode | VLAN | SVI | SVI behavior | NVE associate-vrf | IPv4 | IPv6 |
|---|---:|---|---:|---|---|---|---|---|
| adc-lfsw0101 | 19001 | Traditional VLAN/SVI | 3001 | Vlan3001 | ip-forward | true | - | link-local-only |
| adc-lfsw0102 | 19001 | Traditional VLAN/SVI | 3001 | Vlan3001 | ip-forward | true | - | link-local-only |
| adc-lfsw0103 | 19001 | Traditional VLAN/SVI | 3001 | Vlan3001 | ip-forward | true | - | link-local-only |
| adc-lfsw0104 | 19001 | Traditional VLAN/SVI | 3001 | Vlan3001 | ip-forward | true | - | link-local-only |

## L2 Services

| L2VNI | Node | VLAN | SVI | Gateway | IPv4 SVI address | IPv6 SVI address | NVE member |
|---:|---|---:|---|---|---|---|---|
| 10100 | adc-lfsw0101 | 100 | Vlan100 | yes | 172.16.0.254/24 | fd21:0:0:1::1/64 | true |
| 10100 | adc-lfsw0102 | 100 | Vlan100 | yes | 172.16.0.254/24 | fd21:0:0:1::1/64 | true |
| 10100 | adc-lfsw0103 | 10 | Vlan10 | yes | 172.16.0.254/24 | fd21:0:0:1::1/64 | true |
| 10100 | adc-lfsw0104 | 10 | Vlan10 | yes | 172.16.0.254/24 | fd21:0:0:1::1/64 | true |
| 10101 | adc-lfsw0103 | 11 | Vlan11 | yes | 172.16.1.254/24 | fd21:0:0:2::1/64 | true |
| 10101 | adc-lfsw0104 | 11 | Vlan11 | yes | 172.16.1.254/24 | fd21:0:0:2::1/64 | true |
| 10103 | adc-lfsw0101 | 103 | Vlan103 | yes | 172.16.3.1/24 | fd21:0:0:3::1/64 | true |
| 10103 | adc-lfsw0102 | 103 | Vlan103 | yes | 172.16.3.1/24 | fd21:0:0:3::1/64 | true |
| 10103 | adc-lfsw0103 | 13 | Vlan13 | yes | 172.16.3.1/24 | fd21:0:0:3::1/64 | true |
| 10103 | adc-lfsw0104 | 13 | Vlan13 | yes | 172.16.3.1/24 | fd21:0:0:3::1/64 | true |
| 10104 | adc-lfsw0101 | 104 | Vlan104 | yes | 172.16.4.1/24 | fd21:0:0:4::1/64 | true |
| 10104 | adc-lfsw0102 | 104 | Vlan104 | yes | 172.16.4.1/24 | fd21:0:0:4::1/64 | true |
| 10104 | adc-lfsw0103 | 14 | Vlan14 | yes | 172.16.4.1/24 | fd21:0:0:4::1/64 | true |
| 10104 | adc-lfsw0104 | 14 | Vlan14 | yes | 172.16.4.1/24 | fd21:0:0:4::1/64 | true |

## Route Leaks

| Direction | Peer Service | AF | RT | Policy | Operational | Scope |
|---|---|---|---|---|---|---|
| inbound | adc/controller-vpc1 | ipv6 | 65001:9001 | configured | unknown | unknown |
| outbound | adc/controller-vpc1 | ipv4 | 65001:19001 | configured | unknown | unknown |
| outbound | adc/controller-vpc1 | ipv6 | 65001:19001 | configured | unknown | unknown |
