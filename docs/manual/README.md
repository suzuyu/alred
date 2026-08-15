# alred Manuals

alred の利用者向け manual を、利用目的ごとに案内する入口です。

## 導入

[Installation Guide](./INSTALLATION.md)で、推奨 Release binary、Python package、開発環境、
shell completion、エアギャップ環境への持ち込みを確認してください。

## 現在利用できるマニュアル

| 分野 | 対象 | 入口 |
|---|---|---|
| Network Operations | NX-OS の正常性確認、EVPN／VXLAN 変更、設定投入を行う運用者 | [Network Operations Manual](./network-ops/README.md) |
| Containerlab | 既存ネットワークまたは結線表から検証 lab を生成する利用者 | [Containerlab Manual](./containerlab/README.md) |
| Topology | Evidence Package、Operation、外部 running config から link を整理し、Mermaid、Graphviz、draw.io 構成図を生成する利用者 | [Topology Manual](./topology/README.md) |

Terraform `main.tf` 生成は Topology ではなく inventory 派生機能であるため、Topology Manual の対象外です。

## 文書の位置付け

利用手順は各分野の manual を参照してください。機能仕様の正本は
[設計書一覧](../design/README.md)、実装状況は
[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)です。
