# EVPN Control Plane Diagram Design

## 1. 目的と実装状態

本書は、物理 topology および Underlay routing diagram から EVPN control plane の責務を分離し、
EVPN BGP session、Route Reflector、client、VTEP を独立した diagram として生成する仕様を定める。

本仕様の初期 NX-OS 対応は実装済みである。`generate-network-diagram` は Physical、Underlay、EVPN の成果物を
同じ固定 source から生成し、個別 renderer は `--view` で表示責務を選択する。対応範囲と残課題は
[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md) を参照する。

物理 link と confidence は
[Link Discovery and Normalization Design](LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)、共通 renderer と成果物公開は
[Topology Rendering Design](TOPOLOGY_RENDERING_DESIGN.md)、topology role と function は
[Role Definition and Resolution Design](../common/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)、EVPN の収集・解析・正常性判定は
[Overlay Change Management Design](../network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md) を正本とする。

## 2. Diagram の責務分離

| view | 表示対象 | 表示しない情報 |
|---|---|---|
| `physical` | node、物理 link、interface、任意の管理 address | routing neighbor、EVPN session、VNI |
| `underlay` | routed link、接続 interface address、Router ID／Loopback、Underlay protocol、Underlay RR | EVPN RR、VTEP、EVPN session、VNI |
| `evpn` | EVPN BGP session、EVPN RR／client、VTEP、session state | 物理 interface、Underlay routed link、tenant service |
| `overlay-service` | VRF、L2VNI、L3VNI、RD／RT、NVE membership、route leak | 物理 topology、Underlay routing、EVPN BGP session |

`topology_underlay.md` から `(BGP-RR)` のような AF を特定しない表示を廃止する。Underlay AF の
Route Reflector を実効設定から確認できる場合だけ `(Underlay RR)` と表示する。`evpn-route-reflector` function、
L2VPN EVPN AF、EVPN RR client は EVPN view だけで使用する。

EVPN view は control plane の BGP session を対象とする。VNI、VRF、RT、NVE data-plane tunnel を同じ diagram へ
重ねない。これらは
[Overlay Service Diagram Design](OVERLAY_SERVICE_DIAGRAM_DESIGN.md) に従う独立 view へ分離する。

## 3. Canonical EVPN Control Plane Model

renderer が running-config や show command を直接解釈しないよう、解析結果を
`EVPNControlPlaneModel` として固定する。外部保存形式は YAML、envelope は `api_version: alred/v1` と
`kind: EVPNControlPlaneModel` とする。JSON Schema Draft 2020-12 の package resource で生成時に検証する。

```yaml
api_version: alred/v1
kind: EVPNControlPlaneModel
metadata:
  source:
    type: evidence-package
    value: imported-evidence/<package-id>
  source_manifest_sha256: sha256:<digest>
spec:
  status: complete
  parser_versions:
    running_config: <version>
    bgp_l2vpn_evpn_summary: <version>
  nodes:
    adc-spsw0101:
      topology_role: spine
      site: adc
      functions:
        - evpn-route-reflector
      observed_functions:
        - evpn-route-reflector
      router_id: 10.0.0.254
      update_source_addresses:
        - 10.0.0.254
      vtep_addresses: []
      vpc_domain: null
      vpc_shared_vtep_addresses: []
      cluster_ids: []
      evidence_refs:
        - adc-spsw0101:running_config
  sessions:
    - session_id: <stable-id>
      endpoints:
        - node: adc-lfsw0101
          address: 10.0.0.1
          local_as: "65001"
        - node: adc-spsw0101
          address: 10.0.0.254
          local_as: "65001"
      relationship: rr-client
      rr_node: adc-spsw0101
      client_node: adc-lfsw0101
      state: established
      resolution_status: confirmed
      observations: []
      evidence_refs: []
  peer_ranges: []
  unresolved_peers: []
  diagnostics: []
```

### 3.1 Node

node は hostname を key とし、次を保持する。

