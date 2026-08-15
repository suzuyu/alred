# Evidence Package Quick Start

本手順は、商用環境から搬送した Evidence Package を基に、隔離環境で再現用 lab の成果物を生成する最短手順である。
実環境を基にせず、`hosts.txt` と cable CSV から新しい lab を設計する場合は
[結線表から新規 Lab を生成](03_TABLE_DRIVEN_LAB.md)を使用する。

## 1. Evidence Package を準備

商用環境側で、正常公開済みの `operations/` を基に `digital-twin` Evidence Package を作成する。

```bash
alred evidence-package create --profile digital-twin
```

既存ログの選択方法、必要な場合だけ実行する Health Check inspection、secret scan、`inspect`／`verify`、
隔離 lab への搬送方法は
[Existing Network to Lab](02_EXISTING_NETWORK_TO_LAB.md)の「実機からの任意収集」から
「商用環境で Evidence Package を作成」までを参照する。

本章以降は、作成した `<package-id>.tar.gz` と `<package-id>.sha256` を隔離 lab へ搬送済みであることを前提とする。

## 2. Evidence Package から生成（推奨）

商用環境で作成・搬送した `digital-twin` Evidence Package を隔離 lab で指定する。
必須 option は `--evidence-package` だけである。

```bash
alred clab-set-cmds \
  --evidence-package evidence-packages/<package-id>.tar.gz
```

archive と同じ directory の `<package-id>.sha256` は自動検出する。import 済み directory から再開する場合は
`--evidence-import imported-evidence/<package-id>` を使用する。`verbatim` Package だけは
`--acknowledge-sensitive-config` も必須である。

成功後に最低限確認する。

```bash
test -f hosts.lab.yaml
test -d raw/labconfig
test -f output/links_confirmed.csv
test -f output/topology.clab.yaml
test -f output/clab-set-cmds/current.json
```

pipeline は archive の verify 付き import、link 再生成照合、config 変換、topology、diagram、VNI 生成を
実行する。device access、`containerlab deploy`、config push は実行しない。途中失敗時は後続へ進まず、
`output/clab-set-cmds/attempts/<attempt-id>/pipeline-manifest.yaml` に失敗 step を保存して、前回成功済み
`current.json` を更新しない。

## 3. Containerlab を起動

以下は alred ではなく Containerlab CLI の操作例である。image、license、runtime 権限を環境側で確認してから
実行する。

```bash
containerlab deploy -t output/topology.clab.yaml
```

alred はこの command を自動実行しない。外部 CLI の最新 option は
[containerlab deploy command](https://containerlab.dev/cmd/deploy/)を確認する。

NX-OS 9000v は boot-time の `startup-config` 投入中に停止する場合がある。既定 workflow は、生成 YAML へ
`startup-config` を追加せず起動し、boot 完了後に alred の `clab-apply-config` または `push-config-dir` で
`raw/labconfig/` を投入する方式とする。merge で明示した field は維持されるため、deploy 前に生成 YAML を確認する。詳細は
[NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md)を参照する。

## 4. 変換済み Config を投入

標準経路では、`clab-set-cmds` が生成した `LabTransformManifest` を指定して `clab-apply-config` を実行する。
`--topology`には実際に直前の `containerlab deploy` で使用した file を指定する。既に起動済みの lab へ投入する場合も、
その lab と同じ`name`を持つ Topology が必要である。

```bash
alred clab-apply-config \
  --topology output/topology.clab.yaml \
  --hosts hosts.lab.yaml \
  --lab-transform-manifest raw/lab-transform-manifest.yaml \
  --workers 1 \
  --fail-fast
```

`clab-apply-config` は Topology の `startup-delay` と Docker health を確認してから設定を投入するため、
`containerlab deploy` の直後に起動して待機させることができる。初回は `--workers 1 --fail-fast` で直列投入し、最初の
host failure 後に未着手 host を開始しない。
credential を明示しない初期 NX-OS 9000v 経路では、Containerlab の bootstrap `admin:admin` を使用し、
production credential へ fallback しない。

投入前の risk scan に `WARN` がある場合は、通常の投入対象確認とは別に `yes` の入力が必要である。
`BLOCK`、CLI error、再接続失敗、必須 semantic verification の失敗は無視せず停止する。
config を保存する場合だけ `--write-memory` を追加する。保存対象は verification を通過した node に限定される。
NX-OS 9000v の既存 bootstrap SSH key に対する`ssh key rsa <bits>`の限定 error だけは、
`NXOS_CLAB_SSH_KEY_ALREADY_EXISTS`の`WARN`として記録し、後続 command と verification を継続する。

成功後に、最新の成功 attempt と node ごとの verification 結果が生成されていることを確認する。

```bash
test -f output/clab-apply-config/current.json
find output/clab-apply-config -name verification.yaml -type f -print
```

credential の変更、connectivity risk、再実行、`VERIFIED_WITH_DIFF`、保存条件の詳細は
[NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md)を参照する。

## 5. 出力例を確認

変換前 NX-OS config、変換 parameter、変換後 `raw/labconfig/`、代表差分、`LabTransformManifest`、
`hosts.lab.yaml`、`topology.clab.yaml` の対応例は
[Containerlab Quick Start Sample](examples/quick-start/README.md)を参照する。

sample は架空の 4 node 構成であり、secret を含まない。変換前後を同じ hostname の file で比較でき、
production endpoint の除去・置換と、interface／description／Underlay address の維持を確認できる。

Spine 2 台、Leaf 4 台、Network Function 2 台に server／Kind node を加えた 22 node／40 link の
実用規模例は [Single-site Fabric Sample](examples/single-site-fabric/README.md) を参照する。
`adc-*` の site 命名規則、address plan、Secret Mask、Lab config 変換、Containerlab の runtime 依存 file、
`clab-apply-config` までの対応を確認できる。
