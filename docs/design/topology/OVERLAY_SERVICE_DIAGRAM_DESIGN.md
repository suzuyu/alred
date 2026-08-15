# Overlay Service Diagram Design

## 1. 目的と実装状態

本書は、EVPN Fabric 上の VRF、L2VNI、L3VNI、RD／RT、NVE membership と、VRF 間の
route-target import／export による route leak を、物理 topology、Underlay routing、EVPN control plane から
分離して描画する仕様を定める。

初期実装として、`generate-network-diagram`、`generate-mermaid`、`generate-graphviz`、`generate-drawio` の
`overlay-service` view、`OverlayServiceModel`、有向 route leak、既定 8 page 出力に対応している。保存済み
`OverlayState` を直接優先入力とする adapter と `sampled` verification は未実装である。詳細な実装状態は
[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md) を参照する。

物理 link は [Link Discovery and Normalization Design](LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)、EVPN BGP session は
[EVPN Control Plane Diagram Design](EVPN_CONTROL_PLANE_DIAGRAM_DESIGN.md)、共通描画と公開処理は
[Topology Rendering Design](TOPOLOGY_RENDERING_DESIGN.md)、現在の Type-5 正常性判定は
[NX-OS Overlay Role Health Check Catalog](../network-ops/NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md) を正本とする。

初期実装は検証済み evidence の解析、model 化、状態判定、描画までを対象とする。route-target、VRF、VNI の
config 生成、投入、rollback は対象外とし、既存の Overlay Change と Direct Config Push へ暗黙に接続しない。

## 2. View の責務

| view | 主な表示対象 | 表示しない情報 |
|---|---|---|
| `physical` | node、物理 link、interface | routing session、VNI、service |
| `underlay` | routed link、address、Underlay protocol／RR | EVPN RR、tenant service |
| `evpn` | EVPN BGP session、EVPN RR／client、VTEP | tenant の VRF／VNI、route leak |
| `overlay-service` | VRF、L2VNI、L3VNI、RD／RT、NVE membership、route leak | 物理 interface、Underlay link、個別 MAC／prefix route |

同一 VRF／L3VNI が複数 VTEP へ配置される関係は、1 つの Overlay Service の配置および通常の EVPN 伝搬として
表す。異なる Overlay Service 間で export RT と import RT が一致する関係だけを route leak とする。

## 3. Service identity と canonical model

### 3.1 Service identity

L3 service の identity は `(site, vrf)` とする。L3VNI は属性として保持し、同じ `(site, vrf)` に複数の
L3VNI が観測された場合は自動分割せず `conflict` とする。L2-only service は VRF がないため
`(site, l2vni)` を identity とする。

同じ VRF 名でも site が異なる場合は別 service とする。site を解決できない場合は `default` と推測せず、
`site: unresolved:<hostname>` の node scope で保持する。複数 node の同名 VRF を未解決のまま 1 service へ結合しない。
明示 mapping などにより両端を一意に解決できる場合に限り、site 間の route leak を生成できる。

### 3.2 `OverlayServiceModel`

renderer は config や show output を直接解釈せず、解析結果を `OverlayServiceModel` として受け取る。外部保存形式は
YAML、envelope は `api_version: alred/v1` と `kind: OverlayServiceModel` とする。実装時に JSON Schema Draft 2020-12 の
package resource を追加し、生成および import 時に検証する。

```yaml
api_version: alred/v1
kind: OverlayServiceModel
metadata:
  source:
    type: evidence-package
    value: imported-evidence/<package-id>
  source_manifest_sha256: sha256:<digest>
spec:
  status: complete
  parser_versions:
    running_config: <version>
    overlay_state: <version>
  services:
    - service_id: adc/TENANT-A
      site: adc
      vrf: TENANT-A
      l3vni: 50001
      address_families:
        - ipv4
      route_distinguisher: "65001:50001"
      import_route_targets:
        - "65001:50001"
      export_route_targets:
        - "65001:50001"
      l2_services:
        - l2vni: 10001
          vlan: 101
          svi: Vlan101
      placements:
        - node: adc-lfsw0101
          placement_type: evpn-vtep
          vtep_addresses:
            - 10.0.1.1
          vpc_shared_vtep_addresses:
            - 10.0.1.100
      route_type_summary:
        type2: 24
        type3: 4
        type5: 12
      status: healthy
      evidence_refs: []
  route_leaks:
    - leak_id: adc/TENANT-A-to-SHARED-SERVICES
      source_service: adc/TENANT-A
      destination_service: adc/SHARED-SERVICES
      address_families:
        - ipv4
      matched_route_targets:
        - "65001:9000"
      policy_state: configured
      policy_coverage:
        source_observed: 2
        source_placements: 2
        destination_observed: 2
        destination_placements: 2
      operational_state: verified
      verification_scope: full
      prefix_summary:
        expected: 12
        received: 12
      evidence_refs: []
  diagnostics: []
```

