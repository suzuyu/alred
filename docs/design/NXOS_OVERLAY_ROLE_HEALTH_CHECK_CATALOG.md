# NX-OS Overlay Role Health Check Catalog

## 1. 目的

`nxos-overlay` profile が topology role と function に応じて実行する正常性確認について、 check ID、収集 command、 Snapshot field、判定、 before / after 比較、実装状態を定義する。

role と function の解決は [Role Definition and Resolution Design](./ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)、 Overlay resource の詳細な解析と判定は [Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)、共通 underlay と機器正常性は [NX-OS Baseline Health Check Commands](./NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md) を正本とする。本書は、それらを `nxos-overlay` の role/function 別 check へ対応付ける catalog の正本である。

## 2. 適用範囲

| topology role | `nxos-overlay` | 備考 |
|---|---|---|
| `leaf` | 実行 | `vtep`、 `vpc` function を設定証跡に応じて追加 |
| `border-gateway` | 実行 | `vtep` と external reachability を確認 |
| `spine` | 実行 | RR function がある場合だけ RR 固有 check を追加 |
| `super-spine` | 実行 | RR function がある場合だけ RR 固有 check を追加 |
| `network-functions` | 未実行 | NX-OS なら `network-baseline-nxos` は実行 |
| `server` | 未実行 | NX-OS profile の対象外 |
| `other` | 未実行、 `UNKNOWN` | compare、 plan、 apply は `ROLE_SCOPE_INVALID` |

profile 未実行 host は Checklist の未実行ホスト一覧へ出力する。 check 単位の `NOT_APPLICABLE` と混在させない。

## 3. 実装状態

| 状態 | 意味 |
|---|---|
| `implemented` | 組み込み profile、 parser、 evaluator、 test が接続済み |
| `partial` | parser または Overlay evaluator は存在するが、 role-aware check として未接続、または必要な運用証跡が不足 |
| `designed` | 本書で仕様を確定したが、 command、 parser、 evaluator、 schema の一部または全部が未実装 |
| `baseline` | `network-baseline-nxos` の実装または設計を参照し、 `nxos-overlay` では重複実装しない |

実装状態の全体管理は [Implementation Status](../implementation/IMPLEMENTATION_STATUS.md) を正本とする。

## 4. 共通適用規則

### 4.1 Function expectation

| expectation | config 証跡 | 運用証跡 | 結果 |
|---|---|---|---|
| `required` | 未設定を確認 | - | `FAIL` |
| `required` | 取得・解析不能 | - | `UNKNOWN` |
| `required` | 設定あり | 正常 | `PASS` |
| `required` | 設定あり | 異常 | `FAIL` |
| `required` | 設定あり | 欠落・解析不能 | `UNKNOWN` |
| `optional` | 未設定を確認 | - | `NOT_APPLICABLE` |
| `optional` | 設定あり | 正常・異常・不明 | 運用証跡に従う |
| `forbidden` | 未設定を確認 | - | `PASS` |
| `forbidden` | 設定あり | - | `FAIL` |
| `forbidden` | 取得・解析不能 | - | `UNKNOWN` |

function の実在は hostname から推測せず、同一 Snapshot の running config から確認する。 function expectation rule は「設定されるべきか」を選ぶためだけに使用する。

### 4.2 判定の共通原則

- role/function は check の選択と期待状態に使用し、運用状態の `PASS` を role 名だけから生成しない。
- before で正常だった resource の消失または悪化を `regression` として `FAIL` にする。
- before から異常な状態は `pre_existing` として分離し、 profile policy の severity に従う。
- 設定済み function の必須 command が欠落、 timeout、 parser error の場合は `UNKNOWN` とする。
- 新規 resource は ChangeSet または観測結果と関連付けできる場合だけ期待値を判定する。
- route 数の減少は固定件数だけで即時 `FAIL` にせず、対象 resource、減少率、継続回数を policy で評価する。
- 一般的な underlay neighbor、 route、 ECMP、 interface、 port-channel は baseline の結果を参照する。

## 5. 共通 check catalog

