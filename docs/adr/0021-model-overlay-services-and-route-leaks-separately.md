# ADR-0021: Overlay Service と VRF 間 route leak を独立 model で表す

## 状態

Accepted

## Context

Physical、Underlay、EVPN control-plane diagram の分離後も、VRF、L2VNI、L3VNI、RD／RT、NVE membership と
tenant service の関係を確認する view がない。これらを EVPN BGP session graph へ重ねると、session と service の edge、
状態、evidence の意味が混在する。

また、VRF 間の route-target import／export は階層関係ではなく、exporter から importer への有向 policy である。
同一 L3VNI の Type-5 正常性判定を異なる VRF／L3VNI の route leak へ流用すると、受信対象と期待 prefix を誤って
判定する可能性がある。

## Decision

- VRF／VNI／RD／RT、NVE membership を `OverlayServiceModel` として EVPN session model から分離する。
- L3 service identity は `(site, vrf)`、L2-only service identity は `(site, l2vni)` とする。
- VRF 間 route leak は、source service の export RT と destination service の import RT が一致する有向 relation とする。
- 双方向 leak は canonical model では 2 relation として保持し、推移的な leak を推測しない。
- RT policy の一致と Type-5／destination VRF route による operational verification を分離する。
- RT は node／placement 単位で照合してから service 間 relation へ集約し、policy と verification の coverage を保持する。
- `auto` は wildcard とせず、platform context から一意に解決できない場合は fail closed で `unknown` とする。
- 初期範囲は read-only の解析、状態判定、描画とし、route-target config の生成・投入は含めない。
- `generate-network-diagram --all-graph` は Overlay Service の `TD`／`LR` を加えた既定 8 page とし、
  `--no-overlay-service` で既存 6 page を維持する。
- selector は exact service identity、site、VRF、L2VNI、L3VNI の union とし、route leak の直接隣接 service だけを
  context 表示する。

現行仕様の詳細は
[Overlay Service Diagram Design](../design/topology/OVERLAY_SERVICE_DIAGRAM_DESIGN.md) を正本とする。

## Consequences

- EVPN control plane と tenant service の責務、状態、evidence を独立して追跡できる。
- route leak の方向、RT policy と operational result を区別できる。
- `OverlayServiceModel` schema、builder、renderer、Manifest、sample、golden test の追加が必要になる。
- current Type-5 parser／Snapshot は再利用できるが、同一 L3VNI receiver evaluator は route leak 判定へ流用できない。
- multi-page draw.io の既定 page 数が 6 から 8 へ変わるため、既存 consumer は
  `--no-overlay-service` を使用できる。
- 個別 prefix や MAC を diagram へ大量展開せず、service Detail と将来の report へ分離する必要がある。
