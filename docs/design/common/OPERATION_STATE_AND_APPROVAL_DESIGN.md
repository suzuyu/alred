# Operation State and Approval Design

## 1. 文書の目的

Health CheckとOverlay変更管理のoperation状態、排他制御、中断、承認、成果物保護を定義する。
config内容とrollback生成はOverlayおよびRendering設計書を正本とする。

## 2. 初期制約

- workspaceはlocal filesystemだけを対象とする。
- 同じchange-idのmutating operationは同時に1つだけ許可する。
- 非対話apply、automatic rollback、platform checkpoint rollbackは初期対象外とする。
- applyの途中再開は行わず、実状態のreconcile、再plan、再承認を要求する。
- 最大apply対象は50台とする。

## 3. 状態遷移

Operation metadataの`purpose`は少なくとも`change`、`inspection`、`initial_lab_qualification`を区別する。
`inspection`はbeforeと同じ収集・Snapshot処理を使用するがactive changeへ登録せず、変更継続用gateを
持たない。問題修正後の`after`は明示Operation IDで同じworkspaceへ追加できる。inspection成果物を
approval／applyの入力へ暗黙に昇格しない。

### 3.1 共通Operation lifecycle

Health Checkだけ、offline compare、planだけ、外部投入、Overlay apply、rollback、support bundleの
すべてで次の共通lifecycleを使用する。

```text
CREATED
  └─ RUNNING
       ├─ WAITING_FOR_USER
       ├─ COMPLETED
       ├─ COMPLETED_WITH_WARNINGS
       ├─ FAILED
       ├─ CANCELLED
       └─ STATE_UNKNOWN
```

### 3.2 Phase lifecycle

before、snapshot、compare、plan、approve、apply、after、save、rollback、bundleなど各phaseは
独立して次を持つ。

```text
NOT_STARTED
RUNNING
WAITING_FOR_USER
COMPLETED
COMPLETED_WITH_WARNINGS
FAILED
CANCELLED
UNKNOWN
```

### 3.3 Overlay workflow state

Overlay固有の進行状態は共通lifecycleと分離して記録する。

```text
PLANNED
  └─ BEFORE_RUNNING
       ├─ BEFORE_FAILED
       └─ BEFORE_COMPLETED
            └─ PLAN_READY
                 └─ APPROVED
                      └─ APPLY_RUNNING
                           ├─ APPLY_FAILED
                           ├─ DEVICE_STATE_UNKNOWN
                           └─ APPLY_COMPLETED
                                └─ AFTER_RUNNING
                                     ├─ HEALTH_FAILED
                                     └─ AFTER_COMPLETED
                                          ├─ SAVE_RUNNING
                                          │    ├─ SAVE_FAILED
                                          │    └─ COMPLETED
                                          └─ COMPLETED

APPLY_FAILED / DEVICE_STATE_UNKNOWN / HEALTH_FAILED / SAVE_FAILED
  └─ ROLLBACK_REQUIRED
       └─ ROLLBACK_RUNNING
            ├─ ROLLBACK_FAILED
            └─ ROLLED_BACK
                 ├─ ROLLBACK_HEALTH_FAILED
                 └─ ROLLED_BACK_AND_VERIFIED
                      └─ SAVE_RUNNING
                           ├─ SAVE_FAILED
                           └─ COMPLETED
```

図では視認性のため状態を大文字で示す。JSON/YAMLへ保存するenum値は
`created`、`running`、`waiting_for_user`のような小文字snake_caseへ統一する。

各遷移はtemporary fileへ完全書込み後のatomic renameで`metadata.yaml`と
`execution.json`へ記録する。共通operation state、phase state、workflow stateを別fieldとして
保存し、terminal表示だけを状態の正本にしない。

`metadata.yaml`は`api_version: alred/v1`、`kind: OperationMetadata`の共通envelopeを使用し、
現在状態と最後の遷移を保持する。rootの`execution.json`は
`schema_version: 1`、`kind`相当は`OperationExecution`として扱い、全遷移とerror履歴を保持する。
phase固有の`health/<phase>/execution.json`や`apply/execution.json`とは責務を分離する。

## 4. 排他制御

### 4.1 保存layoutとpath解決

