# Existing Feature Documentation Status

## 1. 文書の目的

現行alredに実装済みの機能について、As-Is解析、レビュー、正式設計書への反映状況を管理する。
本書は機能の実装有無を判定する一覧ではなく、「既存実装をどこまで設計書化できたか」を示す。

最終更新日: 2026-08-09

## 2. 状態の定義

| 状態 | 意味 |
|---|---|
| `not_started` | 体系的なAs-Is解析を開始していない |
| `analyzing` | コード、CLI、文書、テスト、生成物を確認中 |
| `as_is_documented` | 観測結果と不明点を`docs/as-is/`へ記録済み |
| `reviewed` | 現行動作を維持する仕様、変更すべき挙動、未決事項をレビュー済み |
| `integrated` | 承認した仕様を`docs/design/`へ統合し、必要なテストと利用者文書を同期済み |
| `deprecated` | 対象機能を廃止し、移行先または理由を記録済み |

## 3. 優先順位

次の順で設計書化する。

1. 今回の新機能が依存または変更する既存機能
2. 機器接続、設定投入、rollbackなど影響が大きい機能
3. 外部公開CLI、入力形式、出力形式
4. 複数機能から再利用される内部component
5. 安定しており、今回の変更と独立している機能

通常はPhase 0および各機能変更の前提作業として段階的に進める。領域横断の設計整理を明示的に行う場合も、
As-Isの証拠、正式設計への統合先、既知の実装差分を機能単位で追跡する。

## 4. 進捗

| 機能領域 | 主な実装・入口 | As-Is解析 | 設計書反映 | テスト確認 | 優先度・備考 |
|---|---|---|---|---|---|
| NTP Health Check | `alred/health/parsers.py`、`ntp_state.py`、`evaluator.py` | `integrated` | [設計 7.10](../design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md#710-ntpと装置時刻)へ統合。profile `1.9`／parser `1.22` で修正 | NTP 回帰、両入力 adapter、前後比較、既存 baseline テスト | 実機未検証。同一 remote の複数 VRF は `UNKNOWN` |
| CLI基盤 | `alred/cli.py`、`alred.py` | `integrated` | [Common設計](../design/common/CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md)へ反映 | command/help fixture、CLI testあり | top-level command、parser、終了code境界を記録 |
| configuration / resources | `alred/constants.py`、`alred/resources.py`、`CONFIG.md` | `reviewed` | Common設計へ反映 | path、sample、resource testあり | cwd探索とpackage dataを記録。全commandの個別defaultは各設計を正本とする |
| inventory / hosts | `alred/inventory.py` | `reviewed` | [Inventory設計](../design/common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)へ反映 | offline inventory／CLI testあり | `hosts.txt`／YAMLとtarget解決を記録 |
| credential / transport | `alred/utils.py`、`alred/collect.py`、`alred/cli.py` | `reviewed` | Inventory設計へ反映 | mock／offline testあり | NX-API TLS defaultとplatform実機範囲は既知の検討事項 |
| collect | `alred/cli.py`、`alred/collect.py` | `integrated` | [Collection設計](../design/common/COLLECTION_DESIGN.md)へ反映 | syntheticおよびC9300v 10.5(4)選択fixtureあり | current mirrorのatomicityとstale sidecarは実装差分として追跡 |
| 現行VNI map | `alred/cli.py`のrunning-config parser／CSV出力 | `reviewed` | [VNI設計](../design/network-ops/VNI_MAP_AND_LEGACY_CSV_DESIGN.md)へ反映 | parser testあり | release別fixture、mapping後衝突、完全schema validationを追跡 |
| legacy VNI config | `alred/cli.py`、`alred/overlay_render.py`、`alred/j2/vni_*.j2` | `integrated` | VNI設計とrenderer設計へ反映 | goldenあり | legacy CSV互換と共通renderer境界を記録 |
| config push / save | `alred/cli.py`、`alred/managed_config.py` | `integrated` | [Direct Config Push設計](../design/network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md)へ反映 | mock fixtureあり | CLI error text非検出などの安全制約を明示 |
| containerlab transform / generation | `alred/transform.py`、`alred/design.py`、`generate-clab` | `integrated` | [Containerlab設計](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)と[Containerlab Manual](../manual/containerlab/README.md)へ反映 | transform、validation、topology testあり | 非NX-OS対応は未承認。startup確認の既知bugを追跡 |
| topology / link normalization | `alred/parsing.py`、`alred/topology.py` | `reviewed` | [Topology設計](../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)と[Topology Manual](../manual/topology/README.md)へ反映 | evidence、normalization testあり | CSV row順の非決定性とschema validation不足を追跡 |
| canonical role解決 | `roles.yaml`、`alred/health/roles.py`、Health／Overlay | `integrated` | [Role設計](../design/common/ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)へ反映 | v1/v2、conflict、provenance testあり | Health／Overlayのcanonical resolverを実装済み |
| legacy role consumer | topology、diagram、containerlab、Terraform | `reviewed` | Role／Topology／Terraform Inventory Generation設計へ反映 | matcher testあり | single-roleからcanonical multi-roleへの移行は未実装 |
| diagram生成 | `alred/render.py`、`generate-network-diagram`、`generate-mermaid`、`generate-graphviz`、`generate-drawio`、`generate-doc` | `reviewed` | [Rendering設計](../design/topology/TOPOLOGY_RENDERING_DESIGN.md)と[Topology Manual](../manual/topology/README.md)へ反映 | format別testあり | format間metadata parityを追跡 |
| Terraform inventory生成 | `alred/inventory.py`、`generate-tf` | `reviewed` | [Terraform Inventory Generation設計](../design/common/TERRAFORM_INVENTORY_GENERATION_DESIGN.md)へ反映 | inventory renderer testあり | 固定credential、role衝突、atomic publishを追跡 |
| logging / feature parser | `alred/logging_check.py`、`alred/parsing.py`、`alred/health/` | `reviewed` | Common、Topology、Health設計へ責務別に反映 | parser fixtureあり | platform別fixture網羅性は継続監査 |
| packaging / build | `pyproject.toml`、`BUILD.md`、`packaging/`、`scripts/` | `reviewed` | [Development設計](../design/development/DEVELOPMENT_TESTING_AND_PACKAGING_DESIGN.md)へ反映 | packaging test、CI native binary smokeあり | wheel install、glibc定期build、署名は未実装 |

`一部参照のみ`は、新規設計から既存機能を利用する前提が記載されているだけで、既存機能
そのもののAs-Is仕様が網羅されていることを意味しない。

## 5. 更新ルール

- 解析開始時に対象行を`analyzing`へ変更し、対象範囲を明記する。
- `as_is_documented`へ進める前に、証拠pathと未確認事項をAs-Is文書へ記録する。
- `reviewed`では、現行挙動を正式仕様として維持するかを人が確認する。
- `integrated`は、設計書、テスト、CLI help、READMEまたはCONFIGが同期した場合だけ使用する。
- 一つの機能領域が大きい場合は行を分割し、領域全体を早期に`integrated`としない。
- 日付は`Asia/Tokyo`の暦日を使用する。