| Check ID | 対象 | Command ID | Snapshot field | 単体判定 | before / after | 状態 |
|---|---|---|---|---|---|---|
| `overlay_role_scope` | 全 host | なし | `resolved-roles.yaml` | role allowlist 外は未実行。 `other` は `UNKNOWN` | role/hash 不一致は停止 | `implemented` |
| `overlay_function_expectation` | 対象 4 role | `running_config` | `profiles.nxos-overlay.config`、 `resolved-roles.yaml.devices.*.functions` | required / optional / forbidden を 4.1 で判定 | expectation と config の変化を記録 | `implemented` |
| `overlay_collection_completeness` | 実行 host | function 依存 | collection manifest | 設定済み function の必須証跡不足は `UNKNOWN` | before / after を個別に検証 | `partial` |
| `overlay_logging_regression` | 実行 host | `logging` | `common.logging` | Overlay 関連重大候補を policy で判定 | after の新規候補を抽出 | `baseline` |
| `vtep_loopback_reachability` | VTEP を収容する Fabric | `route_ipv4_all_vrfs`、必要時 IPv6 route | `common.routes` | source loopback/VTEP prefix への route が存在 | route 消失、 next-hop 減少を `FAIL` | `designed` |

## 6. `leaf` / `vtep`

### 6.1 Check catalog

| Check ID | Command ID | Snapshot field | 主な判定 | before / after | 状態 |
|---|---|---|---|---|---|
| `nve_interface_health` | `nve_interface` | `profiles.nxos-overlay.nve_interface` | NVE `Up`、 control-plane learning、 source-interface/VTEP IP 取得 | Up から Down、 interface 消失は `FAIL` | `implemented` |
| `nve_peer_regression` | `nve_peers` | `profiles.nxos-overlay.nve_peers` | peer ごとの state と learn type | Up peer の Down/消失は `FAIL` | `implemented` |
| `nve_vni_health` | `nve_vni` | `profiles.nxos-overlay.nve_vnis` | L2/L3 分類、 BD/VRF、 state、 replication | Up VNI の Down/消失は `FAIL` | `implemented` |
| `l2vni_config_consistency` | `running_config`、 `nve_vni` | `config.vlans`、 `config.svis`、 `config.nve`、 `nve_vnis` | VLAN/VNI、 NVE member、 VLAN name、 SVI/Gateway/MTU 整合 | 既存 mapping の消失・変更は `FAIL` | `partial` |
| `l3vni_config_consistency` | `running_config`、 `nve_vni` | `config.vrfs`、 `config.bgp_processes`、 `config.nve`、 `nve_vnis` | VRF/VNI、 mode、 associate-vrf、 VRF AF、 redistribution、 route-map | 既存 mapping/AF の消失は `FAIL` | `partial` |
| `vlan_operational_health` | `vlan_brief` | `profiles.nxos-overlay.vlans` | 対象 VLAN が存在し active | active から非 active/消失は `FAIL` | `implemented` |
| `vrf_operational_health` | `vrf` | `profiles.nxos-overlay.vrfs` | 対象 VRF が存在し Up | Up から Down/消失は `FAIL` | `implemented` |
| `svi_operational_health` | `interface_brief` | `profiles.nxos-overlay.svis` | running config で非 shutdown、SVI `Status` が up | up から悪化、消失は `FAIL` | `implemented` |
| `ingress_replication_health` | `nve_vni_ingress_replication` | `profiles.nxos-overlay.ingress_replication` | 複数 VTEP 配置時の remote VTEP 証跡 | 期待 remote の欠落は収束中待機、 timeout 後 `FAIL` | `partial` |
| `evpn_route_presence` | `bgp_l2vpn_evpn` | `profiles.nxos-overlay.evpn_routes` | 条件に応じ Type-2/3/5 を確認 | 既存 route の異常な減少・期待 route 欠落を評価 | `designed` |
| `type5_prefix_propagation` | `running_config`、 `bgp_l2vpn_evpn`、 `route_ipv4_all_vrfs`、必要時 `route_ipv6_all_vrfs` | `config`、 `profiles.nxos-overlay.evpn_routes`、 `profiles.nxos-overlay.vrf_routes` | 期待 prefix を自動導出し、広報元、EVPN RR、受信対象 Leaf の Type-5 と VRF 導入を確認 | 変更対象 prefix を優先し、既存 prefix の regression も評価 | `partial`（`full` mode を実装） |

### 6.2 EVPN Route Type の適用条件

EVPN route の不在を一律に異常としない。VNI、SVI、VRF、広報 policy から次の条件を
解決し、適用対象となった route type だけを評価する。