新規 Operation は作成日の timezone を使い、次の dated layout へ保存する。

```text
operations/
├── .index/<change-id>.yaml
├── live/YYYY/MM/DD/<change-id>/
├── live/latest -> YYYY/MM/DD/<change-id>/
└── archive/YYYY/MM/DD/<change-id>.tar.gz
```

`.index/<change-id>.yaml`は `OperationLocation` schema に従い、`storage_version`、`state`、
`layout`、`created_date`、`relative_path`、archive 時は archive 全体の SHA-256 を保持する。
各 command は directory を走査または組み立てず、Operation ID を共通 resolver へ渡して実体 path を
解決する。既存の`operations/<change-id>/`は`legacy-flat`として読取り・更新を継続できるが、
新規作成時は使用しない。日付階層は作成日で固定し、phase 追加や再実行で移動しない。

index は lookup 用であり、Operation 本体の状態の正本は`metadata.yaml`と`execution.json`、archive 内容の
正本は`OperationArchiveManifest`とする。未知の`storage_version`や不正な relative path は推測せず
fail closed する。将来 index 再構築を追加できるよう、archive 内 Manifest にも change ID、元 relative path、
作成・終了・archive 時刻、file 単位 size／mode／SHA-256 を保持する。

`live/latest` は運用者が最新ログへ到達するための相対 symbolic link とし、Health phase の成果物が
正常に公開された後だけ atomic に更新する。実行中・失敗 attempt、作成直後で成果物がない Operation は
指さない。機械処理は `latest` を正本として使用せず、Operation index、phase の `current.json`、Manifest、
artifact hash を検証する。archive により参照先が live から除かれる場合は、残存する最新成功 Operation へ
更新するか、安全に更新できなければ `latest` を除去する。

### 4.2 手動archive

archive は自動実行しない。運用者が次の CLI を手動実行するか、同じ CLI を`cron`などから起動する。

```bash
alred operation archive --dry-run
alred operation archive
alred operation archive --change-id CHG-2026-00123
```

- 既定の経過日数は terminal transition から14日とし、`--older-than-days`、または
  `ALRED_OPERATION_ARCHIVE_AFTER_DAYS`で変更できる。
- 対象 state は`completed`、`completed_with_warnings`、`cancelled`だけとする。`failed`、
  `state_unknown`、実行中、lock 保有中は archive しない。
- archive 開始時に専用 Operation lock を排他的に取得し、archive 作成・検証・index 更新・live directory 削除まで
  別処理による成果物変更を防ぐ。この lock 自体は archive へ含めない。
- `--dry-run`は候補表示だけを行い、file を作成・削除しない。
- regular file だけを列挙し、symlink と special file を拒否する。archive 内部 Manifest の全 file hash と
  archive 全体 hash を検証した後だけ index を`archived`へ更新し、live directory を削除する。
- archive 後の`operation status`と`operation inspect`は展開せず、圧縮 archive 全体の checksum を検証して
  `metadata.yaml`と`execution.json`だけを読み取る。作成時は file 単位 hash も全件検証するが、読み取り専用表示で
  全 log を毎回展開・再 hash しない。
- mutating command、Support Bundle／Evidence Package 作成、reference state 選択など live 成果物を必要とする
  consumer は archive を透過展開せず、`OPERATION_ARCHIVED`で停止する。restore／archive 内の任意成果物を
  直接読む共通 reader は将来拡張とする。
- 一括実行では不適格 Operation を`SKIP`して継続し、`--change-id`指定時は不適格を error にする。
- archive 作成・検証・index 公開までに失敗した場合は live Operation を維持し、今回作成した未公開 archive を
  除去して同じ CLI を再実行可能にする。index 公開後の live directory 削除失敗は archive を破棄せず、
  archived index を正本として fail closed する。

この境界により、archive 形式や保存階層を変更しても consumer の CLI 契約を Operation ID 中心に維持できる。
将来は`storage_version`別 adapter、index rebuild、selective restore を追加し、既存 archive を in-place で
書き換えない。

### 4.3 Lock

lock は解決済み`<operation-root>/.operation.lock`とし、次を保存する。

