# Existing Push Config As-Is

- Status: Analyzing
- Last reviewed: 2026-07-26
- Scope: `push-config`、`push-config-dir`、`write-memory`

## Evidence

| 種別 | path | 確認内容 |
|---|---|---|
| Code | `alred/cli.py:push_config_to_host` | Netmikoでconfigを1行ずつ送信 |
| Code | `alred/cli.py:save_config_on_host` | 機種種別ごとの保存commandと成功marker |
| Code | `alred/constants.py` | NX-OS保存commandは`copy running-config startup-config` |
| CLI | `push-config` / `push-config-dir` | 対象表示後、`yes`の対話確認 |
| Test | 既存tests | push応答本文のerror patternと部分投入状態の専用testは未確認 |

## Observed behavior

- `push-config`は全対象に同じconfig fileを使用する。
- `push-config-dir`はhostnameに対応するconfig fileを使用する。
- 接続確認後に対象を表示し、入力が完全一致で`yes`の場合だけ投入する。
- `ThreadPoolExecutor`と`--workers`により複数deviceへ並列投入する。
- device内ではconfigを1行ずつ`send_config_set([line])`で送信する。
- 最初の行でconfig modeへ入り、各行ではconfig modeを維持する。
- Netmikoが例外を送出した場合、そのdeviceの残りの行は送信しない。
- config mode終了はbest effortで、失敗しても明示的な失敗結果にはしない。
- debug logには各行の応答を連結して記録する。
- `--write-memory`指定時はpush成功deviceだけを別phaseで保存する。
- NX-OS保存は`copy running-config startup-config`を実行し、応答に`Copy complete.`が
  含まれない場合を失敗とする。

## Confirmed reusable behavior

Overlay applyでも次は再利用する。

- 既存の接続・credential解決
- Netmiko session確立
- device内の1行単位送信
- 1行の送信例外後に同一deviceの残りを停止
- config保存をpushと別phaseにする構造
- NX-OSの保存commandと成功marker

新しい独立したSSH送信実装を追加せず、既存処理を共通executorへ抽出する。

## Gaps for managed Overlay apply

- NX-OSが応答本文へ返すCLI errorがNetmiko例外にならない場合の判定契約
- command別status、開始・終了時刻、応答範囲を持つJSON
- config fileとcommandのSHA-256
- change-id、plan、approvalとの関連付け
- SIGINT、timeout、接続断後の`DEVICE_STATE_UNKNOWN`
- serial 1、未着手device停止、reconcile
- plan前提と投入直前running-configの再確認
- after health check成功後だけ保存するgate
- operation workspaceのpermission、lock、atomic state更新

これらは送信transportの置換理由ではなく、既存transportへmanaged operationの制御と証跡を
追加する理由である。

## Model-specific behavior

初期対象5機種はすべて`device_type: nxos`として同じ送信executorを使用する。
model名による直接分岐は、fixtureまたは公式仕様で差が確認された場合だけ追加する。

機種・release別に変わり得る箇所:

- capability Levelと対応command
- New L3VNI Modeなどのconfig構文可否
- show commandの出力形式とparser
- command timeout、出力量、収束時間
- TCAM、MTU、featureなどのplatform制約
- save command応答markerに実差が確認された場合のadapter

機種別に変えない箇所:

- approval、hash、lock、operation state
- command別result schema
- fail closedとreconcile
- rollback ownership
- secret maskingとpermission

## Unknowns and conflicts

- `send_config_set`が対象NX-OS応答のどのerrorを例外化するかはfixtureで未確認。
- `% Invalid command`、`ERROR:`、warning系出力の分類は未固定。
- 5機種・対象releaseでのprompt、config mode、save応答差は未検証。
- 現行の並列投入既定をOverlay applyへそのまま引き継がず、初期Overlay applyは`serial: 1`とする。

## Recommended design disposition

既存方式を共通executorの基礎として維持する。Phase 0でNX-OS 10.4(5)Mの成功・CLI error・
timeout・save応答fixtureを取得し、error patternとpost-checkを追加する。model別分岐は
Capability Matrixを経由し、executor本体へ散在させない。
