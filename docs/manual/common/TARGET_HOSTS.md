# 対象ホストの指定

`--target-hosts` は inventory（`hosts.yaml`）の hostname で対象を絞り込みます。
接続先 IP、装置の prompt、inventory group 名との照合ではありません。

## 1. 完全一致で複数指定

```bash
alred collect --hosts ./hosts.yaml --target-hosts site-leaf01,site-spine01
```

`site-leaf01` と `site-spine01` だけが対象です。
照合方式を省略すると、従来どおり完全一致です。`--target-hosts-match exact` と明示しても同じです。
`--target-hosts` も省略すると、inventory のうち policy で許可された全ホストが対象になります。

## 2. 部分一致で複数指定

```bash
alred collect \
  --hosts ./hosts.yaml \
  --target-hosts leaf,spine \
  --target-hosts-match contains
```

hostname に `leaf` **または** `spine` が含まれるホストを選びます。

| Inventory の hostname | 選択結果 |
|---|---|
| `site-leaf01` | 対象 |
| `site-leaf02` | 対象 |
| `site-spine01` | 対象 |
| `site-border01` | 対象外 |
| `site-Leaf03` | 対象外（大文字・小文字を区別） |

- 指定はカンマ区切りの OR 条件です。前後の空白は除去します。
- 同じホストが複数の文字列に一致しても、処理は 1 回だけです。
- `*` はワイルドカードではありません。例えば `leaf*` は `leaf01` に一致しません。
- policy の include／exclude も適用します。部分一致で policy の除外を解除できません。
- 部分一致では接続前に対象 hostname と件数を表示し、log に照合条件と対象一覧を残します。

`--target-hosts-match contains` を指定したのに文字列がない、`leaf,,spine` のような空要素がある、
または指定した文字列のいずれかが inventory に 1 件も一致しない場合は、`VALIDATION_ERROR` で停止します。
例えば `leaf,unknown` は `leaf` に一致するホストだけで処理を続けません。
policy 適用後に対象が 0 件になった場合も停止します。終了 code は `2` です。

## 3. 使用できるコマンド

`--target-hosts` を持つ以下のコマンドで、同じ照合方式を使用できます。

- `collect`、`collect-list`、`collect-run-config`、`collect-run-diff`、`collect-run-diff-cmd`、
  `collect-clab`、`collect-all`、`collect-before-work`、`collect-after-work`
- `check-logging`、`check-clab-startup-config`
- `push-config`、`push-config-dir`、`write-memory`、`clab-apply-config`
- `clab-set-cmds` と `generate-vni-config` の自動収集
- `health-check`／`overlay-check` の `before`・`after`・`rollback` による直接収集

設定投入・保存では、部分一致で選んだ対象に対して既存の確認手順を実施します。
`--show-hosts` による追加 show command の対象指定と、ChangeSet の対象 device 指定は完全 hostname のままです。
外部ログの `--input` 取り込みには `--target-hosts-match` を使いません。
`clab-set-cmds` などの収集を行わない実行では、この option による成果物の絞り込みは行いません。

## 4. Health Check の before／after と retry

初回の before で部分一致を指定します。

```bash
alred health-check before \
  --change-id CHG-TARGETS-001 \
  --collect --hosts ./hosts.yaml \
  --profile network-baseline-nxos \
  --target-hosts leaf,spine \
  --target-hosts-match contains
```

after は対象の指定を省略すると、before と同じホストを使用します。

```bash
alred health-check after --change-id CHG-TARGETS-001
```

初回収集前に `health/execution-context.yaml` へ、指定文字列・照合方式・解決済みの完全 hostname を保存します。
初回収集に失敗した場合の before retry でも、同じ change ID の対象を維持します。
before retry は既存の手順どおり `--collect`、`--hosts` などを指定し、対象 option は省略できます。
after／rollback／retry で対象を再指定した場合は、解決後の対象集合が before と同じである必要があります。
照合方式の省略時は before の方式を継承します。完全 hostname で再指定する場合は `exact` を明示できます。
inventory／policy が変更された場合も接続前に停止します。対象を変更する場合は新しい change ID を使用してください。

新しい execution context では、直接収集の対象が 0 件の場合は開始しません。
旧 execution context は従来の完全一致として読み取り、空の `target_hosts` は従来どおり全対象を意味します。

仕様と互換性の詳細は [Target resolution](../../design/common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md#31---target-hosts-部分一致の対象選択)を参照してください。