```json
{
  "schema_version": 1,
  "change_id": "CHG-2026-00123",
  "operation": "apply",
  "pid": 12345,
  "hostname": "operator-host",
  "os_user": "netops",
  "started_at": "2026-07-26T12:00:00+09:00",
  "tool_version": "0.2.0a1"
}
```

- lock作成は排他的createを使用する。
- lockが存在する場合、PIDだけを根拠に自動削除しない。
- hostnameが異なる、PIDが存在しない、時刻が古い場合もstale候補として表示するだけとする。
- stale lock解除は初期実装では自動化せず、原本を保存したうえで運用者がreconcileする。
- `status`、`inspect`、support bundleなどの読み取り専用操作はlockを取得しない。
- plan/apply/rollback/saveなど成果物またはdeviceを変更する操作はlock必須とする。

## 5. 中断と異常終了

- deviceへcommandを送信する前のSIGINTは`CANCELLED_BEFORE_APPLY`として安全終了する。
- 送信開始後のSIGINT、SIGTERM、timeout、接続断は、command結果を確認できないdeviceを
  `DEVICE_STATE_UNKNOWN`とする。
- 送信中commandを強制的にundoしたと仮定しない。
- interrupt handlerは新しいdeviceへの投入を停止し、得られた結果とlock情報を保存する。
- lockや状態保存に失敗した場合も端末messageだけで成功扱いにしない。
- 次回実行ではstatus、緊急収集、reconcile、新plan、新approvalの順を要求する。

## 6. Approval Record

ChangeSetの`metadata.source`は来歴だけを示す。承認は独立した
解決済み`<operation-root>/approval/approval-record.json`へ保存する。

```json
{
  "schema_version": 1,
  "approval_id": "APR-20260801T120000-p0900-a1b2c3",
  "change_id": "CHG-2026-00123",
  "approved_at": "2026-08-01T12:00:00+09:00",
  "expires_at": "2026-08-02T12:00:00+09:00",
  "approval_method": "interactive",
  "approver": {
    "os_user": "netops",
    "hostname": "operator-host"
  },
  "artifacts": {
    "change_set": "sha256:...",
    "device_groups": "sha256:...",
    "resolved_targets": "sha256:...",
    "input_manifest": "sha256:...",
    "resolved_inventory": "sha256:...",
    "before_snapshot": "sha256:...",
    "execution_plan": "sha256:...",
    "rollback_plan": "sha256:...",
    "render_manifest": "sha256:..."
  },
  "constraints": {
    "max_devices": 50,
    "save_on_success": true,
    "rollback_policy": "manual"
  }
}
```

### 6.1 承認規則

- 初期実装のapplyはTTYを持つ対話実行だけを許可する。
- 承認対象の`ExecutionPlan`はCapability Matrixで`APPLY_VERIFIED`と判定済みでなければならない。
- plan summary、対象device、forward/rollback path、resource action、warning、hash、期限を表示する。
- `yes`に相当する明示入力だけを承認とし、Enter、省略、曖昧な値は拒否する。
- 承認有効期限は既定24時間とし、profileは短縮だけ可能とする。
- 初期実装では暗号署名を行わない。OS userとhostnameは監査情報であり、本人性の強い証明ではない。
- CI、pipe、`--yes`、環境変数だけによる非対話applyは初期実装では許可しない。

### 6.2 無効化条件

次のいずれかで承認を無効とする。

- 有効期限超過
- artifact hash不一致
- 外部device group、input manifest、resolved targetのhash不一致
- inventory対象またはdevice数の変化
- before/current configのplan前提不一致
- tool/schema/renderer versionがplanと不整合
- rollback policyまたはsave policyの変更
- capability Levelが`APPLY_VERIFIED`でない

`save_on_success: true`の承認では、作業前から存在する未保存変更を誤ってstartup-configへ
保存しないため、apply直前の同一sessionで`show running-config diff`を取得し、差分なしで
あることを追加条件とする。差分あり、取得失敗、解析不能ではforward configを1行も送信せず
fail closedする。結果は`apply/execution.json`のdevice別`pre_apply_diff`へ保存する。
`save_on_success: false`ではこの追加条件をapply gateにしない。

最初の承認は`approval/approval-record.json`へ保存する。承認recordを上書きせず、再plan後に
再承認する場合は、新しいapproval IDで
`approval/approval-record.<approval-id>.json`へ保存する。

