# ADR-0020: Underlay routing と EVPN control-plane diagram を分離する

## 状態

Accepted

## Context

従来の Underlay diagram は routed link、Loopback、interface address と、`(BGP-RR)` のような EVPN／Underlay AF を
区別しない注記を同じ view に表示していた。物理到達性を確認する目的と EVPN BGP session／RR client 関係を確認する目的が
混在し、表示された RR が Underlay RR か EVPN RR かを diagram だけから判断できない。

EVPN session は物理 link ではなく論理 control-plane relationship である。LLDP／description の Canonical Link Evidence から
生成する物理 topology と同じ link model へ格納すると、confidence、endpoint、状態、証跡の意味も曖昧になる。

## Decision

- Physical、Underlay、EVPN を独立した view とする。
- Underlay view は routed link、Underlay address／protocol、実効設定で確認した Underlay RR だけを表示する。
- EVPN RR、RR client、VTEP、EVPN BGP session／state は EVPN view だけに表示する。
- EVPN session は `EVPNControlPlaneModel` として正規化し、物理 Canonical Link Evidence と別 model にする。
- running-config と `show bgp l2vpn evpn summary` の検証済み evidence を解析し、role expectation だけから session edge を
  生成しない。
- existing Overlay parser／Snapshot を拡張・再利用し、diagram 専用 BGP parser を重複実装しない。
- `generate-network-diagram` は同じ固定 source から 3 view を生成し、multi-page draw.io は既定 `TD`／`LR` で 6 page とする。
- VNI、VRF、RT、NVE tunnel は EVPN control-plane view に重ねず、将来の Overlay service view へ分離する。

現行仕様の詳細は
[EVPN Control Plane Diagram Design](../design/topology/EVPN_CONTROL_PLANE_DIAGRAM_DESIGN.md) と
[Topology Rendering Design](../design/topology/TOPOLOGY_RENDERING_DESIGN.md) を正本とする。

## Consequences

- Underlay diagram から EVPN 固有表示がなくなり、物理／routing 到達性の確認目的が明確になる。
- EVPN RR と client の論理関係、configured／operational state、証跡不足を独立して確認できる。
- `generate-network-diagram` の成果物、Manifest schema、draw.io page 数、golden sample を拡張する必要がある。
- running-config parser は peer template 継承を含む effective EVPN neighbor を出力する必要がある。
- peer address を node へ一意に解決できない場合は diagram の confirmed edge にせず、diagnostic として残す必要がある。
- `generate-network-diagram` の既定成果物と `--all-graph` は EVPN model／CSV／Mermaid および Physical／Underlay／EVPN の
  6 page を含むため、従来の 4 page を前提にした consumer は成果物一覧と page 数を更新する必要がある。
