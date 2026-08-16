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
| `inventory` | `show inventory` | chassis、module、serial | module交換・消失など構成差分 | Yes |
| `system_resources` | `show system resources` | CPU、memory、load | 閾値超過、beforeからの急増 | Yes |
| `processes_cpu` | `show processes cpu` | 5秒、1分、5分CPU使用率、process別使用率 | 80%以上でWARN、連続超過時は継続確認 | Yes |
| `processes_cpu_history` | `show processes cpu history` | CPU使用率履歴 | spikeの継続性を証跡保存 | Yes |
| `processes_memory` | `show processes memory` | process別memory | 使用量急増と原因候補 | Yes |
| `processes_memory_shared` | `show processes memory shared` | shared memory | 使用量変化を証跡保存 | Yes |
| `environment` | `show environment` | 温度、fan、power | 新規fail、alarm | Yes |
| `module` | `show module` | module、status、model | `ok`からの悪化、module消失 | Yes |
| `feature` | `show feature` | feature有効状態 | 意図しないenable/disable | Yes |
| `ntp_status` | `show ntp status` | synchronized状態、stratum | 同期状態の悪化 | Yes |
| `ntp_peers` | `show ntp peers` | peer一覧 | 選択peerの消失 | Yes |
| `ntp_peer_status` | `show ntp peer-status` | peerごとの状態 | configured peerの状態悪化 | Yes |
| `license_usage` | `show license usage` | license利用状態 | license状態の変化 | Yes |
| `license_all` | `show license all` | license詳細 | 作業証跡。重要状態変化をWARN | Yes |
| `interface_status` | `show interface status` | port state、VLAN、speed | 対象外portのconnectedからnotconnect等への悪化 | Yes |
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

Health判定の既定対象は、inventoryで識別できるmanaged network device間のlinkとする。

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
収集対象外ならlocal LLDPとlocal descriptionだけを照合し、逆方向証拠の欠落を異常にしない。
server、inventory未登録endpoint、外部回線は既定でHealth判定から除外するが、raw evidenceとTopologyの
candidateから削除しない。

| 観測状態 | 既定判定 |
|---|---|
| 双方向LLDPと解釈可能な両側descriptionが一致 | `PASS` |
| 双方向LLDPが一致し、descriptionがない | `PASS`。欠落を補足情報へ記録 |
| 同じlocal interfaceのLLDPとdescriptionが異なる | `WARN`。policyで`FAIL`へ厳格化可能 |
| 両端を正常収集済みだがLLDPが片方向だけ | `WARN` |
| LLDP command取得失敗、破損、対応parserで解釈不能 | `UNKNOWN` |
| description ruleに一致しない | `N/A`。不一致と推測しない |
| Health対象外endpoint | `N/A`。除外理由を記録 |

afterではneighbor消失、接続先／interface変更、新規不整合をbeforeからの差分として記録する。一時的な
LLDP未収束は既存のafter convergence待ちを適用し、timeout後の残存差分だけを最終判定する。

## 4. featureコマンド

### 4.1 NTP

NTPコマンドは作業時刻とログ時刻の信頼性を確認するため、既定で収集する。NTP未設定機器では`not_configured`として扱い、未設定だけをFAILにしない。profileで時刻同期を必須にした場合だけ、未設定または未同期を異常判定する。

| ID | コマンド | 取得内容 | 判定 |
|---|---|---|---|
| `ntp_status` | `show ntp status` | synchronized状態、stratum | synchronizedからunsynchronizedへの悪化 |
| `ntp_peers` | `show ntp peers` | peer一覧 | 選択peerの消失 |
| `ntp_peer_status` | `show ntp peer-status` | peerごとの状態 | configured peerの到達状態悪化 |

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
| Interface | `show interface` | counter、flap、line protocol詳細 |
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
show license all
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

### 6.1 Phase 3実装済み範囲

