# NX-OS Overlay Config Rendering Design

## 1. 文書の目的

Overlay ChangeSetまたはVNI Gateway CSVから、NX-OS EVPN/VXLAN向けのforward configとrollback configを生成する仕様を定義する。

本書は「NX-OSコマンドへどう変換するか」の正本とする。作業管理、投入、正常性確認、失敗・切り戻しworkflowは[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)、ChangeSetの値と対象解決も同文書を参照する。

初期対象release/modelと、observe/plan/applyを許可するcapability Levelは
[NX-OS Capability and Fixture Matrix](./NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)を正本とする。

共通rendererはPhase 5で実装済みである。`overlay-change plan/apply/rollback` CLIへの統合は
Phase 8で行う。現行`generate-vni-config`の外部出力はlegacy-compatible policyで維持し、
新仕様を暗黙適用しない。

## 2. `generate-vni-config`との共存

設定生成ロジックを二重実装しない。CSVとChangeSetをinput adapterで共通Render Modelへ変換し、同じNX-OS Rendererを使用する。

```text
generate-vni-config
    └─ VNI Gateway CSV Adapter ───────┐
                                      ├→ Canonical Render Model
overlay-change plan                   │           ↓
    └─ Overlay ChangeSet Adapter ─────┘    NX-OS Renderer
                                                  ├→ forward config
                                                  └→ rollback config
```

| 項目 | `generate-vni-config` | `overlay-change plan` |
|---|---|---|
| 主入力 | VNI Gateway CSV | Overlay ChangeSet |
| 対象解決 | CSVのdevice行 | group、default、device override |
| before | before CSVまたはrunning-config自動収集 | Health Snapshot、running-config、Collection Manifest |
| 出力 | 任意ディレクトリ、merged text | operation workspace、plan、hash |
| 設定投入 | 行わない | 承認後に`overlay-change apply` |
| rollback | configを生成 | configに加えてrollback planを生成 |

既存CLIと既定出力は互換維持する。`overlay-change plan`から`generate-vni-config`をsubprocess実行せず、renderer moduleを直接呼ぶ。

## 3. 現行`generate-vni-config`の仕様

### 3.1 CSVフィールド

```text
l3vni
vrf
l2vni
gateway_ipv4
gateway_ipv6
device
vlan
vlan_name
```

`device + vlan`を機器内entity keyとし、重複行をエラーにする。before / targetで行全体が異なる場合は、旧行のdeleteと新行のaddへ展開する。

### 3.2 現行の生成内容

現行rendererが直接使用するJinja2テンプレートは次の2ファイルである。

| 用途 | リポジトリ内パス | 呼び出し関数 |
|---|---|---|
| add / forward config | [`alred/j2/vni_add_config.j2`](../../alred/j2/vni_add_config.j2) | `render_vni_add_config_lines()` |
| delete config | [`alred/j2/vni_delete_config.j2`](../../alred/j2/vni_delete_config.j2) | `render_vni_delete_config_lines()` |

Phase 5で追加した新仕様rendererのtemplateは次の2ファイルである。

| 用途 | リポジトリ内パス |
|---|---|
| forward config | [`alred/j2/nxos_overlay_forward_config.j2`](../../alred/j2/nxos_overlay_forward_config.j2) |
| scoped rollback config | [`alred/j2/nxos_overlay_rollback_config.j2`](../../alred/j2/nxos_overlay_rollback_config.j2) |

使用template path、renderer version、機器別config path、file SHA-256、render model SHA-256、
resource actionは`plan/render-manifest.json`へ保存する。schema Kindは
`OverlayRenderManifest`である。

現行のrender context、diff、機器別ファイル出力は[`alred/cli.py`](../../alred/cli.py)の次の関数群で実装されている。

- `build_vni_add_render_context()`
- `render_vni_add_config_lines()`
- `build_vni_delete_render_context()`
- `render_vni_delete_config_lines()`
- `build_vni_diff_record_sets()`
- `write_vni_config_outputs()`
- `write_vni_config_outputs_from_record_sets()`
- `cmd_generate_vni_config()`

テンプレートだけでは生成仕様の全体を決定できず、render contextの組み立て、before / target差分、機器単位のsort、`conf t` / `end`のwrapperは`alred/cli.py`側が担当している。

現行add templateは次を生成する。

- `vrf context`、L3VNI、`rd auto`、IPv4/IPv6 address-familyのauto route-target
- VLAN、VLAN name、L2VNIの`vn-segment`
- SVI、VRF、IPv4/IPv6 gateway、anycast gateway
- `interface nve1`のL2VNI memberとL3VNI `associate-vrf`
- `evpn`配下のL2VNI、RD、route-target

現行delete templateは概ね逆方向に、NVE member、EVPN VNI、SVI、VLAN、VRF内L3VNI関連付けを削除する。

### 3.3 現行制約