`service_id` と `leak_id` は正規化済み field から決定的に生成する。入力順、YAML key 順、Python hash seed に
依存させない。元 file、command ID、parser version、hash は model と `network-diagram-manifest.yaml` から
追跡可能にする。

## 4. 入力と evidence precedence

`generate-network-diagram` は指定された 1 つの固定 source から、Manifest で検証できる artifact だけを使用する。
Evidence Package、Operation、external import、local `raw/` を暗黙に混在させない。

同じ Snapshot 内の fact は次の優先順位で解決する。

1. schema 検証済み `OverlayState`
2. Health Snapshot の parsed operational evidence
3. source Manifest に固定された running config
4. inventory の role／site metadata。ただし label と分類だけに使用する

上位 evidence が下位 evidence の値と矛盾する場合は黙って上書きせず、両方の参照を diagnostic に残す。下位 evidence は
上位に存在しない field の補完にだけ使用できる。異なる Collection／Snapshot の値を最新らしさだけで合成しない。

Evidence Package の `sanitized`、`pseudonymized`、`verbatim` などの開示状態はそのまま使用し、diagram 生成側で原値を
復元しない。VRF 名、RT、address、prefix 集計を描画する前に Package の disclosure metadata を Manifest へ引き継ぐ。

## 5. Service の構成と状態

### 5.1 表示対象

Summary は service ごとに次を表示する。

- site、VRF、L3VNI、address family
- L2VNI／VLAN／SVI 数
- 配置 node 数、VTEP 数、vPC shared VTEP 数
- `healthy`、`configured`、`unknown`、`degraded`、`conflict` の状態
- route leak、diagnostic の件数

Detail は Summary に加えて、RD、import／export RT、L2VNI／VLAN／SVI の対応、node／VTEP／NVE membership、
Type-2／Type-3／Type-5 の集計、route leak の方向と証跡を表示する。個別 MAC、IP、Type-5 prefix を graph edge として
描画しない。必要な個別値は将来の machine-readable report へ分離する。

同じ VRF 名を持つことだけで EVPN Placement と判定しない。canonical `placements[].placement_type` は node ごとの config evidence から
次のように分類する。

| `placement_type` | 判定 | Detail 表示 |
|---|---|---|
| `evpn-vtep` | local L3VNI 設定または NVE L3VNI membership がある | `EVPN Placements` |
| `l2-only` | L3VNI はなく、L2VNI の VLAN binding がある | `EVPN Placements`。Type を `L2-only` と表示 |
| `service-edge` | 対象 VRF はあるが local L3VNI／L2VNI binding と NVE membership がない | `Service Edge Attachments` |

`service-edge` は外部 Network Function、Border Gateway、VRF routing node などの可能性があるが、hostname や role だけで用途を
決めない。VRF config を Service attachment evidence とし、Service へ `VRF attachment` edge で接続する。L3VNI Interface または
L2 Service へは接続しない。物理 link、共有 VLAN、routed interface の対応は、それらの relation evidence を model 化するまで推測しない。
status、RT policy coverage、EVPN route 集計では `service-edge` を EVPN VTEP の期待 node 数へ含めない。

Route Target の Detail 表示では、明示値と `auto` から安全に解決した実効値を区別する。実効値に対応する EVPN scope の
observation のうち 1 件以上が `configured_value: auto` である場合は、`65001:9001 (auto)` のように注記する。同じ値を
明示値と `auto` の両方で観測した場合も値は 1 件へ集約し、`(auto)` を付ける。解決できない `auto` に推測値を表示しない。