次の19 commandをC9300v 10.5(4) sanitized fixtureでparser検証済みとする。

```text
show version
show processes cpu
show system resources
show environment
show clock
show ntp status
show ntp peers
show ntp peer-status
show interface status
show interface counters errors non-zero
show port-channel summary
show system config reload-pending
show logging
show ip route summary vrf all
show ip ospf neighbors
show bgp ipv4 unicast summary vrf all
show vpc brief
show nve interface
show bgp l2vpn evpn summary
```

共通baselineではCPU、memory、environment、clock、NTP、interface、error counter、
port-channel、reload-pending、logging、IPv4 route count、OSPF、BGP IPv4、vPCを単体判定および
before / after比較へ接続した。NVEとEVPN BGPは
`nxos-overlay` profileの初期観測判定として接続した。

一覧中のその他の収集済みcommandは`parse_status: unsupported`としてprovenanceへ保持する。
必須profile commandがunsupportedまたは欠落した場合は正常と推定せず`UNKNOWN`とする。

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


### 7.9 interface状態

`interface_health` は `show interface status` と `show interface brief` を組み合わせ、admin state と
operational／line protocol を区別して判定する。単に `down` である全 port を異常にはしない。

NX-OS が `show interface status` の Status column を `notconnec` と表示する release／表示幅と、
`notconnect` と表示する出力は、canonical status `notconnect` へ正規化する。status の照合は大文字・小文字を
区別しない。`disabled` は admin down／operational down、`connected` は admin up／operational up、
`notconnec`／`notconnect`、`err-disabled`、`inactive`、`sfpAbsent` は admin up／operational down とする。

物理 interface、port-channel、management interface、loopback の行から未対応 status を検出した場合は、その行を
黙って除外して残りの行だけで `PASS` にしてはならない。`interface_status` 全体を parse 不能として記録し、
`interface_health` を `UNKNOWN`／`collection_error` とする。SVI の `down` は Status column だけでは admin state を
確定せず、`show interface brief` の Reason と組み合わせて判定する。

| admin | operational | before／after 条件 | 結果 | classification |
|---|---|---|---|---|
| down | down | 任意 | `NOT_APPLICABLE` | `normal` |
| up | up | 任意 | `PASS` | `normal` |
| up | down | before 単体または after でも継続 | `FAIL` | `target_not_ready` または `pre_existing` |
| up | down | before は up／after は down | `FAIL` | `regression` |
| 任意 | 取得・parse 不能 | 任意 | `UNKNOWN` | `collection_error` |

判定対象は物理 interface、port-channel、loopback、SVI を resource 単位で保持する。profile の
`required_interfaces` に指定した interface は before から down でも `FAIL` とする。未指定 interface でも
admin up／operational down は異常として表示するが、作業で意図した遷移は 7.4 の
`expected_changes.interfaces` により `expected_change` へ分類できる。ignore 対象を設定する場合も
check 自体を無効にせず、除外理由を成果物へ記録する。

### 7.10 NTPと装置時刻

NTPは`show ntp status`、`show ntp peers`、`show ntp peer-status`を同一checkの証跡として使用する。
profileの`thresholds.ntp.required`は既定`false`とし、未設定機器を一律異常にしない。
NX-OS の `show ntp status` が `Distribution : Disabled` または
`Last operational state: No session` を返すことだけでは NTP 未設定と判定しない。この出力は
operational session がない証跡として保持し、`show ntp peers` に configured peer があれば
`configured: true`、peer が空なら `configured: false` とする。明示的な `NTP is not configured`
または同等の出力も未設定とする。command 自体の欠落、command error、その他の未認識形式とは
区別する。

`show clock` の `Time source is NTP` は補助 evidence として保持する。ただし、選択 peer または
synchronized status がない状態をこの表示だけで `PASS` にしない。configured peer が存在し、
`No session` または未選択 peer だけが観測された場合は `configured but unsynchronized` として
`WARN`（`thresholds.ntp.required: true` では `FAIL`）にする。`show ntp peer-status` による詳細確認は
実装済みであり、selected、mode、remote/local、stratum、poll、reach、delay、VRFを証拠として保持する。

