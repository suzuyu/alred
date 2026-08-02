# Topology Instructions

## Scope

LLDP、link正規化、candidate／confirmed CSV、Mermaid、Graphviz、draw.io、Terraform、構成資料生成を
変更または実行するときに適用する。

## Rules

- source endpoint、normalized endpoint、confirmed decisionを区別し、曖昧なlinkを自動確定しない。
- hostname、interface、role、siteのmapping適用順を決定的にし、入力と出力を追跡可能にする。
- 同一入力から安定した順序と同じ生成結果を得られるようにする。
- 既存CSV header、CLI option、生成ファイル名の互換性を、廃止が承認されるまで維持する。
- Mermaid、Graphviz、draw.io、containerlab間でnodeとlinkの意味を独自に再定義しない。
- golden testでは意味のある差分を確認し、無関係な全生成物を一括更新しない。

## Sources

- [Design documentation coverage](../../docs/design/README.md)
- [Existing feature documentation status](../../docs/implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
