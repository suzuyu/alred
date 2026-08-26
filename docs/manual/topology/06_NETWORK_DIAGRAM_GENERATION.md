# Network Diagram Generation

## 1. 目的

`generate-network-diagram` は 1 つの固定 source から link 正規化と診断、Physical／Underlay／EVPN／Overlay Service の生成、
canonical model／CSV／draw.io／Manifest の公開までを一括実行する。Evidence Package、external running config import、Operation、
confirmed CSV／Containerlab YAML を source にできる。隔離環境では Evidence Package を標準経路とする。

Evidence Package を使用する最短手順は [Quick Start](01_QUICK_START.md)、個別の Mermaid／Graphviz／draw.io renderer は
[Diagram Rendering](03_DIAGRAM_RENDERING.md) を参照する。

## 2. Evidence Package の標準 command

主要 4 view、TD／LR の multi-page draw.io、全 Overlay Service Detail を生成する。

`evidence-package import` 済みの最新 package を使用する最小 command は次のとおりである。

```bash
alred generate-network-diagram
```

source を省略すると `imported-evidence/latest` を検証して使用する。過去世代または別 directory を使用する場合は
`--evidence-package <imported-package-directory>` を明示する。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id> \
  --all-graph \
  --all-overlay-details \
  --overlay-detail-format markdown,drawio
```

`generate-network-diagram` と内部の `normalize-links` は device access を行わない。Package Manifest から inventory、running config、
任意 LLDP、mappings、description rules、roles、sites を解決する。隔離環境の local `raw/` を暗黙に混在させない。

## 3. 一括処理

1. archive import 時に検証済みの Package Manifest と artifact hash を確認する。
2. 共通 `normalize-links` を 1 回実行し、canonical links と LinkDiagnostics を生成する。
3. 再生成した canonical links と Package 同梱結果の semantic hash を照合する。
4. LinkDiagnostics を Physical／Underlay edge へ関連付け、`mismatch-links.md` を生成する。
5. 固定 running config と任意 operational output から Underlay、EVPN、Overlay Service model を生成する。
6. staging directory で schema、Manifest、artifact hash を検証する。
7. 全成果物がそろった場合だけ output directory へ atomic publish する。

canonical links が一致しない場合は diagram を公開しない。収集されていない address、session、route state を role や hostname から
推測して補完しない。

VNI の表形式一覧は Network Operations の [VNI Map Guide](../network-ops/09_VNI_MAP_GUIDE.md)を参照する。
Overlay Service diagram と model は service 間関係と placement の可視化を担当し、VNI 一覧の正本にはしない。

## 4. View ごとの evidence

| View | 主な evidence | evidence 不足時 |
|---|---|---|
| Physical | LLDP、interface description、inventory | 片方向 link は candidate とする |
| Underlay | running config の Loopback、接続 interface、Underlay BGP | address や RR を推測しない |
| EVPN | BGP L2VPN EVPN neighbor、peer template、RR client、Router ID、NVE source、任意 summary | config だけなら `configured`、operational state は推測しない |
| Overlay Service | VRF、L2VNI／L3VNI、RD／RT、VTEP／NVE、任意 Type-5／VRF route | policy は `configured`、運用状態は `unknown` とする |

Overlay Service の route 到達性は、対応する Type-5 と destination VRF route が同じ固定 source にある場合だけ `verified` または
`degraded` と判定する。

## 5. 主な option

| Option | 動作 |
|---|---|
| `--all-graph` | Physical／Underlay／EVPN／Overlay Service の TD／LR、Topology Confirmed Links、Topology Defined Roles を 10 page draw.io にまとめる |
| `--directions TD,LR,BT,RL` | `--all-graph` と併用し、反転方向を含む 18 page を生成する |
| `--all-overlay-details` | Detail 上限を解除して全 service を選択する |
| `--overlay-detail-format markdown,drawio` | service Detail を Markdown と draw.io の両形式で生成する |
| `--overlay-detail-limit <count>` | selector 未指定時に生成する Detail 件数を制限する。既定は 20 件 |
| `--site`／`--vrf`／`--l2vni`／`--l3vni`／`--service` | Detail 対象を union で選択する |
| `--output-dir <directory>` | 固定成果物の公開先を変更する |
| `--input <file>` | `imported-evidence/latest` の既定選択を使わず、confirmed CSV または Containerlab YAML を直接入力する |
| `--link-diagnostics <file>` | 直接 CSV／Containerlab 入力で既存の `link-diagnostics.yaml` を使用する |
| `--no-overlay-service` | Overlay Service を除外した 8 page を生成する |
| `--no-group-by-role`／`--no-group-by-site` | role grouping または自動 site grouping を無効化する |

`--all-overlay-details --overlay-detail-format markdown,drawio` は全 VRF の両形式を生成する。大規模環境で review 対象が限定される場合は、
`--service <site>/<vrf>` または他の selector と別の `--output-dir` を使用する。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id> \
  --service site-1/tenant1-vpc1 \
  --overlay-detail-format markdown,drawio \
  --output-dir output/overlay-tenant1
```

