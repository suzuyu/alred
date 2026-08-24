# Diagram Rendering

## 1. 共通入力

Mermaid、Graphviz、draw.ioはconfirmed link CSVまたはContainerlab YAMLを入力にできる。CSVを使う場合、
candidateは`--input-candidates`で別fileとして指定する。

`normalize-links` または `generate-network-diagram` が生成した `link-diagnostics.yaml` は
`--link-diagnostics` で指定する。診断 file を指定しない直接 CSV／Containerlab 入力では描画自体は継続するが、
診断結果は `not-evaluated` となる。

`--min-confidence`は`low`、`medium`、`high`から選択する。candidateを指定しても、表示対象はconfidence filterの
影響を受ける。曖昧なlinkを含める場合は、confirmedとの線種・注記の差をレビューする。

## 2. Physical／Underlay／EVPN／Overlay Service／draw.io の一括生成

Quick Start では `generate-network-diagram` を使用する。Evidence Package、external running config import、Operation、
confirmed CSV／Containerlab YAML の source selector は `generate-mermaid` と共通である。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id>
```

既定では `links_confirmed.csv`、`links_candidates.csv`、`link-diagnostics.yaml`、`mismatch-links.md`、
`topology-graph.md`、`topology_underlay.md`、`topology_evpn.md`、`evpn-control-plane-model.yaml`、
`evpn-session-links.csv`、`topology_overlay_service.md`、`overlay-service-model.yaml`、`overlay-service-links.csv`、
`overlay-services/`、`topology-graph.drawio` と、source／option／hash を記録した
`network-diagram-manifest.yaml` を出力する。role grouping は既定で有効、site grouping は metadata から自動判定し、
すべての diagram へ同じ値を適用する。既定方向は `TD` であり、横方向は `--direction LR` で選択する。draw.io の
主要方向の 4 view と Topology Confirmed Links を 9 page にまとめる場合は `--all-graph` を指定する。`BT`／`RL` も含む 17 page 版が必要な場合は
`--all-graph --directions TD,LR,BT,RL` を指定する。Overlay Service を除く 7／13 page は
`--no-overlay-service` で生成する。

Physical／Underlay の diagnostic 表示は次のとおりである。EVPN／Overlay Service の論理 edge には適用しない。

| 状態 | 表示 |
|---|---|
| 双方向 LLDP と description の不整合 | 赤色の実線、`⚠`、diagnostic code |
| 両端 config 収集済みの description 非相互 claim | 赤色の破線と方向、`⚠`、diagnostic code |
| 対向が inventory 外、または対向 link record がない片方向 description／LLDP | 通常 candidate の灰色破線。mismatch 扱いしない |
| warning | amber の線、`⚠`、diagnostic code |

線上の diagnostic code は 2 件まで表示し、それ以上は `+N more` とする。全件、影響 device、未解決 peer は
`mismatch-links.md` を正本として確認する。

Evidence Package、external import、Operation では、それぞれの Manifest から検証済み running config を host 単位で解決して
`topology_underlay.md` と EVPN model を生成する。直接 CSV／Containerlab YAML を使用する場合は、必要に応じて
`--underlay-raw` を指定する。

## 3. Mermaid

```bash
alred generate-mermaid \
  --input output/links_confirmed.csv \
  --link-diagnostics output/link-diagnostics.yaml \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --sites sites.yaml \
  --min-confidence medium \
  --group-by-site \
  --title "Physical Topology" \
  --output output/topology.md
```

出力は Mermaid を含む Markdown である。role grouping は既定で有効である。site grouping は inventory、Containerlab node、
または `sites.yaml` から 1 台以上の site を解決できる場合に自動的に有効になる。`--group-by-site` で常に有効、
`--no-group-by-site` で常に無効にでき、role grouping は `--no-group-by-role` で無効にできる。

## 4. Graphviz

```bash
alred generate-graphviz \
  --input output/links_confirmed.csv \
  --link-diagnostics output/link-diagnostics.yaml \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --min-confidence medium \
  --direction LR \
  --group-by-role \
  --output output/topology.dot
```

alredが生成するのはDOT fileまでである。Graphvizが別途導入されている環境では、例えば次のように画像化する。

```bash
dot -Tpng output/topology.dot -o output/topology.png
```

## 5. draw.io

```bash
alred generate-drawio \
  --input output/links_confirmed.csv \
  --link-diagnostics output/link-diagnostics.yaml \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --min-confidence medium \
  --direction LR \
  --group-by-role \
  --output output/topology.drawio
