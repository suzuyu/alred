# CLI, Configuration, and Resource Design

## 1. 文書の目的

alred全用途に共通するCLI entry point、設定値の解決、既定path、logging、package resourceの
現行仕様を定める。個別commandの業務仕様は各用途の設計書を正本とし、本書へ重複記載しない。

現行実装の根拠と未確認事項は
[CLI, Configuration, and Resources As-Is](../../as-is/CLI_CONFIGURATION_AND_RESOURCES_AS_IS.md)
を参照する。

## 2. 責務境界

| 責務 | 正本 |
|---|---|
| top-level command、共通dispatch、設定・path・resource探索 | 本書 |
| machine-readable schemaと互換性 | [Schema and Compatibility Policy](./SCHEMA_AND_COMPATIBILITY_POLICY.md) |
| 共通error codeと終了code | [Error Catalog](./ERROR_CATALOG.md) |
| inventory、credential、transport | [Inventory, Credentials, and Device Access Design](./INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md) |
| legacy collectionのcommand選択とraw成果物 | [Collection Design](./COLLECTION_DESIGN.md) |
| operationの状態、lock、approval | [Operation State and Approval Design](./OPERATION_STATE_AND_APPROVAL_DESIGN.md) |
| Health Check、Overlay、containerlab、topology | 各用途別directoryの設計書 |

## 3. CLI契約

### 3.1 Entry point

- installed commandのentry pointは`alred = alred.cli:main`とする。
- source checkoutの`python alred.py`も同じ`main()`を呼ぶ。
- Python要件は`pyproject.toml`の`requires-python`を正本とし、現在は3.11以上とする。
- `.env`はargument parse前に読み込む。
- password prompt optionはparse後、command callback実行前に解決する。

### 3.2 Command分類

現行top-level commandを用途別に分類する。分類は文書の配置と責務を示し、command名を変更しない。

| 用途 | command |
|---|---|
| Common / inventory generation | `prepare-hosts`、`generate-tf`、`generate-sample-config`、`completion` |
| Collection / read-only check | `collect`、`collect-list`、`collect-run-config`、`collect-run-diff`、`collect-run-diff-cmd`、`collect-all`、`collect-before-work`、`collect-after-work`、`check-logging` |
| Direct Config Push | `push-config`、`push-config-dir`、`write-memory` |
| Evidence transfer | `evidence-package create/inspect/verify/import` |
| Network operations | `operation`、`health-check`、`overlay-check`、`overlay-change`、`support-bundle`、`generate-vni-map`、`generate-vni-config` |
| Containerlab | `init-clab`、`collect-clab`、`clab-transform-config`、`clab-apply-config`、`check-clab-startup-config`、`clab-set-cmds`、`generate-clab` |
| Topology | `normalize-links`、`generate-network-diagram`、`generate-mermaid`、`generate-graphviz`、`generate-drawio`、`generate-doc`、`csv-to-md` |
| Internal | `__complete` |

既存command名、option名、alias、入力・出力filenameは、明示的な廃止設計が承認されるまで維持する。
新しい用途別subcommandへ再編する場合も、旧commandを直ちに削除しない。

### 3.3 Parse、dispatch、終了code

- top-level subcommandは必須とする。
- `--help`は終了code `0`、argparseが検出する未知command・不足argumentは`2`とする。
- callbackが非zeroの整数を返す場合、その値をprocess終了codeとして使用する。
- `OperationError`と`ProfileResolutionError`は、code付きの利用者向けerrorへ変換する。
- 予期しない内部例外をtop-levelで包括的に捕捉して正常終了させない。
- 利用者が修正可能なvalidation errorは段階的に[Error Catalog](./ERROR_CATALOG.md)へ接続し、
  Tracebackを表示しない。

### 3.4 Shell completion

- `completion bash`と`completion zsh`はshell scriptを標準出力へ返す。
- `__complete`は通常helpに表示しない。
- file optionはYAML、text、CSVまたは任意fileの種別に応じて候補を返す。
- host list optionは明示inventory、`hosts.lab.yaml`、`hosts.yaml`の順で候補を探索する。
- completion中の入力読込失敗は候補なしとして扱い、通常commandのvalidationを代替しない。

## 4. 設定値の解決

### 4.1 共通優先順位

同じ意味の値が複数sourceにある場合、次の順を基本とする。

1. CLI optionまたは実行時prompt
2. command固有の補助設定file
3. `ALRED_*`環境変数と`.env`
4. 移行互換用`NW_TOOL_*`環境変数
5. code内default