- CSVの全行をSVI候補として扱うため、L2-onlyでSVI不要という意図を明示できない
- L3VNI専用VLAN / SVIと`ip forward`を表現できない
- ingress replicationとmulticast groupを選択できない
- NVE interface名が`nve1`固定
- `auto`以外のRD / route-target policyを表現できない
- `router bgp`配下のVRF address-familyと`advertise l2vpn evpn`を生成しない
- feature、NVE source-interface、anycast gateway MACなどFabric共通前提を管理しない
- 既存設定の所有権を判定せず、削除範囲が広くなる可能性がある
- changeをdelete + addへ展開するため、依存関係と一時的影響の検証が不足している

これらは目標rendererで解消し、既存CLIでは互換性を壊す変更を暗黙に行わない。

## 4. Renderer入力

### 4.1 必須入力

```text
Resolved Overlay ChangeSet
+ input-manifest.json
+ resolved-targets.yaml
+ before running-config
+ before Canonical Health Snapshot
+ inventory
+ NX-OS version / platform facts
+ Rendering Policy
```

ChangeSetの`status`は設定生成に使用せず、解決済み`spec`だけをdesired stateとして使用する。

### 4.2 Canonical Render Model

input adapterは、CSVまたはChangeSetを次の機器別モデルへ正規化する。

```yaml
device: leaf01
platform: nxos

desired:
  vrfs:
    TENANT-A:
      l3vni: 50001
      rd: auto
      route_targets: auto

  l3vnis:
    50001:
      vrf: TENANT-A
      mode: new_l3vni
      address_families:
        ipv4:
          advertise_l2vpn_evpn: true
          redistribute_direct:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          redistribute_static:
            enabled: true
            route_map: IPv4_REDISTRIBUTE_ALL
          maximum_paths_ibgp: 4
        ipv6:
          advertise_l2vpn_evpn: true
          redistribute_direct:
            enabled: true
            route_map: IPv6_REDISTRIBUTE_ALL
          redistribute_static:
            enabled: true
            route_map: IPv6_REDISTRIBUTE_ALL
          maximum_paths_ibgp: 4

  l2vnis:
    10010:
      vlan: 10
      vlan_name: TENANT-A-WEB
      vrf: TENANT-A
      replication:
        mode: global_ingress_replication_bgp
        source: existing_fabric_prerequisite
      svi:
        required: true
        mtu: 9216
        ipv4_addresses:
          - 192.0.2.1/24
        ipv6_addresses:
          - 2001:db8:10::1/64
        ipv6_link_local: fe80::1
        ipv6_nd_suppress_ra: true
        gateway_mode: anycast

  nve:
    interface: nve1
    global_ingress_replication_protocol_bgp: true

  bgp:
    local_as: "65000"
    local_as_source: running_config

current:
  source_snapshot: operations/CHG-2026-00123/health/before/snapshot.json
  running_config_sha256: 0123456789abcdef
```

`current`と`desired`の差分から、各resourceを`create`、`update`、`preserve`、`delete`、`conflict`、`unsupported`へ分類する。

## 5. Rendering Policy

Fabric共通方針はChangeSetへVNIごとに重複記載せず、Rendering Policyとして分離する。

```yaml
api_version: alred/v1
kind: NxosOverlayRenderingPolicy

metadata:
  name: site-a-nxos-overlay
  version: "1.0"

spec:
  nve_interface: nve1

  l2_replication:
    mode: global_ingress_replication_bgp
    require_existing_global_config: true

  rd:
    default_mode: auto

  route_targets:
    default_mode: auto

  l3vni:
    default_mode: new_l3vni
    allow_modes:
      - new_l3vni
      - traditional_vlan_svi
    ipv4_forward_command: ip forward

  bgp_vrf:
    advertise_l2vpn_evpn_default: true
    redistribute_direct_default: true
    redistribute_static_default: true
    ipv4_redistribute_direct_route_map_default: IPv4_REDISTRIBUTE_ALL
    ipv6_redistribute_direct_route_map_default: IPv6_REDISTRIBUTE_ALL
    ipv4_redistribute_static_route_map_default: IPv4_REDISTRIBUTE_ALL
    ipv6_redistribute_static_route_map_default: IPv6_REDISTRIBUTE_ALL
    maximum_paths_ibgp_default: 4
    discover_local_as: true
    create_bgp_process: false

  svi:
    default_mtu: 9216
    gateway_mode: anycast
    ipv4:
      no_redirects: true
    ipv6:
      link_local_default: fe80::1
      suppress_ra: true
      no_redirects: true

  existing_resource_policy: preserve
  conflict_action: plan_error
  emit_config_wrapper: true
```

policyの解決順序はCLI指定、site既定、組み込み既定とする。解決済みpolicyとSHA-256をexecution planへ保存する。

`spec.l3vni.default_mode`の組み込み既定値は`new_l3vni`とする。ChangeSetのL3VNIごとに`mode`を指定した場合は、その値を優先する。初期実装で選択可能な値は次の2つとする。

