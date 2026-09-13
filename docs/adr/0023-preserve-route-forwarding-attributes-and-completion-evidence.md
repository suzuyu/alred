# ADR-0023: Route Diff の転送属性と取得完了の証跡を保持する

## 状態

Accepted。2026-09-13 の実装・試験依頼で採用。

## Context

統合収集ログの管理行、HMM / VXLAN の経路表記、明示 marker を持たない空 VRF が UNKNOWN になった。
単に未知行を除去したり、同じ next-hop address の経路を同一視したりすると、
収集失敗や転送先 segment の変更が正常・差分なしに見える可能性がある。

## Decision

取得形式を検証する section adapter と、転送属性を保持する canonical path を CLI / Health で共通利用する。
NextHop を含む比較で VXLAN 属性を含め、正常空は command の終端証拠に基づいて認定する。
具体的な field、grammar、認定条件、互換性は
[修正設計](../design/network-ops/ROUTE_DIFF_COLLECTION_LOG_FIX_DESIGN.md)を正本とする。

## Consequences

- 元ログ・取得失敗・未対応構文を保持し、比較できないものは UNKNOWN として追跡できる。
- 同じ IP next-hop に対する VXLAN 属性の変更を、転送属性を含む方式でレビューできる。
- source / parser / comparator version が変わるため両時点の再解析が必要になり、旧レビューは誤継承しない。
- EOF のみの空 section、未検証の別 grammar は引き続き UNKNOWN。対応範囲の fixture が必要。
- 構造を検証する分の実装・計測が必要だが、収集 executor や別 parser の重複実装を避けられる。

この ADR は設計判断の理由を記録する。Release の作成・公開は本作業に含まれない。
