# Design Documents

alredの設計検討資料を格納する。

## 設計書の網羅範囲

本ディレクトリは、現時点のalred全機能と現行実装を網羅していない。現在は共通Health Check、
Overlay Change Management、NX-OS Overlay Config Renderingの目標仕様、Support Bundleを
中心に記載している。

既存のcollect、inventory、topology、containerlab生成、transform、diagram生成、現行VNI生成
などには実装済み機能があるが、そのすべては設計書へまだ反映されていない。設計書に記載が
ないことを、機能が存在しない、未実装、不要、または廃止予定である根拠としてはならない。

未反映の既存機能については、コード、CLI help、[README.md](../../README.md)、
[CONFIG.md](../../CONFIG.md)、テストから現行動作を確認する。既存実装の設計書化は
[Existing Feature Documentation Status](../implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
に従って段階的に進める。

現行実装から観測した内容は、正式仕様として承認する前に
[As-Is Implementation Notes](../as-is/README.md)の規則で記録する。レビュー後に本ディレクトリ
の適切な設計書へ統合する。

## 文書一覧

### [Role Definition and Resolution Design](./ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)

device の topology role と feature role、複数 role 解決、provenance、利用機能別の規則、
`evpn-route-reflector` / `underlay-route-reflector` の意味と移行を定める。

### [NX-OS Overlay Role Health Check Catalog](./NXOS_OVERLAY_ROLE_HEALTH_CHECK_CATALOG.md)

`nxos-overlay` の topology role / function 別 check ID、command、Snapshot field、判定、
before / after 比較、実装状態を定める。

### [Health Check Framework Design](./HEALTH_CHECK_FRAMEWORK_DESIGN.md)

作業種別に依存しない共通正常性確認基盤の設計。

- 既存`collect-*`との連携
- 外部CLI transcriptのホスト・コマンド解析
- collection manifest
- Snapshot
- Health Check Profile
- Change IDと自動採番
- `operations/<change-id>/`による作業成果物の責務分離
- before / after比較
- 共通判定、収束待ち、レポート
- 共通`health-check` CLI

### [Overlay Change Management Design](./OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)

L2VNI / L3VNI追加作業に固有の設計。

- Overlay ChangeSet
- 外部・階層device group、default VLAN、SVI
- 外部・手動投入後の自動発見
- NX-OS EVPN/VXLANの収集・判定
- Overlay設定生成・投入
- `overlay-check` / `overlay-change` CLI

### [NX-OS Overlay Config Rendering Design](./NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)

NX-OS EVPN/VXLANのforward / rollback config生成仕様。

- `generate-vni-config`と`overlay-change plan`の共通renderer
- CSV / ChangeSetからCanonical Render Modelへの変換
- VRF、L3VNI、L2VNI、VLAN、SVI、NVE、EVPNの生成規則
- 差分、冪等性、所有権、delete、rollback
- config hashと成果物

### [NX-OS Baseline Health Check Commands](./NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)

NX-OSで共通正常性確認に使用するコマンドと判定方針。

- core / feature / diagnosticの分類
- コマンドごとの取得情報とbefore / after判定
- 初期MVP
- 閾値案
- 既存`show_commands.txt`との統合

### [Health Check Output Formats](./HEALTH_CHECK_OUTPUT_FORMATS.md)

正常性確認の出力仕様と具体例。

- 端末summary
- `summary.md` / `checklist.md`
- `health-result.json`
- `execution.json` / `snapshot.json`
- `resolved-profiles.yaml`
- `transcript-import-manifest.yaml`
- `discovered-changes.yaml`

### [Health Check Execution Scenarios](./HEALTH_CHECK_EXECUTION_SCENARIOS.md)

正常性確認を作業方式別に実行するCLI例。

- health-checkからの直接収集
- 既存collectとの分離
- 外部CLI transcript
- 外部・手動設定投入
- alred内での設定投入
- Snapshotのオフライン再比較
- 最小設定ファイルと代表出力例

### [Support Bundle Design](./SUPPORT_BUNDLE_DESIGN.md)

正常性確認・設定投入・切り戻し障害を人またはAIへ引き渡す共通support bundle設計。

- change-id / phase / device単位のbundle
- allowlist staging、redaction、pseudonymization
- secret scan、Manifest、SHA-256
- AI向けprompt自動生成
- `support-bundle create` / `inspect` / `verify` CLI

### [Operation State and Approval Design](./OPERATION_STATE_AND_APPROVAL_DESIGN.md)

operation状態遷移、排他制御、中断、承認、成果物保護の共通設計。

### [Schema and Compatibility Policy](./SCHEMA_AND_COMPATIBILITY_POLICY.md)

YAML/JSON schema、未知field、default、version、canonical hashの共通規則。

### [Error Catalog](./ERROR_CATALOG.md)

共通error code、retry可否、CLI終了code、operator action。

### [NX-OS Capability and Fixture Matrix](./NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)

NX-OS 10.4(5)M以降、対象Nexus 9000 model、検証Level、fixture管理。

### [NX-OS Hardware Document Review](./NXOS_HARDWARE_DOCUMENT_REVIEW.md)

実機検証対象外hardwareの公式資料確認手順、判定状態、機種別review recordとgolden configの管理。

### [NX-OS Hardware Document Review](./NXOS_HARDWARE_DOCUMENT_REVIEW.md)

実機検証対象外のNexus hardwareに対するCisco公式資料と機種別golden configの確認手順。

## 文書の責務

```text
Health Check Framework
    ↑ 利用                     ┐
Overlay Change Management     ├→ Support Bundle
                              ┘
```

共通機能の仕様変更はHealth Check Frameworkへ記載する。Overlay文書には共通仕様を再定義せず、
Overlay固有のprofile、parser、evaluator、ChangeSet、workflowだけを記載する。operation状態と
承認はOperation State、schema互換性はSchema Policy、error codeはError Catalog、
NX-OS対応可否はCapability Matrix、成果物の選択、redaction、archive、AI promptは
Support Bundle Designへ記載する。

## ステータス

各文書の設計に対する実装済み・一部実装・未実装の状態は、文書ごとに一律ではない。
現在の状態と検証根拠は[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)を
参照する。CLI、schema、出力例は実装とテストfixtureに同期させる。

設計書へ未反映の既存機能は、未実装、不要、または廃止予定であることを意味しない。

実装順序と完了条件は
[Overlay Change and Health Check Implementation Plan](../implementation/OVERLAY_CHANGE_IMPLEMENTATION_PLAN.md)、
設計と現行実装の差は
[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)
で管理する。Codexを含む開発者の作業規則はリポジトリ直下の
[AGENTS.md](../../AGENTS.md)を参照する。

設計判断の背景、採用理由、影響は[Architecture Decision Records](../adr/README.md)へ記録する。
ADRは判断履歴であり、現在有効な仕様は引き続き本ディレクトリの設計書を正本とする。