- canonical `topology_role`
- `evpn-route-reflector`、`vtep` など解決済み function
- BGP Router ID
- EVPN neighbor の update-source として使用できる address
- VTEP／NVE source address
- vPC domain と、複数の vPC node で同一 secondary address を確認した shared VTEP address
- EVPN cluster ID の一覧
- `hostname:command_id` 形式の stable `evidence_refs`

source Manifest、入力 file path と hash は `metadata.source_manifest_sha256` および `NetworkDiagramManifest`、parser version は
`spec.parser_versions` へ記録する。`evidence_refs` とこれらを組み合わせ、各 node／session の入力へ追跡できるようにする。

role の期待値と実効設定を分離する。`roles.yaml` で function が `required` でも、設定証跡がなければ
configured と推測しない。逆に、設定から EVPN RR／VTEP を確認できた場合は、role expectation の欠落を diagnostic として
保持し、観測済み機能を黙って除外しない。

### 3.2 Session

session は endpoint pair 単位で重複排除し、各 device からの片方向 observation を保持する。

| field | 値 |
|---|---|
| `relationship` | `rr-client`、`ibgp-peer`、`ebgp-peer`、`unknown` |
| `state` | `established`、`down`、`configured`、`unknown`、`conflict` |
| `resolution_status` | `confirmed`、`unresolved`、`conflict` |
| `observations` | observer、peer address、AS、state、configured、収集時刻、evidence reference |

`session_id` は正規化した endpoint node／address と relationship から決定的に生成する。同じ Collection／Snapshot 内で
両端の state が矛盾する場合は `conflict` とし、正常側へ自動統合しない。

### 3.3 Peer range と未解決 peer

`neighbor 10.0.0.0/24` のような dynamic neighbor range を単一 device endpoint として扱わない。range は
`peer_ranges` に設定証跡として保持し、exact neighbor または operational peer を確認した場合だけ session を生成する。
ただし、対向 device の exact neighbor または operational peer により session endpoint を確認できた後は、その address と
一致する range の effective peer template を RR 側 observation へ適用できる。これにより dynamic neighbor を使用する RR でも、
既存 session の `rr-client` relationship を判定する。range だけから endpoint を列挙せず、同じ address に複数の
effective range が一致する場合は `conflict` とする。

peer address を hostname へ解決できない場合は `unresolved_peers`、複数 node に一致する場合は diagnostic の
`EVPN_PEER_AMBIGUOUS` とする。曖昧な peer を confirmed session へ昇格しない。既定 diagram では未解決 peer を
logical node として描画せず、件数と理由を注記する。将来明示 option で表示する場合も unresolved styling を必須とする。

## 4. 入力と evidence precedence

`generate-network-diagram` は指定 source の Manifest から検証済み artifact だけを解決する。Evidence Package、external import、
Operation と local `raw/` を暗黙に混在させない。

evidence は次の順に使用する。

1. `show bgp l2vpn evpn summary` の parsed Snapshot で operational peer と state を取得する。
2. running-config の BGP process、L2VPN EVPN AF、neighbor、peer template、`inherit peer`、`remote-as`、
   `update-source`、`route-reflector-client`、cluster ID を解決する。
3. running-config の Loopback／NVE source address と inventory／mapping で peer address を node へ対応付ける。
4. `roles.yaml` の topology role と function expectation を node 分類と不一致診断へ使用する。

operational evidence は state の正本とするが、running-config evidence を捨てない。running-config だけで endpoint を一意に
解決できる session は `configured` として dashed line で描画する。role expectation だけから session edge を生成しない。
収集に成功した summary に設定済み peer が存在しない場合も、その事実だけから `down` と推測せず `unknown` とし、
config observation と operational observation の不足を記録する。summary が `Idle`、`Active` など非 Established state を
明示した場合だけ `down` とする。

既存の Overlay running-config parser を拡張し、EVPN effective neighbor と peer template 継承結果を出力する。
diagram 専用の BGP parser を重複実装しない。既存 `evpn_bgp` Snapshot parser も operational observation として再利用する。

## 5. Address 解決

peer address は次の候補から exact match で解決する。

1. BGP Router ID
2. EVPN neighbor の effective update-source interface address
3. Loopback primary／secondary address
4. 明示 mapping で解決した address

