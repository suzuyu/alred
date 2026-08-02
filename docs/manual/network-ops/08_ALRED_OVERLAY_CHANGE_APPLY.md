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

| 項目 | leaf01 / leaf02 | leaf03 / leaf04 |
|---|---:|---:|
| logical group | server-leafs | storage-leafs |
| vPC group | vpc-leaf-pair-01 | vpc-leaf-pair-02 |
| VRF | TENANT-A | TENANT-A |
| L3VNI | 50001 | 50001 |
| L2VNI | 10020 | 10020 |
| VLAN | 20 | 120 |
| Gateway IPv4 | 198.51.100.1/24 | 198.51.100.1/24 |
| Gateway IPv6 | 2001:db8:20::1/64 | 2001:db8:20::1/64 |
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
Manifest  : operations/CHG-2026-00123/health/before/collection-manifest.yaml
Snapshot  : operations/CHG-2026-00123/health/before/snapshot.json
Checklist : operations/CHG-2026-00123/health/before/checklist.md
Overlay   : operations/CHG-2026-00123/health/before/overlay-state.yaml
VNI Map   : operations/CHG-2026-00123/health/before/vni-map.md
VNI CSV   : operations/CHG-2026-00123/health/before/vni-map.csv
```

beforeが`FAIL`または`UNKNOWN`の場合はplanへ進まず、収集不足または既存異常を解消します。
`WARN`の場合は警告内容を確認し、operation gateが必要ならbefore実行時に`continue`を記録した場合だけ
planへ進めます。

beforeがplanの条件を満たしたら、レビュー済みChangeSetとgroupファイルを同じoperation directoryへ
保存します。

```bash
cp ./changes/CHG-2026-00123/desired-changes.yaml \
  operations/CHG-2026-00123/desired-changes.yaml
cp ./changes/CHG-2026-00123/device-groups.fabric.yaml \
  operations/CHG-2026-00123/device-groups.fabric.yaml
```

## 6. planを生成

```bash
alred overlay-change plan \
  --change-set operations/CHG-2026-00123/desired-changes.yaml \
  --hosts ./hosts.lab.yaml
```

ChangeSetの`metadata.change_id`から同じoperationの最新成功beforeが自動選択されます。監査上pathを
明示したい場合だけ`--before operations/CHG-2026-00123/health/before/snapshot.json`を追加します。
明示指定でも最新性、hash、HealthResult、operation gateの検査は省略されません。

planは機器へ接続せず、設定を投入しません。出力例:

```text
=== OVERLAY CHANGE PLAN ===
Change ID       : CHG-2026-00123
Before source   : inferred from ChangeSet change_id
Before attempt  : before-20260802T091500-p1234-a1b2c3
Before snapshot : operations/CHG-2026-00123/health/before/snapshot.json
Before result   : PASS
Capability      : APPLY_VERIFIED
Devices         : 4
- leaf01: PLANNED config=operations/CHG-2026-00123/generated-config/leaf01.cfg
- leaf02: PLANNED config=operations/CHG-2026-00123/generated-config/leaf02.cfg
- leaf03: PLANNED config=operations/CHG-2026-00123/generated-config/leaf03.cfg
- leaf04: PLANNED config=operations/CHG-2026-00123/generated-config/leaf04.cfg
Execution plan  : operations/CHG-2026-00123/plan/execution-plan.json
Rollback plan   : operations/CHG-2026-00123/plan/rollback-plan.json
Render manifest : operations/CHG-2026-00123/plan/render-manifest.json
Input manifest  : operations/CHG-2026-00123/plan/input-manifest.json
Resolved targets: operations/CHG-2026-00123/plan/resolved-targets.yaml
Conflict report : operations/CHG-2026-00123/plan/conflict-report.json
Capability proof : operations/CHG-2026-00123/plan/capability-evaluation.json
Apply            : ELIGIBLE FOR APPROVAL
```

生成される主なファイル:

```text
operations/CHG-2026-00123/
├── desired-changes.yaml
├── device-groups.fabric.yaml
├── inputs/
│   ├── change-set.yaml
│   └── device-groups.yaml
├── generated-config/
│   ├── leaf01.cfg
│   ├── leaf02.cfg
│   ├── leaf03.cfg
│   └── leaf04.cfg
├── rollback-config/
│   ├── leaf01.cfg
│   ├── leaf02.cfg
│   ├── leaf03.cfg
│   └── leaf04.cfg
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

