# Security and Data Transfer

## 1. Trust boundary

商用環境の raw、隔離 lab の生成物、共有用 artifact を区別する。

```text
Production raw
    ↓ sanitize / verify
Transfer artifact
    ↓ controlled transfer
Isolated lab
    ↓ inject lab-local credential
Containerlab artifacts
```

商用 credential、秘密鍵、token、元の credential file を lab へ持ち込まない。lab credential は隔離環境で注入する。

## 2. 現行運用

現行の `collect-all` archive や手動 tar は Portable Evidence Package ではなく、収集世代、allowlist、redaction、
secret scan を保証しない。移送する場合は承認済み手順で内容、hash、保存先、削除期限を確認する。
未加工の `raw/` や operation directory を AI または外部へ共有しない。

## 3. Portable Evidence Package 経路

[Portable Evidence Package Design](../../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)では、収集 artifact と利用時 policy を
Manifest と checksum 付き tar へ固定し、Digital Twin と AI で開示 policy を分離する。現行実装は Collection Manifest、resolved
inventory、成功済み command output、roles、mappings、description rules、sites、confirmed／candidate canonical link を収録する。
Collection Manifest source の `digital-twin` と `ai-analysis` について、
identity 保持または pseudonymize した sanitized config、および明示確認付き `protected-preserve`／verbatim config の
`alred evidence-package create/inspect/verify/import` を実装済みとする。AI profile は成功した収集 command をすべて収録し、
`analysis/STRUCTURE.md` と `analysis/prompt.md` を追加する。

`digital-twin` の既定は `protected-preserve`／`sanitized` である。hostname、IP address、interface identity は保持するが、
password、secret、community、key、token、private key などは除去する。隔離 lab で元機器との対応を確認しやすくしつつ、
原文 credential は搬送しない。identity も隠す必要がある場合だけ `--disclosure-preset pseudonymized` を明示する。

`create` は sanitizer と独立した secret scan を変換後の content text へ実行する。sanitized member に high confidence
finding が残った場合や text を UTF-8 として scan できない場合は archive を公開しない。`package-manifest.yaml` には
catalog hash、`CLEAN`／`LOW_CONFIDENCE_FINDINGS`／`ACKNOWLEDGED_SENSITIVE` status、high／low 件数、値を含まない
rule ID と位置を記録する。`inspect` と `verify` は summary を表示し、`verify` は同じ catalog で再 scan する。
`verbatim` の high confidence finding は、明示 acknowledgement がある member に限って許可される。
Secret Scan field 導入前の package は `secret_scan_declared: false` として現在の catalog で再 scan される。安全な旧 package
は import できるが、旧 sanitized config に high confidence finding が残る場合は source から package を再作成する。

