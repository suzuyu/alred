# Topology Single-site Fabric Sample

実用規模の [Containerlab Single-site Fabric Sample](../../../containerlab/examples/single-site-fabric/README.md) から
`generate-network-diagram` で生成した 22 node／40 link の出力例である。

| 内容 | Sample |
|---|---|
| Mermaid topology | [topology-graph.md](topology-graph.md) |
| LinkDiagnostics | [link-diagnostics.yaml](link-diagnostics.yaml) |
| link mismatch report | [mismatch-links.md](mismatch-links.md) |
| Mermaid Underlay | [topology_underlay.md](topology_underlay.md) |
| Mermaid EVPN | [topology_evpn.md](topology_evpn.md) |
| EVPN control-plane model | [evpn-control-plane-model.yaml](evpn-control-plane-model.yaml) |
| EVPN session CSV | [evpn-session-links.csv](evpn-session-links.csv) |
| Mermaid Overlay Service | [topology_overlay_service.md](topology_overlay_service.md) |
| Overlay Service model | [overlay-service-model.yaml](overlay-service-model.yaml) |
| Overlay Service route leak CSV | [overlay-service-links.csv](overlay-service-links.csv) |
| Overlay Service Markdown／`draw.io` Detail | [overlay-services/](overlay-services/) |
| `draw.io` 10 page | [topology-graph-all.drawio](topology-graph-all.drawio) |
| 生成 Manifest | [network-diagram-manifest.yaml](network-diagram-manifest.yaml) |

`adc-*` の命名規則から `site=adc` を解決し、明示 label がない node に適用している。`sites.example.yaml` には将来の
`bdc-*`、`cdc-*` と WAN node の rule も含むが、本 sample の生成結果は single-site である。role grouping と site grouping は
有効、方向は既定の `TD` である。role group は priority が小さい順に Spine、Leaf、Network Function、server とし、
Mermaid source で上から出力する。
`network-functions` と `server` は同じ priority とし、draw.io の `TD` page では同じ高さに横並びで配置する。
Mermaid は同一 priority の source 順だけを固定し、横並びは保証しない。

本 sample は Containerlab YAML を直接入力しており、LLDP／description の diagnostic evidence を指定していない。このため
LinkDiagnostics は `not-evaluated`／`UNKNOWN` とし、構成図の link が不整合なしとは判定しない。

通常 topology は server／Kind node を含む全 40 link を表示する。Underlay は target role である Spine／Leaf と、
address を解決できた 8 link だけを表示し、server／Kind node など片方向の対向機器は描画しない。
EVPN view は config evidence から Spine 2 台を RR、Leaf 4 台を VTEP として解決し、Leaf から各 RR への計 8 session を
`configured`／state unknown として表示する。operational summary を含まないため `Established` とは推測しない。
各 vPC pair で一致する NVE source Loopback の secondary address は `VTEP (vPC shared)`、Leaf 固有 address は `VTEP` として
区別する。
Overlay Service view は 3 service と 6 本の有向 route leak を表示する。operational route output を含まないため、policy は
config から確認しても route 到達性は `unknown` とし、`verified` と推測しない。
draw.io Summary は EVPN LR の Spine 右側から Leaf 左側へ session edge を接続する。Overlay Service は最大次数の
`controller-vpc1` を hub とし、TD は上段の controller と下段の tenant 群、LR は左列の controller と右列の tenant 群に分ける。
同じ service pair の逆方向 route leak は 2 lane に分離する。
各 Detail は RT の `auto` 起源、L3VNI Mode、L3VNI 用 VLAN／SVI、L2VNI の device-local VLAN／SVI binding、Gateway、
IPv4／IPv6 SVI address と、直接 route leak を表示する。本 sample の L3VNI は `Traditional VLAN/SVI` である。draw.io Detail は
Inbound／Outbound、Service、L3VNI／L2 component、EVPN Placement の 4 段で、`Service → component → EVPN Placement` の関係を表示する。
VLAN／SVI は `VLAN 2001 (SVI)` のように compact 表示し、同じ shared VTEP を持つ vPC pair は個別 Placement を維持したまま
vPC container にまとめる。両 member に共通する component binding は container 単位の 1 edge に集約する。
`adc-bgrt0101`／`adc-bgrt0102` は対象 VRF を持つが L3VNI／L2VNI／NVE binding を持たないため、EVPN Placement ではなく
`Service Edge Attachments` として分離する。Service Edge は Service へ `VRF attachment` で直接接続し、Leaf の VTEP 数、
EVPN route 集計、component binding には含めない。
Inbound／Outbound の RT は Same-VRF、Route Leak、Additional に分類し、Route Leak は peer、RT、AF、state を 1 node にまとめる。

repository root から次の command で再生成できる。

```bash
alred generate-network-diagram \
  --input docs/manual/containerlab/examples/single-site-fabric/topology.clab.example.yaml \
  --input-format clab \
  --roles docs/manual/containerlab/examples/single-site-fabric/roles.example.yaml \
  --sites docs/manual/containerlab/examples/single-site-fabric/sites.example.yaml \
  --underlay-raw docs/manual/containerlab/examples/single-site-fabric/labconfig \
  --all-graph \
  --all-overlay-details \
  --overlay-detail-format markdown,drawio \
  --output-dir docs/manual/topology/examples/single-site-fabric
```

`network-diagram-manifest.yaml` に入力、実効 option、成果物 hash を記録する。出力に hostname、management address、
Underlay address が含まれるため、実データで生成する場合は共有前に Evidence Package の disclosure policy を確認する。
