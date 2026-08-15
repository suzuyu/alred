# ADR-0016: Terraform inventory生成をTopology renderingから分離する

## 状態

Accepted

## Context

旧設計書はdiagram生成とTerraform `main.tf`生成を同じTopology領域で説明していた。しかし、diagram生成は
LLDP／interface descriptionから正規化したlinkとnodeを描画する処理である一方、現行`generate-tf`は
`hosts.yaml`と`roles.yaml`を読み、NX-OS provider定義を生成するinventory派生処理である。

`generate-tf`はCanonical Link Evidence、Topology Render Model、Mermaid、Graphviz、draw.ioのいずれにも
依存しない。入力準備の流れも`hosts.txt`から`prepare-hosts`で`hosts.yaml`と`roles.yaml`を作る処理に近い。

## Decision

- Topology領域はlink discovery／normalizationとdiagram renderingを所有する。
- Terraform `main.tf`生成はCommon領域のinventory派生生成として扱う。
- 正本を[Topology Rendering Design](../design/topology/TOPOLOGY_RENDERING_DESIGN.md)と
  [Terraform Inventory Generation Design](../design/common/TERRAFORM_INVENTORY_GENERATION_DESIGN.md)へ分離する。
- 既存`generate-tf`のCLI、入力、出力、filter動作は、この文書分離だけでは変更しない。
- 固定credential出力は既知の安全性課題として追跡し、正式なproduction利用仕様は別の設計変更で決定する。

## Consequences

- diagram仕様の変更がTerraform生成仕様へ波及せず、両機能の入力と検証責務が明確になる。
- `hosts.txt -> prepare-hosts -> hosts.yaml / roles.yaml -> generate-tf -> main.tf`というinventory workflowを
  独立して説明できる。
- 将来Terraform生成がprovider以外の成果物へ拡張されても、link／diagram modelへ不必要に結合しない。
- 旧設計書名を参照する文書は、新しい2つの正本へ移行する必要がある。