### 6.3 通常apply後のsave

通常saveは設定投入とafter正常性確認から分離した
`overlay-change save --change-id <ID>`として実行する。新しい承認promptは設けず、対話的に
作成済みのApproval Recordに`save_on_success: true`が固定されている場合だけ許可する。
workflowは`after_completed`、共通HealthResultは`PASS`、OverlayHealthResultは
`VERIFIED`または`OBSERVED_HEALTHY`でなければならない。承認期限、plan / rollback plan hash、
Capability、固定inventoryも保存直前に再検証する。

保存前に全対象deviceへread-only接続し、live `show running-config`がafter Snapshotと一致する
ことを確認する。1台でもdrift、接続失敗、取得不能があれば、どのdeviceにもsaveを送信しない。
全台preflight成功後、forward applyと同じdevice順でserial 1、retryなし、
stop-on-first-errorとして次を同一session内で実行する。

1. `show running-config`とafter Snapshotの再一致確認
2. 保存前`show running-config diff`の証跡取得
3. `copy running-config startup-config`と成功marker確認
4. 保存後`show running-config diff`が差分なしであることの確認

集約結果は`apply/save-execution.json`、device別結果は
`apply/devices/<hostname>/save-result.json`と`save.log`へ保存し、
`apply/execution.json`のdevice別`save`と総合結果も更新する。全台成功時は
`APPLIED_AND_VERIFIED` / workflow `completed`、失敗または不明時は`SAVE_FAILED` /
workflow `save_failed`とする。同じsave commandは自動再送しない。

正常save後に承認済みrollbackを実行する場合、`completed`から
`rollback_required`へ遷移できる。rollback後にraw / semantic / health復元がすべて成功した
`rolled_back_and_verified`では、明示的な`overlay-change save-rollback`により
startup-configもbefore状態へ復元できる。この安全復元では承認期限切れだけを拒否理由に
しないが、元Approval Recordのplan / rollback hashと`save_on_success: true`は再検証する。
全台のlive running-configがrollback Snapshotと一致することを先に確認し、通常saveと同じ
serial 1、retryなし、保存後diffなしを要求する。成果物は`rollback/save-execution.json`と
`rollback/devices/<hostname>/save-result.json`、`save.log`へ保存する。

workflow state が保存条件を満たさない場合の `VALIDATION_ERROR` は、必要な state に加えて
現在の workflow state を表示する。`save-rollback` では、利用可能な rollback verification
の `status.result` と `status.health_result` もエラー末尾へ表示し、`WARN`／`FAIL` のどちらが
state 遷移を止めたかを識別できるようにする。

### 6.4 Lab qualification承認

初回Capability確認では通常のApproval Recordを使用せず、
`qualification/qualification-record.json`を作成する。通常の`approve`が
`PLAN_ONLY`を受け付けるようには変更しない。

qualification recordは少なくとも次を固定する。

- `purpose: initial_lab_qualification`
- exact model、release、role、対象hostname（最大2台）
- `hosts.yaml`、before Snapshot、ChangeSet、外部device group、resolved target、Execution Plan、Rollback Plan、
  render manifest、forward/rollback configのpathとSHA-256
- `save_on_initial_apply: false`
- `rollback_policy: manual`
- 期限、OS user、実行host、TTY確認
- 利用者が入力した、対象model/releaseとchange-idを含む確認phrase

`overlay-change qualify`は通常applyと同じmanaged executorと証跡形式を再利用するが、
通常applyのCapability判定を迂回する汎用flagにはしない。Nexus 9000v以外、3台以上、
非TTY、before非PASS、hash不一致、rollback未生成、既存operationの再開ではfail closedとする。
qualification完了後も通常の`overlay-change approve/apply`はMatrix更新までblockedのままとする。

`overlay-change prepare-plan`が生成する
`preparation/attempts/<attempt-id>/execution-plan.json`は
`preparation_only: true`、`capability_level: PLAN_ONLY`とし、Approval Recordの生成対象にしない。
`approve`は標準path `plan/execution-plan.json`以外、fresh beforeの参照がないplan、
`preparation_only: true`のplanを拒否する。prepare-planはworkflow stateを`plan_ready`へ進めず、
`prepare_plan` phaseだけを記録するため、同じoperationで後からbeforeと通常planを実行できる。
失敗、cancel、unknownからの再実行に限り、新しいattempt IDを指定した`running`へのphase遷移を
許可する。過去attemptのdirectoryは不変とし、成功時だけ`preparation/current.json`を更新する。