```

`--all-graph` は `Topology TD`、`Topology Confirmed Links TD`、`Topology LR`、`Underlay TD`、`Underlay LR`、
`EVPN TD`、`EVPN LR`、`Overlay Service TD`、`Overlay Service LR` の 9 page を 1 file へまとめる。
`Topology Confirmed Links TD` は
candidate link を含めない。candidate／claim などのため非表示になる診断がある場合は、page 上部の amber 警告欄に
非表示診断の総数と `CONFLICT`／`WARNING`／`UNKNOWN` 別件数を表示する。詳細は `mismatch-links.md` を確認する。
警告欄は非表示 link を confirmed へ昇格させない。`--directions TD,LR,BT,RL` を追加すると、反転方向を含む 17 page を生成する。
`--no-overlay-service` では Overlay Service page を生成しない。
EVPN LR の Spine–Leaf session は Spine の右側から Leaf の左側へ接続し、遠い反対側を経由しない。Overlay Service Summary は
route leak の向きを優先し、最大次数の service を hub とする。TD は hub を上段、直接接続する service 群を下段へ横並びにし、
LR は hub を左列、直接接続する service 群を右列へ縦並びにする。相互 import／export による逆方向 edge は別 lane に分けて表示する。

## 6. Underlay 表示

```bash
alred generate-mermaid \
  --input output/links_confirmed.csv \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --view underlay \
  --underlay-config underlay.yaml \
  --underlay-raw raw \
  --output output/topology-underlay.md
```

underlay addressがraw configから解決できない場合、推測値で補完されない。対象role、VRF、interface、labelは
`underlay.yaml`で指定し、生成後に欠落node／linkを確認する。

Underlay diagram は `target_roles` に両 endpoint が一致する link と、同 role の未結線 node だけを表示する。
server／host／Kind member など対象外 role の片方向 endpoint は描画しない。
既存 `--underlay` は `--view underlay` の互換 alias である。Underlay RR は role expectation だけでは表示せず、
running config の Underlay AF で RR client を確認できた場合だけ表示する。

## 7. EVPN control plane 表示

```bash
alred generate-mermaid \
  --view evpn \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --sites sites.yaml \
  --underlay-raw raw \
  --output output/topology_evpn.md
```

EVPN view は物理 interface や Underlay prefix を表示しない。exact neighbor または operational peer で endpoint を確認できた
session だけを edge とし、dynamic neighbor range 単独、role expectation、hostname 類似から session を生成しない。
`configured`／`unknown` は破線、operational state を確認した session は state 名付きで表示する。
NVE source-interface の secondary address が vPC 構成を持つ複数 node で一致する場合は、
`VTEP (vPC shared)` と表示する。これは EVPN route Type ごとの VTEP 分類ではない。
個別 `generate-graphviz`／`generate-drawio` でも `--view physical|underlay|evpn|overlay-service` を使用できる。

## 8. Overlay Service 表示

```bash
alred generate-mermaid \
  --view overlay-service \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --sites sites.yaml \
  --underlay-raw raw \
  --output output/topology_overlay_service.md
```

Overlay Service view は物理 link や Underlay session を表示せず、service と有向 route leak を表示する。`--site`、`--vrf`、
`--l2vni`、`--l3vni`、`--service` は repeatable selector であり、複数指定は union とする。直接 route leak で接続する service は
context として 1 hop だけ含める。

`generate-network-diagram` は service Detail を `overlay-services/` に既定 20 件まで生成する。上限は
`--overlay-detail-limit <count>`、全件は `--all-overlay-details` で指定する。規模が大きい環境では Summary、selector、既定上限を
使用し、必要な service だけを展開する。

Detail の既定形式は Markdown である。VRF 単位の draw.io Detail が必要な場合だけ、次のように形式を明示する。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id> \
  --service site-1/tenant1-vpc1 \
  --overlay-detail-format markdown,drawio \
  --output-dir output/overlay-tenant1
```