| 構成 | Type-3（IMET） | Type-2（MAC/IP） | Type-5（IP Prefix） |
|---|---|---|---|
| L2VNI 単独 | 複数 VTEP 配置時に必須 | 期待 endpoint がある場合だけ必須 | `NOT_APPLICABLE` |
| L2VNI + SVI、connected prefix 非広報 | 複数 VTEP 配置時に必須 | 期待 endpoint がある場合だけ必須 | `NOT_APPLICABLE` |
| L2VNI + SVI、connected prefix 広報 | 複数 VTEP 配置時に必須 | 期待 endpoint がある場合だけ必須 | 広報対象 prefix ごとに必須 |
| L3VNI、広報対象 prefix なし | `NOT_APPLICABLE` | `NOT_APPLICABLE` | `NOT_APPLICABLE` |
| L3VNI、広報対象 prefix あり | `NOT_APPLICABLE` | `NOT_APPLICABLE` | 広報対象 prefix ごとに必須 |

Type-3 を L2VNI の control-plane 伝搬証跡に使用することは、Cisco が VNI 追加確認方法として
明示的に推奨する手順ではない。Type-3 が ingress replication の VTEP 情報を伝える IMET route
であるという仕様に基づく alred の受け入れ policy とする。Type-2 は endpoint の存在、Type-5
は BGP VRF address-family の広報対象 prefix の存在に依存するため、VNI または Anycast Gateway
の設定だけを根拠に必須化しない。仕様の根拠は
[Cisco Nexus 9000 Series NX-OS VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-105x/m_configuring_vxlan_bgp_evpn.html)
を参照する。

### 6.3 Type-5 期待値の自動導出

利用者に `expected_prefixes` の手動定義を要求しない。次の情報から期待値を自動導出する。

1. SVI の interface config と VRF route から、VRF、address family、connected prefix を取得する。
2. VRF と L3VNI、RD、import/export RT の対応を取得する。
3. BGP VRF address-family の `redistribute direct`、`network` と参照 route-map を評価する。
   `advertise l2vpn evpn` は設定整合性の証跡にするが、NX-OS で明示されず Type-5 が生成される
   構成があるため、期待 prefix 生成の一律な必須条件にはしない。
4. route-map を含む広報条件へ一致すると安全に判断できる prefix だけを必須 Type-5 とする。
5. ChangeSet がある場合は変更後の SVI と広報設定を加え、変更対象 prefix を特定する。

route-map の match 条件、参照 object、または収集結果が不足し、安全に包含・除外を判定できない
場合は `UNKNOWN` とする。SVI または `advertise l2vpn evpn` があることだけから Type-5 の存在を
推測しない。SVI connected prefix が `redistribute direct` と route-map の permit 条件に一致する
場合は、`advertise l2vpn evpn` が明示されていなくても期待 Type-5 とする。明確に広報対象外なら
`NOT_APPLICABLE` とする。

通常の変更を伴わない `health-check before` でも、running config と operational state から同じ
期待値を生成する。ChangeSet は必須としない。また、EVPN RR で観測した Type-5 を起点として、
広報元、RT、受信対象、廃止済み VTEP を参照する stale route の有無を逆方向に照合する。

### 6.4 Type-5 の end-to-end 伝搬確認

Type-5 は次の 3 点を別々の証跡として確認する。EVPN RR だけの確認は、受信対象 Leaf への広報、
RT import、VRF routing table への導入を保証しないため、最終的な `PASS` 条件にはしない。

1. 広報元 Leaf
   - SVI prefix または対象 route が VRF routing table に存在する。
   - 広報 policy に一致し、対応する Type-5 が生成されている。
   - 単体 VTEP では local path、primary VTEP IP、secondary VTEP IP のいずれかを origin 証跡とする。
   - vPC VTEP では、同じ secondary VTEP IP を共有する pair を 1 つの origin group とし、両 member
     の primary VTEP IP と共有 secondary VTEP IP を期待 next-hop 集合にする。pair の少なくとも
     1 member から期待 prefix が生成されることを確認する。
2. EVPN RR
   - prefix、RD/RT、next-hop が期待値と一致する Type-5 を広報元から受信している。
3. 受信対象 Leaf
   - Type-5 を受信し、対象 VRF routing table へ導入している。
   - next-hop VTEP と L3VNI が期待値と一致する。

受信対象は「同じ VRF 名の device」ではなく、次をすべて満たす収集対象 device から自動導出する。

- 広報元とは異なる `leaf` または Type-5 受信対象として対応する topology role である。
- 対象 VRF と同じ L3VNI を持つ。
- Type-5 の RT を import する。
- BGP EVPN、NVE、L3VNI が評価対象である。

既定の `full` mode は、収集済みの全受信対象 Leaf を評価する。`PASS` は広報元、EVPN RR、全受信
対象 Leaf の証跡がそろった場合だけとする。対象 Leaf の収集不足は正常と推定せず `UNKNOWN` とする。

