# alredによるVNI設定投入

この章では、宣言済み`OverlayChangeSet`からalredがNX-OS設定とrollback設定を生成し、
承認済みplanを機器へ投入するシナリオを説明します。

手動または別システムで設定を投入する場合は
[NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)を使用してください。本章では、
設定投入、device応答ログ、after検証、設定保存、手動rollbackまでを同じoperationで管理します。

## 1. workflow

```text
共通事前準備
    ↓
change ID決定
    ↓
ChangeSet作成・事前レビュー
    ↓
prepare-plan（任意、過去の正常状態、機器アクセスなし）
    ↓
before収集・正常性確認
    ↓
forward / rollback plan生成
    ↓
config・対象・hashのレビュー
    ↓
対話承認
    ↓
apply（saveしない）
    ↓
after収集・共通health比較
    ↓
Overlay評価
    ↓
save
```

apply、after、Overlay評価、saveは独立したstageです。途中で失敗した場合に、成功済みstageを
推測で繰り返さないためです。

## 2. 前提条件

[Common Preparation](./00_COMMON_PREPARATION.md)を完了したうえで、次を確認します。

- beforeで`network-baseline-nxos`と`nxos-overlay`を使用する
- 対象model、NX-OS release、roleのCapabilityが`APPLY_VERIFIED`
- inventoryとbefore Snapshotの対象hostが一致する
- 対話TTYでplan承認とapply確認を実施できる
- rollback policyは初期実装の`manual`
- `interface nve1`に`global ingress-replication protocol bgp`が設定済み
- ChangeSetで参照するIPv4/IPv6 route-mapが機器に存在する
- apply前にforward configとrollback configの両方をレビューする
- setting saveはafterとOverlay評価が成功するまで実行しない

Capabilityが`PLAN_ONLY`の場合、config生成とレビューはできますが、apply承認へ進めません。

## 3. シナリオと入力例

本章を開始する前に[Overlay ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md)に従い、
`./changes/CHG-2026-00123/desired-changes.yaml`を作成・レビュー済みとします。

この例では、2組（4台）のvPC Leafペアへ次を追加します。vPCペア内の2台には同一設定を
生成し、ペア間で異なるVLANはdevice groupのoverrideで表現します。

| 項目 | adc-lfsw0101 / adc-lfsw0102 | adc-lfsw0103 / adc-lfsw0104 |
|---|---:|---:|
| logical group | adc-vpc-pair-01 | adc-vpc-pair-02 |
| vPC group | adc-vpc-pair-01 | adc-vpc-pair-02 |
| VRF | tenant1-vpc1 | tenant1-vpc1 |
| L3VNI | 19001 | 19001 |
| L2VNI | 10100 | 10100 |
| VLAN | 100 | 10 |
| Gateway IPv4 | 172.16.0.254/24 | 172.16.0.254/24 |
| Gateway IPv6 | fd21:0:0:1::1/64 | fd21:0:0:1::1/64 |
| MTU | 9216 | 9216 |

使用するChangeSet（定義方法は[Overlay ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md)を参照）:

- [desired-changes.yaml](./examples/overlay-changeset/desired-changes.yaml)
- [device-groups.fabric.yaml](./examples/overlay-changeset/device-groups.fabric.yaml)

外部ファイルを使わず一ファイルで表現する場合は
[desired-changes.inline.yaml](./examples/overlay-changeset/desired-changes.inline.yaml)を使用できます。

`metadata.source`は利用者が内容を確認し、期待状態として宣言した入力のため`declared`です。
`metadata.change_id`はbeforeで使用するchange IDと一致させます。

## 4. 機器アクセスなしで準備用planを生成（任意）

過去の正常な最終状態を使い、作業前にconfigと競合候補を確認できます。

```bash
alred overlay-change prepare-plan \
  --change-set ./changes/CHG-2026-00123/desired-changes.yaml \
  --reference-state latest-known-good
```