現行の Containerlab consumer は、package 作成時の sanitization 済み config をそのまま boot-time startup config とせず、隔離 lab 側の
`LabTransformParameters` で management subnet、hostname、vPC keepalive、NTP、logging、DNS、AAA、SNMP、lab user を
明示的に remove／replace する。production credential や接続先へ fallback しない。正式仕様は
[Containerlab Workflow Design](../../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md#56-evidence-packageからのlab-parameter変換)
を参照する。このparameter入力は`clab-transform-config --lab-parameters`で利用できる。

import は安全な展開だけを行い、link を暗黙に解析しない。import 後の `normalize-links --evidence-package`
は任意 LLDP、description、固定済み rules から link を再生成し、package 同梱の canonical link と一致した
`VERIFIED` confirmed link だけを Containerlab 生成へ使用する。import 済み package の config 変換は
`clab-transform-config --evidence-package <directory>` で実行できる。標準はこれらをまとめた
`clab-set-cmds --evidence-package <archive>` とする。

商用環境側:

```bash
alred evidence-package create --profile digital-twin
```

source option 省略時は、live Operation の最新の正常公開済み current before attempt を自動選択する。表示された
`source_change_id`、`source_attempt_id`、`source_completed_at`、`source_manifest` を搬送前に確認する。
`--config-content` は `sanitized`、`--output-dir` は `evidence-packages` を既定とし、出力 directory は必要時に自動作成する。

作成側でも搬送前に metadata と Secret Scan結果を確認する。

```bash
alred evidence-package inspect \
  --bundle evidence-packages/<package-id>.tar.gz \
  --format json

alred evidence-package verify \
  --bundle evidence-packages/<package-id>.tar.gz \
  --format json
```

隔離 lab 側:

```bash
alred evidence-package import \
  --bundle evidence-packages/<package-id>.tar.gz

alred clab-transform-config \
  --evidence-package imported-evidence/<package-id>
```

`--lab-parameters` と出力先 option は任意である。省略時は built-in safety policy と既定出力
`hosts.lab.yaml`、`raw/labconfig/`、`raw/lab-transform-manifest.yaml` を使用する。

`verify` と `import` は、`--checksum-file` 省略時に archive と同じ directory の `<package-id>.sha256` を
自動検出する。checksum file がない場合も内部 checksum 検証で継続し、
`external_checksum_verified: false` を記録する。`import` は `verify` の全検証を内部実行してから atomic に展開する。
展開せず検証結果だけが必要な場合に限り、単独の `evidence-package verify` を先に実行する。

import 成功後は `imported-evidence/latest` が最新の正常公開済み package directory を指す。次の指定も使用できる。

```bash
alred clab-transform-config \
  --evidence-package imported-evidence/latest
```

処理開始時に symbolic link を実体 package directory へ固定し、Manifest、import record、artifact hash を検証する。
再現手順や監査記録では曖昧さを避けるため package ID を明示する。

原文 config が必要な例外では、作成、import、Containerlab 変換の各境界で明示確認する。

```bash
alred evidence-package create \
  --profile digital-twin \
  --disclosure-preset protected-preserve \
  --config-content verbatim \
  --acknowledge-sensitive-config

alred evidence-package import \
  --bundle evidence-packages/<package-id>.sensitive.tar.gz \
  --acknowledge-sensitive-config \
  --output-dir imported-evidence

alred clab-transform-config \
  --evidence-package imported-evidence/<package-id> \
  --acknowledge-sensitive-config
```

## 4. Offline workflow の全体像

### 4.1 Evidence Package

```text
Evidence Package tar.gz
    ↓ evidence-package import（内部 verify）
imported package
    ↓ Manifest から inventory / config を解決
clab-transform-config + lab-transform-parameters.yaml
    ↓
hosts.lab.yaml + raw/labconfig/ + lab-transform-manifest.yaml
    │
    ├── 現行: 商用側で確認済みの links-confirmed.csv を別途移送
    │          ↓ generate-clab
    └──────── topology.clab.yaml
               ↓ containerlab deploy
          clab-apply-config
               ↓
           running lab

将来:
imported package
    ↓ LLDP / description / packaged canonical link を再生成比較
VERIFIED links-confirmed.csv
    ↓ generate-clab
topology.clab.yaml
```

Package Manifest の`config_content`が`sanitized`または`verbatim`のどちらを変換元にするかを固定する。
Containerlab 側に`--config-source`を設けず、directory 名や同名 file の存在から推測しない。

- `sanitized`: Manifest が参照する secret 除去済み config を変換する。`protected-preserve`ではidentityを保持し、
  `pseudonymized`ではidentityも一貫した仮名へ変換する。
- `verbatim`: sensitive config の承認と package 属性を再検証し、Manifest が参照する原文 config を変換する。

`digital-twin`の`mask`は、秘密情報以外では command、block、出現順、安全な option を残す型付き placeholder を優先する。
この構造と Manifest の rule ID から lab-local 値へ置換できるため、mask だけを理由に変換不能とはしない。placeholder を機器へ
投入せず、原値の復元や verbatim artifact からの補完も行わない。

どちらの場合も同じ lab parameter 変換を適用し、management address、hostname、vPC keepalive、AAA、NTP、logging、
DNS、SNMP、credential、production 接続先を lab-local 値へ置換または削除する。`verbatim`を選んだことは production
credential や service endpoint を保持する許可ではない。変換元 artifact、hash、rule、除去／置換件数は
`lab-transform-manifest.yaml`へ記録し、secret の原値は記録しない。

### 4.2 外部 show running-config folder

```text
host 別 file または複数 host transcript
    ↓ import-running-config
per-host config + Running Config Import Manifest
    ├→ clab-transform-config
    └→ normalize-links
           ├─ optional LLDP あり: LLDP + description
           └─ LLDP なし: description-only
                    ↓
               generate-clab
```

host 分割と identity 解決は import 時に一度だけ行い、config 変換と link 正規化で同じ Manifest を使用する。
LLDP がない場合、双方向 description は confirmed `low`、片方向 description は candidate `low`とし、candidate を
Containerlab link へ自動採用しない。この import workflow は `import-running-config`、
`--running-config-import` consumer、`clab-set-cmds` へ実装済みである。

### 4.3 任意収集と既存 Operation の再利用

既存の live `operations/` に必要な正常公開済み before attempt がある場合、実機収集をスキップして
`evidence-package create` へ進む。最新状態が必要な場合だけ、商用環境の実機から変更作業を前提としない inspection を
新規収集する。

```bash
alred health-check before \
  --purpose inspection \
  --collect \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --mappings mappings.yaml \
  --description-rules description_rules.yaml
```

収集を実行した場合もスキップした場合も、通常は source option を省略し、`evidence-package create` に最新の
current before attempt を自動選択させる。既存 Operation を再利用する場合は `health-check` や `collect-clab` を
再実行しない。

最新完了時刻が同じ候補が複数ある場合、または過去の Operation を使用する場合だけ `--change-id` を指定する。

```bash
alred evidence-package create \
  --change-id <operation-id> \
  --profile digital-twin
```

`Storage` が `archived` の Operation は、selective restore CLI が未実装のため直接 source にできない。

選択した attempt の `raw/` と `collection-manifest.yaml` には running config、LLDP、baseline show output が同じ収集世代として
保存される。同じ Collection Manifest から Digital Twin Evidence Package を作成し、隔離 lab で
`clab-set-cmds --evidence-package` による link 再生成照合、config 変換、topology／diagram／VNI 生成を実行できる。詳細手順は
[Existing Network to Lab](02_EXISTING_NETWORK_TO_LAB.md)を参照する。