| 状態 | `required: false` | `required: true` |
|---|---|---|
| 未設定 | `NOT_APPLICABLE` | `FAIL` |
| synchronized、選択peerあり | `PASS` | `PASS` |
| configuredだがunsynchronized | `WARN` | `FAIL` |
| before同期済み / after未同期 | `FAIL / regression` | `FAIL / regression` |
| beforeの選択peerがafterで消失 | `FAIL / regression` | `FAIL / regression` |
| 必須出力の欠落・parse不能 | `UNKNOWN` | `UNKNOWN` |

`show ntp peer-status` は `syncmode`、remote/local address、stratum、poll、reach、delay、VRF を
正規化する。判定は次のとおりとする。

| peer-status | 判定 |
|---|---|
| status が synchronized、selected peer があり、stratum 1～15、reach 1 以上 | `PASS` |
| configured peer はあるが selected peer がない、`No session`、reach 0、または stratum 16 | `WARN`。NTP 必須時は `FAIL` |
| before の selected peer が after で消失、または synchronized から非同期 | `FAIL / regression` |
| peer-status の command 非対応・parse 不能だが status と peers は解析可能 | primary evidence による判定を継続し、peer-status の不足だけで `UNKNOWN` にしない |
| status または peers の必須 evidence が欠落・parse 不能 | `UNKNOWN` |

field と command の根拠は [Cisco Nexus 9000 Series NX-OS 10.4(x) Show Command Reference](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/command-reference/show/b_n9k_show_commands_104x/m_n_showcmds.html#wp2274317467) と [Cisco Nexus 9000 Series NX-API CLI Reference - NTP Commands](https://developer.cisco.com/docs/cisco-nexus-9000-series-nx-api-cli-reference/latest/ntp-commands/) とする。

profile が check を定義しているにもかかわらず対応 command が Collection Manifest にない場合は、
機能が対象外とは判定せず `UNKNOWN / collection_error` とする。`NOT_APPLICABLE` は、収集済み出力、
running config、platform capability のいずれかから機能未設定または非対応を確認できた場合だけ使用する。

`clock_health`は`show clock`のdevice時刻をcollection開始・完了時刻の範囲と比較し、timezoneを
正規化してoffsetを記録する。初期既定は60秒超を`WARN`、300秒超を`FAIL`とし、profileで変更可能
とする。安全にtimezoneまたは時刻を解釈できない場合は`UNKNOWN`とする。`show version`のuptimeが
beforeより短くなった場合は、明示した再起動作業を除き`FAIL / regression`とする。

```yaml
thresholds:
  clock:
    warn_offset_seconds: 60
    fail_offset_seconds: 300
  ntp:
    required: false
```

### 7.11 interface error counter

`interface_error_health`は`show interface counters errors non-zero`を使用し、afterの絶対値ではなく
beforeからの増加量を基本判定値とする。既定は増加1以上を`WARN`、100以上を`FAIL`とし、counter
種別およびinterface roleごとにprofileで上書き可能とする。

- counterが減少し、同期間にuptime減少がある場合は再起動後resetとして扱い、単純差分を出さない
- counterが減少し、resetを説明できない場合は`UNKNOWN`とする
- wrapを安全に識別できるcounter幅がない場合は増加量を推測しない
- 新規interfaceはbefore値がないためabsolute値を証跡として保持し、既定`WARN`とする
- diagnosticの`show interface`は原因確認用であり、取得失敗だけで元checkを`UNKNOWN`にしない

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

既存の`alred/sample_configs/show_commands.example.txt`には、本一覧の多くがすでに含まれている。現行の
収集計画は同じコマンド文字列を二重実行せず、次をマージする。

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