候補が 0 件なら unresolved、2 件以上なら conflict とする。prefix 内包含、hostname 類似、role、連番から peer node を
推測しない。pseudonymized Evidence Package では同一 token mapping により両側を一貫変換できた場合だけ解決し、address が
除外・非一貫 mask された場合は `insufficient-evidence` または unresolved とする。

## 6. EVPN view の表示仕様

### 6.1 Node label

- EVPN RR: hostname、`EVPN RR`、Router ID、任意の cluster ID
- VTEP: hostname、`VTEP`、Router ID、VTEP address
- vPC shared VTEP: NVE source-interface の secondary address が vPC 構成を持つ 2 台以上で一致した場合だけ
  `VTEP (vPC shared)` と表示
- EVPN peer: hostname、Router ID
- function expectation と実効設定が不一致の場合は `Expected`／`Observed` を分離して注記

server、Kind member、EVPN／VTEP 証跡を持たない `network-functions` は既定で除外する。role だけで一律除外せず、
対応 platform の EVPN evidence がある場合は node として保持する。

secondary address が 1 台だけで確認された場合や、vPC 構成を確認できない場合は shared と推測せず、通常の `VTEP` として
表示する。EVPN route Type-2／Type-3／Type-5 ごとに VTEP address を分類しない。

### 6.2 Edge

| state | 表示 |
|---|---|
| `established` | solid line、`Established` |
| `down` | solid line、非正常 state 名 |
| `configured` | dashed line、`Configured / state unknown` |
| `unknown` | dashed line、`Unknown` |
| `conflict` | conflict styling、両 observation の要約 |

edge label は relationship、AS、state を表示し、物理 interface 名と Underlay prefix は表示しない。Mermaid と draw.io で
node／session 集合、状態、label の意味を変えない。色だけに依存せず、line style と text を併用する。

## 7. 成果物と CLI

`generate-network-diagram` は次の成果物を生成する。

| file | 内容 |
|---|---|
| `evpn-control-plane-model.yaml` | canonical node／session／diagnostic と provenance |
| `evpn-session-links.csv` | review 用の正規化済み session 一覧 |
| `topology_evpn.md` | Mermaid EVPN control-plane diagram |
| `topology-graph-all.drawio` | Physical／Underlay／EVPN の multi-page diagram |
| `network-diagram-manifest.yaml` | 全入力、model、artifact、実効 view、hash |

個別 renderer は boolean option を追加せず、次の共通 option を使用する。

```bash
alred generate-mermaid --view evpn
alred generate-graphviz --view evpn
alred generate-drawio --view evpn
```

`--view` は `physical`、`underlay`、`evpn`、`overlay-service` を受け付け、既定は `physical` とする。既存 `--underlay` は後方互換 alias として
`--view underlay` へ解決する。`--underlay` と `--view physical|evpn` の同時指定は validation error とする。

`generate-network-diagram` は既定で 4 view を同じ固定 source から生成する。EVPN evidence がない場合も artifact や page を
黙って省略せず、model を `status: insufficient-evidence` とし、diagram に理由を表示する。

`--all-graph` の既定 `TD,LR` では、次の EVPN までの 6 page に `Overlay Service TD`／`Overlay Service LR` と
`Topology Confirmed Links TD`／`Topology Defined Roles TD` を `Topology TD` の直後へ追加した 10 page を生成する。

1. `Topology TD`
2. `Topology LR`
3. `Underlay TD`
4. `Underlay LR`
5. `EVPN TD`
6. `EVPN LR`

`--directions TD,LR,BT,RL` 指定時は 4 view × 4 direction と Topology Confirmed Links／Topology Defined Roles の
18 page とする。
`--no-overlay-service` を指定した場合は 8／14 page とする。page 名、view 順、direction 順を固定する。

## 8. 不足 evidence と error

| 条件 | 動作 |
|---|---|
| EVPN 設定なし | model は `insufficient-evidence`、EVPN page に設定なしと表示 |
| running-config のみ | configured session を生成し、operational state は `unknown` |
| `show bgp l2vpn evpn summary` のみ | mapped session を生成し、設定 relationship が不明なら `unknown` |
| peer address 未解決 | confirmed edge にせず `unresolved_peers` へ記録 |
| peer address が複数 node に一致 | `conflict` とし、自動選択しない |
| parser unsupported／Manifest hash 不一致 | 既存 `PARSER_UNSUPPORTED`／integrity error で生成を停止 |

