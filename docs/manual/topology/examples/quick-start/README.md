# Topology Quick Start Sample

この directory は、Evidence Package Quick Start で生成する主要成果物の表示例である。node、address、link は
documentation 用に作成した架空値であり、実環境の情報を含まない。

| 内容 | Sample |
|---|---|
| confirmed link | [links_confirmed.example.csv](links_confirmed.example.csv) |
| candidate link | [links_candidates.example.csv](links_candidates.example.csv) |
| Mermaid topology | [topology-graph.example.md](topology-graph.example.md) |
| Mermaid Underlay | [topology_underlay.example.md](topology_underlay.example.md) |
| Mermaid EVPN | [topology_evpn.example.md](topology_evpn.example.md) |
| EVPN control-plane model | [evpn-control-plane-model.example.yaml](evpn-control-plane-model.example.yaml) |
| EVPN session CSV | [evpn-session-links.example.csv](evpn-session-links.example.csv) |
| Mermaid Overlay Service | [topology_overlay_service.example.md](topology_overlay_service.example.md) |
| Overlay Service model | [overlay-service-model.example.yaml](overlay-service-model.example.yaml) |
| Overlay Service route leak CSV | [overlay-service-links.example.csv](overlay-service-links.example.csv) |
| draw.io 8 page | [topology-graph-all.example.drawio](topology-graph-all.example.drawio) |
| 生成 Manifest | [network-diagram-manifest.example.yaml](network-diagram-manifest.example.yaml) |

Mermaid は既定の `TD`、role grouping、site grouping を適用した 4 node／4 link の例である。draw.io は
`--all-graph` により Physical／Underlay／EVPN／Overlay Service の `TD`／`LR` を収容した 8 page 構成である。
Underlay では、同じ link に対して Loopback address と接続 interface address を表示する。

本 Quick Start の最小 config には EVPN BGP／VNI／RT 設定がないため、EVPN model と Overlay Service model は
`insufficient-evidence` とし、diagram に理由を表示する。EVPN session と Overlay Service を含む実用規模の例は
[Single-site Fabric Sample](../single-site-fabric/README.md) を参照する。

`links_candidates.example.csv` は candidate がない正常例であり、互換性のある header だけを保持する。実環境では
candidate が 0 件とは限らないため、`links_confirmed.csv` と合わせて必ず確認する。

表示例は Containerlab sample と共通の架空 topology を使用している。元になる変換前後 config は
[Containerlab Quick Start Sample](../../../containerlab/examples/quick-start/README.md) を参照する。
