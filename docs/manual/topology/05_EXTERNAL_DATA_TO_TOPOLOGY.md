# External Data to Topology

## 1. 用途

Evidence Package を使用せず、alred で収集していない機器別 `show running-config` file または複数機器を含む transcript から、
device access なしで link と構成図を生成する。LLDP は任意であり、存在しない場合は interface description だけを使用する。

この経路は Portable Evidence の disclosure policy や搬送時 checksum を提供しない。元データの保管、共有範囲、秘密情報の扱いは
利用環境で管理する。

## 2. 外部データを import

機器ごとに running config file がある場合は次の形式を使用する。

```bash
alred import-running-config \
  --input collected-configs \
  --input-format running-config-directory \
  --hosts hosts.yaml
```

`--output` の既定は `imported-running-config` である。file 名または config 内の `hostname` から host を一意に解決できない場合だけ
`--source-map` を指定する。機器別 LLDP directory がある場合だけ `--lldp-input collected-lldp` を追加する。

入力形式は次から選択する。

| `--input-format` | 入力 |
|---|---|
| `running-config-directory` | 機器別 running config file |
| `nxos-transcript` | 1 file または複数 file に複数 host の `show running-config` transcript |
| `alred-collect` | 既存の `config/<hostname>_run.txt` directory 構造 |

import は元 file を変更せず、host identity、入力 hash、採用範囲、任意 LLDP を immutable attempt と Manifest へ固定する。
成功した attempt だけが `imported-running-config/current.json` から参照される。

## 3. Network diagram を一括生成

```bash
alred generate-network-diagram \
  --running-config-import imported-running-config
```

この包括 command は Mermaid Physical、`topology_underlay.md`、`topology_evpn.md`、EVPN model／CSV、draw.io を同じ
Import Manifest から生成する。Mermaid だけを
生成する場合は `generate-mermaid --running-config-import imported-running-config` を使用する。

内部で `normalize-links` を実行し、Import Manifest が固定した inventory、running config、任意 LLDP を使用する。既定成果物は
`output/links_confirmed.csv`、`output/links_candidates.csv`、`output/topology-graph.md`、`output/topology_underlay.md`、
`output/topology_evpn.md`、`output/evpn-control-plane-model.yaml`、`output/evpn-session-links.csv`、
`output/topology-graph.drawio`、`output/network-diagram-manifest.yaml` である。

LLDP がない場合、双方向 description は confirmed `low`、片方向 description は candidate `low` となる。candidate を
confirmed とみなさず、元の running config と照合する。

## 4. Link 正規化を個別確認

構成図の前に link evidence を確認する場合は、normalizer を個別実行する。

```bash
alred normalize-links \
  --running-config-import imported-running-config
```

その後、元の inventory を指定して各 renderer を実行できる。

```bash
alred generate-drawio \
  --input output/links_confirmed.csv \
  --input-candidates output/links_candidates.csv \
  --hosts hosts.yaml \
  --roles roles.yaml \
  --all-graph
```

## 5. 制約と確認

- 同じ host の採用可能な running config が複数ある場合、最新を推測せず import を停止する。
- hostname、file 名、transcript prompt、inventory が矛盾する場合は停止する。
- LLDP と description が不一致の場合は一方を消さず warning と candidate を確認する。
- raw config、hostname、管理 address を外部共有または commit する前に情報開示範囲を確認する。

入力仕様の正本は
[External Running Config Import Design](../../design/common/EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)、link 判定は
[Link Discovery and Normalization Design](../../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md) を参照する。