| 値 | 意味 | L3VNI専用VLAN / SVI |
|---|---|---|
| `new_l3vni` | NX-OS New L3VNI Mode。VRFの`vni <id> l3`とNVEの`associate-vrf`を使用する | 生成しない |
| `traditional_vlan_svi` | 従来のVLAN / SVI方式 | 必須 |

`auto`は初期実装の入力値として許可しない。既定値の適用と既存設定の自動判定を混同しないためである。既存VRFを変更する場合はrunning-configから現在のmodeを判定し、指定または既定のmodeと異なる場合は暗黙に移行せず`PLAN_ERROR`とする。mode移行は通常のVNI追加とは別change、別plan、別承認単位として将来設計する。

`spec.svi.default_mtu`の組み込み既定値は`9216`とする。ChangeSetの`svi.mtu`が指定された場合は、その値を優先する。

```text
ChangeSet l2vnis[].svi.mtu
または traditional L3VNI の l3vnis[].svi.mtu
    ↓ 未指定なら
Rendering Policy spec.svi.default_mtu
    ↓ 未指定なら
組み込み既定値 9216
```

このMTUはalredが新規作成するL2VNI用SVI、および`traditional_vlan_svi`で新規作成するL3VNI用SVIに適用する。`new_l3vni`はL3VNI専用SVIを作成しないため、L3VNIに対する`mtu`コマンドも生成しない。物理interface、port-channel、NVE interface、loopback、`system jumbomtu`はFabric基盤設定として扱い、この既定値によって変更しない。

`spec.bgp_vrf.advertise_l2vpn_evpn_default`、`redistribute_direct_default`、`redistribute_static_default`の組み込み既定値は`true`、`maximum_paths_ibgp_default`は`4`とする。IPv4 / IPv6の`redistribute direct`と`redistribute static`に使用するroute-mapの既定名は、それぞれ`IPv4_REDISTRIBUTE_ALL`、`IPv6_REDISTRIBUTE_ALL`とする。対象address-familyでは、既存BGP processのVRF address-family配下にこれらの設定を生成する。BGP process、router-id、global address-family、neighbor、route-map本体、`network`は生成しない。

IPv6 addressを持つSVIでは`ipv6 link-local <address>`を生成し、`svi.ipv6_link_local`省略時は`spec.svi.ipv6.link_local_default`、さらに未指定なら組み込み既定値`fe80::1`を使用する。`svi.ipv6_nd_suppress_ra`の組み込み既定値は`true`とし、`true`では`ipv6 nd suppress-ra`を生成し、`false`では生成しない。IPv6 addressを持たないSVIでは両項目を指定できず、コマンドも生成しない。

`feature nv overlay`、`feature vn-segment-vlan-based`、NVE source-interface、BGP neighbor、global anycast gateway MAC、およびNVEの`global ingress-replication protocol bgp`はFabric基盤設定として初期rendererでは自動生成しない。beforeで前提を確認し、不足時は`PLAN_ERROR`とする。将来生成する場合も、VNI追加とは別の明示policyと承認単位にする。

## 6. Validation

機器configを出力する前に次を検証する。

- deviceがinventoryに存在しNX-OSである
- VLAN、L2VNI、L3VNIがNX-OSとsite policyの範囲内
- device内のVLAN、VNI、VRF mappingが一意
- 同一L2VNIに矛盾するVLAN、VRFがない
- 対象機器のNVE interfaceに`global ingress-replication protocol bgp`が存在する
- 対象L2VNIにper-VNI ingress replicationまたはmulticast設定が存在せず、global方式と競合しない
- 対象機器にBGP processが1つ存在し、local ASを一意に取得できる
- L3VNIのIPv4 / IPv6 address-familyを明示指定または関連L2VNIのGateway AFから一意に解決できる
- 既存BGP VRF address-familyと解決済みaddress-familyに矛盾がない
- 対象address-familyの`advertise l2vpn evpn`が既存または今回の生成対象である
- `redistribute direct`または`redistribute static`が有効なAFでは解決済みroute-map名があり、そのroute-mapが対象機器に存在する
- 既存`redistribute direct`、`redistribute static`のroute-mapおよび`maximum-paths ibgp`が解決済み値と競合しない
- `maximum_paths_ibgp`がNX-OSとsite policyの許容範囲内である
- NX-OS release / platformで対象AFの`advertise l2vpn evpn`がsupportされ、期待する動作条件を満たす
- ChangeSet内部および入力SnapshotにVLAN / L2VNI、VRF / L3VNI、同一device・同一VRFの
  SVI / routed interface / loopback address・prefix競合がない

