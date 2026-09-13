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
| A-02 | 入力schema未知field | fail closedで拒否 | `designed` | [Schema Policy](../design/common/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-03 | 出力reader未知field | 同じmajor schema内では保持または無視可能 | `designed` | [Schema Policy](../design/common/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-04 | Schema version | 初期`alred/v1`、破壊的変更でmajor更新 | `designed` | [Schema Policy](../design/common/SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| A-05 | Error taxonomy | 共通code、終了code、retry可否を中央定義 | `designed` | [Error Catalog](../design/common/ERROR_CATALOG.md) |
| A-06 | CLI分割 | 新規CLIを別moduleへ分離し、既存CLIは一括変更しない | `accepted` | 実装計画 |
| A-07 | Fixture管理 | release、platform、取得元、匿名化、期待結果を記録 | `designed` | [Capability Matrix](../design/network-ops/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md) |
| A-08 | 不明状態 | 推測で補完せず`UNKNOWN`または`UNSUPPORTED` | `designed` | Health Check Framework、Error Catalog |
| A-09 | Operation status | 読み取り専用statusを提供 | `designed` | [Operation State Design](../design/common/OPERATION_STATE_AND_APPROVAL_DESIGN.md) |
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

## 5. Route Diff の初回リリース判断（2026-09-13）

既存 Health / Overlay の決定とは別に、追加機能の設計・証跡を管理する。

| ID | 項目 | 決定・残件 | 状態 | 正本 |
|---|---|---|---|---|
| RD-01 | リリース分離 | CLI・オフライン出力・Health 統合を先行。Web UI の実装・詳細設計はリリース後 | `designed` | [Route Diff 12](../design/network-ops/ROUTE_DIFF_DESIGN.md#12-初回リリース範囲と共通処理の契約) |
| RD-02 | 対応範囲 | README の対象機種、10.4(5)M 以降、10.5(4) / 10.6(4)M を重点対象 | `designed` | [Route Diff 13](../design/network-ops/ROUTE_DIFF_DESIGN.md#13-対応対象と-fixture-の受け入れ) |
| RD-03 | 入力証跡 | 詳細 route の release 付き fixture が不足。合成例で実機対応を認定しない | `needs_input` | [実装計画 P0](ROUTE_DIFF_IMPLEMENTATION_PLAN.md) |
| RD-04 | 共通 schema | Policy / Source Map / RouteSnapshot / RouteDiff / RouteDiffReview の package schema・domain validator を実装。Health 内の参照配置は P1 の残件 | `accepted` | [比較 API 契約](../design/network-ops/ROUTE_DIFF_DESIGN.md#15-snapshot比較policy-判定の実装契約p3) |
| RD-05 | 性能・配布 | 実装版で 1 万 / 10 万 / 100 万 route を測定。数値 budget と正式上限は測定後に確定 | `accepted` | [実装計画 P7](ROUTE_DIFF_IMPLEMENTATION_PLAN.md) |
| RD-06 | 統合収集ログ | 既存 nxos-transcript で構造を検証し、管理行・対象外 command・失敗範囲を分離する | `implemented` | [修正設計 3](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#3-入力と-section-adapter) |
| RD-07 | VXLAN の比較範囲 | 4 属性を NextHop 2 方式と Policy / rollback の path tuple に含める | `implemented` | [修正設計 4](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#4-hmm-と-vxlan-の解析正規化) |
| RD-08 | marker のない正常空 | heading・既知凡例・command 終端・成功証跡を満たす場合だけ 0 件にする | `implemented` | [修正設計 5](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#5-正常空の認定) |
| RD-09 | ログ全文比較の表示範囲 | 対象 route command 区間を既定とし、入力ログ全体へ切り替える。元行番号・UNKNOWN・判定を保持 | `implemented` | [修正設計 6.1](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#61-ログ全文比較の表示範囲) |
| RD-10 | directory 入力 | 既存 before / after に directory を指定し、prompt の host で対応。片側欠落は UNKNOWN、重複は拒否 | `implemented` | [修正設計 3.5](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md#35-複数機器ログの-directory-入力) |
