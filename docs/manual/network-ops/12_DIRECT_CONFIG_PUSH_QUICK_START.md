# Direct Config Push Quick Start

この章では、host 別 config file を `push-config-dir` で直接投入し、投入前後の Health Check を確認してから
`write-memory` で明示的に保存するモデルケースを示します。

Direct Config Push は running-config を変更しますが、Managed Overlay Operation の ChangeSet、plan、approval、
automatic rollback を作成しません。監査可能な Overlay 変更では
[Overlay Configuration Quick Start](./11_OVERLAY_CONFIGURATION_QUICK_START.md)を使用してください。

## 1. 対象と config を準備

[Common Preparation](./00_COMMON_PREPARATION.md)に従って `hosts.yaml` と credential を準備します。
既定の exact mode では `<hostname><suffix>` と一致する file を各 host へ投入します。

```text
raw/config/
├── leaf01_run.txt
└── leaf02_run.txt
```

投入対象は `leaf01` と `leaf02`、suffix は `_run.txt` とします。対象外 host の file を同じ directory に
置いても、`--target-hosts` で選択されなければ投入しません。

## 2. before を収集

Direct Config Push 自体は Operation を作成しないため、投入前後の確認用 Operation を明示的に作成します。

```bash
alred health-check before \
  --collect \
  --hosts hosts.yaml \
  --change-id DIRECT-2026-00123 \
  --profile network-baseline-nxos \
  --logging-days 1 \
  --ask-pass
```

Checklist の対象 host、`FAIL`／`UNKNOWN`、作業継続できない `WARN` がないことを確認します。

## 3. host 別 config を投入

最初は `--workers 1 --fail-fast` で実行します。

```bash
alred push-config-dir \
  --hosts hosts.yaml \
  --input-dir raw/config \
  --file-suffix _run.txt \
  --target-hosts leaf01,leaf02 \
  --workers 1 \
  --fail-fast \
  --ask-pass
```

投入前表示で、host と config file の対応、接続保護 filter で除外された command、投入 command 数を
確認し、意図どおりの場合だけ `yes` と入力します。NX-OS では接続に使用中の username、management VRF、
`interface mgmt0`、`line vty` が既定で除外されます。

CLI error は既定で strict に検出されます。最初の未許可 error で該当 host の残りを停止し、`--fail-fast` は
まだ開始していない host の投入も停止します。失敗した file を無条件で再送せず、log の command 行番号、
該当 command、直前の正常処理済み command から現在状態を確認してください。

## 4. after を収集して確認

```bash
alred health-check after \
  --change-id DIRECT-2026-00123 \
  --ask-pass
```

同じ change ID の before／after、Checklist、running-config diff、対象機能の正常性を確認します。Direct Config
Push は期待差分を ChangeSet として評価しないため、投入した config と実際の差分が一致することは利用者が
確認します。

## 5. configuration を保存

投入成功だけで保存せず、再接続と after の確認が完了してから明示的に実行します。

```bash
alred write-memory \
  --hosts hosts.yaml \
  --target-hosts leaf01,leaf02 \
  --workers 1 \
  --ask-pass
```

`write-memory` は config を追加投入せず、NX-OS では `copy running-config startup-config` の成功応答を
確認します。一部 host が失敗した場合は全対象が保存済みとみなしません。

## 6. 単一 config と例外 option

同じ config を選択した全 host へ投入する場合は `push-config` を使用します。

```bash
alred push-config \
  --hosts hosts.yaml \
  --config-file push_commands.txt \
  --target-hosts leaf01,leaf02 \
  --workers 1 \
  --fail-fast \
  --ask-pass
```

次の option は標準手順では使用しません。

| option | 用途と注意 |
|---|---|
| `--write-memory` | push と保存を同じ実行にする。投入後確認を分離できないため標準手順では使用しない |
| `--allow-cli-error-pattern` | レビュー済みの限定的な command／response 組だけを許可する |
| `--ignore-all-cli-errors` | 非推奨。全 CLI error を無視し、保存対象外となる |
| `--force` | `push-config-dir` の接続保護 filter を解除する。代替接続と復旧手段がある場合だけ使用する |

接続保護 filter、投入前表示、`--force` の詳細は
[push-config-dir Guide](./10_PUSH_CONFIG_DIR.md)、正式仕様は
[Direct Config Push and Save Design](../../design/network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md)を
参照してください。