競合検査は過去の正常状態を使う`overlay-change prepare-plan`とfresh beforeを使う通常
`overlay-change plan`で共通実装する。prepare結果は準備時点の参考であり、通常planは省略せず
同じ検査を再実行する。複数VTEPに意図的に配置する同一anycast gatewayは、同じVLAN、VRF、
prefix、ChangeSet resourceに属する場合に限り許可する。
- 同一VRFに矛盾するL3VNIがない
- SVIはIPv4またはIPv6の少なくとも一方を持つ
- SVI不要指定の機器にSVIを生成しない
- IPv6 SVIの解決済みlink-local addressが`fe80::/10`内の有効なIPv6 link-local addressである
- 既存IPv6 SVIのlink-local addressが解決済み値と異なる場合は暗黙変更せず`PLAN_ERROR`とする
- 解決済みSVI MTUがNX-OSとsite policyの許容範囲内である
- 新規SVIには解決済みMTUを設定する
- 既存SVIのMTUが解決済みMTUと異なる場合は暗黙変更せず、既定で`PLAN_ERROR`とする
- underlay、port-channel、NVE、system jumbo MTUは変更せず、収集できる場合は9216 byte frameを運べる既存前提との明らかな不整合を警告する
- `new_l3vni`ではL3VNI専用VLAN / SVIが指定されていない
- `traditional_vlan_svi`ではL3VNI専用VLANが解決でき、SVI modeが指定されている
- `traditional_vlan_svi`のL3VNI用VLAN / SVIが既存L2VNIと競合しない
- 既存RD / route-targetとpolicyが競合しない
- NVE interfaceと必要featureが存在する
- before running-configとSnapshotの世代・hashがplan入力と一致する
- NX-OS releaseとplatformが選択されたL3VNI modeをsupportする
- 既存VRFのL3VNI modeと解決済みmodeが一致する

競合を推測で上書きせず、既定では`PLAN_ERROR`とする。

Phase 5実装では初期対象modelとNX-OS `10.4(5)M`以上の観測証跡を必須とする。release文字列を
解釈できない場合、対象外model、BGP processが0または複数、route-map不足、global ingress
replication不足、既存VLAN/VNI/VRF/SVI/BGP値の競合ではconfigを出力しない。
`APPLY_VERIFIED`昇格と動作検証はNexus 9000vだけを対象とする。hardware 4機種は文書・golden
config確認後も`PLAN_ONLY`以下とし、Phase 5の生成成功だけで投入許可を意味しない。

Phase 8では`overlay-change plan`を実装し、現行Capability Matrixに従って
`capability_level: PLAN_ONLY`を出力する。plan成功はapply許可を意味せず、既存approval検証は
`APPLY_VERIFIED`以外を拒否する。利用者がlevelを強制昇格するoptionは設けない。

## 7. Forward config生成規則

### 7.1 共通形式

機器別ファイル名:

```text
operations/<change-id>/generated-config/<hostname>.cfg
```

出力はUTF-8、LF、末尾改行ありとする。同じ入力とpolicyからはbyte単位で同じ出力を生成する。コメントheaderにはsecretを含めない。

```text
! alred generated overlay configuration
! change-id: CHG-2026-00123
! host: leaf01
! source: declared
! rendering-policy: site-a-nxos-overlay@1.0
! before-running-config-sha256: 0123456789abcdef
! render-model-sha256: fedcba9876543210
!
configure terminal
!
...
end
```

config SHA-256はファイル確定後に計算し、execution planへ記録する。applyは投入直前に再計算して承認済みhashと一致しなければ`PLAN_ERROR`とする。

### 7.2 生成順序

create / updateの既定順序は次とする。

1. VRFとL3VNI、RD、route-target
2. `traditional_vlan_svi`の場合だけL3VNI用VLANと`vn-segment`
3. `traditional_vlan_svi`の場合だけL3VNI用SVI、VRF関連付け、forwarding mode
4. NVE L3VNI `associate-vrf`
5. L2VNI用VLAN、VLAN name、`vn-segment`
6. L2VNI用SVI
7. NVE L2VNI member（replicationは既存global設定を利用）
8. EVPN L2VNI、RD、route-target
9. BGP VRF address-familyと`advertise l2vpn evpn`

既存設定により順序制約が変わる場合はplatform/version adapterが依存graphを調整し、planへ最終順序を保存する。

### 7.3 VRF / L3VNI

既定の`new_l3vni`:

```text
vrf context TENANT-A
  vni 50001 l3
  rd auto
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
  address-family ipv6 unicast
    route-target both auto
    route-target both auto evpn
!
interface nve1
  member vni 50001 associate-vrf
!
```

IPv4 / IPv6 address-familyを生成するかは、ChangeSetで使用するaddress familyとpolicyから決定する。既存address-familyを削除しない。

`new_l3vni`ではL3VNI専用VLAN、`vn-segment`、L3VNI用SVIを生成しない。PBRまたはNATなどのために`interface vni <L3VNI>`が必要な構成は初期実装の対象外とし、要求を検出した場合は`UNSUPPORTED`とする。L2VNIのVLAN / SVIはこのmodeに関係なく、L2VNIの定義に従って生成する。

明示的に`mode: traditional_vlan_svi`を指定した場合:

