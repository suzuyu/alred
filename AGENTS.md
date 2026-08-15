# Repository Instructions for Codex

## Scope

このファイルはリポジトリ全体に適用する。

alredの設計、実装、テスト、文書更新を行う前に本書を確認すること。サブディレクトリに
より具体的な`AGENTS.md`が追加された場合は、そのディレクトリ配下では両方に従う。

## Japanese writing style

- 日本語と英数字の境界には、原則として半角スペースを入れる。
- command、option、file path、code、識別子は原表記を維持し、必要に応じて backtick で囲む。
- 句読点、括弧、記号の直前・直後には、意味のない半角スペースを追加しない。
- 新規作成する文章と、作業で変更する文章およびその周辺へ適用する。
- 表記統一だけを目的として、依頼と無関係な既存 file を一括変更しない。

## Instruction routing

全作業で本書を適用し、変更内容に応じて次の領域別instructionを作業前に最後まで読む。
複数領域にまたがる場合は該当するものをすべて読む。

| 対象 | 追加instruction |
|---|---|
| inventory、`prepare-hosts`、`generate-tf`、認証、SSH/NX-API、`collect-*`、`push-config*`、`write-memory` | [.agents/instructions/device-access-and-collection.md](.agents/instructions/device-access-and-collection.md) |
| operation、Health Check、Overlay、VNI、apply、rollback、support bundle | [.agents/instructions/network-ops.md](.agents/instructions/network-ops.md) |
| containerlab、lab config変換、lab起動確認 | [.agents/instructions/containerlab.md](.agents/instructions/containerlab.md) |
| LLDP、link正規化、Mermaid、Graphviz、draw.io | [.agents/instructions/topology.md](.agents/instructions/topology.md) |
| 設計書、manual、sample、ADR、実装状況 | [.agents/instructions/documentation.md](.agents/instructions/documentation.md) |

`collect-clab`はdevice accessとcontainerlab、`clab-set-cmds`はdevice access、containerlab、
topologyを読む。VNI処理も変更する場合はnetwork-opsも読む。`generate-doc`はcontainerlabと
topologyを読む。

リポジトリ固有Skill:

- [prepare-pull-request](.agents/skills/prepare-pull-request/SKILL.md): branch、commit、push、Draft PRの準備または作成
- [release-alred](.agents/skills/release-alred/SKILL.md): glibc 2.17 binaryを既定とするDraft GitHub Releaseの準備または作成

ユーザーがこれらの作業を依頼した場合は、該当Skillを使用する。Skillを読んだだけでは
外部変更の承認を意味しない。

## Sources of truth

仕様の正本は[docs/design/README.md](docs/design/README.md)から参照できる設計書とする。
全体構成、データflow、主要operation lifecycleは
[ARCHITECTURE_OVERVIEW.md](docs/design/ARCHITECTURE_OVERVIEW.md)を入口とする。
実装計画は
[docs/implementation/OVERLAY_CHANGE_IMPLEMENTATION_PLAN.md](docs/implementation/OVERLAY_CHANGE_IMPLEMENTATION_PLAN.md)、
実装状況は
[docs/implementation/IMPLEMENTATION_STATUS.md](docs/implementation/IMPLEMENTATION_STATUS.md)
を正本とする。
重要な設計判断の理由と影響は
[docs/adr/README.md](docs/adr/README.md)から参照できるADRへ記録する。ADRは現在の仕様を
再定義せず、設計書を参照する。
既存機能の設計書化状況は
[docs/implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md](docs/implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)、
現行実装の暫定的な解析記録は[docs/as-is/README.md](docs/as-is/README.md)に従う。

主な責務は次のとおり。

- CLI、設定、path、package resource:
  [CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md](docs/design/common/CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md)
- inventory、credential、機器access:
  [INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md](docs/design/common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)
- 既存収集artifact:
  [COLLECTION_DESIGN.md](docs/design/common/COLLECTION_DESIGN.md)