例外となる詳細な順序は、credentialは
[Inventory, Credentials, and Device Access Design](./INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)、
roleは[Role Definition and Resolution Design](./ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md)を正本とする。

### 4.2 既定path

| 用途 | 解決順 | 最終default |
|---|---|---|
| raw collection | `ALRED_RAW_DIR` → `ALRED_OUTPUT_DIR` → `NW_TOOL_RAW_DIR` → `NW_TOOL_OUTPUT_DIR` | `raw` |
| normalized links | `ALRED_LINKS_DIR` → `ALRED_OUTPUT_DIR` → `NW_TOOL_LINKS_DIR` → `NW_TOOL_OUTPUT_DIR` | `output` |
| topology / diagram | `ALRED_TOPOLOGY_DIR` → `ALRED_OUTPUT_DIR` → `NW_TOOL_TOPOLOGY_DIR` → `NW_TOOL_OUTPUT_DIR` | `output` |
| logs | `ALRED_LOG_DIR` → `NW_TOOL_LOG_DIR` | `logs` |
| operation | commandの`--operations-root` | `operations` |

`ALRED_OUTPUT_DIR`は互換用の共通fallbackであり、用途別変数が指定された場合はそちらを優先する。

Operationの物理pathは`operations/live/YYYY/MM/DD/<change-id>/`であり、利用commandは
`operations/<change-id>`を組み立てず共通resolverを使用する。既存のflat layoutは互換入力として
維持する。手動archiveの既定経過日数は`--older-than-days`、
`ALRED_OPERATION_ARCHIVE_AFTER_DAYS`、code defaultの順に解決し、code defaultは14日とする。

### 4.3 Current working directoryの探索

次のfilenameは、対応optionが省略された場合にcurrent working directoryから探索できる。

| 種別 | filename |
|---|---|
| inventory | `hosts.yaml` |
| lab inventory | `hosts.lab.yaml`、次に`hosts.yaml` |
| credential | `clab_credentials.yaml` |
| role | `roles.yaml` |
| site | `sites.yaml` |
| description rule | `description_rules.yaml` |
| show command | `show_commands.txt` |

探索するかどうかはcommandが対応optionを持つ場合に限る。暗黙fileを使用した実行では、運用成果物が
ある場合にresolved pathとhashを記録する。

## 5. YAMLとtext出力

- YAMLの読込はsafe loaderを使用し、空documentは空mappingとして扱う。
- schema対象入力は、汎用YAML読込後に対応するJSON Schemaまたは専用validatorで検証する。
- directoryは必要時に作成し、UTF-8を使用する。
- YAML出力はfield順序を保持し、Unicodeをescapeしない。
- operationのcanonical成果物には汎用writerだけを使わず、atomic publishとhash検証を適用する。

## 6. Logging

- logger名は`alred`とする。
- console levelは通常`INFO`、`--verbose`時`DEBUG`とする。
- `--log-file`指定時のfile levelは`DEBUG`とし、UTF-8で保存する。
- password、enable secret、token、Authorization header、credential file本文をlogへ出力しない。
- host、transport、command、結果を記録する場合も、機器出力の機密性を考慮し、support bundleへ
  直接転用しない。
- operation監査logの不変性と公開順序はOperation State設計を正本とする。

## 7. Package resource

- source／wheelではinstalled `alred` package directoryをresource rootとする。
- PyInstallerでは`sys._MEIPASS/alred`をresource rootとする。
- 配布物には、実装が参照する`health/profiles`、`capabilities`、`schemas`、`j2`、
  `sample_configs`を含める。
- package resourceのpathをcurrent working directoryの同名fileで暗黙に置換しない。外部fileを
  使用する場合はCLI optionまたは定義済み探索規則で明示する。
- source、wheel、PyInstallerの各実行形態でresourceが読めることをtestする。

## 8. 互換性と変更手順

- CLI command、option、default、環境変数、探索filenameの変更では、同じ作業でREADME、CONFIG、
  manual、sample、CLI testを更新する。
- option追加は原則として後方互換とし、既存defaultの意味を黙って変更しない。
- legacy `NW_TOOL_*`を廃止する場合は、警告期間、代替名、対象releaseを先に設計する。
- command分類の変更は文書上の整理であり、既存CLIのnamespace変更を意味しない。

## 9. 実装状態と既知の制約

- entry point、command dispatch、path・resource探索、loggingは実装済みである。
- top-level command集合と主要終了codeはtestで固定済みである。
- 全subcommand optionのmachine-readable catalogと、全legacy errorのError Catalog統合は未実装である。
- schemaを持たないlegacy YAML入力の共通validationは未実装であり、各loaderの確認範囲に依存する。
