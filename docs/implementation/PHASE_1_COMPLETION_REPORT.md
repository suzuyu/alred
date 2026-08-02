# Phase 1 Completion Report

## 1. 結論

Phase 1「operation workspaceとschema」は2026-07-29に完了した。
実機接続、設定投入、設定保存は実施していない。Phase 1は共通operation基盤のoffline実装であり、
NX-OS parser、Health Snapshot生成、health判定、Overlay plan/apply/rollback本体は後続Phaseとする。

## 2. 実装した範囲

### 2.1 Operation workspace

- `operations/<change-id>/`の安全な作成と既存operationの非上書き
- 既定`Asia/Tokyo`、`ALRED_TIMEZONE`、CLI指定を想定したIANA timezone解決
- `HC-YYYYMMDDTHHMMSS-<offset>-<random>`形式の自動change-id
- before / afterなどに使用するattempt ID
- rootの`metadata.yaml`と`execution.json`
- directory `0700`、regular file `0600`
- operation root外path、symlink、非regular fileの拒否
- temporary file、`fsync`、同一directory内renameによるatomic write

### 2.2 Schemaと互換性

JSON Schema Draft 2020-12として次の11 Kindをpackage resourceへ追加した。

- `OperationMetadata`
- `OperationExecution`
- `OperationLock`
- `ActiveHealthCheckChange`
- `ApprovalRecord`
- `HealthCheckProfile`
- `CollectionManifest`
- `HealthSnapshot`
- `HealthResult`
- `ExecutionPlan`
- `RollbackPlan`

利用者入力・新規出力の未知fieldは拒否し、JSON Pointer形式のpathを返す。同じmajorの保存済み
出力readerは、安全に解釈できる未知fieldだけを許容する。canonical JSONとSHA-256、
source byte SHA-256を実装した。

wheelとsource distributionをbuildし、11 schemaが両方へ同梱されることを確認した。
既存`alred.spec`は`collect_data_files("alred")`を使用するためPyInstallerも同じpackage resourceを
収集する。今回の作業では配布binary自体のbuild・対象OS上での起動試験は行っておらず、
release受入で確認する。

### 2.3 状態、lock、中断

- operation lifecycle、phase lifecycle、Overlay workflow transition
- mutating operationに必須の排他`.operation.lock`
- lock owner、別host、存在しないPID、破損lockのread-only診断
- stale候補lockを自動削除しない動作
- `SIGINT` / `SIGTERM`前のhandler状態復元
- device command開始前の`cancelled` / `CANCELLED_BEFORE_APPLY`
- device command開始後の`state_unknown` / `device_state_unknown`
- errorと状態遷移履歴のroot `execution.json`保存

### 2.4 Preflightと承認

- permission、path種別、hostname、OS user、device上限50台の確認
- 空き容量は予想量の2倍または1 GiBの大きい方
- filesystem typeの確認とremote / 不明filesystemでのapply相当処理のfail closed
- `ExecutionPlan` / `RollbackPlan`のschema、change-id、device数、canonical hash確認
- `ExecutionPlan.capability_level == APPLY_VERIFIED`の必須化
- TTYでの明示的な`yes`だけを許可するinteractive approval
- 既定24時間、指定可能範囲1から24時間
- manual rollbackだけを許可
- approval recordの非上書きとartifact hash完全一致検証

承認CLIは次である。これは承認recordを作成するだけで、設定投入は行わない。

```bash
alred overlay-change approve \
  --change-id CHG-2026-00123 \
  --plan operations/CHG-2026-00123/plan/execution-plan.json \
  --rollback-plan operations/CHG-2026-00123/plan/rollback-plan.json
```

read-only CLIは次である。

```bash
alred operation status --change-id CHG-2026-00123
alred operation inspect --change-id CHG-2026-00123
```

### 2.5 afterのchange-id解決

`operations/.state/active-change.yaml`だけを正本として参照し、最新directory検索による推測を
行わない。自動採番before、before完了状態、metadata / snapshot path、output root、
inventory hash、profile hash、after状態がすべて一致した場合だけ同じchange-idを返す。

## 3. 検証結果

```text
Phase 1対象 pytest: 45 passed
全offline pytest (-m "not device"): 94 passed
Ruff対象file: All checks passed
wheel / sdist build: success
wheel / sdist内schema: 11 files
```

## 4. 後続Phaseへ引き継ぐ内容

- Phase 2: 既存collect成果物と外部transcriptからCollection Manifest / Snapshotを生成する。
- Phase 3: 共通baseline evaluatorを実装する。
- Phase 5 / 8: 完全なExecution / Rollback Planをrenderer・running-config・ownershipへ接続する。
- Phase 8: apply開始時にapproval hash、期限、capability、current configを再検証する。
- Phase 9: support bundle用schemaと成果物を実装する。
- Phase 10: PyInstaller配布binaryとNexus 9000vの対象OSで受入試験し、hardware 4機種は
  公式資料と機種別golden configで確認する。

`APPLY_VERIFIED`の実機証跡は今回追加していない。Phase 0のC9300v fixtureはparser開発用であり、
対象hardwareを`APPLY_VERIFIED`へ昇格する根拠には使用しない。