`health-check before`はOverlay workflow開始前に限り、`completed`または
`completed_with_warnings`から新しいattempt IDを指定した`running`への再遷移を許可する。
inventory、profile、入力方式の固定条件が一致しない場合、およびplan／approval／apply開始後は
状態遷移前に拒否する。ただしplan前に空でない`--revision-reason`で明示したprofile改訂は、
変更理由と差分証跡を新attemptへ固定する場合に限って許可する。revision attempt失敗時は以前の
成功済みcurrentと固定profileを変更しない。

通常`overlay-change plan`はChangeSetの`metadata.change_id`でoperationを決定し、
`health/before/current.json`とoperation metadataの`before.current_attempt`が一致する最新成功
attemptだけを参照する。最新retryが`running`、`failed`、`cancelled`、`unknown`の場合は、以前の
成功済みcurrentを自動採用せずfail closedとする。公開済みSnapshot、attempt Snapshot、pointerの
SHA-256、profile hash、HealthResult、必要なoperation gate decisionを検証してからworkflowを
`plan_ready`へ進める。明示`--before`もこの検査を回避しない。

初期CLIは承認record作成と投入を分離する。

```bash
alred overlay-change qualify-approve \
  --change-id HC-20260730T122608-p0900-bc53b8 \
  --hosts ./hosts.lab.yaml

alred overlay-change qualify \
  --change-id HC-20260730T122608-p0900-bc53b8 \
  --hosts ./hosts.lab.yaml

alred overlay-change qualify-rollback \
  --change-id HC-20260730T122608-p0900-bc53b8 \
  --hosts ./hosts.lab.yaml

alred overlay-change qualify-save-baseline \
  --change-id HC-20260730T122608-p0900-bc53b8 \
  --hosts ./hosts.lab.yaml
```

`qualify-approve`は全artifact hashを表示してrecordを作成するだけで、機器へ接続しない。
`qualify`はrecordの期限、全hash、inventory、before PASS、対象model/release/roleを再検証し、
投入直前に同じSSH sessionで`show running-config`を取得する。承認済みbeforeとの差分が
なければ1行ずつconfigを送信し、結果を
`qualification/apply/devices/<hostname>/commands.log`、
`command-results.json`および`qualification/apply/execution.json`へ保存する。
初回qualificationでは設定保存を実行しない。

`qualify`は最初のconfig commandを送信する直前にworkflowを`apply_running`へ遷移し、
interrupt guardへ送信開始を通知する。送信開始後のSIGINT/SIGTERMは
`device_state_unknown`として保存し、自動再送や自動rollbackを行わない。接続、投入前
running-config確認、またはconfig commandの失敗後は、未着手deviceへ進まず
`rollback_required`とする。

`qualify-rollback`は通常rollback capabilityを有効化する汎用経路ではなく、同じ
Qualification Recordが固定した対象とrollback configだけに使用する。次をすべて満たす場合に
限り実行する。

- workflowが`after_completed`または`rollback_required`
- `health/after/snapshot.json`がqualification apply完了後に作成されている。apply失敗後に
  取得した場合もschema上のphaseは`after`とし、用途を緊急afterとして扱う
- Snapshotに対象全deviceのparsed `show running-config`とsource hashがある
- rollback configが新規VRF/VLANを削除する場合、Snapshotのrunning configに
  operation外のVRF/VLAN参照がない
- rollback直前に同じSSH sessionで取得したrunning configがSnapshotと一致する
- inventory path、全Qualification Record artifact hashが一致する

実行順はforward applyの逆device順、serial 1、retryなし、saveなしとする。Qualification
Recordの期限切れは安全なrollbackを妨げないが、recordのchange-idと全artifact hash検証は
省略しない。結果は
`qualification/rollback/devices/<hostname>/commands.log`、
`command-results.json`、`qualification/rollback/execution.json`へ保存する。
config送信後の中断は`rollback_required`へ戻し、状態確認と新しいafter Snapshotなしに
再実行しない。成功後は`rolled_back`とし、rollback healthおよびbeforeとの差分確認が
完了するまで検証済みとはしない。

