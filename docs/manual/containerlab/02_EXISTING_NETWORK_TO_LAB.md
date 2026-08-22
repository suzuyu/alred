# Existing Network to Lab

## 1. 目的と現行 workflow

商用環境の収集結果から Digital Twin 用 config と Containerlab topology を生成する。Evidence Package の入力は、
`operations/` にある最新の正常公開済み current before attempt とする。既存ログを使用できる場合は実機収集を行わず、
そのまま source 自動選択へ進む。最新状態が必要な場合だけ、先に Health Check inspection を実行して新しい attempt を作成する。

```text
任意: 最新状態を実機から収集
health-check before --purpose inspection --collect
                         │
                         ▼
既存または新規 operations
最新の成功済み current before を自動選択
                         │
                         ▼
Collection Manifest + attempt/raw
        ├─ evidence-package create / inspect / verify
        │          ↓ controlled transfer
        │   evidence-package import（内部 verify）
        │          ↓
        │   clab-set-cmds --evidence-package
        │          ├─ normalize-links + canonical 照合
        │          ├─ clab-transform-config
        │          └─ generate-clab / diagram / VNI
        │
        └─ hosts.lab.yaml + raw/labconfig + verified links
                   ↓
              topology 生成
                   ↓
          topology.clab.yaml（NX-OS startup-config なし）
                   ↓ containerlab deploy
              clab-apply-config
```

Evidence Package の `create`、`inspect`、`verify`、`import`、`clab-transform-config` は device access を行わない。
実機へ接続するのは、任意で実行する `health-check ... --collect` だけである。

| 状況 | 開始位置 |
|---|---|
| 最新状態を新しく取得する、または既存 attempt に必要な command がない | 2 章の収集を実行してから 3 章へ進む |
| 既存の正常公開済み before attempt を再利用する | 2 章をスキップして 3 章へ進む |

## 2. 任意: 実機から Health Check inspection を収集

この章はスキップ可能である。最新状態の取得が必要な場合だけ、変更作業を伴わない正常性確認、topology、
Digital Twin 用の収集として `--purpose inspection` を指定する。

```bash
alred health-check before \
  --purpose inspection \
  --collect \
  --hosts hosts.yaml \
  --profile network-baseline-nxos \
  --mappings mappings.yaml \
  --description-rules description_rules.yaml \
  --ask-pass \
  --workers 5
```

running config、LLDP、baseline show output は同じ attempt へ保存される。端末に表示された次の値を記録する。

- Operation／change ID
- `Attempt` directory
- `Manifest` path
- host 数、warning 数、全体判定

端末の `Manifest` は正常公開済み phase の互換 path を示す。Evidence Package 作成時は、通常この path や
Operation ID を再指定する必要はない。自動選択結果として表示される `source_change_id`、`source_attempt_id`、
`source_completed_at`、`source_manifest` が今回の収集結果と一致することを確認する。

接続失敗、必須 `running_config` 不足、Collection Manifest validation failure を無視して Package 作成へ進まない。
`inspection` は active change へ登録せず、変更継続用 Operation Gate を要求しない。

## 3. 既存または新規 `operations/` から source を自動選択

2 章をスキップした場合は既存 Operation、2 章を実行した場合は新しく作成された Operation が候補になる。
いずれも成功済み before attempt と Collection Manifest を、機器へ再接続せずに利用する。
通常は `--change-id` を指定せず、`evidence-package create` に最新の正常公開済み current before attempt を自動選択させる。
選択基準は `health/before/current.json` の `completed_at` であり、directory／file の更新時刻や失敗 attempt は使用しない。

最新完了時刻が同じ候補が複数ある場合は自動選択せず停止する。この場合、または過去の収集世代を選ぶ場合だけ
`--change-id <operation-id>` を指定する。archived Operation は直接 source にできず、selective restore CLI は未実装である。

Collection Manifest が参照する regular file、command 別 line range、SHA-256 を `evidence-package create` が再検証する。
元の Operation directory 全体や `raw/` 全体を直接 tar 化しない。既存ログを別 directory へ寄せ集めたり、複数 attempt を
混在させたりしない。

2 章をスキップした場合は、`health-check before`、`collect-clab`、その他の収集 command を再実行しない。

## 4. 商用環境で Evidence Package を作成

2 章を実行した場合もスキップした場合も、通常は source option を指定しない。

```bash
alred evidence-package create --profile digital-twin
```

