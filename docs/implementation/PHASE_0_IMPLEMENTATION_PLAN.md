# Phase 0 Implementation Plan

## 1. 目的

Phase 1以降で既存動作を意図せず変更しないよう、現行CLI、collect成果物、VNI config生成、
config push/saveをAs-Isとして記録し、自動回帰試験で固定する。将来設計への適合を示す
文書ではなく、変更前の比較基準を作るための計画である。

## 2. 完了条件

Phase 0は次をすべて満たした時点で完了とする。

- 既存pytestと文書link検証がCIで再現可能に実行できる。
- top-level CLI command、helpの正常終了、引数errorの終了codeをfixtureで固定している。
- 現行`generate-vni-config`の代表入力とadd/delete出力をgolden fixtureで固定している。
- collectのdirectory、hostname、command境界、current/old mirrorをAs-Is記録とfixtureで固定している。
- config push/saveの1行送信、途中失敗、timeout伝播、保存成功応答をmock試験で固定している。
- 開発基準となるNexus 9000vのsanitized NX-OS fixtureと由来metadataが揃っている。
- Capability Matrixをfixtureと試験証跡に基づいて更新している。
- `uv.lock`をGit管理し、CIとローカルで同じ依存関係を解決できる。
- Ruffの初期rule setをCIで実行できる。
- 未完了項目と、それを解消するために必要な外部入力を完了報告へ記録している。

## 3. Work breakdown

| ID | 作業 | 成果物 | 状態 |
|---|---|---|---|
| 0.1 | test/CI/文書link baseline | `pyproject.toml`、CI、文書test | 完了 |
| 0.2 | 再現可能な開発依存関係 | `uv.lock`、pytest/Ruff設定 | 完了 |
| 0.3 | CLI As-Is固定 | CLI As-Is文書、command fixture、pytest | 完了 |
| 0.4 | 現行VNI renderer固定 | VNI As-Is文書、CSV/config golden、pytest | 完了 |
| 0.5 | collect成果物契約固定 | collect As-Is文書、synthetic fixture、pytest | 完了 |
| 0.6 | config push/save固定 | mock response fixture、pytest | 完了 |
| 0.7 | Nexus 9000v reference fixture | sanitized raw log、metadata | 完了（C9300v 10.5(4)） |
| 0.8 | 対象hardware確認 | 公式資料、機種別golden config | Phase 10の文書確認へ移管 |
| 0.9 | 設計例と将来schemaの差分確認 | VNI As-Isの既知差分一覧 | 完了 |
| 0.10 | Phase 0判定 | completion report、status/matrix更新 | 完了（判定: implemented） |

## 4. Gate

### Local baseline gate

次のコマンドが成功すること。

```bash
uv run pytest -m "not device"
uv run ruff check .
uv run python alred.py --help
```

### Fixture acceptance gate

実機またはlab fixtureは、認証情報、管理IP、serial、実在hostname等をsanitizeし、
[NX-OS Capability and Fixture Matrix](../design/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)のmetadataを
添付する。手作りfixtureは`synthetic`としてparser開発には使用できるが、release/modelの
capability証明には使用しない。

Phase 0の自動開発環境ではNexus 9000vをreference platformとする。device動作検証は9000vだけで
実施する。対象hardwareはPhase 10で公式資料と機種別golden configを確認し、実機適合性確認は
行わない。hardwareは`APPLY_VERIFIED`へ昇格せず、文書根拠なしにmodel固有動作を推測しない。

## 5. Phase 0で変更しないもの

- `health-check`、`overlay-change`等の新規CLIは実装しない。
- 現行Jinja2出力を将来のNX-OS rendering仕様へ変更しない。
- 実機接続、設定投入、保存、rollbackは実行しない。
- As-Isの偶然の挙動を正式な将来仕様として承認しない。

## 6. 関連文書

- [全体実装計画](./OVERLAY_CHANGE_IMPLEMENTATION_PLAN.md)
- [実装状況](./IMPLEMENTATION_STATUS.md)
- [Phase 0 Progress Report](./PHASE_0_COMPLETION_REPORT.md)
- [既存機能の設計書化状況](./EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
- [NX-OS Capability and Fixture Matrix](../design/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)
