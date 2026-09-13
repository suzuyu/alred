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
| [ADR-0009](./0009-share-canonical-link-evidence.md) | LLDP／descriptionのCanonical Link EvidenceをHealth、Topology、Digital Twinで共有する | Accepted |
| [ADR-0010](./0010-use-portable-evidence-package-boundary.md) | 商用環境と隔離lab／AIの境界に検証可能なEvidence Packageを使用する | Accepted |
| [ADR-0011](./0011-allow-explicit-verbatim-config.md) | 保護環境向けpackageで明示承認された原文config収録を許可する | Accepted |
| [ADR-0012](./0012-transform-evidence-config-in-isolated-lab.md) | Evidence configのlab-local変換をContainerlab workflowが所有する | Superseded in part by ADR-0013 |
| [ADR-0013](./0013-use-package-config-content-for-lab-transform.md) | Containerlab変換元をPackage Manifestの`config_content`で固定する | Accepted |
| [ADR-0014](./0014-verify-links-after-evidence-import.md) | Evidence import後にlinkを再生成検証してからContainerlabへ渡す | Accepted |
| [ADR-0015](./0015-import-external-running-config-once.md) | 外部show runを共通Manifestへ一度importしてTopologyとContainerlabで共有する | Accepted |
| [ADR-0016](./0016-separate-terraform-inventory-generation-from-topology.md) | Terraform inventory生成をTopology renderingから分離する | Accepted |
| [ADR-0017](./0017-push-nxos-config-after-containerlab-boot.md) | NX-OS 9000v は Containerlab 起動後に config を投入する | Accepted |
| [ADR-0018](./0018-enable-strict-direct-config-errors-by-default.md) | Direct Config Push の CLI error 検出を default で有効にする | Accepted |
| [ADR-0019](./0019-auto-select-latest-evidence-source.md) | Evidence Package の最新成功 before source を自動選択する | Accepted |
| [ADR-0020](./0020-separate-underlay-and-evpn-diagrams.md) | Underlay routing と EVPN control-plane diagram を分離する | Accepted |
| [ADR-0021](./0021-model-overlay-services-and-route-leaks-separately.md) | Overlay Service と VRF 間 route leak を独立 model で表す | Accepted |
| [ADR-0022](./0022-release-route-diff-offline-before-webui.md) | Route Diff の CLI・オフライン出力を Web UI に先行してリリースする | Accepted |
| [ADR-0023](./0023-preserve-route-forwarding-attributes-and-completion-evidence.md) | Route Diff の転送属性と取得完了の証跡を保持する | Accepted |

## 追加基準

次に該当する判断はADRの候補とする。

- 複数案があり、将来同じ議論が再発しそうなもの
- 後方互換性、運用、安全性、データ形式へ長期的な影響があるもの
- コンポーネント境界や責務を決めるもの
- rollbackや設定投入の安全性を左右するもの

単純な実装詳細、短期的な進捗、未決事項はADRにしない。