L2 Service Detail は L2VNI、device-local VLAN／SVI binding、Gateway state、明示設定された IPv4／IPv6 SVI address、
NVE membership を表示する。
Gateway state は SVI address または `fabric forwarding mode anycast-gateway` を確認した場合を `yes`、SVI はあるがどちらも
ない場合を `no`、node 間で異なる場合を `mixed`、SVI evidence がない場合を `unknown` とする。`ip forward` だけの L3 transit
SVI を endpoint gateway と推測しない。複数 node の address は決定的に重複排除して表示し、設定されていない address を
推測または補完しない。

L3VNI は L2 Service と分離し、`L3VNI Mode` として次の canonical 値と表示名を保持する。「SVI Mode」は forwarding SVI の
挙動と混同するため、L3VNI 方式全体の列名には使用しない。

| canonical 値 | Detail 表示 | 判定 evidence | 専用 VLAN／SVI |
|---|---|---|---|
| `new_l3vni` | `New L3VNI (VLAN/SVI-less)` | VRF `vni <id> l3` と NVE `member vni <id> associate-vrf` があり、同じ VNI の専用 VLAN／SVI がない | なし |
| `traditional_vlan_svi` | `Traditional VLAN/SVI` | L3VNI と同じ `vn-segment` の VLAN と、同じ VRF の `ip forward` SVI がある | 必須 |

canonical mode と NX-OS config 条件は
[NX-OS Overlay Config Rendering Design](../network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md) および
[ADR-0002](../../adr/0002-default-to-new-l3vni.md) と一致させる。

両方式が node 間で混在する、VLAN はあるが forwarding SVI がない、または evidence が不足する場合は自動選択せず
`conflict`／`unknown` とする。Traditional VLAN/SVI の `ip forward` は `SVI behavior` として別 field に保持する。

VLAN ID は site／service の共通値と仮定しない。L2VNI と Traditional VLAN/SVI L3VNI は、次の device-local binding を
canonical model の正本とする。

```yaml
bindings:
  - node: adc-lfsw0101
    vlan: 3000
    svi: Vlan3000
  - node: adc-lfsw0102
    vlan: 3100
    svi: Vlan3100
```

同じ mapping は表示時だけ group 化できるが、model では node との対応を失わない。共通 VLAN は全 binding が同値の場合の
derived summary にすぎず、異なる VLAN を先頭 node の値で代表させない。New L3VNI は VLAN／SVI binding を持たず、node ごとの
VRF／NVE association を placement evidence として保持する。

vPC shared VTEP は、同じ secondary address、vPC 構成、2 台以上の member を evidence で確認できる場合だけ
`VTEP (vPC shared)` と表示する。route type ごとに別 VTEP として複製しない。

### 5.2 Service status

複数状態が該当する場合の優先順位は次のとおりとする。

```text
conflict > degraded > unknown > configured > healthy
```

| 状態 | 意味 |
|---|---|
| `healthy` | 必要な config と operational evidence がそろい、明確な不整合がない |
| `configured` | config は確認できるが、正常性を確定する operational evidence がない |
| `unknown` | evidence 不足または未対応 policy により安全に判定できない |
| `degraded` | 明確な期待値に対して route、membership、配置などが不足している |
| `conflict` | 同じ service identity の L3VNI、RD／RT、placement などが矛盾する |

route が 0 件であることだけを `degraded` にしない。広報対象がない場合は該当 route type を `not-applicable` とし、
service 全体の状態を不必要に悪化させない。

## 6. VRF 間 route leak

### 6.1 有向 relation

route leak は Service の親子関係ではなく、次の有向 relation として保持する。

```text
source VRF -- export RT と import RT の一致 --> destination VRF
```

source service と destination service が異なり、同じ address family／EVPN scope で、source の実効 export RT と
destination の実効 import RT が一致した場合だけ route leak candidate を生成する。同一 service 内の一致は通常の
EVPN service 伝搬であり、`route_leaks` へ格納しない。

双方向 leak は 2 つの有向 relation として canonical model に保持する。renderer は正反対の 2 relation を視覚上まとめても
よいが、方向ごとの RT、状態、evidence を失ってはならない。方向ごとの RT または状態が異なる場合は 2 本の edge とする。

route leak の推移閉包は計算しない。`A -> B` と `B -> C` から `A -> C` を推測せず、直接一致する policy evidence がある
relation だけを生成する。

### 6.2 RT の正規化と `auto`