- 共通正常性確認:
  [HEALTH_CHECK_FRAMEWORK_DESIGN.md](docs/design/network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
- NX-OS共通取得コマンド:
  [NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md](docs/design/network-ops/NXOS_BASELINE_HEALTH_CHECK_COMMANDS.md)
- 正常性確認の出力:
  [HEALTH_CHECK_OUTPUT_FORMATS.md](docs/design/network-ops/HEALTH_CHECK_OUTPUT_FORMATS.md)
- 実行シナリオ:
  [HEALTH_CHECK_EXECUTION_SCENARIOS.md](docs/design/network-ops/HEALTH_CHECK_EXECUTION_SCENARIOS.md)
- Overlay変更管理:
  [OVERLAY_CHANGE_MANAGEMENT_DESIGN.md](docs/design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
- NX-OS config生成:
  [NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md](docs/design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
- 障害解析用bundle:
  [SUPPORT_BUNDLE_DESIGN.md](docs/design/common/SUPPORT_BUNDLE_DESIGN.md)
- operation状態、承認、排他制御:
  [OPERATION_STATE_AND_APPROVAL_DESIGN.md](docs/design/common/OPERATION_STATE_AND_APPROVAL_DESIGN.md)
- schema互換性:
  [SCHEMA_AND_COMPATIBILITY_POLICY.md](docs/design/common/SCHEMA_AND_COMPATIBILITY_POLICY.md)
- error code:
  [ERROR_CATALOG.md](docs/design/common/ERROR_CATALOG.md)
- NX-OS対応範囲:
  [NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md](docs/design/network-ops/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)
- NX-OS hardware文書確認:
  [NXOS_HARDWARE_DOCUMENT_REVIEW.md](docs/design/network-ops/NXOS_HARDWARE_DOCUMENT_REVIEW.md)
- 既存VNI map／CSV:
  [VNI_MAP_AND_LEGACY_CSV_DESIGN.md](docs/design/network-ops/VNI_MAP_AND_LEGACY_CSV_DESIGN.md)
- 既存config投入:
  [DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md](docs/design/network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md)
- containerlab workflow:
  [CONTAINERLAB_WORKFLOW_DESIGN.md](docs/design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
- link正規化:
  [LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md](docs/design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)
- diagram:
  [TOPOLOGY_RENDERING_DESIGN.md](docs/design/topology/TOPOLOGY_RENDERING_DESIGN.md)
- Terraform inventory生成:
  [TERRAFORM_INVENTORY_GENERATION_DESIGN.md](docs/design/common/TERRAFORM_INVENTORY_GENERATION_DESIGN.md)
- 開発、test、packaging:
  [DEVELOPMENT_TESTING_AND_PACKAGING_DESIGN.md](docs/design/development/DEVELOPMENT_TESTING_AND_PACKAGING_DESIGN.md)
- 既存config投入の観測記録:
  [PUSH_CONFIG_AS_IS.md](docs/as-is/PUSH_CONFIG_AS_IS.md)

設計書、実装、テストに不一致がある場合は、暗黙にどれかへ合わせないこと。不一致と影響を
報告し、既に合意済みの設計を実装する場合だけ設計書を正本として修正する。設計変更が必要な
場合は先に設計を更新する。

設計書は現行alredの全機能をまだ網羅していない。設計書に記載がないことだけを理由に、
既存機能を未実装、不要、削除対象、または置換対象と判断してはならない。既存機能を変更する
前に、コード、CLI help、README、CONFIG、テスト、代表生成物から現行動作を確認する。

## Design work

設計を依頼された場合は、次の順序で進める。

1. 関連する設計書と既存実装を確認する。
2. 既存仕様との重複、矛盾、後方互換性、影響範囲を確認する。
3. CLI、入力schema、出力、ログ、エラー、再実行、設定投入、rollback、テストを必要な範囲で検討する。
4. 合意された内容を、責務を持つ正本の設計書へ反映する。
5. 長期的な影響がある重要判断では、必要に応じてADRを追加する。
6. 文書間のリンク、例、デフォルト値、用語が一致することを確認する。
7. `IMPLEMENTATION_STATUS.md`に設計済み・未実装の状態を反映する。

設計相談だけを依頼された場合は、明示的な依頼なしに実装コードを変更しない。未決事項は
決定済みとして記載せず、`TBD`、検討事項、または選択肢として明示する。

既存機能を設計書化する場合は、観測できたAs-Is、既存文書の記載、推測、不明点を分離する。
コードの偶然の挙動を自動的に正式仕様とせず、レビュー後に設計書へ統合する。統合状態は
`EXISTING_FEATURE_DOCUMENTATION_STATUS.md`へ反映する。

## Design document maintenance

次の変更では、コードと同じ作業内で関連する設計書を更新する。

- CLIのコマンド、option、必須条件、デフォルト値
- YAML、JSON、CSVなどの入力・出力schema
- ディレクトリ構成、成果物、ログの保存先
- health checkの判定、閾値、`PASS` / `WARN` / `FAIL` / `UNKNOWN`
- NX-OSの取得コマンド、解析対象、設定生成内容
- apply、失敗時動作、再実行、rollback、rollback後検証
- 外部システム、手動投入、既存機能との互換性や前提条件
- 認証情報、redaction、機器アクセス、確認promptなどの安全性
- 機能の実装済み・未実装・一部実装の状態

外部動作を変えない内部refactoring、コメント・誤字修正、仕様を変えない内部不具合修正では、
原則として設計書の更新は不要とする。ただし、作業中に設計書との不一致を発見した場合は
報告し、必要な文書を更新する。

設計変更では、可能な限り実装前に以下を設計書へ記載する。

- 変更後の仕様と選択理由
- 前提条件とデフォルト値
- 正常系、異常系、境界条件
- 入出力例とNX-OSコマンド例
- 後方互換性、移行、再実行、rollback
- 未実装部分と将来拡張

実装されていない機能を「実装済み」と記載してはならない。実装完了時は設計書、コード、
テスト、サンプル、`IMPLEMENTATION_STATUS.md`の整合を確認する。

## Implementation policy

- 既存CLIと既存ファイル形式の互換性を、設計で廃止が承認されるまで維持する。
- 既存config投入の接続・1行送信・保存処理を再利用し、別のSSH executorを重複実装しない。
- `generate-vni-config`と`overlay-change plan`でconfig生成処理を二重実装せず、共通rendererを使用する。
- 収集は既存`collect-*`を利用し、health checkのparser・判定と分離する。
- 同じ入力から同じ結果を再生成できるよう、入力、schema version、parser version、hashを記録する。
- 設定投入前にrunning configとplanを比較し、設定済み、競合、不明を区別する。
- 競合や安全に判定できない状態ではfail closedとし、設定投入を継続しない。
- rollbackはoperationが所有する変更だけを対象とし、beforeのrunning configとの差分がないことを検証する。
- 単体テストから実機へ接続したり、設定を投入したりしない。
- timezoneの既定値など、設計済みのデフォルトをコード内で独自に変更しない。
- ユーザーの未コミット変更を保持し、依頼と無関係なファイルを変更しない。
- attemptは成功・失敗を問わず不変の証跡として保持し、retryでは新しいattemptを作成する。
- `current.json`は正常に公開された最新attemptを指す。operation metadataの`current_attempt`は
  実行中または失敗した最新attemptを指す場合があるため、同一と仮定しない。
- partial attemptを常に想定し、必須成果物の存在、schema、hashを検証してから参照する。
- canonical成果物とcurrent pointerは処理完了後だけatomicに更新し、失敗時は以前の成功済み
  pointerを維持する。
- 想定済みのvalidation・operation errorはcode付きで表示し、Python Tracebackを表示しない。
  予期しない内部例外まで包括的に捕捉して隠さない。

## GitHub policy

- `main`へ直接pushしない。`<type>/<short-name>`形式のworking branchとPull Requestを使用する。
- typeは原則`feature`、`fix`、`docs`、`refactor`、`test`、`chore`、`release`から選ぶ。
- branch作成、commit、push、PR作成は、ユーザーがそのGit操作またはPR作成を明示的に依頼した
  場合だけ行う。通常の実装依頼だけから外部GitHub操作を推測しない。
- Agentが作成するPRは既定でDraftとする。merge、PR close、tag push、Release作成・公開は、
  それぞれ対象を確認できる明示的な依頼がある場合だけ行う。
- protected branchへforce-pushしない。ユーザーの変更をstash、rebase、squash、履歴書換えする
  場合は明示的な依頼を必要とする。
- secret、認証情報、未加工の実機ログ、`operations/`、support bundle、生成binaryをcommitしない。
- PR本文は日本語を既定とし、command、option、path、version、error codeは原表記を維持する。
- GitHub上の操作前にremote、current branch、worktree、対象差分、認証状態を確認する。

## Testing and verification

test runnerは`pytest`に統一する。既存の`unittest.TestCase`はpytestで実行し、関連機能を
変更するときに段階的にpytest形式へ移行する。新規テストは原則としてpytestのfixture、
parameterization、plain `assert`を使用する。実装本体をtest runnerへ依存させない。

基本確認:

```bash
python -m pytest
python alred.py --help
```

`uv`を使用する環境:

```bash
uv run pytest
uv run python alred.py --help
```

通常の自動テストでは`device` markerを除外する。labまたは実機へ接続するテストは
明示的な承認と対象指定がある場合だけ実行する。

```bash
uv run pytest -m "not device"
```

変更範囲に応じて、schema validation、parser fixture、golden config、CLI、失敗時動作、
rollback、既存機能の回帰テストを追加する。実機や秘密情報が必要な検証は自動実行せず、
前提と手順を報告する。

retry可能な処理では、成功後の再実行だけでなく、収集後、解析前、公開前、verification前などで
中断してpartial artifactだけが残った状態をテストする。以前の成功済みcurrentと新しい失敗attemptが
同時に存在するケースも含める。

## Definition of done

作業は次を満たした場合に完了とする。

- 合意された設計または受け入れ条件を満たしている。
- 正常系、重要な異常系、境界条件のテストがある。
- 関連する既存テストが成功している。
- CLI help、sample、出力例、設計書が実装と一致している。
- forward config、rollback config、ログ、判定根拠を追跡できる。
- `IMPLEMENTATION_STATUS.md`が実際の状態へ更新されている。
- 未検証事項、制約、残課題を完了済みとして隠していない。
