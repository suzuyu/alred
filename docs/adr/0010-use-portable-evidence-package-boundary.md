# ADR-0010: 商用環境と隔離lab／AIの境界に検証可能なEvidence Packageを使用する

- Status: Superseded in part by ADR-0011
- Date: 2026-08-09

## Context

商用環境で収集した最新状態を、商用機器へ接続できないContainerlab Digital TwinやAI解析環境へ搬送する。
既存の`raw/`、operation directory、手動tarをそのまま渡すと、収集世代の混在、秘密情報、file欠落、
改ざん、安全でない展開を一貫して検出できない。Digital TwinとAIでは必要なsourceは共通する一方、許容される
hostname、IP address、configの開示levelは環境ごとに異なる。

## Decision

検証済みCollection Manifestまたは正常公開済みOperation attemptをpinned sourceとし、用途profileと独立した
開示policyを適用したPortable Evidence Packageを商用環境とのtrust boundaryに使用する。CLIは
`alred evidence-package create/inspect/verify/import`とし、作成、非展開確認、完全性検証、安全な展開の責務を
分離する。

archiveはallowlist、sanitization、secret scan、Manifest、file checksum、archive外checksumを備える。
`import`は検証後に一時directoryへ展開してatomicに公開し、既存directoryを上書きしない。packageとcredentialは
分離し、CLIはdevice access、収集、Topology／Containerlab生成を暗黙に開始しない。

通常のconfigはNX-OS構文を認識して開示変換する。原文configが必要な例外では平文をarchiveへ含めず、受領者の
公開鍵で暗号化したsealed payloadとして収録する。presetからは有効化せず、policy、受領者鍵、明示的な
acknowledgement、承認記録を必須とする。

既存Support Bundleは互換性のためCLIと成果物を維持し、共通実装への移行を暗黙に外部仕様変更へ結び付けない。

## Consequences

- 同一のpinned sourceをDigital Twin、AI、Support用途へ再利用しながら、開示levelを個別に選択できる。
- 隔離環境でsource、schema、checksum、必須capabilityを検証してからconsumerへ渡せる。
- raw directoryの直接tar化や未検証archiveの展開を推奨経路から除外できる。
- 例外的に原文configのbyte同一性を維持しつつ、通常consumerやAI promptから分離できる。
- Evidence Package schema、開示変換、CLI、atomic import、offline consumerの実装とtestが必要になる。
- 既存Support Bundleとの内部共通化時も後方互換testが必要になる。

## References

- [Portable Evidence Package Design](../design/common/PORTABLE_EVIDENCE_PACKAGE_DESIGN.md)
- [Collection Design](../design/common/COLLECTION_DESIGN.md)
- [Support Bundle Design](../design/common/SUPPORT_BUNDLE_DESIGN.md)
- [Containerlab Workflow Design](../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md)