rollback health または統合 verification が非 PASS の場合は `rollback_health_failed` とする。
この状態では設定 rollback 自体を再送せず、同じ固定済み before、profile、inventory、対象
scope を使用した `health-check rollback` の新 attempt だけを許可する。再判定が再び非 PASS
なら `rollback_health_failed` を維持する。

Health Check は常に客観的な判定だけを行い、4 つの統合 gate がすべて PASS した場合だけ
`rolled_back_and_verified` へ自動遷移する。HealthResult が `WARN` の場合は、Snapshot freshness、
normalized raw running-config、semantic config が PASS でも `rollback_health_failed` を維持し、
verification 証跡に state WARN の承認適格性を記録する。

利用者が WARN 内容を確認した後に実行する
`overlay-change accept-rollback-state-warn --change-id <change-id>` は、最新公開済み rollback
attempt の WARN check 件数が `counts.warn` と一致し、すべての WARN が `pre_existing`、
`FAIL`／`UNKNOWN` がなく、Snapshot freshness、normalized raw running-config、semantic config
がすべて PASS の場合だけ承認できる。`regression`、`collection_error`、`target_not_ready`、
未分類 WARN、件数不一致は承認しない。対話 TTY と
`ACCEPT ROLLBACK STATE WARN <change-id>` の完全一致を必須とする。

承認は過去 attempt または verification を変更せず、`rollback/state-warn-acceptance.json` に
attempt ID、verification／HealthResult の path と SHA-256、WARN classification 内訳、確認 phrase、
承認時刻を保存してから `rolled_back_and_verified` へ遷移する。qualification workflow では
`qualification/rollback/state-warn-acceptance.json` を使用する。承認後に元 artifact の hash が
変化した場合は acceptance を無効とする。`rolled_back_and_verified` からの Health Check 再実行は
許可しない。

移行前の `health-check rollback --allow-state-warn` により HealthResult `WARN` のまま
`rolled_back_and_verified` へ進んだ operation は、旧 verification の `allow_state_warn: true` と
`warn_allowed: true`、最新 HealthResult、全復元 gate を再検証した場合に限り同じ承認コマンドを
実行できる。この場合は workflow state を変更せず acceptance だけを追加する。acceptance がない
legacy WARN operation に対して `save-rollback` を継続してはならない。

`qualify-save-baseline`はsave capabilityだけを検証する独立した最終gateとする。
一時的なOverlay設定をstartup-configへ残さないため、qualification apply直後ではなく、
rollback後にworkflowが`rolled_back_and_verified`となった場合だけ実行できる。
各対象deviceについて同一SSH session内で次を順に確認する。

1. live `show running-config`がQualification Recordで固定したbefore Snapshotと一致する
2. `show running-config diff`が空、またはNX-OSの既知の「差分なし」応答である
3. `copy running-config startup-config`の応答にdevice type別の成功markerがある
4. 保存後の`show running-config diff`も差分なしである

対象順はforward applyと同じ、serial 1、stop-on-first-error、retryなしとする。
実行にはTTYで`SAVE-QUALIFICATION-BASELINE <change-id>`の完全一致を要求する。
precheck失敗時はsaveを1台にも送信せず`rolled_back_and_verified`を維持する。
1台目以降でsave結果が失敗または不明になった場合は未着手deviceを停止し、
`qualification_save_failed`とする。同じコマンドを自動再送しない。

device別の保存応答と前後diffは
`qualification/save/devices/<hostname>/save-result.json`と`save.log`、
集約結果は`qualification/save/execution.json`へ保存する。全対象が成功した場合は
`qualification_completed`とする。この成功はCapability Matrixの自動昇格を行わず、
apply、after、rollback、復元差分、saveの証跡を手動レビューして対象keyだけを更新する。

成功applyのafter gateは、共通`health-check after`の比較結果が`PASS`で、かつ
`overlay-check evaluate`が`VERIFIED`または`OBSERVED_HEALTHY`の場合だけ
`after_completed`とする。一方でも満たさない、またはOverlay評価自体が失敗した場合は
`health_failed`を経て`rollback_required`とする。apply途中の失敗で既に
`rollback_required`の場合も、同じ`health-check after --collect`を緊急after収集として
使用でき、その収集だけでworkflowを成功状態へ変更しない。

