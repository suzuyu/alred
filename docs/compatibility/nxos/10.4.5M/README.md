# NX-OS 10.4(5)M Hardware Document Review Records

このディレクトリは、実機を使用しないhardware modelの文書確認記録を保持する。確認結果はCisco公式資料とsynthetic golden configに限定され、実機での投入、保存、収束、rollbackを保証しない。

## 共通参照資料

| ID | 文書・section | 確認用途 |
|---|---|---|
| `release-notes` | Cisco Nexus 9000 Series NX-OS Release Notes, Release 10.4(5)M / Device Hardware | exact PIDと10.4(5)M image |
| `vxlan-guide` | Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.4(x) / Configure VXLAN BGP EVPN | VRF、L2/L3 VNI、NVE、EVPN、SVI、BGP EVPN、vPC前提 |
| `vxlan-new` | 同Guide / New and Changed Information | 9364C-H1のVXLAN対応開始release |
| `ipv6-guide` | Cisco Nexus 9000 Series NX-OS Unicast Routing Configuration Guide, Release 10.4(x) / Configuring IPv6 | IPv6 address、link-local、ND RA suppression |
| `command-reference` | Cisco Nexus 9000 Series NX-OS Command Reference (Configuration Commands), Release 10.4(x) | rendererが生成する個別CLI構文 |
| `interface-guide` | Cisco Nexus 9000 Series NX-OS Interfaces Configuration Guide, Release 10.4(x) / Basic Interface Parameters | interface admin stateとMTU前提 |
| `scale-guide` | Cisco Nexus 9000 Series NX-OS Verified Scalability Guide, Release 10.4(5)M | VLAN、VNI、VRF、route等の上限確認先 |
| `license-guide` | Cisco NX-OS Licensing Options Guide / Nexus 9000 tier-based licenses | BGP、OSPF、VXLAN BGP EVPNのlicense条件 |

## 判定

4機種のrenderer対象commandはNexus 9000共通の10.4(x) guide／command referenceで確認し、exact PIDは10.4(5)M Release Notesで確認した。9364C-H1はVXLAN対応が10.4(3)Fから追加されているため、10.4(5)Mは文書上の対象に含まれる。

scale、license、vPCおよびrelease caveatは構成・契約に依存するため`SUPPORTED_WITH_CONDITIONS`とする。plan時には利用者が実環境の使用量、license、既存Fabric状態を確認する。これらの記録をCapability Registryへ登録せず、runtimeは`PLAN_ONLY`以下を維持する。

Golden configは`tests/fixtures/nxos/hardware_document_review/`に置く。4機種は同じ共通templateを使い、機種固有分岐がないためfull configを共有し、model別manifestでmodel、release、hash、`apply_allowed: false`を固定する。
