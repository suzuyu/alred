# Health Check Execution Scenarios

## 1. 文書の目的

共通Health Check FrameworkとOverlay Change Managementを、実際の作業でどの順序・CLIで利用するかをシナリオ別に示す。

本書の実行例は、個別に「設計案」と明記したものを除き現行実装済みCLIに合わせる。optionの正本は
[Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md)、Overlay固有仕様は
[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)、実装状態は
[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md)とする。

## 2. 共通前提

### 2.1 記載方針

この文書には、シナリオを実行するための最小設定例と、作業者が最初に確認する代表出力を記載する。完全なschemaや全コマンドを重複記載すると仕様差異が発生するため、詳細は次の正本文書を参照する。

| 情報 | この文書 | 正本 |
|---|---|---|
| 最小`hosts.txt`、生成後`hosts.yaml`、`.env`、ChangeSet | 実行可能な最小例を記載 | [CONFIG.md](../../../CONFIG.md)、[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md) |
| showコマンド | 利用するファイルと注意点を記載 | [NX-OS Baseline Health Check Commands](./NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)、[show_commands.example.txt](../../../alred/sample_configs/show_commands.example.txt) |
| 端末summary | シナリオ結果が分かる短い例を記載 | [Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md) |
| Snapshot、manifest、JSON | 主な確認箇所だけ記載 | [Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md) |
| CLI option | シナリオで使用する値だけ記載 | [Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md) |

### 2.2 `.env`

```env
# .env
ALRED_TIMEZONE=Asia/Tokyo
ALRED_USERNAME=admin
ALRED_PASSWORD=replace-with-secret
```

認証情報を`.env`へ保存しない場合は、既存CLIの`--ask-pass`またはcredentials YAMLを使用する。本設計では実値を成果物へ出力しない。

### 2.3 `hosts.txt`から`hosts.yaml`を生成

`hosts.yaml`は手書きせず、既存の`prepare-hosts`で`hosts.txt`から生成することを標準手順とする。

`hosts.txt`の最小例:

```text
192.0.2.11 leaf01 # nxos
192.0.2.12 leaf02 # nxos
192.0.2.21 spine01 # nxos
```

生成コマンド:

```bash
alred prepare-hosts \
  --input hosts.txt \
  --output hosts.yaml
```

生成される`hosts.yaml`の例:

```yaml
all:
  hosts:
    leaf01:
      ansible_host: 192.0.2.11
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos

    leaf02:
      ansible_host: 192.0.2.12
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos

    spine01:
      ansible_host: 192.0.2.21
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
```

以後のシナリオでは、この生成済み`hosts.yaml`を`--hosts hosts.yaml`で指定する。`hosts.txt`と生成形式の完全仕様は[CONFIG.md](../../../CONFIG.md)を参照する。

外部CLI transcriptのprompt名は、原則として`hosts.txt`のhostnameと一致させる。将来alias拡張を利用する場合も、`prepare-hosts`の生成物を正本とし、手編集で都度差分を加える運用にはしない。

### 2.4 `show_commands.txt`

最初に既存の`generate-sample-config`でサンプル一式を`samples/`へ生成する。

```bash
alred generate-sample-config
```

S3で既存collectを使う場合は、生成されたファイルを作業用ファイルへコピーする。

```bash
cp samples/show_commands.example.txt show_commands.txt
```

`samples/show_commands.example.txt`が既に存在する場合、`generate-sample-config`は既定で上書きしない。テンプレートの更新を明示的に反映する場合だけ、既存内容を退避・確認したうえで次を実行する。

```bash
alred generate-sample-config --force
```

コマンド全量はシナリオ文書へ重複記載せず、`generate-sample-config`が生成する`samples/show_commands.example.txt`を利用する。元となる同梱テンプレートは[show_commands.example.txt](../../../alred/sample_configs/show_commands.example.txt)、判定上の必須コマンドは[NX-OS Baseline Health Check Commands](./NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)を正本とする。