収集量を制限する明示的な `sampled` mode では、候補を次の優先順位で決定的に並べ、先頭の Leaf
を選択する。

1. 広報元と異なる vPC domain
2. 広報元と異なる site または pod
3. 対象 L2VNI を持たず、同じ L3VNI と import RT を持つ Leaf
4. canonical device 名の昇順

`sampled` の結果は `type5_propagation_sampled` として全体確認から区別し、候補、選択理由、
`receiver_evidence: <証跡取得数>/<対象総数>` を machine-readable 成果物と Checklist に保存する。
代表 Leaf の `PASS` を fabric 全体の Type-5 伝搬 `PASS` と表示しない。

受信対象が 0 台の場合、receiver stage は `NOT_APPLICABLE` とし、広報元と EVPN RR の証跡が
正常なら prefix 全体を `PASS` とする。ChangeSet が受信対象を明示している場合だけ、その期待
対象の欠落を `FAIL` または `UNKNOWN` とする。

同一 Anycast Gateway subnet を複数 Leaf が広報する構成では、単一 route の存在ではなく、広報
policy から導出した期待 origin VTEP 集合と経路を照合する。vPC pair の member 間で Type-5 の
生成元が一方へ選択される、または `advertise-pip` により primary VTEP IP が next-hop になることを
許容する。origin group と無関係な next-hop の同一 prefix は広報元の証跡に使用しない。自然変動
する best path 数の完全一致だけで異常とせず、期待 origin の欠落、RT 不一致、全経路消失を判定
根拠とする。

判定は次のとおりとする。

| 状態 | 結果 |
|---|---|
| 広報元、EVPN RR、`full` の全受信対象 Leaf で期待 Type-5 と VRF route を確認 | `PASS` |
| 明確な広報対象 prefix が広報元または EVPN RR に存在しない | `FAIL` |
| EVPN RR には存在するが、収集済み受信対象 Leaf で受信または VRF 導入できない | `FAIL` |
| route-map、VRF/L3VNI/RT 対応、または必須収集が安全に解決できない | `UNKNOWN` |
| 広報対象 prefix がない | `NOT_APPLICABLE` |

before / after verification では変更対象 prefix を優先表示し、既存 prefix は regression として
継続評価する。通常の before では現行設定から導出した全対象 prefix を評価する。

#### 6.4.1 Route 検索と成果物の scale policy

`type5_prefix_propagation` は、device または期待 prefix ごとに EVPN route list と VRF route list を
繰り返し全走査しない。1 つの `HealthSnapshot` に対して evaluator の実行前に、少なくとも次の
read-only index を一度だけ生成し、同じ snapshot を評価する全 device で再利用する。

```text
EVPN Type-5 index: device -> prefix -> route/path records
VRF route index:   device -> address family -> (VRF, prefix)
```

index は判定用の一時データであり、`HealthSnapshot` へ重複保存しない。before／after compare では
各 snapshot から独立した index を 1 回ずつ生成する。command の収集結果が存在しない場合と、
収集済みだが期待 route が存在しない場合を index 上でも区別し、前者は `UNKNOWN`、後者は `FAIL`
とする既存判定を維持する。

`health-result.json` は正常な `prefix x receiver` の明細を全件保持しない。`PASS` を含む全結果で
評価 prefix 数と receiver evidence 数を `stage_summary` に集約し、問題のある組み合わせだけを
`failures` または `unknowns` に保存する。各問題には stage、VRF、prefix、device、reason を保持する。
これにより正常時の成果物サイズを receiver 数に比例させない。判定根拠となる raw command、
Snapshot、source hash は従来どおり保持するため、集約後も再評価可能とする。

この初期最適化は収集 command と判定条件を変更しない。EVPN Route Type や VRF／prefix に限定した
targeted command、収集上限、`sampled` mode は NX-OS capability と欠損時動作を別途設計してから
実装する。

### 6.5 Command 仕様