```text
vlan 3001
  vn-segment 50001
!
interface Vlan3001
  no shutdown
  vrf member TENANT-A
  ip forward
!
interface nve1
  member vni 50001 associate-vrf
!
```

NX-OS releaseとplatformにより利用可能なL3VNI modeが異なるため、config生成前にinventoryおよび収集済みの`show version`からcapabilityを検証する。`new_l3vni`が既定でも、対象機器がsupportしない場合に`traditional_vlan_svi`へ自動fallbackしてはならず、`UNSUPPORTED`としてplanを停止する。

### 7.4 BGP VRFとEVPN prefix広告

L3VNIを使用してVRFのIPv4 / IPv6 prefixをEVPNへ広告するため、既存BGP processへVRF address-family設定を生成する。

```text
router bgp 65000
  vrf TENANT-A
    address-family ipv4 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv4_REDISTRIBUTE_ALL
      redistribute static route-map IPv4_REDISTRIBUTE_ALL
      maximum-paths ibgp 4
    address-family ipv6 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv6_REDISTRIBUTE_ALL
      redistribute static route-map IPv6_REDISTRIBUTE_ALL
      maximum-paths ibgp 4
!
```

local ASは機器ごとにbefore running-configから取得する。eBGP Fabricなどで機器ごとにASが異なることを許容し、ChangeSetへ共通ASを重複記載しない。BGP processが存在しない、複数processを一意に選べない、または収集証跡がない場合は`PLAN_ERROR`とする。

`l3vnis[].address_families`には`ipv4`、`ipv6`の一方または両方を指定できる。省略時は、そのL3VNIを参照するL2VNI Gateway SVIのaddress familyの和集合から導出する。新規VRFで明示指定も導出元もない場合は、両方を推測で生成せず`PLAN_ERROR`とする。既存VRFでは既存BGP VRF address-familyを`preserve`し、不足AFの追加だけをplanへ記録する。

```yaml
l3vnis:
  - vni: 50001
    vrf: TENANT-A
    mode: new_l3vni
    address_families:
      ipv4:
        advertise_l2vpn_evpn: true
        redistribute_direct:
          enabled: true
          route_map: IPv4_REDISTRIBUTE_ALL
        redistribute_static:
          enabled: true
          route_map: IPv4_REDISTRIBUTE_ALL
        maximum_paths_ibgp: 4
      ipv6:
        advertise_l2vpn_evpn: true
        redistribute_direct:
          enabled: true
          route_map: IPv6_REDISTRIBUTE_ALL
        redistribute_static:
          enabled: true
          route_map: IPv6_REDISTRIBUTE_ALL
        maximum_paths_ibgp: 4
```

`advertise_l2vpn_evpn`、`redistribute_direct.enabled`、`redistribute_static.enabled`を省略したaddress-familyはpolicy既定の`true`を使用する。direct/staticの`route_map`省略時は、どちらもAF別の同じ既定名を使用する。`maximum_paths_ibgp`の省略時は`4`を使用する。

route-map本体はFabric既存前提とし、対象機器のrunning-configに解決済み名称が存在しなければ`PLAN_ERROR`とする。rendererはroute-mapを作成・変更しない。既存BGP VRF AFに異なるroute-mapの`redistribute direct`、`redistribute static`、または異なる`maximum-paths ibgp`がある場合も暗黙変更せず`PLAN_ERROR`とする。

`advertise_l2vpn_evpn: false`、`redistribute_direct.enabled: false`、`redistribute_static.enabled: false`は、既定の経路広告方針から外れる高影響指定のため初期実装では`UNSUPPORTED`とする。既存のneighbor、他protocolのredistribution、`network`その他のVRF BGP設定を変更・削除しない。

### 7.5 L2VNI / VLAN

```text
vlan 10
  name TENANT-A-WEB
  vn-segment 10010
!
```

VLANはdevice override解決後の値を使用する。VLAN nameが未指定なら`name`を生成しない。既存名と異なる場合は、既定で自動変更せず`conflict`とする。

### 7.6 SVI

L2-onlyで全機器にSVIが不要な場合は、`interface Vlan`を生成しない。一部機器だけ不要な場合も、解決済み対象で`required: false`となる機器には生成しない。

IPv4だけ:

```text
interface Vlan10
  description TENANT-A-WEB
  no shutdown
  mtu 9216
  vrf member TENANT-A
  no ip redirects
  ip address 192.0.2.1/24
  fabric forwarding mode anycast-gateway
!
```

IPv6だけ:

```text
interface Vlan10
  description TENANT-A-WEB
  no shutdown
  mtu 9216
  vrf member TENANT-A
  ipv6 link-local fe80::1
  ipv6 address 2001:db8:10::1/64
  ipv6 nd suppress-ra
  no ipv6 redirects
  fabric forwarding mode anycast-gateway
!
```

