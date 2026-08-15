# Overlay Service: adc/controller-vpc1

- Site: `adc`
- VRF: `controller-vpc1`
- L3VNI: `9001`
- L3VNI Mode: `Traditional VLAN/SVI`
- RD: `auto`
- Status: `configured`

## Route Targets

- Import: `65001:19001, 65001:29001, 65001:9001 (auto)`
- Export: `65001:9001 (auto)`

## EVPN Placements

| Node | Type | VTEP | vPC shared VTEP | NVE L3 member |
|---|---|---|---|---|
| adc-lfsw0101 | evpn-vtep | 10.0.1.1, 10.0.2.1 | 10.0.2.1 | true |
| adc-lfsw0102 | evpn-vtep | 10.0.1.2, 10.0.2.1 | 10.0.2.1 | true |
| adc-lfsw0103 | evpn-vtep | 10.0.1.3, 10.0.2.2 | 10.0.2.2 | true |
| adc-lfsw0104 | evpn-vtep | 10.0.1.4, 10.0.2.2 | 10.0.2.2 | true |

## L3VNI Interfaces

| Node | L3VNI | L3VNI Mode | VLAN | SVI | SVI behavior | NVE associate-vrf | IPv4 | IPv6 |
|---|---:|---|---:|---|---|---|---|---|
| adc-lfsw0101 | 9001 | Traditional VLAN/SVI | 3000 | Vlan3000 | ip-forward | true | - | link-local-only |
| adc-lfsw0102 | 9001 | Traditional VLAN/SVI | 3000 | Vlan3000 | ip-forward | true | - | link-local-only |
| adc-lfsw0103 | 9001 | Traditional VLAN/SVI | 3000 | Vlan3000 | ip-forward | true | - | link-local-only |
| adc-lfsw0104 | 9001 | Traditional VLAN/SVI | 3000 | Vlan3000 | ip-forward | true | - | link-local-only |

## L2 Services

| L2VNI | Node | VLAN | SVI | Gateway | IPv4 SVI address | IPv6 SVI address | NVE member |
|---:|---|---:|---|---|---|---|---|
| 100 | adc-lfsw0101 | 2001 | Vlan2001 | yes | 100.64.0.254/24 | fd12:0:0:1::1/64 | true |
| 100 | adc-lfsw0102 | 2001 | Vlan2001 | yes | 100.64.0.254/24 | fd12:0:0:1::1/64 | true |
| 100 | adc-lfsw0103 | 2001 | Vlan2001 | yes | 100.64.0.254/24 | fd12:0:0:1::1/64 | true |
| 100 | adc-lfsw0104 | 2001 | Vlan2001 | yes | 100.64.0.254/24 | fd12:0:0:1::1/64 | true |

## Route Leaks

| Direction | Peer Service | AF | RT | Policy | Operational | Scope |
|---|---|---|---|---|---|---|
| outbound | adc/tenant1-vpc1 | ipv6 | 65001:9001 | configured | unknown | unknown |
| outbound | adc/tenant2-vpc1 | ipv6 | 65001:9001 | configured | unknown | unknown |
| inbound | adc/tenant1-vpc1 | ipv4 | 65001:19001 | configured | unknown | unknown |
| inbound | adc/tenant1-vpc1 | ipv6 | 65001:19001 | configured | unknown | unknown |
| inbound | adc/tenant2-vpc1 | ipv4 | 65001:29001 | configured | unknown | unknown |
| inbound | adc/tenant2-vpc1 | ipv6 | 65001:29001 | configured | unknown | unknown |
