# Network Operations Manual

このディレクトリは、alredをネットワーク機器の作業で利用する運用者向けマニュアルです。
仕様の正本は[設計書一覧](../../design/README.md)ですが、通常利用では本マニュアルから
参照してください。

## Quick Start

| 文書 | 対象 | 内容 |
|---|---|---|
| [01 Health Check Quick Start](./01_QUICK_START.md) | 情報収集と正常性確認を始める人 | before、after、最初に確認する出力 |
| [11 Overlay Configuration Quick Start](./11_OVERLAY_CONFIGURATION_QUICK_START.md) | Managed Overlay Operation を始める人 | ChangeSet、plan、approval、apply、verification、save／rollback |
| [12 Direct Config Push Quick Start](./12_DIRECT_CONFIG_PUSH_QUICK_START.md) | 既存 config を直接投入する人 | before、`push-config-dir`、after、明示的な save |

## 詳細ガイド

| 文書 | 対象 | 内容 |
|---|---|---|
| [00 Common Preparation](./00_COMMON_PREPARATION.md) | すべての利用者 | 実行環境、timezone、認証、inventory、入力方式、保存先 |
| [02 Health Check Operations](./02_HEALTH_CHECK_OPERATIONS.md) | 作業実施者 | 直接収集、既存ログ解析、時間範囲、rollback確認 |
| [03 Profile Guide](./03_PROFILE_GUIDE.md) | 判定条件を管理する人 | 組み込みprofile、独自profile、logging範囲 |
| [04 Output Guide](./04_OUTPUT_GUIDE.md) | 結果をレビューする人 | 端末、Checklist、JSON、判定と終了code |
| [05 Troubleshooting](./05_TROUBLESHOOTING.md) | 異常を切り分ける人 | UNKNOWN、入力不足、profile不一致、再解析 |
| [06 NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md) | EVPN/VXLAN作業者 | nxos-overlay、VNI map、作業前後の確認 |
| [07 Overlay ChangeSet Guide](./07_OVERLAY_CHANGESET_GUIDE.md) | VNI変更内容を定義する人 | ChangeSet、device group、L2VNI、L3VNI、SVI、BGP、prepare-plan |
| [08 alred Overlay Change Apply](./08_ALRED_OVERLAY_CHANGE_APPLY.md) | VNI設定投入作業者 | 任意の事前plan、before、通常plan、承認、apply、after、save、rollback |
| [09 VNI Map Guide](./09_VNI_MAP_GUIDE.md) | VNI 一覧を作成・確認する人 | Health Check／running config からの VNI 一覧、legacy CSV |
| [10 push-config-dir Guide](./10_PUSH_CONFIG_DIR.md) | host 別 config を直接投入する人 | NX-OS 接続保護 filter、投入前表示、`--force`、投入後確認 |

## 最短の利用経路

1. [Common Preparation](./00_COMMON_PREPARATION.md)でinventory、認証、保存先を準備する。
2. [Quick Start](./01_QUICK_START.md)で実行シナリオを確認する。
3. ラボまたは取得済みログでbeforeを実行する。
4. 端末summaryの保存先を確認する。
5. Checklistを機器ごとに確認する。
6. WARN、FAIL、UNKNOWNがあれば[Output Guide](./04_OUTPUT_GUIDE.md)と
   [Troubleshooting](./05_TROUBLESHOOTING.md)を参照する。
7. 設定変更後に、同じchange IDでafterを実行する。
8. Overlay 作業では [NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)を確認する。
9. alred で Overlay を設定する場合は
   [Overlay Configuration Quick Start](./11_OVERLAY_CONFIGURATION_QUICK_START.md)へ進む。
10. 既存 config を直接投入する場合は
    [Direct Config Push Quick Start](./12_DIRECT_CONFIG_PUSH_QUICK_START.md)へ進む。

## コマンド表記

本文ではインストール済みコマンドを次のように表記します。

```bash
alred health-check before --help
```

リポジトリをcheckoutした開発環境では、次のように読み替えられます。

```bash
uv run python alred.py health-check before --help
```

## 出力例の読み方

本文の端末出力、YAML、JSON、Checklistは、現行実装の形式に合わせてhostnameや事象を匿名化した
説明用の例です。実行時は対象台数、check数、時刻、パス、判定、messageが環境に応じて変わります。
値をそのまま期待するのではなく、項目の意味と確認順を把握するために使用してください。

## 対象範囲

現時点のマニュアルは、共通health check、NX-OS baseline、Overlay正常性確認・設定投入を説明します。
Overlay変更管理の詳細な仕様は[Overlay Change Management Design](../../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)、
設定生成仕様は
[NX-OS Overlay Config Rendering Design](../../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
を参照してください。

## サンプル

再利用可能なprofile例:

- [NX-OS baseline・logging 3日](../../../alred/sample_configs/health-check-profile.network-baseline-logging-3days.example.yaml)
- [nxos-overlay VNI map出力例](./examples/nxos-overlay/README.md)
- [alred内VNI投入のChangeSet・config例](./examples/overlay-changeset/README.md)

サンプルは実行前に対象環境の閾値、対象コマンド、認証方式をレビューしてください。