draw.io Detail は VRF、L3VNI、RD、L3VNI Mode、placement／VTEP、device-local VLAN／SVI binding、Gateway、明示 SVI address、
import／export RT、直接 route leak の隣接 service を 1 page に表示する。上から Inbound／Outbound、中央の Service、
L3VNI Interface／L2 Services、Placement の 4 段とする。edge は Service から L3VNI／L2 component、component から対応する
Placement へ接続し、Placement と Service は直接接続しない。`--all-overlay-details --overlay-detail-format markdown,drawio` は全 service の
両形式を生成するため、VRF 数が多い環境では selector の使用を推奨する。
Inbound／Outbound の RT は、local L3VNI の `Same-VRF Import／Export`、対向 service を解決した
`Inbound／Outbound Route Leak`、対向を解決できない `Additional Import／Export RT` に分ける。Route Leak node は From／To、RT、AF、
state をまとめて表示し、同じ RT の単独 node を重複生成しない。同じ RT が Same-VRF と Route Leak の両用途を持つ場合だけ、両方へ表示する。

Detail は同じ VRF を持つ全 node を同じ Placement として扱わない。L3VNI／NVE evidence がある node と L2-only VTEP は
`EVPN Placements`、VRF だけを持つ node は `Service Edge Attachments` へ分離する。Service Edge は Service へ
`VRF attachment` として接続し、L3VNI／L2 component へは接続しない。
Placement と各 component の device-local binding edge は 40 relation まで表示する。40 relation を超える場合は交差線による
可読性低下を避けるため edge を省略し、node 別の正本は Markdown Detail で確認する。binding を解決できない Placement は
誤接続せず、`Component binding: unresolved` と表示する。
binding edge は membership のみを表すため、VLAN／SVI label を表示しない。component 内では `VLAN 20 (SVI)` または
`VLAN 20 (L2-only)` と表示し、同じ ID の `Vlan20` を重複表示しない。Traditional L3VNI は
`VLAN 3000 (L3VNI SVI: ip-forward)` と表示する。

同じ vPC domain と shared VTEP を持つ 2 台の Placement は、個別 node を維持したまま vPC container にまとめる。これは表示上の
grouping であり、orphan port や片系だけの VLAN／SVI を同一と推測しない。vPC evidence が不足または曖昧な場合は group 化しない。
両 member が同じ component binding を持つ場合は container から 1 本の edge にまとめる。一方だけに binding がある場合は
非対称状態を見えるように、その Placement の個別 edge を残す。

Markdown Detail の RT は、`auto` から解決した値を `65001:9001 (auto)` と表示する。L2 Service の Gateway は明示 config から
`yes`／`no`／`mixed`／`unknown` を判定し、IPv4／IPv6 SVI address を推測せず表示する。
L3VNI Mode は `New L3VNI (VLAN/SVI-less)` または `Traditional VLAN/SVI` と表示する。VLAN が Leaf ごとに異なる場合は
service 共通値へ丸めず、Markdown の node 別 row と draw.io component の binding に保持する。

## 9. Containerlab YAML から描画する

```bash
alred generate-mermaid \
  --input output/topology.clab.yaml \
  --input-format clab \
  --group-by-role \
  --output output/topology-from-clab.md
```

`topology.links[*].endpoints`をlink、`topology.nodes`をnodeとして読み、未結線nodeも表示する。

## 10. 収集 source から Mermaid まで一括生成

`generate-mermaid` は共通 normalizer を内部呼び出し、最新 Operation、特定 Operation、Evidence Package、
external running config import から直接描画できる。

```bash
alred generate-mermaid --latest-operation

alred generate-mermaid \
  --evidence-package imported-evidence/<package-id>
```

内部処理は `normalize-links` と同じ source resolver、parser、confidence、canonical sort を使用する。
renderer 内に別の link 解析は実装しない。
Evidence Package では Package 内の解決済み role／site metadata を使用するが、grouping の既定判定は他の source と共通である。

## 11. 一括構成資料と CSV table

`generate-doc`はconfirmed CSVからContainerlab YAMLとMermaidを一括生成する。Containerlab固有optionと確認事項は
[Containerlab Manual](../containerlab/README.md)を参照する。

```bash
alred generate-doc \
  --input output/links_confirmed.csv \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --include-nodes \
  --output-clab output/topology.clab.yaml \
  --output-md output/topology.md
```

任意CSVをMarkdown tableへ変換する場合は`csv-to-md`を使用する。このcommandはtopologyの意味を解析しない。

```bash
alred csv-to-md \
  --csv-file output/links_confirmed.csv \
  --output-file output/links_confirmed.md
```