この段階では機器へ接続しません。結果は`preparation/attempts/<attempt-id>/`へ保存され、
approve / applyには使用できません。最新の成功attemptは`preparation/current.json`で確認します。
`--allow-reference-state-warn` は、正常完了した Overlay terminal Operation の `WARN` を参照元として
明示的に許可する必要がある場合だけ追加します。既定は `PASS` 限定です。
standalone Health Check の `WARN` は、`--reference-operation-id` で対象を明示した場合だけ同 option で
許可できます。`latest-known-good` から standalone `WARN` を自動選択しません。
参照元を明示する方法、選択条件、競合検査の詳細は
[ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md#11-過去の正常状態で準備用planを作成)を
参照してください。

## 5. beforeを取得

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --logging-days 1 \
  --ask-pass
```

出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : CHG-2026-00123
Phase     : before
Input     : alred-collect
Hosts     : 4
Warnings  : 0
Result    : PASS
Checks    : PASS=44 WARN=0 FAIL=0 UNKNOWN=0 N/A=8
Manifest  : operations/live/2026/08/01/CHG-2026-00123/health/before/collection-manifest.yaml
Snapshot  : operations/live/2026/08/01/CHG-2026-00123/health/before/snapshot.json
Checklist : operations/live/2026/08/01/CHG-2026-00123/health/before/checklist.md
Overlay   : operations/live/2026/08/01/CHG-2026-00123/health/before/overlay-state.yaml
VNI Map   : operations/live/2026/08/01/CHG-2026-00123/health/before/vni-map.md
VNI CSV   : operations/live/2026/08/01/CHG-2026-00123/health/before/vni-map.csv
```

beforeが`FAIL`または`UNKNOWN`の場合はplanへ進まず、収集不足または既存異常を解消します。
`WARN`の場合は警告内容を確認し、operation gateが必要ならbefore実行時に`continue`を記録した場合だけ
planへ進めます。

beforeがplanの条件を満たしたら、レビュー済みChangeSetとgroupファイルを同じoperation directoryへ
保存します。

```bash
cp ./changes/CHG-2026-00123/desired-changes.yaml \
  operations/live/2026/08/01/CHG-2026-00123/desired-changes.yaml
cp ./changes/CHG-2026-00123/device-groups.fabric.yaml \
  operations/live/2026/08/01/CHG-2026-00123/device-groups.fabric.yaml
```

## 6. planを生成

```bash
alred overlay-change plan \
  --change-set operations/live/2026/08/01/CHG-2026-00123/desired-changes.yaml \
  --hosts ./hosts.lab.yaml
```

ChangeSetの`metadata.change_id`から同じoperationの最新成功beforeが自動選択されます。監査上pathを
明示したい場合だけ`--before operations/live/2026/08/01/CHG-2026-00123/health/before/snapshot.json`を追加します。
明示指定でも最新性、hash、HealthResult、operation gateの検査は省略されません。

planは機器へ接続せず、設定を投入しません。出力例:

```text
=== OVERLAY CHANGE PLAN ===
Change ID       : CHG-2026-00123
Before source   : inferred from ChangeSet change_id
Before attempt  : before-20260802T091500-p1234-a1b2c3
Before snapshot : operations/live/2026/08/01/CHG-2026-00123/health/before/snapshot.json
Before result   : PASS
Capability      : APPLY_VERIFIED
Devices         : 4
- adc-lfsw0101: PLANNED config: operations/live/2026/08/01/CHG-2026-00123/generated-config/adc-lfsw0101.cfg
- adc-lfsw0102: PLANNED config: operations/live/2026/08/01/CHG-2026-00123/generated-config/adc-lfsw0102.cfg
- adc-lfsw0103: PLANNED config: operations/live/2026/08/01/CHG-2026-00123/generated-config/adc-lfsw0103.cfg
- adc-lfsw0104: PLANNED config: operations/live/2026/08/01/CHG-2026-00123/generated-config/adc-lfsw0104.cfg
Execution plan  : operations/live/2026/08/01/CHG-2026-00123/plan/execution-plan.json
Rollback plan   : operations/live/2026/08/01/CHG-2026-00123/plan/rollback-plan.json
Render manifest : operations/live/2026/08/01/CHG-2026-00123/plan/render-manifest.json
Input manifest  : operations/live/2026/08/01/CHG-2026-00123/plan/input-manifest.json
Resolved targets: operations/live/2026/08/01/CHG-2026-00123/plan/resolved-targets.yaml
Conflict report : operations/live/2026/08/01/CHG-2026-00123/plan/conflict-report.json
Capability proof : operations/live/2026/08/01/CHG-2026-00123/plan/capability-evaluation.json
Apply            : ELIGIBLE FOR APPROVAL
```

生成される主なファイル:

```text
operations/live/2026/08/01/CHG-2026-00123/
├── desired-changes.yaml
├── device-groups.fabric.yaml
├── inputs/
│   ├── change-set.yaml
│   └── device-groups.yaml
├── generated-config/
│   ├── adc-lfsw0101.cfg
│   ├── adc-lfsw0102.cfg
│   ├── adc-lfsw0103.cfg
│   └── adc-lfsw0104.cfg
├── rollback-config/
│   ├── adc-lfsw0101.cfg
│   ├── adc-lfsw0102.cfg
│   ├── adc-lfsw0103.cfg
│   └── adc-lfsw0104.cfg
└── plan/
    ├── capability-evaluation.json
    ├── conflict-report.json
    ├── conflict-report.md
    ├── execution-plan.json
    ├── input-manifest.json
    ├── inventory.yaml
    ├── render-manifest.json
    ├── resolved-targets.yaml
    └── rollback-plan.json
```

生成config例:

- [adc-lfsw0101.cfg](./examples/overlay-changeset/adc-lfsw0101.cfg)
- [adc-lfsw0101-rollback.cfg](./examples/overlay-changeset/adc-lfsw0101-rollback.cfg)
- [adc-lfsw0103.cfg](./examples/overlay-changeset/adc-lfsw0103.cfg)
- [adc-lfsw0103-rollback.cfg](./examples/overlay-changeset/adc-lfsw0103-rollback.cfg)

`adc-lfsw0102` は `adc-lfsw0101` と、`adc-lfsw0104` は `adc-lfsw0103` と host comment 以外は
同じ config になります。

通常planはprepare-planの結果を信用して省略せず、fresh beforeに対してVLAN、VNI、VRF、SVI IP /
prefixなどの競合検査を再実行します。

## 7. planをレビュー

少なくとも次を確認します。

1. 対象 device が `adc-lfsw0101`、`adc-lfsw0102`、`adc-lfsw0103`、`adc-lfsw0104` だけである。
2. `plan/conflict-report.md`が`PASS`で、VLAN、VNI、VRF、IPの競合がない。
3. `NO_CHANGE`、`PLANNED`の判定が意図どおりである。
4. forward configのVNI、VRF、VLAN、Gateway、MTU、BGP ASが正しい。
5. `adc-vpc-pair-01` と `adc-vpc-pair-02` が各 2 台へ展開されている。
6. pair 1 が VLAN 100、pair 2 が VLAN 10 へ解決されている。
7. vPCペア内でVLAN、VNI、VRF、SVI、BGP設定が一致している。
8. 既存設定と競合するresourceがない。
9. rollback configがoperation所有resourceだけを削除・復元する。
10. 既存 VRF／L3VNI が rollback の削除対象に含まれていない。
11. ChangeSet、group、resolved target、config、rollback configのSHA-256を追跡できる。
12. Capability警告がない。

生成configやplanを編集すると承認対象hashが変わります。修正が必要な場合は既存planを承認せず、
ChangeSetを修正して新しいoperationでplanを再生成します。

## 8. planを承認

この例ではafter成功後のsaveも承認します。

```bash
alred overlay-change approve \
  --change-id CHG-2026-00123
```

`--change-id`だけの場合、`operations/live/2026/08/01/CHG-2026-00123/plan/execution-plan.json`と
`operations/live/2026/08/01/CHG-2026-00123/plan/rollback-plan.json`を使用します。`--save-on-success`の既定値は
有効、`--rollback-policy`の既定値は`manual`です。
標準path以外を明示的に承認する必要がある場合だけ`--plan`と`--rollback-plan`を指定します。

対話出力例:

```text
=== OVERLAY CHANGE APPROVAL ===
Change ID: CHG-2026-00123
Artifacts:
  - change_set: operations/live/2026/08/01/CHG-2026-00123/inputs/change-set.yaml
    sha256:0000000000000000...
  - device_groups: operations/live/2026/08/01/CHG-2026-00123/inputs/device-groups.yaml
    sha256:0000000000000000...
  - execution_plan: operations/live/2026/08/01/CHG-2026-00123/plan/execution-plan.json
    sha256:1111111111111111...
  - input_manifest: operations/live/2026/08/01/CHG-2026-00123/plan/input-manifest.json
    sha256:1111111111111111...
  - resolved_targets: operations/live/2026/08/01/CHG-2026-00123/plan/resolved-targets.yaml
    sha256:2222222222222222...
  - rollback_plan: operations/live/2026/08/01/CHG-2026-00123/plan/rollback-plan.json
    sha256:2222222222222222...
Constraints:
  - max_devices: 50
  - rollback_policy: manual
  - save_on_success: true
Type 'yes' to approve: yes
Approval: operations/live/2026/08/01/CHG-2026-00123/approval/approval-record.json
```

承認は既定24時間有効です。ただしChangeSet、device group、resolved target、plan、rollback plan、
inventory、configなどの承認対象が変化した場合は、有効期限内でもapplyを拒否します。
pipe、非対話実行、`--yes`による承認迂回は
できません。

## 9. applyを実行

```bash
alred overlay-change apply \
  --change-id CHG-2026-00123 \
  --ask-pass
```

apply前にexact phraseを入力します。

```text
=== APPROVED OVERLAY APPLY ===
Change ID : CHG-2026-00123
Devices   : adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104
Serial    : 1
Save      : after health only
Type the exact apply phrase:
APPLY CHG-2026-00123
> APPLY CHG-2026-00123
Execution : operations/live/2026/08/01/CHG-2026-00123/apply/execution.json
- adc-lfsw0101: SUCCESS
- adc-lfsw0102: SUCCESS
- adc-lfsw0103: SUCCESS
- adc-lfsw0104: SUCCESS
Result    : APPLIED_PENDING_HEALTH
```

投入したconfigと機器応答はdeviceごとに保存されます。

```text
operations/live/2026/08/01/CHG-2026-00123/apply/
├── apply.log
├── execution.json
└── devices/
    ├── adc-lfsw0101/
    │   ├── command-results.json
    │   └── commands.log
    ├── adc-lfsw0102/
    │   ├── command-results.json
    │   └── commands.log
    ├── adc-lfsw0103/
    │   ├── command-results.json
    │   └── commands.log
    └── adc-lfsw0104/
        ├── command-results.json
        └── commands.log
```

`commands.log`には送信コマンドとNX-OS応答、`command-results.json`にはcommand単位の成否が
記録されます。applyはserial 1、retryなし、最初のerrorで停止し、この時点ではsaveしません。

## 10. afterとOverlay評価

```bash
alred health-check after \
  --change-id CHG-2026-00123 \
  --ask-pass
```

出力例:

```text
=== HEALTH SNAPSHOT SUMMARY ===
Change ID : CHG-2026-00123
Phase     : after
Input     : alred-collect
Hosts     : 4
Warnings  : 0
Result    : PASS
Checks    : PASS=44 WARN=0 FAIL=0 UNKNOWN=0 N/A=8
Manifest  : operations/live/2026/08/01/CHG-2026-00123/health/after/collection-manifest.yaml
Snapshot  : operations/live/2026/08/01/CHG-2026-00123/health/after/snapshot.json
Checklist : operations/live/2026/08/01/CHG-2026-00123/health/after/checklist.md
Overlay   : operations/live/2026/08/01/CHG-2026-00123/health/after/overlay-state.yaml
VNI Map   : operations/live/2026/08/01/CHG-2026-00123/health/after/vni-map.md
VNI CSV   : operations/live/2026/08/01/CHG-2026-00123/health/after/vni-map.csv
```

共通healthがPASSした後、宣言済みChangeSetと観測結果を評価します。

```bash
alred overlay-check evaluate \
  --change-id CHG-2026-00123
```

`--change-id`だけを指定すると、同じoperationの
`health/before/snapshot.json`、`health/after/snapshot.json`、
`inputs/change-set.yaml`を使用します。この処理は保存済みファイルを読むオフライン評価であり、
機器へ接続しません。外部または再評価用の成果物を使う場合だけ`--before`、`--after`、
`--change-set`を明示します。

出力例:

```text
=== OVERLAY HEALTH SUMMARY ===
Change ID     : CHG-2026-00123
Result        : VERIFIED
Configuration : PASS
Operational   : PASS
Impact        : PASS
Before        : operations/live/2026/08/01/CHG-2026-00123/health/before/snapshot.json
After         : operations/live/2026/08/01/CHG-2026-00123/health/after/snapshot.json
ChangeSet     : operations/live/2026/08/01/CHG-2026-00123/inputs/change-set.yaml
JSON          : operations/live/2026/08/01/CHG-2026-00123/overlay/health-result.json
Summary       : operations/live/2026/08/01/CHG-2026-00123/overlay/overlay-summary.md
```

共通 Health が `PASS`／`WARN` で、Overlay 評価が `VERIFIED`／`OBSERVED_HEALTHY` の場合は save へ進めます。
共通 Health の `WARN` は Checklist で内容を確認し、保存後も未解消事象として扱います。共通 Health が
`FAIL`／`UNKNOWN`／`NOT_APPLICABLE`／`PLAN_ERROR`、または Overlay 評価が非成功の場合、workflow は
rollback 判断が必要な状態となり、save を実行できません。

旧 version で共通 Health の `WARN` だけを理由に `rollback_required` となり、Overlay がすでに
`VERIFIED`／`OBSERVED_HEALTHY` の場合は、更新後に次を実行して不変 Snapshot を明示的に再評価します。

```bash
alred overlay-check evaluate \
  --change-id CHG-2026-00123 \
  --recheck
```

成功すると `overlay/recheck/` へ証跡を追加して `after_completed` へ調停します。元の評価成果物は上書きしません。

## 11. configurationを保存

Approval Record が `save_on_success: true` で、上記 after gate と Overlay 評価が成功した場合だけ実行します。

```bash
alred overlay-change save \
  --change-id CHG-2026-00123 \
  --ask-pass
```

出力例:

```text
=== APPROVED OVERLAY SAVE ===
Change ID : CHG-2026-00123
Devices   : adc-lfsw0101, adc-lfsw0102, adc-lfsw0103, adc-lfsw0104
Snapshot  : operations/live/2026/08/01/CHG-2026-00123/health/after/snapshot.json
Approval  : save_on_success=true
Serial    : 1
Retry     : disabled
Execution : operations/live/2026/08/01/CHG-2026-00123/apply/save-execution.json
- adc-lfsw0101: SUCCESS
  log=operations/live/2026/08/01/CHG-2026-00123/apply/devices/adc-lfsw0101/save.log
- adc-lfsw0102: SUCCESS
  log=operations/live/2026/08/01/CHG-2026-00123/apply/devices/adc-lfsw0102/save.log
- adc-lfsw0103: SUCCESS
  log=operations/live/2026/08/01/CHG-2026-00123/apply/devices/adc-lfsw0103/save.log
- adc-lfsw0104: SUCCESS
  log=operations/live/2026/08/01/CHG-2026-00123/apply/devices/adc-lfsw0104/save.log
Result    : APPLIED_AND_VERIFIED
```

save 前に live running-config と after Snapshot を再検証します。save 応答は apply の command log と混在
させず、device 別 `save.log` と `save-result.json` へ保存します。

全機器が plan 時点で `NO_CHANGE` の場合は、承認、成果物、after gate を検証したうえで no-op save として
完了します。機器への接続と保存 command は実行せず、次のように表示します。

```text
Devices   : (none; all plan devices are NO_CHANGE)
Result    : APPLIED_AND_VERIFIED
```

この場合は認証情報を使用しないため、`--ask-pass` は不要です。

## 12. apply失敗時

最初の設定投入errorで停止します。

```text
Execution : operations/live/2026/08/01/CHG-2026-00123/apply/execution.json
- adc-lfsw0101: SUCCESS
- adc-lfsw0102: SUCCESS
- adc-lfsw0103: FAILED
Result    : APPLY_FAILED
```

この場合:

- 未着手deviceへ投入しない
- 自動retryしない
- configurationをsaveしない
- 自動rollbackしない
- `apply/execution.json`とdevice logで成功範囲を確認する
- 現在状態を収集してから承認済みrollbackを判断する

接続断などでdevice状態が不明な場合、同じapplyを推測で再実行しません。

## 13. 手動rollback

apply後の現在状態をafter Snapshotとして保存したうえで実行します。rollbackは承認済みplanの
逆device順、operation所有resourceだけを対象とします。

```bash
alred overlay-change rollback \
  --change-id CHG-2026-00123 \
  --ask-pass
```

対話出力例:

```text
=== APPROVED OVERLAY ROLLBACK ===
Change ID : CHG-2026-00123
Snapshot  : operations/live/2026/08/01/CHG-2026-00123/health/after/snapshot.json
Serial    : 1 (reverse order)
Save      : disabled
Type the exact rollback phrase:
ROLLBACK CHG-2026-00123
> ROLLBACK CHG-2026-00123
Execution : operations/live/2026/08/01/CHG-2026-00123/rollback/execution.json
- adc-lfsw0104: SUCCESS
- adc-lfsw0103: SUCCESS
- adc-lfsw0102: SUCCESS
- adc-lfsw0101: SUCCESS
Result    : ROLLED_BACK_PENDING_HEALTH
Next      : run health-check rollback
```

rollback後の状態を収集します。

```bash
alred health-check rollback \
  --change-id CHG-2026-00123 \
  --ask-pass
```

同じchange IDのbeforeが直接収集なら、`--collect`と`--hosts`を含む収集条件は固定済みexecution
contextから継承されます。inventoryまたはpolicyの内容が変わっている場合は収集前に停止します。

正常終了時はhealth summaryに続いて復元検証が表示されます。

```text
=== ROLLBACK VERIFICATION ===
Result    : ROLLED_BACK_AND_VERIFIED
Raw config: true
Semantic  : true
Evidence  : operations/live/2026/08/01/CHG-2026-00123/rollback/verification-attempts/rollback-.../verification.json
Checklist : operations/live/2026/08/01/CHG-2026-00123/rollback/verification-attempts/rollback-.../verification-checklist.md
```

before と rollback 後の normalized raw running-config、および Canonical Overlay resource の
一致は `ROLLED_BACK_AND_VERIFIED` の必須条件です。Health Check は `PASS`、または後述する
明示許可済みの既存 WARN である必要があります。Checklist には統合 gate、機器別 raw／semantic
比較、Health Check の非 PASS 理由、証跡 path を表示します。raw config 不一致時は秘密情報を含む設定行を
出力せず、追加・削除行数だけを表示します。semantic不一致時は値を出力せず差分pathを表示します。

Healthまたはverificationが非PASSの場合は、同じchange IDで再実行できます。

```bash
alred health-check rollback \
  --change-id CHG-2026-00123 \
  --ask-pass
```

再実行は設定rollbackを再送せず、収集・解析・復元検証だけを新しいattemptとして実行します。
過去attemptは`health/rollback/attempts/`、`health/rollback-report/attempts/`、
`rollback/verification-attempts/`へ保持され、`current.json`と互換正本は判定完了後だけ更新されます。

rollback 前から存在する警告だけが残り、raw／semantic config が before と一致している場合でも、
`health-check rollback` は `ROLLBACK_HEALTH_FAILED` として終了します。Checklist と HealthResult の
classification を確認した後、別の承認コマンドを実行します。

```bash
alred overlay-change accept-rollback-state-warn \
  --change-id CHG-2026-00123
```

画面に WARN check、classification、verification／HealthResult の path と hash が表示されます。
内容を確認し、次の phrase を完全一致で入力します。

```text
ACCEPT ROLLBACK STATE WARN CHG-2026-00123
```

承認対象は、比較 HealthResult が `WARN`、WARN check がすべて `pre_existing`、WARN 件数が
完全に追跡でき、`FAIL`／`UNKNOWN` がない場合だけです。`regression`、`collection_error`、
`target_not_ready`、未分類 WARN は許可しません。Snapshot freshness、raw running-config 一致、
semantic config 一致は引き続き必須です。承認成立時は `ROLLED_BACK_AND_VERIFIED` へ進みますが、
元の HealthResult、verification、attempt は変更しません。承認証跡は
`rollback/state-warn-acceptance.json` へ保存されます。

`save-rollback` の state 条件を満たさない場合は、次のように現在の workflow state、verification
result、HealthResult がエラー末尾に表示されます。

```text
VALIDATION_ERROR: approved rollback save requires rolled_back_and_verified workflow state (current workflow state: rollback_health_failed; verification result: ROLLBACK_HEALTH_FAILED; next action: overlay-change accept-rollback-state-warn; health result: WARN)
```

WARN が既存状態だけで config 復元 gate が成功している場合は
`accept-rollback-state-warn`、それ以外は `health-check rollback` を新しい attempt として再実行します。

変更をすでにstartup-configへ保存した後でrollbackした場合は、検証成功後に次を実行します。

```bash
alred overlay-change save-rollback \
  --change-id CHG-2026-00123 \
  --ask-pass
```

applyをsaveする前にrollbackした場合、startup-configは変更前のままなので
`save-rollback`は通常不要です。

## 14. 完了時に保存する成果物

```text
operations/live/2026/08/01/CHG-2026-00123/
├── metadata.yaml
├── execution.json
├── desired-changes.yaml
├── device-groups.fabric.yaml
├── preparation/                 # prepare-planを実行した場合
│   ├── current.json
│   └── attempts/<attempt-id>/
│       ├── result.json
│       ├── reference-state.json
│       ├── conflict-report.json
│       ├── conflict-report.md
│       ├── execution-plan.json
│       ├── generated-config/
│       └── rollback-config/
├── inputs/
│   ├── change-set.yaml
│   └── device-groups.yaml
├── approval/approval-record.json
├── plan/
│   ├── input-manifest.json
│   ├── resolved-targets.yaml
│   ├── conflict-report.json
│   └── conflict-report.md
├── generated-config/
├── rollback-config/
├── apply/
│   ├── execution.json
│   └── devices/<hostname>/
├── health/
│   ├── before/
│   ├── after/
│   └── report/
├── overlay/
│   ├── health-result.json
│   └── overlay-summary.md
└── rollback/
    ├── execution.json
    ├── verification.json
    └── devices/<hostname>/
```

作業記録には、change ID、Approval ID、ChangeSet／device group／resolved target hash、plan hash、
forward / rollback config、device応答ログ、before / after / rollback Snapshot、health結果、save結果を
関連付けて保管します。