| Command ID | NX-OS command | 必須条件 |
|---|---|---|
| `running_config` | `show running-config` | role 対象 host で必須 |
| `nve_interface` | `show nve interface` | `vtep` が required、または NVE 設定あり |
| `nve_peers` | `show nve peers` | NVE 設定あり |
| `nve_vni` | `show nve vni` | NVE 設定あり |
| `nve_vni_ingress_replication` | `show nve vni ingress-replication` | 複数 VTEP の L2VNI を評価する場合 |
| `vlan_brief` | `show vlan brief` | L2VNI または traditional L3VNI あり |
| `vrf` | `show vrf` | VRF/L3VNI あり |
| `interface_brief` | `show interface brief` | Overlay VLAN または L3VNI VRF に属する SVI あり |
| `bgp_l2vpn_evpn_summary` | `show bgp l2vpn evpn summary` | EVPN BGP 設定あり |
| `bgp_l2vpn_evpn` | `show bgp l2vpn evpn` | EVPN route を評価する場合 |
| `route_ipv4_all_vrfs` | `show ip route vrf all` | Type-5 の IPv4 origin または VRF 導入を評価する場合 |
| `route_ipv6_all_vrfs` | `show ipv6 route vrf all` | Type-5 の IPv6 origin または VRF 導入を評価する場合 |

`show vlan brief`、`show vrf`、`show interface brief` は VTEP 対象 host で一括収集し、running config
から導出した対象だけを評価する。SVI ごとの command は発行しないため、VLAN／SVI 数に比例して
command 数が増加しない。route command の対象限定は未実装であり、外部 transcript で必要な証跡が
不足する場合は `UNKNOWN` とする。

### 6.6 VLAN／VRF／SVI の対象導出と判定

利用者に期待 VLAN／VRF／SVI の手動定義を要求しない。各 device の running config から次の対象を
導出する。

- `vn-segment` を持つ VLAN を `vlan_operational_health` の対象とする。
- `vni` を持つ `vrf context` と、対象 SVI が参照する非 default VRF を
  `vrf_operational_health` の対象とする。
- `vn-segment` を持つ VLAN、または L3VNI VRF に属する `interface Vlan<VLAN>` を
  `svi_operational_health` の対象とする。

対象が 0 件なら `NOT_APPLICABLE` とする。running config、または対象 command の収集／解析証跡が
なければ `UNKNOWN` とする。対象 VLAN の消失または非 `active`、対象 VRF の消失または非 `Up`、
対象 SVI の消失、running config の明示 `shutdown`、または SVI section の `Status` が非 `up` なら
`FAIL` とする。`Reason=Administratively down` も admin down として扱う。NX-OS の
`show interface brief` は SVI に単一の `Status` だけを表示し、line protocol を独立した列では
返さないため、2 個の状態値を要求しない。
全対象が正常なら `PASS` とする。before が `PASS` で after が非 `PASS` になった場合は
`regression` として表示する。VRF、IP address、MTU、IPv6 link-local などの設定値整合は
running config を使う config consistency check の責務とし、本 operational check では重複判定しない。

## 7. `leaf` / `vpc`

| Check ID | Command ID | Snapshot field | 主な判定 | before / after | 状態 |
|---|---|---|---|---|---|
| `vpc_health` | `vpc_brief` | `common.vpc` | peer adjacency、 keepalive、 consistency | 正常状態の悪化は `FAIL` | `baseline` |
| `vpc_peer_keepalive_health` | `vpc_peer_keepalive` | `common.vpc.peer_keepalive` | alive を期待 | alive から dead/欠落は `FAIL` | `partial` |
| `vpc_orphan_port_regression` | `vpc_orphan_ports` | `common.vpc.orphan_ports` | 単体では証跡保存 | 予期しない増減を原則 `WARN` | `designed` |
| `vpc_port_channel_health` | `port_channel_summary` | `common.port_channels` | peer-link/member の Up と bundled 数 | member 減少、 Up から Down は `FAIL` | `baseline` |
| `vpc_vtep_consistency` | `running_config`、 `nve_interface`、 `nve_vni` | `config`、 `nve_interface`、 `nve_vnis` | pair 間の secondary VTEP、 VLAN/VNI/VRF/NVE 整合 | pair 間差分の新規発生は `FAIL` | `partial` |

`vpc` が `optional` で `vpc domain` が未設定なら、この section は `NOT_APPLICABLE` とする。 `required` で未設定なら `FAIL`、設定済みで運用証跡が不足すれば `UNKNOWN` とする。

## 8. `border-gateway`

`vtep` function がある場合は第 6 章を再利用し、次を追加する。

