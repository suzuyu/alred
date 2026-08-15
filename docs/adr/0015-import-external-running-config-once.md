# ADR-0015: 外部show runを共通Manifestへ一度importしてTopologyとContainerlabで共有する

- Status: Accepted
- Date: 2026-08-09

## Context

Containerlab生成ではalred collection以外に、ホスト別fileまたは複数hostを含むCLI transcriptとして取得済みの
`show running-config`を利用する要件がある。現行`normalize-links`と`clab-transform-config`は
`<hostname>_run.txt|json`形式を読めるが、任意filenameや複数host transcriptを共通の世代・identityで扱わない。
各consumerが独自にhost分割すると、採用区間、alias、重複、途中切断の判断がずれる。

## Decision

外部show runをCommon Collection領域のadapterで一度だけホスト別canonical configと
Running Config Import Manifestへ変換する。input formatは`alred-collect`、`running-config-directory`、
`nxos-transcript`を明示し、内容から推測しない。任意filenameはsource map、既存命名、config内hostname、inventory
aliasを矛盾検査して解決し、複数host transcriptは既存Health transcript adapterを再利用する。

`normalize-links`と`clab-transform-config`は同じImport Manifestを参照する。LLDPを任意capabilityとし、欠落時は
description-onlyで双方向一致をconfirmed `low`、片方向をcandidate `low`として保持する。

## Consequences

- 外部データでもTopologyとstartup configが同じhost／generationを利用できる。
- LLDPがなくてもdescriptionからDigital Twinのlink候補を生成できる。
- 任意filename、transcript分割、source map、Manifest schema、CLI、partial attempt、consumer接続の実装とtestが必要になる。
- descriptionが片方向だけのlinkは自動採用されず、追加証拠または明示design overrideが必要になる。

## References

- [External Running Config Import Design](../design/common/EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md)
- [Collection Design](../design/common/COLLECTION_DESIGN.md)
- [Link Discovery and Normalization Design](../design/topology/LINK_DISCOVERY_AND_NORMALIZATION_DESIGN.md)
- [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