dual-stackではIPv4とIPv6の両方を同じSVIへ生成する。IPv6 addressが1つ以上ある場合は`ipv6 link-local`を1回生成し、省略時は`fe80::1`とする。明示値は`ipv6_link_local`で指定する。`ipv6_nd_suppress_ra`は省略時`true`で、`false`の場合は`ipv6 nd suppress-ra`を省略する。IPv4-only SVIにはこれらのIPv6固有設定を生成しない。`fabric forwarding mode anycast-gateway`は`gateway_mode: anycast`の場合だけ生成する。`mtu`はaddress familyに依存せず、解決済み値を1回だけ生成する。省略時は`mtu 9216`となる。

既存SVIへaddressを追加する場合、既存primary / secondary address、IPv6 link-local、VRF、MTU、HSRP、IPv6 RA policyなどへの影響を検証し、一意に安全と判断できなければ`PLAN_ERROR`とする。既存SVIのMTU、IPv6 link-local、`ipv6 nd suppress-ra`状態の変更は通信影響を伴い得るため、通常のVNI追加では自動変更しない。

### 7.7 NVE / replication

初期実装は、対象機器のNVE interfaceに次のFabric共通設定が投入済みであることを前提とする。

```text
interface nve1
  global ingress-replication protocol bgp
!
```

rendererはこのglobal設定を生成・変更しない。before running-configで存在を確認し、未設定なら`PLAN_ERROR`とする。新規L2VNIにはmemberだけを生成する。

検証結果はCanonical Render Modelの`nve.global_ingress_replication_protocol_bgp`とexecution planのFabric prerequisitesへ保存する。apply時にも承認済みplanの前提と投入直前のrunning-configが一致することを確認する。

```text
interface nve1
  member vni 10010
!
```

VNI配下の`ingress-replication protocol bgp`は生成しない。初期実装ではper-VNI ingress replicationおよびmulticast方式を選択できず、ChangeSetにreplication方式や`mcast-group`が指定された場合は`UNSUPPORTED`とする。global設定の追加・変更はFabric基盤変更として、Overlay VNI追加とは別change、別plan、別承認単位で扱う。

### 7.8 EVPN L2VNI

```text
evpn
  vni 10010 l2
    rd auto
    route-target import auto
    route-target export auto
!
```

explicit RD / route-targetを将来サポートする場合、ChangeSetまたはpolicyで値を明示し、autoとの混在規則を定義する。既存値を暗黙変更しない。

### 7.9 完全な生成例

```text
! alred generated overlay configuration
! change-id: CHG-2026-00123
! host: leaf01
!
configure terminal
!
vrf context TENANT-A
  vni 50001 l3
  rd auto
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
  address-family ipv6 unicast
    route-target both auto
    route-target both auto evpn
!
vlan 10
  name TENANT-A-WEB
  vn-segment 10010
!
interface Vlan10
  description TENANT-A-WEB
  no shutdown
  mtu 9216
  vrf member TENANT-A
  no ip redirects
  ip address 192.0.2.1/24
  ipv6 link-local fe80::1
  ipv6 address 2001:db8:10::1/64
  ipv6 nd suppress-ra
  no ipv6 redirects
  fabric forwarding mode anycast-gateway
!
interface nve1
  member vni 50001 associate-vrf
  member vni 10010
!
evpn
  vni 10010 l2
    rd auto
    route-target import auto
    route-target export auto
!
router bgp 65000
  vrf TENANT-A
    address-family ipv4 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv4_REDISTRIBUTE_ALL
      redistribute static route-map IPv4_REDISTRIBUTE_ALL
      maximum-paths ibgp 4
    address-family ipv6 unicast
      advertise l2vpn evpn
      redistribute direct route-map IPv6_REDISTRIBUTE_ALL
      redistribute static route-map IPv6_REDISTRIBUTE_ALL
      maximum-paths ibgp 4
!
end
```

## 8. Diffと既存resourceの扱い

### 8.1 冪等性

desiredとcurrentが等しいresourceは`preserve`とし、configを生成しない。差分がない機器はファイルを生成せず、planへ`NO_CHANGE`として記録する。

### 8.2 update

同じdevice / VLANの属性変更を無条件にdelete + addへ展開しない。属性ごとに影響を評価する。

| 変更 | 既定動作 |
|---|---|
| VLAN nameだけ | policyで許可した場合だけ更新 |
| gateway address | 既定`PLAN_ERROR`。明示的なreplace承認が必要 |
| SVI MTU | 新規SVIは解決済み値を設定。既存SVIの変更は既定`PLAN_ERROR` |
| VLAN番号 | 新resource作成後に旧resource削除するmigration planが必要 |
| L2VNI番号 | migration planが必要 |
| VRF / L3VNI | 高影響変更として通常の追加とは分離 |
| BGP VRF address-family | 不足AFと`advertise l2vpn evpn`だけ追加。既存設定の置換は`PLAN_ERROR` |
| BGP `redistribute direct` | 既定有効。AF別route-mapを参照し、既存値との不一致は`PLAN_ERROR` |
| BGP `redistribute static` | 既定有効。省略時はdirectと同じAF別route-mapを参照 |
| BGP `maximum-paths ibgp` | 省略時4。既存値との不一致は`PLAN_ERROR` |
| IPv6 SVI link-local | 新規IPv6 SVIは省略時`fe80::1`。既存値の変更は`PLAN_ERROR` |
| replication mode | 通常のVNI追加では変更不可。Fabric基盤変更として別planが必要 |
| RD / route-target | control-plane影響があるため明示承認が必要 |

