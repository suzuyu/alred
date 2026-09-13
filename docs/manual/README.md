# alred Manuals

alred の利用者向け manual を、利用目的ごとに案内する入口です。

## 導入

[Installation Guide](./INSTALLATION.md)で、推奨 Release binary、Python package、開発環境、
shell completion、エアギャップ環境への持ち込みを確認してください。

## 現在利用できるマニュアル

| 分野 | 対象 | 入口 |
|---|---|---|
| Common | 収集・設定投入・Health Check のホスト選択 | [対象ホストの指定](./common/TARGET_HOSTS.md) |
| Network Operations | NX-OS の正常性確認、EVPN／VXLAN 変更、設定投入を行う運用者 | [Network Operations Manual](./network-ops/README.md) |
| Containerlab | 既存ネットワークまたは結線表から検証 lab を生成する利用者 | [Containerlab Manual](./containerlab/README.md) |
| Topology | Evidence Package、Operation、外部 running config から link を整理し、Mermaid、Graphviz、draw.io 構成図を生成する利用者 | [Topology Manual](./topology/README.md) |

Terraform `main.tf` 生成は Topology ではなく inventory 派生機能であるため、Topology Manual の対象外です。

## 実装前レビュー用ドラフト

[Route Diff 利用ガイド](./network-ops/13_ROUTE_DIFF_GUIDE.md)は、IPv4／IPv6 の経路比較について、
入力準備と出力確認の手順をまとめたドラフトです。比較・オフライン出力 API と standalone CLI は実装済みですが、Health 統合も実装済みです。
本番 renderer の実出力 HTML と操作画像で表示を確認できます。

## 文書の位置付け

利用手順は各分野の manual を参照してください。機能仕様の正本は
[設計書一覧](../design/README.md)、実装状況は
[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)です。
