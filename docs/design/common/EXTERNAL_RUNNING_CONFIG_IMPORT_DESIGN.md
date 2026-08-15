# External Running Config Import Design

## 1. 文書の目的

alred自身のcollectionとは別に取得されたNX-OS `show running-config`を、Topology解析とContainerlab config変換で
共用できるホスト別artifactとManifestへ安全にimportする仕様を定める。本処理は保存済みfileだけを読み、deviceへ
接続しない。

外部transcriptのprompt／command区間認識は既存
[Health Check Framework](../network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md#31-transcript-importer)を共通adapterとして
再利用し、Topology用に別parserを実装しない。

## 2. Workflowと責務

```text
external input folder
├── one file per host
└── one transcript containing multiple hosts
                 ↓
External Running Config Import
├── file / prompt / command / hostname resolution
├── ambiguity / completeness validation
├── per-host canonical running config
└── Running Config Import Manifest
                 ↓
          ┌──────┴────────┐
     normalize-links   clab-transform-config
```

importはrunning configの意味解析、link確定、lab parameter変換を行わない。source byte列、採用区間、hostname、
command、hashを固定し、後続consumerが同じ入力世代を参照できる状態までを担当する。

## 3. CLI

CLI を次とする。

```text
alred import-running-config \
  --input <directory> \
  --input-format <alred-collect|running-config-directory|nxos-transcript> \
  --hosts <hosts.yaml> \
  [--source-map <source-map.yaml>] \
  [--lldp-input <directory>] \
  [--output <import-directory>]
```

| option | 意味 |
|---|---|
| `--input` | source directory。単一fileの場合も親directoryと対象mapを固定する |
| `--input-format` | hostname／command境界の解決方式。内容から自動推測しない |
| `--hosts` | canonical hostname、alias、platformを解決するinventory |
| `--source-map` | 任意filenameとhostnameの明示対応。`running-config-directory`で必要時に使用 |
| `--lldp-input` | 任意の補助LLDP directory。省略時はdescription-only |
| `--output` | immutable import attemptの出力先。省略時は `imported-running-config` |

既存の`normalize-links --input`と`clab-transform-config --input`は後方互換のalred collect形式として維持する。
新しいimport結果は両commandが`--running-config-import <manifest-or-directory>`で参照する目標仕様とし、既存raw入力、
Evidence Package入力との同時指定を拒否する。

## 4. Input format

### 4.1 `alred-collect`

`config/<hostname>_run.txt|json`を既存規則で読み、同一hostnameでJSONとtextがある場合はJSONを優先する。legacy
current mirrorを使用する場合も採用fileをManifestへ固定し、`old/`やstale sidecarを混在させない。

### 4.2 `running-config-directory`

一つのfileは一つのdeviceのrunning configだけを含む。`.txt`を対象とし、hostnameを次の順で解決する。

1. `--source-map`のsource相対pathに完全一致するhostname
2. 既存`<hostname>_run.txt`規則
3. config内の一意な`hostname <value>` command
4. inventory hostname／aliasへの一意照合

上位と下位の解決結果が矛盾する場合は上位を黙って採用せず`EXTERNAL_CONFIG_IDENTITY_CONFLICT`とする。任意filenameで
config内hostnameがない場合はsource mapを必須とする。symlink、hidden file、binary、root外pathは拒否する。

source map例:

```yaml
api_version: alred/v1
kind: RunningConfigSourceMap

spec:
  files:
    - path: backup-001.txt
      hostname: leaf01
    - path: rack-a/spine-primary.txt
      hostname: spine01
```

### 4.3 `nxos-transcript`

一つまたは複数fileに複数deviceを含められる。`hostname#`／`hostname>`などのprompt、入力された
`show running-config`、次のpromptまでの出力区間を検出し、inventory hostname／aliasへ一意照合する。

- ANSI escape、backspace、paging markerは既存transcript importerの規則で正規化する。
- `show running-config`以外のcommand区間はrunning configとして採用しない。
- prompt、command、hostをhigh confidenceで確定できる区間だけcanonical artifactへ採用する。
- prompt欠落、複数hostの行単位混在、途中開始、command echo欠落、重複区間は`unresolved_segments`へ記録する。
- 同一hostの採用可能なrunning configが複数ある場合、mtimeや出現順から最新を推測せず失敗する。

## 5. Completenessとhostname整合

canonical running configは、開始と終了を次のいずれかで確定できる必要がある。

- host別file全体が一つのconfigであり、hostnameを一意に解決できる
- transcriptで`show running-config` commandから次のdevice promptまでを確定できる

空file、decode不能、hostname不明、inventory未登録、同一host重複、promptとconfig内hostnameの矛盾、途中切断を
正常完了とみなさない。config内に`hostname` commandがないことだけでは不完全とせず、source mapまたはpromptで
identityが一意なら採用できる。

## 6. LLDPの任意入力

LLDPは補助capabilityであり、外部running config importの必須条件にしない。`--lldp-input`が指定された場合は
既存platform parserで解釈可能なホスト別LLDP、またはtranscript内の`show lldp neighbors detail`区間を同じManifestへ
固定する。LLDPの世代、hostname、hashがrunning configと整合しない場合は混在させない。

LLDPがない場合はManifestへ`lldp: not_provided`を記録し、`normalize-links`はinterface descriptionだけを使用する。

| description evidence | 出力 | confidence | Containerlab自動利用 |
|---|---|---|---|
| 両側descriptionが相互一致 | confirmed | `low` | `min-confidence=low`で利用可能 |
| 片側descriptionのみ | candidate | `low` | 不可 |
| ruleでremoteを解決不能 | unresolved／warning | ― | 不可 |

LLDPが存在する場合はLLDPを優先証拠としてdescriptionと統合し、不一致をwarningへ記録する。LLDP欠落を異常扱いして
description recordを破棄せず、LLDPなしという制約をnormalization resultへ残す。

## 7. 成果物

```text
<import-directory>/attempts/<attempt-id>/
├── running-config-import-manifest.yaml
├── inventory/
│   └── hosts.resolved.yaml
├── config/
│   └── <hostname>_run.txt
├── lldp/                         # 指定・解決できた場合のみ
│   └── <hostname>_lldp.txt
├── unresolved-segments.yaml
└── checksums.sha256
```

Manifestにはsource file／SHA-256／size、採用行範囲、input format、解決前identity、canonical hostname、照合根拠、
command、confidence、normalization内容、LLDP有無、除外／未解決理由、tool／adapter versionを記録する。
resolved inventory は consumer が別途 `--hosts` を必須にしないよう、import 時の入力 inventory を
不変 copy と hash で固定する。
canonical configはsourceの設定行を変更せず、transcript wrapper、prompt、command echo、paging／terminal制御だけを
既存規則で除去する。source fileは変更・削除しない。

attemptは成功・失敗を問わず不変とし、全必須hostのconfig、Manifest、checksum検証完了後だけ`current.json`を
atomicに更新する。partial attemptを後続consumerの既定入力にしない。

## 8. Errorと再実行

| Code | 条件 |
|---|---|
| `EXTERNAL_CONFIG_INPUT_INVALID` | path、形式、encoding、source mapが不正 |
| `EXTERNAL_CONFIG_IDENTITY_UNRESOLVED` | hostname／aliasを一意に解決できない |
| `EXTERNAL_CONFIG_IDENTITY_CONFLICT` | filename、map、prompt、config、inventoryが矛盾 |
| `EXTERNAL_CONFIG_DUPLICATE_HOST` | 同一hostの採用可能configが複数 |
| `EXTERNAL_CONFIG_INCOMPLETE` | 空、途中切断、必須host不足、checksum不成立 |

利用者が入力、map、inventoryを修正できるため終了codeは`2`とする。retryは新attemptを作成し、成功済みcurrentを
失敗attemptで置き換えない。

## 9. 実装状態とtest

ホスト別任意 filename、source map、config 内 hostname、複数 host NX-OS transcript、任意 LLDP、resolved inventory、
immutable attempt／current／Import Manifest、`normalize-links`／`clab-transform-config`／`clab-set-cmds` への接続を
実装済みとする。Health の NX-OS transcript importer との内部 code 共用、ANSI／paging／backspace の
全対応 fixture は未実装である。

実装時はホスト別任意名、source map、embedded hostname、複数host／複数file transcript、alias、ANSI／paging、
重複host、途中切断、identity conflict、LLDPあり／なし、双方向／片方向description、partial attempt、決定的出力を
synthetic fixtureでtestする。
