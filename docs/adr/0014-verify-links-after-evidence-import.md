# ADR-0014: Evidence import後にlinkを再生成検証してからContainerlabへ渡す

- Status: Accepted
- Date: 2026-08-09

## Context

Digital Twin packageはraw LLDP、running config、resolved mapping／description ruleと、商用側で生成したcanonical
linkを含む。隔離labで同梱CSVだけを採用すると、parser／rule version差、開示変換、欠落rawによる再現不能を検出せず
Containerlab topologyを生成する可能性がある。一方、`evidence-package import`へ解析を含めると安全な展開と派生成果物
生成の成否が混在する。

## Decision

`import`は検証済み展開だけを担当する。import後に`normalize-links`のEvidence Package入力modeを独立実行し、
Manifestから解決したrawとrulesでcanonical linkを再生成して、同梱成果物のsemantic hashと比較する。
`VERIFIED`のconfirmed linkだけをContainerlabへ渡し、candidate、warning付き、version不一致、semantic不一致、判定不能を
自動採用しない。

linkはpackage identityで正規化し、lab node mapは`generate-clab`で一度だけ適用する。再生成結果、入力hash、version、
比較状態をLink Verification ResultとNormalization Manifestへ記録する。

## Consequences

- importの安全な展開責務を維持しながら、隔離環境でlinkの再現性を確認できる。
- package同梱canonicalとraw／rulesの不一致をTopology生成前に検出できる。
- Evidence Package入力CLI、semantic hash、比較結果schema、atomic publish、Containerlab gateの実装とtestが必要になる。
- version差などで再現不能なpackageは自動生成できず、対応tool versionまたは新しいpackageが必要になる。

## References

- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
- [Link Discovery and Normalization Design](../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)
- [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
