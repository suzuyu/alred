# ADR-0004: operation所有範囲だけをrollbackする

- Status: Accepted
- Date: 2026-07-26

## Context

設定投入失敗時に安全に切り戻すには、作業前状態へ戻す必要がある。一方で、汎用的な
running-config差分をすべて反転すると、同時作業や既存設定まで削除する危険がある。

## Decision

rollbackは、承認済みplanが新規作成または変更し、operation metadataで所有を証明できる
リソースだけを対象とする。新規VRFをoperationが所有する場合、BGP VRF配下の各行を個別に
削除せず、必要な安全確認後にVRF自体を削除する。

rollback後は、対象範囲についてbeforeのrunning configとの差分がないことと、共通および
Overlay health checkが許容状態であることの両方を確認する。

## Consequences

- unrelatedな既存設定を誤って削除する可能性を抑えられる。
- planにownership、before evidence、config hashを保存する必要がある。
- operation外の変更が混在した場合は完全自動rollbackできないことがある。
- 差分が残った場合はrollback成功とせず、手動判断に必要な証跡を保存する。

## References

- [Overlay Change Management Design](../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
- [NX-OS Overlay Config Rendering Design](../design/network-ops/NXOS_OVERLAY_CONFIG_RENDERING_DESIGN.md)