| Check ID | Command ID | Snapshot field | 主な判定 | before / after | 状態 |
|---|---|---|---|---|---|
| `border_evpn_bgp_health` | `bgp_l2vpn_evpn_summary` | `profiles.nxos-overlay.evpn_bgp` | EVPN neighbor が Established | Established peer の悪化・消失は `FAIL` | `implemented` |
| `border_vrf_route_regression` | `route_ipv4_vrf`、必要時 `route_ipv6_vrf` | `profiles.nxos-overlay.vrf_routes` | 対象 VRF route を取得可能 | 重要 route 消失、異常な減少を評価 | `designed` |
| `border_type5_route_regression` | `bgp_l2vpn_evpn` | `profiles.nxos-overlay.evpn_routes` | 宣言または既存の Type-5 を確認 | 既存 Type-5 消失・異常減少は `FAIL` | `designed` |
| `border_external_bgp_regression` | `bgp_ipv4_summary`、必要時 `bgp_ipv6_summary` | `common.routing_neighbors` | external peer が Established | Established peer の悪化・消失は `FAIL` | `partial`（baseline 結果の識別規則が未実装） |
| `border_external_reachability` | `route_ipv4_vrf`、必要時 `route_ipv6_vrf` | `profiles.nxos-overlay.vrf_routes` | 明示された重要 prefix/default route が存在 | 期待 route 消失は `FAIL` | `designed` |

external peer と重要 prefix の期待値を hostname から生成しない。初期実装は before regression を使用し、新規期待値は ChangeSet または将来の peer/route policy を必要とする。 EVPN Multi-Site 固有項目は本 catalog の初期範囲外とする。

## 9. `spine` / `super-spine` / `evpn-route-reflector`

| Check ID | Command ID | Snapshot field | 主な判定 | before / after | 状態 |
|---|---|---|---|---|---|
| `evpn_rr_config_health` | `running_config` | `config.rr_config.evpn` | L2VPN EVPN AF、直接定義または peer template 継承の RR client、必要時 cluster ID を確認 | RR client 設定の予期しない消失・変更は `FAIL` | `implemented` |
| `evpn_rr_neighbor_health` | `bgp_l2vpn_evpn_summary` | `profiles.nxos-overlay.evpn_bgp` | client neighbor が Established | Established client の悪化・消失は `FAIL` | `implemented` |
| `evpn_rr_route_regression` | `bgp_l2vpn_evpn` | `profiles.nxos-overlay.evpn_routes` | Type-2/3/5 route を正規化 | 既存 route の異常な減少を policy 評価 | `partial`（route type と key の比較を実装。policy threshold は未実装） |
| `evpn_rr_propagation_health` | `bgp_l2vpn_evpn` | `profiles.nxos-overlay.evpn_routes` | 明示された RD/RT/VNI/route type の伝播を確認 | 期待 route 欠落は `FAIL` | `designed` |

初期実装では、 before で Established だった client の消失・ down と EVPN route の異常な減少を判定する。期待 client 一覧は hostname から生成しない。新規 client と厳密な route propagation は ChangeSet または将来の明示 peer policy がある場合だけ判定する。

running config parser は、 BGP process、L2VPN EVPN AF、neighbor、peer template、`inherit peer`、`route-reflector-client`、cluster ID、AF activate を構造化する必要がある。単なる EVPN AF の存在だけで RR function を正常と判定しない。

### 9.1 Peer template 継承

NX-OS では RR client の共通設定を `template peer` へ定義し、neighbor または dynamic neighbor prefix から `inherit peer` で参照できる。次の直接定義と template 継承を同じ実効状態へ正規化する。

直接定義:

```text
router bgp 65001
  neighbor 10.0.0.11
    remote-as internal
    address-family l2vpn evpn
      route-reflector-client
```

peer template 継承:

```text
router bgp 65001
  template peer leaf
    remote-as internal
    address-family l2vpn evpn
      route-reflector-client
  neighbor 10.0.0.0/24
    inherit peer leaf
```

解析は BGP process ごとに次の順序で行う。

1. `template peer <name>` を収集し、template 自身の AF、`route-reflector-client`、`remote-as`、継承先 template を保持する。
2. `neighbor <address-or-prefix>` の直接設定と `inherit peer <name>` を保持する。
3. template の継承を再帰的に展開する。循環参照、存在しない template、複数経路から矛盾する AF 設定は自動解決しない。
4. neighbor の直接設定と展開済み template を合成し、AF ごとの実効設定を生成する。直接記載された同一 field は継承値より優先し、provenance に `direct` または `template:<name>` を残す。
5. EVPN AF で `route-reflector-client` が実効化された neighbor または dynamic neighbor prefix が 1 件以上ある場合だけ、`rr_config.evpn.configured: true` とする。参照されていない template の定義だけでは `configured` にしない。

正規化後の例:

```yaml
rr_config:
  evpn:
    configured: true
    cluster_id: null
    peer_templates:
      leaf:
        address_families:
          l2vpn-evpn:
            route_reflector_client: true
    neighbors:
      10.0.0.0/24:
        inherited_peer_templates: [leaf]
        address_families:
          l2vpn-evpn:
            route_reflector_client: true
            source: template:leaf
```

template を安全に展開できない場合、running config の取得自体が成功していても「RR が未設定」と断定しない。`evpn_rr_config_health` は `UNKNOWN` とし、reason code `RR_TEMPLATE_UNRESOLVED`、BGP process、neighbor、template 名、raw evidence を保存する。`required` function に対して template 未解決を `FAIL` へ変換してはならない。

before / after 比較では、raw template 名の変更だけで regression としない。展開後の neighbor／prefix、AF、`route-reflector-client` の実効値を比較する。template 名を変更しても実効値が等しければ同一とし、実効 RR client の消失、EVPN AF の消失、解決済み状態から未解決状態への変化をそれぞれ `FAIL`、`FAIL`、`UNKNOWN` とする。

## 10. `spine` / `super-spine` / `underlay-route-reflector`

| Check ID | Command ID | Snapshot field | 主な判定 | before / after | 状態 |
|---|---|---|---|---|---|
| `underlay_rr_neighbor_health` | `bgp_ipv4_summary`、必要時 `bgp_ipv6_summary` | `common.routing_neighbors` | underlay client が Established | Established client の悪化・消失は `FAIL` | `baseline` |
| `underlay_route_regression` | `route_ipv4_all_vrfs`、 route summary、必要時 IPv6 route | `common.routes` | loopback/VTEP route と route count | route 消失・異常減少を評価 | `baseline` |
| `underlay_vtep_loopback_reachability` | route detail | `common.routes` | 観測済み VTEP source IP への route が存在 | 到達 route 消失は `FAIL` | `designed` |
| `underlay_rr_config_health` | `running_config` | `config.rr_config.underlay` | 対象 AF の RR client 設定を確認 | 設定消失・ AF 変更は `FAIL` | `implemented` |

一般的な underlay check は `network-baseline-nxos` の結果を参照し、 `nxos-overlay` で重複する check result を生成しない。 Overlay 固有として追加するのは、 NVE source IP から得た VTEP loopback prefix との関連付けである。

underlay RR でも `template peer`／`inherit peer` を使用できるため、9.1 と同じ展開規則を IPv4／IPv6 unicast AF へ適用する。展開不能時は `underlay_rr_config_health` を `UNKNOWN` とし、未設定 `NOT_APPLICABLE` または `FAIL` と区別する。

## 11. `spine` / `super-spine` の共通 transport

RR function がない場合も、 NX-OS であれば `network-baseline-nxos` で次を確認する。

| Check | 所有 profile | 状態 |
|---|---|---|
| OSPF neighbor | `network-baseline-nxos` | `baseline` |
| BGP IPv4/IPv6 neighbor | `network-baseline-nxos` | `baseline` |
| route count / route regression | `network-baseline-nxos` | `baseline` |
| interface admin/operational state | `network-baseline-nxos` | `baseline` |
| port-channel member | `network-baseline-nxos` | `baseline` |
| BFD | `network-baseline-nxos` | 設計済み、一部未実装 |

`nxos-overlay` は baseline 結果を依存関係として参照できるが、同じ異常を別 check ID で重複計上しない。

## 12. Snapshot field 追加

既存 field は維持し、実装時に次を追加する。

| field | 内容 |
|---|---|
| `profiles.nxos-overlay.nve_peers` | peer IP、 state、 learn type、 router MAC |
| `profiles.nxos-overlay.vlans` | VLAN、 name、 status |
| `profiles.nxos-overlay.vrfs` | VRF、 ID、 state、 reason |
| `profiles.nxos-overlay.svis` | interface、admin state、operational state、status、reason。VRF、IP、MTU は `config.svis` に保持 |
| `profiles.nxos-overlay.evpn_routes` | route type、 RD、 RT、 VNI、 prefix/MAC/IP、 next-hop |
| `profiles.nxos-overlay.vrf_routes` | VRF、 AF、 prefix、 protocol、 next-hop |
| `profiles.nxos-overlay.rr_config` | AF 別 neighbor、peer template、継承元、実効 RR client、activate、cluster ID、解決状態 |
| `resolved-roles.yaml.devices.<host>.functions` | expectation、 configured、 evidence、 status |