`route-target both` は同じ値の import と export に展開する。明示 RT は address family と EVPN scope を保持して正規化し、
異なる scope を一致させない。重複行は evidence を保持したまま canonical 値を重複排除する。

`auto` は任意の `auto` と一致する wildcard として扱わない。platform adapter が AS、VNI、address family と設定 context から
実効 RT を一意に導出できた場合だけ明示値へ解決する。解決できない `auto` を含む service は
`OVERLAY_RT_UNRESOLVED` とし、その evidence だけから route leak edge を生成しない。異なる L3VNI の `auto` 同士を
route leak と推測しない。

### 6.3 Policy と operational evidence

RT の一致は route import の許可を表し、実際にどの route が leak されるかを単独では保証しない。route-map、prefix-list、
広報元 route、再広報条件などを安全に解決できない場合は operational state を `unknown` とする。

RT は service 全体の単一値として先に union して比較せず、node／placement 単位の observation から一致を確認した後で、
同じ source service、destination service、AF、RT の relation を集約する。実装は全 service の総当たりではなく、正規化した
`(AF, scope, RT)` index の export／import 対応から candidate を生成する。

`policy_coverage` は export／import RT を観測した node 数と、RT policy を持つことが期待できる placement 数を方向別に保持する。
この placement は EVPN RT observation または NVE L3VNI membership がある node とする。同じ VRF を配置していても、Border
Gateway などで L3VNI／EVPN RT を持たない node は欠落数へ含めず、それだけで `conflict` または `unknown` にしない。一部の
適用対象 node だけで一致した場合も relation は保持するが、意図した配置範囲を確認できなければ service 全体で設定済みと
推測せず `unknown` を付与する。明示 expectation がある場合だけ、その不足を `degraded` とする。

| field／状態 | 判定 |
|---|---|
| `policy_state: configured` | 明示または安全に解決した export／import RT の一致を確認 |
| `operational_state: verified` | origin、必要な RR／control-plane、destination Type-5、destination VRF route の証跡を確認 |
| `operational_state: unknown` | policy は一致するが、route／prefix／filter の証跡が不足 |
| `operational_state: degraded` | 安全に導出した期待 prefix が destination に存在しない |
| `operational_state: not-applicable` | 広報対象 prefix がないことを確認 |
| `operational_state: conflict` | RT、service、origin、destination の対応が複数候補または矛盾 |

`verified` は個別 prefix の完全一致を常に要求する意味ではない。期待 prefix を安全に導出できる場合は expected／received を
比較し、導出できない場合は route の存在だけで `verified` へ昇格しない。best path 数など自然変動する値の完全一致を
必須にしない。

operational verification は `verification_scope: full|sampled|partial|unknown` を保持する。`sampled` の成功を service 全体の
`verified/full` と表示せず、diagram と CSV に scope を併記する。収集対象 node が不足する場合は正常と推測せず
`partial` または `unknown` とする。

現行の Type-5 evaluator は同一 L3VNI の受信対象を前提とするため、異なる VRF／L3VNI 間の route leak 判定へ
そのまま流用しない。既存 parser と Snapshot evidence は共有するが、receiver 選択と policy relation は
`OverlayServiceModel` builder で分離して実装する。

### 6.4 描画

矢印は exporter である source service から importer である destination service へ向ける。edge label は一致した RT、
address family、operational state を簡潔に表示する。

| state | 表示 |
|---|---|
| `verified` | solid line、`RT <value> / verified` |
| `configured`／`unknown` | dashed line、状態名を併記 |
| `degraded` | error styling の solid line、`degraded` を併記 |
| `conflict` | conflict styling、候補数または diagnostic ID を併記 |

色だけに依存せず、線種、arrow、text を併用する。Summary page は route leak edge と件数を表示し、Detail は
source／destination、AF、matched RT、policy state、operational state、expected／received prefix 数、evidence reference を
表または注記として表示する。

## 7. Selector と detail 展開

`generate-network-diagram` および `--view overlay-service` を受け付ける個別 renderer は、次の repeatable selector を
使用する。

- `--site <site>`
- `--vrf <vrf>`
- `--l2vni <vni>`
- `--l3vni <vni>`
- `--service <site>/<vrf>` または `--service <site>/l2vni:<vni>`

