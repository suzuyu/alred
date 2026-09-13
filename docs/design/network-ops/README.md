# Network Operations Design

正常性確認、VNI／Overlay変更、既存config投入、NX-OS対応範囲の設計をまとめる。

## Health Check

| 文書 | 責務 |
|---|---|
| [Health Check Framework Design](HEALTH_CHECK_FRAMEWORK_DESIGN.md) | snapshot、profile、before/after、parser/evaluator共通基盤 |
| [NX-OS Baseline Health Check Commands](NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md) | baseline取得commandと判定 |
| [NX-OS Overlay Role Health Check Catalog](NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md) | role/function別Overlay check |
| [Health Check Output Formats](HEALTH_CHECK_OUTPUT_FORMATS.md) | JSON、Markdown、checklist、terminal summary |
| [Device Summary Design](DEVICE_SUMMARY_DESIGN.md) | Health Check と同時生成する機器一覧、取得元、Markdown／CSV |
| [IPv4 / IPv6 Route Diff 設計案](ROUTE_DIFF_DESIGN.md) | 入力・Snapshot・比較・policy 判定・オフライン renderer API を実装。個別 command `route-diff-nxos` も実装。Health 統合も実装済み。5 比較方式、入出力・HTML モック、CLI・オフライン先行の [実装計画](../../implementation/ROUTE_DIFF_IMPLEMENTATION_PLAN.md) |
| [Route Diff 全体収集ログの修正設計](ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md) | レビュー待ち・未実装。収集管理行、HMM、VXLAN 属性、正常空、互換性と受入条件 |
| [Health Check Execution Scenarios](HEALTH_CHECK_EXECUTION_SCENARIOS.md) | direct、collect、transcript、offline比較のCLI例 |

## VNI、Overlay、設定投入

| 文書 | 責務 |
|---|---|
| [VNI Map and Legacy CSV Design](VNI_MAP_AND_LEGACY_CSV_DESIGN.md) | VNI map parser、CSV、legacy adapter |
| [NX-OS Overlay Config Rendering Design](NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md) | canonical render model、forward／rollback config |
| [Overlay Change Management Design](OVERLAY_CHANGE_MANAGEMENT_DESIGN.md) | ChangeSet、plan、apply、save、rollback、convergence |
| [Direct Config Push and Save Design](DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md) | `push-config*`、`write-memory`の既存互換となる直接投入仕様 |

## 対応範囲

| 文書 | 責務 |
|---|---|
| [NX-OS Capability and Fixture Matrix](NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md) | model／release／role／capabilityと検証level |
| [NX-OS Hardware Document Review](NXOS_HARDWARE_DOCUMENT_REVIEW.md) | 実機対象外hardwareの資料・golden review |

inventory、credential、operation、schema、error、support bundleは[Common Design](../common/README.md)を
正本とする。実装状態は[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md)を参照する。
