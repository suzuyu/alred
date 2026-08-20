# Evidence Package Quick Start

本手順は、商用環境から搬送した `digital-twin` Evidence Package を基に、隔離環境で link を再生成・検証し、
Mermaid Physical、Underlay、EVPN control plane、Overlay Service、draw.io を一括生成する最短手順である。`generate-network-diagram` と内部の
`normalize-links` は device access を行わない。

alred で収集していない `show running-config` file や transcript を使用する場合は
[External Data to Topology](05_EXTERNAL_DATA_TO_TOPOLOGY.md) を参照する。同一環境の最新 Operation を直接使用する場合は
[Link Normalization](02_LINK_NORMALIZATION.md) の「Operation、Evidence Package、external import」を参照する。

## 1. Evidence Package を作成

商用環境側で、正常公開済みの最新 `operations/` を基に `digital-twin` Evidence Package を作成する。

```bash
alred evidence-package create --profile digital-twin
```

最新情報を実機から収集する必要がある場合だけ、先に `health-check before --purpose inspection --collect` を実行する。
既存 Operation の自動選択、任意収集、開示 policy、secret scan、搬送前確認の詳細は
[Existing Network to Lab](../containerlab/02_EXISTING_NETWORK_TO_LAB.md) の 2～4 章を参照する。

本章以降は、生成した `<package-id>.tar.gz` と `<package-id>.sha256` を topology 生成環境へ搬送済みであることを前提とする。

## 2. Evidence Package を import

`import` は内部で archive、Manifest、artifact hash を検証し、成功した場合だけ directory を公開する。

```bash
alred evidence-package import \
  --bundle evidence-packages/<package-id>.tar.gz
```

同じ directory の `<package-id>.sha256` は自動検出する。別名または別 directory の checksum file を使用する場合だけ
`--checksum-file` を明示する。`verbatim` Package の場合は `--acknowledge-sensitive-config` も必要である。
import 成功後は `imported-evidence/latest` から最新版へ到達できる。対話的な確認では
`--evidence-package imported-evidence/latest` も使用できるが、再現手順では package ID を固定する。

## 3. Network diagram を一括生成

import 済み Evidence Package から、主要 diagram と全 Overlay Service Detail を生成する。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id> \
  --all-graph \
  --all-overlay-details \
  --overlay-detail-format markdown,drawio
```

`--all-graph` は Physical／Underlay／EVPN／Overlay Service の TD／LR と Topology Confirmed Links を 9 page の draw.io にまとめる。
`--all-overlay-details --overlay-detail-format markdown,drawio` は全 service の Markdown／draw.io Detail を生成する。
Overlay Service Summary の hub-and-spoke 配置は自動適用され、追加 option は不要である。内部処理、evidence 判定、
規模に応じた selector、個別 renderer は [Network Diagram Generation](06_NETWORK_DIAGRAM_GENERATION.md) を参照する。

### 3.1 生成物

| 生成物 | 用途 | Example |
|---|---|---|
| `topology-graph.md` | Physical topology の Mermaid | [Physical sample](examples/single-site-fabric/topology-graph.md) |
| `topology_underlay.md` | Underlay address／session の Mermaid | [Underlay sample](examples/single-site-fabric/topology_underlay.md) |
| `topology_evpn.md` | EVPN RR／VTEP／session の Mermaid | [EVPN sample](examples/single-site-fabric/topology_evpn.md) |
| `topology_overlay_service.md` | VRF／VNI／route leak の Mermaid Summary | [Overlay Summary sample](examples/single-site-fabric/topology_overlay_service.md) |
| `topology-graph-all.drawio` | 4 view × TD／LR と Topology Confirmed Links の 9 page | [9-page draw.io sample](examples/single-site-fabric/topology-graph-all.drawio) |
| `overlay-services/*.md` | VRF 単位の設定・RT・placement Detail | [tenant1 Markdown sample](examples/single-site-fabric/overlay-services/adc_tenant1-vpc1-faa720c4.md) |
| `overlay-services/*.drawio` | VRF 単位の編集可能な Detail | [tenant1 draw.io sample](examples/single-site-fabric/overlay-services/adc_tenant1-vpc1-faa720c4.drawio) |

canonical model、review CSV、link 検証結果、Manifest を含む全成果物は
[Network Diagram Generation の全生成物一覧](06_NETWORK_DIAGRAM_GENERATION.md#7-全生成物一覧)を参照する。

## 4. Link と構成図を確認

`links_confirmed.csv`、`links_candidates.csv`、`link-verification.json` を確認し、candidate を自動的に confirmed と扱わない。
Mermaid 4 file と `topology-graph-all.drawio` を開き、EVPN／Overlay model の `status` と `diagnostics` を確認する。
共有前に Evidence Package の disclosure policy と、hostname、管理 address、Underlay address の開示可否を確認する。

詳細な確認項目と代表的な問題は [Output and Troubleshooting](04_OUTPUT_AND_TROUBLESHOOTING.md) を参照する。
最小構成は [Topology Quick Start Sample](examples/quick-start/README.md)、EVPN／Overlay を含む実用例は
[Topology Single-site Fabric Sample](examples/single-site-fabric/README.md) を参照する。