`--config-content` の既定は `sanitized`、`--output-dir` の既定は `evidence-packages` である。出力 directory が
存在しない場合は自動作成する。作成成功後は profile と通常／sensitive 区分ごとに最新 3 package を保持し、
それより古い検証済み archive／checksum pair を削除する。保持数は `--keep-latest-packages` または
`ALRED_EVIDENCE_PACKAGE_KEEP_LATEST` で変更でき、`0` で自動削除を無効にできる。

既存 package の削除候補は、先に dry-run で確認できる。

```bash
alred evidence-package prune --keep-latest-packages 3 --dry-run
alred evidence-package prune --keep-latest-packages 3
```

checksum 不一致、archive／checksum の片方だけが存在する package、symlink、未知 file は自動削除しない。
`digital-twin` の既定 disclosure は `protected-preserve` である。

成功時に表示される次の項目を確認する。

```text
source_selection: operation-current-before
source_change_id: <operation-id>
source_attempt_id: <attempt-id>
source_completed_at: <completed-at>
source_manifest: <attempt-dir>/collection-manifest.yaml
```

意図した収集世代でない場合は Package を搬送せず、次のように明示する。

```bash
alred evidence-package create \
  --change-id <operation-id> \
  --profile digital-twin
```

Operation 以外の Collection Manifest を使用する場合、または Manifest path を厳密に固定する場合だけ、互換経路を使用する。

```bash
alred evidence-package create \
  --collection-manifest <attempt-dir>/collection-manifest.yaml \
  --input <attempt-dir> \
  --profile digital-twin
```

`protected-preserve` では hostname と address は保持し、credential、private key、
SNMP community などの secret-bearing material を除去する。identity も隠す場合だけ
`--disclosure-preset pseudonymized` を明示する。

作成直後に metadata と scan 結果を確認する。

```bash
alred evidence-package inspect \
  --bundle evidence-packages/<package-id>.tar.gz \
  --format json

alred evidence-package verify \
  --bundle evidence-packages/<package-id>.tar.gz \
  --format json
```

判定は次のとおりとする。

| 表示 | 継続条件 |
|---|---|
| `CLEAN` | high／low confidence が 0 であることを確認して移送可能 |
| `LOW_CONFIDENCE_FINDINGS` | rule ID、artifact ID、path、位置を確認し、値を表示せず誤検知または許容候補かを判断 |
| `ACKNOWLEDGED_SENSITIVE` | `verbatim` 専用。通常の Digital Twin 搬送手順では使用しない |
| `secret_scan_declared: false` | 旧 Package。現在の catalog による再 scan 結果を確認し、可能なら source から再作成 |

sanitized member に high confidence finding が残る場合、archive は公開されない。error を無視して手動 tar へ切り替えない。

## 5. 隔離 lab で一括生成

Package と archive 外 checksum を隔離 lab へ搬送する。標準手順は次の 1 command である。

```bash
alred clab-set-cmds \
  --evidence-package evidence-packages/<package-id>.tar.gz
```

archive の verify と import、Canonical Link Evidence の再生成照合、config 変換、topology、diagram、VNI 生成を
順番に実行する。device access、deploy、config push は行わない。同じ archive の import 済み directory があり
archive hash が一致する場合は再利用する。hash が異なる場合は停止する。

`--checksum-file` 省略時は、archive と同じ directory の `<package-id>.sha256` を自動検出する。別名または
別 directory の checksum file を使う場合だけ明示する。checksum file がない場合も内部 checksum 検証で継続できるが、
`external_checksum_verified: false` となり搬送中の archive 全体の同一性は確認されない。

`--output-dir` の既定は `imported-evidence` である。展開せずに受領確認、監査、CI 検証だけを行う場合は、任意で
`evidence-package verify` を使用する。

import 成功後は profile・通常／sensitive 区分ごとに import 日時が新しい 3 directory を保持する。
`--keep-latest-packages` または `ALRED_EVIDENCE_IMPORT_KEEP_LATEST` で保持数を変更でき、`0` で無効にできる。
既存 directory は `evidence-package prune-imports --dry-run` で削除候補を確認してから整理できる。
`latest` の参照先、不完全な directory、symlink、検証不能な手動配置物は削除しない。

import 済み directory から pipeline を再開する場合は次とする。

```bash
alred clab-set-cmds \
  --evidence-import imported-evidence/<package-id>
```

