# ADR-0012: Evidence configのlab-local変換をContainerlab workflowが所有する

- Status: Superseded in part by ADR-0013
- Date: 2026-08-09

## Context

Portable Evidence Packageのsanitizationは商用データを安全に搬送するが、管理subnet、hostname、service endpoint、
credential、image capabilityをContainerlabで起動可能な値へ確定する責務は持たない。商用環境と隔離labが直接接続
できない場合、lab parameterを商用側で決定またはpackageへ埋め込むと環境分離と再利用性を損なう。

## Decision

Evidence Packageからstartup configへのlab-local変換は`clab-transform-config`が所有する。隔離lab側で
`LabTransformParameters`を指定し、management、node mapping、vPC keepalive、NTP、logging、DNS、AAA、SNMP、
management ACL、lab userを明示的にremove／replaceする。package exporterはこの変換を行わない。

sanitized configを既定sourceとし、verbatimはsensitive承認を再検証した場合だけ使用する。production credential、
private key、AAA／SNMP secretをstartup configへ継承せず、必要parameter不足時にproduction値へfallbackしない。
変換元、parameter、rule version、生成hashはLab Transform Manifestへ固定する。

## Consequences

- 同じEvidence Packageを複数の隔離lab parameterで再利用できる。
- 搬送時の情報保護とlab起動変換の責務が分離される。
- Evidence consumer、parameter schema、service変換、secret scan、Manifest、atomic publishの実装とtestが必要になる。
- 既存file入力の`clab-transform-config`は互換維持し、新しいpackage入力との同時指定を拒否する必要がある。

## References

- [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
- [Secret Scan Rule Catalog](../design/common/SECRET_SCAN_RULE_CATALOG.md)