`--vrf tenant1-vpc1` は複数 site の同名 VRF を union で選択する。1 service に限定する場合は canonical service ID の
`--service <site>/<vrf>` を使用する。

## 6. Grouping と draw.io layout

role grouping は既定で有効である。Package 内の inventory または `sites.resolved.yaml` から 1 台以上の site を解決できる場合は、
site grouping も自動的に有効になる。service ID の site は hostname prefix ではなく `site_detection` の key である。

Mermaid の既定方向は `TD` である。draw.io の EVPN LR は Spine 右側から Leaf 左側へ session edge を接続する。
Overlay Service Summary は route leak adjacency の最大次数 service を hub とし、TD は hub 上段／spoke 下段、LR は
hub 左列／spoke 右列へ配置する。逆方向 route leak は 2 lane に分離する。この layout は自動動作であり option は不要である。

## 7. 全生成物一覧

`generate-network-diagram` が生成する成果物は次のとおりである。Evidence Package 使用時の再生成検証用 file も含む。

| 生成物 | 生成条件 | 内容 | Example |
|---|---|---|---|
| `links_confirmed.csv` | 常時 | 複数 evidence で確認できた canonical link | [confirmed link](examples/quick-start/links_confirmed.example.csv) |
| `links_candidates.csv` | 常時 | 片方向または未確定の review 対象 link | [candidate link](examples/quick-start/links_candidates.example.csv) |
| `link-diagnostics.yaml` | 常時 | coverage、不整合、警告、未評価 claim、影響 device、未解決 peer reference、非相互 description の逆方向比較 evidence を含む schema 付き結果 | [Link Normalization](02_LINK_NORMALIZATION.md) |
| `mismatch-links.md` | 常時 | Summary、Affected Devices、mismatch、warning、unknown、未解決 peer reference、および診断ごとの期待値／実測値／差分理由。未評価 claim は Summary の件数だけを表示 | [Link Normalization](02_LINK_NORMALIZATION.md) |
| `normalized-links.regenerated.csv` | Evidence Package 使用時 | Package の固定 source から再生成した confirmed link | [Link Normalization](02_LINK_NORMALIZATION.md) |
| `link-verification.json` | Evidence Package 使用時 | Package 同梱 link と再生成 link の semantic hash 検証結果 | [Link Normalization](02_LINK_NORMALIZATION.md) |
| `normalization-manifest.yaml` | Evidence Package 使用時 | normalizer version と検証済み semantic hash | [Link Normalization](02_LINK_NORMALIZATION.md) |
| `topology-graph.md` | 常時 | Physical topology の Mermaid | [Physical sample](examples/single-site-fabric/topology-graph.md) |
| `topology_underlay.md` | 常時 | Underlay address／session の Mermaid | [Underlay sample](examples/single-site-fabric/topology_underlay.md) |
| `topology_evpn.md` | 常時 | EVPN RR／VTEP／session の Mermaid | [EVPN sample](examples/single-site-fabric/topology_evpn.md) |
| `evpn-control-plane-model.yaml` | 常時 | EVPN node、session、diagnostic の canonical model | [EVPN model sample](examples/single-site-fabric/evpn-control-plane-model.yaml) |
| `evpn-session-links.csv` | 常時 | EVPN session の review 用一覧 | [EVPN CSV sample](examples/single-site-fabric/evpn-session-links.csv) |
| `topology_overlay_service.md` | Overlay Service 有効時 | VRF／VNI／route leak の Mermaid Summary | [Overlay Summary sample](examples/single-site-fabric/topology_overlay_service.md) |
| `overlay-service-model.yaml` | Overlay Service 有効時 | service、placement、route leak の canonical model | [Overlay model sample](examples/single-site-fabric/overlay-service-model.yaml) |
| `overlay-service-links.csv` | Overlay Service 有効時 | 有向 route leak の review 用一覧 | [Overlay CSV sample](examples/single-site-fabric/overlay-service-links.csv) |
| `overlay-services/*.md` | Overlay Service Detail で `markdown` を選択時 | VRF 単位の設定・RT・placement Detail | [tenant1 Markdown sample](examples/single-site-fabric/overlay-services/adc_tenant1-vpc1-faa720c4.md) |
| `overlay-services/*.drawio` | Overlay Service Detail で `drawio` を選択時 | VRF 単位の編集可能な Detail | [tenant1 draw.io sample](examples/single-site-fabric/overlay-services/adc_tenant1-vpc1-faa720c4.drawio) |
| `topology-graph.drawio` | `--all-graph` 未指定時 | `--direction` で選択した単一 view の draw.io | [Diagram Rendering](03_DIAGRAM_RENDERING.md) |
| `topology-graph-all.drawio` | `--all-graph` 指定時 | 4 view × TD／LR、Topology Confirmed Links、role 定義済み node だけの Topology Defined Roles を収容する 10 page draw.io。confirmed-only page は非表示診断がある場合に分類別件数と `mismatch-links.md` への参照を警告表示 | [10-page draw.io sample](examples/single-site-fabric/topology-graph-all.drawio) |
| `network-diagram-manifest.yaml` | 常時 | source、実効 option、入力・成果物 hash、Detail 選択結果 | [Manifest sample](examples/single-site-fabric/network-diagram-manifest.yaml) |

