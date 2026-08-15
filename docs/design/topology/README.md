# Topology Design

LLDP、link正規化、各種diagramの設計を用途別にまとめる。Terraform生成はinventory派生機能として
[Common Design](../common/README.md)へ分離する。

| 文書 | 責務 |
|---|---|
| [Link Discovery and Normalization Design](LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md) | LLDP／description、canonical link、confidence、CSV |
| [Topology Rendering Design](TOPOLOGY_RENDERING_DESIGN.md) | `generate-network-diagram`、Mermaid、Graphviz、draw.io、`generate-doc` |
| [EVPN Control Plane Diagram Design](EVPN_CONTROL_PLANE_DIAGRAM_DESIGN.md) | EVPN session model、RR／client、VTEP、Underlay との責務分離 |
| [Overlay Service Diagram Design](OVERLAY_SERVICE_DIAGRAM_DESIGN.md) | VRF／VNI／RD／RT、NVE membership、VRF 間 route leak の解析と描画 |

containerlab固有のnode、startup config、mergeは
[Containerlab Design](../containerlab/README.md)、inventoryとroleは[Common Design](../common/README.md)を
参照する。現行実装の解析記録は[As-Is](../../as-is/TOPOLOGY_AND_RENDERING_AS_IS.md)に置く。
