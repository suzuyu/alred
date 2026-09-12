# NX-OS Baseline Health Check Commands

## 1. 文書の目的

作業種別を問わず利用するNX-OS共通正常性確認profileの収集コマンドを定義する。

共通フレームワークは[Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md)、Overlay固有コマンドは[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

本一覧のうち、Phase 3までにfixture検証済みの初期parser / evaluatorは6.1に記載する。
その他のコマンドは設計案であり、対象platformとNX-OS releaseで実行可否と出力形式を
fixtureにより検証してから実装する。

初期対応下限、対象model、release/model別fixtureと検証Levelは
[NX-OS Capability and Fixture Matrix](./NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)を正本とする。

## 2. 分類

- `core`: NX-OS対象では原則毎回取得する
- `feature`: 機能が有効、またはprofileで要求された場合に取得する
- `diagnostic`: 通常の合否判定には使わず、WARN / FAIL時の追加調査で取得する

「共通」は全コマンドを常時実行する意味ではない。軽量なcoreを常時取得し、routing protocol、vPC、BFD、IPv6などはfeature検出後に追加する。

現行の静的な`show_commands.example.txt`では事前のfeature検出を挟めないため、coreとfeatureの要約コマンドをデフォルトで有効にする。未設定featureはparserで`NOT_APPLICABLE`として扱う。Health Check Profileによる動的収集を実装した後は、feature検出結果に基づく実行へ最適化できる。

## 3. coreコマンド

| ID | NX-OSコマンド | 取得内容 | 主なbefore / after判定 | 必須 |
|---|---|---|---|---|
| `clock` | `show clock` | 装置時刻、timezone | ログ期間との整合、時刻の大幅なずれ | Yes |
| `boot` | `show boot` | boot image、boot variable | 意図しないboot image変更 | Yes |
| `version` | `show version` | NX-OS version、uptime、reload reason | 意図しない再起動、version変化 | Yes |
| `inventory` | `show inventory` | chassis、module、serial | Device Summary。構成差分判定は未実装 | No |
| `system_resources` | `show system resources` | CPU、memory、load | 閾値超過、beforeからの急増 | Yes |
| `processes_cpu` | `show processes cpu` | 5秒、1分、5分CPU使用率、process別使用率 | 80%以上でWARN、連続超過時は継続確認 | Yes |
| `processes_cpu_history` | `show processes cpu history` | CPU使用率履歴 | spikeの継続性を証跡保存 | Yes |
| `processes_memory` | `show processes memory` | process別memory | 使用量急増と原因候補 | Yes |
| `processes_memory_shared` | `show processes memory shared` | shared memory | 使用量変化を証跡保存 | Yes |
| `environment` | `show environment` | 温度、fan、power | 新規fail、alarm | Yes |
| `module` | `show module` | module、status、model | `ok`からの悪化、module消失 | Yes |
| `feature` | `show feature` | feature有効状態 | 意図しないenable/disable | Yes |
| `ntp_status` | `show ntp status` | 配布状態（時刻同期とは別） | 補助証跡、明示同期行のある従来入力も保持 | Yes |
| `ntp_peers` | `show ntp peers` | 設定済み peer 一覧 | 設定有無と詳細 peer の整合 | Yes |
| `ntp_peer_status` | `show ntp peer-status` | 選択 marker、stratum、reach | 同期・選択 peer の健全性と消失 | Yes |
| `license_usage` | `show license usage` | license利用状態 | Device Summary。license Health判定は未実装 | No |
| `license_all` | `show license all` | Smart Licensingを含むlicense詳細候補 | 初期Device Summary対象外 | No |
| `interface_status` | `show interface status` | port state、VLAN、speed | 対象外portのconnectedからnotconnect等への悪化 | Yes |
| `interface_detail` | `show interface` | 物理 Ethernet の明示的な admin state、operational state、down 理由 | `interface_health` の状態補完・矛盾検出（7.9.10） | No（毎回取得する補完証跡） |
| `interface_counters_table` | `show interface counters table` | load interval、input／output Mbps・利用率 | 50%以上をINFO、70%以上をWARN、90%以上をFAIL | Yes |
| `interface_brief` | `show interface brief` | interface、protocol、状態 | up/upからdownへの遷移 | Yes |
| `interface_errors` | `show interface counters errors non-zero` | error counter | 新規error、増加量・増加率 | Yes |
| `lldp_neighbors_detail` | `show lldp neighbors detail` | local／remote hostname・interface、管理address | managed network機器間のLLDP相互関係とdescriptionの不整合 | Yes |
| `route_ipv4_default` | `show ip route` | default VRFのIPv4 route table | 経路の追加・消失を証跡保存 | Yes |
| `route_ipv4_all_vrfs` | `show ip route vrf all` | 全VRFのIPv4 route table | VRF単位の重要経路消失、詳細差分 | Yes |
| `route_summary_ipv4` | `show ip route summary vrf all` | VRF別IPv4 route数 | route数の異常な減少 | Yes |
| `logging` | `show logging` | syslog | 既存`check-logging`による新規異常候補 | Yes |
| `running_config` | `show running-config` | 実行中設定全体 | 作業前後の設定証跡 | Yes |
| `running_config_diff` | `show running-config diff unified` | running/startup 差分 | 未保存設定の新規発生 | Yes |
| `reload_pending` | `show system config reload-pending` | reloadを必要とする設定コマンド | beforeの既存pendingとafterの新規pendingを区別 | Yes |

`show interface counters errors non-zero`が対象releaseで利用できない場合は、`show interface counters errors`へfallbackする。

### 3.1 LLDP／description整合性

`network-baseline-nxos`は`show lldp neighbors detail`と`show running-config`を同じCollection attemptで
取得する。LLDP、interface description、hostname／interface mapping、exclude規則の解析は
[Link Discovery and Normalization Design](../topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)の
Canonical Link Evidenceを共用し、Health専用parserを重複実装しない。

直接収集と offline 入力は同じ command ID と Canonical Link Evidence builder を使用する。
新規の`alred-collect`では通常のcommand artifactである
`<host>/commands/<sequence>_lldp_neighbors_detail.txt`と専用の`config/*_run.txt`を使用する。既存Topology
consumerとの互換性のため`lldp/*_lldp.txt|json`も同じ実行結果から更新するが、Manifestには登録しない。
command artifactが存在しない過去成果物だけ、`lldp/*_lldp.txt|json`をfallbackとして使用する。
`nxos-transcript`では prompt 付きの`show lldp neighbors detail`と`show running-config`の
選択済み command 区間を使用する。transcript adapter は正規化後 command をそれぞれ
`lldp_neighbors_detail`、`running_config`として Collection Manifest へ登録し、source file、hash、
command／output行範囲を保持する。同一 host・command の重複は共通 transcript duplicate policyで
解決し、曖昧な LLDP または running config 区間を推測で採用しない。

どちらの入力形式でも、成功済みの両 command を同じ Snapshot 世代から読み、Canonical Link Evidence、
`LinkDiagnostics`、Health checkを生成する。LLDP commandの欠落、失敗、空output、CLI error、必要anchorの
欠落、または曖昧なduplicateは`UNKNOWN`とする。明示的にneighbor 0件を示す対応済みoutputは正常な空集合と
して扱い、破損outputと区別する。

Health判定の既定対象は、inventoryで識別できるmanaged network device間のlinkとする。NX-OS profileを
EOS host自身へ適用しないが、NX-OSとの対向確認に使用するEOSのLLDP／interface description evidenceは
platform対応parserで解析する。

```yaml
link_health:
  network_devices: include
  network_functions: auto
  servers: exclude
  unmanaged_endpoints: exclude
  description_missing: pass
  mismatch: warn
```

`network_functions: auto`では、LLDPでneighborとして観測され、inventoryから一意に識別でき、対応parserで
解析できる場合だけ対象へ含める。両端が収集対象なら双方向LLDPと両側descriptionを照合する。remote側が
収集対象外ならlocal LLDPとlocal descriptionをTopology evidenceへ保持するが、Healthの
`lldp_description_consistency`では評価しない。
server、inventory未登録endpoint、`wan-provider`などの外部回線、role競合hostは既定でHealth判定から
除外するが、raw evidenceとTopologyのcandidateから削除しない。

Health checkはevidenceの完全性と、評価可能なlinkの不一致を分離する。

- `lldp_evidence_completeness`: LLDP／running configの取得・parse、managed peerの逆方向LLDP、
  description ambiguityを評価する。取得・parse不能および対向evidence不足は`UNKNOWN`、両端を正常収集した
  片方向LLDPは`WARN`とする。
- `lldp_description_consistency`: `evidence: bidirectional-lldp`のconfirmed linkだけを対象に、各local
  interfaceのLLDP remote device／interfaceと解釈可能なdescriptionを比較する。対象linkがないhostは
  `NOT_APPLICABLE`とし、completeness不足を重複して`UNKNOWN`にしない。

| 観測状態 | 既定判定 |
|---|---|
| 双方向LLDPと解釈可能な両側descriptionが一致 | `PASS` |
| 双方向LLDPが一致し、descriptionがない | `PASS`。欠落を補足情報へ記録 |
| 双方向LLDPが成立した同じlocal interfaceのLLDPとdescriptionが異なる | `WARN`。policyで`FAIL`へ厳格化可能 |
| 両端を正常収集済みだがLLDPが片方向だけ | `WARN` |
| 対向がinventory内のmanaged deviceだが、対向のLLDP link recordがない片方向claim | completenessを`UNKNOWN`。consistencyでは評価しない |
| 対向がinventory外、外部回線、server、またはHealth対象外 | `N/A`。mismatchとして扱わない |
| LLDP command取得失敗、破損、対応parserで解釈不能 | `UNKNOWN` |
| description ruleに一致しない | `N/A`。不一致と推測しない |
| Health対象外endpoint | `N/A`。除外理由を記録 |

Topologyの`LinkDiagnostics`はevidence間の客観的な整合性を表し、Health resultとは分離する。diagram上の
`CONFLICT`は常にHealth `FAIL`を意味しない。Health evaluatorは同じ診断IDを参照し、既定policyでは
`LLDP_DESC_DEVICE_CONFLICT`、`LLDP_DESC_INTERFACE_CONFLICT`、`DESCRIPTION_NOT_RECIPROCAL`、`ONE_WAY_LLDP`を
`WARN`とし、`mismatch: fail`の場合だけ`FAIL`へ厳格化する。`UNKNOWN`と`NOT_APPLICABLE`をmismatchとして再分類しない。
`DESCRIPTION_NOT_RECIPROCAL` は両端 running config、`ONE_WAY_LLDP` は両端 LLDP output の正常収集を前提とする。

afterではneighbor消失、接続先／interface変更、新規不整合をbeforeからの差分として記録する。一時的な
LLDP未収束は既存のafter convergence待ちを適用し、timeout後の残存差分だけを最終判定する。

## 4. featureコマンド

### 4.1 NTP

NTP command は作業時刻とログ時刻の信頼性を確認するため、既定で収集する。正常な空の peer 一覧を確認できた場合は未設定として扱い、NTP 任意なら `NOT_APPLICABLE` とする。証跡不足を未設定と扱わず、配布状態と時刻同期を分離する。解析箇所・優先順位・閾値は [7.10](#710-ntpと装置時刻)を参照する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `ntp_status` | `show ntp status` | 配布状態（時刻同期とは別） | 補助証跡、明示同期行のある従来入力も保持 |
| `ntp_peers` | `show ntp peers` | 設定済み peer 一覧 | 設定有無と詳細 peer の整合 |
| `ntp_peer_status` | `show ntp peer-status` | 選択 marker、stratum、reach | 同期・選択 peer の健全性と消失 |

### 4.2 IPv6

IPv6 interfaceまたはIPv6 routeが存在する場合に取得する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `ipv6_interface_brief` | `show ipv6 interface brief vrf all` | IPv6 interface状態 | upからdown、address消失 |
| `route_summary_ipv6` | `show ipv6 route summary vrf all` | VRF別IPv6 route数 | route数の異常な減少 |
| `ipv6_neighbors` | `show ipv6 neighbor vrf all` | IPv6 neighbor | 対象を宣言した場合のみentry消失を評価 |

### 4.3 Port-channel / LACP

port-channelが設定されている場合に取得する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `port_channel_summary` | `show port-channel summary` | bundle、member flag | Up port-channelのdown、bundled member減少 |
| `lacp_internal` | `show lacp internal info` | LACP member状態 | member stateの悪化。詳細確認用としても利用 |

### 4.4 vPC

vPC featureまたはvPC domainが設定されている機器だけで取得する。

EVPN/VXLAN leaf profileでは、作業証跡の統一を優先して全leafで要約コマンドを取得してよい。vPC domainが未設定の場合はコマンド失敗や異常ではなく`NOT_APPLICABLE`とする。vPC設定済みの場合だけpeer adjacency、keepalive、consistencyを評価する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `vpc_brief` | `show vpc brief` | peer adjacency、keepalive、consistency | peer adjacency down、consistency failure |
| `vpc_peer_keepalive` | `show vpc peer-keepalive` | keepalive状態 | aliveからdeadへの悪化 |
| `vpc_orphan_ports` | `show vpc orphan-ports` | orphan port一覧 | EVPN/VXLAN leafでは既定取得。予期しない変化は原則WARN |

### 4.5 BFD

BFD clientまたはneighborが存在する場合に取得する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `bfd_clients` | `show bfd clients` | BFD利用protocol | client消失 |
| `bfd_neighbors` | `show bfd neighbors vrf all` | session状態 | Up sessionのDown、session消失 |

### 4.6 OSPF

OSPF featureまたはrouter ospf設定が存在する場合に取得する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `ospf_neighbors` | `show ip ospf neighbors` | neighbor、state、interface | Full neighborの悪化・消失 |

### 4.7 BGP IPv4/IPv6 unicast

BGP設定が存在する場合に取得する。Overlay EVPN neighborは`nxos-overlay` profileで別途扱う。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `bgp_ipv4_summary` | `show bgp ipv4 unicast summary vrf all` | IPv4 BGP neighbor、prefix数 | Established neighborの悪化・消失 |
| `bgp_ipv6_summary` | `show bgp ipv6 unicast summary vrf all` | IPv6 BGP neighbor、prefix数 | Established neighborの悪化・消失 |

NX-OS releaseや構成によってsummary構文が異なる場合は、対応profileで実行コマンドを上書きする。未対応構文を別コマンドへ推測置換せず`UNKNOWN`とする。

dynamic neighborの期待値は`show running-config`の`router bgp` sectionから取得する。globalまたはVRF内の
`neighbor <address-or-prefix>`と、その配下または継承済みtemplateの`address-family ipv4 unicast`／
`address-family ipv6 unicast`を同じBGP process、VRF、address familyへ正規化する。`/`を含む値は
`ipaddress.ip_network(..., strict=False)`でcanonical prefixにし、含まれるoperational peerを対応付ける。

summary parserは`BGP summary information for VRF <vrf>, address family <AF>`をsection anchorとし、
`Neighbor ... State/PfxRcd` heading以降のrowからneighbor address、remote AS、uptime、state／prefix数を抽出する。
`config peers`／`capable peers`は診断値として保持するが、dynamic rangeの期待peer数には使用しない。

### 4.8 Spanning Tree

L2 portを運用している場合に取得する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `spanning_tree` | `show spanning-tree` | root、port role/state、topology change | root変更、forwarding portのblocking等。既定WARN |

## 5. diagnosticコマンド

通常は常時取得せず、core / feature checkでWARNまたはFAILになった場合や、明示指定時に取得する。

| 対象 | コマンド例 | 用途 |
|---|---|---|
| Transceiver | `show interface transceiver detail` | optical level、alarm |
| Hardware | `show hardware capacity` | resource枯渇調査 |
| Forwarding | `show hardware capacity forwarding` | forwarding resource確認 |
| ACL | `show hardware access-list resource utilization` | TCAM利用状況 |
| BFD | `show bfd neighbors vrf all detail` | Down理由、timer詳細 |
| BGP | `show bgp ipv4 unicast neighbors vrf all` | neighbor詳細、last reset reason |

診断コマンドの収集失敗は、元の正常性判定を`UNKNOWN`へ変更しない。診断情報の不足として別途記録する。

## 6. 初期MVP

初期実装では、次のcoreコマンドと既存機能連携から開始する。

```text
show clock
show boot
show version
show inventory
show system resources
show processes cpu
show processes cpu history
show processes memory
show processes memory shared
show environment
show module
show feature
show ntp status
show ntp peers
show ntp peer-status
show license usage
show interface status
show interface brief
show interface counters errors non-zero
show lldp neighbors detail
show ip route
show ip route vrf all
show ip route summary vrf all
show logging
show running-config
show running-config diff unified
show system config reload-pending
```

`show inventory` と `show license usage` は Device Summary 向けの任意収集であり、
Health 判定の成否は変更しない。`show license all` は初期 Device Summary profile からは
収集しない。既存の汎用 `show_commands.example.txt` に含まれる同 command の収集互換性は変更しない。

### 6.1 Phase 3実装済み範囲

現行実装では、重複を除く次の 23 command を C9300v 10.5(4) sanitized fixture で parser 検証済みとする。
command の所有 profile と目的を次のように整理する。

#### `network-baseline-nxos`

| 分類 | command | 主な正規化先／check |
|---|---|---|
| config | `show running-config` | dynamic BGP range などの設定意図 |
| identity | `show version` | platform、version、model、hostname、uptime |
| resource | `show processes cpu` | `cpu_utilization` |
| resource | `show system resources` | `memory_utilization` |
| hardware | `show environment` | `environment_health` |
| time | `show clock` | `clock_health` と NTP 補助 evidence |
| time | `show ntp status`、`show ntp peers`、`show ntp peer-status` | `ntp_health` |
| interface | `show interface status` | `interface_health` の primary source |
| interface | `show interface counters table` | `interface_utilization` |
| interface | `show interface counters errors non-zero` | `interface_error_health` |
| interface | `show port-channel summary` | `port_channel_health` |
| config safety | `show system config reload-pending` | `reload_pending` |
| config safety | `show running-config diff unified` | `running_config_diff` |
| logging | `show logging` | `logging_health` |
| routing | `show ip route summary vrf all` | `ipv4_route_count` |
| routing | `show ip ospf neighbors` | `ospf_neighbor_health` |
| routing | `show bgp ipv4 unicast summary vrf all` | `bgp_ipv4_health` と dynamic neighbor |
| routing | `show bgp ipv6 unicast summary vrf all` | IPv6 dynamic neighbor |
| redundancy | `show vpc brief` | `vpc_health` |

#### `nxos-overlay`

| 分類 | command | 主な正規化先／check |
|---|---|---|
| config | `show running-config` | Overlay 設定意図。共通 profile と 1 回の収集を共有する |
| VXLAN | `show nve interface` | `nve_interface_health` |
| EVPN | `show bgp l2vpn evpn summary` | `evpn_bgp_health` |

`show interface brief`、NVE peer／VNI、VLAN、VRF、EVPN route などにも parser と evaluator があるが、
C9300v 10.5(4) fixture ではなく documented sample、sanitized synthetic fixture、または role test で確認している。
`show interface` の `interface_detail` parser と `interface_health` への補完も実装済み。
[合成 fixture](../../../tests/fixtures/nxos/show_interface/README.md)で検証し、上記の実機由来 23 command には含めない。

Device Summary 向けの `show inventory` と `show license usage` は上記 23 command の
C9300v 10.5(4) fixture 検証数には含めない。NTC Templates による parser、canonical 正規化、
sanitized synthetic NX-OS fixture による境界条件の検証は実装済みとする。取得元、列、欠落時動作は
[Device Summary Design](./DEVICE_SUMMARY_DESIGN.md)に定義する。

対応 command ID がない出力は `parse_status: unsupported` として provenance へ保持する。profile が判定に
必要とする command の欠落、収集失敗、unsupported、parse 失敗は正常と推定せず `UNKNOWN` とする。

### 6.2 Profile 詳細設計の共通記載形式

各 profile の check は、command 一覧だけで実装済みとせず、次の項目を 1 check 単位で記載する。
`interface_health` は 7.9 を pilot とし、同じ形式を他 check へ順次適用する。

1. profile、check ID、evaluator、実装状態、対象 platform／release
2. primary／supplemental command、必須性、収集条件、source の優先順位
3. text／JSON などの入力形式と parser backend
4. heading、row、column、label などの識別 anchor
5. raw field から Canonical Snapshot field への正規化規則
6. 未設定、対象外、欠落、空、command error、未知値、parser error の区別
7. 単体の `PASS`／`WARN`／`FAIL`／`UNKNOWN`／`NOT_APPLICABLE` 条件
8. before／after の resource identity、追加、消失、状態変化、classification
9. message、evidence、raw file、parser version の追跡方法
10. sanitized fixture、境界条件、対象外 release、既知制約、設計済み・未実装項目

現行サンプルではデフォルト取得し、将来はfeature検出後に追加する対象:

```text
show port-channel summary
show vpc brief
show bfd neighbors vrf all
show ip ospf neighbors
show bgp ipv4 unicast summary vrf all
show bgp ipv6 unicast summary vrf all
show ipv6 route summary vrf all
```

## 7. 判定ポリシー

### 7.1 即時FAIL候補

- module、fan、powerの正常状態からfailへの遷移
- beforeでupだった重要interfaceのdown
- port-channelまたは必須memberのdown
- BFD、OSPF、BGPの確立済みneighbor/sessionのdownまたは消失
- 必須routeの消失

`environment_health` は `show environment` で検出した alarm 行を `Snapshot` の
`common.environment.alarms` へ保存する。`FAIL` の場合は固定文言だけでなく、該当 alarm 行を
semicolon 区切りで check message へ含め、Checklist から power、fan、temperature などの原因を確認可能にする。

### 7.2 WARN候補

- CPU、memoryの一時的閾値超過
- interface error counterの少量増加
- route総数の小幅な変化
- spanning-tree root / topology変化
- 新規の未保存設定
- `check-logging`一致

### 7.3 UNKNOWN

- 必須コマンド失敗
- 出力が空
- parser未対応
- 必須フィールドを抽出不能
- beforeとafterで対象集合またはcollection manifestが不整合

### 7.4 作業対象の除外

意図した作業変更をregressionとして誤検出しないよう、profileまたは作業planから除外対象を渡せるようにする。

```yaml
expected_changes:
  interfaces:
    - device: leaf01
      name: Ethernet1/10
      allowed_transitions:
        - up_to_down
        - down_to_up
  routing_neighbors: []
```

除外はcheck自体を無効にせず、該当resourceの変化を`expected_change`として記録する。作業対象外で同じ変化が起きた場合は通常どおり`regression`とする。

### 7.5 CPU閾値と作業継続確認

`show processes cpu`からCPU使用率を抽出し、既定では1分平均を判定値として使用する。対象releaseで1分平均を取得できない場合は5秒値へfallbackし、使用したmetricを結果へ記録する。process別CPU値は原因調査用として保存し、合計CPUとの単純合算には使用しない。

代表的なNX-OS出力:

```text
switch# show processes cpu
CPU utilization for five seconds: 82%/2%; one minute: 85%; five minutes: 74%
PID    Runtime(ms)  Invoked   uSecs  5Sec  1Min  5Min  TTY  Process
-----  -----------  --------  -----  ----  ----  ----  ---  ----------------
1234       1200345    450012   2667   42%   38%   31%    -  example_process
```

この例では判定対象の1分平均は85%であり、既定閾値80%以上のためWARNとする。`five seconds`の`82%/2%`は、先頭を合計CPU、`/`以降をinterrupt levelとして別々に保存する。

初期既定値:

```yaml
checks:
  cpu_utilization:
    command: show processes cpu
    metric: one_minute_percent
    warning_threshold_percent: 80
    comparison: greater_than_or_equal
    consecutive_samples: 3
    sample_interval_seconds: 15
    on_single_threshold_exceeded: warn
    on_consecutive_threshold_exceeded: confirm_continue
    non_interactive_action: abort
```

動作:

1. CPU使用率が80%未満: `PASS`
2. 1回でも80%以上: `WARN`として記録し、15秒後に再取得
3. 3回連続で80%以上: `SUSTAINED_HIGH_CPU`とし、後続作業を開始せず利用者へ継続確認
4. 途中で80%未満になった場合: 連続回数を0へ戻す。発生したWARNは履歴へ残す
5. 利用者が継続を拒否、または対話不可の実行: 後続処理を中止
6. 利用者が継続を承認: 承認者、時刻、sample値を`execution.json`へ記録して続行

Phase 3でsample列の連続判定とOperation Gate理由生成を実装した。offline
`health-check snapshot`は機器へ再接続しないため、単一sampleの閾値超過はWARNと
`HIGH_CPU`を記録するが、継続確認を要求しない。Phase 7で実装したdirect収集runnerが15秒間隔など
profile指定の再sampleを行い、3回連続時に`SUSTAINED_HIGH_CPU`として同じEvaluatorへ渡す。

対話例:

```text
WARNING: SUSTAINED_HIGH_CPU
Host: leaf01
Metric: one_minute_percent
Threshold: >= 80%
Samples: 82%, 85%, 84% (15-second interval)

Continue the planned operation? [yes/no]:
```

この確認は、作業前check、およびalred内設定投入のbatch間checkで使用する。外部作業後のafter確認では続行対象がないため質問せず、`WARN`と`SUSTAINED_HIGH_CPU`を最終結果へ記録する。

非対話実行ではpromptを出さない。既定は`abort`とし、事前承認済みplanで明示した場合だけ継続可能にする。

```yaml
execution_policy:
  sustained_high_cpu:
    action: continue
    approved_by: change-manager
```

CLIだけの`--yes`でこの安全確認を暗黙に迂回しない。閾値、連続回数、間隔はprofileで変更可能とする。

### 7.5.1 running／startup config 差分

`show running-config diff unified` は running-config と startup-config の未保存差分を unified diff 形式で
確認する。差分発生時の前後関係を確認しやすいため、`network-baseline-nxos` の既定 command とする。空出力または
既知の差分なし message は `PASS`、1 行以上の差分出力は `WARN` とする。差分本文は secret を含む可能性が
あるため Checklist へ転載せず、Snapshot には差分有無、非空行数、出力 SHA-256、Collection Manifest の
evidence path を保持する。command 未収集または解釈不能は `UNKNOWN` とする。

旧版の既定 command で収集した `show running-config diff` も同じ `running_config_diff` command ID へ
正規化し、既存の Collection と Evidence Package を解析可能なまま維持する。

`reload_pending` は reload を必要とする設定の別判定であり、本 check で置き換えない。

### 7.6 reload-pending確認

作業前後で`show system config reload-pending`を実行し、反映にstartup-configへの保存とreloadを必要とする設定が存在しないか確認する。

コマンド:

```text
show system config reload-pending
```

reload-pendingが存在する代表的なNX-OS出力:

```text
switch# show system config reload-pending
Following config commands require copy r s + reload :
======================================================
0       hardware profile dlb ; dlb-interface Eth1/5,Eth1/7
======================================================
```

parserは説明行、空行、区切り線を除外し、pending設定コマンドを正規化したlistとしてSnapshotへ保存する。表示順だけの変化を差分としない。

```json
{
  "reload_pending": {
    "required": true,
    "commands": [
      "hardware profile dlb ; dlb-interface Eth1/5,Eth1/7"
    ]
  }
}
```

before / after判定:

| before | after | 結果 | 分類・動作 |
|---|---|---|---|
| なし | なし | `PASS` | reload不要 |
| あり | 同じpendingのみ | `WARN` | `pre_existing`。作業前gateで継続確認 |
| あり | pendingが減少または解消 | `PASS` | 改善として記録 |
| なし | 新規pendingあり | `FAIL` | `regression` / `unexpected_change` |
| あり | 新しいpendingが追加 | `FAIL` | 追加分を`regression`として表示 |
| 任意 | コマンド失敗・parse不能 | `UNKNOWN` | reload要否を判定不能 |

作業前にpendingが存在する場合の対話例:

```text
WARNING: RELOAD_PENDING_CONFIG_EXISTS
Host: leaf01
Pending commands:
- hardware profile dlb ; dlb-interface Eth1/5,Eth1/7

The pending configuration existed before this operation.
Continue the planned operation? [yes/no]:
```

非対話実行では既定で後続処理を中止する。明示的なexpected ChangeSetでreload-required変更を予定している場合は、新規pendingを`expected_change`へ分類できるが、reloadが必要な状態であることは`WARN`として必ず最終レポートへ残す。自動的なreloadや`clear system config reload-pending`は実行しない。

出力例:

```text
RELOAD PENDING CHECK: FAIL
- leaf01: new reload-pending configuration detected
  before: none
  after: hardware profile dlb ; dlb-interface Eth1/5,Eth1/7
```

### 7.7 IPv4 route tableの扱い

`show ip route`と`show ip route vrf all`は作業前後の詳細証跡として常時保存する。合否判定では、動的経路の自然変動による誤検出を避けるため、全entryの完全一致を要求しない。

- `show ip route summary vrf all`: VRF別route数の減少率を一次判定に使用
- `show ip route`: default VRFの重要prefixと詳細差分の根拠に使用
- `show ip route vrf all`: tenant VRFを含む重要prefixと詳細差分の根拠に使用
- profileで`required_prefixes`に指定した経路の消失は`FAIL`
- required指定のない個別経路変化は既定`WARN`または情報として記録

```yaml
checks:
  routing:
    required_prefixes:
      - vrf: default
        prefix: 0.0.0.0/0
      - vrf: TENANT-A
        prefix: 198.51.100.0/24

```
### 7.8 logging確認

`network-baseline-nxos`は`show logging`を必須収集し、既存`check-logging`と同じNX-OS
severityおよび大文字小文字を区別しない文字列照合の考え方を共通利用する。

- `severity_threshold`: `0`から指定値までを異常候補とする。既定値は`4`
- `time_range.mode`: `all`、`days`、`start-time`から確認範囲を選択する
- `time_range.days`: Snapshot実施日時から遡る日数。1以上の整数
- `time_range.start_time`: 確認開始日時。timezone offset付きISO 8601
- `lookback_seconds`: 後方互換用の秒数指定。既定値は`604800`（7日）
- `time_range`と`lookback_seconds`が両方存在する場合は`time_range`を優先する
- `include_patterns`: severityに関係なく異常候補に含める部分文字列
- `exclude_patterns`: 異常候補から除外する部分文字列。severityとincludeより優先する

before単体判定では、選択した開始境界からSnapshot作成時刻までの一致ログを既存baselineとして
`WARN / pre_existing`で記録し、一致がなければ`PASS`とする。`all`では解析できた全recordを
対象とするが、Snapshot作成時刻より未来のrecordは除外する。このWARNだけではOperation Gate
による継続確認を要求しない。

before / after比較では、before Snapshot作成時刻を排他的な開始境界、after Snapshot作成時刻を
包含する終了境界として作業期間を決める。afterに含まれる一致ログのうち、この期間内で、
beforeのfingerprintに存在しないものを新規異常候補として`WARN / regression`にする。
新規候補がなくbeforeの一致だけが存在する場合は`PASS / pre_existing`、双方に候補がない
場合は`PASS / normal`とする。
`time_range`はbefore baselineの範囲に適用する。before / after比較における作業期間は、
選択したbaseline範囲にかかわらずbefore Snapshot作成時刻より後からafter Snapshot作成時刻まで
とする。


`show logging`の収集失敗、欠落、空出力、またはtimestampを安全に解析できないrecordがある場合は
正常と推定せず`UNKNOWN / collection_error`とする。NX-OSの構造化syslogでは、facility名に
ハイフンを含む形式（例: `%USER-SLOT1-5-SYSTEM_MSG`）からもseverityを解析する。NX-OSが出力する
timestamp付き非構造化record（例: `nve: Warning: ...`）は有効なrecordとして保存し、severityは
`null`とする。severityが`null`のrecordはseverity閾値では一致せず、`include_patterns`に一致した
場合だけ異常候補となる。severityがないことだけをparse warningや`UNKNOWN`の理由にはしない。

NX-OS log timestampにはoperationのtimezone（既定`Asia/Tokyo`）を適用する。Snapshotには
timestamp、severity、fingerprint、正規化text、parse warningを保存し、rawファイルは
Collection Manifestから追跡する。

```yaml
thresholds:
  logging:
    severity_threshold: 4
    lookback_seconds: 604800
    include_patterns: []
    exclude_patterns: []
```

`time_range`をprofileで指定する例:

```yaml
# 全期間
thresholds:
  logging:
    time_range:
      mode: all

# Snapshot実施日時から3日前
thresholds:
  logging:
    time_range:
      mode: days
      days: 3

# 指定日時以降
thresholds:
  logging:
    time_range:
      mode: start-time
      start_time: "2026-08-01T09:00:00+09:00"
```


### 7.9 `network-baseline-nxos`／`interface_health`

本節は 6.2 の共通記載形式を適用する pilot であり、現行実装と設計済み・未実装の境界を明示する。

#### 7.9.1 識別情報と目的

| 項目 | 値 |
|---|---|
| profile | `network-baseline-nxos` |
| current profile version | `1.9` |
| check ID | `interface_health` |
| evaluator | `interface_health` |
| current parser | `nxos.interface_status`／`nxos.interface_detail`、`NXOS_PARSER_VERSION: 1.22` |
| platform scope | `nxos` |
| current implementation | `implemented`。ただし SVI の単独 profile 収集と policy 指定は未完了 |
| resource | `interfaces` |

目的は、admin-up の interface が operational-down である状態と、before で operational-up だった
interface の消失または down 遷移を検出することである。単に operational-down である全 port を異常にせず、
admin state と operational state を分けて扱う。

#### 7.9.2 Profile と command の対応

| source | command | profile | 収集設定 | 判定上の扱い |
|---|---|---|---|---|
| primary | `show interface status` | `network-baseline-nxos` | `required: false` | `interface_health` では必須。欠落または parse 不能は `UNKNOWN` |
| physical supplemental | `show interface` | `network-baseline-nxos` | `required: false` | 明示的な admin state と operational state の照合（7.9.10） |
| supplemental | `show interface brief` | `nxos-overlay` | `required: false` | 収集された場合だけ SVI の Status／Reason を補完 |

`required: false` は `collection_complete` が command 単体の失敗だけで `FAIL` にならないことを意味する。
`interface_health` が正常と推定できることは意味せず、primary source がなければ check は `UNKNOWN` とする。
現行の `network-baseline-nxos` 単独実行は `show interface brief` を収集しない。このため、物理 interface、
port-channel、management interface、loopback は primary source で判定できるが、SVI の admin state 補完は
`nxos-overlay` を併用して同じ Collection Manifest に supplemental source がある場合だけ行う。

#### 7.9.3 入力形式と識別 anchor

現行 parser backend は alred 内蔵の NX-OS CLI text parser である。NX-API JSON の
`TABLE_interface`／`ROW_interface`／`state` は入力対象ではない。

`show interface status` は次を anchor とする。

- heading は行頭の `Port`、`Name`、`Status`、`Vlan`
- row の interface 名は `Eth`／`Ethernet`、`Po`／`port-channel`、`mgmt`、`Vlan`、`Lo`／`loopback`
- heading 検出後は、末尾側の安定した `Vlan`、`Duplex`、`Speed`、`Type` の 4 column を基準に、
  その直前を Status として取得する
- heading を識別できない入力では、row 内の既知 status token を補助 anchor とする
- 空出力、NX-OS CLI error marker、対象 row なし、未知 status は parser error とする

`show interface brief` は `Vlan<id>`、address token、`up|down`、残りの Reason を SVI row の anchor とする。
Reason に `Administratively down` が含まれる場合だけ admin-down とし、それ以外は admin-up とする。

#### 7.9.4 正規化

`show interface status` の Status は大文字・小文字を区別せず、次のように正規化する。

| raw Status | canonical status | admin state | operational state |
|---|---|---|---|
| `connected` | `connected` | `up` | `up` |
| `disabled` | `disabled` | `down` | `down` |
| `notconnec`／`notconnect` | `notconnect` | `up` | `down` |
| `err-disabled` | `err-disabled` | `up` | `down` |
| `inactive` | `inactive` | `up` | `down` |
| `sfpAbsent` | `sfpAbsent` | `unknown` | `down` |
| `xcvrAbsen`／`xcvrAbsent` | `sfpAbsent` | `unknown` | `down` |
| `down` | `down` | `up` | `down` |

SFP 未装着表示だけでは shutdown／no shutdown を識別できないため、admin state は `unknown` とする。
既知の Status として parse は成功させ、operational-down と未装着の証跡を保持する。
admin 状態が不明なだけで未使用と推定したり、`PASS` または admin-up に補完したりしない。

この判断の根拠は
[Cisco Nexus 7000 Interfaces Configuration Guide 7.x](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/sw/nx-os/interfaces/configuration/guide/b-Cisco-Nexus-7000-Series-NX-OS-Interfaces-Configuration-Guide-Book.pdf#page=50)
の SFP 未装着と admin-down の併存例、および
[Nexus 3400-S 9.3(x) の公式例](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus3400s/sw/93x/interfaces/configuration/guide/cisco-nexus-3400s-nx-os-interfaces-configuration-guide-93x/m_3400s_overview.html)
の `xcvrAbsen`／`XCVR not inserted` の対応である。対象 Nexus 9000 の各 release の表示優先順位は未検証。

parser `1.20`／profile `1.7` でこの意味変更を記録する。Snapshot v1 の既存 `common` object 内で
`admin_state: unknown` を使用するため schema version は維持する。旧 parser の Snapshot を再評価する場合も、
未装着 Status の admin-up は信用せず `unknown` として評価し、元 Snapshot は変更しない。
既存 operation の profile hash は書き換えず、before／after の固定 profile を維持する。

profile `1.8`／parser `1.21` では、`show interface` の独立した `admin state is up/down` 行を
`common.interface_details` に保持し、評価時に物理 port の admin 状態を補完する。
上表は primary parser の観測値であり、補完後の評価値は `HealthResult.after.interfaces` に保存する。
詳細証跡がない未装着 port は引き続き `UNKNOWN`。解析 anchor、優先順位、矛盾検出は 7.9.10 を参照する。

`Vlan<id>` の raw Status が `down` の場合は primary source だけで admin state を確定せず、その row を
primary parser の結果から除外する。supplemental source があれば、Status と Reason から次のように補完する。

| SVI Status | Reason | canonical status | admin state | operational state |
|---|---|---|---|---|
| `up` | 任意 | `connected` | `up` | `up` |
| `down` | `Administratively down` を含む | `disabled` | `down` | `down` |
| `down` | その他 | `down` | `up` | `down` |

Snapshot は command に現れた interface 表記を key として、次の形で保持する。interface 名の短縮形を
Snapshot 作成時に書き換えない。

```json
{
  "common": {
    "interfaces": {
      "Eth1/3": {
        "admin_state": "unknown",
        "operational_state": "down",
        "status": "sfpAbsent"
      }
    }
  }
}
```

#### 7.9.5 Parser error と fail-closed 条件

1 row でも対象 interface に未知 status があれば、その row だけを捨てて残りを `PASS` にせず、
`interface_status` source 全体を `parse_status: unknown` にする。具体的な理由は
`sources.interface_status.parse_warning` と host の `parse_warnings` に保存する。

| 状態 | `parse_warning` または source 状態 | check message |
|---|---|---|
| command 未収集 | source なし | `Interface status was not collected` |
| collection 失敗 | `status != success`、`parse_status: unknown` | `Interface status could not be parsed` |
| 空出力 | `command output is empty` | `Interface status could not be parsed` |
| CLI error | `NX-OS command returned an error` | `Interface status could not be parsed` |
| 対象 row なし | `interface status rows were not recognized` | `Interface status could not be parsed` |
| 未知 status | `unsupported interface status row(s): <interface>=<status>` | `Interface status could not be parsed` |
| 同じ interface key の重複 | `duplicate interface status row: <interface>` | `Interface status could not be parsed` |

いずれも `UNKNOWN / collection_error` とし、空集合、admin-down、または正常状態へ補完しない。

#### 7.9.6 単体判定

primary source が `parse_status: parsed` で `common.interfaces` が存在する場合、7.9.10 の補完・
矛盾検出後の評価用 view について各 resource を次のように扱う。

| admin state | operational state | resource の扱い |
|---|---|---|
| `down` | `down` | 異常対象から除外 |
| `up` | `up` | 正常 |
| `up` | `down` | 異常 |
| 任意 | 未知値・矛盾 | 状態の証跡不足 |
| `unknown` または欠落 | 任意 | admin 状態の証跡不足 |

admin-up／operational-down が 1 件以上あれば check は `FAIL / target_not_ready` とし、message に対象
interface を sort して列挙する。異常がなく admin 状態不明が 1 件以上なら `UNKNOWN / collection_error`、
どちらもなければ `PASS / normal` とする。不明 port は message と `after.admin_state_unknown` に列挙し、
確定した異常と不明 port が混在する場合は `FAIL` とし、両方の対象を残す。すべての interface が admin-down の
場合も、現行の aggregate check は `NOT_APPLICABLE` ではなく `PASS` である。

```text
Admin-up interfaces are down: Eth1/3, Eth1/4
```

#### 7.9.7 Before／after 比較

resource identity は Snapshot の interface key の完全一致とする。各 phase の補完・矛盾検出後、
before の信頼できる `operational_state: up` 集合から after の同集合を引き、消失または down 遷移を
regression とする。operational 証跡が不明・矛盾する port はこの差分から除外し、`UNKNOWN` とする。
確定した稼働喪失が 1 件以上あれば `FAIL / regression` を優先する。
before が up、after が SFP 未装着で operational-down を確認できれば、admin-down または admin 不明でも
稼働喪失として `FAIL`。両時点とも未装着・admin-down と確認できれば `PASS` になる。

```text
Interface regression: Eth1/49
```

before または after の primary source が欠落・解析不能の場合は `UNKNOWN` とする。
短縮形と完全形の identity 正規化は `interface_utilization` との照合には使用するが、現行の before／after
`interface_health` 比較には使用しない。

#### 7.9.8 Evidence と追跡性

check の evidence は primary と、存在する場合は supplemental source について、`collection_id`、`command`、
`file`、`sha256`、`parse_status`、取得時刻、parser 名・version、行範囲、warning を保持する。
詳細 port ごとの evidence には採用値の由来、block 行範囲、不足・矛盾理由を追加する。
Snapshot の `sources` には transport も保持する。原因調査では Checklist の
message に加えて、次を確認する。

```text
hosts.<hostname>.sources.interface_status
hosts.<hostname>.common.interfaces
hosts.<hostname>.sources.interface_detail
hosts.<hostname>.common.interface_details
hosts.<hostname>.parse_warnings
```

#### 7.9.9 検証範囲と未実装

- C9300v 10.5(4) sanitized fixture で `connected`、`disabled`、`notconnec` を確認済み
- documented SVI sample で `up`、`down / Administratively down` を確認済み
- synthetic test で `xcvrAbsen`、`xcvrAbsent`、未知 status の fail-closed を確認済み
- N9K-C93180YC の raw output は repository へ持ち出しておらず、sanitized device fixture は未追加
- `required_interfaces`、`expected_changes.interfaces`、interface ignore policy は設計候補であり未実装
- `network-baseline-nxos` 単独での `show interface brief` 収集、SVI source completeness 判定は未実装
- before／after identity の `Eth`／`Ethernet`、`Po`／`port-channel` 正規化は未実装
- `show interface` の合成 fixture、両入力 adapter、単体・比較判定、失敗時の証跡を offline test で検証。
  追加 command の 9000v／hardware 接続検証は未実施

#### 7.9.10 `show interface` による admin 状態補完

profile `1.8`／parser `1.21` で収集・parser・補完を実装した。
Snapshot Builder は `1.3`、補完ロジックの provenance `interface_state` は `1.0` とする。
合成 fixture と offline test による検証であり、追加 command の実機検証済みを意味しない。

##### a. 選択理由と適用範囲

`show running-config` の shutdown 行の有無から既定値を推定せず、機器が表示する明示的な admin state を
使用する。`show interface status` は対象一覧と operational 状態の primary source として維持し、
`show interface` は補完 source とする。両出力の不整合を検出し、片方を黙って優先して正常とはしない。

最初の補完対象は物理 Ethernet と breakout port とする。SVI、port-channel、management、loopback、
subinterface は既存 evaluator の対象範囲を維持し、今回の詳細補完には含めない。
全 interface を一括取得するが、対象外 block は境界を認識して読み飛ばす。

根拠は [Cisco Nexus 9000 NX-OS 10.5(x) Interface Guide](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-105x/m_configuring_basic_interface_parameters_93x.html)
の interface 見出しと独立した admin state の出力例、および 7.9.4 の未装着・admin-down 併存例とする。
10.5(x) ガイド内にも旧 release の例が含まれるため、文書掲載だけで対象 hardware／release の parser を
検証済みとはしない。初期 fixture 検証対象は NX-OS 9000v 10.5(4)、hardware は既存方針に従い文書確認とする。

##### b. 収集契約

profile 定義の抜粋:

```yaml
- id: interface_detail
  command: show interface
  required: false
```

- `network-baseline-nxos` の NX-OS 共通 command group に追加し、before／after／rollback の各収集で
  host ごとに 1 回取得する。role や SFP 有無を判定してから個別 command を組み立てる方式にはしない。
- `required: false` は `collection_complete` の全体必須 command にしないための設定であり、
  `interface_health` の admin 不明を正常にする設定ではない。既存 profile の固定・合成・重複排除を使用する。
- CLI option、SSH executor、device ごとの接続は追加しない。既存 collector の timeout と paging 制御を使い、
  transport の成功・失敗を manifest に記録する。出力量は増えるため、多数 port の出力と timeout を検証する。
- `alred-collect` と `nxos-transcript` の双方で、正規化後に完全一致する `show interface` を
  `interface_detail` へ対応付ける。`show interface status`／`brief`／`counters ...` と prefix 一致で混同しない。
  個別 port 指定や任意の pipe filter は初期対応外。既存の `| no-more` 正規化は維持する。
- 初期 parser 入力は CLI text。構造化 NX-API JSON の直接解析は含めず、既存 transport／adapter が
  text を提供できない場合は unsupported として証跡を残す。SSH への独自 fallback は追加しない。
- canonical raw は既存の `commands/<sequence>_interface_detail.txt`、manifest は
  `hosts.<hostname>.commands.interface_detail` とする。新しい保存ディレクトリは作らない。
  sequence は既存の command sort に従い、特定の数値へ固定しない。

##### c. 解析 anchor と正規化

設計用の合成入力例:

```text
Ethernet1/3 is down (XCVR not inserted)
admin state is down, Dedicated Interface
  Hardware: Ethernet
Ethernet1/4 is down (XCVR not inserted)
admin state is up, Dedicated Interface
  Hardware: Ethernet
```

| 取得 field | 解析箇所・規則 |
|---|---|
| interface identity | block 先頭の `Ethernet<slot>/<port>` または `Eth<slot>/<port>`。breakout の `/subport` を含む。`.` 付き subinterface は対象外 |
| operational state | 同じ見出しの `is up`／`is down`／`is administratively down`。最後の形式は operational-down とし、admin は別行から取得 |
| admin state | 同一 block 内の行頭 `admin state is up`／`admin state is down`。後続の comma と interface 種別などの説明は許容 |
| down reason | 見出しの括弧内の理由を文字列で保持。空の場合は `null`。未知の理由文字列だけでは解析失敗にしない |
| line range | block の開始・終了行。manifest の command 出力範囲を基準に raw file の絶対行番号へ変換 |

field 識別と state token は大文字・小文字を区別せず、前後空白を除去する。admin／operational の
正規化値は `up`／`down`／`unknown`。counter、MTU、速度、光レベルは本 parser の判定 field にしない。
`SFP not inserted`／`XCVR not inserted` という理由から admin 状態を作らない。

次の interface 見出しで必ず block を閉じ、隣接 port や対象外 interface の admin 行を取り込まない。
同じ正規化 identity の重複、admin 行の重複、未知 state、必須 admin 行の欠落は当該 port の解析不完全とする。
境界を認識できない破損、空出力、CLI error、物理 port block が 0 件の場合は source 全体を unknown とする。
途中切れで最後の port の admin 行がない場合も、その port を削除して正常扱いしない。

parser は `common.interface_details` へ出力し、既存 `common.interfaces` を直接上書きしない。
詳細 object は次の形式とする:

```json
{
  "interface_details": {
    "Ethernet1/3": {
      "admin_state": "down",
      "operational_state": "down",
      "down_reason": "XCVR not inserted",
      "parse_status": "parsed",
      "parse_warning": null,
      "line_start": 1,
      "line_end": 3
    }
  }
}
```

行番号の raw file への変換は Snapshot Builder が行う。parser は入力 text 内の相対行番号を返す。
不完全な port は `parse_status: unknown` と理由を保持し、source の `parse_warning` と host の
`parse_warnings` にも記録する。正常 port の結果と不完全 port の結果を分離して保持する。
source は全対象 port が正常なら parsed、1 件でも不完全なら unknown とし、後者だけに
`partial_records: true` を記録する。補完には正常な port record
だけを使用できるが、transport 失敗・source 全体の破損の場合は部分出力を補完に使わない。

##### d. 照合・優先順位・判定

同じ host・collection ID・phase に固定された証跡だけを使用する。`Eth1/3` と `Ethernet1/3` は
数字部分を維持して照合し、breakout を親 port と混同しない。primary の Snapshot key は書き換えない。
同一 identity に複数 record が対応する場合は曖昧として `UNKNOWN` にする。

| primary / detail の状態 | 補完と単体判定 |
|---|---|
| primary が欠落・解析不能 | 従来どおり `UNKNOWN`。詳細出力だけで対象一覧を置き換えない |
| `xcvrAbsen` 等、detail は admin-down / oper-down | admin-down を明示証跡で確定し、単体判定の異常対象から除外 |
| `xcvrAbsen` 等、detail は admin-up / oper-down | admin-up／operational-down として `FAIL` |
| `xcvrAbsen` 等、detail の source／当該 port／admin 行が不足 | admin 不明の `UNKNOWN` を維持 |
| `connected` または `disabled` と detail が一致 | 明示的な admin state を採用し、通常の判定を行う |
| primary の operational state と detail の operational state が不一致 | 収集時点差を含む不整合として当該 port を `UNKNOWN`。新しい方を自動採用しない |
| `connected` と detail admin-down、または `disabled` と detail admin-up | 明示的な証跡の矛盾として当該 port を `UNKNOWN` |
| detail 自体が admin-down / oper-up | 内部矛盾として当該 port を `UNKNOWN` |
| その他の既知 Status と正常な detail | operational 状態の一致を確認し、Status から推定した admin 値より detail の明示値を優先 |
| detail がない旧ログ、または補完できない detail | primary だけで確定できる既存判定は維持し、未装着の admin 不明は `UNKNOWN`。不足理由を evidence に残す |

Status の未知 token は、detail の有無にかかわらず既存の primary parse error とする。
detail にしか現れない port は補完対象へ追加せず、未照合の証跡として保持する。
物理 port 以外は本項による補完を行わず、既存 SVI 補完や他 check の結果を変えない。

補完した値は `interface_health` の評価用 view と `HealthResult.after.interfaces` に保持し、元の
Snapshot は変更しない。各 port の `after.interface_state_sources` に採用 command ID、admin の由来
（`interface_detail`／`interface_status`／`unknown`）、詳細 block の行範囲、矛盾・不足理由を記録する。
旧 Snapshot の未装着 admin-up を無効化する保護は、正常な明示 detail で補完できた場合だけ解除する。

判定は port ごとに確定してから集約する。確定した異常があれば `FAIL`、異常がなく不明・矛盾があれば
`UNKNOWN`、すべて確認できれば `PASS`。admin-down だけの host は既存どおり `PASS` とする。
message と `after.admin_state_unknown` に不明 port を残し、矛盾 port は `after.interface_state_conflicts`
へも理由付きで記録する。`FAIL` と不明が混在しても不明証跡を隠さない。

##### e. 前後比較・証跡・互換性

- before／after それぞれで補完・矛盾検出を行ってから、既存の operational-up 消失判定を行う。
  before が up、after が未装着で双方の operational 状態を信頼できる場合は、after の admin-down に
  かかわらず `FAIL / regression`。両時点とも未装着・admin-down と確認できれば `PASS`。
- operational 証跡が矛盾する port は up 集合の差分から `FAIL` と断定せず `UNKNOWN` とする。
  admin 証跡だけが不足していても、operational-up から down の変化を両時点で確認できれば `FAIL`。
  詳細 source 自体の取得漏れを port の消失と扱わず、primary の欠落・破損も `UNKNOWN` にする。
- 旧 Snapshot の interface key による前後比較は維持する。今回の短縮形照合は同一 Snapshot 内の
  source 統合だけに使用し、過去の比較 identity を暗黙に変更しない。
- check evidence に primary と detail の両 source を含め、command、path、hash、取得時刻、parser
  version、行範囲へ追跡可能にする。`show interface` の原文全体を Checklist へ転載しない。
- Snapshot schema v1 内の追加 optional object とし、既存 field は削除しない。採用前に object 内の
  state、型、identity、行範囲を検証する。parser と補完ロジックの version を Snapshot provenance に記録する。
- baseline profile は `1.9`、NX-OS parser は `1.22`。固定済み profile や過去の
  Snapshot／HealthResult は上書きしない。
- 既存 operation の after は before の profile を継承するため、新 command を暗黙追加しない。
  新規 before または既存の明示 profile revision 手順で新 command を採用する。独自 profile は
  command の追加が必要。旧ログは import 可能なままとし、未装着の `UNKNOWN` は維持する。
- command 失敗・解析不能は既存の collection／parser の error 表示を使い、想定済みエラーで Traceback を
  出さない。追加の承認 prompt や自動設定投入は導入しない。
- retry は新 attempt を作り、部分収集済みの旧 attempt に追記しない。Snapshot／HealthResult の公開前に
  必須成果物と hash を検証し、処理失敗時は以前の成功済み current を維持する。rollback phase にも同じ
  読み取り判定を適用し、設定 rollback の所有範囲は変えない。

##### f. 実装順序・受け入れ条件

1. command ID、profile、role 共通収集、collect／transcript adapter を接続する。追加 command が
   host ごとに 1 回だけ実行対象となり、baseline 単独と Overlay 併用で同じ証跡を使うことを確認する。
2. 複数 port の CLI text fixture と parser を追加する。up、shutdown、未装着＋admin-up／down、
   大文字小文字、breakout、対象外 block、未知理由、未知 state、admin 行欠落、重複、途中切れを検証する。
3. Snapshot の別 field 保存と統合用 helper を追加し、評価器から raw text を再解析しない。
   正常 port と破損 port の混在、短縮形、矛盾、詳細だけに現れる port、旧 Snapshot の無変更を検証する。
4. 単体・比較の表を parameterized test 化する。特に未装着＋admin-down の誤 `FAIL` 解消、
   未装着＋admin-up の `FAIL`、欠落の `UNKNOWN`、up からの喪失、矛盾と既存異常の混在を検証する。
5. 収集後／解析前／公開前の失敗を模擬し、旧成功 current と新失敗 attempt の共存、retry の新 attempt、
   source hash の破損、CLI エラー・成果物への evidence 出力を確認する。
6. profile／parser version、配布 command sample、manual、設計の現行仕様、実装状況、golden 成果物の
   provenance を更新し、既存の `interface_health`／utilization／SVI／Overlay 回帰テストを実行する。

9000v／hardware への接続は対象指定を含む承認を得た検証だけで行い、通常の単体テストは offline とする。
実装前に実機検証済みとは記載しない。光レベル判定、詳細 counter 判定、非物理 interface の補完、
個別 port の条件付き再収集、構造化 NX-API JSON は今回の範囲外とする。

offline の受け入れ確認は [interface detail test](../../../tests/test_health_interface_detail.py)で実施する。
1,024 port の合成出力、既存 collector の timeout 伝播と失敗証跡、両入力 adapter、phase 別の行範囲、
部分解析、矛盾、旧 Snapshot、単体・比較、成功済み current を保持する retry を対象とする。

### 7.10 NTPと装置時刻

`network-baseline-nxos` `1.9`／NX-OS parser `1.22` で、配布状態を時刻未同期と混同する不具合を修正した。
追加 command や CLI option は不要。既存の同一 host・phase・collection の CLI text を使用する。
`thresholds.ntp.required` の既定は `false`。調査時の不具合と再現入力は
[NTP 実装レビュー](../../as-is/NTP_HEALTH_CHECK_REVIEW.md)に記録し、本節を修正仕様の正本とする。

#### 7.10.1 Command と解析箇所

| command / ID | 解析 anchor と取得値 | 利用目的 |
|---|---|---|
| `show ntp status` / `ntp_status` | 行頭 `Distribution : <state>`、`Last operational state: <state>` | `common.ntp.distribution` に配布状態を保存。`Disabled`／`No session` から時計の未同期・未設定を推定しない |
| 同上（従来入力との互換） | `Clock is synchronized`／`Clock is unsynchronized`、`stratum <n>`、`reference is <address>` | 明示された `synchronized` と `status_kind: clock`、stratum、reference を保存。配布状態との併記でも混同しない |
| 同上 | 明示的な `NTP is not configured`／`No NTP configuration` | `configured: false`、`status_kind: not_configured`。他の出力に peer があれば矛盾 |
| `show ntp peers` / `ntp_peers` | `Peer IP Address / Serv/Peer` の一覧、または従来の marker 付き address 行 | `common.ntp.peers.<address>`。通常の NX-OS 一覧には選択 marker がないため、marker 不在を非同期の証拠にしない。従来入力の `*` は selected として保持 |
| `show ntp peer-status` / `ntp_peer_status` | `Total peers`、`remote local st poll reach delay vrf` の列、行頭 `*`／`+`／`-`／`=` | `common.ntp.peer_status.peers.<remote>`。`*` は選択済み、`st` は stratum、`reach` は到達履歴。local、poll、delay、VRF、行範囲も保存 |
| `show clock` / `clock` | `Time source is ...` | `clock_time_source` に補助証跡として保持。単独では同期／未同期を確定しない |

大小文字と列間の空白差を許容し、IP address は IPv4／IPv6 として検証して正規化する。
peer-status の `delay` と `vrf` の連結（例 `0.00107management`）は数値部と VRF 部を分離する。
未知 marker、壊れた行、未知の数値、`Total peers` と解析行数の不一致を黙って読み飛ばさない。
同じ正規化 remote address が複数行に現れた場合は、別 VRF でも現在の辞書表現では曖昧なため
source 全体を parse error とする。上書きや任意の行選択はしない。

`reach` の表示は 8 bit の八進表記（`0`～`377`）。互換 field `reach` は従来の表示数字の整数値を維持し、
`reach_text` に表示文字列、`reach_value` に八進解釈した 0～255 の値を追加する。
判定は `reach_value > 0` とし、`377` まで埋まっていることは必須にしない。
`poll`、`delay` に新しい合否閾値は設けない。

空 text は取得・解析不能であり、未設定と扱わない。明示的な peer 0 件、空の正規一覧表、
`No NTP peers` は正常な空集合として区別する。CLI error と transport 失敗は既存 source 証跡を残す。

外部 transcript の末尾に残る単独 CLI prompt は表の行として扱わない。途中の不明行は
読み飛ばさず解析不能とし、raw file の行番号は維持する。

#### 7.10.2 証跡の優先順位と単体判定

- `ntp_status` と `ntp_peers` は check の必須証跡。source の欠落、収集失敗、解析不能は `UNKNOWN`。
- 正常な `ntp_peer_status` を選択状態と peer 健全性の優先証跡にする。同期可否は配布状態から作らない。
- peer-status の欠落・transport 失敗・CLI 非対応では、従来の明示同期状態と marker 付き peers が
  そろっている場合だけ代替評価する。配布状態と通常の peers 一覧だけでは同期不明の `UNKNOWN`。
- peer-status の壊れた行・重複・件数不一致は `UNKNOWN`。部分集合への fallback で異常を隠さない。
- 明示的な未設定と peer 存在、明示的な未同期と選択済み健全 peer は矛盾として `UNKNOWN`。
- 設定済みだが詳細 peer が 0 件、または selected address が通常 peers 一覧にない場合も
  source 間不整合として `UNKNOWN`。収集時点の違いを推測で解消しない。

| 観測結果 | NTP 任意 | NTP 必須 |
|---|---|---|
| 正常な空の peers、明示同期・peer 存在の矛盾なし | `NOT_APPLICABLE` | `FAIL` |
| 詳細の selected peer あり、全 selected peer の `reach_value > 0`、stratum 1～13 | `PASS` | `PASS` |
| 詳細 peer は存在するが selected なし、または selected peer の reach 0／stratum 0・14～16 | `WARN` | `FAIL` |
| 詳細取得不可だが従来入力で明示同期＋selected peer を確認 | `PASS` | `PASS` |
| 従来入力で明示未同期、または明示同期だが selected なし | `WARN` | `FAIL` |
| 同期証跡不足、解析不能、source 間矛盾 | `UNKNOWN` | `UNKNOWN` |

stratum 上限 13 は、本 project の対応候補である NX-OS 10.4(5)M 以降に適用する。
[Cisco の Nexus 9000 向け確認手順](https://www.cisco.com/c/en/us/support/docs/switches/nexus-9000-series-switches/221746-configure-network-time-protocol-on-nexus.html)
が示す 10.1(1) 以降の制約に従う。範囲外 release の動作保証へ拡張しない。
local reference clock を禁止する policy は今回追加せず、既存の選択済み peer 判定対象を維持する。

配布状態の command 定義は
[NX-OS 10.4(x) command reference](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/show/b_n9k_show_commands_104x/m_n_showcmds.html)、
列と表示例は [NX-API CLI reference](https://developer.cisco.com/docs/cisco-nexus-9000-series-nx-api-cli-reference/latest/ntp-commands/)を参照する。

正常例（架空 address）では、`show ntp status` が `Distribution : Disabled`／
`Last operational state: No session` でも、`show ntp peers` に `192.0.2.123 Server` があり、
`show ntp peer-status` が次の内容なら `PASS` とする。

```text
Total peers : 1
remote        local       st poll reach delay   vrf
*192.0.2.123   192.0.2.10  3  64   377   0.00107management
```

この例では行頭 `*`、`st=3`、`reach=377`（正規化値 255）を判定し、
`delay=0.00107` と `vrf=management` を分離して証跡に保存する。

#### 7.10.3 前後比較、証跡と互換性

両 phase に同じ正規化・評価を行い、確定した同期喪失または選択済み peer 消失を `FAIL / regression` とする。
片側が同期不明・解析不能なら比較も `UNKNOWN` とし、空集合との差分で稼働喪失を捏造しない。
address は正規化して比較し、両側で VRF が明示されている場合は VRF の変化も peer の変化として扱う。
旧入力などで VRF がない場合は従来の address 比較を維持する。正常な切替でも旧 selected peer の
消失を regression にする従来 policy は変更しない。

元 Snapshot を変更せず、評価用の `after.synchronized`、`synchronization_source`、`selected_peers`、
`unhealthy_selected_peers`、不足・矛盾理由を結果へ保存する。compare の before にも同じ評価値を保存し、
evidence に両 phase の source file／hash／command／parser version／行範囲を残す。
詳細 row の行番号は Snapshot Builder が raw file の絶対行番号へ変換する。

旧 Snapshot の `operational_state: No session` に由来する `synchronized: false` は、明示同期の証跡と
して信用せず、正常な詳細 source があれば再評価する。旧 parser が行を失った場合は `Total peers` との
不一致も検証し、復元できない field を推測しない。必要時は元 raw を新 parser で別成果物へ再 import する。
旧 Snapshot に正常な詳細 source がなければ、配布状態だけで正常へ補完しない。
追加 field は Snapshot schema v1 の optional field とし、旧 `reach` の表現と source／profile 固定は維持する。
parser `1.22`、profile `1.9`、Snapshot Builder `1.4`、`ntp_state: 1.0` を provenance に記録する。

受け入れテストは正常 selected＋配布 Disabled、列連結、IPv6、stratum と reach 境界、空／破損／重複、
source 欠落・非対応、NTP 必須、旧 Snapshot、前後比較、両入力 adapter と根拠行を対象とする。
実機接続は今回の offline テストに含めない。

#### 7.10.4 装置時刻

`clock_health` は直接収集または `alred-collect` の `show clock` について、device 時刻を command artifact の
`COLLECTED_AT` と比較する。60 秒超を `WARN`、300 秒超を `FAIL` とし、安全に日時を解析できなければ `UNKNOWN`。
`nxos-transcript` では実際の取得時刻を保証しないため `NOT_APPLICABLE` とし、import 時刻で代用しない。
`show version` の uptime が before より短い場合は、明示した再起動作業を除き `FAIL / regression` とする。

### 7.11 interface error counter

`interface_error_health`は`show interface counters errors non-zero`を使用し、afterの絶対値ではなく
beforeからの増加量を基本判定値とする。既定は増加1以上を`WARN`、100以上を`FAIL`とし、counter
種別およびinterface roleごとにprofileで上書き可能とする。

- counterが減少し、同期間にuptime減少がある場合は再起動後resetとして扱い、単純差分を出さない
- counterが減少し、resetを説明できない場合は`UNKNOWN`とする
- wrapを安全に識別できるcounter幅がない場合は増加量を推測しない
- 新規interfaceはbefore値がないためabsolute値を証跡として保持し、既定`WARN`とする
- `show interface` は admin 状態補完に使用するが、詳細 counter は本 check の入力にしない。
  同 command の取得失敗だけで `interface_error_health` を `UNKNOWN` にしない

### 7.12 port-channel / LACP

port-channelが設定されている場合、`show port-channel summary`を必須証跡として
`port_channel_health`を実行する。`show lacp internal info`はmember状態の補完証跡とする。
収集成功かつ出力が空の場合は port-channel 未設定として `NOT_APPLICABLE` とする。NX-OS の
virtual vPC peer-link のように protocol が `NONE` で physical member を持たない Up port-channel は、
member 欠落を異常とせず channel の Up 状態を確認する。LACP など member を持つ protocol では、
従来どおり bundled member がない状態を異常とする。

| 状態 | 結果 |
|---|---|
| port-channelと期待memberがUp / bundled | `PASS` |
| configured port-channelがdown | `FAIL` |
| beforeよりbundled memberが減少 | `FAIL / regression` |
| member状態を安全に解析できない | `UNKNOWN` |
| port-channel未設定 | `NOT_APPLICABLE` |

期待member数をprofileで宣言した場合はその値を優先し、未宣言時はbeforeのbundled member集合を
baselineとする。意図したmember追加・削除は7.4のexpected changeとして宣言し、計画外のmember
変化を隠さない。

### 7.13 hostname identity

`show version`のHardware sectionにある`Device name: <hostname>`を識別anchorとし、値の前後空白だけを除いて
`common.system.reported_hostname`へ保存する。inventory keyをexpected hostnameとし、大文字・小文字を含めて
完全一致比較する。

| 状態 | 判定 |
|---|---|
| `Device name`がinventory hostnameと一致 | `PASS` |
| `Device name`が不一致 | `FAIL` |
| `show version`取得失敗、anchor欠落、値が空 | `UNKNOWN` |

before／afterでも各Snapshotをinventory hostnameと個別に比較する。接続確認でdefault hostname `switch`を
初期設定候補としてwarning扱いする規則はmutation前の安全gateであり、正常性確認ではinventory不一致のため
`FAIL`とする。

### 7.14 interface利用率

`show interface counters table`は、次の2種類のtext table headingを識別anchorとする。

- `Port`、`Description`、`Interval`、`InRate(Mbps)`、`InRate(%)`、`OutRate(Mbps)`、`OutRate(%)`
- C9300v 10.5(4)で観測した`Port`、`Description`、`Intvl`、`Rx Mbps`、`Rx %%`、`Tx Mbps`、`Tx %%`

`InRate`／`Rx`をinput、`OutRate`／`Tx`をoutputへ正規化する。headingの各column開始位置をanchorにして
続くrowをsliceし、固定幅いっぱいのdescriptionと`Intvl`の間に空白がない場合もdescription末尾の数字を
intervalへ誤結合しない。単一の`Interval`値はinput／output共通秒数、`Intvl`の`<rx>/<tx>`はそれぞれ
`input_load_interval_seconds`／`output_load_interval_seconds`として整数化する。両方向が同じ場合は後方互換field
`load_interval_seconds`にも同じ値を保持する。

interface、description、interval、input rate Mbps、input rate %、output rate Mbps、output rate %の必須column、
または数値を識別できない場合は空集合や0へ補完せずparser errorとする。descriptionの`N/A`および`--`は
未設定として`null`へ正規化する。JSON sidecarは初期実装の対象外とする。

初期対象はoperational-upのEthernetとport-channelとし、management、loopback、SVI、NVE、admin-downまたは
operational-down interfaceは利用率判定から除外する。`show interface counters table`の`Ethernet`／`port-channel`と
`show interface status`の`Eth`／`Po`は、数字部分を維持した同一identityとして照合する。evidenceには各commandで
観測したinterface表記を保持する。inputとoutputを合算せず`max(input_percent, output_percent)`を判定値とする。
各方向はfull-duplex capacityに対する独立した利用率である。

```yaml
interface_utilization:
  info_percent: 50
  warn_percent: 70
  fail_percent: 90
```

閾値は`0 <= info < warn < fail <= 100`を必須とし、境界値を含めて次のように判定する。

| 最大利用率 | check result | Checklist表示 |
|---:|---|---|
| 50%未満 | `PASS` | `PASS` |
| 50%以上70%未満 | `PASS` | overallを悪化させない`INFO` |
| 70%以上90%未満 | `WARN` | `WARN` |
| 90%以上 | `FAIL` | `FAIL` |

result evidenceにはinterface、input／output rate、input／output percent、判定に使用した最大値、方向別load interval、
command、raw fileを残す。利用率fieldが欠落または数値変換不能ならそのinterfaceを0%とせず`UNKNOWN`とする。before／afterでは
afterの閾値判定に加え、beforeの判定値とlevelを`before`へ残し、悪化を`regression`、継続を`pre_existing`とする。

device計算rateはload interval内の平均でありmicroburstを示さない。queue drop／buffer congestionは
`show interface counters errors non-zero`などのerror／discard evidenceを併用し、model依存queue commandは
本checkへ推測統合しない。

field名と単位の根拠は[Cisco Nexus 9000 Series NX-OS Command Reference - `show interface counters table`](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/101x/command-reference/show/b_n9k_show_commands_101x/m_i_showcmds.html)とする。
将来の補完checkではqueue drop historyとmicro-burst monitoringを別resourceとして扱う。micro-burstは対応model／release、
queueごとの設定、rise／fall thresholdに依存するため、本checkの平均利用率から推測しない。仕様根拠は
[Cisco Nexus 9000 Series NX-OS Quality of Service Configuration Guide - Micro-Burst Monitoring](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/102x/configuration/qos/cisco-nexus-9000-nx-os-quality-of-service-configuration-guide-102x/m-configuring-microburst-monitoring.html)とする。

### 7.15 dynamic BGP neighbor range

running configではindent 0の`router bgp <local-as>`をprocess anchorとする。process直下のindent 2にある
`template peer <name>`、`neighbor <address-or-prefix>`、`vrf <name>`を識別し、VRF配下ではindentを2つ戻した
`neighbor`を同じfieldへ正規化する。`inherit peer <name>`を多段展開し、`address-family ipv4 unicast`／
`address-family ipv6 unicast`、`remote-as`、resolution statusをprocess／VRF／neighbor単位で保存する。
`neighbor`の値に`/`があるIPv4／IPv6 prefixをdynamic range、host addressをstatic peerとして区別する。

operational outputでは`BGP summary information for VRF <vrf>, address family IPv4 Unicast`または
`IPv6 Unicast`をVRF／address family anchorとし、同blockの`Neighbor V AS ... State/PfxRcd` rowからaddress、
remote AS、uptime、state、Established時の受信prefix数を取得する。dynamic prefixごとに同じVRF／address familyの
summary neighbor addressを包含判定し、range単位で`matched_neighbors`と`established_neighbors`を保存する。
template未解決、address／prefix不正、summary headingまたはrowの未認識を正常な0件へ変換しない。

| 状態 | 単体判定 | before／after |
|---|---|---|
| range内にEstablished peerが1件以上、非Establishedなし | `PASS` | 維持なら`PASS` |
| range内のpeerが0件 | `WARN` | beforeも0件なら`pre_existing`、beforeに存在した場合は`FAIL` regression |
| range内に非Established peerあり | `FAIL` | 新規または悪化は`FAIL` regression |
| configまたはsummary evidence不足 | `UNKNOWN` | `UNKNOWN` |

IPv4とIPv6を同じ規則で処理する。overlapするrangeは各rangeへ対応関係を残し、総peer数だけで一方を正常と推測しない。

## 8. 閾値の初期案

固定値をコードへ埋め込まずprofileで変更可能にする。

```yaml
thresholds:
  logging:
    severity_threshold: 4
    lookback_seconds: 604800
    include_patterns: []
    exclude_patterns: []
  cpu:
    warn_percent: 80
    metric: one_minute_percent
    required_consecutive_samples: 3
    sample_interval_seconds: 15
    sustained_action: confirm_continue
    non_interactive_action: abort
  memory:
    warn_percent: 85
    fail_percent: 95
  interface_errors:
    warn_delta: 1
    fail_delta: 100
  clock:
    warn_offset_seconds: 60
    fail_offset_seconds: 300
  route_count:
    warn_decrease_percent: 10
    fail_decrease_percent: 30
```

CPU、memory、route数、counterは自然変動するため、単発の値だけでFAILにしない。実運用データを取得した後に既定閾値を調整する。

## 9. profile例

```yaml
api_version: alred/v1
kind: HealthCheckProfile

metadata:
  name: network-baseline-nxos
  version: "1.0"

spec:
  platforms:
    - nxos

  command_sets:
    - core

  auto_features:
    ntp: true
    ipv6: true
    port_channel: true
    vpc: true
    bfd: true
    ospf: true
    bgp_unicast: true

  thresholds:
    ntp:
      required: false

  checks:
    logging:
      severity: warn
    unsaved_config:
      severity: warn
    preserve_neighbors:
      severity: fail
    preserve_interfaces:
      severity: fail
```

## 10. 既存show_commands.txtとの関係

配布用 `alred/sample_configs/show_commands.example.txt` の `[device_type:nxos]` では、
`show interface` を有効な command として収集する。Health baseline profile `1.8` にも同 command を
追加し、7.9.10 の詳細 parser・admin 状態補完へ接続している。

既存の`alred/sample_configs/show_commands.example.txt`には、本一覧の多くがすでに含まれている。現行の
`show lldp neighbors detail`と`show running-config`は既存collectorのbase collectionが1回収集する。
Health profileから生成する`show-commands.txt`にはLLDPを先頭に表示するが、collectorはbase collection結果を
再利用し、追加commandとして再実行しない。running configはbase collectionと`raw/config/`の保存先を
`# show running-config`とともにコメント表示するが、実行可能なshow listには加えない。専用artifactを
Collection Manifestへ登録し、通常のcommand artifactや統合show logへ複製しない。
その他の収集計画は同じコマンド文字列を二重実行せず、次をマージする。

```text
既存show_commands.txt
    ∪ network-baseline-nxos profile
    ∪ 作業固有profile
```

結果ファイルでは、コマンドを要求したprofileを複数記録できるようにする。

```yaml
commands:
  show_logging:
    command: show logging
    requested_by:
      - network-baseline-nxos
      - nxos-overlay
    executed_once: true
```

## 11. 参考資料

- Cisco Nexus 9000 Series NX-OS Troubleshooting Guide, `show processes cpu`
  - https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/troubleshooting/guide/b-cisco-nexus-9000-nx-os-troubleshooting-guide-93x.pdf
- Cisco Nexus 9000 Series NX-OS Unicast Routing Configuration Guide, `show system config reload-pending`
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/unicast-routing-configuration/cisco-nexus-9000-series-nx-os-unicast-routing-configuration-guide/m-configure-dynamic-load-balancing.html
- Cisco Nexus 9000 Series NX-OS Command Reference, Show Commands
  - https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/show/b_n9k_show_commands_104x/m_s_showcmds.html