### 8.3 所有権

rendererが削除できるのは次のいずれかに限る。

- 同じoperationが作成し、apply結果で確認済み
- beforeとdeclared ChangeSetから、今回の削除対象として明示承認済み
- ownership metadataまたはsite policyでalred管理対象と確認済み

既存resourceを「targetにない」という理由だけで削除しない。

## 9. Delete config

削除は依存関係の逆順で行う。

1. BGP VRFを今回新規作成した場合は`router bgp <AS>`配下の`no vrf <VRF>`。既存BGP VRFの場合は今回追加した行だけ削除
2. NVE L2VNI member
3. EVPN L2VNI
4. L2 SVI
5. L2 VLAN
6. NVE L3VNI `associate-vrf`
7. `traditional_vlan_svi`の場合だけL3VNI SVI
8. `traditional_vlan_svi`の場合だけL3VNI VLAN
9. 既存global VRFの場合だけVRF内L3VNI関連付け
10. global VRFを今回新規作成した場合は`no vrf context <VRF>`

BGP VRFとglobal VRF contextは別resourceとして、beforeでの存在と今回のownershipを記録する。今回新規作成したVRFは、配下の今回作成resourceを除去し、作業外の参照やdriftがないことを確認した後、VRF自体まで削除する。beforeから存在したVRFは削除せず、今回追加した行だけを戻す。

`global ingress-replication protocol bgp`は今回のoperationが所有するresourceではないため、delete configおよびrollback configで削除・変更しない。

BGP process自体は削除しない。BGP VRFが今回新規作成された場合は、その配下の行を個別に削除せず`no vrf <VRF>`でBGP VRF全体を削除する。既存BGP VRFの場合だけ、beforeに存在せず今回追加した`advertise l2vpn evpn`、`redistribute direct`、`redistribute static`、`maximum-paths ibgp`を個別に削除する。

新規BGP VRFおよび新規global VRFの削除例:

```text
configure terminal
!
router bgp 65000
  no vrf TENANT-A
!
interface nve1
  no member vni 10010
!
evpn
  no vni 10010 l2
!
no interface Vlan10
no vlan 10
!
interface nve1
  no member vni 50001 associate-vrf
!
! The following two commands are emitted only for traditional_vlan_svi.
no interface Vlan3001
no vlan 3001
!
no vrf context TENANT-A
end
```

既存BGP VRFおよび既存global VRFへ今回の行だけ追加した場合:

```text
router bgp 65000
  vrf TENANT-A
    address-family ipv4 unicast
      no maximum-paths ibgp 4
      no redistribute static route-map IPv4_REDISTRIBUTE_ALL
      no redistribute direct route-map IPv4_REDISTRIBUTE_ALL
      no advertise l2vpn evpn
!
vrf context TENANT-A
  no vni 50001
!
```

個別の`no`コマンドは、その行を今回のoperationが追加した場合だけ生成する。beforeから存在した行は削除しない。新規VRFの一括削除条件を満たさない場合は、推測で部分削除せず`ROLLBACK_REQUIRED`としてmanual runbookへ次の残存参照を記録する。

- VRFを参照するinterface / SVI
- static route、BGP route、ほかのrouting protocol設定
- route leaking、service、policyなどの作業外設定
- apply開始後に追加されたdrift
- ownershipを確認できないresource

実際のdelete configはcurrent stateとownershipを評価し、共有resourceや残存参照があれば該当行を生成しない。

## 10. Rollback config

forward planと同時に次へ生成する。

```text
operations/<change-id>/rollback-config/<hostname>.cfg
```

単純な追加作業ではforward configの依存関係を逆順にしたscoped inverse configを生成する。既存resourceの更新では、before値を復元するコマンドを生成する。

rollback configには次を記録する。

- forward execution plan hash
- before running-config hash
- rollback render model hash
- 対象resourceとownership
- 実行前提

状態不明、既存drift、before値不足、platform非対応により安全な逆操作を生成できない場合は、automatic rollbackを許可せずmanual runbookを生成する。

## 11. 出力成果物

`overlay-change plan`:

```text
operations/<change-id>/
├── inputs/
│   ├── change-set.yaml
│   └── device-groups.yaml
├── plan/
│   ├── input-manifest.json
│   ├── resolved-targets.yaml
│   ├── resolved-rendering-policy.yaml
│   ├── render-model.json
│   ├── render-manifest.json
│   ├── execution-plan.md
│   ├── execution-plan.json
│   ├── rollback-plan.md
│   └── rollback-plan.json
├── generated-config/
│   └── <hostname>.cfg
└── rollback-config/
    └── <hostname>.cfg
```

