# Pre-Implementation Decision Tracker

## 1. 目的

Health CheckとOverlay変更管理の実装前に必要な設計判断を管理する。詳細仕様は各設計書を正本
とし、本書は論点、決定状態、反映先を追跡するために使用する。

最終更新日: 2026-07-26

## 2. 状態

| 状態 | 意味 |
|---|---|
| `proposed` | 推奨案を提示済みだが未合意 |
| `needs_input` | 利用環境または運用上の追加判断が必要 |
| `accepted` | 方針合意済み |
| `designed` | 正本の設計書へ反映済み |
| `implemented` | 実装とテストが完了 |
| `deferred` | 初期実装の対象外 |

## 3. 決定事項

| ID | 項目 | 決定 | 状態 | 正本・反映先 |
|---|---|---|---|---|
| A-01 | As-Is解析順 | 現行VNI生成、collect、CLI基盤の順 | `accepted` | [既存機能設計書化状況](./EXISTING_FEATURE_DOCUMENTATION_STATUS.md) |
| A-02 | 入力schema未知field | fail closedで拒否 | `designed` | [Schema Policy](../design/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-03 | 出力reader未知field | 同じmajor schema内では保持または無視可能 | `designed` | [Schema Policy](../design/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-04 | Schema version | 初期`alred/v1`、破壊的変更でmajor更新 | `designed` | [Schema Policy](../design/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-05 | Error taxonomy | 共通code、終了code、retry可否を中央定義 | `designed` | [Error Catalog](../design/ERROR_CATALOG.md) |
| A-06 | CLI分割 | 新規CLIを別moduleへ分離し、既存CLIは一括変更しない | `accepted` | 実装計画 |
| A-07 | Fixture管理 | release、platform、取得元、匿名化、期待結果を記録 | `designed` | [Capability Matrix](../design/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md) |
| A-08 | 不明状態 | 推測で補完せず`UNKNOWN`または`UNSUPPORTED` | `designed` | Health Check Framework、Error Catalog |
| A-09 | Operation status | 読み取り専用statusを提供 | `designed` | [Operation State Design](../design/OPERATION_STATE_AND_APPROVAL_DESIGN.md) |
| A-10 | Operation自動削除 | 行わない | `designed` | Operation State Design |
| A-11 | Symlink | operation workspaceの入出力では拒否 | `designed` | Operation State Design |
| A-12 | 新規依存 | 必要性確定まで最小限 | `accepted` | `AGENTS.md`、実装計画 |
| A-13 | CLI終了code | Error Catalogへ統一し、旧`PLAN_ERROR`はlegacy umbrella | `designed` | Error Catalog、Health Check Framework |
| A-14 | ChangeSet採用操作 | `overlay-change-set promote`。operation承認と分離 | `designed` | Overlay Change Management |
| A-15 | Operation状態 | 共通lifecycle、phase、workflow stateを分離 | `designed` | Operation State Design |
| A-16 | 既存config投入 | 1行単位Netmiko executorを再利用し、managed operation証跡を追加 | `designed` | Overlay Change Management、As-Is |
| A-17 | Schema実装 | JSON Schema Draft 2020-12と`jsonschema`、domain validatorを分離 | `designed` | Schema Policy |
| A-18 | Schema配布 | wheel、sdist、PyInstallerへpackage resourceとして同梱 | `designed` | Schema Policy |
| A-19 | Operation preflight | permission、lock、hash、容量、local filesystemをapply前確認 | `designed` | Operation State Design |
| A-20 | NX-OS release | exact release/model keyでapply capabilityを判定 | `designed` | Capability Matrix |
| A-21 | Credential | 既存解決を再利用し、CLI passwordへ露出warning | `designed` | Operation State Design、As-Is |
| A-22 | 開発環境lock | `uv.lock`をGit管理し、再現可能なCIを目標とする | `accepted` | Phase 0 |
| A-23 | 静的検査 | Phase 0でRuff baselineを監査後、既存挙動を変えず段階導入 | `accepted` | Phase 0 |
| B-01 | 承認記録 | ChangeSetとは別の`approval-record.json` | `designed` | Operation State Design |
| B-02 | 承認対象 | ChangeSet、inventory、before、plan、forward、rollbackのhash | `designed` | Operation State Design |
| B-03 | 対話承認 | 内容提示後の明示確認が必須 | `designed` | Operation State Design |
| B-04 | 非対話apply | 初期実装では無効 | `deferred` | Operation State Design |
| B-05 | 暗号署名 | 初期実装では行わずOS userとhashを記録 | `deferred` | Operation State Design |
| B-06 | 承認有効期限 | 既定24時間、profileで短縮可能 | `designed` | Operation State Design |
| B-07 | 排他制御 | change-id単位のfile lock | `designed` | Operation State Design |
| B-08 | stale lock | 自動解除しない | `designed` | Operation State Design |
| B-09 | apply自動再開 | 行わず、reconcileと新planを要求 | `designed` | Operation State Design |
| B-10 | rollback既定 | `manual` | `designed` | Overlay Change Management |
| B-11 | automatic rollback | 初期実装では無効 | `deferred` | Operation State Design |
| B-12 | checkpoint rollback | 初期実装では無効 | `deferred` | Operation State Design |
| B-13 | inverse config | ownershipを証明できる操作だけ生成 | `designed` | Config Rendering Design |
| B-14 | rollback検証 | semantic diff、normalized raw diff、health check | `designed` | Overlay Change Management |
| B-15 | 設定保存 | after正常性確認成功後だけ | `designed` | Overlay Change Management |
| C-01 | NX-OS対応下限 | NX-OS `10.4(5)M` | `designed` | Capability Matrix、ADR-0005 |
| C-02 | 初期対象機種 | Nexus 9000v、9336C-FX2、93180YC-FX3、9348GC-FX3、9364C-H1 | `designed` | Capability Matrix、ADR-0005 |
| C-03 | 最大device数 | 初期soft limit 50台、超過はapply停止 | `designed` | Operation State Design |
| C-04 | 収集時間 | 1台5分を初期soft budget、実測後に更新 | `designed` | Capability Matrix |
| C-05 | 成果物保持 | 自動削除なし | `designed` | Operation State Design |
| C-06 | 出力先 | 初期実装はlocal filesystem | `designed` | Operation State Design |
| C-07 | 検証対象 | 動作検証は9000vのみ。hardware 4機種は公式資料と機種別golden configで確認し、apply検証対象外 | `accepted` | Capability Matrix、ADR-0007 |
| C-08 | Multi-Site | 初期実装対象外 | `deferred` | Capability Matrix |

## 4. 未決事項

初期設計上の必須判断は完了している。次は実装前証跡として以下を収集する。

- Nexus 9000vの`show version`とNX-OS 10.4(5)Mのbaseline・Overlayコマンドfixture
- 9336C-FX2、93180YC-FX3、9348GC-FX3、9364C-H1の公式資料確認と機種別golden config
- 10.4(5)Mより新しいreleaseを追加対応する際の同等fixture
- 既存collect成果物と現行VNI config生成のAs-Is記録
- 既存config push/saveのNX-OS成功、CLI error、timeout、保存応答fixture
- Ruff baseline監査結果と初期rule set

これらがないrelease・modelは「バージョン番号が新しい」という理由だけでapply対応済みと
みなさない。
