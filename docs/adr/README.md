# Architecture Decision Records

## 目的

alredの重要な設計判断について、「何を選んだか」だけでなく、背景、選択理由、影響を残す。
現在の仕様の正本は[設計書一覧](../design/README.md)であり、ADRは仕様を重複定義するものでは
ない。設計書には現在有効な仕様を、ADRにはその判断履歴を記録する。

## 状態

- `Proposed`: 検討中であり、実装の根拠にはしない
- `Accepted`: 合意済み
- `Superseded`: 後続ADRに置き換えられた
- `Deprecated`: 判断または機能が廃止された

Accepted ADRの内容を変更する場合は本文を上書きせず、新しいADRを追加して
`Superseded by ADR-NNNN`と記録する。誤字、リンク切れ、意味を変えない説明の修正は許容する。

## 一覧

| ADR | 判断 | 状態 |
|---|---|---|
| [ADR-0001](./0001-reuse-existing-collect-framework.md) | 既存collect基盤を再利用する | Accepted |
| [ADR-0002](./0002-default-to-new-l3vni.md) | L3VNI modeの既定を`new_l3vni`とする | Accepted |
| [ADR-0003](./0003-require-global-ingress-replication.md) | global ingress-replicationを前提条件とする | Accepted |
| [ADR-0004](./0004-operation-scoped-rollback.md) | operation所有範囲だけをrollbackする | Accepted |
| [ADR-0005](./0005-initial-nxos-support-scope.md) | 初期NX-OS対応範囲と検証Levelを限定する | Accepted |
| [ADR-0006](./0006-external-hierarchical-device-groups.md) | device groupを外部化し階層参照を許可する | Accepted |
| [ADR-0007](./0007-limit-device-validation-to-nexus-9000v.md) | 動作検証をNexus 9000vに限定しhardwareは文書確認とする | Accepted |
| [ADR-0008](./0008-use-canonical-multi-role-resolution.md) | canonical な複数 role 解決を利用機能間で共有する | Accepted |

## 追加基準

次に該当する判断はADRの候補とする。

- 複数案があり、将来同じ議論が再発しそうなもの
- 後方互換性、運用、安全性、データ形式へ長期的な影響があるもの
- コンポーネント境界や責務を決めるもの
- rollbackや設定投入の安全性を左右するもの

単純な実装詳細、短期的な進捗、未決事項はADRにしない。