- [leaf01.cfg](./examples/overlay-changeset/leaf01.cfg)
- [leaf01-rollback.cfg](./examples/overlay-changeset/leaf01-rollback.cfg)
- [leaf03.cfg](./examples/overlay-changeset/leaf03.cfg)
- [leaf03-rollback.cfg](./examples/overlay-changeset/leaf03-rollback.cfg)

`leaf02`は`leaf01`と、`leaf04`は`leaf03`とhostコメント以外は同じconfigになります。

通常planはprepare-planの結果を信用して省略せず、fresh beforeに対してVLAN、VNI、VRF、SVI IP /
prefixなどの競合検査を再実行します。

## 7. planをレビュー

少なくとも次を確認します。

1. 対象deviceが`leaf01`、`leaf02`、`leaf03`、`leaf04`だけである。
2. `plan/conflict-report.md`が`PASS`で、VLAN、VNI、VRF、IPの競合がない。
3. `NO_CHANGE`、`PLANNED`の判定が意図どおりである。
4. forward configのVNI、VRF、VLAN、Gateway、MTU、BGP ASが正しい。
5. `server-leafs`が`leaf01/leaf02`、`storage-leafs`が`leaf03/leaf04`へ展開されている。
6. `leaf01/leaf02`がVLAN 20、`leaf03/leaf04`がVLAN 120へ解決されている。
7. vPCペア内でVLAN、VNI、VRF、SVI、BGP設定が一致している。
8. 既存設定と競合するresourceがない。
9. rollback configがoperation所有resourceだけを削除・復元する。
10. 新規VRFではBGP VRF設定と`vrf context`の削除順が安全である。
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

`--change-id`だけの場合、`operations/CHG-2026-00123/plan/execution-plan.json`と
`operations/CHG-2026-00123/plan/rollback-plan.json`を使用します。`--save-on-success`の既定値は
有効、`--rollback-policy`の既定値は`manual`です。
標準path以外を明示的に承認する必要がある場合だけ`--plan`と`--rollback-plan`を指定します。

対話出力例:

```text
=== OVERLAY CHANGE APPROVAL ===
Change ID: CHG-2026-00123
Artifacts:
  - change_set: operations/CHG-2026-00123/inputs/change-set.yaml
    sha256:0000000000000000...
  - device_groups: operations/CHG-2026-00123/inputs/device-groups.yaml
    sha256:0000000000000000...
  - execution_plan: operations/CHG-2026-00123/plan/execution-plan.json
    sha256:1111111111111111...
  - input_manifest: operations/CHG-2026-00123/plan/input-manifest.json
    sha256:1111111111111111...
  - resolved_targets: operations/CHG-2026-00123/plan/resolved-targets.yaml
    sha256:2222222222222222...
  - rollback_plan: operations/CHG-2026-00123/plan/rollback-plan.json
    sha256:2222222222222222...
Constraints:
  - max_devices: 50
  - rollback_policy: manual
  - save_on_success: true
Type 'yes' to approve: yes
Approval: operations/CHG-2026-00123/approval/approval-record.json
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
Devices   : leaf01, leaf02, leaf03, leaf04
Serial    : 1
Save      : after health only
Type the exact apply phrase:
APPLY CHG-2026-00123
> APPLY CHG-2026-00123
Execution : operations/CHG-2026-00123/apply/execution.json
- leaf01: SUCCESS
- leaf02: SUCCESS
- leaf03: SUCCESS
- leaf04: SUCCESS
Result    : APPLIED_PENDING_HEALTH
```