複数 selector は union とする。selector に直接一致した service に加え、直接 inbound／outbound route leak がある隣接
service を context node として表示する。context node は identity、L3VNI、route leak edge だけを表示し、L2VNI、placement、
route 集計の Detail を自動展開しない。隣接先からさらに先の route leak は展開しない。

同じ VRF 名が複数 site に存在し、`--vrf` だけでは一意にならない場合も union semantics により一致 service をすべて選ぶ。
1 service への限定には canonical identity を受け付ける `--service` を使用する。`--service` が複数件に解決される場合は
identity conflict として停止する。指定値が 1 件も一致しない場合は、空 diagram を成功として出力せず validation error とする。

Summary は既定で全 service を 1 page に集約する。service ごとの Detail は `overlay-services/` に別 artifact として出力し、
既定の自動生成上限を 20 service とする。selector で選択した service を優先し、stable service ID 順で決定する。上限を
超えた場合は省略数と対象 ID を Manifest に記録する。全 Detail の生成は明示 option に限り許可し、無制限な既定動作に
しない。上限は `--overlay-detail-limit <count>`、全件は `--all-overlay-details` とし、両者の同時指定は validation error とする。
`--overlay-detail-limit` の既定値は `20`、`0` は Detail を生成しない指定とする。

Detail の形式は `--overlay-detail-format <formats>` で指定し、comma 区切りの `markdown`、`drawio` を受け付ける。既定は
`markdown` とし、draw.io は明示指定時だけ生成する。`markdown,drawio` は同じ選択 service について両形式を生成する。
VRF Detail draw.io は、中心 service、EVPN placement node／VTEP、Service Edge Attachment、L2VNI／VLAN／SVI、import／export RT、直接 inbound／outbound
route leak の隣接 service を 1 page に表示する。layout は次の 4 band に固定する。

Inbound／Outbound 内の RT は用途を混在させず、次の 3 種類に分類する。

| 分類 | 判定 | 表示 |
|---|---|---|
| Same-VRF Import／Export | local L3VNI の `auto` から安全に解決した実効 RT | RT、`(auto)`、`Purpose: EVPN service` |
| Inbound／Outbound Route Leak | `route_leaks[].matched_route_targets` と一致する方向別 RT | From／To service、RT、AF、operational state |
| Additional Import／Export RT | 明示 RT だが current evidence の直接 route leak peer と一致しない | RT、`Peer: unresolved` |

Route Leak RT は単独 Import／Export RT node と Route Leak node に重複表示せず、Route Leak node へ集約する。ただし同じ実効 RT が
local L3VNI の Same-VRF RT と直接 Route Leak の両方に使われる場合は、異なる用途を隠さないため両分類へ表示する。同じ方向と peer の
Route Leak relation は 1 node へまとめ、RT と AF を重複排除して表示する。AF ごとに state が異なる場合は AF 別 state を表示する。
Route Leak edge は関係だけを表し、RT／AF／state は node 内へ表示する。

1. 上段: `Inbound` と `Outbound`。Import／Export RT と直接 route leak neighbor を同じ line に分けて配置
2. 中段: 対象 `Service` を page 中央に配置
3. component 段: `L3VNI Interface`、`L2 Services`、`Service Edge Attachments` を sibling container として同じ line に配置
4. 下段: `evpn-vtep`／`l2-only` の `EVPN Placement` を配置

edge は `Service -- component --> L3VNI Interface／L2 Service -- device-local binding --> Placement` とする。
Placement と Service の直接 edge は生成しない。これにより Service／component 間の edge と device-local binding edge が同じ
高さで重なることを避ける。Placement と service component は多対多であり、親子関係ではないため入れ子にしない。
device-local binding は component 内の grouped mapping と Markdown table に必ず表示する。binding relation が既定上限以下の場合は
Placement と component の edge でも示す。既定上限は 40 relation とし、上限を超える場合は edge を省略して件数と Markdown 参照を
注記する。component binding を evidence から解決できない Placement は誤った edge を推測せず、`Component binding: unresolved` と
表示する。全 VRF の Detail draw.io を暗黙に生成せず、selector、Detail 上限、または
`--all-overlay-details` の明示指定に従う。

device-local binding edge は membership だけを表し、VLAN／SVI の変換または物理 link を表さない。このため edge label に
VLAN／SVI、L3VNI Mode を重複表示しない。L2 Service component 内の表示は SVI 名を VLAN ID と重複させず、次の形式とする。

