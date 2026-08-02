# Error Catalog

## 1. 文書の目的

Health Check、Overlay変更管理、support bundleに共通するerror code、retry可否、CLI終了code、
設定投入との関係を定義する。

## 2. 原則

- 人間向けmessageとmachine-readable codeを分離する。
- deviceが正常であることと、判定不能であることを区別する。
- retry可能性をerror名から推測せずmetadataで示す。
- secret、password、token、完全な認証文字列をmessageへ含めない。
- 複数deviceの結果は個別に保存し、最後のerrorだけで上書きしない。
- option不足など利用者が修正可能なCLI validation errorは終了code `2`とし、通常実行では
  Python Tracebackを表示しない。予期しない内部例外まで包括的に捕捉して隠さない。

## 3. CLI終了code

| Exit | 意味 |
|---:|---|
| `0` | 要求した処理が成功し、blockingな異常なし |
| `1` | WARNまたは利用者判断が必要。処理結果は生成済み |
| `2` | validation、plan、approval、capability error。設定投入開始前 |
| `3` | collection、parser、schema世代不整合により判定不能 |
| `4` | health check FAILまたはregression |
| `5` | apply、save、rollbackの実行失敗またはdevice状態不明 |
| `6` | support bundleのsecret、integrity、生成失敗 |
| `130` | SIGINT。処理状態はexecution resultで確認 |

複数errorがある場合は、単純な最大値ではなく、設定投入後の実行失敗、安全性、判定不能、
health failure、warningの順にoperationの代表終了codeを選ぶ。

## 4. 共通Catalog

| Code | Exit | Retry | Apply状態 | 初期対応 |
|---|---:|---|---|---|
| `VALIDATION_ERROR` | 2 | no | 未開始 | 入力を修正 |
| `SCHEMA_UNSUPPORTED` | 3 | no | 未開始 | 対応versionを使用 |
| `INPUT_NOT_FOUND` | 2 | no | 未開始 | path/manifestを修正 |
| `REFERENCE_STATE_NOT_FOUND` | 2 | no | 未開始 | 対象operation、phase、正常性、対象deviceを確認 |
| `REFERENCE_STATE_NOT_ELIGIBLE` | 2 | conditional | 未開始 | workflowまたはhealth／compare成果物を確認 |
| `REFERENCE_STATE_STALE` | 2 | no | 未開始 | より新しい正常状態を取得 |
| `PLAN_CONFLICT` | 2 | no | 未開始 | beforeまたはChangeSetを確認 |
| `PLAN_STALE` | 2 | no | 未開始 | 再収集・再plan・再承認 |
| `APPROVAL_REQUIRED` | 2 | no | 未開始 | 対話承認 |
| `APPROVAL_INVALID` | 2 | no | 未開始 | hash/期限を確認し再承認 |
| `OPERATION_LOCKED` | 2 | later | 不変 | 実行中operationを確認 |
| `UNSUPPORTED_PLATFORM` | 2 | no | 未開始 | Capability Matrixを確認 |
| `COLLECTION_FAILED` | 3 | conditional | 不変 | device別原因を確認 |
| `COMMAND_UNSUPPORTED` | 3 | no | 不変 | release profile/fixture追加 |
| `PARSER_UNSUPPORTED` | 3 | no | 不変 | raw保存後parser追加 |
| `HEALTH_CHECK_FAILED` | 4 | conditional | 投入前/後 | check結果を確認 |
| `CONVERGENCE_TIMEOUT` | 4 | conditional | 投入済み可 | 最終attemptを保存 |
| `APPLY_FAILED` | 5 | no | 部分投入可 | 自動再開せずreconcile |
| `DEVICE_STATE_UNKNOWN` | 5 | no | 不明 | 再接続し実状態を収集 |
| `SAVE_FAILED` | 5 | conditional | running変更済み | startupとの差を確認 |
| `ROLLBACK_REQUIRED` | 5 | no | 投入済み | 承認済みrunbookを実行 |
| `ROLLBACK_FAILED` | 5 | no | 不明/差分あり | 緊急収集と手動対応 |
| `PERFORMANCE_BUDGET_EXCEEDED` | 1 | yes | 原則不変 | timeout/対象を見直す |
| `BUNDLE_BLOCKED_SECRET` | 6 | no | 不変 | redaction policyを修正 |
| `BUNDLE_INTEGRITY_FAILED` | 6 | no | 不変 | bundleを使用しない |

Support Bundle固有の`BUNDLE_CREATE_FAILED`、`BUNDLE_INCOMPLETE`、
`BUNDLE_INVALID_SOURCE`、`BUNDLE_TOO_LARGE`も終了code `6`へ割り当てる。

## 4.1 名称の分類

設計書で使用する大文字識別子を次に分ける。

| 種別 | 例 | 用途 |
|---|---|---|
| Error code | `PLAN_STALE`、`APPLY_FAILED` | machine-readableな失敗原因 |
| Check ID | `SUSTAINED_HIGH_CPU`、`RELOAD_PENDING_CONFIG_EXISTS` | evaluatorの判定項目 |
| Operation state | `CANCELLED_BEFORE_APPLY`、`ROLLBACK_HEALTH_FAILED` | lifecycle上の状態 |
| Result classification | `PASS`、`WARN`、`FAIL`、`UNKNOWN` | 正常性確認結果 |
| Legacy umbrella | `PLAN_ERROR`、`UNSUPPORTED` | 旧表示との互換。新規JSONでは具体codeを併記 |

`REQUIRED_MANUAL_DECISION`は独立errorにせず、原因となったerror codeと
`operator_action`で表現する。旧`PLAN_ERROR`は終了code `2`へ対応させる。

## 5. Result形式

```json
{
  "code": "PLAN_STALE",
  "severity": "ERROR",
  "retryable": false,
  "phase": "apply-precheck",
  "change_id": "CHG-2026-00123",
  "device": "leaf01",
  "resource": "vrf:TENANT-A",
  "message": "Current configuration does not match the approved plan.",
  "evidence": [
    "plan/execution-plan.json",
    "health/apply-precheck/collection-manifest.yaml"
  ],
  "operator_action": "Collect current state and create a new plan."
}
```

messageは表示用であり、自動処理は`code`、`phase`、`retryable`、構造化fieldを使用する。
