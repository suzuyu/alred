# ADR-0013: Containerlab変換元をPackage Manifestの`config_content`で固定する

- Status: Accepted
- Date: 2026-08-09

## Context

Evidence Packageの`verbatim` modeは原文とsanitized copyを併載するため、Containerlab側で変換元を選択する案では
同じpackageとparameterから異なるstartup configが生成され得る。しかしsanitized／verbatimのどちらでも、
production secretやexternal serviceは同じContainerlab変換flowで書き換えまたは削除する。

## Decision

Containerlab側に`--config-source`を設けない。Evidence Package作成時に`config_content`を
`sanitized|verbatim|exclude`としてPackage Manifestへ固定し、`clab-transform-config`はそのartifactだけを変換元にする。
directoryやfileの存在から推測せず、CLI／lab parameterによるoverrideを許可しない。

`verbatim`でもproduction credential、AAA／SNMP secret、private keyをstartup configへ継承せず、sanitizedと同じ
lab-local parameter変換と最終secret scanを適用する。`exclude`ではconfig変換を実行しない。

## Consequences

- package作成時の意図とContainerlab変換元が一致し、再生成結果が一意になる。
- 利用者はpackage内部directoryを意識してsourceを選ぶ必要がない。
- `verbatim` packageではsensitive承認の再検証が必要だが、source選択optionは不要になる。
- ADR-0012のsanitizedを常に既定sourceとする部分だけを置き換え、lab-local変換の責務は維持する。

## References

- [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