field 追加は [Schema and Compatibility Policy](./SCHEMA_AND_COMPATIBILITY_POLICY.md) に従う。同じ major version で追加し、旧成果物の欠落を正常値へ変換せず `UNKNOWN` または未実装として扱う。

## 13. Command、 parser、 evaluator mapping

| Command ID | Parser ID | 主な利用 check | 状態 |
|---|---|---|---|
| `running_config` | `overlay_running_config` | function expectation、VNI/VRF/VLAN/SVI/RR config | `implemented`（neighbor 直接定義、peer template、`inherit peer` 展開を含む） |
| `nve_interface` | `nve_interface` | `nve_interface_health` | `implemented` |
| `nve_peers` | `nve_peers` | `nve_peer_regression` | `implemented` |
| `nve_vni` | `nve_vni` | `nve_vni_health` | parser `implemented`、 profile check `partial` |
| `nve_vni_ingress_replication` | `nve_vni_ingress_replication` | `ingress_replication_health` | parser `implemented`、 profile check `partial` |
| `bgp_l2vpn_evpn_summary` | `bgp_l2vpn_evpn_summary` | EVPN neighbor / RR neighbor | generic check `implemented`、 RR 識別 `partial` |
| `bgp_l2vpn_evpn` | `bgp_l2vpn_evpn` | route presence / propagation | `partial`（Type-2/3/5 key、件数、Type-5 prefix／RD／L3VNI と NLRI ごとの全 path／next-hop／local flag を実装） |
| `route_ipv4_all_vrfs` | `route_ipv4_all_vrfs` | Type-5 origin / VRF 導入 | `implemented` |
| `route_ipv6_all_vrfs` | `route_ipv6_all_vrfs` | Type-5 origin / VRF 導入 | `implemented` |
| `vlan_brief` | `vlan_brief` | `vlan_operational_health` | `implemented` |
| `vrf` | `vrf` | `vrf_operational_health` | `implemented` |
| `interface_brief` | `interface_brief` | `svi_operational_health` | `implemented` |
| `route_ipv4_vrf` | `route_ipv4_vrf` | border/VRF route | `designed` |
| `route_ipv6_vrf` | `route_ipv6_vrf` | border/VRF IPv6 route | `designed` |

## 14. Test 要件

- topology role ごとの profile 実行・未実行と `other` の `UNKNOWN`
- required / optional / forbidden function と expectation rule conflict
- role/function から command ID への決定的な展開と重複排除
- running config 取得後の 2 段階収集と外部 transcript の証跡不足
- NVE interface、 peer、連続する L2/L3 VNI、 replication
- L2VNI / L3VNI mode、 VLAN、 VRF、 SVI、 anycast gateway、 IPv6 link-local、 MTU
- vPC pair の secondary VTEP と VNI consistency
- border gateway の EVPN、 VRF、 Type-5、 external BGP regression
- spine と super-spine それぞれの EVPN RR、 underlay RR、 RR 非搭載
- RR client 設定、 AF activate、 cluster ID、 client 消失
- neighbor 直接定義と `template peer`／`inherit peer` が同じ実効 RR client へ正規化されること
- dynamic neighbor prefix の template 継承、未参照 template、template 多段継承、循環、未知参照、矛盾
- template 名だけを変更して実効設定が同じ場合は regression にしないこと
- template 展開不能を未設定 `FAIL` ではなく `UNKNOWN`／`RR_TEMPLATE_UNRESOLVED` にすること
- Type-2/3/5 route の正規化、減少、明示期待 route の欠落
- baseline 結果の参照と二重計上防止
- before 固定 role/function hash、 after mismatch、 partial attempt
- Checklist 未実行ホスト一覧と machine-readable `unexecuted_hosts`

## 15. 実装順序

1. role/function resolver、 scope、 `resolved-roles.yaml` を実装する。
2. catalog を profile schema へ表現し、 host ごとの command plan を生成する。
3. 既存 `nve_interface_health` と `evpn_bgp_health` を role-aware に接続する。
4. NVE peer、 VLAN、 VRF、 SVI、 EVPN route parser と Snapshot field を追加する。
5. leaf/VTEP と vPC pair check を接続する。
6. border gateway 固有 check を追加する。
7. EVPN RR、 underlay RR 固有 check を追加する。
8. Checklist、 `unexecuted_hosts`、 error code、 before/after 固定を接続する。
9. fixture、 schema、 CLI help、 sample、実装状況を同期する。

各段階で未実装 check を `PASS` または実装済みとして表示しない。 command 不足または parser 未対応を正常と推定せず `UNKNOWN` とする。