```text
VLAN 20 (SVI): adc-lfsw0101, adc-lfsw0102
VLAN 30 (L2-only): adc-lfsw0103
```

Traditional VLAN/SVI の L3VNI は `VLAN 3000 (L3VNI SVI: ip-forward)`、New L3VNI は
`VLAN/SVI: not applicable` と表示する。canonical model では解析と platform 拡張のため `vlan`、`svi`、`svi_behavior` を
別 field のまま保持し、簡略化は renderer だけで行う。

vPC Placement は 2 台を 1 Placement に統合しない。同じ service／site 内で、同じ非空の vPC domain と shared VTEP address を
持つ Placement が正確に 2 台ある場合だけ、`vPC Domain <id> · shared VTEP <address>` container 内へ個別 Placement を並べる。
vPC domain だけの一致、shared VTEP 不明、1 台だけ、または 3 台以上の曖昧な対応では group 化しない。

この container は視覚的な grouping であり、2 台の VLAN／SVI、NVE membership、状態、接続 interface が同一であることを意味しない。
orphan port や移行中の非対称 config を隠さないよう、component binding edge と node 別表示は各 Placement の evidence に従う。
一方だけに binding がある場合は、その Placement だけへ edge を生成する。

同じ vPC container の 2 Placement が同じ L3VNI Interface または L2 Service component への binding を持つ場合、draw.io では
2 本の edge を container 単位の 1 本へ集約する。これは表示上の edge 集約であり、canonical model と Markdown の node 別 binding は
変更しない。一方だけが component binding を持つ場合は orphan／非対称状態を隠さず、その Placement からの個別 edge を残す。
異なる component への edge は集約しない。40 relation の描画上限は vPC group edge へ集約した後の表示 edge 数で判定する。

Detail file の basename は portable に正規化した canonical service ID と、その ID の SHA-256 先頭 8 文字から決定する。
suffix は内容 hash や random 値ではなく、同名 VRF、portable 文字置換後の衝突を避けつつ再生成時に安定させる識別子である。

## 8. 成果物と CLI

`generate-network-diagram` の追加成果物は次のとおりとする。

| file | 内容 |
|---|---|
| `overlay-service-model.yaml` | canonical service／route leak／diagnostic と provenance |
| `overlay-service-links.csv` | service と有向 route leak の review 用一覧 |
| `topology_overlay_service.md` | Overlay Service Summary の Mermaid diagram |
| `overlay-services/` | selector／上限に従う service Detail artifact |
| `topology-graph-all.drawio` | Overlay Service を含む multi-page draw.io |
| `network-diagram-manifest.yaml` | model、selector、detail 省略、全 artifact と hash |

個別 renderer は共通 `--view` を拡張する。

```bash
alred generate-mermaid --view overlay-service
alred generate-graphviz --view overlay-service
alred generate-drawio --view overlay-service
```

Evidence Package から VRF 単位の Detail を生成する例は次のとおりである。同名 VRF が複数 site に存在し得るため、
`--vrf` より canonical identity の `--service` を推奨する。

```bash
alred generate-network-diagram \
  --evidence-package imported-evidence/<package-id> \
  --service site-1/tenant1-vpc1 \
  --overlay-detail-format markdown,drawio \
  --output-dir output/overlay-tenant1
```

実装後の `generate-network-diagram --all-graph` は、既定 `TD,LR` で次の 8 page をこの順序で生成する。

1. `Topology TD`
2. `Topology LR`
3. `Underlay TD`
4. `Underlay LR`
5. `EVPN TD`
6. `EVPN LR`
7. `Overlay Service TD`
8. `Overlay Service LR`

Overlay Service Summary の draw.io page は route leak adjacency の最大次数 node を hub とする。`TD` では hub を上段、直接接続する
service 群を下段へ横並びにし、`LR` では hub を左列、直接接続する service 群を右列へ縦並びにする。3 service の例で
`controller-vpc1` が `tenant1-vpc1`／`tenant2-vpc1` の両方へ接続する場合、tenant 間を横切る直線上に controller を置かない。
同数の hub candidate は canonical service ID で決定し、hub からの最短 hop 数を後続 rank とする。逆方向を含む同一 service pair の
edge は別 lane に分離し、完全に重ねない。interface を持たない論理 edge は配置後の座標から相手 node に最も近い側へ接続する。

