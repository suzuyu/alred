# Existing Feature Documentation Status

## 1. 文書の目的

現行alredに実装済みの機能について、As-Is解析、レビュー、正式設計書への反映状況を管理する。
本書は機能の実装有無を判定する一覧ではなく、「既存実装をどこまで設計書化できたか」を示す。

最終更新日: 2026-08-08

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

設計書化だけを目的とする一括変更は行わず、Phase 0および各機能変更の前提作業として
段階的に進める。

## 4. 進捗

| 機能領域 | 主な実装・入口 | As-Is解析 | 設計書反映 | テスト確認 | 優先度・備考 |
|---|---|---|---|---|---|
| CLI基盤 | `alred/cli.py`、`alred.py` | `as_is_documented` | 未反映 | Phase 0 fixtureあり | 高。top-level commandと終了codeを固定 |
| collect | `alred/cli.py`、`alred/collect.py` | `as_is_documented` | 一部参照のみ | syntheticおよびC9300v 10.5(4)選択fixtureあり | 高。manifest/Snapshot連携は未実装 |
| inventory / hosts | `alred/inventory.py` | `not_started` | 未反映 | 要監査 | 高。対象device解決が依存 |
| 現行VNI map/config | `alred/templates.py`、`alred/j2/vni_*.j2` | `as_is_documented` | 一部 | 現行goldenあり | 最優先。VNI map側は引き続き要監査 |
| config push / save | `alred/cli.py`、`alred/constants.py` | `as_is_documented` | 未反映 | mock fixtureあり | 高。既存transportをOverlay applyで再利用 |
| transform | `alred/transform.py`、transform用Jinja2 | `not_started` | 未反映 | あり | 中 |
| topology / link normalization | `alred/topology.py`、`alred/design.py` | `not_started` | 未反映 | 一部あり | 中 |
| role 検出・解決 | `roles.yaml`、`alred/topology.py`、`alred/cli.py` | `reviewed` | 正式設計へ反映。canonical resolver は未実装 | matcher・role 別収集の既存 test あり。新設計 test は未実装 | 高。legacy RR の意味を分離して移行 |
| diagram生成 | `alred/render.py` | `not_started` | 未反映 | 一部あり | 低 |
| configuration / resources | `alred/constants.py`、`alred/resources.py`、`CONFIG.md` | `not_started` | 未反映 | 要監査 | 中 |
| logging / parsing共通処理 | `alred/logging_check.py`、`alred/parsing.py` | `not_started` | 未反映 | 要監査 | 中 |
| packaging / build | `BUILD.md`、`packaging/`、`scripts/` | `not_started` | 未反映 | 要監査 | 低 |

`一部参照のみ`は、新規設計から既存機能を利用する前提が記載されているだけで、既存機能
そのもののAs-Is仕様が網羅されていることを意味しない。

## 5. 更新ルール

- 解析開始時に対象行を`analyzing`へ変更し、対象範囲を明記する。
- `as_is_documented`へ進める前に、証拠pathと未確認事項をAs-Is文書へ記録する。
- `reviewed`では、現行挙動を正式仕様として維持するかを人が確認する。
- `integrated`は、設計書、テスト、CLI help、READMEまたはCONFIGが同期した場合だけ使用する。
- 一つの機能領域が大きい場合は行を分割し、領域全体を早期に`integrated`としない。
- 日付は`Asia/Tokyo`の暦日を使用する。
