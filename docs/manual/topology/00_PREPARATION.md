# Preparation

## 1. 入力 source を選択

Topology workflow は次の入力 source を排他的に使用する。

| source | 主な option | 用途 |
|---|---|---|
| Evidence Package（推奨） | `--evidence-package <imported-directory>` | 商用環境から隔離環境へ検証済みデータを搬送して使用 |
| 最新 Operation | `--latest-operation` | 商用環境内で最新の正常公開済み before attempt を直接使用 |
| 特定 Operation | `--change-id <operation-id>` | 商用環境内で収集世代を固定して使用 |
| 外部 running config import | `--running-config-import <import-root>` | alred 以外で収集した running config／transcript を使用 |
| legacy raw file | `--hosts hosts.yaml --input raw` | 既存の `raw/config/` と任意 `raw/lldp/` を直接使用 |

隔離環境や環境間搬送では Evidence Package を標準とする。同一環境で Operation を直接参照する場合や、Portable Evidence を
使用しない外部データでは、それぞれ専用 selector を使用する。複数 source を混在させない。

## 2. Evidence Package の入力

`digital-twin` Evidence Package は inventory、running config、任意 LLDP、mappings、description rules、roles、sites、
packaged canonical links を Manifest と hash で固定する。archive は `evidence-package import` で検証・展開してから使用する。

```text
imported-evidence/<package-id>/
├── package-manifest.yaml
├── inventory/
├── policy/
├── raw/
└── canonical/
```

標準手順は [Quick Start](01_QUICK_START.md) を参照する。

## 3. 外部収集データの入力

alred 以外で取得した running config は、直接 directory 名を推測して解析せず、`import-running-config` で host identity と hash を
固定する。必要な入力は `hosts.yaml`、機器別 running config または NX-OS transcript、任意 LLDP である。

```text
.
├── hosts.yaml
├── collected-configs/
├── collected-lldp/              # 任意
├── mappings.yaml                # 任意
├── description_rules.yaml       # 任意
├── roles.yaml                   # 任意
└── sites.yaml                   # 任意
```

詳細は [External Data to Topology](05_EXTERNAL_DATA_TO_TOPOLOGY.md) を参照する。

## 4. CLI 確認

```bash
alred evidence-package import --help
alred import-running-config --help
alred normalize-links --help
alred generate-network-diagram --help
alred generate-mermaid --help
alred generate-graphviz --help
alred generate-drawio --help
```

## 5. 安全上の注意

- `evidence-package import`、`import-running-config`、`normalize-links`、各 renderer は機器へ接続しない。
- Evidence Package の disclosure preset と secret scan 結果を搬送前に確認する。
- 外部 running config、管理 address、hostname をそのまま commit または外部共有しない。
- candidate や warning 付き link を正しい結線として自動採用せず、raw evidence と照合する。
- mapping や description rule を変更した場合は、以前の CSV との差を実結線変更とみなす前に rule 差分を確認する。