## 7. Rollback初期方針

- 既定policyは`manual`。
- forward planと同時にownershipを証明できるinverse rollback planを生成する。
- automatic rollbackとcheckpoint rollbackは初期実装では`UNSUPPORTED`。
- timeout、接続断、作業外drift、state unknownではautomatic rollbackを行わない。
- rollback後はsemantic diff、normalized raw diff、共通/Overlay health checkを実施する。
- qualification rollback前のSnapshot取得は、apply失敗時も「緊急after」として省略しない。
  ただし接続不能で取得できないdeviceは状態不明のままとし、推測でrollbackを実行しない。

## 8. 成果物保護

- operation root directoryは既定`0700`、regular fileは`0600`で作成する。
- permission設定失敗時は機微情報を保存する処理を開始しない。
- symlink、device file、FIFO、socketをoperation入力・出力として使用しない。
- pathはresolve後に設定済みoutput root配下であることを検証する。
- credential、password、enable secretをmetadata、command log、exceptionへ出力しない。
- operation成果物は自動削除しない。
- 初期実装ではremote filesystem、object storage、共有workspaceを対応対象にしない。
- cleanupを将来追加する場合も、明示対象、dry-run、terminal state、保持policyを必須とする。

## 9. Operation preflight

mutating operationの開始前に次を確認する。

- output rootとoperation rootがlocal filesystem上で書き込み可能
- directory `0700`、regular file `0600`を設定可能
- input/output pathにsymlink、device file、FIFO、socketがない
- temporary fileとatomic rename先が同一filesystem
- lockを排他的に作成可能
- system clock、IANA timezone、hostname、OS userを取得可能
- plan、approval、inventory、before、config、rollbackのhashが一致
- 対象device数が50以下
- Capability Matrixの要求Levelを満たす
- 予想成果物を保存できる空き容量がある

空き容量はPhase 0の実測でhard limitを決めるまでsoft checkとし、予想成果物サイズの2倍か
1 GiBの大きい方を初期目安とする。不足時はapplyを開始せず`PLAN_CONFLICT`として停止する。
network filesystem判定不能またはfilesystem特性を確認できない場合も初期applyを許可しない。

## 10. Credential

既存CLIのcredential解決を再利用する。初期優先順位は現行仕様に従う。

1. CLI optionと`--ask-pass`
2. host固有credential
3. device type固有credential
4. credential fileのdefault
5. environment

CLIの`--password`は互換目的で維持するが、process listとshell historyへの露出warningを表示する。
新規operation成果物、approval、exceptionへcredential値を保存しない。Phase 0のAs-Is解析で
実際の優先順位とprompt動作をtestへ固定する。

## 11. CLI

```bash
alred operation status --change-id CHG-2026-00123
alred operation inspect --change-id CHG-2026-00123

alred overlay-change approve \
  --change-id CHG-2026-00123
```

`approve`は`--change-id`からoperationを一意に決定し、`--plan`省略時は
`<operation-root>/plan/execution-plan.json`、`--rollback-plan`省略時は
`<operation-root>/plan/rollback-plan.json`を使用する。directory内の別名planを検索したり、
最新時刻から推測したりしない。明示optionは非標準pathを監査目的で指定する互換機能として残し、
いずれの場合もoperation root配下、change ID、schema、Capability、workflow、artifact hashを同じように
検証する。

`status`は現在状態、lock、last successful transition、device result count、推奨actionを短く表示する。
`inspect`はartifact hash、attempt、approval、error historyを表示する。どちらもdevice接続や
workspace変更を行わない。`approve`だけが対話確認後にapproval recordを新規作成する。

## 12. Test方針

- 状態遷移の正常・不正遷移
- lock競合、別hostname、PID不存在、破損lock
- SIGINT before apply / during apply
- approval期限、hash差分、inventory差分
- TTYなし、pipe、曖昧な承認入力の拒否
- 51台以上のapply拒否
- permission、symlink、path traversal
- state保存失敗時のfail closed
- reconcileなしのapply再開拒否
