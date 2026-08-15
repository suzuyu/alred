# Design Documents

alredの正式な設計書を、`docs/manual/`と同様に用途別directoryへ整理する。本indexから参照できる設計書を
現在仕様の正本とし、実装状態は別の進捗表で管理する。

## 全体構成

[Alred Architecture Overview](ARCHITECTURE_OVERVIEW.md)に、機能領域、データと成果物のflow、managed
Network Operationの主要state、CLIと設計領域の対応をMermaid図と表で示す。図は全体把握の入口であり、
個別仕様は用途別設計を正本とする。

## 用途別index

| directory | 対象 | 入口 |
|---|---|---|
| `common/` | CLI、設定、inventory、credential、収集、role、Terraform inventory生成、operation、schema、error、support | [Common Design](common/README.md) |
| `network-ops/` | Health Check、VNI、Overlay、config投入、NX-OS capability | [Network Operations Design](network-ops/README.md) |
| `containerlab/` | lab初期化、config変換、topology生成、起動後確認 | [Containerlab Design](containerlab/README.md) |
| `topology/` | LLDP、link正規化、Mermaid、Graphviz、draw.io | [Topology Design](topology/README.md) |
| `development/` | test、package data、PyInstaller、glibc binary | [Development Design](development/README.md) |

利用者向けの操作手順は[Manual](../manual/README.md)、開発とbuildの手順は
[CONTRIBUTING.md](../../CONTRIBUTING.md)と[BUILD.md](../../BUILD.md)を参照する。

## 文書の役割

| 種類 | 正本と用途 |
|---|---|
| `docs/design/` | 現在有効な仕様、責務、入力、出力、error、互換性 |
| `docs/as-is/` | 既存実装から観測した事実、不明点、偶然の挙動、設計差分 |
| `docs/adr/` | 重要な判断の背景、採用理由、影響。現行仕様は再定義しない |
| `docs/implementation/` | 設計に対する実装状態、既存機能の設計書化状態、実装計画 |
| `docs/manual/` | 利用者が実行する手順、運用上の確認、復旧 |

設計書に記載がないことだけを理由に、既存機能を未実装、不要、廃止予定と判断してはならない。未反映または
レビュー中の機能は、コード、CLI help、[README.md](../../README.md)、[CONFIG.md](../../CONFIG.md)、test、
代表生成物を確認する。

## 責務の境界

全体の依存関係は[ツール全体の機能構成図](ARCHITECTURE_OVERVIEW.md#2-ツール全体の機能構成)を参照する。

- 共通のCLI、path、inventory、credential、transport、operation、schema、errorをfeature文書で再定義しない。
- link evidenceとconfidenceはTopology、lab node／merge／startup configはContainerlabを正本とする。
- Health CheckとOverlayは収集・operation・roleをCommonから利用し、feature固有parserと判定だけを定義する。
- implementationの既知の問題を、観測したという理由だけで正式仕様へ昇格しない。

## 既存機能を設計書化する手順

1. code、CLI help、README／CONFIG、test、sample、代表生成物を確認する。
2. 観測事実、既存文書、推測、不明点を[As-Is Implementation Notes](../as-is/README.md)へ分けて記録する。
3. 既存仕様との重複、矛盾、後方互換性、安全性を確認する。
4. 承認した内容だけを責務を持つ設計書へ統合し、重要判断はADRへ記録する。
5. test、利用者文書、[Existing Feature Documentation Status](../implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
   と[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)を同期する。

## 現在の網羅性と状態

主要な公開CLIと共通基盤は用途別設計へ整理済みである。ただし、設計書化済みであっても、すべての仕様が実装済み、
全platformで検証済み、または安全性上の課題が解消済みとは限らない。特に次は進捗表の状態と既知差分を確認する。

- topology link CSVの決定的なrow順と入力schema validation
- legacy role consumerのcanonical multi-role resolver移行
- containerlab startup接続失敗時の結果処理
- Terraform credentialの安全な注入
- collect current artifactのatomic publishとstale sidecar防止
- NX-OS以外のtransport、LLDP、config transform対応範囲

実装状態は[Implementation Status](../implementation/IMPLEMENTATION_STATUS.md)、設計書化の進捗は
[Existing Feature Documentation Status](../implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)を参照する。
設計変更と実装の作業規則は[AGENTS.md](../../AGENTS.md)に従う。