一部 peer が unresolved でも解決済み session の diagram は生成できる。この場合は model／Manifest を `partial` とし、CLI は
warning 終了 code `1` を返す。入力 Manifest、schema、hash の検証失敗は部分生成せず、以前の公開済み artifact を維持する。

EVPN model 内の `diagnostics` は次の識別子を使用する。これらは diagram の evidence coverage を示す診断であり、共通
[Error Catalog](../common/ERROR_CATALOG.md) の CLI error code とは分離する。

| 診断 ID | 条件 | session edge |
|---|---|---|
| `EVPN_PEER_UNRESOLVED` | peer address を node へ解決できない | 生成せず `unresolved_peers` へ記録 |
| `EVPN_PEER_AMBIGUOUS` | peer address が複数 node に一致する | 生成せず `conflict` として記録 |
| `EVPN_PEER_TEMPLATE_UNRESOLVED` | peer template の参照先がない、または循環して実効設定を解決できない | 解決できない observation から edge を生成しない |
| `EVPN_SESSION_STATE_CONFLICT` | 両端または複数 evidence の state が矛盾する | edge を生成し、state を `conflict` と表示 |
| `EVPN_ROLE_FUNCTION_MISMATCH` | 設定済み RR／VTEP と role function が矛盾する | evidence に基づく edge を生成し、warning を付与 |

## 9. Publish と再実行

Physical、Underlay、EVPN、Canonical EVPN Model、CSV、draw.io、Manifest は同じ staging attempt で生成する。schema、hash、
page 数、artifact 一覧を検証してから atomic publish し、途中失敗で Physical だけが新世代へ切り替わる状態を作らない。

`network-diagram-manifest.yaml` は source Manifest、Collection／Snapshot ID、roles／sites、parser version、model hash、
renderer version、実効 view／direction、成果物 hash を記録する。同じ固定入力と version から stable order の同じ model と
diagram を再生成できることを要求する。

## 10. 初期 NX-OS 対応範囲

初期実装は NX-OS の次を対象とする。

- global BGP L2VPN EVPN AF
- exact neighbor と peer template 継承
- internal／明示 remote AS
- Loopback update-source
- EVPN `route-reflector-client`
- cluster ID
- `show bgp l2vpn evpn summary` の peer state
- roles schema version 2 の `evpn-route-reflector`／`vtep`

dynamic neighbor range は evidence として保持するが、range 単独から session を生成しない。EVPN Multi-Site 固有 session、
route-server、NVE tunnel、VNI／RT service graph は本 view の対象外とする。VNI／RT service graph は独立した
`overlay-service` view が所有する。

## 11. Test 要件

- peer template の複数段継承、direct override、循環、未解決 template
- exact neighbor と Router ID／Loopback address の一意 mapping
- dynamic neighbor range を device endpoint にせず、確認済み session への effective template 適用だけに使うこと
- overlapping dynamic neighbor range を `conflict` とすること
- unilateral／bilateral config、operational state、state conflict
- role expectation だけから session を生成しないこと
- Underlay view に EVPN RR／VTEP 表示が残らないこと
- EVPN view に物理 interface／Underlay prefix が混入しないこと
- evidence 不足、unresolved、ambiguous、pseudonymized address
- Mermaid／Graphviz／draw.io の node／session parity
- draw.io の既定 10 page、全 direction 18 page、`--no-overlay-service` の 8／14 page の名称・順序
- staging 失敗時に以前の model／diagram／Manifest を維持すること
- hash seed、input row／YAML rule 順に依存しない stable output

single-site Fabric sample では、Spine 2 台を EVPN RR、Leaf 4 台を VTEP とし、Leaf から各 RR への計 8 session を
config evidence から生成する golden test を用意する。operational show output がない sample の state は
`configured` とし、`Established` と推測しない。
