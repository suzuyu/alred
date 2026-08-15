# Topology Manual

Evidence Package、Operation、または外部収集済みの LLDP／running config から link を正規化し、Mermaid topology、
Mermaid Underlay、EVPN control plane、Overlay Service、Graphviz、draw.io
形式の構成図を生成する利用者向け manual である。隔離環境では Evidence Package を標準経路とする。機器への収集、
Containerlab topology 生成、Terraform 生成は別の責務として扱う。

仕様の正本は [Topology Design](../../design/topology/README.md)、実装状況は
[Implementation Status](../../implementation/IMPLEMENTATION_STATUS.md) を参照する。

## 読む順序

| 文書 | 対象 |
|---|---|
| [Preparation](00_PREPARATION.md) | 入力 source、前提条件、安全上の注意 |
| [Quick Start](01_QUICK_START.md) | Evidence Package から Physical／Underlay／EVPN／Overlay Service／draw.io を一括生成する標準手順 |
| [Link Normalization](02_LINK_NORMALIZATION.md) | LLDP／description、confirmed／candidate の確認方法 |
| [Diagram Rendering](03_DIAGRAM_RENDERING.md) | Mermaid、Graphviz、draw.io、構成資料の生成 |
| [Output and Troubleshooting](04_OUTPUT_AND_TROUBLESHOOTING.md) | 成果物、確認項目、代表的な問題 |
| [External Data to Topology](05_EXTERNAL_DATA_TO_TOPOLOGY.md) | alred 非依存の running config／transcript から生成する手順 |
| [Network Diagram Generation](06_NETWORK_DIAGRAM_GENERATION.md) | `generate-network-diagram` の内部処理、option、evidence 判定、規模別の使い分け |

## 責務境界

- 商用機器からの収集は [Network Operations Manual](../network-ops/README.md) を参照する。
- Containerlab YAML 生成は [Containerlab Manual](../containerlab/README.md) を参照する。
- Terraform `main.tf` 生成は link や diagram を使用しないため Topology Manual へ含めない。
- Evidence Package の verify 付き import は Portable Evidence、外部 running config の host 分割と identity 解決は
  External Running Config Import が所有する。Topology は検証済み入力からの link 正規化と描画を所有する。
