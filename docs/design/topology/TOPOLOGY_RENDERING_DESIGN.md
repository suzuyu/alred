# Topology Rendering Design

## 1. 目的

本書はcanonical linkからMermaid、Graphviz、draw.ioおよび構成資料を生成する共通仕様を定める。linkの意味と
confidenceは[Link Discovery and Normalization Design](LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)、containerlab nodeと
mergeは[Containerlab Workflow Design](../containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)を正本とする。
EVPN BGP session と EVPN RR／VTEP を描画する論理 topology は
[EVPN Control Plane Diagram Design](EVPN_CONTROL_PLANE_DIAGRAM_DESIGN.md) を正本とし、物理 link model と混在させない。
VRF／VNI／RD／RT、NVE membership と VRF 間 route leak は
[Overlay Service Diagram Design](OVERLAY_SERVICE_DIAGRAM_DESIGN.md) を正本とし、EVPN session model と分離する。

Terraform `main.tf`生成はcanonical linkやrender modelを使用しないため、本書の対象外とする。正本は
[Terraform Inventory Generation Design](../common/TERRAFORM_INVENTORY_GENERATION_DESIGN.md)である。

現行実装の根拠は[Topology and Rendering As-Is](../../as-is/TOPOLOGY_AND_RENDERING_AS_IS.md)を参照する。

## 2. 共通render model

rendererは入力形式ごとのadapterでlinkとnodeを共通modelへ変換し、次を一度だけ適用する。

1. `min-confidence`によるconfirmed linkのfilter
2. hostname／interface normalizationとexclude
3. role priority、次にnode名によるendpoint ordering
4. canonical endpoint pairによるdeduplication
5. stable sort
6. optional candidate、role、site、address metadataの付加

CSV、containerlab YAMLのどちらを入力にしても、同じcanonical link集合から同等のnode/link関係を生成する。
format固有の表現差は許容するが、linkの追加・削除を暗黙に行わない。

legacy rendererが使うsingle-role detectorと、Health Check／Overlayのcanonical multi-role resolverは意味が異なる。
複数roleをgroup化する仕様を決めるまでは、既存のgroup名を互換動作として維持し、canonical roleへ自動変更しない。

## 3. Diagram output

| command | output | 主な特性 |
|---|---|---|
| `generate-network-diagram` | Markdown + draw.io XML + Manifest | link 正規化と主要 diagram の一括生成 |
| `generate-mermaid` | Markdown | Mermaid flowchart |
| `generate-graphviz` | DOT | Graphviz graph |
| `generate-drawio` | draw.io XML | 編集可能なdiagram |
| `generate-doc` | containerlab YAML + Markdown | clabとMermaidの一括生成 |
| `csv-to-md` | Markdown | 汎用CSV table変換 |

candidate は confirmed と区別できる線種・注記で表示する。`generate-mermaid` の role grouping は既定で有効とし、
`--no-group-by-role` で無効化する。site grouping は source 種別ではなく、inventory の `site`、Containerlab node label、
または解決済み `sites.yaml` rule から 1 台以上の site を解決できた場合に自動的に有効化する。明示的な
`--group-by-site` は metadata がない場合も `default` site へ group 化し、`--no-group-by-site` は自動判定を無効化する。
node に明示した site は hostname の `sites.yaml` rule より優先し、命名規則で上書きしない。
site の `priority` は数値が小さい順とし、未指定または未定義の site は `1000` とする。
role group は `roles.yaml` の `priority` 数値が小さい順に出力する。同一 priority は role 名で決定的に並べ、
Mermaid source 上で上から順に subgraph を定義する。
draw.io は同一 priority の role を同じ layout band に配置し、`TD` では横並び、`LR` では縦並びにする。
Mermaid は source 順を固定するが、layout engine が最終配置を決めるため、同一 priority の横並びは保証しない。
ただし、Overlay Service Summary は node 間の有向 route leak を主題とするため、同一 `overlay-service` role 内を
route leak の無向 adjacency から決定的な hub-and-spoke rank へ配置する。connected component ごとに隣接 service 数が最大の
node を hub とし、同数の場合は canonical service ID の昇順で選択する。hub からの最短 hop 数を rank とする。`TD` は hub を
上段、次 rank の service 群を下段で横並びにし、`LR` は hub を左列、次 rank の service 群を右列で縦並びにする。同じ rank の
service を経由して遠い service へ edge を引かない。この例外は Physical／Underlay／EVPN および Overlay Service Detail の
role band には適用しない。