`--no-overlay-service` 指定時は Overlay Service Summary、model、CSV、Detail を生成しない。Detail の生成件数と形式は
selector、`--overlay-detail-limit`、`--all-overlay-details`、`--overlay-detail-format` によって変わる。

## 8. 生成後の確認

最低限、次を確認する。

```bash
test -f output/links_confirmed.csv
test -f output/links_candidates.csv
test -f output/link-diagnostics.yaml
test -f output/mismatch-links.md
test -f output/link-verification.json
test -f output/topology-graph.md
test -f output/topology_underlay.md
test -f output/topology_evpn.md
test -f output/evpn-control-plane-model.yaml
test -f output/topology_overlay_service.md
test -f output/overlay-service-model.yaml
test -f output/topology-graph-all.drawio
test -f output/network-diagram-manifest.yaml
test -d output/overlay-services
```

`mismatch-links.md` で evaluation status、影響 device、対象 link、期待値／実測値／差分理由、片方向だが未評価の claim を確認する。`network-diagram-manifest.yaml` で source、
実効 option、LinkDiagnostics の result／件数、input／artifact hash、Detail の generated／omitted service ID を確認する。
成果物の意味と troubleshooting は [Output and Troubleshooting](04_OUTPUT_AND_TROUBLESHOOTING.md) を参照する。

## 9. Graphviz を追加生成

一括処理後の検証済み CSV と Package 内の解決済み metadata を個別 renderer へ渡せる。

```bash
alred generate-graphviz \
  --input output/links_confirmed.csv \
  --input-candidates output/links_candidates.csv \
  --hosts imported-evidence/<package-id>/inventory/hosts.resolved.yaml \
  --roles imported-evidence/<package-id>/policy/roles.resolved.yaml \
  --sites imported-evidence/<package-id>/policy/sites.resolved.yaml
```