profileが要求する必須コマンドが含まれていることを、Snapshot生成時のcollection completenessで確認する。

### 2.5 `desired-changes.yaml`

S5で使用する宣言済みChangeSetの最小例:

```yaml
api_version: alred/v1
kind: OverlayChangeSet

metadata:
  change_id: CHG-2026-00123
  source: declared

spec:
  device_groups:
    server-leafs:
      devices:
        - leaf01
        - leaf02

  l2vnis:
    - vni: 10010
      default_vlan: 10
      vlan_name: TENANT-A-WEB
      vrf: TENANT-A
      l3vni: 50001
      svi:
        mtu: 9216
        ipv4_addresses:
          - 192.0.2.1/24
        ipv6_addresses:
          - 2001:db8:10::1/64
        ipv6_link_local: fe80::1
        gateway_mode: anycast
      targets:
        groups:
          server-leafs: {}

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
      targets:
        groups:
          server-leafs: {}
```

device override、group別VLAN、SVI不要機器などを含む完全例は[Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照する。

### 2.6 profile

通常のEVPN/VXLAN作業では、既存Fabricへの影響とOverlay固有状態を確認するため、次の2つのprofileを併用する。

```text
network-baseline-nxos
nxos-overlay
```

例では次のファイルを使用する。

```text
hosts.txt                          prepare-hostsへの機器入力
hosts.yaml                         prepare-hostsが生成したinventory
show_commands.txt                  既存collectで取得するコマンド
desired-changes.yaml               宣言済みOverlay ChangeSet
external-before-logs/              外部収集したbefore CLIログ
external-after-logs/               外部収集したafter CLIログ
operations/<change-id>/          作業全体のworkspace
```

## 3. シナリオ一覧

| ID | シナリオ | 機器収集 | 設定投入 | ChangeSet |
|---|---|---|---|---|
| S1 | health-checkから直接収集し、外部・手動で設定投入 | alred | 外部・手動 | なし。before / afterから自動発見 |
| S2 | 自動採番を利用して直接収集 | alred | 外部・手動 | なし |
| S3 | 既存collectと解析を分離 | alredの既存collect | 外部・手動 | なし |
| S4 | alred以外で取得したCLIログを解析 | 外部ツール・手動 | 外部・手動 | なし |
| S5 | 宣言済みChangeSetをalred内で投入 | alred | alred | あり |
| S6 | 保存済みSnapshotをオフライン再比較 | 収集なし | なし | 自動発見済みまたは宣言済み |
| S7 | 定期・随時inspectionと修正後確認 | alred | 必要時だけ外部またはalred | なし |

## 4. S1: 直接収集＋外部・手動設定投入

### 4.1 before

```bash
alred health-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --logging-days 3 \
  --collect \
  --output operations/CHG-2026-00123
```
`show logging`を全期間確認する場合は`--logging-all`、特定日時以降を確認する場合は
`--logging-start-time "2026-08-01T09:00:00+09:00"`を使用する。省略時はprofileの
`time_range`または後方互換用`lookback_seconds`を使用する。


このコマンドは既存collect処理を利用して機器へ接続し、次を行う。

1. baselineとOverlayのshowコマンドを収集
2. `resolved-profiles.yaml`を固定
3. before Snapshotを生成
4. CPU、reload-pendingなどを評価
5. Operation Gateが必要なら作業継続を確認

代表出力:

```text
=== HEALTH CHECK BEFORE SUMMARY ===
Change ID : CHG-2026-00123
Profile   : network-baseline-nxos, nxos-overlay
Hosts     : 3
Result    : PASS

Checks:
  PASS           46
  WARN            0
  FAIL            0
  UNKNOWN         0
  NOT_APPLICABLE  3

Snapshot : operations/CHG-2026-00123/health/before/snapshot.json
Report   : operations/CHG-2026-00123/health/before/checklist.md
===================================
```

### 4.2 外部・手動で設定投入

別システム、作業者のCLI、既存自動化などでL2VNI / L3VNI設定を投入する。この段階でalredへ投入内容を渡す必要はない。

### 4.3 after

```bash
alred health-check after \
  --change-id CHG-2026-00123
```

afterではbeforeのprofileに加え、inventory、policy、対象host、収集方法、transport、timeoutを
`health/execution-context.yaml`から再利用するため、通常は`--profile`、`--hosts`、`--collect`を
再指定しない。passwordとenable secretは保存せず、環境変数またはcredentials fileから再解決し、
beforeで対話・CLI入力した場合はafterで再入力する。

代表出力:

```text
=== HEALTH CHECK AFTER SUMMARY ===
Change ID : CHG-2026-00123
Result    : PASS

Changes:
- L2VNI 10010 added on leaf01, leaf02
- L3VNI 50001 added on leaf01, leaf02

Regressions: 0
Warnings   : 0

Report : operations/CHG-2026-00123/health/report/summary.md
JSON   : operations/CHG-2026-00123/health/report/health-result.json
==================================
```

### 4.4 Overlay変更の自動発見

```bash
alred overlay-check discover \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/overlay
```

主な確認先:

```text
operations/CHG-2026-00123/health/report/summary.md
operations/CHG-2026-00123/health/report/health-result.json
operations/CHG-2026-00123/overlay/discovered-changes.yaml
operations/CHG-2026-00123/overlay/overlay-summary.md
```

`discovered-changes.yaml`の要約例:

```yaml
metadata:
  change_id: CHG-2026-00123
  source: discovered

spec:
  l2vnis:
    - vni: 10010
      default_vlan: 10
      vlan_name: TENANT-A-WEB
      vrf: TENANT-A
      l3vni: 50001
      targets:
        devices:
          leaf01: {}
          leaf02: {}

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
      targets:
        devices:
          leaf01: {}
          leaf02: {}
```

完全な出力schemaとWARN / FAIL例は[Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md)を参照する。

## 5. S2: Change IDを自動採番

### 5.1 before

```bash
alred health-check before \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect
```

出力例:

```text
Generated Change ID: HC-20260725T100203-p0900-a1b2c3
Timezone: Asia/Tokyo (+09:00)
Output: operations/HC-20260725T100203-p0900-a1b2c3/
```

表示されたIDを作業記録へ保存する。

### 5.2 after

afterは新しいIDを自動採番せず、`--change-id`省略時はactive change stateから直前の自動採番beforeを引き継ぐ。

```bash
alred health-check after
```

出力例:

```text
Change ID was not specified.
Using active before Change ID: HC-20260725T100203-p0900-a1b2c3
Before completed at: 2026-07-25T10:05:31+09:00
```

active changeを一意に検証できない場合は自動選択せず、beforeで表示されたIDを明示する。

```bash
alred health-check after \
  --change-id HC-20260725T100203-p0900-a1b2c3
```

## 6. S3: 既存collectと解析を分離

設定投入前後の収集を既存collectで行い、正常性確認は収集済み成果物だけを読む。

`show_commands.txt`には、`network-baseline-nxos`と`nxos-overlay`が必須とするコマンドを含める。必要なコマンドが不足した場合、Snapshot Builderは不足項目を正常と推定せず`UNKNOWN`またはcollection不成立として報告する。

### 6.1 beforeログ収集

```bash
alred collect-all \
  --hosts hosts.yaml \
  --show-commands-file show_commands.txt \
  --output raw-before
```

### 6.2 before Snapshot生成

```bash
alred health-check snapshot \
  --input raw-before \
  --input-format alred-collect \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before
```

### 6.3 外部・手動で設定投入

この間に対象設定を投入する。

### 6.4 afterログ収集

```bash
alred collect-all \
  --hosts hosts.yaml \
  --show-commands-file show_commands.txt \
  --output raw-after
```

### 6.5 after Snapshot生成

```bash
alred health-check snapshot \
  --input raw-after \
  --input-format alred-collect \
  --phase after \
  --change-id CHG-2026-00123 \
  --output operations/CHG-2026-00123/health/after
```

### 6.6 比較

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/health/report
```

`snapshot`と`compare`は機器へ直接アクセスしない。

## 7. S4: 外部CLIログを解析

### 7.1 推奨する外部ログ

prompt、入力コマンド、出力を残す。

```text
leaf01# show processes cpu
CPU utilization for five seconds: 12%/3%; one minute: 10%

leaf01# show nve vni
...

leaf02# show processes cpu
CPU utilization for five seconds: 18%/4%; one minute: 13%
```

### 7.2 before Snapshot生成

```bash
alred health-check snapshot \
  --input external-before-logs \
  --input-format nxos-transcript \
  --hosts hosts.yaml \
  --phase before \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --output operations/CHG-2026-00123/health/before
```

`--hosts`は検出したprompt名とinventory hostname / aliasの照合に使用する。

### 7.3 設定投入後のログを解析

```bash
alred health-check snapshot \
  --input external-after-logs \
  --input-format nxos-transcript \
  --hosts hosts.yaml \
  --phase after \
  --change-id CHG-2026-00123 \
  --output operations/CHG-2026-00123/health/after
```

### 7.4 認識結果を確認

```text
operations/CHG-2026-00123/health/before/transcript-import-manifest.yaml
operations/CHG-2026-00123/health/after/transcript-import-manifest.yaml
```

`unresolved_segments`、`ambiguous_segments`、必須コマンド不足がある場合は、比較結果だけでなくimport manifestも確認する。

端末出力例:

```text
=== TRANSCRIPT IMPORT SUMMARY ===
Phase             : before
Files scanned     : 2
Hosts detected    : 3
Commands detected : 69
Unresolved        : 0
Ambiguous         : 0

Manifest: operations/CHG-2026-00123/health/before/transcript-import-manifest.yaml
=================================
```

manifestの完全例は[Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md)を参照する。

### 7.5 比較と自動発見

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/health/report

alred overlay-check discover \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --output operations/CHG-2026-00123/overlay
```

## 8. S5: 宣言済みChangeSetをalred内で投入

### 8.1 過去の正常状態による準備用plan（任意）

作業前準備で機器へアクセスしない場合、過去operationの正常な最終状態から非投入planを生成する。

```bash
alred overlay-change prepare-plan \
  --change-set desired-changes.yaml \
  --reference-state latest-known-good \
  --reference-max-age-days 30 \
  --operations-root operations
```

出力は`preparation/attempts/<attempt-id>/`配下へ分離し、approve / applyには使用できない。
失敗attemptは保持して同じchange IDで再実行でき、成功attemptは`preparation/current.json`から
参照する。VLAN、VNI、VRF、SVI IP / prefixの競合を過去状態に対して検査するが、投入前のfresh
beforeと通常planを省略しない。

### 8.2 before確認

```bash
alred health-check before \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --collect \
  --output operations/CHG-2026-00123
```

### 8.3 forward / rollback plan生成

```bash
alred overlay-change plan \
  --hosts hosts.yaml \
  --change-set desired-changes.yaml \
  --operations-root operations
```

`--before`省略時はChangeSetの`metadata.change_id`に対応するoperationから、
`health/before/current.json`と一致する最新成功beforeを使用する。別operationのSnapshotは検索しない。

planでは対象機器、生成設定、VLAN / VNI / VRF / SVI IP競合、実行コマンド、正常性確認項目、
切り戻し方式とコマンドをfresh beforeに対して確定する。機器へ設定投入しない。

代表出力:

```text
=== OVERLAY CHANGE PLAN ===
Change ID       : CHG-2026-00123
Before source   : inferred from ChangeSet change_id
Before attempt  : before-20260802T091500-p1234-a1b2c3
Before snapshot : operations/CHG-2026-00123/health/before/snapshot.json
Before result   : PASS
Capability      : APPLY_VERIFIED
Devices         : 2
Execution plan  : operations/CHG-2026-00123/plan/execution-plan.json
Rollback plan   : operations/CHG-2026-00123/plan/rollback-plan.json
```

plan、rollback plan、resolved ChangeSet、inventory、before Snapshot、生成configの内容を確認後、
対話的に承認recordを生成する。

```bash
alred overlay-change approve \
  --change-id CHG-2026-00123
```

`--plan`と`--rollback-plan`は省略時に同じoperationの標準pathへ解決される。別operationや
準備用planは自動選択しない。

```text
Approve this plan for interactive apply? [yes/no]: yes
Approval  : operations/CHG-2026-00123/approval/approval-record.json
Expires   : 2026-08-02T12:00:00+09:00
```

承認recordは既定24時間有効で、対象artifactのhashが変わった場合は期限内でも無効になる。
非対話承認と`--yes`による迂回は初期実装では許可しない。

### 8.4 設定投入

```bash
alred overlay-change apply \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --change-set desired-changes.yaml \
  --approved-plan operations/CHG-2026-00123/plan/execution-plan.json \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --approval-record operations/CHG-2026-00123/approval/approval-record.json \
  --health-check \
  --wait-until-healthy 300 \
  --save-on-success \
  --output operations/CHG-2026-00123
```

`apply --health-check`は、事前に`health-check before --collect`で取得したbeforeを検証し、設定投入後の収集、after Snapshot、収束待ち、before / after比較を共通Health Check Frameworkへ委譲する。before / afterの機器収集には既存collect処理を使用する。設定保存は正常性確認成功後だけ行う。

現行の段階実行CLIでは、apply、after収集・判定、Overlay判定、saveを個別に再実行可能な
コマンドへ分離する。Approval Recordで`save_on_success: true`を承認した場合の実行順は次とする。

```bash
alred overlay-change apply \
  --change-id CHG-2026-00123 \
  --operations-root operations

alred health-check after \
  --change-id CHG-2026-00123 \
  --operations-root operations

alred overlay-check evaluate \
  --change-id CHG-2026-00123 \
  --operations-root operations

alred overlay-change save \
  --change-id CHG-2026-00123 \
  --operations-root operations
```

`overlay-change save`はApproval Recordのsave許可、after gate、plan hash、固定inventory、
live running-configを再検証する。追加の承認入力は要求せず、承認済みpolicyを変更する
optionも提供しない。

after gate は共通 Health Result の `PASS`／`WARN` と Overlay Result の `VERIFIED`／`OBSERVED_HEALTHY` を
成功条件とする。共通 Health の `FAIL`／`UNKNOWN`／`NOT_APPLICABLE`／`PLAN_ERROR` または Overlay の非成功結果は
save を拒否する。`WARN` は Checklist のレビュー対象として維持し、save 成功によって解消済みとは扱わない。

保存済み変更を後から切り戻してstartup-configも復元する場合は、rollback後検証に成功してから
次を実行する。

```bash
alred overlay-change save-rollback \
  --change-id CHG-2026-00123 \
  --operations-root operations
```

このコマンドはrollback Snapshotとlive running-configの全台一致をsave前に確認し、
`rollback/save-execution.json`とdevice別saveログを出力する。

正常終了時の代表出力:

```text
=== OVERLAY CHANGE APPLY ===
Change ID : CHG-2026-00123
Plan      : operations/CHG-2026-00123/plan/execution-plan.json
Targets   : leaf01, leaf02

[1/6] Validate approved plan
  PASS  plan hash, ChangeSet hash, inventory hash

[2/6] Verify before health
  PASS  operations/CHG-2026-00123/health/before/snapshot.json
  Raw   operations/CHG-2026-00123/health/before/raw/

[3/6] Apply generated configuration
  PASS  leaf01  commands=18
        config: operations/CHG-2026-00123/generated-config/leaf01.cfg
        log=operations/CHG-2026-00123/apply/devices/leaf01/commands.log
  PASS  leaf02  commands=18
        config: operations/CHG-2026-00123/generated-config/leaf02.cfg
        log=operations/CHG-2026-00123/apply/devices/leaf02/commands.log

[4/6] Collect after state
  PASS  leaf01
  PASS  leaf02
  Raw   operations/CHG-2026-00123/health/after/attempts/attempt-001/raw/

[5/6] Wait for convergence
  Attempt 1/20  WARN  NVE VNI 10010 is Down on leaf02
  Attempt 2/20  PASS  all required checks healthy
  Converged in 27 seconds
  Final raw: operations/CHG-2026-00123/health/after/attempts/attempt-002/raw/

[6/6] Save configuration
  PASS  leaf01  copy running-config startup-config
        log=operations/CHG-2026-00123/apply/devices/leaf01/save.log
  PASS  leaf02  copy running-config startup-config
        log=operations/CHG-2026-00123/apply/devices/leaf02/save.log

Result    : APPLIED_AND_VERIFIED
Applied   : 2/2 devices
Saved     : 2/2 devices
Warnings  : 0
Failures  : 0

Apply report  : operations/CHG-2026-00123/apply/apply-summary.md
Apply result  : operations/CHG-2026-00123/apply/execution.json
Health report : operations/CHG-2026-00123/health/report/summary.md
Overlay report: operations/CHG-2026-00123/overlay/overlay-summary.md
============================
```

この例の`Attempt 1/20`は一時的な未収束であり、最終結果のWARNを意味しない。timeout、設定投入失敗、正常性確認FAIL、設定保存失敗は区別して`apply/execution.json`へ記録する。`--save-on-success`指定時も、after正常性確認が成功する前に設定保存しない。

beforeとafterの`collection-manifest.yaml`には、実際に判定へ使用したrawファイルをコマンド単位で記録する。収束待ちで再収集した場合はattemptごとにrawログを分離し、最終Snapshotが採用したattemptを`health/after/execution.json`へ記録する。

### 8.5 Apply失敗時

初期既定では最初の設定投入失敗で停止し、未着手機器へ投入せず、設定保存も行わない。

```text
[3/6] Apply generated configuration
  PASS         leaf01  commands=18
  FAIL         leaf02  command=7/18
  NOT_STARTED  leaf03

Configuration save: SKIPPED
Emergency raw: operations/CHG-2026-00123/health/after/attempts/failure-001/raw/
Result: APPLY_FAILED
Rollback: REQUIRED_MANUAL_DECISION
```

### 8.6 手動切り戻し

apply前に生成・承認したrollback planを指定する。

```bash
alred overlay-change rollback \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --approved-rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json \
  --health-check \
  --output operations/CHG-2026-00123
```

正常終了時の代表出力:

```text
=== OVERLAY CHANGE ROLLBACK ===
Change ID : CHG-2026-00123
Policy    : manual
Targets   : leaf02, leaf01

  PASS  leaf02
        log=operations/CHG-2026-00123/rollback/devices/leaf02/commands.log
  PASS  leaf01
        log=operations/CHG-2026-00123/rollback/devices/leaf01/commands.log

Rollback health: PASS
Configuration save: SKIPPED
Result: ROLLED_BACK_AND_VERIFIED

Report: operations/CHG-2026-00123/rollback/rollback-summary.md
================================
```

初回9000v qualificationでは、専用rollback後に同じ固定profileと対象scopeで次を実行する。
共通health比較、対象deviceのnormalized raw running-config完全一致、Overlay semantic
config一致がすべて成功した場合だけ`rolled_back_and_verified`となる。

```bash
alred health-check rollback \
  --change-id HC-20260730T122608-p0900-bc53b8
```

beforeが直接収集の場合は、同じchange IDから`--collect`、hosts、target hosts、transportなどを
継承する。別scopeでのrollback確認は同一作業の比較条件を変えるため許可しない。

出力は`health/rollback/`、`health/rollback-report/`、
`qualification/rollback/verification.json`へ保存する。

## 9. S6: Snapshotをオフライン再比較

判定ロジック更新後の再評価やレポート再生成では、機器収集を繰り返さない。

```bash
alred health-check compare \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after/snapshot.json \
  --recheck

alred health-check snapshot \
  --input operations/CHG-2026-00123/health/after/raw \
  --input-format alred-collect \
  --phase after \
  --change-id CHG-2026-00123 \
  --recheck

alred overlay-check evaluate \
  --before operations/CHG-2026-00123/health/before/snapshot.json \
  --after operations/CHG-2026-00123/health/after-recheck/snapshot.json \
  --recheck
```

compareは次を検証する。

- before / afterの`change_id`一致
- profile hash一致
- Snapshot schema互換性
- 対象hostの対応

元の report は暗黙に上書きせず、新しい attempt または別の出力先へ保存する。
`snapshot --recheck` は `health/<phase>-recheck/`、`compare --recheck` は
`health/report-recheck/`、`overlay-check evaluate --recheck` は
`overlay/recheck/` へ固定して保存する。元の raw、Snapshot、report および Overlay 結果は
不変とする。

recheck は parser または判定ロジック修正後の証跡再評価であり、機器状態の再観測ではない。
元の Overlay 結果が `UNKNOWN` で、そのため workflow が `rollback_required` となった場合は、
同一 operation の不変入力を使った Overlay recheck の `VERIFIED` 結果で
`after_completed` へ調停できる。また、旧実装が共通 Health の `WARN` を誤って `rollback_required` にした場合は、
元 Overlay 結果が `VERIFIED`／`OBSERVED_HEALTHY` であることを確認して同じ明示 recheck で調停できる。
元結果が `FAIL` の場合、入力 hash が一致しない場合、または設定投入失敗を recheck で成功へ変更してはならない。

## 10. S7: 定期・随時inspectionと修正後確認

変更作業を前提としない正常性確認と、Topology／Digital Twin／AI解析へ利用できる情報を同じattemptで
収集する。`purpose: inspection`でも保存上のphaseは互換性のため`before`とする。

```bash
alred health-check before \
  --purpose inspection \
  --collect \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --mappings mappings.yaml \
  --description-rules description_rules.yaml
```

LLDP、running config、baseline show commandを同じCollection Manifestへ固定する。inspectionはactive
changeへ登録せず、変更継続用Operation Gateを表示しない。異常を修正した場合は、対象Operationを明示して
follow-upを取得する。

現行実装では、このCollection Manifestと`health/before/raw/`を入力として`normalize-links`を実行し、
confirmed linkからTopologyを生成できる。同じCollection Manifestから`digital-twin` Evidence Packageを作成し、
import後のsanitized configを`clab-transform-config`へ渡すこともできる。Evidence PackageへのCanonical Link
Evidence同梱と隔離環境での再生成一致gateは未実装であり、Package単体からのTopology再生成とは区別する。

```bash
alred health-check after \
  --change-id INS-20260809T100000-p0900-a1b2c3
```

afterはbeforeのinventory、profile、collection条件、mappings、description rules、link health policyを
継承・hash検証し、HealthとCanonical Link Evidenceの差分を生成する。inspectionをManaged Config
Operationへ利用する場合は暗黙に昇格せず、別のchange operationまたは明示的な移行手順を使用する。

## 11. 実行方式の選択目安

| 条件 | 推奨シナリオ |
|---|---|
| alredから機器へ接続できる | S1 |
| 変更管理番号がなく、簡単に開始したい | S2 |
| 既存collectの運用を維持したい | S3 |
| terminal serverや別ツールのログしかない | S4 |
| 設定生成・投入もalredで一貫して行う | S5 |
| 保存済みデータで判定だけ再実行したい | S6 |
| 変更予定なしで正常性・結線・解析材料を収集したい | S7 |

初期導入ではS3またはS4で収集と判定を分離し、parserと判定結果を確認した後にS1またはS5へ広げる方法を推奨する。