Overlay Service を不要とする既存 consumer 向けに `--no-overlay-service` を用意し、従来と同じ 6 page を生成する。
`--directions TD,LR,BT,RL` では、Overlay Service を含む場合は 4 view × 4 direction の 16 page、
`--no-overlay-service` の場合は従来どおり 12 page とする。

単体 `--view overlay-service` で evidence が不足する場合は `status: insufficient-evidence` の model と理由を記載した
artifact を生成する。入力 Manifest、schema、hash の検証失敗では部分生成せず、以前の公開済み artifact を維持する。

## 9. Diagnostic

model 内の diagnostic は diagram の evidence coverage を示し、共通 Error Catalog の CLI error code と分離する。

| 診断 ID | 条件 |
|---|---|
| `OVERLAY_SERVICE_IDENTITY_CONFLICT` | 同じ service identity に複数の L3VNI など矛盾する値がある |
| `OVERLAY_RT_UNRESOLVED` | `auto` または未対応構文から実効 RT を一意に解決できない |
| `OVERLAY_L3VNI_MODE_AMBIGUOUS` | L3VNI の New／Traditional mode を node evidence から一意に分類できない |
| `OVERLAY_RT_LEAK_AMBIGUOUS` | export／import RT の対応先が複数候補で service を一意に解決できない |
| `OVERLAY_ROUTE_LEAK_EVIDENCE_INCOMPLETE` | policy は一致するが operational 判定に必要な evidence が不足する |
| `OVERLAY_ROUTE_LEAK_STATE_CONFLICT` | config、Type-5、VRF route の観測結果が矛盾する |
| `OVERLAY_SERVICE_DETAIL_LIMIT` | Detail の生成対象が既定または指定上限を超えた。省略 ID は Manifest に記録する |

一部 service の evidence 不足は解決済み service の描画を妨げない。この場合は model を `partial` とし、CLI は warning 終了
code `1` を返す。source integrity、schema、selector の曖昧でない不一致は code 付き validation error とする。

## 10. Publish、再実行、互換性

Physical、Underlay、EVPN、Overlay Service の model、CSV、Markdown、draw.io、Manifest は同じ staging attempt で生成する。
全 artifact と hash を検証してから atomic publish し、途中失敗で一部 view だけが新世代へ切り替わらないようにする。

同じ固定 source、parser version、selector、detail limit、direction からは、stable order の同じ model と diagram を
再生成できることを要求する。route leak edge は source service ID、destination service ID、AF、matched RT の順で sort する。

既存の Physical／Underlay／EVPN 6 page の内容と page 名は変更しない。Overlay Service は末尾へ追加する。
`--no-overlay-service` は既存 6 page consumer の互換経路であり、従来の page 内容と名称を変更しない。

## 11. Test 要件

- VRF／L3VNI、L2VNI／VLAN／SVI、RD／RT、node／VTEP／NVE membership の正規化
- `(site, vrf)` と `(site, l2vni)` の identity、site 未解決、同名 VRF の複数 site
- `route-target both` の展開、explicit RT の一致、EVPN scope／AF 不一致
- `auto` の platform 別解決、未解決 `auto` の fail-closed 動作
- 同一 service の通常伝搬と異なる service 間 route leak の分離
- 片方向／双方向 route leak、方向別 RT、推移関係を生成しないこと
- route-map／prefix evidence 不足の `unknown` と、期待 prefix 欠落の `degraded`
- Type-5 と destination VRF route による `verified`、広報対象なしの `not-applicable`
- selector の union、直接隣接 context、非推移展開、0 件時の validation error
- Detail 20 service 上限、明示的な全件生成、stable ID／sort
- RT の明示値／`auto` 注記、SVI Gateway state、IPv4／IPv6 address の集約
- Markdown／draw.io Detail の形式選択、VRF Detail draw.io の node／edge parity
- Mermaid、Graphviz、draw.io の service／route leak parity
- draw.io の既定 8 page、`--no-overlay-service` の 6 page、全方向の 16／12 page
- Evidence Package の disclosure、Manifest hash、parser version、evidence reference の保持
- partial evidence、schema 不正、staging 失敗時に以前の公開済み成果物を維持すること