draw.io の論理 link のように interface endpoint がない場合も、配置後の node 座標から相手に最も近い側を決定し、edge を
その側へ接続する。横に離れた node は右側と左側、縦に離れた node は下側と上側を使用する。同じ node pair に逆方向の
有向 edge がある場合は、中央で完全に重ならない 2 つの lane へ分離し、arrow と label を個別に追跡できるようにする。
Evidence Package だけに別の描画既定値を持たせず、Package 内の `roles.resolved.yaml` と `sites.resolved.yaml` も同じ判定へ
入力する。管理 address、underlay address と link label は明示 option で有効化する。raw config 不足時は該当 label を欠落として
扱い、誤った address を補完しない。

Mermaid の方向は、縦長の構成を上から下へ追いやすい `TD` を既定とし、`generate-mermaid`、
`generate-network-diagram`、`generate-doc` で統一する。横方向が必要な場合は `--direction LR` を明示する。
Graphviz と単体 draw.io renderer の既定方向も `TD` とする。

draw.io `--all-graph` は、`TD` と `LR` について Physical、Underlay、EVPN、Overlay Service を作成し、
candidate を除外した `Topology Confirmed Links TD` を加えた計 9 page を
1 file へ格納する。page 名と順序は `Topology TD`、`Topology Confirmed Links TD`、`Topology LR`、
`Underlay TD`、`Underlay LR`、`EVPN TD`、`EVPN LR`、`Overlay Service TD`、`Overlay Service LR` とする。
`Topology Confirmed Links TD` は
`--directions` の先頭方向を使用し、`links_confirmed.csv` の link と endpoint node だけを描画する。
`--no-overlay-service` を指定した場合は 7 page とする。`--directions TD,LR,BT,RL` を明示した場合は
Overlay Service を含むと 17 page、除外すると 13 page とする。詳細は
[Overlay Service Diagram Design](OVERLAY_SERVICE_DIAGRAM_DESIGN.md) を参照する。
`--directions` は comma 区切りの `TD`、`LR`、`BT`、`RL` を受け付け、指定順を Physical、Underlay、EVPN の
各 page 順に反映する。
`--all-graph` を伴わない `--directions` は validation error とする。

`csv-to-md`はtopology意味を解釈しない汎用adapterである。先頭rowをheaderとし、最大列数へ空cellを補い、
Markdownのpipeと改行をescapeする。空CSVはvalidation errorとする。

### 3.1 `generate-network-diagram`

Quick Start の標準 command として、次の source selector のいずれかから共通 normalizer を 1 回だけ実行し、同じ canonical link、
inventory、mapping、role、site を使って diagram を生成する。

- `--evidence-package <imported-package-directory>`
- `--running-config-import <import-root>`
- `--latest-operation`
- `--change-id <operation-id>`
- `--input <confirmed-csv-or-containerlab-yaml>`

既定成果物は次のとおりとする。

| file | 内容 |
|---|---|
| `topology-graph.md` | 管理 address を含む Mermaid topology |
| `topology_underlay.md` | Loopback と接続 interface address を含む Mermaid Underlay |
| `evpn-control-plane-model.yaml` | EVPN node／session／diagnostic と provenance |
| `evpn-session-links.csv` | review 用の EVPN session 一覧 |
| `topology_evpn.md` | EVPN BGP session、RR／client、VTEP の Mermaid diagram |
| `overlay-service-model.yaml` | VRF／VNI／RD／RT、NVE membership、route leak と provenance |
| `overlay-service-links.csv` | service と有向 route leak の review 用一覧 |
| `topology_overlay_service.md` | Overlay Service Summary の Mermaid diagram |
| `overlay-services/` | selector／上限に従う service Detail |
| `topology-graph.drawio` | topology の draw.io XML |
| `network-diagram-manifest.yaml` | source、実効 option、入力・成果物 hash |

`--all-graph` 指定時は `topology-graph.drawio` の代わりに `topology-graph-all.drawio` を生成する。既定は 9 page、
`--directions TD,LR,BT,RL` 指定時は 17 page とする。`--no-overlay-service` では 7／13 page とする。
role grouping は既定で有効、site grouping は解決済み metadata により
自動判定し、全 view で同じ実効値を使う。