投入したconfigと機器応答はdeviceごとに保存されます。

```text
operations/CHG-2026-00123/apply/
├── apply.log
├── execution.json
└── devices/
    ├── leaf01/
    │   ├── command-results.json
    │   └── commands.log
    ├── leaf02/
    │   ├── command-results.json
    │   └── commands.log
    ├── leaf03/
    │   ├── command-results.json
    │   └── commands.log
    └── leaf04/
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
Manifest  : operations/CHG-2026-00123/health/after/collection-manifest.yaml
Snapshot  : operations/CHG-2026-00123/health/after/snapshot.json
Checklist : operations/CHG-2026-00123/health/after/checklist.md
Overlay   : operations/CHG-2026-00123/health/after/overlay-state.yaml
VNI Map   : operations/CHG-2026-00123/health/after/vni-map.md
VNI CSV   : operations/CHG-2026-00123/health/after/vni-map.csv
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
Before        : operations/CHG-2026-00123/health/before/snapshot.json
After         : operations/CHG-2026-00123/health/after/snapshot.json
ChangeSet     : operations/CHG-2026-00123/inputs/change-set.yaml
JSON          : operations/CHG-2026-00123/overlay/health-result.json
Summary       : operations/CHG-2026-00123/overlay/overlay-summary.md
```

共通healthまたはOverlay評価がFAIL、UNKNOWNの場合、workflowはrollback判断が必要な状態となり、
saveを実行できません。

## 11. configurationを保存

Approval Recordが`save_on_success: true`で、afterとOverlay評価が成功した場合だけ実行します。

```bash
alred overlay-change save \
  --change-id CHG-2026-00123 \
  --ask-pass
```

出力例:

```text
=== APPROVED OVERLAY SAVE ===
Change ID : CHG-2026-00123
Devices   : leaf01, leaf02, leaf03, leaf04
Snapshot  : operations/CHG-2026-00123/health/after/snapshot.json
Approval  : save_on_success=true
Serial    : 1
Retry     : disabled
Execution : operations/CHG-2026-00123/apply/save-execution.json
- leaf01: SUCCESS
  log=operations/CHG-2026-00123/apply/devices/leaf01/save.log
- leaf02: SUCCESS
  log=operations/CHG-2026-00123/apply/devices/leaf02/save.log
- leaf03: SUCCESS
  log=operations/CHG-2026-00123/apply/devices/leaf03/save.log
- leaf04: SUCCESS
  log=operations/CHG-2026-00123/apply/devices/leaf04/save.log
Result    : APPLIED_AND_VERIFIED
```

save前にlive running-configとafter Snapshotを再検証します。save応答はapplyのcommand logと混在
させず、device別`save.log`と`save-result.json`へ保存します。

## 12. apply失敗時

最初の設定投入errorで停止します。

```text
Execution : operations/CHG-2026-00123/apply/execution.json
- leaf01: SUCCESS
- leaf02: SUCCESS
- leaf03: FAILED
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
Snapshot  : operations/CHG-2026-00123/health/after/snapshot.json
Serial    : 1 (reverse order)
Save      : disabled
Type the exact rollback phrase:
ROLLBACK CHG-2026-00123
> ROLLBACK CHG-2026-00123
Execution : operations/CHG-2026-00123/rollback/execution.json
- leaf04: SUCCESS
- leaf03: SUCCESS
- leaf02: SUCCESS
- leaf01: SUCCESS
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
Evidence  : operations/CHG-2026-00123/rollback/verification-attempts/rollback-.../verification.json
Checklist : operations/CHG-2026-00123/rollback/verification-attempts/rollback-.../verification-checklist.md
```

beforeとrollback後のnormalized raw running-config、およびCanonical Overlay resourceが一致した
場合だけ`ROLLED_BACK_AND_VERIFIED`です。Checklistには統合gate、機器別raw / semantic比較、
Health Checkの非PASS理由、証跡pathを表示します。raw config不一致時は秘密情報を含む設定行を
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
operations/CHG-2026-00123/
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