`--lab-parameters` を省略した場合も built-in safety policy を適用する。既定出力は `hosts.lab.yaml`、
`raw/labconfig/`、`raw/lab-transform-manifest.yaml` である。出力先を変更する場合だけ、`--output-hosts`、
`--output-dir`、`--manifest-output` を指定する。`LabTransformManifest` で device 数、
missing source、変換 hash、warning、risk finding を確認する。既定の bootstrap `admin:admin` 保持は
`BOOTSTRAP_CREDENTIAL_PRESERVED` の `WARN` となる。production credential へ fallback しない。

## 6. 詳細手順: import、Link 照合、config 変換

各 gate の成果物を個別に確認したい場合は次のように実行する。`import` は内部 verify に成功した場合だけ
directory を atomic に公開する。

```bash
alred evidence-package import \
  --bundle evidence-packages/<package-id>.tar.gz

alred normalize-links \
  --evidence-package imported-evidence/<package-id>

alred clab-transform-config \
  --evidence-package imported-evidence/<package-id>
```

Evidence Package mode で `normalize-links` に必須な option は `--evidence-package` だけである。inventory、mappings、
description rules、running config、任意 LLDP、packaged canonical links は Manifest から解決する。
既定出力は `output/links_confirmed.csv`、`output/links_candidates.csv`、`output/link-verification.json`、
`output/normalization-manifest.yaml` である。`VERIFIED` 以外では confirmed link を公開せず停止する。

LLDP が Package に含まれる場合は LLDP と description を統合し、ない場合は description-only で継続する。
candidate と warning 付き link を confirmed へ自動昇格しない。

## 7. Topology 生成

個別実行する場合は、検証済み confirmed link と Package から生成した `hosts.lab.yaml` を使用する。
Package は解決済み mappings、description rules、roles、sites も同梱する。runtime 固有の `clab_merge.yaml`、
lab profile、image、credential は隔離 lab 側で指定する。

```bash
alred generate-clab \
  --hosts hosts.lab.yaml
```

`--input` の既定は `output/links_confirmed.csv`、`--output` の既定は `output/topology.clab.yaml` である。
merge や lab profile が必要な場合だけ追加する。

生成後に network node 数、link 数、management address を既存設計と比較する。NX-OS 9000v node または
`topology.kinds.cisco_n9kv` に有効な `startup-config` がないことを確認する。merge／lab profile で明示した field は維持される。

## 8. Deploy と boot 後の config 投入

Containerlab CLI は alred の管理外である。image、license、runtime 権限を確認してから実行する。

```bash
containerlab deploy -t output/topology.clab.yaml
containerlab inspect -t output/topology.clab.yaml
```

全 NX-OS 9000v node が runtime ready になった後、標準の Manifest 経路で投入する。

```bash
alred clab-apply-config \
  --topology output/topology.clab.yaml \
  --hosts hosts.lab.yaml \
  --lab-transform-manifest raw/lab-transform-manifest.yaml \
  --workers 1
```

`clab-apply-config` は topology の `startup-delay` と Docker health を考慮し、strict CLI error、再接続、semantic verification を
実行する。`WARN` がある場合は通常の対象確認とは別に `yes` が必要である。automation で確認済み connectivity risk を許可する
場合だけ `--accept-connectivity-risk` を指定する。`BLOCK` は option で回避できない。

## 9. 既存互換の同一環境内経路

Evidence Package による環境分離が不要な既存運用では、`collect-clab → --input raw` 経路を利用できる。

```bash
alred collect-clab \
  --hosts hosts.yaml \
  --ask-pass \
  --transport ssh \
  --output raw \
  --workers 5

alred clab-transform-config
```

既定で `./hosts.yaml`、`raw/config/<hostname>_run.txt`、`hosts.lab.yaml`、`raw/labconfig/` を使用する。別 path や
file suffix を使う場合だけ `--hosts`、`--input`、`--output-hosts`、`--output-dir`、`--file-suffix` を指定する。

この経路は後方互換用であり、収集世代を Portable Evidence Manifest で固定しない。source 不足を warning で skip する legacy 動作と、
Evidence Package 経路の fail-closed 動作を混同しない。

## 10. 外部 show running-config folder

alred で収集していない host 別 show run や複数 host transcript を共通 Manifest へ import し、config 変換と link 正規化で
共用できる。LLDP は任意で、ない場合は双方向 description を confirmed `low`、片方向を candidate `low` とする。
手順は [External Config to Lab](02_EXTERNAL_CONFIG_TO_LAB.md)、正式仕様は
[External Running Config Import Design](../../design/common/EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)を参照する。
