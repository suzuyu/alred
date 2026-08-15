# Device Access and Collection Instructions

## Scope

inventory、credentials、SSH/NX-API、`collect-*`、`push-config*`、`write-memory`、既存接続処理を
変更または実行するときに適用する。

## Rules

- 読み取り収集と機器状態を変更する操作を区別する。機器変更は対象host、目的、許可範囲を確認する。
- 通常の自動テストから機器へ接続しない。接続テストには`device` markerを付ける。
- password、enable secret、tokenをsource、log、operation artifact、test fixtureへ保存しない。
- inventoryとpolicyは使用したpathとhashを記録し、follow-up phaseでは固定済みcontextを検証する。
- 収集は既存collector、設定投入と保存は既存managed executorを再利用し、接続処理を重複実装しない。
- timeout、切断、途中成功を正常完了とみなさず、host単位の結果と最後に確認できたcommandを保存する。
- raw logをfixture化するときはsecret、管理IP、実在hostnameなどをsanitizationし、元ログをcommitしない。
- 実機・lab検証を実行した場合は対象、時刻、read-only／mutation、結果、未確認範囲を報告する。

## Sources

- [Collect Output As-Is](../../docs/as-is/COLLECT_OUTPUT_AS_IS.md)
- [Push Config As-Is](../../docs/as-is/PUSH_CONFIG_AS_IS.md)
- [Health Check Framework](../../docs/design/network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