Underlay の running config は、Evidence Package では検証済み Package Manifest、external import では Import Manifest、Operation
では Collection Manifest から host 単位に解決する。これらの source では local `raw/` を暗黙に混在させない。直接 CSV／
Containerlab YAML を指定した場合だけ `--underlay-raw` を使用する。address がない場合は推測値を生成しない。
Underlay の node は `target_roles` に両 endpoint が一致する link と、`target_roles` に一致する未結線 node に限定する。
server／host／Kind member など対象外 role の片方向 endpoint は Underlay diagram に表示しない。
Underlay view は EVPN RR、VTEP、EVPN BGP session を表示しない。AF を特定しない `(BGP-RR)` 表示は使用せず、
Underlay RR を実効設定から確認できる場合だけ `(Underlay RR)` と表示する。EVPN view の model、evidence、表示仕様は
[EVPN Control Plane Diagram Design](EVPN_CONTROL_PLANE_DIAGRAM_DESIGN.md) に従う。
Overlay Service view の service identity、selector、route leak、Detail 上限、表示仕様は
[Overlay Service Diagram Design](OVERLAY_SERVICE_DIAGRAM_DESIGN.md) に従う。

全 view と canonical model は staging directory で全生成と Manifest schema 検証を完了してから file 単位で atomic publish する。render 失敗時は
既存の公開済み diagram を維持し、Manifest は全 artifact の公開完了後にだけ更新する。正規化済み link artifact は共通
normalizer の publish 規則に従う。

`generate-network-diagram` は atomic publish 完了後、stdout の最後に `Diagrams`、生成された場合の
`Overlay Service details`、`Status` だけを含む結果 summary を表示する。model が完全なら `Status: SUCCESS`、artifact は公開したが
EVPN または Overlay Service model が `partial` なら `Status: PARTIAL` とし、従来どおり終了 code `1` を返す。publish 前の例外では
成功または partial summary を表示しない。詳細な model、CSV、Manifest は summary に列挙せず、既存 log と Manifest を正本とする。

output directory の表示は command に指定された `--output-dir` を `Path` として正規化した表示文字列で判定する。root anchor と `.` を
階層数から除き、次の両方を満たす場合は各 diagram path と Detail directory に output directory を付ける。

- 階層数が 2 以下
- 末尾 `/` を除いた `/` 込みの表示文字数が 16 以下

どちらかを超える場合は `Output directory` を 1 回だけ表示し、`Diagrams` は file name、`Overlay Service details` は
`overlay-services/` と形式別 file 数だけを表示する。Detail file は多数になる可能性があるため個別列挙しない。生成されなかった
optional diagram／Detail section は表示しない。

## 4. Determinism

同じcanonical input、mapping、role、site、render optionからはbyte単位で同じ出力を生成することを目標とする。
node、link、group、pageはstable sortし、入力CSVのrow順やPython hash seedに依存しない。日時などの可変metadataを
埋め込む場合は明示optionとする。

## 5. Underlay view

underlay configは対象role、VRF、loopback/interface、表示labelを定義する。running config parserは指定VRFと
interfaceに一致するprimary／secondary addressだけを採用する。addressが解決できないnode／linkは、推測値を
表示せず欠落として残す。

Underlay view は routed link と Underlay address／protocol の表示に限定する。EVPN AF の RR client、VTEP、NVE、VNI は
表示しない。Underlay AF の RR は `underlay-route-reflector` の期待値だけで推測せず、実効 BGP 設定を証跡にする。

underlay rawは機器情報を含むためcommitしない。diagramを共有する場合もaddressとhostnameの機密性を確認する。

## 6. Containerlab boundary

containerlabでは物理endpointとして扱えないport-channel linkを除外する。node kind、management address、startup
config、merge precedence、table-driven validationは
[Containerlab Workflow Design](../containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)へ委譲する。

`generate-doc`はcontainerlabとMermaidの既存処理を再利用し、独自のlink判定を持たない。`generate-network-diagram` は
Containerlab YAML を生成しない diagram 専用 command であり、`generate-doc` の互換責務を置換しない。

## 7. Errorとvalidation

- 入力形式を判別できない、必須headerがない、link endpointが空の場合はvalidation errorとする。
- role/site/mapping fileのschema不正を黙ってdefaultへ置換しない。
- output writerは親directoryを作成し、完成後にatomicに公開することが望ましい。
- candidate、confidence skip、metadata欠落の件数をlogへ記録する。
- Graphvizやdraw.io applicationの起動は行わず、file生成までを責務とする。

## 8. Test要件

- CSVとcontainerlab入力から同一link集合になること
- confidence境界、exclude、endpoint ordering、deduplication
- Mermaid、DOT、draw.ioのgolden testとhash seed差分
- draw.io の既定 9 page／全方向 17 page と、`--no-overlay-service` の 7／13 page の名称・順序、および
  `Topology Confirmed Links <direction>` に candidate link が含まれないこと
- role/site groupingとunderlay address欠落
- Underlay／EVPN view の責務分離と model parity
- malformed CSV/YAMLのcode付きerrorとpartial file非公開