`input-manifest.json`にはChangeSet、外部device group、resolved targetのpath、schema version、
source / canonical hashを記録する。inline groupでは外部device groupのentryを省略する。
`render-manifest.json`には機器ごとにinput hash、renderer version、template version、forward / rollback pathとSHA-256、resource action、warningを記録する。

既存`generate-vni-config`は当面、既存の`.txt`ファイル名とmerged outputを維持する。共通rendererの内容が同じでも、CLI互換性のため出力包装と配置はadapter側で変換できる。

## 12. Errorとwarning

- `PLAN_ERROR`: 入力、競合、capability、hash、依存関係が不正で安全なconfigを生成できない
- `WARN`: config生成は可能だが、既存resource、release差、運用確認事項がある
- `NO_CHANGE`: desiredとcurrentが同じで投入不要

WARNを含むplanは内容を明示し、apply時に承認済みplan hashへ含める。未承認のWARNをapply時に無視しない。

## 13. 実装構成

### 13.1 現行ファイル

```text
alred/
├── cli.py
└── j2/
    ├── vni_add_config.j2
    └── vni_delete_config.j2
```

- [`alred/j2/vni_add_config.j2`](../../alred/j2/vni_add_config.j2): 現行add / forward template
- [`alred/j2/vni_delete_config.j2`](../../alred/j2/vni_delete_config.j2): 現行delete template
- [`alred/cli.py`](../../alred/cli.py): CSV adapter、diff、render context、出力処理、CLI

既存`generate-vni-config`の互換性testでは、これらの現行templateから生成される結果をgolden fixtureとして固定する。

### 13.2 共通化後の目標ファイル

```text
alred/overlay/
├── render_model.py
├── csv_adapter.py
├── changeset_adapter.py
├── diff.py
├── validation.py
├── nxos_renderer.py
├── rollback_renderer.py
├── artifacts.py
└── templates/
    ├── nxos_overlay_add.j2
    └── nxos_overlay_delete.j2
```

現行[`alred/cli.py`](../../alred/cli.py)のrender context、diff、output処理と、[`alred/j2/vni_add_config.j2`](../../alred/j2/vni_add_config.j2)、[`alred/j2/vni_delete_config.j2`](../../alred/j2/vni_delete_config.j2)をこのmoduleへ段階的に移す。移行中も既存CLI出力をgolden testで保護する。

共通化完了まで現行Jinja2ファイルを削除・移動しない。新旧templateを同時に変更する期間を設ける場合は、同一Render Modelに対する出力差分をtestし、意図しない互換性変更を防止する。

## 14. Test方針

- 現行CSV fixtureに対する既存出力互換
- L2-onlyでSVIを生成しない
- IPv4-only、IPv6-only、dual-stack
- IPv6 SVI link-local省略時の`fe80::1`生成、明示override、既存値競合
- SVI MTU省略時の`9216`生成、明示override、既存MTU競合
- deviceごとのVLAN override
- 一部機器だけSVI不要
- modeに応じたL3VNI resource（`new_l3vni`はVRF / NVE association、`traditional_vlan_svi`はこれに加えてVLAN / SVI）
- IPv4-only / IPv6-only / dual-stackのBGP VRF AF生成と`advertise l2vpn evpn`
- AF別`redistribute direct route-map`既定名、override、route-map不存在
- AF別`redistribute static route-map`既定名、override、directとの共通既定
- `maximum-paths ibgp`省略時4、override、既存値競合
- 機器ごとに異なるBGP local ASの検出、processなし・複数候補時の`PLAN_ERROR`
- 既存BGP VRF設定のpreserveとscoped rollback
- 新規BGP VRFは`no vrf <VRF>`、既存BGP VRFは今回追加行だけを削除
- 新規global VRFは残存参照確認後に`no vrf context <VRF>`、既存global VRFは保持
- 新規VRFに作業外driftまたは残存参照がある場合の`ROLLBACK_REQUIRED`
- 既存global ingress replication前提、未設定時の`PLAN_ERROR`
- per-VNI ingress replication / multicast指定時の`UNSUPPORTED`
- 同一入力の決定的出力
- NO_CHANGE時にconfigなし
- 共有resourceを削除しない
- update conflict
- forward configとrollback configの対応
- config / plan hash不一致時のapply拒否
- NX-OS release capability差

template単体testだけでなく、Render Modelからforward / rollback成果物までのgolden testを作成する。

## 15. NX-OS参考資料

- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.6(x)
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-106x.pdf
- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.2(x), Configuring VXLAN BGP EVPN
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-102x/m-configuring-vxlan-bbgp-evpn.html
- Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide, Release 10.2(x), Configuring VXLAN
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-102x/m_configuring_vxlan_93x.html

実装時は対象機器のNX-OS releaseに対応するCisco公式guideとcommand referenceで構文・制約を確認し、release未確認の構文を推測して生成しない。
